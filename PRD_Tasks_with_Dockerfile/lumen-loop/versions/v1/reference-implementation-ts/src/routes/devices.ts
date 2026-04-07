import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, forbidden, notFound } from "../errors";
import { getCustomerOrThrow, getProgramOrThrow } from "../domain";
import { runMutating } from "./helpers";
import { deviceResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerDevicesRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.get("/programs/:program_id/devices/:device_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT device_id, order_id, customer_id, serial_number, build_tag, device_status
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(req.params.program_id, req.params.device_id) as any;
      if (!row) throw notFound("Device not found");
      res.json(deviceResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/devices/:device_id/activate", (req, res, next) => {
    const programId = req.params.program_id;
    const deviceId = req.params.device_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType === "Support" || ctx.actorType === "Ops") throw forbidden("Forbidden for actor");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const device = db
        .prepare(
          `SELECT device_id, order_id, customer_id, device_status, created_by_claim_id, build_tag
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(programId, deviceId) as any;
      if (!device) throw notFound("Device not found");
      if (device.device_status === "QUARANTINED") throw badRequest("ERR_DEVICE_QUARANTINED", "Device quarantined");

      const order = db
        .prepare(`SELECT order_status, care_plan_id FROM orders WHERE program_id = ? AND order_id = ?`)
        .get(programId, device.order_id) as any;
      if (!order) throw notFound("Order not found");
      if (order.order_status !== "DELIVERED") throw badRequest("ERR_DEVICE_NOT_ACTIVATABLE", "Device not activatable");

      const customer = getCustomerOrThrow(db, programId, device.customer_id);
      if (customer.customer_status === "CLOSED") throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
      if (customer.customer_status === "LOCKED") throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");

      if (program.program_posture === "PROGRAM_FROZEN") {
        const recallFrozenActivationOk = Boolean(
          db
            .prepare(
              `SELECT 1 AS ok FROM quality_campaigns
               WHERE program_id = ? AND campaign_type = 'RECALL' AND campaign_status != 'CLOSED'
               LIMIT 1`
            )
            .get(programId)
        )
          && Boolean(
            device.created_by_claim_id &&
              db
                .prepare(
                  `SELECT 1 AS ok FROM claims
                   WHERE program_id = ? AND claim_id = ? AND claim_type = 'RECALL'
                   LIMIT 1`
                )
                .get(programId, device.created_by_claim_id)
          );
        if (!recallFrozenActivationOk) throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
      }

      db.prepare(`UPDATE devices SET device_status = 'ACTIVE', activated_ops_run_index = ? WHERE program_id = ? AND device_id = ?`).run(
        program.ops_run_index,
        programId,
        deviceId
      );
      if (order.care_plan_id) {
        const plan = db
          .prepare(`SELECT care_plan_status, paused_reason FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        if (plan?.care_plan_status === "PENDING_ACTIVATION") {
          db.prepare(`UPDATE care_plans SET care_plan_status = 'ACTIVE' WHERE program_id = ? AND care_plan_id = ?`).run(
            programId,
            order.care_plan_id
          );
        } else if (plan?.care_plan_status === "PAUSED" && plan.paused_reason === "RECALL") {
          db.prepare(
            `UPDATE care_plans SET care_plan_status = 'ACTIVE', paused_reason = NULL
             WHERE program_id = ? AND care_plan_id = ?`
          ).run(programId, order.care_plan_id);
        }
      }
      const row = db
        .prepare(
          `SELECT device_id, order_id, customer_id, serial_number, build_tag, device_status
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(programId, deviceId) as any;
      return { status: 200, body: deviceResponse(row) };
    });
  });

  app.post("/programs/:program_id/devices/:device_id/remediate", (req, res, next) => {
    const programId = req.params.program_id;
    const deviceId = req.params.device_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const body = z.object({ note: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const device = db
        .prepare(
          `SELECT device_id, device_status, pre_quarantine_status, order_id
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(programId, deviceId) as any;
      if (!device) throw notFound("Device not found");
      if (device.device_status !== "QUARANTINED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      const restoreTo = device.pre_quarantine_status ?? "SHIPPED";
      db.prepare(`UPDATE devices SET device_status = ?, pre_quarantine_status = NULL WHERE program_id = ? AND device_id = ?`).run(
        restoreTo,
        programId,
        deviceId
      );

      const order = db
        .prepare(`SELECT care_plan_id FROM orders WHERE program_id = ? AND order_id = ?`)
        .get(programId, device.order_id) as any;
      if (order?.care_plan_id) {
        const plan = db
          .prepare(`SELECT care_plan_status, paused_reason FROM care_plans WHERE program_id = ? AND care_plan_id = ?`)
          .get(programId, order.care_plan_id) as any;
        if (plan?.care_plan_status === "PAUSED" && plan.paused_reason === "RECALL") {
          const newStatus = restoreTo === "ACTIVE" ? "ACTIVE" : "PENDING_ACTIVATION";
          db.prepare(`UPDATE care_plans SET care_plan_status = ?, paused_reason = NULL WHERE program_id = ? AND care_plan_id = ?`).run(
            newStatus,
            programId,
            order.care_plan_id
          );
        }
      }

      const row = db
        .prepare(
          `SELECT device_id, order_id, customer_id, serial_number, build_tag, device_status
           FROM devices WHERE program_id = ? AND device_id = ?`
        )
        .get(programId, deviceId) as any;
      return { status: 200, body: deviceResponse(row) };
    });
  });
}
