import {
  postAs,
  postAsNoIdem,
  patchAs,
  patchAsNoIfMatch,
  idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode
} from '../../../test-helpers/assertions';
import {
  createStudio,
  getStudio,
  createAsset,
  patchAsset,
  activateAsset,
  createClearance,
  grantClearance,
  createDispute,
  resolveDispute,
  createMix,
  uniqueId,
  unwrap,
  Asset,
  Mix
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

describe('Asset Tests', () => {

  test('ASSET_001: POST /studios/S/assets creates asset with status DRAFT', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('a1');
    const res = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 120
    }, 'curator', idemKey);

    expectSuccess(res);
    const asset = unwrap(res.body) as Asset;

    expect(asset.status).toBe('DRAFT');
    expect(asset.duration_sec).toBe(120);
    expect(asset.version).toBe(1);
  });

  test('ASSET_002: POST /studios/S/assets with duration_sec 0 fails ERR_BAD_REQUEST', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('a2');
    const res = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 0
    }, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.BAD_REQUEST);
  });

  test('ASSET_003: PATCH /studios/S/assets/A with curator on DRAFT updates title', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    expect(asset.status).toBe('DRAFT');
    expect(asset.version).toBe(1);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { title: 't2' },
      1,
      'curator'
    );

    expectSuccess(res);
    const updated = unwrap(res.body) as Asset;

    expect(updated.status).toBe('DRAFT');
    expect(updated.title).toBe('t2');
    expect(updated.version).toBe(2);
  });

  test('ASSET_004: PATCH /studios/S/assets/A without If-Match fails ERR_MISSING_IF_MATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    await patchAsset(studio.id, asset.id, { title: 'v2' }, asset.version);

    const res = await patchAsNoIfMatch(
      `/studios/${studio.id}/assets/${asset.id}`,
      { title: 'x' },
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.MISSING_IF_MATCH);
  });

  test('ASSET_005: PATCH /studios/S/assets/A with wrong If-Match fails ERR_VERSION_CONFLICT', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    await patchAsset(studio.id, asset.id, { title: 'v2' }, asset.version);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { title: 'x' },
      1,
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.VERSION_CONFLICT);
  });

  test('ASSET_006: PATCH /studios/S/assets/A with curator on ACTIVE fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    const activeAsset = await activateAsset(studio.id, asset.id);
    expect(activeAsset.status).toBe('ACTIVE');

    const res = await patchAs(
      `/studios/${studio.id}/assets/${activeAsset.id}`,
      { title: 'nope' },
      activeAsset.version,
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('ASSET_007: PATCH /studios/S/assets/A with legal editing title on ACTIVE fails ERR_BAD_REQUEST', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    const activeAsset = await activateAsset(studio.id, asset.id);
    expect(activeAsset.status).toBe('ACTIVE');

    const res = await patchAs(
      `/studios/${studio.id}/assets/${activeAsset.id}`,
      { title: 'nope' },
      activeAsset.version,
      'legal'
    );

    expectErrorCode(res, CONSTANTS.errors.BAD_REQUEST);
  });

  test('ASSET_008: PATCH /studios/S/assets/A with legal duration correction quarantines asset', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    const activeAsset = await activateAsset(studio.id, asset.id);
    expect(activeAsset.status).toBe('ACTIVE');

    const res = await patchAs(
      `/studios/${studio.id}/assets/${activeAsset.id}`,
      { duration_sec: 240 },
      activeAsset.version,
      'legal'
    );

    expectSuccess(res);
    const updated = unwrap(res.body) as Asset;

    expect(updated.status).toBe('QUARANTINED');
    expect(updated.duration_sec).toBe(240);
    expect(updated.version).toBeGreaterThan(activeAsset.version);
  });

  test('ASSET_009: PATCH /studios/S/assets/A with legal on QUARANTINED updates duration', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    await activateAsset(studio.id, asset.id);

    const quarantinedAsset = await patchAsset(
      studio.id,
      asset.id,
      { duration_sec: 200 },
      2,
      'legal'
    );
    expect(quarantinedAsset.status).toBe('QUARANTINED');

    const res = await patchAs(
      `/studios/${studio.id}/assets/${quarantinedAsset.id}`,
      { duration_sec: 241 },
      quarantinedAsset.version,
      'legal'
    );

    expectSuccess(res);
    const updated = unwrap(res.body) as Asset;

    expect(updated.status).toBe('QUARANTINED');
    expect(updated.duration_sec).toBe(241);
    expect(updated.version).toBeGreaterThan(quarantinedAsset.version);
  });

  test('ASSET_010: POST /studios/S/assets/A/activate with PENDING clearance fails ERR_CLEARANCE_REQUIRED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });

    const res = await postAs(
      `/studios/${studio.id}/assets/${asset.id}/activate`,
      {},
      'curator',
      idempotencyKey('a10')
    );

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_REQUIRED);
  });

  test('ASSET_011: POST /studios/S/assets/A/activate with GRANTED clearance succeeds', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);

    const res = await postAs(
      `/studios/${studio.id}/assets/${asset.id}/activate`,
      {},
      'curator',
      idempotencyKey('a11')
    );

    expectSuccess(res);
    const activated = unwrap(res.body) as Asset;

    expect(activated.status).toBe('ACTIVE');
    expect(activated.version).toBeGreaterThan(asset.version);
  });

  test('ASSET_012: POST /studios/S/assets/A/activate with posture HALT fails ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);

    const otherAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: otherAsset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/assets/${asset.id}/activate`,
      {},
      'curator',
      idempotencyKey('a12')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('ASSET_013: POST /studios/S/assets/A/activate with dispute on asset fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await postAs(
      `/studios/${studio.id}/assets/${asset.id}/activate`,
      {},
      'curator',
      idempotencyKey('a13')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('ASSET_014: POST /studios/S/assets/A/activate on QUARANTINED asset fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    await activateAsset(studio.id, asset.id);

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await postAs(
      `/studios/${studio.id}/assets/${asset.id}/activate`,
      {},
      'curator',
      idempotencyKey('a14')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('ASSET_015: PATCH /studios/S/assets/A on RETIRED asset fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, {
      asset_id: asset.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearance.id);
    const activeAsset = await activateAsset(studio.id, asset.id);

    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    await resolveDispute(studio.id, dispute.id, 'UPHELD');

    const res = await patchAsNoIfMatch(
      `/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 200 },
      'legal'
    );
    expectErrorCode(res, CONSTANTS.errors.MISSING_IF_MATCH);
  });

  test('ASSET_016: POST /studios/S/assets idempotency replay returns original asset', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('same1');

    const res1 = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 120
    }, 'curator', idemKey);
    expectSuccess(res1);
    const originalAsset = unwrap(res1.body) as Asset;

    const res2 = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 120
    }, 'curator', idemKey);

    expectSuccess(res2);
    const replayedAsset = unwrap(res2.body) as Asset;

    expect(replayedAsset.id).toBe(originalAsset.id);
    expect(replayedAsset.version).toBe(originalAsset.version);
  });

  test('ASSET_017: POST /studios/S/assets idempotency replay with different body fails', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('same2');

    const res1 = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 120
    }, 'curator', idemKey);
    expectSuccess(res1);

    const res2 = await postAs(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 121
    }, 'curator', idemKey);

    expectErrorCode(res2, CONSTANTS.errors.IDEMPOTENCY_REPLAY_MISMATCH);
  });

  test('ASSET_018: POST /studios/S/mixes creates mix with token_cost 0 until entries are set', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const res = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'm',
      kind: 'PUBLIC'
    }, 'curator', idempotencyKey('a18'));

    expectSuccess(res);
    const mix = unwrap(res.body) as Mix;

    expect(mix.status).toBe('DRAFT');
    expect(mix.token_cost).toBe(0);
  });

  test('ASSET_019: POST /studios/S/assets without Idempotency-Key fails ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const res = await postAsNoIdem(`/studios/${studio.id}/assets`, {
      title: 't',
      duration_sec: 120
    }, 'curator');

    expectErrorCode(res, CONSTANTS.errors.MISSING_IDEMPOTENCY_KEY);
  });

  test('ASSET_020: PATCH /studios/S/assets/A with legal on DRAFT fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    expect(asset.status).toBe('DRAFT');

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 200 },
      asset.version,
      'legal'
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

});
