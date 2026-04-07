import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';

// =============================================================================
// TYPES & ENUMS
// =============================================================================

type Trade = 'ELECTRICAL' | 'PLUMBING' | 'STRUCTURAL' | 'GENERAL';
type Zone = 'ZONE_A' | 'ZONE_B' | 'ZONE_C';
type Criticality = 'CRITICAL' | 'STANDARD';
type WorkItemStatus = 'DRAFT' | 'READY' | 'IN_PROGRESS' | 'DONE' | 'CANCELLED';
type PermitStatus = 'REQUESTED' | 'GRANTED' | 'REVOKED';
type InspectionKind = 'SAFETY' | 'QUALITY';
type InspectionStatus = 'PLANNED' | 'PASSED' | 'FAILED' | 'VOIDED';
type ChangeOrderStatus = 'PROPOSED' | 'APPROVED' | 'APPLIED' | 'CANCELLED';
type Posture = 'OPEN' | 'REVIEW' | 'STOP_WORK';
type ActorRole = 'FOREMAN' | 'INSPECTOR' | 'MANAGER';
type StartBlocker = 'POSTURE' | 'PERMIT' | 'ZONE' | 'CHANGE_ORDER' | 'SAFETY';

interface Project {
  id: string;
  name: string;
  labor_budget_hours: number;
  created_at: string;
}

interface WorkItem {
  id: string;
  project_id: string;
  title: string;
  trade: Trade;
  zone: Zone;
  criticality: Criticality;
  estimated_hours: number;
  actual_hours?: number;
  status: WorkItemStatus;
  etag: string;
  created_at: string;
}

interface Permit {
  id: string;
  project_id: string;
  trade: Trade;
  status: PermitStatus;
  replaces_permit_id?: string;
  created_at: string;
}

interface Inspection {
  id: string;
  project_id: string;
  work_item_id: string;
  kind: InspectionKind;
  status: InspectionStatus;
  created_at: string;
}

interface ChangeOrder {
  id: string;
  project_id: string;
  work_item_id: string;
  summary: string;
  labor_budget_hours_delta?: number;
  new_estimated_hours?: number;
  new_trade?: Trade;
  new_zone?: Zone;
  status: ChangeOrderStatus;
  etag: string;
  created_at: string;
}

interface IdempotencyRecord {
  key: string;
  requestHash: string;
  response: any;
  statusCode: number;
}

// =============================================================================
// IN-MEMORY STORAGE
// =============================================================================

const projects: Map<string, Project> = new Map();
const workItems: Map<string, WorkItem> = new Map();
const permits: Map<string, Permit> = new Map();
const inspections: Map<string, Inspection> = new Map();
const changeOrders: Map<string, ChangeOrder> = new Map();
const idempotencyStore: Map<string, IdempotencyRecord> = new Map();

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function generateEtag(): string {
  return uuidv4();
}

function successResponse(data: any): object {
  return { response_type: 'object', data };
}

function errorResponse(error_code: string, message: string): object {
  return { response_type: 'error', data: { error_code, message } };
}

function getProjectWorkItems(projectId: string): WorkItem[] {
  return Array.from(workItems.values()).filter(wi => wi.project_id === projectId);
}

function getProjectPermits(projectId: string): Permit[] {
  return Array.from(permits.values()).filter(p => p.project_id === projectId);
}

function getProjectInspections(projectId: string): Inspection[] {
  return Array.from(inspections.values()).filter(i => i.project_id === projectId);
}

function getProjectChangeOrders(projectId: string): ChangeOrder[] {
  return Array.from(changeOrders.values()).filter(co => co.project_id === projectId);
}

function getWorkItemInspections(workItemId: string): Inspection[] {
  return Array.from(inspections.values()).filter(i => i.work_item_id === workItemId);
}

function getWorkItemChangeOrders(workItemId: string): ChangeOrder[] {
  return Array.from(changeOrders.values()).filter(co => co.work_item_id === workItemId);
}

function isActiveWorkItem(wi: WorkItem): boolean {
  return wi.status !== 'DONE' && wi.status !== 'CANCELLED';
}

function getCurrentPermitForTrade(projectId: string, trade: Trade): Permit | undefined {
  const tradePermits = getProjectPermits(projectId)
    .filter(p => p.trade === trade)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return tradePermits[0];
}

function getLatestInspection(workItemId: string, kind: InspectionKind): Inspection | undefined {
  const workItemInspections = getWorkItemInspections(workItemId)
    .filter(i => i.kind === kind && i.status !== 'VOIDED')
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return workItemInspections[0];
}

function getLatestSafetyStatus(workItemId: string): InspectionStatus | null {
  const inspection = getLatestInspection(workItemId, 'SAFETY');
  return inspection ? inspection.status : null;
}

function getLatestQualityStatus(workItemId: string): InspectionStatus | null {
  const inspection = getLatestInspection(workItemId, 'QUALITY');
  return inspection ? inspection.status : null;
}

function isWorkItemFrozen(workItemId: string): boolean {
  const cos = getWorkItemChangeOrders(workItemId);
  return cos.some(co => co.status === 'APPROVED');
}

function getOpenChangeOrder(workItemId: string): ChangeOrder | undefined {
  const cos = getWorkItemChangeOrders(workItemId);
  return cos.find(co => co.status === 'PROPOSED' || co.status === 'APPROVED');
}

function calculateLaborReservedHours(projectId: string): number {
  return getProjectWorkItems(projectId)
    .filter(wi => wi.status === 'READY')
    .reduce((sum, wi) => sum + wi.estimated_hours, 0);
}

function calculateLaborCommittedHours(projectId: string): number {
  return getProjectWorkItems(projectId)
    .filter(wi => wi.status === 'IN_PROGRESS')
    .reduce((sum, wi) => sum + wi.estimated_hours, 0);
}

function calculateLaborUsedHours(projectId: string): number {
  return getProjectWorkItems(projectId)
    .filter(wi => wi.status === 'DONE')
    .reduce((sum, wi) => sum + (wi.actual_hours || 0), 0);
}

function calculateLaborAvailableHours(projectId: string): number {
  const project = projects.get(projectId);
  if (!project) return 0;
  const reserved = calculateLaborReservedHours(projectId);
  const committed = calculateLaborCommittedHours(projectId);
  const used = calculateLaborUsedHours(projectId);
  return project.labor_budget_hours - reserved - committed - used;
}

function calculatePosture(projectId: string): Posture {
  const activeWorkItems = getProjectWorkItems(projectId).filter(isActiveWorkItem);
  
  // Rule 1: STOP_WORK if any active work item has latest_safety_status=FAILED
  for (const wi of activeWorkItems) {
    const safetyStatus = getLatestSafetyStatus(wi.id);
    if (safetyStatus === 'FAILED') {
      return 'STOP_WORK';
    }
  }
  
  // Rule 2: STOP_WORK if a trade has a current permit in REVOKED and there's active work in READY or IN_PROGRESS
  const trades: Trade[] = ['ELECTRICAL', 'PLUMBING', 'STRUCTURAL'];
  for (const trade of trades) {
    const currentPermit = getCurrentPermitForTrade(projectId, trade);
    if (currentPermit && currentPermit.status === 'REVOKED') {
      const hasActiveWork = activeWorkItems.some(
        wi => wi.trade === trade && (wi.status === 'READY' || wi.status === 'IN_PROGRESS')
      );
      if (hasActiveWork) {
        return 'STOP_WORK';
      }
    }
  }
  
  // Rule 3: REVIEW if 2+ distinct active work items have latest_quality_status=FAILED
  const failedQualityCount = activeWorkItems.filter(wi => {
    const qualityStatus = getLatestQualityStatus(wi.id);
    return qualityStatus === 'FAILED';
  }).length;
  if (failedQualityCount >= 2) {
    return 'REVIEW';
  }
  
  // Rule 4: REVIEW if labor_available_hours < 20
  const availableHours = calculateLaborAvailableHours(projectId);
  if (availableHours < 20) {
    return 'REVIEW';
  }
  
  return 'OPEN';
}

function calculateStartBlockers(workItem: WorkItem): StartBlocker[] {
  const blockers: StartBlocker[] = [];
  const projectId = workItem.project_id;
  const posture = calculatePosture(projectId);
  
  // POSTURE blocker: if project is STOP_WORK, or if REVIEW and latest_safety_status is not PASSED
  if (posture === 'STOP_WORK') {
    blockers.push('POSTURE');
  } else if (posture === 'REVIEW') {
    const safetyStatus = getLatestSafetyStatus(workItem.id);
    if (safetyStatus !== 'PASSED') {
      blockers.push('SAFETY');
    }
  }
  
  // PERMIT blocker: non-GENERAL trades need a GRANTED permit
  if (workItem.trade !== 'GENERAL') {
    const currentPermit = getCurrentPermitForTrade(projectId, workItem.trade);
    if (!currentPermit || currentPermit.status !== 'GRANTED') {
      blockers.push('PERMIT');
    }
  }
  
  // ZONE blocker: check if zone is occupied by non-GENERAL work
  if (workItem.trade !== 'GENERAL') {
    const activeInZone = getProjectWorkItems(projectId).filter(
      wi => wi.id !== workItem.id && 
            wi.zone === workItem.zone && 
            wi.status === 'IN_PROGRESS' && 
            wi.trade !== 'GENERAL'
    );
    if (activeInZone.length > 0) {
      blockers.push('ZONE');
    }
  }
  
  // CHANGE_ORDER blocker: if work item is frozen
  if (isWorkItemFrozen(workItem.id)) {
    blockers.push('CHANGE_ORDER');
  }
  
  return blockers;
}

function isWorkItemStartable(workItem: WorkItem): boolean {
  if (workItem.status !== 'READY') return false;
  const blockers = calculateStartBlockers(workItem);
  return blockers.length === 0;
}

function hashRequest(body: any, params: any): string {
  return JSON.stringify({ body, params });
}

function validateTrade(trade: any): trade is Trade {
  return ['ELECTRICAL', 'PLUMBING', 'STRUCTURAL', 'GENERAL'].includes(trade);
}

function validateZone(zone: any): zone is Zone {
  return ['ZONE_A', 'ZONE_B', 'ZONE_C'].includes(zone);
}

function validateCriticality(criticality: any): criticality is Criticality {
  return ['CRITICAL', 'STANDARD'].includes(criticality);
}

function validateInspectionKind(kind: any): kind is InspectionKind {
  return ['SAFETY', 'QUALITY'].includes(kind);
}

function formatWorkItemResponse(wi: WorkItem): object {
  return {
    id: wi.id,
    project_id: wi.project_id,
    title: wi.title,
    trade: wi.trade,
    zone: wi.zone,
    criticality: wi.criticality,
    estimated_hours: wi.estimated_hours,
    actual_hours: wi.actual_hours,
    status: wi.status,
    is_startable: isWorkItemStartable(wi),
    start_blockers: calculateStartBlockers(wi),
    latest_safety_status: getLatestSafetyStatus(wi.id),
    latest_quality_status: getLatestQualityStatus(wi.id),
    etag: wi.etag,
    created_at: wi.created_at
  };
}

function formatProjectResponse(project: Project): object {
  const projectPermits = getProjectPermits(project.id).map(p => ({
    id: p.id,
    trade: p.trade,
    status: p.status,
    replaces_permit_id: p.replaces_permit_id ?? null
  }));
  
  return {
    id: project.id,
    name: project.name,
    labor_budget_hours: project.labor_budget_hours,
    labor_reserved_hours: calculateLaborReservedHours(project.id),
    labor_committed_hours: calculateLaborCommittedHours(project.id),
    labor_used_hours: calculateLaborUsedHours(project.id),
    labor_available_hours: calculateLaborAvailableHours(project.id),
    posture: calculatePosture(project.id),
    permits: projectPermits,
    created_at: project.created_at
  };
}

function formatChangeOrderResponse(co: ChangeOrder): object {
  return {
    id: co.id,
    project_id: co.project_id,
    work_item_id: co.work_item_id,
    summary: co.summary,
    labor_budget_hours_delta: co.labor_budget_hours_delta,
    new_estimated_hours: co.new_estimated_hours,
    new_trade: co.new_trade,
    new_zone: co.new_zone,
    status: co.status,
    etag: co.etag,
    created_at: co.created_at
  };
}

// =============================================================================
// EXPRESS APP SETUP
// =============================================================================

const app = express();
app.use(express.json());

// =============================================================================
// MIDDLEWARE
// =============================================================================

interface AuthenticatedRequest extends Request {
  actorRole?: ActorRole;
}

function authMiddleware(req: AuthenticatedRequest, res: Response, next: NextFunction): void {
  const role = req.headers['x-actor-role'] as string;
  if (!role) {
    res.status(401).json(errorResponse('ERR_UNAUTHENTICATED', 'Missing X-Actor-Role header'));
    return;
  }
  if (!['FOREMAN', 'INSPECTOR', 'MANAGER'].includes(role)) {
    res.status(401).json(errorResponse('ERR_UNAUTHENTICATED', 'Invalid X-Actor-Role header'));
    return;
  }
  req.actorRole = role as ActorRole;
  next();
}

function idempotencyMiddleware(req: AuthenticatedRequest, res: Response, next: NextFunction): void {
  if (req.method !== 'POST') {
    next();
    return;
  }
  
  const idempotencyKey = req.headers['idempotency-key'] as string;
  if (!idempotencyKey) {
    res.status(400).json(errorResponse('ERR_MISSING_IDEMPOTENCY_KEY', 'Missing Idempotency-Key header'));
    return;
  }
  
  const existing = idempotencyStore.get(idempotencyKey);
  if (existing) {
    const currentHash = hashRequest(req.body, req.params);
    if (existing.requestHash !== currentHash) {
      res.status(409).json(errorResponse('ERR_IDEMPOTENCY_REPLAY_MISMATCH', 'Idempotency key reused with different request'));
      return;
    }
    res.status(existing.statusCode).json(existing.response);
    return;
  }
  
  // Store the key temporarily to mark it as in-progress
  (req as any).idempotencyKey = idempotencyKey;
  (req as any).requestHash = hashRequest(req.body, req.params);
  
  next();
}

function storeIdempotencyResult(req: Request, statusCode: number, response: any): void {
  const idempotencyKey = (req as any).idempotencyKey;
  const requestHash = (req as any).requestHash;
  if (idempotencyKey && requestHash) {
    idempotencyStore.set(idempotencyKey, { key: idempotencyKey, requestHash, response, statusCode });
  }
}

app.use(authMiddleware);
app.use(idempotencyMiddleware);

// =============================================================================
// ROLE-BASED ACCESS CONTROL
// =============================================================================

const ROLE_PERMISSIONS: Record<string, ActorRole[]> = {
  // Projects
  'POST /projects': ['FOREMAN', 'MANAGER'],
  'GET /projects/:project_id': ['FOREMAN', 'INSPECTOR', 'MANAGER'],
  
  // Work Items
  'POST /projects/:project_id/work_items': ['FOREMAN', 'MANAGER'],
  'GET /projects/:project_id/work_items/:work_item_id': ['FOREMAN', 'INSPECTOR', 'MANAGER'],
  'POST /projects/:project_id/work_items/:work_item_id/ready': ['FOREMAN', 'MANAGER'],
  'POST /projects/:project_id/work_items/:work_item_id/start': ['FOREMAN', 'MANAGER'],
  'POST /projects/:project_id/work_items/:work_item_id/complete': ['FOREMAN', 'MANAGER'],
  'POST /projects/:project_id/work_items/:work_item_id/cancel': ['FOREMAN', 'MANAGER'],
  
  // Permits
  'POST /projects/:project_id/permits': ['FOREMAN', 'MANAGER'],
  'POST /projects/:project_id/permits/:permit_id/decide': ['MANAGER'],
  
  // Inspections
  'POST /projects/:project_id/inspections': ['INSPECTOR', 'MANAGER'],
  'POST /projects/:project_id/inspections/:inspection_id/submit': ['INSPECTOR', 'MANAGER'],
  'POST /projects/:project_id/inspections/:inspection_id/void': ['MANAGER'],
  
  // Change Orders
  'POST /projects/:project_id/change_orders': ['FOREMAN', 'MANAGER'],
  'GET /projects/:project_id/change_orders/:change_order_id': ['FOREMAN', 'INSPECTOR', 'MANAGER'],
  'POST /projects/:project_id/change_orders/:change_order_id/approve': ['MANAGER'],
  'POST /projects/:project_id/change_orders/:change_order_id/apply': ['MANAGER'],
  'POST /projects/:project_id/change_orders/:change_order_id/cancel': ['FOREMAN', 'MANAGER']
};

function checkPermission(req: AuthenticatedRequest, res: Response, routeKey: string): boolean {
  const allowedRoles = ROLE_PERMISSIONS[routeKey];
  if (!allowedRoles || !req.actorRole || !allowedRoles.includes(req.actorRole)) {
    res.status(403).json(errorResponse('ERR_FORBIDDEN', 'Operation not allowed for this role'));
    return false;
  }
  return true;
}

// =============================================================================
// PROJECT ENDPOINTS
// =============================================================================

app.post('/projects', (req: AuthenticatedRequest, res: Response) => {
  if (!checkPermission(req, res, 'POST /projects')) return;
  
  const { name, labor_budget_hours } = req.body;
  
  if (!name || typeof name !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid name');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (typeof labor_budget_hours !== 'number' || labor_budget_hours < 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid labor_budget_hours');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  const project: Project = {
    id: uuidv4(),
    name,
    labor_budget_hours,
    created_at: new Date().toISOString()
  };
  
  projects.set(project.id, project);
  
  const response = successResponse(formatProjectResponse(project));
  storeIdempotencyResult(req, 201, response);
  res.status(201).json(response);
});

app.get('/projects/:project_id', (req: AuthenticatedRequest, res: Response) => {
  if (!checkPermission(req, res, 'GET /projects/:project_id')) return;
  
  const project = projects.get(req.params.project_id);
  if (!project) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Project not found'));
    return;
  }
  
  res.status(200).json(successResponse(formatProjectResponse(project)));
});

// =============================================================================
// WORK ITEM ENDPOINTS
// =============================================================================

app.post('/projects/:project_id/work_items', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/work_items')) return;
  
  // Check posture - creating work items is blocked in STOP_WORK
  const posture = calculatePosture(project.id);
  if (posture === 'STOP_WORK') {
    const response = errorResponse('ERR_POSTURE_BLOCKED', 'Project is in STOP_WORK posture');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  const { title, trade, zone, criticality, estimated_hours } = req.body;
  
  if (!title || typeof title !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid title');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (!validateTrade(trade)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid trade');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (!validateZone(zone)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid zone');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (!validateCriticality(criticality)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid criticality');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (typeof estimated_hours !== 'number' || estimated_hours < 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid estimated_hours');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  const workItem: WorkItem = {
    id: uuidv4(),
    project_id: project.id,
    title,
    trade,
    zone,
    criticality,
    estimated_hours,
    status: 'DRAFT',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };
  
  workItems.set(workItem.id, workItem);
  
  const response = successResponse(formatWorkItemResponse(workItem));
  storeIdempotencyResult(req, 201, response);
  res.status(201).json(response);
});

app.get('/projects/:project_id/work_items/:work_item_id', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Project not found'));
    return;
  }
  
  if (!checkPermission(req, res, 'GET /projects/:project_id/work_items/:work_item_id')) return;
  
  const workItem = workItems.get(req.params.work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Work item not found'));
    return;
  }
  
  res.status(200).json(successResponse(formatWorkItemResponse(workItem)));
});

app.post('/projects/:project_id/work_items/:work_item_id/ready', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const workItem = workItems.get(req.params.work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/work_items/:work_item_id/ready')) return;
  
  // Check posture
  const posture = calculatePosture(project.id);
  if (posture === 'STOP_WORK') {
    const response = errorResponse('ERR_POSTURE_BLOCKED', 'Project is in STOP_WORK posture');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== workItem.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  // Check state
  if (workItem.status !== 'DRAFT') {
    const response = errorResponse('ERR_INVALID_STATE', 'Work item must be in DRAFT status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check if frozen
  if (isWorkItemFrozen(workItem.id)) {
    const response = errorResponse('ERR_WORK_ITEM_FROZEN', 'Work item is frozen by an approved change order');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check permit requirement for non-GENERAL trades
  if (workItem.trade !== 'GENERAL') {
    const currentPermit = getCurrentPermitForTrade(project.id, workItem.trade);
    if (!currentPermit || currentPermit.status !== 'GRANTED') {
      const response = errorResponse('ERR_PERMIT_REQUIRED', `A GRANTED permit is required for ${workItem.trade} work`);
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Check labor budget
  const availableHours = calculateLaborAvailableHours(project.id);
  if (workItem.estimated_hours > availableHours) {
    const response = errorResponse('ERR_LABOR_BUDGET_EXCEEDED', 'Moving to READY would exceed labor budget');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  workItem.status = 'READY';
  workItem.etag = generateEtag();
  workItems.set(workItem.id, workItem);
  
  const response = successResponse(formatWorkItemResponse(workItem));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/work_items/:work_item_id/start', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const workItem = workItems.get(req.params.work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/work_items/:work_item_id/start')) return;
  
  // Check posture
  const posture = calculatePosture(project.id);
  if (posture === 'STOP_WORK') {
    const response = errorResponse('ERR_POSTURE_BLOCKED', 'Project is in STOP_WORK posture');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== workItem.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  // Check state
  if (workItem.status !== 'READY') {
    const response = errorResponse('ERR_INVALID_STATE', 'Work item must be in READY status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check if frozen
  if (isWorkItemFrozen(workItem.id)) {
    const response = errorResponse('ERR_WORK_ITEM_FROZEN', 'Work item is frozen by an approved change order');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check REVIEW posture requires PASSED safety
  if (posture === 'REVIEW') {
    const safetyStatus = getLatestSafetyStatus(workItem.id);
    if (safetyStatus !== 'PASSED') {
      const response = errorResponse('ERR_POSTURE_BLOCKED', 'Project is in REVIEW and work item does not have PASSED safety inspection');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Check permit requirement for non-GENERAL trades
  if (workItem.trade !== 'GENERAL') {
    const currentPermit = getCurrentPermitForTrade(project.id, workItem.trade);
    if (!currentPermit || currentPermit.status !== 'GRANTED') {
      const response = errorResponse('ERR_PERMIT_REQUIRED', `A GRANTED permit is required for ${workItem.trade} work`);
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Check zone occupancy (non-GENERAL only)
  if (workItem.trade !== 'GENERAL') {
    const occupiedInZone = getProjectWorkItems(project.id).filter(
      wi => wi.id !== workItem.id && 
            wi.zone === workItem.zone && 
            wi.status === 'IN_PROGRESS' && 
            wi.trade !== 'GENERAL'
    );
    if (occupiedInZone.length > 0) {
      const response = errorResponse('ERR_ZONE_OCCUPIED', `Zone ${workItem.zone} is already occupied`);
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  workItem.status = 'IN_PROGRESS';
  workItem.etag = generateEtag();
  workItems.set(workItem.id, workItem);
  
  const response = successResponse(formatWorkItemResponse(workItem));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/work_items/:work_item_id/complete', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const workItem = workItems.get(req.params.work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/work_items/:work_item_id/complete')) return;
  
  // Check posture
  const posture = calculatePosture(project.id);
  if (posture === 'STOP_WORK') {
    const response = errorResponse('ERR_POSTURE_BLOCKED', 'Project is in STOP_WORK posture');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== workItem.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  // Check state
  if (workItem.status !== 'IN_PROGRESS') {
    const response = errorResponse('ERR_INVALID_STATE', 'Work item must be in IN_PROGRESS status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  // Check if frozen
  if (isWorkItemFrozen(workItem.id)) {
    const response = errorResponse('ERR_WORK_ITEM_FROZEN', 'Work item is frozen by an approved change order');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  const { actual_hours } = req.body;
  
  if (typeof actual_hours !== 'number' || actual_hours < 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid actual_hours');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  // Check quality for CRITICAL items
  if (workItem.criticality === 'CRITICAL') {
    const qualityStatus = getLatestQualityStatus(workItem.id);
    if (qualityStatus !== 'PASSED') {
      const response = errorResponse('ERR_QUALITY_FAILED_BLOCKING', 'CRITICAL work items require PASSED quality inspection');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  } else {
    // Non-critical: check for FAILED quality
    const qualityStatus = getLatestQualityStatus(workItem.id);
    if (qualityStatus === 'FAILED') {
      const response = errorResponse('ERR_QUALITY_FAILED_BLOCKING', 'Work item has FAILED quality inspection');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Check labor budget - completing releases committed hours but adds actual_hours to used
  // Current committed will be released, but actual_hours will be added to used
  // Available after = budget - reserved - (committed - estimated_hours) - (used + actual_hours)
  // Simplify: we need to check if (used + actual_hours) + reserved + (committed - estimated_hours) <= budget
  const reserved = calculateLaborReservedHours(project.id);
  const committed = calculateLaborCommittedHours(project.id);
  const used = calculateLaborUsedHours(project.id);
  
  const newCommitted = committed - workItem.estimated_hours;
  const newUsed = used + actual_hours;
  const newAvailable = project.labor_budget_hours - reserved - newCommitted - newUsed;
  
  if (newAvailable < 0) {
    const response = errorResponse('ERR_LABOR_BUDGET_EXCEEDED', 'Completion would exceed labor budget');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  workItem.status = 'DONE';
  workItem.actual_hours = actual_hours;
  workItem.etag = generateEtag();
  workItems.set(workItem.id, workItem);
  
  const response = successResponse(formatWorkItemResponse(workItem));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/work_items/:work_item_id/cancel', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const workItem = workItems.get(req.params.work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/work_items/:work_item_id/cancel')) return;
  
  // Cancellation is allowed even in STOP_WORK (recovery action)
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== workItem.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  // Check state - can cancel from DRAFT, READY, or IN_PROGRESS
  if (!['DRAFT', 'READY', 'IN_PROGRESS'].includes(workItem.status)) {
    const response = errorResponse('ERR_INVALID_STATE', 'Work item cannot be cancelled from this status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  workItem.status = 'CANCELLED';
  workItem.etag = generateEtag();
  workItems.set(workItem.id, workItem);
  
  // Cancel any open change orders for this work item
  const openChangeOrders = getWorkItemChangeOrders(workItem.id)
    .filter(co => co.status === 'PROPOSED' || co.status === 'APPROVED');
  for (const co of openChangeOrders) {
    co.status = 'CANCELLED';
    co.etag = generateEtag();
    changeOrders.set(co.id, co);
  }
  
  const response = successResponse(formatWorkItemResponse(workItem));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

// =============================================================================
// PERMIT ENDPOINTS
// =============================================================================

app.post('/projects/:project_id/permits', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/permits')) return;
  
  const { trade, replaces_permit_id } = req.body;
  
  if (!validateTrade(trade)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid trade');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  const currentPermit = getCurrentPermitForTrade(project.id, trade);
  
  if (currentPermit) {
    if (currentPermit.status !== 'REVOKED') {
      const response = errorResponse('ERR_PERMIT_ALREADY_EXISTS', `A permit for ${trade} already exists and is not revoked`);
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
    
    // Current permit is revoked, need replaces_permit_id
    if (!replaces_permit_id) {
      const response = errorResponse('ERR_PERMIT_REPLACEMENT_REQUIRED', 'replaces_permit_id is required when replacing a revoked permit');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
    
    if (replaces_permit_id !== currentPermit.id) {
      const response = errorResponse('ERR_BAD_REQUEST', 'replaces_permit_id does not match the current revoked permit');
      storeIdempotencyResult(req, 400, response);
      res.status(400).json(response);
      return;
    }
  }
  
  const permit: Permit = {
    id: uuidv4(),
    project_id: project.id,
    trade,
    status: 'REQUESTED',
    replaces_permit_id,
    created_at: new Date().toISOString()
  };
  
  permits.set(permit.id, permit);
  
  const response = successResponse({
    id: permit.id,
    project_id: permit.project_id,
    trade: permit.trade,
    status: permit.status,
    replaces_permit_id: permit.replaces_permit_id,
    created_at: permit.created_at
  });
  storeIdempotencyResult(req, 201, response);
  res.status(201).json(response);
});

app.post('/projects/:project_id/permits/:permit_id/decide', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const permit = permits.get(req.params.permit_id);
  if (!permit || permit.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Permit not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/permits/:permit_id/decide')) return;
  
  // Permit decisions are allowed even in STOP_WORK (recovery action)
  
  const { decision } = req.body;
  
  if (!['GRANT', 'REVOKE'].includes(decision)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid decision, must be GRANT or REVOKE');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }

  if (decision === 'GRANT') {
    if (permit.status !== 'REQUESTED') {
      const response = errorResponse('ERR_INVALID_STATE', 'Permit can only be GRANTED from REQUESTED');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
    permit.status = 'GRANTED';
  } else {
    // REVOKE is allowed from REQUESTED or GRANTED; REVOKED is terminal.
    if (permit.status === 'REVOKED') {
      const response = errorResponse('ERR_INVALID_STATE', 'Permit is already REVOKED');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
    permit.status = 'REVOKED';
  }
  permits.set(permit.id, permit);
  
  const response = successResponse({
    id: permit.id,
    project_id: permit.project_id,
    trade: permit.trade,
    status: permit.status,
    replaces_permit_id: permit.replaces_permit_id,
    created_at: permit.created_at
  });
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

// =============================================================================
// INSPECTION ENDPOINTS
// =============================================================================

app.post('/projects/:project_id/inspections', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const { work_item_id, kind } = req.body;
  
  const workItem = workItems.get(work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/inspections')) return;
  
  // Inspections can be created even in STOP_WORK (recovery action)
  
  if (!validateInspectionKind(kind)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid kind, must be SAFETY or QUALITY');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  // Check for existing PLANNED inspection of same kind
  const existingPlanned = getWorkItemInspections(work_item_id)
    .find(i => i.kind === kind && i.status === 'PLANNED');
  
  if (existingPlanned) {
    const response = errorResponse('ERR_INSPECTION_ALREADY_PLANNED', `A ${kind} inspection is already planned for this work item`);
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  const inspection: Inspection = {
    id: uuidv4(),
    project_id: project.id,
    work_item_id,
    kind,
    status: 'PLANNED',
    created_at: new Date().toISOString()
  };
  
  inspections.set(inspection.id, inspection);
  
  const response = successResponse({
    id: inspection.id,
    project_id: inspection.project_id,
    work_item_id: inspection.work_item_id,
    kind: inspection.kind,
    status: inspection.status,
    created_at: inspection.created_at
  });
  storeIdempotencyResult(req, 201, response);
  res.status(201).json(response);
});

app.post('/projects/:project_id/inspections/:inspection_id/submit', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const inspection = inspections.get(req.params.inspection_id);
  if (!inspection || inspection.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Inspection not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/inspections/:inspection_id/submit')) return;
  
  // Submitting inspections is allowed even in STOP_WORK (recovery action)
  
  const { outcome } = req.body;
  
  if (!['PASSED', 'FAILED'].includes(outcome)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid outcome, must be PASSED or FAILED');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (inspection.status !== 'PLANNED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Inspection must be in PLANNED status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  inspection.status = outcome as InspectionStatus;
  inspections.set(inspection.id, inspection);
  
  const response = successResponse({
    id: inspection.id,
    project_id: inspection.project_id,
    work_item_id: inspection.work_item_id,
    kind: inspection.kind,
    status: inspection.status,
    created_at: inspection.created_at
  });
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/inspections/:inspection_id/void', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const inspection = inspections.get(req.params.inspection_id);
  if (!inspection || inspection.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Inspection not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/inspections/:inspection_id/void')) return;
  
  // Voiding inspections is allowed even in STOP_WORK (recovery action)
  
  if (inspection.status === 'VOIDED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Inspection is already voided');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  inspection.status = 'VOIDED';
  inspections.set(inspection.id, inspection);
  
  const response = successResponse({
    id: inspection.id,
    project_id: inspection.project_id,
    work_item_id: inspection.work_item_id,
    kind: inspection.kind,
    status: inspection.status,
    created_at: inspection.created_at
  });
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

// =============================================================================
// CHANGE ORDER ENDPOINTS
// =============================================================================

app.post('/projects/:project_id/change_orders', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const { work_item_id, summary, labor_budget_hours_delta, new_estimated_hours, new_trade, new_zone } = req.body;
  
  const workItem = workItems.get(work_item_id);
  if (!workItem || workItem.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Work item not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/change_orders')) return;
  
  // Creating change orders is allowed even in STOP_WORK (recovery action)
  
  if (!summary || typeof summary !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'Missing or invalid summary');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (labor_budget_hours_delta !== undefined && typeof labor_budget_hours_delta !== 'number') {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid labor_budget_hours_delta');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (new_estimated_hours !== undefined && (typeof new_estimated_hours !== 'number' || new_estimated_hours < 0)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid new_estimated_hours');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (new_trade !== undefined && !validateTrade(new_trade)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid new_trade');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  if (new_zone !== undefined && !validateZone(new_zone)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'Invalid new_zone');
    storeIdempotencyResult(req, 400, response);
    res.status(400).json(response);
    return;
  }
  
  // Check for existing open change order
  const existingOpen = getOpenChangeOrder(work_item_id);
  if (existingOpen) {
    const response = errorResponse('ERR_CHANGE_ORDER_CONFLICT', 'Work item already has an open change order');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  const changeOrder: ChangeOrder = {
    id: uuidv4(),
    project_id: project.id,
    work_item_id,
    summary,
    labor_budget_hours_delta,
    new_estimated_hours,
    new_trade,
    new_zone,
    status: 'PROPOSED',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };
  
  changeOrders.set(changeOrder.id, changeOrder);
  
  const response = successResponse(formatChangeOrderResponse(changeOrder));
  storeIdempotencyResult(req, 201, response);
  res.status(201).json(response);
});

app.get('/projects/:project_id/change_orders/:change_order_id', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Project not found'));
    return;
  }
  
  if (!checkPermission(req, res, 'GET /projects/:project_id/change_orders/:change_order_id')) return;
  
  const changeOrder = changeOrders.get(req.params.change_order_id);
  if (!changeOrder || changeOrder.project_id !== project.id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Change order not found'));
    return;
  }
  
  res.status(200).json(successResponse(formatChangeOrderResponse(changeOrder)));
});

app.post('/projects/:project_id/change_orders/:change_order_id/approve', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const changeOrder = changeOrders.get(req.params.change_order_id);
  if (!changeOrder || changeOrder.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Change order not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/change_orders/:change_order_id/approve')) return;
  
  // Approving change orders is allowed even in STOP_WORK (recovery action)
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== changeOrder.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  if (changeOrder.status !== 'PROPOSED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Change order must be in PROPOSED status');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  changeOrder.status = 'APPROVED';
  changeOrder.etag = generateEtag();
  changeOrders.set(changeOrder.id, changeOrder);
  
  const response = successResponse(formatChangeOrderResponse(changeOrder));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/change_orders/:change_order_id/apply', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const changeOrder = changeOrders.get(req.params.change_order_id);
  if (!changeOrder || changeOrder.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Change order not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/change_orders/:change_order_id/apply')) return;
  
  // Applying change orders is allowed even in STOP_WORK (recovery action)
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== changeOrder.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  if (changeOrder.status !== 'APPROVED') {
    const response = errorResponse('ERR_CHANGE_ORDER_NOT_APPROVED', 'Change order must be APPROVED before applying');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  const workItem = workItems.get(changeOrder.work_item_id)!;
  
  // Check scope change constraints
  const hasScopeChange = changeOrder.new_estimated_hours !== undefined || 
                          changeOrder.new_trade !== undefined || 
                          changeOrder.new_zone !== undefined;
  
  if (hasScopeChange) {
    if (workItem.status === 'IN_PROGRESS' || workItem.status === 'DONE') {
      const response = errorResponse('ERR_SCOPE_CHANGE_NOT_ALLOWED', 'Scope changes not allowed for IN_PROGRESS or DONE work items');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Check budget change constraints
  if (changeOrder.labor_budget_hours_delta !== undefined) {
    const newBudget = project.labor_budget_hours + changeOrder.labor_budget_hours_delta;
    const reserved = calculateLaborReservedHours(project.id);
    const committed = calculateLaborCommittedHours(project.id);
    const used = calculateLaborUsedHours(project.id);
    
    // Account for potential scope change releasing reserved hours
    let adjustedReserved = reserved;
    if (hasScopeChange && workItem.status === 'READY') {
      adjustedReserved -= workItem.estimated_hours;
    }
    
    if (newBudget < adjustedReserved + committed + used) {
      const response = errorResponse('ERR_LABOR_BUDGET_EXCEEDED', 'Budget change would drop below committed/used hours');
      storeIdempotencyResult(req, 409, response);
      res.status(409).json(response);
      return;
    }
  }
  
  // Apply changes
  if (changeOrder.labor_budget_hours_delta !== undefined) {
    project.labor_budget_hours += changeOrder.labor_budget_hours_delta;
    projects.set(project.id, project);
  }
  
  if (hasScopeChange) {
    if (changeOrder.new_estimated_hours !== undefined) {
      workItem.estimated_hours = changeOrder.new_estimated_hours;
    }
    if (changeOrder.new_trade !== undefined) {
      workItem.trade = changeOrder.new_trade;
    }
    if (changeOrder.new_zone !== undefined) {
      workItem.zone = changeOrder.new_zone;
    }
    
    // Reset to DRAFT and void inspections
    workItem.status = 'DRAFT';
    workItem.etag = generateEtag();
    workItems.set(workItem.id, workItem);
    
    // Void all inspections for this work item
    const workItemInspections = getWorkItemInspections(workItem.id);
    for (const insp of workItemInspections) {
      if (insp.status !== 'VOIDED') {
        insp.status = 'VOIDED';
        inspections.set(insp.id, insp);
      }
    }
  }
  
  changeOrder.status = 'APPLIED';
  changeOrder.etag = generateEtag();
  changeOrders.set(changeOrder.id, changeOrder);
  
  const response = successResponse(formatChangeOrderResponse(changeOrder));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

app.post('/projects/:project_id/change_orders/:change_order_id/cancel', (req: AuthenticatedRequest, res: Response) => {
  const project = projects.get(req.params.project_id);
  if (!project) {
    const response = errorResponse('ERR_NOT_FOUND', 'Project not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  const changeOrder = changeOrders.get(req.params.change_order_id);
  if (!changeOrder || changeOrder.project_id !== project.id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Change order not found');
    storeIdempotencyResult(req, 404, response);
    res.status(404).json(response);
    return;
  }
  
  if (!checkPermission(req, res, 'POST /projects/:project_id/change_orders/:change_order_id/cancel')) return;
  
  // Cancelling change orders is allowed even in STOP_WORK (recovery action)
  
  // Check If-Match
  const ifMatch = req.headers['if-match'] as string;
  if (!ifMatch) {
    const response = errorResponse('ERR_MISSING_IF_MATCH', 'Missing If-Match header');
    storeIdempotencyResult(req, 428, response);
    res.status(428).json(response);
    return;
  }
  
  if (ifMatch !== changeOrder.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag mismatch');
    storeIdempotencyResult(req, 412, response);
    res.status(412).json(response);
    return;
  }
  
  if (changeOrder.status !== 'PROPOSED' && changeOrder.status !== 'APPROVED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Change order must be PROPOSED or APPROVED to cancel');
    storeIdempotencyResult(req, 409, response);
    res.status(409).json(response);
    return;
  }
  
  changeOrder.status = 'CANCELLED';
  changeOrder.etag = generateEtag();
  changeOrders.set(changeOrder.id, changeOrder);
  
  const response = successResponse(formatChangeOrderResponse(changeOrder));
  storeIdempotencyResult(req, 200, response);
  res.status(200).json(response);
});

// =============================================================================
// SERVER STARTUP
// =============================================================================

const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '127.0.0.1';

app.listen(Number(PORT), HOST, () => {
  console.log(`SiteLedger API running on http://${HOST}:${PORT}`);
});

export default app;
