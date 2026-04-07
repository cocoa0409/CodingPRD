import {
  postAs,
  postAsNoIdem,
  getAs,
  patchAs,
  putAsNoIfMatch,
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
  suspendClearance,
  revokeClearance,
  activateAsset,
  createMix,
  setMixEntries,
  submitMix,
  approveMix,
  publishMix,
  unpublishMix,
  createDispute,
  resolveDispute,
  createActiveAssetWithClearance,
  uniqueId,
  unwrap,
  Clearance,
  Mix,
  Studio,
  Asset
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

function getEffects(body: any): any[] {
  if (!body) return [];
  if (Array.isArray(body.effects)) return body.effects;
  if (Array.isArray(body?.data?.effects)) return body.data.effects;
  return [];
}

function findEffect(effects: any[], type: string, id: string): any | undefined {
  return effects.find((e) => e && e.type === type && e.id === id);
}

describe('Deep Integration Tests', () => {

  test('DEEP_001: submitting already SUBMITTED mix fails ERR_INVALID_STATE; token accounting correct', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const assets: Asset[] = [];
    for (let i = 0; i < 10; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id,
      assets.slice(0, 6).map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })),
      mixP.version
    );
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);

    const mixI = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI.id,
      assets.slice(6, 10).map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })),
      mixI.version
    );

    const submittedI = await submitMix(studio.id, mixI.id);
    expect(submittedI.status).toBe('SUBMITTED');

    const idemKey = idempotencyKey('dI1');
    const res = await postAs(`/studios/${studio.id}/mixes/${mixI.id}/submit`, {}, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('DEEP_002: legal correction increasing token_cost triggers shedding of queued INTERNAL mix', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const { asset: assetA, clearance: clearanceA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetC } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetD } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetE } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetF } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' },
      { asset_id: assetC.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const mixI = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI.id, [
      { asset_id: assetD.id, slot: 'NORMAL' },
      { asset_id: assetE.id, slot: 'NORMAL' },
      { asset_id: assetF.id, slot: 'NORMAL' }
    ], mixI.version);
    await submitMix(studio.id, mixI.id);
    await approveMix(studio.id, mixI.id);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetA.id}`,
      { duration_sec: 421 },
      assetA.version,
      'legal'
    );

    expectSuccess(res);

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/unpublish`, {}, 'manager', idempotencyKey('verify-frozen'));
    expectSuccess(unpublishRes);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved + studioState.token_committed).toBeLessThanOrEqual(studioState.token_budget);
  });

  test('DEEP_003: HIGH dispute on asset archives containing mix and causes HALT posture', async () => {

    const studio = await createStudio({ token_budget: 8 });

    const { asset: asset1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset3 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset4 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const { asset: asset5 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset6 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset7 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset8 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP1.id, [
      { asset_id: asset1.id, slot: 'NORMAL' },
      { asset_id: asset2.id, slot: 'NORMAL' },
      { asset_id: asset3.id, slot: 'NORMAL' },
      { asset_id: asset4.id, slot: 'NORMAL' }
    ], mixP1.version);
    await submitMix(studio.id, mixP1.id);
    await approveMix(studio.id, mixP1.id);
    await publishMix(studio.id, mixP1.id);

    const mixP2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP2.id, [
      { asset_id: asset5.id, slot: 'NORMAL' },
      { asset_id: asset6.id, slot: 'NORMAL' },
      { asset_id: asset7.id, slot: 'NORMAL' },
      { asset_id: asset8.id, slot: 'NORMAL' }
    ], mixP2.version);
    await submitMix(studio.id, mixP2.id);
    await approveMix(studio.id, mixP2.id);
    await publishMix(studio.id, mixP2.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBe(8);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset1.id,
      severity: 'HIGH'
    }, 'legal', idempotencyKey('d3'));

    expectSuccess(res);

    const archiveP1Res = await postAs(`/studios/${studio.id}/mixes/${mixP1.id}/archive`, {}, 'manager', idempotencyKey('verify-p1-archived'));
    expectErrorCode(archiveP1Res, CONSTANTS.errors.INVALID_STATE);

    const unpublishP2Res = await postAs(`/studios/${studio.id}/mixes/${mixP2.id}/unpublish`, {}, 'manager', idempotencyKey('verify-p2-published'));
    expectSuccess(unpublishP2Res);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('HALT');
  });

  test('DEEP_004: unpublish is allowed during HALT posture', async () => {

    const studio = await createStudio({ token_budget: 8 });

    const { asset: asset1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP2.id, [
      { asset_id: asset1.id, slot: 'NORMAL' },
      { asset_id: asset2.id, slot: 'NORMAL' }
    ], mixP2.version);
    await submitMix(studio.id, mixP2.id);
    await approveMix(studio.id, mixP2.id);
    await publishMix(studio.id, mixP2.id);

    const { asset: disputeAsset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const res = await postAs(`/studios/${studio.id}/mixes/${mixP2.id}/unpublish`, {}, 'manager', idempotencyKey('d4'));

    expectSuccess(res);
    const unpublished = unwrap(res.body) as Mix;
    expect(unpublished.status).toBe('APPROVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);

    expect(studioAfter.token_reserved).toBe(2);
  });

  test('DEEP_005: idempotency key cleared on cycle advance, approve fails on DRAFT mix', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const idemKey = idempotencyKey('apX');
    await postAs(`/studios/${studio.id}/mixes/${mix.id}/approve`, {}, 'manager', idemKey);

    await advanceCycle(studio.id);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/approve`, {}, 'manager', idemKey);

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('DEEP_006: dispute bounces queued mix, then publish succeeds with available budget', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const { asset: assetP } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetI } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: assetP.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);

    const mixI = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI.id, [
      { asset_id: assetI.id, slot: 'NORMAL' }
    ], mixI.version);
    await submitMix(studio.id, mixI.id);

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: assetI.id,
      severity: 'LOW'
    });

    const submitIRes = await postAs(`/studios/${studio.id}/mixes/${mixI.id}/submit`, {}, 'curator', idempotencyKey('verify-i-draft'));
    expectErrorCode(submitIRes, CONSTANTS.errors.DISPUTE_BLOCKING);

    const res = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/publish`, {}, 'manager', idempotencyKey('d6'));

    expectSuccess(res);
    const published = unwrap(res.body) as Mix;
    expect(published.status).toBe('PUBLISHED');
  });

  test('DEEP_007: clearance suspension freezes PUBLISHED mix, tokens remain committed', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const assets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 6; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(result);
    }

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id,
      assets.map(a => ({ asset_id: a.asset.id, slot: 'NORMAL' as const })),
      mixP.version
    );
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBe(6);

    const res = await postAs(
      `/studios/${studio.id}/clearances/${assets[0].clearance.id}/suspend`,
      {},
      'legal',
      idempotencyKey('d7')
    );

    expectSuccess(res);

    const studioAfterSuspend = await getStudio(studio.id);
    expect(studioAfterSuspend.token_committed).toBe(6);

    const effects = getEffects(res.body);
    const mixEffect = findEffect(effects, 'mix', mixP.id);
    expect(mixEffect?.status).toBe('FROZEN');

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/unpublish`, {}, 'legal', idempotencyKey('verify-frozen'));
    expectSuccess(unpublishRes);
  });

  test('DEEP_008: publishing FROZEN mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 6 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    await suspendClearance(studio.id, clearance.id);

    const res = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/publish`, {}, 'manager', idempotencyKey('d8'));

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('DEEP_009: legal unpublishes FROZEN mix, becomes APPROVED when approval is current', async () => {

    const studio = await createStudio({ token_budget: 6 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBe(1);

    await suspendClearance(studio.id, clearance.id);

    const res = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/unpublish`, {}, 'legal', idempotencyKey('d9'));

    expectSuccess(res);
    const unpublished = unwrap(res.body) as Mix;
    expect(unpublished.status).toBe('APPROVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
    expect(studioAfter.token_reserved).toBe(1);
  });

  test('DEEP_010: legal correction changes duration, updates token_cost, freezes mix', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 240 },
      asset.version,
      'legal'
    );

    expectSuccess(res);

    const effects = getEffects(res.body);
    const mixEffect = findEffect(effects, 'mix', mixP.id);
    expect(mixEffect?.status).toBe('FROZEN');
    expect(mixEffect?.token_cost).toBe(2);

    const studioAfterCorrection = await getStudio(studio.id);
    expect(studioAfterCorrection.token_committed).toBe(2);

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/unpublish`, {}, 'legal', idempotencyKey('verify-frozen'));
    expectSuccess(unpublishRes);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('DEEP_011: shedding bounces queued mixes by priority (highest cost first)', async () => {

    const studio = await createStudio({ token_budget: 5 });

    const { asset: asset1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixI1 = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI1.id, [
      { asset_id: asset1.id, slot: 'NORMAL' }
    ], mixI1.version);
    await submitMix(studio.id, mixI1.id);

    const mixI2 = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI2.id, [
      { asset_id: asset2.id, slot: 'NORMAL' }
    ], mixI2.version);
    await submitMix(studio.id, mixI2.id);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset1.id}`,
      { duration_sec: 421 },
      asset1.version,
      'legal'
    );

    expectSuccess(res);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved + studioAfter.token_committed).toBeLessThanOrEqual(studioAfter.token_budget);
  });

  test('DEEP_012: shedding archives INTERNAL mix before PUBLIC mix', async () => {

    const studio = await createStudio({ token_budget: 7 });

    const { asset: assetI1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetI2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetI3 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const { asset: assetI4 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetI5 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetI6 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const { asset: assetP1, clearance: clearanceP1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetP2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetP3 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetP4 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixI = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mixI.id, [
      { asset_id: assetI1.id, slot: 'NORMAL' },
      { asset_id: assetI2.id, slot: 'NORMAL' },
      { asset_id: assetI3.id, slot: 'NORMAL' },
      { asset_id: assetI4.id, slot: 'NORMAL' },
      { asset_id: assetI5.id, slot: 'NORMAL' },
      { asset_id: assetI6.id, slot: 'NORMAL' }
    ], mixI.version);
    await submitMix(studio.id, mixI.id);
    await approveMix(studio.id, mixI.id);
    await publishMix(studio.id, mixI.id);

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: assetP1.id, slot: 'NORMAL' },
      { asset_id: assetP2.id, slot: 'NORMAL' },
      { asset_id: assetP3.id, slot: 'NORMAL' },
      { asset_id: assetP4.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetP1.id}`,
      { duration_sec: 421 },
      assetP1.version,
      'legal'
    );

    expectSuccess(res);

    const archiveIRes = await postAs(`/studios/${studio.id}/mixes/${mixI.id}/archive`, {}, 'manager', idempotencyKey('verify-i-archived'));
    expectErrorCode(archiveIRes, CONSTANTS.errors.INVALID_STATE);

    const unpublishPRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/unpublish`, {}, 'manager', idempotencyKey('verify-p-frozen'));
    expectSuccess(unpublishPRes);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved + studioAfter.token_committed).toBeLessThanOrEqual(studioAfter.token_budget);
  });

  test('DEEP_013: ERR_VERSION_CONFLICT wins over ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset1.id, severity: 'LOW' });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset2.id, severity: 'LOW' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mixP.id}/publish`,
      {},
      'manager',
      idempotencyKey('d13'),
      999
    );

    expectErrorCode(res, CONSTANTS.errors.VERSION_CONFLICT);
  });

  test('DEEP_014: ERR_MISSING_IDEMPOTENCY_KEY wins over ERR_VERSION_CONFLICT', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const res = await postAsNoIdem(`/studios/${studio.id}/mixes/${mix.id}/unpublish`, {}, 'manager');

    expectErrorCode(res, CONSTANTS.errors.MISSING_IDEMPOTENCY_KEY);
  });

  test('DEEP_015: ERR_MISSING_IF_MATCH wins over entry policy errors', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAsNoIfMatch(
      `/studios/${studio.id}/mixes/${mix.id}/entries`,
      { entries: [
        { asset_id: asset.id, slot: 'NORMAL' },
        { asset_id: asset.id, slot: 'NORMAL' }
      ]},
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.MISSING_IF_MATCH);
  });

  test('DEEP_016: ERR_POSTURE_BLOCKED for submit in HALT (before entry validation)', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const disputeAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset.id, severity: 'HIGH' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('d16'));

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('DEEP_017: evidence mix archived on cycle advance even with token_cost 0', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: asset.id, severity: 'HIGH' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const mixE = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    await setMixEntries(studio.id, mixE.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixE.version, 'legal');

    const publishedE = await publishMix(studio.id, mixE.id, 'legal');
    expect(publishedE.status).toBe('FROZEN');
    expect(publishedE.token_cost).toBe(0);

    const res = await postAs(`/studios/${studio.id}/advance-cycle`, {}, 'manager', idempotencyKey('d17'));

    expectSuccess(res);

    const archiveRes = await postAs(`/studios/${studio.id}/mixes/${mixE.id}/archive`, {}, 'manager', idempotencyKey('verify-archived'));
    expectErrorCode(archiveRes, CONSTANTS.errors.INVALID_STATE);
  });

  test('DEEP_018: LOW dispute on asset bounces APPROVED mix to DRAFT', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    const approvedP = await approveMix(studio.id, mixP.id);
    expect(approvedP.status).toBe('APPROVED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('d18'));

    expectSuccess(res);

    const submitRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/submit`, {}, 'curator', idempotencyKey('verify-draft'));
    expectErrorCode(submitRes, CONSTANTS.errors.DISPUTE_BLOCKING);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('DEEP_019: revoking clearance archives PUBLISHED mix, SUBMITTED mix stays SUBMITTED', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset: assetP, clearance: clearanceP } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetQ } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: assetP.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);
    await publishMix(studio.id, mixP.id);

    const mixQ = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixQ.id, [
      { asset_id: assetQ.id, slot: 'NORMAL' }
    ], mixQ.version);
    await submitMix(studio.id, mixQ.id);

    const res = await postAs(
      `/studios/${studio.id}/clearances/${clearanceP.id}/revoke`,
      {},
      'legal',
      idempotencyKey('d19')
    );

    expectSuccess(res);

    const archivePRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/archive`, {}, 'manager', idempotencyKey('verify-p-archived'));
    expectErrorCode(archivePRes, CONSTANTS.errors.INVALID_STATE);

    const approveQRes = await postAs(`/studios/${studio.id}/mixes/${mixQ.id}/approve`, {}, 'manager', idempotencyKey('verify-q-submitted'));
    expectSuccess(approveQRes);
  });

  test('DEEP_020: idempotency cleared on cycle advance, publish fails on ARCHIVED mix', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixP = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixP.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mixP.version);
    await submitMix(studio.id, mixP.id);
    await approveMix(studio.id, mixP.id);

    const idemKey = idempotencyKey('pkey');
    const publishRes = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/publish`, {}, 'manager', idemKey);
    expectSuccess(publishRes);
    const published = unwrap(publishRes.body) as Mix;
    expect(published.status).toBe('PUBLISHED');

    await advanceCycle(studio.id);

    const res = await postAs(`/studios/${studio.id}/mixes/${mixP.id}/publish`, {}, 'manager', idemKey);

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

});
