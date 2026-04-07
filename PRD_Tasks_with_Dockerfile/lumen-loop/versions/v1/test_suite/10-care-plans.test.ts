import { getRequest } from '../../../test-helpers/api-client';
import { expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  approveReturn,
  cancelOrder,
  completeClaim,
  completeReturn,
  createBuildLot,
  createClaim,
  createCustomer,
  createOrder,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSession,
  getClaim,
  getCarePlan,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  markDelivered,
  markInboundClaim,
  markInboundReturn,
  receiveClaim,
  receiveReturn,
  remediateDevice,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 10: Care Plans: Activation, Pause/Resume & Replacement Following (v1)', () => {
  test('CARE_001: canceling unshipped order voids the care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, `TAG-${uniqueId('t')}`, 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, true);
    expectSuccess(submitRes, 200);

    const o1Submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Submitted.order_status).toBe('SUBMITTED');
    expect(o1Submitted.care_plan_id).toBeTruthy();
    expect(o1Submitted.payment_id).toBeTruthy();

    const cpBefore = await getCarePlan(program.program_id, o1Submitted.care_plan_id as string, ops);
    expect(cpBefore.care_plan_status).toBe('PENDING_ACTIVATION');

    const pmBefore = await getPayment(program.program_id, o1Submitted.payment_id as string, ops);
    expect(pmBefore.payment_status).toBe('AUTHORIZED');

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(0);

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'changed my mind');
    expectSuccess(cancelRes, 200);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('CANCELED');

    const cpAfter = await getCarePlan(program.program_id, o1Submitted.care_plan_id as string, ops);
    expect(cpAfter.care_plan_status).toBe('VOIDED');

    const pmAfter = await getPayment(program.program_id, o1Submitted.payment_id as string, ops);
    expect(pmAfter.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);
  });

  test('CARE_002: activating device activates the care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, `TAG-${uniqueId('t')}`, 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);

    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Del.order_status).toBe('DELIVERED');
    expect(o1Del.device_id).toBeTruthy();
    expect(o1Del.care_plan_id).toBeTruthy();

    const deviceBefore = await getDevice(program.program_id, o1Del.device_id as string, ops);
    expect(deviceBefore.device_status).toBe('SHIPPED');

    const cpBefore = await getCarePlan(program.program_id, o1Del.care_plan_id as string, ops);
    expect(cpBefore.care_plan_status).toBe('PENDING_ACTIVATION');

    const activateRes = await activateDevice(program.program_id, o1Del.device_id as string, c1Ctx);
    expectSuccess(activateRes, 200);

    const deviceAfter = await getDevice(program.program_id, o1Del.device_id as string, ops);
    expect(deviceAfter.device_status).toBe('ACTIVE');

    const cpAfter = await getCarePlan(program.program_id, o1Del.care_plan_id as string, ops);
    expect(cpAfter.care_plan_status).toBe('ACTIVE');
    expect(cpAfter.device_id).toBe(o1Del.device_id);
  });

  test('CARE_003: escalating campaign to RECALL quarantines device and pauses care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const deviceActive = await getDevice(program.program_id, deviceId, ops);
    expect(deviceActive.device_status).toBe('ACTIVE');

    const cpActive = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpActive.care_plan_status).toBe('ACTIVE');

    const qcCreate = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ campaign_type: 'SHIP_HOLD', build_tag_prefix: 'B99' });
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const escalateRes = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns/${qcId}/escalate`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({});
    expectSuccess(escalateRes, 200);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');

    const deviceQuarantined = await getDevice(program.program_id, deviceId, ops);
    expect(deviceQuarantined.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');
  });

  test('CARE_004: remediating quarantined device resumes PAUSED care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const qcCreate = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ campaign_type: 'RECALL', build_tag_prefix: 'B99' });
    expectSuccess(qcCreate, 201);

    const deviceQ = await getDevice(program.program_id, deviceId, ops);
    expect(deviceQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const remedRes = await remediateDevice(program.program_id, deviceId, opsCtx, 'verified safe');
    expectSuccess(remedRes, 200);

    const deviceRemediated = await getDevice(program.program_id, deviceId, ops);
    expect(deviceRemediated.device_status).toBe('ACTIVE');

    const cpResumed = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpResumed.care_plan_status).toBe('ACTIVE');
  });

  test('CARE_005: refund on never-activated device voids the care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, `TAG-${uniqueId('t')}`, 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;
    const paymentId = o1Del.payment_id as string;

    const deviceBefore = await getDevice(program.program_id, deviceId, ops);
    expect(deviceBefore.device_status).toBe('SHIPPED');

    const cpBefore = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpBefore.care_plan_status).toBe('PENDING_ACTIVATION');

    const pmBefore = await getPayment(program.program_id, paymentId, ops);
    expect(pmBefore.payment_status).toBe('CAPTURED');

    const pBefore = await getProgram(program.program_id, ops);

    const retCreate = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectSuccess(retCreate, 201);
    const returnId = retCreate.body.return_id as string;

    expectSuccess(await approveReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK'), 200);

    const completeRes = await completeReturn(program.program_id, returnId, supportCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('REFUNDED');

    const pmAfter = await getPayment(program.program_id, paymentId, ops);
    expect(pmAfter.payment_status).toBe('REFUNDED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('VOIDED');

    const deviceAfter = await getDevice(program.program_id, deviceId, ops);
    expect(deviceAfter.device_status).toBe('RETURNED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units + 1);
  });

  test('CARE_006: refund on activated/quarantined device cancels the care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;
    const paymentId = o1Del.payment_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const qcCreate = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ campaign_type: 'RECALL', build_tag_prefix: 'B99' });
    expectSuccess(qcCreate, 201);

    const deviceQ = await getDevice(program.program_id, deviceId, ops);
    expect(deviceQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const retCreate = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectSuccess(retCreate, 201);
    const returnId = retCreate.body.return_id as string;

    expectSuccess(await approveReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeReturn(program.program_id, returnId, supportCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const retAfter = await getReturn(program.program_id, returnId, ops);
    expect(retAfter.return_status).toBe('COMPLETED');

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('REFUNDED');

    const pmAfter = await getPayment(program.program_id, paymentId, ops);
    expect(pmAfter.payment_status).toBe('REFUNDED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('CANCELED');

    const deviceAfter = await getDevice(program.program_id, deviceId, ops);
    expect(deviceAfter.device_status).toBe('SCRAPPED');
  });

  test('CARE_008: replacement on PAUSED care plan keeps it PAUSED until new device activated', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const origDeviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, origDeviceId, c1Ctx), 200);

    const qcCreate = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ campaign_type: 'RECALL', build_tag_prefix: 'B99' });
    expectSuccess(qcCreate, 201);

    const deviceQ = await getDevice(program.program_id, origDeviceId, ops);
    expect(deviceQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const retCreate = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REPLACEMENT');
    expectSuccess(retCreate, 201);
    const returnId = retCreate.body.return_id as string;

    expectSuccess(await approveReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, supportCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeReturn(program.program_id, returnId, supportCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN998',
      replacement_build_tag: replacementLot.build_tag
    });
    expectSuccess(completeRes, 200);

    const retAfter = await getReturn(program.program_id, returnId, ops);
    expect(retAfter.return_status).toBe('COMPLETED');
    const newDeviceId = retAfter.replacement_device_id as string;

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.device_id).toBe(newDeviceId);

    const newDevice = await getDevice(program.program_id, newDeviceId, ops);
    expect(newDevice.device_status).toBe('SHIPPED');

    const origDeviceAfter = await getDevice(program.program_id, origDeviceId, ops);
    expect(origDeviceAfter.device_status).toBe('SCRAPPED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.device_id).toBe(newDeviceId);
    expect(cpAfter.care_plan_status).toBe('PAUSED');
  });

  test('CARE_009: activating recall-claim replacement device resumes care plan even while frozen', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    const origDeviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, origDeviceId, c1Ctx), 200);

    const qcCreate = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ campaign_type: 'RECALL', build_tag_prefix: 'B99' });
    expectSuccess(qcCreate, 201);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const deviceQ = await getDevice(program.program_id, origDeviceId, ops);
    expect(deviceQ.device_status).toBe('QUARANTINED');

    const claimCreate = await createClaim(program.program_id, origDeviceId, supportCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claimId, supportCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipAdv = await shipAdvanceReplacement(program.program_id, claimId, supportCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: `SN-ADV-${uniqueId('sn')}`,
      replacement_build_tag: replacementLot.build_tag
    });
    expectSuccess(shipAdv, 200);

    const claim = shipAdv.body;
    const newDeviceId = claim.replacement_device_id as string;

    const o1AdvShipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1AdvShipped.device_id).toBe(newDeviceId);

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.device_id).toBe(newDeviceId);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const newDevice = await getDevice(program.program_id, newDeviceId, ops);
    expect(newDevice.device_status).toBe('SHIPPED');

    const origDeviceStill = await getDevice(program.program_id, origDeviceId, ops);
    expect(origDeviceStill.device_status).toBe('QUARANTINED');

    const pStillFrozen = await getProgram(program.program_id, ops);
    expect(pStillFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const activateRes = await activateDevice(program.program_id, newDeviceId, c1Ctx);
    expectSuccess(activateRes, 200);

    const newDeviceActive = await getDevice(program.program_id, newDeviceId, ops);
    expect(newDeviceActive.device_status).toBe('ACTIVE');

    const cpActive = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpActive.device_id).toBe(newDeviceId);
    expect(cpActive.care_plan_status).toBe('ACTIVE');

    const origDeviceFinal = await getDevice(program.program_id, origDeviceId, ops);
    expect(origDeviceFinal.device_status).toBe('QUARANTINED');

    const pFinal = await getProgram(program.program_id, ops);
    expect(pFinal.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('CAREID_002: completing replacement claim moves care plan to replacement device and resets to PENDING_ACTIVATION', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const sup = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supSession = await createSession(program.program_id, sup);
    const supCtx = { ...sup, session_id: supSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');

    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Del = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Del.order_status).toBe('DELIVERED');
    expect(o1Del.device_id).toBeTruthy();
    expect(o1Del.care_plan_id).toBeTruthy();
    expect(o1Del.payment_id).toBeTruthy();

    const deviceId = o1Del.device_id as string;
    const carePlanId = o1Del.care_plan_id as string;
    const paymentId = o1Del.payment_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const dActive = await getDevice(program.program_id, deviceId, ops);
    expect(dActive.device_status).toBe('ACTIVE');

    const cpActive = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpActive.care_plan_status).toBe('ACTIVE');
    expect(cpActive.device_id).toBe(deviceId);

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const clCreate = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(clCreate, 201);
    const claimId = clCreate.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const clReceived = await getClaim(program.program_id, claimId, ops);
    expect(clReceived.claim_status).toBe('RECEIVED');
    expect(clReceived.replacement_device_id).toBeNull();

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-CP-CLM',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(completeRes, 200);

    const replacementDeviceId = completeRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const clDone = await getClaim(program.program_id, claimId, ops);
    expect(clDone.claim_status).toBe('COMPLETED');
    expect(clDone.replacement_device_id).toBe(replacementDeviceId);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementDeviceId);
    expect(oAfter.care_plan_id).toBe(carePlanId);

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.device_id).toBe(replacementDeviceId);
    expect(cpAfter.care_plan_status).toBe('PENDING_ACTIVATION');

    const pmAfter = await getPayment(program.program_id, paymentId, ops);
    expect(pmAfter.payment_status).toBe('CAPTURED');
  });
});
