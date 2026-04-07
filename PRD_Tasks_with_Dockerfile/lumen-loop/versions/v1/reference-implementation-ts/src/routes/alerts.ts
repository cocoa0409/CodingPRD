import type express from "express";
import type { Db } from "../db";
import { badRequest, notFound } from "../errors";
import { computeSupplyShortfall, getAlertOrThrow, getCustomerOrThrow, getProgramOrThrow } from "../domain";
import { runMutating } from "./helpers";
import { alertResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerAlertsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.get("/programs/:program_id/alerts", (req, res, next) => {
    try {
      const programId = req.params.program_id;
      const alert_status = typeof req.query.alert_status === "string" ? req.query.alert_status : undefined;
      const alert_type = typeof req.query.alert_type === "string" ? req.query.alert_type : undefined;
      const customer_id = typeof req.query.customer_id === "string" ? req.query.customer_id : undefined;
      const payment_id = typeof req.query.payment_id === "string" ? req.query.payment_id : undefined;
      const tradein_id = typeof req.query.tradein_id === "string" ? req.query.tradein_id : undefined;
      const claim_id = typeof req.query.claim_id === "string" ? req.query.claim_id : undefined;

      const rows = db
        .prepare(
          `SELECT alert_id, alert_type, alert_status, opened_ops_run_index, customer_id, order_id, device_id,
                  payment_id, tradein_id, quality_campaign_id, claim_id
           FROM alerts
           WHERE program_id = ?
             AND (? IS NULL OR alert_status = ?)
             AND (? IS NULL OR alert_type = ?)
             AND (? IS NULL OR customer_id = ?)
             AND (? IS NULL OR payment_id = ?)
             AND (? IS NULL OR tradein_id = ?)
             AND (? IS NULL OR claim_id = ?)
           ORDER BY rowid ASC`
        )
        .all(
          programId,
          alert_status ?? null,
          alert_status ?? null,
          alert_type ?? null,
          alert_type ?? null,
          customer_id ?? null,
          customer_id ?? null,
          payment_id ?? null,
          payment_id ?? null,
          tradein_id ?? null,
          tradein_id ?? null,
          claim_id ?? null,
          claim_id ?? null
        ) as any[];
      res.json({ alerts: rows.map(alertResponse) });
    } catch (e) {
      next(e);
    }
  });

  app.get("/programs/:program_id/alerts/:alert_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT alert_id, alert_type, alert_status, opened_ops_run_index, customer_id, order_id, device_id,
                  payment_id, tradein_id, quality_campaign_id, claim_id
           FROM alerts WHERE program_id = ? AND alert_id = ?`
        )
        .get(req.params.program_id, req.params.alert_id) as any;
      if (!row) throw notFound("Alert not found");
      res.json(alertResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/alerts/:alert_id/acknowledge", (req, res, next) => {
    const programId = req.params.program_id;
    const alertId = req.params.alert_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const alert = getAlertOrThrow(db, programId, alertId);
      if (alert.alert_status !== "OPEN") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
      db.prepare(`UPDATE alerts SET alert_status = 'ACKNOWLEDGED' WHERE program_id = ? AND alert_id = ?`).run(programId, alertId);
      const row = getAlertOrThrow(db, programId, alertId);
      return { status: 200, body: alertResponse(row) };
    });
  });

  app.post("/programs/:program_id/alerts/:alert_id/resolve", (req, res, next) => {
    const programId = req.params.program_id;
    const alertId = req.params.alert_id;
    runMutating(db, requireSessionIfNeeded, req, res, next, { programScope: programId, programIdForSessionCheck: programId }, () => {
      const program = getProgramOrThrow(db, programId);
      if (program.program_posture === "PROGRAM_CLOSED") throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
      const alert = getAlertOrThrow(db, programId, alertId);
      if (alert.alert_status === "RESOLVED") throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");

      const notResolvable = () => badRequest("ERR_ALERT_NOT_RESOLVABLE", "Alert not resolvable");

      if (alert.alert_type === "PAYMENT_DISPUTED") {
        if (!alert.payment_id) throw notResolvable();
        const p = db.prepare(`SELECT payment_status FROM payments WHERE program_id = ? AND payment_id = ?`).get(programId, alert.payment_id) as any;
        if (!p || p.payment_status === "DISPUTED") throw notResolvable();
      } else if (alert.alert_type === "CHARGEBACK_LOST") {
        if (!alert.customer_id) throw notResolvable();
        const c = getCustomerOrThrow(db, programId, alert.customer_id);
        if (c.balance_due_cents > 0) throw notResolvable();
      } else if (alert.alert_type === "TRADEIN_REVERSAL") {
        if (!alert.tradein_id || !alert.customer_id) throw notResolvable();
        const ti = db.prepare(`SELECT tradein_status FROM tradeins WHERE program_id = ? AND tradein_id = ?`).get(programId, alert.tradein_id) as any;
        const c = getCustomerOrThrow(db, programId, alert.customer_id);
        if (!ti || ti.tradein_status === "REVERSED" || c.customer_status === "LOCKED") throw notResolvable();
      } else if (alert.alert_type === "SUPPLY_SHORTFALL") {
        if (computeSupplyShortfall(db, program)) throw notResolvable();
      } else if (alert.alert_type === "RECALL_ACTIVE") {
        if (!alert.quality_campaign_id) throw notResolvable();
        const qc = db.prepare(`SELECT campaign_status FROM quality_campaigns WHERE program_id = ? AND quality_campaign_id = ?`).get(programId, alert.quality_campaign_id) as any;
        if (!qc || qc.campaign_status !== "CLOSED") throw notResolvable();
      } else if (alert.alert_type === "AFTERCARE_OVERDUE") {
        if (!alert.claim_id) throw notResolvable();
        const claim = db.prepare(`SELECT claim_status FROM claims WHERE program_id = ? AND claim_id = ?`).get(programId, alert.claim_id) as any;
        if (!claim || claim.claim_status !== "COMPLETED") throw notResolvable();
        if (alert.customer_id) {
          const c = getCustomerOrThrow(db, programId, alert.customer_id);
          if (c.balance_due_cents > 0) throw notResolvable();
        }
      } else if (alert.alert_type === "CUSTOMER_LOCKED") {
        if (!alert.customer_id) throw notResolvable();
        const c = getCustomerOrThrow(db, programId, alert.customer_id);
        if (c.balance_due_cents > 0) throw notResolvable();
      }

      db.prepare(`UPDATE alerts SET alert_status = 'RESOLVED' WHERE program_id = ? AND alert_id = ?`).run(programId, alertId);
      const row = getAlertOrThrow(db, programId, alertId);
      return { status: 200, body: alertResponse(row) };
    });
  });
}
