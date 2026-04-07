import { postAs, getAs } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
} from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createCause,
  getCause,
  createContribution,
  allocateContribution,
  createDisbursement,
  getDisbursement,
  approveDisbursement,
  completeDisbursement,
  voidDisbursement,
  createHold,
  resolveHold,
  closeCause,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_THRESHOLD_MET_CAUSE,
  FX_CAMPAIGN_WITH_CAUSE,
  FX_DISBURSEMENT_PENDING,
  FX_DISBURSEMENT_APPROVED,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
  FX_CAMPAIGN,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 7: Disbursement Tests', () => {

  test('DISB_001: Create disbursement on THRESHOLD_MET cause succeeds with PENDING status', async () => {

    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Shelter Inc',
      amount: 500,
    });

    expectSuccess(res);
    const disbursement = unwrap(res.body);
    expect(disbursement.status).toBe('PENDING');

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.disbursed_amount).toBe(0);
  });

  test('DISB_002: Create disbursement fails when cause is OPEN (threshold not met)', async () => {

    const { campaign, cause } = await FX_CAMPAIGN_WITH_CAUSE();

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });
    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 100,
    });

    const causeState = await getCause(campaign.id, cause.id);
    expect(causeState.status).toBe('OPEN');

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('DISB_003: Create disbursement fails when amount exceeds allocated', async () => {

    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 801,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('DISB_004: Create disbursement fails when pending disbursements reduce disbursable amount', async () => {

    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Other',
      amount: 400,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('DISB_005: Approve pending disbursement succeeds', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_PENDING();

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/approve`,
      {}
    );

    expectSuccess(res);
    const updatedDisbursement = await getDisbursement(campaign.id, disbursement.id);
    expect(updatedDisbursement.status).toBe('APPROVED');
  });

  test('DISB_006: Approve already approved disbursement fails', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_APPROVED();

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/approve`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('DISB_007: Complete approved disbursement succeeds and updates totals', async () => {

    const { campaign, cause, disbursement } = await FX_DISBURSEMENT_APPROVED();

    const campaignBefore = await getCampaign(campaign.id);

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/complete`,
      {}
    );

    expectSuccess(res);

    const updatedDisbursement = await getDisbursement(campaign.id, disbursement.id);
    expect(updatedDisbursement.status).toBe('COMPLETED');

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.disbursed_amount).toBe(500);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.disbursed_total).toBe(500);

    expect(updatedCampaign.available_balance).toBe(373);
  });

  test('DISB_008: Complete pending disbursement fails (must be APPROVED first)', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_PENDING();

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/complete`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('DISB_009: Void pending disbursement succeeds', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_PENDING();

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/void`,
      {}
    );

    expectSuccess(res);
    const updatedDisbursement = await getDisbursement(campaign.id, disbursement.id);
    expect(updatedDisbursement.status).toBe('VOIDED');
  });

  test('DISB_010: Void approved disbursement succeeds', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_APPROVED();

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/void`,
      {}
    );

    expectSuccess(res);
    const updatedDisbursement = await getDisbursement(campaign.id, disbursement.id);
    expect(updatedDisbursement.status).toBe('VOIDED');
  });

  test('DISB_011: Void completed disbursement fails', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_APPROVED();
    await completeDisbursement(campaign.id, disbursement.id);

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/void`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('DISB_012: Create disbursement fails when campaign posture is RESTRICTED', async () => {

    const { campaign, hold } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    await resolveHold(campaign.id, hold.id);

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 1000,
    });
    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 500,
    });

    const causeState = await getCause(campaign.id, cause.id);
    expect(causeState.status).toBe('THRESHOLD_MET');

    await createHold(campaign.id, {
      reason: 'New issue',
      severity: 'STANDARD',
    });

    const campaignState = await getCampaign(campaign.id);
    expect(campaignState.posture).toBe('RESTRICTED');

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.POSTURE_RESTRICTED);
  });

  test('DISB_013: Complete disbursement fails when campaign posture is RESTRICTED', async () => {

    const { campaign, disbursement } = await FX_DISBURSEMENT_APPROVED();

    await createHold(campaign.id, {
      reason: 'Issue',
      severity: 'STANDARD',
    });

    const campaignState = await getCampaign(campaign.id);
    expect(campaignState.posture).toBe('RESTRICTED');

    const res = await postAs(
      `/campaigns/${campaign.id}/disbursements/${disbursement.id}/complete`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.POSTURE_RESTRICTED);
  });

  test('DISB_014: Voiding disbursement releases reserved amount for new disbursement', async () => {

    const { campaign, cause, disbursement } = await FX_DISBURSEMENT_PENDING();

    const resBefore = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'PreVoid',
      amount: 800,
    });
    await expectErrorCode(resBefore, ERROR_CODES.ALLOCATION_EXCEEDED);

    await voidDisbursement(campaign.id, disbursement.id);

    const d2 = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Other',
      amount: 800,
    });
    expect(d2.status).toBe('PENDING');

    const res = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);

    expectSuccess(res);
    const updatedCause = unwrap(res.body);
    expect(updatedCause.allocated_amount).toBe(800);
    expect(updatedCause.disbursed_amount).toBe(0);

    const resAfter = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Another',
      amount: 1,
    });
    await expectErrorCode(resAfter, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('DISB_015: Create disbursement fails when campaign has insufficient available_balance', async () => {

    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    const campaignState = await getCampaign(campaign.id);
    expect(campaignState.available_balance).toBe(873);

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 900,
    });

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_FUNDS);
  });

  test('DISB_016: Create disbursement succeeds on CLOSED cause with funds', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 1000,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 800,
    });

    const causeStateBefore = await getCause(campaign.id, cause.id);
    expect(causeStateBefore.status).toBe('THRESHOLD_MET');

    await closeCause(campaign.id, cause.id);

    const causeStateAfter = await getCause(campaign.id, cause.id);
    expect(causeStateAfter.status).toBe('CLOSED');

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    expectSuccess(res);
    const disbursement = unwrap(res.body);
    expect(disbursement.status).toBe('PENDING');
  });
});
