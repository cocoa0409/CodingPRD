import {
  postAs,
  patchAs,
  patchWithVersion,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  expectEventLockdown,
  expectInvalidState,
  expectVersionConflict,
  expectPreconditionRequired,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEvent,
  createEventDraft,
  createEventOpen,
  getEvent,
  updateEvent,
  runOps,
  runOpsSuccess,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  countersignCommitment,
  createClaim,
  finalizeClaim,
  transitionApplication,
  transitionClaim,
  getCommitment,
  createDraftApplicationVettedGold,
  createSubmittedHeldApplicationVettedGold,
  createActiveWithFinalizedSpotlight,
  createTwoFinalizedSpotlightsEventFull,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 1: Event & Posture Tests', () => {

  test('EVENT_001: POST /events with name and spotlight_slot_count creates DRAFT event', async () => {

    const res = await postAs('/events', {
      name: uniqueId('E1'),
      spotlight_slot_count: 2,
    });

    expectSuccess(res);
    const event = unwrap(res.body);
    expect(event.posture).toBe('DRAFT');
    expect(event.ops_run_index).toBe(0);
    expect(event.spotlight_slots_remaining).toBe(2);

    expect(typeof event.version).toBe('number');
    expect(event.version).toBeGreaterThan(0);
  });

  test('EVENT_002: PATCH posture to OPEN with If-Match succeeds', async () => {

    const event = await createEventDraft();
    const initialVersion = event.version;

    const res = await patchWithVersion(`/events/${event.id}`, { posture: 'OPEN' }, initialVersion);

    expectSuccess(res);
    const updated = await getEvent(event.id);
    expect(updated.posture).toBe('OPEN');
    expect(updated.version).toBeGreaterThan(initialVersion);
  });

  test('EVENT_003: PATCH posture without If-Match returns ERR_PRECONDITION_REQUIRED', async () => {

    const event = await createEventDraft();
    const initialVersion = event.version;

    const res = await patchAs(`/events/${event.id}`, { posture: 'OPEN' });

    expectPreconditionRequired(res);
    const unchanged = await getEvent(event.id);
    expect(unchanged.posture).toBe('DRAFT');
    expect(unchanged.version).toBe(initialVersion);
  });

  test('EVENT_004: PATCH with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const event = await createEventDraft();
    const initialVersion = event.version;
    const patchRes = await patchWithVersion(`/events/${event.id}`, { posture: 'OPEN' }, initialVersion);
    expectSuccess(patchRes);

    const res = await patchWithVersion(`/events/${event.id}`, { spotlight_slot_count: 3 }, initialVersion);

    expectVersionConflict(res);
    const unchanged = await getEvent(event.id);
    expect(unchanged.spotlight_slot_count).toBe(2);
    expect(unchanged.version).toBeGreaterThan(initialVersion);
  });

  test('EVENT_005: PATCH posture from ARCHIVED back to OPEN returns ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();
    const archiveRes = await patchWithVersion(`/events/${event.id}`, { posture: 'ARCHIVED' }, event.version);
    expectSuccess(archiveRes);

    const archivedEvent = await getEvent(event.id);

    const res = await patchWithVersion(`/events/${event.id}`, { posture: 'OPEN' }, archivedEvent.version);

    expectInvalidState(res);
    const unchanged = await getEvent(event.id);
    expect(unchanged.posture).toBe('ARCHIVED');
  });

  test('EVENT_006: POST /events/:E/run_ops bumps ops_run_index', async () => {

    const event = await createEventOpen();

    const res = await runOps(event.id);

    expectSuccess(res);
    const updated = await getEvent(event.id);
    expect(updated.ops_run_index).toBe(1);
    expect(updated.version).toBeGreaterThan(event.version);
  });

  test('EVENT_008: SUBMIT during LOCKDOWN returns ERR_EVENT_LOCKDOWN', async () => {

    const fixture = await createDraftApplicationVettedGold();
    const lockdownRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      fixture.event.version
    );
    expectSuccess(lockdownRes);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'SUBMIT');

    expectEventLockdown(res);
    const appCheck = await getAs(`/events/${fixture.event.id}/applications/${fixture.application.id}`);
    expectSuccess(appCheck);
    const app = unwrap(appCheck.body);
    expect(app.status).toBe('DRAFT');
  });

  test('EVENT_009: WITHDRAW during LOCKDOWN succeeds and releases slot', async () => {

    const fixture = await createSubmittedHeldApplicationVettedGold();

    const currentEvent = await getEvent(fixture.event.id);
    const lockdownRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      currentEvent.version
    );
    expectSuccess(lockdownRes);

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'WITHDRAW');

    expectSuccess(res);
    const appCheck = await getAs(`/events/${fixture.event.id}/applications/${fixture.application.id}`);
    expectSuccess(appCheck);
    const app = unwrap(appCheck.body);
    expect(app.status).toBe('WITHDRAWN');

    const pkgCheck = await getAs(`/events/${fixture.event.id}/packages/${fixture.gold.id}`);
    expectSuccess(pkgCheck);
    const pkg = unwrap(pkgCheck.body);
    expect(pkg.slots_remaining).toBe(1);
  });

  test('EVENT_010: POST /events/:E/packages during LOCKDOWN returns ERR_EVENT_LOCKDOWN', async () => {

    const event = await createEventOpen();
    const lockdownRes = await patchWithVersion(`/events/${event.id}`, { posture: 'LOCKDOWN' }, event.version);
    expectSuccess(lockdownRes);

    const res = await postAs(`/events/${event.id}/packages`, {
      label: 'BRONZE',
      price_cents: 100000,
      slot_count: 1,
      included_benefits: [],
    });

    expectEventLockdown(res);
    const eventCheck = await getEvent(event.id);
    expect(eventCheck.posture).toBe('LOCKDOWN');
  });

  test('EVENT_011: PATCH spotlight_slot_count increases remaining slots', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const currentEvent = await getEvent(fixture.event.id);
    const finalizedSpotlightCount = 1;

    const res = await patchWithVersion(`/events/${fixture.event.id}`, { spotlight_slot_count: 3 }, currentEvent.version);

    expectSuccess(res);
    const updated = await getEvent(fixture.event.id);
    expect(updated.spotlight_slot_count).toBe(3);
    expect(updated.spotlight_slots_remaining).toBe(3 - finalizedSpotlightCount);
  });

  test('EVENT_012: PATCH spotlight_slot_count below finalized returns ERR_SPOTLIGHT_IN_USE', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const res = await patchWithVersion(`/events/${fixture.event.id}`, { spotlight_slot_count: 1 }, fixture.event.version);

    expectClientError(res);
    expect(extractErrorCode(res.body)).toBe(ERROR_CODES.SPOTLIGHT_IN_USE);
    const unchanged = await getEvent(fixture.event.id);
    expect(unchanged.spotlight_slot_count).toBe(2);
    expect(unchanged.spotlight_slots_remaining).toBe(0);
  });

  test('EVENT_013: VOID finalized spotlight claim releases slot to event', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    expect(fixture.event.spotlight_slots_remaining).toBe(0);

    const commitmentA = await getCommitment(fixture.event.id, fixture.commitmentA.id);
    const spotlightClaimA = commitmentA.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'FINALIZED');
    expect(spotlightClaimA).toBeDefined();

    const res = await transitionClaim(fixture.event.id, fixture.commitmentA.id, spotlightClaimA!.id, 'VOID');

    expectSuccess(res);
    const updated = await getEvent(fixture.event.id);
    expect(updated.spotlight_slots_remaining).toBe(1);
  });

  test('EVENT_014: After VOIDing spotlight, can reduce spotlight_slot_count', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();
    const commitmentA = await getCommitment(fixture.event.id, fixture.commitmentA.id);
    const spotlightClaimA = commitmentA.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'FINALIZED');
    expect(spotlightClaimA).toBeDefined();

    const voidRes = await transitionClaim(fixture.event.id, fixture.commitmentA.id, spotlightClaimA!.id, 'VOID');
    expectSuccess(voidRes);

    const eventAfterVoid = await getEvent(fixture.event.id);

    const res = await patchWithVersion(`/events/${fixture.event.id}`, { spotlight_slot_count: 1 }, eventAfterVoid.version);

    expectSuccess(res);
    const updated = await getEvent(fixture.event.id);
    expect(updated.spotlight_slot_count).toBe(1);
    expect(updated.spotlight_slots_remaining).toBe(0);
  });

  test('EVENT_015: run_ops works during ARCHIVED posture', async () => {

    const event = await createEventOpen();
    const archiveRes = await patchWithVersion(`/events/${event.id}`, { posture: 'ARCHIVED' }, event.version);
    expectSuccess(archiveRes);

    const res = await runOps(event.id);

    expectSuccess(res);
    const updated = await getEvent(event.id);
    expect(updated.ops_run_index).toBe(1);
    expect(updated.posture).toBe('ARCHIVED');
  });

  test('EVENT_016: LOCKDOWN to OPEN transitions work and bump version', async () => {

    const event = await createEventOpen();
    const initialVersion = event.version;
    const lockdownRes = await patchWithVersion(`/events/${event.id}`, { posture: 'LOCKDOWN' }, initialVersion);
    expectSuccess(lockdownRes);

    const lockedEvent = await getEvent(event.id);
    const openRes = await patchWithVersion(`/events/${event.id}`, { posture: 'OPEN' }, lockedEvent.version);
    expectSuccess(openRes);

    const res = await getAs(`/events/${event.id}`);

    expectSuccess(res);
    const updated = unwrap(res.body);
    expect(updated.posture).toBe('OPEN');

    expect(updated.version).toBeGreaterThan(lockedEvent.version);
  });

  test('EVENT_017: POST /events/:E/applications during LOCKDOWN returns ERR_EVENT_LOCKDOWN', async () => {

    const event = await createEventOpen();
    const pkg = await createPackage(event.id, {
      label: 'TEST',
      price_cents: 100000,
      slot_count: 1,
      included_benefits: [],
    });
    const sponsor = await createSponsor(event.id, { status: 'VETTED' });

    const currentEvent = await getEvent(event.id);
    const lockdownRes = await patchWithVersion(`/events/${event.id}`, { posture: 'LOCKDOWN' }, currentEvent.version);
    expectSuccess(lockdownRes);

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: pkg.id,
    });

    expectEventLockdown(res);
  });

  test('EVENT_018: run_ops works during DRAFT posture', async () => {

    const event = await createEventDraft();

    const res = await runOps(event.id);

    expectSuccess(res);
    const updated = await getEvent(event.id);
    expect(updated.ops_run_index).toBe(1);
  });

  test('EVENT_019: POST /events/:E/packages during ARCHIVED returns ERR_EVENT_LOCKDOWN', async () => {

    const event = await createEventOpen();
    const archiveRes = await patchWithVersion(`/events/${event.id}`, { posture: 'ARCHIVED' }, event.version);
    expectSuccess(archiveRes);

    const res = await postAs(`/events/${event.id}/packages`, {
      label: 'TEST',
      price_cents: 100000,
      slot_count: 1,
      included_benefits: [],
    });

    expectClientError(res);
    const code = extractErrorCode(res.body);
    expect([ERROR_CODES.EVENT_LOCKDOWN, ERROR_CODES.EVENT_NOT_OPEN]).toContain(code);

    const eventCheck = await getEvent(event.id);
    expect(eventCheck.posture).toBe('ARCHIVED');
  });

  test('EVENT_020: PATCH posture from OPEN to DRAFT returns ERR_INVALID_STATE', async () => {

    const event = await createEventOpen();

    const res = await patchWithVersion(`/events/${event.id}`, { posture: 'DRAFT' }, event.version);

    expectInvalidState(res);
    const unchanged = await getEvent(event.id);
    expect(unchanged.posture).toBe('OPEN');
  });

});
