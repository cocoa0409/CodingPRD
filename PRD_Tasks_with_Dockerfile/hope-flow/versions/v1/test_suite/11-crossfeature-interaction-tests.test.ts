import { postAs, getAs } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
} from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createPledge,
  getPledge,
  lapsePledge,
  voidPledge,
  createContribution,
  getContribution,
  refundContribution,
  allocateContribution,
  createGrant,
  getGrant,
  suspendGrant,
  revokeGrant,
  createCause,
  getCause,
  closeCause,
  createDisbursement,
  getDisbursement,
  approveDisbursement,
  completeDisbursement,
  createHold,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
} from '../../../test-helpers/fixtures';

describe('Feature 11: Cross-Feature Interaction Tests', () => {

  test('CROSS_001: contribution fulfilling pledge is excluded from matching when grant has excludes_pledge_fulfillment=true', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
      excludes_pledge_fulfillment: true,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
      match_eligible: true,
    });

    expect(contribution.matched_amount).toBe(0);

    const updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('FULFILLED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(0);
  });

  test('CROSS_002: matched contribution funds can be allocated to cause and trigger threshold', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 500,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 500,
    });

    expect(contribution.matched_amount).toBe(500);
    expect(contribution.net_amount).toBe(485);

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 985,
    });

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.allocations).toContainEqual({
      cause_id: cause.id,
      amount: 985,
    });

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.allocated_total).toBe(985);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(985);
  });

  test('CROSS_003: refunded contribution reverts pledge to OUTSTANDING allowing re-fulfillment', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    let updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('FULFILLED');

    await refundContribution(campaign.id, contribution.id);

    updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('OUTSTANDING');

    const secondContribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('FULFILLED');
    expect(updatedPledge.fulfilled_contribution_id).toBe(secondContribution.id);
  });

  test('CROSS_004: disbursement succeeds from FUNDED cause (threshold_percent=100)', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 500,
      priority: 1,
      threshold_percent: 100,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 600,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 500,
    });

    const fundedCause = await getCause(campaign.id, cause.id);
    expect(fundedCause.status).toBe('FUNDED');

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    expect(disbursement.status).toBe('PENDING');
    expect(disbursement.amount).toBe(500);
  });

  test('CROSS_005: suspended grant preserves existing matches but does not match new contributions', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 600,
    });

    expect(c1.matched_amount).toBe(600);

    await suspendGrant(campaign.id, grant.id);

    const suspendedGrant = await getGrant(campaign.id, grant.id);
    expect(suspendedGrant.status).toBe('SUSPENDED');

    const c2 = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 400,
    });

    expect(c2.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);

    const updatedC1 = await getContribution(campaign.id, c1.id);
    expect(updatedC1.matched_amount).toBe(600);

    expect(updatedCampaign.match_total).toBe(600);
  });

  test('CROSS_006: causes have independent status transitions based on allocations', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause1 = await createCause(campaign.id, {
      name: 'A',
      target_amount: 1000,
      priority: 1,

    });

    const cause2 = await createCause(campaign.id, {
      name: 'B',
      target_amount: 1000,
      priority: 2,

    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 2000,
    });

    expect(contribution.net_amount).toBe(1940);

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause1.id,
      amount: 1000,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause2.id,
      amount: 940,
    });

    const updatedCampaign = await getCampaign(campaign.id);

    const updatedCause1 = await getCause(campaign.id, cause1.id);
    expect(updatedCause1.status).toBe('FUNDED');
    expect(updatedCause1.allocated_amount).toBe(1000);

    const updatedCause2 = await getCause(campaign.id, cause2.id);
    expect(updatedCause2.status).toBe('OPEN');
    expect(updatedCause2.allocated_amount).toBe(940);
  });

  test('CROSS_007: pledge can be voided under RESTRICTED posture', async () => {

    const { campaign } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    expect(campaign.posture).toBe('RESTRICTED');

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });

    const res = await postAs(
      `/campaigns/${campaign.id}/pledges/${pledge.id}/void`,
      {}
    );

    expectSuccess(res);

    const updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('VOIDED');
  });

  test('CROSS_008: fulfilled pledges are excluded from pledge_outstanding', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const pledge1 = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const pledge2 = await createPledge(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      amount: 500,
    });

    let updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(1500);

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge1.id,
    });

    const updatedPledge1 = await getPledge(campaign.id, pledge1.id);
    expect(updatedPledge1.status).toBe('FULFILLED');
    expect(updatedPledge1.fulfilled_contribution_id).toBe(contribution.id);

    updatedCampaign = await getCampaign(campaign.id);

    expect(updatedCampaign.pledge_outstanding).toBe(500);

    expect(updatedCampaign.contribution_total).toBe(970);
  });

  test('CROSS_009: second disbursement succeeds when disbursable amount is sufficient', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 800,
    });

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');

    const disbursement1 = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 400,
    });

    await approveDisbursement(campaign.id, disbursement1.id);
    await completeDisbursement(campaign.id, disbursement1.id);

    const completedDisbursement = await getDisbursement(
      campaign.id,
      disbursement1.id
    );
    expect(completedDisbursement.status).toBe('COMPLETED');

    const disbursement2 = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Other',
      amount: 400,
    });

    expect(disbursement2.status).toBe('PENDING');
    expect(disbursement2.amount).toBe(400);

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Third',
      amount: 1,
    });

    expectClientError(res);
  });

  test('CROSS_010: allocation of net + matched funds triggers cause threshold', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 0.5,
      cap_amount: 5000,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 2000,
      priority: 1,
      threshold_percent: 50,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });

    expect(contribution.matched_amount).toBe(500);
    expect(contribution.net_amount).toBe(970);

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 1470,
    });

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(1470);

    expect(updatedCause.status).toBe('THRESHOLD_MET');
  });

  test('CROSS_011: FROZEN posture blocks pledge creation', async () => {

    const { campaign } = await FX_CAMPAIGN();

    await createHold(campaign.id, {
      reason: 'Hold',
      severity: 'CRITICAL',
    });

    const frozenCampaign = await getCampaign(campaign.id);
    expect(frozenCampaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });

    await expectErrorCode(res, 'ERR_POSTURE_FROZEN');
  });

  test('CROSS_012: disbursement allowed from CLOSED cause', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 600,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 500,
    });

    let updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');

    await closeCause(campaign.id, cause.id);

    updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('CLOSED');

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 300,
    });

    expect(disbursement.status).toBe('PENDING');
    expect(disbursement.amount).toBe(300);
  });

  test('CROSS_013: revoking one grant only claws back that grants matches', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant1 = await createGrant(campaign.id, {
      sponsor_name: 'First',
      match_ratio: 1.0,
      cap_amount: 200,
    });

    const grant2 = await createGrant(campaign.id, {
      sponsor_name: 'Second',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 500,
    });

    expect(contribution.matched_amount).toBe(700);

    let updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(700);

    const g1BeforeRevoke = await getGrant(campaign.id, grant1.id);
    expect(g1BeforeRevoke.status).toBe('EXHAUSTED');
    expect(g1BeforeRevoke.matched_so_far).toBe(200);

    const g2BeforeRevoke = await getGrant(campaign.id, grant2.id);
    expect(g2BeforeRevoke.matched_so_far).toBe(500);

    await revokeGrant(campaign.id, grant1.id);

    const revokedGrant = await getGrant(campaign.id, grant1.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const updatedContribution = await getContribution(
      campaign.id,
      contribution.id
    );
    expect(updatedContribution.matched_amount).toBe(500);

    updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(500);

    const g2AfterRevoke = await getGrant(campaign.id, grant2.id);
    expect(g2AfterRevoke.status).toBe('ACTIVE');
    expect(g2AfterRevoke.matched_so_far).toBe(500);
  });

  test('CROSS_014: contribution cannot fulfill LAPSED pledge', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    await lapsePledge(campaign.id, pledge.id);

    const lapsedPledge = await getPledge(campaign.id, pledge.id);
    expect(lapsedPledge.status).toBe('LAPSED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const pledgeAfterFailure = await getPledge(campaign.id, pledge.id);
    expect(pledgeAfterFailure.status).toBe('LAPSED');
  });
});
