import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, forbidden, notFound } from "../errors";
import { newId } from "../ids";
import { getCampaignOrThrow, getProgramOrThrow, openAlertDeduped, recomputeAvailability, recomputePosture, setProgramFrozen } from "../domain";
import { runMutating } from "./helpers";
import { qualityCampaignResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerQualityCampaignRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/quality_campaigns", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const body = z.object({ campaign_type: z.enum(["SHIP_HOLD", "RECALL"]), build_tag_prefix: z.string().min(1) }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");

      const campaignId = newId("campaign");
      db.prepare(
        `INSERT INTO quality_campaigns (quality_campaign_id, program_id, campaign_type, campaign_status, build_tag_prefix)
         VALUES (?, ?, ?, 'OPEN', ?)`
      ).run(campaignId, programId, body.data.campaign_type, body.data.build_tag_prefix);

      db.prepare(
        `UPDATE build_lots
         SET build_lot_status = 'QUARANTINED', quarantined_by_campaign_id = ?
         WHERE program_id = ? AND build_lot_status = 'AVAILABLE' AND build_tag LIKE ? || '%'`
      ).run(campaignId, programId, body.data.build_tag_prefix);

      if (body.data.campaign_type === "RECALL") {
        const affected = db
          .prepare(
            `SELECT device_id FROM devices
             WHERE program_id = ? AND build_tag LIKE ? || '%' AND device_status IN ('ACTIVE','SHIPPED')`
          )
          .all(programId, body.data.build_tag_prefix) as { device_id: string }[];
        for (const d of affected) {
          db.prepare(
            `UPDATE devices SET pre_quarantine_status = device_status, device_status = 'QUARANTINED'
             WHERE program_id = ? AND device_id = ?`
          ).run(programId, d.device_id);
        }
        db.prepare(
          `UPDATE care_plans
           SET care_plan_status = 'PAUSED', paused_reason = 'RECALL'
           WHERE program_id = ? AND device_id IN (
             SELECT device_id FROM devices WHERE program_id = ? AND build_tag LIKE ? || '%' AND device_status = 'QUARANTINED'
           ) AND care_plan_status IN ('ACTIVE','PENDING_ACTIVATION')`
        ).run(programId, programId, body.data.build_tag_prefix);

        setProgramFrozen(db, programId);
        openAlertDeduped(db, programId, { alert_type: "RECALL_ACTIVE", quality_campaign_id: campaignId });
      }

      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db.prepare(`SELECT * FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(programId, campaignId) as any;
      return { status: 201, body: qualityCampaignResponse(row) };
    });
  });

  app.get("/programs/:program_id/quality_campaigns/:quality_campaign_id", (req, res, next) => {
    try {
      const row = db.prepare(`SELECT * FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(req.params.program_id, req.params.quality_campaign_id) as any;
      if (!row) throw notFound("Quality campaign not found");
      res.json(qualityCampaignResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/quality_campaigns/:quality_campaign_id/escalate", (req, res, next) => {
    const programId = req.params.program_id;
    const campaignId = req.params.quality_campaign_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const campaign = getCampaignOrThrow(db, programId, campaignId);
      if (campaign.campaign_type !== "SHIP_HOLD") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE quality_campaigns SET campaign_type = 'RECALL' WHERE program_id = ? AND quality_campaign_id = ?`).run(programId, campaignId);

      const affected = db
        .prepare(
          `SELECT device_id FROM devices
           WHERE program_id = ? AND build_tag LIKE ? || '%' AND device_status IN ('ACTIVE','SHIPPED')`
        )
        .all(programId, campaign.build_tag_prefix) as { device_id: string }[];
      for (const d of affected) {
        db.prepare(
          `UPDATE devices SET pre_quarantine_status = device_status, device_status = 'QUARANTINED'
           WHERE program_id = ? AND device_id = ?`
        ).run(programId, d.device_id);
      }
      db.prepare(
        `UPDATE care_plans
         SET care_plan_status = 'PAUSED', paused_reason = 'RECALL'
         WHERE program_id = ? AND device_id IN (
           SELECT device_id FROM devices WHERE program_id = ? AND build_tag LIKE ? || '%' AND device_status = 'QUARANTINED'
         ) AND care_plan_status IN ('ACTIVE','PENDING_ACTIVATION')`
      ).run(programId, programId, campaign.build_tag_prefix);

      setProgramFrozen(db, programId);
      openAlertDeduped(db, programId, { alert_type: "RECALL_ACTIVE", quality_campaign_id: campaignId });
      recomputeAvailability(db, programId);
      const row = db.prepare(`SELECT * FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(programId, campaignId) as any;
      return { status: 200, body: qualityCampaignResponse(row) };
    });
  });

  app.post("/programs/:program_id/quality_campaigns/:quality_campaign_id/resolve", (req, res, next) => {
    const programId = req.params.program_id;
    const campaignId = req.params.quality_campaign_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const campaign = getCampaignOrThrow(db, programId, campaignId);
      if (campaign.campaign_type === "RECALL") {
        const remaining = db
          .prepare(
            `SELECT 1 AS ok FROM devices
             WHERE program_id = ? AND build_tag LIKE ? || '%' AND device_status = 'QUARANTINED'
             LIMIT 1`
          )
          .get(programId, campaign.build_tag_prefix) as any;
        if (remaining) throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
      }
      db.prepare(`UPDATE quality_campaigns SET campaign_status = 'RESOLVED' WHERE program_id = ? AND quality_campaign_id = ?`).run(programId, campaignId);
      const row = db.prepare(`SELECT * FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(programId, campaignId) as any;
      return { status: 200, body: qualityCampaignResponse(row) };
    });
  });

  app.post("/programs/:program_id/quality_campaigns/:quality_campaign_id/close", (req, res, next) => {
    const programId = req.params.program_id;
    const campaignId = req.params.quality_campaign_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const campaign = getCampaignOrThrow(db, programId, campaignId);
      if (campaign.campaign_type === "RECALL" && campaign.campaign_status !== "RESOLVED") {
        throw badRequest("ERR_INVALID_REQUEST", "Invalid request");
      }
      db.prepare(`UPDATE quality_campaigns SET campaign_status = 'CLOSED' WHERE program_id = ? AND quality_campaign_id = ?`).run(programId, campaignId);

      if (campaign.campaign_type === "SHIP_HOLD") {
        db.prepare(
          `UPDATE build_lots
           SET build_lot_status = 'AVAILABLE', quarantined_by_campaign_id = NULL
           WHERE program_id = ?
             AND build_lot_status = 'QUARANTINED'
             AND build_tag LIKE ? || '%'
             AND NOT EXISTS (
               SELECT 1 AS ok FROM quality_campaigns qc
               WHERE qc.program_id = build_lots.program_id
                 AND qc.campaign_status != 'CLOSED'
                 AND build_lots.build_tag LIKE qc.build_tag_prefix || '%'
             )`
        ).run(programId, campaign.build_tag_prefix);
      }
      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db.prepare(`SELECT * FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(programId, campaignId) as any;
      return { status: 200, body: qualityCampaignResponse(row) };
    });
  });
}
