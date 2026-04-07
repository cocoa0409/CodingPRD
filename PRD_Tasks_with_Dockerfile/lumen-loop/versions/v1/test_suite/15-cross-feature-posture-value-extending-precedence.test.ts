import { post } from '../../../test-helpers/api-client';
import { expectError, expectErrorOneOf, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  applyAdjustment,
  appraiseTradeIn,
  approveReturn,
  cancelOrder,
  completeReturn,
  createAdjustment,
  createBuildLot,
  createCustomer,
  createCustomerCtx,
  createOpsCtx,
  createOrder,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSupportCtx,
  createTradeIn,
  disputePayment,
  freezeProgram,
  getAlert,
  getBuildLot,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  lockCustomer,
  markInboundReturn,
  markInboundTradeIn,
  markDelivered,
  receiveReturn,
  refreshPayment,
  resolveAlert,
  resolveDispute,
  runOps,
  shipOrder,
  submitOrder,
  submitTradeIn,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 15: Cross-Feature: Posture × Value-Extending Actions & Error Precedence (v1)', () => {
  async function unlockRaw(program_id: string, customer_id: string, ctx: { actor_id: string; actor_type: 'Ops' | 'Support' | 'Customer'; session_id: string }) {
    return post(`/programs/${program_id}/customers/${customer_id}/unlock`, {}, ctx);
  }

  async function createShippedNotDeliveredOrderWithDevice(args: {
    program_id: string;
    opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
    opsActor: { actor_id: string; actor_type: 'Ops' };
    customer_id: string;
    customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
    build_lot_id: string;
    build_tag: string;
    include_care_plan: boolean;
    serial_number: string;
  }) {
    const o1 = await createOrder(args.program_id, args.customer_id, args.customerCtx);
    expectSuccess(await submitOrder(args.program_id, o1.order_id, args.customerCtx, args.include_care_plan), 200);
    expectSuccess(
      await shipOrder(args.program_id, o1.order_id, args.opsCtx, {
        build_lot_id: args.build_lot_id,
        serial_number: args.serial_number,
        build_tag: args.build_tag
      }),
      200
    );

    const shipped = await getOrder(args.program_id, o1.order_id, args.opsActor);
    expect(shipped.order_status).toBe('SHIPPED');
    expect(shipped.device_id).toBeTruthy();
    expect(shipped.payment_id).toBeTruthy();

    const payment_id = shipped.payment_id as string;
    const pm = await getPayment(args.program_id, payment_id, args.opsActor);
    expect(pm.payment_status).toBe('CAPTURED');

    return { order_id: shipped.order_id, device_id: shipped.device_id as string, payment_id };
  }

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

  async function makeCustomerLimited(args: {
    program_id: string;
    opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
    opsActor: { actor_id: string; actor_type: 'Ops' };
    customer_id: string;
    customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
    quoted_credit_cents: number;
    final_credit_cents: number;
    spend_credit_cents: number;
  }) {
    const trCreate = await createTradeIn(args.program_id, args.customer_id, args.customerCtx, args.quoted_credit_cents);
    expectSuccess(trCreate, 201);
    const tradein_id = trCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(args.program_id, tradein_id, args.customerCtx), 200);

    const spendOrder = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: args.spend_credit_cents });
    expectSuccess(await submitOrder(args.program_id, spendOrder.order_id, args.customerCtx, false), 200);

    expectSuccess(await markInboundTradeIn(args.program_id, tradein_id, args.opsCtx), 200);
    expectSuccess(await appraiseTradeIn(args.program_id, tradein_id, args.opsCtx, { accepted: true, final_credit_cents: args.final_credit_cents }), 200);

    return getCustomer(args.program_id, args.customer_id, args.opsActor);
  }

  test('CROSS_009: guarded mode blocks unlocking an otherwise unlock-eligible customer (ERR_PROGRAM_REVIEW_REQUIRED)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 2000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, adjId, supCtx), 200);

    expect((await getCustomer(program.program_id, c1.customer_id, ops)).customer_status).toBe('LOCKED');
    expectSuccess(await post(`/programs/${program.program_id}/customers/${c1.customer_id}/settle_balance_due`, { amount_cents: 2000 }, supCtx), 200);
    expect((await getCustomer(program.program_id, c1.customer_id, ops)).balance_due_cents).toBe(0);

    await runOps(program.program_id, opsCtx);

    const c1Open = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    for (const a of c1Open.alerts) {
      expectSuccess(await resolveAlert(program.program_id, a.alert_id, opsCtx), 200);
    }

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const other = await createCustomer(program.program_id, opsCtx);
    const { ctx: otherCtx } = await createCustomerCtx(program.program_id, other.customer_id);
    const oX = await createOrder(program.program_id, other.customer_id, otherCtx);
    expectSuccess(await submitOrder(program.program_id, oX.order_id, otherCtx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, oX.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, oX.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, oX.order_id, ops);
    const paymentId = delivered.payment_id as string;
    expect(paymentId).toBeTruthy();
    expectSuccess(await disputePayment(program.program_id, paymentId, supCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const unlockRes = await unlockRaw(program.program_id, c1.customer_id, opsCtx);
    expectError(unlockRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ERR_001: activation when order not DELIVERED returns ERR_DEVICE_NOT_ACTIVATABLE even if PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, device_id } = await createShippedNotDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false,
      serial_number: `SN-${uniqueId('sn')}`
    });

    expect((await freezeProgram(program.program_id, opsCtx, 'manual freeze')).program_posture).toBe('PROGRAM_FROZEN');

    const act = await activateDevice(program.program_id, device_id, c1Ctx);
    expectError(act, 400, 'ERR_DEVICE_NOT_ACTIVATABLE');

    expect((await getDevice(program.program_id, device_id, ops)).device_status).toBe('SHIPPED');
    expect((await getOrder(program.program_id, order_id, ops)).order_status).toBe('SHIPPED');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_FROZEN');
  });

  test('ERR_002: refresh_payment on ON_HOLD due to lock returns ERR_INVALID_STATE_TRANSITION even if PROGRAM_GUARDED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const oCap = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, oCap.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, oCap.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, oCap.order_id, opsCtx), 200);
    const oDelivered = await getOrder(program.program_id, oCap.order_id, ops);
    const p1Id = oDelivered.payment_id as string;
    expect(p1Id).toBeTruthy();

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    const o1Submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Submitted.order_status).toBe('SUBMITTED');
    const o1Pay = o1Submitted.payment_id as string;
    expect(o1Pay).toBeTruthy();

    expectSuccess(await disputePayment(program.program_id, p1Id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, p1Id, supCtx, 'CHARGEBACK_LOST'), 200);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    expect(held.payment_id).toBe(o1Pay);

    const pm = await getPayment(program.program_id, o1Pay, ops);
    expect(pm.payment_status).toBe('AUTHORIZED');

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectError(refreshRes, 400, 'ERR_INVALID_STATE_TRANSITION');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('ON_HOLD');
    expect(oAfter.payment_id).toBe(o1Pay);

    expect((await getPayment(program.program_id, o1Pay, ops)).payment_status).toBe('AUTHORIZED');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ERR_003: submit in PROGRAM_GUARDED with locked customer returns posture or lock error', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(5);

    const cX = await createCustomer(program.program_id, opsCtx);
    await lockCustomer(program.program_id, cX.customer_id, opsCtx, 'risk containment');

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');
    expect(pGuarded.available_to_commit_units).toBe(5);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk');
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expect(o1.order_status).toBe('DRAFT');

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);

    expectErrorOneOf(submitRes, 400, ['ERR_PROGRAM_REVIEW_REQUIRED', 'ERR_CUSTOMER_LOCKED']);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
    expect(pAfter.available_to_commit_units).toBe(5);
  });

  test('ERR_004: activation when order not DELIVERED and device is QUARANTINED returns activation-blocking error', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, device_id } = await createShippedNotDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, device_id, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const act = await activateDevice(program.program_id, device_id, c1Ctx);

    expectErrorOneOf(act, 400, ['ERR_DEVICE_NOT_ACTIVATABLE', 'ERR_DEVICE_QUARANTINED']);

    expect((await getDevice(program.program_id, device_id, ops)).device_status).toBe('QUARANTINED');
    expect((await getOrder(program.program_id, order_id, ops)).order_status).toBe('SHIPPED');
  });

  test('ERR_005: forbidden-for-actor wins before posture for activation (Support → 403 ERR_FORBIDDEN_FOR_ACTOR)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = delivered.device_id as string;
    expect(deviceId).toBeTruthy();

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const act = await activateDevice(program.program_id, deviceId, supCtx);
    expectError(act, 403, 'ERR_FORBIDDEN_FOR_ACTOR');

    expect((await getDevice(program.program_id, deviceId, ops)).device_status).toBe('SHIPPED');
    expect((await getOrder(program.program_id, o1.order_id, ops)).order_status).toBe('DELIVERED');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_FROZEN');
  });

  test('POST_001: shipping a committed order is allowed in PROGRAM_GUARDED; captures payment; posture and alerts remain', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    const pay1 = submitted.payment_id as string;
    expect((await getPayment(program.program_id, pay1, ops)).payment_status).toBe('AUTHORIZED');

    const cA = await createCustomer(program.program_id, opsCtx);
    const { ctx: cACtx } = await createCustomerCtx(program.program_id, cA.customer_id);
    const oA = await createOrder(program.program_id, cA.customer_id, cACtx);
    expectSuccess(await submitOrder(program.program_id, oA.order_id, cACtx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, oA.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: `SN-${uniqueId('sn')}`, build_tag: lot.build_tag }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, oA.order_id, opsCtx), 200);
    const deliveredA = await getOrder(program.program_id, oA.order_id, ops);
    const payA = deliveredA.payment_id as string;
    expectSuccess(await disputePayment(program.program_id, payA, supCtx), 200);
    const a1 = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: payA });
    expect(a1.alerts.length).toBe(1);
    const a1Id = a1.alerts[0].alert_id;

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');
    const availableBeforeShip = pGuarded.available_to_commit_units;

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SN-GUARD-1',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SHIPPED');
    expect(oAfter.device_id).toBeTruthy();

    const pmAfter = await getPayment(program.program_id, pay1, ops);
    expect(pmAfter.payment_status).toBe('CAPTURED');

    const d = await getDevice(program.program_id, oAfter.device_id as string, ops);
    expect(d.device_status).toBe('SHIPPED');
    expect(d.serial_number).toBe('SN-GUARD-1');
    expect(d.build_tag).toBe('B99Z');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
    expect(pAfter.available_to_commit_units).toBe(availableBeforeShip);

    expect((await getAlert(program.program_id, a1Id, ops)).alert_status).toBe('OPEN');
  });

  test('POST_002: shipping in PROGRAM_FROZEN returns ERR_PROGRAM_FROZEN and preserves order/payment/inventory invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    const pay1 = submitted.payment_id as string;
    expect((await getPayment(program.program_id, pay1, ops)).payment_status).toBe('AUTHORIZED');

    const pBefore = await getProgram(program.program_id, ops);
    const availBefore = pBefore.available_to_commit_units;
    expect((await getBuildLot(program.program_id, lot.build_lot_id, ops)).build_lot_status).toBe('AVAILABLE');

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_FROZEN');

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: 'SN-FRZ-1', build_tag: 'B99Z' });
    expectError(shipRes, 400, 'ERR_PROGRAM_FROZEN');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SUBMITTED');
    expect(oAfter.device_id).toBeNull();

    expect((await getPayment(program.program_id, pay1, ops)).payment_status).toBe('AUTHORIZED');
    expect((await getBuildLot(program.program_id, lot.build_lot_id, ops)).build_lot_status).toBe('AVAILABLE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.available_to_commit_units).toBe(availBefore);
  });

  test('XPOST_001: guarded blocks submit before out-of-stock errors (ERR_PROGRAM_REVIEW_REQUIRED)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(0);

    const cX = await createCustomer(program.program_id, opsCtx);
    const adjCreate = await createAdjustment(program.program_id, cX.customer_id, supCtx, 'CREDIT_CLAWBACK', 1000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, adjId, supCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');
    expect(pGuarded.available_to_commit_units).toBe(0);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expect(o1.order_status).toBe('DRAFT');

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectError(submitRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();

    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(0);
  });

  test('XPOST_002: frozen beats guarded for submit (ERR_PROGRAM_FROZEN)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const cX = await createCustomer(program.program_id, opsCtx);
    const adjCreate = await createAdjustment(program.program_id, cX.customer_id, supCtx, 'CREDIT_CLAWBACK', 1000);
    expectSuccess(adjCreate, 201);
    expectSuccess(await applyAdjustment(program.program_id, adjCreate.body.adjustment_id as string, supCtx), 200);
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_GUARDED');

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_FROZEN');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const availBefore = (await getProgram(program.program_id, ops)).available_to_commit_units;

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectError(submitRes, 400, 'ERR_PROGRAM_FROZEN');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();

    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(availBefore);
  });

  test('XPOST_003: invalid transition wins before posture for cancel (SHIPPED → ERR_ORDER_NOT_CANCELABLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: `SN-${uniqueId('sn')}`, build_tag: lot.build_tag }), 200);

    const shipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped.order_status).toBe('SHIPPED');
    const payId = shipped.payment_id as string;
    expect((await getPayment(program.program_id, payId, ops)).payment_status).toBe('CAPTURED');

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cancel');
    expectError(cancelRes, 400, 'ERR_ORDER_NOT_CANCELABLE');

    expect((await getOrder(program.program_id, o1.order_id, ops)).order_status).toBe('SHIPPED');
    expect((await getPayment(program.program_id, payId, ops)).payment_status).toBe('CAPTURED');
  });

  test('XPOST_004: forbidden-for-actor wins before posture for Ops-only endpoints (quality_campaigns)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const qcRes = await post(`/programs/${program.program_id}/quality_campaigns`, { campaign_type: 'SHIP_HOLD', build_tag_prefix: 'A17' }, supCtx);
    expectError(qcRes, 403, 'ERR_FORBIDDEN_FOR_ACTOR');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('XPOST_005: locked customer cannot activate device (ERR_CUSTOMER_LOCKED)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: `SN-${uniqueId('sn')}`, build_tag: lot.build_tag }), 200);
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    expect(delivered.order_status).toBe('DELIVERED');
    const deviceId = delivered.device_id as string;

    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk');

    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectError(act, 400, 'ERR_CUSTOMER_LOCKED');

    expect((await getDevice(program.program_id, deviceId, ops)).device_status).toBe('SHIPPED');
    expect((await getOrder(program.program_id, o1.order_id, ops)).order_status).toBe('DELIVERED');
  });

  test('XPOST_006: LIMITED customer cannot submit a new order (ERR_CUSTOMER_NOT_ELIGIBLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expect(o1.order_status).toBe('DRAFT');

    const limited = await makeCustomerLimited({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      quoted_credit_cents: 25000,
      final_credit_cents: 20000,
      spend_credit_cents: 25000
    });
    expect(limited.customer_status).toBe('LIMITED');

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBeGreaterThanOrEqual(1);

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectError(submitRes, 400, 'ERR_CUSTOMER_NOT_ELIGIBLE');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('XPOST_007: guarded blocks replacement completion (ERR_PROGRAM_REVIEW_REQUIRED); preserves return and order invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: `SN-${uniqueId('sn')}`, build_tag: lot.build_tag }), 200);
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = delivered.device_id as string;
    expect(deviceId).toBeTruthy();

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: delivered.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const r0 = await getReturn(program.program_id, returnId, ops);
    expect(r0.return_status).toBe('RECEIVED');
    expect(r0.replacement_device_id).toBeNull();

    const cOther = await createCustomer(program.program_id, opsCtx);
    await lockCustomer(program.program_id, cOther.customer_id, opsCtx, 'risk');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_GUARDED');

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SNX',
      replacement_build_tag: 'B99Z'
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const r1 = await getReturn(program.program_id, returnId, ops);
    expect(r1.return_status).toBe('RECEIVED');
    expect(r1.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.device_id).toBe(deviceId);
  });

  test('XPOST_008: frozen blocks replacement completion (ERR_PROGRAM_FROZEN); preserves return invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: `SN-${uniqueId('sn')}`, build_tag: lot.build_tag }), 200);
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    const originalDeviceId = delivered.device_id as string;
    expect(originalDeviceId).toBeTruthy();

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: delivered.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_FROZEN');

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SNY',
      replacement_build_tag: 'B99Z'
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_FROZEN');

    const r1 = await getReturn(program.program_id, returnId, ops);
    expect(r1.return_status).toBe('RECEIVED');
    expect(r1.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.device_id).toBe(originalDeviceId);
  });
});
