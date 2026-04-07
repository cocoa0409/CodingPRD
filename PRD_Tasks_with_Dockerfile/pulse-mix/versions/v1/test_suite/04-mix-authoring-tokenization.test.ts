import {
  postAs,
  putAs,
  putAsNoIfMatch,
  getAs,
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
  createAsset,
  createClearance,
  grantClearance,
  activateAsset,
  createMix,
  setMixEntries,
  submitMix,
  approveMix,
  publishMix,
  createDispute,
  createActiveAssetWithClearance,
  submitApproveAndPublishMix,
  uniqueId,
  unwrap,
  Mix,
  Studio,
  Asset
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

describe('Mix Authoring & Tokenization Tests', () => {

  async function putEntriesAndAllowEitherStage(
    studioId: string,
    mix: Mix,
    entries: Array<{ asset_id: string; slot: any }>,
    role: 'curator' | 'manager' | 'legal',
    expectedErrorCode: string
  ): Promise<{ ok: false } | { ok: true; mix: Mix }> {
    const putRes = await putAs(`/studios/${studioId}/mixes/${mix.id}/entries`, { entries }, mix.version, role);
    if (putRes.status >= 400) {
      expectErrorCode(putRes, expectedErrorCode);
      return { ok: false };
    }
    expectSuccess(putRes);
    return { ok: true, mix: unwrap(putRes.body) as Mix };
  }

  test('MIX_A_001: POST /studios/S/mixes creates DRAFT mix with empty entries and token_cost 0', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const idemKey = idempotencyKey('m1');
    const res = await postAs(`/studios/${studio.id}/mixes`, {
      title: 'p',
      kind: 'PUBLIC'
    }, 'curator', idemKey);

    expectSuccess(res);
    const mix = unwrap(res.body) as Mix;

    expect(mix.status).toBe('DRAFT');
    expect(mix.entries).toEqual([]);
    expect(mix.token_cost).toBe(0);
  });

  test('MIX_A_002: PUT /studios/S/mixes/M/entries without If-Match fails ERR_MISSING_IF_MATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAsNoIfMatch(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: []
    }, 'curator');

    expectErrorCode(res, CONSTANTS.errors.MISSING_IF_MATCH);
  });

  test('MIX_A_003: PUT entries with assets 120s and 121s calculates token_cost = 1 + 2 = 3', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 121, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetB.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(3);
    expect(updatedMix.status).toBe('DRAFT');
    expect(updatedMix.version).toBeGreaterThan(mix.version);
  });

  test('MIX_A_004: PUT entries with SPOTLIGHT calculates token_cost = (2+1) + 3 = 6', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 240, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 241, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'SPOTLIGHT' },
        { asset_id: assetB.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(6);
  });

  test('MIX_A_005: PUBLIC mix with duplicate asset_id fails ERR_ENTRY_DUPLICATE_PUBLIC', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetA.id, slot: 'NORMAL' }
      ],
      'curator',
      CONSTANTS.errors.ENTRY_DUPLICATE_PUBLIC
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m5'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_DUPLICATE_PUBLIC);
  });

  test('MIX_A_006: PUT entries with duplicate asset_id in INTERNAL mix succeeds if not adjacent', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetB.id, slot: 'NORMAL' },
        { asset_id: assetA.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(1);
  });

  test('MIX_A_007: submit INTERNAL mix with adjacent duplicates fails ERR_ENTRY_ADJACENT_DUPLICATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetA.id, slot: 'NORMAL' }
      ],
      'curator',
      CONSTANTS.errors.ENTRY_ADJACENT_DUPLICATE
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m7'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_ADJACENT_DUPLICATE);
  });

  test('MIX_A_008: INTERNAL mix with 1 entry has token_cost = 1 (minimum)', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(1);
  });

  test('MIX_A_009: INTERNAL mix with raw sum 2 has token_cost = floor(2/2) = 1', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetB.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(1);
  });

  test('MIX_A_010: INTERNAL mix with SPOTLIGHT has token_cost = floor(5/2) = 2', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 240, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 240, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'SPOTLIGHT' },
        { asset_id: assetB.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(2);
  });

  test('MIX_A_011: PUBLIC/INTERNAL mix with 26 entries fails ERR_ENTRY_LIMIT', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const assets: Asset[] = [];
    for (let i = 0; i < 26; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      assets.map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })),
      'curator',
      CONSTANTS.errors.ENTRY_LIMIT
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m11'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_LIMIT);
  });

  test('MIX_A_012: EVIDENCE mix with 11 entries fails ERR_ENTRY_LIMIT', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const assets: Asset[] = [];
    for (let i = 0; i < 11; i++) {
      const asset = await createAsset(studio.id, { duration_sec: 120 });
      await createDispute(studio.id, {
        target_type: 'ASSET',
        target_id: asset.id,
        severity: 'LOW'
      });

      assets.push(asset);
    }

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');

    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      assets.map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })),
      'legal',
      CONSTANTS.errors.ENTRY_LIMIT
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/publish`, {}, 'legal', idempotencyKey('m12'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_LIMIT);
  });

  test('MIX_A_013: submit PUBLIC mix with 4 SPOTLIGHT entries fails ERR_SPOTLIGHT_CAP_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const assets: Asset[] = [];
    for (let i = 0; i < 4; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      assets.map(a => ({ asset_id: a.id, slot: 'SPOTLIGHT' as const })),
      'curator',
      CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m13'));

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED);
  });

  test('MIX_A_014: submit INTERNAL mix with 6 SPOTLIGHT entries fails ERR_SPOTLIGHT_CAP_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const assets: Asset[] = [];
    for (let i = 0; i < 6; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      assets.map(a => ({ asset_id: a.id, slot: 'SPOTLIGHT' as const })),
      'curator',
      CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m14'));

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED);
  });

  test('MIX_A_015: submit mix with 2 SPOTLIGHT entries in REVIEW posture fails ERR_SPOTLIGHT_CAP_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset1.id, severity: 'LOW' });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset2.id, severity: 'LOW' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [
        { asset_id: assetA.id, slot: 'SPOTLIGHT' },
        { asset_id: assetB.id, slot: 'SPOTLIGHT' }
      ],
      'curator',
      CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m15'));

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_CAP_EXCEEDED);
  });

  test('MIX_A_016: publish EVIDENCE mix with SPOTLIGHT entry fails ERR_SPOTLIGHT_NOT_ALLOWED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' });

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [{ asset_id: asset.id, slot: 'SPOTLIGHT' }],
      'legal',
      CONSTANTS.errors.SPOTLIGHT_NOT_ALLOWED
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/publish`, {}, 'legal', idempotencyKey('m16'));

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_NOT_ALLOWED);
  });

  test('MIX_A_017: submit mix with DRAFT asset fails ERR_ASSET_NOT_ACTIVE', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m17'));

    expectErrorCode(res, CONSTANTS.errors.ASSET_NOT_ACTIVE);
  });

  test('MIX_A_018: submit mix with QUARANTINED asset fails ERR_ASSET_QUARANTINED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const patchRes = await patchAs(`/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 240 },
      asset.version,
      'legal'
    );
    expectSuccess(patchRes);

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m18'));

    expectErrorCode(res, CONSTANTS.errors.ASSET_QUARANTINED);
  });

  test('MIX_A_019: submit mix with SUSPENDED clearance fails ERR_CLEARANCE_SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);
    await activateAsset(studio.id, asset.id);

    await postAs(`/studios/${studio.id}/clearances/${clearance.id}/suspend`, {}, 'legal', idempotencyKey('suspend'));

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m19'));

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_SUSPENDED);
  });

  test('MIX_A_020: submit PUBLIC mix with PROMO clearance fails ERR_CLEARANCE_POLICY_MISMATCH', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m20'));

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_POLICY_MISMATCH);
  });

  test('MIX_A_021: submit INTERNAL mix with PROMO clearance succeeds', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    const mixWithEntries = await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m21'));

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.status).toBe('SUBMITTED');

    const studioState = await getStudio(studio.id);
    expect(studioState.token_reserved).toBe(mixWithEntries.token_cost);
  });

  test('MIX_A_022: submit mix with no entries fails ERR_ENTRY_LIMIT', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m22'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_LIMIT);
  });

  test('MIX_A_023: publish EVIDENCE mix with adjacent duplicates fails ERR_ENTRY_ADJACENT_DUPLICATE', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' });

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [
        { asset_id: asset.id, slot: 'NORMAL' },
        { asset_id: asset.id, slot: 'NORMAL' }
      ],
      'legal',
      CONSTANTS.errors.ENTRY_ADJACENT_DUPLICATE
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/publish`, {}, 'legal', idempotencyKey('m23'));

    expectErrorCode(res, CONSTANTS.errors.ENTRY_ADJACENT_DUPLICATE);
  });

  test('MIX_A_025: publish EVIDENCE mix with quarantined asset without dispute fails ERR_DISPUTE_BLOCKING', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const patchRes = await patchAs(`/studios/${studio.id}/assets/${asset.id}`,
      { duration_sec: 240 },
      asset.version,
      'legal'
    );
    expectSuccess(patchRes);

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    const putResult = await putEntriesAndAllowEitherStage(
      studio.id,
      mix,
      [{ asset_id: asset.id, slot: 'NORMAL' }],
      'legal',
      CONSTANTS.errors.DISPUTE_BLOCKING
    );
    if (!putResult.ok) return;

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/publish`, {}, 'legal', idempotencyKey('m25'));

    expectErrorCode(res, CONSTANTS.errors.DISPUTE_BLOCKING);
  });

  test('MIX_A_026: publish valid EVIDENCE mix goes directly to FROZEN with token_cost 0', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const assetA = await createAsset(studio.id, { duration_sec: 120 });
    const assetB = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: assetA.id, severity: 'LOW' });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: assetB.id, severity: 'LOW' });

    const studioBeforePublish = await getStudio(studio.id);

    const mix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    await setMixEntries(studio.id, mix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], mix.version, 'legal');

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/publish`, {}, 'legal', idempotencyKey('m26'));

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;

    expect(publishedMix.status).toBe('FROZEN');
    expect(publishedMix.token_cost).toBe(0);

    const studioAfterPublish = await getStudio(studio.id);
    expect(studioAfterPublish.token_committed).toBe(studioBeforePublish.token_committed);
    expect(studioAfterPublish.token_reserved).toBe(studioBeforePublish.token_reserved);
  });

  test('MIX_A_027: submit PUBLIC mix in REVIEW posture succeeds if spotlight cap satisfied', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset1.id, severity: 'LOW' });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset2.id, severity: 'LOW' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m27'));

    expectSuccess(res);
    const submittedMix = unwrap(res.body) as Mix;

    expect(submittedMix.status).toBe('SUBMITTED');
  });

  test('MIX_A_028: PUT entries with wrong If-Match fails ERR_VERSION_CONFLICT', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const updatedMix = await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [{ asset_id: asset.id, slot: 'NORMAL' }]
    }, 1, 'curator');

    expectErrorCode(res, CONSTANTS.errors.VERSION_CONFLICT);
  });

  test('MIX_A_029: PUT entries on PUBLISHED mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [{ asset_id: asset.id, slot: 'NORMAL' }], mix.version);
    const publishedMix = await submitApproveAndPublishMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [{ asset_id: asset.id, slot: 'NORMAL' }]
    }, publishedMix.version, 'curator');

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_A_030: PUT entries on SUBMITTED mix resets to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], mix.version);
    const submittedMix = await submitMix(studio.id, mix.id);

    const studioBeforeEdit = await getStudio(studio.id);
    expect(studioBeforeEdit.token_reserved).toBeGreaterThan(0);

    expect(submittedMix.status).toBe('SUBMITTED');

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [{ asset_id: assetA.id, slot: 'NORMAL' }]
    }, submittedMix.version, 'curator');

    expectSuccess(res);
    const editedMix = unwrap(res.body) as Mix;

    expect(editedMix.status).toBe('DRAFT');

    const studioAfterEdit = await getStudio(studio.id);
    expect(studioAfterEdit.token_reserved).toBe(0);
  });

  test('MIX_A_031: PUT entries on APPROVED mix resets to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);

    const studioBeforeEdit = await getStudio(studio.id);
    expect(studioBeforeEdit.token_reserved).toBeGreaterThan(0);

    expect(approvedMix.status).toBe('APPROVED');

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [{ asset_id: assetA.id, slot: 'NORMAL' }]
    }, approvedMix.version, 'curator');

    expectSuccess(res);
    const editedMix = unwrap(res.body) as Mix;

    expect(editedMix.status).toBe('DRAFT');

    const studioAfterEdit = await getStudio(studio.id);
    expect(studioAfterEdit.token_reserved).toBe(0);
  });

  test('MIX_A_032: submit INTERNAL mix reserves correct token_cost', async () => {

    const studio = await createStudio({ token_budget: 2 });

    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 240, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 240, 'FULL');
    const { asset: assetC } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    const withEntries = await setMixEntries(studio.id, mix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' },
      { asset_id: assetC.id, slot: 'NORMAL' }
    ], mix.version);
    expect(withEntries.token_cost).toBe(2);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m32'));

    expectSuccess(res);
    const submittedMix = unwrap(res.body) as Mix;

    expect(submittedMix.status).toBe('SUBMITTED');

    const studioAfterSubmit = await getStudio(studio.id);
    expect(studioAfterSubmit.token_reserved).toBe(2);
    expect(studioAfterSubmit.token_available).toBe(0);
  });

  test('MIX_A_033: submit mix that exceeds budget fails ERR_TOKEN_BUDGET_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 2 });

    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const publishedMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, publishedMix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], publishedMix.version);
    await submitApproveAndPublishMix(studio.id, publishedMix.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(2);

    const { asset: assetC } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const newMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, newMix.id, [
      { asset_id: assetC.id, slot: 'NORMAL' }
    ], newMix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${newMix.id}/submit`, {}, 'curator', idempotencyKey('m33'));

    expectErrorCode(res, CONSTANTS.errors.TOKEN_BUDGET_EXCEEDED);
  });

  test('MIX_A_034: clearance policy error takes precedence over budget error', async () => {

    const studio = await createStudio({ token_budget: 2 });

    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const publishedMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, publishedMix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], publishedMix.version);
    await submitApproveAndPublishMix(studio.id, publishedMix.id);

    const { asset: promoAsset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const newMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, newMix.id, [
      { asset_id: promoAsset.id, slot: 'NORMAL' }
    ], newMix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${newMix.id}/submit`, {}, 'curator', idempotencyKey('m34'));

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_POLICY_MISMATCH);
  });

  test('MIX_A_035: dispute blocking error takes precedence over budget error', async () => {

    const studio = await createStudio({ token_budget: 2 });

    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const publishedMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, publishedMix.id, [
      { asset_id: assetA.id, slot: 'NORMAL' },
      { asset_id: assetB.id, slot: 'NORMAL' }
    ], publishedMix.version);
    await submitApproveAndPublishMix(studio.id, publishedMix.id);

    const { asset: disputedAsset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputedAsset.id, severity: 'LOW' });

    const newMix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, newMix.id, [
      { asset_id: disputedAsset.id, slot: 'NORMAL' }
    ], newMix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${newMix.id}/submit`, {}, 'curator', idempotencyKey('m35'));

    expectErrorCode(res, CONSTANTS.errors.DISPUTE_BLOCKING);
  });

  test('MIX_A_036: PUT entries with assets 420s and 421s calculates token_cost = 3 + 4 = 7', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 420, 'FULL');
    const { asset: assetB } = await createActiveAssetWithClearance(studio.id, 421, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' },
        { asset_id: assetB.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(7);
  });

  test('MIX_A_037: PUT entries with 3600s asset in SPOTLIGHT calculates token_cost = 5', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 3600, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'SPOTLIGHT' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(5);
  });

  test('MIX_A_038: INTERNAL mix with 121s asset has token_cost = floor(2/2) = 1', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 121, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });

    const res = await putAs(`/studios/${studio.id}/mixes/${mix.id}/entries`, {
      entries: [
        { asset_id: assetA.id, slot: 'NORMAL' }
      ]
    }, mix.version, 'curator');

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;

    expect(updatedMix.token_cost).toBe(1);
  });

  test('MIX_A_039: submit INTERNAL mix with PROMO asset in SPOTLIGHT fails ERR_SPOTLIGHT_NOT_ALLOWED', async () => {

    const studio = await createStudio({ token_budget: 100 });
    const { asset: assetA } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: assetA.id, slot: 'SPOTLIGHT' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m39'));

    expectErrorCode(res, CONSTANTS.errors.SPOTLIGHT_NOT_ALLOWED);
  });

  test('MIX_A_040: submit INTERNAL mix with PROMO in NORMAL slot succeeds in REVIEW posture', async () => {

    const studio = await createStudio({ token_budget: 100 });

    const disputeAsset1 = await createAsset(studio.id, { duration_sec: 120 });
    const disputeAsset2 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset1.id, severity: 'LOW' });
    await createDispute(studio.id, { target_type: 'ASSET', target_id: disputeAsset2.id, severity: 'LOW' });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('REVIEW');

    const { asset: promoAsset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    const mixWithEntries = await setMixEntries(studio.id, mix.id, [
      { asset_id: promoAsset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idempotencyKey('m40'));

    expectSuccess(res);
    const submittedMix = unwrap(res.body) as Mix;

    expect(submittedMix.status).toBe('SUBMITTED');

    const studioAfterSubmit = await getStudio(studio.id);
    expect(studioAfterSubmit.token_reserved).toBe(mixWithEntries.token_cost);
  });

});
