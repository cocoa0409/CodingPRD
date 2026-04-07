import Database, { Database as DatabaseType } from 'better-sqlite3';
import path from 'path';

const dbPath = process.env.DB_PATH || path.join(__dirname, '../../data.db');
export const db: DatabaseType = new Database(dbPath);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

export function initializeDatabase() {
  db.exec(`
    -- Workspaces
    CREATE TABLE IF NOT EXISTS workspaces (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      currency TEXT NOT NULL DEFAULT 'USD',
      period_index INTEGER NOT NULL DEFAULT 0,
      books_closed_through_period_index INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Idempotency schema migration (safe to recreate; it's a cache table).
    -- We intentionally drop+recreate so tests don't depend on old schemas.
    DROP TABLE IF EXISTS idempotency_keys;
    DROP TABLE IF EXISTS workspace_ledger_versions;

    -- Workspace ledger versions (monotonic counter used for idempotency conflict detection)
    CREATE TABLE IF NOT EXISTS workspace_ledger_versions (
      workspace_id TEXT PRIMARY KEY,
      version INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );

    -- Idempotency keys
    CREATE TABLE IF NOT EXISTS idempotency_keys (
      workspace_id TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      path TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      ledger_version INTEGER NOT NULL,
      response TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (workspace_id, idempotency_key, path),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );

    -- Customers
    CREATE TABLE IF NOT EXISTS customers (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      display_name TEXT NOT NULL,
      external_customer_ref TEXT,
      status TEXT NOT NULL DEFAULT 'ACTIVE',
      credit_limit_cents INTEGER NOT NULL DEFAULT 0,
      balance_due_cents INTEGER NOT NULL DEFAULT 0,
      unapplied_cash_cents INTEGER NOT NULL DEFAULT 0,
      available_credit_cents INTEGER NOT NULL DEFAULT 0,
      freeze_reason TEXT,
      freeze_period_index INTEGER,
      last_fraud_dispute_closed_period INTEGER,
      last_reversal_period_index INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );

    CREATE INDEX IF NOT EXISTS idx_customers_workspace ON customers(workspace_id);

    -- Contracts
    CREATE TABLE IF NOT EXISTS contracts (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'DRAFT',
      payment_terms_periods INTEGER NOT NULL DEFAULT 2,
      requires_po INTEGER NOT NULL DEFAULT 0,
      billing_cap_cents_per_period INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE INDEX IF NOT EXISTS idx_contracts_workspace ON contracts(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_contracts_customer ON contracts(customer_id);

    -- Purchase Orders
    CREATE TABLE IF NOT EXISTS purchase_orders (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      po_number TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'OPEN',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE INDEX IF NOT EXISTS idx_purchase_orders_workspace ON purchase_orders(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_purchase_orders_customer ON purchase_orders(customer_id);

    -- Purchase Order Lines
    CREATE TABLE IF NOT EXISTS purchase_order_lines (
      id TEXT PRIMARY KEY,
      purchase_order_id TEXT NOT NULL,
      description TEXT NOT NULL,
      ordered_units REAL NOT NULL,
      unit_price_cents INTEGER NOT NULL,
      is_service INTEGER NOT NULL DEFAULT 0,
      received_units REAL NOT NULL DEFAULT 0,
      net_billed_units REAL NOT NULL DEFAULT 0,
      FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id)
    );

    CREATE INDEX IF NOT EXISTS idx_po_lines_po ON purchase_order_lines(purchase_order_id);

    -- Invoices
    CREATE TABLE IF NOT EXISTS invoices (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      contract_id TEXT NOT NULL,
      purchase_order_id TEXT,
      external_invoice_ref TEXT,
      document_number TEXT,
      status TEXT NOT NULL DEFAULT 'DRAFT',
      type TEXT NOT NULL DEFAULT 'STANDARD',
      invoice_total_cents INTEGER NOT NULL DEFAULT 0,
      amount_due_cents INTEGER NOT NULL DEFAULT 0,
      amount_disputed_cents INTEGER NOT NULL DEFAULT 0,
      amount_paid_cents INTEGER NOT NULL DEFAULT 0,
      amount_credited_cents INTEGER NOT NULL DEFAULT 0,
      amount_written_off_cents INTEGER NOT NULL DEFAULT 0,
      collections_stage TEXT NOT NULL DEFAULT 'CURRENT',
      match_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
      issued_period_index INTEGER,
      delivered_period_index INTEGER,
      accepted_period_index INTEGER,
      due_period_index INTEGER,
      is_final_invoice INTEGER NOT NULL DEFAULT 0,
      parent_invoice_id TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id),
      FOREIGN KEY (contract_id) REFERENCES contracts(id),
      FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id),
      FOREIGN KEY (parent_invoice_id) REFERENCES invoices(id)
    );

    CREATE INDEX IF NOT EXISTS idx_invoices_workspace ON invoices(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
    CREATE INDEX IF NOT EXISTS idx_invoices_contract ON invoices(contract_id);
    CREATE INDEX IF NOT EXISTS idx_invoices_po ON invoices(purchase_order_id);

    -- Invoice Lines
    CREATE TABLE IF NOT EXISTS invoice_lines (
      id TEXT PRIMARY KEY,
      invoice_id TEXT NOT NULL,
      purchase_order_line_id TEXT,
      description TEXT NOT NULL,
      quantity_units REAL NOT NULL,
      unit_price_cents INTEGER NOT NULL,
      line_total_cents INTEGER NOT NULL DEFAULT 0,
      credited_amount_cents INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (invoice_id) REFERENCES invoices(id),
      FOREIGN KEY (purchase_order_line_id) REFERENCES purchase_order_lines(id)
    );

    CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id);
    CREATE INDEX IF NOT EXISTS idx_invoice_lines_po_line ON invoice_lines(purchase_order_line_id);

    -- Payments
    CREATE TABLE IF NOT EXISTS payments (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'INITIATED',
      initiated_period_index INTEGER,
      cleared_period_index INTEGER,
      reversed_period_index INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE INDEX IF NOT EXISTS idx_payments_workspace ON payments(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id);

    -- Payment Allocations
    CREATE TABLE IF NOT EXISTS payment_allocations (
      id TEXT PRIMARY KEY,
      payment_id TEXT NOT NULL,
      invoice_id TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      is_reserved INTEGER NOT NULL DEFAULT 1,
      is_applied INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (payment_id) REFERENCES payments(id),
      FOREIGN KEY (invoice_id) REFERENCES invoices(id)
    );

    CREATE INDEX IF NOT EXISTS idx_allocations_payment ON payment_allocations(payment_id);
    CREATE INDEX IF NOT EXISTS idx_allocations_invoice ON payment_allocations(invoice_id);

    -- Disputes
    CREATE TABLE IF NOT EXISTS disputes (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      invoice_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'OPEN',
      disputed_amount_cents INTEGER NOT NULL DEFAULT 0,
      opened_period_index INTEGER NOT NULL,
      proposed_period_index INTEGER,
      closed_period_index INTEGER,
      seller_responded INTEGER NOT NULL DEFAULT 0,
      proposed_credit_memo_id TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (invoice_id) REFERENCES invoices(id)
    );

    CREATE INDEX IF NOT EXISTS idx_disputes_workspace ON disputes(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_disputes_invoice ON disputes(invoice_id);

    -- Dispute Items
    CREATE TABLE IF NOT EXISTS dispute_items (
      id TEXT PRIMARY KEY,
      dispute_id TEXT NOT NULL,
      invoice_line_id TEXT NOT NULL,
      disputed_units REAL,
      disputed_amount_cents INTEGER,
      FOREIGN KEY (dispute_id) REFERENCES disputes(id),
      FOREIGN KEY (invoice_line_id) REFERENCES invoice_lines(id)
    );

    CREATE INDEX IF NOT EXISTS idx_dispute_items_dispute ON dispute_items(dispute_id);

    -- Credit Memos
    CREATE TABLE IF NOT EXISTS credit_memos (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      invoice_id TEXT,
      document_number TEXT,
      status TEXT NOT NULL DEFAULT 'DRAFT',
      type TEXT NOT NULL DEFAULT 'GOODWILL',
      total_cents INTEGER NOT NULL DEFAULT 0,
      applied_cents INTEGER NOT NULL DEFAULT 0,
      reason TEXT,
      dispute_id TEXT,
      issued_period_index INTEGER,
      is_system_generated INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id),
      FOREIGN KEY (invoice_id) REFERENCES invoices(id),
      FOREIGN KEY (dispute_id) REFERENCES disputes(id)
    );

    CREATE INDEX IF NOT EXISTS idx_credit_memos_workspace ON credit_memos(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_credit_memos_customer ON credit_memos(customer_id);
    CREATE INDEX IF NOT EXISTS idx_credit_memos_invoice ON credit_memos(invoice_id);

    -- Credit Memo Items
    CREATE TABLE IF NOT EXISTS credit_memo_items (
      id TEXT PRIMARY KEY,
      credit_memo_id TEXT NOT NULL,
      invoice_line_id TEXT,
      description TEXT,
      quantity_units REAL,
      unit_price_cents INTEGER,
      amount_cents INTEGER NOT NULL,
      FOREIGN KEY (credit_memo_id) REFERENCES credit_memos(id),
      FOREIGN KEY (invoice_line_id) REFERENCES invoice_lines(id)
    );

    CREATE INDEX IF NOT EXISTS idx_credit_memo_items_memo ON credit_memo_items(credit_memo_id);

    -- Credit Memo Applications (tracks which invoices credits are applied to)
    CREATE TABLE IF NOT EXISTS credit_memo_applications (
      id TEXT PRIMARY KEY,
      credit_memo_id TEXT NOT NULL,
      invoice_id TEXT NOT NULL,
      amount_cents INTEGER NOT NULL,
      applied_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (credit_memo_id) REFERENCES credit_memos(id),
      FOREIGN KEY (invoice_id) REFERENCES invoices(id)
    );

    CREATE INDEX IF NOT EXISTS idx_credit_apps_memo ON credit_memo_applications(credit_memo_id);
    CREATE INDEX IF NOT EXISTS idx_credit_apps_invoice ON credit_memo_applications(invoice_id);

    -- Document number sequences
    CREATE TABLE IF NOT EXISTS document_sequences (
      workspace_id TEXT NOT NULL,
      document_type TEXT NOT NULL,
      next_number INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (workspace_id, document_type),
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );
  `);
}

export function getNextDocumentNumber(workspaceId: string, documentType: string): string {
  const row = db.prepare(`
    INSERT INTO document_sequences (workspace_id, document_type, next_number)
    VALUES (?, ?, 1)
    ON CONFLICT(workspace_id, document_type) DO UPDATE SET next_number = next_number + 1
    RETURNING next_number - 1 as current_number
  `).get(workspaceId, documentType) as { current_number: number } | undefined;

  if (!row) {
    const insertRow = db.prepare(`
      SELECT next_number FROM document_sequences WHERE workspace_id = ? AND document_type = ?
    `).get(workspaceId, documentType) as { next_number: number };
    const prefix = documentType === 'INVOICE' ? 'INV' : 'CM';
    return `${prefix}-${String(insertRow.next_number).padStart(6, '0')}`;
  }

  const prefix = documentType === 'INVOICE' ? 'INV' : 'CM';
  return `${prefix}-${String(row.current_number).padStart(6, '0')}`;
}
