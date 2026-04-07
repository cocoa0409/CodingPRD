import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { getProgramOrThrow, openAlertDeduped } from "../domain";
import { runMutating } from "./helpers";
import { paymentResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerPaymentsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.get("/programs/:program_id/payments/:payment_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT payment_id, order_id, payment_status, amount_cents
           FROM payments WHERE program_id = ? AND payment_id = ?`
        )
        .get(req.params.program_id, req.params.payment_id) as any;
      if (!row) throw notFound("Payment not found");
      res.json(paymentResponse(row));
    } catch (e) {
      next(e);
    }
  });

	  app.post("/programs/:program_id/payments/:payment_id/dispute", (req, res, next) => {
	    const programId = req.params.program_id;
	    const paymentId = req.params.payment_id;
	    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
	      const p = db
	        .prepare(
	          `SELECT payment_id, order_id, customer_id, payment_status, amount_cents
	           FROM payments WHERE program_id = ? AND payment_id = ?`
	        )
	        .get(programId, paymentId) as any;
	      if (!p) throw notFound("Payment not found");
	      if (p.payment_status !== "AUTHORIZED" && p.payment_status !== "CAPTURED") {
	        throw badRequest("ERR_PAYMENT_NOT_DISPUTABLE", "Payment not disputable");
	      }
	      const program = getProgramOrThrow(db, programId);
	      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
	      db.prepare(`UPDATE payments SET payment_status = 'DISPUTED' WHERE program_id = ? AND payment_id = ?`).run(programId, paymentId);
	      openAlertDeduped(db, programId, { alert_type: "PAYMENT_DISPUTED", customer_id: p.customer_id, payment_id: paymentId });
	      const row = db
	        .prepare(`SELECT payment_id, order_id, payment_status, amount_cents FROM payments WHERE program_id = ? AND payment_id = ?`)
	        .get(programId, paymentId) as any;
      return { status: 200, body: paymentResponse(row) };
    });
  });

	  app.post("/programs/:program_id/payments/:payment_id/resolve_dispute", (req, res, next) => {
	    const programId = req.params.program_id;
	    const paymentId = req.params.payment_id;
	    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
	      const body = z.object({ outcome: z.enum(["CHARGEBACK_LOST", "REFUNDED"]) }).safeParse(req.body);
	      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
	      const p = db
	        .prepare(
	          `SELECT payment_id, order_id, customer_id, payment_status, amount_cents
	           FROM payments WHERE program_id = ? AND payment_id = ?`
	        )
	        .get(programId, paymentId) as any;
	      if (!p) throw notFound("Payment not found");
	      if (p.payment_status !== "DISPUTED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
	      const program = getProgramOrThrow(db, programId);
	      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

	      if (body.data.outcome === "REFUNDED") {
	        db.prepare(`UPDATE payments SET payment_status = 'REFUNDED' WHERE program_id = ? AND payment_id = ?`).run(programId, paymentId);
	      } else {
        db.prepare(
          `UPDATE payments SET payment_status = 'CHARGEBACK_LOST', chargeback_lost_ops_run_index = ? WHERE program_id = ? AND payment_id = ?`
        ).run(program.ops_run_index, programId, paymentId);
	        db.prepare(`UPDATE customers SET balance_due_cents = balance_due_cents + ?, customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(
	          p.amount_cents,
	          programId,
	          p.customer_id
	        );
	        openAlertDeduped(db, programId, { alert_type: "CHARGEBACK_LOST", customer_id: p.customer_id, payment_id: paymentId });
	        db.prepare(
	          `UPDATE orders
	           SET order_status = 'ON_HOLD', hold_reason = 'CUSTOMER_LOCKED', hold_set_ops_run_index = ?
           WHERE program_id = ? AND customer_id = ? AND order_status = 'SUBMITTED'`
        ).run(program.ops_run_index, programId, p.customer_id);
      }

      const row = db
        .prepare(`SELECT payment_id, order_id, payment_status, amount_cents FROM payments WHERE program_id = ? AND payment_id = ?`)
        .get(programId, paymentId) as any;
      return { status: 200, body: paymentResponse(row) };
    });
  });
}
