import {
  postAs,
  getAs,
  patchWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  transitionApplication,
  transitionCommitment,
  countersignCommitment,
  rescindCommitment,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  updateEvent,
  updateSponsor,
  createClaim,
  finalizeClaim,
  voidClaim,
  transitionClaim,
  createGoldSilverPackages,
  createActiveCommitmentVettedGold,
  createPendingCommitmentProspectGold,
  createSuspendedCommitmentWatchlistGold,
  createActiveWithFinalizedLeads,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 5: Commitment Lifecycle & Revocation Tests', () => {

  test('COMMIT_001: GET commitment shows status=ACTIVE and benefits_left summary', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('ACTIVE');
    expect(commitment.benefits_left).toBeDefined();
    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
    expect(commitment.benefits_left.STAGE_MINUTES).toBe(30);
    expect(commitment.benefits_left.SPOTLIGHT).toBe(1);
  });

  test('COMMIT_002: COUNTERSIGN on PENDING_COUNTERSIGN commitment makes it ACTIVE', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('PENDING_COUNTERSIGN');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_003: Double COUNTERSIGN on already ACTIVE commitment fails with ERR_INVALID_STATE', async () => {

    const fixture = await createPendingCommitmentProspectGold();
    await countersignCommitment(fixture.event.id, fixture.commitment.id);

    const commitmentActive = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentActive.status).toBe('ACTIVE');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_004: COUNTERSIGN on SUSPENDED commitment makes it ACTIVE', async () => {

    const fixture = await createSuspendedCommitmentWatchlistGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('SUSPENDED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_005: RESCIND on SUSPENDED commitment releases slot', async () => {

    const fixture = await createSuspendedCommitmentWatchlistGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('SUSPENDED');
    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_006: RESCIND on commitment with FINALIZED claims fails with ERR_HAS_FINALIZED_CLAIMS', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 1,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitmentWithClaim = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentWithClaim.claims.some(c => c.id === claim.id && c.status === 'FINALIZED')).toBe(true);

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    await expectErrorCode(res, ERROR_CODES.HAS_FINALIZED_CLAIMS);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_007: VOID on FINALIZED claim restores benefits_left', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(70);

    const finalizedClaim = commitmentBefore.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id, 'VOID');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('COMMIT_008: RESCIND allowed after voiding all FINALIZED claims', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitmentBefore.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();
    await voidClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id);

    const commitmentAfterVoid = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterVoid.claims.find(c => c.id === finalizedClaim!.id)?.status).toBe('VOIDED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_009: run_ops does not revoke PENDING commitment before deadline, then revokes at deadline', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('PENDING_COUNTERSIGN');
    expect(commitmentBefore.activation_deadline_on_ops).toBeDefined();
    const deadline = commitmentBefore.activation_deadline_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < deadline - 1) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    expect(event.ops_run_index).toBe(deadline - 1);
    const commitmentPreDeadline = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentPreDeadline.status).toBe('PENDING_COUNTERSIGN');

    const res = await runOps(fixture.event.id);
    expectSuccess(res);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.ops_run_index).toBe(deadline);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('COMMIT_010: run_ops revokes PENDING commitment when deadline reached', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.activation_deadline_on_ops).toBeDefined();
    const deadline = commitmentBefore.activation_deadline_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < deadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('RESCINDED');

    const hasNonVoidedClaim = commitment.claims.some(c => c.status !== 'VOIDED');
    expect(hasNonVoidedClaim).toBe(false);
  });

  test('COMMIT_011: Auto-rescind during run_ops releases slot', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    const slotsBefore = pkgBefore.slots_remaining;

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.activation_deadline_on_ops).toBeDefined();
    const deadline = commitmentBefore.activation_deadline_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < deadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBeGreaterThan(slotsBefore);
  });

  test('COMMIT_012: COUNTERSIGN blocked during LOCKDOWN', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('PENDING_COUNTERSIGN');
  });

  test('COMMIT_013: RESCIND allowed during LOCKDOWN as cleanup', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('COMMIT_014: RESCIND allowed during ARCHIVED as paperwork correction', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'ARCHIVED' },
      event.version
    );
    expectSuccess(patchRes);

    const eventArchived = await getEvent(fixture.event.id);
    expect(eventArchived.posture).toBe('ARCHIVED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('COMMIT_015: Suspending sponsor does not release slot', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );
    expectSuccess(patchRes);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('SUSPENDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBe(0);
  });

  test('COMMIT_016: RESCIND on SUSPENDED commitment releases slot', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_017: SUSPENDED commitment auto-rescinded when activation deadline reached', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');
    expect(commitmentSuspended.activation_deadline_on_ops).toBeDefined();
    const deadline = commitmentSuspended.activation_deadline_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < deadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('RESCINDED');
  });

  test('COMMIT_018: COUNTERSIGN on SUSPENDED commitment makes it ACTIVE again', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');
    expect(commitmentSuspended.activation_deadline_on_ops).toBeDefined();
    const priorDeadline = commitmentSuspended.activation_deadline_on_ops!;

    await countersignCommitment(fixture.event.id, fixture.commitment.id);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('ACTIVE');

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < priorDeadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const commitmentAfterOps = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterOps.status).toBe('ACTIVE');
  });

  test('COMMIT_019: RESCIND on ACTIVE commitment releases slot', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_020: COUNTERSIGN on ACTIVE commitment blocked during LOCKDOWN', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_021: COUNTERSIGN on already ACTIVE commitment fails with ERR_INVALID_STATE', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('COMMIT_022: Blocking PROSPECT sponsor rescinds PENDING_COUNTERSIGN commitment', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('PENDING_COUNTERSIGN');

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('RESCINDED');
  });

  test('COMMIT_023: Blocking sponsor releases slot', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_024: RESCIND on commitment with PROPOSED claim succeeds', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });

    const commitmentWithClaim = await getCommitment(fixture.event.id, fixture.commitment.id);
    const proposedClaim = commitmentWithClaim.claims.find(c => c.id === claim.id);
    expect(proposedClaim).toBeDefined();
    expect(proposedClaim!.status).toBe('PROPOSED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('COMMIT_025: Blocking sponsor voids FINALIZED claims and restores benefits', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitmentWithClaim = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitmentWithClaim.claims.find(c => c.id === claim.id);
    expect(finalizedClaim).toBeDefined();
    expect(finalizedClaim!.status).toBe('FINALIZED');
    expect(commitmentWithClaim.benefits_left.LEAD_SCANS).toBe(90);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    expectSuccess(patchRes);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const voidedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(voidedClaim).toBeDefined();
    expect(voidedClaim!.status).toBe('VOIDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

});
