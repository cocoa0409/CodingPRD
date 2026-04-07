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
  closeCampaign,
  createPledge,
  voidPledge,
  createCause,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_PLEDGE,
  FX_CAMPAIGN_WITH_CONTRIBUTION,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
  FX_CAMPAIGN_WITH_CAUSE,
  FX_THRESHOLD_MET_CAUSE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Campaign Tests', () => {

  test('CAMPAIGN_001: POST /campaigns creates campaign with correct initial values', async () => {
    const res = await postAs('/campaigns', {
      name: 'Hope Fund',
      fundraising_target: 50000,
    });

    expectSuccess(res);
    const campaign = unwrap(res.body);
    expect(campaign.id).toBeDefined();
    expect(campaign.name).toBe('Hope Fund');
    expect(campaign.fundraising_target).toBe(50000);
    expect(campaign.phase).toBe('ACTIVE');
    expect(campaign.posture).toBe('OPEN');
    expect(campaign.pledge_outstanding).toBe(0);
    expect(campaign.contribution_total).toBe(0);
    expect(campaign.match_total).toBe(0);
    expect(campaign.allocated_total).toBe(0);
    expect(campaign.disbursed_total).toBe(0);
    expect(campaign.available_balance).toBe(0);
  });

  test('CAMPAIGN_002: GET /campaigns/:C returns campaign with all fields', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const fetched = unwrap(res.body);
    expect(fetched.id).toBe(campaign.id);
    expect(fetched.name).toBe('Test Campaign');
    expect(fetched.fundraising_target).toBe(100000);
    expect(fetched.phase).toBe('ACTIVE');
    expect(fetched.posture).toBe('OPEN');
    expect(fetched.pledge_outstanding).toBe(0);
    expect(fetched.contribution_total).toBe(0);
    expect(fetched.match_total).toBe(0);
    expect(fetched.allocated_total).toBe(0);
    expect(fetched.disbursed_total).toBe(0);
    expect(fetched.available_balance).toBe(0);
  });

  test('CAMPAIGN_003: POST /campaigns with missing fundraising_target returns ERR_INVALID_REQUEST', async () => {
    const res = await postAs('/campaigns', {
      name: 'Test',
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_REQUEST);
  });

  test('CAMPAIGN_004: GET /campaigns/nonexistent-id returns ERR_NOT_FOUND', async () => {
    const res = await getAs('/campaigns/nonexistent-id');

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('CAMPAIGN_005: POST /campaigns/:C/close succeeds when all pledges are in terminal status', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const pledge = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });
    await voidPledge(campaign.id, pledge.id);

    const res = await postAs(`/campaigns/${campaign.id}/close`, {});

    expectSuccess(res);

    const closedCampaign = await getCampaign(campaign.id);
    expect(closedCampaign.phase).toBe('CLOSED');
  });

  test('CAMPAIGN_006: POST /campaigns/:C/close fails with outstanding pledges', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_PLEDGE();

    const res = await postAs(`/campaigns/${campaign.id}/close`, {});

    await expectErrorCode(res, ERROR_CODES.PLEDGES_OUTSTANDING);

    const unchangedCampaign = await getCampaign(campaign.id);
    expect(unchangedCampaign.phase).toBe('ACTIVE');
  });

  test('CAMPAIGN_007: POST /campaigns/:C/close fails when posture is RESTRICTED', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    const res = await postAs(`/campaigns/${campaign.id}/close`, {});

    await expectErrorCode(res, ERROR_CODES.POSTURE_RESTRICTED);

    const unchangedCampaign = await getCampaign(campaign.id);
    expect(unchangedCampaign.phase).toBe('ACTIVE');
  });

  test('CAMPAIGN_008: POST /campaigns/:C/pledges fails when campaign is closed', async () => {
    const { campaign } = await FX_CAMPAIGN();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'X',
      donor_email: 'x@t.com',
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.CAMPAIGN_CLOSED);
  });

  test('CAMPAIGN_009: POST /campaigns/:C/contributions fails when campaign is closed', async () => {
    const { campaign } = await FX_CAMPAIGN();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'X',
      donor_email: 'x@t.com',
      gross_amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.CAMPAIGN_CLOSED);
  });

  test('CAMPAIGN_010: POST /campaigns/:C/grants fails when campaign is closed', async () => {
    const { campaign } = await FX_CAMPAIGN();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/grants`, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 1000,
    });

    await expectErrorCode(res, ERROR_CODES.CAMPAIGN_CLOSED);
  });

  test('CAMPAIGN_011: POST /campaigns/:C/disbursements succeeds after campaign is closed', async () => {
    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 100,
    });

    expectSuccess(res);
    const disbursement = unwrap(res.body);
    expect(disbursement.id).toBeDefined();
    expect(disbursement.status).toBe('PENDING');
    expect(disbursement.cause_id).toBe(cause.id);
    expect(disbursement.beneficiary_name).toBe('Ben');
    expect(disbursement.amount).toBe(100);
  });

  test('CAMPAIGN_012: POST /campaigns/:C/contributions/:CON/allocate succeeds after campaign is closed', async () => {
    const { campaign, contribution } = await FX_CAMPAIGN_WITH_CONTRIBUTION();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 500,
      priority: 1,
    });

    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 100,
    });

    expectSuccess(res);

    const updatedCause = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);
    expectSuccess(updatedCause);
    const causeData = unwrap(updatedCause.body);
    expect(causeData.allocated_amount).toBe(100);
  });

  test('CAMPAIGN_013: POST /campaigns/:C/causes/:CA/close succeeds after campaign is closed', async () => {
    const { campaign, cause } = await FX_CAMPAIGN_WITH_CAUSE();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/causes/${cause.id}/close`, {});

    expectSuccess(res);

    const closedCause = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);
    expectSuccess(closedCause);
    const causeData = unwrap(closedCause.body);
    expect(causeData.status).toBe('CLOSED');
  });
});
