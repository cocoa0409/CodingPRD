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
  closeCampaign,
} from '../../../test-helpers/resources';
import { FX_CAMPAIGN } from '../../../test-helpers/fixtures';

describe('Feature 12: Deep Integration Tests', () => {

  test('DEEP_001: comprehensive state tracking across resources', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
    });

    const ca1 = await createCause(campaign.id, {
      name: 'Medical',
      target_amount: 3000,
      priority: 1,
      threshold_percent: 80,
    });

    const ca2 = await createCause(campaign.id, {
      name: 'Education',
      target_amount: 2000,
      priority: 2,
      threshold_percent: 100,
    });

    const pledge = await createPledge(campaign.id, {
      donor_name: 'Alice',
      donor_email: 'alice@t.com',
      amount: 2000,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'Bob',
      donor_email: 'bob@t.com',
      gross_amount: 1500,
    });

    expect(c1.net_amount).toBe(1455);
    expect(c1.matched_amount).toBe(1500);

    await allocateContribution(campaign.id, c1.id, {
      cause_id: ca1.id,
      amount: 2910,
    });

    const updatedCampaign = await getCampaign(campaign.id);

    expect(updatedCampaign.pledge_outstanding).toBe(2000);
    expect(updatedCampaign.contribution_total).toBe(1455);
    expect(updatedCampaign.match_total).toBe(1500);
    expect(updatedCampaign.allocated_total).toBe(2910);

    const updatedCA1 = await getCause(campaign.id, ca1.id);
    expect(updatedCA1.allocated_amount).toBe(2910);
    expect(updatedCA1.status).toBe('THRESHOLD_MET');

    const updatedCA2 = await getCause(campaign.id, ca2.id);
    expect(updatedCA2.allocated_amount).toBe(0);
    expect(updatedCA2.status).toBe('OPEN');
  });

  test('DEEP_002: grant revocation affects allocations but completed disbursements remain', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 2000,
      priority: 1,
      threshold_percent: 50,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });

    expect(con.net_amount).toBe(970);
    expect(con.matched_amount).toBe(1000);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 1970,
    });

    let updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(1970);

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 800,
    });

    await approveDisbursement(campaign.id, disbursement.id);
    await completeDisbursement(campaign.id, disbursement.id);

    const completedDisb = await getDisbursement(campaign.id, disbursement.id);
    expect(completedDisb.status).toBe('COMPLETED');

    let campaignBeforeRevoke = await getCampaign(campaign.id);
    expect(campaignBeforeRevoke.disbursed_total).toBe(800);

    await revokeGrant(campaign.id, grant.id);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const campaignAfterRevoke = await getCampaign(campaign.id);

    expect(campaignAfterRevoke.match_total).toBe(0);

    expect(campaignAfterRevoke.disbursed_total).toBe(800);

    const updatedCon = await getContribution(campaign.id, con.id);
    expect(updatedCon.matched_amount).toBe(0);

    updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(970);

    expect(updatedCause.status).toBe('OPEN');

    expect(campaignAfterRevoke.allocated_total).toBe(970);
  });

  test('DEEP_003: refund cascades through pledge, match, and allocation', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 0.5,
      cap_amount: 5000,
      excludes_pledge_fulfillment: false,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
      threshold_percent: 80,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    expect(con.net_amount).toBe(970);
    expect(con.matched_amount).toBe(500);

    let updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('FULFILLED');

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 1470,
    });

    let updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(1470);

    const refundedCon = await refundContribution(campaign.id, con.id);

    expect(refundedCon.status).toBe('REFUNDED');

    updatedPledge = await getPledge(campaign.id, pledge.id);
    expect(updatedPledge.status).toBe('OUTSTANDING');

    updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(0);
    expect(updatedCause.status).toBe('OPEN');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(0);
    expect(updatedCampaign.match_total).toBe(0);
    expect(updatedCampaign.allocated_total).toBe(0);
  });

  test('DEEP_004: disbursed_total reflects only COMPLETED disbursements', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const ca1 = await createCause(campaign.id, {
      name: 'A',
      target_amount: 500,
      priority: 1,
      threshold_percent: 50,
    });

    const ca2 = await createCause(campaign.id, {
      name: 'B',
      target_amount: 500,
      priority: 2,
      threshold_percent: 50,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 1000,
    });

    expect(con.net_amount).toBe(970);

    await allocateContribution(campaign.id, con.id, {
      cause_id: ca1.id,
      amount: 500,
    });

    await allocateContribution(campaign.id, con.id, {
      cause_id: ca2.id,
      amount: 470,
    });

    let updatedCA1 = await getCause(campaign.id, ca1.id);
    expect(updatedCA1.status).toBe('FUNDED');

    let updatedCA2 = await getCause(campaign.id, ca2.id);
    expect(updatedCA2.status).toBe('THRESHOLD_MET');

    const d1 = await createDisbursement(campaign.id, {
      cause_id: ca1.id,
      beneficiary_name: 'B1',
      amount: 300,
    });
    await approveDisbursement(campaign.id, d1.id);
    await completeDisbursement(campaign.id, d1.id);

    const completedD1 = await getDisbursement(campaign.id, d1.id);
    expect(completedD1.status).toBe('COMPLETED');

    const d2 = await createDisbursement(campaign.id, {
      cause_id: ca2.id,
      beneficiary_name: 'B2',
      amount: 200,
    });
    await approveDisbursement(campaign.id, d2.id);

    const approvedD2 = await getDisbursement(campaign.id, d2.id);
    expect(approvedD2.status).toBe('APPROVED');

    const updatedCampaign = await getCampaign(campaign.id);

    expect(updatedCampaign.disbursed_total).toBe(300);

    expect(updatedCampaign.available_balance).toBe(670);

    updatedCA1 = await getCause(campaign.id, ca1.id);
    expect(updatedCA1.disbursed_amount).toBe(300);

    updatedCA2 = await getCause(campaign.id, ca2.id);
    expect(updatedCA2.disbursed_amount).toBe(0);
  });

  test('DEEP_005: grant exhaustion and match eligibility', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 2000,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });
    expect(c1.matched_amount).toBe(1000);

    const c2 = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 1000,
    });
    expect(c2.matched_amount).toBe(1000);

    const c3 = await createContribution(campaign.id, {
      donor_name: 'C',
      donor_email: 'c@t.com',
      gross_amount: 1000,
      match_eligible: false,
    });
    expect(c3.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.status).toBe('EXHAUSTED');
    expect(updatedGrant.matched_so_far).toBe(2000);

    expect(updatedCampaign.contribution_total).toBe(2910);
    expect(updatedCampaign.match_total).toBe(2000);

    const refreshedC1 = await getContribution(campaign.id, c1.id);
    const refreshedC2 = await getContribution(campaign.id, c2.id);
    const refreshedC3 = await getContribution(campaign.id, c3.id);
    expect(refreshedC1.matched_amount).toBe(1000);
    expect(refreshedC2.matched_amount).toBe(1000);
    expect(refreshedC3.matched_amount).toBe(0);
  });

  test('DEEP_006: disbursement allowed when cause threshold is met', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 500,
    });

    expect(con.net_amount).toBe(485);
    expect(con.matched_amount).toBe(500);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 970,
    });

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(970);

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    expect(disbursement.status).toBe('PENDING');
    expect(disbursement.amount).toBe(500);
  });

  test('DEEP_007: campaign close with all pledges in terminal states', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const p1 = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const p2 = await createPledge(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      amount: 500,
    });

    const p3 = await createPledge(campaign.id, {
      donor_name: 'C',
      donor_email: 'c@t.com',
      amount: 200,
    });

    const closeAttemptRes = await postAs(`/campaigns/${campaign.id}/close`, {});
    await expectErrorCode(closeAttemptRes, 'ERR_PLEDGES_OUTSTANDING');

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: p1.id,
    });

    const fulfilledP1 = await getPledge(campaign.id, p1.id);
    expect(fulfilledP1.status).toBe('FULFILLED');

    await voidPledge(campaign.id, p2.id);
    const voidedP2 = await getPledge(campaign.id, p2.id);
    expect(voidedP2.status).toBe('VOIDED');

    await lapsePledge(campaign.id, p3.id);
    const lapsedP3 = await getPledge(campaign.id, p3.id);
    expect(lapsedP3.status).toBe('LAPSED');

    const closedCampaign = await closeCampaign(campaign.id);

    expect(closedCampaign.phase).toBe('CLOSED');
  });

  test('DEEP_008: error precedence - FROZEN takes priority over RESTRICTED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    await createHold(campaign.id, {
      reason: 'Audit',
      severity: 'STANDARD',
    });

    await createHold(campaign.id, {
      reason: 'Fraud',
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

  test('DEEP_009: manually closed cause allows disbursement', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 600,
    });

    expect(con.net_amount).toBe(582);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 582,
    });

    let updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');

    await closeCause(campaign.id, cause.id);

    updatedCause = await getCause(campaign.id, cause.id);

    expect(updatedCause.status).toBe('CLOSED');
    expect(updatedCause.allocated_amount).toBe(582);

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    expect(disbursement.status).toBe('PENDING');
  });

  test('DEEP_010: suspended grant does not match new contributions', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 2000,
      priority: 1,
      threshold_percent: 50,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 600,
    });

    expect(c1.matched_amount).toBe(600);

    await allocateContribution(campaign.id, c1.id, {
      cause_id: cause.id,
      amount: 1182,
    });

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 1000,
    });
    await approveDisbursement(campaign.id, disbursement.id);

    await suspendGrant(campaign.id, grant.id);

    const suspendedGrant = await getGrant(campaign.id, grant.id);
    expect(suspendedGrant.status).toBe('SUSPENDED');

    const c2 = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    expect(c2.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);

    expect(updatedCampaign.contribution_total).toBe(1067);

    expect(updatedCampaign.match_total).toBe(600);
  });

  test('DEEP_011: FUNDED cause rejects additional allocations', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'A',
      target_amount: 100,
      priority: 1,
      threshold_percent: 100,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 200,
    });

    expect(con.net_amount).toBe(194);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 100,
    });

    const fundedCause = await getCause(campaign.id, cause.id);
    expect(fundedCause.status).toBe('FUNDED');

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${con.id}/allocate`,
      {
        cause_id: cause.id,
        amount: 50,
      }
    );

    await expectErrorCode(res, 'ERR_CAUSE_FULL');
  });

  test('DEEP_012: grants apply in creation order with individual caps', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const g1 = await createGrant(campaign.id, {
      sponsor_name: 'A',
      match_ratio: 0.25,
      cap_amount: 100,
    });

    const g2 = await createGrant(campaign.id, {
      sponsor_name: 'B',
      match_ratio: 0.5,
      cap_amount: 200,
    });

    const g3 = await createGrant(campaign.id, {
      sponsor_name: 'C',
      match_ratio: 1.0,
      cap_amount: 300,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 400,
    });

    const updatedCon = await getContribution(campaign.id, con.id);

    expect(updatedCon.matched_amount).toBe(600);

    const updatedG1 = await getGrant(campaign.id, g1.id);
    expect(updatedG1.status).toBe('EXHAUSTED');
    expect(updatedG1.matched_so_far).toBe(100);

    const updatedG2 = await getGrant(campaign.id, g2.id);
    expect(updatedG2.status).toBe('EXHAUSTED');
    expect(updatedG2.matched_so_far).toBe(200);

    const updatedG3 = await getGrant(campaign.id, g3.id);
    expect(updatedG3.status).toBe('EXHAUSTED');
    expect(updatedG3.matched_so_far).toBe(300);
  });

  test('DEEP_013: refund blocked when pending disbursement would be uncovered', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'A',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const con = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 1000,
    });

    expect(con.net_amount).toBe(970);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 800,
    });

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');

    const d1 = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'B1',
      amount: 500,
    });

    expect(d1.status).toBe('PENDING');

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${con.id}/refund`,
      {}
    );

    await expectErrorCode(res, 'ERR_DISBURSEMENT_BLOCKED');
  });

  test('DEEP_014: cause close allowed under RESTRICTED posture', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });

    await createHold(campaign.id, {
      reason: 'Issue',
      severity: 'STANDARD',
    });

    const restrictedCampaign = await getCampaign(campaign.id);
    expect(restrictedCampaign.posture).toBe('RESTRICTED');

    const closedCause = await closeCause(campaign.id, cause.id);

    expect(closedCause.status).toBe('CLOSED');
  });

  test('DEEP_015: comprehensive accounting verification', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'A',
      target_amount: 500,
      priority: 1,

    });

    const con = await createContribution(campaign.id, {
      donor_name: 'D',
      donor_email: 'd@t.com',
      gross_amount: 600,
    });

    expect(con.net_amount).toBe(582);

    await allocateContribution(campaign.id, con.id, {
      cause_id: cause.id,
      amount: 500,
    });

    let updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('FUNDED');

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });
    await approveDisbursement(campaign.id, disbursement.id);
    await completeDisbursement(campaign.id, disbursement.id);

    const completedDisb = await getDisbursement(campaign.id, disbursement.id);
    expect(completedDisb.status).toBe('COMPLETED');

    const updatedCampaign = await getCampaign(campaign.id);

    expect(updatedCampaign.contribution_total).toBe(582);

    expect(updatedCampaign.allocated_total).toBe(500);

    expect(updatedCampaign.disbursed_total).toBe(500);

    expect(updatedCampaign.available_balance).toBe(82);

    updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('FUNDED');
    expect(updatedCause.disbursed_amount).toBe(500);
  });
});
