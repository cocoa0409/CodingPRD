import { v4 as uuidv4 } from 'uuid';
import { postAs, getAs } from './api-client';
import { expectSuccess } from './assertions';
import {
  Posture,
  Phase,
  PledgeStatus,
  ContributionStatus,
  GrantStatus,
  CauseStatus,
  DisbursementStatus,
  HoldStatus,
  HoldSeverity,
} from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return body && typeof body === 'object' && 'data' in body ? body.data : body;
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

export interface Campaign {
  id: string;
  name: string;
  fundraising_target: number;
  phase: Phase;
  posture: Posture;
  pledge_outstanding: number;
  contribution_total: number;
  match_total: number;
  allocated_total: number;
  disbursed_total: number;
  available_balance: number;
}

export interface Pledge {
  id: string;
  donor_name: string;
  donor_email: string;
  amount: number;
  status: PledgeStatus;
  fulfilled_contribution_id: string | null;
}

export interface Contribution {
  id: string;
  donor_name: string;
  donor_email: string;
  gross_amount: number;
  net_amount: number;
  fee_amount: number;
  status: ContributionStatus;
  matched_amount: number;
  match_eligible: boolean;
  fulfills_pledge_id: string | null;
  allocations: Array<{ cause_id: string; amount: number }>;
}

export interface Grant {
  id: string;
  sponsor_name: string;
  match_ratio: number;
  cap_amount: number;
  min_contribution: number;
  excludes_pledge_fulfillment: boolean;
  status: GrantStatus;
  matched_so_far: number;
}

export interface Cause {
  id: string;
  name: string;
  target_amount: number;
  priority: number;
  threshold_percent: number;
  status: CauseStatus;
  allocated_amount: number;
  disbursed_amount: number;
}

export interface Disbursement {
  id: string;
  cause_id: string;
  beneficiary_name: string;
  amount: number;
  status: DisbursementStatus;
}

export interface Hold {
  id: string;
  reason: string;
  severity: HoldSeverity;
  status: HoldStatus;
}

export interface CampaignInput {
  name: string;
  fundraising_target: number;
}

export interface PledgeInput {
  donor_name: string;
  donor_email: string;
  amount: number;
}

export interface ContributionInput {
  donor_name: string;
  donor_email: string;
  gross_amount: number;
  fulfills_pledge_id?: string;
  match_eligible?: boolean;
}

export interface GrantInput {
  sponsor_name: string;
  match_ratio: number;
  cap_amount: number;
  min_contribution?: number;
  excludes_pledge_fulfillment?: boolean;
}

export interface CauseInput {
  name: string;
  target_amount: number;
  priority: number;
  threshold_percent?: number;
}

export interface DisbursementInput {
  cause_id: string;
  beneficiary_name: string;
  amount: number;
}

export interface HoldInput {
  reason: string;
  severity: HoldSeverity;
}

export interface AllocationInput {
  cause_id: string;
  amount: number;
}

export async function createCampaign(data: Partial<CampaignInput> = {}): Promise<Campaign> {
  const payload: CampaignInput = {
    name: data.name ?? `Campaign-${uniqueId()}`,
    fundraising_target: data.fundraising_target ?? 100000,
  };
  const res = await postAs('/campaigns', payload);
  expectSuccess(res);
  return unwrap(res.body) as Campaign;
}

export async function getCampaign(campaignId: string): Promise<Campaign> {
  const res = await getAs(`/campaigns/${campaignId}`);
  expectSuccess(res);
  return unwrap(res.body) as Campaign;
}

export async function closeCampaign(campaignId: string): Promise<Campaign> {
  const res = await postAs(`/campaigns/${campaignId}/close`, {});
  expectSuccess(res);
  return unwrap(res.body) as Campaign;
}

export async function createPledge(campaignId: string, data: Partial<PledgeInput> = {}): Promise<Pledge> {
  const payload: PledgeInput = {
    donor_name: data.donor_name ?? `Donor-${uniqueId()}`,
    donor_email: data.donor_email ?? `${uniqueId()}@test.com`,
    amount: data.amount ?? 1000,
  };
  const res = await postAs(`/campaigns/${campaignId}/pledges`, payload);
  expectSuccess(res);
  return unwrap(res.body) as Pledge;
}

export async function getPledge(campaignId: string, pledgeId: string): Promise<Pledge> {
  const res = await getAs(`/campaigns/${campaignId}/pledges/${pledgeId}`);
  expectSuccess(res);
  return unwrap(res.body) as Pledge;
}

export async function fulfillPledge(campaignId: string, pledgeId: string): Promise<Pledge> {
  const res = await postAs(`/campaigns/${campaignId}/pledges/${pledgeId}/fulfill`, {});
  expectSuccess(res);
  return unwrap(res.body) as Pledge;
}

export async function lapsePledge(campaignId: string, pledgeId: string): Promise<Pledge> {
  const res = await postAs(`/campaigns/${campaignId}/pledges/${pledgeId}/lapse`, {});
  expectSuccess(res);
  return unwrap(res.body) as Pledge;
}

export async function voidPledge(campaignId: string, pledgeId: string): Promise<Pledge> {
  const res = await postAs(`/campaigns/${campaignId}/pledges/${pledgeId}/void`, {});
  expectSuccess(res);
  return unwrap(res.body) as Pledge;
}

export async function createContribution(campaignId: string, data: Partial<ContributionInput> = {}): Promise<Contribution> {
  const payload: ContributionInput = {
    donor_name: data.donor_name ?? `Donor-${uniqueId()}`,
    donor_email: data.donor_email ?? `${uniqueId()}@test.com`,
    gross_amount: data.gross_amount ?? 1000,
  };
  if (data.fulfills_pledge_id !== undefined) {
    payload.fulfills_pledge_id = data.fulfills_pledge_id;
  }
  if (data.match_eligible !== undefined) {
    payload.match_eligible = data.match_eligible;
  }
  const res = await postAs(`/campaigns/${campaignId}/contributions`, payload);
  expectSuccess(res);
  return unwrap(res.body) as Contribution;
}

export async function getContribution(campaignId: string, contributionId: string): Promise<Contribution> {
  const res = await getAs(`/campaigns/${campaignId}/contributions/${contributionId}`);
  expectSuccess(res);
  return unwrap(res.body) as Contribution;
}

export async function refundContribution(campaignId: string, contributionId: string): Promise<Contribution> {
  const res = await postAs(`/campaigns/${campaignId}/contributions/${contributionId}/refund`, {});
  expectSuccess(res);
  return unwrap(res.body) as Contribution;
}

export async function allocateContribution(
  campaignId: string,
  contributionId: string,
  data: AllocationInput
): Promise<Contribution> {
  const res = await postAs(`/campaigns/${campaignId}/contributions/${contributionId}/allocate`, data);
  expectSuccess(res);
  return unwrap(res.body) as Contribution;
}

export async function createGrant(campaignId: string, data: Partial<GrantInput> = {}): Promise<Grant> {
  const payload: GrantInput = {
    sponsor_name: data.sponsor_name ?? `Sponsor-${uniqueId()}`,
    match_ratio: data.match_ratio ?? 1.0,
    cap_amount: data.cap_amount ?? 5000,
  };
  if (data.min_contribution !== undefined) {
    payload.min_contribution = data.min_contribution;
  }
  if (data.excludes_pledge_fulfillment !== undefined) {
    payload.excludes_pledge_fulfillment = data.excludes_pledge_fulfillment;
  }
  const res = await postAs(`/campaigns/${campaignId}/grants`, payload);
  expectSuccess(res);
  return unwrap(res.body) as Grant;
}

export async function getGrant(campaignId: string, grantId: string): Promise<Grant> {
  const res = await getAs(`/campaigns/${campaignId}/grants/${grantId}`);
  expectSuccess(res);
  return unwrap(res.body) as Grant;
}

export async function suspendGrant(campaignId: string, grantId: string): Promise<Grant> {
  const res = await postAs(`/campaigns/${campaignId}/grants/${grantId}/suspend`, {});
  expectSuccess(res);
  return unwrap(res.body) as Grant;
}

export async function reactivateGrant(campaignId: string, grantId: string): Promise<Grant> {
  const res = await postAs(`/campaigns/${campaignId}/grants/${grantId}/reactivate`, {});
  expectSuccess(res);
  return unwrap(res.body) as Grant;
}

export async function revokeGrant(campaignId: string, grantId: string): Promise<Grant> {
  const res = await postAs(`/campaigns/${campaignId}/grants/${grantId}/revoke`, {});
  expectSuccess(res);
  return unwrap(res.body) as Grant;
}

export async function createCause(campaignId: string, data: Partial<CauseInput> = {}): Promise<Cause> {
  const payload: CauseInput = {
    name: data.name ?? `Cause-${uniqueId()}`,
    target_amount: data.target_amount ?? 10000,
    priority: data.priority ?? 1,
  };
  if (data.threshold_percent !== undefined) {
    payload.threshold_percent = data.threshold_percent;
  }
  const res = await postAs(`/campaigns/${campaignId}/causes`, payload);
  expectSuccess(res);
  return unwrap(res.body) as Cause;
}

export async function getCause(campaignId: string, causeId: string): Promise<Cause> {
  const res = await getAs(`/campaigns/${campaignId}/causes/${causeId}`);
  expectSuccess(res);
  return unwrap(res.body) as Cause;
}

export async function closeCause(campaignId: string, causeId: string): Promise<Cause> {
  const res = await postAs(`/campaigns/${campaignId}/causes/${causeId}/close`, {});
  expectSuccess(res);
  return unwrap(res.body) as Cause;
}

export async function createDisbursement(campaignId: string, data: DisbursementInput): Promise<Disbursement> {
  const res = await postAs(`/campaigns/${campaignId}/disbursements`, data);
  expectSuccess(res);
  return unwrap(res.body) as Disbursement;
}

export async function getDisbursement(campaignId: string, disbursementId: string): Promise<Disbursement> {
  const res = await getAs(`/campaigns/${campaignId}/disbursements/${disbursementId}`);
  expectSuccess(res);
  return unwrap(res.body) as Disbursement;
}

export async function approveDisbursement(campaignId: string, disbursementId: string): Promise<Disbursement> {
  const res = await postAs(`/campaigns/${campaignId}/disbursements/${disbursementId}/approve`, {});
  expectSuccess(res);
  return unwrap(res.body) as Disbursement;
}

export async function completeDisbursement(campaignId: string, disbursementId: string): Promise<Disbursement> {
  const res = await postAs(`/campaigns/${campaignId}/disbursements/${disbursementId}/complete`, {});
  expectSuccess(res);
  return unwrap(res.body) as Disbursement;
}

export async function voidDisbursement(campaignId: string, disbursementId: string): Promise<Disbursement> {
  const res = await postAs(`/campaigns/${campaignId}/disbursements/${disbursementId}/void`, {});
  expectSuccess(res);
  return unwrap(res.body) as Disbursement;
}

export async function createHold(campaignId: string, data: HoldInput): Promise<Hold> {
  const res = await postAs(`/campaigns/${campaignId}/holds`, data);
  expectSuccess(res);
  return unwrap(res.body) as Hold;
}

export async function getHold(campaignId: string, holdId: string): Promise<Hold> {
  const res = await getAs(`/campaigns/${campaignId}/holds/${holdId}`);
  expectSuccess(res);
  return unwrap(res.body) as Hold;
}

export async function resolveHold(campaignId: string, holdId: string): Promise<Hold> {
  const res = await postAs(`/campaigns/${campaignId}/holds/${holdId}/resolve`, {});
  expectSuccess(res);
  return unwrap(res.body) as Hold;
}
