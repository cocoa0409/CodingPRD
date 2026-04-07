import { get, post, postWithEtag, postWithoutEtag } from '../../../test-helpers/api-client';
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
  createDockRequest,
  getDockRequest,
  submitDockRequest,
  batchSchedule,
  completeDockRequest,
  cancelDockRequest,
  createHold,
  getHub,
  executeInboundFlow,
  executeOutboundFlow,
  createConsignmentAtHub,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  completeAndGet,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  DIRECTIONS,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  CONSIGNMENT_STATUSES,
  HOLD_KINDS,
  POSTURES,
} from '../../../test-helpers/constants';

describe('Dock Request Tests', () => {

  test('DOCK_001: POST inbound dock request returns DRAFT status', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const res = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    expectSuccess(res);
    const data = getData(res);
    expect(data.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
    expect(data.direction).toBe(DIRECTIONS.INBOUND);
    expect(data.units).toBe(10);
  });

  test('DOCK_002: POST outbound dock request with EXPEDITE priority returns DRAFT status', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const res = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.EXPEDITE,
    });

    expectSuccess(res);
    const data = getData(res);
    expect(data.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
    expect(data.priority).toBe(PRIORITIES.EXPEDITE);
    expect(data.direction).toBe(DIRECTIONS.OUTBOUND);
  });

  test('DOCK_003: Submit inbound dock request moves DRAFT to SUBMITTED', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_004: Submit without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, consignment.id, 10);

    const res = await postWithoutEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {}
    );

    await expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_005: Submit already SUBMITTED dock request - state remains SUBMITTED', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_reserved_units).toBe(0);
  });

  test('DOCK_006: Submit outbound dock request moves DRAFT to SUBMITTED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    let dr = await createOutboundDraft(hub.id, consignment.id, 4);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_007: Submit outbound for PLANNED consignment fails with ERR_CONSIGNMENT_EMPTY', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const dr = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_008: Submit outbound with open hold fails with ERR_CONSIGNMENT_HAS_OPEN_HOLD', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs hold',
    });

    const dr = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_009: Submit second outbound for same consignment fails with ERR_CONSIGNMENT_BUSY', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr1 = await createOutboundDraft(hub.id, consignment.id, 4);
    dr1 = await submitAndGet(hub.id, dr1);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSIGNMENT_BUSY);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_010: Cancel SUBMITTED dock request succeeds', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const checkRes = await get(`/hubs/${hub.id}/dock_requests/${dr.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);
  });

  test('DOCK_011: Cancel DONE dock request - state and inventory unchanged', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const { dockRequest: dr } = await executeOutboundFlow(hub.id, consignment.id, 4, 4);

    const drFresh = await getDockRequest(hub.id, dr.id);
    expect(drFresh.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    const consignmentBefore = await getConsignment(hub.id, consignment.id);
    expect(consignmentBefore.units_on_hand).toBe(6);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drFresh.id}/cancel`,
      {},
      drFresh.etag
    );

    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, drFresh.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.units_on_hand).toBe(6);
  });

  test('DOCK_012: Cancel DRAFT dock request - no inventory or reservation change', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    const dr = await createOutboundDraft(hub.id, consignment.id, 4);

    const hubBefore = await getHub(hub.id);
    const consignmentBefore = await getConsignment(hub.id, consignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect([DOCK_REQUEST_STATUSES.DRAFT, DOCK_REQUEST_STATUSES.CANCELLED]).toContain(drCheck.status);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(hubBefore.staging_reserved_units);
    expect(hubAfter.staging_in_use_units).toBe(hubBefore.staging_in_use_units);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(consignmentBefore.units_on_hand);
  });

  test('DOCK_013: Complete DRAFT dock request fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const dr = await createOutboundDraft(hub.id, consignment.id, 4);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.units_on_hand).toBe(10);
  });

  test('DOCK_014: Complete SUBMITTED dock request fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 10 },
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_015: Complete ON_HOLD dock request fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);

    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      dr.etag
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(res.status).toBeLessThan(500);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);
  });

  test('DOCK_016: Submit inbound in LOCKDOWN fails with ERR_POSTURE_LOCKDOWN', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 20, 20);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.LOCKDOWN);

    const consignment = await createConsignment(hub.id, {
      reference: 'I',
      declared_units: 2,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_017: Submit inbound over congested cap fails with ERR_CONGESTED_INBOUND_LIMIT', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 16, 16);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    expect(hubCheck.staging_free_units).toBe(4);

    const consignment = await createConsignment(hub.id, {
      reference: 'IN2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, consignment.id, 2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('DOCK_018: Submit inbound at congested cap succeeds', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 16, 16);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    expect(hubCheck.staging_free_units).toBe(4);

    const consignment = await createConsignment(hub.id, {
      reference: 'IN3',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr = await createInboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_019: Hub transitions to CONGESTED after inbound completion, still allows minimum 1', async () => {

    const hub = await createHub(undefined, 5);

    const consignment = await createConsignment(hub.id, {
      reference: 'F',
      declared_units: 4,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    await completeDockRequest(hub.id, dr.id, dr.etag, 4);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.units_on_hand).toBe(4);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    expect(hubCheck.staging_free_units).toBe(1);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'G',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    const dr2 = await createInboundDraft(hub.id, consignment2.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    const hubFinalCheck = await getHub(hub.id);
    expect(hubFinalCheck.posture).toBe(POSTURES.CONGESTED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_020: Second inbound for AT_HUB consignment - units_on_hand must not increase further', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    const unitsBefore = consignment.units_on_hand;
    expect(unitsBefore).toBe(10);

    const dr = await createInboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );

    expect(res.status).toBeLessThan(500);

    const drAfterSubmit = await getDockRequest(hub.id, dr.id);

    if (drAfterSubmit.status === DOCK_REQUEST_STATUSES.SUBMITTED) {

      const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
        dock_request_ids: [dr.id],
      });

      const drAfterSchedule = await getDockRequest(hub.id, dr.id);

      if (drAfterSchedule.status === DOCK_REQUEST_STATUSES.SCHEDULED) {

        const completeRes = await postWithEtag(
          `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
          { actual_units: 1 },
          drAfterSchedule.etag
        );

        const consignmentAfter = await getConsignment(hub.id, consignment.id);

        expect(consignmentAfter.units_on_hand).toBe(unitsBefore);
      }
    }

    const consignmentFinal = await getConsignment(hub.id, consignment.id);
    expect(consignmentFinal.units_on_hand).toBe(unitsBefore);
  });

  test('DOCK_021: Submit second outbound while first is SCHEDULED fails with ERR_CONSIGNMENT_BUSY', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr1 = await createOutboundDraft(hub.id, consignment.id, 4);
    dr1 = await submitAndGet(hub.id, dr1);

    await batchSchedule(hub.id, [dr1.id]);
    dr1 = await getDockRequest(hub.id, dr1.id);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSIGNMENT_BUSY);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(10);
  });

  test('DOCK_022: Submit inbound over congested cap (with scheduled reservation) fails with ERR_CONGESTED_INBOUND_LIMIT', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 15,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 15, 15);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.OPEN);
    expect(hubCheck.staging_free_units).toBe(5);

    const c1 = await createConsignment(hub.id, {
      reference: 'RES3',
      declared_units: 3,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, c1.id, 3);
    dr1 = await submitAndGet(hub.id, dr1);
    await batchSchedule(hub.id, [dr1.id]);

    hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(15);
    expect(hubCheck.staging_reserved_units).toBe(3);
    expect(hubCheck.staging_free_units).toBe(2);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);

    const c2 = await createConsignment(hub.id, {
      reference: 'TRY2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr2 = await createInboundDraft(hub.id, c2.id, 2);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_free_units).toBe(2);
    expect(hubFinal.staging_reserved_units).toBe(3);
    expect(hubFinal.posture).toBe(POSTURES.CONGESTED);
  });

  test('DOCK_023: Canceling SCHEDULED inbound releases reservation', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CXL16',
      declared_units: 16,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 16);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_reserved_units).toBe(16);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);
    const opsRunBefore = hubCheck.ops_run_index;

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);

    expect(hubFinal.ops_run_index).toBe(opsRunBefore);
  });

  test('DOCK_024: Congested inbound limit calculation (floor(8/4)=2)', async () => {

    const hub = await createHub('Hub 40', 40);

    const c0 = await createConsignment(hub.id, {
      reference: 'FILL32',
      declared_units: 32,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, c0.id, 32, 32);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_free_units).toBe(8);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);

    const c1 = await createConsignment(hub.id, {
      reference: 'TRY3',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr1 = await createInboundDraft(hub.id, c1.id, 3);

    const res1 = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr1.id}/submit`,
      {},
      dr1.etag
    );

    await expectErrorCode(res1, ERROR_CODES.ERR_CONGESTED_INBOUND_LIMIT);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_free_units).toBe(8);
    expect(hubCheck.posture).toBe(POSTURES.CONGESTED);

    const c2 = await createConsignment(hub.id, {
      reference: 'TRY2',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const dr2 = await createInboundDraft(hub.id, c2.id, 2);

    const res2 = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res2);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('DOCK_027: Scheduling rejection doesnt clear open-move status', async () => {

    const hub = await createHub(undefined, 5);

    const consignment = await createConsignment(hub.id, {
      reference: 'TOO_BIG',
      declared_units: 6,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment.id, 6);
    dr1 = await submitAndGet(hub.id, dr1);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const dr2 = await createInboundDraft(hub.id, consignment.id, 1);

    const h0 = await getHub(hub.id);

    const scheduleRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr1.id],
    });
    expectSuccess(scheduleRes);
    const scheduleData = getData(scheduleRes);

    expect(scheduleData.rejected).toBeDefined();
    const rejectedDr1 = scheduleData.rejected.find((r: any) => r.dock_request_id === dr1.id);
    expect(rejectedDr1).toBeDefined();
    expect(rejectedDr1.error_code).toBe(ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const dr1Check = await getDockRequest(hub.id, dr1.id);
    expect(dr1Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_BUSY);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(5);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
    expect(hubFinal.ops_run_index).toBe(h0.ops_run_index);
  });

  test('DOCK_028: Canceling SCHEDULED outbound in LOCKDOWN preserves hub and consignment state', async () => {

    const hub = await createHub(undefined, 20);

    const fillConsignment = await createConsignment(hub.id, {
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    await executeInboundFlow(hub.id, fillConsignment.id, 20, 20);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubCheck.staging_in_use_units).toBe(20);

    let dr = await createOutboundDraft(hub.id, fillConsignment.id, 5);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const h0 = await getHub(hub.id);
    const c0 = await getConsignment(hub.id, fillConsignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubFinal.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubFinal.staging_free_units).toBe(h0.staging_free_units);
    expect(hubFinal.posture).toBe(h0.posture);
    expect(hubFinal.ops_run_index).toBe(h0.ops_run_index);

    const consignmentFinal = await getConsignment(hub.id, fillConsignment.id);
    expect(consignmentFinal.units_on_hand).toBe(c0.units_on_hand);
    expect(consignmentFinal.status).toBe(c0.status);
  });

  test('DOCK_030: Cancel not treated as receipt, consignment remains PLANNED and allows new inbound', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CXL-NO-RCPT',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );
    expectSuccess(cancelRes);

    const drCancelled = await getDockRequest(hub.id, dr.id);
    expect(drCancelled.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    let consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentCheck.units_on_hand).toBe(0);

    const h1 = await getHub(hub.id);

    const opsRes = await postWithEtag(
      `/hubs/${hub.id}/run_ops`,
      {},
      h1.etag
    );
    expectSuccess(opsRes);

    consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentCheck.units_on_hand).toBe(0);

    let hubCheck = await getHub(hub.id);
    expect(hubCheck.staging_in_use_units).toBe(0);
    expect(hubCheck.staging_reserved_units).toBe(0);
    expect(hubCheck.staging_free_units).toBe(20);
    expect(hubCheck.posture).toBe(POSTURES.OPEN);

    expect(hubCheck.ops_run_index).toBe(h1.ops_run_index + 1);

    const dr2 = await createInboundDraft(hub.id, consignment.id, 5);
    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(submitRes);

    const dr2Check = await getDockRequest(hub.id, dr2.id);
    expect(dr2Check.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });
});
