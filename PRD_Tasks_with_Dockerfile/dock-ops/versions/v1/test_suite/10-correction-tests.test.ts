import { post, postWithEtag } from '../../../test-helpers/api-client';
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
  getDockRequest,
  getHold,
  createHold,
  clearHold,
  createInboundDraft,
  createOutboundDraft,
  submitAndGet,
  scheduleAndGet,
  createConsignmentAtHub,
  batchSchedule,
  executeOutboundFlow,
  completeDockRequest,
  voidDockRequest,
} from '../../../test-helpers/resources';
import {
  COMMODITIES,
  PRIORITIES,
  ERROR_CODES,
  DOCK_REQUEST_STATUSES,
  CONSIGNMENT_STATUSES,
  POSTURES,
  HOLD_STATUSES,
} from '../../../test-helpers/constants';

describe('Correction Tests', () => {

  test('CORR_001: Voiding a scheduled inbound dock request releases reserved units', async () => {

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
    expect(hubBefore.staging_free_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/void`,
      {},
      dr.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
  });

  test('CORR_002: Voiding a completed inbound dock request reverses on-hand units', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 10 },
      dr.etag
    );
    expectSuccess(completeRes);

    const consignmentBefore = await getConsignment(hub.id, consignment.id);
    expect(consignmentBefore.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(consignmentBefore.units_on_hand).toBe(10);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_in_use_units).toBe(10);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(0);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
  });

  test('CORR_003: Voiding a completed outbound dock request restores on-hand units', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let dr = await createOutboundDraft(hub.id, consignment.id, 4);
    dr = await submitAndGet(hub.id, dr);
    dr = await scheduleAndGet(hub.id, dr);
    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 4 },
      dr.etag
    );
    expectSuccess(completeRes);

    const consignmentBefore = await getConsignment(hub.id, consignment.id);
    expect(consignmentBefore.units_on_hand).toBe(6);
    expect(consignmentBefore.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.staging_in_use_units).toBe(6);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);
  });

  test('CORR_004: Voiding a completed inbound changes hub posture from LOCKDOWN to OPEN', async () => {

    const hub = await createHub(undefined, 20);

    const consignmentFill = await createConsignment(hub.id, {
      reference: 'FILL20',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let drFill = await createInboundDraft(hub.id, consignmentFill.id, 20);
    drFill = await submitAndGet(hub.id, drFill);
    drFill = await scheduleAndGet(hub.id, drFill);
    await completeDockRequest(hub.id, drFill.id, drFill.etag, 20);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_free_units).toBe(0);

    const drDone = await getDockRequest(hub.id, drFill.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const consignmentB = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    let drB = await createInboundDraft(hub.id, consignmentB.id, 1);

    const submitResB = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drB.id}/submit`,
      {},
      drB.etag
    );
    await expectErrorCode(submitResB, ERROR_CODES.ERR_POSTURE_LOCKDOWN);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(voidRes);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
    expect(hubAfter.staging_free_units).toBe(20);

    const drBAfterVoid = await getDockRequest(hub.id, drB.id);
    const submitResBAfterVoid = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drBAfterVoid.id}/submit`,
      {},
      drBAfterVoid.etag
    );
    expectSuccess(submitResBAfterVoid);

    const drBSubmitted = await getDockRequest(hub.id, drB.id);
    expect(drBSubmitted.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('CORR_005: Voiding a dock request with an open auto-variance hold also voids the hold', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      reference: 'VAR10',
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

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const holdBefore = await getHold(hub.id, autoHoldId);
    expect(holdBefore.status).toBe(HOLD_STATUSES.OPEN);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);
  });

  test('CORR_006: Voiding a dock request does not void an already-cleared auto-variance hold', async () => {

    const hub = await createHub(undefined, 20);
    const consignment = await createConsignment(hub.id, {
      reference: 'VAR10',
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

    const holdH0 = await getHold(hub.id, autoHoldId);
    expect(holdH0.status).toBe(HOLD_STATUSES.OPEN);

    const clearRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${autoHoldId}/clear`,
      {},
      holdH0.etag
    );
    expectSuccess(clearRes);

    const holdH1 = await getHold(hub.id, autoHoldId);
    expect(holdH1.status).toBe(HOLD_STATUSES.CLEARED);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.CLEARED);
  });

  test('CORR_007: Voiding an outbound restores units and can cause LOCKDOWN', async () => {

    const hub = await createHub(undefined, 5);

    const consignment = await createConsignment(hub.id, {
      reference: 'C',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });

    let drIn = await createInboundDraft(hub.id, consignment.id, 5);
    drIn = await submitAndGet(hub.id, drIn);
    drIn = await scheduleAndGet(hub.id, drIn);
    await completeDockRequest(hub.id, drIn.id, drIn.etag, 5);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_in_use_units).toBe(5);
    expect(hubState.staging_free_units).toBe(0);

    const consignmentAfterIn = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfterIn.units_on_hand).toBe(5);

    let drOut = await createOutboundDraft(hub.id, consignment.id, 5);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    await completeDockRequest(hub.id, drOut.id, drOut.etag, 5);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_free_units).toBe(5);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    const outDone = await getDockRequest(hub.id, drOut.id);
    expect(outDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${outDone.id}/void`,
      {},
      outDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, drOut.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(5);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(5);
    expect(hubAfter.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('CORR_008: Void can\'t make on-hand negative - fails with ERR_CONSTRAINT_VIOLATION', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CHAIN',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let drIn = await createInboundDraft(hub.id, consignment.id, 10);
    drIn = await submitAndGet(hub.id, drIn);
    drIn = await scheduleAndGet(hub.id, drIn);
    await completeDockRequest(hub.id, drIn.id, drIn.etag, 10);

    let drOut = await createOutboundDraft(hub.id, consignment.id, 6);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    await completeDockRequest(hub.id, drOut.id, drOut.etag, 6);

    const consignmentBefore = await getConsignment(hub.id, consignment.id);
    expect(consignmentBefore.units_on_hand).toBe(4);

    const drInDone = await getDockRequest(hub.id, drIn.id);
    expect(drInDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drInDone.id}/void`,
      {},
      drInDone.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CONSTRAINT_VIOLATION);

    const drInAfter = await getDockRequest(hub.id, drIn.id);
    expect(drInAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(4);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(4);
  });

  test('CORR_009: Void outbound fails if would exceed capacity - ERR_CAPACITY_EXCEEDED', async () => {

    const hub = await createHub(undefined, 5);

    const consignmentA = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let drInA = await createInboundDraft(hub.id, consignmentA.id, 5);
    drInA = await submitAndGet(hub.id, drInA);
    drInA = await scheduleAndGet(hub.id, drInA);
    await completeDockRequest(hub.id, drInA.id, drInA.etag, 5);

    let drOutA = await createOutboundDraft(hub.id, consignmentA.id, 5);
    drOutA = await submitAndGet(hub.id, drOutA);
    drOutA = await scheduleAndGet(hub.id, drOutA);
    await completeDockRequest(hub.id, drOutA.id, drOutA.etag, 5);

    let consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.units_on_hand).toBe(0);
    expect(consignmentAState.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    const consignmentB = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let drInB = await createInboundDraft(hub.id, consignmentB.id, 5);
    drInB = await submitAndGet(hub.id, drInB);
    drInB = await scheduleAndGet(hub.id, drInB);
    await completeDockRequest(hub.id, drInB.id, drInB.etag, 5);

    let hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(5);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);

    const drOutADone = await getDockRequest(hub.id, drOutA.id);
    expect(drOutADone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOutADone.id}/void`,
      {},
      drOutADone.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const drOutAAfter = await getDockRequest(hub.id, drOutA.id);
    expect(drOutAAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.units_on_hand).toBe(0);
    expect(consignmentAState.status).toBe(CONSIGNMENT_STATUSES.RELEASED);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(5);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('CORR_010: Voiding outbound reopens CLOSED consignment to AT_HUB', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CLOSEME',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let drIn = await createInboundDraft(hub.id, consignment.id, 10);
    drIn = await submitAndGet(hub.id, drIn);
    drIn = await scheduleAndGet(hub.id, drIn);
    await completeDockRequest(hub.id, drIn.id, drIn.etag, 10);

    let drOut = await createOutboundDraft(hub.id, consignment.id, 10);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    await completeDockRequest(hub.id, drOut.id, drOut.etag, 10);

    let hubState = await getHub(hub.id);
    const opsRes = await postWithEtag(
      `/hubs/${hub.id}/run_ops`,
      {},
      hubState.etag
    );
    expectSuccess(opsRes);

    let consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.CLOSED);

    const drOutDone = await getDockRequest(hub.id, drOut.id);
    expect(drOutDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOutDone.id}/void`,
      {},
      drOutDone.etag
    );

    expectSuccess(res);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(consignmentState.units_on_hand).toBe(10);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(10);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(10);
    expect(hubState.posture).toBe(POSTURES.OPEN);
  });

  test('CORR_011: Void with variance hold voids auto-hold but manual hold remains', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let drOut = await createOutboundDraft(hub.id, consignment.id, 4);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOut.id}/complete`,
      { actual_units: 1 },
      drOut.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();
    const autoHoldId = completeData.auto_hold_id;

    const autoHoldBefore = await getHold(hub.id, autoHoldId);
    expect(autoHoldBefore.status).toBe(HOLD_STATUSES.OPEN);

    const manualHold = await createHold(hub.id, {
      consignment_id: consignment.id,
      kind: 'DOCS',
      note: 'manual docs',
    });
    expect(manualHold.status).toBe(HOLD_STATUSES.OPEN);

    const drDone = await getDockRequest(hub.id, drOut.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, drOut.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const autoHoldAfter = await getHold(hub.id, autoHoldId);
    expect(autoHoldAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const manualHoldAfter = await getHold(hub.id, manualHold.id);
    expect(manualHoldAfter.status).toBe(HOLD_STATUSES.OPEN);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);

    let drNew = await createOutboundDraft(hub.id, consignment.id, 1);
    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drNew.id}/submit`,
      {},
      drNew.etag
    );
    await expectErrorCode(submitRes, ERROR_CODES.ERR_CONSIGNMENT_HAS_OPEN_HOLD);
  });

  test('CORR_012: Void outbound with variance also voids auto-hold and restores units', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment } = await createConsignmentAtHub(hub.id, 10);

    let drOut = await createOutboundDraft(hub.id, consignment.id, 4);
    drOut = await submitAndGet(hub.id, drOut);
    drOut = await scheduleAndGet(hub.id, drOut);
    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOut.id}/complete`,
      { actual_units: 1 },
      drOut.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();
    const autoHoldId = completeData.auto_hold_id;

    const holdBefore = await getHold(hub.id, autoHoldId);
    expect(holdBefore.status).toBe(HOLD_STATUSES.OPEN);

    const drDone = await getDockRequest(hub.id, drOut.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, drOut.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(10);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(10);
  });

  test('CORR_013: Void scheduled inbound allows new inbound submit for same consignment', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'VOIDME',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment.id, 10);
    dr1 = await submitAndGet(hub.id, dr1);
    dr1 = await scheduleAndGet(hub.id, dr1);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr1.id}/void`,
      {},
      dr1.etag
    );
    expectSuccess(voidRes);

    let consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentState.units_on_hand).toBe(0);

    let dr2 = await createInboundDraft(hub.id, consignment.id, 5);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentState.units_on_hand).toBe(0);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);
  });

  test('CORR_014: Void completed inbound allows new inbound submit for same consignment', async () => {

    const hub = await createHub(undefined, 20);
    const { consignment, inboundDockRequest } = await createConsignmentAtHub(hub.id, 10);

    let consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);
    expect(consignmentState.units_on_hand).toBe(10);

    const drDone = await getDockRequest(hub.id, inboundDockRequest.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const voidRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );
    expectSuccess(voidRes);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentState.units_on_hand).toBe(0);

    let dr2 = await createInboundDraft(hub.id, consignment.id, 5);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentState.units_on_hand).toBe(0);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
  });

  test('CORR_015: Cancelling scheduled inbound allows new inbound submit for same consignment', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'R',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });

    let dr1 = await createInboundDraft(hub.id, consignment.id, 10);
    let dr2 = await createInboundDraft(hub.id, consignment.id, 10);

    dr1 = await submitAndGet(hub.id, dr1);
    dr1 = await scheduleAndGet(hub.id, dr1);

    const cancelRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr1.id}/cancel`,
      {},
      dr1.etag
    );
    expectSuccess(cancelRes);

    let hubState = await getHub(hub.id);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    dr2 = await getDockRequest(hub.id, dr2.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );

    expectSuccess(res);

    const dr1After = await getDockRequest(hub.id, dr1.id);
    expect(dr1After.status).toBe(DOCK_REQUEST_STATUSES.CANCELLED);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);

    const consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);
    expect(consignmentState.units_on_hand).toBe(0);

    hubState = await getHub(hub.id);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);
  });

  test('CORR_016: Voiding scheduled inbound in LOCKDOWN releases posture to OPEN', async () => {

    const hub = await createHub(undefined, 20);

    const consignment1 = await createConsignment(hub.id, {
      reference: 'LOCKRES',
      declared_units: 20,
      commodity: COMMODITIES.GENERAL,
    });
    let dr1 = await createInboundDraft(hub.id, consignment1.id, 20);
    dr1 = await submitAndGet(hub.id, dr1);
    dr1 = await scheduleAndGet(hub.id, dr1);

    let hubState = await getHub(hub.id);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
    expect(hubState.staging_reserved_units).toBe(20);
    expect(hubState.staging_free_units).toBe(0);

    const consignment2 = await createConsignment(hub.id, {
      reference: 'AFTER',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    let dr2 = await createInboundDraft(hub.id, consignment2.id, 1);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr1.id}/void`,
      {},
      dr1.etag
    );

    expectSuccess(res);

    hubState = await getHub(hub.id);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_in_use_units).toBe(0);
    expect(hubState.staging_free_units).toBe(20);
    expect(hubState.posture).toBe(POSTURES.OPEN);

    dr2 = await getDockRequest(hub.id, dr2.id);
    const submitRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr2.id}/submit`,
      {},
      dr2.etag
    );
    expectSuccess(submitRes);

    const dr2After = await getDockRequest(hub.id, dr2.id);
    expect(dr2After.status).toBe(DOCK_REQUEST_STATUSES.SUBMITTED);
  });

  test('CORR_017: Void outbound fails at capacity, auto-hold remains OPEN', async () => {

    const hub = await createHub(undefined, 20);

    const consignmentA = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let drInA = await createInboundDraft(hub.id, consignmentA.id, 10);
    drInA = await submitAndGet(hub.id, drInA);
    drInA = await scheduleAndGet(hub.id, drInA);
    await completeDockRequest(hub.id, drInA.id, drInA.etag, 10);

    let drOutA = await createOutboundDraft(hub.id, consignmentA.id, 4);
    drOutA = await submitAndGet(hub.id, drOutA);
    drOutA = await scheduleAndGet(hub.id, drOutA);
    const outCompleteRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOutA.id}/complete`,
      { actual_units: 1 },
      drOutA.etag
    );
    expectSuccess(outCompleteRes);

    const outData = getData(outCompleteRes);
    expect(outData.auto_hold_id).toBeDefined();
    const autoHoldId = outData.auto_hold_id;

    let consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.units_on_hand).toBe(9);

    const consignmentB = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 11,
      commodity: COMMODITIES.GENERAL,
    });
    let drInB = await createInboundDraft(hub.id, consignmentB.id, 11);
    drInB = await submitAndGet(hub.id, drInB);
    drInB = await scheduleAndGet(hub.id, drInB);
    await completeDockRequest(hub.id, drInB.id, drInB.etag, 11);

    let hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(20);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);

    const holdBefore = await getHold(hub.id, autoHoldId);
    expect(holdBefore.status).toBe(HOLD_STATUSES.OPEN);

    const drOutADone = await getDockRequest(hub.id, drOutA.id);
    expect(drOutADone.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drOutADone.variance_units).toBe(-3);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOutADone.id}/void`,
      {},
      drOutADone.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const drOutAAfter = await getDockRequest(hub.id, drOutA.id);
    expect(drOutAAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);
    expect(drOutAAfter.variance_units).toBe(-3);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.OPEN);

    consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.units_on_hand).toBe(9);
    expect(consignmentAState.status).toBe(CONSIGNMENT_STATUSES.AT_HUB);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(20);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('CORR_018: Void outbound from CLOSED consignment fails at capacity, consignment stays CLOSED', async () => {

    const hub = await createHub(undefined, 5);

    const consignmentA = await createConsignment(hub.id, {
      reference: 'A',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let drInA = await createInboundDraft(hub.id, consignmentA.id, 5);
    drInA = await submitAndGet(hub.id, drInA);
    drInA = await scheduleAndGet(hub.id, drInA);
    await completeDockRequest(hub.id, drInA.id, drInA.etag, 5);

    let drOutA = await createOutboundDraft(hub.id, consignmentA.id, 5);
    drOutA = await submitAndGet(hub.id, drOutA);
    drOutA = await scheduleAndGet(hub.id, drOutA);
    await completeDockRequest(hub.id, drOutA.id, drOutA.etag, 5);

    let hubState = await getHub(hub.id);
    const opsRes = await postWithEtag(
      `/hubs/${hub.id}/run_ops`,
      {},
      hubState.etag
    );
    expectSuccess(opsRes);

    let consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignmentAState.units_on_hand).toBe(0);

    const consignmentB = await createConsignment(hub.id, {
      reference: 'B',
      declared_units: 5,
      commodity: COMMODITIES.GENERAL,
    });
    let drInB = await createInboundDraft(hub.id, consignmentB.id, 5);
    drInB = await submitAndGet(hub.id, drInB);
    drInB = await scheduleAndGet(hub.id, drInB);
    await completeDockRequest(hub.id, drInB.id, drInB.etag, 5);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(5);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);

    const drOutADone = await getDockRequest(hub.id, drOutA.id);
    expect(drOutADone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drOutADone.id}/void`,
      {},
      drOutADone.etag
    );

    await expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const drOutAAfter = await getDockRequest(hub.id, drOutA.id);
    expect(drOutAAfter.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    consignmentAState = await getConsignment(hub.id, consignmentA.id);
    expect(consignmentAState.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignmentAState.units_on_hand).toBe(0);

    hubState = await getHub(hub.id);
    expect(hubState.staging_in_use_units).toBe(5);
    expect(hubState.staging_reserved_units).toBe(0);
    expect(hubState.staging_free_units).toBe(0);
    expect(hubState.posture).toBe(POSTURES.LOCKDOWN);
  });

  test('CORR_019: Void completed inbound with auto-hold voids hold and rolls back all state', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'VAR',
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

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    const holdBefore = await getHold(hub.id, autoHoldId);
    expect(holdBefore.status).toBe(HOLD_STATUSES.OPEN);

    const hubBefore = await getHub(hub.id);
    const consignmentBefore = await getConsignment(hub.id, consignment.id);
    expect(consignmentBefore.units_on_hand).toBe(6);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(0);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);

    expect(hubAfter.ops_run_index).toBe(hubBefore.ops_run_index);
  });

  test('CORR_024: Void dock request when auto-hold was already voided - hold stays VOIDED', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'AUTO_V',
      declared_units: 10,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 10);
    dr = await submitAndGet(hub.id, dr);

    let hubState = await getHub(hub.id);
    const scheduleRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/batch_schedule`,
      { dock_request_ids: [dr.id] },
      hubState.etag
    );
    expectSuccess(scheduleRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 6 },
      dr.etag
    );
    expectSuccess(completeRes);

    const completeData = getData(completeRes);
    expect(completeData.auto_hold_id).toBeDefined();
    const autoHoldId = completeData.auto_hold_id;

    let hold = await getHold(hub.id, autoHoldId);
    expect(hold.status).toBe(HOLD_STATUSES.OPEN);

    const voidHoldRes = await postWithEtag(
      `/hubs/${hub.id}/holds/${autoHoldId}/void`,
      {},
      hold.etag
    );
    expectSuccess(voidHoldRes);

    hold = await getHold(hub.id, autoHoldId);
    expect(hold.status).toBe(HOLD_STATUSES.VOIDED);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    hubState = await getHub(hub.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);

    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    const holdAfter = await getHold(hub.id, autoHoldId);
    expect(holdAfter.status).toBe(HOLD_STATUSES.VOIDED);

    const consignmentAfter = await getConsignment(hub.id, consignment.id);
    expect(consignmentAfter.units_on_hand).toBe(0);
    expect(consignmentAfter.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);

    expect(hubAfter.ops_run_index).toBe(hubState.ops_run_index);
  });

  test('CORR_026: Void inbound with actual_units=0 reopens CLOSED consignment to PLANNED', async () => {

    const hub = await createHub(undefined, 20);

    const consignment = await createConsignment(hub.id, {
      reference: 'CLOSE-ZERO',
      declared_units: 1,
      commodity: COMMODITIES.GENERAL,
    });
    let dr = await createInboundDraft(hub.id, consignment.id, 1);
    dr = await submitAndGet(hub.id, dr);

    let hubState = await getHub(hub.id);
    const scheduleRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/batch_schedule`,
      { dock_request_ids: [dr.id] },
      hubState.etag
    );
    expectSuccess(scheduleRes);

    dr = await getDockRequest(hub.id, dr.id);
    expect(dr.status).toBe(DOCK_REQUEST_STATUSES.SCHEDULED);

    const completeRes = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${dr.id}/complete`,
      { actual_units: 0 },
      dr.etag
    );
    expectSuccess(completeRes);

    hubState = await getHub(hub.id);
    const opsRes = await postWithEtag(
      `/hubs/${hub.id}/run_ops`,
      {},
      hubState.etag
    );
    expectSuccess(opsRes);

    let consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.CLOSED);
    expect(consignmentState.units_on_hand).toBe(0);

    const drDone = await getDockRequest(hub.id, dr.id);
    expect(drDone.status).toBe(DOCK_REQUEST_STATUSES.DONE);

    hubState = await getHub(hub.id);

    const res = await postWithEtag(
      `/hubs/${hub.id}/dock_requests/${drDone.id}/void`,
      {},
      drDone.etag
    );

    expectSuccess(res);
    const drAfter = await getDockRequest(hub.id, dr.id);
    expect(drAfter.status).toBe(DOCK_REQUEST_STATUSES.VOIDED);

    consignmentState = await getConsignment(hub.id, consignment.id);
    expect(consignmentState.units_on_hand).toBe(0);
    expect(consignmentState.status).toBe(CONSIGNMENT_STATUSES.PLANNED);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.staging_in_use_units).toBe(0);
    expect(hubAfter.staging_reserved_units).toBe(0);
    expect(hubAfter.staging_free_units).toBe(20);
    expect(hubAfter.posture).toBe(POSTURES.OPEN);

    expect(hubAfter.ops_run_index).toBe(hubState.ops_run_index);
  });
});
