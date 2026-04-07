import {
  postAs,
  getAs,
  patchWithVersion,
  patchAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  transitionCommitment,
  countersignCommitment,
  createClaim,
  finalizeClaim,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  updateSponsor,
  updateSponsorStatus,
  createGoldSilverPackages,
  createActiveCommitmentVettedGold,
  createPendingCommitmentProspectGold,
  createActiveWithFinalizedLeads,
  createActiveWithFinalizedSpotlight,
  createWaitlistTwoAppsGold,
  createSubmittedHeldApplicationVettedGold,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 3: Sponsor Status & Cascade Tests', () => {

  test('SPONSOR_001: POST /events/:E/sponsors creates sponsor with status=PROSPECT and version present', async () => {

    const event = await createEventOpen();

    const res = await postAs(`/events/${event.id}/sponsors`, {
      display_name: 'NewCo',
      legal_name: 'NewCo LLC',
      primary_contact_email: 'c@new.test',
      status: 'PROSPECT',
    });

    expectSuccess(res);
    const sponsor = unwrap(res.body);

    const sponsorCheck = await getSponsor(event.id, sponsor.id);
    expect(sponsorCheck.status).toBe('PROSPECT');

    expect(sponsorCheck.version).toBeGreaterThanOrEqual(1);
  });

  test('SPONSOR_002: PATCH sponsor status from PROSPECT to VETTED with If-Match updates version', async () => {

    const event = await createEventOpen();
    const sponsor = await createSponsor(event.id, {
      display_name: 'ProspectCo',
      legal_name: 'ProspectCo LLC',
      primary_contact_email: 'p@prospect.test',
      status: 'PROSPECT',
    });

    const versionBefore = sponsor.version;

    const res = await patchWithVersion(
      `/events/${event.id}/sponsors/${sponsor.id}`,
      { status: 'VETTED' },
      sponsor.version
    );

    expectSuccess(res);

    const sponsorCheck = await getSponsor(event.id, sponsor.id);
    expect(sponsorCheck.status).toBe('VETTED');
    expect(sponsorCheck.version).toBe(versionBefore + 1);
  });

  test('SPONSOR_003: PATCH sponsor without If-Match returns ERR_PRECONDITION_REQUIRED', async () => {

    const event = await createEventOpen();
    const sponsor = await createSponsor(event.id, {
      display_name: 'ProspectCo',
      legal_name: 'ProspectCo LLC',
      primary_contact_email: 'p@prospect.test',
      status: 'PROSPECT',
    });

    const versionBefore = sponsor.version;

    const res = await patchAs(`/events/${event.id}/sponsors/${sponsor.id}`, { status: 'VETTED' });

    await expectErrorCode(res, ERROR_CODES.PRECONDITION_REQUIRED);

    const sponsorCheck = await getSponsor(event.id, sponsor.id);
    expect(sponsorCheck.status).toBe('PROSPECT');
    expect(sponsorCheck.version).toBe(versionBefore);
  });

  test('SPONSOR_004: PATCH sponsor with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const event = await createEventOpen();
    const sponsor = await createSponsor(event.id, {
      display_name: 'ProspectCo',
      legal_name: 'ProspectCo LLC',
      primary_contact_email: 'p@prospect.test',
      status: 'PROSPECT',
    });

    const staleVersion = sponsor.version;

    const firstUpdate = await patchWithVersion(
      `/events/${event.id}/sponsors/${sponsor.id}`,
      { status: 'VETTED' },
      sponsor.version
    );
    expectSuccess(firstUpdate);

    const res = await patchWithVersion(
      `/events/${event.id}/sponsors/${sponsor.id}`,
      { status: 'WATCHLIST' },
      staleVersion
    );

    await expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);

    const sponsorCheck = await getSponsor(event.id, sponsor.id);
    expect(sponsorCheck.status).toBe('VETTED');
  });

  test('SPONSOR_005: Moving sponsor to WATCHLIST suspends active commitment and sets activation_deadline_on_ops', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const eventBefore = await getEvent(fixture.event.id);

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );
    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.status).toBe('SUSPENDED');
    expect(commitment.activation_deadline_on_ops).toBeDefined();
    expect(commitment.activation_deadline_on_ops).toBeGreaterThan(eventBefore.ops_run_index);
  });

  test('SPONSOR_006: Creating claim on SUSPENDED commitment fails with ERR_COMMITMENT_NOT_ACTIVE', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('SUSPENDED');

    const res = await postAs(`/events/${fixture.event.id}/commitments/${commitment.id}/claims`, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 1,
    });

    await expectErrorCode(res, ERROR_CODES.COMMITMENT_NOT_ACTIVE);

    const commitmentCheck = await getCommitment(fixture.event.id, commitment.id);
    expect(commitmentCheck.status).toBe('SUSPENDED');
    expect(commitmentCheck.claims.length).toBe(0);
  });

  test('SPONSOR_007: COUNTERSIGN on SUSPENDED commitment reactivates it and clears activation_deadline', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('SUSPENDED');
    expect(commitmentBefore.activation_deadline_on_ops).toBeDefined();

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'COUNTERSIGN');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');

    expect(commitment.activation_deadline_on_ops === undefined || commitment.activation_deadline_on_ops === null).toBe(true);
  });

  test('SPONSOR_008: After COUNTERSIGN on previously SUSPENDED commitment, claims can be created', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );
    await countersignCommitment(fixture.event.id, fixture.commitment.id);

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const res = await postAs(`/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 5,
    });

    expectSuccess(res);
    const createdClaim = unwrap(res.body);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.claims.length).toBeGreaterThanOrEqual(1);
    const claim = commitment.claims.find(c => c.id === createdClaim.id);
    expect(claim).toBeDefined();
    expect(claim!.benefit_kind).toBe('LEAD_SCANS');
    expect(claim!.quantity).toBe(5);
    expect(claim!.status).toBe('PROPOSED');
  });

  test('SPONSOR_009: Blocking sponsor with finalized SPOTLIGHT claim rescinds commitment and releases spotlight slot', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const eventBefore = await getEvent(fixture.event.id);
    expect(eventBefore.spotlight_slots_remaining).toBe(1);

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'BLOCKED' },
      fixture.sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const event = await getEvent(fixture.event.id);
    expect(event.spotlight_slots_remaining).toBe(2);
  });

  test('SPONSOR_010: Blocking sponsor with finalized LEAD_SCANS claim rescinds commitment and restores benefits_left', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    const leadScansBenefit = pkg.included_benefits.find(b => b.benefit_kind === 'LEAD_SCANS');
    const originalLeadScans = leadScansBenefit?.quantity ?? 0;

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const benefitsLeftBefore = commitmentBefore.benefits_left.LEAD_SCANS ?? 0;

    expect(benefitsLeftBefore).toBeLessThan(originalLeadScans);

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'BLOCKED' },
      fixture.sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const voidedClaims = commitment.claims.filter(c => c.status === 'VOIDED');
    expect(voidedClaims.length).toBeGreaterThanOrEqual(1);

    const benefitsLeftAfter = commitment.benefits_left.LEAD_SCANS ?? 0;
    expect(benefitsLeftAfter).toBeGreaterThan(benefitsLeftBefore);
  });

  test('SPONSOR_011: Blocking sponsor with waitlisted application withdraws it', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.status).toBe('SUBMITTED');
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor2.id,
      { status: 'BLOCKED' },
      fixture.sponsor2.version
    );

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('WITHDRAWN');

    expect(app2.hold_status === undefined || app2.hold_status === null || (app2.hold_status as any) === 'NONE').toBe(true);
  });

  test('SPONSOR_012: BLOCKED sponsor cannot create new application', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'BlockedCo',
      legal_name: 'BlockedCo LLC',
      primary_contact_email: 'blocked@test.com',
      status: 'BLOCKED',
    });

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });

    await expectErrorCode(res, ERROR_CODES.SPONSOR_BLOCKED);
  });

  test('SPONSOR_013: Changing sponsor status does not restore previously rescinded commitments', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('ACTIVE');

    const blockRes = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'BLOCKED' },
      fixture.sponsor.version
    );
    expectSuccess(blockRes);

    const commitmentAfterBlock = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterBlock.status).toBe('RESCINDED');

    const blockedSponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    expect(blockedSponsor.status).toBe('BLOCKED');

    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'VETTED' },
      blockedSponsor.version
    );

    if (res.status >= 200 && res.status < 300) {
      const commitmentAfterChange = await getCommitment(fixture.event.id, fixture.commitment.id);
      expect(commitmentAfterChange.status).toBe('RESCINDED');
    }

    else {
      const commitmentAfterAttempt = await getCommitment(fixture.event.id, fixture.commitment.id);
      expect(commitmentAfterAttempt.status).toBe('RESCINDED');
    }
  });

  test('SPONSOR_014: Moving sponsor PROSPECT->VETTED does not auto-activate PENDING_COUNTERSIGN commitment', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('PENDING_COUNTERSIGN');

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'VETTED' },
      fixture.sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('PENDING_COUNTERSIGN');
  });

  test('SPONSOR_015: Blocking sponsor works even in LOCKDOWN posture', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const eventBefore = await getEvent(fixture.event.id);
    const lockdownRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      eventBefore.version
    );
    expectSuccess(lockdownRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'BLOCKED' },
      fixture.sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('SPONSOR_016: Duplicate sponsor records are allowed across events (no global uniqueness)', async () => {

    const event1 = await createEventOpen();
    const event2 = await createEventOpen();

    const sponsor1Res = await postAs(`/events/${event1.id}/sponsors`, {
      display_name: 'Dup',
      legal_name: 'Dup LLC',
      primary_contact_email: 'd@d.test',
      status: 'PROSPECT',
    });
    expectSuccess(sponsor1Res);
    const sponsor1 = unwrap(sponsor1Res.body);

    const res = await postAs(`/events/${event2.id}/sponsors`, {
      display_name: 'Dup',
      legal_name: 'Dup LLC',
      primary_contact_email: 'd@d.test',
      status: 'PROSPECT',
    });

    expectSuccess(res);
    const sponsor2 = unwrap(res.body);

    expect(sponsor2.id).not.toBe(sponsor1.id);

    const event1Check = await getEvent(event1.id);
    expect(event1Check.posture).toBe('OPEN');
    const event2Check = await getEvent(event2.id);
    expect(event2Check.posture).toBe('OPEN');
  });

  test('SPONSOR_017: run_ops rescinds SUSPENDED commitment when activation_deadline_on_ops is reached', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );

    const commitmentAfterWatch = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterWatch.status).toBe('SUSPENDED');
    expect(commitmentAfterWatch.activation_deadline_on_ops).toBeDefined();

    const deadline = commitmentAfterWatch.activation_deadline_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < deadline) {
      const res = await runOps(fixture.event.id);
      expectSuccess(res);
      event = await getEvent(fixture.event.id);
    }

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
  });

  test('SPONSOR_018: After run_ops reaches deadline, SUSPENDED commitment is RESCINDED', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );

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
  });

  test('SPONSOR_019: COUNTERSIGN clears deadline; run_ops does not rescind ACTIVE commitment', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'WATCHLIST' },
      fixture.sponsor.version
    );

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');

    await countersignCommitment(fixture.event.id, fixture.commitment.id);

    const commitmentActive = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentActive.status).toBe('ACTIVE');
    expect(commitmentActive.activation_deadline_on_ops === undefined || commitmentActive.activation_deadline_on_ops === null).toBe(true);

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('SPONSOR_020: Blocking sponsor with SUBMITTED HELD application withdraws it and releases slot', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.status).toBe('SUBMITTED');
    expect(appBefore.hold_status).toBe('HELD');

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await updateSponsor(
      fixture.event.id,
      fixture.sponsor.id,
      { status: 'BLOCKED' },
      fixture.sponsor.version
    );

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('WITHDRAWN');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

});
