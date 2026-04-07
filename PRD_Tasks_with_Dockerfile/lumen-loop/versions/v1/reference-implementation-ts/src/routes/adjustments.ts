import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { ensureNoOpenAlertsForCustomer, getCustomerOrThrow, getProgramOrThrow, openAlertDeduped, putCustomerUnshippedOrdersOnHold } from "../domain";
import { runMutating } from "./helpers";
import { adjustmentResponse } from "./responses";
import { newId } from "../ids";
import type { RequestWithCtx } from "../app";

export function registerAdjustmentsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/customers/:customer_id/adjustments", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({
          adjustment_type: z.enum(["GOODWILL_CREDIT", "WRITE_OFF", "CREDIT_CLAWBACK"]),
          amount_cents: z.number().int().positive(),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const customer = getCustomerOrThrow(db, programId, customerId);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      const adjustmentId = newId("adjustment");
      db.prepare(
        `INSERT INTO adjustments (adjustment_id, program_id, customer_id, adjustment_type, adjustment_status, amount_cents, applied_ops_run_index)
         VALUES (?, ?, ?, ?, 'PENDING', ?, NULL)`
      ).run(adjustmentId, programId, customerId, body.data.adjustment_type, body.data.amount_cents);
      const row = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(programId, adjustmentId) as any;
      return { status: 201, body: adjustmentResponse(row) };
    });
  });

  app.get("/programs/:program_id/adjustments/:adjustment_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(req.params.program_id, req.params.adjustment_id) as any;
      if (!row) throw notFound("Adjustment not found");
      res.json(adjustmentResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/adjustments/:adjustment_id/apply", (req, res, next) => {
    const programId = req.params.program_id;
    const adjustmentId = req.params.adjustment_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const adj = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(programId, adjustmentId) as any;
      if (!adj) throw notFound("Adjustment not found");
      if (adj.adjustment_status !== "PENDING") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      const customer = getCustomerOrThrow(db, programId, adj.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      if (adj.adjustment_type === "GOODWILL_CREDIT") {
        if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
        if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");
        if (customer.customer_status !== "ACTIVE" || customer.balance_due_cents !== 0) {
          throw badRequest("ERR_ADJUSTMENT_NOT_ELIGIBLE", "Adjustment not eligible");
        }
        ensureNoOpenAlertsForCustomer(db, programId, adj.customer_id);
        db.prepare(`UPDATE customers SET credit_balance_cents = credit_balance_cents + ? WHERE program_id = ? AND customer_id = ?`).run(
          adj.amount_cents,
          programId,
          adj.customer_id
        );
      } else if (adj.adjustment_type === "WRITE_OFF") {
        const toReduce = Math.min(customer.balance_due_cents, adj.amount_cents);
        db.prepare(`UPDATE customers SET balance_due_cents = balance_due_cents - ? WHERE program_id = ? AND customer_id = ?`).run(
          toReduce,
          programId,
          adj.customer_id
        );
        const after = getCustomerOrThrow(db, programId, adj.customer_id);
        if (after.balance_due_cents === 0) {
          db.prepare(`UPDATE customers SET balance_due_cleared_ops_run_index = ? WHERE program_id = ? AND customer_id = ?`).run(
            program.ops_run_index,
            programId,
            adj.customer_id
          );
        }
      } else {
        const toRemoveFromCredit = Math.min(customer.credit_balance_cents, adj.amount_cents);
        const toDue = adj.amount_cents - toRemoveFromCredit;
        db.prepare(
          `UPDATE customers
           SET credit_balance_cents = credit_balance_cents - ?, balance_due_cents = balance_due_cents + ?
           WHERE program_id = ? AND customer_id = ?`
        ).run(toRemoveFromCredit, toDue, programId, adj.customer_id);
        if (toDue > 0) {
          db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(programId, adj.customer_id);
          openAlertDeduped(db, programId, { alert_type: "CUSTOMER_LOCKED", customer_id: adj.customer_id });
          putCustomerUnshippedOrdersOnHold(db, programId, adj.customer_id, "CREDIT_CLAWBACK");
        }
      }

      db.prepare(
        `UPDATE adjustments SET adjustment_status = 'APPLIED', applied_ops_run_index = ? WHERE program_id = ? AND adjustment_id = ?`
      ).run(program.ops_run_index, programId, adjustmentId);

      const row = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(programId, adjustmentId) as any;
      return { status: 200, body: adjustmentResponse(row) };
    });
  });

  app.post("/programs/:program_id/adjustments/:adjustment_id/void", (req, res, next) => {
    const programId = req.params.program_id;
    const adjustmentId = req.params.adjustment_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const adj = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents, applied_ops_run_index
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(programId, adjustmentId) as any;
      if (!adj) throw notFound("Adjustment not found");
      if (adj.adjustment_status !== "APPLIED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      if (adj.applied_ops_run_index !== program.ops_run_index) {
        throw badRequest("ERR_ADJUSTMENT_NOT_VOIDABLE", "Adjustment not voidable");
      }

      const customer = getCustomerOrThrow(db, programId, adj.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      if (adj.adjustment_type === "GOODWILL_CREDIT") {
        const toRemoveFromCredit = Math.min(customer.credit_balance_cents, adj.amount_cents);
        const toDue = adj.amount_cents - toRemoveFromCredit;
        db.prepare(
          `UPDATE customers
           SET credit_balance_cents = credit_balance_cents - ?, balance_due_cents = balance_due_cents + ?
           WHERE program_id = ? AND customer_id = ?`
        ).run(toRemoveFromCredit, toDue, programId, adj.customer_id);
        if (toDue > 0) {
          db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(programId, adj.customer_id);
          openAlertDeduped(db, programId, { alert_type: "CUSTOMER_LOCKED", customer_id: adj.customer_id });
          putCustomerUnshippedOrdersOnHold(db, programId, adj.customer_id, "ADJUSTMENT_VOID");
        }
      } else if (adj.adjustment_type === "WRITE_OFF") {
        db.prepare(`UPDATE customers SET balance_due_cents = balance_due_cents + ? WHERE program_id = ? AND customer_id = ?`).run(
          adj.amount_cents,
          programId,
          adj.customer_id
        );
      } else {
        const toReduceDue = Math.min(customer.balance_due_cents, adj.amount_cents);
        const toCredit = adj.amount_cents - toReduceDue;
        db.prepare(
          `UPDATE customers
           SET balance_due_cents = balance_due_cents - ?, credit_balance_cents = credit_balance_cents + ?
           WHERE program_id = ? AND customer_id = ?`
        ).run(toReduceDue, toCredit, programId, adj.customer_id);
        const after = getCustomerOrThrow(db, programId, adj.customer_id);
        if (after.balance_due_cents === 0) {
          db.prepare(`UPDATE customers SET balance_due_cleared_ops_run_index = ? WHERE program_id = ? AND customer_id = ?`).run(
            program.ops_run_index,
            programId,
            adj.customer_id
          );
        }
      }

      db.prepare(`UPDATE adjustments SET adjustment_status = 'VOIDED' WHERE program_id = ? AND adjustment_id = ?`).run(
        programId,
        adjustmentId
      );
      const row = db
        .prepare(
          `SELECT adjustment_id, customer_id, adjustment_type, adjustment_status, amount_cents
           FROM adjustments WHERE program_id = ? AND adjustment_id = ?`
        )
        .get(programId, adjustmentId) as any;
      return { status: 200, body: adjustmentResponse(row) };
    });
  });
}
