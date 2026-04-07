import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  acknowledgeAlert,
  approveReturn,
  appraiseTradeIn,
  cancelOrder,
  createBuildLot,
  createCustomer,
  createOrder,
  createProgram,
  createReturn,
  createSession,
  createTradeIn,
  completeReturn,
  disputePayment,
  freezeProgram,
  getAlert,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  markInboundTradeIn,
  markInboundReturn,
  markDelivered,
  receiveReturn,
  resolveAlert,
  resolveDispute,
  runOps,
  shipOrder,
  submitOrder,
  submitTradeIn,
  unlockCustomer,
  uniqueId
} from '../../../test-helpers/resources';

async function createCustomerCtx(program_id: string, customer_id: string) {
  const actor = { actor_id: customer_id, actor_type: 'Customer' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createSupportCtx(program_id: string) {
  const actor = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createOpsCtx(program_id: string) {
  const actor = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createDeliveredOrderWithCapturedPayment(args: {
  program_id: string;
  build_lot_id: string;
  build_tag: string;
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
}) {
  const opsActor = { actor_id: args.opsCtx.actor_id, actor_type: 'Ops' as const };

  const order = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: 0 });
  expectSuccess(await submitOrder(args.program_id, order.order_id, args.customerCtx, false), 200);

  const shipRes = await shipOrder(args.program_id, order.order_id, args.opsCtx, {
    build_lot_id: args.build_lot_id,
    serial_number: `SN-${uniqueId('sn')}`,
    build_tag: args.build_tag
  });
  expectSuccess(shipRes, 200);

  const deliveredRes = await markDelivered(args.program_id, order.order_id, args.opsCtx);
  expectSuccess(deliveredRes, 200);

  const delivered = await getOrder(args.program_id, order.order_id, opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.payment_id).toBeTruthy();

  const payment = await getPayment(args.program_id, delivered.payment_id as string, opsActor);
  expect(payment.payment_status).toBe('CAPTURED');

  return { order_id: delivered.order_id, payment_id: payment.payment_id, customer_id: delivered.customer_id };
}

async function disputeAndGetAlertId(program_id: string, payment_id: string, supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string }, opsActor: { actor_id: string; actor_type: 'Ops' }) {
  const disputeRes = await disputePayment(program_id, payment_id, supportCtx);
  expectSuccess(disputeRes, 200);

  const alerts = await listAlerts(program_id, opsActor, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
  expect(alerts.alerts.length).toBe(1);
  return alerts.alerts[0].alert_id;
}

describe('Feature 5: Payments: Disputes, Chargebacks & Checkpoint Freezes (v1)', () => {
  async function createReturnToReceived(args: {
    program_id: string;
    order_id: string;
    createCtx: { actor_id: string; actor_type: 'Customer' | 'Support'; session_id: string };
    supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
    opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
    resolution_preference: 'REFUND' | 'REPLACEMENT';
    inspection_outcome: 'RESTOCK' | 'REFURB' | 'SCRAP';
  }) {
    const rCreate = await createReturn(args.program_id, args.order_id, args.createCtx, args.resolution_preference);
    expectSuccess(rCreate, 201);
    const returnId = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(args.program_id, returnId, args.supportCtx), 200);
    expectSuccess(await markInboundReturn(args.program_id, returnId, args.supportCtx), 200);
    expectSuccess(await receiveReturn(args.program_id, returnId, args.opsCtx, args.inspection_outcome), 200);
    return returnId;
  }

  test('PAY_001: disputing a CAPTURED payment marks DISPUTED, opens PAYMENT_DISPUTED alert, guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { actor: sup, ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');

    const openBefore = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(openBefore.alerts.length).toBe(0);

    const { payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    const disputeRes = await disputePayment(program.program_id, payment_id, supCtx);
    expectSuccess(disputeRes, 200);

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('DISPUTED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].payment_id).toBe(payment_id);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAYALRT_001: dispute then resolve_dispute CHARGEBACK_LOST opens CHARGEBACK_LOST alert without resolving PAYMENT_DISPUTED; locks customer; holds other orders; guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const openBefore = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(openBefore.alerts.length).toBe(0);

    const { payment_id: p1Id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);
    const o2Submitted = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Submitted.order_status).toBe('SUBMITTED');

    expectSuccess(await disputePayment(program.program_id, p1Id, supCtx), 200);

    expectSuccess(await resolveDispute(program.program_id, p1Id, supCtx, 'CHARGEBACK_LOST'), 200);

    const pm = await getPayment(program.program_id, p1Id, ops);
    expect(pm.payment_status).toBe('CHARGEBACK_LOST');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('ON_HOLD');

    const disputeAlerts = await listAlerts(program.program_id, ops, {
      alert_type: 'PAYMENT_DISPUTED',
      alert_status: 'OPEN',
      customer_id: c1.customer_id,
      payment_id: p1Id
    });
    expect(disputeAlerts.alerts.length).toBe(1);
    expect(disputeAlerts.alerts[0].payment_id).toBe(p1Id);

    const cbAlerts = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', customer_id: c1.customer_id, payment_id: p1Id });
    expect(cbAlerts.alerts.length).toBe(1);
    expect(cbAlerts.alerts[0].payment_id).toBe(p1Id);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAY_002: resolving dispute to CHARGEBACK_LOST locks customer, opens CHARGEBACK_LOST alert, and holds other unshipped orders', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { payment_id: p1Id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);
    const o2Submitted = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Submitted.order_status).toBe('SUBMITTED');

    expectSuccess(await disputePayment(program.program_id, p1Id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, p1Id, supCtx, 'CHARGEBACK_LOST'), 200);

    const pm = await getPayment(program.program_id, p1Id, ops);
    expect(pm.payment_status).toBe('CHARGEBACK_LOST');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');

    const cbAlerts = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', customer_id: c1.customer_id, payment_id: p1Id });
    expect(cbAlerts.alerts.length).toBe(1);

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('ON_HOLD');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAYREF_001: completing a return refund when payment is already REFUNDED either fails or succeeds without double-refunding', async () => {
    const program = await createProgram({ unit_price_cents: 59900, care_plan_price_cents: 0 });
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });
    const oDelivered = await getOrder(program.program_id, order_id, ops);
    expect(oDelivered.order_status).toBe('DELIVERED');
    const deviceId = oDelivered.device_id as string;

    const d0 = await getDevice(program.program_id, deviceId, ops);
    expect(d0.device_status).toBe('SHIPPED');

    expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED'), 200);

    const pmRefunded = await getPayment(program.program_id, payment_id, ops);
    expect(pmRefunded.payment_status).toBe('REFUNDED');
    expect(pmRefunded.amount_cents).toBe(59900);

    const disputeAlerts = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    if (disputeAlerts.alerts.length === 1) {
      expectSuccess(await resolveAlert(program.program_id, disputeAlerts.alerts[0].alert_id, opsCtx), 200);
    }

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });

    const r0 = await getReturn(program.program_id, returnId, ops);
    expect(r0.return_status).toBe('RECEIVED');
    expect(r0.inspection_outcome).toBe('REFURB');
    expect(r0.refunded_to_card_cents).toBe(0);
    expect(r0.refunded_to_credit_cents).toBe(0);
    expect(r0.replacement_device_id).toBeNull();

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });

    if (completeRes.status === 200) {

      const r1 = await getReturn(program.program_id, returnId, ops);
      expect(r1.return_status).toBe('COMPLETED');

      expect(r1.refunded_to_card_cents).toBe(0);
      expect(r1.replacement_device_id).toBeNull();

      const oAfter = await getOrder(program.program_id, order_id, ops);
      expect(oAfter.order_status).toBe('REFUNDED');
    } else {

      expect(completeRes.status).toBe(400);
      const errorCode = completeRes.body?.error?.code;
      expect(['ERR_PAYMENT_NOT_REFUNDABLE', 'ERR_RETURN_NOT_RESOLVABLE', 'ERR_INVALID_STATE_TRANSITION']).toContain(errorCode);

      const r1 = await getReturn(program.program_id, returnId, ops);
      expect(r1.return_status).toBe('RECEIVED');
      expect(r1.refunded_to_card_cents).toBe(0);
      expect(r1.refunded_to_credit_cents).toBe(0);
      expect(r1.replacement_device_id).toBeNull();

      const oAfter = await getOrder(program.program_id, order_id, ops);
      expect(oAfter.order_status).toBe('DELIVERED');
    }

    const pmAfter = await getPayment(program.program_id, payment_id, ops);
    expect(pmAfter.payment_status).toBe('REFUNDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);
  });

  test('PAYRET_002: completing a return refund while payment is DISPUTED either fails or succeeds without issuing card refund', async () => {
    const program = await createProgram({ unit_price_cents: 59900, care_plan_price_cents: 0 });
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });
    const deviceId = (await getOrder(program.program_id, order_id, ops)).device_id as string;

    expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
    const pmDisputed = await getPayment(program.program_id, payment_id, ops);
    expect(pmDisputed.payment_status).toBe('DISPUTED');

    const a1List = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    expect(a1List.alerts.length).toBe(1);
    const a1Id = a1List.alerts[0].alert_id;
    const a1 = await getAlert(program.program_id, a1Id, ops);
    expect(a1.alert_status).toBe('OPEN');

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });

    const r0 = await getReturn(program.program_id, returnId, ops);
    expect(r0.return_status).toBe('RECEIVED');
    expect(r0.replacement_device_id).toBeNull();
    expect(r0.refunded_to_card_cents).toBe(0);
    expect(r0.refunded_to_credit_cents).toBe(0);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });

    if (completeRes.status === 200) {

      const r1 = await getReturn(program.program_id, returnId, ops);
      expect(r1.return_status).toBe('COMPLETED');

      expect(r1.refunded_to_card_cents).toBe(0);
      expect(r1.replacement_device_id).toBeNull();

      const oAfter = await getOrder(program.program_id, order_id, ops);
      expect(oAfter.order_status).toBe('REFUNDED');

      const pmAfter = await getPayment(program.program_id, payment_id, ops);
      expect(pmAfter.payment_status).toBe('DISPUTED');
    } else {

      expect(completeRes.status).toBe(400);
      const errorCode = completeRes.body?.error?.code;
      expect(['ERR_PAYMENT_NOT_REFUNDABLE', 'ERR_RETURN_NOT_RESOLVABLE', 'ERR_INVALID_STATE_TRANSITION']).toContain(errorCode);

      const r1 = await getReturn(program.program_id, returnId, ops);
      expect(r1.return_status).toBe('RECEIVED');
      expect(r1.replacement_device_id).toBeNull();
      expect(r1.refunded_to_card_cents).toBe(0);
      expect(r1.refunded_to_credit_cents).toBe(0);

      const oAfter = await getOrder(program.program_id, order_id, ops);
      expect(oAfter.order_status).toBe('DELIVERED');
      expect(oAfter.device_id).toBe(deviceId);

      const pmAfter = await getPayment(program.program_id, payment_id, ops);
      expect(pmAfter.payment_status).toBe('DISPUTED');
    }

    const aAfter = await getAlert(program.program_id, a1Id, ops);
    expect(aAfter.alert_status).toBe('OPEN');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAY_003: resolving dispute to REFUNDED updates payment only; order stays DELIVERED; posture stays GUARDED until alert resolved', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    await disputeAndGetAlertId(program.program_id, payment_id, supCtx, ops);

    const resolveRes = await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED');
    expectSuccess(resolveRes, 200);

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const o1 = await getOrder(program.program_id, order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');

    const stillOpen = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    expect(stillOpen.alerts.length).toBe(1);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAY_004: disputing a VOIDED payment fails ERR_PAYMENT_NOT_DISPUTABLE and creates no dispute alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const payment_id = submitted.payment_id as string;
    expect(payment_id).toBeTruthy();

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cancel');
    expectSuccess(cancelRes, 200);

    const pmVoided = await getPayment(program.program_id, payment_id, ops);
    expect(pmVoided.payment_status).toBe('VOIDED');

    const openBefore = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(openBefore.alerts.length).toBe(0);

    const disputeRes = await disputePayment(program.program_id, payment_id, supCtx);
    expectError(disputeRes, 400, 'ERR_PAYMENT_NOT_DISPUTABLE');

    const pmStill = await getPayment(program.program_id, payment_id, ops);
    expect(pmStill.payment_status).toBe('VOIDED');

    const a = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    expect(a.alerts.length).toBe(0);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('PAY_005: 3 payments entering CHARGEBACK_LOST during the run freezes program at ops-run close', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 30);

    const base = (await getProgram(program.program_id, ops)).ops_run_index;

    const paymentIds: string[] = [];
    for (let i = 0; i < 3; i++) {
      const c = await createCustomer(program.program_id, opsCtx);
      const { ctx: cCtx } = await createCustomerCtx(program.program_id, c.customer_id);
      const { payment_id } = await createDeliveredOrderWithCapturedPayment({
        program_id: program.program_id,
        build_lot_id: lot.build_lot_id,
        build_tag: lot.build_tag,
        customer_id: c.customer_id,
        customerCtx: cCtx,
        opsCtx
      });
      paymentIds.push(payment_id);
    }

    for (const pid of paymentIds) {
      expectSuccess(await disputePayment(program.program_id, pid, supCtx), 200);
      expectSuccess(await resolveDispute(program.program_id, pid, supCtx, 'CHARGEBACK_LOST'), 200);
    }

    for (const pid of paymentIds) {
      const pm = await getPayment(program.program_id, pid, ops);
      expect(pm.payment_status).toBe('CHARGEBACK_LOST');
    }

    const after = await runOps(program.program_id, opsCtx);
    expect(after.ops_run_index).toBe(base + 1);
    expect(after.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('PAY_006: chargeback-freeze threshold is per-run (2 this run then 1 next run => no freeze)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 30);

    const base = (await getProgram(program.program_id, ops)).ops_run_index;

    const payments: Array<{ customer_id: string; payment_id: string }> = [];
    for (let i = 0; i < 3; i++) {
      const c = await createCustomer(program.program_id, opsCtx);
      const { ctx: cCtx } = await createCustomerCtx(program.program_id, c.customer_id);
      const { payment_id } = await createDeliveredOrderWithCapturedPayment({
        program_id: program.program_id,
        build_lot_id: lot.build_lot_id,
        build_tag: lot.build_tag,
        customer_id: c.customer_id,
        customerCtx: cCtx,
        opsCtx
      });
      payments.push({ customer_id: c.customer_id, payment_id });
    }

    for (const { payment_id } of payments.slice(0, 2)) {
      expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
      expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST'), 200);
    }

    const afterRunN = await runOps(program.program_id, opsCtx);
    expect(afterRunN.ops_run_index).toBe(base + 1);
    expect(afterRunN.program_posture).not.toBe('PROGRAM_FROZEN');

    for (const { customer_id } of payments.slice(0, 2)) {
      const open = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id });
      for (const a of open.alerts) {
        const ack = await acknowledgeAlert(program.program_id, a.alert_id, opsCtx);
        expectSuccess(ack, 200);
        expect(ack.body.alert_status).toBe('ACKNOWLEDGED');
      }

      const openAfter = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id });
      expect(openAfter.alerts.length).toBe(0);
    }

    const p3 = payments[2].payment_id;
    expectSuccess(await disputePayment(program.program_id, p3, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, p3, supCtx, 'CHARGEBACK_LOST'), 200);

    const afterRunN1 = await runOps(program.program_id, opsCtx);
    expect(afterRunN1.ops_run_index).toBe(base + 2);
    expect(afterRunN1.program_posture).not.toBe('PROGRAM_FROZEN');

    const pFinal = await getProgram(program.program_id, ops);
    expect(pFinal.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAY_007: resolve_dispute on CAPTURED payment fails ERR_INVALID_STATE_TRANSITION even in frozen', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const res = await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST');
    expectError(res, 400, 'ERR_INVALID_STATE_TRANSITION');

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('PAY_008: acknowledging chargeback alerts does not prevent checkpoint freeze', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 30);

    const base = (await getProgram(program.program_id, ops)).ops_run_index;

    const payments: Array<{ customer_id: string; payment_id: string }> = [];
    for (let i = 0; i < 3; i++) {
      const c = await createCustomer(program.program_id, opsCtx);
      const { ctx: cCtx } = await createCustomerCtx(program.program_id, c.customer_id);
      const { payment_id } = await createDeliveredOrderWithCapturedPayment({
        program_id: program.program_id,
        build_lot_id: lot.build_lot_id,
        build_tag: lot.build_tag,
        customer_id: c.customer_id,
        customerCtx: cCtx,
        opsCtx
      });
      payments.push({ customer_id: c.customer_id, payment_id });
    }

    const chargebacks: Array<{ customer_id: string; payment_id: string; alert_id: string }> = [];
    for (const { customer_id, payment_id } of payments) {
      expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
      expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST'), 200);

      const a = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', customer_id, payment_id });
      expect(a.alerts.length).toBe(1);
      chargebacks.push({ customer_id, payment_id, alert_id: a.alerts[0].alert_id });
    }

    for (const { alert_id } of chargebacks) {
      const ack = await acknowledgeAlert(program.program_id, alert_id, opsCtx);
      expectSuccess(ack, 200);
      expect(ack.body.alert_status).toBe('ACKNOWLEDGED');
    }

    const after = await runOps(program.program_id, opsCtx);
    expect(after.ops_run_index).toBe(base + 1);
    expect(after.program_posture).toBe('PROGRAM_FROZEN');

    for (const { alert_id } of chargebacks) {
      const alertAfter = await getAlert(program.program_id, alert_id, ops);
      expect(alertAfter.alert_status).toBe('ACKNOWLEDGED');
    }
  });

  test('PAY_009: disputing AUTHORIZED payment on SUBMITTED order guards program; order stays SUBMITTED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');
    const N = p0.ops_run_index;

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    const pmId = submitted.payment_id as string;
    expect(pmId).toBeTruthy();

    const pm0 = await getPayment(program.program_id, pmId, ops);
    expect(pm0.payment_status).toBe('AUTHORIZED');

    expectSuccess(await disputePayment(program.program_id, pmId, supCtx), 200);

    const pm1 = await getPayment(program.program_id, pmId, ops);
    expect(pm1.payment_status).toBe('DISPUTED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmId });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].payment_id).toBe(pmId);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');
    expect(p1.ops_run_index).toBe(N);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SUBMITTED');
    expect(oAfter.payment_id).toBe(pmId);
  });

  test('PAY_010: disputing an already DISPUTED payment fails ERR_PAYMENT_NOT_DISPUTABLE and does not duplicate alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = submitted.payment_id as string;

    const a1 = await disputeAndGetAlertId(program.program_id, pmId, supCtx, ops);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const disputeAgain = await disputePayment(program.program_id, pmId, supCtx);
    expectError(disputeAgain, 400, 'ERR_PAYMENT_NOT_DISPUTABLE');

    const pmStill = await getPayment(program.program_id, pmId, ops);
    expect(pmStill.payment_status).toBe('DISPUTED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmId });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].alert_id).toBe(a1);

    const pStill = await getProgram(program.program_id, ops);
    expect(pStill.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('PAY_011: dispute + resolve_dispute REFUNDED changes payment only; customer balances/standing unchanged; alert stays OPEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx
    });

    const trCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 19134);
    expectSuccess(trCreate, 201);
    const tradein_id = trCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const spendingOrder = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 19134 });
    expectSuccess(await submitOrder(program.program_id, spendingOrder.order_id, c1Ctx, false), 200);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 12345 }), 200);

    const cSetup = await getCustomer(program.program_id, c1.customer_id, ops);
    const creditBefore = cSetup.credit_balance_cents;
    const dueBefore = cSetup.balance_due_cents;
    const statusBefore = cSetup.customer_status;

    expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED'), 200);

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const o1 = await getOrder(program.program_id, order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(creditBefore);
    expect(cAfter.balance_due_cents).toBe(dueBefore);
    expect(cAfter.customer_status).toBe(statusBefore);

    const openDispute = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    expect(openDispute.alerts.length).toBe(1);

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });
});
