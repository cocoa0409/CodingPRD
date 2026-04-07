import express, { Request, Response, NextFunction } from 'express';

type WorkspacePosture = 'NORMAL' | 'REVIEW' | 'LOCKDOWN';

type MatterType = 'LITIGATION' | 'INVESTIGATION';
type MatterStatus = 'DRAFT' | 'ACTIVE' | 'CLOSED';
type MatterPosture = 'OPEN' | 'REVIEW' | 'FROZEN';

type CustodianStatus = 'ACTIVE' | 'DEPARTED' | 'PURGED';

type LegalBasis = 'LITIGATION' | 'REGULATORY' | 'CONTRACT';
type HoldScope = 'ALL_DATA' | 'EMAIL_ONLY' | 'CHAT_ONLY' | 'DRIVE_ONLY';
type HoldStatus = 'DRAFT' | 'ISSUED' | 'ACTIVE' | 'SUSPENDED' | 'RELEASED' | 'VOID';

type DataSource = 'EMAIL' | 'CHAT' | 'DRIVE';
type CollectionStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'IN_PROGRESS' | 'DELIVERED' | 'WITHDRAWN' | 'REJECTED';

type ErrorCode =
  | 'ERR_BAD_REQUEST'
  | 'ERR_NOT_FOUND'
  | 'ERR_MISSING_IDEMPOTENCY_KEY'
  | 'ERR_MISSING_IF_MATCH'
  | 'ERR_IDEMPOTENCY_REPLAY_MISMATCH'
  | 'ERR_ETAG_MISMATCH'
  | 'ERR_POSTURE_BLOCKED'
  | 'ERR_INVALID_STATE'
  | 'ERR_QUOTA_EXCEEDED'
  | 'ERR_HOLD_SCOPE_MISMATCH'
  | 'ERR_HOLD_NOT_ACTIVE'
  | 'ERR_CUSTODIAN_NOT_IN_HOLD'
  | 'ERR_CUSTODIAN_DEPARTED'
  | 'ERR_CUSTODIAN_PURGED'
  | 'ERR_COURT_ORDERED_RESTRICTION'
  | 'ERR_MATTER_HAS_ACTIVE_HOLDS'
  | 'ERR_MATTER_HAS_PENDING_COLLECTIONS';

interface Workspace {
  id: string;
  name: string;
  quota_bytes: number;
  etag: string;
  created_at: string;
}

interface Matter {
  id: string;
  workspace_id: string;
  title: string;
  matter_type: MatterType;
  status: MatterStatus;
  etag: string;
  created_at: string;
}

interface Custodian {
  id: string;
  matter_id: string;
  full_name: string;
  email: string;
  status: CustodianStatus;
  etag: string;
  created_at: string;
}

interface Hold {
  id: string;
  matter_id: string;
  title: string;
  legal_basis: LegalBasis;
  scope: HoldScope;
  is_court_ordered: boolean;
  custodian_ids: string[];
  status: HoldStatus;
  etag: string;
  created_at: string;
}

interface Collection {
  id: string;
  matter_id: string;
  hold_id: string;
  custodian_id: string;
  data_source: DataSource;
  estimated_bytes: number;
  actual_bytes?: number;
  status: CollectionStatus;
  etag: string;
  created_at: string;
}

interface IdempotencyRecord {
  key: string;
  method: string;
  path: string;
  body: string;
  response: any;
}

const workspaces: Map<string, Workspace> = new Map();
const matters: Map<string, Matter> = new Map();
const custodians: Map<string, Custodian> = new Map();
const holds: Map<string, Hold> = new Map();
const collections: Map<string, Collection> = new Map();
const idempotencyStore: Map<string, IdempotencyRecord> = new Map();

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

function generateEtag(): string {
  return `"${Date.now()}-${Math.random().toString(36).substr(2, 9)}"`;
}

function successResponse(data: any, type: 'object' | 'array' = 'object'): object {
  return {
    response_type: type,
    data
  };
}

function errorResponse(error_code: ErrorCode, message: string): object {
  return {
    response_type: 'error',
    data: { error_code, message }
  };
}

function getCollectionsForMatter(matterId: string): Collection[] {
  return Array.from(collections.values()).filter(c => c.matter_id === matterId);
}

function getCollectionsForWorkspace(workspaceId: string): Collection[] {
  const matterIds = Array.from(matters.values())
    .filter(m => m.workspace_id === workspaceId)
    .map(m => m.id);
  return Array.from(collections.values()).filter(c => matterIds.includes(c.matter_id));
}

function isCollectionInFlight(status: CollectionStatus): boolean {
  return ['SUBMITTED', 'APPROVED', 'IN_PROGRESS'].includes(status);
}

function calculateBytesReserved(colls: Collection[]): number {
  return colls
    .filter(c => isCollectionInFlight(c.status))
    .reduce((sum, c) => sum + c.estimated_bytes, 0);
}

function calculateBytesStored(colls: Collection[]): number {
  return colls
    .filter(c => c.status === 'DELIVERED')
    .reduce((sum, c) => sum + (c.actual_bytes || 0), 0);
}

function getMatterStorageRollup(matterId: string): { bytes_reserved: number; bytes_stored: number } {
  const colls = getCollectionsForMatter(matterId);
  return {
    bytes_reserved: calculateBytesReserved(colls),
    bytes_stored: calculateBytesStored(colls)
  };
}

function getWorkspaceStorageRollup(workspaceId: string): { bytes_reserved: number; bytes_stored: number; bytes_available: number } {
  const workspace = workspaces.get(workspaceId);
  if (!workspace) return { bytes_reserved: 0, bytes_stored: 0, bytes_available: 0 };

  const colls = getCollectionsForWorkspace(workspaceId);
  const bytes_reserved = calculateBytesReserved(colls);
  const bytes_stored = calculateBytesStored(colls);
  const bytes_available = Math.max(0, workspace.quota_bytes - bytes_reserved - bytes_stored);

  return { bytes_reserved, bytes_stored, bytes_available };
}

function getHoldsForMatter(matterId: string): Hold[] {
  return Array.from(holds.values()).filter(h => h.matter_id === matterId);
}

function getMatterPosture(matterId: string): MatterPosture {
  const matterHolds = getHoldsForMatter(matterId);
  const matterCollections = getCollectionsForMatter(matterId);

  const hasActiveCourtOrderedHold = matterHolds.some(
    h => h.is_court_ordered && h.status === 'ACTIVE'
  );
  if (hasActiveCourtOrderedHold) return 'FROZEN';

  const hasIssuedHold = matterHolds.some(h => h.status === 'ISSUED');
  const hasInFlightCollection = matterCollections.some(c => isCollectionInFlight(c.status));
  if (hasIssuedHold || hasInFlightCollection) return 'REVIEW';

  return 'OPEN';
}

function getWorkspacePosture(workspaceId: string): WorkspacePosture {
  const workspaceMatters = Array.from(matters.values()).filter(m => m.workspace_id === workspaceId);

  const hasFrozenMatter = workspaceMatters.some(m => getMatterPosture(m.id) === 'FROZEN');
  if (hasFrozenMatter) return 'LOCKDOWN';

  const workspace = workspaces.get(workspaceId);
  if (workspace) {
    const storage = getWorkspaceStorageRollup(workspaceId);
    const threshold = workspace.quota_bytes * 0.1;
    if (storage.bytes_available < threshold) return 'REVIEW';
  }

  return 'NORMAL';
}

function scopeCoversDataSource(scope: HoldScope, dataSource: DataSource): boolean {
  if (scope === 'ALL_DATA') return true;
  if (scope === 'EMAIL_ONLY' && dataSource === 'EMAIL') return true;
  if (scope === 'CHAT_ONLY' && dataSource === 'CHAT') return true;
  if (scope === 'DRIVE_ONLY' && dataSource === 'DRIVE') return true;
  return false;
}

function isLegalBasisValidForMatter(legalBasis: LegalBasis, matterType: MatterType, isCourtOrdered: boolean): boolean {
  if (matterType === 'LITIGATION') {

    if (legalBasis === 'LITIGATION' || legalBasis === 'CONTRACT') return true;
    if (legalBasis === 'REGULATORY' && isCourtOrdered) return true;
    return false;
  } else {

    if (legalBasis === 'REGULATORY' || legalBasis === 'CONTRACT') return true;
    if (legalBasis === 'LITIGATION' && isCourtOrdered) return true;
    return false;
  }
}

function withdrawNonDeliveredCollectionsForHold(holdId: string): void {
  for (const [id, collection] of collections) {
    if (collection.hold_id === holdId && collection.status !== 'DELIVERED') {
      collection.status = 'WITHDRAWN';
      collection.etag = generateEtag();
    }
  }
}

function withdrawNonDeliveredCollectionsForCustodian(custodianId: string, courtOrderedOnly: boolean = false): void {
  for (const [id, collection] of collections) {
    if (collection.custodian_id === custodianId && collection.status !== 'DELIVERED') {
      const hold = holds.get(collection.hold_id);
      if (!courtOrderedOnly || (hold && !hold.is_court_ordered)) {
        collection.status = 'WITHDRAWN';
        collection.etag = generateEtag();
      }
    }
  }
}

function releaseNonCourtOrderedHoldsForCustodian(custodianId: string): void {
  for (const [id, hold] of holds) {
    if (hold.custodian_ids.includes(custodianId) && !hold.is_court_ordered) {
      if (['DRAFT', 'ISSUED', 'ACTIVE', 'SUSPENDED'].includes(hold.status)) {
        hold.status = 'RELEASED';
        hold.etag = generateEtag();

        withdrawNonDeliveredCollectionsForHold(id);
      }
    }
  }
}

function withdrawPreStartCollectionsForHold(holdId: string): void {

  for (const [id, collection] of collections) {
    if (collection.hold_id === holdId) {
      if (['DRAFT', 'SUBMITTED', 'APPROVED'].includes(collection.status)) {
        collection.status = 'WITHDRAWN';
        collection.etag = generateEtag();
      }
    }
  }
}

const app = express();
app.use(express.json());

function idempotencyMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (req.method === 'POST' || req.method === 'PATCH') {
    const idempotencyKey = req.headers['idempotency-key'] as string;

    if (!idempotencyKey) {
      res.status(400).json(errorResponse('ERR_MISSING_IDEMPOTENCY_KEY', 'Idempotency-Key header is required'));
      return;
    }

    const existing = idempotencyStore.get(idempotencyKey);
    if (existing) {

      const currentBody = JSON.stringify(req.body);
      if (existing.method !== req.method || existing.path !== req.path || existing.body !== currentBody) {
        res.status(409).json(errorResponse('ERR_IDEMPOTENCY_REPLAY_MISMATCH', 'Idempotency key used with different request'));
        return;
      }

      res.status(200).json(existing.response);
      return;
    }

    (req as any).idempotencyKey = idempotencyKey;
  }
  next();
}

function ifMatchMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (req.method === 'PATCH' || req.path.endsWith('/state')) {
    if (req.method === 'POST' && !req.path.endsWith('/state')) {
      next();
      return;
    }

    const ifMatch = req.headers['if-match'] as string;
    if (!ifMatch) {
      res.status(400).json(errorResponse('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
      return;
    }
    (req as any).ifMatch = ifMatch;
  }
  next();
}

app.use(idempotencyMiddleware);
app.use(ifMatchMiddleware);

function storeIdempotency(req: Request, response: any): void {
  const key = (req as any).idempotencyKey;
  if (key) {
    idempotencyStore.set(key, {
      key,
      method: req.method,
      path: req.path,
      body: JSON.stringify(req.body),
      response
    });
  }
}

app.post('/workspaces', (req: Request, res: Response) => {
  const { name, quota_bytes } = req.body;

  if (!name || typeof name !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'name is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (quota_bytes === undefined || typeof quota_bytes !== 'number' || quota_bytes < 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'quota_bytes is required and must be a non-negative number');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const workspace: Workspace = {
    id: generateId(),
    name,
    quota_bytes,
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };

  workspaces.set(workspace.id, workspace);

  const storage = getWorkspaceStorageRollup(workspace.id);
  const posture = getWorkspacePosture(workspace.id);

  const response = successResponse({
    id: workspace.id,
    name: workspace.name,
    quota_bytes: workspace.quota_bytes,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    bytes_available: storage.bytes_available,
    etag: workspace.etag,
    created_at: workspace.created_at
  });

  storeIdempotency(req, response);
  res.status(201).json(response);
});

app.get('/workspaces/:workspace_id', (req: Request, res: Response) => {
  const { workspace_id } = req.params;
  const workspace = workspaces.get(workspace_id);

  if (!workspace) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
    return;
  }

  const storage = getWorkspaceStorageRollup(workspace_id);
  const posture = getWorkspacePosture(workspace_id);

  res.json(successResponse({
    id: workspace.id,
    name: workspace.name,
    quota_bytes: workspace.quota_bytes,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    bytes_available: storage.bytes_available,
    etag: workspace.etag,
    created_at: workspace.created_at
  }));
});

app.post('/workspaces/:workspace_id/matters', (req: Request, res: Response) => {
  const { workspace_id } = req.params;
  const workspace = workspaces.get(workspace_id);

  if (!workspace) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const { title, matter_type } = req.body;

  if (!title || typeof title !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'title is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!matter_type || !['LITIGATION', 'INVESTIGATION'].includes(matter_type)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'matter_type must be LITIGATION or INVESTIGATION');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const matter: Matter = {
    id: generateId(),
    workspace_id,
    title,
    matter_type,
    status: 'DRAFT',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };

  matters.set(matter.id, matter);

  const storage = getMatterStorageRollup(matter.id);
  const posture = getMatterPosture(matter.id);

  const response = successResponse({
    id: matter.id,
    workspace_id: matter.workspace_id,
    title: matter.title,
    matter_type: matter.matter_type,
    status: matter.status,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    etag: matter.etag,
    created_at: matter.created_at
  });

  storeIdempotency(req, response);
  res.status(201).json(response);
});

app.get('/workspaces/:workspace_id/matters/:matter_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Matter not found'));
    return;
  }

  const storage = getMatterStorageRollup(matter_id);
  const posture = getMatterPosture(matter_id);

  res.json(successResponse({
    id: matter.id,
    workspace_id: matter.workspace_id,
    title: matter.title,
    matter_type: matter.matter_type,
    status: matter.status,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    etag: matter.etag,
    created_at: matter.created_at
  }));
});

app.patch('/workspaces/:workspace_id/matters/:matter_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== matter.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  const { title } = req.body;

  if (title !== undefined) {
    if (typeof title !== 'string' || title.length === 0) {
      const response = errorResponse('ERR_BAD_REQUEST', 'title must be a non-empty string');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    matter.title = title;
  }

  matter.etag = generateEtag();

  const storage = getMatterStorageRollup(matter_id);
  const posture = getMatterPosture(matter_id);

  const response = successResponse({
    id: matter.id,
    workspace_id: matter.workspace_id,
    title: matter.title,
    matter_type: matter.matter_type,
    status: matter.status,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    etag: matter.etag,
    created_at: matter.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/state', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== matter.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  const { to_status } = req.body;

  if (!to_status || !['DRAFT', 'ACTIVE', 'CLOSED'].includes(to_status)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'to_status must be DRAFT, ACTIVE, or CLOSED');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const matterHolds = getHoldsForMatter(matter_id);
  const matterCollections = getCollectionsForMatter(matter_id);
  const matterCustodians = Array.from(custodians.values()).filter(c => c.matter_id === matter_id);

  if (matter.status === 'DRAFT' && to_status === 'ACTIVE') {

    const hasActiveCustodian = matterCustodians.some(c => c.status === 'ACTIVE');
    if (!hasActiveCustodian) {
      const response = errorResponse('ERR_INVALID_STATE', 'Matter must have at least one active custodian to activate');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    const courtOrderedHolds = matterHolds.filter(h => h.is_court_ordered);
    const hasInactiveCourtOrderedHold = courtOrderedHolds.some(h => h.status !== 'ACTIVE');
    if (hasInactiveCourtOrderedHold) {
      const response = errorResponse('ERR_INVALID_STATE', 'All court-ordered holds must be active before activating matter');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  } else if (matter.status === 'ACTIVE' && to_status === 'CLOSED') {

    const hasActiveHolds = matterHolds.some(h => ['ISSUED', 'ACTIVE', 'SUSPENDED'].includes(h.status));
    if (hasActiveHolds) {
      const response = errorResponse('ERR_MATTER_HAS_ACTIVE_HOLDS', 'Cannot close matter with active holds');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    const hasInFlightCollections = matterCollections.some(c => isCollectionInFlight(c.status));
    if (hasInFlightCollections) {
      const response = errorResponse('ERR_MATTER_HAS_PENDING_COLLECTIONS', 'Cannot close matter with pending collections');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  } else if (matter.status === 'CLOSED' && to_status === 'ACTIVE') {

  } else if (matter.status === to_status) {

  } else if (to_status === 'DRAFT' && matter.status !== 'DRAFT') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot transition back to DRAFT');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  } else if (matter.status === 'DRAFT' && to_status === 'CLOSED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot transition from DRAFT directly to CLOSED');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  matter.status = to_status;
  matter.etag = generateEtag();

  const storage = getMatterStorageRollup(matter_id);
  const posture = getMatterPosture(matter_id);

  const response = successResponse({
    id: matter.id,
    workspace_id: matter.workspace_id,
    title: matter.title,
    matter_type: matter.matter_type,
    status: matter.status,
    posture,
    bytes_reserved: storage.bytes_reserved,
    bytes_stored: storage.bytes_stored,
    etag: matter.etag,
    created_at: matter.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/custodians', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const { full_name, email } = req.body;

  if (!full_name || typeof full_name !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'full_name is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!email || typeof email !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'email is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const custodian: Custodian = {
    id: generateId(),
    matter_id,
    full_name,
    email,
    status: 'ACTIVE',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };

  custodians.set(custodian.id, custodian);

  const response = successResponse({
    id: custodian.id,
    matter_id: custodian.matter_id,
    full_name: custodian.full_name,
    email: custodian.email,
    status: custodian.status,
    etag: custodian.etag,
    created_at: custodian.created_at
  });

  storeIdempotency(req, response);
  res.status(201).json(response);
});

app.get('/workspaces/:workspace_id/matters/:matter_id/custodians/:custodian_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id, custodian_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Matter not found'));
    return;
  }

  const custodian = custodians.get(custodian_id);
  if (!custodian || custodian.matter_id !== matter_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Custodian not found'));
    return;
  }

  res.json(successResponse({
    id: custodian.id,
    matter_id: custodian.matter_id,
    full_name: custodian.full_name,
    email: custodian.email,
    status: custodian.status,
    etag: custodian.etag,
    created_at: custodian.created_at
  }));
});

app.post('/workspaces/:workspace_id/matters/:matter_id/custodians/:custodian_id/state', (req: Request, res: Response) => {
  const { workspace_id, matter_id, custodian_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const custodian = custodians.get(custodian_id);
  if (!custodian || custodian.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Custodian not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== custodian.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  const { to_status } = req.body;

  if (!to_status || !['ACTIVE', 'DEPARTED', 'PURGED'].includes(to_status)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'to_status must be ACTIVE, DEPARTED, or PURGED');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (to_status === 'PURGED') {

    const matterHolds = getHoldsForMatter(matter_id);
    const activeCourtOrderedHoldsCoveringCustodian = matterHolds.filter(
      h => h.is_court_ordered && h.status === 'ACTIVE' && h.custodian_ids.includes(custodian_id)
    );

    if (activeCourtOrderedHoldsCoveringCustodian.length > 0) {
      const response = errorResponse('ERR_COURT_ORDERED_RESTRICTION', 'Cannot purge custodian covered by active court-ordered hold');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    releaseNonCourtOrderedHoldsForCustodian(custodian_id);
    withdrawNonDeliveredCollectionsForCustodian(custodian_id, true);
  }

  if (custodian.status === 'PURGED' && to_status !== 'PURGED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot transition from PURGED');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  custodian.status = to_status;
  custodian.etag = generateEtag();

  const response = successResponse({
    id: custodian.id,
    matter_id: custodian.matter_id,
    full_name: custodian.full_name,
    email: custodian.email,
    status: custodian.status,
    etag: custodian.etag,
    created_at: custodian.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/holds', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (matter.status === 'CLOSED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot create holds on a CLOSED matter');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const { title, legal_basis, scope, is_court_ordered, custodian_ids } = req.body;

  if (!title || typeof title !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'title is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!legal_basis || !['LITIGATION', 'REGULATORY', 'CONTRACT'].includes(legal_basis)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'legal_basis must be LITIGATION, REGULATORY, or CONTRACT');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!scope || !['ALL_DATA', 'EMAIL_ONLY', 'CHAT_ONLY', 'DRIVE_ONLY'].includes(scope)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'scope must be ALL_DATA, EMAIL_ONLY, CHAT_ONLY, or DRIVE_ONLY');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (is_court_ordered === undefined || typeof is_court_ordered !== 'boolean') {
    const response = errorResponse('ERR_BAD_REQUEST', 'is_court_ordered is required and must be a boolean');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!custodian_ids || !Array.isArray(custodian_ids) || custodian_ids.length === 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'custodian_ids is required and must be a non-empty array');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  for (const cid of custodian_ids) {
    const custodian = custodians.get(cid);
    if (!custodian || custodian.matter_id !== matter_id) {
      const response = errorResponse('ERR_NOT_FOUND', `Custodian ${cid} not found in this matter`);
      storeIdempotency(req, response);
      res.status(404).json(response);
      return;
    }

    if (custodian.status === 'PURGED') {
      const response = errorResponse('ERR_CUSTODIAN_PURGED', 'Custodian is PURGED and not eligible for new holds');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  if (!isLegalBasisValidForMatter(legal_basis, matter.matter_type, is_court_ordered)) {
    const response = errorResponse('ERR_BAD_REQUEST', `Legal basis ${legal_basis} is not valid for ${matter.matter_type} matters unless court-ordered`);
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const hold: Hold = {
    id: generateId(),
    matter_id,
    title,
    legal_basis,
    scope,
    is_court_ordered,
    custodian_ids: [...custodian_ids],
    status: 'DRAFT',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };

  holds.set(hold.id, hold);

  const response = successResponse({
    id: hold.id,
    matter_id: hold.matter_id,
    title: hold.title,
    legal_basis: hold.legal_basis,
    scope: hold.scope,
    is_court_ordered: hold.is_court_ordered,
    custodian_ids: hold.custodian_ids,
    status: hold.status,
    etag: hold.etag,
    created_at: hold.created_at
  });

  storeIdempotency(req, response);
  res.status(201).json(response);
});

app.get('/workspaces/:workspace_id/matters/:matter_id/holds/:hold_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id, hold_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Matter not found'));
    return;
  }

  const hold = holds.get(hold_id);
  if (!hold || hold.matter_id !== matter_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Hold not found'));
    return;
  }

  res.json(successResponse({
    id: hold.id,
    matter_id: hold.matter_id,
    title: hold.title,
    legal_basis: hold.legal_basis,
    scope: hold.scope,
    is_court_ordered: hold.is_court_ordered,
    custodian_ids: hold.custodian_ids,
    status: hold.status,
    etag: hold.etag,
    created_at: hold.created_at
  }));
});

app.patch('/workspaces/:workspace_id/matters/:matter_id/holds/:hold_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id, hold_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const hold = holds.get(hold_id);
  if (!hold || hold.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Hold not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== hold.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  if (hold.status !== 'DRAFT') {
    const response = errorResponse('ERR_INVALID_STATE', 'Can only edit draft holds');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const { title, legal_basis, scope, custodian_ids } = req.body;

  if (title !== undefined) {
    if (typeof title !== 'string' || title.length === 0) {
      const response = errorResponse('ERR_BAD_REQUEST', 'title must be a non-empty string');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    hold.title = title;
  }

  if (legal_basis !== undefined) {
    if (!['LITIGATION', 'REGULATORY', 'CONTRACT'].includes(legal_basis)) {
      const response = errorResponse('ERR_BAD_REQUEST', 'legal_basis must be LITIGATION, REGULATORY, or CONTRACT');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    if (!isLegalBasisValidForMatter(legal_basis, matter.matter_type, hold.is_court_ordered)) {
      const response = errorResponse('ERR_BAD_REQUEST', `Legal basis ${legal_basis} is not valid for ${matter.matter_type} matters unless court-ordered`);
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    hold.legal_basis = legal_basis;
  }

  if (scope !== undefined) {
    if (!['ALL_DATA', 'EMAIL_ONLY', 'CHAT_ONLY', 'DRIVE_ONLY'].includes(scope)) {
      const response = errorResponse('ERR_BAD_REQUEST', 'scope must be ALL_DATA, EMAIL_ONLY, CHAT_ONLY, or DRIVE_ONLY');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    hold.scope = scope;
  }

  if (custodian_ids !== undefined) {
    if (!Array.isArray(custodian_ids) || custodian_ids.length === 0) {
      const response = errorResponse('ERR_BAD_REQUEST', 'custodian_ids must be a non-empty array');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    for (const cid of custodian_ids) {
      const custodian = custodians.get(cid);
      if (!custodian || custodian.matter_id !== matter_id) {
        const response = errorResponse('ERR_NOT_FOUND', `Custodian ${cid} not found in this matter`);
        storeIdempotency(req, response);
        res.status(404).json(response);
        return;
      }
    }
    hold.custodian_ids = [...custodian_ids];
  }

  hold.etag = generateEtag();

  const response = successResponse({
    id: hold.id,
    matter_id: hold.matter_id,
    title: hold.title,
    legal_basis: hold.legal_basis,
    scope: hold.scope,
    is_court_ordered: hold.is_court_ordered,
    custodian_ids: hold.custodian_ids,
    status: hold.status,
    etag: hold.etag,
    created_at: hold.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/holds/:hold_id/state', (req: Request, res: Response) => {
  const { workspace_id, matter_id, hold_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const hold = holds.get(hold_id);
  if (!hold || hold.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Hold not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== hold.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  const { to_status } = req.body;

  if (!to_status || !['DRAFT', 'ISSUED', 'ACTIVE', 'SUSPENDED', 'RELEASED', 'VOID'].includes(to_status)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'to_status must be DRAFT, ISSUED, ACTIVE, SUSPENDED, RELEASED, or VOID');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const workspacePosture = getWorkspacePosture(workspace_id);
  if (workspacePosture === 'LOCKDOWN') {

    if (!['RELEASED', 'VOID'].includes(to_status)) {
      const response = errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in LOCKDOWN; only releasing or voiding holds is allowed');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  const validTransitions: Record<HoldStatus, HoldStatus[]> = {
    'DRAFT': ['ISSUED', 'VOID'],
    'ISSUED': ['ACTIVE', 'VOID'],
    'ACTIVE': ['SUSPENDED', 'RELEASED', 'VOID'],
    'SUSPENDED': ['ACTIVE', 'RELEASED', 'VOID'],
    'RELEASED': [],
    'VOID': []
  };

  if (!validTransitions[hold.status].includes(to_status as HoldStatus) && hold.status !== to_status) {
    const response = errorResponse('ERR_INVALID_STATE', `Cannot transition from ${hold.status} to ${to_status}`);
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (hold.is_court_ordered && to_status === 'SUSPENDED') {
    const response = errorResponse('ERR_COURT_ORDERED_RESTRICTION', 'Court-ordered holds cannot be suspended');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (to_status === 'ISSUED' && !hold.is_court_ordered) {
    for (const cid of hold.custodian_ids) {
      const custodian = custodians.get(cid);
      if (custodian && custodian.status === 'DEPARTED') {
        const response = errorResponse('ERR_CUSTODIAN_DEPARTED', 'Non-court-ordered holds cannot be issued to departed custodians');
        storeIdempotency(req, response);
        res.status(400).json(response);
        return;
      }
      if (custodian && custodian.status === 'PURGED') {
        const response = errorResponse('ERR_CUSTODIAN_PURGED', 'Cannot issue hold to purged custodian');
        storeIdempotency(req, response);
        res.status(400).json(response);
        return;
      }
    }
  }

  if (to_status === 'RELEASED' || to_status === 'VOID') {
    withdrawNonDeliveredCollectionsForHold(hold_id);
  }

  if (to_status === 'SUSPENDED' && !hold.is_court_ordered) {
    withdrawPreStartCollectionsForHold(hold_id);
  }

  hold.status = to_status as HoldStatus;
  hold.etag = generateEtag();

  const response = successResponse({
    id: hold.id,
    matter_id: hold.matter_id,
    title: hold.title,
    legal_basis: hold.legal_basis,
    scope: hold.scope,
    is_court_ordered: hold.is_court_ordered,
    custodian_ids: hold.custodian_ids,
    status: hold.status,
    etag: hold.etag,
    created_at: hold.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/collections', (req: Request, res: Response) => {
  const { workspace_id, matter_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (matter.status === 'CLOSED') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot create collections on a CLOSED matter');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const { hold_id, custodian_id, data_source, estimated_bytes } = req.body;

  if (!hold_id || typeof hold_id !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'hold_id is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!custodian_id || typeof custodian_id !== 'string') {
    const response = errorResponse('ERR_BAD_REQUEST', 'custodian_id is required');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!data_source || !['EMAIL', 'CHAT', 'DRIVE'].includes(data_source)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'data_source must be EMAIL, CHAT, or DRIVE');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (estimated_bytes === undefined || typeof estimated_bytes !== 'number' || estimated_bytes < 0) {
    const response = errorResponse('ERR_BAD_REQUEST', 'estimated_bytes is required and must be a non-negative number');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const hold = holds.get(hold_id);
  if (!hold || hold.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Hold not found in this matter');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const custodian = custodians.get(custodian_id);
  if (!custodian || custodian.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Custodian not found in this matter');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (custodian.status === 'PURGED') {
    const response = errorResponse('ERR_CUSTODIAN_PURGED', 'Custodian is PURGED and not eligible for new collections');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (hold.status === 'RELEASED' || hold.status === 'VOID') {
    const response = errorResponse('ERR_INVALID_STATE', 'Cannot create collections under a released/void hold');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!hold.custodian_ids.includes(custodian_id)) {
    const response = errorResponse('ERR_CUSTODIAN_NOT_IN_HOLD', 'Custodian is not included in this hold');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (!scopeCoversDataSource(hold.scope, data_source)) {
    const response = errorResponse('ERR_HOLD_SCOPE_MISMATCH', `Hold scope ${hold.scope} does not cover data source ${data_source}`);
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const collection: Collection = {
    id: generateId(),
    matter_id,
    hold_id,
    custodian_id,
    data_source,
    estimated_bytes,
    status: 'DRAFT',
    etag: generateEtag(),
    created_at: new Date().toISOString()
  };

  collections.set(collection.id, collection);

  const response = successResponse({
    id: collection.id,
    matter_id: collection.matter_id,
    hold_id: collection.hold_id,
    custodian_id: collection.custodian_id,
    data_source: collection.data_source,
    estimated_bytes: collection.estimated_bytes,
    actual_bytes: collection.actual_bytes,
    status: collection.status,
    etag: collection.etag,
    created_at: collection.created_at
  });

  storeIdempotency(req, response);
  res.status(201).json(response);
});

app.get('/workspaces/:workspace_id/matters/:matter_id/collections/:collection_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id, collection_id } = req.params;

  if (!workspaces.has(workspace_id)) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Workspace not found'));
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Matter not found'));
    return;
  }

  const collection = collections.get(collection_id);
  if (!collection || collection.matter_id !== matter_id) {
    res.status(404).json(errorResponse('ERR_NOT_FOUND', 'Collection not found'));
    return;
  }

  res.json(successResponse({
    id: collection.id,
    matter_id: collection.matter_id,
    hold_id: collection.hold_id,
    custodian_id: collection.custodian_id,
    data_source: collection.data_source,
    estimated_bytes: collection.estimated_bytes,
    actual_bytes: collection.actual_bytes,
    status: collection.status,
    etag: collection.etag,
    created_at: collection.created_at
  }));
});

app.patch('/workspaces/:workspace_id/matters/:matter_id/collections/:collection_id', (req: Request, res: Response) => {
  const { workspace_id, matter_id, collection_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  if (!workspaces.has(workspace_id)) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const collection = collections.get(collection_id);
  if (!collection || collection.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Collection not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== collection.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  if (collection.status !== 'DRAFT') {
    const response = errorResponse('ERR_INVALID_STATE', 'Can only edit draft collections');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const { estimated_bytes } = req.body;

  if (estimated_bytes !== undefined) {
    if (typeof estimated_bytes !== 'number' || estimated_bytes < 0) {
      const response = errorResponse('ERR_BAD_REQUEST', 'estimated_bytes must be a non-negative number');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    collection.estimated_bytes = estimated_bytes;
  }

  collection.etag = generateEtag();

  const response = successResponse({
    id: collection.id,
    matter_id: collection.matter_id,
    hold_id: collection.hold_id,
    custodian_id: collection.custodian_id,
    data_source: collection.data_source,
    estimated_bytes: collection.estimated_bytes,
    actual_bytes: collection.actual_bytes,
    status: collection.status,
    etag: collection.etag,
    created_at: collection.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

app.post('/workspaces/:workspace_id/matters/:matter_id/collections/:collection_id/state', (req: Request, res: Response) => {
  const { workspace_id, matter_id, collection_id } = req.params;
  const ifMatch = (req as any).ifMatch;

  const workspace = workspaces.get(workspace_id);
  if (!workspace) {
    const response = errorResponse('ERR_NOT_FOUND', 'Workspace not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const matter = matters.get(matter_id);
  if (!matter || matter.workspace_id !== workspace_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Matter not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  const collection = collections.get(collection_id);
  if (!collection || collection.matter_id !== matter_id) {
    const response = errorResponse('ERR_NOT_FOUND', 'Collection not found');
    storeIdempotency(req, response);
    res.status(404).json(response);
    return;
  }

  if (ifMatch !== collection.etag) {
    const response = errorResponse('ERR_ETAG_MISMATCH', 'ETag does not match');
    storeIdempotency(req, response);
    res.status(412).json(response);
    return;
  }

  const { to_status, actual_bytes } = req.body;

  if (!to_status || !['DRAFT', 'SUBMITTED', 'APPROVED', 'IN_PROGRESS', 'DELIVERED', 'WITHDRAWN', 'REJECTED'].includes(to_status)) {
    const response = errorResponse('ERR_BAD_REQUEST', 'to_status must be DRAFT, SUBMITTED, APPROVED, IN_PROGRESS, DELIVERED, WITHDRAWN, or REJECTED');
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  const hold = holds.get(collection.hold_id);
  const custodian = custodians.get(collection.custodian_id);

  const workspacePosture = getWorkspacePosture(workspace_id);

  if (workspacePosture === 'LOCKDOWN') {

    if (to_status !== 'WITHDRAWN' && to_status !== collection.status) {
      const response = errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in LOCKDOWN; only withdrawing collections is allowed');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  if (workspacePosture === 'REVIEW') {

    if (['APPROVED', 'IN_PROGRESS'].includes(to_status) && hold && !hold.is_court_ordered) {
      const response = errorResponse('ERR_POSTURE_BLOCKED', 'Workspace is in REVIEW; only court-ordered collections can advance to APPROVED or IN_PROGRESS');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  const validTransitions: Record<CollectionStatus, CollectionStatus[]> = {
    'DRAFT': ['SUBMITTED', 'WITHDRAWN'],
    'SUBMITTED': ['APPROVED', 'REJECTED', 'WITHDRAWN'],
    'APPROVED': ['IN_PROGRESS', 'REJECTED', 'WITHDRAWN'],
    'IN_PROGRESS': ['DELIVERED', 'WITHDRAWN'],
    'DELIVERED': [],
    'WITHDRAWN': [],
    'REJECTED': []
  };

  if (!validTransitions[collection.status].includes(to_status as CollectionStatus) && collection.status !== to_status) {
    const response = errorResponse('ERR_INVALID_STATE', `Cannot transition from ${collection.status} to ${to_status}`);
    storeIdempotency(req, response);
    res.status(400).json(response);
    return;
  }

  if (to_status === 'SUBMITTED') {
    if (!hold || hold.status !== 'ACTIVE') {
      const response = errorResponse('ERR_HOLD_NOT_ACTIVE', 'Collection can only be submitted when hold is ACTIVE');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    const storage = getWorkspaceStorageRollup(workspace_id);
    if (collection.estimated_bytes > storage.bytes_available) {
      const response = errorResponse('ERR_QUOTA_EXCEEDED', 'Insufficient workspace capacity');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  if (to_status === 'IN_PROGRESS') {
    if (custodian && custodian.status === 'DEPARTED' && hold && !hold.is_court_ordered) {
      const response = errorResponse('ERR_CUSTODIAN_DEPARTED', 'Cannot move to IN_PROGRESS for departed custodian without court order');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
    if (custodian && custodian.status === 'PURGED') {
      const response = errorResponse('ERR_CUSTODIAN_PURGED', 'Cannot move to IN_PROGRESS for purged custodian');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }
  }

  if (to_status === 'DELIVERED') {
    if (actual_bytes === undefined || typeof actual_bytes !== 'number' || actual_bytes < 0) {
      const response = errorResponse('ERR_BAD_REQUEST', 'actual_bytes is required for DELIVERED status');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    if (!hold || hold.status !== 'ACTIVE') {
      const response = errorResponse('ERR_HOLD_NOT_ACTIVE', 'Collection can only be delivered when hold is ACTIVE');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    const storage = getWorkspaceStorageRollup(workspace_id);
    const currentReserved = collection.estimated_bytes;
    const availableAfterRelease = storage.bytes_available + currentReserved;
    if (actual_bytes > availableAfterRelease) {
      const response = errorResponse('ERR_QUOTA_EXCEEDED', 'Insufficient workspace capacity for actual bytes');
      storeIdempotency(req, response);
      res.status(400).json(response);
      return;
    }

    collection.actual_bytes = actual_bytes;
  }

  collection.status = to_status as CollectionStatus;
  collection.etag = generateEtag();

  const response = successResponse({
    id: collection.id,
    matter_id: collection.matter_id,
    hold_id: collection.hold_id,
    custodian_id: collection.custodian_id,
    data_source: collection.data_source,
    estimated_bytes: collection.estimated_bytes,
    actual_bytes: collection.actual_bytes,
    status: collection.status,
    etag: collection.etag,
    created_at: collection.created_at
  });

  storeIdempotency(req, response);
  res.json(response);
});

if (require.main === module) {
  const PORT = process.env.PORT ? Number(process.env.PORT) : 3000;
  const HOST = process.env.HOST || '127.0.0.1';

  app.listen(PORT, HOST, () => {
    console.log(`CounselGrid API server running on http://${HOST}:${PORT}`);
  });
}

export default app;
