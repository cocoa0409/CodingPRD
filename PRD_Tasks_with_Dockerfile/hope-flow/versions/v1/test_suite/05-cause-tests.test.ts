import {
  postAs,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  getCause,
  createCause,
  closeCause,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_CAUSE,
  FX_THRESHOLD_MET_CAUSE,
  FX_FUNDED_CAUSE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Cause Tests', () => {

  test('CAUSE_001: POST /campaigns/:C/causes creates cause with explicit threshold_percent', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/causes`, {
      name: 'Medical Aid',
      target_amount: 10000,
      priority: 1,
      threshold_percent: 80,
    });

    expectSuccess(res);
    const cause = unwrap(res.body);
    expect(cause.id).toBeDefined();
    expect(cause.name).toBe('Medical Aid');
    expect(cause.target_amount).toBe(10000);
    expect(cause.priority).toBe(1);
    expect(cause.threshold_percent).toBe(80);
    expect(cause.status).toBe('OPEN');
    expect(cause.allocated_amount).toBe(0);
    expect(cause.disbursed_amount).toBe(0);
  });

  test('CAUSE_002: POST /campaigns/:C/causes creates cause with default threshold_percent=100', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/causes`, {
      name: 'Education',
      target_amount: 5000,
      priority: 1,
    });

    expectSuccess(res);
    const cause = unwrap(res.body);
    expect(cause.id).toBeDefined();
    expect(cause.name).toBe('Education');
    expect(cause.target_amount).toBe(5000);
    expect(cause.priority).toBe(1);
    expect(cause.threshold_percent).toBe(100);
    expect(cause.status).toBe('OPEN');
    expect(cause.allocated_amount).toBe(0);
    expect(cause.disbursed_amount).toBe(0);
  });

  test('CAUSE_003: POST /campaigns/:C/causes with duplicate priority returns ERR_PRIORITY_CONFLICT', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause1 = await createCause(campaign.id, {
      name: 'First',
      target_amount: 1000,
      priority: 1,
    });
    expect(cause1.priority).toBe(1);

    const res = await postAs(`/campaigns/${campaign.id}/causes`, {
      name: 'Second',
      target_amount: 1000,
      priority: 1,
    });

    await expectErrorCode(res, ERROR_CODES.PRIORITY_CONFLICT);
  });

  test('CAUSE_004: POST /campaigns/:C/causes with different priority succeeds', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const cause1 = await createCause(campaign.id, {
      name: 'First',
      target_amount: 1000,
      priority: 1,
    });
    expect(cause1.priority).toBe(1);

    const res = await postAs(`/campaigns/${campaign.id}/causes`, {
      name: 'Second',
      target_amount: 1000,
      priority: 2,
    });

    expectSuccess(res);
    const cause2 = unwrap(res.body);
    expect(cause2.id).toBeDefined();
    expect(cause2.name).toBe('Second');
    expect(cause2.target_amount).toBe(1000);
    expect(cause2.priority).toBe(2);
    expect(cause2.threshold_percent).toBe(100);
    expect(cause2.status).toBe('OPEN');
    expect(cause2.allocated_amount).toBe(0);
    expect(cause2.disbursed_amount).toBe(0);
  });

  test('CAUSE_005: POST /campaigns/:C/causes/:CA/close closes the cause', async () => {
    const { campaign, cause } = await FX_CAMPAIGN_WITH_CAUSE();

    expect(cause.status).toBe('OPEN');

    const res = await postAs(`/campaigns/${campaign.id}/causes/${cause.id}/close`, {});

    expectSuccess(res);

    const closedCause = await getCause(campaign.id, cause.id);
    expect(closedCause.status).toBe('CLOSED');
  });

  test('CAUSE_006: POST /campaigns/:C/causes/:CA/close on already closed cause keeps it CLOSED', async () => {
    const { campaign, cause } = await FX_CAMPAIGN_WITH_CAUSE();

    await closeCause(campaign.id, cause.id);

    const closedCause = await getCause(campaign.id, cause.id);
    expect(closedCause.status).toBe('CLOSED');

    const res = await postAs(`/campaigns/${campaign.id}/causes/${cause.id}/close`, {});

    const isSuccess = res.status >= 200 && res.status < 300;
    if (!isSuccess) {

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(500);
      const errorCode = extractErrorCode(res.body);
      expect(errorCode).toBe(ERROR_CODES.INVALID_STATE);
    }

    const stillClosed = await getCause(campaign.id, cause.id);
    expect(stillClosed.status).toBe('CLOSED');
  });

  test('CAUSE_007: GET /campaigns/:C/causes/:CA returns THRESHOLD_MET status when threshold reached', async () => {
    const { campaign, cause } = await FX_THRESHOLD_MET_CAUSE();

    const res = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);

    expectSuccess(res);
    const retrievedCause = unwrap(res.body);
    expect(retrievedCause.status).toBe('THRESHOLD_MET');
    expect(retrievedCause.allocated_amount).toBe(800);
    expect(retrievedCause.target_amount).toBe(1000);
    expect(retrievedCause.threshold_percent).toBe(80);
    expect(retrievedCause.disbursed_amount).toBe(0);
  });

  test('CAUSE_008: GET /campaigns/:C/causes/:CA returns FUNDED status when fully funded', async () => {
    const { campaign, cause } = await FX_FUNDED_CAUSE();

    const res = await getAs(`/campaigns/${campaign.id}/causes/${cause.id}`);

    expectSuccess(res);
    const retrievedCause = unwrap(res.body);
    expect(retrievedCause.status).toBe('FUNDED');
    expect(retrievedCause.allocated_amount).toBe(1000);
    expect(retrievedCause.target_amount).toBe(1000);
    expect(retrievedCause.threshold_percent).toBe(80);
    expect(retrievedCause.disbursed_amount).toBe(0);
  });
});
