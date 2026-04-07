import { v4 as uuidv4 } from 'uuid';
import {
  get,
  post,
  postAs,
  patchWithVersion,
  putWithVersion,
  patchWithoutVersion,
  putWithoutVersion
} from './api-client';
import { expectSuccess, getData } from './assertions';
import {
  DropStatus,
  DROP_STATUSES,
  OrderStatus,
  ORDER_STATUSES,
  BundleStatus,
  BUNDLE_STATUSES,
  Posture,
  POSTURES,
  MakegoodStatus,
  MAKEGOOD_STATUSES
} from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return (body && typeof body === 'object' && 'data' in body) ? body.data : body;
}

export function pickId(body: any, keys: string[]): string {
  for (const key of keys) {
    const value = body?.[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  throw new Error(`Could not find id in response. Looked for: ${keys.join(', ')}`);
}

export function asArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

export interface Storefront {
  id: string;
  name?: string;
  posture: Posture;
  ops_run_index: number;
  version?: string | number;
}

export interface Drop {
  id: string;
  title: string;
  status: DropStatus;
  servings_total: number;
  servings_remaining: number;
  version: string | number;
}

export interface Order {
  id: string;
  drop_id: string;
  customer_ref: string;
  quantity: number;
  note?: string;
  status: OrderStatus;
  ticket_no: number;
  bundle_id?: string;
  version: string | number;
}

export interface Bundle {
  id: string;
  drop_id: string;
  max_orders: number;
  order_ids: string[];
  status: BundleStatus;
}

export interface Makegood {
  id: string;
  order_id: string;
  amount_cents: number;
  status: MakegoodStatus;
}

export async function createStorefront(name?: string): Promise<Storefront> {
  const payload = name ? { name } : {};
  const res = await post('/storefronts', payload);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getStorefront(storefrontId: string): Promise<Storefront> {
  const res = await get(`/storefronts/${storefrontId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function runOps(storefrontId: string): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/run_ops`, {});
  expectSuccess(res);
}

export async function createDrop(
  storefrontId: string,
  title: string,
  servingsTotal: number
): Promise<Drop> {
  const res = await post(`/storefronts/${storefrontId}/drops`, {
    title,
    servings_total: servingsTotal,
  });
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getDrop(storefrontId: string, dropId: string): Promise<Drop> {
  const res = await get(`/storefronts/${storefrontId}/drops/${dropId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateDrop(
  storefrontId: string,
  dropId: string,
  version: string | number,
  updates: { status?: DropStatus; servings_total?: number }
): Promise<Drop> {
  const res = await patchWithVersion(
    `/storefronts/${storefrontId}/drops/${dropId}`,
    updates,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function goLive(storefrontId: string, dropId: string): Promise<Drop> {
  const drop = await getDrop(storefrontId, dropId);
  return updateDrop(storefrontId, dropId, drop.version, { status: DROP_STATUSES.LIVE });
}

export async function pauseDrop(storefrontId: string, dropId: string): Promise<Drop> {
  const drop = await getDrop(storefrontId, dropId);
  return updateDrop(storefrontId, dropId, drop.version, { status: DROP_STATUSES.PAUSED });
}

export async function closeDrop(storefrontId: string, dropId: string): Promise<Drop> {
  const drop = await getDrop(storefrontId, dropId);
  return updateDrop(storefrontId, dropId, drop.version, { status: DROP_STATUSES.CLOSED });
}

export async function createLiveDrop(
  storefrontId: string,
  title: string,
  servingsTotal: number
): Promise<Drop> {
  const drop = await createDrop(storefrontId, title, servingsTotal);
  return goLive(storefrontId, drop.id);
}

export async function createOrder(
  storefrontId: string,
  dropId: string,
  customerRef: string,
  quantity: number,
  note: string = 'n/a'
): Promise<Order> {
  const res = await post(`/storefronts/${storefrontId}/orders`, {
    drop_id: dropId,
    customer_ref: customerRef,
    quantity,
    note,
  });
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getOrder(storefrontId: string, orderId: string): Promise<Order> {
  const res = await get(`/storefronts/${storefrontId}/orders/${orderId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateOrder(
  storefrontId: string,
  orderId: string,
  version: string | number,
  updates: { quantity?: number; note?: string }
): Promise<Order> {
  const res = await putWithVersion(
    `/storefronts/${storefrontId}/orders/${orderId}`,
    updates,
    version
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function submitOrder(storefrontId: string, orderId: string): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/orders/${orderId}/submit`, {});
  expectSuccess(res);
}

export async function cancelOrder(storefrontId: string, orderId: string): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/orders/${orderId}/cancel`, {});
  expectSuccess(res);
}

export async function advanceOrder(storefrontId: string, orderId: string): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/orders/${orderId}/advance`, {});
  expectSuccess(res);
}

export async function voidOrder(storefrontId: string, orderId: string): Promise<{ makegood_id?: string }> {
  const res = await post(`/storefronts/${storefrontId}/orders/${orderId}/void`, {});
  expectSuccess(res);
  return unwrap(res.body);
}

export async function createSubmittedOrder(
  storefrontId: string,
  dropId: string,
  customerRef: string,
  quantity: number,
  note: string = 'n/a'
): Promise<Order> {
  const order = await createOrder(storefrontId, dropId, customerRef, quantity, note);
  await submitOrder(storefrontId, order.id);
  return getOrder(storefrontId, order.id);
}

export async function createAcceptedOrder(
  storefrontId: string,
  dropId: string,
  customerRef: string,
  quantity: number,
  note: string = 'n/a'
): Promise<Order> {
  const order = await createSubmittedOrder(storefrontId, dropId, customerRef, quantity, note);
  await runOps(storefrontId);
  return getOrder(storefrontId, order.id);
}

export async function createReadyOrder(
  storefrontId: string,
  dropId: string,
  customerRef: string,
  quantity: number,
  note: string = 'n/a'
): Promise<Order> {
  const order = await createAcceptedOrder(storefrontId, dropId, customerRef, quantity, note);
  await advanceOrder(storefrontId, order.id);
  await advanceOrder(storefrontId, order.id);
  return getOrder(storefrontId, order.id);
}

export async function createBundle(
  storefrontId: string,
  dropId: string,
  maxOrders: number
): Promise<Bundle> {
  const res = await post(`/storefronts/${storefrontId}/bundles`, {
    drop_id: dropId,
    max_orders: maxOrders,
  });
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getBundle(storefrontId: string, bundleId: string): Promise<Bundle> {
  const res = await get(`/storefronts/${storefrontId}/bundles/${bundleId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function addOrderToBundle(
  storefrontId: string,
  bundleId: string,
  orderId: string
): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/bundles/${bundleId}/add_order`, {
    order_id: orderId,
  });
  expectSuccess(res);
}

export async function sealBundle(storefrontId: string, bundleId: string): Promise<void> {
  const res = await post(`/storefronts/${storefrontId}/bundles/${bundleId}/seal`, {});
  expectSuccess(res);
}

export async function createSealedBundleWithOrder(
  storefrontId: string,
  dropId: string,
  orderId: string,
  maxOrders: number = 2
): Promise<Bundle> {
  const bundle = await createBundle(storefrontId, dropId, maxOrders);
  await addOrderToBundle(storefrontId, bundle.id, orderId);
  await sealBundle(storefrontId, bundle.id);
  return getBundle(storefrontId, bundle.id);
}

export async function getMakegood(storefrontId: string, makegoodId: string): Promise<Makegood> {
  const res = await get(`/storefronts/${storefrontId}/makegoods/${makegoodId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function createStorefrontWithLiveDrop(
  servingsTotal: number = 10,
  title: string = 'Test Drop'
): Promise<{ storefront: Storefront; drop: Drop }> {
  const storefront = await createStorefront(`SF-${uniqueId()}`);
  const drop = await createLiveDrop(storefront.id, title, servingsTotal);
  return { storefront, drop };
}

export async function createThrottledStorefront(): Promise<{
  storefront: Storefront;
  drop: Drop;
}> {
  const { storefront, drop } = await createStorefrontWithLiveDrop(10);

  const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 1);
  await voidOrder(storefront.id, order.id);

  await runOps(storefront.id);

  const updatedStorefront = await getStorefront(storefront.id);
  const updatedDrop = await getDrop(storefront.id, drop.id);

  return { storefront: updatedStorefront, drop: updatedDrop };
}

export async function createPausedStorefront(): Promise<{
  storefront: Storefront;
  drop: Drop;
}> {
  const { storefront, drop } = await createStorefrontWithLiveDrop(10);

  const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 1);
  const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 1);
  await voidOrder(storefront.id, order1.id);
  await voidOrder(storefront.id, order2.id);

  await runOps(storefront.id);

  const updatedStorefront = await getStorefront(storefront.id);
  const updatedDrop = await getDrop(storefront.id, drop.id);

  return { storefront: updatedStorefront, drop: updatedDrop };
}

export async function createPausedDropWithReviewOrder(): Promise<{
  storefront: Storefront;
  drop: Drop;
  order: Order;
}> {
  const { storefront, drop } = await createStorefrontWithLiveDrop(10);

  const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2);

  await pauseDrop(storefront.id, drop.id);

  const updatedDrop = await getDrop(storefront.id, drop.id);
  const updatedOrder = await getOrder(storefront.id, order.id);

  return { storefront, drop: updatedDrop, order: updatedOrder };
}

export async function createSettledAcceptWaitlist(): Promise<{
  storefront: Storefront;
  drop: Drop;
  acceptedOrder: Order;
  waitlistedOrder: Order;
}> {
  const { storefront, drop } = await createStorefrontWithLiveDrop(2);

  const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2);
  const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2);

  await runOps(storefront.id);

  const acceptedOrder = await getOrder(storefront.id, order1.id);
  const waitlistedOrder = await getOrder(storefront.id, order2.id);
  const updatedDrop = await getDrop(storefront.id, drop.id);

  return { storefront, drop: updatedDrop, acceptedOrder, waitlistedOrder };
}
