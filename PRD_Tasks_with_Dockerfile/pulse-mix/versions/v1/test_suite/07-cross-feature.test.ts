import {
  postAs,
  putAs,
  patchAs,
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
  patchAsset,
  activateAsset,
  createClearance,
  grantClearance,
  suspendClearance,
  revokeClearance,
  createMix,
  setMixEntries,
  submitMix,
  approveMix,
  publishMix,
  createDispute,
  resolveDispute,
  createActiveAssetWithClearance,
  uniqueId,
  unwrap,
  Studio,
  Mix,
  Asset,
  Clearance
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

describe('Cross-Feature Interaction Tests', () => {

  test('CROSS_001: submit fails ERR_TOKEN_BUDGET_EXCEEDED when budget full', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const assets: Asset[] = [];
    for (let i = 0; i < 7; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const m1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, m1.id, assets.slice(0, 6).map(a => ({
      asset_id: a.id,
      slot: 'NORMAL' as const
    })), m1.version);
    await submitMix(studio.id, m1.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(6);

    const m2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, m2.id, [
      { asset_id: assets[6].id, slot: 'NORMAL' }
    ], m2.version);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${m2.id}/submit`,
      {},
      'curator',
      idempotencyKey('x1')
    );

    expectErrorCode(res, CONSTANTS.errors.TOKEN_BUDGET_EXCEEDED);
  });

  test('CROSS_002: suspending clearance bounces queued mix, freeing budget for new submit', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const assets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 7; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(result);
    }

    const m1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, m1.id, assets.slice(0, 6).map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), m1.version);
    await submitMix(studio.id, m1.id);

    const m2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, m2.id, [
      { asset_id: assets[6].asset.id, slot: 'NORMAL' }
    ], m2.version);

    await suspendClearance(studio.id, assets[0].clearance.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(0);

    const resubmitM1 = await postAs(
      `/studios/${studio.id}/mixes/${m1.id}/submit`,
      {},
      'curator',
      idempotencyKey('x2-resubmit-m1')
    );
    expectErrorCode(resubmitM1, CONSTANTS.errors.CLEARANCE_SUSPENDED);

    const approveRes = await postAs(
      `/studios/${studio.id}/mixes/${m1.id}/approve`,
      {},
      'manager',
      idempotencyKey('x2-approve')
    );
    expectErrorCode(approveRes, CONSTANTS.errors.INVALID_STATE);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${m2.id}/submit`,
      {},
      'curator',
      idempotencyKey('x2')
    );

    expectSuccess(res);
    const m2Updated = unwrap(res.body) as Mix;
    expect(m2Updated.status).toBe('SUBMITTED');
  });

  test('CROSS_003: legal correction triggers shedding, INTERNAL archived before PUBLIC', async () => {

    const studio = await createStudio({ token_budget: 8 });

    const iAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 5; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 121, 'FULL');
      iAssets.push(result);
    }

    const pAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 3; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      pAssets.push(result);
    }

    const iMix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, iMix.id, iAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), iMix.version);
    await submitMix(studio.id, iMix.id);
    await approveMix(studio.id, iMix.id);
    await publishMix(studio.id, iMix.id);

    const pMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, pMix.id, pAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), pMix.version);
    await submitMix(studio.id, pMix.id);
    await approveMix(studio.id, pMix.id);
    await publishMix(studio.id, pMix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(8);

    const assetToCorrect = pAssets[0].asset;
    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetToCorrect.id}`,
      { duration_sec: 121 },
      assetToCorrect.version,
      'legal'
    );

    expectSuccess(res);

    const iUnpublish = await postAs(
      `/studios/${studio.id}/mixes/${iMix.id}/unpublish`,
      {},
      'manager',
      idempotencyKey('x3-i-unpublish')
    );
    expectErrorCode(iUnpublish, CONSTANTS.errors.INVALID_STATE);

    const pLegalUnpublish = await postAs(
      `/studios/${studio.id}/mixes/${pMix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('x3-p-legal-unpublish')
    );
    expectSuccess(pLegalUnpublish);
  });

  test('CROSS_004: shedding archives INTERNAL first when budget exceeded', async () => {

    const studio = await createStudio({ token_budget: 8 });

    const iAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 4; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      iAssets.push(result);
    }

    const p1Assets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 3; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      p1Assets.push(result);
    }

    const p2Assets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 3; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      p2Assets.push(result);
    }

    const iMix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, iMix.id, iAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), iMix.version);
    await submitMix(studio.id, iMix.id);
    await approveMix(studio.id, iMix.id);
    await publishMix(studio.id, iMix.id);

    const p1Mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, p1Mix.id, p1Assets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), p1Mix.version);
    await submitMix(studio.id, p1Mix.id);
    await approveMix(studio.id, p1Mix.id);
    await publishMix(studio.id, p1Mix.id);

    const p2Mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, p2Mix.id, p2Assets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), p2Mix.version);
    await submitMix(studio.id, p2Mix.id);
    await approveMix(studio.id, p2Mix.id);
    await publishMix(studio.id, p2Mix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(8);

    const assetToCorrect = p1Assets[0].asset;

    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetToCorrect.id}`,
      { duration_sec: 121 },
      assetToCorrect.version,
      'legal'
    );

    expectSuccess(res);

    const archiveIRes = await postAs(`/studios/${studio.id}/mixes/${iMix.id}/archive`, {}, 'manager', idempotencyKey('verify-i-archived'));
    expectErrorCode(archiveIRes, CONSTANTS.errors.INVALID_STATE);

    const unpublishP1LegalRes = await postAs(`/studios/${studio.id}/mixes/${p1Mix.id}/unpublish`, {}, 'legal', idempotencyKey('verify-p1-frozen-legal'));
    expectSuccess(unpublishP1LegalRes);

    const unpublishP2LegalRes = await postAs(`/studios/${studio.id}/mixes/${p2Mix.id}/unpublish`, {}, 'legal', idempotencyKey('verify-p2-published-legal'));

    expectErrorCode(unpublishP2LegalRes, CONSTANTS.errors.ROLE_FORBIDDEN);
    const unpublishP2ManagerRes = await postAs(`/studios/${studio.id}/mixes/${p2Mix.id}/unpublish`, {}, 'manager', idempotencyKey('verify-p2-published-manager'));
    expectSuccess(unpublishP2ManagerRes);
  });

  test('CROSS_005: shedding with same kind and cost uses lexicographic mix id order', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const sharedResult = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const sharedAsset = sharedResult.asset;

    const p1Extra: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 2; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      p1Extra.push(result);
    }

    const p2Extra: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 2; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      p2Extra.push(result);
    }

    const p1Mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, p1Mix.id, [
      { asset_id: sharedAsset.id, slot: 'NORMAL' },
      { asset_id: p1Extra[0].asset.id, slot: 'NORMAL' },
      { asset_id: p1Extra[1].asset.id, slot: 'NORMAL' }
    ], p1Mix.version);
    await submitMix(studio.id, p1Mix.id);
    await approveMix(studio.id, p1Mix.id);
    await publishMix(studio.id, p1Mix.id);

    const p2Mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, p2Mix.id, [
      { asset_id: sharedAsset.id, slot: 'NORMAL' },
      { asset_id: p2Extra[0].asset.id, slot: 'NORMAL' },
      { asset_id: p2Extra[1].asset.id, slot: 'NORMAL' }
    ], p2Mix.version);
    await submitMix(studio.id, p2Mix.id);
    await approveMix(studio.id, p2Mix.id);
    await publishMix(studio.id, p2Mix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(6);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${sharedAsset.id}`,
      { duration_sec: 421 },
      sharedResult.asset.version,
      'legal'
    );

    expectSuccess(res);

    const studioAfterShedding = await getStudio(studio.id);
    expect(studioAfterShedding.token_reserved).toBe(0);
    expect(studioAfterShedding.token_committed).toBe(6);

    const smallerId = (p1Mix.id < p2Mix.id) ? p1Mix.id : p2Mix.id;
    const largerId = (p1Mix.id < p2Mix.id) ? p2Mix.id : p1Mix.id;

    const unpubSmall = await postAs(`/studios/${studio.id}/mixes/${smallerId}/unpublish`, {}, 'manager', idempotencyKey('x5-small'));
    const unpubLarge = await postAs(`/studios/${studio.id}/mixes/${largerId}/unpublish`, {}, 'manager', idempotencyKey('x5-large'));
    expectErrorCode(unpubSmall, CONSTANTS.errors.INVALID_STATE);
    expectSuccess(unpubLarge);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved + studioAfter.token_committed).toBeLessThanOrEqual(studioAfter.token_budget);
  });

  test('CROSS_006: legal correction bounces affected queued mix and restores budget invariants', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const iAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 6; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      iAssets.push(result);
    }

    const pAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 3; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      pAssets.push(result);
    }

    const iMix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, iMix.id, iAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), iMix.version);
    await submitMix(studio.id, iMix.id);

    const pMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, pMix.id, pAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), pMix.version);
    await submitMix(studio.id, pMix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(6);

    const assetToCorrect = pAssets[0].asset;

    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetToCorrect.id}`,
      { duration_sec: 240 },
      assetToCorrect.version,
      'legal'
    );

    expectSuccess(res);

    const studioAfter = await getStudio(studio.id);

    expect(studioAfter.token_reserved).toBe(3);
    expect(studioAfter.token_reserved + studioAfter.token_committed).toBeLessThanOrEqual(studioAfter.token_budget);

    const submitPRes = await postAs(`/studios/${studio.id}/mixes/${pMix.id}/submit`, {}, 'curator', idempotencyKey('verify-p-draft'));
    expectErrorCode(submitPRes, CONSTANTS.errors.ASSET_QUARANTINED);

    const approveIRes = await postAs(`/studios/${studio.id}/mixes/${iMix.id}/approve`, {}, 'manager', idempotencyKey('verify-i-still-submitted'));
    expectSuccess(approveIRes);
  });

  test('CROSS_007: legal correction bounces SUBMITTED mix containing corrected asset', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(1);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 240 },
      asset.version,
      'legal'
    );

    expectSuccess(res);

    const submitRes = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('verify-draft'));
    expectErrorCode(submitRes, CONSTANTS.errors.ASSET_QUARANTINED);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('CROSS_008: legal correction freezes PUBLISHED mix and updates token_cost', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(1);

    const res = await patchAs(
      `/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 240 },
      asset.version,
      'legal'
    );

    expectSuccess(res);

    const studioAfterCorrection = await getStudio(studio.id);
    expect(studioAfterCorrection.token_committed).toBe(2);

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${mix.id}/unpublish`, {}, 'legal', idempotencyKey('verify-frozen'));
    expectSuccess(unpublishRes);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('CROSS_009: unpublish from FROZEN returns mix to APPROVED when approved_in_cycle is current', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [{ asset_id: asset.id, slot: 'NORMAL' }], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    await createDispute(studio.id, { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' });

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('x9')
    );

    expectSuccess(res);
    const unpublished = unwrap(res.body) as Mix;
    expect(unpublished.status).toBe('APPROVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('CROSS_010: ERR_SPOTLIGHT_CAP_EXCEEDED precedes ERR_TOKEN_BUDGET_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 1 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset1.id,
      severity: 'LOW'
    });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset2.id,
      severity: 'LOW'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const { asset: a1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: a2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const putRes = await putAs(
      `/studios/${studio.id}/mixes/${mix.id}/entries`,
      {
        entries: [
          { asset_id: a1.id, slot: 'SPOTLIGHT' },
          { asset_id: a2.id, slot: 'SPOTLIGHT' }
        ]
      },
      mix.version,
      'curator'
    );

    if (putRes.status >= 400) {
      expectErrorCode(putRes, CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED);
      return;
    }

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('x10')
    );

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED);
  });

  test('CROSS_011: curator cannot publish evidence mix, ERR_ROLE_FORBIDDEN', async () => {

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

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version, 'legal');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'curator',
      idempotencyKey('x11')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('CROSS_012: submit fails ERR_CLEARANCE_SUSPENDED when clearance is suspended', async () => {
    const studio2 = await createStudio({ token_budget: 20 });
    const { asset: asset2, clearance: clearance2 } = await createActiveAssetWithClearance(studio2.id, 120, 'FULL');

    const mix2 = await createMix(studio2.id, { kind: 'PUBLIC' });
    await setMixEntries(studio2.id, mix2.id, [
      { asset_id: asset2.id, slot: 'NORMAL' }
    ], mix2.version);
    await submitMix(studio2.id, mix2.id);
    await approveMix(studio2.id, mix2.id);

    await suspendClearance(studio2.id, clearance2.id);

    const res = await postAs(
      `/studios/${studio2.id}/mixes/${mix2.id}/submit`,
      {},
      'curator',
      idempotencyKey('x12')
    );

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_SUSPENDED);
  });

  test('CROSS_013: revoking clearance archives PUBLISHED mix', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(1);

    const res = await postAs(
      `/studios/${studio.id}/clearances/${clearance.id}/revoke`,
      {},
      'legal',
      idempotencyKey('x13')
    );

    expectSuccess(res);

    const archiveRes = await postAs(`/studios/${studio.id}/mixes/${mix.id}/archive`, {}, 'manager', idempotencyKey('verify-archived'));
    expectErrorCode(archiveRes, CONSTANTS.errors.INVALID_STATE);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('CROSS_014: LOW dispute on PUBLISHED mix freezes it, tokens unchanged', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const qAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 6; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      qAssets.push(result);
    }

    const lAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 4; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      lAssets.push(result);
    }

    const qMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, qMix.id, qAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), qMix.version);
    await submitMix(studio.id, qMix.id);

    const lMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, lMix.id, lAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), lMix.version);
    await submitMix(studio.id, lMix.id);
    await approveMix(studio.id, lMix.id);
    await publishMix(studio.id, lMix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(6);
    expect(studioState.token_committed).toBe(4);

    const res = await postAs(
      `/studios/${studio.id}/disputes`,
      {
        target_type: 'MIX',
        target_id: lMix.id,
        severity: 'LOW'
      },
      'legal',
      idempotencyKey('x14')
    );

    expectSuccess(res);

    const studioAfterDispute = await getStudio(studio.id);

    expect(studioAfterDispute.token_reserved).toBe(6);
    expect(studioAfterDispute.token_committed).toBe(4);

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${lMix.id}/unpublish`, {}, 'legal', idempotencyKey('verify-frozen'));
    expectSuccess(unpublishRes);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('CROSS_015: legal correction triggers shedding, queued bounced first', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const qAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 6; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      qAssets.push(result);
    }

    const lAssets: { asset: Asset; clearance: Clearance }[] = [];
    for (let i = 0; i < 4; i++) {
      const result = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      lAssets.push(result);
    }

    const qMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, qMix.id, qAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), qMix.version);
    await submitMix(studio.id, qMix.id);

    const lMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, lMix.id, lAssets.map(a => ({
      asset_id: a.asset.id,
      slot: 'NORMAL' as const
    })), lMix.version);
    await submitMix(studio.id, lMix.id);
    await approveMix(studio.id, lMix.id);
    await publishMix(studio.id, lMix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(6);
    expect(studioState.token_committed).toBe(4);

    const assetToCorrect = lAssets[0].asset;

    const res = await patchAs(
      `/studios/${studio.id}/assets/${assetToCorrect.id}`,
      { duration_sec: 421 },
      assetToCorrect.version,
      'legal'
    );

    expectSuccess(res);

    const studioAfterCorrection = await getStudio(studio.id);
    expect(studioAfterCorrection.token_reserved).toBe(0);
    expect(studioAfterCorrection.token_reserved + studioAfterCorrection.token_committed).toBeLessThanOrEqual(studioAfterCorrection.token_budget);

    const submitQRes = await postAs(`/studios/${studio.id}/mixes/${qMix.id}/submit`, {}, 'curator', idempotencyKey('verify-q-draft'));
    expectErrorCode(submitQRes, CONSTANTS.errors.TOKEN_BUDGET_EXCEEDED);

    const unpublishLRes = await postAs(`/studios/${studio.id}/mixes/${lMix.id}/unpublish`, {}, 'manager', idempotencyKey('verify-l-frozen'));
    expectSuccess(unpublishLRes);
  });

  test('CROSS_016: dispute on unrelated asset keeps posture REVIEW, published mix unaffected', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset1.id,
      severity: 'LOW'
    });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    const res = await postAs(
      `/studios/${studio.id}/disputes`,
      {
        target_type: 'ASSET',
        target_id: disputeAsset2.id,
        severity: 'LOW'
      },
      'legal',
      idempotencyKey('x16')
    );

    expectSuccess(res);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('REVIEW');

    const unpublishRes = await postAs(`/studios/${studio.id}/mixes/${mix.id}/unpublish`, {}, 'manager', idempotencyKey('verify-still-published'));
    expectSuccess(unpublishRes);
  });

  test('CROSS_017: PUBLIC publish fails ERR_POSTURE_BLOCKED in REVIEW posture', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset1.id,
      severity: 'LOW'
    });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset2.id,
      severity: 'LOW'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);
    expect(approvedMix.status).toBe('APPROVED');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('x17')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('CROSS_018: publish fails ERR_POSTURE_BLOCKED when posture becomes HALT', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    let studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('OPEN');

    const disputeAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset.id,
      severity: 'HIGH'
    });

    studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('x18')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('CROSS_019: idempotency key reuse allowed in new cycle', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const idemKey = idempotencyKey('x19');
    await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idemKey
    );

    const studioAfterCycle1Submit = await getStudio(studio.id);
    expect(studioAfterCycle1Submit.token_reserved).toBe(1);

    await advanceCycle(studio.id);

    const studioAfterAdvance = await getStudio(studio.id);
    expect(studioAfterAdvance.cycle_index).toBe(2);
    expect(studioAfterAdvance.token_reserved).toBe(0);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idemKey
    );

    expectSuccess(res);
    const submitted = unwrap(res.body) as Mix;
    expect(submitted.status).toBe('SUBMITTED');

    const studioAfterCycle2Submit = await getStudio(studio.id);
    expect(studioAfterCycle2Submit.token_reserved).toBe(1);
  });

  test('CROSS_020: dismissing a dispute removes quarantine but does not auto-regrant clearance', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const disputeRes = await postAs(
      `/studios/${studio.id}/disputes`,
      { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' },
      'legal',
      idempotencyKey('x20-create')
    );
    expectSuccess(disputeRes);
    const dispute = unwrap(disputeRes.body) as any;

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal',
      idempotencyKey('x20-dismiss')
    );
    expectSuccess(res);

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [{ asset_id: asset.id, slot: 'NORMAL' }], mix.version);
    const submitRes = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('x20-submit'));
    expectErrorCode(submitRes, CONSTANTS.errors.CLEARANCE_SUSPENDED);

    await grantClearance(studio.id, clearance.id);
    const submitAfterGrant = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('x20-submit-after-grant'));
    expectSuccess(submitAfterGrant);
  });

});
