import {
  postAs,
  postAsNoIdem,
  getAs,
  idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode
} from '../../../test-helpers/assertions';
import {
  createStudio,
  getStudio,
  advanceCycle,
  createAsset,
  createClearance,
  grantClearance,
  activateAsset,
  createMix,
  setMixEntries,
  submitMix,
  approveMix,
  publishMix,
  freezeMix,
  createDispute,
  createActiveAssetWithClearance,
  uniqueId,
  unwrap,
  Mix,
  Studio
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

describe('Studio & Cycle Tests', () => {

  test('STUDIO_001: POST /studios creates studio with posture OPEN, cycle_index 1, correct token fields', async () => {

    const idemKey = idempotencyKey('studio001');
    const res = await postAs('/studios', {
      name: uniqueId('studio'),
      token_budget: 20
    }, 'curator', idemKey);

    expectSuccess(res);
    const studio = unwrap(res.body) as Studio;

    expect(studio.posture).toBe('OPEN');
    expect(studio.cycle_index).toBe(1);
    expect(studio.token_reserved).toBe(0);
    expect(studio.token_committed).toBe(0);
    expect(studio.token_available).toBe(20);
    expect(studio.token_budget).toBe(20);
  });

  test('STUDIO_002: POST /studios with token_budget 0 fails ERR_BAD_REQUEST', async () => {

    const idemKey = idempotencyKey('studio002');
    const res = await postAs('/studios', {
      name: uniqueId('studio'),
      token_budget: 0
    }, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.BAD_REQUEST);
  });

  test('STUDIO_003: POST /studios/:id/advance-cycle increments cycle_index and resets idempotency scope', async () => {

    const studio = await createStudio({ token_budget: 20 });
    expect(studio.cycle_index).toBe(1);

    const idemKey = idempotencyKey('studio003');
    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idemKey
    );

    expectSuccess(res);
    const updated = unwrap(res.body) as Studio;

    expect(updated.cycle_index).toBe(2);
    expect(updated.token_reserved).toBe(0);
    expect(updated.token_committed).toBe(0);
  });

  test('STUDIO_004: advance-cycle resets SUBMITTED mix to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const submittedMix = await submitMix(studio.id, mix.id);
    expect(submittedMix.status).toBe('SUBMITTED');

    const studioBeforeAdvance = await getStudio(studio.id);
    expect(studioBeforeAdvance.token_reserved).toBeGreaterThan(0);

    const idemKey = idempotencyKey('studio004');
    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idemKey
    );

    expectSuccess(res);
    const updatedStudio = unwrap(res.body) as Studio;

    expect(updatedStudio.cycle_index).toBe(2);
    expect(updatedStudio.token_reserved).toBe(0);

    const reSubmitRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('studio004-resubmit')
    );
    expectSuccess(reSubmitRes);

    const studioAfterResubmit = await getStudio(studio.id);
    expect(studioAfterResubmit.token_reserved).toBeGreaterThan(0);
  });

  test('STUDIO_005: advance-cycle resets APPROVED mix to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);
    expect(approvedMix.status).toBe('APPROVED');

    const studioBeforeAdvance = await getStudio(studio.id);
    expect(studioBeforeAdvance.token_reserved).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idempotencyKey('studio005')
    );

    expectSuccess(res);
    const updatedStudio = unwrap(res.body) as Studio;

    expect(updatedStudio.token_reserved).toBe(0);

    const reSubmitRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('studio005-resubmit')
    );
    expectSuccess(reSubmitRes);

    const studioAfterResubmit = await getStudio(studio.id);
    expect(studioAfterResubmit.token_reserved).toBeGreaterThan(0);
  });

  test('STUDIO_006: advance-cycle archives PUBLISHED mix and releases committed tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const studioBeforeAdvance = await getStudio(studio.id);
    expect(studioBeforeAdvance.token_committed).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idempotencyKey('studio006')
    );

    expectSuccess(res);
    const updatedStudio = unwrap(res.body) as Studio;

    expect(updatedStudio.token_committed).toBe(0);

    const archiveRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'manager',
      idempotencyKey('verify-archived-006')
    );
    expectErrorCode(archiveRes, CONSTANTS.errors.INVALID_STATE);
  });

  test('STUDIO_007: advance-cycle archives FROZEN mix and releases committed tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);
    const frozenMix = await freezeMix(studio.id, mix.id);
    expect(frozenMix.status).toBe('FROZEN');

    const studioBeforeAdvance = await getStudio(studio.id);
    expect(studioBeforeAdvance.token_committed).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idempotencyKey('studio007')
    );

    expectSuccess(res);
    const updatedStudio = unwrap(res.body) as Studio;

    expect(updatedStudio.token_committed).toBe(0);

    const archiveRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'manager',
      idempotencyKey('verify-archived-007')
    );
    expectErrorCode(archiveRes, CONSTANTS.errors.INVALID_STATE);
  });

  test('STUDIO_008: studio posture is OPEN with only 1 OPEN dispute', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await getAs(`/studios/${studio.id}`, 'curator');

    expectSuccess(res);
    const studioState = unwrap(res.body) as Studio;

    expect(studioState.posture).toBe('OPEN');
  });

  test('STUDIO_009: studio posture is REVIEW with 2+ OPEN disputes', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset1 = await createAsset(studio.id, { duration_sec: 120 });
    const asset2 = await createAsset(studio.id, { duration_sec: 120 });

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset1.id,
      severity: 'LOW'
    });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset2.id,
      severity: 'LOW'
    });

    const res = await getAs(`/studios/${studio.id}`, 'curator');

    expectSuccess(res);
    const studioState = unwrap(res.body) as Studio;

    expect(studioState.posture).toBe('REVIEW');
  });

  test('STUDIO_010: studio posture is HALT with ESCALATED dispute', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    });

    const res = await getAs(`/studios/${studio.id}`, 'curator');

    expectSuccess(res);
    const studioState = unwrap(res.body) as Studio;

    expect(studioState.posture).toBe('HALT');
  });

  test('STUDIO_011: token_available equals token_budget - token_reserved - token_committed', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const { asset: asset1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset3 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const publishedMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, publishedMix.id, [
      { asset_id: asset1.id, slot: 'NORMAL' },
      { asset_id: asset2.id, slot: 'NORMAL' },
      { asset_id: asset3.id, slot: 'NORMAL' },

    ], publishedMix.version);

    const studioFresh = await createStudio({ token_budget: 10 });
    const { asset: assetA } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetC } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetD } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetE } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetF } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');
    const { asset: assetG } = await createActiveAssetWithClearance(studioFresh.id, 120, 'FULL');

    const mix1 = await createMix(studioFresh.id, { kind: 'PUBLIC' });
    await setMixEntries(studioFresh.id, mix1.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' },
      { asset_id: assetC.id, slot: 'NORMAL' },
      { asset_id: assetD.id, slot: 'NORMAL' }
    ], mix1.version);
    await submitMix(studioFresh.id, mix1.id);
    await approveMix(studioFresh.id, mix1.id);
    await publishMix(studioFresh.id, mix1.id);

    const mix2 = await createMix(studioFresh.id, { kind: 'PUBLIC' });
    await setMixEntries(studioFresh.id, mix2.id, [
      { asset_id: assetE.id, slot: 'NORMAL' },
      { asset_id: assetF.id, slot: 'NORMAL' },
      { asset_id: assetG.id, slot: 'NORMAL' }
    ], mix2.version);
    await submitMix(studioFresh.id, mix2.id);

    const res = await getAs(`/studios/${studioFresh.id}`, 'manager');

    expectSuccess(res);
    const studioState = unwrap(res.body) as Studio;

    expect(studioState.token_budget).toBe(10);
    expect(studioState.token_reserved).toBe(3);
    expect(studioState.token_committed).toBe(4);
    expect(studioState.token_available).toBe(3);
  });

  test('STUDIO_012: idempotency replay returns exact stored response', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('dup1');

    const res1 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'X',
      kind: 'PUBLIC'
    }, 'curator', idemKey);
    expectSuccess(res1);
    const originalMix = unwrap(res1.body) as Mix;

    const res2 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'X',
      kind: 'PUBLIC'
    }, 'curator', idemKey);

    expectSuccess(res2);
    const replayedMix = unwrap(res2.body) as Mix;

    expect(replayedMix.id).toBe(originalMix.id);
    expect(replayedMix.version).toBe(originalMix.version);
    expect(replayedMix.title).toBe(originalMix.title);
    expect(replayedMix.kind).toBe(originalMix.kind);
  });

  test('STUDIO_013: idempotency replay with different body fails ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('dup2');

    const res1 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'A',
      kind: 'PUBLIC'
    }, 'curator', idemKey);
    expectSuccess(res1);

    const res2 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'B',
      kind: 'PUBLIC'
    }, 'curator', idemKey);

    expectErrorCode(res2, CONSTANTS.errors.IDEMPOTENCY_REPLAY_MISMATCH);
  });

  test('STUDIO_014: idempotency key reuse is allowed in new cycle', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('kx');

    const res1 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'Old',
      kind: 'PUBLIC'
    }, 'curator', idemKey);
    expectSuccess(res1);
    const oldMix = unwrap(res1.body) as Mix;

    await advanceCycle(studio.id);

    const res2 = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'New',
      kind: 'PUBLIC'
    }, 'curator', idemKey);

    expectSuccess(res2);
    const newMix = unwrap(res2.body) as Mix;

    expect(newMix.id).not.toBe(oldMix.id);
    expect(newMix.title).toBe('New');
  });

  test('STUDIO_015: POST without Idempotency-Key fails ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const res = await postAsNoIdem(`/studios/${studio.id}/advance-cycle`, {}, 'manager');

    expectErrorCode(res, CONSTANTS.errors.MISSING_IDEMPOTENCY_KEY);
  });

});
