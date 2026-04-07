import express, { Request, Response, NextFunction } from 'express';

type Commodity = 'GENERAL' | 'COLD_CHAIN' | 'HAZMAT';
type ConsignmentStatus = 'PLANNED' | 'AT_HUB' | 'RELEASED' | 'CLOSED' | 'VOIDED';
type DockRequestDirection = 'INBOUND' | 'OUTBOUND';
type DockRequestPriority = 'EXPEDITE' | 'STANDARD' | 'DEFERRED';
type DockRequestStatus = 'DRAFT' | 'SUBMITTED' | 'SCHEDULED' | 'ON_HOLD' | 'DONE' | 'CANCELLED' | 'EXPIRED' | 'VOIDED';
type HoldKind = 'DOCS' | 'DAMAGE' | 'TEMPERATURE' | 'CUSTOMS';
type HoldStatus = 'OPEN' | 'CLEARED' | 'VOIDED';
type HoldSource = 'MANUAL' | 'AUTO_VARIANCE';
type Posture = 'OPEN' | 'CONGESTED' | 'LOCKDOWN';

interface Hub {
  id: string;
  name: string;
  staging_capacity_units: number;
  ops_run_index: number;
  etag: string;
  dock_request_sequence: number;
}

interface Consignment {
  id: string;
  hub_id: string;
  reference: string;
  declared_units: number;
  commodity: Commodity;
  units_on_hand: number;
  status: ConsignmentStatus;
  has_had_receipt: boolean;
  etag: string;
}

interface DockRequest {
  id: string;
  hub_id: string;
  consignment_id: string;
  direction: DockRequestDirection;
  units: number;
  priority: DockRequestPriority;
  status: DockRequestStatus;
  sequence: number;
  actual_units?: number;
  variance_units?: number;
  ops_run_at_submit?: number;
  etag: string;
}

interface Hold {
  id: string;
  hub_id: string;
  consignment_id: string;
  kind: HoldKind;
  note: string;
  status: HoldStatus;
  source: HoldSource;
  source_dock_request_id?: string;
  etag: string;
}

interface ApiResponse<T = any> {
  response_type: 'success' | 'error';
  data?: T;
  error_code?: string;
  message?: string;
}

const hubs: Map<string, Hub> = new Map();
const consignments: Map<string, Consignment> = new Map();
const dockRequests: Map<string, DockRequest> = new Map();
const holds: Map<string, Hold> = new Map();

let globalIdCounter = 1;

function generateId(): string {
  return `id_${Date.now()}_${globalIdCounter++}`;
}

function generateEtag(): string {
  return `etag_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

function calculateStagingInUse(hubId: string): number {
  let total = 0;
  for (const c of consignments.values()) {
    if (c.hub_id === hubId && c.status !== 'VOIDED') {
      total += c.units_on_hand;
    }
  }
  return total;
}

function calculateStagingReserved(hubId: string): number {
  let total = 0;
  for (const dr of dockRequests.values()) {
    if (dr.hub_id === hubId && dr.direction === 'INBOUND' && dr.status === 'SCHEDULED') {
      total += dr.units;
    }
  }
  return total;
}

function calculateStagingFree(hub: Hub): number {
  const inUse = calculateStagingInUse(hub.id);
  const reserved = calculateStagingReserved(hub.id);
  return Math.max(0, hub.staging_capacity_units - inUse - reserved);
}

function calculatePosture(hub: Hub): Posture {
  const free = calculateStagingFree(hub);
  if (free === 0) return 'LOCKDOWN';
  const threshold = Math.floor(hub.staging_capacity_units * 0.2);
  if (free <= threshold) return 'CONGESTED';
  return 'OPEN';
}

function getHubResponse(hub: Hub) {
  const stagingInUse = calculateStagingInUse(hub.id);
  const stagingReserved = calculateStagingReserved(hub.id);
  const stagingFree = Math.max(0, hub.staging_capacity_units - stagingInUse - stagingReserved);
  return {
    id: hub.id,
    name: hub.name,
    staging_capacity_units: hub.staging_capacity_units,
    staging_in_use_units: stagingInUse,
    staging_reserved_units: stagingReserved,
    staging_free_units: stagingFree,
    posture: calculatePosture(hub),
    ops_run_index: hub.ops_run_index,
    etag: hub.etag,
  };
}

function getConsignmentResponse(c: Consignment) {
  return {
    id: c.id,
    hub_id: c.hub_id,
    reference: c.reference,
    declared_units: c.declared_units,
    commodity: c.commodity,
    units_on_hand: c.units_on_hand,
    status: c.status,
    etag: c.etag,
  };
}

function getDockRequestResponse(dr: DockRequest) {
  const resp: any = {
    id: dr.id,
    hub_id: dr.hub_id,
    consignment_id: dr.consignment_id,
    direction: dr.direction,
    units: dr.units,
    priority: dr.priority,
    status: dr.status,
    sequence: dr.sequence,
    etag: dr.etag,
  };
  if (dr.actual_units !== undefined) resp.actual_units = dr.actual_units;
  if (dr.variance_units !== undefined) resp.variance_units = dr.variance_units;
  return resp;
}

function getHoldResponse(h: Hold) {
  const resp: any = {
    id: h.id,
    hub_id: h.hub_id,
    consignment_id: h.consignment_id,
    kind: h.kind,
    note: h.note,
    status: h.status,
    source: h.source,
    etag: h.etag,
  };
  if (h.source_dock_request_id) resp.source_dock_request_id = h.source_dock_request_id;
  return resp;
}

function successResponse<T>(data: T): ApiResponse<T> {
  return { response_type: 'success', data };
}

function errorResponse(error_code: string, message: string): ApiResponse {
  return { response_type: 'error', error_code, message };
}

function hasOpenHolds(consignmentId: string): boolean {
  for (const h of holds.values()) {
    if (h.consignment_id === consignmentId && h.status === 'OPEN') {
      return true;
    }
  }
  return false;
}

function getOpenHoldsForConsignment(consignmentId: string): Hold[] {
  const result: Hold[] = [];
  for (const h of holds.values()) {
    if (h.consignment_id === consignmentId && h.status === 'OPEN') {
      result.push(h);
    }
  }
  return result;
}

function hasOpenMove(consignmentId: string): boolean {
  const openStatuses: DockRequestStatus[] = ['SUBMITTED', 'SCHEDULED', 'ON_HOLD'];
  for (const dr of dockRequests.values()) {
    if (dr.consignment_id === consignmentId && openStatuses.includes(dr.status)) {
      return true;
    }
  }
  return false;
}

function getOpenMoveForConsignment(consignmentId: string): DockRequest | undefined {
  const openStatuses: DockRequestStatus[] = ['SUBMITTED', 'SCHEDULED', 'ON_HOLD'];
  for (const dr of dockRequests.values()) {
    if (dr.consignment_id === consignmentId && openStatuses.includes(dr.status)) {
      return dr;
    }
  }
  return undefined;
}

function updateConsignmentStatus(consignment: Consignment): void {
  if (consignment.status === 'VOIDED') return;

  if (consignment.units_on_hand > 0) {
    consignment.status = 'AT_HUB';
  } else if (consignment.has_had_receipt) {

    const hasOpenWork = hasOpenMove(consignment.id);
    const hasHolds = hasOpenHolds(consignment.id);
    if (hasOpenWork || hasHolds) {
      consignment.status = 'RELEASED';
    } else if (consignment.status === 'CLOSED') {

    } else {
      consignment.status = 'RELEASED';
    }
  } else {
    consignment.status = 'PLANNED';
  }
  consignment.etag = generateEtag();
}

function reactivateClosedConsignment(consignment: Consignment): void {
  if (consignment.status === 'CLOSED') {
    if (consignment.units_on_hand > 0) {
      consignment.status = 'AT_HUB';
    } else if (consignment.has_had_receipt) {
      consignment.status = 'RELEASED';
    } else {
      consignment.status = 'PLANNED';
    }
    consignment.etag = generateEtag();
  }
}

function getDockRequestsForConsignment(consignmentId: string): DockRequest[] {
  const result: DockRequest[] = [];
  for (const dr of dockRequests.values()) {
    if (dr.consignment_id === consignmentId) {
      result.push(dr);
    }
  }
  return result;
}

function getHoldsForConsignment(consignmentId: string): Hold[] {
  const result: Hold[] = [];
  for (const h of holds.values()) {
    if (h.consignment_id === consignmentId) {
      result.push(h);
    }
  }
  return result;
}

const app = express();
app.use(express.json());

function asyncHandler(fn: (req: Request, res: Response, next: NextFunction) => Promise<any>) {
  return (req: Request, res: Response, next: NextFunction) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
}

app.post('/hubs', asyncHandler(async (req: Request, res: Response) => {
  const { name, staging_capacity_units } = req.body;

  if (!name || typeof name !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'name is required and must be a string'));
  }
  if (typeof staging_capacity_units !== 'number' || staging_capacity_units < 0 || !Number.isInteger(staging_capacity_units)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'staging_capacity_units is required and must be a non-negative integer'));
  }

  const hub: Hub = {
    id: generateId(),
    name,
    staging_capacity_units,
    ops_run_index: 0,
    etag: generateEtag(),
    dock_request_sequence: 0,
  };

  hubs.set(hub.id, hub);
  res.status(201).json(successResponse(getHubResponse(hub)));
}));

app.get('/hubs/:hub_id', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }
  res.json(successResponse(getHubResponse(hub)));
}));

app.post('/hubs/:hub_id/consignments', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { reference, declared_units, commodity } = req.body;

  if (!reference || typeof reference !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'reference is required and must be a string'));
  }
  if (typeof declared_units !== 'number' || declared_units < 0 || !Number.isInteger(declared_units)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'declared_units is required and must be a non-negative integer'));
  }
  const validCommodities: Commodity[] = ['GENERAL', 'COLD_CHAIN', 'HAZMAT'];
  if (!commodity || !validCommodities.includes(commodity)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'commodity is required and must be GENERAL, COLD_CHAIN, or HAZMAT'));
  }

  const consignment: Consignment = {
    id: generateId(),
    hub_id: hub.id,
    reference,
    declared_units,
    commodity,
    units_on_hand: 0,
    status: 'PLANNED',
    has_had_receipt: false,
    etag: generateEtag(),
  };

  consignments.set(consignment.id, consignment);
  res.status(201).json(successResponse(getConsignmentResponse(consignment)));
}));

app.get('/hubs/:hub_id/consignments/:consignment_id', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const consignment = consignments.get(req.params.consignment_id);
  if (!consignment || consignment.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Consignment not found'));
  }

  res.json(successResponse(getConsignmentResponse(consignment)));
}));

app.post('/hubs/:hub_id/consignments/:consignment_id/void', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const consignment = consignments.get(req.params.consignment_id);
  if (!consignment || consignment.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Consignment not found'));
  }

  if (consignment.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (consignment.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Consignment is already voided'));
  }

  if (consignment.units_on_hand !== 0) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot void consignment with units on hand'));
  }

  const drs = getDockRequestsForConsignment(consignment.id);
  for (const dr of drs) {
    if (dr.status !== 'DRAFT' && dr.status !== 'VOIDED' && dr.status !== 'CANCELLED') {
      return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot void consignment with active dock requests'));
    }
  }

  if (hasOpenHolds(consignment.id)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot void consignment with open holds'));
  }

  consignment.status = 'VOIDED';
  consignment.etag = generateEtag();

  res.json(successResponse(getConsignmentResponse(consignment)));
}));

app.post('/hubs/:hub_id/dock_requests', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { consignment_id, direction, units, priority } = req.body;

  const consignment = consignments.get(consignment_id);
  if (!consignment || consignment.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Consignment not found'));
  }

  if (consignment.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot create dock request for voided consignment'));
  }

  const validDirections: DockRequestDirection[] = ['INBOUND', 'OUTBOUND'];
  if (!direction || !validDirections.includes(direction)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'direction is required and must be INBOUND or OUTBOUND'));
  }

  if (typeof units !== 'number' || units <= 0 || !Number.isInteger(units)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'units is required and must be a positive integer'));
  }

  const validPriorities: DockRequestPriority[] = ['EXPEDITE', 'STANDARD', 'DEFERRED'];
  if (!priority || !validPriorities.includes(priority)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'priority is required and must be EXPEDITE, STANDARD, or DEFERRED'));
  }

  hub.dock_request_sequence++;

  const dockRequest: DockRequest = {
    id: generateId(),
    hub_id: hub.id,
    consignment_id,
    direction,
    units,
    priority,
    status: 'DRAFT',
    sequence: hub.dock_request_sequence,
    etag: generateEtag(),
  };

  dockRequests.set(dockRequest.id, dockRequest);
  res.status(201).json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.get('/hubs/:hub_id/dock_requests/:dock_request_id', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  res.json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.put('/hubs/:hub_id/dock_requests/:dock_request_id', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  if (dockRequest.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (dockRequest.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Can only update dock requests in DRAFT status'));
  }

  const { units, priority } = req.body;

  if (units !== undefined) {
    if (typeof units !== 'number' || units <= 0 || !Number.isInteger(units)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'units must be a positive integer'));
    }
    dockRequest.units = units;
  }

  if (priority !== undefined) {
    const validPriorities: DockRequestPriority[] = ['EXPEDITE', 'STANDARD', 'DEFERRED'];
    if (!validPriorities.includes(priority)) {
      return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'priority must be EXPEDITE, STANDARD, or DEFERRED'));
    }
    dockRequest.priority = priority;
  }

  dockRequest.etag = generateEtag();
  res.json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.post('/hubs/:hub_id/dock_requests/:dock_request_id/submit', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  if (dockRequest.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  const consignment = consignments.get(dockRequest.consignment_id)!;

  if (consignment.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Consignment is voided'));
  }

  const posture = calculatePosture(hub);
  const stagingFree = calculateStagingFree(hub);

  if (dockRequest.direction === 'INBOUND') {
    if (posture === 'LOCKDOWN') {
      return res.status(409).json(errorResponse('ERR_POSTURE_LOCKDOWN', 'Hub is in lockdown; inbound submissions blocked'));
    }

    if (posture === 'CONGESTED') {
      const maxAllowed = Math.max(1, Math.floor(stagingFree / 4));
      if (dockRequest.units > maxAllowed) {
        return res.status(409).json(errorResponse('ERR_CONGESTED_INBOUND_LIMIT', `Congested mode: inbound limited to ${maxAllowed} units`));
      }
    }

    if (consignment.has_had_receipt) {
      return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Consignment has already been received'));
    }
  }

  if (dockRequest.direction === 'OUTBOUND') {

    if (hasOpenHolds(dockRequest.consignment_id)) {
      return res.status(409).json(errorResponse('ERR_CONSIGNMENT_HAS_OPEN_HOLD', 'Consignment has open holds'));
    }

    if (consignment.units_on_hand < dockRequest.units) {
      return res.status(409).json(errorResponse('ERR_CONSIGNMENT_EMPTY', 'Not enough units on hand'));
    }
  }

  if (dockRequest.status !== 'DRAFT') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Dock request must be in DRAFT status to submit'));
  }

  if (hasOpenMove(dockRequest.consignment_id)) {
    return res.status(409).json(errorResponse('ERR_CONSIGNMENT_BUSY', 'Consignment already has an open move'));
  }

  dockRequest.status = 'SUBMITTED';
  dockRequest.ops_run_at_submit = hub.ops_run_index;
  dockRequest.etag = generateEtag();

  res.json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.post('/hubs/:hub_id/dock_requests/batch_schedule', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { dock_request_ids } = req.body;

  if (!Array.isArray(dock_request_ids)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'dock_request_ids must be an array'));
  }

  const requestsToSchedule: DockRequest[] = [];
  const rejected: { dock_request_id: string; error_code: string }[] = [];

  for (const id of dock_request_ids) {
    const dr = dockRequests.get(id);
    if (!dr || dr.hub_id !== hub.id) {
      rejected.push({ dock_request_id: id, error_code: 'ERR_NOT_FOUND' });
      continue;
    }
    if (dr.status !== 'SUBMITTED') {
      rejected.push({ dock_request_id: id, error_code: 'ERR_INVALID_STATE' });
      continue;
    }
    requestsToSchedule.push(dr);
  }

  const priorityOrder: Record<DockRequestPriority, number> = {
    'EXPEDITE': 0,
    'STANDARD': 1,
    'DEFERRED': 2,
  };

  requestsToSchedule.sort((a, b) => {
    const priorityDiff = priorityOrder[a.priority] - priorityOrder[b.priority];
    if (priorityDiff !== 0) return priorityDiff;
    return a.sequence - b.sequence;
  });

  const scheduled_ids: string[] = [];

  for (const dr of requestsToSchedule) {
    const consignment = consignments.get(dr.consignment_id)!;

    if (dr.direction === 'INBOUND') {
      const posture = calculatePosture(hub);
      if (posture === 'LOCKDOWN') {
        rejected.push({ dock_request_id: dr.id, error_code: 'ERR_POSTURE_LOCKDOWN' });
        continue;
      }
      const stagingFree = calculateStagingFree(hub);
      if (dr.units > stagingFree) {
        rejected.push({ dock_request_id: dr.id, error_code: 'ERR_CAPACITY_EXCEEDED' });
        continue;
      }
    } else {

      if (consignment.units_on_hand < dr.units) {
        rejected.push({ dock_request_id: dr.id, error_code: 'ERR_CONSIGNMENT_EMPTY' });
        continue;
      }
    }

    dr.status = 'SCHEDULED';
    dr.etag = generateEtag();
    scheduled_ids.push(dr.id);
  }

  res.json(successResponse({ scheduled_ids, rejected }));
}));

app.post('/hubs/:hub_id/dock_requests/:dock_request_id/cancel', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  if (dockRequest.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  const cancellableStatuses: DockRequestStatus[] = ['DRAFT', 'SUBMITTED', 'SCHEDULED', 'ON_HOLD'];
  if (!cancellableStatuses.includes(dockRequest.status)) {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Dock request cannot be cancelled in current status'));
  }

  dockRequest.status = 'CANCELLED';
  dockRequest.etag = generateEtag();

  res.json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.post('/hubs/:hub_id/dock_requests/:dock_request_id/complete', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  if (dockRequest.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (dockRequest.status !== 'SCHEDULED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Dock request must be SCHEDULED to complete'));
  }

  const { actual_units } = req.body;

  if (typeof actual_units !== 'number' || actual_units < 0 || !Number.isInteger(actual_units)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'actual_units is required and must be a non-negative integer'));
  }

  const consignment = consignments.get(dockRequest.consignment_id)!;

  if (dockRequest.direction === 'INBOUND') {

    const extraUnits = Math.max(0, actual_units - dockRequest.units);
    if (extraUnits > 0) {

      const currentFree = calculateStagingFree(hub);

      if (actual_units > currentFree + dockRequest.units) {
        return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Actual units exceed available capacity'));
      }
    }

    consignment.units_on_hand += actual_units;
    consignment.has_had_receipt = true;
  } else {

    if (actual_units > consignment.units_on_hand) {
      return res.status(409).json(errorResponse('ERR_CONSIGNMENT_EMPTY', 'Cannot remove more units than on hand'));
    }
    consignment.units_on_hand -= actual_units;
  }

  const variance = actual_units - dockRequest.units;
  dockRequest.actual_units = actual_units;
  dockRequest.variance_units = variance;
  dockRequest.status = 'DONE';
  dockRequest.etag = generateEtag();

  updateConsignmentStatus(consignment);

  let auto_hold_id: string | undefined;

  if (Math.abs(variance) >= 3) {
    const hold: Hold = {
      id: generateId(),
      hub_id: hub.id,
      consignment_id: consignment.id,
      kind: 'DAMAGE',
      note: `Auto-created due to variance of ${variance} units`,
      status: 'OPEN',
      source: 'AUTO_VARIANCE',
      source_dock_request_id: dockRequest.id,
      etag: generateEtag(),
    };
    holds.set(hold.id, hold);
    auto_hold_id = hold.id;

    for (const dr of dockRequests.values()) {
      if (dr.consignment_id === consignment.id && dr.direction === 'OUTBOUND') {
        if (['SUBMITTED', 'SCHEDULED'].includes(dr.status)) {
          dr.status = 'ON_HOLD';
          dr.etag = generateEtag();
        }
      }
    }

    reactivateClosedConsignment(consignment);
  }

  const response: any = getDockRequestResponse(dockRequest);
  if (auto_hold_id) {
    response.auto_hold_id = auto_hold_id;
  }

  res.json(successResponse(response));
}));

app.post('/hubs/:hub_id/dock_requests/:dock_request_id/void', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const dockRequest = dockRequests.get(req.params.dock_request_id);
  if (!dockRequest || dockRequest.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Dock request not found'));
  }

  if (dockRequest.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (dockRequest.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Dock request is already voided'));
  }

  const consignment = consignments.get(dockRequest.consignment_id)!;

  if (dockRequest.status === 'DONE') {
    if (dockRequest.direction === 'INBOUND') {

      const unitsToRemove = dockRequest.actual_units || 0;
      if (consignment.units_on_hand < unitsToRemove) {
        return res.status(409).json(errorResponse('ERR_CONSTRAINT_VIOLATION', 'Cannot void: would make units on hand negative'));
      }
      consignment.units_on_hand -= unitsToRemove;

      consignment.has_had_receipt = false;
    } else {

      const unitsToAdd = dockRequest.actual_units || 0;

      const stagingInUse = calculateStagingInUse(hub.id);
      const stagingReserved = calculateStagingReserved(hub.id);

      const newInUse = stagingInUse + unitsToAdd;
      if (newInUse + stagingReserved > hub.staging_capacity_units) {
        return res.status(409).json(errorResponse('ERR_CAPACITY_EXCEEDED', 'Cannot void: would exceed capacity'));
      }
      consignment.units_on_hand += unitsToAdd;
    }

    for (const h of holds.values()) {
      if (h.source_dock_request_id === dockRequest.id && h.status === 'OPEN') {
        h.status = 'VOIDED';
        h.etag = generateEtag();
      }
    }
  }

  dockRequest.status = 'VOIDED';
  dockRequest.etag = generateEtag();

  updateConsignmentStatus(consignment);

  res.json(successResponse(getDockRequestResponse(dockRequest)));
}));

app.post('/hubs/:hub_id/holds', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { consignment_id, kind, note } = req.body;

  const consignment = consignments.get(consignment_id);
  if (!consignment || consignment.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Consignment not found'));
  }

  if (consignment.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Cannot create hold for voided consignment'));
  }

  const validKinds: HoldKind[] = ['DOCS', 'DAMAGE', 'TEMPERATURE', 'CUSTOMS'];
  if (!kind || !validKinds.includes(kind)) {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'kind is required and must be DOCS, DAMAGE, TEMPERATURE, or CUSTOMS'));
  }

  if (typeof note !== 'string') {
    return res.status(400).json(errorResponse('ERR_BAD_REQUEST', 'note is required and must be a string'));
  }

  const hold: Hold = {
    id: generateId(),
    hub_id: hub.id,
    consignment_id,
    kind,
    note,
    status: 'OPEN',
    source: 'MANUAL',
    etag: generateEtag(),
  };

  holds.set(hold.id, hold);

  for (const dr of dockRequests.values()) {
    if (dr.consignment_id === consignment_id && dr.direction === 'OUTBOUND') {
      if (['SUBMITTED', 'SCHEDULED'].includes(dr.status)) {
        dr.status = 'ON_HOLD';
        dr.etag = generateEtag();
      }
    }
  }

  reactivateClosedConsignment(consignment);

  res.status(201).json(successResponse(getHoldResponse(hold)));
}));

app.get('/hubs/:hub_id/holds/:hold_id', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const hold = holds.get(req.params.hold_id);
  if (!hold || hold.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
  }

  res.json(successResponse(getHoldResponse(hold)));
}));

app.post('/hubs/:hub_id/holds/:hold_id/clear', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const hold = holds.get(req.params.hold_id);
  if (!hold || hold.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
  }

  if (hold.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (hold.status !== 'OPEN') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Hold is not in OPEN status'));
  }

  hold.status = 'CLEARED';
  hold.etag = generateEtag();

  if (!hasOpenHolds(hold.consignment_id)) {
    for (const dr of dockRequests.values()) {
      if (dr.consignment_id === hold.consignment_id && dr.status === 'ON_HOLD') {
        dr.status = 'SUBMITTED';
        dr.etag = generateEtag();
      }
    }
  }

  res.json(successResponse(getHoldResponse(hold)));
}));

app.post('/hubs/:hub_id/holds/:hold_id/void', asyncHandler(async (req: Request, res: Response) => {
  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const hold = holds.get(req.params.hold_id);
  if (!hold || hold.hub_id !== hub.id) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
  }

  if (hold.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  if (hold.status === 'VOIDED') {
    return res.status(409).json(errorResponse('ERR_INVALID_STATE', 'Hold is already voided'));
  }

  hold.status = 'VOIDED';
  hold.etag = generateEtag();

  if (!hasOpenHolds(hold.consignment_id)) {
    for (const dr of dockRequests.values()) {
      if (dr.consignment_id === hold.consignment_id && dr.status === 'ON_HOLD') {
        dr.status = 'SUBMITTED';
        dr.etag = generateEtag();
      }
    }
  }

  res.json(successResponse(getHoldResponse(hold)));
}));

app.post('/hubs/:hub_id/run_ops', asyncHandler(async (req: Request, res: Response) => {
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    return res.status(428).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const hub = hubs.get(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hub not found'));
  }

  if (hub.etag !== ifMatch) {
    return res.status(409).json(errorResponse('ERR_VERSION_CONFLICT', 'ETag mismatch'));
  }

  hub.ops_run_index++;
  hub.etag = generateEtag();

  const expired_request_ids: string[] = [];
  const closed_consignment_ids: string[] = [];

  for (const dr of dockRequests.values()) {
    if (dr.hub_id !== hub.id) continue;
    if (dr.status === 'SUBMITTED' || dr.status === 'ON_HOLD') {
      const runsSinceSubmit = hub.ops_run_index - (dr.ops_run_at_submit || 0);
      if (runsSinceSubmit >= 2) {
        dr.status = 'EXPIRED';
        dr.etag = generateEtag();
        expired_request_ids.push(dr.id);
      }
    }
  }

  for (const c of consignments.values()) {
    if (c.hub_id !== hub.id) continue;
    if (c.status === 'RELEASED') {
      const hasHolds = hasOpenHolds(c.id);
      const hasMove = hasOpenMove(c.id);
      if (!hasHolds && !hasMove) {
        c.status = 'CLOSED';
        c.etag = generateEtag();
        closed_consignment_ids.push(c.id);
      }
    }
  }

  res.json(successResponse({
    ops_run_index: hub.ops_run_index,
    expired_request_ids,
    closed_consignment_ids,
  }));
}));

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error(err);
  res.status(500).json(errorResponse('ERR_INTERNAL', 'Internal server error'));
});

if (require.main === module) {
  const PORT = Number(process.env.PORT ?? 3000);
  const HOST = process.env.HOST ?? '127.0.0.1';
  app.listen(PORT, HOST, () => {
    console.log(`DockOps Hub API listening on http://${HOST}:${PORT}`);
  });
}

export default app;
