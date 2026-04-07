import Database, { Database as DatabaseType } from 'better-sqlite3';
import path from 'path';

const dbPath = process.env.DATABASE_PATH || path.join(__dirname, '../../data.db');
export const db: DatabaseType = new Database(dbPath);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

export function initializeDatabase(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS studios (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      cycle_index INTEGER NOT NULL DEFAULT 1,
      token_budget INTEGER NOT NULL DEFAULT 100,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS assets (
      id TEXT PRIMARY KEY,
      studio_id TEXT NOT NULL REFERENCES studios(id),
      title TEXT NOT NULL,
      duration_sec INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'QUARANTINED', 'RETIRED')),
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS clearances (
      id TEXT PRIMARY KEY,
      studio_id TEXT NOT NULL REFERENCES studios(id),
      asset_id TEXT NOT NULL UNIQUE REFERENCES assets(id),
      policy TEXT NOT NULL CHECK (policy IN ('FULL', 'PROMO')),
      status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'GRANTED', 'SUSPENDED', 'REVOKED')),
      last_granted_in_cycle INTEGER,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mixes (
      id TEXT PRIMARY KEY,
      studio_id TEXT NOT NULL REFERENCES studios(id),
      title TEXT NOT NULL,
      kind TEXT NOT NULL CHECK (kind IN ('PUBLIC', 'INTERNAL', 'EVIDENCE')),
      status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'PUBLISHED', 'FROZEN', 'ARCHIVED')),
      token_cost INTEGER NOT NULL DEFAULT 0,
      approved_in_cycle INTEGER,
      published_in_cycle INTEGER,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mix_entries (
      id TEXT PRIMARY KEY,
      mix_id TEXT NOT NULL REFERENCES mixes(id) ON DELETE CASCADE,
      asset_id TEXT NOT NULL REFERENCES assets(id),
      slot TEXT NOT NULL CHECK (slot IN ('NORMAL', 'SPOTLIGHT')),
      position INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS disputes (
      id TEXT PRIMARY KEY,
      studio_id TEXT NOT NULL REFERENCES studios(id),
      target_type TEXT NOT NULL CHECK (target_type IN ('ASSET', 'MIX')),
      target_id TEXT NOT NULL,
      severity TEXT NOT NULL CHECK (severity IN ('LOW', 'HIGH')),
      status TEXT NOT NULL CHECK (status IN ('OPEN', 'ESCALATED', 'RESOLVED', 'VOID')),
      resolution TEXT CHECK (resolution IN ('UPHELD', 'DISMISSED', 'VOID')),
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS idempotency_keys (
      key TEXT NOT NULL,
      studio_id TEXT NOT NULL,
      cycle_index INTEGER NOT NULL,
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      request_body_hash TEXT NOT NULL,
      response_status INTEGER NOT NULL,
      response_body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (key, studio_id, cycle_index, method, path)
    );

    CREATE INDEX IF NOT EXISTS idx_assets_studio ON assets(studio_id);
    CREATE INDEX IF NOT EXISTS idx_clearances_studio ON clearances(studio_id);
    CREATE INDEX IF NOT EXISTS idx_clearances_asset ON clearances(asset_id);
    CREATE INDEX IF NOT EXISTS idx_mixes_studio ON mixes(studio_id);
    CREATE INDEX IF NOT EXISTS idx_mix_entries_mix ON mix_entries(mix_id);
    CREATE INDEX IF NOT EXISTS idx_mix_entries_asset ON mix_entries(asset_id);
    CREATE INDEX IF NOT EXISTS idx_disputes_studio ON disputes(studio_id);
    CREATE INDEX IF NOT EXISTS idx_disputes_target ON disputes(target_type, target_id);
  `);
}

export default db;
