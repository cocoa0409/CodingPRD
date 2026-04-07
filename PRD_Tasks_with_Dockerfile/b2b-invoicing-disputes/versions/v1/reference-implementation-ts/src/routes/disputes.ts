import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db, getNextDocumentNumber } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  DisputeRow,
  DisputeItemRow,
  InvoiceRow,
  InvoiceLineRow,
  CustomerRow,
  WorkspaceRow,
  CreditMemoRow,
  DisputeReason,
} from '../types';
import { recalculateInvoiceAmounts, updateInvoiceCollectionsStage, updateInvoiceMatchStatus } from '../services/invoiceService';
import { recalculateCustomerBalances, updateCustomerStatus } from '../services/customerService';

const router = Router({ mergeParams: true });

const DISPUTE_REASONS: DisputeReason[] = ['PRICE_MISMATCH', 'MISSING_RECEIPT', 'SERVICE_QUALITY', 'TAX_ERROR', 'DUPLICATE_INVOICE', 'FRAUD'];
const ALWAYS_ALLOWED_REASONS: DisputeReason[] = ['FRAUD', 'DUPLICATE_INVOICE'];
const FINANCE_CHARGE_ALLOWED_REASONS: DisputeReason[] = ['FRAUD', 'DUPLICATE_INVOICE'];

function formatDispute(dispute: DisputeRow, items: DisputeItemRow[]) {
  return {
    dispute_id: dispute.id,
    workspace_id: dispute.workspace_id,
    invoice_id: dispute.invoice_id,
    reason: dispute.reason,
    status: dispute.status,
    disputed_amount_cents: dispute.disputed_amount_cents,
    opened_period_index: dispute.opened_period_index,
    proposed_period_index: dispute.proposed_period_index,
    closed_period_index: dispute.closed_period_index,
    seller_responded: !!dispute.seller_responded,
    proposed_credit_memo_id: dispute.proposed_credit_memo_id,
    items: items.map(i => ({
      dispute_item_id: i.id,
      invoice_line_id: i.invoice_line_id,
      disputed_units: i.disputed_units,
      disputed_amount_cents: i.disputed_amount_cents,
    })),
  };
}

function getContestableAmount(invoice: InvoiceRow): number {

  const activeDisputedResult = db.prepare(`
    SELECT COALESCE(SUM(disputed_amount_cents), 0) as total
    FROM disputes
    WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
  `).get(invoice.id) as { total: number };

  return Math.max(0, invoice.amount_due_cents - activeDisputedResult.total);
}

router.post(
  '/',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;
    const { reason, items = [] } = req.body;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(invoice.customer_id) as CustomerRow;

    if (customer.status === 'FROZEN') {
      throw new ApiError(ErrorCodes.CUSTOMER_FROZEN, 'Customer is frozen');
    }

    if (invoice.status !== 'SENT' && invoice.status !== 'ACCEPTED') {
      throw new ApiError(ErrorCodes.INVOICE_NOT_DISPUTABLE, 'Invoice is not in a disputable state');
    }

    const activeDispute = db.prepare(`
      SELECT 1 FROM disputes
      WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
      LIMIT 1
    `).get(invoice_id);

    if (activeDispute) {
      throw new ApiError(ErrorCodes.DISPUTE_ALREADY_ACTIVE, 'An active dispute already exists for this invoice');
    }

    if (!reason || !DISPUTE_REASONS.includes(reason)) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invalid dispute reason');
    }

    if (invoice.type === 'FINANCE_CHARGE') {
      if (!FINANCE_CHARGE_ALLOWED_REASONS.includes(reason)) {
        throw new ApiError(ErrorCodes.DISPUTE_REASON_NOT_ALLOWED, 'This dispute reason is not allowed for finance charge invoices');
      }
    }

    if (invoice.collections_stage === 'COLLECTIONS') {
      if (!ALWAYS_ALLOWED_REASONS.includes(reason)) {
        throw new ApiError(ErrorCodes.COLLECTIONS_RESTRICTS_DISPUTES, 'Only FRAUD and DUPLICATE_INVOICE disputes allowed in collections');
      }
    }

    if (!ALWAYS_ALLOWED_REASONS.includes(reason)) {

      const acceptedPeriod = invoice.accepted_period_index;
      if (acceptedPeriod !== null) {
        const maxPeriods = reason === 'TAX_ERROR' ? 6 : 2;
        if (workspace.period_index - acceptedPeriod > maxPeriods) {
          throw new ApiError(ErrorCodes.DISPUTE_WINDOW_CLOSED, 'Dispute window has closed for this reason');
        }
      }
    }

    if (!items || items.length === 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'At least one dispute item is required');
    }

    let totalDisputedAmount = 0;

    for (const item of items) {
      if (!item.invoice_line_id) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each item must have invoice_line_id');
      }

      const line = db.prepare(`
        SELECT * FROM invoice_lines WHERE id = ? AND invoice_id = ?
      `).get(item.invoice_line_id, invoice_id) as InvoiceLineRow | undefined;

      if (!line) {
        throw new ApiError(ErrorCodes.NOT_FOUND, `Invoice line ${item.invoice_line_id} not found`, 404);
      }

      let itemAmount = 0;

      if (item.disputed_amount_cents !== undefined && item.disputed_units !== undefined) {

        const impliedAmount = Math.round(item.disputed_units * line.unit_price_cents);
        if (Math.abs(impliedAmount - item.disputed_amount_cents) > 1) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Disputed units and amount are inconsistent');
        }
        itemAmount = item.disputed_amount_cents;
      } else if (item.disputed_units !== undefined) {
        itemAmount = Math.round(item.disputed_units * line.unit_price_cents);
      } else if (item.disputed_amount_cents !== undefined) {
        itemAmount = item.disputed_amount_cents;
      } else {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each item must have disputed_units or disputed_amount_cents');
      }

      if (itemAmount <= 0) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Disputed amount must be positive');
      }

      totalDisputedAmount += itemAmount;
    }

    const contestable = getContestableAmount(invoice);
    if (totalDisputedAmount > contestable) {
      throw new ApiError(
        ErrorCodes.DISPUTE_AMOUNT_EXCEEDS_AVAILABLE,
        `Disputed amount ${totalDisputedAmount} exceeds contestable amount ${contestable}`
      );
    }

    const disputeId = uuidv4();

    db.transaction(() => {
      db.prepare(`
        INSERT INTO disputes (
          id, workspace_id, invoice_id, reason, status,
          disputed_amount_cents, opened_period_index, seller_responded
        ) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, 0)
      `).run(disputeId, workspace_id, invoice_id, reason, totalDisputedAmount, workspace.period_index);

      for (const item of items) {
        const line = db.prepare('SELECT * FROM invoice_lines WHERE id = ?').get(item.invoice_line_id) as InvoiceLineRow;

        let itemAmount = item.disputed_amount_cents;
        if (itemAmount === undefined && item.disputed_units !== undefined) {
          itemAmount = Math.round(item.disputed_units * line.unit_price_cents);
        }

        const itemId = uuidv4();
        db.prepare(`
          INSERT INTO dispute_items (id, dispute_id, invoice_line_id, disputed_units, disputed_amount_cents)
          VALUES (?, ?, ?, ?, ?)
        `).run(itemId, disputeId, item.invoice_line_id, item.disputed_units ?? null, itemAmount);
      }

      recalculateInvoiceAmounts(invoice_id);
      updateInvoiceMatchStatus(invoice_id);
      updateInvoiceCollectionsStage(invoice_id, workspace.period_index);

      if (reason === 'FRAUD') {
        db.prepare(`
          UPDATE customers SET status = 'FROZEN', freeze_reason = 'FRAUD_DISPUTE'
          WHERE id = ?
        `).run(invoice.customer_id);
      }

      recalculateCustomerBalances(invoice.customer_id);
      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const dispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(disputeId) as DisputeRow;
    const disputeItems = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(disputeId) as DisputeItemRow[];

    res.status(201).json(formatDispute(dispute, disputeItems));
  }
);

router.get('/:dispute_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, dispute_id } = req.params;

  const dispute = db.prepare(`
    SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
  `).get(dispute_id, workspace_id) as DisputeRow | undefined;

  if (!dispute) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
  }

  const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

  res.json(formatDispute(dispute, items));
});

router.post(
  '/:dispute_id/seller_respond',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, dispute_id } = req.params;

    const dispute = db.prepare(`
      SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
    `).get(dispute_id, workspace_id) as DisputeRow | undefined;

    if (!dispute) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
    }

    if (dispute.status === 'CLOSED' || dispute.status === 'WITHDRAWN') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Dispute is already closed or withdrawn');
    }

    let newStatus = dispute.status === 'ESCALATED' ? 'ESCALATED' : 'IN_REVIEW';

    db.prepare(`
      UPDATE disputes SET status = ?, seller_responded = 1 WHERE id = ?
    `).run(newStatus, dispute_id);

    const updatedDispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(dispute_id) as DisputeRow;
    const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

    res.json(formatDispute(updatedDispute, items));
  }
);

router.post(
  '/:dispute_id/propose_resolution',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, dispute_id } = req.params;
    const { proposed_credit } = req.body;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const dispute = db.prepare(`
      SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
    `).get(dispute_id, workspace_id) as DisputeRow | undefined;

    if (!dispute) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
    }

    if (dispute.status === 'CLOSED' || dispute.status === 'WITHDRAWN' || dispute.status === 'PROPOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Cannot propose resolution for this dispute');
    }

    const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(dispute.invoice_id) as InvoiceRow;

    let creditMemoId: string | null = null;

    if (proposed_credit && proposed_credit.items && proposed_credit.items.length > 0) {
      creditMemoId = uuidv4();
      let totalCreditAmount = 0;

      db.transaction(() => {
        db.prepare(`
          INSERT INTO credit_memos (
            id, workspace_id, customer_id, invoice_id,
            status, type, total_cents, applied_cents, reason, dispute_id
          ) VALUES (?, ?, ?, ?, 'DRAFT', 'DISPUTE_RESOLUTION', 0, 0, 'Dispute resolution', ?)
        `).run(creditMemoId, workspace_id, invoice.customer_id, invoice.id, dispute_id);

        for (const item of proposed_credit.items) {
          let itemAmount = 0;

          if (item.amount_cents !== undefined) {
            itemAmount = item.amount_cents;
          } else if (item.quantity_units !== undefined && item.unit_price_cents !== undefined) {
            itemAmount = Math.round(item.quantity_units * item.unit_price_cents);
          } else {
            throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Credit item must have amount_cents or quantity_units and unit_price_cents');
          }

          totalCreditAmount += itemAmount;

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
            item.description || 'Dispute resolution credit',
            item.quantity_units || null,
            item.unit_price_cents || null,
            itemAmount
          );
        }

        db.prepare(`UPDATE credit_memos SET total_cents = ? WHERE id = ?`).run(totalCreditAmount, creditMemoId);
      })();
    }

    db.prepare(`
      UPDATE disputes SET
        status = 'PROPOSED',
        proposed_period_index = ?,
        proposed_credit_memo_id = ?,
        seller_responded = 1
      WHERE id = ?
    `).run(workspace.period_index, creditMemoId, dispute_id);

    const updatedDispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(dispute_id) as DisputeRow;
    const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

    res.json(formatDispute(updatedDispute, items));
  }
);

router.post(
  '/:dispute_id/accept_resolution',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, dispute_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const dispute = db.prepare(`
      SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
    `).get(dispute_id, workspace_id) as DisputeRow | undefined;

    if (!dispute) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
    }

    if (dispute.status !== 'PROPOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only accept PROPOSED disputes');
    }

    const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(dispute.invoice_id) as InvoiceRow;

    db.transaction(() => {

      if (dispute.proposed_credit_memo_id) {
        const creditMemo = db.prepare('SELECT * FROM credit_memos WHERE id = ?').get(dispute.proposed_credit_memo_id) as CreditMemoRow;

        if (creditMemo && creditMemo.status === 'DRAFT') {
          const docNumber = getNextDocumentNumber(workspace_id, 'CREDIT_MEMO');

          db.prepare(`
            UPDATE credit_memos SET
              status = 'ISSUED',
              document_number = ?,
              issued_period_index = ?
            WHERE id = ?
          `).run(docNumber, workspace.period_index, creditMemo.id);

          const applyAmount = Math.min(creditMemo.total_cents, invoice.amount_due_cents);

          const appId = uuidv4();
          db.prepare(`
            INSERT INTO credit_memo_applications (id, credit_memo_id, invoice_id, amount_cents)
            VALUES (?, ?, ?, ?)
          `).run(appId, creditMemo.id, invoice.id, applyAmount);

          db.prepare(`
            UPDATE credit_memos SET applied_cents = ? WHERE id = ?
          `).run(applyAmount, creditMemo.id);

          const newAmountDue = Math.max(0, invoice.amount_due_cents - applyAmount);
          const newCredited = invoice.amount_credited_cents + applyAmount;

          const creditItems = db.prepare('SELECT * FROM credit_memo_items WHERE credit_memo_id = ?').all(creditMemo.id) as any[];
          const disputeItems = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

          let disputeReduction = 0;
          for (const ci of creditItems) {
            if (ci.invoice_line_id) {
              const matchingDisputeItem = disputeItems.find(di => di.invoice_line_id === ci.invoice_line_id);
              if (matchingDisputeItem) {
                disputeReduction += Math.min(ci.amount_cents, matchingDisputeItem.disputed_amount_cents || 0);
              }
            }
          }

          if (disputeReduction === 0) {
            disputeReduction = Math.min(applyAmount, dispute.disputed_amount_cents);
          }

          db.prepare(`
            UPDATE invoices SET
              amount_due_cents = ?,
              amount_credited_cents = ?,
              amount_disputed_cents = CASE WHEN amount_disputed_cents >= ? THEN amount_disputed_cents - ? ELSE 0 END
            WHERE id = ?
          `).run(newAmountDue, newCredited, disputeReduction, disputeReduction, invoice.id);

          for (const ci of creditItems) {
            if (ci.invoice_line_id && ci.quantity_units != null) {
              const invoiceLine = db.prepare('SELECT * FROM invoice_lines WHERE id = ?').get(ci.invoice_line_id) as InvoiceLineRow;
              if (invoiceLine?.purchase_order_line_id) {
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

          const remainingCredit = creditMemo.total_cents - applyAmount;
          if (remainingCredit > 0) {
            db.prepare(`
              UPDATE customers SET available_credit_cents = available_credit_cents + ?
              WHERE id = ?
            `).run(remainingCredit, invoice.customer_id);
          }

          const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice.id) as InvoiceRow;
          if (updatedInvoice.amount_due_cents === 0 && updatedInvoice.status !== 'CLOSED') {
            db.prepare(`UPDATE invoices SET status = 'CLOSED' WHERE id = ?`).run(invoice.id);
          }
        }
      }

      db.prepare(`
        UPDATE disputes SET status = 'CLOSED', closed_period_index = ? WHERE id = ?
      `).run(workspace.period_index, dispute_id);

      recalculateInvoiceAmounts(dispute.invoice_id);
      updateInvoiceMatchStatus(dispute.invoice_id);
      updateInvoiceCollectionsStage(dispute.invoice_id, workspace.period_index);
      recalculateCustomerBalances(invoice.customer_id);

      if (dispute.reason === 'FRAUD') {
        db.prepare(`
          UPDATE customers SET last_fraud_dispute_closed_period = ? WHERE id = ?
        `).run(workspace.period_index, invoice.customer_id);
      }

      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const updatedDispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(dispute_id) as DisputeRow;
    const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

    res.json(formatDispute(updatedDispute, items));
  }
);

router.post(
  '/:dispute_id/reject_resolution',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, dispute_id } = req.params;

    const dispute = db.prepare(`
      SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
    `).get(dispute_id, workspace_id) as DisputeRow | undefined;

    if (!dispute) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
    }

    if (dispute.status !== 'PROPOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only reject PROPOSED disputes');
    }

    const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(dispute.invoice_id) as InvoiceRow;
    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;

    db.transaction(() => {
      db.prepare(`UPDATE disputes SET status = 'ESCALATED' WHERE id = ?`).run(dispute_id);

      if (dispute.proposed_credit_memo_id) {
        db.prepare(`UPDATE credit_memos SET status = 'VOIDED' WHERE id = ? AND status = 'DRAFT'`)
          .run(dispute.proposed_credit_memo_id);
      }

      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const updatedDispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(dispute_id) as DisputeRow;
    const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

    res.json(formatDispute(updatedDispute, items));
  }
);

router.post(
  '/:dispute_id/withdraw',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, dispute_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const dispute = db.prepare(`
      SELECT * FROM disputes WHERE id = ? AND workspace_id = ?
    `).get(dispute_id, workspace_id) as DisputeRow | undefined;

    if (!dispute) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Dispute not found', 404);
    }

    if (dispute.status === 'CLOSED' || dispute.status === 'WITHDRAWN') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Dispute is already closed or withdrawn');
    }

    const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(dispute.invoice_id) as InvoiceRow;

    db.transaction(() => {
      db.prepare(`UPDATE disputes SET status = 'WITHDRAWN' WHERE id = ?`).run(dispute_id);

      if (dispute.proposed_credit_memo_id) {
        db.prepare(`UPDATE credit_memos SET status = 'VOIDED' WHERE id = ? AND status = 'DRAFT'`)
          .run(dispute.proposed_credit_memo_id);
      }

      recalculateInvoiceAmounts(dispute.invoice_id);
      updateInvoiceMatchStatus(dispute.invoice_id);
      updateInvoiceCollectionsStage(dispute.invoice_id, workspace.period_index);
      recalculateCustomerBalances(invoice.customer_id);

      if (dispute.reason === 'FRAUD') {
        db.prepare(`
          UPDATE customers SET last_fraud_dispute_closed_period = ? WHERE id = ?
        `).run(workspace.period_index, invoice.customer_id);
      }

      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const updatedDispute = db.prepare('SELECT * FROM disputes WHERE id = ?').get(dispute_id) as DisputeRow;
    const items = db.prepare('SELECT * FROM dispute_items WHERE dispute_id = ?').all(dispute_id) as DisputeItemRow[];

    res.json(formatDispute(updatedDispute, items));
  }
);

export default router;
