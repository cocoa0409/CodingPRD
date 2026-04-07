import { post, postWithEtag } from '../../../test-helpers/api-client';
import { expectSuccess } from '../../../test-helpers/assertions';
import {
  createHub,
  getHub,
  getConsignment,
  getHold,
  createHold,
  createOutboundDraft,
  submitAndGet,
  batchSchedule,
  runOps,
  createConsignmentAtHub,
  createClosedConsignment,
  getDockRequest,
  completeAndGet,
} from '../../../test-helpers/resources';
import {
  HOLD_KINDS,
  HOLD_STATUSES,
  CONSIGNMENT_STATUSES,
  DOCK_REQUEST_STATUSES,
} from '../../../test-helpers/constants';

describe('Deep Integration Tests', () => {

  test('DEEP_001: Partial outbound leaves consignment AT_HUB with remaining units', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    expect(consignment.units_on_hand).toBe(10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    let dr = await createOutboundDraft(hub.id, consignment.id, 6);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleResult = await batchSchedule(hub.id, [dr.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr.id);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    dr = await completeAndGet(hub.id, dr, 6);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);

    expect(consignmentAfter.units_on_hand).toBe(4);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
  });

  test('DEEP_002: Full outbound and ops run closes consignment', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);
    expect(consignment.units_on_hand).toBe(10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    let dr = await createOutboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const scheduleResult = await batchSchedule(hub.id, [dr.id]);
    expect(scheduleResult.scheduled_ids).toContain(dr.id);
    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    dr = await completeAndGet(hub.id, dr, 10);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    let consignmentAfterComplete = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterComplete.units_on_hand).toBe(0);
    expect(consignmentAfterComplete.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    await runOps(hub.id);

    const consignmentAfterOps = await getConsignment(hub.id, consignment.id);

    expect(consignmentAfterOps.units_on_hand).toBe(0);
    expect(consignmentAfterOps.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
  });

  test('DEEP_003: Hold on closed consignment then clear and ops re-closes it', async () => {

    const hub = await createHub(undefined, 100);
    const { consignment } = await createClosedConsignment(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignment.units_on_hand).toBe(0);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'late docs',
    });

    const consignmentAfterHold = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterHold.status).not.toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignmentAfterHold.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const h0 = await getHold(hub.id, hold.id);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/clear`,
      {},
      h0.etag
    );
    expectSuccess(clearRes);

    const holdAfterClear = await getHold(hub.id, hold.id);
    expect(holdAfterClear.status).toBe(HOLD_STATUSES.CLEARED);

    const consignmentAfterClear = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterClear.status).not.toBe(CONSIGNMENT_STATUSES.CLOSED);

    const hub0 = await getHub(hub.id);
    const opsRes = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, hub0.etag);
    expectSuccess(opsRes);

    const consignmentAfterOps = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterOps.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
  });

  test('DEEP_004: Voided hold does not block re-closure', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createClosedConsignment(hub.id, 10);
    expect(consignment.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignment.units_on_hand).toBe(0);

    const hold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: HOLD_KINDS.DOCS,
      note: 'docs',
    });

    const consignmentAfterHold = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterHold.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const h0 = await getHold(hub.id, hold.id);
    expect(h0.status).toBe(HOLD_STATUSES.OPEN);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${h0.id}/void`,
      {},
      h0.etag
    );
    expectSuccess(voidRes);

    const holdAfterVoid = await getHold(hub.id, hold.id);
    expect(holdAfterVoid.status).toBe(HOLD_STATUSES.VOIDED);

    const consignmentBeforeOps = await getConsignment(hub.id, consignment.id);
    expect(consignmentBeforeOps.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const hub0 = await getHub(hub.id);
    const opsRes = await postWithEtag(`/hubs/${hub.id}/run_ops`, {}, hub0.etag);
    expectSuccess(opsRes);

    const holdFinal = await getHold(hub.id, hold.id);
    expect(holdFinal.status).toBe(HOLD_STATUSES.VOIDED);

    const consignmentFinal = await getConsignment(hub.id, consignment.id);
    expect(consignmentFinal.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignmentFinal.units_on_hand).toBe(0);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.staging_in_use_units).toBe(0);
    expect(hubFinal.staging_reserved_units).toBe(0);
    expect(hubFinal.staging_free_units).toBe(20);
    expect(hubFinal.posture).toBe('OPEN');
  });
});
