import Database from "better-sqlite3";

export type Db = Database.Database;

export function openDb() {
  const dbPath = process.env.DB_PATH || "lumenloop.sqlite";
  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  migrate(db);
  return db;
}

function migrate(db: Db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS programs (
      program_id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      unit_price_cents INTEGER NOT NULL,
      care_plan_price_cents INTEGER NOT NULL,
      program_posture TEXT NOT NULL,
      ops_run_index INTEGER NOT NULL,
      replacement_reserve_remaining INTEGER NOT NULL,
      frozen_since_ops_run_index INTEGER,
      available_to_commit_units INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sessions (
      session_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      actor_id TEXT NOT NULL,
      actor_type TEXT NOT NULL,
      session_status TEXT NOT NULL,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS customers (
      customer_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      display_name TEXT NOT NULL,
      customer_status TEXT NOT NULL,
      credit_balance_cents INTEGER NOT NULL,
      balance_due_cents INTEGER NOT NULL,
      balance_due_cleared_ops_run_index INTEGER,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS build_lots (
      build_lot_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      build_tag TEXT NOT NULL,
      build_lot_status TEXT NOT NULL,
      units_total INTEGER NOT NULL,
      units_remaining INTEGER NOT NULL,
      quarantined_by_campaign_id TEXT,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS payments (
      payment_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      order_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      payment_status TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      authorized_ops_run_index INTEGER,
      chargeback_lost_ops_run_index INTEGER,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS devices (
      device_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      order_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      serial_number TEXT NOT NULL,
      build_tag TEXT NOT NULL,
      device_status TEXT NOT NULL,
      pre_quarantine_status TEXT,
      activated_ops_run_index INTEGER,
      created_by_claim_id TEXT,
      created_by_return_id TEXT,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_program_serial ON devices(program_id, serial_number);

    CREATE TABLE IF NOT EXISTS care_plans (
      care_plan_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      order_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      device_id TEXT,
      care_plan_status TEXT NOT NULL,
      paused_reason TEXT,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS tradeins (
      tradein_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      tradein_status TEXT NOT NULL,
      quoted_credit_cents INTEGER NOT NULL,
      final_credit_cents INTEGER,
      provisional_credit_cents INTEGER,
      credit_issued_cents INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS orders (
      order_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      order_status TEXT NOT NULL,
      model_code TEXT NOT NULL,
      unit_price_cents INTEGER NOT NULL,
      care_plan_price_cents INTEGER NOT NULL,
      requested_use_credit_cents INTEGER NOT NULL,
      paid_by_credit_cents INTEGER NOT NULL,
      paid_by_card_cents INTEGER NOT NULL,
      payment_id TEXT,
      device_id TEXT,
      care_plan_id TEXT,
      tradein_id TEXT,
      hold_reason TEXT,
      hold_set_ops_run_index INTEGER,
      committed_ops_run_index INTEGER,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS returns (
      return_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      order_id TEXT NOT NULL,
      device_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      return_status TEXT NOT NULL,
      resolution_preference TEXT NOT NULL,
      inspection_outcome TEXT,
      refunded_to_card_cents INTEGER NOT NULL,
      refunded_to_credit_cents INTEGER NOT NULL,
      replacement_device_id TEXT,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS claims (
      claim_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      order_id TEXT NOT NULL,
      device_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      claim_status TEXT NOT NULL,
      claim_type TEXT NOT NULL,
      claim_resolution TEXT,
      inspection_outcome TEXT,
      replacement_device_id TEXT,
      approved_ops_run_index INTEGER,
      inbound_ops_run_index INTEGER,
      advance_shipped_ops_run_index INTEGER,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS adjustments (
      adjustment_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      adjustment_type TEXT NOT NULL,
      adjustment_status TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      applied_ops_run_index INTEGER,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS quality_campaigns (
      quality_campaign_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      campaign_type TEXT NOT NULL,
      campaign_status TEXT NOT NULL,
      build_tag_prefix TEXT NOT NULL,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );

    CREATE TABLE IF NOT EXISTS alerts (
      alert_id TEXT PRIMARY KEY,
      program_id TEXT NOT NULL,
      alert_type TEXT NOT NULL,
      alert_status TEXT NOT NULL,
      opened_ops_run_index INTEGER NOT NULL,
      customer_id TEXT,
      order_id TEXT,
      device_id TEXT,
      payment_id TEXT,
      tradein_id TEXT,
      quality_campaign_id TEXT,
      claim_id TEXT,
      dedupe_key TEXT NOT NULL,
      FOREIGN KEY(program_id) REFERENCES programs(program_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_dedupe ON alerts(program_id, dedupe_key) WHERE alert_status != 'RESOLVED';

    CREATE TABLE IF NOT EXISTS idempotency_keys (
      program_scope TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      response_status INTEGER NOT NULL,
      response_body TEXT NOT NULL,
      PRIMARY KEY (program_scope, idempotency_key)
    );
  `);
}
