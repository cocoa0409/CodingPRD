import {
  postAs,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  getCampaign,
  getContribution,
  getCause,
  createCause,
  createContribution,
  closeCause,
  refundContribution,
  allocateContribution,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_CONTRIBUTION,
  FX_CONTRIBUTION_WITH_MATCH,
  FX_FUNDED_CAUSE,
  FX_CAMPAIGN_WITH_CAUSE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Allocation Tests', () => {

  test('ALLOC_001: POST /campaigns/:C/contributions/:CON/allocate records allocation successfully', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 500,
    });

    expectSuccess(res);

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.allocations.length).toBe(1);
    expect(updatedContribution.allocations[0].cause_id).toBe(cause.id);
    expect(updatedContribution.allocations[0].amount).toBe(500);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(500);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.allocated_total).toBe(500);
  });

  test('ALLOC_002: POST /campaigns/:C/contributions/:CON/allocate fails when amount exceeds unallocated balance', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    expect(contribution.net_amount).toBe(970);
    expect(contribution.matched_amount).toBe(0);

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 1000,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('ALLOC_003: POST /campaigns/:C/contributions/:CON/allocate can use matched funds', async () => {
    const { campaign, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    expect(contribution.net_amount).toBe(970);
    expect(contribution.matched_amount).toBe(1000);

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 1970,
    });

    expectSuccess(res);

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.allocations.length).toBe(1);
    expect(updatedContribution.allocations[0].cause_id).toBe(cause.id);
    expect(updatedContribution.allocations[0].amount).toBe(1970);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(1970);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.allocated_total).toBe(1970);
  });

  test('ALLOC_004: POST /campaigns/:C/contributions/:CON/allocate fails for FUNDED cause', async () => {
    const { campaign, cause, contribution } = await FX_FUNDED_CAUSE();

    expect(cause.status).toBe('FUNDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.CAUSE_FULL);
  });

  test('ALLOC_005: POST /campaigns/:C/contributions/:CON/allocate fails for CLOSED cause', async () => {
    const { campaign, cause } = await FX_CAMPAIGN_WITH_CAUSE();

    await closeCause(campaign.id, cause.id);
    const closedCause = await getCause(campaign.id, cause.id);
    expect(closedCause.status).toBe('CLOSED');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('ALLOC_006: POST /campaigns/:C/contributions/:CON/allocate fails when amount exceeds cause target', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Small',
      target_amount: 100,
      priority: 1,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 150,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('ALLOC_007: POST /campaigns/:C/contributions/:CON/allocate reaching target transitions cause to FUNDED', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Small',
      target_amount: 100,
      priority: 1,
    });
    expect(cause.status).toBe('OPEN');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 100,
    });

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('FUNDED');
    expect(updatedCause.allocated_amount).toBe(100);
  });

  test('ALLOC_008: POST /campaigns/:C/contributions/:CON/allocate reaching threshold transitions cause to THRESHOLD_MET', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 50,
    });
    expect(cause.status).toBe('OPEN');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 600,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 500,
    });

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(500);
  });

  test('ALLOC_009: POST /campaigns/:C/contributions/:CON/allocate fails for REFUNDED contribution', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    await refundContribution(campaign.id, contribution.id);
    const refundedContribution = await getContribution(campaign.id, contribution.id);
    expect(refundedContribution.status).toBe('REFUNDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('ALLOC_010: POST /campaigns/:C/contributions/:CON/allocate fails when second allocation exceeds remaining balance', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    expect(contribution.net_amount).toBe(970);

    const cause1 = await createCause(campaign.id, {
      name: 'A',
      target_amount: 500,
      priority: 1,
    });

    const cause2 = await createCause(campaign.id, {
      name: 'B',
      target_amount: 500,
      priority: 2,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause1.id,
      amount: 500,
    });

    const afterFirst = await getContribution(campaign.id, contribution.id);
    expect(afterFirst.allocations.length).toBe(1);
    expect(afterFirst.allocations[0].cause_id).toBe(cause1.id);
    expect(afterFirst.allocations[0].amount).toBe(500);

    const campaignBeforeFailure = await getCampaign(campaign.id);
    const cause2BeforeFailure = await getCause(campaign.id, cause2.id);

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause2.id,
      amount: 500,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);

    const contributionAfterFailure = await getContribution(campaign.id, contribution.id);
    expect(contributionAfterFailure.allocations.length).toBe(1);
    expect(contributionAfterFailure.allocations[0].cause_id).toBe(cause1.id);
    expect(contributionAfterFailure.allocations[0].amount).toBe(500);

    const cause2AfterFailure = await getCause(campaign.id, cause2.id);
    expect(cause2AfterFailure.allocated_amount).toBe(cause2BeforeFailure.allocated_amount);
    expect(cause2AfterFailure.allocated_amount).toBe(0);

    const campaignAfterFailure = await getCampaign(campaign.id);
    expect(campaignAfterFailure.allocated_total).toBe(campaignBeforeFailure.allocated_total);
    expect(campaignAfterFailure.allocated_total).toBe(500);
  });

  test('ALLOC_011: GET /campaigns/:C shows correct allocated_total after multiple allocations', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    expect(contribution.net_amount).toBe(970);

    const cause1 = await createCause(campaign.id, {
      name: 'A',
      target_amount: 500,
      priority: 1,
    });

    const cause2 = await createCause(campaign.id, {
      name: 'B',
      target_amount: 500,
      priority: 2,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause1.id,
      amount: 500,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause2.id,
      amount: 470,
    });

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const campaignData = unwrap(res.body);
    expect(campaignData.allocated_total).toBe(970);
  });
});
