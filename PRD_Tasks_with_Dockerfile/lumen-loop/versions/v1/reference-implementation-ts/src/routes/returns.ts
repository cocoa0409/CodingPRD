import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import { getCustomerOrThrow, getProgramOrThrow, hasRecallCampaignAffectingBuildTag, recomputeAvailability } from "../domain";
import { runMutating } from "./helpers";
import { returnResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerReturnsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/orders/:order_id/returns", (req, res, next) => {
    const programId = req.params.program_id;
    const orderId = req.params.order_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ resolution_preference: z.enum(["REFUND", "REPLACEMENT"]) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, orderId) as any;
      if (!order) throw notFound("Order not found");
      if (order.order_status !== "DELIVERED") throw badRequest("ERR_RETURN_NOT_ELIGIBLE", "Return not eligible");
      if (!order.device_id) throw badRequest("ERR_RETURN_NOT_ELIGIBLE", "Return not eligible");

      const existingReturn = db
        .prepare(
          `SELECT 1 AS ok FROM returns WHERE program_id = ? AND order_id = ? AND return_status NOT IN ('COMPLETED','REJECTED') LIMIT 1`
        )
        .get(programId, orderId) as any;
      const existingClaim = db
        .prepare(
          `SELECT 1 AS ok FROM claims WHERE program_id = ? AND order_id = ? AND claim_status NOT IN ('COMPLETED','CANCELED','EXPIRED') LIMIT 1`
        )
        .get(programId, orderId) as any;
      if (existingReturn || existingClaim) throw badRequest("ERR_RETURN_NOT_ELIGIBLE", "Return not eligible");

      const customer = getCustomerOrThrow(db, programId, order.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");

      const device = db
        .prepare(`SELECT device_status, build_tag, pre_quarantine_status FROM devices WHERE program_id = ? AND device_id = ?`)
        .get(programId, order.device_id) as any;
      if (!device) throw notFound("Device not found");
      const quarantinedByRecall = device.device_status === "QUARANTINED" && hasRecallCampaignAffectingBuildTag(db, programId, device.build_tag);
      const activated = device.device_status === "ACTIVE" || device.pre_quarantine_status === "ACTIVE";
      if (!quarantinedByRecall && activated) {
        throw badRequest("ERR_RETURN_NOT_ELIGIBLE", "Return not eligible");
      }

      const returnId = newId("return");
      db.prepare(
        `INSERT INTO returns (
          return_id, program_id, order_id, device_id, customer_id, return_status,
          resolution_preference, inspection_outcome, refunded_to_card_cents, refunded_to_credit_cents, replacement_device_id
        ) VALUES (?, ?, ?, ?, ?, 'REQUESTED', ?, NULL, 0, 0, NULL)`
      ).run(returnId, programId, orderId, order.device_id, order.customer_id, body.data.resolution_preference);
      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      return { status: 201, body: returnResponse(row) };
    });
  });

  app.get("/programs/:program_id/returns/:return_id", (req, res, next) => {
    try {
      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(req.params.program_id, req.params.return_id) as any;
      if (!row) throw notFound("Return not found");
      res.json(returnResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/returns/:return_id/approve", (req, res, next) => {
    const programId = req.params.program_id;
    const returnId = req.params.return_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ret = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      if (!ret) throw notFound("Return not found");
      if (ret.return_status !== "REQUESTED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE returns SET return_status = 'APPROVED' WHERE program_id = ? AND return_id = ?`).run(programId, returnId);
      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      return { status: 200, body: returnResponse(row) };
    });
  });

  app.post("/programs/:program_id/returns/:return_id/mark_inbound", (req, res, next) => {
    const programId = req.params.program_id;
    const returnId = req.params.return_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ret = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      if (!ret) throw notFound("Return not found");
      if (ret.return_status !== "APPROVED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE returns SET return_status = 'INBOUND' WHERE program_id = ? AND return_id = ?`).run(programId, returnId);
      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      return { status: 200, body: returnResponse(row) };
    });
  });

  app.post("/programs/:program_id/returns/:return_id/receive", (req, res, next) => {
    const programId = req.params.program_id;
    const returnId = req.params.return_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ inspection_outcome: z.enum(["RESTOCK", "REFURB", "SCRAP"]) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const ret = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      if (!ret) throw notFound("Return not found");
      if (ret.return_status !== "INBOUND") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

      const device = db
        .prepare(`SELECT device_status, pre_quarantine_status, build_tag FROM devices WHERE program_id = ? AND device_id = ?`)
        .get(programId, ret.device_id) as any;
      if (!device) throw notFound("Device not found");
      const activated = device.device_status === "ACTIVE" || device.pre_quarantine_status === "ACTIVE";
      const quarantined = device.device_status === "QUARANTINED";
      if (body.data.inspection_outcome === "RESTOCK" && (activated || quarantined)) {
        throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
      }

      db.prepare(`UPDATE returns SET return_status = 'RECEIVED', inspection_outcome = ? WHERE program_id = ? AND return_id = ?`).run(
        body.data.inspection_outcome,
        programId,
        returnId
      );
      if (body.data.inspection_outcome === "RESTOCK") {
        const lotId = newId("buildlot");
        db.prepare(
          `INSERT INTO build_lots (build_lot_id, program_id, build_tag, build_lot_status, units_total, units_remaining, quarantined_by_campaign_id)
           VALUES (?, ?, ?, 'AVAILABLE', 1, 1, NULL)`
        ).run(lotId, programId, device.build_tag);
        recomputeAvailability(db, programId);
      }

      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      return { status: 200, body: returnResponse(row) };
    });
  });

  app.post("/programs/:program_id/returns/:return_id/complete", (req, res, next) => {
    const programId = req.params.program_id;
    const returnId = req.params.return_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({
          resolution: z.enum(["REFUND", "REPLACEMENT"]),
          replacement_build_lot_id: z.string().min(1).nullable(),
          replacement_serial_number: z.string().min(1).nullable(),
          replacement_build_tag: z.string().min(1).nullable(),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const ret = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      if (!ret) throw notFound("Return not found");
      if (ret.return_status !== "RECEIVED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

      const order = db.prepare(`SELECT * FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, ret.order_id) as any;
      if (!order) throw notFound("Order not found");
      const customer = getCustomerOrThrow(db, programId, ret.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");

      const device = db
        .prepare(`SELECT device_status, build_tag FROM devices WHERE program_id = ? AND device_id = ?`)
        .get(programId, ret.device_id) as any;
      if (!device) throw notFound("Device not found");

      if (body.data.resolution === "REFUND") {
        let refundedToCard = 0;
        if (order.payment_id) {
          const payment = db
            .prepare(`SELECT payment_status, amount_cents FROM payments WHERE program_id = ? AND payment_id = ?`)
            .get(programId, order.payment_id) as any;
          if (payment?.payment_status === "CAPTURED") {
            refundedToCard = payment.amount_cents;
            db.prepare(`UPDATE payments SET payment_status = 'REFUNDED' WHERE program_id = ? AND payment_id = ?`).run(programId, order.payment_id);
          } else if (payment && payment.amount_cents > 0 && payment.payment_status !== "REFUNDED") {
            throw badRequest("ERR_PAYMENT_NOT_REFUNDABLE", "Payment not refundable");
          }
        }

        let refundedToCredit = 0;
        if (order.paid_by_credit_cents > 0) {
          const currentCustomer = getCustomerOrThrow(db, programId, ret.customer_id);
          const toDue = Math.min(currentCustomer.balance_due_cents, order.paid_by_credit_cents);
          refundedToCredit = order.paid_by_credit_cents - toDue;
          db.prepare(
            `UPDATE customers
             SET balance_due_cents = balance_due_cents - ?, credit_balance_cents = credit_balance_cents + ?
             WHERE program_id = ? AND customer_id = ?`
          ).run(toDue, refundedToCredit, programId, ret.customer_id);
        }

        db.prepare(`UPDATE orders SET order_status = 'REFUNDED' WHERE program_id = ? AND order_id = ?`).run(programId, order.order_id);
        const deviceStatus = ret.inspection_outcome === "SCRAP" ? "SCRAPPED" : "RETURNED";
        db.prepare(`UPDATE devices SET device_status = ?, pre_quarantine_status = NULL WHERE program_id = ? AND device_id = ?`).run(deviceStatus, programId, ret.device_id);

        if (order.care_plan_id) {
          const plan = db
            .prepare(`SELECT care_plan_status FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
            .get(programId, order.care_plan_id) as any;
          const newStatus = plan?.care_plan_status === "PENDING_ACTIVATION" ? "VOIDED" : "CANCELED";
          db.prepare(`UPDATE care_plans SET care_plan_status = ? WHERE program_id = ? AND care_plan_id = ?`).run(newStatus, programId, order.care_plan_id);
        }

        db.prepare(
          `UPDATE returns
           SET return_status = 'COMPLETED', refunded_to_card_cents = ?, refunded_to_credit_cents = ?
           WHERE program_id = ? AND return_id = ?`
        ).run(refundedToCard, refundedToCredit, programId, returnId);
        const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
        return { status: 200, body: returnResponse(row) };
      }

      if (ret.inspection_outcome === "RESTOCK") throw badRequest("ERR_RETURN_NOT_RESOLVABLE", "Return not resolvable");
      if (program.program_posture === "PROGRAM_FROZEN") {
        const isRecallRemediation = device.device_status === "QUARANTINED" && hasRecallCampaignAffectingBuildTag(db, programId, device.build_tag);
        if (!isRecallRemediation) throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
      }
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");
      if (program.program_posture === "PROGRAM_GUARDED") throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");

      if (program.replacement_reserve_remaining <= 0 && program.available_to_commit_units <= 0) {
        throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
      }
      if (!body.data.replacement_build_lot_id || !body.data.replacement_serial_number || !body.data.replacement_build_tag) {
        throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
      }
      const lot = db
        .prepare(`SELECT build_lot_id, build_tag, build_lot_status, units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`)
        .get(programId, body.data.replacement_build_lot_id) as any;
      if (!lot) throw notFound("Build lot not found");
      if (lot.build_lot_status !== "AVAILABLE") throw badRequest("ERR_BUILD_LOT_QUARANTINED", "Build lot quarantined");
      if (lot.units_remaining <= 0) throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
      if (lot.build_tag !== body.data.replacement_build_tag) throw badRequest("ERR_INVALID_REQUEST", "Invalid request");

      const replacementDeviceId = newId("device");
      db.prepare(
        `INSERT INTO devices (
          device_id, program_id, order_id, customer_id, serial_number, build_tag,
          device_status, pre_quarantine_status, activated_ops_run_index, created_by_claim_id, created_by_return_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'SHIPPED', NULL, NULL, NULL, ?)`
      ).run(
        replacementDeviceId,
        programId,
        order.order_id,
        order.customer_id,
        body.data.replacement_serial_number,
        body.data.replacement_build_tag,
        returnId
      );
      db.prepare(`UPDATE orders SET device_id = ? WHERE program_id = ? AND order_id = ?`).run(replacementDeviceId, programId, order.order_id);

      const oldDeviceStatus = ret.inspection_outcome === "SCRAP" ? "SCRAPPED" : "RETURNED";
      db.prepare(`UPDATE devices SET device_status = ?, pre_quarantine_status = NULL WHERE program_id = ? AND device_id = ?`).run(oldDeviceStatus, programId, ret.device_id);

      if (order.care_plan_id) {
        const plan = db
          .prepare(`SELECT care_plan_status, paused_reason FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        db.prepare(`UPDATE care_plans SET device_id = ? WHERE program_id = ? AND care_plan_id = ?`).run(replacementDeviceId, programId, order.care_plan_id);
        if (plan?.care_plan_status === "ACTIVE") {
          db.prepare(`UPDATE care_plans SET care_plan_status = 'PENDING_ACTIVATION' WHERE program_id = ? AND care_plan_id = ?`).run(programId, order.care_plan_id);
        }
      }

      if (program.replacement_reserve_remaining > 0) {
        db.prepare(`UPDATE programs SET replacement_reserve_remaining = replacement_reserve_remaining - 1 WHERE program_id = ?`).run(programId);
      }
      db.prepare(`UPDATE build_lots SET units_remaining = units_remaining - 1 WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
      const afterLot = db.prepare(`SELECT units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`).get(programId, lot.build_lot_id) as any;
      if (afterLot.units_remaining <= 0) {
        db.prepare(`UPDATE build_lots SET build_lot_status = 'CONSUMED' WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
      }

      db.prepare(`UPDATE returns SET return_status = 'COMPLETED', replacement_device_id = ? WHERE program_id = ? AND return_id = ?`).run(replacementDeviceId, programId, returnId);
      recomputeAvailability(db, programId);
      const row = db.prepare(`SELECT * FROM returns WHERE program_id = ? AND return_id = ?`).get(programId, returnId) as any;
      return { status: 200, body: returnResponse(row) };
    });
  });
}
