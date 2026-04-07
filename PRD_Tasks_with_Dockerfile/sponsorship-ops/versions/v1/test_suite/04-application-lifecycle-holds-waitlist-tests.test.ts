import {
  postAs,
  getAs,
  patchWithVersion,
  putWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  expectErrorCodeOneOf,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createEventDraft,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  transitionApplication,
  withdrawApplication,
  rejectApplication,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  getSponsor,
  runOps,
  runOpsSuccess,
  updateEvent,
  updateSponsor,
  transitionPackage,
  rescindCommitment,
  transitionCommitment,
  createGoldSilverPackages,
  createActiveCommitmentVettedGold,
  createDraftApplicationVettedGold,
  createSubmittedHeldApplicationVettedGold,
  createWaitlistTwoAppsGold,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 4: Application Lifecycle, Holds, Waitlist Tests', () => {

  test('APP_001: POST /events/:E/applications creates application with status=DRAFT and version=1', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'VettedCo',
      legal_name: 'VettedCo LLC',
      primary_contact_email: 'v@vetted.test',
      status: 'VETTED',
    });

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
      note: 'draft',
    });

    expectSuccess(res);
    const application = unwrap(res.body);

    const appCheck = await getApplication(event.id, application.id);
    expect(appCheck.status).toBe('DRAFT');
    expect(appCheck.version).toBe(1);
  });

  test('APP_002: PUT /events/:E/applications/:A with If-Match updates draft application', async () => {

    const fixture = await createDraftApplicationVettedGold();

    const res = await putWithVersion(
      `/events/${fixture.event.id}/applications/${fixture.application.id}`,
      { note: 'edited draft' },
      fixture.application.version
    );

    expectSuccess(res);

    const appCheck = await getApplication(fixture.event.id, fixture.application.id);
    expect(appCheck.status).toBe('DRAFT');
    expect(appCheck.version).toBe(2);
    expect(appCheck.note).toBe('edited draft');
  });

  test('APP_003: PUT on submitted application fails with ERR_INVALID_STATE', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.status).toBe('SUBMITTED');

    const res = await putWithVersion(
      `/events/${fixture.event.id}/applications/${fixture.application.id}`,
      { note: 'attempt edit after submit' },
      appBefore.version
    );

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const appCheck = await getApplication(fixture.event.id, fixture.application.id);
    expect(appCheck.status).toBe('SUBMITTED');
  });

  test('APP_004: SUBMIT transition on draft creates hold with submit_seq and hold_expires_on_ops', async () => {

    const fixture = await createDraftApplicationVettedGold();

    const event = await getEvent(fixture.event.id);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'SUBMIT');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('SUBMITTED');
    expect(app.hold_status).toBe('HELD');

    expect(app.hold_expires_on_ops).toBeDefined();
    expect(app.hold_expires_on_ops).toBeGreaterThan(event.ops_run_index);

    expect(app.submit_seq).toBeDefined();
    expect(app.submit_seq).toBeGreaterThanOrEqual(1);
  });

  test('APP_005: SUBMIT fails with ERR_EVENT_NOT_OPEN when event is in DRAFT posture', async () => {

    const event = await createEventDraft();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'S',
      legal_name: 'S LLC',
      primary_contact_email: 's@s.test',
      status: 'VETTED',
    });
    const application = await createApplication(event.id, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });

    const eventDraft = await getEvent(event.id);
    expect(eventDraft.posture).toBe('DRAFT');

    const res = await transitionApplication(event.id, application.id, 'SUBMIT');

    await expectErrorCode(res, ERROR_CODES.EVENT_NOT_OPEN);

    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('DRAFT');
  });

  test('APP_006: SUBMIT fails with ERR_EVENT_LOCKDOWN when event is in LOCKDOWN posture', async () => {

    const fixture = await createDraftApplicationVettedGold();

    const eventBefore = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      eventBefore.version
    );
    expectSuccess(patchRes);

    const eventLockdown = await getEvent(fixture.event.id);
    expect(eventLockdown.posture).toBe('LOCKDOWN');

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'SUBMIT');

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('DRAFT');
  });

  test('APP_007: APPROVE fails with ERR_NO_ACTIVE_HOLD when application is WAITLISTED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('SUBMITTED');
    expect(app2.hold_status).toBe('WAITLISTED');

    const res = await transitionApplication(fixture.event.id, fixture.application2.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.NO_ACTIVE_HOLD);

    const app2Check = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Check.status).toBe('SUBMITTED');
    expect(app2Check.hold_status).toBe('WAITLISTED');
  });

  test('APP_008: APPROVE on HELD application creates commitment and consumes slot', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.hold_status).toBe('HELD');
    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'APPROVE');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('APPROVED');
    expect(app.commitment_id).toBeDefined();

    const commitment = await getCommitment(fixture.event.id, app.commitment_id!);
    expect(commitment.status).toBe('ACTIVE');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('APP_009: APPROVE on already APPROVED application fails with ERR_INVALID_STATE', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();
    await approveApplication(fixture.event.id, fixture.application.id);

    const appApproved = await getApplication(fixture.event.id, fixture.application.id);
    expect(appApproved.status).toBe('APPROVED');

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('APPROVED');
  });

  test('APP_010: REJECT on HELD application releases slot', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.hold_status).toBe('HELD');
    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'REJECT');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('REJECTED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('APP_011: REJECT on WAITLISTED application keeps A1 HELD and slots unchanged', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');
    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionApplication(fixture.event.id, fixture.application2.id, 'REJECT');

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('REJECTED');

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.hold_status).toBe('HELD');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('APP_012: WITHDRAW on DRAFT application succeeds with no inventory side effects', async () => {

    const fixture = await createDraftApplicationVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'WITHDRAW');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('WITHDRAWN');

    const pkgAfter = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgAfter.slots_remaining).toBe(pkgBefore.slots_remaining);
  });

  test('APP_013: WITHDRAW on SUBMITTED HELD application releases slot', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'WITHDRAW');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('WITHDRAWN');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('APP_014: WITHDRAW on HELD A1 releases slot; A2 remains WAITLISTED until run_ops', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const res = await transitionApplication(fixture.event.id, fixture.application1.id, 'WITHDRAW');

    expectSuccess(res);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('WITHDRAWN');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('WAITLISTED');
  });

  test('APP_015: run_ops advances waitlist after WITHDRAW; A2 becomes HELD', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await withdrawApplication(fixture.event.id, fixture.application1.id);

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const eventAfter = await getEvent(fixture.event.id);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');

    expect(app2.hold_expires_on_ops).toBeDefined();
    expect(app2.hold_expires_on_ops).toBeGreaterThan(eventAfter.ops_run_index);
  });

  test('APP_016: run_ops expires A1 hold when ops_run_index reaches hold_expires_on_ops; GET shows status=EXPIRED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_expires_on_ops).toBeDefined();
    const expirationIndex = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < expirationIndex) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);

    expect(app1.status).toBe('EXPIRED');
  });

  test('APP_017: After A1 expires, A2 becomes HELD with updated hold_expires_on_ops', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const expirationIndex = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < expirationIndex) {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
    }

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(app2.hold_status).toBe('HELD');
    expect(app2.hold_expires_on_ops).toBeDefined();
    expect(app2.hold_expires_on_ops).toBeGreaterThan(event.ops_run_index);
  });

  test('APP_018: SUBMIT on EXPIRED application fails with ERR_INVALID_STATE', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await runOpsSuccess(fixture.event.id);
    await runOpsSuccess(fixture.event.id);

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.status).toBe('EXPIRED');

    const res = await transitionApplication(fixture.event.id, fixture.application1.id, 'SUBMIT');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('EXPIRED');
  });

  test('APP_019: APPROVE on A2 after A1 expires creates commitment', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const expirationIndex = app1Before.hold_expires_on_ops!;

    let event = await getEvent(fixture.event.id);
    let app2 = await getApplication(fixture.event.id, fixture.application2.id);
    while (event.ops_run_index < expirationIndex || app2.hold_status !== 'HELD') {
      await runOpsSuccess(fixture.event.id);
      event = await getEvent(fixture.event.id);
      app2 = await getApplication(fixture.event.id, fixture.application2.id);
    }

    expect(app2.hold_status).toBe('HELD');

    const res = await transitionApplication(fixture.event.id, fixture.application2.id, 'APPROVE');

    expectSuccess(res);

    const app2After = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2After.status).toBe('APPROVED');
    expect(app2After.commitment_id).toBeDefined();

    const commitment = await getCommitment(fixture.event.id, app2After.commitment_id!);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('APP_020: Creating application for sponsor with existing active commitment fails', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const res = await postAs(`/events/${fixture.event.id}/applications`, {
      sponsor_id: fixture.sponsor.id,
      package_id: fixture.gold.id,
    });

    await expectErrorCodeOneOf(res, [ERROR_CODES.DUPLICATE_APPLICATION, ERROR_CODES.DUPLICATE_COMMITMENT]);
  });

  test('APP_021: New application allowed after commitment is rescinded', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await rescindCommitment(fixture.event.id, fixture.commitment.id);

    const commitmentRescinded = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentRescinded.status).toBe('RESCINDED');

    const pkgAfterRescind = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgAfterRescind.slots_remaining).toBe(1);

    const res = await postAs(`/events/${fixture.event.id}/applications`, {
      sponsor_id: fixture.sponsor.id,
      package_id: fixture.gold.id,
    });

    expectSuccess(res);
    const newApp = unwrap(res.body);

    const appCheck = await getApplication(fixture.event.id, newApp.id);
    expect(appCheck.status).toBe('DRAFT');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('APP_022: APPROVE on DRAFT application fails with ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'X',
      legal_name: 'X LLC',
      primary_contact_email: 'x@x.test',
      status: 'VETTED',
    });
    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    const appBefore = await getApplication(event.id, application.id);
    expect(appBefore.status).toBe('DRAFT');

    const res = await transitionApplication(event.id, application.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const appCheck = await getApplication(event.id, application.id);
    expect(appCheck.status).toBe('DRAFT');
  });

  test('APP_023: PROSPECT sponsor can submit application and gets HELD or WAITLISTED', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'ProspectCo',
      legal_name: 'ProspectCo LLC',
      primary_contact_email: 'p@prospect.test',
      status: 'PROSPECT',
    });

    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    const res = await transitionApplication(event.id, application.id, 'SUBMIT');

    expectSuccess(res);

    const eventAfter = await getEvent(event.id);
    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('SUBMITTED');
    expect(['HELD', 'WAITLISTED']).toContain(app.hold_status);

    if (app.hold_status === 'HELD') {

      expect(app.hold_expires_on_ops).toBeDefined();
      expect(app.hold_expires_on_ops).toBeGreaterThan(eventAfter.ops_run_index);
    }
  });

  test('APP_024: BLOCKED sponsor cannot create application', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const blockedSponsor = await createSponsor(event.id, {
      display_name: 'BlockedCo',
      legal_name: 'BlockedCo LLC',
      primary_contact_email: 'blocked@test.test',
      status: 'BLOCKED',
    });

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: blockedSponsor.id,
      package_id: gold.id,
    });

    await expectErrorCode(res, ERROR_CODES.SPONSOR_BLOCKED);

    const eventCheck = await getEvent(event.id);
    expect(eventCheck.posture).toBe('OPEN');
  });

  test('APP_025: APPROVE on WAITLISTED app after package RETIRE fails with appropriate error', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await transitionPackage(fixture.event.id, fixture.gold.id, 'RETIRE');

    const pkgRetired = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgRetired.status).toBe('RETIRED');

    const res = await transitionApplication(fixture.event.id, fixture.application2.id, 'APPROVE');

    await expectErrorCodeOneOf(res, [ERROR_CODES.PACKAGE_RETIRED, ERROR_CODES.NO_ACTIVE_HOLD]);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('SUBMITTED');
  });

  test('APP_026: APPROVE works after package REACTIVATE and run_ops grants hold', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await transitionPackage(fixture.event.id, fixture.gold.id, 'RETIRE');

    await transitionPackage(fixture.event.id, fixture.gold.id, 'REACTIVATE');

    const pkgActive = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgActive.status).toBe('ACTIVE');

    await runOpsSuccess(fixture.event.id);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.hold_status).toBe('HELD');

    const res = await transitionApplication(fixture.event.id, fixture.application1.id, 'APPROVE');

    expectSuccess(res);

    const app1Approved = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Approved.status).toBe('APPROVED');
  });

  test('APP_027: APPROVE fails with ERR_EVENT_LOCKDOWN when event is locked', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const eventBefore = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      eventBefore.version
    );
    expectSuccess(patchRes);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'APPROVE');

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('SUBMITTED');
  });

  test('APP_028: APPROVE fails when event is ARCHIVED', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const eventBefore = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'ARCHIVED' },
      eventBefore.version
    );
    expectSuccess(patchRes);

    const eventArchived = await getEvent(fixture.event.id);
    expect(eventArchived.posture).toBe('ARCHIVED');

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'APPROVE');

    await expectErrorCodeOneOf(res, [ERROR_CODES.EVENT_LOCKDOWN, ERROR_CODES.EVENT_NOT_OPEN]);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('SUBMITTED');
  });

  test('APP_029: REJECT allowed during LOCKDOWN as cleanup action', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const eventBefore = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      eventBefore.version
    );
    expectSuccess(patchRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');
    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'REJECT');

    expectSuccess(res);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('REJECTED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('APP_030: Blocking S1 withdraws A1; run_ops advances A2 to HELD', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      fixture.sponsor1.version
    );

    const app1Withdrawn = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Withdrawn.status).toBe('WITHDRAWN');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');
  });

  test('APP_031: After blocking S1, slots_remaining=1 until run_ops', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      fixture.sponsor1.version
    );

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBe(1);
  });

  test('APP_032: After blocking S1 and run_ops, slots_remaining=0 (A2 now held)', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor1.id}`,
      { status: 'BLOCKED' },
      fixture.sponsor1.version
    );

    await runOpsSuccess(fixture.event.id);

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);

    expect(pkg.slots_remaining).toBe(0);
  });

  test('APP_033: Double SUBMIT on application fails with ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'DoubleSub',
      legal_name: 'DoubleSub LLC',
      primary_contact_email: 'ds@test.test',
      status: 'VETTED',
    });

    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    await submitApplication(event.id, application.id);

    const appSubmitted = await getApplication(event.id, application.id);
    expect(appSubmitted.status).toBe('SUBMITTED');
    const originalSubmitSeq = appSubmitted.submit_seq;

    const res = await transitionApplication(event.id, application.id, 'SUBMIT');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('SUBMITTED');
    expect(app.submit_seq).toBe(originalSubmitSeq);
  });

  test('APP_034: Double WITHDRAW on application fails with ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'DoubleWith',
      legal_name: 'DoubleWith LLC',
      primary_contact_email: 'dw@test.test',
      status: 'VETTED',
    });

    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    await withdrawApplication(event.id, application.id);

    const appWithdrawn = await getApplication(event.id, application.id);
    expect(appWithdrawn.status).toBe('WITHDRAWN');

    const res = await transitionApplication(event.id, application.id, 'WITHDRAW');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('WITHDRAWN');
  });

  test('APP_035: REJECT on DRAFT application fails with ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'RejectDraft',
      legal_name: 'RejectDraft LLC',
      primary_contact_email: 'rd@test.test',
      status: 'VETTED',
    });

    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    const appDraft = await getApplication(event.id, application.id);
    expect(appDraft.status).toBe('DRAFT');

    const res = await transitionApplication(event.id, application.id, 'REJECT');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('DRAFT');
  });

  test('APP_036: New application allowed after previous was REJECTED', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'ReApply',
      legal_name: 'ReApply LLC',
      primary_contact_email: 'ra@test.test',
      status: 'VETTED',
    });

    const app1Res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(app1Res);
    const app1 = unwrap(app1Res.body);

    await submitApplication(event.id, app1.id);
    await rejectApplication(event.id, app1.id);

    const app1Rejected = await getApplication(event.id, app1.id);
    expect(app1Rejected.status).toBe('REJECTED');

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });

    expectSuccess(res);
    const newApp = unwrap(res.body);

    const appCheck = await getApplication(event.id, newApp.id);
    expect(appCheck.status).toBe('DRAFT');
  });

  test('APP_037: New application allowed after previous was EXPIRED', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, {
      display_name: 'ExpireRe',
      legal_name: 'ExpireRe LLC',
      primary_contact_email: 'er@test.test',
      status: 'VETTED',
    });

    const app1Res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });
    expectSuccess(app1Res);
    const app1 = unwrap(app1Res.body);

    await submitApplication(event.id, app1.id);

    await runOpsSuccess(event.id);
    await runOpsSuccess(event.id);

    const app1Expired = await getApplication(event.id, app1.id);
    expect(app1Expired.status).toBe('EXPIRED');

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });

    expectSuccess(res);
    const newApp = unwrap(res.body);

    const appCheck = await getApplication(event.id, newApp.id);
    expect(appCheck.status).toBe('DRAFT');
  });

  test('APP_038: run_ops works during LOCKDOWN; hold expires normally', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const appBefore = await getApplication(fixture.event.id, fixture.application.id);
    expect(appBefore.hold_expires_on_ops).toBeDefined();
    const expirationIndex = appBefore.hold_expires_on_ops!;

    const eventBefore = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      eventBefore.version
    );
    expectSuccess(patchRes);

    const eventLocked = await getEvent(fixture.event.id);
    expect(eventLocked.posture).toBe('LOCKDOWN');

    let event = await getEvent(fixture.event.id);
    while (event.ops_run_index < expirationIndex) {
      const res = await runOps(fixture.event.id);
      expectSuccess(res);
      event = await getEvent(fixture.event.id);
    }

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('EXPIRED');
  });

  test('APP_039: WITHDRAW on EXPIRED application fails with ERR_INVALID_STATE', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    await runOpsSuccess(fixture.event.id);
    await runOpsSuccess(fixture.event.id);

    const appExpired = await getApplication(fixture.event.id, fixture.application.id);
    expect(appExpired.status).toBe('EXPIRED');

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'WITHDRAW');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const app = await getApplication(fixture.event.id, fixture.application.id);
    expect(app.status).toBe('EXPIRED');
  });

  test('APP_040: Approval on package without included_benefits creates commitment with empty/zeroed benefits_left', async () => {

    const event = await createEventOpen();

    const pkg = await createPackage(event.id, {
      label: 'GOLD',
      price_cents: 500000,
      slot_count: 1,
      included_benefits: [],
    });

    const sponsor = await createSponsor(event.id, {
      display_name: 'S',
      legal_name: 'S LLC',
      primary_contact_email: 's@s.test',
      status: 'VETTED',
    });

    const appRes = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: pkg.id,
    });
    expectSuccess(appRes);
    const application = unwrap(appRes.body);

    await submitApplication(event.id, application.id);

    const appSubmitted = await getApplication(event.id, application.id);
    expect(appSubmitted.hold_status).toBe('HELD');

    const res = await transitionApplication(event.id, application.id, 'APPROVE');

    expectSuccess(res);

    const app = await getApplication(event.id, application.id);
    expect(app.status).toBe('APPROVED');
    expect(app.commitment_id).toBeDefined();

    const commitment = await getCommitment(event.id, app.commitment_id!);
    expect(commitment.status).toBe('ACTIVE');

    const benefitsLeft = commitment.benefits_left;

    const allZeroOrUndefined =
      !benefitsLeft ||
      Object.keys(benefitsLeft).length === 0 ||
      Object.values(benefitsLeft).every(v => v === 0 || v === undefined || v === null);
    expect(allZeroOrUndefined).toBe(true);
  });

});
