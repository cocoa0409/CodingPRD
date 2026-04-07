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
  countersignCommitment,
  transitionClaim,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  createGoldSilverPackages,
  createWaitlistTwoAppsGold,
  createActiveWithFinalizedLeads,
  createTwoFinalizedSpotlightsEventFull,
  createPendingCommitmentProspectGold,
  createClaim,
  finalizeClaim,
  voidClaim,
  unwrap,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 10: Deep Integration Sequences', () => {

  test('DEEP_001: Two submitted applications get HELD and WAITLISTED after run_ops', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);

    const sponsor1 = await createSponsor(event.id, {
      display_name: 'S1',
      legal_name: 'S1 LLC',
      primary_contact_email: 's1@s.test',
      status: 'VETTED',
    });

    const sponsor2 = await createSponsor(event.id, {
      display_name: 'S2',
      legal_name: 'S2 LLC',
      primary_contact_email: 's2@s.test',
      status: 'VETTED',
    });

    const app1 = await createApplication(event.id, { sponsor_id: sponsor1.id, package_id: gold.id });
    await submitApplication(event.id, app1.id);

    const app2 = await createApplication(event.id, { sponsor_id: sponsor2.id, package_id: gold.id });
    await submitApplication(event.id, app2.id);

    const res = await runOps(event.id);

    expectSuccess(res);

    const application1 = await getApplication(event.id, app1.id);
    expect(application1.hold_status).toBe('HELD');

    const application2 = await getApplication(event.id, app2.id);
    expect(application2.hold_status).toBe('WAITLISTED');

    const pkg = await getPackage(event.id, gold.id);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('DEEP_002: Creating a claim records intent (PROPOSED); benefits_left unchanged', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    let { commitment: c1 } = await approveApplication(fixture.event.id, fixture.application1.id);

    if (c1.status !== 'ACTIVE') {
      c1 = await countersignCommitment(fixture.event.id, c1.id);
    }
    expect(c1.status).toBe('ACTIVE');

    const commitmentBefore = await getCommitment(fixture.event.id, c1.id);
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(100);

    const res = await postAs(`/events/${fixture.event.id}/commitments/${c1.id}/claims`, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 40,
    });

    expectSuccess(res);
    const claim = unwrap(res.body);
    expect(claim.status).toBe('PROPOSED');

    const commitmentAfter = await getCommitment(fixture.event.id, c1.id);
    expect(commitmentAfter.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('DEEP_003: Finalizing claim decrements benefits_left; waitlisted app remains WAITLISTED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    let { commitment: c1 } = await approveApplication(fixture.event.id, fixture.application1.id);

    if (c1.status !== 'ACTIVE') {
      c1 = await countersignCommitment(fixture.event.id, c1.id);
    }

    const claim = await createClaim(fixture.event.id, c1.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 40,
    });
    expect(claim.status).toBe('PROPOSED');

    const res = await transitionClaim(fixture.event.id, c1.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, c1.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(60);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('WAITLISTED');
  });

  test('DEEP_004: Blocking sponsor rescinds commitment, voids claim, frees slot; waitlist unchanged', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    let { commitment: c1 } = await approveApplication(fixture.event.id, fixture.application1.id);

    if (c1.status !== 'ACTIVE') {
      c1 = await countersignCommitment(fixture.event.id, c1.id);
    }

    const claim = await createClaim(fixture.event.id, c1.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 40,
    });
    await finalizeClaim(fixture.event.id, c1.id, claim.id);

    const commitmentBefore = await getCommitment(fixture.event.id, c1.id);
    expect(commitmentBefore.status).toBe('ACTIVE');
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(60);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor1.id);

    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, c1.id);
    expect(commitment.status).toBe('RESCINDED');

    const voidedClaim = commitment.claims.find(cl => cl.id === claim.id);
    expect(voidedClaim).toBeDefined();
    expect(voidedClaim!.status).toBe('VOIDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('WAITLISTED');
  });

  test('DEEP_005: After BLOCKED sponsor and run_ops, waitlisted app becomes HELD (promotion)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const { commitment: c1 } = await approveApplication(fixture.event.id, fixture.application1.id);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor1.id);

    const blockRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );
    expectSuccess(blockRes);

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const eventBefore = await getEvent(fixture.event.id);

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');

    expect(app2.hold_expires_on_ops).toBeDefined();

    const eventAfter = await getEvent(fixture.event.id);
    expect(app2.hold_expires_on_ops).toBeGreaterThan(eventAfter.ops_run_index);
  });

  test('DEEP_006: Pending commitment auto-rescinds after 3 run_ops; slots freed; application stays APPROVED', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    expect(fixture.commitment.status).toBe('PENDING_COUNTERSIGN');
    expect(fixture.commitment.activation_deadline_on_ops).toBeDefined();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const deadline = fixture.commitment.activation_deadline_on_ops!;
    let event = await getEvent(fixture.event.id);

    while (event.ops_run_index < deadline) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('DEEP_007: Finalizing spotlight fails when event spotlight slots are full (ERR_SPOTLIGHT_FULL)', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const eventBefore = await getEvent(fixture.event.id);
    expect(eventBefore.spotlight_slots_remaining).toBe(0);

    const p3 = await createPackage(fixture.event.id, {
      label: 'G3',
      price_cents: 1,
      slot_count: 1,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsorC = await createSponsor(fixture.event.id, {
      display_name: 'C',
      legal_name: 'C LLC',
      primary_contact_email: 'c@c.test',
      status: 'VETTED',
    });

    const appC = await createApplication(fixture.event.id, { sponsor_id: sponsorC.id, package_id: p3.id });
    await submitApplication(fixture.event.id, appC.id);
    let { commitment: cc } = await approveApplication(fixture.event.id, appC.id);

    if (cc.status !== 'ACTIVE') {
      cc = await countersignCommitment(fixture.event.id, cc.id);
    }

    const claimC = await createClaim(fixture.event.id, cc.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });
    expect(claimC.status).toBe('PROPOSED');

    const res = await transitionClaim(fixture.event.id, cc.id, claimC.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.SPOTLIGHT_FULL);

    const commitment = await getCommitment(fixture.event.id, cc.id);
    expect(commitment.status).toBe('ACTIVE');

    const claim = commitment.claims.find(cl => cl.id === claimC.id);
    expect(claim).toBeDefined();
    expect(claim!.status).toBe('PROPOSED');
  });

  test('DEEP_008: After voiding a spotlight, new sponsor can finalize their spotlight claim', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const eventBefore = await getEvent(fixture.event.id);
    expect(eventBefore.spotlight_slots_remaining).toBe(0);

    const commitmentA = await getCommitment(fixture.event.id, fixture.commitmentA.id);
    const spotlightClaimA = commitmentA.claims.find(cl => cl.benefit_kind === 'SPOTLIGHT');
    expect(spotlightClaimA).toBeDefined();
    expect(spotlightClaimA!.status).toBe('FINALIZED');

    await voidClaim(fixture.event.id, fixture.commitmentA.id, spotlightClaimA!.id);

    const eventAfterVoid = await getEvent(fixture.event.id);
    expect(eventAfterVoid.spotlight_slots_remaining).toBe(1);

    const p3 = await createPackage(fixture.event.id, {
      label: 'G3',
      price_cents: 1,
      slot_count: 1,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsorC = await createSponsor(fixture.event.id, {
      display_name: 'C',
      legal_name: 'C LLC',
      primary_contact_email: 'c@c.test',
      status: 'VETTED',
    });

    const appC = await createApplication(fixture.event.id, { sponsor_id: sponsorC.id, package_id: p3.id });
    await submitApplication(fixture.event.id, appC.id);
    let { commitment: cc } = await approveApplication(fixture.event.id, appC.id);

    if (cc.status !== 'ACTIVE') {
      cc = await countersignCommitment(fixture.event.id, cc.id);
    }

    const claimC = await createClaim(fixture.event.id, cc.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const res = await transitionClaim(fixture.event.id, cc.id, claimC.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, cc.id);
    const finalizedClaim = commitment.claims.find(cl => cl.id === claimC.id);
    expect(finalizedClaim).toBeDefined();
    expect(finalizedClaim!.status).toBe('FINALIZED');

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(0);
  });

  test('DEEP_009: Under WATCHLIST and LOCKDOWN, void still works and benefits restored', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const commitmentInitial = await getCommitment(fixture.event.id, fixture.commitment.id);
    const benefitsAfterClaim = commitmentInitial.benefits_left.LEAD_SCANS;

    expect(benefitsAfterClaim).toBe(70);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const watchlistRes = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );
    expectSuccess(watchlistRes);

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');

    const event = await getEvent(fixture.event.id);
    const lockdownRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(lockdownRes);

    const eventLockdown = await getEvent(fixture.event.id);
    expect(eventLockdown.posture).toBe('LOCKDOWN');

    const commitmentWithClaim = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitmentWithClaim.claims.find(cl => cl.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();

    const res = await transitionClaim(
      fixture.event.id,
      fixture.commitment.id,
      finalizedClaim!.id,
      'VOID'
    );

    expectSuccess(res);

    const commitmentAfterVoid = await getCommitment(fixture.event.id, fixture.commitment.id);

    const voidedClaim = commitmentAfterVoid.claims.find(cl => cl.id === finalizedClaim!.id);
    expect(voidedClaim).toBeDefined();
    expect(voidedClaim!.status).toBe('VOIDED');

    expect(commitmentAfterVoid.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('DEEP_010: Under LOCKDOWN, run_ops still works; holds expire and waitlist advances', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app1Before.hold_expires_on_ops).toBeDefined();

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const event = await getEvent(fixture.event.id);
    const lockdownRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(lockdownRes);

    const eventLockdown = await getEvent(fixture.event.id);
    expect(eventLockdown.posture).toBe('LOCKDOWN');

    const holdDeadline = app1Before.hold_expires_on_ops!;

    let currentEvent = await getEvent(fixture.event.id);
    while (currentEvent.ops_run_index < holdDeadline) {
      const res = await runOps(fixture.event.id);
      expectSuccess(res);
      currentEvent = await getEvent(fixture.event.id);
    }

    const app1After = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1After.status).toBe('EXPIRED');

    const app2After = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2After.hold_status).toBe('HELD');
    expect(app2After.hold_expires_on_ops).toBeDefined();
  });

});
