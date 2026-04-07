import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, forbidden, notFound } from "../errors";
import { newId } from "../ids";
import { recomputeAvailability, recomputePosture } from "../domain";
import { runMutating } from "./helpers";
import { buildLotResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerBuildLotsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/build_lots", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const ctx = (req as any as RequestWithCtx).ctx!;
      if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
      const body = z.object({ build_tag: z.string().min(1), units: z.number().int().positive() }).safeParse(req.body);
      if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

      const quarantiningCampaign = db
        .prepare(
          `SELECT quality_campaign_id
           FROM quality_campaigns
           WHERE program_id = ? AND campaign_status != 'CLOSED' AND ? LIKE build_tag_prefix || '%'
           LIMIT 1`
        )
        .get(programId, body.data.build_tag) as { quality_campaign_id: string } | undefined;
      const status = quarantiningCampaign ? "QUARANTINED" : "AVAILABLE";

      const buildLotId = newId("buildlot");
      db.prepare(
        `INSERT INTO build_lots (build_lot_id, program_id, build_tag, build_lot_status, units_total, units_remaining, quarantined_by_campaign_id)
         VALUES (?, ?, ?, ?, ?, ?, ?)`
      ).run(
        buildLotId,
        programId,
        body.data.build_tag,
        status,
        body.data.units,
        body.data.units,
        quarantiningCampaign?.quality_campaign_id ?? null
      );
      recomputeAvailability(db, programId);
      recomputePosture(db, programId);
      const row = db
        .prepare(`SELECT build_lot_id, build_tag, build_lot_status FROM build_lots WHERE program_id = ? AND build_lot_id = ?`)
        .get(programId, buildLotId) as any;
      return { status: 201, body: buildLotResponse(row) };
    });
  });

  app.get("/programs/:program_id/build_lots/:build_lot_id", (req, res, next) => {
    try {
      const row = db
        .prepare(`SELECT build_lot_id, build_tag, build_lot_status FROM build_lots WHERE program_id = ? AND build_lot_id = ?`)
        .get(req.params.program_id, req.params.build_lot_id) as any;
      if (!row) throw notFound("Build lot not found");
      res.json(buildLotResponse(row));
    } catch (e) {
      next(e);
    }
  });
}
