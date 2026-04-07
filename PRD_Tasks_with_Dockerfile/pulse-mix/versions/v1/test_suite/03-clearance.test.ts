import {
  postAs,
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
  suspendClearance,
  revokeClearance,
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
  Clearance,
  Mix,
  Studio
} from '../../../test-helpers/resources';
import { CONSTANTS } from '../../../test-helpers/constants';

describe('Clearance Tests', () => {

  test('CLEAR_001: POST /clearances creates clearance with status PENDING', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const idemKey = idempotencyKey('c1');
    const res = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'FULL'
    }, 'legal', idemKey);

    expectSuccess(res);
    const clearance = unwrap(res.body) as Clearance;

    expect(clearance.status).toBe('PENDING');
    expect(clearance.policy).toBe('FULL');
    expect(clearance.last_granted_in_cycle).toBeNull();
    expect(clearance.asset_id).toBe(asset.id);
  });

  test('CLEAR_002: creating second clearance for same asset fails ERR_CLEARANCE_ALREADY_EXISTS', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });

    const idemKey = idempotencyKey('c2');
    const res = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'FULL'
    }, 'legal', idemKey);

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_ALREADY_EXISTS);
  });

  test('CLEAR_003: granting PENDING clearance sets status to GRANTED and stamps last_granted_in_cycle', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    expect(clearance.status).toBe('PENDING');
    expect(studio.cycle_index).toBe(1);

    const idemKey = idempotencyKey('c3');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'legal', idemKey);

    expectSuccess(res);
    const granted = unwrap(res.body) as Clearance;

    expect(granted.status).toBe('GRANTED');
    expect(granted.last_granted_in_cycle).toBe(1);
  });

  test('CLEAR_004: curator cannot grant clearance - ERR_ROLE_FORBIDDEN', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });

    const idemKey = idempotencyKey('c4');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.ROLE_FORBIDDEN);
  });

  test('CLEAR_005: granting clearance blocked when posture is HALT - ERR_POSTURE_BLOCKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });

    const disputeAsset = await createAsset(studio.id, { duration_sec: 120 });
    await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: disputeAsset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id);
    expect(studioState.posture).toBe('HALT');

    const idemKey = idempotencyKey('c5');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'legal', idemKey);

    expectErrorCode(res, CONSTANTS.errors.POSTURE_BLOCKED);
  });

  test('CLEAR_006: suspending GRANTED clearance sets status to SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);

    const idemKey = idempotencyKey('c6');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/suspend`, {}, 'legal', idemKey);

    expectSuccess(res);
    const suspended = unwrap(res.body) as Clearance;

    expect(suspended.status).toBe('SUSPENDED');
  });

  test('CLEAR_007: granting SUSPENDED clearance reactivates it and updates last_granted_in_cycle', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);
    await suspendClearance(studio.id, clearance.id);

    await advanceCycle(studio.id);
    const studioAfterAdvance = await getStudio(studio.id);
    expect(studioAfterAdvance.cycle_index).toBe(2);

    const idemKey = idempotencyKey('c7');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'legal', idemKey);

    expectSuccess(res);
    const granted = unwrap(res.body) as Clearance;

    expect(granted.status).toBe('GRANTED');
    expect(granted.last_granted_in_cycle).toBe(2);
  });

  test('CLEAR_008: revoking GRANTED clearance sets status to REVOKED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);

    const idemKey = idempotencyKey('c8');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/revoke`, {}, 'legal', idemKey);

    expectSuccess(res);
    const revoked = unwrap(res.body) as Clearance;

    expect(revoked.status).toBe('REVOKED');
  });

  test('CLEAR_009: granting REVOKED clearance fails ERR_INVALID_STATE', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    await grantClearance(studio.id, clearance.id);
    await revokeClearance(studio.id, clearance.id);

    const idemKey = idempotencyKey('c9');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'legal', idemKey);

    expectErrorCode(res, CONSTANTS.errors.INVALID_STATE);
  });

  test('CLEAR_010: suspending clearance bounces SUBMITTED mix to DRAFT and releases reserved tokens', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);
    const submittedMix = await submitMix(studio.id, mix.id);
    expect(submittedMix.status).toBe('SUBMITTED');

    const studioBefore = await getStudio(studio.id);
    const reservedBefore = studioBefore.token_reserved;
    expect(reservedBefore).toBeGreaterThan(0);

    const idemKey = idempotencyKey('c10');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/suspend`, {}, 'legal', idemKey);

    expectSuccess(res);

    const submitRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('c10-submit')
    );
    expectErrorCode(submitRes, CONSTANTS.errors.CLEARANCE_SUSPENDED);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_reserved).toBeLessThan(reservedBefore);
  });

  test('CLEAR_011: suspending clearance freezes PUBLISHED mix, tokens remain committed', async () => {

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

    const idemKey = idempotencyKey('c11');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/suspend`, {}, 'legal', idemKey);

    expectSuccess(res);

    const studioAfterSuspend = await getStudio(studio.id);
    expect(studioAfterSuspend.token_committed).toBe(committedBefore);

    const legalUnpublish = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'legal',
      idempotencyKey('c11-legal-unpublish')
    );
    expectSuccess(legalUnpublish);

    const studioAfterUnpublish = await getStudio(studio.id);
    expect(studioAfterUnpublish.token_committed).toBe(0);
  });

  test('CLEAR_012: revoking clearance archives PUBLISHED mix and releases committed tokens', async () => {

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

    const idemKey = idempotencyKey('c12');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/revoke`, {}, 'legal', idemKey);

    expectSuccess(res);

    const unpublishRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/unpublish`,
      {},
      'manager',
      idempotencyKey('c12-unpublish')
    );
    expectErrorCode(unpublishRes, CONSTANTS.errors.INVALID_STATE);

    const studioAfter = await getStudio(studio.id);
    expect(studioAfter.token_committed).toBe(0);
  });

  test('CLEAR_013: submitting mix with SUSPENDED clearance fails ERR_CLEARANCE_SUSPENDED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    await suspendClearance(studio.id, clearance.id);

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const idemKey = idempotencyKey('c13');
    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_SUSPENDED);
  });

  test('CLEAR_014: submitting PUBLIC mix with PROMO clearance fails ERR_CLEARANCE_POLICY_MISMATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'NORMAL' }
    ], mix.version);

    const idemKey = idempotencyKey('c14');
    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_POLICY_MISMATCH);
  });

  test('CLEAR_015: submitting INTERNAL mix with PROMO asset in SPOTLIGHT fails', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset } = await createActiveAssetWithClearance(studio.id, 120, 'PROMO');

    const mix = await createMix(studio.id, { kind: 'INTERNAL' });
    await setMixEntries(studio.id, mix.id, [
      { asset_id: asset.id, slot: 'SPOTLIGHT' }
    ], mix.version);

    const idemKey = idempotencyKey('c15');
    const res = await postAs(`/studios/${studio.id}/mixes/${mix.id}/submit`, {}, 'curator', idemKey);

    expectErrorCodeOneOf(res, [
      CONSTANTS.errors.SPOTLIGHT_NOT_ALLOWED,
      CONSTANTS.errors.CLEARANCE_POLICY_MISMATCH
    ]);
  });

  test('CLEAR_016: idempotency replay returns exact stored clearance response', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const idemKey = idempotencyKey('cx');

    const res1 = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'FULL'
    }, 'legal', idemKey);
    expectSuccess(res1);

    const res2 = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'FULL'
    }, 'legal', idemKey);

    expectSuccess(res2);
    expect(res2.body).toEqual(res1.body);
  });

  test('CLEAR_017: idempotency replay with different policy fails ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });

    const idemKey = idempotencyKey('cy');

    const res1 = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'FULL'
    }, 'legal', idemKey);
    expectSuccess(res1);

    const res2 = await postAs(`/studios/${studio.id}/clearances`, {
      asset_id: asset.id,
      policy: 'PROMO'
    }, 'legal', idemKey);

    expectErrorCode(res2, CONSTANTS.errors.IDEMPOTENCY_REPLAY_MISMATCH);
  });

  test('CLEAR_018: HIGH dispute on asset causes HALT posture and suspends clearance', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'HIGH'
    });

    const studioState = await getStudio(studio.id, 'legal');
    expect(studioState.posture).toBe('HALT');

    await resolveDispute(studio.id, dispute.id, 'VOID');
    const studioAfterVoid = await getStudio(studio.id, 'legal');
    expect(studioAfterVoid.posture).toBe('OPEN');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    const mixWithEntries = await setMixEntries(studio.id, mix.id, [{ asset_id: asset.id, slot: 'NORMAL' }], mix.version);
    const submitRes = await postAs(
      `/studios/${studio.id}/mixes/${mixWithEntries.id}/submit`,
      {},
      'curator',
      idempotencyKey('c18-submit')
    );
    expectErrorCode(submitRes, CONSTANTS.errors.CLEARANCE_SUSPENDED);
  });

  test('CLEAR_019: activating asset with PENDING clearance fails ERR_CLEARANCE_REQUIRED', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const asset = await createAsset(studio.id, { duration_sec: 120 });
    const clearance = await createClearance(studio.id, { asset_id: asset.id, policy: 'FULL' });
    expect(clearance.status).toBe('PENDING');

    const idemKey = idempotencyKey('c19');
    const res = await postAs(`/studios/${studio.id}/assets/${asset.id}/activate`, {}, 'curator', idemKey);

    expectErrorCode(res, CONSTANTS.errors.CLEARANCE_REQUIRED);
  });

  test('CLEAR_020: after dispute dismissed, legal can re-grant suspended clearance', async () => {

    const studio = await createStudio({ token_budget: 20 });
    const { asset, clearance } = await createActiveAssetWithClearance(studio.id, 120, 'FULL');

    const dispute = await createDispute(studio.id, {
      target_type: 'ASSET',
      target_id: asset.id,
      severity: 'LOW'
    });

    await resolveDispute(studio.id, dispute.id, 'DISMISSED');

    const mix = await createMix(studio.id, { kind: 'PUBLIC' });
    await setMixEntries(studio.id, mix.id, [{ asset_id: asset.id, slot: 'NORMAL' }], mix.version);

    const submitRes = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('c20-submit')
    );
    expectErrorCode(submitRes, CONSTANTS.errors.CLEARANCE_SUSPENDED);

    const studioState = await getStudio(studio.id);
    const currentCycle = studioState.cycle_index;

    const idemKey = idempotencyKey('c20');
    const res = await postAs(`/studios/${studio.id}/clearances/${clearance.id}/grant`, {}, 'legal', idemKey);

    expectSuccess(res);
    const granted = unwrap(res.body) as Clearance;

    expect(granted.status).toBe('GRANTED');
    expect(granted.last_granted_in_cycle).toBe(currentCycle);

    const submitRes2 = await postAs(
      `/studios/${studio.id}/mixes/${mix.id}/submit`,
      {},
      'curator',
      idempotencyKey('c20-submit2')
    );
    expectSuccess(submitRes2);
  });

});
