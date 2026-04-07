import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  CustomerRow,
  WorkspaceRow,
} from '../types';
import {
  updateCustomerStatus,
  recalculateCustomerBalances,
  canUnfreezeCustomer,
} from '../services/customerService';

const router = Router({ mergeParams: true });

router.post(
  '/',
  authMiddleware,
  requireRoles('SellerAdmin', 'SellerAR'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id } = req.params;
    const { display_name, external_customer_ref, credit_limit_cents = 0 } = req.body;

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow | undefined;
    if (!workspace) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Workspace not found', 404);
    }

    if (!display_name) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'display_name is required');
    }

    const id = uuidv4();
    db.prepare(`
      INSERT INTO customers (
        id, workspace_id, display_name, external_customer_ref, credit_limit_cents,
        status, balance_due_cents, unapplied_cash_cents, available_credit_cents
      ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', 0, 0, 0)
    `).run(id, workspace_id, display_name, external_customer_ref || null, credit_limit_cents);

    const customer = db.prepare('SELECT * FROM customers WHERE id = ?').get(id) as CustomerRow;

    res.status(201).json({
      customer_id: customer.id,
      workspace_id: customer.workspace_id,
      display_name: customer.display_name,
      external_customer_ref: customer.external_customer_ref,
      status: customer.status,
      credit_limit_cents: customer.credit_limit_cents,
      balance_due_cents: customer.balance_due_cents,
      unapplied_cash_cents: customer.unapplied_cash_cents,
      available_credit_cents: customer.available_credit_cents,
    });
  }
);

router.get('/:customer_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, customer_id } = req.params;

  const customer = db.prepare(`
    SELECT * FROM customers WHERE id = ? AND workspace_id = ?
  `).get(customer_id, workspace_id) as CustomerRow | undefined;

  if (!customer) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Customer not found', 404);
  }

  res.json({
    customer_id: customer.id,
    workspace_id: customer.workspace_id,
    display_name: customer.display_name,
    external_customer_ref: customer.external_customer_ref,
    status: customer.status,
    credit_limit_cents: customer.credit_limit_cents,
    balance_due_cents: customer.balance_due_cents,
    unapplied_cash_cents: customer.unapplied_cash_cents,
    available_credit_cents: customer.available_credit_cents,
  });
});

router.post(
  '/:customer_id/freeze',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const { reason = 'MANUAL' } = req.body;

    const customer = db.prepare(`
      SELECT * FROM customers WHERE id = ? AND workspace_id = ?
    `).get(customer_id, workspace_id) as CustomerRow | undefined;

    if (!customer) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Customer not found', 404);
    }

    if (customer.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Cannot freeze a closed customer');
    }

    if (customer.status === 'FROZEN') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Customer is already frozen');
    }

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;

    db.prepare(`
      UPDATE customers SET status = 'FROZEN', freeze_reason = ?, freeze_period_index = ?
      WHERE id = ?
    `).run(reason, workspace.period_index, customer_id);

    const updatedCustomer = db.prepare('SELECT * FROM customers WHERE id = ?').get(customer_id) as CustomerRow;

    res.json({
      customer_id: updatedCustomer.id,
      status: updatedCustomer.status,
      freeze_reason: updatedCustomer.freeze_reason,
    });
  }
);

router.post(
  '/:customer_id/unfreeze',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;

    const customer = db.prepare(`
      SELECT * FROM customers WHERE id = ? AND workspace_id = ?
    `).get(customer_id, workspace_id) as CustomerRow | undefined;

    if (!customer) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Customer not found', 404);
    }

    if (customer.status !== 'FROZEN') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Customer is not frozen');
    }

    const workspace = db.prepare('SELECT * FROM workspaces WHERE id = ?').get(workspace_id) as WorkspaceRow;

    if (!canUnfreezeCustomer(customer, workspace.period_index)) {
      throw new ApiError(
        ErrorCodes.CUSTOMER_STILL_FROZEN,
        'Customer cannot be unfrozen yet - freeze conditions are still active'
      );
    }

    const updatedCustomer = updateCustomerStatus(customer_id, workspace.period_index, { allowManualUnfreeze: true });

    res.json({
      customer_id: updatedCustomer.id,
      status: updatedCustomer.status,
    });
  }
);

router.post(
  '/:customer_id/close',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;

    const customer = db.prepare(`
      SELECT * FROM customers WHERE id = ? AND workspace_id = ?
    `).get(customer_id, workspace_id) as CustomerRow | undefined;

    if (!customer) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Customer not found', 404);
    }

    if (customer.status === 'CLOSED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Customer is already closed');
    }

    recalculateCustomerBalances(customer_id);
    const updatedCustomer = db.prepare('SELECT * FROM customers WHERE id = ?').get(customer_id) as CustomerRow;

    if (updatedCustomer.balance_due_cents !== 0 ||
        updatedCustomer.unapplied_cash_cents !== 0 ||
        updatedCustomer.available_credit_cents !== 0) {
      throw new ApiError(
        ErrorCodes.CUSTOMER_NOT_SETTLED,
        'Cannot close customer: ledger is not clean (has balance due, unapplied cash, or available credits)'
      );
    }

    const activeDisputes = db.prepare(`
      SELECT 1 FROM disputes d
      JOIN invoices i ON d.invoice_id = i.id
      WHERE i.customer_id = ? AND d.status IN ('OPEN', 'IN_REVIEW', 'PROPOSED', 'ESCALATED')
      LIMIT 1
    `).get(customer_id);

    if (activeDisputes) {
      throw new ApiError(
        ErrorCodes.CUSTOMER_NOT_SETTLED,
        'Cannot close customer: has active disputes'
      );
    }

    db.prepare(`
      UPDATE customers SET status = 'CLOSED' WHERE id = ?
    `).run(customer_id);

    const closedCustomer = db.prepare('SELECT * FROM customers WHERE id = ?').get(customer_id) as CustomerRow;

    res.json({
      customer_id: closedCustomer.id,
      status: closedCustomer.status,
    });
  }
);

export default router;
