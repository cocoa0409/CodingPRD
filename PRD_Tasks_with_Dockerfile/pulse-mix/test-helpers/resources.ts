import { v4 as uuidv4 } from 'uuid';
import { postAs, getAs, putAs, patchAs, idempotencyKey } from './api-client';
import { expectSuccess } from './assertions';
import {
  Role,
  ClearancePolicy,
  MixKind,
  Slot,
  DisputeSeverity,
  DisputeResolution,
  CONSTANTS
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

export interface Studio {
  id: string;
  name: string;
  posture: string;
  cycle_index: number;
  token_budget: number;
  token_reserved: number;
  token_committed: number;
  token_available: number;
  version: number;
}

export interface Asset {
  id: string;
  title: string;
  duration_sec: number;
  status: string;
  version: number;
}

export interface Clearance {
  id: string;
  asset_id: string;
  policy: string;
  status: string;
  last_granted_in_cycle: number | null;
  version: number;
}

export interface MixEntry {
  asset_id: string;
  slot: Slot;
}

export interface Mix {
  id: string;
  title: string;
  kind: string;
  status: string;
  entries: MixEntry[];
  token_cost: number;
  approved_in_cycle: number | null;
  published_in_cycle: number | null;
  version: number;
}

export interface Dispute {
  id: string;
  target_type: string;
  target_id: string;
  severity: string;
  status: string;
  resolution: string | null;
  version: number;
}

export interface CreateStudioInput {
  name?: string;
  token_budget: number;
}

export async function createStudio(
  input: CreateStudioInput,
  idemKey?: string
): Promise<Studio> {
  const payload = {
    name: input.name || uniqueId('studio'),
    token_budget: input.token_budget
  };
  const res = await postAs('/studios', payload, 'curator', idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Studio;
}

export async function getStudio(studioId: string, role: Role = 'curator'): Promise<Studio> {
  const res = await getAs(`/studios/${studioId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as Studio;
}

export async function advanceCycle(
  studioId: string,
  role: Role = 'manager',
  idemKey?: string
): Promise<Studio> {
  const res = await postAs(`/studios/${studioId}/advance-cycle`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Studio;
}

export interface CreateAssetInput {
  title?: string;
  duration_sec: number;
}

export async function createAsset(
  studioId: string,
  input: CreateAssetInput,
  role: Role = 'curator',
  idemKey?: string
): Promise<Asset> {
  const payload = {
    title: input.title || uniqueId('asset'),
    duration_sec: input.duration_sec
  };
  const res = await postAs(`/studios/${studioId}/assets`, payload, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Asset;
}

export async function patchAsset(
  studioId: string,
  assetId: string,
  updates: Partial<{ title: string; duration_sec: number }>,
  ifMatch: number,
  role: Role = 'curator'
): Promise<Asset> {
  const res = await patchAs(`/studios/${studioId}/assets/${assetId}`, updates, ifMatch, role);
  expectSuccess(res);
  return unwrap(res.body) as Asset;
}

export async function activateAsset(
  studioId: string,
  assetId: string,
  role: Role = 'curator',
  idemKey?: string
): Promise<Asset> {
  const res = await postAs(`/studios/${studioId}/assets/${assetId}/activate`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Asset;
}

export interface CreateClearanceInput {
  asset_id: string;
  policy: ClearancePolicy;
}

export async function createClearance(
  studioId: string,
  input: CreateClearanceInput,
  role: Role = 'legal',
  idemKey?: string
): Promise<Clearance> {
  const res = await postAs(`/studios/${studioId}/clearances`, input, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Clearance;
}

export async function grantClearance(
  studioId: string,
  clearanceId: string,
  role: Role = 'legal',
  idemKey?: string
): Promise<Clearance> {
  const res = await postAs(`/studios/${studioId}/clearances/${clearanceId}/grant`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Clearance;
}

export async function suspendClearance(
  studioId: string,
  clearanceId: string,
  role: Role = 'legal',
  idemKey?: string
): Promise<Clearance> {
  const res = await postAs(`/studios/${studioId}/clearances/${clearanceId}/suspend`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Clearance;
}

export async function revokeClearance(
  studioId: string,
  clearanceId: string,
  role: Role = 'legal',
  idemKey?: string
): Promise<Clearance> {
  const res = await postAs(`/studios/${studioId}/clearances/${clearanceId}/revoke`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Clearance;
}

export interface CreateMixInput {
  title?: string;
  kind: MixKind;
}

export async function createMix(
  studioId: string,
  input: CreateMixInput,
  role: Role = 'curator',
  idemKey?: string
): Promise<Mix> {
  const payload = {
    title: input.title || uniqueId('mix'),
    kind: input.kind
  };
  const res = await postAs(`/studios/${studioId}/mixes`, payload, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function setMixEntries(
  studioId: string,
  mixId: string,
  entries: MixEntry[],
  ifMatch: number,
  role: Role = 'curator'
): Promise<Mix> {
  const res = await putAs(`/studios/${studioId}/mixes/${mixId}/entries`, { entries }, ifMatch, role);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function submitMix(
  studioId: string,
  mixId: string,
  role: Role = 'curator',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/submit`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function approveMix(
  studioId: string,
  mixId: string,
  role: Role = 'manager',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/approve`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function publishMix(
  studioId: string,
  mixId: string,
  role: Role = 'manager',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/publish`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function unpublishMix(
  studioId: string,
  mixId: string,
  role: Role = 'manager',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/unpublish`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function freezeMix(
  studioId: string,
  mixId: string,
  role: Role = 'legal',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/freeze`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export async function archiveMix(
  studioId: string,
  mixId: string,
  role: Role = 'manager',
  idemKey?: string
): Promise<Mix> {
  const res = await postAs(`/studios/${studioId}/mixes/${mixId}/archive`, {}, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}

export interface CreateDisputeInput {
  target_type: 'ASSET' | 'MIX';
  target_id: string;
  severity: DisputeSeverity;
}

export async function createDispute(
  studioId: string,
  input: CreateDisputeInput,
  role: Role = 'legal',
  idemKey?: string
): Promise<Dispute> {
  const res = await postAs(`/studios/${studioId}/disputes`, input, role, idemKey);
  expectSuccess(res);
  return unwrap(res.body) as Dispute;
}

export async function resolveDispute(
  studioId: string,
  disputeId: string,
  resolution: DisputeResolution | 'VOID',
  role: Role = 'legal',
  idemKey?: string
): Promise<Dispute> {
  const res = await postAs(
    `/studios/${studioId}/disputes/${disputeId}/resolve`,
    { resolution },
    role,
    idemKey
  );
  expectSuccess(res);
  return unwrap(res.body) as Dispute;
}

export async function createActiveAssetWithClearance(
  studioId: string,
  duration_sec: number,
  policy: ClearancePolicy = 'FULL'
): Promise<{ asset: Asset; clearance: Clearance }> {

  const asset = await createAsset(studioId, { duration_sec });

  const clearance = await createClearance(studioId, {
    asset_id: asset.id,
    policy
  });
  const grantedClearance = await grantClearance(studioId, clearance.id);

  const activeAsset = await activateAsset(studioId, asset.id);

  return { asset: activeAsset, clearance: grantedClearance };
}

export async function createMixWithEntries(
  studioId: string,
  kind: MixKind,
  entries: MixEntry[],
  role: Role = 'curator'
): Promise<Mix> {
  const mix = await createMix(studioId, { kind }, role);
  if (entries.length > 0) {
    return await setMixEntries(studioId, mix.id, entries, mix.version, role);
  }
  return mix;
}

export async function submitAndApproveMix(
  studioId: string,
  mixId: string
): Promise<Mix> {
  await submitMix(studioId, mixId, 'curator');
  return await approveMix(studioId, mixId, 'manager');
}

export async function submitApproveAndPublishMix(
  studioId: string,
  mixId: string
): Promise<Mix> {
  await submitMix(studioId, mixId, 'curator');
  await approveMix(studioId, mixId, 'manager');
  return await publishMix(studioId, mixId, 'manager');
}
