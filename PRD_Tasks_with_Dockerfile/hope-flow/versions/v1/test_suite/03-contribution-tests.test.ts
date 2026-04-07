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
  getPledge,
  createContribution,
  refundContribution,
  voidPledge,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_CONTRIBUTION,
  FX_CAMPAIGN_WITH_PLEDGE,
  FX_PLEDGE_FULFILLED,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
  FX_CAMPAIGN_WITH_CRITICAL_HOLD,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Contribution Tests', () => {

  test('CONTRIB_001: POST /campaigns/:C/contributions creates contribution with 3% fee (1000 → 970 net)', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.id).toBeDefined();
    expect(contribution.donor_name).toBe('Bob');
    expect(contribution.donor_email).toBe('bob@test.com');
    expect(contribution.gross_amount).toBe(1000);
    expect(contribution.fee_amount).toBe(30);
    expect(contribution.net_amount).toBe(970);
    expect(contribution.status).toBe('CLEARED');
    expect(contribution.matched_amount).toBe(0);
    expect(contribution.allocations).toEqual([]);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(970);
  });

  test('CONTRIB_002: POST /campaigns/:C/contributions with gross_amount=999 has fee=29 (floor of 29.97)', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 999,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.gross_amount).toBe(999);
    expect(contribution.fee_amount).toBe(29);
    expect(contribution.net_amount).toBe(970);
  });

  test('CONTRIB_003: POST /campaigns/:C/contributions with gross_amount=1 has fee=0 (floor of 0.03)', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.gross_amount).toBe(1);
    expect(contribution.fee_amount).toBe(0);
    expect(contribution.net_amount).toBe(1);
  });

  test('CONTRIB_004: POST /campaigns/:C/contributions/:CON/refund refunds contribution and reduces contribution_total', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    const initialCampaign = await getCampaign(campaign.id);
    const initialContributionTotal = initialCampaign.contribution_total;
    const contributionNetAmount = contribution.net_amount;

    expect(initialContributionTotal).toBe(contributionNetAmount);

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/refund`, {});
    expectSuccess(res);

    const refundedContribution = await getContribution(campaign.id, contribution.id);
    expect(refundedContribution.status).toBe('REFUNDED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.contribution_total).toBe(initialContributionTotal - contributionNetAmount);
  });

  test('CONTRIB_005: POST /campaigns/:C/contributions/:CON/refund on REFUNDED contribution returns ERR_INVALID_STATE', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    await refundContribution(campaign.id, contribution.id);

    const refundedContribution = await getContribution(campaign.id, contribution.id);
    expect(refundedContribution.status).toBe('REFUNDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/refund`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getContribution(campaign.id, contribution.id);
    expect(unchanged.status).toBe('REFUNDED');
  });

  test('CONTRIB_006: POST /campaigns/:C/contributions with fulfills_pledge_id fulfills the pledge', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    const pledgeAmount = pledge.amount;

    const initialCampaign = await getCampaign(campaign.id);
    expect(initialCampaign.pledge_outstanding).toBe(pledgeAmount);

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: pledgeAmount,
      fulfills_pledge_id: pledge.id,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.id).toBeDefined();
    expect(contribution.status).toBe('CLEARED');

    const fulfilledPledge = await getPledge(campaign.id, pledge.id);
    expect(fulfilledPledge.status).toBe('FULFILLED');
    expect(fulfilledPledge.fulfilled_contribution_id).toBe(contribution.id);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(0);
  });

  test('CONTRIB_007: POST /campaigns/:C/contributions with mismatched gross_amount returns ERR_PLEDGE_MISMATCH', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: 500,
      fulfills_pledge_id: pledge.id,
    });

    await expectErrorCode(res, ERROR_CODES.PLEDGE_MISMATCH);

    const unchanged = await getPledge(campaign.id, pledge.id);
    expect(unchanged.status).toBe('OUTSTANDING');
  });

  test('CONTRIB_008: POST /campaigns/:C/contributions fulfilling FULFILLED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_PLEDGE_FULFILLED();

    expect(pledge.status).toBe('FULFILLED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('CONTRIB_009: POST /campaigns/:C/contributions fulfilling VOIDED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    await voidPledge(campaign.id, pledge.id);

    const voidedPledge = await getPledge(campaign.id, pledge.id);
    expect(voidedPledge.status).toBe('VOIDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('CONTRIB_010: Refunding contribution that fulfilled pledge reverts pledge to OUTSTANDING', async () => {
    const { campaign, pledge, contribution } = await FX_PLEDGE_FULFILLED();

    const pledgeAmount = pledge.amount;

    expect(pledge.status).toBe('FULFILLED');
    expect(pledge.fulfilled_contribution_id).toBe(contribution.id);

    const initialCampaign = await getCampaign(campaign.id);
    expect(initialCampaign.pledge_outstanding).toBe(0);

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/refund`, {});
    expectSuccess(res);

    const refundedContribution = await getContribution(campaign.id, contribution.id);
    expect(refundedContribution.status).toBe('REFUNDED');

    const revertedPledge = await getPledge(campaign.id, pledge.id);
    expect(revertedPledge.status).toBe('OUTSTANDING');
    expect(revertedPledge.fulfilled_contribution_id).toBeNull();

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(pledgeAmount);
  });

  test('CONTRIB_011: POST /campaigns/:C/contributions on RESTRICTED campaign returns ERR_POSTURE_RESTRICTED', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    expect(campaign.posture).toBe('RESTRICTED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
    });

    await expectErrorCode(res, ERROR_CODES.POSTURE_RESTRICTED);
  });

  test('CONTRIB_012: POST /campaigns/:C/contributions on FROZEN campaign returns ERR_POSTURE_FROZEN', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    expect(campaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
    });

    await expectErrorCode(res, ERROR_CODES.POSTURE_FROZEN);
  });

  test('CONTRIB_013: POST /campaigns/:C/contributions with match_eligible=false creates non-match-eligible contribution', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grantRes = await postAs(`/campaigns/${campaign.id}/grants`, {
      sponsor_name: 'Test Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
    });
    expectSuccess(grantRes);

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: false,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.match_eligible).toBe(false);
    expect(contribution.matched_amount).toBe(0);

    const matchableRes = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: 1000,
    });

    expectSuccess(matchableRes);
    const matchableContribution = unwrap(matchableRes.body);

    expect(matchableContribution.matched_amount).toBe(1000);
  });

  test('CONTRIB_014: Multiple contributions accumulate correctly in contribution_total', async () => {
    const { campaign } = await FX_CAMPAIGN();

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });

    await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 2000,
    });

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const updatedCampaign = unwrap(res.body);
    expect(updatedCampaign.contribution_total).toBe(2910);
  });

  test('CONTRIB_015: POST /campaigns/:C/contributions with missing required fields returns ERR_INVALID_REQUEST', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',

    });

    await expectErrorCode(res, ERROR_CODES.INVALID_REQUEST);
  });
});
