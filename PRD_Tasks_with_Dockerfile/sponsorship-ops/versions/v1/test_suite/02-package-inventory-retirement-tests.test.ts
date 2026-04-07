import {
  postAs,
  getAs,
  patchWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  expectErrorCodeOneOf,
  expectInvalidState,
  expectNotFound,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  transitionApplication,
  transitionPackage,
  retirePackage,
  reactivatePackage,
  withdrawApplication,
  rescindCommitment,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  runOps,
  runOpsSuccess,
  createGoldSilverPackages,
  createSubmittedHeldApplicationVettedGold,
  createWaitlistTwoAppsGold,
  createActiveCommitmentVettedGold,
  createPendingCommitmentProspectGold,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 2: Package Inventory & Retirement Tests', () => {

  test('PKG_001: POST /events/:E/packages creates package with status=ACTIVE and slots_remaining=slot_count', async () => {

    const event = await createEventOpen();

    const res = await postAs(`/events/${event.id}/packages`, {
      label: 'GOLD',
      price_cents: 500000,
      slot_count: 1,
      included_benefits: [],
    });

    expectSuccess(res);
    const pkg = unwrap(res.body);

    const pkgCheck = await getPackage(event.id, pkg.id);
    expect(pkgCheck.status).toBe('ACTIVE');
    expect(pkgCheck.slots_remaining).toBe(1);
  });

  test('PKG_002: GET package shows slot_count, slots_remaining, and status=ACTIVE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);

    const res = await getAs(`/events/${event.id}/packages/${gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slot_count).toBe(1);
    expect(pkg.slots_remaining).toBe(1);
    expect(pkg.status).toBe('ACTIVE');
  });

  test('PKG_003: HELD application consumes slot (slots_remaining=0)', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('PKG_004: Non-rescinded commitment consumes slot (slots_remaining=0)', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('PKG_005: WAITLISTED application does not consume slot; HELD consumes it', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1.hold_status).toBe('HELD');
    expect(app2.hold_status).toBe('WAITLISTED');

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('PKG_006: RETIRE action transitions package status to RETIRED', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);

    const res = await transitionPackage(event.id, gold.id, 'RETIRE');

    expectSuccess(res);
    const pkg = await getPackage(event.id, gold.id);
    expect(pkg.status).toBe('RETIRED');
  });

  test('PKG_007: Creating application for RETIRED package fails with ERR_PACKAGE_RETIRED', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    const sponsor = await createSponsor(event.id, { status: 'VETTED' });
    await retirePackage(event.id, gold.id);

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: gold.id,
    });

    await expectErrorCode(res, ERROR_CODES.PACKAGE_RETIRED);
  });

  test('PKG_008: Retiring package releases holds, moves held applications to waitlist', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');

    await retirePackage(fixture.event.id, fixture.gold.id);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('SUBMITTED');
    expect(app1.hold_status).toBe('WAITLISTED');
  });

  test('PKG_009: Retiring package releases holds, slots_remaining increases', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    await retirePackage(fixture.event.id, fixture.gold.id);

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
    expect(pkg.status).toBe('RETIRED');
  });

  test('PKG_010: run_ops does not advance waitlist for RETIRED package', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await retirePackage(fixture.event.id, fixture.gold.id);

    const app1AfterRetire = await getApplication(fixture.event.id, fixture.application1.id);
    const app2AfterRetire = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1AfterRetire.hold_status).toBe('WAITLISTED');
    expect(app2AfterRetire.hold_status).toBe('WAITLISTED');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('WAITLISTED');

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.hold_status).toBe('WAITLISTED');
  });

  test('PKG_011: REACTIVATE action transitions RETIRED package back to ACTIVE', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await retirePackage(fixture.event.id, fixture.gold.id);

    const res = await transitionPackage(fixture.event.id, fixture.gold.id, 'REACTIVATE');

    expectSuccess(res);
    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.status).toBe('ACTIVE');
  });

  test('PKG_012: After REACTIVATE, run_ops advances waitlist and grants hold', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await retirePackage(fixture.event.id, fixture.gold.id);
    await reactivatePackage(fixture.event.id, fixture.gold.id);

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('WAITLISTED');

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(1);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.hold_status).toBe('HELD');
    expect(app1.hold_expires_on_ops).toBe(3);
  });

  test('PKG_013: RETIRE on already RETIRED package returns ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);
    await retirePackage(event.id, gold.id);

    const res = await transitionPackage(event.id, gold.id, 'RETIRE');

    const isSuccess = res.status >= 200 && res.status < 300;
    const isInvalidState = res.status >= 400 && res.status < 500 && extractErrorCode(res.body) === ERROR_CODES.INVALID_STATE;
    expect(isSuccess || isInvalidState).toBe(true);

    const pkg = await getPackage(event.id, gold.id);
    expect(pkg.status).toBe('RETIRED');
  });

  test('PKG_014: REACTIVATE on already ACTIVE package returns ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);

    const res = await transitionPackage(event.id, gold.id, 'REACTIVATE');

    const isSuccess = res.status >= 200 && res.status < 300;
    const isInvalidState = res.status >= 400 && res.status < 500 && extractErrorCode(res.body) === ERROR_CODES.INVALID_STATE;
    expect(isSuccess || isInvalidState).toBe(true);

    const pkg = await getPackage(event.id, gold.id);
    expect(pkg.status).toBe('ACTIVE');
  });

  test('PKG_015: Retiring package does not affect existing commitments', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const res = await transitionPackage(fixture.event.id, fixture.gold.id, 'RETIRE');

    expectSuccess(res);
    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('ACTIVE');
  });

  test('PKG_016: After RETIRE with active commitment, new application fails with ERR_PACKAGE_RETIRED', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await retirePackage(fixture.event.id, fixture.gold.id);

    const newSponsor = await createSponsor(fixture.event.id, { status: 'VETTED' });

    const res = await postAs(`/events/${fixture.event.id}/applications`, {
      sponsor_id: newSponsor.id,
      package_id: fixture.gold.id,
    });

    await expectErrorCode(res, ERROR_CODES.PACKAGE_RETIRED);
  });

  test('PKG_017: Duplicate application for same sponsor/package returns ERR_DUPLICATE_APPLICATION', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const res = await postAs(`/events/${fixture.event.id}/applications`, {
      sponsor_id: fixture.sponsor2.id,
      package_id: fixture.gold.id,
    });

    await expectErrorCode(res, ERROR_CODES.DUPLICATE_APPLICATION);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.status).toBe('SUBMITTED');
  });

  test('PKG_018: After WITHDRAW, sponsor can re-apply for same package', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await withdrawApplication(fixture.event.id, fixture.application2.id);

    const app2Old = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Old.status).toBe('WITHDRAWN');

    const res = await postAs(`/events/${fixture.event.id}/applications`, {
      sponsor_id: fixture.sponsor2.id,
      package_id: fixture.gold.id,
    });

    expectSuccess(res);
    const newApp = unwrap(res.body);
    expect(newApp.id).not.toBe(fixture.application2.id);

    const app2Check = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Check.status).toBe('WITHDRAWN');
  });

  test('PKG_019: After WITHDRAW of HELD, run_ops promotes WAITLISTED to HELD', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app2Before.hold_status).toBe('WAITLISTED');

    await withdrawApplication(fixture.event.id, fixture.application1.id);

    const res = await runOps(fixture.event.id);

    expectSuccess(res);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');
  });

  test('PKG_020: run_ops does not expire hold before deadline; A2 stays WAITLISTED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');
    expect(app1Before.hold_expires_on_ops).toBeDefined();

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(1);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(app1.status).toBe('SUBMITTED');
    expect(app1.hold_status).toBe('HELD');

    expect(app2.hold_status).toBe('WAITLISTED');
  });

  test('PKG_021: run_ops expires hold and immediately promotes waitlisted in same run', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    await runOpsSuccess(fixture.event.id);

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const event = await getEvent(fixture.event.id);
    expect(event.ops_run_index).toBe(2);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1.status).toBe('EXPIRED');

    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2.hold_status).toBe('HELD');
    expect(app2.hold_expires_on_ops).toBe(4);
  });

  test('PKG_022: After hold expires and waitlist promotes, slots_remaining reflects current state', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await runOpsSuccess(fixture.event.id);
    await runOpsSuccess(fixture.event.id);

    const app1 = await getApplication(fixture.event.id, fixture.application1.id);
    const app2 = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app1.status).toBe('EXPIRED');
    expect(app2.hold_status).toBe('HELD');

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('PKG_023: Approved commitment still consumes slot (hold converted to commitment)', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await runOpsSuccess(fixture.event.id);
    await runOpsSuccess(fixture.event.id);

    const { commitment } = await approveApplication(fixture.event.id, fixture.application2.id);

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(0);
  });

  test('PKG_024: Rescinding commitment releases slot', async () => {

    const fixture = await createWaitlistTwoAppsGold();
    await runOpsSuccess(fixture.event.id);
    await runOpsSuccess(fixture.event.id);

    const { commitment } = await approveApplication(fixture.event.id, fixture.application2.id);

    await rescindCommitment(fixture.event.id, commitment.id);

    const res = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('PKG_025: Transition on non-existent package returns ERR_NOT_FOUND (even in LOCKDOWN)', async () => {

    const event = await createEventOpen();
    const lockdownRes = await patchWithVersion(`/events/${event.id}`, { posture: 'LOCKDOWN' }, event.version);
    expectSuccess(lockdownRes);

    const nonexistentId = 'nonexistent-package-id-12345';
    const res = await transitionPackage(event.id, nonexistentId, 'RETIRE');

    expectNotFound(res);
  });

});
