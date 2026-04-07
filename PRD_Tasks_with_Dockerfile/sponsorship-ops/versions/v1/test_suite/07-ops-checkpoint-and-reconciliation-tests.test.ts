import {
  postAs,
  patchWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
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
  transitionPackage,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  createClaim,
  finalizeClaim,
  createGoldSilverPackages,
  createSubmittedHeldApplicationVettedGold,
  createWaitlistTwoAppsGold,
  createPendingCommitmentProspectGold,
  createActiveWithFinalizedSpotlight,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 7: Ops Checkpoint and Reconciliation Tests', () => {

  test('OPS_001: run_ops before hold_expires_on_ops does not expire hold', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.status).toBe('SUBMITTED');
    expect(appBefore.hold_status).toBe('HELD');
    expect(appBefore.hold_expires_on_ops).toBeDefined();
    const expiresAt = appBefore.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < expiresAt - 2) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const opsIndexBefore = event.ops_run_index;

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(opsIndexBefore + 1);
    expect(event.ops_run_index).toBeLessThan(expiresAt);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('SUBMITTED');
    expect(app.hold_status).toBe('HELD');
  });

  test('OPS_002: run_ops expires hold when hold_expires_on_ops is reached', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.hold_expires_on_ops).toBeDefined();
    const expiresAt = appBefore.hold_expires_on_ops!;

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    const slotsBefore = pkgBefore.slots_remaining;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < expiresAt) {
      const res = await runOps(fixture.event.id);
      expectSuccess(res);
      event = await getEvent(fixture.event.id);
    }

    expect(event.ops_run_index).toBe(expiresAt);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('EXPIRED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(slotsBefore + 1);
  });

  test('OPS_003: waitlist promotion after hold expiry assigns new hold with future hold_expires_on_ops', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app2Before.hold_status).toBe('WAITLISTED');
    expect(app1Before.hold_expires_on_ops).toBeDefined();
    const a1ExpiresAt = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < a1ExpiresAt) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const app1After = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1After.status).toBe('EXPIRED');

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(app2.status).toBe('SUBMITTED');
    expect(app2.hold_status).toBe('HELD');
    expect(app2.hold_expires_on_ops).toBeDefined();
    expect(app2.hold_expires_on_ops).toBeGreaterThan(event.ops_run_index);
  });

  test('OPS_004: promoted hold remains HELD before its hold_expires_on_ops', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_expires_on_ops).toBeDefined();
    const a1ExpiresAt = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < a1ExpiresAt) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const app2AfterPromotion = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2AfterPromotion.hold_status).toBe('HELD');
    expect(app2AfterPromotion.hold_expires_on_ops).toBeDefined();
    const a2ExpiresAt = app2AfterPromotion.hold_expires_on_ops!;

    expect(a2ExpiresAt).toBeGreaterThan(event.ops_run_index);

    if (event.ops_run_index + 1 < a2ExpiresAt) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
      expect(event.ops_run_index).toBeLessThan(a2ExpiresAt);

      const app2 = await getApplication(fixture.event.id, fixture.application2.id);

      expect(app2.status).toBe('SUBMITTED');
      expect(app2.hold_status).toBe('HELD');
    } else {

      expect(app2AfterPromotion.status).toBe('SUBMITTED');
      expect(app2AfterPromotion.hold_status).toBe('HELD');
    }
  });

  test('OPS_005: promoted hold expires when hold_expires_on_ops is reached', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_expires_on_ops).toBeDefined();
    const a1ExpiresAt = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < a1ExpiresAt) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const app2AfterPromotion = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2AfterPromotion.hold_status).toBe('HELD');
    expect(app2AfterPromotion.hold_expires_on_ops).toBeDefined();
    const a2ExpiresAt = app2AfterPromotion.hold_expires_on_ops!;

    while (event.ops_run_index < a2ExpiresAt) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    expect(event.ops_run_index).toBe(a2ExpiresAt);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(app2.status).toBe('EXPIRED');
  });

  test('OPS_006: non-active commitment is rescinded when activation_deadline_on_ops is reached', async () => {

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

    const commitmentBeforeDeadline = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBeforeDeadline.status).toBe('PENDING_COUNTERSIGN');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(deadline);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('OPS_007: countersigned commitment is not revoked by run_ops', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    await runOpsSuccess(fixture.event.id);

    await countersignCommitment(fixture.event.id, fixture.commitment.id);

    const commitmentAfterCountersign = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterCountersign.status).toBe('ACTIVE');

    let event = await getEvent(fixture.event.id);
    const opsIndexBefore = event.ops_run_index;

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(opsIndexBefore + 1);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('OPS_008: abandoned commitment with finalized spotlight claim gets rescinded and spotlight slot released', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const eventBefore = await getEvent(fixture.event.id);
    const spotlightBefore = eventBefore.spotlight_slots_remaining;
    const commitmentWithClaim = await getCommitment(fixture.event.id, fixture.commitment.id);
    const spotlightClaim = commitmentWithClaim.claims.find(c => c.benefit_kind === 'SPOTLIGHT');
    expect(spotlightClaim).toBeDefined();
    expect(spotlightClaim!.status).toBe('FINALIZED');

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );
    expectSuccess(patchRes);

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

    const voidedSpotlightClaim = commitment.claims.find(c => c.benefit_kind === 'SPOTLIGHT');
    expect(voidedSpotlightClaim).toBeDefined();
    expect(voidedSpotlightClaim!.status).toBe('VOIDED');

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(spotlightBefore + 1);
  });

  test('OPS_009: blocking sponsor withdraws application and run_ops promotes waitlisted app', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const sponsor1 = await getSponsor(fixture.event.id, fixture.sponsor1.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      sponsor1.version
    );
    expectSuccess(patchRes);

    const app1AfterBlock = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1AfterBlock.status).toBe('WITHDRAWN');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('SUBMITTED');
    expect(app2.hold_status).toBe('HELD');
  });

  test('OPS_010: withdrawn waitlisted app does not get promoted', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const withdrawRes = await transitionApplication(fixture.event.id, fixture.application2.id, 'WITHDRAW');
    expectSuccess(withdrawRes);

    const app2AfterWithdraw = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2AfterWithdraw.status).toBe('WITHDRAWN');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('SUBMITTED');
    expect(app1.hold_status).toBe('HELD');

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('WITHDRAWN');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('OPS_011: waitlist does not advance while package is RETIRED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const retireRes = await transitionPackage(fixture.event.id, fixture.gold.id, 'RETIRE');
    expectSuccess(retireRes);

    const pkgAfterRetire = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgAfterRetire.status).toBe('RETIRED');

    const app1AfterRetire = await getApplication(fixture.event.id, fixture.application1.id);
    const app2AfterRetire = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1AfterRetire.status).toBe('SUBMITTED');
    expect(app1AfterRetire.hold_status).toBe('WAITLISTED');
    expect(app2AfterRetire.status).toBe('SUBMITTED');
    expect(app2AfterRetire.hold_status).toBe('WAITLISTED');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(app1.status).toBe('SUBMITTED');
    expect(app1.hold_status).toBe('WAITLISTED');
    expect(app2.status).toBe('SUBMITTED');
    expect(app2.hold_status).toBe('WAITLISTED');
  });

});
