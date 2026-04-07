import {
  postAs,
  postAsNoIdem,
  getAs,
  putAs,
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
  resolveDispute,
  createActiveAssetWithClearance,
  uniqueId,
  unwrap,
  Mix,
  Studio,
  Asset,
  Clearance,
  Dispute
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

describe('Dispute Tests', () => {

  test('DISP_001: LOW asset dispute quarantines asset and suspends clearance', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    expect(asset.status).toBe('ACTIVE');
    expect(clearance.status).toBe('GRANTED');

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp001'));

    expectSuccess(res);
    const dispute = unwrap(res.body) as Dispute;

    expect(dispute.status).toBe('OPEN');
    expect(dispute.severity).toBe('LOW');
    expect(dispute.target_type).toBe('ASSET');
    expect(dispute.target_id).toBe(asset.id);

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'asset', asset.id)?.status).toBe('QUARANTINED');
    expect(findEffect(effects, 'clearance', clearance.id)?.status).toBe('SUSPENDED');
  });

  test('DISP_002: LOW asset dispute bounces SUBMITTED mix to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    const submittedMix = await submitMix(studio.id, mix.id);
    expect(submittedMix.status).toBe('SUBMITTED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp002'));

    expectSuccess(res);

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('DRAFT');
    expect(findEffect(effects, 'asset', asset.id)?.status).toBe('QUARANTINED');
    expect(findEffect(effects, 'clearance', clearance.id)?.status).toBe('SUSPENDED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('DISP_003: LOW asset dispute freezes PUBLISHED mix, keeps tokens committed', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const studioBefore = await getStudio(studio.id);
    const committedBefore = studioBefore.token_committed;
    expect(committedBefore).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp003'));

    expectSuccess(res);

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('FROZEN');
    expect(findEffect(effects, 'asset', asset.id)?.status).toBe('QUARANTINED');
    expect(findEffect(effects, 'clearance', clearance.id)?.status).toBe('SUSPENDED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(committedBefore);
  });

  test('DISP_004: HIGH asset dispute archives PUBLISHED mix, causes HALT posture', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    const publishedMix = await publishMix(studio.id, mix.id);
    expect(publishedMix.status).toBe('PUBLISHED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    }, 'legal', idempotencyKey('disp004'));

    expectSuccess(res);
    const dispute = unwrap(res.body) as Dispute;

    expect(dispute.status).toBe('ESCALATED');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('ARCHIVED');
    expect(findEffect(effects, 'asset', asset.id)?.status).toBe('QUARANTINED');
    expect(findEffect(effects, 'clearance', clearance.id)?.status).toBe('SUSPENDED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('HALT');
    expect(studioAfter.token_committed).toBe(0);
  });

  test('DISP_005: LOW mix dispute bounces SUBMITTED mix to DRAFT', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    const submittedMix = await submitMix(studio.id, mix.id);
    expect(submittedMix.status).toBe('SUBMITTED');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_reserved).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'MIX',
      target_id: mix.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp005'));

    expectSuccess(res);
    const dispute = unwrap(res.body) as Dispute;

    expect(dispute.status).toBe('OPEN');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('DRAFT');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBe(0);
  });

  test('DISP_006: LOW mix dispute freezes PUBLISHED mix, keeps tokens committed', async () => {

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

    const studioBefore = await getStudio(studio.id);
    const committedBefore = studioBefore.token_committed;
    expect(committedBefore).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'MIX',
      target_id: mix.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp006'));

    expectSuccess(res);

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('FROZEN');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(committedBefore);
  });

  test('DISP_007: HIGH mix dispute archives PUBLISHED mix and causes HALT', async () => {

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

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'MIX',
      target_id: mix.id,
      severity: 'HIGH'
    }, 'legal', idempotencyKey('disp007'));

    expectSuccess(res);
    const dispute = unwrap(res.body) as Dispute;

    expect(dispute.status).toBe('ESCALATED');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('ARCHIVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('HALT');
    expect(studioAfter.token_committed).toBe(0);
  });

  test('DISP_008: second OPEN dispute causes REVIEW posture', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset1 = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset1.id,
      severity: 'LOW'
    });

    const studioAfter1 = await getStudio(studio.id);
    expect(studioAfter1.posture).toBe('OPEN');

    const asset2 = await createAsset(studio.id, { duration_sec: 120 });

    const res = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset2.id,
      severity: 'LOW'
    }, 'legal', idempotencyKey('disp008'));

    expectSuccess(res);

    const studioAfter2 = await getStudio(studio.id);
    expect(studioAfter2.posture).toBe('REVIEW');
  });

  test('DISP_009: resolving one of two OPEN disputes changes posture from REVIEW to OPEN', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset1 = await createAsset(studio.id, { duration_sec: 120 });
    const asset2 = await createAsset(studio.id, { duration_sec: 120 });

    const dispute1 = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset1.id,
      severity: 'LOW'
    });
    const dispute2 = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset2.id,
      severity: 'LOW'
    });

    const studioReview = await getStudio(studio.id);
    expect(studioReview.posture).toBe('REVIEW');

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute1.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal',
      idempotencyKey('disp009')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('RESOLVED');
    expect(resolvedDispute.resolution).toBe('DISMISSED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('OPEN');
  });

  test('DISP_010: resolving ESCALATED dispute changes posture from HALT to OPEN', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    });

    expect(dispute.status).toBe('ESCALATED');

    const studioHalt = await getStudio(studio.id);
    expect(studioHalt.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal',
      idempotencyKey('disp010')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('RESOLVED');
    expect(resolvedDispute.resolution).toBe('DISMISSED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('OPEN');
  });

  test('DISP_011: dismissing dispute removes quarantine if last dispute, clearance stays SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const disputeRes = await postAs(
      `/studios/${studio.id}/disputes`,
      { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' },
      'legal',
      idempotencyKey('disp011-create')
    );
    expectSuccess(disputeRes);
    const dispute = unwrap(disputeRes.body) as Dispute;

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal',
      idempotencyKey('disp011')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('RESOLVED');
    expect(resolvedDispute.resolution).toBe('DISMISSED');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'asset', asset.id)?.status).not.toBe('QUARANTINED');

    expect(findEffect(effects, 'clearance', clearance.id)?.status).not.toBe('GRANTED');
  });

  test('DISP_012: VOIDing dispute removes quarantine if last dispute, clearance stays SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const disputeRes = await postAs(
      `/studios/${studio.id}/disputes`,
      { target_type: 'ASSET', target_id: asset.id, severity: 'LOW' },
      'legal',
      idempotencyKey('disp012-create')
    );
    expectSuccess(disputeRes);
    const dispute = unwrap(disputeRes.body) as Dispute;

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'VOID' },
      'legal',
      idempotencyKey('disp012')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('VOID');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'asset', asset.id)?.status).not.toBe('QUARANTINED');

    expect(findEffect(effects, 'clearance', clearance.id)?.status).not.toBe('GRANTED');
  });

  test('DISP_013: UPHELD asset dispute retires asset, revokes clearance, archives mixes', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'UPHELD' },
      'legal',
      idempotencyKey('disp013')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('RESOLVED');
    expect(resolvedDispute.resolution).toBe('UPHELD');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'asset', asset.id)?.status).toBe('RETIRED');
    expect(findEffect(effects, 'clearance', clearance.id)?.status).toBe('REVOKED');
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('ARCHIVED');
  });

  test('DISP_014: UPHELD mix dispute archives the mix and releases tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const disputeRes = await postAs(
      `/studios/${studio.id}/disputes`,
      { target_type: 'MIX', target_id: mix.id, severity: 'LOW' },
      'legal',
      idempotencyKey('disp014-create')
    );
    expectSuccess(disputeRes);
    const dispute = unwrap(disputeRes.body) as Dispute;
    expect(findEffect(getEffects(disputeRes.body), 'mix', mix.id)?.status).toBe('FROZEN');

    const studioBefore = await getStudio(studio.id);
    expect(studioBefore.token_committed).toBeGreaterThan(0);

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'UPHELD' },
      'legal',
      idempotencyKey('disp014')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('RESOLVED');
    expect(resolvedDispute.resolution).toBe('UPHELD');

    const effects = getEffects(res.body);
    expect(findEffect(effects, 'mix', mix.id)?.status).toBe('ARCHIVED');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('DISP_015: manager cannot resolve disputes - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await postAs(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'manager',
      idempotencyKey('disp015')
    );

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('DISP_016: resolve without Idempotency-Key fails ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    const res = await postAsNoIdem(
      `/studios/${studio.id}/disputes/${dispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal'
    );

    expectErrorCode(res, CONSTANTS.errors.MISSING_IDEMPOTENCY_KEY);
  });

  test('DISP_017: idempotency replay on dispute creation returns exact stored response', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const idemKey = idempotencyKey('dd1');

    const res1 = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idemKey);
    expectSuccess(res1);
    const originalDispute = unwrap(res1.body) as Dispute;

    const res2 = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idemKey);

    expectSuccess(res2);
    expect(res1.status).toBe(res2.status);

    const replayedDispute = unwrap(res2.body) as Dispute;

    expect(replayedDispute.id).toBe(originalDispute.id);
    expect(replayedDispute.version).toBe(originalDispute.version);
    expect(replayedDispute.status).toBe(originalDispute.status);
    expect(replayedDispute.severity).toBe(originalDispute.severity);
    expect(replayedDispute.target_type).toBe(originalDispute.target_type);
    expect(replayedDispute.target_id).toBe(originalDispute.target_id);
  });

  test('DISP_018: idempotency replay with different severity fails ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const idemKey = idempotencyKey('dd2');

    const res1 = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    }, 'legal', idemKey);
    expectSuccess(res1);

    const res2 = await postAs(`/studios/${studio.id}/disputes`, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    }, 'legal', idemKey);

    expectErrorCode(res2, CONSTANTS.errors.IDEMPOTENCY_REPLAY_MISMATCH);
  });

  test('DISP_019: activation blocked during HALT posture - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const assetB = await createAsset(studio.id, { duration_sec: 120 });
    const clearanceB = await createClearance(studio.id, {
      asset_id: assetB.id,
      policy: 'FULL'
    });
    await grantClearance(studio.id, clearanceB.id);

    const assetA = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: assetA.id,
      severity: 'HIGH'
    });

    const studioHalt = await getStudio(studio.id);
    expect(studioHalt.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/assets/${assetB.id}/activate`,
      {},
      'curator',
      idempotencyKey('disp019')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('DISP_020: evidence mix can publish even in HALT posture', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    });

    const studioHalt = await getStudio(studio.id);
    expect(studioHalt.posture).toBe('HALT');

    const evidenceMix = await createMix(studio.id, { kind: 'EVIDENCE' }, 'legal');
    await setMixEntries(studio.id, evidenceMix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], evidenceMix.version, 'legal');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${evidenceMix.id}/publish`,
      {},
      'legal',
      idempotencyKey('disp020')
    );

    expectSuccess(res);
    const publishedMix = unwrap(res.body) as Mix;

    expect(publishedMix.status).toBe('FROZEN');
    expect(publishedMix.token_cost).toBe(0);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('DISP_021: submitting mix with SUSPENDED clearance fails ERR_CLEARANCE_SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    await resolveDispute(studio.id, dispute.id, 'DISMISSED');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('disp021')
    );

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_SUSPENDED);
  });

  test('DISP_022: cannot edit entries of FROZEN mix - ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const { asset: asset2 } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);
    await publishMix(studio.id, mix.id);

    const freezeRes = await postAs(
      `/studios/${studio.id}/disputes`,
      { target_type: 'MIX', target_id: mix.id, severity: 'LOW' },
      'legal',
      idempotencyKey('disp022-freeze')
    );
    expectSuccess(freezeRes);
    const freezeEffects = getEffects(freezeRes.body);
    const mixEffect = findEffect(freezeEffects, 'mix', mix.id);
    expect(mixEffect?.status).toBe('FROZEN');

    const res = await putAs(
      `/studios/${studio.id}/mixes/${mix.id}/entries`,
      { entries: [{ asset_id: asset2.id, slot: 'NORMAL' }] },
      mixEffect.version,
      'curator'
    );

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('DISP_023: PUBLIC publish blocked during REVIEW posture - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');
    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    await submitMix(studio.id, mix.id);
    await approveMix(studio.id, mix.id);

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

    const studioReview = await getStudio(studio.id);
    expect(studioReview.posture).toBe('REVIEW');

    const res = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/publish`,
      {},
      'manager',
      idempotencyKey('disp023')
    );

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('DISP_024: resolving ESCALATED dispute with 2+ OPEN remaining changes posture to REVIEW', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset1 = await createAsset(studio.id, { duration_sec: 120 });
    const asset2 = await createAsset(studio.id, { duration_sec: 120 });
    const asset3 = await createAsset(studio.id, { duration_sec: 120 });

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

    const escalatedDispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset3.id,
      severity: 'HIGH'
    });

    const studioHalt = await getStudio(studio.id);
    expect(studioHalt.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/disputes/${escalatedDispute.id}/resolve`,
      { resolution: 'DISMISSED' },
      'legal',
      idempotencyKey('disp024')
    );

    expectSuccess(res);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('REVIEW');
  });

  test('DISP_025: VOIDing ESCALATED dispute with 1 OPEN remaining changes posture to OPEN', async () => {

    const studio = await createStudio({ token_budget: 20 });

    const asset1 = await createAsset(studio.id, { duration_sec: 120 });
    const asset2 = await createAsset(studio.id, { duration_sec: 120 });

    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset1.id,
      severity: 'LOW'
    });

    const escalatedDispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset2.id,
      severity: 'HIGH'
    });

    const studioHalt = await getStudio(studio.id);
    expect(studioHalt.posture).toBe('HALT');

    const res = await postAs(
      `/studios/${studio.id}/disputes/${escalatedDispute.id}/resolve`,
      { resolution: 'VOID' },
      'legal',
      idempotencyKey('disp025')
    );

    expectSuccess(res);
    const resolvedDispute = unwrap(res.body) as Dispute;

    expect(resolvedDispute.status).toBe('VOID');

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.posture).toBe('OPEN');
  });

});
