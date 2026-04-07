import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';

const app = express();
app.use(express.json());

type StorefrontPosture = 'OPEN' | 'THROTTLED' | 'PAUSED';
type DropStatus = 'PLANNED' | 'LIVE' | 'PAUSED' | 'CLOSED';
type OrderStatus = 'DRAFT' | 'SUBMITTED' | 'WAITLISTED' | 'NEEDS_REVIEW' | 'ACCEPTED' | 'IN_KITCHEN' | 'READY' | 'PICKED_UP' | 'CANCELLED' | 'VOIDED';
type BundleStatus = 'DRAFT' | 'SEALED';
type MakegoodStatus = 'ISSUED';

interface Storefront {
  id: string;
  posture: StorefrontPosture;
  ops_run_index: number;
  waste_voids_since_last_run: number;
  ticket_counter: number;
  version: number;
}

interface Drop {
  id: string;
  storefront_id: string;
  title: string;
  servings_total: number;
  status: DropStatus;
  version: number;
}

interface Order {
  id: string;
  storefront_id: string;
  drop_id: string;
  customer_ref: string;
  quantity: number;
  note: string | null;
  ticket_no: number;
  status: OrderStatus;
  bundle_id: string | null;
  version: number;
}

interface Bundle {
  id: string;
  storefront_id: string;
  drop_id: string;
  max_orders: number;
  order_ids: string[];
  status: BundleStatus;
  version: number;
}

interface Makegood {
  id: string;
  storefront_id: string;
  order_id: string;
  amount_cents: number;
  status: MakegoodStatus;
}

const storefronts: Map<string, Storefront> = new Map();
const drops: Map<string, Drop> = new Map();
const orders: Map<string, Order> = new Map();
const bundles: Map<string, Bundle> = new Map();
const makegoods: Map<string, Makegood> = new Map();

function bumpDropVersion(dropId: string): void {
  const drop = drops.get(dropId);
  if (!drop) return;
  drop.version++;
}

function successResponse(data: any) {
  return { response_type: 'success', data };
}

function errorResponse(error_code: string, message: string) {
  return { response_type: 'error', data: { error_code, message } };
}

function getStorefront(storefrontId: string): Storefront | null {
  return storefronts.get(storefrontId) || null;
}

function getDrop(dropId: string): Drop | null {
  return drops.get(dropId) || null;
}

function getOrder(orderId: string): Order | null {
  return orders.get(orderId) || null;
}

function getBundle(bundleId: string): Bundle | null {
  return bundles.get(bundleId) || null;
}

function getMakegood(makegoodId: string): Makegood | null {
  return makegoods.get(makegoodId) || null;
}

function isActiveOrderStatus(status: OrderStatus): boolean {
  return ['DRAFT', 'SUBMITTED', 'WAITLISTED', 'NEEDS_REVIEW', 'ACCEPTED', 'IN_KITCHEN', 'READY'].includes(status);
}

function isIntakeStatus(status: OrderStatus): boolean {
  return ['DRAFT', 'SUBMITTED', 'WAITLISTED', 'NEEDS_REVIEW'].includes(status);
}

function isCommittedStatus(status: OrderStatus): boolean {
  return ['ACCEPTED', 'IN_KITCHEN', 'READY', 'PICKED_UP'].includes(status);
}

function getCommittedServings(dropId: string): number {
  let total = 0;
  for (const order of orders.values()) {
    if (order.drop_id === dropId && isCommittedStatus(order.status)) {
      total += order.quantity;
    }
  }
  return total;
}

function getServingsRemaining(dropId: string): number {
  const drop = getDrop(dropId);
  if (!drop) return 0;
  return Math.max(0, drop.servings_total - getCommittedServings(dropId));
}

function getMaxQuantityForPosture(posture: StorefrontPosture): number {
  switch (posture) {
    case 'OPEN': return 6;
    case 'THROTTLED': return 2;
    case 'PAUSED': return 0;
  }
}

function hasActiveOrderForCustomerOnDrop(dropId: string, customerRef: string, excludeOrderId?: string): boolean {
  for (const order of orders.values()) {
    if (order.drop_id === dropId && order.customer_ref === customerRef && isActiveOrderStatus(order.status)) {
      if (excludeOrderId && order.id === excludeOrderId) continue;
      return true;
    }
  }
  return false;
}

function getDropResponse(drop: Drop) {
  return {
    id: drop.id,
    storefront_id: drop.storefront_id,
    title: drop.title,
    servings_total: drop.servings_total,
    servings_remaining: getServingsRemaining(drop.id),
    status: drop.status,
    version: drop.version,
  };
}

function getOrderResponse(order: Order) {
  const response: any = {
    id: order.id,
    storefront_id: order.storefront_id,
    drop_id: order.drop_id,
    customer_ref: order.customer_ref,
    quantity: order.quantity,
    note: order.note,
    ticket_no: order.ticket_no,
    status: order.status,
    version: order.version,
  };

  if (order.bundle_id) {
    response.bundle_id = order.bundle_id;
  }

  return response;
}

function getBundleResponse(bundle: Bundle) {
  return {
    id: bundle.id,
    storefront_id: bundle.storefront_id,
    drop_id: bundle.drop_id,
    max_orders: bundle.max_orders,
    order_ids: bundle.order_ids,
    status: bundle.status,
    version: bundle.version,
  };
}

function getStorefrontResponse(storefront: Storefront) {
  return {
    id: storefront.id,
    posture: storefront.posture,
    ops_run_index: storefront.ops_run_index,
    version: storefront.version,
  };
}

function getMakegoodResponse(makegood: Makegood) {
  return {
    id: makegood.id,
    order_id: makegood.order_id,
    amount_cents: makegood.amount_cents,
    status: makegood.status,
  };
}

app.post('/storefronts', (req: Request, res: Response) => {
  const storefront: Storefront = {
    id: uuidv4(),
    posture: 'OPEN',
    ops_run_index: 0,
    waste_voids_since_last_run: 0,
    ticket_counter: 0,
    version: 1,
  };
  storefronts.set(storefront.id, storefront);
  res.status(201).json(successResponse(getStorefrontResponse(storefront)));
});

app.get('/storefronts/:storefront_id', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }
  res.json(successResponse(getStorefrontResponse(storefront)));
});

app.post('/storefronts/:storefront_id/run_ops', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  storefront.ops_run_index++;

  if (storefront.waste_voids_since_last_run === 0) {
    storefront.posture = 'OPEN';
  } else if (storefront.waste_voids_since_last_run === 1) {
    storefront.posture = 'THROTTLED';
  } else {
    storefront.posture = 'PAUSED';
  }
  storefront.waste_voids_since_last_run = 0;

  const storefrontDrops = Array.from(drops.values()).filter(d => d.storefront_id === storefront.id);

  for (const drop of storefrontDrops) {
    if (drop.status === 'CLOSED') {
      for (const order of orders.values()) {
        if (order.drop_id === drop.id && ['SUBMITTED', 'WAITLISTED', 'NEEDS_REVIEW'].includes(order.status)) {
          order.status = 'CANCELLED';
          order.version++;
        }
      }
    }
  }

  if (storefront.posture === 'THROTTLED') {
    const maxQty = getMaxQuantityForPosture('THROTTLED');
    for (const order of orders.values()) {
      if (order.storefront_id !== storefront.id) continue;
      if (!['SUBMITTED', 'WAITLISTED'].includes(order.status)) continue;
      if (order.quantity > maxQty) {
        order.status = 'NEEDS_REVIEW';
        order.version++;
      }
    }
  }

  if (storefront.posture !== 'PAUSED') {
    for (const drop of storefrontDrops) {
      if (drop.status !== 'LIVE') continue;

      const settleableOrders = Array.from(orders.values())
        .filter((o) => o.drop_id === drop.id && ['SUBMITTED', 'WAITLISTED'].includes(o.status))
        .sort((a, b) => a.ticket_no - b.ticket_no);

      let remaining = getServingsRemaining(drop.id);
      let blocked = false;

      for (const order of settleableOrders) {
        if (blocked) {

          if (order.status === 'SUBMITTED') {
            order.status = 'WAITLISTED';
            order.version++;
          }
          continue;
        }

        if (order.quantity <= remaining) {

          order.status = 'ACCEPTED';
          order.version++;
          remaining -= order.quantity;
          bumpDropVersion(drop.id);
        } else {

          if (order.status === 'SUBMITTED') {
            order.status = 'WAITLISTED';
            order.version++;
          }
          blocked = true;
        }
      }
    }
  }

  storefront.version++;
  res.json(successResponse(getStorefrontResponse(storefront)));
});

app.post('/storefronts/:storefront_id/drops', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const { title, servings_total } = req.body;

  if (!title || typeof title !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'title is required'));
  }
  if (servings_total === undefined || typeof servings_total !== 'number' || servings_total < 0 || !Number.isInteger(servings_total)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'servings_total must be a non-negative integer'));
  }

  const existing = Array.from(drops.values()).find(
    (d) =>
      d.storefront_id === storefront.id &&
      d.status === 'PLANNED' &&
      d.title === title &&
      d.servings_total === servings_total
  );
  if (existing) {
    return res.status(201).json(successResponse(getDropResponse(existing)));
  }

  const drop: Drop = {
    id: uuidv4(),
    storefront_id: storefront.id,
    title,
    servings_total,
    status: 'PLANNED',
    version: 1,
  };
  drops.set(drop.id, drop);
  res.status(201).json(successResponse(getDropResponse(drop)));
});

app.get('/storefronts/:storefront_id/drops/:drop_id', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const drop = getDrop(req.params.drop_id);
  if (!drop || drop.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Drop not found'));
  }

  res.json(successResponse(getDropResponse(drop)));
});

app.patch('/storefronts/:storefront_id/drops/:drop_id', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const drop = getDrop(req.params.drop_id);
  if (!drop || drop.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Drop not found'));
  }

  const version = parseInt(ifMatch as string, 10);
  if (version !== drop.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  const { status, servings_total, title } = req.body;

  if (status !== undefined) {
    const validStatuses: DropStatus[] = ['PLANNED', 'LIVE', 'PAUSED', 'CLOSED'];
    if (typeof status !== 'string' || !validStatuses.includes(status as DropStatus)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'Invalid drop status'));
    }

    const nextStatus = status as DropStatus;

    const validTransitions: Record<DropStatus, DropStatus[]> = {
      'PLANNED': ['LIVE'],
      'LIVE': ['PAUSED', 'CLOSED'],
      'PAUSED': ['LIVE', 'CLOSED'],
      'CLOSED': [],
    };

    if (!validTransitions[drop.status].includes(nextStatus)) {
      return res
        .status(409)
        .json(errorResponse('ERR_INVALID_STATE', `Cannot transition from ${drop.status} to ${nextStatus}`));
    }

    if (drop.status === 'LIVE' && nextStatus === 'PAUSED') {
      for (const order of orders.values()) {
        if (order.drop_id === drop.id && ['SUBMITTED', 'WAITLISTED'].includes(order.status)) {
          order.status = 'NEEDS_REVIEW';
          order.version++;
        }
      }
    }

    drop.status = nextStatus;
  }

  if (servings_total !== undefined) {
    if (drop.status === 'CLOSED') {
      return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot modify servings_total of a closed drop'));
    }

    if (typeof servings_total !== 'number' || servings_total < 0 || !Number.isInteger(servings_total)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'servings_total must be a non-negative integer'));
    }

    const committed = getCommittedServings(drop.id);
    if (servings_total < committed) {
      return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', `Cannot reduce servings_total below committed amount (${committed})`));
    }

    drop.servings_total = servings_total;
  }

  if (title !== undefined) {
    if (typeof title !== 'string' || title.length === 0) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'title must be a non-empty string'));
    }
    drop.title = title;
  }

  drop.version++;
  res.json(successResponse(getDropResponse(drop)));
});

app.post('/storefronts/:storefront_id/orders', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  if (storefront.posture === 'PAUSED') {
    return res.status(409).json(errorResponse('ERR_STORE_PAUSED', 'Storefront is paused'));
  }

  const { drop_id, customer_ref, quantity, note } = req.body;

  if (!drop_id || typeof drop_id !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'drop_id is required'));
  }
  if (!customer_ref || typeof customer_ref !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'customer_ref is required'));
  }
  if (quantity === undefined || typeof quantity !== 'number' || quantity < 1 || !Number.isInteger(quantity)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'quantity must be a positive integer'));
  }

  const drop = getDrop(drop_id);
  if (!drop || drop.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Drop not found'));
  }

  if (hasActiveOrderForCustomerOnDrop(drop_id, customer_ref)) {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Customer already has an active order for this drop'));
  }

  const maxQty = getMaxQuantityForPosture(storefront.posture);
  const shouldRequireReview = storefront.posture === 'THROTTLED' && quantity > maxQty;
  if (storefront.posture === 'OPEN' && quantity > maxQty) {
    return res
      .status(409)
      .json(errorResponse('ERR_QUANTITY_LIMIT_EXCEEDED', `Maximum quantity is ${maxQty} in ${storefront.posture} mode`));
  }

  storefront.ticket_counter++;
  const order: Order = {
    id: uuidv4(),
    storefront_id: storefront.id,
    drop_id,
    customer_ref,
    quantity,
    note: note || null,
    ticket_no: storefront.ticket_counter,
    status: shouldRequireReview ? 'NEEDS_REVIEW' : 'DRAFT',
    bundle_id: null,
    version: 1,
  };
  orders.set(order.id, order);
  res.status(201).json(successResponse(getOrderResponse(order)));
});

app.get('/storefronts/:storefront_id/orders/:order_id', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  res.json(successResponse(getOrderResponse(order)));
});

app.put('/storefronts/:storefront_id/orders/:order_id', (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'];
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  const version = parseInt(ifMatch as string, 10);
  if (version !== order.version) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  if (['ACCEPTED', 'IN_KITCHEN', 'READY', 'PICKED_UP', 'CANCELLED', 'VOIDED'].includes(order.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order cannot be edited in current state'));
  }

  const { quantity, note } = req.body;

  const nextNote = note !== undefined ? (note || null) : order.note;
  let nextQuantity = order.quantity;
  let nextStatus: OrderStatus = order.status;

  if (quantity !== undefined) {
    if (typeof quantity !== 'number' || quantity < 1 || !Number.isInteger(quantity)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'quantity must be a positive integer'));
    }

    if (order.status === 'DRAFT') {
      const maxQty = getMaxQuantityForPosture(storefront.posture);
      if (storefront.posture === 'OPEN' && quantity > maxQty) {
        return res
          .status(409)
          .json(errorResponse('ERR_QUANTITY_LIMIT_EXCEEDED', `Maximum quantity is ${maxQty} in ${storefront.posture} mode`));
      }
      if (storefront.posture === 'THROTTLED' && quantity > maxQty) {
        nextStatus = 'NEEDS_REVIEW';
      }
      nextQuantity = quantity;
    } else if (['SUBMITTED', 'WAITLISTED', 'NEEDS_REVIEW'].includes(order.status)) {

      if (quantity > order.quantity) {
        return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Cannot increase quantity after submission'));
      }
      nextQuantity = quantity;
    }
  }

  order.note = nextNote;
  order.quantity = nextQuantity;
  order.status = nextStatus;

  order.version++;
  res.json(successResponse(getOrderResponse(order)));
});

app.post('/storefronts/:storefront_id/orders/:order_id/submit', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!['DRAFT', 'NEEDS_REVIEW'].includes(order.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order cannot be submitted from current state'));
  }

  if (storefront.posture === 'PAUSED') {
    return res.status(409).json(errorResponse('ERR_STORE_PAUSED', 'Storefront is paused'));
  }

  const drop = getDrop(order.drop_id);
  if (!drop) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Drop not found'));
  }

  if (drop.status !== 'LIVE') {
    if (drop.status === 'PAUSED') {
      return res.status(409).json(errorResponse('ERR_DROP_PAUSED', 'Drop is paused'));
    } else if (drop.status === 'CLOSED') {
      return res.status(409).json(errorResponse('ERR_DROP_CLOSED', 'Drop is closed'));
    } else {
      return res.status(409).json(errorResponse('ERR_DROP_NOT_LIVE', 'Drop is not live'));
    }
  }

  const maxQty = getMaxQuantityForPosture(storefront.posture);
  if (storefront.posture === 'THROTTLED' && order.quantity > maxQty) {

    if (order.status === 'DRAFT') {
      order.status = 'NEEDS_REVIEW';
      order.version++;
      return res.json(successResponse(getOrderResponse(order)));
    }
    return res
      .status(409)
      .json(errorResponse('ERR_INVALID_STATE', 'Order requires review before it can be submitted'));
  }

  order.status = 'SUBMITTED';
  order.version++;
  res.json(successResponse(getOrderResponse(order)));
});

app.post('/storefronts/:storefront_id/orders/:order_id/cancel', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!['DRAFT', 'SUBMITTED', 'WAITLISTED', 'NEEDS_REVIEW'].includes(order.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order cannot be cancelled from current state'));
  }

  order.status = 'CANCELLED';
  order.version++;
  res.json(successResponse(getOrderResponse(order)));
});

app.post('/storefronts/:storefront_id/orders/:order_id/advance', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (order.status === 'ACCEPTED') {
    order.status = 'IN_KITCHEN';
  } else if (order.status === 'IN_KITCHEN') {
    order.status = 'READY';
  } else if (order.status === 'READY') {

    if (!order.bundle_id) {
      return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order must be in a sealed bundle to be picked up'));
    }
    const bundle = getBundle(order.bundle_id);
    if (!bundle || bundle.status !== 'SEALED') {
      return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order must be in a sealed bundle to be picked up'));
    }
    order.status = 'PICKED_UP';
  } else {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order cannot be advanced from current state'));
  }

  order.version++;
  res.json(successResponse(getOrderResponse(order)));
});

app.post('/storefronts/:storefront_id/orders/:order_id/void', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const order = getOrder(req.params.order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (!['ACCEPTED', 'IN_KITCHEN', 'READY'].includes(order.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Order cannot be voided from current state'));
  }

  const wasWasteVoid = order.status === 'IN_KITCHEN' || order.status === 'READY';
  const wasReady = order.status === 'READY';

  if (order.bundle_id) {
    const bundle = getBundle(order.bundle_id);
    if (bundle) {
      bundle.order_ids = bundle.order_ids.filter(id => id !== order.id);
      bundle.version++;
    }
    order.bundle_id = null;
  }

  order.status = 'VOIDED';
  order.version++;
  bumpDropVersion(order.drop_id);

  if (wasWasteVoid) {
    storefront.waste_voids_since_last_run++;
  }

  let makegood_id: string | undefined;
  if (wasReady) {
    const amountCents = Math.min(order.quantity * 500, 2000);
    const makegood: Makegood = {
      id: uuidv4(),
      storefront_id: storefront.id,
      order_id: order.id,
      amount_cents: amountCents,
      status: 'ISSUED',
    };
    makegoods.set(makegood.id, makegood);
    makegood_id = makegood.id;
  }

  const response: any = getOrderResponse(order);
  if (makegood_id) {
    response.makegood_id = makegood_id;
  }

  res.json(successResponse(response));
});

app.post('/storefronts/:storefront_id/bundles', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const { drop_id, max_orders } = req.body;

  if (!drop_id || typeof drop_id !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'drop_id is required'));
  }
  if (max_orders === undefined || typeof max_orders !== 'number' || max_orders < 1 || !Number.isInteger(max_orders)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'max_orders must be a positive integer'));
  }

  const drop = getDrop(drop_id);
  if (!drop || drop.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Drop not found'));
  }

  const bundle: Bundle = {
    id: uuidv4(),
    storefront_id: storefront.id,
    drop_id,
    max_orders,
    order_ids: [],
    status: 'DRAFT',
    version: 1,
  };
  bundles.set(bundle.id, bundle);
  res.status(201).json(successResponse(getBundleResponse(bundle)));
});

app.get('/storefronts/:storefront_id/bundles/:bundle_id', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const bundle = getBundle(req.params.bundle_id);
  if (!bundle || bundle.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Bundle not found'));
  }

  res.json(successResponse(getBundleResponse(bundle)));
});

app.post('/storefronts/:storefront_id/bundles/:bundle_id/add_order', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const bundle = getBundle(req.params.bundle_id);
  if (!bundle || bundle.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Bundle not found'));
  }

  const { order_id } = req.body;
  if (!order_id || typeof order_id !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'order_id is required'));
  }

  const order = getOrder(order_id);
  if (!order || order.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Order not found'));
  }

  if (bundle.status === 'SEALED') {
    return res.status(409).json(errorResponse('ERR_BUNDLE_LOCKED', 'Bundle is sealed'));
  }

  if (order.status !== 'READY') {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order must be READY to add to bundle'));
  }

  if (order.drop_id !== bundle.drop_id) {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order must belong to the same drop as the bundle'));
  }

  if (bundle.order_ids.length >= bundle.max_orders) {
    return res.status(409).json(errorResponse('ERR_BUNDLE_FULL', 'Bundle has reached max_orders'));
  }

  if (order.bundle_id && order.bundle_id !== bundle.id) {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order is already in another bundle'));
  }

  if (bundle.order_ids.includes(order.id)) {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Order is already in this bundle'));
  }

  bundle.order_ids.push(order.id);
  bundle.version++;
  order.bundle_id = bundle.id;
  order.version++;

  res.json(successResponse(getBundleResponse(bundle)));
});

app.post('/storefronts/:storefront_id/bundles/:bundle_id/seal', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const bundle = getBundle(req.params.bundle_id);
  if (!bundle || bundle.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Bundle not found'));
  }

  if (bundle.status === 'SEALED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Bundle is already sealed'));
  }

  if (bundle.order_ids.length === 0) {
    return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Cannot seal an empty bundle'));
  }

  for (const orderId of bundle.order_ids) {
    const order = getOrder(orderId);
    if (!order || order.storefront_id !== storefront.id || order.drop_id !== bundle.drop_id || order.status !== 'READY') {
      return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Bundle contains non-READY orders'));
    }
  }

  bundle.status = 'SEALED';
  bundle.version++;

  res.json(successResponse(getBundleResponse(bundle)));
});

app.get('/storefronts/:storefront_id/makegoods/:makegood_id', (req: Request, res: Response) => {
  const storefront = getStorefront(req.params.storefront_id);
  if (!storefront) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Storefront not found'));
  }

  const makegood = getMakegood(req.params.makegood_id);
  if (!makegood || makegood.storefront_id !== storefront.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Makegood not found'));
  }

  res.json(successResponse(getMakegoodResponse(makegood)));
});

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error(err);
  res.status(500).json(errorResponse('ERR_BAD_REQUEST', 'Internal server error'));
});

if (process.env.INPROCESS_HTTP !== 'true') {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`DropBite API running on port ${PORT}`);
  });
}

export default app;
