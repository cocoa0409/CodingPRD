import { get, post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createConsignment,
  getConsignment,
  getDockRequest,
  batchSchedule,
  getHub,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  createHold,
  executeInboundFlow,
  createConsignmentAtHub,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  HOLD_KINDS,
  POSTURES,
} from '../../../test-helpers/constants';

describe('Scheduling Tests', () => {

  test('SCHEDULE_001: Schedule inbound SUBMITTED dock request succeeds', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(0);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids).toContain(dr.id);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(10);
  });

  test('SCHEDULE_002: Schedule outbound SUBMITTED dock request - staging_reserved_units unchanged', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);

    const hubBefore = await getHub(hub.id);
    const reservedBefore = hubBefore.staging_reserved_units;

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids).toContain(dr.id);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(reservedBefore);
  });

  test('SCHEDULE_003: Schedule DRAFT dock request rejected with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, consignment.id, 10);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr.id,
          error_code: ERROR_CODES.ERR_INVALID_STATE,
        }),
      ])
    );

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('SCHEDULE_004: Partial scheduling with capacity exceeded - one scheduled, one rejected', async () => {

    const hub = await createHub(undefined, 5);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, consignment1.id, 4);
    dr1 = await submitAndGet(hub.id, dr1);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 3,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, consignment2.id, 3);
    dr2 = await submitAndGet(hub.id, dr2);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr1.id, dr2.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids.length).toBe(1);
    expect(scheduleResult.rejected.length).toBe(1);

    const scheduledId = scheduleResult.scheduled_ids[0];
    const rejectedEntry = scheduleResult.rejected[0];

    expect(scheduledId).toBe(dr1.id);
    expect(rejectedEntry.dock_request_id).toBe(dr2.id);
    expect(rejectedEntry.error_code).toBe(ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(4);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('SCHEDULE_005: Priority ordering - EXPEDITE scheduled before DEFERRED', async () => {

    const hub = await createHub(undefined, 100);

    const consignmentA = await createConsignment(hub.id, {
      reference: 'PA',
      declared_units: 60,
      commodity: COMMODITIES.GENERAL,
    });
    let drA = await createInboundDraft(hub.id, consignmentA.id, 60, PRIORITIES.DEFERRED);
    drA = await submitAndGet(hub.id, drA);

    const consignmentB = await createConsignment(hub.id, {
      reference: 'PB',
      declared_units: 60,
      commodity: COMMODITIES.GENERAL,
    });
    let drB = await createInboundDraft(hub.id, consignmentB.id, 60, PRIORITIES.EXPEDITE);
    drB = await submitAndGet(hub.id, drB);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [drA.id, drB.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.scheduled_ids).toContain(drB.id);
    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: drA.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(60);

    const drBCheck = await getDockRequest(hub.id, drB.id);
    expect(drBCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const drACheck = await getDockRequest(hub.id, drA.id);
    expect(drACheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('SCHEDULE_006: Inbound scheduling blocked in LOCKDOWN with ERR_POSTURE_LOCKDOWN', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 20, 20);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.LOCKDOWN);

    const hub2 = await createHub(undefined, 20);

    const testConsignment = await createConsignment(hub2.id, {
      reference: 'X',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub2.id, testConsignment.id, 1, PRIORITIES.EXPEDITE);

    dr = await submitAndGet(hub2.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const lockdownConsignment = await createConsignment(hub2.id, {
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub2.id, lockdownConsignment.id, 20, 20);

    const hub2Check = await getHub(hub2.id);
    expect(hub2Check.posture).toBe(POSTURES.LOCKDOWN);

    const res = await post(`/hubs/${hub2.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr.id,
          error_code: ERROR_CODES.ERR_POSTURE_LOCKDOWN,
        }),
      ])
    );

    const drCheck = await getDockRequest(hub2.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('SCHEDULE_007: Outbound scheduling in LOCKDOWN - rejected with ERR_CONSIGNMENT_EMPTY', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'Y',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10, 10);

    let consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.units_on_hand).toBe(10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 1, PRIORITIES.EXPEDITE);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hub2 = await createHub(undefined, 20);

    const testConsignment = await createConsignment(hub2.id, {
      reference: 'Y2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub2.id, testConsignment.id, 10, 10);

    let drTest = await createOutboundDraft(hub2.id, testConsignment.id, 1, PRIORITIES.EXPEDITE);
    drTest = await submitAndGet(hub2.id, drTest);

    const drTestFresh = await getDockRequest(hub2.id, drTest.id);
    const cancelRes = await postWithEtag(
      `/hubs/${hub2.id}/dock_requests/${drTest.id}/cancel`,
      {},
      drTestFresh.etag
    );
    expectSuccess(cancelRes);

    let drDrain = await createOutboundDraft(hub2.id, testConsignment.id, 10, PRIORITIES.STANDARD);
    drDrain = await submitAndGet(hub2.id, drDrain);
    const schedDrain = await batchSchedule(hub2.id, [drDrain.id]);
    drDrain = await getDockRequest(hub2.id, drDrain.id);
    const completeDrainRes = await postWithEtag(
      `/hubs/${hub2.id}/dock_requests/${drDrain.id}/complete`,
      { actual_units: 10 },
      drDrain.etag
    );
    expectSuccess(completeDrainRes);

    const consignmentDrained = await getConsignment(hub2.id, testConsignment.id);
    expect(consignmentDrained.units_on_hand).toBe(0);

    const lockdownConsignment = await createConsignment(hub2.id, {
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub2.id, lockdownConsignment.id, 20, 20);

    const hub2Lockdown = await getHub(hub2.id);
    expect(hub2Lockdown.posture).toBe(POSTURES.LOCKDOWN);

    const drEmpty = await createOutboundDraft(hub2.id, testConsignment.id, 1, PRIORITIES.EXPEDITE);
    const submitRes = await postWithEtag(
      `/hubs/${hub2.id}/dock_requests/${drEmpty.id}/submit`,
      {},
      drEmpty.etag
    );

    if (submitRes.status >= 400) {

      expect(submitRes.status).toBeLessThan(500);

      return;
    }

    const drSubmitted = await getDockRequest(hub2.id, drEmpty.id);
    expect(drSubmitted.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const res = await post(`/hubs/${hub2.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [drEmpty.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: drEmpty.id,
          error_code: ERROR_CODES.ERR_CONSIGNMENT_EMPTY,
        }),
      ])
    );

    const drCheck = await getDockRequest(hub2.id, drEmpty.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('SCHEDULE_008: ON_HOLD dock request rejected with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr.id,
          error_code: ERROR_CODES.ERR_INVALID_STATE,
        }),
      ])
    );

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);
  });

  test('SCHEDULE_009: Already SCHEDULED dock request rejected with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    await batchSchedule(hub.id, [dr.id]);
    const drScheduled = await getDockRequest(hub.id, dr.id);
    expect(drScheduled.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [drScheduled.id],
    });

    expectSuccess(res);
    const scheduleResult = getData(res);

    expect(scheduleResult.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: drScheduled.id,
          error_code: ERROR_CODES.ERR_INVALID_STATE,
        }),
      ])
    );

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('SCHEDULE_010: Scheduling updates staging_reserved_units and staging_free_units correctly', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_capacity_units).toBe(100);
    expect(hubBefore.staging_in_use_units).toBe(0);
    expect(hubBefore.staging_reserved_units).toBe(0);
    expect(hubBefore.staging_free_units).toBe(100);
    expect(hubBefore.posture).toBe(POSTURES.OPEN);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(res);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(10);
    expect(hubAfter.staging_free_units).toBe(90);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
    expect(hubAfter.staging_in_use_units).toBe(0);
  });

  test('SCHEDULE_015: Schedule EXPEDITE first, cancel, then schedule DEFERRED', async () => {

    const hub = await createHub(undefined, 5);

    const c1 = await createConsignment(hub.id, {
      reference: 'A4',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, c1.id, 4, PRIORITIES.EXPEDITE);
    dr1 = await submitAndGet(hub.id, dr1);

    const c2 = await createConsignment(hub.id, {
      reference: 'B3',
      declared_units: 3,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, c2.id, 3, PRIORITIES.DEFERRED);
    dr2 = await submitAndGet(hub.id, dr2);

    const b1Res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr1.id, dr2.id],
    });
    expectSuccess(b1Res);
    const b1Data = getData(b1Res);

    expect(b1Data.scheduled_ids).toContain(dr1.id);
    const rejectedS2 = b1Data.rejected.find((r: any) => r.dock_request_id === dr2.id);
    expect(rejectedS2).toBeDefined();
    expect(rejectedS2.error_code).toBe(ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const s1Sch = await getDockRequest(hub.id, dr1.id);
    expect(s1Sch.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const s2After = await getDockRequest(hub.id, dr2.id);
    expect(s2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h1 = await getHub(hub.id);
    expect(h1.staging_reserved_units).toBe(4);
    expect(h1.staging_free_units).toBe(1);
    expect(h1.posture).toBe(POSTURES.CONGESTED);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${s1Sch.id}/cancel`,
      {},
      s1Sch.etag
    );
    expectSuccess(cancelRes);

    const s1Cancelled = await getDockRequest(hub.id, dr1.id);
    expect(s1Cancelled.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const hubAfterCancel = await getHub(hub.id);
    expect(hubAfterCancel.staging_reserved_units).toBe(0);
    expect(hubAfterCancel.staging_free_units).toBe(5);
    expect(hubAfterCancel.posture).toBe(POSTURES.OPEN);

    const b2Res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr2.id],
    });
    expectSuccess(b2Res);
    const b2Data = getData(b2Res);

    expect(b2Data.scheduled_ids).toContain(dr2.id);

    const s2Scheduled = await getDockRequest(hub.id, dr2.id);
    expect(s2Scheduled.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfterB2 = await getHub(hub.id);
    expect(hubAfterB2.staging_reserved_units).toBe(3);
    expect(hubAfterB2.staging_free_units).toBe(2);
    expect(hubAfterB2.posture).toBe(POSTURES.OPEN);

    const c1Check = await getConsignment(hub.id, c1.id);
    expect(c1Check.units_on_hand).toBe(0);
    expect(c1Check.status).toBe('PLANNED');

    const c2Check = await getConsignment(hub.id, c2.id);
    expect(c2Check.units_on_hand).toBe(0);
    expect(c2Check.status).toBe('PLANNED');
  });

  test('SCHED_019: Schedule batch with cancelled request - cancelled rejected, submitted scheduled', async () => {

    const hub = await createHub(undefined, 20);

    const c1 = await createConsignment(hub.id, {
      reference: 'C10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, c1.id, 10);
    dr1 = await submitAndGet(hub.id, dr1);

    const c2 = await createConsignment(hub.id, {
      reference: 'C5',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, c2.id, 5);
    dr2 = await submitAndGet(hub.id, dr2);

    const dr2Fresh = await getDockRequest(hub.id, dr2.id);
    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/cancel`,
      {},
      dr2Fresh.etag
    );
    expectSuccess(cancelRes);

    const dr2Cancelled = await getDockRequest(hub.id, dr2.id);
    expect(dr2Cancelled.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const h0 = await getHub(hub.id);

    const res = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr1.id, dr2.id],
    });
    expectSuccess(res);
    const scheduleData = getData(res);

    expect(scheduleData.scheduled_ids).toContain(dr1.id);

    const rejectedS2 = scheduleData.rejected.find((r: any) => r.dock_request_id === dr2.id);
    expect(rejectedS2).toBeDefined();
    expect(rejectedS2.error_code).toBe(ERROR_CODES.ERR_INVALID_STATE);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(10);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(10);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });
});
