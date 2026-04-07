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
  getCause,
  getContribution,
  getGrant,
  createCause,
  createContribution,
  createGrant,
  createPledge,
  allocateContribution,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Boundary and Edge Cases Tests', () => {

  test('EDGE_003: POST /campaigns/:C/causes with threshold_percent=0 creates cause eligible for disbursement', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/causes`, {
      name: 'Aid',
      target_amount: 100,
      priority: 1,
      threshold_percent: 0,
    });

    expectSuccess(res);
    const cause = unwrap(res.body);
    expect(cause.id).toBeDefined();
    expect(cause.name).toBe('Aid');
    expect(cause.target_amount).toBe(100);
    expect(cause.priority).toBe(1);
    expect(cause.threshold_percent).toBe(0);

    expect(cause.status).toBe('THRESHOLD_MET');
  });

  test('EDGE_006: contribution below min_contribution gets no matching', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
      min_contribution: 1000,
    });
    expect(grant.min_contribution).toBe(1000);

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 999,
    });

    const res = await getAs(`/campaigns/${campaign.id}/contributions/${contribution.id}`);
    expectSuccess(res);
    const verifiedContribution = unwrap(res.body);
    expect(verifiedContribution.matched_amount).toBe(0);
  });

  test('EDGE_007: allocating exactly target_amount=1 transitions cause to FUNDED', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Tiny',
      target_amount: 1,
      priority: 1,
      threshold_percent: 100,
    });
    expect(cause.status).toBe('OPEN');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 1,
    });

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.status).toBe('FUNDED');
    expect(updatedCause.allocated_amount).toBe(1);
  });

  test('EDGE_008: 98.9% allocation is below 99% threshold - cause remains OPEN', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 99,
    });
    expect(cause.status).toBe('OPEN');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1100,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 989,
    });

    const res = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);
    expectSuccess(res);
    const updatedCause = unwrap(res.body);
    expect(updatedCause.status).toBe('OPEN');
    expect(updatedCause.allocated_amount).toBe(989);
  });

  test('EDGE_009: exactly 99% allocation meets 99% threshold - cause becomes THRESHOLD_MET', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 99,
    });
    expect(cause.status).toBe('OPEN');

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1100,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 990,
    });

    const res = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);
    expectSuccess(res);
    const updatedCause = unwrap(res.body);
    expect(updatedCause.status).toBe('THRESHOLD_MET');
    expect(updatedCause.allocated_amount).toBe(990);
  });

  test('EDGE_010: contribution with gross_amount=33 has fee_amount=0 (floor of 0.99)', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 33,
    });

    const res = await getAs(`/campaigns/${campaign.id}/contributions/${contribution.id}`);
    expectSuccess(res);
    const verifiedContribution = unwrap(res.body);
    expect(verifiedContribution.fee_amount).toBe(0);
    expect(verifiedContribution.net_amount).toBe(33);
  });

  test('EDGE_011: contribution with gross_amount=34 has fee_amount=1 (floor of 1.02)', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 34,
    });

    const res = await getAs(`/campaigns/${campaign.id}/contributions/${contribution.id}`);
    expectSuccess(res);
    const verifiedContribution = unwrap(res.body);
    expect(verifiedContribution.fee_amount).toBe(1);
    expect(verifiedContribution.net_amount).toBe(33);
  });

  test('EDGE_013: pledge with amount=1 can be fulfilled with contribution of gross_amount=1', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 1,
    });
    expect(pledge.amount).toBe(1);
    expect(pledge.status).toBe('OUTSTANDING');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1,
      fulfills_pledge_id: pledge.id,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.gross_amount).toBe(1);
    expect(contribution.fee_amount).toBe(0);
    expect(contribution.net_amount).toBe(1);
    expect(contribution.status).toBe('CLEARED');

    const updatedPledge = await getAs(`/campaigns/${campaign.id}/pledges/${pledge.id}`);
    expectSuccess(updatedPledge);
    const pledgeData = unwrap(updatedPledge.body);
    expect(pledgeData.status).toBe('FULFILLED');
    expect(pledgeData.fulfilled_contribution_id).toBe(contribution.id);
  });

  test('EDGE_014: campaign can have multiple causes with unique priorities 1-4', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause1 = await createCause(campaign.id, {
      name: 'A',
      target_amount: 1000,
      priority: 1,
    });
    expect(cause1.priority).toBe(1);

    const cause2 = await createCause(campaign.id, {
      name: 'B',
      target_amount: 1000,
      priority: 2,
    });
    expect(cause2.priority).toBe(2);

    const cause3 = await createCause(campaign.id, {
      name: 'C',
      target_amount: 1000,
      priority: 3,
    });
    expect(cause3.priority).toBe(3);

    const cause4 = await createCause(campaign.id, {
      name: 'D',
      target_amount: 1000,
      priority: 4,
    });
    expect(cause4.priority).toBe(4);

    const res = await getAs(`/campaigns/${campaign.id}`);
    expectSuccess(res);
    const campaignData = unwrap(res.body);
    expect(campaignData.id).toBe(campaign.id);

    const verifiedCause1 = await getCause(campaign.id, cause1.id);
    expect(verifiedCause1.priority).toBe(1);

    const verifiedCause2 = await getCause(campaign.id, cause2.id);
    expect(verifiedCause2.priority).toBe(2);

    const verifiedCause3 = await getCause(campaign.id, cause3.id);
    expect(verifiedCause3.priority).toBe(3);

    const verifiedCause4 = await getCause(campaign.id, cause4.id);
    expect(verifiedCause4.priority).toBe(4);
  });

});
