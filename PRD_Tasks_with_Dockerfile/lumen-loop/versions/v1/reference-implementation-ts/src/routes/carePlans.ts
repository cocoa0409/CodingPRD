import type express from "express";
import type { Db } from "../db";
import { notFound } from "../errors";
import { carePlanResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerCarePlansRoutes(
  app: express.Express,
  db: Db,
  _requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.get("/programs/:program_id/care_plans/:care_plan_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT care_plan_id, order_id, customer_id, device_id, care_plan_status
           FROM care_plans WHERE program_id = ? AND care_plan_id = ?`
        )
        .get(req.params.program_id, req.params.care_plan_id) as any;
      if (!row) throw notFound("Care plan not found");
      res.json(carePlanResponse(row));
    } catch (e) {
      next(e);
    }
  });
}
