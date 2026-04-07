import {
  postAs,
  patchWithVersion,
  putWithVersion,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  expectVersionConflict,
  expectNotFound,
  expectEventLockdown,
  expectEventNotOpen,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createEventDraft,
  getEvent,
  updateEvent,
  runOps,
  runOpsSuccess,
  createPackage,
  createSponsor,
  createApplication,
  getApplication,
  submitApplication,
  transitionApplication,
  transitionPackage,
  transitionCommitment,
  transitionClaim,
  getPackage,
  getSponsor,
  getCommitment,
  createActiveCommitmentVettedGold,
  createDraftApplicationVettedGold,
  createClaim,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';
import { v4 as uuidv4 } from 'uuid';

describe('Feature 8: Versioning (Headers, Precedence) Tests', () => {

  test('MATCH_001: PATCH /events/:E with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const event = await createEventDraft();
    const initialPosture = event.posture;

    const res = await patchWithVersion(`/events/${event.id}`, { posture: 'OPEN' }, 999);

    expectVersionConflict(res);
    const unchanged = await getEvent(event.id);
    expect(unchanged.posture).toBe('DRAFT');
  });

  test('MATCH_002: PATCH /events/:E/sponsors/:S with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const event = await createEventOpen();
    const sponsor = await createSponsor(event.id, { status: 'PROSPECT' });

    const res = await patchWithVersion(
      `/events/${event.id}/sponsors/${sponsor.id}`,
      { status: 'VETTED' },
      999
    );

    expectVersionConflict(res);
    const unchanged = await getSponsor(event.id, sponsor.id);
    expect(unchanged.status).toBe('PROSPECT');
  });

  test('MATCH_003: PUT /events/:E/applications/:A with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fixture = await createDraftApplicationVettedGold();
    const originalNote = fixture.application.note;

    const res = await putWithVersion(
      `/events/${fixture.event.id}/applications/${fixture.application.id}`,
      { note: 'x' },
      999
    );

    expectVersionConflict(res);
    const unchanged = await getApplication(fixture.event.id, fixture.application.id);
    expect(unchanged.note).toBe(originalNote);
  });

  test('ERR_002: POST /events/:missing/run_ops returns ERR_NOT_FOUND', async () => {

    const missingId = uuidv4();
    const res = await postAs(`/events/${missingId}/run_ops`, {});

    expectNotFound(res);
  });

  test('ERR_003: GET /events/:E/packages/:missing returns ERR_NOT_FOUND', async () => {

    const event = await createEventOpen();

    const missingPkgId = uuidv4();
    const res = await getAs(`/events/${event.id}/packages/${missingPkgId}`);

    expectNotFound(res);
  });

  test('ERR_004: POST /events/:E/packages/:missing/transition returns ERR_NOT_FOUND', async () => {

    const event = await createEventOpen();

    const missingPkgId = uuidv4();
    const res = await postAs(`/events/${event.id}/packages/${missingPkgId}/transition`, {
      action: 'RETIRE',
    });

    expectNotFound(res);
  });

  test('ERR_005: POST /events/:E/run_ops during LOCKDOWN succeeds and increments ops_run_index', async () => {

    const event = await createEventOpen();
    const lockdownRes = await patchWithVersion(
      `/events/${event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(lockdownRes);

    const lockedEvent = await getEvent(event.id);
    const opsIndexBefore = lockedEvent.ops_run_index;

    const res = await runOps(event.id);

    expectSuccess(res);
    const updated = await getEvent(event.id);
    expect(updated.ops_run_index).toBe(opsIndexBefore + 1);
  });

  test('ERR_006: POST /events/:E/applications during LOCKDOWN returns ERR_EVENT_LOCKDOWN', async () => {

    const event = await createEventOpen();
    const pkg = await createPackage(event.id, {
      label: uniqueId('PKG'),
      price_cents: 10000,
      slot_count: 1,
      included_benefits: [],
    });
    const sponsor = await createSponsor(event.id, { status: 'VETTED' });

    const currentEvent = await getEvent(event.id);
    const lockdownRes = await patchWithVersion(
      `/events/${event.id}`,
      { posture: 'LOCKDOWN' },
      currentEvent.version
    );
    expectSuccess(lockdownRes);

    const res = await postAs(`/events/${event.id}/applications`, {
      sponsor_id: sponsor.id,
      package_id: pkg.id,
    });

    expectEventLockdown(res);
  });

  test('ERR_007: POST /events/:E/packages during DRAFT succeeds', async () => {

    const event = await createEventDraft();

    const res = await postAs(`/events/${event.id}/packages`, {
      label: uniqueId('X'),
      price_cents: 1,
      slot_count: 1,
      included_benefits: [],
    });

    expectSuccess(res);
    const pkg = unwrap(res.body);
    expect(pkg.label).toContain('X');
    expect(pkg.status).toBe('ACTIVE');
  });

  test('ERR_008: SUBMIT application during DRAFT event returns ERR_EVENT_NOT_OPEN', async () => {

    const event = await createEventDraft();

    const pkg = await createPackage(event.id, {
      label: uniqueId('X'),
      price_cents: 1,
      slot_count: 1,
      included_benefits: [],
    });

    const sponsor = await createSponsor(event.id, {
      display_name: 'S',
      legal_name: 'S LLC',
      primary_contact_email: `${uniqueId('s')}@s.test`,
      status: 'VETTED',
    });

    const app = await createApplication(event.id, {
      sponsor_id: sponsor.id,
      package_id: pkg.id,
    });

    const res = await transitionApplication(event.id, app.id, 'SUBMIT');

    expectEventNotOpen(res);
    const unchanged = await getApplication(event.id, app.id);
    expect(unchanged.status).toBe('DRAFT');
  });

  test('ERR_009: POST /events/:E/packages/:P/transition with action="BOGUS" returns ERR_BAD_REQUEST', async () => {

    const event = await createEventOpen();
    const pkg = await createPackage(event.id, {
      label: uniqueId('X'),
      price_cents: 1,
      slot_count: 1,
      included_benefits: [],
    });
    const initialStatus = pkg.status;

    const res = await postAs(`/events/${event.id}/packages/${pkg.id}/transition`, {
      action: 'BOGUS',
    });

    expectClientError(res);
    expect(extractErrorCode(res.body)).toBe(ERROR_CODES.BAD_REQUEST);
    const unchanged = await getPackage(event.id, pkg.id);
    expect(unchanged.status).toBe(initialStatus);
  });

  test('ERR_010: POST /events/:E/applications/:A/transition with action="BOGUS" returns ERR_BAD_REQUEST', async () => {

    const fixture = await createDraftApplicationVettedGold();
    const initialStatus = fixture.application.status;

    const res = await transitionApplication(fixture.event.id, fixture.application.id, 'BOGUS' as any);

    expectClientError(res);
    expect(extractErrorCode(res.body)).toBe(ERROR_CODES.BAD_REQUEST);
    const unchanged = await getApplication(fixture.event.id, fixture.application.id);
    expect(unchanged.status).toBe(initialStatus);
  });

  test('ERR_011: POST /events/:E/commitments/:C/transition with action="BOGUS" returns ERR_BAD_REQUEST', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const initialStatus = fixture.commitment.status;

    const res = await transitionCommitment(fixture.event.id, fixture.commitment.id, 'BOGUS' as any);

    expectClientError(res);
    expect(extractErrorCode(res.body)).toBe(ERROR_CODES.BAD_REQUEST);
    const unchanged = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(unchanged.status).toBe(initialStatus);
  });

  test('ERR_012: POST /events/:E/commitments/:C/claims/:CL/transition with action="BOGUS" returns ERR_BAD_REQUEST', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 1,
    });
    const initialStatus = claim.status;

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'BOGUS' as any);

    expectClientError(res);
    expect(extractErrorCode(res.body)).toBe(ERROR_CODES.BAD_REQUEST);

    const updatedCommitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const unchangedClaim = updatedCommitment.claims.find(c => c.id === claim.id);
    expect(unchangedClaim).toBeDefined();
    expect(unchangedClaim!.status).toBe(initialStatus);
  });

});
