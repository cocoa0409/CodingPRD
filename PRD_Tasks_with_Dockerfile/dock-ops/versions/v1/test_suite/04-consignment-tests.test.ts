import { get, post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectStatus,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  getHub,
  createConsignment,
  getConsignment,
  createDockRequest,
  getDockRequest,
  submitDockRequest,
  batchSchedule,
  createHold,
  getHold,
  executeInboundFlow,
  executeOutboundFlow,
  createConsignmentAtHub,
  createReleasedConsignment,
  createClosedConsignment,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  DIRECTIONS,
  PRIORITIES,
  ERROR_CODES,
  CONSIGNMENT_STATUSES,
  HOLD_STATUSES,
  HOLD_KINDS,
  HOLD_SOURCES,
} from '../../../test-helpers/constants';

describe('Consignment Tests', () => {

  test('CONSIGNMENT_001: POST new consignment returns PLANNED status with 0 units_on_hand', async () => {

    const hub = await createHub(undefined, 20);

    const res = await post(`/hubs/${hub.id}/consignments`, {
      reference: 'CNEW',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    expectStatus(res, 201);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(data.units_on_hand).toBe(0);
    expect(data.commodity).toBe(COMMODITIES.GENERAL);
  });

  test('CONSIGNMENT_002: GET consignment shows AT_HUB when units_on_hand > 0', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(data.units_on_hand).toBe(10);
  });

  test('CONSIGNMENT_003: After outbound completion, units_on_hand is decreased', async () => {

    const hub = await createHub(undefined, 100);

    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await executeInboundFlow(hub.id, consignment.id, 10, 10);

    await executeOutboundFlow(hub.id, consignment.id, 4, 4);

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(data.units_on_hand).toBe(6);
  });

  test('CONSIGNMENT_004: GET consignment shows RELEASED when all units shipped after receipt', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createReleasedConsignment(hub.id, 10);

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(data.units_on_hand).toBe(0);
  });

  test('CONSIGNMENT_005: GET consignment shows CLOSED after ops run on RELEASED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createClosedConsignment(hub.id, 10);

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(data.units_on_hand).toBe(0);
  });

  test('CONSIGNMENT_006: CLOSED consignment reverts to RELEASED when new hold is added', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createClosedConsignment(hub.id, 10);

    let consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.status).toBe(CONSIGNMENT_STATUSES.CLOSED);

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'late docs',
    });

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(data.units_on_hand).toBe(0);
  });

  test('CONSIGNMENT_007: Void PLANNED consignment succeeds and sets status=VOIDED', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const c0 = await getConsignment(hub.id, consignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c0.etag
    );

    expectSuccess(res);

    const checkRes = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(CONSIGNMENT_STATUSES.VOIDED);
  });

  test('CONSIGNMENT_008: Void AT_HUB consignment fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const c0 = await getConsignment(hub.id, consignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/consignments/${c0.id}/void`,
      {},
      c0.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const checkRes = await get(`/hubs/${hub.id}/consignments/${c0.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
  });

  test('CONSIGNMENT_009: Void PLANNED consignment with dock request fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    dr = await getDockRequest(hub.id, dr.id);
    await submitDockRequest(hub.id, dr.id, dr.etag);

    const c0 = await getConsignment(hub.id, consignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c0.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const checkRes = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);
    expectSuccess(checkRes);
    expect(getData(checkRes).status).toBe(CONSIGNMENT_STATUSES.PLANNED);
  });

  test('CONSIGNMENT_010: Void PLANNED consignment with active hold fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const c1 = await getConsignment(hub.id, consignment.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c1.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);
  });

  test('CONSIGNMENT_011: Actions on VOIDED consignment fail - dock request cannot be scheduled', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const c0 = await getConsignment(hub.id, consignment.id);
    await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c0.etag
    );

    const voidedConsignment = await getConsignment(hub.id, consignment.id);
    expect(voidedConsignment.status).toBe(CONSIGNMENT_STATUSES.VOIDED);

    const createRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 1,
      priority: PRIORITIES.STANDARD,
    });

    if (createRes.status >= 400) {
      await expectErrorCode(createRes, ERROR_CODES.ERR_INVALID_STATE);
    } else {

      expectSuccess(createRes);
      const dr = getData(createRes);
      const submitRes = await postWithEtag(
        `/hubs/${hub.id}/dock_requests/${dr.id}/submit`,
        {},
        dr.etag
      );
      await expectErrorCode(submitRes, ERROR_CODES.ERR_INVALID_STATE);
    }

    const hubCheck = await get(`/hubs/${hub.id}`);
    expectSuccess(hubCheck);
    const hubData = getData(hubCheck);
    expect(hubData.staging_reserved_units).toBe(0);
    expect(hubData.staging_in_use_units).toBe(0);
  });

  test('CONSIGNMENT_012: GET consignment shows COLD_CHAIN commodity', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 8,
      commodity: COMMODITIES.COLD_CHAIN,
    });

    const res = await get(`/hubs/${hub.id}/consignments/${consignment.id}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.commodity).toBe(COMMODITIES.COLD_CHAIN);
    expect(data.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
  });

  test('CONSIGNMENT_013: Auto-variance hold has correct source and source_dock_request_id', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createDockRequest(hub.id, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });

    dr = await getDockRequest(hub.id, dr.id);
    await submitDockRequest(hub.id, dr.id, dr.etag);

    await batchSchedule(hub.id, [dr.id]);
    dr = await getDockRequest(hub.id, dr.id);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 13 },
      dr.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();

    const autoHoldId = completeData.auto_hold_id;

    const res = await get(`/hubs/${hub.id}/holds/${autoHoldId}`);

    expectStatus(res, 200);
    const data = getData(res);
    expect(data.status).toBe(HOLD_STATUSES.OPEN);
    expect(data.kind).toBe(HOLD_KINDS.DAMAGE);
    expect(data.source).toBe(HOLD_SOURCES.AUTO_VARIANCE);
    expect(data.source_dock_request_id).toBe(dr.id);
  });

  test('CONSIGNMENT_014: RELEASED consignment with open hold does not become CLOSED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createReleasedConsignment(hub.id, 10);

    let consignmentCheck = await getConsignment(hub.id, consignment.id);
    expect(consignmentCheck.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const h0 = await getHub(hub.id);
    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    expectSuccess(res);

    const finalCheck = await getConsignment(hub.id, consignment.id);
    expect(finalCheck.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
  });

  test('CONSIGNMENT_015: Submit dock request for voided consignment fails', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const drRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.OUTBOUND,
      units: 1,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(drRes);
    const drDraft = getData(drRes);

    const c0 = await getConsignment(hub.id, consignment.id);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c0.etag
    );
    expectSuccess(voidRes);

    const h0Res = await get(`/hubs/${hub.id}`);
    expectSuccess(h0Res);
    const h0 = getData(h0Res);

    const dr0 = await getDockRequest(hub.id, drDraft.id);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDraft.id}/submit`,
      {},
      dr0.etag
    );

    expect(submitRes.status).toBeGreaterThanOrEqual(400);
    expect(submitRes.status).toBeLessThan(500);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.VOIDED);
    expect(consignmentAfter.units_on_hand).toBe(0);

    const hubAfter = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfter);
    const hubData = getData(hubAfter);
    expect(hubData.staging_in_use_units).toBe(h0.staging_in_use_units);
    expect(hubData.staging_reserved_units).toBe(h0.staging_reserved_units);
    expect(hubData.staging_free_units).toBe(h0.staging_free_units);
    expect(hubData.posture).toBe(h0.posture);
  });

  test('CONSIGN_016: Void consignment with cleared hold succeeds', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'VCLR',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const h0 = await getHold(hub.id, hold.id);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold.id}/clear`,
      {},
      h0.etag
    );
    expectSuccess(clearRes);

    const c0 = await getConsignment(hub.id, consignment.id);

    const hub0Res = await get(`/hubs/${hub.id}`);
    expectSuccess(hub0Res);
    const hub0 = getData(hub0Res);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      c0.etag
    );

    expectSuccess(voidRes);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.VOIDED);
    expect(consignmentAfter.units_on_hand).toBe(0);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);

    const hubAfter = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfter);
    const hubData = getData(hubAfter);
    expect(hubData.staging_in_use_units).toBe(hub0.staging_in_use_units);
    expect(hubData.staging_reserved_units).toBe(hub0.staging_reserved_units);
    expect(hubData.staging_free_units).toBe(hub0.staging_free_units);
    expect(hubData.posture).toBe(hub0.posture);
    expect(hubData.ops_run_index).toBe(hub0.ops_run_index);
  });

  test('CONSIGNMENT_018: Void with stale etag returns ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'STALE-VOID',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    const c0 = await getConsignment(hub.id, consignment.id);
    const staleEtag = c0.etag;

    const inRes = await post(`/hubs/${hub.id}/dock_requests`, {
      consignment_id: consignment.id,
      direction: DIRECTIONS.INBOUND,
      units: 10,
      priority: PRIORITIES.STANDARD,
    });
    expectSuccess(inRes);
    let inDr = getData(inRes);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inDr.id}/submit`,
      {},
      inDr.etag
    );
    expectSuccess(submitRes);

    await batchSchedule(hub.id, [inDr.id]);

    inDr = await getDockRequest(hub.id, inDr.id);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inDr.id}/complete`,
      { actual_units: 10 },
      inDr.etag
    );
    expectSuccess(completeRes);

    const h1Res = await get(`/hubs/${hub.id}`);
    expectSuccess(h1Res);
    const h1 = getData(h1Res);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/consignments/${consignment.id}/void`,
      {},
      staleEtag
    );

    await expectErrorCode(voidRes, ERROR_CODES.ERR_VERSION_CONFLICT);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfter);
    const hubData = getData(hubAfter);
    expect(hubData.staging_in_use_units).toBe(10);
    expect(hubData.staging_reserved_units).toBe(0);
    expect(hubData.staging_free_units).toBe(10);
    expect(hubData.posture).toBe('OPEN');
    expect(hubData.ops_run_index).toBe(h1.ops_run_index);
  });
});
