import { get, post, postWithEtag, postWithoutEtag, putWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createConsignment,
  createDockRequest,
  getDockRequest,
  getHub,
  getConsignment,
  getHold,
  submitDockRequest,
  batchSchedule,
  completeDockRequest,
  createHold,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  completeAndGet,
  createConsignmentAtHub,
  createReleasedConsignment,
  updateDockRequest,
} from '../../../test-helpers/resources';
import {
  DIRECTIONS,
  PRIORITIES,
  COMMODITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  HOLD_KINDS,
  HOLD_STATUSES,
  CONSIGNMENT_STATUSES,
  POSTURES,
} from '../../../test-helpers/constants';

describe('Error Precedence Tests', () => {

  test('ERR_002: Complete without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, inboundDr.id, inboundDr.etag);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await batchSchedule(hub.id, [inboundDr.id]);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await completeDockRequest(hub.id, inboundDr.id, inboundDr.etag, 10);

    let outboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, outboundDr.id, outboundDr.etag);
    outboundDr = await getDockRequest(hub.id, outboundDr.id);

    await batchSchedule(hub.id, [outboundDr.id]);
    const drScheduled = await getDockRequest(hub.id, outboundDr.id);
    expect(drScheduled.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const completeRes = await postWithoutEtag(
      `/hubs/${hub.id}/dock_requests/${drScheduled.id}/complete`,
      { actual_units: 4 }
    );

    await expectErrorCode(completeRes, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const drCheck = await getDockRequest(hub.id, drScheduled.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('ERR_003: Cancel non-existent dock request returns ERR_NOT_FOUND', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, inboundDr.id, inboundDr.etag);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await batchSchedule(hub.id, [inboundDr.id]);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await completeDockRequest(hub.id, inboundDr.id, inboundDr.etag, 10);

    let outboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, outboundDr.id, outboundDr.etag);
    outboundDr = await getDockRequest(hub.id, outboundDr.id);

    await batchSchedule(hub.id, [outboundDr.id]);

    const hubBefore = await getHub(hub.id);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/DR_DOES_NOT_EXIST/cancel`,
      {},
      'any'
    );

    await expectErrorCode(cancelRes, ERROR_CODES.ERR_NOT_FOUND);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(hubBefore.staging_reserved_units);
    expect(hubAfter.staging_in_use_units).toBe(hubBefore.staging_in_use_units);
  });

  test('ERR_004: Submit already SUBMITTED dock request returns ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, inboundDr.id, inboundDr.etag);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await batchSchedule(hub.id, [inboundDr.id]);
    inboundDr = await getDockRequest(hub.id, inboundDr.id);

    await completeDockRequest(hub.id, inboundDr.id, inboundDr.etag, 10);

    let outboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, outboundDr.id, outboundDr.etag);
    const drSubmitted = await getDockRequest(hub.id, outboundDr.id);
    expect(drSubmitted.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drSubmitted.id}/submit`,
      {},
      drSubmitted.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_INVALID_STATE);

    const drCheck = await getDockRequest(hub.id, drSubmitted.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('ERR_005: Submit inbound in LOCKDOWN returns ERR_POSTURE_LOCKDOWN', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });

    let fillDr = await createDockRequest(hub.id, {
      consignment_id: fillConsignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 20,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, fillDr.id, fillDr.etag);
    fillDr = await getDockRequest(hub.id, fillDr.id);

    await batchSchedule(hub.id, [fillDr.id]);
    fillDr = await getDockRequest(hub.id, fillDr.id);

    await completeDockRequest(hub.id, fillDr.id, fillDr.etag, 20);

    const hubLockdown = await getHub(hub.id);
    expect(hubLockdown.posture).toBe('LOCKDOWN');
    expect(hubLockdown.staging_free_units).toBe(0);

    const newConsignment = await createConsignment(hub.id, {
      reference: 'IN1',
      declared_units: 3,
      commodity: COMMODITIES.GENERAL,
    });

    const inboundDr = await createDockRequest(hub.id, {
      consignment_id: newConsignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 1,
      priority: PRIORITIES.STANDARD,
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inboundDr.id}/submit`,
      {},
      inboundDr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const drCheck = await getDockRequest(hub.id, inboundDr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('ERR_006: Submit outbound with open hold returns ERR_CONSIGNMENT_HAS_OPEN_HOLD', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'P10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const outboundDr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 1,
      priority: PRIORITIES.STANDARD,
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outboundDr.id}/submit`,
      {},
      outboundDr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drCheck = await getDockRequest(hub.id, outboundDr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('ERR_007: Batch schedule with mixed valid/invalid returns partial success', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'P10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    await submitDockRequest(hub.id, dr.id, dr.etag);
    const drSubmitted = await getDockRequest(hub.id, dr.id);
    expect(drSubmitted.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [drSubmitted.id, 'DR_MISSING'],
    });

    expectSuccess(scheduleRes);
    const scheduleData = getData(scheduleRes);

    expect(scheduleData.scheduled_ids).toBeDefined();
    expect(scheduleData.scheduled_ids).toContain(drSubmitted.id);

    expect(scheduleData.rejected).toBeDefined();
    const rejectedEntry = scheduleData.rejected.find(
      (r: { dock_request_id: string }) => r.dock_request_id === 'DR_MISSING'
    );
    expect(rejectedEntry).toBeDefined();
    expect(rejectedEntry.error_code).toBe(ERROR_CODES.ERR_NOT_FOUND);

    const drCheck = await getDockRequest(hub.id, drSubmitted.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('ERR_008: Submit draft inbound moves to SUBMITTED', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'P10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(submitRes);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('ERR_009: Submit outbound when consignment has open hold returns ERR_CONSIGNMENT_HAS_OPEN_HOLD', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let drSub = await createOutboundDraft(hub.id, consignment.id, 4);
    drSub = await submitAndGet(hub.id, drSub);
    expect(drSub.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    drSub = await getDockRequest(hub.id, drSub.id);
    expect(drSub.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drSubCheck = await getDockRequest(hub.id, drSub.id);
    expect(drSubCheck.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);
  });

  test('ERR_010: run_ops without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub(undefined, 20);
    const h0 = await getHub(hub.id);

    const res = await postWithoutEtag(`/hubs/${hub.id}/run_ops`, {});

    await expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.ops_run_index).toBe(h0.ops_run_index);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);
  });

  test('ERR_011: run_ops with stale etag returns ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const h0 = await getHub(hub.id);

    const ops1Res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);
    expectSuccess(ops1Res);

    const h1 = await getHub(hub.id);
    expect(h1.ops_run_index).toBe(h0.ops_run_index + 1);

    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    await expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.ops_run_index).toBe(h1.ops_run_index);
    expect(hubCheck.staging_in_use_units).toBe(h1.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h1.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h1.staging_free_units);
    expect(hubCheck.posture).toBe(h1.posture);
  });

  test('ERR_012: Submit with stale etag returns ERR_VERSION_CONFLICT before posture check', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 20);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 20);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);

    const c2 = await createConsignment(hub.id, {
      reference: 'ELOCK',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, c2.id, 1);
    const dr0 = await getDockRequest(hub.id, dr.id);

    const dr1 = await updateDockRequest(hub.id, dr.id, dr0.etag, { units: 1, priority: PRIORITIES.STANDARD });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr0.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_in_use_units).toBe(20);
  });

  test('ERR_013: Submit inbound in LOCKDOWN returns ERR_POSTURE_LOCKDOWN', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 20);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 20);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);

    const dr = await createInboundDraft(hub.id, fillConsignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);
  });

  test('ERR_014: Cancel non-existent dock request without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub(undefined, 20);
    const h0 = await getHub(hub.id);

    const res = await postWithoutEtag(`/hubs/${hub.id}/dock_requests/DR_DOES_NOT_EXIST/cancel`, {});

    await expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.ops_run_index).toBe(h0.ops_run_index);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);
  });

  test('ERR_015: Submit with stale etag returns ERR_VERSION_CONFLICT before hold check', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 1);
    const dr0 = await getDockRequest(hub.id, dr.id);

    const dr1 = await updateDockRequest(hub.id, dr.id, dr0.etag, { units: 1, priority: PRIORITIES.DEFERRED });

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr0.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
    expect(drCheck.priority).toBe(PRIORITIES.DEFERRED);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(10);
    expect(hubCheck.staging_reserved_units).toBe(0);
  });

  test('ERR_016: Submit inbound in LOCKDOWN returns ERR_POSTURE_LOCKDOWN with full invariants', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 20);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 20);

    const h0 = await getHub(hub.id);
    const c0 = await getConsignment(hub.id, fillConsignment.id);
    expect(h0.posture).toBe(POSTURES.LOCKDOWN);

    const dr = await createInboundDraft(hub.id, fillConsignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);

    const cCheck = await getConsignment(hub.id, fillConsignment.id);
    expect(cCheck.status).toBe(c0.status);
    expect(cCheck.units_on_hand).toBe(c0.units_on_hand);
  });

  test('ERR_017: Cancel dock request on wrong hub returns ERR_NOT_FOUND', async () => {

    const hub1 = await createHub(undefined, 20);
    const hub2 = await createHub(undefined, 20);

    const c1 = await createConsignment(hub1.id, {
      reference: 'X',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub1.id, c1.id, 1);
    const drSub = await submitAndGet(hub1.id, dr);

    const a0 = await getHub(hub1.id);
    const b0 = await getHub(hub2.id);

    const cancelRes = await postWithEtag(
      `/hubs/${hub2.id}/dock_requests/${drSub.id}/cancel`,
      {},
      'stale-etag'
    );

    await expectErrorCode(cancelRes, ERROR_CODES.ERR_NOT_FOUND);

    const drCheck = await getDockRequest(hub1.id, drSub.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const a1 = await getHub(hub1.id);
    expect(a1.staging_in_use_units).toBe(a0.staging_in_use_units);
    expect(a1.staging_reserved_units).toBe(a0.staging_reserved_units);
    expect(a1.ops_run_index).toBe(a0.ops_run_index);

    const b1 = await getHub(hub2.id);
    expect(b1.staging_in_use_units).toBe(b0.staging_in_use_units);
    expect(b1.staging_reserved_units).toBe(b0.staging_reserved_units);
    expect(b1.ops_run_index).toBe(b0.ops_run_index);
  });

  test('ERR_018: Cancel dock request on wrong hub without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub1 = await createHub(undefined, 20);
    const hub2 = await createHub(undefined, 20);

    const c1 = await createConsignment(hub1.id, {
      reference: 'X',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub1.id, c1.id, 1);
    const drSub = await submitAndGet(hub1.id, dr);

    const a0 = await getHub(hub1.id);
    const b0 = await getHub(hub2.id);

    const cancelRes = await postWithoutEtag(
      `/hubs/${hub2.id}/dock_requests/${drSub.id}/cancel`,
      {}
    );

    await expectErrorCode(cancelRes, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const drCheck = await getDockRequest(hub1.id, drSub.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const a1 = await getHub(hub1.id);
    expect(a1.staging_in_use_units).toBe(a0.staging_in_use_units);
    expect(a1.staging_reserved_units).toBe(a0.staging_reserved_units);
    expect(a1.ops_run_index).toBe(a0.ops_run_index);

    const b1 = await getHub(hub2.id);
    expect(b1.staging_in_use_units).toBe(b0.staging_in_use_units);
    expect(b1.staging_reserved_units).toBe(b0.staging_reserved_units);
    expect(b1.ops_run_index).toBe(b0.ops_run_index);
  });

  test('ERR_019: Submit outbound with open hold returns ERR_CONSIGNMENT_HAS_OPEN_HOLD before ERR_CONSIGNMENT_EMPTY', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createReleasedConsignment(hub.id, 10);

    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(consignment.units_on_hand).toBe(0);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const dr = await createOutboundDraft(hub.id, consignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const cCheck = await getConsignment(hub.id, consignment.id);
    expect(cCheck.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(cCheck.units_on_hand).toBe(0);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(0);
    expect(hubCheck.staging_reserved_units).toBe(0);
  });

  test('ERR_020: Submit inbound in CONGESTED exceeding limit returns ERR_CONGESTED_INBOUND_LIMIT', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL16',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 16);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 16);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.CONGESTED);
    expect(hubState.staging_free_units).toBe(4);

    const c = await createConsignment(hub.id, {
      reference: 'BUSYCONG',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const dr1 = await createInboundDraft(hub.id, c.id, 1);
    const dr1Sub = await submitAndGet(hub.id, dr1);
    expect(dr1Sub.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2 = await createInboundDraft(hub.id, c.id, 2);

    const h0 = await getHub(hub.id);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);
  });

  test('ERR_021: Submit without If-Match returns ERR_MISSING_IF_MATCH before CONGESTED check', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL16',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 16);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 16);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.CONGESTED);
    expect(hubState.staging_free_units).toBe(4);

    const c = await createConsignment(hub.id, {
      reference: 'PUSH2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, c.id, 2);

    const h0 = await getHub(hub.id);

    const submitRes = await postWithoutEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {}
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);
  });

  test('ERR_022: Submit outbound in LOCKDOWN with open hold returns ERR_CONSIGNMENT_HAS_OPEN_HOLD', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 20);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 20);

    const h0 = await getHub(hub.id);
    expect(h0.posture).toBe(POSTURES.LOCKDOWN);

    const hold = await createHold(hub.id, {
      consignment_id: fillConsignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const dr = await createOutboundDraft(hub.id, fillConsignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(h0.posture);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.ops_run_index).toBe(h0.ops_run_index);
  });

  test('ERR_023: Submit outbound when consignment is empty returns ERR_CONSIGNMENT_EMPTY before ERR_CONSIGNMENT_BUSY', async () => {

    const hub = await createHub(undefined, 20);

    const c = await createConsignment(hub.id, {
      reference: 'EMPTY-VS-BUSY',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const inDr = await createInboundDraft(hub.id, c.id, 1);
    const inSub = await submitAndGet(hub.id, inDr);
    expect(inSub.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const outDr = await createOutboundDraft(hub.id, c.id, 1);

    const h0 = await getHub(hub.id);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outDr.id}/submit`,
      {},
      outDr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_EMPTY);

    const inCheck = await getDockRequest(hub.id, inDr.id);
    expect(inCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const outCheck = await getDockRequest(hub.id, outDr.id);
    expect(outCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubCheck.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubCheck.staging_free_units).toBe(h0.staging_free_units);
    expect(hubCheck.posture).toBe(h0.posture);
    expect(hubCheck.ops_run_index).toBe(h0.ops_run_index);
  });
});
