import { post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectStatus,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createConsignment,
  getConsignment,
  getHub,
  getDockRequest,
  getHold,
  createHold,
  clearHold,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  completeAndGet,
  batchSchedule,
  createConsignmentAtHub,
  runOps,
  cancelDockRequest,
  voidDockRequest,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  HOLD_KINDS,
  POSTURES,
} from '../../../test-helpers/constants';

describe('Cross-Feature Interaction Tests', () => {

  test('CROSS_001: In CONGESTED posture, inbound submission for 1 unit succeeds due to minimum rule', async () => {

    const hub = await createHub(undefined, 20);
    const fillConsignment = await createConsignment(hub.id, {
      reference: 'FILL17',
      declared_units: 17,
      commodity: COMMODITIES.GENERAL,
    });

    let fillDr = await createInboundDraft(hub.id, fillConsignment.id, 17);
    fillDr = await submitAndGet(hub.id, fillDr);
    fillDr = await scheduleAndGet(hub.id, fillDr);
    fillDr = await completeAndGet(hub.id, fillDr, 17);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.CONGESTED);
    expect(hubState.staging_free_units).toBe(3);

    const consignment = await createConsignment(hub.id, {
      reference: 'OUT',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });

    const dr = await createInboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('CROSS_002: In LOCKDOWN, outbound submission fails if consignment has no units on hand', async () => {

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

    const consignment = await createConsignment(hub.id, {
      reference: 'REL',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });

    const dr = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSIGNMENT_EMPTY);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('CROSS_003: Clearing hold allows outbound dock request to be scheduled', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const h0 = await getHold(hub.id, hold.id);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/clear`,
      {},
      h0.etag
    );

    expectSuccess(clearRes);

    const drAfterClear = await getDockRequest(hub.id, dr.id);
    expect(drAfterClear.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleRes = await batchSchedule(hub.id, [dr.id]);
    expect(scheduleRes.scheduled_ids).toContain(dr.id);

    const drAfterSchedule = await getDockRequest(hub.id, dr.id);
    expect(drAfterSchedule.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('CROSS_004: Completing inbound in CONGESTED hub keeps posture CONGESTED', async () => {

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

    const consignment = await createConsignment(hub.id, {
      reference: 'X2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 1);

    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleResult = await batchSchedule(hub.id, [dr.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr.id);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    dr = await completeAndGet(hub.id, dr, 1);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    hubState = await getHub(hub.id);

    expect(hubState.posture).toBe(POSTURES.CONGESTED);
    expect(hubState.staging_free_units).toBe(3);
    expect(hubState.staging_in_use_units).toBe(17);
  });

  test('CROSS_005: LOCKDOWN from reservation blocking inbound submit', async () => {

    const hub = await createHub(undefined, 20);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'R20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment1.id, 20);

    dr1 = await submitAndGet(hub.id, dr1);
    const scheduleResult = await batchSchedule(hub.id, [dr1.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr1.id);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_reserved_units).toBe(20);
    expect(hubState.staging_free_units).toBe(0);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'NEXT',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });

    const dr2 = await createInboundDraft(hub.id, consignment2.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_reserved_units).toBe(20);
    expect(hubState.staging_free_units).toBe(0);
  });

  test('CROSS_006: EXPIRED request allows new submit after hold cleared', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 1);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    await runOps(hub.id);
    await runOps(hub.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const h0 = await getHold(hub.id, hold.id);
    await clearHold(hub.id, h0.id, h0.etag);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    const drOriginal = await getDockRequest(hub.id, dr.id);
    expect(drOriginal.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe('AT_HUB');
    expect(consignmentAfter.units_on_hand).toBe(10);

    const hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(10);
  });

  test('CROSS_007: Outbound completion in LOCKDOWN enables inbound', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment: filledConsignment } = await createConsignmentAtHub(hub.id, 20);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_in_use_units).toBe(20);
    expect(hubState.staging_free_units).toBe(0);

    let dr = await createOutboundDraft(hub.id, filledConsignment.id, 5);
    dr = await submitAndGet(hub.id, dr);

    const scheduleResult = await batchSchedule(hub.id, [dr.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr.id);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);

    dr = await completeAndGet(hub.id, dr, 5);

    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(15);
    expect(hubState.staging_free_units).toBe(5);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'NEWIN',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });

    let in2 = await createInboundDraft(hub.id, consignment2.id, 5);
    in2 = await submitAndGet(hub.id, in2);
    expect(in2.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('CROSS_008: Hold on PLANNED consignment does not block inbound', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      reference: 'PLANNED10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    expect(consignment.status).toBe('PLANNED');
    expect(consignment.units_on_hand).toBe(0);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs before receipt',
    });
    expect(hold.status).toBe('OPEN');

    const dr = await createInboundDraft(hub.id, consignment.id, 5);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe('OPEN');

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe('PLANNED');
    expect(consignmentAfter.units_on_hand).toBe(0);
  });

  test('CROSS_009: EXPIRED request, hold still blocks new outbound', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 1);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    await runOps(hub.id);
    await runOps(hub.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const drOriginal = await getDockRequest(hub.id, dr.id);
    expect(drOriginal.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe('OPEN');

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe('AT_HUB');
    expect(consignmentAfter.units_on_hand).toBe(10);

    const hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(10);
    expect(hubState.staging_reserved_units).toBe(0);
  });

  test('CROSS_010: CONGESTED cap + cancel recovery', async () => {

    const hub = await createHub(undefined, 20);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'R16',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment1.id, 16);

    dr1 = await submitAndGet(hub.id, dr1);
    const scheduleResult = await batchSchedule(hub.id, [dr1.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr1.id);
    let sch1 = await getDockRequest(hub.id, dr1.id);
    expect(sch1.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.CONGESTED);
    expect(hubState.staging_reserved_units).toBe(16);
    expect(hubState.staging_free_units).toBe(4);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'TRY2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr2 = await createInboundDraft(hub.id, consignment2.id, 2);

    let res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    dr2 = await getDockRequest(hub.id, dr2.id);
    expect(dr2.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    sch1 = await getDockRequest(hub.id, dr1.id);
    await cancelDockRequest(hub.id, sch1.id, sch1.etag);

    sch1 = await getDockRequest(hub.id, dr1.id);
    expect(sch1.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.OPEN);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);

    dr2 = await getDockRequest(hub.id, dr2.id);
    res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    dr2 = await getDockRequest(hub.id, dr2.id);
    expect(dr2.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_reserved_units).toBe(0);
  });

  test('CROSS_011: Mixed priority batch scheduling', async () => {

    const hub = await createHub(undefined, 20);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'ON15',
      declared_units: 15,
      commodity: COMMODITIES.GENERAL,
    });

    let in15 = await createInboundDraft(hub.id, consignment1.id, 15);
    in15 = await submitAndGet(hub.id, in15);
    in15 = await scheduleAndGet(hub.id, in15);
    in15 = await completeAndGet(hub.id, in15, 15);
    expect(in15.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    let hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(15);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(5);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    let out10 = await createOutboundDraft(hub.id, consignment1.id, 10, PRIORITIES.EXPEDITE);
    out10 = await submitAndGet(hub.id, out10);
    expect(out10.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'IN10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let in10 = await createInboundDraft(hub.id, consignment2.id, 10, PRIORITIES.DEFERRED);
    in10 = await submitAndGet(hub.id, in10);
    expect(in10.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleRes = await batchSchedule(hub.id, [out10.id, in10.id]);

    expect(scheduleRes.scheduled_ids).toContain(out10.id);

    expect(scheduleRes.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: in10.id,
          error_code: ERROR_CODES.ERR_CAPACITY_EXCEEDED,
        }),
      ])
    );

    out10 = await getDockRequest(hub.id, out10.id);
    expect(out10.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
    expect(out10.direction).toBe('OUTBOUND');

    in10 = await getDockRequest(hub.id, in10.id);
    expect(in10.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(15);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(5);
    expect(hubState.posture).toBe(POSTURES.OPEN);
  });

  test('CROSS_013: Void inbound makes outbound schedule fail ERR_CONSIGNMENT_EMPTY', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'UNSCHED-AFTER-VOID',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inDr = await createInboundDraft(hub.id, consignment.id, 10);
    inDr = await submitAndGet(hub.id, inDr);
    inDr = await scheduleAndGet(hub.id, inDr);
    inDr = await completeAndGet(hub.id, inDr, 10);
    expect(inDr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    let consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe('AT_HUB');
    expect(consignmentState.units_on_hand).toBe(10);

    let outDr = await createOutboundDraft(hub.id, consignment.id, 10);
    outDr = await submitAndGet(hub.id, outDr);
    expect(outDr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    inDr = await getDockRequest(hub.id, inDr.id);
    await voidDockRequest(hub.id, inDr.id, inDr.etag);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe('PLANNED');
    expect(consignmentState.units_on_hand).toBe(0);

    let hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    const scheduleRes = await batchSchedule(hub.id, [outDr.id]);

    expect(scheduleRes.scheduled_ids).not.toContain(outDr.id);
    expect(scheduleRes.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: outDr.id,
          error_code: ERROR_CODES.ERR_CONSIGNMENT_EMPTY,
        }),
      ])
    );

    outDr = await getDockRequest(hub.id, outDr.id);
    expect(outDr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);
    expect(hubState.posture).toBe(POSTURES.OPEN);
  });

  test('SCHEDULE_011: Scheduling into CONGESTED', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'R16',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 16);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    const scheduleRes = await batchSchedule(hub.id, [dr.id]);

    expect(scheduleRes.scheduled_ids).toContain(dr.id);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_reserved_units).toBe(16);
    expect(hubState.staging_free_units).toBe(4);
    expect(hubState.posture).toBe(POSTURES.CONGESTED);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('SCOPE_001: Cross-hub scheduling fails ERR_NOT_FOUND', async () => {

    const hub1 = await createHub('Hub1', 20);
    const hub2 = await createHub('Hub2', 20);

    const consignment = await createConsignment(hub1.id, {
      reference: 'X',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub1.id, consignment.id, 10);
    dr = await submitAndGet(hub1.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hub1Before = await getHub(hub1.id);
    const hub2Before = await getHub(hub2.id);

    const scheduleRes = await batchSchedule(hub2.id, [dr.id]);

    expect(scheduleRes.rejected).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          dock_request_id: dr.id,
          error_code: ERROR_CODES.ERR_NOT_FOUND,
        }),
      ])
    );

    dr = await getDockRequest(hub1.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hub1After = await getHub(hub1.id);
    expect(hub1After.staging_reserved_units).toBe(hub1Before.staging_reserved_units);
    expect(hub1After.staging_in_use_units).toBe(hub1Before.staging_in_use_units);

    const hub2After = await getHub(hub2.id);
    expect(hub2After.staging_reserved_units).toBe(hub2Before.staging_reserved_units);
    expect(hub2After.staging_in_use_units).toBe(hub2Before.staging_in_use_units);
  });
});
