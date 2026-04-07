import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';
import crypto from 'crypto';

const app = express();
app.use(express.json());

type Role = 'ORGANIZER' | 'SELLER' | 'MANAGER' | 'GATE' | 'AUDITOR';
type Posture = 'OPEN' | 'REVIEW' | 'HALT';
type EventStatus = 'DRAFT' | 'ONSALE' | 'PAUSED' | 'CLOSED' | 'CANCELLED';
type PoolKind = 'STANDARD' | 'PREMIUM' | 'BOX';
type RefundPolicy = 'REFUNDABLE' | 'CREDIT_ONLY' | 'FINAL_SALE';
type TransferPolicy = 'OPEN' | 'ONCE' | 'NONE';
type OrderStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVAL_REQUIRED' | 'APPROVED' | 'PAID' | 'CANCELLED' | 'REFUNDED' | 'CREDITED' | 'MIXED';
type AdmissionState = 'ACTIVE' | 'SCANNED' | 'VOIDED';
type RemedyReason = 'CUSTOMER_REQUEST' | 'FRAUD' | 'EVENT_CANCELLED';

interface Workspace {
  id: string;
  name: string;
  settlement_currency: string;
  version: string;
}

interface Event {
  id: string;
  workspace_id: string;
  title: string;
  starts_at_local: string;
  max_tickets_per_actor: number;
  status: EventStatus;
  version: string;
}

interface Pool {
  id: string;
  event_id: string;
  workspace_id: string;
  label: string;
  kind: PoolKind;
  price_cents: number;
  currency: string;
  capacity_total: number;
  holdback_qty: number;
  refund_policy: RefundPolicy;
  transfer_policy: TransferPolicy;
  pool_holdings_limit: number | null;
  version: string;
}

interface OrderLine {
  pool_id: string;
  quantity: number;
  unit_price_cents: number;
}

interface Order {
  id: string;
  workspace_id: string;
  event_id: string;
  buyer_actor_id: string;
  status: OrderStatus;
  lines: OrderLine[];
  currency: string;
  total_cents: number;
  admission_ids: string[];
  version: string;
}

interface Admission {
  id: string;
  workspace_id: string;
  event_id: string;
  pool_id: string;
  order_id: string;
  holder_actor_id: string;
  transfer_count: number;
  state: AdmissionState;
  scanned_by_actor_id: string | null;
  version: string;
}

interface IdempotencyRecord {
  payload_hash: string;
  response: any;
  status_code: number;
}

const workspaces: Map<string, Workspace> = new Map();
const events: Map<string, Event> = new Map();
const pools: Map<string, Pool> = new Map();
const orders: Map<string, Order> = new Map();
const admissions: Map<string, Admission> = new Map();
const idempotencyStore: Map<string, IdempotencyRecord> = new Map();

function newVersion(): string {
  return uuidv4();
}

function hashPayload(payload: any): string {
  return crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex');
}

function errorResponse(code: string, message: string) {
  return { error: { code, message } };
}

function ensureRoleAllowed(req: AuthRequest, res: Response, allowedRoles: Role[]): boolean {
  if (!req.role || !allowedRoles.includes(req.role)) {
    res.status(403).json(errorResponse('ERR_ROLE_FORBIDDEN', `Role ${req.role} not allowed for this operation`));
    return false;
  }
  return true;
}

function requireIfMatch(req: Request, res: Response): string | null {
  const ifMatch = req.headers['if-match'] as string | undefined;
  if (!ifMatch) {
    res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
    return null;
  }
  return ifMatch;
}

function getEffectiveOrderStatus(order: Order): OrderStatus {
  if (order.status === 'SUBMITTED') {
    const posture = calculatePosture(order.workspace_id);
    if (posture === 'REVIEW') return 'APPROVAL_REQUIRED';
  }
  return order.status;
}

function getPoolQuantities(pool: Pool): { quantity_held: number; quantity_sold: number; quantity_available: number; is_overallocated: boolean } {
  let quantity_held = 0;
  let quantity_sold = 0;

  for (const order of orders.values()) {
    if (order.workspace_id !== pool.workspace_id) continue;

    for (const line of order.lines) {
      if (line.pool_id !== pool.id) continue;

      if (['SUBMITTED', 'APPROVAL_REQUIRED', 'APPROVED'].includes(order.status)) {
        quantity_held += line.quantity;
      } else if (['PAID', 'REFUNDED', 'CREDITED', 'MIXED'].includes(order.status)) {

        const activeAdmissions = Array.from(admissions.values()).filter(
          a => a.order_id === order.id && a.pool_id === pool.id && a.state !== 'VOIDED'
        ).length;
        quantity_sold += activeAdmissions;
      }
    }
  }

  const sellable_capacity = pool.capacity_total - pool.holdback_qty;
  const quantity_available = Math.max(0, sellable_capacity - quantity_sold - quantity_held);
  const is_overallocated = (quantity_sold + quantity_held) > sellable_capacity;

  return { quantity_held, quantity_sold, quantity_available, is_overallocated };
}

function calculatePosture(workspace_id: string): Posture {

  for (const event of events.values()) {
    if (event.workspace_id !== workspace_id) continue;
    if (event.status !== 'CANCELLED') continue;

    for (const order of orders.values()) {
      if (order.event_id === event.id && order.status === 'PAID') {
        return 'HALT';
      }
    }
  }

  for (const event of events.values()) {
    if (event.workspace_id !== workspace_id) continue;
    if (event.status === 'PAUSED') return 'REVIEW';
  }

  for (const pool of pools.values()) {
    if (pool.workspace_id !== workspace_id) continue;
    const { is_overallocated } = getPoolQuantities(pool);
    if (is_overallocated) return 'REVIEW';
  }

  for (const order of orders.values()) {
    if (order.workspace_id !== workspace_id) continue;
    if (order.status === 'APPROVAL_REQUIRED') return 'REVIEW';
  }

  return 'OPEN';
}

function getActorHoldings(actor_id: string, event_id: string): number {
  let count = 0;
  for (const admission of admissions.values()) {
    if (admission.event_id === event_id &&
        admission.holder_actor_id === actor_id &&
        admission.state !== 'VOIDED') {
      count++;
    }
  }
  return count;
}

function orderNeedsApproval(order: Order, workspace_id: string): boolean {
  if (order.total_cents >= 100000) return true;

  for (const line of order.lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) continue;
    if (pool.kind === 'PREMIUM' || pool.kind === 'BOX') return true;
    if (line.unit_price_cents !== pool.price_cents) return true;
  }

  return false;
}

interface AuthRequest extends Request {
  actorId?: string;
  role?: Role;
}

function authMiddleware(req: AuthRequest, res: Response, next: NextFunction) {
  const actorId = req.headers['x-actor-id'] as string;
  const role = req.headers['x-role'] as Role;

  if (!actorId || !role) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required headers X-Actor-Id and X-Role'));
  }

  const validRoles: Role[] = ['ORGANIZER', 'SELLER', 'MANAGER', 'GATE', 'AUDITOR'];
  if (!validRoles.includes(role)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid role'));
  }

  req.actorId = actorId;
  req.role = role;
  next();
}

function idempotencyMiddleware(req: AuthRequest, res: Response, next: NextFunction) {
  if (req.method !== 'POST') return next();

  const idempotencyKey = req.headers['idempotency-key'] as string;
  if (!idempotencyKey) {
    return res.status(400).json(errorResponse('ERR_MISSING_IDEMPOTENCY_KEY', 'Idempotency-Key header is required for POST requests'));
  }

  const existing = idempotencyStore.get(idempotencyKey);
  if (existing) {
    const currentHash = hashPayload(req.body);
    if (existing.payload_hash !== currentHash) {
      return res.status(409).json(errorResponse('ERR_IDEMPOTENCY_REPLAY_MISMATCH', 'Idempotency key reused with different payload'));
    }
    return res.status(existing.status_code).json(existing.response);
  }

  const originalJson = res.json.bind(res);
  res.json = (body: any) => {
    idempotencyStore.set(idempotencyKey, {
      payload_hash: hashPayload(req.body),
      response: body,
      status_code: res.statusCode
    });
    return originalJson(body);
  };

  next();
}

app.use(authMiddleware);
app.use(idempotencyMiddleware);

app.post('/workspaces', (req: AuthRequest, res: Response) => {
  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  const { name, settlement_currency } = req.body;

  if (!name || !settlement_currency) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'name and settlement_currency are required'));
  }

  const workspace: Workspace = {
    id: uuidv4(),
    name,
    settlement_currency,
    version: newVersion()
  };

  workspaces.set(workspace.id, workspace);

  const posture = calculatePosture(workspace.id);
  return res.status(201).json({ ...workspace, posture });
});

app.get('/workspaces/:workspace_id', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const posture = calculatePosture(workspace.id);
  return res.status(200).json({ ...workspace, posture });
});

app.post('/workspaces/:workspace_id/events', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  const { title, starts_at_local, max_tickets_per_actor } = req.body;

  if (!title || !starts_at_local || max_tickets_per_actor === undefined) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'title, starts_at_local, and max_tickets_per_actor are required'));
  }

  const event: Event = {
    id: uuidv4(),
    workspace_id: workspace.id,
    title,
    starts_at_local,
    max_tickets_per_actor,
    status: 'DRAFT',
    version: newVersion()
  };

  events.set(event.id, event);
  return res.status(201).json(event);
});

app.get('/workspaces/:workspace_id/events/:event_id', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  return res.status(200).json(event);
});

function eventStateTransition(req: AuthRequest, res: Response, targetStatus: EventStatus, allowedFrom: EventStatus[]) {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  if (ifMatch !== event.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (!allowedFrom.includes(event.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', `Cannot transition from ${event.status} to ${targetStatus}`));
  }

  event.status = targetStatus;
  event.version = newVersion();
  return res.status(200).json(event);
}

app.post('/workspaces/:workspace_id/events/:event_id/on_sale', (req: AuthRequest, res: Response) => {
  return eventStateTransition(req, res, 'ONSALE', ['DRAFT', 'PAUSED']);
});

app.post('/workspaces/:workspace_id/events/:event_id/pause', (req: AuthRequest, res: Response) => {
  return eventStateTransition(req, res, 'PAUSED', ['ONSALE']);
});

app.post('/workspaces/:workspace_id/events/:event_id/close', (req: AuthRequest, res: Response) => {
  return eventStateTransition(req, res, 'CLOSED', ['ONSALE', 'PAUSED']);
});

app.post('/workspaces/:workspace_id/events/:event_id/cancel', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  if (ifMatch !== event.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (event.status === 'CANCELLED') {
    return res.status(200).json(event);
  }

  for (const order of orders.values()) {
    if (order.event_id === event.id && !['PAID', 'REFUNDED', 'CREDITED', 'MIXED', 'CANCELLED'].includes(order.status)) {
      order.status = 'CANCELLED';
      order.version = newVersion();
    }
  }

  event.status = 'CANCELLED';
  event.version = newVersion();
  return res.status(200).json(event);
});

app.post('/workspaces/:workspace_id/events/:event_id/pools', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  const { label, kind, price_cents, currency, capacity_total, holdback_qty, refund_policy, transfer_policy, pool_holdings_limit } = req.body;

  if (!label || !kind || price_cents === undefined || !currency || capacity_total === undefined || holdback_qty === undefined || !refund_policy || !transfer_policy) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Missing required pool fields'));
  }

  if (currency !== workspace.settlement_currency) {
    return res.status(400).json(errorResponse('ERR_CURRENCY_MISMATCH', 'Pool currency must match workspace settlement_currency'));
  }

  const validKinds: PoolKind[] = ['STANDARD', 'PREMIUM', 'BOX'];
  if (!validKinds.includes(kind)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid pool kind'));
  }

  const validRefundPolicies: RefundPolicy[] = ['REFUNDABLE', 'CREDIT_ONLY', 'FINAL_SALE'];
  if (!validRefundPolicies.includes(refund_policy)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid refund_policy'));
  }

  const validTransferPolicies: TransferPolicy[] = ['OPEN', 'ONCE', 'NONE'];
  if (!validTransferPolicies.includes(transfer_policy)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid transfer_policy'));
  }

  const pool: Pool = {
    id: uuidv4(),
    event_id: event.id,
    workspace_id: workspace.id,
    label,
    kind,
    price_cents,
    currency,
    capacity_total,
    holdback_qty,
    refund_policy,
    transfer_policy,
    pool_holdings_limit: pool_holdings_limit ?? null,
    version: newVersion()
  };

  pools.set(pool.id, pool);

  const quantities = getPoolQuantities(pool);
  return res.status(201).json({ ...pool, ...quantities });
});

app.get('/workspaces/:workspace_id/events/:event_id/pools/:pool_id', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  const pool = pools.get(req.params.pool_id);
  if (!pool || pool.event_id !== event.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pool not found'));
  }

  const quantities = getPoolQuantities(pool);
  return res.status(200).json({ ...pool, ...quantities });
});

app.post('/workspaces/:workspace_id/events/:event_id/pools/:pool_id/adjust', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const event = events.get(req.params.event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  const pool = pools.get(req.params.pool_id);
  if (!pool || pool.event_id !== event.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pool not found'));
  }

  if (!ensureRoleAllowed(req, res, ['ORGANIZER'])) return;

  if (ifMatch !== pool.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  const { capacity_delta, holdback_delta, new_price_cents, note } = req.body;

  if (new_price_cents !== undefined && event.status === 'ONSALE') {
    return res.status(409).json(errorResponse('ERR_POOL_PRICE_CHANGE_BLOCKED', 'Price changes not allowed while event is ONSALE'));
  }

  const quantities = getPoolQuantities(pool);

  if (capacity_delta !== undefined) {
    const newCapacity = pool.capacity_total + capacity_delta;
    if (newCapacity < quantities.quantity_sold) {
      return res.status(409).json(errorResponse('ERR_CAPACITY_FLOOR', 'Cannot reduce capacity below sold tickets'));
    }
    pool.capacity_total = newCapacity;
  }

  if (holdback_delta !== undefined) {
    const newHoldback = pool.holdback_qty + holdback_delta;
    if (newHoldback < 0) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Holdback cannot go below zero'));
    }
    pool.holdback_qty = newHoldback;
  }

  if (new_price_cents !== undefined) {
    pool.price_cents = new_price_cents;
  }

  pool.version = newVersion();

  const updatedQuantities = getPoolQuantities(pool);
  return res.status(200).json({ ...pool, ...updatedQuantities });
});

app.post('/workspaces/:workspace_id/orders', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const { event_id } = req.body;
  if (!event_id) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'event_id is required'));
  }

  const event = events.get(event_id);
  if (!event || event.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  const order: Order = {
    id: uuidv4(),
    workspace_id: workspace.id,
    event_id: event.id,
    buyer_actor_id: req.actorId!,
    status: 'DRAFT',
    lines: [],
    currency: workspace.settlement_currency,
    total_cents: 0,
    admission_ids: [],
    version: newVersion()
  };

  orders.set(order.id, order);
  return res.status(201).json(order);
});

app.get('/workspaces/:workspace_id/orders/:order_id', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  const effectiveStatus = getEffectiveOrderStatus(order);
  if (effectiveStatus === order.status) return res.status(200).json(order);
  return res.status(200).json({ ...order, status: effectiveStatus });
});

app.put('/workspaces/:workspace_id/orders/:order_id/lines', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (order.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Can only update lines on DRAFT orders'));
  }

  const { lines } = req.body;
  if (!Array.isArray(lines)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'lines must be an array'));
  }

  const poolIds = new Set<string>();
  for (const line of lines) {
    if (poolIds.has(line.pool_id)) {
      return res.status(400).json(errorResponse('ERR_LINE_DUPLICATE', 'Same pool_id cannot appear twice in one order'));
    }
    poolIds.add(line.pool_id);
  }

  const event = events.get(order.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  const newLines: OrderLine[] = [];
  let total_cents = 0;

  for (const line of lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) {
      return res.status(404).json(errorResponse('ERR_NOT_FOUND', `Pool ${line.pool_id} not found`));
    }
    if (pool.event_id !== order.event_id) {
      return res.status(400).json(errorResponse('ERR_LINE_EVENT_MISMATCH', 'All pools must belong to the order event'));
    }

    const unit_price = line.unit_price_cents !== undefined ? line.unit_price_cents : pool.price_cents;
    newLines.push({
      pool_id: line.pool_id,
      quantity: line.quantity,
      unit_price_cents: unit_price
    });
    total_cents += unit_price * line.quantity;
  }

  order.lines = newLines;
  order.total_cents = total_cents;
  order.version = newVersion();

  return res.status(200).json(order);
});

app.post('/workspaces/:workspace_id/orders/:order_id/submit', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (order.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Can only submit DRAFT orders'));
  }

  if (order.lines.length === 0) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Cannot submit order with empty lines'));
  }

  const event = events.get(order.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (event.status !== 'ONSALE') {
    return res.status(409).json(errorResponse('ERR_EVENT_NOT_SELLING', 'Event is not on sale'));
  }

  for (const line of order.lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) continue;

    const quantities = getPoolQuantities(pool);
    if (quantities.is_overallocated) {
      return res.status(409).json(errorResponse('ERR_POOL_OVERALLOCATED', `Pool ${pool.id} is overallocated`));
    }
    if (quantities.quantity_available < line.quantity) {
      return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', `Not enough availability in pool ${pool.id}`));
    }
  }

  if (orderNeedsApproval(order, workspace.id)) {
    order.status = 'APPROVAL_REQUIRED';
  } else {
    order.status = 'SUBMITTED';
  }

  order.version = newVersion();
  return res.status(200).json(order);
});

app.post('/workspaces/:workspace_id/orders/:order_id/approve', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['MANAGER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  const effectiveStatus = getEffectiveOrderStatus(order);
  if (effectiveStatus !== 'APPROVAL_REQUIRED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order is not in APPROVAL_REQUIRED status'));
  }

  order.status = 'APPROVED';
  order.version = newVersion();
  return res.status(200).json(order);
});

app.post('/workspaces/:workspace_id/orders/:order_id/pay', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

	  if (['PAID', 'CANCELLED', 'REFUNDED', 'CREDITED', 'MIXED'].includes(order.status)) {
	    return res.status(409).json(errorResponse('ERR_INVALID_STATE', `Cannot pay order in status ${order.status}`));
	  }
	  if (order.status === 'DRAFT') {
	    return res.status(409).json(errorResponse('ERR_ORDER_NOT_READY', 'Order is not ready for payment'));
	  }

	  const effectiveStatus: OrderStatus =
	    order.status === 'SUBMITTED' && posture === 'REVIEW' ? 'APPROVAL_REQUIRED' : order.status;

  const event = events.get(order.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (event.status !== 'ONSALE') {
    return res.status(409).json(errorResponse('ERR_EVENT_NOT_SELLING', 'Event is not on sale'));
  }

  for (const line of order.lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) continue;

    const quantities = getPoolQuantities(pool);
    if (quantities.is_overallocated) {
      return res.status(409).json(errorResponse('ERR_POOL_OVERALLOCATED', `Pool ${pool.id} is overallocated`));
    }
  }

	  if (effectiveStatus === 'APPROVAL_REQUIRED') {
	    return res.status(409).json(errorResponse('ERR_APPROVAL_REQUIRED', 'Order requires approval before payment'));
	  }

  if (order.status !== 'SUBMITTED' && order.status !== 'APPROVED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', `Cannot pay order in status ${order.status}`));
  }

  let totalTickets = 0;
  for (const line of order.lines) {
    totalTickets += line.quantity;
  }

  const currentHoldings = getActorHoldings(order.buyer_actor_id, order.event_id);
  if (currentHoldings + totalTickets > event.max_tickets_per_actor) {
    return res.status(409).json(errorResponse('ERR_HOLDINGS_LIMIT_EXCEEDED', 'Would exceed max tickets per actor for event'));
  }

  for (const line of order.lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) continue;

    if (pool.pool_holdings_limit !== null) {
      let poolHoldings = 0;
      for (const admission of admissions.values()) {
        if (admission.pool_id === pool.id &&
            admission.holder_actor_id === order.buyer_actor_id &&
            admission.state !== 'VOIDED') {
          poolHoldings++;
        }
      }
      if (poolHoldings + line.quantity > pool.pool_holdings_limit) {
        return res.status(409).json(errorResponse('ERR_HOLDINGS_LIMIT_EXCEEDED', `Would exceed pool holdings limit for pool ${pool.id}`));
      }
    }
  }

  const admission_ids: string[] = [];
  for (const line of order.lines) {
    for (let i = 0; i < line.quantity; i++) {
      const admission: Admission = {
        id: uuidv4(),
        workspace_id: workspace.id,
        event_id: order.event_id,
        pool_id: line.pool_id,
        order_id: order.id,
        holder_actor_id: order.buyer_actor_id,
        transfer_count: 0,
        state: 'ACTIVE',
        scanned_by_actor_id: null,
        version: newVersion()
      };
      admissions.set(admission.id, admission);
      admission_ids.push(admission.id);
    }
  }

  order.status = 'PAID';
  order.admission_ids = admission_ids;
  order.version = newVersion();

  return res.status(200).json(order);
});

app.post('/workspaces/:workspace_id/orders/:order_id/cancel', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER'])) return;

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (!['DRAFT', 'SUBMITTED', 'APPROVAL_REQUIRED', 'APPROVED'].includes(order.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Can only cancel unpaid orders'));
  }

  order.status = 'CANCELLED';
  order.version = newVersion();

  return res.status(200).json(order);
});

app.post('/workspaces/:workspace_id/orders/:order_id/refund', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const order = orders.get(req.params.order_id);
  if (!order || order.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!ensureRoleAllowed(req, res, ['MANAGER'])) return;

  if (ifMatch !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (order.status !== 'PAID') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Can only refund PAID orders'));
  }

  const { reason } = req.body;
  if (!reason) {
    return res.status(400).json(errorResponse('ERR_REMEDY_REASON_REQUIRED', 'reason is required'));
  }

  const validReasons: RemedyReason[] = ['CUSTOMER_REQUEST', 'FRAUD', 'EVENT_CANCELLED'];
  if (!validReasons.includes(reason)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid reason'));
  }

  const event = events.get(order.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (event.status === 'CANCELLED' && reason !== 'EVENT_CANCELLED') {
    return res.status(400).json(errorResponse('ERR_REMEDY_REASON_REQUIRED', 'Refund reason must be EVENT_CANCELLED for cancelled events'));
  }

  if (event.status === 'CLOSED' && reason === 'CUSTOMER_REQUEST') {
    return res.status(409).json(errorResponse('ERR_REFUND_NOT_ALLOWED', 'Customer request refunds not allowed after event is closed'));
  }

  for (const admissionId of order.admission_ids) {
    const admission = admissions.get(admissionId);
    if (admission && admission.state === 'SCANNED') {
      return res.status(409).json(errorResponse('ERR_ADMISSION_ALREADY_SCANNED', 'Cannot refund orders with scanned tickets'));
    }
  }

  let hasRefund = false;
  let hasCredit = false;

  for (const line of order.lines) {
    const pool = pools.get(line.pool_id);
    if (!pool) continue;

    if (reason === 'EVENT_CANCELLED') {

      if (pool.refund_policy === 'REFUNDABLE') {
        hasRefund = true;
      } else if (pool.refund_policy === 'CREDIT_ONLY') {
        hasCredit = true;
      } else if (pool.refund_policy === 'FINAL_SALE') {

        hasCredit = true;
      }
    } else {

      if (pool.refund_policy === 'REFUNDABLE') {
        hasRefund = true;
      } else if (pool.refund_policy === 'CREDIT_ONLY') {
        hasCredit = true;
      } else if (pool.refund_policy === 'FINAL_SALE') {
        return res.status(409).json(errorResponse('ERR_REFUND_NOT_ALLOWED', `Pool ${pool.id} has FINAL_SALE policy`));
      }
    }
  }

  for (const admissionId of order.admission_ids) {
    const admission = admissions.get(admissionId);
    if (admission) {
      admission.state = 'VOIDED';
      admission.version = newVersion();
    }
  }

  if (hasRefund && hasCredit) {
    order.status = 'MIXED';
  } else if (hasCredit) {
    order.status = 'CREDITED';
  } else {
    order.status = 'REFUNDED';
  }

  order.version = newVersion();
  return res.status(200).json(order);
});

app.get('/workspaces/:workspace_id/admissions/:admission_id', (req: AuthRequest, res: Response) => {
  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const admission = admissions.get(req.params.admission_id);
  if (!admission || admission.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Admission not found'));
  }

  return res.status(200).json(admission);
});

app.post('/workspaces/:workspace_id/admissions/:admission_id/transfer', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const admission = admissions.get(req.params.admission_id);
  if (!admission || admission.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Admission not found'));
  }

  if (!ensureRoleAllowed(req, res, ['SELLER', 'MANAGER'])) return;

  const posture = calculatePosture(workspace.id);
  if (posture === 'HALT') {
    return res.status(409).json(errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in HALT posture'));
  }

  if (ifMatch !== admission.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (admission.state === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_ADMISSION_VOIDED', 'Cannot transfer voided admission'));
  }

  const event = events.get(admission.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!['ONSALE', 'PAUSED'].includes(event.status)) {
    return res.status(409).json(errorResponse('ERR_POOL_TRANSFER_BLOCKED', 'Transfers not allowed for this event status'));
  }

  const pool = pools.get(admission.pool_id);
  if (!pool) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Pool not found'));
  }

  if (pool.transfer_policy === 'NONE') {
    return res.status(409).json(errorResponse('ERR_POOL_TRANSFER_BLOCKED', 'Pool does not allow transfers'));
  }

  if (pool.transfer_policy === 'ONCE' && admission.transfer_count >= 1) {
    return res.status(409).json(errorResponse('ERR_POOL_TRANSFER_BLOCKED', 'Pool only allows one transfer'));
  }

  if (posture === 'REVIEW' && pool.transfer_policy === 'OPEN' && admission.transfer_count >= 1) {
    return res.status(409).json(errorResponse('ERR_POOL_TRANSFER_BLOCKED', 'Additional transfers blocked in REVIEW posture'));
  }

  const { to_actor_id } = req.body;
  if (!to_actor_id) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'to_actor_id is required'));
  }

  if (req.role === 'SELLER' && req.actorId !== admission.holder_actor_id) {
    return res.status(409).json(errorResponse('ERR_NOT_HOLDER', 'Only the current holder can transfer this admission'));
  }

  const recipientHoldings = getActorHoldings(to_actor_id, event.id);
  if (recipientHoldings + 1 > event.max_tickets_per_actor) {
    return res.status(409).json(errorResponse('ERR_HOLDINGS_LIMIT_EXCEEDED', 'Recipient would exceed max tickets per actor'));
  }

  if (pool.pool_holdings_limit !== null) {
    let poolHoldings = 0;
    for (const adm of admissions.values()) {
      if (adm.pool_id === pool.id && adm.holder_actor_id === to_actor_id && adm.state !== 'VOIDED') {
        poolHoldings++;
      }
    }
    if (poolHoldings + 1 > pool.pool_holdings_limit) {
      return res.status(409).json(errorResponse('ERR_HOLDINGS_LIMIT_EXCEEDED', 'Recipient would exceed pool holdings limit'));
    }
  }

  admission.holder_actor_id = to_actor_id;
  admission.transfer_count += 1;
  admission.version = newVersion();

  return res.status(200).json(admission);
});

app.post('/workspaces/:workspace_id/admissions/:admission_id/scan', (req: AuthRequest, res: Response) => {
  const ifMatch = requireIfMatch(req, res);
  if (!ifMatch) return;

  const workspace = workspaces.get(req.params.workspace_id);
  if (!workspace) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
  }

  const admission = admissions.get(req.params.admission_id);
  if (!admission || admission.workspace_id !== workspace.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Admission not found'));
  }

  if (!ensureRoleAllowed(req, res, ['GATE'])) return;

  if (ifMatch !== admission.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (admission.state === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_ADMISSION_VOIDED', 'Cannot scan voided admission'));
  }

  if (admission.state === 'SCANNED') {
    return res.status(409).json(errorResponse('ERR_ADMISSION_ALREADY_SCANNED', 'Admission already scanned'));
  }

  const event = events.get(admission.event_id);
  if (!event) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Event not found'));
  }

  if (!['ONSALE', 'PAUSED', 'CLOSED'].includes(event.status)) {
    return res.status(409).json(errorResponse('ERR_SCAN_NOT_ALLOWED', 'Scanning not allowed for this event status'));
  }

  admission.state = 'SCANNED';
  admission.scanned_by_actor_id = req.actorId!;
  admission.version = newVersion();

  return res.status(200).json(admission);
});

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error(err);
  return res.status(500).json(errorResponse('ERR_INTERNAL', 'Internal server error'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Marquee Ticketing API listening on port ${PORT}`);
});

export default app;
