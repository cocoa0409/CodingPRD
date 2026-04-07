import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import {
  ensureNoOpenAlertsForCustomer,
  ensureCustomerStandingAfterBalanceChange,
  getCustomerOrThrow,
  getProgramOrThrow,
  openAlertDeduped,
  putCustomerUnshippedOrdersOnHold,
} from "../domain";
import { runMutating } from "./helpers";
import { tradeinResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerTradeinsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/customers/:customer_id/tradeins", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ quoted_credit_cents: z.number().int().positive() }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const customer = getCustomerOrThrow(db, programId, customerId);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");
      const tradeinId = newId("tradein");
      db.prepare(
        `INSERT INTO tradeins (tradein_id, program_id, customer_id, tradein_status, quoted_credit_cents, final_credit_cents, provisional_credit_cents, credit_issued_cents)
         VALUES (?, ?, ?, 'DRAFT', ?, NULL, NULL, 0)`
      ).run(tradeinId, programId, customerId, body.data.quoted_credit_cents);
      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      return { status: 201, body: tradeinResponse(row) };
    });
  });

  app.get("/programs/:program_id/tradeins/:tradein_id", (req, res, next) => {
    try {
      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(req.params.program_id, req.params.tradein_id) as any;
      if (!row) throw notFound("Trade-in not found");
      res.json(tradeinResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/tradeins/:tradein_id/submit", (req, res, next) => {
    const programId = req.params.program_id;
    const tradeinId = req.params.tradein_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
      if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");

      const tradein = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      if (!tradein) throw notFound("Trade-in not found");
      if (tradein.tradein_status !== "DRAFT") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      const customer = getCustomerOrThrow(db, programId, tradein.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");

      db.prepare(`UPDATE tradeins SET tradein_status = 'SUBMITTED' WHERE program_id = ? AND tradein_id = ?`).run(programId, tradeinId);

      const qualifies =
        program.program_posture === "PROGRAM_ACTIVE" &&
        customer.customer_status === "ACTIVE" &&
        customer.balance_due_cents === 0 &&
        tradein.quoted_credit_cents <= 30000;
      if (qualifies) {
        ensureNoOpenAlertsForCustomer(db, programId, tradein.customer_id);
        db.prepare(`UPDATE customers SET credit_balance_cents = credit_balance_cents + ? WHERE program_id = ? AND customer_id = ?`).run(
          tradein.quoted_credit_cents,
          programId,
          tradein.customer_id
        );
        db.prepare(`UPDATE tradeins SET provisional_credit_cents = ?, credit_issued_cents = credit_issued_cents + ? WHERE program_id = ? AND tradein_id = ?`).run(
          tradein.quoted_credit_cents,
          tradein.quoted_credit_cents,
          programId,
          tradeinId
        );
      }
      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      return { status: 200, body: tradeinResponse(row) };
    });
  });

  app.post("/programs/:program_id/tradeins/:tradein_id/mark_inbound", (req, res, next) => {
    const programId = req.params.program_id;
    const tradeinId = req.params.tradein_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const tradein = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      if (!tradein) throw notFound("Trade-in not found");
      if (tradein.tradein_status !== "SUBMITTED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE tradeins SET tradein_status = 'INBOUND' WHERE program_id = ? AND tradein_id = ?`).run(programId, tradeinId);
      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      return { status: 200, body: tradeinResponse(row) };
    });
  });

  app.post("/programs/:program_id/tradeins/:tradein_id/appraise", (req, res, next) => {
    const programId = req.params.program_id;
    const tradeinId = req.params.tradein_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ accepted: z.boolean(), final_credit_cents: z.number().int().nonnegative() }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const tradein = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      if (!tradein) throw notFound("Trade-in not found");
      if (tradein.tradein_status !== "INBOUND") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      const customer = getCustomerOrThrow(db, programId, tradein.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      const provisional = tradein.provisional_credit_cents ?? 0;
      const finalValue = body.data.accepted ? body.data.final_credit_cents : 0;

      db.prepare(`UPDATE tradeins SET tradein_status = 'APPRAISED', final_credit_cents = ? WHERE program_id = ? AND tradein_id = ?`).run(
        finalValue,
        programId,
        tradeinId
      );

      if (!body.data.accepted) {
        if (provisional > 0) {
          const toRemoveFromCredit = Math.min(customer.credit_balance_cents, provisional);
          const toDue = provisional - toRemoveFromCredit;
          db.prepare(
            `UPDATE customers
             SET credit_balance_cents = credit_balance_cents - ?, balance_due_cents = balance_due_cents + ?
             WHERE program_id = ? AND customer_id = ?`
          ).run(toRemoveFromCredit, toDue, programId, tradein.customer_id);
        }
        db.prepare(`UPDATE tradeins SET credit_issued_cents = 0 WHERE program_id = ? AND tradein_id = ?`).run(programId, tradeinId);
        db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(programId, tradein.customer_id);
        openAlertDeduped(db, programId, { alert_type: "TRADEIN_REVERSAL", customer_id: tradein.customer_id, tradein_id: tradeinId });
        putCustomerUnshippedOrdersOnHold(db, programId, tradein.customer_id, "TRADEIN_REVERSAL");
      } else {
        const delta = finalValue - provisional;
        if (delta > 0) {
          db.prepare(`UPDATE customers SET credit_balance_cents = credit_balance_cents + ? WHERE program_id = ? AND customer_id = ?`).run(
            delta,
            programId,
            tradein.customer_id
          );
          db.prepare(`UPDATE tradeins SET credit_issued_cents = credit_issued_cents + ? WHERE program_id = ? AND tradein_id = ?`).run(
            delta,
            programId,
            tradeinId
          );
        } else if (delta < 0) {
          const short = -delta;
          const toRemoveFromCredit = Math.min(customer.credit_balance_cents, short);
          const toDue = short - toRemoveFromCredit;
          db.prepare(
            `UPDATE customers
             SET credit_balance_cents = credit_balance_cents - ?, balance_due_cents = balance_due_cents + ?
             WHERE program_id = ? AND customer_id = ?`
          ).run(toRemoveFromCredit, toDue, programId, tradein.customer_id);
          db.prepare(`UPDATE tradeins SET credit_issued_cents = credit_issued_cents + ? WHERE program_id = ? AND tradein_id = ?`).run(
            delta,
            programId,
            tradeinId
          );
          ensureCustomerStandingAfterBalanceChange(db, programId, tradein.customer_id);
        }
        if (finalValue > 0) {
          db.prepare(`UPDATE tradeins SET tradein_status = 'CREDITED' WHERE program_id = ? AND tradein_id = ?`).run(programId, tradeinId);
        }
      }

      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      return { status: 200, body: tradeinResponse(row) };
    });
  });

  app.post("/programs/:program_id/tradeins/:tradein_id/reverse_credit", (req, res, next) => {
    const programId = req.params.program_id;
    const tradeinId = req.params.tradein_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ reason: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const tradein = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      if (!tradein) throw notFound("Trade-in not found");
      if (tradein.tradein_status === "REVERSED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      const credited = tradein.credit_issued_cents ?? 0;
      if (credited <= 0) throw badRequest("ERR_TRADEIN_NOT_ELIGIBLE", "Trade-in not eligible");

      const customer = getCustomerOrThrow(db, programId, tradein.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      const toRemoveFromCredit = Math.min(customer.credit_balance_cents, credited);
      const toDue = credited - toRemoveFromCredit;
      db.prepare(
        `UPDATE customers
         SET credit_balance_cents = credit_balance_cents - ?, balance_due_cents = balance_due_cents + ?
         WHERE program_id = ? AND customer_id = ?`
      ).run(toRemoveFromCredit, toDue, programId, tradein.customer_id);
      db.prepare(`UPDATE tradeins SET tradein_status = 'REVERSED' WHERE program_id = ? AND tradein_id = ?`).run(programId, tradeinId);

      openAlertDeduped(db, programId, { alert_type: "TRADEIN_REVERSAL", customer_id: tradein.customer_id, tradein_id: tradeinId });
      putCustomerUnshippedOrdersOnHold(db, programId, tradein.customer_id, "TRADEIN_REVERSAL");
      if (toDue > 0) {
        db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(programId, tradein.customer_id);
      }

      const row = db.prepare(`SELECT * FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, tradeinId) as any;
      return { status: 200, body: tradeinResponse(row) };
    });
  });
}
