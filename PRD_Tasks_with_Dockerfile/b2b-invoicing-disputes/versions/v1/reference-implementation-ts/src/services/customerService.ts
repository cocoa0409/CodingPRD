import { db } from '../db/schema';
import {
  CustomerRow,
  InvoiceRow,
  DisputeRow,
  PaymentRow,
  CustomerStatus,
} from '../types';

const HOLD_THRESHOLD_CENTS = 2500000;
const RELEASE_THRESHOLD_CENTS = 500000;

export function getUndisputedOverdueExposure(customerId: string, currentPeriodIndex: number): number {
  const invoices = db.prepare(`
    SELECT * FROM invoices
    WHERE customer_id = ? AND status NOT IN ('DRAFT', 'VOIDED', 'CLOSED')
    AND due_period_index IS NOT NULL AND due_period_index < ?
  `).all(customerId, currentPeriodIndex) as InvoiceRow[];

  let total = 0;
  for (const inv of invoices) {
    const undisputed = inv.amount_due_cents - inv.amount_disputed_cents;
    if (undisputed > 0) {
      total += undisputed;
    }
  }
  return total;
}

export function hasEscalatedDisputes(customerId: string): boolean {
  const dispute = db.prepare(`
    SELECT 1 FROM disputes d
    JOIN invoices i ON d.invoice_id = i.id
    WHERE i.customer_id = ? AND d.status = 'ESCALATED'
    LIMIT 1
  `).get(customerId);
  return !!dispute;
}

export function hasInvoicesInCollections(customerId: string): boolean {
  const inv = db.prepare(`
    SELECT 1 FROM invoices
    WHERE customer_id = ? AND collections_stage = 'COLLECTIONS'
    AND status NOT IN ('VOIDED', 'CLOSED')
    LIMIT 1
  `).get(customerId);
  return !!inv;
}

export function hasActiveFraudDispute(customerId: string): boolean {
  const dispute = db.prepare(`
    SELECT 1 FROM disputes d
    JOIN invoices i ON d.invoice_id = i.id
    WHERE i.customer_id = ? AND d.reason = 'FRAUD'
    AND d.status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
    LIMIT 1
  `).get(customerId);
  return !!dispute;
}

export function getReversedPaymentsInWindow(customerId: string, currentPeriodIndex: number): PaymentRow[] {

  return db.prepare(`
    SELECT * FROM payments
    WHERE customer_id = ? AND status = 'REVERSED'
    AND reversed_period_index IS NOT NULL
    AND reversed_period_index > ? - 2
  `).all(customerId, currentPeriodIndex) as PaymentRow[];
}

export function shouldAutoFreezeCustomer(customer: CustomerRow, workspacePeriodIndex: number): { freeze: boolean; reason?: string } {

  const reversedPayments = getReversedPaymentsInWindow(customer.id, workspacePeriodIndex);
  if (reversedPayments.length > 0) {
    return { freeze: true, reason: 'PAYMENT_REVERSAL' };
  }

  if (hasActiveFraudDispute(customer.id)) {
    return { freeze: true, reason: 'FRAUD_DISPUTE' };
  }

  return { freeze: false };
}

export function canUnfreezeCustomer(customer: CustomerRow, workspacePeriodIndex: number): boolean {
  if (customer.status !== 'FROZEN') return true;

  if (hasActiveFraudDispute(customer.id)) {
    return false;
  }

  if (customer.last_fraud_dispute_closed_period !== null) {
    if (workspacePeriodIndex - customer.last_fraud_dispute_closed_period < 2) {
      return false;
    }
  }

  const reversedPayments = db.prepare(`
    SELECT * FROM payments
    WHERE customer_id = ? AND status = 'REVERSED'
    AND reversed_period_index IS NOT NULL
  `).all(customer.id) as PaymentRow[];

  for (const payment of reversedPayments) {
    if (payment.reversed_period_index !== null &&
        workspacePeriodIndex - payment.reversed_period_index < 2) {
      return false;
    }
  }

  return true;
}

export function shouldAutoCreditHold(customer: CustomerRow, workspacePeriodIndex: number): boolean {
  if (customer.status === 'FROZEN' || customer.status === 'CLOSED') return false;

  if (hasInvoicesInCollections(customer.id)) {
    return true;
  }

  const undisputedOverdue = getUndisputedOverdueExposure(customer.id, workspacePeriodIndex);
  if (undisputedOverdue > HOLD_THRESHOLD_CENTS) {
    return true;
  }

  if (hasEscalatedDisputes(customer.id)) {
    return true;
  }

  return false;
}

export function canReleaseCreditHold(customer: CustomerRow, workspacePeriodIndex: number): boolean {
  if (customer.status !== 'CREDIT_HOLD') return true;

  const undisputedOverdue = getUndisputedOverdueExposure(customer.id, workspacePeriodIndex);
  if (undisputedOverdue >= RELEASE_THRESHOLD_CENTS) {
    return false;
  }

  if (hasInvoicesInCollections(customer.id)) {
    return false;
  }

  if (hasEscalatedDisputes(customer.id)) {
    return false;
  }

  return true;
}

type UpdateCustomerStatusOptions = {
  allowManualUnfreeze?: boolean;
};

export function updateCustomerStatus(
  customerId: string,
  workspacePeriodIndex: number,
  options: UpdateCustomerStatusOptions = {}
): CustomerRow {
  const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(customerId) as CustomerRow;
  if (!customer) throw new Error('Customer not found');

  if (customer.status === 'CLOSED') {
    return customer;
  }

  let newStatus: CustomerStatus = customer.status;

  const freezeCheck = shouldAutoFreezeCustomer(customer, workspacePeriodIndex);
  if (freezeCheck.freeze && customer.status !== 'FROZEN') {
    newStatus = 'FROZEN';
    db.prepare(`
      UPDATE customers SET status = ?, freeze_reason = ?
      WHERE id = ?
    `).run(newStatus, freezeCheck.reason, customerId);
    return db.prepare('SELECT * FROM customers WHERE id = ?').get(customerId) as CustomerRow;
  }

  if (customer.status === 'FROZEN') {
    if (customer.freeze_reason === 'MANUAL' && !options.allowManualUnfreeze) {
      return customer;
    }

    if (canUnfreezeCustomer(customer, workspacePeriodIndex)) {

      if (shouldAutoCreditHold({ ...customer, status: 'ACTIVE' }, workspacePeriodIndex)) {
        newStatus = 'CREDIT_HOLD';
      } else {
        newStatus = 'ACTIVE';
      }
      db.prepare(`
        UPDATE customers SET status = ?, freeze_reason = NULL
        WHERE id = ?
      `).run(newStatus, customerId);
      return db.prepare('SELECT * FROM customers WHERE id = ?').get(customerId) as CustomerRow;
    }
    return customer;
  }

  if (shouldAutoCreditHold(customer, workspacePeriodIndex)) {
    if (customer.status !== 'CREDIT_HOLD') {
      newStatus = 'CREDIT_HOLD';
      db.prepare('UPDATE customers SET status = ? WHERE id = ?').run(newStatus, customerId);
    }
  } else if (customer.status === 'CREDIT_HOLD' && canReleaseCreditHold(customer, workspacePeriodIndex)) {
    newStatus = 'ACTIVE';
    db.prepare('UPDATE customers SET status = ? WHERE id = ?').run(newStatus, customerId);
  }

  return db.prepare('SELECT * FROM customers WHERE id = ?').get(customerId) as CustomerRow;
}

export function recalculateCustomerBalances(customerId: string): void {

  const balanceResult = db.prepare(`
    SELECT COALESCE(SUM(amount_due_cents), 0) as total
    FROM invoices
    WHERE customer_id = ? AND status NOT IN ('DRAFT', 'VOIDED', 'CLOSED')
  `).get(customerId) as { total: number };

  const creditResult = db.prepare(`
    SELECT COALESCE(SUM(total_cents - applied_cents), 0) as total
    FROM credit_memos
    WHERE customer_id = ? AND status = 'ISSUED'
  `).get(customerId) as { total: number };

  const unappliedResult = db.prepare(`
    SELECT COALESCE(SUM(p.amount_cents - COALESCE(alloc.total_applied, 0)), 0) as total
    FROM payments p
    LEFT JOIN (
      SELECT payment_id, SUM(amount_cents) as total_applied
      FROM payment_allocations
      WHERE is_applied = 1
      GROUP BY payment_id
    ) alloc ON p.id = alloc.payment_id
    WHERE p.customer_id = ? AND p.status = 'CLEARED'
  `).get(customerId) as { total: number };

  db.prepare(`
    UPDATE customers
    SET balance_due_cents = ?,
        available_credit_cents = ?,
        unapplied_cash_cents = ?
    WHERE id = ?
  `).run(balanceResult.total, creditResult.total, Math.max(0, unappliedResult.total), customerId);
}
