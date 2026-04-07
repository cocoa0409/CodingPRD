import { v4 as uuidv4 } from 'uuid';
import {
  getAs,
  postAs,
  postWithIfMatch,
  generateIdempotencyKey
} from './api-client';
import { expectSuccess } from './assertions';
import {
  Role,
  Trade,
  Zone,
  Criticality,
  PermitDecision,
  InspectionKind,
  InspectionOutcome
} from './constants';

export interface Project {
  id: string;
  name: string;
  posture: string;
  labor_budget_hours: number;
  labor_reserved_hours: number;
  labor_committed_hours: number;
  labor_used_hours: number;
  labor_available_hours: number;
  permits: Permit[];
}

export interface Permit {
  id: string;
  trade: Trade;
  status: string;
}

export interface WorkItem {
  id: string;
  title: string;
  trade: Trade;
  zone: Zone;
  criticality: Criticality;
  estimated_hours: number;
  actual_hours?: number;
  status: string;
  is_startable: boolean;
  start_blockers: string[];
  latest_safety_status?: string;
  latest_quality_status?: string;
  etag: string;
}

export interface Inspection {
  id: string;
  work_item_id: string;
  kind: InspectionKind;
  status: string;
}

export interface ChangeOrder {
  id: string;
  work_item_id: string;
  summary: string;
  status: string;
  labor_budget_hours_delta?: number;
  new_estimated_hours?: number;
  new_trade?: Trade;
  new_zone?: Zone;
  etag: string;
}

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

export interface CreateProjectInput {
  name: string;
  labor_budget_hours: number;
}

export async function createProject(
  input: CreateProjectInput,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<Project> {
  const res = await postAs('/projects', input, role, idempotencyKey);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getProject(
  projectId: string,
  role: Role = 'MANAGER'
): Promise<Project> {
  const res = await getAs(`/projects/${projectId}`, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export interface CreateWorkItemInput {
  title: string;
  trade: Trade;
  zone: Zone;
  criticality: Criticality;
  estimated_hours: number;
}

export async function createWorkItem(
  projectId: string,
  input: CreateWorkItemInput,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<WorkItem> {
  const res = await postAs(
    `/projects/${projectId}/work_items`,
    input,
    role,
    idempotencyKey
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getWorkItem(
  projectId: string,
  workItemId: string,
  role: Role = 'FOREMAN'
): Promise<WorkItem> {
  const res = await getAs(`/projects/${projectId}/work_items/${workItemId}`, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function readyWorkItem(
  projectId: string,
  workItemId: string,
  etag: string,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/work_items/${workItemId}/ready`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function startWorkItem(
  projectId: string,
  workItemId: string,
  etag: string,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/work_items/${workItemId}/start`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function completeWorkItem(
  projectId: string,
  workItemId: string,
  etag: string,
  actualHours: number,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/work_items/${workItemId}/complete`,
    { actual_hours: actualHours },
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function cancelWorkItem(
  projectId: string,
  workItemId: string,
  etag: string,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/work_items/${workItemId}/cancel`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export interface CreatePermitInput {
  trade: Trade;
  replaces_permit_id?: string;
}

export async function createPermit(
  projectId: string,
  input: CreatePermitInput,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<Permit> {
  const res = await postAs(
    `/projects/${projectId}/permits`,
    input,
    role,
    idempotencyKey
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function decidePermit(
  projectId: string,
  permitId: string,
  decision: PermitDecision,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<void> {
  const res = await postAs(
    `/projects/${projectId}/permits/${permitId}/decide`,
    { decision },
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export interface CreateInspectionInput {
  work_item_id: string;
  kind: InspectionKind;
}

export async function createInspection(
  projectId: string,
  input: CreateInspectionInput,
  role: Role = 'INSPECTOR',
  idempotencyKey?: string
): Promise<Inspection> {
  const res = await postAs(
    `/projects/${projectId}/inspections`,
    input,
    role,
    idempotencyKey
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function submitInspection(
  projectId: string,
  inspectionId: string,
  outcome: InspectionOutcome,
  role: Role = 'INSPECTOR',
  idempotencyKey?: string
): Promise<void> {
  const res = await postAs(
    `/projects/${projectId}/inspections/${inspectionId}/submit`,
    { outcome },
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function voidInspection(
  projectId: string,
  inspectionId: string,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<void> {
  const res = await postAs(
    `/projects/${projectId}/inspections/${inspectionId}/void`,
    {},
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export interface CreateChangeOrderInput {
  work_item_id: string;
  summary: string;
  labor_budget_hours_delta?: number;
  new_estimated_hours?: number;
  new_trade?: Trade;
  new_zone?: Zone;
}

export async function createChangeOrder(
  projectId: string,
  input: CreateChangeOrderInput,
  role: Role = 'FOREMAN',
  idempotencyKey?: string
): Promise<ChangeOrder> {
  const res = await postAs(
    `/projects/${projectId}/change_orders`,
    input,
    role,
    idempotencyKey
  );
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getChangeOrder(
  projectId: string,
  changeOrderId: string,
  role: Role = 'FOREMAN'
): Promise<ChangeOrder> {
  const res = await getAs(`/projects/${projectId}/change_orders/${changeOrderId}`, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function approveChangeOrder(
  projectId: string,
  changeOrderId: string,
  etag: string,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/change_orders/${changeOrderId}/approve`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function applyChangeOrder(
  projectId: string,
  changeOrderId: string,
  etag: string,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/change_orders/${changeOrderId}/apply`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}

export async function cancelChangeOrder(
  projectId: string,
  changeOrderId: string,
  etag: string,
  role: Role = 'MANAGER',
  idempotencyKey?: string
): Promise<void> {
  const res = await postWithIfMatch(
    `/projects/${projectId}/change_orders/${changeOrderId}/cancel`,
    {},
    etag,
    role,
    idempotencyKey
  );
  expectSuccess(res);
}
