import { post, postWithEtag } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  getData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  getHub,
  createConsignment,
  getConsignment,
  getDockRequest,
  getHold,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  createConsignmentAtHub,
  createReleasedConsignment,
  createHold,
  batchSchedule,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  DOCK_REQUEST_STATUSES,
  CONSIGNMENT_STATUSES,
  HOLD_KINDS,
  HOLD_STATUSES,
  POSTURES,
  ERROR_CODES,
} from '../../../test-helpers/constants';

async function runOpsWithEtag(hubId: string): Promise<void> {
  const hub = await getHub(hubId);
  const res = await postWithEtag(`/hubs/${hubId}/run_ops`, {}, hub.etag);
  expectSuccess(res);
}

describe('Ops Run Tests', () => {

  test('OPS_001: run_ops increments ops_run_index', async () => {

    const hub = await createHub(undefined, 20);

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;

    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    expectSuccess(res);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(initialIndex + 1);
  });

  test('OPS_002: stale SUBMITTED request expires after 2 ops runs', async () => {

    const hub = await createHub(undefined, 100);

    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 5);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);
    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);
  });

  test('OPS_003: SCHEDULED requests do not expire from ops runs', async () => {

    const hub = await createHub(undefined, 100);

    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    await runOpsWithEtag(hub.id);

    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);
  });

  test('OPS_004: RELEASED consignment with no open moves/holds becomes CLOSED on run_ops', async () => {

    const hub = await createHub(undefined, 100);

    const { consignment } = await createReleasedConsignment(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const h0 = await getHub(hub.id);
    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
  });

  test('OPS_005: Draft dock request does not block closeout', async () => {

    const hub = await createHub(undefined, 100);

    const { consignment } = await createReleasedConsignment(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const dr = await createOutboundDraft(hub.id, consignment.id, 1, PRIORITIES.STANDARD);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DRAFT);

    const h0 = await getHub(hub.id);
    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
  });

  test('OPS_006: RELEASED consignment with open hold remains RELEASED after run_ops', async () => {

    const hub = await createHub(undefined, 100);

    const { consignment } = await createReleasedConsignment(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });
    expect(hold.status).toBe('OPEN');

    const h0 = await getHub(hub.id);
    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);

    expectSuccess(res);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
  });

  test('OPS_007: ON_HOLD request expires after 2 ops runs', async () => {

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

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;

    await runOpsWithEtag(hub.id);

    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(initialIndex + 2);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.OPEN);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(10);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    expect(hubAfter.staging_in_use_units).toBe(10);
    expect(hubAfter.staging_reserved_units).toBe(0);
  });

  test('OPS_008: SUBMITTED request expires only after 2 runs (not 1)', async () => {

    const hub = await createHub(undefined, 20);

    await runOpsWithEtag(hub.id);

    const consignment = await createConsignment(hub.id, {
      reference: 'S10',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h2 = await getHub(hub.id);

    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h2.etag);
    expectSuccess(res);

    let drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h3 = await getHub(hub.id);
    expect(h3.ops_run_index).toBe(h2.ops_run_index + 1);

    const res2 = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h3.etag);
    expectSuccess(res2);

    drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20);
    expect(hubFinal.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_009: EXPIRED request allows new request for same consignment', async () => {

    const hub = await createHub(undefined, 100);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);
    await runOpsWithEtag(hub.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2 = await createInboundDraft(hub.id, consignment.id, 5);

    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(submitRes);

    const dr1After = await getDockRequest(hub.id, dr.id);
    expect(dr1After.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consAfter.units_on_hand).toBe(0);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_in_use_units).toBe(0);
  });

  test('OPS_010: ON_HOLD then SUBMITTED expires after total 2 ops runs', async () => {

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

    await runOpsWithEtag(hub.id);

    const hold0 = await getHold(hub.id, hold.id);
    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold0.id}/clear`,
      {},
      hold0.etag
    );
    expectSuccess(clearRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(10);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);
    expect(hubAfter.staging_reserved_units).toBe(0);
  });

  test('OPS_012: Scheduling before 2nd ops run prevents expiry', async () => {

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

    await runOpsWithEtag(hub.id);

    const hold0 = await getHold(hub.id, hold.id);
    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${hold0.id}/clear`,
      {},
      hold0.etag
    );
    expectSuccess(clearRes);

    const batchRes = await batchSchedule(hub.id, [dr.id]);
    expect(batchRes.scheduled_ids).toContain(dr.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_in_use_units).toBe(10);
  });

  test('OPS_013: EXPIRED outbound doesnt count as open move - RELEASED consignment closes', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CLOSEX',
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

    let out1 = await createOutboundDraft(hub.id, consignment.id, 1);
    out1 = await submitAndGet(hub.id, out1);
    expect(out1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);
    await runOpsWithEtag(hub.id);

    out1 = await getDockRequest(hub.id, out1.id);
    expect(out1.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    let out10 = await createOutboundDraft(hub.id, consignment.id, 10);
    out10 = await submitAndGet(hub.id, out10);
    out10 = await scheduleAndGet(hub.id, out10);
    const out10CompleteRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${out10.id}/complete`,
      { actual_units: 10 },
      out10.etag
    );
    expectSuccess(out10CompleteRes);

    let consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(consAfter.units_on_hand).toBe(0);

    await runOpsWithEtag(hub.id);

    consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consAfter.units_on_hand).toBe(0);

    const out1After = await getDockRequest(hub.id, out1.id);
    expect(out1After.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_014: Per-request aging - newer request does not expire when older does', async () => {

    const hub = await createHub(undefined, 20);

    const consignmentA = await createConsignment(hub.id, {
      reference: 'AGE-A',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    const consignmentB = await createConsignment(hub.id, {
      reference: 'AGE-B',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignmentA.id, 1);
    dr1 = await submitAndGet(hub.id, dr1);
    expect(dr1.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);

    let dr2 = await createInboundDraft(hub.id, consignmentB.id, 1);
    dr2 = await submitAndGet(hub.id, dr2);
    expect(dr2.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);

    const dr1After = await getDockRequest(hub.id, dr1.id);
    expect(dr1After.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_015: SCHEDULED outbound dropped to ON_HOLD expires after 2 ops runs', async () => {

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

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.ON_HOLD);

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;

    await runOpsWithEtag(hub.id);
    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);

    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const holdAfter = await getHold(hub.id, hold.id);
    expect(holdAfter.status).toBe(HOLD_STATUSES.OPEN);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.units_on_hand).toBe(10);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(initialIndex + 2);
    expect(hubAfter.staging_in_use_units).toBe(10);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(90);
  });

  test('OPS_016: CANCELLED request does not expire', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;

    await runOpsWithEtag(hub.id);

    dr = await getDockRequest(hub.id, dr.id);
    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/cancel`,
      {},
      dr.etag
    );
    expectSuccess(cancelRes);

    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const h2 = await getHub(hub.id);
    expect(h2.ops_run_index).toBe(initialIndex + 2);

    expect(h2.staging_reserved_units).toBe(0);
    expect(h2.staging_in_use_units).toBe(0);
    expect(h2.staging_free_units).toBe(20);
    expect(h2.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_017: Scheduling between ops runs prevents expiry', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;

    await runOpsWithEtag(hub.id);

    const batchRes = await batchSchedule(hub.id, [dr.id]);
    expect(batchRes.scheduled_ids).toContain(dr.id);

    await runOpsWithEtag(hub.id);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(initialIndex + 2);

    expect(hubAfter.staging_reserved_units).toBe(10);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(10);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_018: CANCELLED outbound doesnt count as open move - RELEASED consignment closes', async () => {
    const hub = await createHub(undefined, 20);

    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(consignment.units_on_hand).toBe(10);

    let cancelled = await createOutboundDraft(hub.id, consignment.id, 1);
    cancelled = await submitAndGet(hub.id, cancelled);

    const cancelRes = await postWithEtag(`/hubs/${hub.id}/dock_requests/${cancelled.id}/cancel`, {}, cancelled.etag);
    expectSuccess(cancelRes);

    const cancelledAfter = await getDockRequest(hub.id, cancelled.id);
    expect(cancelledAfter.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    let out = await createOutboundDraft(hub.id, consignment.id, 10);
    out = await submitAndGet(hub.id, out);
    out = await scheduleAndGet(hub.id, out);
    const completeRes = await postWithEtag(`/hubs/${hub.id}/dock_requests/${out.id}/complete`, { actual_units: 10 }, out.etag);
    expectSuccess(completeRes);

    const consReleased = await getConsignment(hub.id, consignment.id);
    expect(consReleased.status).toBe(CONSIGNMENT_STATUSES.RELEASED);
    expect(consReleased.units_on_hand).toBe(0);

    const h0 = await getHub(hub.id);
    const initialIndex = h0.ops_run_index;
    const res = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, h0.etag);
    expectSuccess(res);

    const consAfter = await getConsignment(hub.id, consignment.id);
    expect(consAfter.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consAfter.units_on_hand).toBe(0);

    const cancelledFinal = await getDockRequest(hub.id, cancelled.id);
    expect(cancelledFinal.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
    expect(hubAfter.ops_run_index).toBe(initialIndex + 1);
  });

  test('OPS_019: EXPIRED request cannot be scheduled', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'EXP-SCHED',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    await runOpsWithEtag(hub.id);
    await runOpsWithEtag(hub.id);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const h2 = await getHub(hub.id);

    const batchRes = await post(`/hubs/${hub.id}/dock_requests/batch_schedule`, {
      dock_request_ids: [dr.id],
    });

    expectSuccess(batchRes);
    const batchData = getData(batchRes);
    expect(batchData.rejected).toBeDefined();
    expect(batchData.rejected.length).toBeGreaterThan(0);
    const rejectedItem = batchData.rejected.find((r: any) => r.dock_request_id === dr.id);
    expect(rejectedItem).toBeDefined();
    expect(rejectedItem.error_code).toBe(ERROR_CODES.ERR_INVALID_STATE);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.EXPIRED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
    expect(hubAfter.ops_run_index).toBe(h2.ops_run_index);
  });
});
