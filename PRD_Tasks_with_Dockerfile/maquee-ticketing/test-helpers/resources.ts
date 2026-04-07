import { v4 as uuidv4 } from 'uuid';
import { getAs, postAs, putAs, PostOptions, PutOptions } from './api-client';
import { expectSuccess, extractData, extractId, extractVersion } from './assertions';
import {
  Role,
  PoolKind,
  RefundPolicy,
  TransferPolicy,
  RefundReason,
  EventStatus,
  OrderStatus,
  AdmissionState,
  Posture,
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

export interface Workspace {
  id: string;
  name: string;
  settlement_currency: string;
  posture: Posture;
  version: string;
}

export interface Event {
  id: string;
  title: string;
  starts_at_local: string;
  max_tickets_per_actor: number;
  status: EventStatus;
  version: string;
}

export interface Pool {
  id: string;
  label: string;
  kind: PoolKind;
  price_cents: number;
  currency: string;
  capacity_total: number;
  holdback_qty: number;
  refund_policy: RefundPolicy;
  transfer_policy: TransferPolicy;
  pool_holdings_limit?: number;
  quantity_held: number;
  quantity_sold: number;
  quantity_available: number;
  is_overallocated: boolean;
  version: string;
}

export interface OrderLine {
  pool_id: string;
  quantity: number;
  unit_price_cents?: number;
}

export interface Order {
  id: string;
  event_id: string;
  buyer_actor_id: string;
  status: OrderStatus;
  lines: OrderLine[];
  currency: string;
  total_cents: number;
  admission_ids?: string[];
  version: string;
}

export interface Admission {
  id: string;
  event_id: string;
  pool_id: string;
  order_id: string;
  holder_actor_id: string;
  transfer_count: number;
  state: AdmissionState;
  scanned_by_actor_id?: string;
  version: string;
}

export interface CreateWorkspaceInput {
  name?: string;
  settlement_currency?: string;
}

export async function createWorkspace(
  input: CreateWorkspaceInput = {},
  options: PostOptions = {}
): Promise<Workspace> {
  const payload = {
    name: input.name || `WS-${uniqueId()}`,
    settlement_currency: input.settlement_currency || 'USD',
  };

  const res = await postAs('/workspaces', payload, {
    role: 'ORGANIZER',
    ...options,
  });
  expectSuccess(res);
  return extractData<Workspace>(res);
}

export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const res = await getAs(`/workspaces/${workspaceId}`);
  expectSuccess(res);
  return extractData<Workspace>(res);
}

export interface CreateEventInput {
  title?: string;
  starts_at_local?: string;
  max_tickets_per_actor?: number;
}

export async function createEvent(
  workspaceId: string,
  input: CreateEventInput = {},
  options: PostOptions = {}
): Promise<Event> {
  const payload = {
    title: input.title || `Event-${uniqueId()}`,
    starts_at_local: input.starts_at_local || '2026-04-01T20:00',
    max_tickets_per_actor: input.max_tickets_per_actor ?? 6,
  };

  const res = await postAs(`/workspaces/${workspaceId}/events`, payload, {
    role: 'ORGANIZER',
    ...options,
  });
  expectSuccess(res);
  return extractData<Event>(res);
}

export async function getEvent(workspaceId: string, eventId: string): Promise<Event> {
  const res = await getAs(`/workspaces/${workspaceId}/events/${eventId}`);
  expectSuccess(res);
  return extractData<Event>(res);
}

export async function putEventOnSale(
  workspaceId: string,
  eventId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/on_sale`,
    {},
    { role: 'ORGANIZER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function pauseEvent(
  workspaceId: string,
  eventId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/pause`,
    {},
    { role: 'ORGANIZER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function closeEvent(
  workspaceId: string,
  eventId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/close`,
    {},
    { role: 'ORGANIZER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function cancelEvent(
  workspaceId: string,
  eventId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/cancel`,
    {},
    { role: 'ORGANIZER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export interface CreatePoolInput {
  label?: string;
  kind?: PoolKind;
  price_cents?: number;
  currency?: string;
  capacity_total?: number;
  holdback_qty?: number;
  refund_policy?: RefundPolicy;
  transfer_policy?: TransferPolicy;
  pool_holdings_limit?: number;
}

export async function createPool(
  workspaceId: string,
  eventId: string,
  input: CreatePoolInput = {},
  options: PostOptions = {}
): Promise<Pool> {
  const payload = {
    label: input.label || `Pool-${uniqueId()}`,
    kind: input.kind || 'STANDARD',
    price_cents: input.price_cents ?? 5000,
    currency: input.currency || 'USD',
    capacity_total: input.capacity_total ?? 10,
    holdback_qty: input.holdback_qty ?? 0,
    refund_policy: input.refund_policy || 'REFUNDABLE',
    transfer_policy: input.transfer_policy || 'OPEN',
    ...(input.pool_holdings_limit !== undefined && { pool_holdings_limit: input.pool_holdings_limit }),
  };

  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/pools`,
    payload,
    { role: 'ORGANIZER', ...options }
  );
  expectSuccess(res);
  return extractData<Pool>(res);
}

export async function getPool(
  workspaceId: string,
  eventId: string,
  poolId: string
): Promise<Pool> {
  const res = await getAs(`/workspaces/${workspaceId}/events/${eventId}/pools/${poolId}`);
  expectSuccess(res);
  return extractData<Pool>(res);
}

export interface AdjustPoolInput {
  capacity_delta: number;
  holdback_delta: number;
  new_price_cents?: number;
  note: string;
}

export async function adjustPool(
  workspaceId: string,
  eventId: string,
  poolId: string,
  version: string,
  input: AdjustPoolInput,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/events/${eventId}/pools/${poolId}/adjust`,
    input,
    { role: 'ORGANIZER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function createOrder(
  workspaceId: string,
  eventId: string,
  actorId: string = 'U1',
  options: PostOptions = {}
): Promise<Order> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders`,
    { event_id: eventId },
    { role: 'SELLER', actorId, ...options }
  );
  expectSuccess(res);
  return extractData<Order>(res);
}

export async function getOrder(workspaceId: string, orderId: string): Promise<Order> {
  const res = await getAs(`/workspaces/${workspaceId}/orders/${orderId}`);
  expectSuccess(res);
  return extractData<Order>(res);
}

export async function setOrderLines(
  workspaceId: string,
  orderId: string,
  version: string,
  lines: OrderLine[],
  options: PutOptions = {}
): Promise<void> {
  const res = await putAs(
    `/workspaces/${workspaceId}/orders/${orderId}/lines`,
    { lines },
    { role: 'SELLER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function submitOrder(
  workspaceId: string,
  orderId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders/${orderId}/submit`,
    {},
    { role: 'SELLER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function approveOrder(
  workspaceId: string,
  orderId: string,
  version: string,
  actorId: string = 'M1',
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders/${orderId}/approve`,
    {},
    { role: 'MANAGER', actorId, ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export interface PayOrderResult {
  admission_ids: string[];
}

export async function payOrder(
  workspaceId: string,
  orderId: string,
  version: string,
  options: PostOptions = {}
): Promise<PayOrderResult> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders/${orderId}/pay`,
    {},
    { role: 'SELLER', ifMatch: version, ...options }
  );
  expectSuccess(res);

  const data = extractData(res);
  return {
    admission_ids: data.admission_ids || [],
  };
}

export async function cancelOrder(
  workspaceId: string,
  orderId: string,
  version: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders/${orderId}/cancel`,
    {},
    { role: 'SELLER', ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function refundOrder(
  workspaceId: string,
  orderId: string,
  version: string,
  reason: RefundReason,
  actorId: string = 'M1',
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/orders/${orderId}/refund`,
    { reason },
    { role: 'MANAGER', actorId, ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function getAdmission(
  workspaceId: string,
  admissionId: string
): Promise<Admission> {
  const res = await getAs(`/workspaces/${workspaceId}/admissions/${admissionId}`);
  expectSuccess(res);
  return extractData<Admission>(res);
}

export async function transferAdmission(
  workspaceId: string,
  admissionId: string,
  version: string,
  toActorId: string,
  fromActorId: string,
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/admissions/${admissionId}/transfer`,
    { to_actor_id: toActorId },
    { role: 'SELLER', actorId: fromActorId, ifMatch: version, ...options }
  );
  expectSuccess(res);
}

export async function scanAdmission(
  workspaceId: string,
  admissionId: string,
  version: string,
  gateActorId: string = 'G1',
  options: PostOptions = {}
): Promise<void> {
  const res = await postAs(
    `/workspaces/${workspaceId}/admissions/${admissionId}/scan`,
    {},
    { role: 'GATE', actorId: gateActorId, ifMatch: version, ...options }
  );
  expectSuccess(res);
}
