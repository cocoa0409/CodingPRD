import { postAs, getAs } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createHold,
  getHold,
  resolveHold,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_STANDARD_HOLD,
  FX_CAMPAIGN_WITH_CRITICAL_HOLD,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 8: Hold Tests', () => {

  test('HOLD_001: Create standard hold, campaign becomes RESTRICTED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/holds`, {
      reason: 'Audit required',
      severity: 'STANDARD',
    });

    expectSuccess(res);
    const hold = unwrap(res.body);
    expect(hold.id).toBeDefined();
    expect(hold.reason).toBe('Audit required');
    expect(hold.severity).toBe('STANDARD');
    expect(hold.status).toBe('ACTIVE');

    const fetchedHold = await getHold(campaign.id, hold.id);
    expect(fetchedHold.status).toBe('ACTIVE');
    expect(fetchedHold.reason).toBe('Audit required');
    expect(fetchedHold.severity).toBe('STANDARD');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.posture).toBe('RESTRICTED');
  });

  test('HOLD_002: Create critical hold, campaign becomes FROZEN', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/holds`, {
      reason: 'Fraud investigation',
      severity: 'CRITICAL',
    });

    expectSuccess(res);
    const hold = unwrap(res.body);
    expect(hold.id).toBeDefined();
    expect(hold.reason).toBe('Fraud investigation');
    expect(hold.severity).toBe('CRITICAL');
    expect(hold.status).toBe('ACTIVE');

    const fetchedHold = await getHold(campaign.id, hold.id);
    expect(fetchedHold.status).toBe('ACTIVE');
    expect(fetchedHold.reason).toBe('Fraud investigation');
    expect(fetchedHold.severity).toBe('CRITICAL');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.posture).toBe('FROZEN');
  });

  test('HOLD_003: Resolve standard hold, campaign returns to OPEN', async () => {

    const { campaign, hold } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    expect(campaign.posture).toBe('RESTRICTED');

    const res = await postAs(
      `/campaigns/${campaign.id}/holds/${hold.id}/resolve`,
      {}
    );

    expectSuccess(res);
    const resolvedHold = unwrap(res.body);
    expect(resolvedHold.id).toBe(hold.id);
    expect(resolvedHold.status).toBe('RESOLVED');

    const fetchedHold = await getHold(campaign.id, hold.id);
    expect(fetchedHold.id).toBe(hold.id);
    expect(fetchedHold.status).toBe('RESOLVED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.posture).toBe('OPEN');
  });

  test('HOLD_004: Resolve already resolved hold fails', async () => {

    const { campaign, hold } = await FX_CAMPAIGN_WITH_STANDARD_HOLD();

    await resolveHold(campaign.id, hold.id);

    const resolvedHold = await getHold(campaign.id, hold.id);
    expect(resolvedHold.status).toBe('RESOLVED');

    const res = await postAs(
      `/campaigns/${campaign.id}/holds/${hold.id}/resolve`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('HOLD_005: Resolving one of two standard holds keeps RESTRICTED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const h1 = await createHold(campaign.id, {
      reason: 'Issue 1',
      severity: 'STANDARD',
    });
    const h2 = await createHold(campaign.id, {
      reason: 'Issue 2',
      severity: 'STANDARD',
    });

    const campaignAfterHolds = await getCampaign(campaign.id);
    expect(campaignAfterHolds.posture).toBe('RESTRICTED');

    const res = await postAs(
      `/campaigns/${campaign.id}/holds/${h1.id}/resolve`,
      {}
    );

    expectSuccess(res);
    const resolvedH1 = unwrap(res.body);
    expect(resolvedH1.status).toBe('RESOLVED');

    const h1State = await getHold(campaign.id, h1.id);
    expect(h1State.id).toBe(h1.id);
    expect(h1State.status).toBe('RESOLVED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.posture).toBe('RESTRICTED');

    const h2State = await getHold(campaign.id, h2.id);
    expect(h2State.status).toBe('ACTIVE');
  });

  test('HOLD_006: Critical hold overrides standard hold for FROZEN posture', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const h1 = await createHold(campaign.id, {
      reason: 'Minor',
      severity: 'STANDARD',
    });

    expect(h1.status).toBe('ACTIVE');
    expect(h1.severity).toBe('STANDARD');

    const h2 = await createHold(campaign.id, {
      reason: 'Major',
      severity: 'CRITICAL',
    });

    expect(h2.status).toBe('ACTIVE');
    expect(h2.severity).toBe('CRITICAL');

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const updatedCampaign = unwrap(res.body);
    expect(updatedCampaign.posture).toBe('FROZEN');
  });

  test('HOLD_007: Resolving critical hold leaves standard causing RESTRICTED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const h1 = await createHold(campaign.id, {
      reason: 'Minor',
      severity: 'STANDARD',
    });

    const h2 = await createHold(campaign.id, {
      reason: 'Major',
      severity: 'CRITICAL',
    });

    const campaignFrozen = await getCampaign(campaign.id);
    expect(campaignFrozen.posture).toBe('FROZEN');

    await resolveHold(campaign.id, h2.id);

    const h2State = await getHold(campaign.id, h2.id);
    expect(h2State.id).toBe(h2.id);
    expect(h2State.status).toBe('RESOLVED');

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const updatedCampaign = unwrap(res.body);
    expect(updatedCampaign.posture).toBe('RESTRICTED');

    const h1State = await getHold(campaign.id, h1.id);
    expect(h1State.status).toBe('ACTIVE');
  });

  test('HOLD_008: Resolve critical hold, campaign returns to OPEN', async () => {

    const { campaign, hold } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    expect(campaign.posture).toBe('FROZEN');

    const res = await postAs(
      `/campaigns/${campaign.id}/holds/${hold.id}/resolve`,
      {}
    );

    expectSuccess(res);
    const resolvedHold = unwrap(res.body);
    expect(resolvedHold.id).toBe(hold.id);
    expect(resolvedHold.status).toBe('RESOLVED');

    const fetchedHold = await getHold(campaign.id, hold.id);
    expect(fetchedHold.status).toBe('RESOLVED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.posture).toBe('OPEN');
  });

  test('HOLD_009: Contributions blocked when FROZEN', async () => {

    const { campaign } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    expect(campaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 1000,
    });

    await expectErrorCode(res, ERROR_CODES.POSTURE_FROZEN);
  });

  test('HOLD_010: Read operations allowed when FROZEN', async () => {

    const { campaign } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    expect(campaign.posture).toBe('FROZEN');

    const res = await getAs(`/campaigns/${campaign.id}`);

    expectSuccess(res);
    const returnedCampaign = unwrap(res.body);
    expect(returnedCampaign.id).toBe(campaign.id);
    expect(returnedCampaign.posture).toBe('FROZEN');
  });
});
