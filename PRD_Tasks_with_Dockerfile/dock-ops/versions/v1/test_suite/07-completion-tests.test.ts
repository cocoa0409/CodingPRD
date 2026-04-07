import { post, postWithEtag } from '../../../test-helpers/api-client';
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
  getHold,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  executeInboundFlow,
  createConsignmentAtHub,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  CONSIGNMENT_STATUSES,
  HOLD_KINDS,
  HOLD_SOURCES,
  HOLD_STATUSES,
} from '../../../test-helpers/constants';

describe('Completion Tests', () => {

  test('COMPLETE_001: Inbound completion increases units_on_hand and releases reservation', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(10);
    expect(hubBefore.staging_in_use_units).toBe(0);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 10 },
      dr.etag
    );

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);
    expect(hubAfter.staging_reserved_units).toBe(0);
  });

  test('COMPLETE_002: Completion with fewer actual_units updates staging correctly', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(10);
    expect(hubBefore.staging_free_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 6 },
      dr.etag
    );

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(6);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(6);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(14);
  });

  test('COMPLETE_003: Inbound completion exceeding capacity fails with ERR_CAPACITY_EXCEEDED', async () => {

    const hub = await createHub(undefined, 12);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(10);
    expect(hubBefore.staging_in_use_units).toBe(0);
    expect(hubBefore.staging_free_units).toBe(2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 15 },
      dr.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(10);
    expect(hubAfter.staging_in_use_units).toBe(0);
  });

  test('COMPLETE_004: Extra units must fit in remaining free staging', async () => {

    const hub = await createHub(undefined, 20);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 18,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment1.id, 18, PRIORITIES.STANDARD);

    dr1 = await submitAndGet(hub.id, dr1);

    await batchSchedule(hub.id, [dr1.id]);
    dr1 = await getDockRequest(hub.id, dr1.id);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(18);
    expect(hubBefore.staging_free_units).toBe(2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr1.id}/complete`,
      { actual_units: 21 },
      dr1.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(18);
    expect(hubAfter.staging_free_units).toBe(2);

    const dr1After = await getDockRequest(hub.id, dr1.id);
    expect(dr1After.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('COMPLETE_005: Outbound completion decreases units_on_hand', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    expect(consignment.units_on_hand).toBe(10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_in_use_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      dr.etag
    );

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(6);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(6);
  });

  test('COMPLETE_006: Outbound completion to zero units results in RELEASED status', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    expect(consignment.units_on_hand).toBe(10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    let dr = await createOutboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_in_use_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 10 },
      dr.etag
    );

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(0);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
  });

  test('COMPLETE_007: Outbound completion cannot remove more than available', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    expect(consignment.units_on_hand).toBe(10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 10, PRIORITIES.STANDARD);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubBefore = await getHub(hub.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 12 },
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(hubBefore.staging_in_use_units);
  });

  test('COMPLETE_008: Large variance triggers auto-hold and records variance_units', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 6 },
      dr.etag
    );

    expectSuccess(res);

    const completeData = getData(res);
    expect(completeData.auto_hold_id).toBeDefined();
    expect(completeData.auto_hold_id).not.toBeNull();

    const hold = await getHold(hub.id, completeData.auto_hold_id);
    expect(hold.kind).toBe(HOLD_KINDS.DAMAGE);
    expect(hold.source).toBe(HOLD_SOURCES.AUTO_VARIANCE);
    expect(hold.source_dock_request_id).toBe(dr.id);
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.variance_units).toBe(-4);
  });

  test('COMPLETE_009: Creating outbound DRAFT is allowed despite open hold', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 6 },
      dr.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();

    const res = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: 'OUTBOUND',
      units: 1,
      priority: PRIORITIES.STANDARD,
    });

    expectSuccess(res);
    const data = getData(res);
    expect(data.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('COMPLETE_010: Submitting outbound is blocked by open hold', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inboundDr = await createInboundDraft(hub.id, consignment.id, 10);
    inboundDr = await submitAndGet(hub.id, inboundDr);
    inboundDr = await scheduleAndGet(hub.id, inboundDr);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inboundDr.id}/complete`,
      { actual_units: 6 },
      inboundDr.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();

    const createRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: 'OUTBOUND',
      units: 1,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(createRes);
    const outboundDr = getData(createRes);
    expect(outboundDr.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outboundDr.id}/submit`,
      {},
      outboundDr.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drAfter = await getDockRequest(hub.id, outboundDr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('COMPLETE_013: Large negative variance in LOCKDOWN creates auto-hold and updates posture to OPEN', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'ALL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 20);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(20);
    expect(hubBefore.staging_free_units).toBe(0);
    expect(hubBefore.posture).toBe('LOCKDOWN');

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 5 },
      dr.etag
    );

    expectSuccess(res);
    const completeData = getData(res);

    expect(completeData.auto_hold_id).toBeDefined();
    expect(completeData.auto_hold_id).not.toBeNull();
    const holdId = completeData.auto_hold_id;

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drAfter.variance_units).toBe(-15);

    const hold = await getHold(hub.id, holdId);
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);
    expect(hold.kind).toBe(HOLD_KINDS.DAMAGE);
    expect(hold.source).toBe(HOLD_SOURCES.AUTO_VARIANCE);
    expect(hold.source_dock_request_id).toBe(dr.id);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(5);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(5);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(15);
    expect(hubAfter.posture).toBe('OPEN');
  });

  test('COMPLETE_014: Positive variance (actual > planned) creates auto-hold', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'PLUS10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_reserved_units).toBe(10);
    expect(hubBefore.staging_free_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 13 },
      dr.etag
    );

    expectSuccess(res);
    const completeData = getData(res);

    expect(completeData.auto_hold_id).toBeDefined();
    expect(completeData.auto_hold_id).not.toBeNull();
    const holdId = completeData.auto_hold_id;

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drAfter.variance_units).toBe(3);

    const hold = await getHold(hub.id, holdId);
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);
    expect(hold.kind).toBe(HOLD_KINDS.DAMAGE);
    expect(hold.source).toBe(HOLD_SOURCES.AUTO_VARIANCE);
    expect(hold.source_dock_request_id).toBe(dr.id);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(13);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(13);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(7);
    expect(hubAfter.posture).toBe('OPEN');
  });

  test('COMPLETE_015: Small variance (< 3) does not create hold, outbound submit succeeds', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'NOHOLD',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 12 },
      dr.etag
    );
    expectSuccess(completeRes);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drAfter.variance_units).toBe(2);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(12);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(12);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(8);
    expect(hubAfter.posture).toBe('OPEN');

    const outboundDr = await createOutboundDraft(hub.id, consignment.id, 1);
    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outboundDr.id}/submit`,
      {},
      outboundDr.etag
    );

    expectSuccess(submitRes);

    const outboundAfter = await getDockRequest(hub.id, outboundDr.id);
    expect(outboundAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });
});
