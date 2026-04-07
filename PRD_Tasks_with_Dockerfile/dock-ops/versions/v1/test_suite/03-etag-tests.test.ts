import { get, post, postWithEtag, putWithEtag, putWithoutEtag } from '../../../test-helpers/api-client';
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
  getConsignment,
  getHold,
  submitDockRequest,
  batchSchedule,
  completeDockRequest,
  createHold,
  executeInboundFlow,
  createConsignmentAtHub,
  runOps,
  executeOutboundFlow,
} from '../../../test-helpers/resources';
import {
  DIRECTIONS,
  PRIORITIES,
  COMMODITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  HOLD_STATUSES,
  HOLD_KINDS,
  CONSIGNMENT_STATUSES,
} from '../../../test-helpers/constants';

describe('ETag Tests', () => {

  test('ETAG_002: PUT without If-Match header returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    expect(dr.units).toBe(4);

    const res = await putWithoutEtag(`/hubs/${hub.id}/dock_requests/${dr.id}`, {
      units: 5,
      priority: PRIORITIES.STANDARD,
    });

    await expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.units).toBe(4);
  });

  test('ETAG_003: PUT with stale etag returns ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    expect(dr.units).toBe(4);

    const res = await putWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}`, {
      units: 5,
      priority: PRIORITIES.STANDARD,
    }, 'stale');

    await expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.units).toBe(4);
  });

  test('ETAG_004: PUT with correct etag updates dock request successfully', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    expect(dr.units).toBe(4);
    expect(dr.priority).toBe(PRIORITIES.STANDARD);

    const res = await putWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}`, {
      units: 5,
      priority: PRIORITIES.DEFERRED,
    }, dr.etag);

    expectSuccess(res);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.units).toBe(5);
    expect(drCheck.priority).toBe(PRIORITIES.DEFERRED);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('ETAG_005: Submit with stale etag after PUT fails with ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    const originalEtag = dr.etag;

    const putRes = await putWithEtag(`/hubs/${hub.id}/dock_requests/${dr.id}`, {
      units: 5,
      priority: PRIORITIES.DEFERRED,
    }, dr.etag);
    expectSuccess(putRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      originalEtag
    );

    await expectErrorCode(submitRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.units).toBe(5);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);
  });

  test('ETAG_006: Cancel with stale etag after submit fails with ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    const dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });
    const originalEtag = dr.etag;

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      originalEtag
    );

    await expectErrorCode(cancelRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('ETAG_007: Cancel with fresh etag after submit succeeds', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    let dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expectSuccess(cancelRes);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);
  });

  test('ETAG_008: Cancel with stale etag fails after hold changes dock request status', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);
    const updatedConsignment = await getConsignment(hub.id, consignment.id);

    let dr = await createDockRequest(hub.id, {
      consignment_id: updatedConsignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
    const submittedEtag = dr.etag;

    const hold = await createHold(hub.id, {
      consignment_id: updatedConsignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const drAfterHold = await getDockRequest(hub.id, dr.id);
    expect(drAfterHold.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      submittedEtag
    );

    await expectErrorCode(cancelRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);
  });

  test('ETAG_009: Cancel with fresh etag succeeds after hold changes dock request status', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);
    const updatedConsignment = await getConsignment(hub.id, consignment.id);

    let dr = await createDockRequest(hub.id, {
      consignment_id: updatedConsignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 4,
      priority: PRIORITIES.STANDARD,
    });

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
      {},
      dr.etag
    );
    expectSuccess(submitRes);

    const hold = await createHold(hub.id, {
      consignment_id: updatedConsignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );

    expectSuccess(cancelRes);

    const drCheck = await getDockRequest(hub.id, dr.id);
    expect(drCheck.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);
  });

  test('ETAG_010: Void consignment with stale etag fails after hold reopens consignment', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10);

    await executeOutboundFlow(hub.id, consignment.id, 10);

    let c = await getConsignment(hub.id, consignment.id);
    expect(c.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    await runOps(hub.id);

    c = await getConsignment(hub.id, consignment.id);
    expect(c.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    const closedEtag = c.etag;

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.CUSTOMS,
      note: 'audit',
    });
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const cAfterHold = await getConsignment(hub.id, consignment.id);
    expect(cAfterHold.status).not.toBe(CONSIGNMENT_STATUSES.CLOSED);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      closedEtag
    );

    await expectErrorCode(voidRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);
  });
});
