import { postAs, getAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createPledge,
  getPledge,
  createContribution,
  getContribution,
  refundContribution,
  allocateContribution,
  createGrant,
  createCause,
  getCause,
  createHold,
  resolveHold,
  closeCampaign,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_PLEDGE,
  FX_CAMPAIGN_WITH_CRITICAL_HOLD,
  FX_PLEDGE_FULFILLED,
  FX_THRESHOLD_MET_CAUSE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 13: Error Precedence Tests', () => {

  test('ERR_001: GET nonexistent campaign/pledge returns ERR_NOT_FOUND for campaign level', async () => {

    const fakeCampaignId = uniqueId('campaign');
    const fakePledgeId = uniqueId('pledge');

    const res = await getAs(`/campaigns/${fakeCampaignId}/pledges/${fakePledgeId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_002: GET nonexistent pledge on existing campaign returns ERR_NOT_FOUND for pledge', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const fakePledgeId = uniqueId('pledge');

    const res = await getAs(`/campaigns/${campaign.id}/pledges/${fakePledgeId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_003: Creating pledge on closed campaign returns ERR_CAMPAIGN_CLOSED (before posture checks)', async () => {

    const { campaign } = await FX_CAMPAIGN();
    await closeCampaign(campaign.id);

    const res = await postAs(`/campaigns/${campaign.id}/pledges`, {
      donor_name: 'Test',
      donor_email: 't@t.com',
      amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.CAMPAIGN_CLOSED);
  });

  test('ERR_004: Creating contribution on closed+frozen campaign returns ERR_CAMPAIGN_CLOSED (precedes ERR_POSTURE_FROZEN)', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const hold1 = await createHold(campaign.id, {
      reason: 'Issue',
      severity: 'CRITICAL',
    });
    await resolveHold(campaign.id, hold1.id);

    await closeCampaign(campaign.id);

    await createHold(campaign.id, {
      reason: 'New',
      severity: 'CRITICAL',
    });

    const verifiedCampaign = await getCampaign(campaign.id);
    expect(verifiedCampaign.phase).toBe('CLOSED');
    expect(verifiedCampaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Test',
      donor_email: 't@t.com',
      gross_amount: 100,
    });

    await expectErrorCode(res, ERROR_CODES.CAMPAIGN_CLOSED);
  });

  test('ERR_005: Creating contribution with missing gross_amount on frozen campaign returns ERR_INVALID_REQUEST (first in precedence)', async () => {

    const { campaign } = await FX_CAMPAIGN_WITH_CRITICAL_HOLD();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Test',

    });

    await expectErrorCode(res, ERROR_CODES.INVALID_REQUEST);
  });

  test('ERR_006: Voiding pledge on frozen campaign returns ERR_POSTURE_FROZEN', async () => {

    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    await createHold(campaign.id, {
      reason: 'Issue',
      severity: 'CRITICAL',
    });

    const verifiedCampaign = await getCampaign(campaign.id);
    expect(verifiedCampaign.posture).toBe('FROZEN');

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/void`, {});

    await expectErrorCode(res, ERROR_CODES.POSTURE_FROZEN);
  });

  test('ERR_007: Voiding fulfilled pledge with STANDARD hold returns ERR_INVALID_STATE (RESTRICTED allows pledge ops)', async () => {

    const { campaign, pledge } = await FX_PLEDGE_FULFILLED();

    await createHold(campaign.id, {
      reason: 'Issue',
      severity: 'STANDARD',
    });

    const verifiedCampaign = await getCampaign(campaign.id);
    expect(verifiedCampaign.posture).toBe('RESTRICTED');

    const verifiedPledge = await getPledge(campaign.id, pledge.id);
    expect(verifiedPledge.status).toBe('FULFILLED');

    const res = await postAs(`/campaigns/${campaign.id}/pledges/${pledge.id}/void`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('ERR_008: Allocating to nonexistent cause returns ERR_NOT_FOUND', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
    });

    const fakeCauseId = uniqueId('cause');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: fakeCauseId,
      amount: 50,
    });

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_009: Allocating from REFUNDED contribution returns ERR_INVALID_STATE', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 100,
      priority: 1,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 50,
    });

    await refundContribution(campaign.id, contribution.id);

    const refundedContribution = await getContribution(campaign.id, contribution.id);
    expect(refundedContribution.status).toBe('REFUNDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 25,
    });

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);
  });

  test('ERR_010: Allocating to FUNDED cause returns ERR_CAUSE_FULL', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 100,
      priority: 1,
      threshold_percent: 100,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 200,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 100,
    });

    const fundedCause = await getCause(campaign.id, cause.id);
    expect(fundedCause.status).toBe('FUNDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 50,
    });

    await expectErrorCode(res, ERROR_CODES.CAUSE_FULL);
  });

  test('ERR_011: Allocating more than contribution balance returns ERR_ALLOCATION_EXCEEDED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 100,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
    });

    const verifiedContribution = await getContribution(campaign.id, contribution.id);
    expect(verifiedContribution.net_amount).toBe(97);

    const res = await postAs(`/campaigns/${campaign.id}/contributions/${contribution.id}/allocate`, {
      cause_id: cause.id,
      amount: 98,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('ERR_012: Contribution with pledge amount mismatch returns ERR_PLEDGE_MISMATCH', async () => {

    const { campaign, pledge } = await FX_CAMPAIGN_WITH_PLEDGE();

    expect(pledge.amount).toBe(1000);

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Wrong',
      donor_email: 'w@t.com',
      gross_amount: 500,
      fulfills_pledge_id: pledge.id,
    });

    await expectErrorCode(res, ERROR_CODES.PLEDGE_MISMATCH);
  });

  test('ERR_013: Disbursing more than allocated returns ERR_ALLOCATION_EXCEEDED', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 500,
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
      amount: 250,
    });

    const thresholdMetCause = await getCause(campaign.id, cause.id);
    expect(thresholdMetCause.status).toBe('THRESHOLD_MET');
    expect(thresholdMetCause.allocated_amount).toBe(250);

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 300,
    });

    await expectErrorCode(res, ERROR_CODES.ALLOCATION_EXCEEDED);
  });

  test('ERR_014: Disbursing more than available_balance returns ERR_INSUFFICIENT_FUNDS', async () => {

    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    const verifiedCampaign = await getCampaign(campaign.id);
    expect(verifiedCampaign.available_balance).toBe(873);

    const verifiedCause = await getCause(campaign.id, cause.id);
    expect(verifiedCause.allocated_amount).toBe(800);

    const res = await postAs(`/campaigns/${campaign.id}/disbursements`, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 900,
    });

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_FUNDS);
  });

});
