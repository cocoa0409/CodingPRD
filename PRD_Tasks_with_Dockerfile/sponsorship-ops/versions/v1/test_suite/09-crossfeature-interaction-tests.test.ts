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
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  updateSponsor,
  createGoldSilverPackages,
  createWaitlistTwoAppsGold,
  createActiveCommitmentVettedGold,
  createActiveWithFinalizedSpotlight,
  createClaim,
  finalizeClaim,
  transitionPackage,
  reactivatePackage,
  retirePackage,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 9: Cross-Feature Interaction Tests', () => {

  test('CROSS_001: Approving A1 then run_ops leaves A2 WAITLISTED (commitment consumes slot)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const approveRes = await transitionApplication(fixture.event.id, fixture.application1.id, 'APPROVE');
    expectSuccess(approveRes);

    const app1Approved = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Approved.status).toBe('APPROVED');
    expect(app1Approved.commitment_id).toBeDefined();

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('WAITLISTED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('CROSS_002: After rejecting A1, approving A2 fails until run_ops (ERR_NO_ACTIVE_HOLD)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const rejectRes = await transitionApplication(fixture.event.id, fixture.application1.id, 'REJECT');
    expectSuccess(rejectRes);

    const app1Rejected = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Rejected.status).toBe('REJECTED');

    const app2Still = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Still.hold_status).toBe('WAITLISTED');

    const res = await transitionApplication(fixture.event.id, fixture.application2.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.NO_ACTIVE_HOLD);

    const app2After = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2After.status).toBe('SUBMITTED');
    expect(app2After.hold_status).toBe('WAITLISTED');
  });

  test('CROSS_003: After rejecting A1 and run_ops, A2 becomes HELD (promotion)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const rejectRes = await transitionApplication(fixture.event.id, fixture.application1.id, 'REJECT');
    expectSuccess(rejectRes);

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');

    expect(app2.hold_expires_on_ops).toBeDefined();
  });

  test('CROSS_004: Moving sponsor to WATCHLIST suspends commitment even with finalized claims', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentInitial = await getCommitment(fixture.event.id, fixture.commitment.id);
    const startingLeadScans = commitmentInitial.benefits_left.LEAD_SCANS ?? 0;

    const claimQuantity = 10;
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: claimQuantity,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const expectedAfterClaim = startingLeadScans - claimQuantity;
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(expectedAfterClaim);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);

    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('SUSPENDED');

    expect(commitment.benefits_left.LEAD_SCANS).toBe(expectedAfterClaim);

    const sponsorAfter = await getSponsor(fixture.event.id, fixture.sponsor.id);
    expect(sponsorAfter.status).toBe('WATCHLIST');
  });

  test('CROSS_005: Rescinding suspended commitment with finalized claims fails (polite rescind)', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const watchlistRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );
    expectSuccess(watchlistRes);

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'RESCIND');

    await expectErrorCode(res, ERROR_CODES.HAS_FINALIZED_CLAIMS);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('SUSPENDED');
  });

  test('CROSS_006: Auto-revoke after deadline frees slot (run_ops 3 times)', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const packageBenefits = fixture.gold.included_benefits.find(b => b.benefit_kind === 'LEAD_SCANS');
    const originalLeadScans = packageBenefits?.quantity ?? 100;

    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const watchlistRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );
    expectSuccess(watchlistRes);

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');
    expect(commitmentSuspended.activation_deadline_on_ops).toBeDefined();

    const deadline = commitmentSuspended.activation_deadline_on_ops!;
    let event = await getEvent(fixture.event.id);

    while (event.ops_run_index < deadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBe(1);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const voidedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(voidedClaim).toBeDefined();
    expect(voidedClaim!.status).toBe('VOIDED');

    expect(commitment.benefits_left.LEAD_SCANS).toBe(originalLeadScans);
  });

  test('CROSS_007: WATCHLIST suspends commitment with finalized spotlight; spotlight_slots_remaining unchanged', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const eventBefore = await getEvent(fixture.event.id);
    const spotlightSlotsBefore = eventBefore.spotlight_slots_remaining;

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);

    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('SUSPENDED');

    const spotlightClaim = commitment.claims.find(c => c.benefit_kind === 'SPOTLIGHT');
    expect(spotlightClaim).toBeDefined();
    expect(spotlightClaim!.status).toBe('FINALIZED');

    const event = await getEvent(fixture.event.id);
    expect(event.spotlight_slots_remaining).toBe(spotlightSlotsBefore);
  });

  test('CROSS_008: BLOCKED sponsor cascades void on finalized spotlight; spotlight_slots_remaining increases', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const eventBefore = await getEvent(fixture.event.id);
    const spotlightSlotsBefore = eventBefore.spotlight_slots_remaining;

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);

    const blockRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );
    expectSuccess(blockRes);

    const event = await getEvent(fixture.event.id);

    expect(event.spotlight_slots_remaining).toBe(spotlightSlotsBefore + 1);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const spotlightClaim = commitment.claims.find(c => c.benefit_kind === 'SPOTLIGHT');
    expect(spotlightClaim).toBeDefined();
    expect(spotlightClaim!.status).toBe('VOIDED');
  });

  test('CROSS_009: Reactivating package alone does not grant holds (ERR_NO_ACTIVE_HOLD)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');

    await retirePackage(fixture.event.id, fixture.gold.id);

    const app1AfterRetire = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1AfterRetire.hold_status).toBe('WAITLISTED');

    await reactivatePackage(fixture.event.id, fixture.gold.id);

    const pkgActive = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgActive.status).toBe('ACTIVE');

    const app1AfterReactivate = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1AfterReactivate.hold_status).toBe('WAITLISTED');

    const res = await transitionApplication(fixture.event.id, fixture.application1.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.NO_ACTIVE_HOLD);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('SUBMITTED');
    expect(app1.hold_status).toBe('WAITLISTED');
  });

  test('CROSS_010: After RETIRE, REACTIVATE, and run_ops, approval works (now HELD again)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await retirePackage(fixture.event.id, fixture.gold.id);

    await reactivatePackage(fixture.event.id, fixture.gold.id);

    await runOpsSuccess(fixture.event.id);

    const app1AfterOps = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1AfterOps.hold_status).toBe('HELD');

    const res = await transitionApplication(fixture.event.id, fixture.application1.id, 'APPROVE');

    expectSuccess(res);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('APPROVED');
    expect(app1.commitment_id).toBeDefined();

    const commitment = await getCommitment(fixture.event.id, app1.commitment_id!);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor1.id);
    if (sponsor.status === 'VETTED') {
      expect(commitment.status).toBe('ACTIVE');
    } else {
      expect(commitment.status).toBe('PENDING_COUNTERSIGN');
    }
  });

});
