import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import {
  getCustomerOrThrow,
  getProgramOrThrow,
  hasRecallCampaignAffectingBuildTag,
  putCustomerUnshippedOrdersOnHold,
  recomputeAvailability,
} from "../domain";
import { runMutating } from "./helpers";
import { claimResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerClaimsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/devices/:device_id/claims", (req, res, next) => {
    const programId = req.params.program_id;
    const deviceId = req.params.device_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ claim_type: z.enum(["WARRANTY", "CARE_PLAN", "RECALL"]) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const device = db
        .prepare(
          `SELECT device_id, order_id, customer_id, device_status, activated_ops_run_index, build_tag
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(programId, deviceId) as any;
      if (!device) throw notFound("Device not found");

      const order = db
        .prepare(`SELECT order_id, care_plan_id FROM orders WHERE program_id = ? AND order_id = ?`)
        .get(programId, device.order_id) as any;
      if (!order) throw notFound("Order not found");

      const existingClaim = db
        .prepare(
          `SELECT 1 AS ok FROM claims
           WHERE program_id = ? AND device_id = ? AND claim_status NOT IN ('COMPLETED','CANCELED','EXPIRED')
           LIMIT 1`
        )
        .get(programId, deviceId) as any;
      if (existingClaim) throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");

      const existingReturn = db
        .prepare(
          `SELECT 1 AS ok FROM returns
           WHERE program_id = ? AND order_id = ? AND return_status NOT IN ('COMPLETED','REJECTED')
           LIMIT 1`
        )
        .get(programId, device.order_id) as any;
      if (existingReturn) throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");

      const customer = getCustomerOrThrow(db, programId, device.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");

      if (body.data.claim_type === "WARRANTY") {
        if (device.device_status !== "ACTIVE" || device.activated_ops_run_index === null) {
          throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
        }
        if (program.ops_run_index >= device.activated_ops_run_index + 12) {
          throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
        }
      } else if (body.data.claim_type === "CARE_PLAN") {
        if (!order.care_plan_id) throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
        const plan = db
          .prepare(`SELECT care_plan_status FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        if (!plan || plan.care_plan_status !== "ACTIVE") throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
      } else {
        if (device.device_status !== "QUARANTINED") throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
        if (!hasRecallCampaignAffectingBuildTag(db, programId, device.build_tag)) {
          throw badRequest("ERR_CLAIM_NOT_ELIGIBLE", "Claim not eligible");
        }
      }

      const claimId = newId("claim");
      db.prepare(
        `INSERT INTO claims (
          claim_id, program_id, order_id, device_id, customer_id,
          claim_status, claim_type, claim_resolution, inspection_outcome, replacement_device_id,
          approved_ops_run_index, inbound_ops_run_index, advance_shipped_ops_run_index
        ) VALUES (?, ?, ?, ?, ?, 'OPEN', ?, NULL, NULL, NULL, NULL, NULL, NULL)`
      ).run(claimId, programId, device.order_id, deviceId, device.customer_id, body.data.claim_type);

      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 201, body: claimResponse(row) };
    });
  });

  app.get("/programs/:program_id/claims/:claim_id", (req, res, next) => {
    try {
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(req.params.program_id, req.params.claim_id) as any;
      if (!row) throw notFound("Claim not found");
      res.json(claimResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/claims/:claim_id/approve", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ resolution: z.enum(["REPLACEMENT", "ADVANCE_REPLACEMENT"]) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (claim.claim_status !== "OPEN") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      if (body.data.resolution === "ADVANCE_REPLACEMENT" && claim.claim_type !== "RECALL") {
        throw badRequest("ERR_CLAIM_NOT_RESOLVABLE", "Claim not resolvable");
      }
      db.prepare(
        `UPDATE claims SET claim_status = 'APPROVED', claim_resolution = ?, approved_ops_run_index = ?
         WHERE program_id = ? AND claim_id = ?`
      ).run(body.data.resolution, program.ops_run_index, programId, claimId);

      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });

  app.post("/programs/:program_id/claims/:claim_id/cancel", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ reason: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (!["OPEN", "APPROVED", "INBOUND"].includes(claim.claim_status)) {
        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      }
      if (claim.replacement_device_id) throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE claims SET claim_status = 'CANCELED' WHERE program_id = ? AND claim_id = ?`).run(programId, claimId);
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });

  app.post("/programs/:program_id/claims/:claim_id/mark_inbound", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (!["APPROVED", "ADVANCE_SHIPPED"].includes(claim.claim_status)) {
        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      }
      db.prepare(`UPDATE claims SET claim_status = 'INBOUND', inbound_ops_run_index = ? WHERE program_id = ? AND claim_id = ?`).run(
        program.ops_run_index,
        programId,
        claimId
      );
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });

  app.post("/programs/:program_id/claims/:claim_id/receive", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z.object({ inspection_outcome: z.enum(["REFURB", "SCRAP"]) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (!["INBOUND", "ADVANCE_SHIPPED"].includes(claim.claim_status)) {
        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      }
      db.prepare(`UPDATE claims SET claim_status = 'RECEIVED', inspection_outcome = ? WHERE program_id = ? AND claim_id = ?`).run(
        body.data.inspection_outcome,
        programId,
        claimId
      );
      const newDeviceStatus = body.data.inspection_outcome === "SCRAP" ? "SCRAPPED" : "RETURNED";
      db.prepare(`UPDATE devices SET device_status = ? WHERE program_id = ? AND device_id = ?`).run(newDeviceStatus, programId, claim.device_id);
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });

  app.post("/programs/:program_id/claims/:claim_id/ship_advance_replacement", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({
          replacement_build_lot_id: z.string().min(1),
          replacement_serial_number: z.string().min(1),
          replacement_build_tag: z.string().min(1),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (claim.claim_status !== "APPROVED" || claim.claim_resolution !== "ADVANCE_REPLACEMENT") {
        throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      }

      const ctx = (req as any as RequestWithCtx).ctx!;
      if (program.replacement_reserve_remaining <= 0 && ctx.actorType !== "Ops") {
        throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
      }

      const lot = db
        .prepare(`SELECT build_lot_id, build_tag, build_lot_status, units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`)
        .get(programId, body.data.replacement_build_lot_id) as any;
      if (!lot) throw notFound("Build lot not found");
      if (lot.build_lot_status !== "AVAILABLE") throw badRequest("ERR_BUILD_LOT_QUARANTINED", "Build lot quarantined");
      if (lot.units_remaining <= 0) throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
      if (lot.build_tag !== body.data.replacement_build_tag) throw badRequest("ERR_INVALID_REQUEST", "Invalid request");

      const deposit = 15000;
      db.prepare(
        `UPDATE customers
         SET balance_due_cents = balance_due_cents + ?,
             customer_status = CASE WHEN customer_status = 'ACTIVE' THEN 'LIMITED' ELSE customer_status END
         WHERE program_id = ? AND customer_id = ?`
      ).run(deposit, programId, claim.customer_id);
      putCustomerUnshippedOrdersOnHold(db, programId, claim.customer_id, "AFTERCARE_DEPOSIT_HOLD");

      const replacementDeviceId = newId("device");
      db.prepare(
        `INSERT INTO devices (
          device_id, program_id, order_id, customer_id, serial_number, build_tag,
          device_status, pre_quarantine_status, activated_ops_run_index, created_by_claim_id, created_by_return_id
        ) VALUES (?, ?, ?, ?, ?, ?, 'SHIPPED', NULL, NULL, ?, NULL)`
      ).run(
        replacementDeviceId,
        programId,
        claim.order_id,
        claim.customer_id,
        body.data.replacement_serial_number,
        body.data.replacement_build_tag,
        claimId
      );
      db.prepare(`UPDATE orders SET device_id = ? WHERE program_id = ? AND order_id = ?`).run(replacementDeviceId, programId, claim.order_id);

      const order = db
        .prepare(`SELECT care_plan_id FROM orders WHERE program_id = ? AND order_id = ?`)
        .get(programId, claim.order_id) as any;
      if (order?.care_plan_id) {
        const plan = db
          .prepare(`SELECT care_plan_status FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        db.prepare(`UPDATE care_plans SET device_id = ? WHERE program_id = ? AND care_plan_id = ?`).run(
          replacementDeviceId,
          programId,
          order.care_plan_id
        );
        if (plan?.care_plan_status === "ACTIVE") {
          db.prepare(`UPDATE care_plans SET care_plan_status = 'PENDING_ACTIVATION' WHERE program_id = ? AND care_plan_id = ?`).run(
            programId,
            order.care_plan_id
          );
        }
      }

      db.prepare(`UPDATE claims SET claim_status = 'ADVANCE_SHIPPED', replacement_device_id = ?, advance_shipped_ops_run_index = ? WHERE program_id = ? AND claim_id = ?`).run(
        replacementDeviceId,
        program.ops_run_index,
        programId,
        claimId
      );

      if (program.replacement_reserve_remaining > 0) {
        db.prepare(`UPDATE programs SET replacement_reserve_remaining = replacement_reserve_remaining - 1 WHERE program_id = ?`).run(programId);
      }

      db.prepare(`UPDATE build_lots SET units_remaining = units_remaining - 1 WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
      const afterLot = db.prepare(`SELECT units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`).get(programId, lot.build_lot_id) as any;
      if (afterLot.units_remaining <= 0) {
        db.prepare(`UPDATE build_lots SET build_lot_status = 'CONSUMED' WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
      }

      recomputeAvailability(db, programId);
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });

  app.post("/programs/:program_id/claims/:claim_id/complete", (req, res, next) => {
    const programId = req.params.program_id;
    const claimId = req.params.claim_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const body = z
        .object({
          replacement_build_lot_id: z.string().min(1).nullable(),
          replacement_serial_number: z.string().min(1).nullable(),
          replacement_build_tag: z.string().min(1).nullable(),
        })
        .safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const claim = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      if (!claim) throw notFound("Claim not found");
      if (!["RECEIVED", "ADVANCE_SHIPPED"].includes(claim.claim_status)) throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

      const ctx = (req as any as RequestWithCtx).ctx!;
      const alreadyHasReplacement = Boolean(claim.replacement_device_id);
      const willShipReplacementNow = !alreadyHasReplacement;

      if (willShipReplacementNow) {
        if (program.program_posture === "PROGRAM_GUARDED") {
          throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");
        }
        if (program.program_posture === "PROGRAM_FROZEN") {
          const hasRecall = db
            .prepare(
              `SELECT 1 AS ok FROM quality_campaigns
               WHERE program_id = ? AND campaign_type = 'RECALL' AND campaign_status != 'CLOSED'
               LIMIT 1`
            )
            .get(programId) as { ok: 1 } | undefined;
          if (!(hasRecall && claim.claim_type === "RECALL")) {
            throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
          }
        }
      }

      if (willShipReplacementNow) {
        if (!body.data.replacement_build_lot_id || !body.data.replacement_serial_number || !body.data.replacement_build_tag) {
          throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
        }
        if (program.replacement_reserve_remaining <= 0 && ctx.actorType !== "Ops") throw badRequest("ERR_OUT_OF_STOCK", "Out of stock");
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
          ) VALUES (?, ?, ?, ?, ?, ?, 'SHIPPED', NULL, NULL, ?, NULL)`
        ).run(
          replacementDeviceId,
          programId,
          claim.order_id,
          claim.customer_id,
          body.data.replacement_serial_number,
          body.data.replacement_build_tag,
          claimId
        );
        db.prepare(`UPDATE orders SET device_id = ? WHERE program_id = ? AND order_id = ?`).run(replacementDeviceId, programId, claim.order_id);
        db.prepare(`UPDATE claims SET replacement_device_id = ? WHERE program_id = ? AND claim_id = ?`).run(replacementDeviceId, programId, claimId);
        if (program.replacement_reserve_remaining > 0) {
          db.prepare(`UPDATE programs SET replacement_reserve_remaining = replacement_reserve_remaining - 1 WHERE program_id = ?`).run(programId);
        }
        db.prepare(`UPDATE build_lots SET units_remaining = units_remaining - 1 WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
        const afterLot = db.prepare(`SELECT units_remaining FROM build_lots WHERE program_id = ? AND build_lot_id = ?`).get(programId, lot.build_lot_id) as any;
        if (afterLot.units_remaining <= 0) {
          db.prepare(`UPDATE build_lots SET build_lot_status = 'CONSUMED' WHERE program_id = ? AND build_lot_id = ?`).run(programId, lot.build_lot_id);
        }
      } else {
        if (body.data.replacement_build_lot_id || body.data.replacement_serial_number || body.data.replacement_build_tag) {
          throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
        }
      }

      const order = db.prepare(`SELECT care_plan_id, device_id FROM orders WHERE program_id = ? AND order_id = ?`).get(programId, claim.order_id) as any;
      if (order?.care_plan_id) {
        const plan = db
          .prepare(`SELECT care_plan_status, paused_reason FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        db.prepare(`UPDATE care_plans SET device_id = ? WHERE program_id = ? AND care_plan_id = ?`).run(order.device_id, programId, order.care_plan_id);
        if (plan?.care_plan_status === "ACTIVE") {
          db.prepare(`UPDATE care_plans SET care_plan_status = 'PENDING_ACTIVATION' WHERE program_id = ? AND care_plan_id = ?`).run(programId, order.care_plan_id);
        }
      }

      if (claim.claim_resolution === "ADVANCE_REPLACEMENT") {
        const deposit = 15000;
        const customer = getCustomerOrThrow(db, programId, claim.customer_id);
        const toDue = Math.min(customer.balance_due_cents, deposit);
        const toCredit = deposit - toDue;
        db.prepare(
          `UPDATE customers
           SET balance_due_cents = balance_due_cents - ?, credit_balance_cents = credit_balance_cents + ?
           WHERE program_id = ? AND customer_id = ?`
        ).run(toDue, toCredit, programId, claim.customer_id);
        const after = getCustomerOrThrow(db, programId, claim.customer_id);
        if (after.balance_due_cents === 0) {
          db.prepare(`UPDATE customers SET balance_due_cleared_ops_run_index = ? WHERE program_id = ? AND customer_id = ?`).run(
            program.ops_run_index,
            programId,
            claim.customer_id
          );
        }
      }

      db.prepare(`UPDATE claims SET claim_status = 'COMPLETED' WHERE program_id = ? AND claim_id = ?`).run(programId, claimId);

      recomputeAvailability(db, programId);
      const row = db.prepare(`SELECT * FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, claimId) as any;
      return { status: 200, body: claimResponse(row) };
    });
  });
}
