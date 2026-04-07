import { v4 as uuidv4 } from 'uuid';
import { post, get, postWithEtag, putWithEtag } from './api-client';
import { expectSuccess, getEtag, getData, expectStatus } from './assertions';
import {
  Commodity,
  Direction,
  Priority,
  COMMODITIES,
  DIRECTIONS,
  PRIORITIES,
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

export interface Hub {
  id: string;
  name: string;
  staging_capacity_units: number;
  staging_in_use_units: number;
  staging_reserved_units: number;
  staging_free_units: number;
  posture: string;
  ops_run_index: number;
  etag: string;
}

export interface Consignment {
  id: string;
  hub_id: string;
  reference: string;
  declared_units: number;
  commodity: Commodity;
  units_on_hand: number;
  status: string;
  etag: string;
}

export interface DockRequest {
  id: string;
  hub_id: string;
  consignment_id: string;
  direction: Direction;
  units: number;
  priority: Priority;
  status: string;
  sequence: number;
  variance_units?: number;
  auto_hold_id?: string;
  etag: string;
}

export interface Hold {
  id: string;
  hub_id: string;
  consignment_id: string;
  kind: string;
  note: string;
  status: string;
  source: string;
  source_dock_request_id?: string;
  etag: string;
}

export interface BatchScheduleResult {
  scheduled_ids: string[];
  rejected: Array<{ dock_request_id: string; error_code: string }>;
}

export async function createHub(name?: string, stagingCapacity: number = 100): Promise<Hub> {
  const res = await post('/hubs', {
    name: name ?? uniqueId('hub'),
    staging_capacity_units: stagingCapacity,
  });
  expectSuccess(res);
  return getData(res);
}

export async function getHub(hubId: string): Promise<Hub> {
  const res = await get(`/hubs/${hubId}`);
  expectSuccess(res);
  return getData(res);
}

export async function runOps(hubId: string): Promise<void> {
  const hub = await getHub(hubId);
  const res = await postWithEtag(`/hubs/${hubId}/run_ops`, {}, hub.etag);
  expectSuccess(res);
}

export interface CreateConsignmentInput {
  reference?: string;
  declared_units: number;
  commodity?: Commodity;
}

export async function createConsignment(
  hubId: string,
  input: CreateConsignmentInput
): Promise<Consignment> {
  const res = await post(`/hubs/${hubId}/consignments`, {
    reference: input.reference ?? uniqueId('consignment'),
    declared_units: input.declared_units,
    commodity: input.commodity ?? COMMODITIES.GENERAL,
  });
  expectSuccess(res);
  return getData(res);
}

export async function getConsignment(hubId: string, consignmentId: string): Promise<Consignment> {
  const res = await get(`/hubs/${hubId}/consignments/${consignmentId}`);
  expectSuccess(res);
  return getData(res);
}

export async function voidConsignment(hubId: string, consignmentId: string, etag: string): Promise<Consignment> {
  const res = await postWithEtag(`/hubs/${hubId}/consignments/${consignmentId}/void`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export interface CreateDockRequestInput {
  consignment_id: string;
  direction: Direction;
  units: number;
  priority?: Priority;
}

export async function createDockRequest(
  hubId: string,
  input: CreateDockRequestInput
): Promise<DockRequest> {
  const res = await post(`/hubs/${hubId}/dock_requests`, {
    consignment_id: input.consignment_id,
    direction: input.direction,
    units: input.units,
    priority: input.priority ?? PRIORITIES.STANDARD,
  });
  expectSuccess(res);
  return getData(res);
}

export async function getDockRequest(hubId: string, dockRequestId: string): Promise<DockRequest> {
  const res = await get(`/hubs/${hubId}/dock_requests/${dockRequestId}`);
  expectSuccess(res);
  return getData(res);
}

export async function updateDockRequest(
  hubId: string,
  dockRequestId: string,
  etag: string,
  updates: { units?: number; priority?: Priority }
): Promise<DockRequest> {
  const res = await putWithEtag(`/hubs/${hubId}/dock_requests/${dockRequestId}`, updates, etag);
  expectSuccess(res);
  return getData(res);
}

export async function submitDockRequest(hubId: string, dockRequestId: string, etag: string): Promise<DockRequest> {
  const res = await postWithEtag(`/hubs/${hubId}/dock_requests/${dockRequestId}/submit`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export async function cancelDockRequest(hubId: string, dockRequestId: string, etag: string): Promise<DockRequest> {
  const res = await postWithEtag(`/hubs/${hubId}/dock_requests/${dockRequestId}/cancel`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export async function completeDockRequest(
  hubId: string,
  dockRequestId: string,
  etag: string,
  actualUnits: number
): Promise<DockRequest> {
  const res = await postWithEtag(
    `/hubs/${hubId}/dock_requests/${dockRequestId}/complete`,
    { actual_units: actualUnits },
    etag
  );
  expectSuccess(res);
  return getData(res);
}

export async function voidDockRequest(hubId: string, dockRequestId: string, etag: string): Promise<DockRequest> {
  const res = await postWithEtag(`/hubs/${hubId}/dock_requests/${dockRequestId}/void`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export async function batchSchedule(hubId: string, dockRequestIds: string[]): Promise<BatchScheduleResult> {
  const res = await post(`/hubs/${hubId}/dock_requests/batch_schedule`, {
    dock_request_ids: dockRequestIds,
  });
  expectSuccess(res);
  return getData(res);
}

export interface CreateHoldInput {
  consignment_id: string;
  kind: string;
  note?: string;
}

export async function createHold(hubId: string, input: CreateHoldInput): Promise<Hold> {
  const res = await post(`/hubs/${hubId}/holds`, {
    consignment_id: input.consignment_id,
    kind: input.kind,
    note: input.note ?? 'test hold',
  });
  expectSuccess(res);
  return getData(res);
}

export async function getHold(hubId: string, holdId: string): Promise<Hold> {
  const res = await get(`/hubs/${hubId}/holds/${holdId}`);
  expectSuccess(res);
  return getData(res);
}

export async function clearHold(hubId: string, holdId: string, etag: string): Promise<Hold> {
  const res = await postWithEtag(`/hubs/${hubId}/holds/${holdId}/clear`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export async function voidHold(hubId: string, holdId: string, etag: string): Promise<Hold> {
  const res = await postWithEtag(`/hubs/${hubId}/holds/${holdId}/void`, {}, etag);
  expectSuccess(res);
  return getData(res);
}

export async function createHubWithCapacity(capacity: number): Promise<Hub> {
  return createHub(`Hub-${capacity}`, capacity);
}

export async function createPlannedConsignment(
  hubId: string,
  declaredUnits: number,
  commodity: Commodity = COMMODITIES.GENERAL
): Promise<Consignment> {
  return createConsignment(hubId, {
    declared_units: declaredUnits,
    commodity,
  });
}

export async function createInboundDraft(
  hubId: string,
  consignmentId: string,
  units: number,
  priority: Priority = PRIORITIES.STANDARD
): Promise<DockRequest> {
  return createDockRequest(hubId, {
    consignment_id: consignmentId,
    direction: DIRECTIONS.INBOUND,
    units,
    priority,
  });
}

export async function createOutboundDraft(
  hubId: string,
  consignmentId: string,
  units: number,
  priority: Priority = PRIORITIES.STANDARD
): Promise<DockRequest> {
  return createDockRequest(hubId, {
    consignment_id: consignmentId,
    direction: DIRECTIONS.OUTBOUND,
    units,
    priority,
  });
}

export async function submitAndGet(hubId: string, dr: DockRequest): Promise<DockRequest> {
  await submitDockRequest(hubId, dr.id, dr.etag);
  return getDockRequest(hubId, dr.id);
}

export async function scheduleAndGet(hubId: string, dr: DockRequest): Promise<DockRequest> {
  await batchSchedule(hubId, [dr.id]);
  return getDockRequest(hubId, dr.id);
}

export async function completeAndGet(
  hubId: string,
  dr: DockRequest,
  actualUnits: number
): Promise<DockRequest> {
  await completeDockRequest(hubId, dr.id, dr.etag, actualUnits);
  return getDockRequest(hubId, dr.id);
}

export async function executeInboundFlow(
  hubId: string,
  consignmentId: string,
  plannedUnits: number,
  actualUnits?: number,
  priority: Priority = PRIORITIES.STANDARD
): Promise<{ dockRequest: DockRequest; consignment: Consignment }> {

  let dr = await createInboundDraft(hubId, consignmentId, plannedUnits, priority);

  dr = await submitAndGet(hubId, dr);

  dr = await scheduleAndGet(hubId, dr);

  dr = await completeAndGet(hubId, dr, actualUnits ?? plannedUnits);

  const consignment = await getConsignment(hubId, consignmentId);
  return { dockRequest: dr, consignment };
}

export async function executeOutboundFlow(
  hubId: string,
  consignmentId: string,
  plannedUnits: number,
  actualUnits?: number,
  priority: Priority = PRIORITIES.STANDARD
): Promise<{ dockRequest: DockRequest; consignment: Consignment }> {

  let dr = await createOutboundDraft(hubId, consignmentId, plannedUnits, priority);

  dr = await submitAndGet(hubId, dr);

  dr = await scheduleAndGet(hubId, dr);

  dr = await completeAndGet(hubId, dr, actualUnits ?? plannedUnits);

  const consignment = await getConsignment(hubId, consignmentId);
  return { dockRequest: dr, consignment };
}

export async function createConsignmentAtHub(
  hubId: string,
  declaredUnits: number,
  actualUnits?: number
): Promise<{ consignment: Consignment; inboundDockRequest: DockRequest }> {
  const consignment = await createPlannedConsignment(hubId, declaredUnits);
  const { dockRequest } = await executeInboundFlow(
    hubId,
    consignment.id,
    declaredUnits,
    actualUnits ?? declaredUnits
  );
  const updatedConsignment = await getConsignment(hubId, consignment.id);
  return { consignment: updatedConsignment, inboundDockRequest: dockRequest };
}

export async function fillHubToCongested(hub: Hub): Promise<{ consignment: Consignment; dockRequest: DockRequest }> {
  const threshold = Math.floor(hub.staging_capacity_units * 0.20);
  const fillAmount = hub.staging_capacity_units - threshold;

  const consignment = await createPlannedConsignment(hub.id, fillAmount);
  const { dockRequest } = await executeInboundFlow(hub.id, consignment.id, fillAmount);

  return { consignment, dockRequest };
}

export async function fillHubToLockdown(hub: Hub): Promise<{ consignment: Consignment; dockRequest: DockRequest }> {
  const fillAmount = hub.staging_capacity_units;

  const consignment = await createPlannedConsignment(hub.id, fillAmount);
  const { dockRequest } = await executeInboundFlow(hub.id, consignment.id, fillAmount);

  return { consignment, dockRequest };
}

export async function createConsignmentWithAutoVarianceHold(
  hubId: string,
  declaredUnits: number,
  actualUnits: number
): Promise<{ consignment: Consignment; dockRequest: DockRequest; hold: Hold }> {
  const consignment = await createPlannedConsignment(hubId, declaredUnits);
  const { dockRequest } = await executeInboundFlow(hubId, consignment.id, declaredUnits, actualUnits);

  if (!dockRequest.auto_hold_id) {
    throw new Error('Expected auto_hold_id from variance but none was created');
  }

  const hold = await getHold(hubId, dockRequest.auto_hold_id);
  const updatedConsignment = await getConsignment(hubId, consignment.id);

  return { consignment: updatedConsignment, dockRequest, hold };
}

export async function createReleasedConsignment(
  hubId: string,
  units: number
): Promise<{ consignment: Consignment; inboundDockRequest: DockRequest; outboundDockRequest: DockRequest }> {
  const { consignment, inboundDockRequest } = await createConsignmentAtHub(hubId, units);
  const { dockRequest: outboundDockRequest } = await executeOutboundFlow(hubId, consignment.id, units);
  const updatedConsignment = await getConsignment(hubId, consignment.id);

  return { consignment: updatedConsignment, inboundDockRequest, outboundDockRequest };
}

export async function createClosedConsignment(
  hubId: string,
  units: number
): Promise<{ consignment: Consignment; inboundDockRequest: DockRequest; outboundDockRequest: DockRequest }> {
  const result = await createReleasedConsignment(hubId, units);
  await runOps(hubId);
  const updatedConsignment = await getConsignment(hubId, result.consignment.id);

  return { ...result, consignment: updatedConsignment };
}

export async function createExpiredDockRequest(
  hubId: string,
  consignmentId: string,
  direction: Direction,
  units: number
): Promise<DockRequest> {
  let dr = await createDockRequest(hubId, {
    consignment_id: consignmentId,
    direction,
    units,
  });

  dr = await submitAndGet(hubId, dr);

  await runOps(hubId);
  await runOps(hubId);

  return getDockRequest(hubId, dr.id);
}
