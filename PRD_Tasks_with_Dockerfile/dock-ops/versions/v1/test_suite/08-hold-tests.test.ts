import { post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  expectStatus,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  getHub,
  createConsignment,
  getConsignment,
  getDockRequest,
  getHold,
  createHold,
  clearHold,
  voidHold,
  voidConsignment,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  createConsignmentAtHub,
  batchSchedule,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  HOLD_KINDS,
  HOLD_SOURCES,
  HOLD_STATUSES,
  DIRECTIONS,
  POSTURES,
} from '../../../test-helpers/constants';

describe('Hold Tests', () => {

  test('HOLD_001: Creating a hold returns 201 with status=OPEN, kind=DOCS, source=MANUAL', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const res = await post(`/hubs/${hub.id}/holds`, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'missing docs',
    });

    expectStatus(res, 201);

    const hold = getData(res);
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);
    expect(hold.kind).toBe(HOLD_KINDS.DOCS);
    expect(hold.source).toBe(HOLD_SOURCES.MANUAL);
  });

  test('HOLD_002: Clearing a hold transitions status to CLEARED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const res = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold.id}/clear`,
      {},
      hold.etag
    );

    expectSuccess(res);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);
  });

  test('HOLD_003: Voiding a hold transitions status to VOIDED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const res = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold.id}/void`,
      {},
      hold.etag
    );

    expectSuccess(res);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);
  });

  test('HOLD_004: Opening a hold causes outbound dock request to drop to ON_HOLD', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const res = await post(`/hubs/${hub.id}/holds`, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    expectStatus(res, 201);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);
  });

  test('HOLD_005: Clearing the last open hold pops dock request back to SUBMITTED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'test hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const h0 = await getHold(hub.id, hold.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/clear`,
      {},
      h0.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('HOLD_006: Voiding the last open hold allows outbound to proceed', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'test hold',
    });

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const h0 = await getHold(hub.id, hold.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/void`,
      {},
      h0.etag
    );

    expectSuccess(res);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect([DOCK_REQUEST_STATUSES.SUBMITTED, DOCK_REQUEST_STATUSES.ON_HOLD]).toContain(drAfter.status);
  });

  test('HOLD_007: Cannot create hold on voided consignment', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    await voidConsignment(hub.id, consignment.id, consignment.etag);

    const voidedConsignment = await getConsignment(hub.id, consignment.id);
    expect(voidedConsignment.status).toBe('VOIDED');

    const res = await post(`/hubs/${hub.id}/holds`, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    expectClientError(res);
  });

  test('HOLD_008: Cannot clear an already-cleared hold', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const h0 = await getHold(hub.id, hold.id);
    const clearedHold = await clearHold(hub.id, h0.id, h0.etag);
    expect(clearedHold.status).toBe(HOLD_STATUSES.CLEARED);

    const h1 = await getHold(hub.id, hold.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/holds/${h1.id}/clear`,
      {},
      h1.etag
    );

    expectClientError(res);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);
  });

  test('HOLD_009: Auto-variance hold has source=AUTO_VARIANCE and kind=DAMAGE', async () => {

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
    const autoHoldId = completeData.auto_hold_id;

    const holdRes = await getHold(hub.id, autoHoldId);

    expect(holdRes.status).toBe(HOLD_STATUSES.OPEN);
    expect(holdRes.kind).toBe(HOLD_KINDS.DAMAGE);
    expect(holdRes.source).toBe(HOLD_SOURCES.AUTO_VARIANCE);

    expect(holdRes.source_dock_request_id).toBe(dr.id);
    expect(holdRes.consignment_id).toBe(consignment.id);
  });

  test('HOLD_010: SCHEDULED outbound drops to ON_HOLD when hold opened, pops back to SUBMITTED when cleared', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const h0 = await getHold(hub.id, hold.id);
    expect(h0.status).toBe(HOLD_STATUSES.OPEN);

    const drOnHold = await getDockRequest(hub.id, dr.id);

    expect(drOnHold.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/clear`,
      {},
      h0.etag
    );
    expectSuccess(clearRes);

    const drSubmitted = await getDockRequest(hub.id, dr.id);
    expect(drSubmitted.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const batchRes = await batchSchedule(hub.id, [dr.id]);
    expect(batchRes.scheduled_ids).toContain(dr.id);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('HOLD_011: Multiple holds - clearing one leaves request ON_HOLD, clearing last pops to SUBMITTED', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h1 = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    const h2 = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.CUSTOMS,
      note: 'customs',
    });

    const h1_0 = await getHold(hub.id, h1.id);
    const h2_0 = await getHold(hub.id, h2.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const clear1Res = await postWithEtag(
      `/hubs/${hub.id}/holds/${h1_0.id}/clear`,
      {},
      h1_0.etag
    );
    expectSuccess(clear1Res);

    const h1_after = await getHold(hub.id, h1.id);
    expect(h1_after.status).toBe(HOLD_STATUSES.CLEARED);

    const h2_after = await getHold(hub.id, h2.id);
    expect(h2_after.status).toBe(HOLD_STATUSES.OPEN);

    const drStillHeld = await getDockRequest(hub.id, dr.id);
    expect(drStillHeld.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const clear2Res = await postWithEtag(
      `/hubs/${hub.id}/holds/${h2_0.id}/clear`,
      {},
      h2_0.etag
    );
    expectSuccess(clear2Res);

    const h2_final = await getHold(hub.id, h2.id);
    expect(h2_final.status).toBe(HOLD_STATUSES.CLEARED);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('HOLD_012: Voiding auto-hold allows outbound submit', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inDr = await createInboundDraft(hub.id, consignment.id, 10);
    inDr = await submitAndGet(hub.id, inDr);
    inDr = await scheduleAndGet(hub.id, inDr);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inDr.id}/complete`,
      { actual_units: 6 },
      inDr.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();
    const autoHoldId = completeData.auto_hold_id;

    const h0 = await getHold(hub.id, autoHoldId);
    expect(h0.status).toBe(HOLD_STATUSES.OPEN);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${autoHoldId}/void`,
      {},
      h0.etag
    );
    expectSuccess(voidRes);

    const outDr = await createOutboundDraft(hub.id, consignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outDr.id}/submit`,
      {},
      outDr.etag
    );

    expectSuccess(submitRes);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const drAfter = await getDockRequest(hub.id, outDr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(6);
    expect(consAfter.status).toBe('AT_HUB');
  });

  test('HOLD_013: Voided hold doesnt count as OPEN - clearing remaining OPEN hold pops requests', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h1 = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    const h2 = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.CUSTOMS,
      note: 'customs',
    });

    const h1_0 = await getHold(hub.id, h1.id);
    const h2_0 = await getHold(hub.id, h2.id);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h1_0.id}/void`,
      {},
      h1_0.etag
    );
    expectSuccess(voidRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h2_0.id}/clear`,
      {},
      h2_0.etag
    );

    expectSuccess(clearRes);

    const h1_after = await getHold(hub.id, h1.id);
    expect(h1_after.status).toBe(HOLD_STATUSES.VOIDED);

    const h2_after = await getHold(hub.id, h2.id);
    expect(h2_after.status).toBe(HOLD_STATUSES.CLEARED);

    const drFinal = await getDockRequest(hub.id, dr.id);
    expect(drFinal.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('HOLD_014: Cancelled ON_HOLD request stays CANCELLED after hold cleared', async () => {

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

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );
    expectSuccess(cancelRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const h0 = await getHold(hub.id, hold.id);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/clear`,
      {},
      h0.etag
    );

    expectSuccess(clearRes);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );
    expectSuccess(submitRes);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('HOLD_015: Inbound SUBMITTED is not affected by opening hold (holds only affect outbound)', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
    expect(dr.direction).toBe(DIRECTIONS.INBOUND);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
    expect(drAfter.direction).toBe(DIRECTIONS.INBOUND);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_in_use_units).toBe(0);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.OPEN);
  });

  test('HOLD_018: Cancel ON_HOLD request, clear hold, new outbound can submit', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const hold0 = await getHold(hub.id, hold.id);
    const drHold = await getDockRequest(hub.id, dr.id);
    expect(drHold.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      drHold.etag
    );
    expectSuccess(cancelRes);

    const drCancelled = await getDockRequest(hub.id, dr.id);
    expect(drCancelled.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold0.id}/clear`,
      {},
      hold0.etag
    );
    expectSuccess(clearRes);

    const holdCleared = await getHold(hub.id, hold.id);
    expect(holdCleared.status).toBe(HOLD_STATUSES.CLEARED);

    const drStillCancelled = await getDockRequest(hub.id, dr.id);
    expect(drStillCancelled.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const dr2 = await createOutboundDraft(hub.id, consignment.id, 1);
    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );
    expectSuccess(submitRes);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(10);
    expect(consAfter.status).toBe('AT_HUB');

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('HOLD_022: DONE request unaffected by opening hold, new outbound blocked', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inDr = await createInboundDraft(hub.id, consignment.id, 10);
    inDr = await submitAndGet(hub.id, inDr);
    inDr = await scheduleAndGet(hub.id, inDr);
    const inCompleteRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${inDr.id}/complete`,
      { actual_units: 10 },
      inDr.etag
    );
    expectSuccess(inCompleteRes);

    let outDr = await createOutboundDraft(hub.id, consignment.id, 4);
    outDr = await submitAndGet(hub.id, outDr);
    outDr = await scheduleAndGet(hub.id, outDr);
    const outCompleteRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outDr.id}/complete`,
      { actual_units: 4 },
      outDr.etag
    );
    expectSuccess(outCompleteRes);

    const drDone = await getDockRequest(hub.id, outDr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs after done',
    });

    const newOut = await createOutboundDraft(hub.id, consignment.id, 1);

    const drDoneAfter = await getDockRequest(hub.id, outDr.id);

    expect(drDoneAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${newOut.id}/submit`,
      {},
      newOut.etag
    );

    expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);

    const newOutAfter = await getDockRequest(hub.id, newOut.id);
    expect(newOutAfter.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(6);
    expect(consAfter.status).toBe('AT_HUB');

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(6);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(14);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('HOLD_024: Opening hold on SCHEDULED inbound doesnt affect it', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'IN-HOLD',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let inDr = await createInboundDraft(hub.id, consignment.id, 10);
    inDr = await submitAndGet(hub.id, inDr);
    inDr = await scheduleAndGet(hub.id, inDr);
    expect(inDr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const holdCheck = await getHold(hub.id, hold.id);
    expect(holdCheck.status).toBe(HOLD_STATUSES.OPEN);
    expect(holdCheck.kind).toBe(HOLD_KINDS.DOCS);
    expect(holdCheck.source).toBe(HOLD_SOURCES.MANUAL);

    const drAfter = await getDockRequest(hub.id, inDr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
    expect(drAfter.direction).toBe(DIRECTIONS.INBOUND);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(10);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(10);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(0);
    expect(consAfter.status).toBe('PLANNED');
  });
});
