import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db, getNextDocumentNumber } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  CreditMemoRow,
  CreditMemoItemRow,
  CreditMemoApplicationRow,
  InvoiceRow,
  InvoiceLineRow,
  CustomerRow,
  WorkspaceRow,
  DisputeRow,
  DisputeItemRow,
} from '../types';
import { recalculateInvoiceAmounts, updateInvoiceCollectionsStage, updateInvoiceMatchStatus } from '../services/invoiceService';
import { recalculateCustomerBalances, updateCustomerStatus } from '../services/customerService';

const router = Router({ mergeParams: true });

function formatCreditMemo(cm: CreditMemoRow, items: CreditMemoItemRow[], applications: CreditMemoApplicationRow[]) {
  return {
    credit_memo_id: cm.id,
    workspace_id: cm.workspace_id,
    customer_id: cm.customer_id,
    invoice_id: cm.invoice_id,
    document_number: cm.document_number,
    status: cm.status,
    type: cm.type,
    total_cents: cm.total_cents,
    applied_cents: cm.applied_cents,
    reason: cm.reason,
    dispute_id: cm.dispute_id,
    issued_period_index: cm.issued_period_index,
    is_system_generated: !!cm.is_system_generated,
    items: items.map(i => ({
      credit_memo_item_id: i.id,
      invoice_line_id: i.invoice_line_id,
      description: i.description,
      quantity_units: i.quantity_units,
      unit_price_cents: i.unit_price_cents,
      amount_cents: i.amount_cents,
    })),
    applications: applications.map(a => ({
      application_id: a.id,
      invoice_id: a.invoice_id,
      amount_cents: a.amount_cents,
      applied_at: a.applied_at,
    })),
  };
}

const MAX_GOODWILL_PER_MEMO_CENTS = 100000;
const MAX_GOODWILL_PER_CUSTOMER_PER_PERIOD_CENTS = 250000;

router.post(
  '/',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const { invoice_id, reason = 'GOODWILL', items = [] } = req.body;

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

    let invoice: InvoiceRow | undefined;
    if (invoice_id) {
      invoice = db.prepare(`
        SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
      `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

      if (!invoice) {
        throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
      }

      if (invoice.customer_id !== customer_id) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice does not belong to this customer');
      }
    }

    if (!items || items.length === 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'At least one item is required');
    }

    let totalAmount = 0;

    for (const item of items) {
      let itemAmount = 0;

      if (item.amount_cents !== undefined) {
        itemAmount = item.amount_cents;
      } else if (item.quantity_units !== undefined && item.unit_price_cents !== undefined) {
        itemAmount = Math.round(item.quantity_units * item.unit_price_cents);
      } else {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each item must have amount_cents or (quantity_units and unit_price_cents)');
      }

      if (itemAmount <= 0) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Credit item amount must be positive');
      }

      if (item.invoice_line_id) {
        const line = db.prepare(`
          SELECT il.*, i.id as inv_id FROM invoice_lines il
          JOIN invoices i ON il.invoice_id = i.id
          WHERE il.id = ?
        `).get(item.invoice_line_id) as (InvoiceLineRow & { inv_id: string }) | undefined;

        if (!line) {
          throw new ApiError(ErrorCodes.NOT_FOUND, `Invoice line ${item.invoice_line_id} not found`, 404);
        }

        if (invoice_id && line.inv_id !== invoice_id) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice line does not belong to the specified invoice');
        }
      }

      totalAmount += itemAmount;
    }

    const creditMemoId = uuidv4();

    db.transaction(() => {
      db.prepare(`
        INSERT INTO credit_memos (
          id, workspace_id, customer_id, invoice_id,
          status, type, total_cents, applied_cents, reason
        ) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, 0, ?)
      `).run(creditMemoId, workspace_id, customer_id, invoice_id || null, reason, totalAmount, reason);

      for (const item of items) {
        let itemAmount = item.amount_cents;
        if (itemAmount === undefined) {
          itemAmount = Math.round(item.quantity_units * item.unit_price_cents);
        }

        const itemId = uuidv4();
        db.prepare(`
          INSERT INTO credit_memo_items (
            id, credit_memo_id, invoice_line_id, description,
            quantity_units, unit_price_cents, amount_cents
          ) VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(
          itemId,
          creditMemoId,
          item.invoice_line_id || null,
          item.description || null,
          item.quantity_units || null,
          item.unit_price_cents || null,
          itemAmount
        );
      }
    })();

    const creditMemo = db.prepare('SELECT * FROM credit_memos WHERE id = ?').get(creditMemoId) as CreditMemoRow;
    const creditItems = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(creditMemoId) as CreditMemoItemRow[];
    const applications: CreditMemoApplicationRow[] = [];

    res.status(201).json(formatCreditMemo(creditMemo, creditItems, applications));
  }
);

router.get('/:credit_memo_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, credit_memo_id } = req.params;

  const creditMemo = db.prepare(`
    SELECT * FROM credit_memos WHERE id = ? AND workspace_id = ?
  `).get(credit_memo_id, workspace_id) as CreditMemoRow | undefined;

  if (!creditMemo) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Credit memo not found', 404);
  }

  const items = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoItemRow[];
  const applications = db.prepare('SELECT * FROM credit_memo_applications WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoApplicationRow[];

  res.json(formatCreditMemo(creditMemo, items, applications));
});

router.get('/', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id } = req.params;
  const { customer_id, status } = req.query;

  let query = 'SELECT * FROM credit_memos WHERE workspace_id = ?';
  const params: any[] = [workspace_id];

  if (customer_id) {
    query += ' AND customer_id = ?';
    params.push(customer_id);
  }

  if (status) {
    query += ' AND status = ?';
    params.push(status);
  }

  const creditMemos = db.prepare(query).all(...params) as CreditMemoRow[];

  const result = creditMemos.map(cm => {
    const items = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(cm.id) as CreditMemoItemRow[];
    const applications = db.prepare('SELECT * FROM credit_memo_applications WHERE credit_memo_id = ?').all(cm.id) as CreditMemoApplicationRow[];
    return formatCreditMemo(cm, items, applications);
  });

  res.json({ credit_memos: result });
});

router.post(
  '/:credit_memo_id/issue',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, credit_memo_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const creditMemo = db.prepare(`
      SELECT * FROM credit_memos WHERE id = ? AND workspace_id = ?
    `).get(credit_memo_id, workspace_id) as CreditMemoRow | undefined;

    if (!creditMemo) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Credit memo not found', 404);
    }

    if (creditMemo.status !== 'DRAFT') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only issue DRAFT credit memos');
    }

    if (creditMemo.dispute_id) {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Dispute resolution credit memos are issued through dispute workflow');
    }

    if (creditMemo.type === 'GOODWILL' && req.context.actorRole === 'SellerAR') {
      if (creditMemo.total_cents > MAX_GOODWILL_PER_MEMO_CENTS) {
        throw new ApiError(
          ErrorCodes.CREDIT_EXCEEDS_AUTHORITY,
          `Goodwill credit exceeds per-memo limit of ${MAX_GOODWILL_PER_MEMO_CENTS / 100} dollars`
        );
      }

      const periodGoodwillResult = db.prepare(`
        SELECT COALESCE(SUM(total_cents), 0) as total
        FROM credit_memos
        WHERE customer_id = ? AND type = 'GOODWILL' AND issued_period_index = ?
        AND status = 'ISSUED' AND dispute_id IS NULL
      `).get(creditMemo.customer_id, workspace.period_index) as { total: number };

      if (periodGoodwillResult.total + creditMemo.total_cents > MAX_GOODWILL_PER_CUSTOMER_PER_PERIOD_CENTS) {
        throw new ApiError(
          ErrorCodes.CREDIT_EXCEEDS_AUTHORITY,
          `Goodwill credit exceeds per-customer-per-period limit of ${MAX_GOODWILL_PER_CUSTOMER_PER_PERIOD_CENTS / 100} dollars`
        );
      }
    }

    const docNumber = getNextDocumentNumber(workspace_id, 'CREDIT_MEMO');

    db.transaction(() => {
      db.prepare(`
        UPDATE credit_memos SET
          status = 'ISSUED',
          document_number = ?,
          issued_period_index = ?
        WHERE id = ?
      `).run(docNumber, workspace.period_index, credit_memo_id);

      db.prepare(`
        UPDATE customers SET available_credit_cents = available_credit_cents + ?
        WHERE id = ?
      `).run(creditMemo.total_cents, creditMemo.customer_id);

      recalculateCustomerBalances(creditMemo.customer_id);
    })();

    const updatedCreditMemo = db.prepare('SELECT * FROM credit_memos WHERE id = ?').get(credit_memo_id) as CreditMemoRow;
    const items = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoItemRow[];
    const applications = db.prepare('SELECT * FROM credit_memo_applications WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoApplicationRow[];

    res.json(formatCreditMemo(updatedCreditMemo, items, applications));
  }
);

router.post(
  '/:credit_memo_id/apply',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, credit_memo_id } = req.params;
    const { invoice_id } = req.body;

    if (!invoice_id) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'invoice_id is required');
    }

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const creditMemo = db.prepare(`
      SELECT * FROM credit_memos WHERE id = ? AND workspace_id = ?
    `).get(credit_memo_id, workspace_id) as CreditMemoRow | undefined;

    if (!creditMemo) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Credit memo not found', 404);
    }

    if (creditMemo.status !== 'ISSUED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only apply ISSUED credit memos');
    }

    if (creditMemo.invoice_id && creditMemo.invoice_id !== invoice_id) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice-tied credit memo cannot be applied to a different invoice');
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    if (invoice.customer_id !== creditMemo.customer_id) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice does not belong to the same customer');
    }

    if (invoice.status === 'CLOSED' || invoice.status === 'VOIDED') {
      throw new ApiError(ErrorCodes.INVOICE_NOT_CREDITABLE, 'Invoice cannot accept credits');
    }

    const availableCredit = creditMemo.total_cents - creditMemo.applied_cents;
    if (availableCredit <= 0) {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Credit memo has no remaining balance');
    }

    const applyAmount = Math.min(availableCredit, invoice.amount_due_cents);

    if (applyAmount <= 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'No applicable amount');
    }

    db.transaction(() => {

      const appId = uuidv4();
      db.prepare(`
        INSERT INTO credit_memo_applications (id, credit_memo_id, invoice_id, amount_cents)
        VALUES (?, ?, ?, ?)
      `).run(appId, credit_memo_id, invoice_id, applyAmount);

      db.prepare(`
        UPDATE credit_memos SET applied_cents = applied_cents + ? WHERE id = ?
      `).run(applyAmount, credit_memo_id);

      const newAmountDue = Math.max(0, invoice.amount_due_cents - applyAmount);
      const newCredited = invoice.amount_credited_cents + applyAmount;

      const creditItems = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoItemRow[];

      const activeDisputes = db.prepare(`
        SELECT * FROM disputes WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
      `).all(invoice_id) as DisputeRow[];

      let disputeReduction = 0;

      if (activeDisputes.length > 0) {
        for (const ci of creditItems) {
          if (ci.invoice_line_id) {

            for (const dispute of activeDisputes) {
              const disputeItem = db.prepare(`
                SELECT * FROM dispute_items WHERE dispute_id = ? AND invoice_line_id = ?
              `).get(dispute.id, ci.invoice_line_id) as DisputeItemRow | undefined;

              if (disputeItem) {
                disputeReduction += Math.min(ci.amount_cents, disputeItem.disputed_amount_cents || 0);
              }
            }
          }
        }
      }

      const newDisputed = Math.min(Math.max(0, invoice.amount_disputed_cents - disputeReduction), newAmountDue);

      db.prepare(`
        UPDATE invoices SET
          amount_due_cents = ?,
          amount_credited_cents = ?,
          amount_disputed_cents = ?
        WHERE id = ?
      `).run(newAmountDue, newCredited, newDisputed, invoice_id);

      for (const ci of creditItems) {
        if (ci.invoice_line_id && ci.quantity_units) {
          const invoiceLine = db.prepare('SELECT * FROM invoice_lines WHERE id = ?').get(ci.invoice_line_id) as InvoiceLineRow;
          if (invoiceLine && invoiceLine.purchase_order_line_id) {
            db.prepare(`
              UPDATE purchase_order_lines
              SET net_billed_units = net_billed_units - ?
              WHERE id = ?
            `).run(ci.quantity_units, invoiceLine.purchase_order_line_id);
          }

          db.prepare(`
            UPDATE invoice_lines SET credited_amount_cents = credited_amount_cents + ?
            WHERE id = ?
          `).run(ci.amount_cents, ci.invoice_line_id);
        }
      }

      db.prepare(`
        UPDATE customers SET available_credit_cents = available_credit_cents - ?
        WHERE id = ?
      `).run(applyAmount, creditMemo.customer_id);

      const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
      if (updatedInvoice.amount_due_cents === 0 && updatedInvoice.status !== 'CLOSED') {
        db.prepare(`UPDATE invoices SET status = 'CLOSED' WHERE id = ?`).run(invoice_id);
      }

      updateInvoiceMatchStatus(invoice_id);

      updateInvoiceCollectionsStage(invoice_id, workspace.period_index);

      recalculateCustomerBalances(creditMemo.customer_id);
      updateCustomerStatus(creditMemo.customer_id, workspace.period_index);
    })();

    const updatedCreditMemo = db.prepare('SELECT * FROM credit_memos WHERE id = ?').get(credit_memo_id) as CreditMemoRow;
    const items = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoItemRow[];
    const applications = db.prepare('SELECT * FROM credit_memo_applications WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoApplicationRow[];

    res.json(formatCreditMemo(updatedCreditMemo, items, applications));
  }
);

router.post(
  '/:credit_memo_id/void',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, credit_memo_id } = req.params;

    const creditMemo = db.prepare(`
      SELECT * FROM credit_memos WHERE id = ? AND workspace_id = ?
    `).get(credit_memo_id, workspace_id) as CreditMemoRow | undefined;

    if (!creditMemo) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Credit memo not found', 404);
    }

    if (creditMemo.status === 'VOIDED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Credit memo is already voided');
    }

    if (creditMemo.type === 'EARLY_PAY_DISCOUNT' && creditMemo.is_system_generated) {
      throw new ApiError(ErrorCodes.CREDIT_MEMO_LOCKED, 'Cannot void system-generated early pay discount');
    }

    if (creditMemo.applied_cents > 0) {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Cannot void a credit memo that has been applied');
    }

    db.transaction(() => {
      db.prepare(`UPDATE credit_memos SET status = 'VOIDED' WHERE id = ?`).run(credit_memo_id);

      if (creditMemo.status === 'ISSUED') {
        db.prepare(`
          UPDATE customers SET available_credit_cents = available_credit_cents - ?
          WHERE id = ?
        `).run(creditMemo.total_cents, creditMemo.customer_id);
      }

      recalculateCustomerBalances(creditMemo.customer_id);
    })();

    const updatedCreditMemo = db.prepare('SELECT * FROM credit_memos WHERE id = ?').get(credit_memo_id) as CreditMemoRow;
    const items = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoItemRow[];
    const applications = db.prepare('SELECT * FROM credit_memo_applications WHERE credit_memo_id = ?').all(credit_memo_id) as CreditMemoApplicationRow[];

    res.json(formatCreditMemo(updatedCreditMemo, items, applications));
  }
);

export default router;
