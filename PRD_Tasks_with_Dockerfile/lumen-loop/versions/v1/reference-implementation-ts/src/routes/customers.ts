import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import { ensureNoOpenAlertsForCustomer, getCustomerOrThrow, getProgramOrThrow, openAlertDeduped, putCustomerUnshippedOrdersOnHold } from "../domain";
import { runMutating } from "./helpers";
import { customerResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerCustomersRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/customers", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ display_name: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const customerId = newId("customer");
      db.prepare(
        `INSERT INTO customers (
          customer_id, program_id, display_name, customer_status,
          credit_balance_cents, balance_due_cents, balance_due_cleared_ops_run_index
        ) VALUES (?, ?, ?, 'ACTIVE', 0, 0, NULL)`
      ).run(customerId, programId, body.data.display_name);
      return { status: 201, body: customerResponse(db, programId, customerId) };
    });
  });

  app.get("/programs/:program_id/customers/:customer_id", (req, res, next) => {
    try {
      res.json(customerResponse(db, req.params.program_id, req.params.customer_id));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/customers/:customer_id/lock", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ reason: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const existing = db
        .prepare(`SELECT customer_id FROM customers WHERE program_id = ? AND customer_id = ?`)
        .get(programId, customerId) as any;
      if (!existing) throw notFound("Customer not found");
      db.prepare(`UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`).run(programId, customerId);
      openAlertDeduped(db, programId, { alert_type: "CUSTOMER_LOCKED", customer_id: customerId });
      putCustomerUnshippedOrdersOnHold(db, programId, customerId, "CUSTOMER_LOCKED");
      return { status: 200, body: customerResponse(db, programId, customerId) };
    });
  });

  app.post("/programs/:program_id/customers/:customer_id/unlock", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
      if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");

      const customer = getCustomerOrThrow(db, programId, customerId);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.balance_due_cents > 0) throw badRequest("ERR_CUSTOMER_NOT_ELIGIBLE", "Customer not eligible");
      ensureNoOpenAlertsForCustomer(db, programId, customerId);

      const clearedAt = customer.balance_due_cleared_ops_run_index;
      const eligible = clearedAt !== null && program.ops_run_index >= clearedAt + 1;
      if (!eligible) throw badRequest("ERR_CUSTOMER_NOT_ELIGIBLE", "Customer not eligible");

      db.prepare(`UPDATE customers SET customer_status = 'ACTIVE' WHERE program_id = ? AND customer_id = ?`).run(programId, customerId);
      return { status: 200, body: customerResponse(db, programId, customerId) };
    });
  });

  app.post("/programs/:program_id/customers/:customer_id/settle_balance_due", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ amount_cents: z.number().int().positive() }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const customer = getCustomerOrThrow(db, programId, customerId);
      const amount = Math.min(customer.balance_due_cents, body.data.amount_cents);
      db.prepare(`UPDATE customers SET balance_due_cents = balance_due_cents - ? WHERE program_id = ? AND customer_id = ?`).run(
        amount,
        programId,
        customerId
      );
      const after = getCustomerOrThrow(db, programId, customerId);
      if (after.balance_due_cents === 0) {
        const program = getProgramOrThrow(db, programId);
        db.prepare(
          `UPDATE customers SET balance_due_cleared_ops_run_index = ? WHERE program_id = ? AND customer_id = ?`
        ).run(program.ops_run_index, programId, customerId);
      }
      return { status: 200, body: customerResponse(db, programId, customerId) };
    });
  });
}
