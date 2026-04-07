import { get, post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  getData,
} from '../../../test-helpers/assertions';
import { createHub } from '../../../test-helpers/resources';
import {
  POSTURES,
  DIRECTIONS,
  PRIORITIES,
  COMMODITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
} from '../../../test-helpers/constants';

describe('Hub Tests', () => {

  test('HUB_001: GET hub shows OPEN posture with full staging available', async () => {

    const hub = await createHub(undefined, 5);

    const res = await get(`/hubs/${hub.id}`);

    expectSuccess(res);
    const data = getData(res);
    expect(data.posture).toBe(POSTURES.OPEN);
    expect(data.staging_free_units).toBe(5);
    expect(data.staging_in_use_units).toBe(0);
    expect(data.staging_reserved_units).toBe(0);
  });

  test('HUB_002: Hub becomes CONGESTED when 4/5 units are in use', async () => {

    const hub = await createHub(undefined, 5);

    const consignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'X',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(consignmentRes);
    const consignment = getData(consignmentRes);

    const drRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(drRes);
    let dr = getData(drRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });
    expectSuccess(scheduleRes);
    const scheduleData = getData(scheduleRes);

    expect(scheduleData.scheduled_ids).toContain(dr.id);
    expect(scheduleData.rejected || []).not.toContainEqual(
      expect.objectContaining({ dock_request_id: dr.id })
    );

    const hubAfterScheduleRes = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfterScheduleRes);
    const hubAfterSchedule = getData(hubAfterScheduleRes);
    expect(hubAfterSchedule.staging_reserved_units).toBe(4);
    expect(hubAfterSchedule.staging_in_use_units).toBe(0);
    expect(hubAfterSchedule.staging_free_units).toBe(1);
    expect(hubAfterSchedule.posture).toBe(POSTURES.CONGESTED);

    const drSchRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(drSchRes);
    dr = getData(drSchRes);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      dr.etag
    );
    expectSuccess(completeRes);

    const res = await get(`/hubs/${hub.id}`);

    expectSuccess(res);
    const data = getData(res);
    expect(data.staging_in_use_units).toBe(4);
    expect(data.staging_free_units).toBe(1);
    expect(data.staging_reserved_units).toBe(0);
    expect(data.posture).toBe(POSTURES.CONGESTED);
  });

  test('HUB_003: Hub becomes LOCKDOWN when all staging is used', async () => {

    const hub = await createHub(undefined, 5);

    const consignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'Y',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(consignmentRes);
    const consignment = getData(consignmentRes);

    const drRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 5,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(drRes);
    let dr = getData(drRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });
    expectSuccess(scheduleRes);

    const hubAfterScheduleRes = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfterScheduleRes);
    const hubAfterSchedule = getData(hubAfterScheduleRes);
    expect(hubAfterSchedule.staging_reserved_units).toBe(5);
    expect(hubAfterSchedule.staging_free_units).toBe(0);
    expect(hubAfterSchedule.posture).toBe(POSTURES.LOCKDOWN);

    const drSchRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(drSchRes);
    dr = getData(drSchRes);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 5 },
      dr.etag
    );
    expectSuccess(completeRes);

    const res = await get(`/hubs/${hub.id}`);

    expectSuccess(res);
    const data = getData(res);
    expect(data.staging_free_units).toBe(0);
    expect(data.staging_in_use_units).toBe(5);
    expect(data.staging_reserved_units).toBe(0);
    expect(data.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('HUB_004: Hub with capacity 20 shows CONGESTED when free_units=4', async () => {

    const hub = await createHub(undefined, 20);

    const consignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'FILL',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(consignmentRes);
    const consignment = getData(consignmentRes);

    const drRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 16,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(drRes);
    let dr = getData(drRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });
    expectSuccess(scheduleRes);

    const hubAfterScheduleRes = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfterScheduleRes);
    const hubAfterSchedule = getData(hubAfterScheduleRes);
    expect(hubAfterSchedule.staging_reserved_units).toBe(16);
    expect(hubAfterSchedule.staging_free_units).toBe(4);
    expect(hubAfterSchedule.posture).toBe(POSTURES.CONGESTED);

    const drSchRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(drSchRes);
    dr = getData(drSchRes);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 16 },
      dr.etag
    );
    expectSuccess(completeRes);

    const res = await get(`/hubs/${hub.id}`);

    expectSuccess(res);
    const data = getData(res);
    expect(data.posture).toBe(POSTURES.CONGESTED);
    expect(data.staging_free_units).toBe(4);
    expect(data.staging_in_use_units).toBe(16);
    expect(data.staging_reserved_units).toBe(0);
  });

  test('HUB_005: Hub with capacity 20 shows LOCKDOWN when free_units=0', async () => {

    const hub = await createHub(undefined, 20);

    const consignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'FILL_FULL',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(consignmentRes);
    const consignment = getData(consignmentRes);

    const drRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 20,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(drRes);
    let dr = getData(drRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });
    expectSuccess(scheduleRes);

    const hubAfterScheduleRes = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfterScheduleRes);
    const hubAfterSchedule = getData(hubAfterScheduleRes);
    expect(hubAfterSchedule.staging_reserved_units).toBe(20);
    expect(hubAfterSchedule.staging_free_units).toBe(0);
    expect(hubAfterSchedule.posture).toBe(POSTURES.LOCKDOWN);

    const drSchRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(drSchRes);
    dr = getData(drSchRes);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 20 },
      dr.etag
    );
    expectSuccess(completeRes);

    const res = await get(`/hubs/${hub.id}`);

    expectSuccess(res);
    const data = getData(res);
    expect(data.posture).toBe(POSTURES.LOCKDOWN);
    expect(data.staging_free_units).toBe(0);
    expect(data.staging_in_use_units).toBe(20);
    expect(data.staging_reserved_units).toBe(0);
  });

  test('HUB_006: Outbound submit fails with ERR_CONSIGNMENT_EMPTY when no units on hand', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'LOCKDOWN_FILL',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(fillConsignmentRes);
    const fillConsignment = getData(fillConsignmentRes);

    const fillDrRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: fillConsignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 20,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(fillDrRes);
    let fillDr = getData(fillDrRes);

    const fillSubmitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${fillDr.id}/submit`,
      {},
      fillDr.etag
    );
    expectSuccess(fillSubmitRes);

    const fillScheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [fillDr.id],
    });
    expectSuccess(fillScheduleRes);

    const fillDrSchRes = await get(`/hubs/${hub.id}/dock_requests/${fillDr.id}`);
    expectSuccess(fillDrSchRes);
    fillDr = getData(fillDrSchRes);

    const fillCompleteRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${fillDr.id}/complete`,
      { actual_units: 20 },
      fillDr.etag
    );
    expectSuccess(fillCompleteRes);

    const hubCheck = await get(`/hubs/${hub.id}`);
    expectSuccess(hubCheck);
    expect(getData(hubCheck).posture).toBe(POSTURES.LOCKDOWN);

    const newConsignmentRes = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'REL',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    expectSuccess(newConsignmentRes);
    const newConsignment = getData(newConsignmentRes);

    const outboundDrRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: newConsignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 1,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(outboundDrRes);
    const outboundDr = getData(outboundDrRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outboundDr.id}/submit`,
      {},
      outboundDr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_EMPTY);

    const drCheckRes = await get(`/hubs/${hub.id}/dock_requests/${outboundDr.id}`);
    expectSuccess(drCheckRes);
    expect(getData(drCheckRes).status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });
});
