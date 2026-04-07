import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  WorkspaceRow,
  InvoiceRow,
  DisputeRow,
  PaymentRow,
  CustomerRow,
} from '../types';
import {
  updateCustomerStatus,
  recalculateCustomerBalances,
} from '../services/customerService';
import {
  updateAllInvoiceStages,
  updateInvoiceMatchStatus,
  recalculateInvoiceAmounts,
} from '../services/invoiceService';
import { getNextDocumentNumber } from '../db/schema';

const router = Router();

router.post('/', authMiddleware, (req: Request, res: Response) => {
  const { name, currency = 'USD' } = req.body;

  if (!name) {
    throw new ApiError(ErrorCodes.INVALID_REQUEST, 'name is required');
  }

  const id = uuidv4();
  db.prepare(`
    INSERT INTO workspaces (id, name, currency, period_index, books_closed_through_period_index)
    VALUES (?, ?, ?, 0, NULL)
  `).run(id, name, currency);

  const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(id) as WorkspaceRow;

  res.status(201).json({
    workspace_id: workspace.id,
    name: workspace.name,
    currency: workspace.currency,
    period_index: workspace.period_index,
    books_closed_through_period_index: workspace.books_closed_through_period_index,
  });
});

router.get('/:workspace_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id } = req.params;

  const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;

  if (!workspace) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
  }

  res.json({
    workspace_id: workspace.id,
    name: workspace.name,
    currency: workspace.currency,
    period_index: workspace.period_index,
    books_closed_through_period_index: workspace.books_closed_through_period_index,
    integrity_status: 'OK',
  });
});

router.post(
  '/:workspace_id/advance_period',
  authMiddleware,
  requireRoles('SellerAdmin', 'System'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const closingPeriod = workspace.period_index;
    const newPeriodIndex = workspace.period_index + 1;

    const financeChargeInvoiceIds: string[] = [];

    db.transaction(() => {

      const disputesToWithdraw = db.prepare(`
        SELECT * FROM disputes
        WHERE workspace_id = ? AND status = 'PROPOSED'
        AND proposed_period_index IS NOT NULL
        AND proposed_period_index <= ?
      `).all(workspace_id, closingPeriod - 2) as DisputeRow[];

      for (const dispute of disputesToWithdraw) {
        db.prepare(`UPDATE disputes SET status = 'WITHDRAWN' WHERE id = ?`).run(dispute.id);

        if (dispute.proposed_credit_memo_id) {
          db.prepare(`UPDATE credit_memos SET status = 'VOIDED' WHERE id = ? AND status = 'DRAFT'`)
            .run(dispute.proposed_credit_memo_id);
        }

        if (dispute.reason === 'FRAUD') {
          const invoice = db.prepare(`SELECT * FROM invoices WHERE id = ?`).get(dispute.invoice_id) as InvoiceRow | undefined;
          if (invoice) {
            db.prepare(`
              UPDATE customers SET last_fraud_dispute_closed_period = ? WHERE id = ?
            `).run(newPeriodIndex, invoice.customer_id);
          }
        }

        recalculateInvoiceAmounts(dispute.invoice_id);
      }

      const invoicesForDeemedAcceptance = db.prepare(`
        SELECT * FROM invoices
        WHERE workspace_id = ? AND status = 'SENT'
        AND delivered_period_index IS NOT NULL
        AND delivered_period_index <= ?
      `).all(workspace_id, closingPeriod - 1) as InvoiceRow[];

      for (const invoice of invoicesForDeemedAcceptance) {

        const activeDispute = db.prepare(`
          SELECT 1 FROM disputes
          WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
          LIMIT 1
        `).get(invoice.id);

        if (activeDispute) continue;

        updateInvoiceMatchStatus(invoice.id);
        const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice.id) as InvoiceRow;

        if (updatedInvoice.match_status === 'MATCHED' || updatedInvoice.match_status === 'NOT_APPLICABLE') {
          const contract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(invoice.contract_id) as any;
          const paymentTerms = contract?.payment_terms_periods || 2;

          db.prepare(`
            UPDATE invoices
            SET status = 'ACCEPTED',
                accepted_period_index = ?,
                due_period_index = ?
            WHERE id = ?
          `).run(closingPeriod, closingPeriod + paymentTerms, invoice.id);
        }
      }

      const disputesToEscalate = db.prepare(`
        SELECT * FROM disputes
        WHERE workspace_id = ? AND status = 'OPEN'
        AND opened_period_index <= ?
        AND seller_responded = 0
      `).all(workspace_id, closingPeriod - 1) as DisputeRow[];

      for (const dispute of disputesToEscalate) {
        db.prepare(`UPDATE disputes SET status = 'ESCALATED' WHERE id = ?`).run(dispute.id);
      }

      updateAllInvoiceStages(workspace_id, newPeriodIndex);

      const overdueInvoices = db.prepare(`
        SELECT * FROM invoices
        WHERE workspace_id = ? AND status IN ('SENT', 'ACCEPTED')
        AND due_period_index IS NOT NULL AND due_period_index < ?
        AND amount_due_cents > amount_disputed_cents
      `).all(workspace_id, closingPeriod) as InvoiceRow[];

      const financeCharges: { invoice: InvoiceRow; amount: number }[] = [];
      let totalFinanceCharges = 0;

      const customerCharges: Map<string, { invoice: InvoiceRow; amount: number }[]> = new Map();

      for (const invoice of overdueInvoices) {
        const undisputedOverdue = invoice.amount_due_cents - invoice.amount_disputed_cents;
        if (undisputedOverdue <= 0) continue;

        let charge = Math.floor(undisputedOverdue * 0.015);
        charge = Math.max(2500, Math.min(25000, charge));

        if (!customerCharges.has(invoice.customer_id)) {
          customerCharges.set(invoice.customer_id, []);
        }
        customerCharges.get(invoice.customer_id)!.push({ invoice, amount: charge });
      }

      for (const [customerId, charges] of customerCharges) {
        const totalForCustomer = charges.reduce((sum, c) => sum + c.amount, 0);

        if (totalForCustomer > 50000) {

          const scaleFactor = 50000 / totalForCustomer;

          charges.sort((a, b) => {
            if (a.invoice.due_period_index !== b.invoice.due_period_index) {
              return (a.invoice.due_period_index || 0) - (b.invoice.due_period_index || 0);
            }
            return a.invoice.id.localeCompare(b.invoice.id);
          });

          let remaining = 50000;
          for (let i = 0; i < charges.length; i++) {
            const scaled = Math.floor(charges[i].amount * scaleFactor);
            charges[i].amount = scaled;
            remaining -= scaled;
          }

          for (let i = 0; i < charges.length && remaining > 0; i++) {
            charges[i].amount += 1;
            remaining -= 1;
          }
        }

        financeCharges.push(...charges);
      }

      for (const { invoice, amount } of financeCharges) {
        if (amount <= 0) continue;

        const fcInvoiceId = uuidv4();
        const docNumber = getNextDocumentNumber(workspace_id, 'INVOICE');

        db.prepare(`
          INSERT INTO invoices (
            id, workspace_id, customer_id, contract_id, document_number,
            status, type, invoice_total_cents, amount_due_cents,
            collections_stage, match_status,
            issued_period_index, delivered_period_index, accepted_period_index, due_period_index,
            parent_invoice_id
          ) VALUES (?, ?, ?, ?, ?, 'ACCEPTED', 'FINANCE_CHARGE', ?, ?, 'CURRENT', 'NOT_APPLICABLE', ?, ?, ?, ?, ?)
        `).run(
          fcInvoiceId,
          workspace_id,
          invoice.customer_id,
          invoice.contract_id,
          docNumber,
          amount,
          amount,
          newPeriodIndex,
          newPeriodIndex,
          newPeriodIndex,
          newPeriodIndex + 1,
          invoice.id
        );

        const lineId = uuidv4();
        db.prepare(`
          INSERT INTO invoice_lines (id, invoice_id, description, quantity_units, unit_price_cents, line_total_cents)
          VALUES (?, ?, ?, 1, ?, ?)
        `).run(lineId, fcInvoiceId, `Finance charge for invoice ${invoice.document_number}`, amount, amount);

        financeChargeInvoiceIds.push(fcInvoiceId);

        recalculateCustomerBalances(invoice.customer_id);
      }

      const customers = db.prepare(`
        SELECT * FROM customers WHERE workspace_id = ?
      `).all(workspace_id) as CustomerRow[];

      for (const customer of customers) {
        updateCustomerStatus(customer.id, newPeriodIndex);
        recalculateCustomerBalances(customer.id);
      }

      db.prepare('UPDATE workspaces SET period_index = ? WHERE id = ?').run(newPeriodIndex, workspace_id);
    })();

    const updatedWorkspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;

    res.json({
      workspace_id: updatedWorkspace.id,
      period_index: updatedWorkspace.period_index,
      books_closed_through_period_index: updatedWorkspace.books_closed_through_period_index,
      finance_charge_invoice_ids: financeChargeInvoiceIds,
    });
  }
);

router.post(
  '/:workspace_id/close_books',
  authMiddleware,
  requireRoles('SellerAdmin', 'Auditor'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const periodToClose = workspace.period_index - 1;

    if (workspace.period_index === 0) {
      throw new ApiError(
        ErrorCodes.INVALID_STATE_TRANSITION,
        'Cannot close books: no completed periods exist',
        400
      );
    }

    if (workspace.books_closed_through_period_index !== null &&
        workspace.books_closed_through_period_index >= periodToClose) {
      throw new ApiError(
        ErrorCodes.INVALID_STATE_TRANSITION,
        'Cannot close books: period already closed',
        400
      );
    }

    const pendingPayments = db.prepare(`
      SELECT 1 FROM payments
      WHERE workspace_id = ? AND status = 'INITIATED'
      AND initiated_period_index = ?
      LIMIT 1
    `).get(workspace_id, periodToClose);

    if (pendingPayments) {
      throw new ApiError(
        ErrorCodes.PERIOD_HAS_PENDING_PAYMENTS,
        'Cannot close books: there are pending payments in the period',
        400
      );
    }

    db.prepare(`
      UPDATE workspaces SET books_closed_through_period_index = ? WHERE id = ?
    `).run(periodToClose, workspace_id);

    const updatedWorkspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;

    res.json({
      workspace_id: updatedWorkspace.id,
      period_index: updatedWorkspace.period_index,
      books_closed_through_period_index: updatedWorkspace.books_closed_through_period_index,
    });
  }
);

router.post(
  '/:workspace_id/recompute',
  authMiddleware,
  requireRoles('SellerAdmin', 'System'),
  (req: Request, res: Response) => {
    const { workspace_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    db.transaction(() => {

      const invoices = db.prepare(`
        SELECT id FROM invoices WHERE workspace_id = ?
      `).all(workspace_id) as { id: string }[];

      for (const inv of invoices) {
        recalculateInvoiceAmounts(inv.id);
        updateInvoiceMatchStatus(inv.id);
      }

      updateAllInvoiceStages(workspace_id, workspace.period_index);

      const customers = db.prepare(`
        SELECT id FROM customers WHERE workspace_id = ?
      `).all(workspace_id) as { id: string }[];

      for (const cust of customers) {
        recalculateCustomerBalances(cust.id);
        updateCustomerStatus(cust.id, workspace.period_index);
      }
    })();

    res.json({
      workspace_id: workspace.id,
      name: workspace.name,
      currency: workspace.currency,
      period_index: workspace.period_index,
      books_closed_through_period_index: workspace.books_closed_through_period_index,
      integrity_status: 'OK',
    });
  }
);

export default router;
