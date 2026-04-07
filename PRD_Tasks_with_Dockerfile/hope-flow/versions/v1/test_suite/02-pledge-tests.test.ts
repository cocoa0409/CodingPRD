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
  getPledge,
  createPledge,
  voidPledge,
  lapsePledge,
  createHold,
  resolveHold,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_PLEDGE,
  FX_PLEDGE_FULFILLED,
  FX_CAMPAIGN_WITH_CRITICAL_HOLD,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Pledge Tests', () => {

  test('PLEDGE_001: POST /campaigns/:C/pledges creates pledge with OUTSTANDING status', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      amount: 5000,
    });

    expectSuccess(res);
    const pledge = unwrap(res.body);
    expect(pledge.id).toBeDefined();
    expect(pledge.donor_name).toBe('Alice');
    expect(pledge.donor_email).toBe('alice@test.com');
    expect(pledge.amount).toBe(5000);
    expect(pledge.status).toBe('OUTSTANDING');
    expect(pledge.fulfilled_contribution_id).toBeNull();

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(5000);
  });

  test('PLEDGE_002: GET /campaigns/:C/pledges/:P returns pledge with correct fields', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    const res = await getAs(`/campaigns/${campaign.id}/pledges/${pledge.id}`);

    expectSuccess(res);
    const fetched = unwrap(res.body);

    expect(fetched.id).toBe(pledge.id);
    expect(fetched.donor_name).toBe(pledge.donor_name);
    expect(fetched.donor_email).toBe(pledge.donor_email);
    expect(fetched.amount).toBe(pledge.amount);
    expect(fetched.status).toBe(pledge.status);
    expect(fetched.fulfilled_contribution_id).toBe(pledge.fulfilled_contribution_id);
  });

  test('PLEDGE_003: POST /campaigns/:C/pledges with missing required fields returns ERR_INVALID_REQUEST', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'Test',
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_REQUEST);
  });

  test('PLEDGE_004: POST /campaigns/:C/pledges/:P/void voids pledge and reduces pledge_outstanding', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    const initialCampaign = await getCampaign(campaign.id);
    expect(initialCampaign.pledge_outstanding).toBe(1000);

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/void`, {});
    expectSuccess(res);

    const voidedPledge = await getPledge(campaign.id, pledge.id);
    expect(voidedPledge.status).toBe('VOIDED');
    expect(voidedPledge.fulfilled_contribution_id).toBeNull();

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(0);
  });

  test('PLEDGE_005: POST /campaigns/:C/pledges/:P/lapse lapses pledge and reduces pledge_outstanding', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    const initialCampaign = await getCampaign(campaign.id);
    expect(initialCampaign.pledge_outstanding).toBe(1000);

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/lapse`, {});
    expectSuccess(res);

    const lapsedPledge = await getPledge(campaign.id, pledge.id);
    expect(lapsedPledge.status).toBe('LAPSED');
    expect(lapsedPledge.fulfilled_contribution_id).toBeNull();

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(0);
  });

  test('PLEDGE_006: POST /campaigns/:C/pledges/:P/void on FULFILLED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_PLEDGE_FULFILLED();

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/void`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getPledge(campaign.id, pledge.id);
    expect(unchanged.status).toBe('FULFILLED');
  });

  test('PLEDGE_007: POST /campaigns/:C/pledges/:P/lapse on FULFILLED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_PLEDGE_FULFILLED();

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/lapse`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getPledge(campaign.id, pledge.id);
    expect(unchanged.status).toBe('FULFILLED');
  });

  test('PLEDGE_008: POST /campaigns/:C/pledges/:P/lapse on VOIDED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    await voidPledge(campaign.id, pledge.id);

    const voidedPledge = await getPledge(campaign.id, pledge.id);
    expect(voidedPledge.status).toBe('VOIDED');

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/lapse`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getPledge(campaign.id, pledge.id);
    expect(unchanged.status).toBe('VOIDED');
  });

  test('PLEDGE_009: POST /campaigns/:C/pledges/:P/void on LAPSED pledge returns ERR_INVALID_STATE', async () => {
    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    await lapsePledge(campaign.id, pledge.id);

    const lapsedPledge = await getPledge(campaign.id, pledge.id);
    expect(lapsedPledge.status).toBe('LAPSED');

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/void`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getPledge(campaign.id, pledge.id);
    expect(unchanged.status).toBe('LAPSED');
  });

  test('PLEDGE_010: Multiple pledges sum correctly in pledge_outstanding', async () => {
    const { campaign } = await FX_CAMPAIGN();

    await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });

    await createPledge(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      amount: 200,
    });

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const updatedCampaign = unwrap(res.body);
    expect(updatedCampaign.pledge_outstanding).toBe(300);
  });

  test('PLEDGE_011: Voiding one pledge reduces pledge_outstanding correctly', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const pledge1 = await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });

    await createPledge(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      amount: 200,
    });

    await voidPledge(campaign.id, pledge1.id);

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const updatedCampaign = unwrap(res.body);
    expect(updatedCampaign.pledge_outstanding).toBe(200);
  });

  test('PLEDGE_012: Creating a new critical hold after pledge creation freezes campaign', async () => {
    const { campaign, hold } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    await resolveHold(campaign.id, hold.id);

    const openCampaign = await getCampaign(campaign.id);
    expect(openCampaign.posture).toBe('OPEN');

    await createPledge(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      amount: 100,
    });

    const res = await postAs(`/campaigns/${campaign.id}/holds`, {
      reason: 'New issue',
      severity: 'CRITICAL',
    });

    expectSuccess(res);
    const newHold = unwrap(res.body);
    expect(newHold.status).toBe('ACTIVE');
    expect(newHold.severity).toBe('CRITICAL');

    const frozenCampaign = await getCampaign(campaign.id);
    expect(frozenCampaign.posture).toBe('FROZEN');
  });

  test('PLEDGE_013: POST /campaigns/:C/pledges on FROZEN campaign returns ERR_POSTURE_FROZEN', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    expect(campaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'Test',
      donor_email: 't@t.com',
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.POSTURE_FROZEN);
  });

  test('PLEDGE_014: POST /campaigns/:C/pledges on RESTRICTED campaign succeeds', async () => {
    const { campaign } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    const initialCampaign = await getCampaign(campaign.id);
    const initialPledgeOutstanding = initialCampaign.pledge_outstanding;

    expect(campaign.posture).toBe('RESTRICTED');

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'Test',
      donor_email: 't@t.com',
      amount: 100,
    });

    expectSuccess(res);
    const pledge = unwrap(res.body);
    expect(pledge.id).toBeDefined();
    expect(pledge.donor_name).toBe('Test');
    expect(pledge.donor_email).toBe('t@t.com');
    expect(pledge.amount).toBe(100);
    expect(pledge.status).toBe('OUTSTANDING');
    expect(pledge.fulfilled_contribution_id).toBeNull();

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.pledge_outstanding).toBe(initialPledgeOutstanding + 100);
  });
});
