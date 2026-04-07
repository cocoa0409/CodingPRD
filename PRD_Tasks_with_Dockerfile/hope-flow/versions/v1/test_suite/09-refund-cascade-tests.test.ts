import { postAs } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createContribution,
  getContribution,
  allocateContribution,
  createCause,
  getCause,
  createGrant,
  createDisbursement,
  getDisbursement,
  voidDisbursement,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CONTRIBUTION_WITH_MATCH,
  FX_FUNDED_CAUSE,
  FX_THRESHOLD_MET_CAUSE,
} from '../../../test-helpers/fixtures';

describe('Feature 9: Refund Cascade Tests', () => {

  test('REFUND_001: refunding contribution clears allocations and updates totals', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
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

    const preRefundCampaign = await getCampaign(campaign.id);
    expect(preRefundCampaign.contribution_total).toBe(970);
    expect(preRefundCampaign.allocated_total).toBe(500);

    const preRefundCause = await getCause(campaign.id, cause.id);
    expect(preRefundCause.allocated_amount).toBe(500);

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    expectSuccess(res);

    const refundedContribution = await getContribution(
      campaign.id,
      contribution.id
    );
    expect(refundedContribution.status).toBe('REFUNDED');

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(0);
    expect(updatedCampaign.allocated_total).toBe(0);
  });

  test('REFUND_002: refunding matched contribution claws back match and clears allocations', async () => {

    const { campaign, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 1970,
    });

    const preRefundCampaign = await getCampaign(campaign.id);
    expect(preRefundCampaign.contribution_total).toBe(970);
    expect(preRefundCampaign.match_total).toBe(1000);
    expect(preRefundCampaign.allocated_total).toBe(1970);

    const preRefundContribution = await getContribution(
      campaign.id,
      contribution.id
    );
    expect(preRefundContribution.matched_amount).toBe(1000);

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    expectSuccess(res);

    const refundedContribution = await getContribution(
      campaign.id,
      contribution.id
    );
    expect(refundedContribution.status).toBe('REFUNDED');
    expect(refundedContribution.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(0);
    expect(updatedCampaign.match_total).toBe(0);
    expect(updatedCampaign.allocated_total).toBe(0);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(0);
  });

  test('REFUND_003: refunding contribution reverts cause status from THRESHOLD_MET to OPEN', async () => {

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

    const preRefundCause = await getCause(campaign.id, cause.id);
    expect(preRefundCause.status).toBe('THRESHOLD_MET');
    expect(preRefundCause.allocated_amount).toBe(800);

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('OPEN');
    expect(updatedCause.allocated_amount).toBe(0);
  });

  test('REFUND_004: refunding contribution reverts cause status from FUNDED to OPEN', async () => {

    const { campaign, cause, contribution } = await FX_FUNDED_CAUSE();

    expect(cause.status).toBe('FUNDED');
    expect(cause.allocated_amount).toBe(1000);

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('OPEN');
    expect(updatedCause.allocated_amount).toBe(0);
  });

  test('REFUND_005: refund recalculates cause status, stays THRESHOLD_MET if still above threshold', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 700,
    });

    const c2 = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    await allocateContribution(campaign.id, c1.id, {
      cause_id: cause.id,
      amount: 679,
    });

    await allocateContribution(campaign.id, c2.id, {
      cause_id: cause.id,
      amount: 321,
    });

    const preRefundCause = await getCause(campaign.id, cause.id);
    expect(preRefundCause.allocated_amount).toBe(1000);
    expect(preRefundCause.status).toBe('FUNDED');

    const preRefundCampaign = await getCampaign(campaign.id);
    expect(preRefundCampaign.contribution_total).toBe(1164);
    expect(preRefundCampaign.allocated_total).toBe(1000);

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${c2.id}/refund`,
      {}
    );

    expectSuccess(res);

    const refundedC2 = await getContribution(campaign.id, c2.id);
    expect(refundedC2.status).toBe('REFUNDED');

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(679);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(679);
    expect(updatedCampaign.allocated_total).toBe(679);
  });

  test('REFUND_006: refund fails when pending disbursement exists', async () => {

    const { campaign, cause, contribution } = await FX_THRESHOLD_MET_CAUSE();

    const preRefundCampaign = await getCampaign(campaign.id);
    const preRefundCause = await getCause(campaign.id, cause.id);
    const preRefundContribution = await getContribution(campaign.id, contribution.id);

    await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    await expectErrorCode(res, 'ERR_DISBURSEMENT_BLOCKED');

    const unchangedContribution = await getContribution(campaign.id, contribution.id);
    expect(unchangedContribution.status).toBe('CLEARED');

    const unchangedCause = await getCause(campaign.id, cause.id);
    expect(unchangedCause.allocated_amount).toBe(preRefundCause.allocated_amount);

    const unchangedCampaign = await getCampaign(campaign.id);
    expect(unchangedCampaign.contribution_total).toBe(preRefundCampaign.contribution_total);
    expect(unchangedCampaign.allocated_total).toBe(preRefundCampaign.allocated_total);
  });

  test('REFUND_007: refund succeeds after disbursement is voided', async () => {

    const { campaign, cause, contribution } = await FX_THRESHOLD_MET_CAUSE();

    const preRefundCampaign = await getCampaign(campaign.id);
    const preRefundCause = await getCause(campaign.id, cause.id);

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 500,
    });

    await voidDisbursement(campaign.id, disbursement.id);

    const voidedDisbursement = await getDisbursement(campaign.id, disbursement.id);
    expect(voidedDisbursement.status).toBe('VOIDED');

    const res = await postAs(
      `/campaigns/${campaign.id}/contributions/${contribution.id}/refund`,
      {}
    );

    expectSuccess(res);

    const refundedContribution = await getContribution(
      campaign.id,
      contribution.id
    );
    expect(refundedContribution.status).toBe('REFUNDED');

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(0);
    expect(updatedCause.status).toBe('OPEN');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(0);
    expect(updatedCampaign.allocated_total).toBe(0);
  });
});
