import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import {
  computeSupplyShortfall,
  ensureCustomerEligibleForNewCommitment,
  ensureCustomerNotClosed,
  ensureCustomerNotLocked,
  ensureNoOpenAlertsForCustomer,
  getCustomerOrThrow,
  getProgramOrThrow,
  recomputeAvailability,
  recomputePosture,
} from "../domain";
import { runMutating } from "./helpers";
import { orderResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerOrdersRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/customers/:customer_id/orders", (req, res, next) => {
    const programId = req.params.program_id;
    const customerId = req.params.customer_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({
          model_code: z.string().min(1),
          use_credit_cents: z.number().int().nonnegative(),
          tradein_id: z.string().min(1).nullable(),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

	      const customer = getCustomerOrThrow(db, programId, customerId);
	      ensureCustomerNotClosed(customer);

	      if (body.data.tradein_id) {
	        const ti = db
	          .prepare(`SELECT tradein_id FROM tradeins WHERE program_id = ? AND tradein_id = ? AND customer_id = ?`)
          .get(programId, body.data.tradein_id, customerId) as { tradein_id: string } | undefined;
        if (!ti) throw badRequest("ERR_TRADEIN_NOT_ELIGIBLE", "Trade-in not eligible");
      }

      const orderId = newId("order");
      db.prepare(
        `INSERT INTO orders (
          order_id, program_id, customer_id, order_status, model_code,
          unit_price_cents, care_plan_price_cents, requested_use_credit_cents,
          paid_by_credit_cents, paid_by_card_cents, payment_id, device_id, care_plan_id, tradein_id,
          hold_reason, hold_set_ops_run_index, committed_ops_run_index
        ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, 0, 0, NULL, NULL, NULL, ?, NULL, NULL, NULL)`
      ).run(
        orderId,
        programId,
        customerId,
        body.data.model_code,
        program.unit_price_cents,
        program.care_plan_price_cents,
        body.data.use_credit_cents,
        body.data.tradein_id
      );
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 201, body: orderResponse(row) };
    });
  });

  app.get("/programs/:program_id/orders/:order_id", (req, res, next) => {
    try {
      const row = db
        .prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`)
        .get(req.params.program_id, req.params.order_id) as any;
      if (!row) throw notFound("Order not found");
      res.json(orderResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.get("/programs/:program_id/orders", (req, res, next) => {
    try {
      const programId = req.params.program_id;
      const customerId = typeof req.query.customer_id === "string" ? req.query.customer_id : undefined;
      const orderStatus = typeof req.query.order_status === "string" ? req.query.order_status : undefined;
      const rows = db
        .prepare(
          `SELECT * FROM orders
           WHERE program_id = ?
             AND (? IS NULL OR customer_id = ?)
             AND (? IS NULL OR order_status = ?)
           ORDER BY rowid ASC`
        )
        .all(programId, customerId ?? null, customerId ?? null, orderStatus ?? null, orderStatus ?? null) as any[];
      res.json({ orders: rows.map(orderResponse) });
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/orders/:order_id/submit", (req, res, next) => {
    const programId = req.params.program_id;
    const orderId = req.params.order_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ include_care_plan: z.boolean() }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
      if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");

      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      if (!order) throw notFound("Order not found");
      if (order.order_status !== "DRAFT") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

      const customer = getCustomerOrThrow(db, programId, order.customer_id);
      ensureCustomerNotClosed(customer);
      ensureCustomerEligibleForNewCommitment(customer);
      ensureNoOpenAlertsForCustomer(db, programId, order.customer_id);

      recomputeAvailability(db, programId);
      const refreshedProgram = getProgramOrThrow(db, programId);
      if (refreshedProgram.available_to_commit_units <= 0) throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");

      const total = program.unit_price_cents + (body.data.include_care_plan ? program.care_plan_price_cents : 0);
      const creditToUse = Math.min(order.requested_use_credit_cents, customer.credit_balance_cents, total);
      const paidByCard = total - creditToUse;

      if (creditToUse > 0) {
        db.prepare(`UPDATE customers SET credit_balance_cents = credit_balance_cents - ? WHERE program_id = ? AND customer_id = ?`).run(
          creditToUse,
          programId,
          order.customer_id
        );
      }

      let paymentId: string | null = null;
      if (paidByCard > 0) {
        paymentId = newId("payment");
        db.prepare(
          `INSERT INTO payments (payment_id, program_id, order_id, customer_id, payment_status, amount_cents, authorized_ops_run_index, chargeback_lost_ops_run_index)
           VALUES (?, ?, ?, ?, 'AUTHORIZED', ?, ?, NULL)`
        ).run(paymentId, programId, orderId, order.customer_id, paidByCard, program.ops_run_index);
      }

      let carePlanId: string | null = null;
      if (body.data.include_care_plan) {
        carePlanId = newId("careplan");
        db.prepare(
          `INSERT INTO care_plans (care_plan_id, program_id, order_id, customer_id, device_id, care_plan_status, paused_reason)
           VALUES (?, ?, ?, ?, NULL, 'PENDING_ACTIVATION', NULL)`
        ).run(carePlanId, programId, orderId, order.customer_id);
      }

      db.prepare(
        `UPDATE orders
         SET order_status = 'SUBMITTED',
             paid_by_credit_cents = ?,
             paid_by_card_cents = ?,
             payment_id = ?,
             care_plan_id = ?,
             committed_ops_run_index = ?
         WHERE program_id = ? AND order_id = ?`
      ).run(creditToUse, paidByCard, paymentId, carePlanId, program.ops_run_index, programId, orderId);

      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 200, body: orderResponse(row) };
    });
  });

	  app.post("/programs/:program_id/orders/:order_id/refresh_payment", (req, res, next) => {
	    const programId = req.params.program_id;
	    const orderId = req.params.order_id;
	    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
	      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
	      if (!order) throw notFound("Order not found");
	      if (order.order_status !== "ON_HOLD" || order.hold_reason !== "PAYMENT_REFRESH_REQUIRED") {
	        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
	      }

	      const program = getProgramOrThrow(db, programId);
	      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
	      if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");

	      const customer = getCustomerOrThrow(db, programId, order.customer_id);
	      ensureCustomerNotClosed(customer);
	      ensureCustomerNotLocked(customer);
	      if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");
	      if (order.paid_by_card_cents <= 0) throw badRequest("ERR_ORDER_PAYMENT_REQUIRED", "Order payment required");

      const paymentId = newId("payment");
      db.prepare(
        `INSERT INTO payments (payment_id, program_id, order_id, customer_id, payment_status, amount_cents, authorized_ops_run_index, chargeback_lost_ops_run_index)
         VALUES (?, ?, ?, ?, 'AUTHORIZED', ?, ?, NULL)`
      ).run(paymentId, programId, orderId, order.customer_id, order.paid_by_card_cents, program.ops_run_index);
      db.prepare(
        `UPDATE orders
         SET order_status = 'SUBMITTED', payment_id = ?, hold_reason = NULL, hold_set_ops_run_index = NULL
         WHERE program_id = ? AND order_id = ?`
      ).run(paymentId, programId, orderId);
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 200, body: orderResponse(row) };
    });
  });

	  app.post("/programs/:program_id/orders/:order_id/cancel", (req, res, next) => {
	    const programId = req.params.program_id;
	    const orderId = req.params.order_id;
	    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
	      const body = z.object({ reason: z.string().min(1) }).safeParse(req.body);
	      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

	      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
	      if (!order) throw notFound("Order not found");
	      if (order.order_status === "SHIPPED" || order.order_status === "DELIVERED") {
	        throw badRequest("ERR_ORDER_NOT_CANCELABLE", "Order not cancelable");
	      }
	      if (order.order_status === "CANCELED" || order.order_status === "EXPIRED" || order.order_status === "REFUNDED") {
	        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
	      }

	      const program = getProgramOrThrow(db, programId);
	      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

	      if (order.payment_id) {
	        const p = db
	          .prepare(`SELECT payment_status FROM payments WHERE program_id = ? AND payment_id = ?`)
	          .get(programId, order.payment_id) as any;
        if (p && p.payment_status === "AUTHORIZED") {
          db.prepare(`UPDATE payments SET payment_status = 'VOIDED' WHERE program_id = ? AND payment_id = ?`).run(
            programId,
            order.payment_id
          );
        }
      }

      if (order.paid_by_credit_cents > 0) {
        const customer = getCustomerOrThrow(db, programId, order.customer_id);
        const toDue = Math.min(customer.balance_due_cents, order.paid_by_credit_cents);
        const toCredit = order.paid_by_credit_cents - toDue;
        db.prepare(
          `UPDATE customers
           SET balance_due_cents = balance_due_cents - ?, credit_balance_cents = credit_balance_cents + ?
           WHERE program_id = ? AND customer_id = ?`
        ).run(toDue, toCredit, programId, order.customer_id);
      }

      if (order.care_plan_id) {
        db.prepare(`UPDATE care_plans SET care_plan_status = 'VOIDED' WHERE program_id = ? AND care_plan_id = ?`).run(
          programId,
          order.care_plan_id
        );
      }

      db.prepare(`UPDATE orders SET order_status = 'CANCELED' WHERE program_id = ? AND order_id = ?`).run(programId, orderId);
      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 200, body: orderResponse(row) };
    });
  });

  app.post("/programs/:program_id/orders/:order_id/ship", (req, res, next) => {
    const programId = req.params.program_id;
    const orderId = req.params.order_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({ build_lot_id: z.string().min(1), serial_number: z.string().min(1), build_tag: z.string().min(1) })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      if (program.program_posture === "PROGRAM_FROZEN") throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");

	      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
	      if (!order) throw notFound("Order not found");
	      if (order.order_status === "ON_HOLD") throw badRequest("ERR_ORDER_ON_HOLD", "Order on hold");
	      if (order.order_status !== "SUBMITTED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

	      if (computeSupplyShortfall(db, program)) {
	        db.prepare(
	          `UPDATE orders
	           SET order_status = 'ON_HOLD', hold_reason = 'SUPPLY_SHORTFALL', hold_set_ops_run_index = ?
	           WHERE program_id = ? AND order_id = ?`
	        ).run(program.ops_run_index, programId, orderId);
	        return { status: 400, body: { error: { code: "ERR_ORDER_ON_HOLD", message: "Order on hold" } } };
	      }

	      const lot = db
	        .prepare(
	          `SELECT build_lot_id, build_tag, build_lot_status, units_remaining
	           FROM build_lots WHERE program_id = ? AND build_lot_id = ?`
	      )
	      .get(programId, body.data.build_lot_id) as any;
	      if (!lot) throw notFound("Build lot not found");
	      if (lot.build_lot_status !== "AVAILABLE") {
	        if (lot.build_lot_status === "CONSUMED") throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
	        throw badRequest("ERR_BUILD_LOT_QUARANTINED", "Build lot quarantined");
	      }
	      if (lot.units_remaining <= 0) throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
	      if (lot.build_tag !== body.data.build_tag) throw badRequest("ERR_INVALID_REQUEST", "Invalid request");

      if (order.paid_by_card_cents > 0) {
        if (!order.payment_id) throw badRequest("ERR_ORDER_PAYMENT_REQUIRED", "Order payment required");
        const p = db
          .prepare(`SELECT payment_status FROM payments WHERE program_id = ? AND payment_id = ?`)
          .get(programId, order.payment_id) as any;
        if (!p || p.payment_status !== "AUTHORIZED") throw badRequest("ERR_ORDER_PAYMENT_REQUIRED", "Order payment required");
        db.prepare(`UPDATE payments SET payment_status = 'CAPTURED' WHERE program_id = ? AND payment_id = ?`).run(
          programId,
          order.payment_id
        );
      }

      const deviceId = newId("device");
      db.prepare(
        `INSERT INTO devices (
          device_id, program_id, order_id, customer_id, serial_number, build_tag,
          device_status, pre_quarantine_status, activated_ops_run_index, created_by_claim_id, created_by_return_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'SHIPPED', NULL, NULL, NULL, NULL)`
      ).run(deviceId, programId, orderId, order.customer_id, body.data.serial_number, body.data.build_tag);
      db.prepare(`UPDATE orders SET order_status = 'SHIPPED', device_id = ? WHERE program_id = ? AND order_id = ?`).run(
        deviceId,
        programId,
        orderId
      );
      if (order.care_plan_id) {
        db.prepare(`UPDATE care_plans SET device_id = ? WHERE program_id = ? AND care_plan_id = ?`).run(
          deviceId,
          programId,
          order.care_plan_id
        );
      }

      db.prepare(`UPDATE build_lots SET units_remaining = units_remaining - 1 WHERE program_id = ? AND build_lot_id = ?`).run(
        programId,
        lot.build_lot_id
      );
      const afterLot = db
        .prepare(`SELECT units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`)
        .get(programId, lot.build_lot_id) as { units_remaining: number };
      if (afterLot.units_remaining <= 0) {
        db.prepare(`UPDATE build_lots SET build_lot_status = 'CONSUMED' WHERE program_id = ? AND build_lot_id = ?`).run(
          programId,
          lot.build_lot_id
        );
      }

      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 200, body: orderResponse(row) };
    });
  });

  app.post("/programs/:program_id/orders/:order_id/mark_delivered", (req, res, next) => {
    const programId = req.params.program_id;
    const orderId = req.params.order_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      if (!order) throw notFound("Order not found");
      if (order.order_status !== "SHIPPED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE orders SET order_status = 'DELIVERED' WHERE program_id = ? AND order_id = ?`).run(programId, orderId);
      const row = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      return { status: 200, body: orderResponse(row) };
    });
  });
}
