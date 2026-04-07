import { post, postWithEtag, get } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  getData,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createConsignment,
  getDockRequest,
  getHub,
  getConsignment,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  completeAndGet,
  batchSchedule,
  createConsignmentAtHub,
  createPlannedConsignment,
  runOps,
  createHold,
  getHold,
  clearHold,
  cancelDockRequest,
  voidDockRequest,
  submitDockRequest,
  completeDockRequest,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  CONSIGNMENT_STATUSES,
  POSTURES,
  HOLD_KINDS,
  HOLD_STATUSES,
} from '../../../test-helpers/constants';

describe('Deterministic Contention Tests', () => {

  test('CONCUR_001: Same priority - sequence (creation order) determines scheduling, not caller-provided order', async () => {

    const hub = await createHub(undefined, 5);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, consignment1.id, 4, PRIORITIES.STANDARD);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, consignment2.id, 4, PRIORITIES.STANDARD);

    expect(dr1.sequence).toBeLessThan(dr2.sequence);

    dr1 = await submitAndGet(hub.id, dr1);
    dr2 = await submitAndGet(hub.id, dr2);

    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
    expect(dr2.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr2.id, dr1.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids.length).toBe(1);
    expect(scheduleResult.rejected.length).toBe(1);

    expect(scheduleResult.scheduled_ids[0]).toBe(dr1.id);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr2.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(4);
  });

  test('SEQ_001: Sequence is monotone within a hub', async () => {

    const hub = await createHub(undefined, 20);

    const c1 = await createConsignment(hub.id, {
      reference: 'S1',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    const c2 = await createConsignment(hub.id, {
      reference: 'S2',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    const c3 = await createConsignment(hub.id, {
      reference: 'S3',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });

    const dr1 = await createInboundDraft(hub.id, c1.id, 1, PRIORITIES.STANDARD);
    const dr2 = await createInboundDraft(hub.id, c2.id, 1, PRIORITIES.STANDARD);
    const dr3 = await createInboundDraft(hub.id, c3.id, 1, PRIORITIES.STANDARD);

    const [dr1Final, dr2Final, dr3Final, hubFinal] = await Promise.all([
      getDockRequest(hub.id, dr1.id),
      getDockRequest(hub.id, dr2.id),
      getDockRequest(hub.id, dr3.id),
      getHub(hub.id),
    ]);

    expect(dr1Final.sequence).toBeLessThan(dr2Final.sequence);
    expect(dr2Final.sequence).toBeLessThan(dr3Final.sequence);

    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
    expect(dr3Final.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('CONCUR_002: Different priorities - EXPEDITE scheduled before DEFERRED regardless of creation order', async () => {

    const hub = await createHub(undefined, 5);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, consignment1.id, 5, PRIORITIES.DEFERRED);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 2,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, consignment2.id, 2, PRIORITIES.EXPEDITE);

    expect(dr1.priority).toBe(PRIORITIES.DEFERRED);
    expect(dr2.priority).toBe(PRIORITIES.EXPEDITE);

    expect(dr1.sequence).toBeLessThan(dr2.sequence);

    dr1 = await submitAndGet(hub.id, dr1);
    dr2 = await submitAndGet(hub.id, dr2);

    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
    expect(dr2.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr1.id, dr2.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids.length).toBe(1);
    expect(scheduleResult.rejected.length).toBe(1);

    expect(scheduleResult.scheduled_ids[0]).toBe(dr2.id);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(2);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr1.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('CONCUR_003: Concurrent submit attempts - exactly one wins with ERR_CONSIGNMENT_BUSY', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    const h0 = await getHub(hub.id);

    const dr1 = await createInboundDraft(hub.id, consignment.id, 3, PRIORITIES.STANDARD);
    const dr2 = await createInboundDraft(hub.id, consignment.id, 3, PRIORITIES.STANDARD);

    const [res1, res2] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr1.id}/submit`, {}, dr1.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr2.id}/submit`, {}, dr2.etag),
    ]);

    const success1 = res1.status >= 200 && res1.status < 300;
    const success2 = res2.status >= 200 && res2.status < 300;

    expect(success1 !== success2).toBe(true);

    const failedRes = success1 ? res2 : res1;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_CONSIGNMENT_BUSY);

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    const dr2Final = await getDockRequest(hub.id, dr2.id);

    const statuses = [dr1Final.status, dr2Final.status];
    expect(statuses.filter(s => s === DOCK_REQUEST_STATUSES.SUBMITTED).length).toBe(1);
    expect(statuses.filter(s => s === DOCK_REQUEST_STATUSES.DRAFT).length).toBe(1);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubFinal.staging_in_use_units).toBe(h0.staging_in_use_units);
  });

  test('CONCUR_004: Concurrent batch_schedule - capacity contention', async () => {

    const hub = await createHub(undefined, 5);

    const c1 = await createConsignment(hub.id, { reference: 'A', declared_units: 4, commodity: COMMODITIES.GENERAL });
    const c2 = await createConsignment(hub.id, { reference: 'B', declared_units: 4, commodity: COMMODITIES.GENERAL });

    let dr1 = await createInboundDraft(hub.id, c1.id, 4, PRIORITIES.STANDARD);
    let dr2 = await createInboundDraft(hub.id, c2.id, 4, PRIORITIES.STANDARD);

    dr1 = await submitAndGet(hub.id, dr1);
    dr2 = await submitAndGet(hub.id, dr2);

    await Promise.all([
      post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr1.id] }),
      post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr2.id] }),
    ]);

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    const dr2Final = await getDockRequest(hub.id, dr2.id);

    const statuses = [dr1Final.status, dr2Final.status];
    expect(statuses.filter(s => s === DOCK_REQUEST_STATUSES.SCHEDULED).length).toBe(1);
    expect(statuses.filter(s => s === DOCK_REQUEST_STATUSES.SUBMITTED).length).toBe(1);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(4);
    expect(hubFinal.staging_free_units).toBe(1);
    expect(hubFinal.posture).toBe(POSTURES.CONGESTED);
  });

  test('CONCUR_005: Concurrent completions with over-receipt - capacity contention', async () => {

    const hub = await createHub(undefined, 20);

    const ca = await createConsignment(hub.id, { reference: 'A', declared_units: 10, commodity: COMMODITIES.GENERAL });
    const cb = await createConsignment(hub.id, { reference: 'B', declared_units: 6, commodity: COMMODITIES.GENERAL });

    let dra = await createInboundDraft(hub.id, ca.id, 10, PRIORITIES.STANDARD);
    let drb = await createInboundDraft(hub.id, cb.id, 6, PRIORITIES.STANDARD);
    dra = await submitAndGet(hub.id, dra);
    drb = await submitAndGet(hub.id, drb);

    await batchSchedule(hub.id, [dra.id, drb.id]);
    dra = await getDockRequest(hub.id, dra.id);
    drb = await getDockRequest(hub.id, drb.id);

    const hubSetup = await getHub(hub.id);
    expect(hubSetup.staging_reserved_units).toBe(16);
    expect(hubSetup.staging_free_units).toBe(4);

    const [resA, resB] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dra.id}/complete`, { actual_units: 14 }, dra.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${drb.id}/complete`, { actual_units: 10 }, drb.etag),
    ]);

    const successA = resA.status >= 200 && resA.status < 300;
    const successB = resB.status >= 200 && resB.status < 300;

    expect(successA !== successB).toBe(true);

    const failedRes = successA ? resB : resA;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubFinal.staging_free_units).toBe(0);

    const draFinal = await getDockRequest(hub.id, dra.id);
    const drbFinal = await getDockRequest(hub.id, drb.id);

    if (successA) {
      expect(draFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
      expect(drbFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
      expect(hubFinal.staging_in_use_units).toBe(14);
      expect(hubFinal.staging_reserved_units).toBe(6);
    } else {
      expect(drbFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
      expect(draFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
      expect(hubFinal.staging_in_use_units).toBe(10);
      expect(hubFinal.staging_reserved_units).toBe(10);
    }
  });

  test('CONCUR_006: Concurrent cancel vs complete - exactly one wins with ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    let dr = await createInboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const [cancelRes, completeRes] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/cancel`, {}, dr.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/complete`, { actual_units: 10 }, dr.etag),
    ]);

    const cancelSuccess = cancelRes.status >= 200 && cancelRes.status < 300;
    const completeSuccess = completeRes.status >= 200 && completeRes.status < 300;

    expect(cancelSuccess !== completeSuccess).toBe(true);

    const failedRes = cancelSuccess ? completeRes : cancelRes;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_VERSION_CONFLICT);

    const drFinal = await getDockRequest(hub.id, dr.id);
    const cFinal = await getConsignment(hub.id, consignment.id);
    const hubFinal = await getHub(hub.id);

    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20 - hubFinal.staging_in_use_units);

    if (cancelSuccess) {
      expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);
      expect(cFinal.units_on_hand).toBe(0);
      expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
      expect(hubFinal.staging_in_use_units).toBe(0);
    } else {
      expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
      expect(cFinal.units_on_hand).toBe(10);
      expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
      expect(hubFinal.staging_in_use_units).toBe(10);
    }
  });

  test('CONCUR_007: Concurrent void vs complete - exactly one wins with ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    let dr = await createInboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    const [voidRes, completeRes] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/void`, {}, dr.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/complete`, { actual_units: 10 }, dr.etag),
    ]);

    const voidSuccess = voidRes.status >= 200 && voidRes.status < 300;
    const completeSuccess = completeRes.status >= 200 && completeRes.status < 300;

    expect(voidSuccess !== completeSuccess).toBe(true);

    const failedRes = voidSuccess ? completeRes : voidRes;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_VERSION_CONFLICT);

    const drFinal = await getDockRequest(hub.id, dr.id);
    const cFinal = await getConsignment(hub.id, consignment.id);
    const hubFinal = await getHub(hub.id);

    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20 - hubFinal.staging_in_use_units);

    if (voidSuccess) {
      expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);
      expect(cFinal.units_on_hand).toBe(0);
      expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
      expect(hubFinal.staging_in_use_units).toBe(0);
    } else {
      expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
      expect(cFinal.units_on_hand).toBe(10);
      expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
      expect(hubFinal.staging_in_use_units).toBe(10);
    }
  });

  test('CONCUR_010: Concurrent run_ops vs batch_schedule race', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    let dr = await createInboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);

    await runOps(hub.id);
    const h1 = await getHub(hub.id);
    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await Promise.all([
      postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h1.etag),
      post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr.id] }),
    ]);

    const drFinal = await getDockRequest(hub.id, dr.id);
    const hubFinal = await getHub(hub.id);

    expect(hubFinal.ops_run_index).toBeGreaterThanOrEqual(h1.ops_run_index + 1);

    if (drFinal.status === DOCK_REQUEST_STATUSES.EXPIRED) {
      expect(hubFinal.staging_reserved_units).toBe(0);
      expect(hubFinal.staging_in_use_units).toBe(0);
      expect(hubFinal.staging_free_units).toBe(20);
    } else {
      expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
      expect(hubFinal.staging_reserved_units).toBe(10);
      expect(hubFinal.staging_in_use_units).toBe(0);
      expect(hubFinal.staging_free_units).toBe(10);
    }

    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('CONCUR_011: Concurrent batch_schedule vs hold creation - hold gating wins', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    let dr = await createOutboundDraft(hub.id, consignment.id, 4, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);

    const c0 = await getConsignment(hub.id, consignment.id);
    const h0 = await getHub(hub.id);

    const [_schedRes, holdRes] = await Promise.all([
      post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr.id] }),
      post(`/hubs/${hub.id}/holds`, { consignment_id: consignment.id, kind: HOLD_KINDS.DOCS, note: 'docs' }),
    ]);

    const hold = getData(holdRes);
    const drAfter = await getDockRequest(hub.id, dr.id);
    const holdFinal = await getHold(hub.id, hold.id);

    expect(holdFinal.status).toBe(HOLD_STATUSES.OPEN);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      drAfter.etag
    );
    expect(completeRes.status).toBeGreaterThanOrEqual(400);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const cFinal = await getConsignment(hub.id, consignment.id);
    expect(cFinal.units_on_hand).toBe(c0.units_on_hand);
    expect(cFinal.status).toBe(c0.status);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubFinal.staging_reserved_units).toBe(0);
  });

  test('CONCUR_012: Concurrent duplicate completions - exactly one wins', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    let dr = await createInboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    const h0 = await getHub(hub.id);

    const [res1, res2] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/complete`, { actual_units: 10 }, dr.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/complete`, { actual_units: 10 }, dr.etag),
    ]);

    const success1 = res1.status >= 200 && res1.status < 300;
    const success2 = res2.status >= 200 && res2.status < 300;

    expect(success1 !== success2).toBe(true);

    const failedRes = success1 ? res2 : res1;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_VERSION_CONFLICT);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const cFinal = await getConsignment(hub.id, consignment.id);
    expect(cFinal.units_on_hand).toBe(10);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(10);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(10);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
    expect(hubFinal.ops_run_index).toBe(h0.ops_run_index);
  });

  test('CONCUR_013: Concurrent duplicate voids - exactly one wins', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    dr = await completeAndGet(hub.id, dr, 4);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const cAfter = await getConsignment(hub.id, consignment.id);
    expect(cAfter.units_on_hand).toBe(6);

    const h0 = await getHub(hub.id);

    const [res1, res2] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/void`, {}, dr.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/void`, {}, dr.etag),
    ]);

    const success1 = res1.status >= 200 && res1.status < 300;
    const success2 = res2.status >= 200 && res2.status < 300;

    expect(success1 !== success2).toBe(true);

    const failedRes = success1 ? res2 : res1;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_VERSION_CONFLICT);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const cFinal = await getConsignment(hub.id, consignment.id);
    expect(cFinal.units_on_hand).toBe(10);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(10);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(10);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('CONCUR_014: Concurrent clear hold vs batch_schedule', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    let dr = await createOutboundDraft(hub.id, consignment.id, 4, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const hold0 = await getHold(hub.id, hold.id);
    const h0 = await getHub(hub.id);

    await Promise.all([
      postWithEtag(`/hubs/${hub.id}/holds/${hold.id}/clear`, {}, hold0.etag),
      post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr.id] }),
    ]);

    const drFinal = await getDockRequest(hub.id, dr.id);
    const holdFinal = await getHold(hub.id, hold.id);
    const hubFinal = await getHub(hub.id);

    expect(holdFinal.status).toBe(HOLD_STATUSES.CLEARED);

    expect([DOCK_REQUEST_STATUSES.SUBMITTED, DOCK_REQUEST_STATUSES.SCHEDULED]).toContain(drFinal.status);
    expect(drFinal.direction).toBe('OUTBOUND');

    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(10);
    expect(hubFinal.staging_free_units).toBe(10);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('CONCUR_015: Concurrent duplicate run_ops - exactly one wins', async () => {

    const hub = await createHub(undefined, 20);
    const h0 = await getHub(hub.id);

    const [res1, res2] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag),
      postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag),
    ]);

    const success1 = res1.status >= 200 && res1.status < 300;
    const success2 = res2.status >= 200 && res2.status < 300;

    expect(success1 !== success2).toBe(true);

    const failedRes = success1 ? res2 : res1;
    const failedErrorCode = extractErrorCode(failedRes.body);
    expect(failedErrorCode).toBe(ERROR_CODES.ERR_VERSION_CONFLICT);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.ops_run_index).toBe(h0.ops_run_index + 1);
    expect(hubFinal.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubFinal.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubFinal.staging_free_units).toBe(h0.staging_free_units);
    expect(hubFinal.posture).toBe(h0.posture);
  });

  test('CONCUR_016: Concurrent batch_schedule vs cancel', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createPlannedConsignment(hub.id, 10);
    let dr = await createInboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);

    const h0 = await getHub(hub.id);

    await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr.id] }, h0.etag),
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/cancel`, {}, dr.etag),
    ]);

    const drFinal = await getDockRequest(hub.id, dr.id);
    const cFinal = await getConsignment(hub.id, consignment.id);
    const hubFinal = await getHub(hub.id);

    expect([DOCK_REQUEST_STATUSES.SCHEDULED, DOCK_REQUEST_STATUSES.CANCELLED]).toContain(drFinal.status);

    expect(cFinal.units_on_hand).toBe(0);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(hubFinal.staging_in_use_units).toBe(0);

    if (drFinal.status === DOCK_REQUEST_STATUSES.SCHEDULED) {
      expect(hubFinal.staging_reserved_units).toBe(10);
      expect(hubFinal.staging_free_units).toBe(10);
    } else {
      expect(hubFinal.staging_reserved_units).toBe(0);
      expect(hubFinal.staging_free_units).toBe(20);
    }
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('CONCUR_017: Concurrent submit vs hold creation', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const dr = await createOutboundDraft(hub.id, consignment.id, 4, PRIORITIES.STANDARD);

    const c0 = await getConsignment(hub.id, consignment.id);
    const h0 = await getHub(hub.id);

    const [_submitRes, holdRes] = await Promise.all([
      postWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}/submit`, {}, dr.etag),
      post(`/hubs/${hub.id}/holds`, { consignment_id: consignment.id, kind: HOLD_KINDS.DOCS, note: 'docs' }),
    ]);

    const hold = getData(holdRes);
    const holdFinal = await getHold(hub.id, hold.id);
    const drFinal = await getDockRequest(hub.id, dr.id);
    const cFinal = await getConsignment(hub.id, consignment.id);
    const hubFinal = await getHub(hub.id);

    expect(holdFinal.status).toBe(HOLD_STATUSES.OPEN);

    expect([DOCK_REQUEST_STATUSES.DRAFT, DOCK_REQUEST_STATUSES.ON_HOLD]).toContain(drFinal.status);

    expect(cFinal.units_on_hand).toBe(c0.units_on_hand);
    expect(cFinal.status).toBe(c0.status);

    expect(hubFinal.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubFinal.staging_reserved_units).toBe(0);
  });

  test('SCHEDULE_012: CONGESTED blocks inbound submissions over cap', async () => {

    const hub = await createHub(undefined, 20);

    const c1 = await createConsignment(hub.id, { reference: 'R16', declared_units: 16, commodity: COMMODITIES.GENERAL });
    let dr1 = await createInboundDraft(hub.id, c1.id, 16, PRIORITIES.STANDARD);
    dr1 = await submitAndGet(hub.id, dr1);
    await batchSchedule(hub.id, [dr1.id]);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    expect(hubCheck.staging_reserved_units).toBe(16);
    expect(hubCheck.staging_free_units).toBe(4);

    const c2 = await createConsignment(hub.id, { reference: 'TRY2', declared_units: 10, commodity: COMMODITIES.GENERAL });
    const dr2 = await createInboundDraft(hub.id, c2.id, 2, PRIORITIES.STANDARD);

    const res = await postWithEtag(`/hubs/${hub.id}/dock_requests/${dr2.id}/submit`, {}, dr2.etag);

    await expectErrorCode(res, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.posture).toBe(POSTURES.CONGESTED);
    expect(hubFinal.staging_free_units).toBe(4);
    expect(hubFinal.staging_reserved_units).toBe(16);
  });

  test('SCHEDULE_013: Scheduling rejects when capacity insufficient', async () => {

    const hub = await createHub(undefined, 20);

    const cBig = await createConsignment(hub.id, { reference: 'BIG', declared_units: 10, commodity: COMMODITIES.GENERAL });
    let drBig = await createInboundDraft(hub.id, cBig.id, 10, PRIORITIES.STANDARD);
    drBig = await submitAndGet(hub.id, drBig);

    const cFill = await createConsignment(hub.id, { reference: 'FILL16', declared_units: 16, commodity: COMMODITIES.GENERAL });
    let drFill = await createInboundDraft(hub.id, cFill.id, 16, PRIORITIES.STANDARD);
    drFill = await submitAndGet(hub.id, drFill);
    drFill = await scheduleAndGet(hub.id, drFill);
    drFill = await completeAndGet(hub.id, drFill, 16);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    expect(hubCheck.staging_in_use_units).toBe(16);
    expect(hubCheck.staging_free_units).toBe(4);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [drBig.id] });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: drBig.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    const drBigFinal = await getDockRequest(hub.id, drBig.id);
    expect(drBigFinal.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(16);
    expect(hubFinal.staging_free_units).toBe(4);
    expect(hubFinal.posture).toBe(POSTURES.CONGESTED);
  });

  test('SCHEDULE_014: Batch scheduling skips over-capacity and schedules fit', async () => {

    const hub = await createHub(undefined, 5);

    const c1 = await createConsignment(hub.id, { reference: 'TOO6', declared_units: 6, commodity: COMMODITIES.GENERAL });
    const c2 = await createConsignment(hub.id, { reference: 'FIT5', declared_units: 5, commodity: COMMODITIES.GENERAL });

    let dr1 = await createInboundDraft(hub.id, c1.id, 6, PRIORITIES.STANDARD);
    let dr2 = await createInboundDraft(hub.id, c2.id, 5, PRIORITIES.STANDARD);
    dr1 = await submitAndGet(hub.id, dr1);
    dr2 = await submitAndGet(hub.id, dr2);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr1.id, dr2.id] });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr1.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    expect(scheduleResult.scheduled_ids).toContain(dr2.id);

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(5);
    expect(hubFinal.staging_free_units).toBe(0);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('SCHEDULE_016: LOCKDOWN recovery allows inbound scheduling', async () => {

    const hub = await createHub(undefined, 20);

    const cSmall = await createConsignment(hub.id, { reference: 'SMALL5', declared_units: 5, commodity: COMMODITIES.GENERAL });
    let drSmall = await createInboundDraft(hub.id, cSmall.id, 5, PRIORITIES.STANDARD);
    drSmall = await submitAndGet(hub.id, drSmall);

    const cFill = await createConsignment(hub.id, { reference: 'FILL20', declared_units: 20, commodity: COMMODITIES.GENERAL });
    let drFill = await createInboundDraft(hub.id, cFill.id, 20, PRIORITIES.STANDARD);
    drFill = await submitAndGet(hub.id, drFill);
    drFill = await scheduleAndGet(hub.id, drFill);
    drFill = await completeAndGet(hub.id, drFill, 20);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubCheck.staging_free_units).toBe(0);
    expect(hubCheck.staging_in_use_units).toBe(20);

    const res1 = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [drSmall.id] });
    expectSuccess(res1);
    const result1 = getData(res1);
    expect(result1.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: drSmall.id,
          error_code: ERROR_CODES.ERR_POSTURE_LOCKDOWN,
        }),
      ])
    );

    let drOut = await createOutboundDraft(hub.id, cFill.id, 10, PRIORITIES.STANDARD);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    drOut = await completeAndGet(hub.id, drOut, 10);

    hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.OPEN);
    expect(hubCheck.staging_free_units).toBe(10);

    const res2 = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [drSmall.id] });
    expectSuccess(res2);
    const result2 = getData(res2);
    expect(result2.scheduled_ids).toContain(drSmall.id);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(5);
    expect(hubFinal.staging_free_units).toBe(5);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('SCHEDULE_017: Priority ordering fills capacity with EXPEDITE first', async () => {

    const hub = await createHub(undefined, 20);
    const h0 = await getHub(hub.id);

    const c1 = await createConsignment(hub.id, { reference: 'FILL20', declared_units: 20, commodity: COMMODITIES.GENERAL });
    let dr1 = await createInboundDraft(hub.id, c1.id, 20, PRIORITIES.EXPEDITE);
    dr1 = await submitAndGet(hub.id, dr1);

    const c2 = await createConsignment(hub.id, { reference: 'LATE1', declared_units: 1, commodity: COMMODITIES.GENERAL });
    let dr2 = await createInboundDraft(hub.id, c2.id, 1, PRIORITIES.DEFERRED);
    dr2 = await submitAndGet(hub.id, dr2);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [dr1.id, dr2.id] });

    expectSuccess(res);
    const result = getData(res);

    expect(result.scheduled_ids).toContain(dr1.id);

    expect(result.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr2.id,
          error_code: ERROR_CODES.ERR_POSTURE_LOCKDOWN,
        }),
      ])
    );

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(20);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(0);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubFinal.ops_run_index).toBe(h0.ops_run_index);
  });

  test('SCHEDULE_018: Mixed inbound/outbound batch scheduling', async () => {

    const hub = await createHub(undefined, 20);

    const cOn = await createConsignment(hub.id, { reference: 'ONHAND5', declared_units: 5, commodity: COMMODITIES.GENERAL });
    let in5 = await createInboundDraft(hub.id, cOn.id, 5, PRIORITIES.STANDARD);
    in5 = await submitAndGet(hub.id, in5);
    in5 = await scheduleAndGet(hub.id, in5);
    in5 = await completeAndGet(hub.id, in5, 5);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(5);
    expect(hubCheck.staging_free_units).toBe(15);
    expect(hubCheck.posture).toBe(POSTURES.OPEN);

    const cIn = await createConsignment(hub.id, { reference: 'RES15', declared_units: 15, commodity: COMMODITIES.GENERAL });
    let in15 = await createInboundDraft(hub.id, cIn.id, 15, PRIORITIES.EXPEDITE);
    in15 = await submitAndGet(hub.id, in15);

    let out5 = await createOutboundDraft(hub.id, cOn.id, 5, PRIORITIES.DEFERRED);
    out5 = await submitAndGet(hub.id, out5);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, { dock_request_ids: [in15.id, out5.id] });

    expectSuccess(res);
    const result = getData(res);

    expect(result.scheduled_ids).toContain(in15.id);
    expect(result.scheduled_ids).toContain(out5.id);

    const in15Final = await getDockRequest(hub.id, in15.id);
    expect(in15Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const out5Final = await getDockRequest(hub.id, out5.id);
    expect(out5Final.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(5);
    expect(hubFinal.staging_reserved_units).toBe(15);
    expect(hubFinal.staging_free_units).toBe(0);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('COMPLETE_011: Inbound completion with exact-fit over-receipt', async () => {

    const hub = await createHub(undefined, 20);

    const c = await createConsignment(hub.id, { reference: 'EXACT', declared_units: 18, commodity: COMMODITIES.GENERAL });
    let dr = await createInboundDraft(hub.id, c.id, 18, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_reserved_units).toBe(18);
    expect(hubCheck.staging_free_units).toBe(2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 20 },
      dr.etag
    );

    expectSuccess(res);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drFinal.variance_units).toBe(2);

    const cFinal = await getConsignment(hub.id, c.id);
    expect(cFinal.units_on_hand).toBe(20);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(20);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(0);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('COMPLETE_012: Inbound completion rejected when over-receipt exceeds capacity', async () => {

    const hub = await createHub(undefined, 20);

    const c = await createConsignment(hub.id, { reference: 'PLAN18', declared_units: 18, commodity: COMMODITIES.GENERAL });
    let dr = await createInboundDraft(hub.id, c.id, 18, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_reserved_units).toBe(18);
    expect(hubCheck.staging_free_units).toBe(2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 25 },
      dr.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const cFinal = await getConsignment(hub.id, c.id);
    expect(cFinal.units_on_hand).toBe(0);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(18);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(2);

    const drOut = await createOutboundDraft(hub.id, c.id, 1, PRIORITIES.STANDARD);
    const outSubmitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOut.id}/submit`,
      {},
      drOut.etag
    );

    await expectErrorCode(outSubmitRes, ERROR_CODES.ERR_CONSIGNMENT_EMPTY);
  });

  test('COMPLETE_016: Zero actual_units completion creates no variance hold', async () => {

    const hub = await createHub(undefined, 20);

    const c = await createConsignment(hub.id, { reference: 'ZERO1', declared_units: 1, commodity: COMMODITIES.GENERAL });
    let drIn = await createInboundDraft(hub.id, c.id, 1, PRIORITIES.STANDARD);
    drIn = await submitAndGet(hub.id, drIn);
    drIn = await scheduleAndGet(hub.id, drIn);

    const drOut = await createOutboundDraft(hub.id, c.id, 1, PRIORITIES.STANDARD);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drIn.id}/complete`,
      { actual_units: 0 },
      drIn.etag
    );
    expectSuccess(completeRes);

    const drInFinal = await getDockRequest(hub.id, drIn.id);
    expect(drInFinal.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drInFinal.variance_units).toBe(-1);

    expect(drInFinal.auto_hold_id).toBeFalsy();

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);

    const outSubmitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOut.id}/submit`,
      {},
      drOut.etag
    );
    await expectErrorCode(outSubmitRes, ERROR_CODES.ERR_CONSIGNMENT_EMPTY);

    const drOutFinal = await getDockRequest(hub.id, drOut.id);
    expect(drOutFinal.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('COMPLETE_018: Concurrent scheduling blocks over-receipt completion', async () => {

    const hub = await createHub(undefined, 20);

    const ca = await createConsignment(hub.id, { reference: 'A10', declared_units: 10, commodity: COMMODITIES.GENERAL });
    const cb = await createConsignment(hub.id, { reference: 'B10', declared_units: 10, commodity: COMMODITIES.GENERAL });

    let inaSubmit = await createInboundDraft(hub.id, ca.id, 10, PRIORITIES.STANDARD);
    let inbSubmit = await createInboundDraft(hub.id, cb.id, 10, PRIORITIES.STANDARD);
    inaSubmit = await submitAndGet(hub.id, inaSubmit);
    inbSubmit = await submitAndGet(hub.id, inbSubmit);

    await batchSchedule(hub.id, [inaSubmit.id, inbSubmit.id]);
    const inaSch = await getDockRequest(hub.id, inaSubmit.id);
    const inbSch = await getDockRequest(hub.id, inbSubmit.id);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_reserved_units).toBe(20);
    expect(hubCheck.staging_free_units).toBe(0);
    expect(hubCheck.posture).toBe(POSTURES.LOCKDOWN);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inaSch.id}/complete`,
      { actual_units: 15 },
      inaSch.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const inaFinal = await getDockRequest(hub.id, inaSch.id);
    expect(inaFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const inbFinal = await getDockRequest(hub.id, inbSch.id);
    expect(inbFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(20);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(0);
    expect(hubFinal.posture).toBe(POSTURES.LOCKDOWN);

    const caFinal = await getConsignment(hub.id, ca.id);
    expect(caFinal.units_on_hand).toBe(0);
    expect(caFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const cbFinal = await getConsignment(hub.id, cb.id);
    expect(cbFinal.units_on_hand).toBe(0);
    expect(cbFinal.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
  });

  test('HOLD_016: Cleared hold pops ON_HOLD back to SUBMITTED, blocking second open move', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr1 = await createOutboundDraft(hub.id, consignment.id, 4, PRIORITIES.STANDARD);
    dr1 = await submitAndGet(hub.id, dr1);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    dr1 = await getDockRequest(hub.id, dr1.id);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const h0 = await getHold(hub.id, hold.id);
    await clearHold(hub.id, hold.id, h0.etag);

    dr1 = await getDockRequest(hub.id, dr1.id);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1, PRIORITIES.STANDARD);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSIGNMENT_BUSY);

    const dr1Final = await getDockRequest(hub.id, dr1.id);
    expect(dr1Final.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2Final = await getDockRequest(hub.id, dr2.id);
    expect(dr2Final.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const holdFinal = await getHold(hub.id, hold.id);
    expect(holdFinal.status).toBe(HOLD_STATUSES.CLEARED);

    const cFinal = await getConsignment(hub.id, consignment.id);
    expect(cFinal.units_on_hand).toBe(10);
    expect(cFinal.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(10);
    expect(hubFinal.staging_reserved_units).toBe(0);
  });
});
