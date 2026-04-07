import { db } from '../db/schema';
import {
  InvoiceRow,
  InvoiceLineRow,
  PurchaseOrderLineRow,
  DisputeRow,
  CreditMemoItemRow,
  CollectionsStage,
  MatchStatus,
} from '../types';

export function computeMatchStatus(invoiceId: string): MatchStatus {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;
  if (!invoice || !invoice.purchase_order_id) {
    return 'NOT_APPLICABLE';
  }

  const lines = db.prepare(`
    SELECT * FROM invoice_lines WHERE invoice_id = ?
  `).all(invoiceId) as InvoiceLineRow[];

  const poLinkedLines = lines.filter(l => l.purchase_order_line_id);
  if (poLinkedLines.length === 0) {
    return 'NOT_APPLICABLE';
  }

  for (const line of poLinkedLines) {
    const poLine = db.prepare(`
      SELECT * FROM purchase_order_lines WHERE id = ?
    `).get(line.purchase_order_line_id) as PurchaseOrderLineRow | undefined;

    if (!poLine) continue;

    const creditedAmountCents = db.prepare(`
      SELECT COALESCE(SUM(cmi.amount_cents), 0) as total
      FROM credit_memo_items cmi
      JOIN credit_memos cm ON cmi.credit_memo_id = cm.id
      JOIN credit_memo_applications cma ON cma.credit_memo_id = cm.id
      WHERE cmi.invoice_line_id = ? AND cm.status = 'ISSUED' AND cma.invoice_id = ?
    `).get(line.id, invoiceId) as { total: number };

    const grossLineAmount = line.quantity_units * line.unit_price_cents;
    const netLineAmount = grossLineAmount - creditedAmountCents.total;
    const effectiveUnitPrice = line.quantity_units > 0 ? Math.floor(netLineAmount / line.quantity_units) : 0;
    const poPriceWithTolerance = poLine.unit_price_cents * 1.05;

    if (effectiveUnitPrice > poPriceWithTolerance) {
      return 'EXCEPTION';
    }

    const maxAllowedUnits = poLine.ordered_units * 1.02;
    if (poLine.net_billed_units > maxAllowedUnits) {
      return 'EXCEPTION';
    }

    if (!poLine.is_service) {

      if (poLine.received_units < poLine.net_billed_units) {
        return 'EXCEPTION';
      }
    }
  }

  return 'MATCHED';
}

export function computeCollectionsStage(invoiceId: string, currentPeriodIndex: number): CollectionsStage {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;

  if (!invoice || invoice.status === 'DRAFT' || invoice.status === 'VOIDED' || invoice.status === 'CLOSED') {
    return 'CURRENT';
  }

  if (invoice.due_period_index === null || invoice.due_period_index >= currentPeriodIndex) {
    return 'CURRENT';
  }

  const undisputedDue = invoice.amount_due_cents - invoice.amount_disputed_cents;
  if (undisputedDue <= 0) {
    return 'CURRENT';
  }

  const periodsPastDue = currentPeriodIndex - invoice.due_period_index;

  if (periodsPastDue >= 3) {
    return 'COLLECTIONS';
  } else if (periodsPastDue === 2) {
    return 'FINAL_NOTICE';
  } else if (periodsPastDue === 1) {
    return 'REMINDER';
  }

  return 'CURRENT';
}

export function updateInvoiceMatchStatus(invoiceId: string): void {
  const matchStatus = computeMatchStatus(invoiceId);
  db.prepare('UPDATE invoices SET match_status = ? WHERE id = ?').run(matchStatus, invoiceId);
}

export function updateInvoiceCollectionsStage(invoiceId: string, currentPeriodIndex: number): void {
  const stage = computeCollectionsStage(invoiceId, currentPeriodIndex);
  db.prepare('UPDATE invoices SET collections_stage = ? WHERE id = ?').run(stage, invoiceId);
}

export function updateAllInvoiceStages(workspaceId: string, currentPeriodIndex: number): void {
  const invoices = db.prepare(`
    SELECT id FROM invoices
    WHERE workspace_id = ? AND status NOT IN ('DRAFT', 'VOIDED', 'CLOSED')
  `).all(workspaceId) as { id: string }[];

  for (const inv of invoices) {
    updateInvoiceCollectionsStage(inv.id, currentPeriodIndex);
  }
}

export function recalculateInvoiceAmounts(invoiceId: string): void {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;
  if (!invoice) return;

  if (invoice.status === 'DRAFT') return;

  const linesResult = db.prepare(`
    SELECT COALESCE(SUM(line_total_cents), 0) as total
    FROM invoice_lines WHERE invoice_id = ?
  `).get(invoiceId) as { total: number };

  const paidResult = db.prepare(`
    SELECT COALESCE(SUM(amount_cents), 0) as total
    FROM payment_allocations
    WHERE invoice_id = ? AND is_applied = 1
  `).get(invoiceId) as { total: number };

  const creditedResult = db.prepare(`
    SELECT COALESCE(SUM(amount_cents), 0) as total
    FROM credit_memo_applications
    WHERE invoice_id = ?
  `).get(invoiceId) as { total: number };

  const disputedResult = db.prepare(`
    SELECT COALESCE(SUM(disputed_amount_cents), 0) as total
    FROM disputes
    WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
  `).get(invoiceId) as { total: number };

  const invoiceTotal = linesResult.total;
  const amountPaid = paidResult.total;
  const amountCredited = creditedResult.total;
  const amountWrittenOff = invoice.amount_written_off_cents;
  const amountDisputed = disputedResult.total;
  const amountDue = Math.max(0, invoiceTotal - amountPaid - amountCredited - amountWrittenOff);

  db.prepare(`
    UPDATE invoices
    SET invoice_total_cents = ?,
        amount_due_cents = ?,
        amount_paid_cents = ?,
        amount_credited_cents = ?,
        amount_disputed_cents = ?
    WHERE id = ?
  `).run(invoiceTotal, amountDue, amountPaid, amountCredited, Math.min(amountDisputed, amountDue), invoiceId);
}

export function canAcceptInvoiceWithExceptions(invoiceId: string): boolean {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;
  if (!invoice || invoice.match_status !== 'EXCEPTION') return true;

  const activeDisputes = db.prepare(`
    SELECT * FROM disputes
    WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
  `).all(invoiceId) as DisputeRow[];

  if (activeDisputes.length === 0) return false;

  const lines = db.prepare(`SELECT * FROM invoice_lines WHERE invoice_id = ?`).all(invoiceId) as InvoiceLineRow[];
  const poLinkedLines = lines.filter(l => l.purchase_order_line_id);

  for (const line of poLinkedLines) {
    const poLine = db.prepare(`SELECT * FROM purchase_order_lines WHERE id = ?`).get(line.purchase_order_line_id) as PurchaseOrderLineRow | undefined;
    if (!poLine) continue;

    const appliedCredits = db.prepare(`
      SELECT
        COALESCE(SUM(cmi.amount_cents), 0) as credited_cents,
        COALESCE(SUM(COALESCE(cmi.quantity_units, 0)), 0) as credited_units
      FROM credit_memo_items cmi
      JOIN credit_memos cm ON cmi.credit_memo_id = cm.id
      JOIN credit_memo_applications cma ON cma.credit_memo_id = cm.id
      WHERE cmi.invoice_line_id = ? AND cm.status = 'ISSUED' AND cma.invoice_id = ?
    `).get(line.id, invoiceId) as { credited_cents: number; credited_units: number };

    const billedUnitsGross = Number(line.quantity_units ?? 0);
    const billedUnitsNet = Math.max(0, billedUnitsGross - Number(appliedCredits.credited_units ?? 0));
    const netLineAmountCents = Math.max(0, Number(line.line_total_cents ?? 0) - Number(appliedCredits.credited_cents ?? 0));

    let matchableUnits = billedUnitsNet;
    matchableUnits = Math.min(matchableUnits, Number(poLine.ordered_units ?? 0) * 1.02);
    if (!poLine.is_service) {
      matchableUnits = Math.min(matchableUnits, Number(poLine.received_units ?? 0));
    }

    const matchableFromUnits =
      billedUnitsNet > 0 ? Math.floor(netLineAmountCents * (matchableUnits / billedUnitsNet)) : 0;
    const maxMatchableByPrice = Math.floor(matchableUnits * Number(poLine.unit_price_cents ?? 0) * 1.05);
    const matchableCents = Math.min(matchableFromUnits, maxMatchableByPrice);
    const requiredDisputedCents = Math.max(0, netLineAmountCents - matchableCents);

    if (requiredDisputedCents <= 0) continue;

    const disputedRow = db.prepare(`
      SELECT COALESCE(SUM(di.disputed_amount_cents), 0) as total
      FROM dispute_items di
      JOIN disputes d ON di.dispute_id = d.id
      WHERE di.invoice_line_id = ? AND d.status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
    `).get(line.id) as { total: number };

    if ((disputedRow.total ?? 0) + 1 < requiredDisputedCents) {
      return false;
    }
  }

  return true;
}
