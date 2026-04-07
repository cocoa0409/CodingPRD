import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db, getNextDocumentNumber } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  InvoiceRow,
  InvoiceLineRow,
  CustomerRow,
  ContractRow,
  PurchaseOrderRow,
  PurchaseOrderLineRow,
  WorkspaceRow,
  DisputeRow,
  PaymentAllocationRow,
} from '../types';
import {
  updateInvoiceMatchStatus,
  updateInvoiceCollectionsStage,
  recalculateInvoiceAmounts,
  canAcceptInvoiceWithExceptions,
} from '../services/invoiceService';
import { recalculateCustomerBalances, updateCustomerStatus, hasInvoicesInCollections } from '../services/customerService';

const router = Router({ mergeParams: true });

function formatInvoice(invoice: InvoiceRow, lines: InvoiceLineRow[]) {
  return {
    invoice_id: invoice.id,
    workspace_id: invoice.workspace_id,
    customer_id: invoice.customer_id,
    contract_id: invoice.contract_id,
    purchase_order_id: invoice.purchase_order_id,
    external_invoice_ref: invoice.external_invoice_ref,
    document_number: invoice.document_number,
    status: invoice.status,
    type: invoice.type,
    invoice_total_cents: invoice.invoice_total_cents,
    amount_due_cents: invoice.amount_due_cents,
    amount_disputed_cents: invoice.amount_disputed_cents,
    amount_paid_cents: invoice.amount_paid_cents,
    amount_credited_cents: invoice.amount_credited_cents,
    amount_written_off_cents: invoice.amount_written_off_cents,
    collections_stage: invoice.collections_stage,
    match_status: invoice.match_status,
    issued_period_index: invoice.issued_period_index,
    delivered_period_index: invoice.delivered_period_index,
    accepted_period_index: invoice.accepted_period_index,
    due_period_index: invoice.due_period_index,
    is_final_invoice: !!invoice.is_final_invoice,

    reference_invoice_id: invoice.parent_invoice_id,
    parent_invoice_id: invoice.parent_invoice_id,
    lines: lines.map(l => ({
      invoice_line_id: l.id,
      purchase_order_line_id: l.purchase_order_line_id,
      description: l.description,
      quantity_units: l.quantity_units,
      unit_price_cents: l.unit_price_cents,
      line_total_cents: l.line_total_cents,
      credited_amount_cents: l.credited_amount_cents,
    })),
  };
}

router.post(
  '/',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const { contract_id, purchase_order_id, external_invoice_ref } = req.body;

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

    if (customer.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.CUSTOMER_CLOSED, 'Cannot create invoices for a closed customer');
    }

    if (!contract_id) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'contract_id is required');
    }

    const contract = db.prepare(`
      SELECT * FROM contracts WHERE id = ? AND workspace_id = ?
    `).get(contract_id, workspace_id) as ContractRow | undefined;

    if (!contract) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Contract not found', 404);
    }

    if (contract.customer_id !== customer_id) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Contract does not belong to this customer');
    }

    if (purchase_order_id) {
      const po = db.prepare(`
        SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
      `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

      if (!po) {
        throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
      }

      if (po.customer_id !== customer_id) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Purchase order does not belong to this customer');
      }
    }

    const invoiceId = uuidv4();

    db.prepare(`
      INSERT INTO invoices (
        id, workspace_id, customer_id, contract_id, purchase_order_id,
        external_invoice_ref, status, type, invoice_total_cents, amount_due_cents,
        collections_stage, match_status
      ) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', 'STANDARD', 0, 0, 'CURRENT', 'NOT_APPLICABLE')
    `).run(
      invoiceId,
      workspace_id,
      customer_id,
      contract_id,
      purchase_order_id || null,
      external_invoice_ref || null
    );

    const invoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoiceId) as InvoiceRow;
    const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoiceId) as InvoiceLineRow[];

    res.status(201).json(formatInvoice(invoice, lines));
  }
);

router.post(
  '/:invoice_id/lines',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;
    const { description, quantity_units, unit_price_cents, purchase_order_line_id } = req.body;

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    if (invoice.status !== 'DRAFT') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only add lines to DRAFT invoices');
    }

    if (!description || quantity_units === undefined || unit_price_cents === undefined) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'description, quantity_units, and unit_price_cents are required');
    }

    if (quantity_units <= 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'quantity_units must be positive');
    }

    if (unit_price_cents < 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'unit_price_cents must be non-negative');
    }

    if (purchase_order_line_id) {
      const poLine = db.prepare(`
        SELECT pol.*, po.id as po_id FROM purchase_order_lines pol
        JOIN purchase_orders po ON pol.purchase_order_id = po.id
        WHERE pol.id = ?
      `).get(purchase_order_line_id) as (PurchaseOrderLineRow & { po_id: string }) | undefined;

      if (!poLine) {
        throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order line not found', 404);
      }

      if (invoice.purchase_order_id && poLine.po_id !== invoice.purchase_order_id) {
        throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Purchase order line must belong to the invoice\'s purchase order');
      }
    }

    const lineId = uuidv4();
    const lineTotal = Math.round(quantity_units * unit_price_cents);

    db.prepare(`
      INSERT INTO invoice_lines (
        id, invoice_id, purchase_order_line_id, description,
        quantity_units, unit_price_cents, line_total_cents, credited_amount_cents
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    `).run(lineId, invoice_id, purchase_order_line_id || null, description, quantity_units, unit_price_cents, lineTotal);

    const line = db.prepare('SELECT * FROM invoice_lines WHERE id = ?').get(lineId) as InvoiceLineRow;

    res.status(201).json({
      invoice_line_id: line.id,
      invoice_id: line.invoice_id,
      purchase_order_line_id: line.purchase_order_line_id,
      description: line.description,
      quantity_units: line.quantity_units,
      unit_price_cents: line.unit_price_cents,
      line_total_cents: line.line_total_cents,
    });
  }
);

router.post(
  '/:invoice_id/finalize',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;
    const { override_hold = false, override_billing_cap = false, final_invoice = false } = req.body;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    if (invoice.status !== 'DRAFT') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only finalize DRAFT invoices');
    }

    const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(invoice.customer_id) as CustomerRow;
    const contract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(invoice.contract_id) as ContractRow;

    if (customer.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.CUSTOMER_CLOSED, 'Cannot finalize invoices for a closed customer');
    }

    const linesResult = db.prepare(`
      SELECT COALESCE(SUM(line_total_cents), 0) as total FROM invoice_lines WHERE invoice_id = ?
    `).get(invoice_id) as { total: number };

    const invoiceTotal = linesResult.total;

    if (invoiceTotal <= 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Invoice must have a positive total');
    }

    if (customer.status === 'CREDIT_HOLD' || hasInvoicesInCollections(customer.id)) {
      const canOverride = req.context.actorRole === 'SellerAdmin' &&
                         override_hold &&
                         invoiceTotal <= 1000000 &&
                         !hasInvoicesInCollections(customer.id);

      if (!canOverride) {
        throw new ApiError(ErrorCodes.CUSTOMER_ON_HOLD, 'Customer is on credit hold');
      }
    }

    const isFinalTrueUpCandidate =
      final_invoice &&
      req.context.actorRole === 'SellerAdmin' &&
      (contract.status === 'SUSPENDED' || contract.status === 'TERMINATED') &&
      invoiceTotal <= 200000 &&
      !invoice.purchase_order_id;

    if (contract.status !== 'ACTIVE' && !isFinalTrueUpCandidate) {
      throw new ApiError(ErrorCodes.CONTRACT_INACTIVE, 'Contract is not active');
    }

    if (!isFinalTrueUpCandidate) {
      if (contract.requires_po && !invoice.purchase_order_id) {
        throw new ApiError(ErrorCodes.PO_REQUIRED, 'Contract requires a purchase order');
      }

      if (invoice.purchase_order_id) {
        const po = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(invoice.purchase_order_id) as PurchaseOrderRow;
        if (po.status !== 'OPEN' && po.status !== 'ACKNOWLEDGED') {
          throw new ApiError(ErrorCodes.PO_NOT_OPEN, 'Purchase order is not open or acknowledged');
        }
      }
    }

    if (invoice.external_invoice_ref) {
      const duplicateRef = db.prepare(`
        SELECT 1 FROM invoices
        WHERE customer_id = ? AND external_invoice_ref = ?
        AND status NOT IN ('DRAFT', 'VOIDED') AND id != ?
        LIMIT 1
      `).get(invoice.customer_id, invoice.external_invoice_ref, invoice_id);

      if (duplicateRef) {
        throw new ApiError(ErrorCodes.DUPLICATE_EXTERNAL_REF, 'External invoice reference already exists');
      }
    }

    if (contract.billing_cap_cents_per_period) {
      const periodInvoicesTotal = db.prepare(`
        SELECT COALESCE(SUM(invoice_total_cents), 0) as total FROM invoices
        WHERE customer_id = ? AND contract_id = ? AND issued_period_index = ?
        AND status NOT IN ('DRAFT', 'VOIDED') AND id != ?
      `).get(invoice.customer_id, invoice.contract_id, workspace.period_index, invoice_id) as { total: number };

      const totalForPeriod = periodInvoicesTotal.total + invoiceTotal;

      if (totalForPeriod > contract.billing_cap_cents_per_period) {
        const canOverrideCap = req.context.actorRole === 'SellerAdmin' && override_billing_cap;
        if (!canOverrideCap) {
          throw new ApiError(ErrorCodes.BILLING_CAP_EXCEEDED, 'Billing cap exceeded for this period');
        }
      }
    }

    db.transaction(() => {
      const documentNumber = getNextDocumentNumber(workspace_id, 'INVOICE');

      if (isFinalTrueUpCandidate) {

        const updated = db.prepare(`
          UPDATE invoices SET
            status = 'FINALIZED',
            document_number = ?,
            invoice_total_cents = ?,
            amount_due_cents = ?,
            issued_period_index = ?,
            is_final_invoice = 1
          WHERE id = ?
            AND NOT EXISTS (
              SELECT 1 FROM invoices WHERE contract_id = ? AND is_final_invoice = 1
            )
        `).run(documentNumber, invoiceTotal, invoiceTotal, workspace.period_index, invoice_id, invoice.contract_id);

        if (updated.changes === 0) {
          throw new ApiError(ErrorCodes.CONTRACT_INACTIVE, 'Contract is not active');
        }
      } else {
        db.prepare(`
          UPDATE invoices SET
            status = 'FINALIZED',
            document_number = ?,
            invoice_total_cents = ?,
            amount_due_cents = ?,
            issued_period_index = ?,
            is_final_invoice = 0
          WHERE id = ?
        `).run(documentNumber, invoiceTotal, invoiceTotal, workspace.period_index, invoice_id);
      }

      const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];
      for (const line of lines) {
        if (line.purchase_order_line_id) {
          db.prepare(`
            UPDATE purchase_order_lines
            SET net_billed_units = net_billed_units + ?
            WHERE id = ?
          `).run(line.quantity_units, line.purchase_order_line_id);
        }
      }

      updateInvoiceMatchStatus(invoice_id);

      recalculateCustomerBalances(invoice.customer_id);
    })();

    const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
    const invoiceLines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

    res.json(formatInvoice(updatedInvoice, invoiceLines));
  }
);

router.post(
  '/:invoice_id/send',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    if (invoice.status !== 'FINALIZED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only send FINALIZED invoices');
    }

    const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(invoice.customer_id) as CustomerRow;

    if (customer.status === 'FROZEN') {
      throw new ApiError(ErrorCodes.CUSTOMER_FROZEN, 'Cannot send invoices to a frozen customer');
    }

    db.prepare(`
      UPDATE invoices SET status = 'SENT', delivered_period_index = ? WHERE id = ?
    `).run(workspace.period_index, invoice_id);

    const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
    const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

    res.json(formatInvoice(updatedInvoice, lines));
  }
);

router.post(
  '/:invoice_id/accept',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
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

    if (invoice.status !== 'SENT') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only accept SENT invoices');
    }

    updateInvoiceMatchStatus(invoice_id);
    const refreshedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;

    if (refreshedInvoice.match_status === 'EXCEPTION') {
      if (!canAcceptInvoiceWithExceptions(invoice_id)) {
        throw new ApiError(ErrorCodes.MATCH_EXCEPTION, 'Invoice has match exceptions not covered by active disputes');
      }
    }

    const contract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(invoice.contract_id) as ContractRow;
    const paymentTerms = contract?.payment_terms_periods || 2;

    db.prepare(`
      UPDATE invoices SET
        status = 'ACCEPTED',
        accepted_period_index = ?,
        due_period_index = ?
      WHERE id = ?
    `).run(workspace.period_index, workspace.period_index + paymentTerms, invoice_id);

    const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
    const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

    res.json(formatInvoice(updatedInvoice, lines));
  }
);

router.post(
  '/:invoice_id/void',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    if (invoice.status === 'DRAFT') {
      db.prepare('UPDATE invoices SET status = ? WHERE id = ?').run('VOIDED', invoice_id);
      const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
      const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];
      return res.json(formatInvoice(updatedInvoice, lines));
    }

    const activeDispute = db.prepare(`
      SELECT 1 FROM disputes
      WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
      LIMIT 1
    `).get(invoice_id);

    if (activeDispute) {
      throw new ApiError(ErrorCodes.INVOICE_HAS_DISPUTE, 'Invoice has active disputes');
    }

    const payments = db.prepare(`
      SELECT pa.*, p.status as payment_status FROM payment_allocations pa
      JOIN payments p ON pa.payment_id = p.id
      WHERE pa.invoice_id = ? AND p.status IN ('INITIATED', 'CLEARED')
    `).all(invoice_id) as (PaymentAllocationRow & { payment_status: string })[];

    if (payments.length > 0) {
      throw new ApiError(ErrorCodes.INVOICE_HAS_PAYMENTS, 'Invoice has payments allocated');
    }

    const booksClosedThrough = workspace.books_closed_through_period_index;
    if (booksClosedThrough !== null && invoice.issued_period_index !== null &&
        invoice.issued_period_index <= booksClosedThrough) {

      if (req.context.actorRole !== 'SellerAdmin') {
        throw new ApiError(ErrorCodes.BOOKS_CLOSED, 'Books are closed for this period');
      }

      const everCleared = db.prepare(`
        SELECT 1 FROM payment_allocations pa
        JOIN payments p ON pa.payment_id = p.id
        WHERE pa.invoice_id = ? AND (p.status = 'CLEARED' OR p.status = 'REVERSED')
        LIMIT 1
      `).get(invoice_id);

      if (everCleared) {
        throw new ApiError(ErrorCodes.BOOKS_CLOSED, 'Cannot void invoice with payment history in closed period');
      }
    }

    if (invoice.status !== 'FINALIZED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Invoice cannot be voided in its current status');
    }

    db.transaction(() => {

      const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];
      for (const line of lines) {
        if (line.purchase_order_line_id) {
          db.prepare(`
            UPDATE purchase_order_lines
            SET net_billed_units = net_billed_units - ?
            WHERE id = ?
          `).run(line.quantity_units, line.purchase_order_line_id);
        }
      }

      db.prepare(`
        UPDATE invoices SET
          status = 'VOIDED',
          amount_due_cents = 0,
          amount_disputed_cents = 0
        WHERE id = ?
      `).run(invoice_id);
      updateInvoiceCollectionsStage(invoice_id, workspace.period_index);
      recalculateCustomerBalances(invoice.customer_id);
      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
    const invoiceLines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

    res.json(formatInvoice(updatedInvoice, invoiceLines));
  }
);

router.post(
  '/:invoice_id/write_off',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, invoice_id } = req.params;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    const invoice = db.prepare(`
      SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
    `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

    if (!invoice) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
    }

    const activeDispute = db.prepare(`
      SELECT 1 FROM disputes
      WHERE invoice_id = ? AND status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
      LIMIT 1
    `).get(invoice_id);

    if (activeDispute) {
      throw new ApiError(ErrorCodes.INVOICE_HAS_DISPUTE, 'Invoice has active disputes');
    }

    if (invoice.status === 'CLOSED' || invoice.status === 'VOIDED') {
      throw new ApiError(ErrorCodes.WRITE_OFF_NOT_ALLOWED, 'Invoice is already closed or voided');
    }

    if (invoice.collections_stage !== 'COLLECTIONS') {
      throw new ApiError(ErrorCodes.WRITE_OFF_NOT_ALLOWED, 'Invoice must be in COLLECTIONS stage');
    }

    if (invoice.amount_due_cents > 20000) {
      throw new ApiError(ErrorCodes.WRITE_OFF_NOT_ALLOWED, 'Amount due exceeds write-off limit');
    }

    db.transaction(() => {
      db.prepare(`
        UPDATE invoices SET
          status = 'CLOSED',
          amount_written_off_cents = amount_due_cents,
          amount_due_cents = 0,
          amount_disputed_cents = 0
        WHERE id = ?
      `).run(invoice_id);

      updateInvoiceCollectionsStage(invoice_id, workspace.period_index);
      recalculateCustomerBalances(invoice.customer_id);
      updateCustomerStatus(invoice.customer_id, workspace.period_index);
    })();

    const updatedInvoice = db.prepare('SELECT * FROM invoices WHERE id = ?').get(invoice_id) as InvoiceRow;
    const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

    res.json(formatInvoice(updatedInvoice, lines));
  }
);

router.get('/:invoice_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, invoice_id } = req.params;

  const invoice = db.prepare(`
    SELECT * FROM invoices WHERE id = ? AND workspace_id = ?
  `).get(invoice_id, workspace_id) as InvoiceRow | undefined;

  if (!invoice) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Invoice not found', 404);
  }

  const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice_id) as InvoiceLineRow[];

  res.json(formatInvoice(invoice, lines));
});

router.get('/', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id } = req.params;
  const { customer_id, status, type } = req.query;

  let query = 'SELECT * FROM invoices WHERE workspace_id = ?';
  const params: any[] = [workspace_id];

  if (customer_id) {
    query += ' AND customer_id = ?';
    params.push(customer_id);
  }

  if (status) {
    query += ' AND status = ?';
    params.push(status);
  }

  if (type) {
    query += ' AND type = ?';
    params.push(type);
  }

  const invoices = db.prepare(query).all(...params) as InvoiceRow[];

  const result = invoices.map(invoice => {
    const lines = db.prepare('SELECT * FROM invoice_lines WHERE invoice_id = ?').all(invoice.id) as InvoiceLineRow[];
    return formatInvoice(invoice, lines);
  });

  res.json({ invoices: result });
});

export default router;
