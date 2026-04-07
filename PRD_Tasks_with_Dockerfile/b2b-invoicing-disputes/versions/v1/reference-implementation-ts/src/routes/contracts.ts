import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../db/schema';
import { authMiddleware, requireRoles } from '../middleware/auth';
import { idempotencyMiddleware } from '../middleware/idempotency';
import {
  ApiError,
  ErrorCodes,
  ContractRow,
  CustomerRow,
  WorkspaceRow,
} from '../types';

const router = Router({ mergeParams: true });

router.post(
  '/',
  authMiddleware,
  requireRoles('SellerAdmin', 'SellerAR'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, customer_id } = req.params;
    const {
      name,
      payment_terms_periods = 2,
      requires_po = false,
      billing_cap_cents_per_period,
    } = req.body;

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

    if (!name) {
      throw new ApiError(ErrorCodes.INVALID_REQUEST, 'name is required');
    }

    const id = uuidv4();
    db.prepare(`
      INSERT INTO contracts (
        id, workspace_id, customer_id, name, status,
        payment_terms_periods, requires_po, billing_cap_cents_per_period
      ) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?)
    `).run(
      id,
      workspace_id,
      customer_id,
      name,
      payment_terms_periods,
      requires_po ? 1 : 0,
      billing_cap_cents_per_period || null
    );

    const contract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(id) as ContractRow;

    res.status(201).json({
      contract_id: contract.id,
      workspace_id: contract.workspace_id,
      customer_id: contract.customer_id,
      name: contract.name,
      status: contract.status,
      payment_terms_periods: contract.payment_terms_periods,
      requires_po: !!contract.requires_po,
      billing_cap_cents_per_period: contract.billing_cap_cents_per_period,
    });
  }
);

router.get('/:contract_id', authMiddleware, (req: Request, res: Response) => {
  const { workspace_id, contract_id } = req.params;

  const contract = db.prepare(`
    SELECT * FROM contracts WHERE id = ? AND workspace_id = ?
  `).get(contract_id, workspace_id) as ContractRow | undefined;

  if (!contract) {
    throw new ApiError(ErrorCodes.NOT_FOUND, 'Contract not found', 404);
  }

  res.json({
    contract_id: contract.id,
    workspace_id: contract.workspace_id,
    customer_id: contract.customer_id,
    name: contract.name,
    status: contract.status,
    payment_terms_periods: contract.payment_terms_periods,
    requires_po: !!contract.requires_po,
    billing_cap_cents_per_period: contract.billing_cap_cents_per_period,
  });
});

router.post(
  '/:contract_id/activate',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, contract_id } = req.params;

    const contract = db.prepare(`
      SELECT * FROM contracts WHERE id = ? AND workspace_id = ?
    `).get(contract_id, workspace_id) as ContractRow | undefined;

    if (!contract) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Contract not found', 404);
    }

    if (contract.status === 'ACTIVE') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Contract is already active');
    }

    if (contract.status !== 'DRAFT') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only activate DRAFT contracts');
    }

    db.prepare('UPDATE contracts SET status = ? WHERE id = ?').run('ACTIVE', contract_id);

    const updatedContract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(contract_id) as ContractRow;

    res.json({
      contract_id: updatedContract.id,
      status: updatedContract.status,
    });
  }
);

router.post(
  '/:contract_id/suspend',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, contract_id } = req.params;

    const contract = db.prepare(`
      SELECT * FROM contracts WHERE id = ? AND workspace_id = ?
    `).get(contract_id, workspace_id) as ContractRow | undefined;

    if (!contract) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Contract not found', 404);
    }

    if (contract.status === 'SUSPENDED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Contract is already suspended');
    }

    if (contract.status !== 'ACTIVE') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only suspend ACTIVE contracts');
    }

    db.prepare('UPDATE contracts SET status = ? WHERE id = ?').run('SUSPENDED', contract_id);

    const updatedContract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(contract_id) as ContractRow;

    res.json({
      contract_id: updatedContract.id,
      status: updatedContract.status,
    });
  }
);

router.post(
  '/:contract_id/terminate',
  authMiddleware,
  requireRoles('SellerAdmin'),
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const { workspace_id, contract_id } = req.params;

    const contract = db.prepare(`
      SELECT * FROM contracts WHERE id = ? AND workspace_id = ?
    `).get(contract_id, workspace_id) as ContractRow | undefined;

    if (!contract) {
      throw new ApiError(ErrorCodes.NOT_FOUND, 'Contract not found', 404);
    }

    if (contract.status === 'TERMINATED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Contract is already terminated');
    }

    if (contract.status !== 'ACTIVE' && contract.status !== 'SUSPENDED') {
      throw new ApiError(ErrorCodes.INVALID_STATE_TRANSITION, 'Can only terminate ACTIVE or SUSPENDED contracts');
    }

    db.prepare('UPDATE contracts SET status = ? WHERE id = ?').run('TERMINATED', contract_id);

    const updatedContract = db.prepare('SELECT * FROM contracts WHERE id = ?').get(contract_id) as ContractRow;

    res.json({
      contract_id: updatedContract.id,
      status: updatedContract.status,
    });
  }
);

export default router;
