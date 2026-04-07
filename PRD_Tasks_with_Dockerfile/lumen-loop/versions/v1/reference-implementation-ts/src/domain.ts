import type { Db } from "./db";
import { badRequest, notFound } from "./errors";
import type {
  AlertStatus,
  AlertType,
  CustomerStatus,
  ProgramPosture,
  QualityCampaignType,
} from "./types";
import { newId } from "./ids";

export type ProgramRow = {
  program_id: string;
  display_name: string;
  unit_price_cents: number;
  care_plan_price_cents: number;
  program_posture: ProgramPosture;
  ops_run_index: number;
  replacement_reserve_remaining: number;
  frozen_since_ops_run_index: number | null;
  available_to_commit_units: number;
};

export function getProgramOrThrow(db: Db, programId: string): ProgramRow {
  const row = db
    .prepare(
      `SELECT program_id, display_name, unit_price_cents, care_plan_price_cents, program_posture, ops_run_index,
              replacement_reserve_remaining, frozen_since_ops_run_index, available_to_commit_units
       FROM programs WHERE program_id = ?`
    )
    .get(programId) as ProgramRow | undefined;
  if (!row) throw notFound("Program not found");
  return row;
}

export function getCustomerOrThrow(db: Db, programId: string, customerId: string) {
  const row = db
    .prepare(
      `SELECT customer_id, display_name, customer_status, credit_balance_cents, balance_due_cents, balance_due_cleared_ops_run_index
       FROM customers WHERE program_id = ? AND customer_id = ?`
    )
    .get(programId, customerId) as
    | {
        customer_id: string;
        display_name: string;
        customer_status: CustomerStatus;
        credit_balance_cents: number;
        balance_due_cents: number;
        balance_due_cleared_ops_run_index: number | null;
      }
    | undefined;
  if (!row) throw notFound("Customer not found");
  return row;
}

export function ensureProgramNotClosed(program: ProgramRow) {
  if (program.program_posture === "PROGRAM_CLOSED") {
    throw badRequest("ERR_PROGRAM_CLOSED", "Program is closed");
  }
}

export function ensureProgramNotFrozen(program: ProgramRow) {
  if (program.program_posture === "PROGRAM_FROZEN") {
    throw badRequest("ERR_PROGRAM_FROZEN", "Program is frozen");
  }
}

export function ensureProgramNotGuarded(program: ProgramRow) {
  if (program.program_posture === "PROGRAM_GUARDED") {
    throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");
  }
}

export function computeShippableUnits(db: Db, programId: string): number {
  const row = db
    .prepare(
      `SELECT COALESCE(SUM(units_remaining), 0) AS units
       FROM build_lots
       WHERE program_id = ? AND build_lot_status = 'AVAILABLE'`
    )
    .get(programId) as { units: number };
  return row.units ?? 0;
}

export function computeCommittedUnits(db: Db, programId: string): number {
  const row = db
    .prepare(
      `SELECT COUNT(1) AS cnt
       FROM orders
       WHERE program_id = ? AND order_status IN ('SUBMITTED', 'ON_HOLD')`
    )
    .get(programId) as { cnt: number };
  return row.cnt ?? 0;
}

export function computeSupplyShortfall(db: Db, program: ProgramRow): boolean {
  const shippable = computeShippableUnits(db, program.program_id);
  const committed = computeCommittedUnits(db, program.program_id);
  const sellable = Math.max(0, shippable - program.replacement_reserve_remaining);
  return committed > sellable;
}

export function recomputeAvailability(db: Db, programId: string) {
  const program = getProgramOrThrow(db, programId);
  const shippable = computeShippableUnits(db, programId);
  const committed = computeCommittedUnits(db, programId);
  const sellable = Math.max(0, shippable - program.replacement_reserve_remaining);
  const available = Math.max(0, sellable - committed);
  db.prepare(`UPDATE programs SET available_to_commit_units = ? WHERE program_id = ?`).run(
    available,
    programId
  );
}

export function openAlertDeduped(
  db: Db,
  programId: string,
  alert: {
    alert_type: AlertType;
    customer_id?: string | null;
    order_id?: string | null;
    device_id?: string | null;
    payment_id?: string | null;
    tradein_id?: string | null;
    quality_campaign_id?: string | null;
    claim_id?: string | null;
  }
) {
  const program = getProgramOrThrow(db, programId);
  const dedupeKey = JSON.stringify({
    alert_type: alert.alert_type,
    customer_id: alert.customer_id ?? null,
    order_id: alert.order_id ?? null,
    device_id: alert.device_id ?? null,
    payment_id: alert.payment_id ?? null,
    tradein_id: alert.tradein_id ?? null,
    quality_campaign_id: alert.quality_campaign_id ?? null,
    claim_id: alert.claim_id ?? null,
  });

  const existing = db
    .prepare(
      `SELECT alert_id FROM alerts WHERE program_id = ? AND dedupe_key = ? AND alert_status != 'RESOLVED'`
    )
    .get(programId, dedupeKey) as { alert_id: string } | undefined;
  if (existing) return existing.alert_id;

  const alertId = newId("alert");
  db.prepare(
    `INSERT INTO alerts (
      alert_id, program_id, alert_type, alert_status, opened_ops_run_index,
      customer_id, order_id, device_id, payment_id, tradein_id, quality_campaign_id, claim_id, dedupe_key
    ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    alertId,
    programId,
    alert.alert_type,
    program.ops_run_index,
    alert.customer_id ?? null,
    alert.order_id ?? null,
    alert.device_id ?? null,
    alert.payment_id ?? null,
    alert.tradein_id ?? null,
    alert.quality_campaign_id ?? null,
    alert.claim_id ?? null,
    dedupeKey
  );
  return alertId;
}

export function setProgramPosture(db: Db, programId: string, posture: ProgramPosture) {
  db.prepare(`UPDATE programs SET program_posture = ? WHERE program_id = ?`).run(posture, programId);
}

export function setProgramFrozen(db: Db, programId: string) {
  const program = getProgramOrThrow(db, programId);
  if (program.program_posture === "PROGRAM_CLOSED") return;
  db.prepare(
    `UPDATE programs
     SET program_posture = 'PROGRAM_FROZEN', frozen_since_ops_run_index = ?
     WHERE program_id = ?`
  ).run(program.ops_run_index, programId);
}

export function recomputePosture(db: Db, programId: string) {
  const program = getProgramOrThrow(db, programId);
  if (program.program_posture === "PROGRAM_CLOSED") return;
  if (program.program_posture === "PROGRAM_FROZEN") return;

  const hasRecall = db
    .prepare(
      `SELECT 1 AS ok
       FROM quality_campaigns
       WHERE program_id = ? AND campaign_type = 'RECALL' AND campaign_status != 'CLOSED'
       LIMIT 1`
    )
    .get(programId) as { ok: 1 } | undefined;
  if (hasRecall) {
    setProgramFrozen(db, programId);
    return;
  }

  const supplyShortfall = computeSupplyShortfall(db, program);
  if (supplyShortfall) {
    openAlertDeduped(db, programId, { alert_type: "SUPPLY_SHORTFALL" });
  }

  const hasNonResolvedAlert = db
    .prepare(
      `SELECT 1 AS ok FROM alerts WHERE program_id = ? AND alert_status != 'RESOLVED' LIMIT 1`
    )
    .get(programId) as { ok: 1 } | undefined;

  const posture: ProgramPosture =
    hasNonResolvedAlert || supplyShortfall ? "PROGRAM_GUARDED" : "PROGRAM_ACTIVE";
  setProgramPosture(db, programId, posture);
}

export function ensureCustomerNotClosed(customer: { customer_status: CustomerStatus }) {
  if (customer.customer_status === "CLOSED") {
    throw badRequest("ERR_CUSTOMER_CLOSED", "Customer is closed");
  }
}

export function ensureCustomerNotLocked(customer: { customer_status: CustomerStatus }) {
  if (customer.customer_status === "LOCKED") {
    throw badRequest("ERR_CUSTOMER_LOCKED", "Customer is locked");
  }
}

export function ensureCustomerEligibleForNewCommitment(customer: { customer_status: CustomerStatus }) {
  if (customer.customer_status !== "ACTIVE") {
    throw badRequest("ERR_CUSTOMER_NOT_ELIGIBLE", "Customer not eligible");
  }
}

export function ensureCustomerStandingAfterBalanceChange(
  db: Db,
  programId: string,
  customerId: string
) {
  const customer = getCustomerOrThrow(db, programId, customerId);
  if (customer.customer_status === "CLOSED" || customer.customer_status === "LOCKED") return;
  if (customer.balance_due_cents > 0 && customer.customer_status === "ACTIVE") {
    db.prepare(`UPDATE customers SET customer_status = 'LIMITED' WHERE program_id = ? AND customer_id = ?`).run(
      programId,
      customerId
    );
  }
}

export function putCustomerUnshippedOrdersOnHold(
  db: Db,
  programId: string,
  customerId: string,
  reason: string
) {
  const program = getProgramOrThrow(db, programId);
  db.prepare(
    `UPDATE orders
     SET order_status = 'ON_HOLD', hold_reason = ?, hold_set_ops_run_index = ?
     WHERE program_id = ? AND customer_id = ? AND order_status = 'SUBMITTED'`
  ).run(reason, program.ops_run_index, programId, customerId);
}

export function lockCustomer(
  db: Db,
  programId: string,
  customerId: string,
  alertType: AlertType,
  alertFields: {
    payment_id?: string | null;
    tradein_id?: string | null;
    claim_id?: string | null;
  } = {}
) {
  db.prepare(
    `UPDATE customers SET customer_status = 'LOCKED' WHERE program_id = ? AND customer_id = ?`
  ).run(programId, customerId);

  openAlertDeduped(db, programId, { alert_type: "CUSTOMER_LOCKED", customer_id: customerId });
  openAlertDeduped(db, programId, {
    alert_type: alertType,
    customer_id: customerId,
    payment_id: alertFields.payment_id ?? null,
    tradein_id: alertFields.tradein_id ?? null,
    claim_id: alertFields.claim_id ?? null,
  });
  putCustomerUnshippedOrdersOnHold(db, programId, customerId, "CUSTOMER_LOCKED");
}

export function listOpenAlertsForCustomer(db: Db, programId: string, customerId: string): string[] {
  return db
    .prepare(
      `SELECT alert_id FROM alerts WHERE program_id = ? AND customer_id = ? AND alert_status = 'OPEN'`
    )
    .all(programId, customerId)
    .map((r: any) => r.alert_id as string);
}

export function ensureNoOpenAlertsForCustomer(db: Db, programId: string, customerId: string) {
  const row = db
    .prepare(
      `SELECT 1 AS ok FROM alerts WHERE program_id = ? AND customer_id = ? AND alert_status = 'OPEN' LIMIT 1`
    )
    .get(programId, customerId) as { ok: 1 } | undefined;
  if (row) throw badRequest("ERR_CUSTOMER_NOT_ELIGIBLE", "Customer not eligible");
}

export function ensureProgramHasNoOpenAlerts(db: Db, programId: string) {
  const row = db
    .prepare(`SELECT 1 AS ok FROM alerts WHERE program_id = ? AND alert_status = 'OPEN' LIMIT 1`)
    .get(programId) as { ok: 1 } | undefined;
  if (row) throw badRequest("ERR_PROGRAM_REVIEW_REQUIRED", "Program requires review");
}

export function hasRecallCampaignAffectingBuildTag(
  db: Db,
  programId: string,
  buildTag: string
): boolean {
  const row = db
    .prepare(
      `SELECT 1 AS ok
       FROM quality_campaigns
       WHERE program_id = ? AND campaign_type = 'RECALL' AND campaign_status != 'CLOSED' AND ? LIKE build_tag_prefix || '%'
       LIMIT 1`
    )
    .get(programId, buildTag) as { ok: 1 } | undefined;
  return Boolean(row);
}

export function getCampaignOrThrow(db: Db, programId: string, campaignId: string) {
  const row = db
    .prepare(
      `SELECT quality_campaign_id, campaign_type, campaign_status, build_tag_prefix
       FROM quality_campaigns
       WHERE program_id = ? AND quality_campaign_id = ?`
    )
    .get(programId, campaignId) as
    | {
        quality_campaign_id: string;
        campaign_type: QualityCampaignType;
        campaign_status: string;
        build_tag_prefix: string;
      }
    | undefined;
  if (!row) throw notFound("Quality campaign not found");
  return row;
}

export function getAlertOrThrow(db: Db, programId: string, alertId: string) {
  const row = db
    .prepare(
      `SELECT alert_id, alert_type, alert_status, opened_ops_run_index, customer_id, order_id, device_id,
              payment_id, tradein_id, quality_campaign_id, claim_id
       FROM alerts WHERE program_id = ? AND alert_id = ?`
    )
    .get(programId, alertId) as any;
  if (!row) throw notFound("Alert not found");
  return row as {
    alert_id: string;
    alert_type: AlertType;
    alert_status: AlertStatus;
    opened_ops_run_index: number;
    customer_id: string | null;
    order_id: string | null;
    device_id: string | null;
    payment_id: string | null;
    tradein_id: string | null;
    quality_campaign_id: string | null;
    claim_id: string | null;
  };
}
