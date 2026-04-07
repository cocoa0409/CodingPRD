import { v4 as uuidv4 } from 'uuid';
import { get, post, postState, patch, idempotencyKey } from './api-client';
import { expectSuccess, getEtag, getId } from './assertions';
import {
  MatterType, MatterStatus, CustodianStatus, HoldStatus,
  LegalBasis, HoldScope, CollectionStatus, DataSource,
  WorkspacePosture, MatterPosture
} from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return (body && typeof body === 'object' && 'data' in body) ? body.data : body;
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
  quota_bytes: number;
  bytes_reserved: number;
  bytes_stored: number;
  bytes_available: number;
  posture: WorkspacePosture;
  etag?: string;
}

export interface Matter {
  id: string;
  title: string;
  matter_type: MatterType;
  status: MatterStatus;
  posture: MatterPosture;
  bytes_reserved: number;
  bytes_stored: number;
  etag?: string;
}

export interface Custodian {
  id: string;
  full_name: string;
  email: string;
  status: CustodianStatus;
  etag?: string;
}

export interface Hold {
  id: string;
  title: string;
  legal_basis: LegalBasis;
  scope: HoldScope;
  is_court_ordered: boolean;
  custodian_ids: string[];
  status: HoldStatus;
  etag?: string;
}

export interface Collection {
  id: string;
  hold_id: string;
  custodian_id: string;
  data_source: DataSource;
  estimated_bytes: number;
  actual_bytes?: number;
  status: CollectionStatus;
  etag?: string;
}

export interface CreateWorkspaceInput {
  name?: string;
  quota_bytes: number;
}

export async function createWorkspace(input: CreateWorkspaceInput): Promise<Workspace> {
  const payload = {
    name: input.name || `WS-${uniqueId('ws')}`,
    quota_bytes: input.quota_bytes,
  };

  const res = await post('/workspaces', payload, idempotencyKey('create-ws'));
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const res = await get(`/workspaces/${workspaceId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export interface CreateMatterInput {
  title?: string;
  matter_type: MatterType;
}

export async function createMatter(
  workspaceId: string,
  input: CreateMatterInput
): Promise<Matter> {
  const payload = {
    title: input.title || `Matter-${uniqueId('mat')}`,
    matter_type: input.matter_type,
  };

  const res = await post(
    `/workspaces/${workspaceId}/matters`,
    payload,
    idempotencyKey('create-matter')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getMatter(workspaceId: string, matterId: string): Promise<Matter> {
  const res = await get(`/workspaces/${workspaceId}/matters/${matterId}`);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateMatter(
  workspaceId: string,
  matterId: string,
  etag: string,
  updates: Partial<{ title: string }>
): Promise<Matter> {
  const res = await patch(
    `/workspaces/${workspaceId}/matters/${matterId}`,
    updates,
    etag,
    idempotencyKey('update-matter')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function transitionMatter(
  workspaceId: string,
  matterId: string,
  etag: string,
  toStatus: MatterStatus
): Promise<Matter> {
  const res = await postState(
    `/workspaces/${workspaceId}/matters/${matterId}/state`,
    { to_status: toStatus },
    etag,
    idempotencyKey('matter-state')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function activateMatter(workspaceId: string, matterId: string): Promise<Matter> {
  const matter = await getMatter(workspaceId, matterId);
  return transitionMatter(workspaceId, matterId, matter.etag!, 'ACTIVE');
}

export async function closeMatter(workspaceId: string, matterId: string): Promise<Matter> {
  const matter = await getMatter(workspaceId, matterId);
  return transitionMatter(workspaceId, matterId, matter.etag!, 'CLOSED');
}

export interface CreateCustodianInput {
  full_name?: string;
  email?: string;
}

export async function createCustodian(
  workspaceId: string,
  matterId: string,
  input: CreateCustodianInput = {}
): Promise<Custodian> {
  const uniqueSuffix = uniqueId('cust');
  const payload = {
    full_name: input.full_name || `Custodian ${uniqueSuffix}`,
    email: input.email || `${uniqueSuffix}@example.com`,
  };

  const res = await post(
    `/workspaces/${workspaceId}/matters/${matterId}/custodians`,
    payload,
    idempotencyKey('create-custodian')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getCustodian(
  workspaceId: string,
  matterId: string,
  custodianId: string
): Promise<Custodian> {
  const res = await get(
    `/workspaces/${workspaceId}/matters/${matterId}/custodians/${custodianId}`
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function transitionCustodian(
  workspaceId: string,
  matterId: string,
  custodianId: string,
  etag: string,
  toStatus: CustodianStatus
): Promise<Custodian> {
  const res = await postState(
    `/workspaces/${workspaceId}/matters/${matterId}/custodians/${custodianId}/state`,
    { to_status: toStatus },
    etag,
    idempotencyKey('custodian-state')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function departCustodian(
  workspaceId: string,
  matterId: string,
  custodianId: string
): Promise<Custodian> {
  const custodian = await getCustodian(workspaceId, matterId, custodianId);
  return transitionCustodian(workspaceId, matterId, custodianId, custodian.etag!, 'DEPARTED');
}

export async function purgeCustodian(
  workspaceId: string,
  matterId: string,
  custodianId: string
): Promise<Custodian> {
  const custodian = await getCustodian(workspaceId, matterId, custodianId);
  return transitionCustodian(workspaceId, matterId, custodianId, custodian.etag!, 'PURGED');
}

export interface CreateHoldInput {
  title?: string;
  legal_basis: LegalBasis;
  scope: HoldScope;
  is_court_ordered: boolean;
  custodian_ids: string[];
}

export async function createHold(
  workspaceId: string,
  matterId: string,
  input: CreateHoldInput
): Promise<Hold> {
  const payload = {
    title: input.title || `Hold-${uniqueId('hold')}`,
    legal_basis: input.legal_basis,
    scope: input.scope,
    is_court_ordered: input.is_court_ordered,
    custodian_ids: input.custodian_ids,
  };

  const res = await post(
    `/workspaces/${workspaceId}/matters/${matterId}/holds`,
    payload,
    idempotencyKey('create-hold')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const res = await get(
    `/workspaces/${workspaceId}/matters/${matterId}/holds/${holdId}`
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateHold(
  workspaceId: string,
  matterId: string,
  holdId: string,
  etag: string,
  updates: Partial<{ title: string; legal_basis: LegalBasis; scope: HoldScope; custodian_ids: string[] }>
): Promise<Hold> {
  const res = await patch(
    `/workspaces/${workspaceId}/matters/${matterId}/holds/${holdId}`,
    updates,
    etag,
    idempotencyKey('update-hold')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function transitionHold(
  workspaceId: string,
  matterId: string,
  holdId: string,
  etag: string,
  toStatus: HoldStatus
): Promise<Hold> {
  const res = await postState(
    `/workspaces/${workspaceId}/matters/${matterId}/holds/${holdId}/state`,
    { to_status: toStatus },
    etag,
    idempotencyKey('hold-state')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function issueHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const hold = await getHold(workspaceId, matterId, holdId);
  return transitionHold(workspaceId, matterId, holdId, hold.etag!, 'ISSUED');
}

export async function activateHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const hold = await getHold(workspaceId, matterId, holdId);
  return transitionHold(workspaceId, matterId, holdId, hold.etag!, 'ACTIVE');
}

export async function issueAndActivateHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  await issueHold(workspaceId, matterId, holdId);
  return activateHold(workspaceId, matterId, holdId);
}

export async function suspendHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const hold = await getHold(workspaceId, matterId, holdId);
  return transitionHold(workspaceId, matterId, holdId, hold.etag!, 'SUSPENDED');
}

export async function releaseHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const hold = await getHold(workspaceId, matterId, holdId);
  return transitionHold(workspaceId, matterId, holdId, hold.etag!, 'RELEASED');
}

export async function voidHold(
  workspaceId: string,
  matterId: string,
  holdId: string
): Promise<Hold> {
  const hold = await getHold(workspaceId, matterId, holdId);
  return transitionHold(workspaceId, matterId, holdId, hold.etag!, 'VOID');
}

export interface CreateCollectionInput {
  hold_id: string;
  custodian_id: string;
  data_source: DataSource;
  estimated_bytes: number;
}

export async function createCollection(
  workspaceId: string,
  matterId: string,
  input: CreateCollectionInput
): Promise<Collection> {
  const payload = {
    hold_id: input.hold_id,
    custodian_id: input.custodian_id,
    data_source: input.data_source,
    estimated_bytes: input.estimated_bytes,
  };

  const res = await post(
    `/workspaces/${workspaceId}/matters/${matterId}/collections`,
    payload,
    idempotencyKey('create-collection')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const res = await get(
    `/workspaces/${workspaceId}/matters/${matterId}/collections/${collectionId}`
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function updateCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string,
  etag: string,
  updates: Partial<{ estimated_bytes: number }>
): Promise<Collection> {
  const res = await patch(
    `/workspaces/${workspaceId}/matters/${matterId}/collections/${collectionId}`,
    updates,
    etag,
    idempotencyKey('update-collection')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function transitionCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string,
  etag: string,
  toStatus: CollectionStatus,
  actualBytes?: number
): Promise<Collection> {
  const body: any = { to_status: toStatus };
  if (toStatus === 'DELIVERED' && actualBytes !== undefined) {
    body.actual_bytes = actualBytes;
  }

  const res = await postState(
    `/workspaces/${workspaceId}/matters/${matterId}/collections/${collectionId}/state`,
    body,
    etag,
    idempotencyKey('collection-state')
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function submitCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'SUBMITTED');
}

export async function approveCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'APPROVED');
}

export async function startCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'IN_PROGRESS');
}

export async function deliverCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string,
  actualBytes: number
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'DELIVERED', actualBytes);
}

export async function withdrawCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'WITHDRAWN');
}

export async function rejectCollection(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  const collection = await getCollection(workspaceId, matterId, collectionId);
  return transitionCollection(workspaceId, matterId, collectionId, collection.etag!, 'REJECTED');
}

export async function advanceCollectionToDelivered(
  workspaceId: string,
  matterId: string,
  collectionId: string,
  actualBytes: number
): Promise<Collection> {
  await submitCollection(workspaceId, matterId, collectionId);
  await approveCollection(workspaceId, matterId, collectionId);
  await startCollection(workspaceId, matterId, collectionId);
  return deliverCollection(workspaceId, matterId, collectionId, actualBytes);
}

export async function advanceCollectionToInProgress(
  workspaceId: string,
  matterId: string,
  collectionId: string
): Promise<Collection> {
  await submitCollection(workspaceId, matterId, collectionId);
  await approveCollection(workspaceId, matterId, collectionId);
  return startCollection(workspaceId, matterId, collectionId);
}

export async function createActiveLitMatter(quotaBytes: number = 1000): Promise<{
  workspace: Workspace;
  matter: Matter;
  custodian: Custodian;
}> {
  const workspace = await createWorkspace({ quota_bytes: quotaBytes });
  const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
  const custodian = await createCustodian(workspace.id, matter.id);
  const activatedMatter = await activateMatter(workspace.id, matter.id);

  return { workspace, matter: activatedMatter, custodian };
}

export async function createActiveInvMatter(quotaBytes: number = 1000): Promise<{
  workspace: Workspace;
  matter: Matter;
  custodian: Custodian;
}> {
  const workspace = await createWorkspace({ quota_bytes: quotaBytes });
  const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
  const custodian = await createCustodian(workspace.id, matter.id);
  const activatedMatter = await activateMatter(workspace.id, matter.id);

  return { workspace, matter: activatedMatter, custodian };
}

export async function createActiveLitMatterWithHold(
  quotaBytes: number = 1000,
  holdOptions: Partial<CreateHoldInput> = {}
): Promise<{
  workspace: Workspace;
  matter: Matter;
  custodian: Custodian;
  hold: Hold;
}> {
  const { workspace, matter, custodian } = await createActiveLitMatter(quotaBytes);

  const hold = await createHold(workspace.id, matter.id, {
    legal_basis: holdOptions.legal_basis || 'LITIGATION',
    scope: holdOptions.scope || 'ALL_DATA',
    is_court_ordered: holdOptions.is_court_ordered ?? false,
    custodian_ids: holdOptions.custodian_ids || [custodian.id],
    title: holdOptions.title,
  });

  const activeHold = await issueAndActivateHold(workspace.id, matter.id, hold.id);

  return { workspace, matter, custodian, hold: activeHold };
}

export async function createDraftCollection(
  quotaBytes: number = 1000,
  collectionOptions: Partial<CreateCollectionInput> = {}
): Promise<{
  workspace: Workspace;
  matter: Matter;
  custodian: Custodian;
  hold: Hold;
  collection: Collection;
}> {
  const { workspace, matter, custodian, hold } = await createActiveLitMatterWithHold(quotaBytes);

  const collection = await createCollection(workspace.id, matter.id, {
    hold_id: collectionOptions.hold_id || hold.id,
    custodian_id: collectionOptions.custodian_id || custodian.id,
    data_source: collectionOptions.data_source || 'EMAIL',
    estimated_bytes: collectionOptions.estimated_bytes || 200,
  });

  return { workspace, matter, custodian, hold, collection };
}

export async function createLockdownWorkspace(quotaBytes: number = 1000): Promise<{
  workspace: Workspace;
  matter: Matter;
  custodian: Custodian;
  hold: Hold;
}> {
  return createActiveLitMatterWithHold(quotaBytes, {
    legal_basis: 'REGULATORY',
    scope: 'EMAIL_ONLY',
    is_court_ordered: true,
  });
}
