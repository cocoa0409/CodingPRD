import {
  postAs,
  postAsNoIdem,
  getAs,
  putAs,
  idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectErrorCodeOneOf
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
  unpublishMix,
  freezeMix,
  archiveMix,
  createDispute,
  createActiveAssetWithClearance,
  uniqueId,
  unwrap,
  Mix,
  Studio,
  Asset
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

describe('Mix Lifecycle Tests', () => {

  test('MIX_L_001: submit reserves token_cost into token_reserved', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const { asset: a1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: a2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: a3 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: a4 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: a1.id, slot: 'NORMAL' },
      { asset_id: a2.id, slot: 'NORMAL' },
      { asset_id: a3.id, slot: 'NORMAL' },
      { asset_id: a4.id, slot: 'NORMAL' }
    ], mix.version);

    const studioBeforeSubmit = await getStudio(studio.id);
    expect(studioBeforeSubmit.token_reserved).toBe(0);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('l1')
    );

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;
    expect(updatedMix.status).toBe('SUBMITTED');

    const studioAfterSubmit = await getStudio(studio.id);
    expect(studioAfterSubmit.token_reserved).toBe(4);
  });

  test('MIX_L_002: approve transitions SUBMITTED to APPROVED with approved_in_cycle set', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const submittedMix = await submitMix(studio.id, mix.id);
    const reservedBefore = (await getStudio(studio.id)).token_reserved;

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/approve`,
      {},
      'manager',
      idempotencyKey('l2')
    );

    expectSuccess(res);
    const approvedMix = unwrap(res.body) as Mix;
    expect(approvedMix.status).toBe('APPROVED');
    expect(approvedMix.approved_in_cycle).toBe(studio.cycle_index);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(reservedBefore);
  });

  test('MIX_L_003: curator cannot approve mix - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/approve`,
      {},
      'curator',
      idempotencyKey('l3')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('MIX_L_004: HALT posture blocks mix approval - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const disputeAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/approve`,
      {},
      'manager',
      idempotencyKey('l4')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('MIX_L_005: publish moves tokens from reserved to committed', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    const reservedBefore = studioBefore.token_reserved;
    const committedBefore = studioBefore.token_committed;

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l5')
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;
    expect(publishedMix.status).toBe('PUBLISHED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(reservedBefore - publishedMix.token_cost);
    expect(studioAfter.token_committed).toBe(committedBefore + publishedMix.token_cost);
  });

  test('MIX_L_006: advance-cycle resets APPROVED mix to DRAFT preventing stale publish', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);
    expect(approvedMix.status).toBe('APPROVED');
    expect(approvedMix.approved_in_cycle).toBe(1);

    await advanceCycle(studio.id);

    const mixAfterAdvance = await getMix(studio.id, mix.id);
    expect(mixAfterAdvance.status).toBe('DRAFT');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l6')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_007: INTERNAL publish allowed in REVIEW posture', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

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

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l7')
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;
    expect(publishedMix.status).toBe('PUBLISHED');
  });

  test('MIX_L_008: PUBLIC publish blocked in REVIEW posture - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

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

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l8')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('MIX_L_009: HALT posture blocks INTERNAL publish - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const disputeAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l9')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('MIX_L_010: publish DRAFT mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l10')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_011: unpublish moves tokens from committed to reserved when returning to APPROVED', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);
    expect(studioBefore.token_reserved).toBe(0);
    const committedBefore = studioBefore.token_committed;

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'manager',
      idempotencyKey('l11')
    );

    expectSuccess(res);
    const unpublishedMix = unwrap(res.body) as Mix;
    expect(unpublishedMix.status).toBe('APPROVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(committedBefore - publishedMix.token_cost);

    expect(studioAfter.token_reserved).toBe(publishedMix.token_cost);
  });

  test('MIX_L_012: legal can unpublish FROZEN mix and tokens move to reserved', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const frozenMix = await getMix(studio.id, mix.id);
    expect(frozenMix.status).toBe('FROZEN');

    const studioBefore = await getStudio(studio.id);
    const committedBefore = studioBefore.token_committed;

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('l12')
    );

    expectSuccess(res);
    const unpublishedMix = unwrap(res.body) as Mix;
    expect(unpublishedMix.status).toBe('APPROVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(committedBefore - publishedMix.token_cost);
    expect(studioAfter.token_reserved).toBe(publishedMix.token_cost);
  });

  test('MIX_L_013: legal cannot unpublish PUBLISHED mix - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const publishedMix = await getMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('l13')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('MIX_L_014: curator cannot freeze mix - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/freeze`,
      {},
      'curator',
      idempotencyKey('l14')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('MIX_L_015: freeze keeps tokens committed', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    const committedBefore = studioBefore.token_committed;

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/freeze`,
      {},
      'legal',
      idempotencyKey('l15')
    );

    expectSuccess(res);
    const frozenMix = unwrap(res.body) as Mix;
    expect(frozenMix.status).toBe('FROZEN');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(committedBefore);
  });

  test('MIX_L_016: freeze DRAFT mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/freeze`,
      {},
      'legal',
      idempotencyKey('l16')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_017: archive SUBMITTED mix releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'manager',
      idempotencyKey('l17')
    );

    expectSuccess(res);
    const archivedMix = unwrap(res.body) as Mix;
    expect(archivedMix.status).toBe('ARCHIVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('MIX_L_018: archive PUBLISHED mix releases committed tokens', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'manager',
      idempotencyKey('l18')
    );

    expectSuccess(res);
    const archivedMix = unwrap(res.body) as Mix;
    expect(archivedMix.status).toBe('ARCHIVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('MIX_L_019: archive already ARCHIVED mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await archiveMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'manager',
      idempotencyKey('l19')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_020: editing entries while APPROVED resets to DRAFT and releases tokens', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset: asset1 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset1.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);
    expect(approvedMix.status).toBe('APPROVED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const currentMix = await getMix(studio.id, mix.id);

    const res = await putAs(
      `/studios/${studio.id}/mixes/${mix.id}/entries`,
      { entries: [{ asset_id: asset2.id, slot: 'NORMAL' }] },
      currentMix.version,
      'curator'
    );

    expectSuccess(res);
    const updatedMix = unwrap(res.body) as Mix;
    expect(updatedMix.status).toBe('DRAFT');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('MIX_L_021: editing entries while PUBLISHED fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);

    const res = await putAs(
      `/studios/${studio.id}/mixes/${mix.id}/entries`,
      { entries: [{ asset_id: asset.id, slot: 'SPOTLIGHT' }] },
      publishedMix.version,
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_022: submit already SUBMITTED mix fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('l22')
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('MIX_L_023: submit that exceeds budget fails ERR_TOKEN_BUDGET_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 5 });

    const assets: Asset[] = [];
    for (let i = 0; i < 5; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix1.id, assets.map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })), mix1.version);
    await submitMix(studio.id, mix1.id);
    await approveMix(studio.id, mix1.id);
    await publishMix(studio.id, mix1.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(5);
    expect(studioState.token_reserved).toBe(0);

    const { asset: newAsset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix2.id, [
      { asset_id: newAsset.id, slot: 'NORMAL' }
    ], mix2.version);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix2.id}/submit`,
      {},
      'curator',
      idempotencyKey('l23')
    );

    expectErrorCode(res, CONSTANTS.errors.TOKEN_BUDGET_EXCEEDED);
  });

  test('MIX_L_024: publish succeeds when reserved already includes mix cost', async () => {

    const studio = await createStudio({ token_budget: 6 });

    const assets: Asset[] = [];
    for (let i = 0; i < 5; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix1.id, assets.map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })), mix1.version);
    await submitMix(studio.id, mix1.id);
    await approveMix(studio.id, mix1.id);
    await publishMix(studio.id, mix1.id);

    const { asset: newAsset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mixM = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mixM.id, [
      { asset_id: newAsset.id, slot: 'NORMAL' }
    ], mixM.version);
    await submitMix(studio.id, mixM.id);
    await approveMix(studio.id, mixM.id);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(5);
    expect(studioState.token_reserved).toBe(1);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mixM.id}/publish`,
      {},
      'manager',
      idempotencyKey('l24')
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;
    expect(publishedMix.status).toBe('PUBLISHED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(6);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('MIX_L_025: submit fails when budget is full - ERR_TOKEN_BUDGET_EXCEEDED', async () => {

    const studio = await createStudio({ token_budget: 5 });

    const assets: Asset[] = [];
    for (let i = 0; i < 6; i++) {
      const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
      assets.push(asset);
    }

    const mix1 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix1.id, assets.slice(0, 5).map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })), mix1.version);
    await submitMix(studio.id, mix1.id);
    await approveMix(studio.id, mix1.id);
    await publishMix(studio.id, mix1.id);

    const studioAfterPublish = await getStudio(studio.id);
    expect(studioAfterPublish.token_committed).toBe(5);

    await unpublishMix(studio.id, mix1.id);

    const studioAfterUnpublish = await getStudio(studio.id);
    expect(studioAfterUnpublish.token_committed).toBe(0);
    expect(studioAfterUnpublish.token_reserved).toBe(5);

    await archiveMix(studio.id, mix1.id);

    const studioAfterArchive = await getStudio(studio.id);
    expect(studioAfterArchive.token_reserved).toBe(0);
    expect(studioAfterArchive.token_available).toBe(5);

    const mix2 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix2.id, assets.slice(0, 5).map(a => ({ asset_id: a.id, slot: 'NORMAL' as const })), mix2.version);
    await submitMix(studio.id, mix2.id);
    await approveMix(studio.id, mix2.id);
    await publishMix(studio.id, mix2.id);

    const mix3 = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix3.id, [{ asset_id: assets[5].id, slot: 'NORMAL' }], mix3.version);

    const studioState = await getStudio(studio.id);
    expect(studioState.token_committed).toBe(5);
    expect(studioState.token_available).toBe(0);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix3.id}/submit`,
      {},
      'curator',
      idempotencyKey('l25')
    );

    expectErrorCode(res, CONSTANTS.errors.TOKEN_BUDGET_EXCEEDED);
  });

  test('MIX_L_026: idempotency replay on publish returns stored response', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const idemKey = idempotencyKey('p1');

    const res1 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idemKey
    );
    expectSuccess(res1);
    const originalResult = unwrap(res1.body) as Mix;

    const studioAfterFirst = await getStudio(studio.id);
    const committedAfterFirst = studioAfterFirst.token_committed;

    const res2 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idemKey
    );

    expectSuccess(res2);
    const replayResult = unwrap(res2.body) as Mix;

    expect(replayResult.id).toBe(originalResult.id);
    expect(replayResult.status).toBe(originalResult.status);

    const studioAfterReplay = await getStudio(studio.id);
    expect(studioAfterReplay.token_committed).toBe(committedAfterFirst);
  });

  test('MIX_L_027: idempotency replay on unpublish returns stored response', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const idemKey = idempotencyKey('u1');

    const res1 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'manager',
      idemKey
    );
    expectSuccess(res1);
    const originalResult = unwrap(res1.body) as Mix;

    const studioAfterFirst = await getStudio(studio.id);
    const committedAfterFirst = studioAfterFirst.token_committed;

    const res2 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'manager',
      idemKey
    );

    expectSuccess(res2);
    const replayResult = unwrap(res2.body) as Mix;

    expect(replayResult.id).toBe(originalResult.id);

    const studioAfterReplay = await getStudio(studio.id);
    expect(studioAfterReplay.token_committed).toBe(committedAfterFirst);
  });

  test('MIX_L_028: unpublish without Idempotency-Key fails ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const res = await postAsNoIdem(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'manager'
    );

    expectErrorCode(res, CONSTANTS.errors.MISSING_IDEMPOTENCY_KEY);
  });

  test('MIX_L_029: idempotency replay on approve returns stored response', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const idemKey = idempotencyKey('ap1');

    const res1 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/approve`,
      {},
      'manager',
      idemKey
    );
    expectSuccess(res1);
    const originalResult = unwrap(res1.body) as Mix;

    const res2 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/approve`,
      {},
      'manager',
      idemKey
    );

    expectSuccess(res2);
    const replayResult = unwrap(res2.body) as Mix;

    expect(replayResult.id).toBe(originalResult.id);
    expect(replayResult.status).toBe(originalResult.status);
    expect(replayResult.approved_in_cycle).toBe(originalResult.approved_in_cycle);
  });

  test('MIX_L_030: publish with wrong If-Match fails ERR_VERSION_CONFLICT', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l30'),
      999
    );

    expectErrorCode(res, CONSTANTS.errors.VERSION_CONFLICT);
  });

  test('MIX_L_031: publish with correct If-Match succeeds', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    const approvedMix = await approveMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l31'),
      approvedMix.version
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;
    expect(publishedMix.status).toBe('PUBLISHED');
    expect(publishedMix.version).toBeGreaterThan(approvedMix.version);
  });

  test('MIX_L_032: submit EVIDENCE mix fails', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const evidenceMix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');

    await setMixEntries(studio.id, evidenceMix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], evidenceMix.version, 'legal');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${evidenceMix.id}/submit`,
      {},
      'curator',
      idempotencyKey('l32')
    );

    expectErrorCodeOneOf(res, [
      CONSTANTS.errors.INVALID_STATE,
      CONSTANTS.errors.ROLE_FORBIDDEN
    ]);
  });

  test('MIX_L_033: manager cannot publish EVIDENCE mix - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const evidenceMix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');

    await setMixEntries(studio.id, evidenceMix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], evidenceMix.version, 'legal');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${evidenceMix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l33')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('MIX_L_034: unpublish FROZEN evidence mix transitions to DRAFT', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const evidenceMix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    await setMixEntries(studio.id, evidenceMix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], evidenceMix.version, 'legal');

    const publishedEvidence = await publishMix(studio.id, evidenceMix.id, 'legal');
    expect(publishedEvidence.status).toBe('FROZEN');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${evidenceMix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('l34')
    );

    expectSuccess(res);
    const unpublishedMix = unwrap(res.body) as Mix;
    expect(unpublishedMix.status).toBe('DRAFT');
  });

  test('MIX_L_035: advance-cycle archives PUBLISHED mix', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idempotencyKey('l35')
    );

    expectSuccess(res);

    const mixAfter = await getMix(studio.id, mix.id);
    expect(mixAfter.status).toBe('ARCHIVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('MIX_L_036: advance-cycle resets SUBMITTED mix to DRAFT', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/advance-cycle`,
      {},
      'manager',
      idempotencyKey('l36')
    );

    expectSuccess(res);

    const mixAfter = await getMix(studio.id, mix.id);
    expect(mixAfter.status).toBe('DRAFT');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('MIX_L_037: PUBLIC publish blocked in REVIEW posture', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

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

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l37')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('MIX_L_038: INTERNAL mix with PROMO assets publishes successfully', async () => {

    const studio = await createStudio({ token_budget: 10 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('l38')
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;
    expect(publishedMix.status).toBe('PUBLISHED');
  });

  test('MIX_L_039: dispute on asset bounces APPROVED mix to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

    const mixBefore = await getMix(studio.id, mix.id);
    expect(mixBefore.status).toBe('APPROVED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);
    const reservedBefore = studioBefore.token_reserved;

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const mixAfterDispute = await getMix(studio.id, mix.id);
    expect(mixAfterDispute.status).toBe('DRAFT');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(reservedBefore - mixBefore.token_cost);

    const assetAfter = await getAs(`/studios/${studio.id}/assets/${asset.id}`, 'curator');
    expectSuccess(assetAfter);
    expect(unwrap(assetAfter.body).status).toBe('QUARANTINED');
  });

  test('MIX_L_040: curator cannot archive mix - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 10 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/archive`,
      {},
      'curator',
      idempotencyKey('l40')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

});

async function getMix(studioId: string, mixId: string): Promise<Mix> {
  const res = await getAs(`/studios/${studioId}/mixes/${mixId}`, 'curator');
  expectSuccess(res);
  return unwrap(res.body) as Mix;
}
