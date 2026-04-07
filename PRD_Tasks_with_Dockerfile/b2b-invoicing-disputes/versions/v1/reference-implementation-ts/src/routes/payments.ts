import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db, getNextDocumentNumber } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  PaymentRow,
  PaymentAllocationRow,
  InvoiceRow,
  CustomerRow,
  WorkspaceRow,
  ContractRow,
} from '../types';
import { recalculateInvoiceAmounts, updateInvoiceCollectionsStage } from '../services/invoiceService';
import { recalculateCustomerBalances, updateCustomerStatus } from '../services/customerService';

const router = Router({ mergeParams: true });

function formatPayment(payment: PaymentRow, allocations: PaymentAllocationRow[]) {
  return {
    payment_id: payment.id,
    workspace_id: payment.workspace_id,
    customer_id: payment.customer_id,
    amount_cents: payment.amount_cents,
    status: payment.status,
    initiated_period_index: payment.initiated_period_index,
    cleared_period_index: payment.cleared_period_index,
    reversed_period_index: payment.reversed_period_index,
    allocations: allocations.map(a => ({
      allocation_id: a.id,
      invoice_id: a.invoice_id,
      amount_cents: a.amount_cents,
      is_reserved: !!a.is_reserved,
      is_applied: !!a.is_applied,
    })),
  };
}

function getPayableCap(invoice: InvoiceRow): number {
  const undisputed = invoice.amount_due_cents - invoice.amount_disputed_cents;
  if (undisputed <= 0) return 0;

  if (!invoice.purchase_order_id || invoice.match_status !== 'EXCEPTION') {
    return undisputed;
  }

  const lines = db.prepare(`SELECT * FROM invoice_lines WHERE invoice_id = ?`).all(invoice.id) as any[];

  let matchableCents = 0;
  for (const line of lines) {
    if (!line.purchase_order_line_id) {
      matchableCents += Number(line.line_total_cents ?? 0);
      continue;
    }

    const poLine = db.prepare(`SELECT * FROM purchase_order_lines WHERE id = ?`).get(line.purchase_order_line_id) as any | undefined;
    if (!poLine) {
      matchableCents += Number(line.line_total_cents ?? 0);
      continue;
    }

    if (poLine.is_service) {
      matchableCents += Number(line.line_total_cents ?? 0);
      continue;
    }

    const billedUnits = Number(line.quantity_units ?? 0);
    const receivedUnits = Number(poLine.received_units ?? 0);
    const unitPrice = Number(line.unit_price_cents ?? 0);
    const matchableUnits = Math.min(billedUnits, receivedUnits);
    matchableCents += matchableUnits * unitPrice;
  }

  return Math.min(undisputed, matchableCents);
}

function getPayableAmount(invoiceId: string): number {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow | undefined;
  if (!invoice) return 0;
  if (invoice.status === 'VOIDED' || invoice.status === 'CLOSED') return 0;

  const reservedResult = db.prepare(`
    SELECT COALESCE(SUM(pa.amount_cents), 0) as total
    FROM payment_allocations pa
    JOIN payments p ON pa.payment_id = p.id
    WHERE pa.invoice_id = ? AND p.status = 'INITIATED' AND pa.is_reserved = 1
  `).get(invoiceId) as { total: number };

  const payableCap = getPayableCap(invoice);
  return Math.max(0, payableCap - reservedResult.total);
}

router.post(
  '/',
  authMiddleware,
  requireRoles('BuyerAP', 'SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const { amount_cents, allocations = [] } = req.body;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const customer = db.prepare(`
      SELECT * FROM customers WHERE id = ? AND workspace_id = ?
    `).get(customer_id, workspace_id) as CustomerRow | undefined;

    if (!customer) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Customer not found', 404);
    }

    if (customer.status === 'FROZEN' && req.context.actorRole === 'BuyerAP') {
      throw new ApiError(ErrorCodes.CUSTOMER_FROZEN, 'Customer is frozen');
    }

    if (!amount_cents || amount_cents <= 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'amount_cents must be positive');
    }

    const allocationsSum = allocations.reduce((sum: number, a: any) => sum + (a.amount_cents || 0), 0);
    if (allocationsSum > amount_cents) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Allocations sum exceeds payment amount');
    }

    for (const alloc of allocations) {
      if (!alloc.invoice_id || !alloc.amount_cents) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each allocation must have invoice_id and amount_cents');
      }

      const invoice = db.prepare(`
        SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
      `).get(alloc.invoice_id, workspace_id) as InvoiceRow | undefined;

      if (!invoice) {
        throw new ApiError(ErrorCodes.NOT_FOUND, `Invoice ${alloc.invoice_id} not found`, 404);
      }

      if (invoice.customer_id !== customer_id) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice does not belong to this customer');
      }

      if (invoice.status === 'VOIDED' || invoice.status === 'CLOSED') {
        throw new ApiError(ErrorCodes.INVOICE_NOT_PAYABLE, `Invoice ${alloc.invoice_id} is not payable`);
      }

      const payable = getPayableAmount(alloc.invoice_id);
      if (alloc.amount_cents > payable) {
        throw new ApiError(
          ErrorCodes.PAYMENT_EXCEEDS_ALLOWED,
          `Allocation ${alloc.amount_cents} exceeds payable amount ${payable} for invoice ${alloc.invoice_id}`
        );
      }
    }

    const paymentId = uuidv4();

    db.transaction(() => {
      db.prepare(`
        INSERT INTO payments (id, workspace_id, customer_id, amount_cents, status, initiated_period_index)
        VALUES (?, ?, ?, ?, 'INITIATED', ?)
      `).run(paymentId, workspace_id, customer_id, amount_cents, workspace.period_index);

      for (const alloc of allocations) {
        const allocId = uuidv4();
        db.prepare(`
          INSERT INTO payment_allocations (id, payment_id, invoice_id, amount_cents, is_reserved, is_applied)
          VALUES (?, ?, ?, ?, 1, 0)
        `).run(allocId, paymentId, alloc.invoice_id, alloc.amount_cents);
      }

      if (allocations.length === 0 && amount_cents > 0) {

        const eligibleInvoices = db.prepare(`
          SELECT * FROM invoices
          WHERE customer_id = ? AND status NOT IN ('DRAFT', 'VOIDED', 'CLOSED')
          AND amount_due_cents > amount_disputed_cents
          ORDER BY
            (due_period_index IS NULL) ASC,
            due_period_index ASC,
            (issued_period_index IS NULL) ASC,
            issued_period_index ASC,
            id ASC
        `).all(customer_id) as InvoiceRow[];

        let remaining = amount_cents;

        for (const invoice of eligibleInvoices) {
          if (remaining <= 0) break;

          const payable = getPayableAmount(invoice.id);
          if (payable <= 0) continue;

          const allocAmount = Math.min(remaining, payable);
          const allocId = uuidv4();

          db.prepare(`
            INSERT INTO payment_allocations (id, payment_id, invoice_id, amount_cents, is_reserved, is_applied)
            VALUES (?, ?, ?, ?, 1, 0)
          `).run(allocId, paymentId, invoice.id, allocAmount);

          remaining -= allocAmount;
        }
      }
    })();

    const payment = db.prepare('SELECT * FROM payments WHERE id = ?').get(paymentId) as PaymentRow;
    const paymentAllocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(paymentId) as PaymentAllocationRow[];

    res.status(201).json(formatPayment(payment, paymentAllocations));
  }
);

router.get('/:payment_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, payment_id } = req.params;

  const payment = db.prepare(`
    SELECT * FROM payments WHERE id = ? AND workspace_id = ?
  `).get(payment_id, workspace_id) as PaymentRow | undefined;

  if (!payment) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Payment not found', 404);
  }

  const allocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

  res.json(formatPayment(payment, allocations));
});

router.post(
  '/:payment_id/mark_cleared',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin', 'System'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, payment_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const payment = db.prepare(`
      SELECT * FROM payments WHERE id = ? AND workspace_id = ?
    `).get(payment_id, workspace_id) as PaymentRow | undefined;

    if (!payment) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Payment not found', 404);
    }

    if (payment.status !== 'INITIATED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only clear INITIATED payments');
    }

    const allocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

    db.transaction(() => {
      let totalApplied = 0;

      for (const alloc of allocations) {
        const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(alloc.invoice_id) as InvoiceRow;

        if (invoice.status === 'VOIDED' || invoice.status === 'CLOSED') {

          continue;
        }

        const stillPayable = getPayableCap(invoice);
        const applyAmount = Math.min(alloc.amount_cents, stillPayable);

        if (applyAmount > 0) {

          db.prepare(`
            UPDATE payment_allocations
            SET is_applied = 1, is_reserved = 0, amount_cents = ?
            WHERE id = ?
          `).run(applyAmount, alloc.id);

          totalApplied += applyAmount;

          const newAmountDue = Math.max(0, invoice.amount_due_cents - applyAmount);
          const newAmountPaid = invoice.amount_paid_cents + applyAmount;

          db.prepare(`
            UPDATE invoices SET amount_due_cents = ?, amount_paid_cents = ? WHERE id = ?
          `).run(newAmountDue, newAmountPaid, invoice.id);

          checkAndApplyEarlyPayDiscount(invoice.id, workspace, payment);

          const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice.id) as InvoiceRow;
          if (updatedInvoice.amount_due_cents === 0 && updatedInvoice.status !== 'CLOSED') {
            db.prepare(`UPDATE invoices SET status = 'CLOSED' WHERE id = ?`).run(invoice.id);
          }

          updateInvoiceCollectionsStage(invoice.id, workspace.period_index);
        } else {

          db.prepare(`UPDATE payment_allocations SET is_applied = 0, is_reserved = 0 WHERE id = ?`).run(alloc.id);
        }
      }

      db.prepare(`
        UPDATE payments SET status = 'CLEARED', cleared_period_index = ? WHERE id = ?
      `).run(workspace.period_index, payment_id);

      recalculateCustomerBalances(payment.customer_id);
      updateCustomerStatus(payment.customer_id, workspace.period_index);
    })();

    const updatedPayment = db.prepare('SELECT * FROM payments WHERE id = ?').get(payment_id) as PaymentRow;
    const updatedAllocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

    res.json(formatPayment(updatedPayment, updatedAllocations));
  }
);

function checkAndApplyEarlyPayDiscount(invoiceId: string, workspace: WorkspaceRow, payment: PaymentRow) {
  const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;

  if (invoice.status === 'CLOSED') return;
  if (invoice.amount_disputed_cents > 0) return;
  if (invoice.amount_credited_cents > 0) return;
  if (invoice.due_period_index !== null && workspace.period_index > invoice.due_period_index) return;
  if (invoice.accepted_period_index === null) return;
  if (workspace.period_index > invoice.accepted_period_index + 1) return;

  const paymentCount = db.prepare(`
    SELECT COUNT(*) as count FROM payment_allocations pa
    JOIN payments p ON pa.payment_id = p.id
    WHERE pa.invoice_id = ? AND p.status IN ('CLEARED', 'INITIATED') AND pa.is_applied = 1
  `).get(invoiceId) as { count: number };

  if (paymentCount.count > 1) return;

  const remainingDue = invoice.amount_due_cents;
  if (remainingDue <= 0) return;

  const maxDiscount = Math.min(Math.floor(invoice.invoice_total_cents * 0.02), 50000);

  if (remainingDue > maxDiscount) return;

  const creditMemoId = uuidv4();
  const docNumber = getNextDocumentNumber(workspace.id, 'CREDIT_MEMO');

  db.prepare(`
    INSERT INTO credit_memos (
      id, workspace_id, customer_id, invoice_id, document_number,
      status, type, total_cents, applied_cents, reason,
      issued_period_index, is_system_generated
    ) VALUES (?, ?, ?, ?, ?, 'ISSUED', 'EARLY_PAY_DISCOUNT', ?, ?, 'Early pay discount', ?, 1)
  `).run(
    creditMemoId,
    workspace.id,
    invoice.customer_id,
    invoiceId,
    docNumber,
    remainingDue,
    remainingDue,
    workspace.period_index
  );

  const itemId = uuidv4();
  db.prepare(`
    INSERT INTO credit_memo_items (id, credit_memo_id, description, amount_cents)
    VALUES (?, ?, 'Early pay discount', ?)
  `).run(itemId, creditMemoId, remainingDue);

  const appId = uuidv4();
  db.prepare(`
    INSERT INTO credit_memo_applications (id, credit_memo_id, invoice_id, amount_cents)
    VALUES (?, ?, ?, ?)
  `).run(appId, creditMemoId, invoiceId, remainingDue);

  db.prepare(`
    UPDATE invoices SET
      amount_due_cents = 0,
      amount_credited_cents = amount_credited_cents + ?,
      status = 'CLOSED'
    WHERE id = ?
  `).run(remainingDue, invoiceId);
}

router.post(
  '/:payment_id/mark_failed',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin', 'System'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, payment_id } = req.params;

    const payment = db.prepare(`
      SELECT * FROM payments WHERE id = ? AND workspace_id = ?
    `).get(payment_id, workspace_id) as PaymentRow | undefined;

    if (!payment) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Payment not found', 404);
    }

    if (payment.status !== 'INITIATED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only fail INITIATED payments');
    }

    db.transaction(() => {

      db.prepare(`
        UPDATE payment_allocations SET is_reserved = 0 WHERE payment_id = ?
      `).run(payment_id);

      db.prepare(`UPDATE payments SET status = 'FAILED' WHERE id = ?`).run(payment_id);
    })();

    const updatedPayment = db.prepare('SELECT * FROM payments WHERE id = ?').get(payment_id) as PaymentRow;
    const allocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

    res.json(formatPayment(updatedPayment, allocations));
  }
);

router.post(
  '/:payment_id/reverse',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, payment_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const payment = db.prepare(`
      SELECT * FROM payments WHERE id = ? AND workspace_id = ?
    `).get(payment_id, workspace_id) as PaymentRow | undefined;

    if (!payment) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Payment not found', 404);
    }

    if (payment.status !== 'CLEARED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only reverse CLEARED payments');
    }

    const allocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

    db.transaction(() => {

      for (const alloc of allocations) {
        if (!alloc.is_applied) continue;

        const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(alloc.invoice_id) as InvoiceRow;

        const newAmountDue = invoice.amount_due_cents + alloc.amount_cents;
        const newAmountPaid = Math.max(0, invoice.amount_paid_cents - alloc.amount_cents);

        db.prepare(`
          UPDATE invoices SET amount_due_cents = ?, amount_paid_cents = ? WHERE id = ?
        `).run(newAmountDue, newAmountPaid, invoice.id);

        if (invoice.status === 'CLOSED') {

          const restoredStatus =
            invoice.accepted_period_index !== null && invoice.accepted_period_index !== undefined
              ? 'ACCEPTED'
              : invoice.delivered_period_index !== null && invoice.delivered_period_index !== undefined
                ? 'SENT'
                : 'FINALIZED';
          db.prepare(`UPDATE invoices SET status = ? WHERE id = ?`).run(restoredStatus, invoice.id);
        }

        const earlyPayCredit = db.prepare(`
          SELECT * FROM credit_memos
          WHERE invoice_id = ? AND type = 'EARLY_PAY_DISCOUNT' AND status = 'ISSUED'
        `).get(invoice.id) as any;

        if (earlyPayCredit) {

          db.prepare(`UPDATE credit_memos SET status = 'VOIDED' WHERE id = ?`).run(earlyPayCredit.id);

          db.prepare(`
            UPDATE invoices SET
              amount_due_cents = amount_due_cents + ?,
              amount_credited_cents = amount_credited_cents - ?
            WHERE id = ?
          `).run(earlyPayCredit.total_cents, earlyPayCredit.total_cents, invoice.id);

          db.prepare(`DELETE FROM credit_memo_applications WHERE credit_memo_id = ?`).run(earlyPayCredit.id);
        }

        db.prepare(`UPDATE payment_allocations SET is_applied = 0 WHERE id = ?`).run(alloc.id);

        updateInvoiceCollectionsStage(invoice.id, workspace.period_index);
      }

      db.prepare(`
        UPDATE payments SET status = 'REVERSED', reversed_period_index = ? WHERE id = ?
      `).run(workspace.period_index, payment_id);

      db.prepare(`
        UPDATE customers SET
          status = 'FROZEN',
          freeze_reason = 'PAYMENT_REVERSAL',
          last_reversal_period_index = ?
        WHERE id = ?
      `).run(workspace.period_index, payment.customer_id);

      recalculateCustomerBalances(payment.customer_id);
    })();

    const updatedPayment = db.prepare('SELECT * FROM payments WHERE id = ?').get(payment_id) as PaymentRow;
    const updatedAllocations = db.prepare('SELECT * FROM payment_allocations WHERE payment_id = ?').all(payment_id) as PaymentAllocationRow[];

    res.json(formatPayment(updatedPayment, updatedAllocations));
  }
);

export default router;
