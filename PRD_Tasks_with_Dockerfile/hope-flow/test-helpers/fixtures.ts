import {
  Campaign,
  Pledge,
  Contribution,
  Grant,
  Cause,
  Disbursement,
  Hold,
  createCampaign,
  getCampaign,
  createPledge,
  getPledge,
  createContribution,
  getContribution,
  allocateContribution,
  createGrant,
  getGrant,
  createCause,
  getCause,
  createDisbursement,
  getDisbursement,
  approveDisbursement,
  createHold,
} from './resources';

export interface FX_CAMPAIGN_Result {
  campaign: Campaign;
}

export interface FX_CAMPAIGN_WITH_PLEDGE_Result extends FX_CAMPAIGN_Result {
  pledge: Pledge;
}

export interface FX_CAMPAIGN_WITH_CONTRIBUTION_Result extends FX_CAMPAIGN_Result {
  contribution: Contribution;
}

export interface FX_CAMPAIGN_WITH_GRANT_Result extends FX_CAMPAIGN_Result {
  grant: Grant;
}

export interface FX_CAMPAIGN_WITH_CAUSE_Result extends FX_CAMPAIGN_Result {
  cause: Cause;
}

export interface FX_CAMPAIGN_WITH_HOLD_Result extends FX_CAMPAIGN_Result {
  hold: Hold;
}

export interface FX_FUNDED_CAUSE_Result extends FX_CAMPAIGN_Result {
  cause: Cause;
  contribution: Contribution;
}

export interface FX_THRESHOLD_MET_CAUSE_Result extends FX_CAMPAIGN_Result {
  cause: Cause;
  contribution: Contribution;
}

export interface FX_CONTRIBUTION_WITH_MATCH_Result extends FX_CAMPAIGN_Result {
  grant: Grant;
  contribution: Contribution;
}

export interface FX_DISBURSEMENT_PENDING_Result extends FX_THRESHOLD_MET_CAUSE_Result {
  disbursement: Disbursement;
}

export interface FX_DISBURSEMENT_APPROVED_Result extends FX_DISBURSEMENT_PENDING_Result {}

export interface FX_MULTI_GRANT_Result extends FX_CAMPAIGN_Result {
  grant1: Grant;
  grant2: Grant;
}

export interface FX_MULTI_CAUSE_Result extends FX_CAMPAIGN_Result {
  cause1: Cause;
  cause2: Cause;
  cause3: Cause;
}

export interface FX_PLEDGE_FULFILLED_Result extends FX_CAMPAIGN_WITH_PLEDGE_Result {
  contribution: Contribution;
}

export async function FX_CAMPAIGN(): Promise<FX_CAMPAIGN_Result> {
  const campaign = await createCampaign({
    name: 'Test Campaign',
    fundraising_target: 100000,
  });

  const verified = await getCampaign(campaign.id);
  expect(verified.phase).toBe('ACTIVE');
  expect(verified.posture).toBe('OPEN');
  expect(verified.pledge_outstanding).toBe(0);
  expect(verified.contribution_total).toBe(0);
  expect(verified.match_total).toBe(0);
  expect(verified.allocated_total).toBe(0);
  expect(verified.disbursed_total).toBe(0);
  expect(verified.available_balance).toBe(0);

  return { campaign: verified };
}

export async function FX_CAMPAIGN_WITH_PLEDGE(): Promise<FX_CAMPAIGN_WITH_PLEDGE_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const pledge = await createPledge(campaign.id, {
    donor_name: 'Alice',
    donor_email: 'alice@test.com',
    amount: 1000,
  });

  const verifiedPledge = await getPledge(campaign.id, pledge.id);
  expect(verifiedPledge.status).toBe('OUTSTANDING');

  return { campaign, pledge: verifiedPledge };
}

export async function FX_CAMPAIGN_WITH_CONTRIBUTION(): Promise<FX_CAMPAIGN_WITH_CONTRIBUTION_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const contribution = await createContribution(campaign.id, {
    donor_name: 'Bob',
    donor_email: 'bob@test.com',
    gross_amount: 1000,
  });

  const verifiedContribution = await getContribution(campaign.id, contribution.id);
  expect(verifiedContribution.status).toBe('CLEARED');
  expect(verifiedContribution.net_amount).toBe(970);
  expect(verifiedContribution.fee_amount).toBe(30);
  expect(verifiedContribution.matched_amount).toBe(0);

  return { campaign, contribution: verifiedContribution };
}

export async function FX_CAMPAIGN_WITH_GRANT(): Promise<FX_CAMPAIGN_WITH_GRANT_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const grant = await createGrant(campaign.id, {
    sponsor_name: 'Acme Corp',
    match_ratio: 1.0,
    cap_amount: 5000,
  });

  const verifiedGrant = await getGrant(campaign.id, grant.id);
  expect(verifiedGrant.status).toBe('ACTIVE');
  expect(verifiedGrant.matched_so_far).toBe(0);

  return { campaign, grant: verifiedGrant };
}

export async function FX_CAMPAIGN_WITH_CAUSE(): Promise<FX_CAMPAIGN_WITH_CAUSE_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const cause = await createCause(campaign.id, {
    name: 'Medical Aid',
    target_amount: 10000,
    priority: 1,
    threshold_percent: 80,
  });

  const verifiedCause = await getCause(campaign.id, cause.id);
  expect(verifiedCause.status).toBe('OPEN');
  expect(verifiedCause.allocated_amount).toBe(0);
  expect(verifiedCause.disbursed_amount).toBe(0);

  return { campaign, cause: verifiedCause };
}

export async function FX_CAMPAIGN_WITH_STANDARD_HOLD(): Promise<FX_CAMPAIGN_WITH_HOLD_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const hold = await createHold(campaign.id, {
    reason: 'Audit required',
    severity: 'STANDARD',
  });

  const verifiedCampaign = await getCampaign(campaign.id);
  expect(verifiedCampaign.posture).toBe('RESTRICTED');

  return { campaign: verifiedCampaign, hold };
}

export async function FX_CAMPAIGN_WITH_CRITICAL_HOLD(): Promise<FX_CAMPAIGN_WITH_HOLD_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const hold = await createHold(campaign.id, {
    reason: 'Fraud investigation',
    severity: 'CRITICAL',
  });

  const verifiedCampaign = await getCampaign(campaign.id);
  expect(verifiedCampaign.posture).toBe('FROZEN');

  return { campaign: verifiedCampaign, hold };
}

export async function FX_FUNDED_CAUSE(): Promise<FX_FUNDED_CAUSE_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const cause = await createCause(campaign.id, {
    name: 'Education',
    target_amount: 1000,
    priority: 1,
    threshold_percent: 80,
  });

  const contribution = await createContribution(campaign.id, {
    donor_name: 'Bob',
    donor_email: 'bob@test.com',
    gross_amount: 1100,
  });

  await allocateContribution(campaign.id, contribution.id, {
    cause_id: cause.id,
    amount: 1000,
  });

  const verifiedCause = await getCause(campaign.id, cause.id);
  expect(verifiedCause.status).toBe('FUNDED');

  const verifiedContribution = await getContribution(campaign.id, contribution.id);

  return { campaign, cause: verifiedCause, contribution: verifiedContribution };
}

export async function FX_THRESHOLD_MET_CAUSE(): Promise<FX_THRESHOLD_MET_CAUSE_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const cause = await createCause(campaign.id, {
    name: 'Shelter',
    target_amount: 1000,
    priority: 1,
    threshold_percent: 80,
  });

  const contribution = await createContribution(campaign.id, {
    donor_name: 'Bob',
    donor_email: 'bob@test.com',
    gross_amount: 900,
  });

  await allocateContribution(campaign.id, contribution.id, {
    cause_id: cause.id,
    amount: 800,
  });

  const verifiedCause = await getCause(campaign.id, cause.id);
  expect(verifiedCause.status).toBe('THRESHOLD_MET');

  const verifiedContribution = await getContribution(campaign.id, contribution.id);

  return { campaign, cause: verifiedCause, contribution: verifiedContribution };
}

export async function FX_CONTRIBUTION_WITH_MATCH(): Promise<FX_CONTRIBUTION_WITH_MATCH_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const grant = await createGrant(campaign.id, {
    sponsor_name: 'Acme Corp',
    match_ratio: 1.0,
    cap_amount: 5000,
  });

  const contribution = await createContribution(campaign.id, {
    donor_name: 'Bob',
    donor_email: 'bob@test.com',
    gross_amount: 1000,
    match_eligible: true,
  });

  const verifiedContribution = await getContribution(campaign.id, contribution.id);
  expect(verifiedContribution.matched_amount).toBe(1000);

  const verifiedCampaign = await getCampaign(campaign.id);
  expect(verifiedCampaign.match_total).toBe(1000);

  const verifiedGrant = await getGrant(campaign.id, grant.id);

  return { campaign: verifiedCampaign, grant: verifiedGrant, contribution: verifiedContribution };
}

export async function FX_DISBURSEMENT_PENDING(): Promise<FX_DISBURSEMENT_PENDING_Result> {
  const { campaign, cause, contribution } = await FX_THRESHOLD_MET_CAUSE();

  const disbursement = await createDisbursement(campaign.id, {
    cause_id: cause.id,
    beneficiary_name: 'Shelter Inc',
    amount: 500,
  });

  const verifiedDisbursement = await getDisbursement(campaign.id, disbursement.id);
  expect(verifiedDisbursement.status).toBe('PENDING');

  return { campaign, cause, contribution, disbursement: verifiedDisbursement };
}

export async function FX_DISBURSEMENT_APPROVED(): Promise<FX_DISBURSEMENT_APPROVED_Result> {
  const { campaign, cause, contribution, disbursement } = await FX_DISBURSEMENT_PENDING();

  await approveDisbursement(campaign.id, disbursement.id);

  const verifiedDisbursement = await getDisbursement(campaign.id, disbursement.id);
  expect(verifiedDisbursement.status).toBe('APPROVED');

  return { campaign, cause, contribution, disbursement: verifiedDisbursement };
}

export async function FX_MULTI_GRANT(): Promise<FX_MULTI_GRANT_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const grant1 = await createGrant(campaign.id, {
    sponsor_name: 'First Corp',
    match_ratio: 0.5,
    cap_amount: 500,
  });

  const grant2 = await createGrant(campaign.id, {
    sponsor_name: 'Second Corp',
    match_ratio: 1.0,
    cap_amount: 1000,
  });

  return { campaign, grant1, grant2 };
}

export async function FX_MULTI_CAUSE(): Promise<FX_MULTI_CAUSE_Result> {
  const { campaign } = await FX_CAMPAIGN();

  const cause1 = await createCause(campaign.id, {
    name: 'Cause A',
    target_amount: 5000,
    priority: 1,
    threshold_percent: 50,
  });

  const cause2 = await createCause(campaign.id, {
    name: 'Cause B',
    target_amount: 3000,
    priority: 2,
    threshold_percent: 80,
  });

  const cause3 = await createCause(campaign.id, {
    name: 'Cause C',
    target_amount: 2000,
    priority: 3,
    threshold_percent: 100,
  });

  return { campaign, cause1, cause2, cause3 };
}

export async function FX_PLEDGE_FULFILLED(): Promise<FX_PLEDGE_FULFILLED_Result> {
  const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

  const contribution = await createContribution(campaign.id, {
    donor_name: 'Alice',
    donor_email: 'alice@test.com',
    gross_amount: 1000,
    fulfills_pledge_id: pledge.id,
  });

  const verifiedPledge = await getPledge(campaign.id, pledge.id);
  expect(verifiedPledge.status).toBe('FULFILLED');
  expect(verifiedPledge.fulfilled_contribution_id).toBe(contribution.id);

  const verifiedContribution = await getContribution(campaign.id, contribution.id);

  return { campaign, pledge: verifiedPledge, contribution: verifiedContribution };
}
