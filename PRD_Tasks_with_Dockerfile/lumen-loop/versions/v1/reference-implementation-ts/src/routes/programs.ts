import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, forbidden } from "../errors";
import { newId } from "../ids";
import {
  computeSupplyShortfall,
  getProgramOrThrow,
  openAlertDeduped,
  recomputeAvailability,
  recomputePosture,
  setProgramFrozen,
  setProgramPosture,
} from "../domain";
import { runMutating } from "./helpers";
import { programResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerProgramsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs", (req, res, next) =>
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: "__global__", sessionExempt: true }, () => {
      const body = z
        .object({
          display_name: z.string().min(1),
          unit_price_cents: z.number().int().nonnegative(),
          care_plan_price_cents: z.number().int().nonnegative(),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

      const programId = newId("program");
      db.prepare(
        `INSERT INTO programs (
          program_id, display_name, unit_price_cents, care_plan_price_cents,
          program_posture, ops_run_index, replacement_reserve_remaining, frozen_since_ops_run_index, available_to_commit_units
        ) VALUES (?, ?, ?, ?, 'PROGRAM_ACTIVE', 0, 5, NULL, 0)`
      ).run(programId, body.data.display_name, body.data.unit_price_cents, body.data.care_plan_price_cents);
      return { status: 201, body: programResponse(db, programId) };
    })
  );

  app.get("/programs/:program_id", (req, res, next) => {
    try {
      res.json(programResponse(db, req.params.program_id));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/run_ops", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const tx = db.transaction(() => {
        const programBefore = getProgramOrThrow(db, programId);
        if (programBefore.program_posture === "PROGRAM_CLOSED") {
          throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
        }

        db.prepare(`UPDATE programs SET ops_run_index = ops_run_index + 1 WHERE program_id = ?`).run(programId);
        const program = getProgramOrThrow(db, programId);

        const stalePayments = db
          .prepare(
            `SELECT p.payment_id, p.order_id
             FROM payments p
             JOIN orders o ON o.order_id = p.order_id AND o.program_id = p.program_id
             WHERE p.program_id = ?
               AND p.payment_status = 'AUTHORIZED'
               AND p.authorized_ops_run_index < ?
               AND o.order_status = 'SUBMITTED'`
          )
          .all(programId, program.ops_run_index) as { payment_id: string; order_id: string }[];
        for (const sp of stalePayments) {
          db.prepare(`UPDATE payments SET payment_status = 'VOIDED' WHERE program_id = ? AND payment_id = ?`).run(
            programId,
            sp.payment_id
          );
          db.prepare(
            `UPDATE orders
             SET order_status = 'ON_HOLD', hold_reason = 'PAYMENT_REFRESH_REQUIRED', hold_set_ops_run_index = ?
             WHERE program_id = ? AND order_id = ? AND order_status = 'SUBMITTED'`
          ).run(program.ops_run_index, programId, sp.order_id);
        }

        const expiringOrders = db
          .prepare(
            `SELECT order_id, customer_id, paid_by_credit_cents, care_plan_id
             FROM orders
             WHERE program_id = ?
               AND order_status = 'ON_HOLD'
               AND hold_reason = 'PAYMENT_REFRESH_REQUIRED'
               AND hold_set_ops_run_index < ?`
          )
          .all(programId, program.ops_run_index) as {
          order_id: string;
          customer_id: string;
          paid_by_credit_cents: number;
          care_plan_id: string | null;
        }[];
        for (const eo of expiringOrders) {
          db.prepare(`UPDATE orders SET order_status = 'EXPIRED' WHERE program_id = ? AND order_id = ?`).run(
            programId,
            eo.order_id
          );
          if (eo.care_plan_id) {
            db.prepare(
              `UPDATE care_plans
               SET care_plan_status = 'VOIDED', paused_reason = NULL, device_id = NULL
               WHERE program_id = ? AND care_plan_id = ?`
            ).run(programId, eo.care_plan_id);
          }
          if (eo.paid_by_credit_cents > 0) {
            const c = db
              .prepare(
                `SELECT credit_balance_cents, balance_due_cents FROM customers WHERE program_id = ? AND customer_id = ?`
              )
              .get(programId, eo.customer_id) as { credit_balance_cents: number; balance_due_cents: number };
            const toBalanceDue = Math.min(c.balance_due_cents, eo.paid_by_credit_cents);
            const toCredit = eo.paid_by_credit_cents - toBalanceDue;
            db.prepare(
              `UPDATE customers
               SET balance_due_cents = balance_due_cents - ?, credit_balance_cents = credit_balance_cents + ?
               WHERE program_id = ? AND customer_id = ?`
            ).run(toBalanceDue, toCredit, programId, eo.customer_id);
          }
        }

        db.prepare(
          `UPDATE claims
           SET claim_status = 'EXPIRED'
           WHERE program_id = ?
             AND claim_resolution != 'ADVANCE_REPLACEMENT'
             AND claim_status = 'APPROVED'
             AND approved_ops_run_index < ?`
        ).run(programId, program.ops_run_index);

        db.prepare(
          `UPDATE claims
           SET claim_status = 'EXPIRED'
           WHERE program_id = ?
             AND claim_resolution != 'ADVANCE_REPLACEMENT'
             AND claim_status = 'INBOUND'
             AND inbound_ops_run_index < ?`
        ).run(programId, program.ops_run_index);

        const overdueClaims = db
          .prepare(
            `SELECT claim_id, customer_id
             FROM claims
             WHERE program_id = ?
               AND claim_resolution = 'ADVANCE_REPLACEMENT'
               AND advance_shipped_ops_run_index IS NOT NULL
               AND claim_status IN ('ADVANCE_SHIPPED', 'INBOUND', 'APPROVED')
               AND advance_shipped_ops_run_index + 2 <= ?`
          )
          .all(programId, program.ops_run_index) as { claim_id: string; customer_id: string }[];
        for (const oc of overdueClaims) {
          db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(
            programId,
            oc.customer_id
          );
          openAlertDeduped(db, programId, { alert_type: "AFTERCARE_OVERDUE", customer_id: oc.customer_id, claim_id: oc.claim_id });
          db.prepare(
            `UPDATE orders
             SET order_status = 'ON_HOLD', hold_reason = 'CUSTOMER_LOCKED', hold_set_ops_run_index = ?
             WHERE program_id = ? AND customer_id = ? AND order_status = 'SUBMITTED'`
          ).run(program.ops_run_index, programId, oc.customer_id);
        }

        recomputeAvailability(db, programId);
        const programAfterAvail = getProgramOrThrow(db, programId);
        if (computeSupplyShortfall(db, programAfterAvail)) {
          openAlertDeduped(db, programId, { alert_type: "SUPPLY_SHORTFALL" });
        }

        const chargebacksInRun = db
          .prepare(
            `SELECT COUNT(1) AS cnt
             FROM payments
             WHERE program_id = ? AND chargeback_lost_ops_run_index = ?`
          )
          .get(programId, program.ops_run_index - 1) as { cnt: number };
        const lockedCustomers = db
          .prepare(
            `SELECT COUNT(1) AS cnt FROM customers WHERE program_id = ? AND customer_status = 'LOCKED'`
          )
          .get(programId) as { cnt: number };
        const staleOpenAlert = db
          .prepare(
            `SELECT 1 AS ok
             FROM alerts
             WHERE program_id = ? AND alert_status = 'OPEN' AND opened_ops_run_index <= ?
             LIMIT 1`
          )
          .get(programId, program.ops_run_index - 2) as { ok: 1 } | undefined;

        if (chargebacksInRun.cnt >= 3 || lockedCustomers.cnt >= 5 || staleOpenAlert) {
          setProgramFrozen(db, programId);
        } else {
          recomputePosture(db, programId);
        }
      });
      tx();
      return { status: 200, body: programResponse(db, programId) };
    });
  });

  app.post("/programs/:program_id/freeze", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ reason: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      setProgramFrozen(db, programId);
      return { status: 200, body: programResponse(db, programId) };
    });
  });

  app.post("/programs/:program_id/unfreeze", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture !== "PROGRAM_FROZEN") {
        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      }
      const hasRecallNotClosed = db
        .prepare(
          `SELECT 1 AS ok
           FROM quality_campaigns
           WHERE program_id = ? AND campaign_type = 'RECALL' AND campaign_status != 'CLOSED'
           LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;
      const hasOpenAlerts = db
        .prepare(`SELECT 1 AS ok FROM alerts WHERE program_id = ? AND alert_status = 'OPEN' LIMIT 1`)
        .get(programId) as { ok: 1 } | undefined;
      const cooledOff =
        program.frozen_since_ops_run_index !== null && program.ops_run_index > program.frozen_since_ops_run_index;
      if (hasRecallNotClosed || hasOpenAlerts || !cooledOff) {
        throw badRequest("ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE", "Program not eligible to unfreeze");
      }
      db.prepare(
        `UPDATE programs SET program_posture = 'PROGRAM_ACTIVE', frozen_since_ops_run_index = NULL WHERE program_id = ?`
      ).run(programId);
      recomputePosture(db, programId);
      return { status: 200, body: programResponse(db, programId) };
    });
  });

  app.post("/programs/:program_id/close", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture !== "PROGRAM_ACTIVE") {
        throw badRequest("ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE", "Program not eligible to close");
      }
      const hasOpenAlerts = db
        .prepare(`SELECT 1 AS ok FROM alerts WHERE program_id = ? AND alert_status = 'OPEN' LIMIT 1`)
        .get(programId) as { ok: 1 } | undefined;
      const hasOpenOrders = db
        .prepare(
          `SELECT 1 AS ok
           FROM orders
           WHERE program_id = ? AND order_status IN ('SUBMITTED','ON_HOLD','SHIPPED','DELIVERED')
           LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;
      const hasOpenReturns = db
        .prepare(
          `SELECT 1 AS ok
           FROM returns
           WHERE program_id = ? AND return_status IN ('REQUESTED','APPROVED','INBOUND','RECEIVED')
           LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;
      const hasOpenClaims = db
        .prepare(
          `SELECT 1 AS ok
           FROM claims
           WHERE program_id = ? AND claim_status IN ('OPEN','APPROVED','INBOUND','RECEIVED','ADVANCE_SHIPPED')
           LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;
      const hasPendingAdjustments = db
        .prepare(
          `SELECT 1 AS ok FROM adjustments WHERE program_id = ? AND adjustment_status = 'PENDING' LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;
      const hasOpenCampaigns = db
        .prepare(
          `SELECT 1 AS ok FROM quality_campaigns WHERE program_id = ? AND campaign_status != 'CLOSED' LIMIT 1`
        )
        .get(programId) as { ok: 1 } | undefined;

      if (hasOpenAlerts || hasOpenOrders || hasOpenReturns || hasOpenClaims || hasPendingAdjustments || hasOpenCampaigns) {
        throw badRequest("ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE", "Program not eligible to close");
      }

      setProgramPosture(db, programId, "PROGRAM_CLOSED");
      return { status: 200, body: programResponse(db, programId) };
    });
  });
}
