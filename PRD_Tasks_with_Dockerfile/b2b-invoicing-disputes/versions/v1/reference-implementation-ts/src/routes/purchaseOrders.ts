import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import { updateInvoiceMatchStatus } from '../services/invoiceService';
import {
  ApiError,
  ErrorCodes,
  PurchaseOrderRow,
  PurchaseOrderLineRow,
  CustomerRow,
  WorkspaceRow,
  InvoiceRow,
} from '../types';

const router = Router({ mergeParams: true });

function formatPurchaseOrder(po: PurchaseOrderRow, lines: PurchaseOrderLineRow[]) {
  return {
    purchase_order_id: po.id,
    workspace_id: po.workspace_id,
    customer_id: po.customer_id,
    po_number: po.po_number,
    status: po.status,
    lines: lines.map(l => ({
      purchase_order_line_id: l.id,
      description: l.description,
      ordered_units: l.ordered_units,
      unit_price_cents: l.unit_price_cents,
      is_service: !!l.is_service,
      received_units: l.received_units,
      net_billed_units: l.net_billed_units,
    })),
  };
}

router.post(
  '/',
  authMiddleware,
  requireRoles('BuyerAP', 'SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const { po_number, lines = [] } = req.body;

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

    if (!po_number) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'po_number is required');
    }

    const existingPO = db.prepare(`
      SELECT 1 FROM purchase_orders
      WHERE customer_id = ? AND po_number = ? AND status IN ('OPEN', 'ACKNOWLEDGED')
    `).get(customer_id, po_number);

    if (existingPO) {
      throw new ApiError(ErrorCodes.DUPLICATE_PO_NUMBER, 'PO number already in use for this customer');
    }

    if (!lines || lines.length === 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'At least one line is required');
    }

    const poId = uuidv4();

    db.transaction(() => {
      db.prepare(`
        INSERT INTO purchase_orders (id, workspace_id, customer_id, po_number, status)
        VALUES (?, ?, ?, ?, 'OPEN')
      `).run(poId, workspace_id, customer_id, po_number);

      for (const line of lines) {
        if (!line.description || line.ordered_units === undefined || line.unit_price_cents === undefined) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each line must have description, ordered_units, and unit_price_cents');
        }

        if (line.ordered_units <= 0 || line.unit_price_cents < 0) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'ordered_units must be positive and unit_price_cents must be non-negative');
        }

        const lineId = uuidv4();
        db.prepare(`
          INSERT INTO purchase_order_lines (
            id, purchase_order_id, description, ordered_units, unit_price_cents,
            is_service, received_units, net_billed_units
          ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        `).run(
          lineId,
          poId,
          line.description,
          line.ordered_units,
          line.unit_price_cents,
          line.is_service ? 1 : 0
        );
      }
    })();

    const po = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(poId) as PurchaseOrderRow;
    const poLines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(poId) as PurchaseOrderLineRow[];

    res.status(201).json(formatPurchaseOrder(po, poLines));
  }
);

router.get('/:purchase_order_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, purchase_order_id } = req.params;

  const po = db.prepare(`
    SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
  `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

  if (!po) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
  }

  const lines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(purchase_order_id) as PurchaseOrderLineRow[];

  res.json(formatPurchaseOrder(po, lines));
});

router.post(
  '/:purchase_order_id/acknowledge',
  authMiddleware,
  requireRoles('SellerAR', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, purchase_order_id } = req.params;

    const po = db.prepare(`
      SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
    `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

    if (!po) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
    }

    if (po.status !== 'OPEN') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only acknowledge OPEN purchase orders');
    }

    db.prepare('UPDATE purchase_orders SET status = ? WHERE id = ?').run('ACKNOWLEDGED', purchase_order_id);

    const updatedPO = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(purchase_order_id) as PurchaseOrderRow;
    const lines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(purchase_order_id) as PurchaseOrderLineRow[];

    res.json(formatPurchaseOrder(updatedPO, lines));
  }
);

router.post(
  '/:purchase_order_id/record_receipt',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, purchase_order_id } = req.params;
    const { items = [] } = req.body;

    const po = db.prepare(`
      SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
    `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

    if (!po) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
    }

    if (po.status !== 'OPEN' && po.status !== 'ACKNOWLEDGED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only record receipts for OPEN or ACKNOWLEDGED purchase orders');
    }

    if (!items || items.length === 0) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'At least one item is required');
    }

    db.transaction(() => {
      for (const item of items) {
        if (!item.purchase_order_line_id || item.received_units === undefined) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'Each item must have purchase_order_line_id and received_units');
        }

        const line = db.prepare(`
          SELECT * FROM purchase_order_lines WHERE id = ? AND purchase_order_id = ?
        `).get(item.purchase_order_line_id, purchase_order_id) as PurchaseOrderLineRow | undefined;

        if (!line) {
          throw new ApiError(ErrorCodes.NOT_FOUND, `Purchase order line ${item.purchase_order_line_id} not found`, 404);
        }

        const receivedDelta = Number(item.received_units);
        if (!Number.isFinite(receivedDelta) || receivedDelta < 0) {
          throw new ApiError(ErrorCodes.INVALID_REQUEST, 'received_units must be a non-negative number');
        }

        if (receivedDelta > 0) {
          const maxAllowed = line.ordered_units * 1.01;
          const update = db.prepare(`
            UPDATE purchase_order_lines
            SET received_units = received_units + ?
            WHERE id = ? AND purchase_order_id = ? AND received_units + ? <= ?
          `).run(receivedDelta, item.purchase_order_line_id, purchase_order_id, receivedDelta, maxAllowed);

          if (update.changes === 0) {
            throw new ApiError(
              ErrorCodes.RECEIPT_EXCEEDS_TOLERANCE,
              `Receipt exceeds 1% tolerance for line ${item.purchase_order_line_id}`
            );
          }
        }

        const affectedInvoices = db.prepare(`
          SELECT DISTINCT il.invoice_id as id
          FROM invoice_lines il
          JOIN invoices i ON il.invoice_id = i.id
          WHERE il.purchase_order_line_id = ?
          AND i.status NOT IN ('DRAFT', 'VOIDED', 'CLOSED')
        `).all(item.purchase_order_line_id) as { id: string }[];
        for (const inv of affectedInvoices) {
          updateInvoiceMatchStatus(inv.id);
        }
      }
    })();

    const updatedPO = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(purchase_order_id) as PurchaseOrderRow;
    const lines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(purchase_order_id) as PurchaseOrderLineRow[];

    res.json(formatPurchaseOrder(updatedPO, lines));
  }
);

router.post(
  '/:purchase_order_id/cancel',
  authMiddleware,
  requireRoles('BuyerAP'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, purchase_order_id } = req.params;

    const po = db.prepare(`
      SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
    `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

    if (!po) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
    }

    const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(po.customer_id) as CustomerRow;

    if (customer.status === 'FROZEN') {
      throw new ApiError(ErrorCodes.CUSTOMER_FROZEN, 'Customer is frozen');
    }

    if (po.status === 'CANCELLED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Purchase order is already cancelled');
    }

    if (po.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Cannot cancel a closed purchase order');
    }

    const invoiceWithPO = db.prepare(`
      SELECT 1 FROM invoices
      WHERE purchase_order_id = ? AND status != 'DRAFT'
      LIMIT 1
    `).get(purchase_order_id);

    if (invoiceWithPO) {
      throw new ApiError(ErrorCodes.PO_HAS_INVOICES, 'Cannot cancel a purchase order with finalized invoices');
    }

    db.prepare('UPDATE purchase_orders SET status = ? WHERE id = ?').run('CANCELLED', purchase_order_id);

    const updatedPO = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(purchase_order_id) as PurchaseOrderRow;
    const lines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(purchase_order_id) as PurchaseOrderLineRow[];

    res.json(formatPurchaseOrder(updatedPO, lines));
  }
);

router.post(
  '/:purchase_order_id/close',
  authMiddleware,
  requireRoles('BuyerAP', 'SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, purchase_order_id } = req.params;

    const po = db.prepare(`
      SELECT * FROM purchase_orders WHERE id = ? AND workspace_id = ?
    `).get(purchase_order_id, workspace_id) as PurchaseOrderRow | undefined;

    if (!po) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Purchase order not found', 404);
    }

    if (po.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Purchase order is already closed');
    }

    if (po.status === 'CANCELLED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Cannot close a cancelled purchase order');
    }

    db.prepare('UPDATE purchase_orders SET status = ? WHERE id = ?').run('CLOSED', purchase_order_id);

    const updatedPO = db.prepare('SELECT * FROM purchase_orders WHERE id = ?').get(purchase_order_id) as PurchaseOrderRow;
    const lines = db.prepare('SELECT * FROM purchase_order_lines WHERE purchase_order_id = ?').all(purchase_order_id) as PurchaseOrderLineRow[];

    res.json(formatPurchaseOrder(updatedPO, lines));
  }
);

export default router;
