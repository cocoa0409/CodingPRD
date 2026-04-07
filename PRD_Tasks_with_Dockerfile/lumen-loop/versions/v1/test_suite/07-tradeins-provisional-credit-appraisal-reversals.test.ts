import { post } from '../../../test-helpers/api-client';
import { expectError, expectSuccess, extractErrorCode } from '../../../test-helpers/assertions';
import {
  approveReturn,
  acknowledgeAlert,
  appraiseTradeIn,
  completeReturn,
  createAndApplyBalanceDue,
  applyAdjustment,
  createAdjustment,
  createBuildLot,
  createCustomer,
  createOrder,
  createProgram,
  createReturn,
  createSession,
  createTradeIn,
  disputePayment,
  freezeProgram,
  getAlert,
  getBuildLot,
  getCustomer,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  getTradeIn,
  listAlerts,
  markDelivered,
  markInboundReturn,
  markInboundTradeIn,
  receiveReturn,
  resolveAlert,
  resolveDispute,
  reverseTradeInCredit,
  runOps,
  settleBalanceDue,
  shipOrder,
  submitOrder,
  submitTradeIn,
  uniqueId
} from '../../../test-helpers/resources';

async function createOpsCtx(program_id: string) {
  const actor = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createSupportCtx(program_id: string) {
  const actor = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createCustomerCtx(program_id: string, customer_id: string) {
  const actor = { actor_id: customer_id, actor_type: 'Customer' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

async function createDeliveredOrder(args: {
  program_id: string;
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  opsActor: { actor_id: string; actor_type: 'Ops' };
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  build_lot_id: string;
  build_tag: string;
  use_credit_cents: number;
}) {
  const o = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: args.use_credit_cents });
  const submitRes = await submitOrder(args.program_id, o.order_id, args.customerCtx, false);
  expectSuccess(submitRes, 200);

  const shipped = await shipOrder(args.program_id, o.order_id, args.opsCtx, {
    build_lot_id: args.build_lot_id,
    serial_number: `SN-${uniqueId('sn')}`,
    build_tag: args.build_tag
  });
  expectSuccess(shipped, 200);

  expectSuccess(await markDelivered(args.program_id, o.order_id, args.opsCtx), 200);

  const oAfter = await getOrder(args.program_id, o.order_id, args.opsActor);
  expect(oAfter.order_status).toBe('DELIVERED');
  expect(oAfter.payment_id).toBeTruthy();
  return oAfter;
}

describe('Feature 7: Trade-ins: Provisional Credit, Appraisal & Reversals (v1)', () => {
  test('TRD_001: provisional credit is issued immediately on qualifying submit', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const open = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(open.alerts.length).toBe(0);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    const submit = await submitTradeIn(program.program_id, tradein_id, c1Ctx);
    expectSuccess(submit, 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('SUBMITTED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(25000);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('ACTIVE');
  });

  test('TRD_002: quoted_credit_cents > 30000 submits but does not issue provisional credit', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 35000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('SUBMITTED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);
  });

  test('TRD_003: in PROGRAM_GUARDED, trade-in submit succeeds but provisional credit is withheld', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c2 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);

    const o2 = await createDeliveredOrder({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c2.customer_id,
      customerCtx: c2Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      use_credit_cents: 0
    });

    const pm2 = await getPayment(program.program_id, o2.payment_id as string, ops);
    expect(pm2.payment_status).toBe('CAPTURED');

    expectSuccess(await disputePayment(program.program_id, pm2.payment_id, supCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    const submitRes = await submitTradeIn(program.program_id, tradein_id, c1Ctx);
    if (submitRes.status === 200) {
      const t1 = await getTradeIn(program.program_id, tradein_id, ops);
      expect(t1.tradein_status).toBe('SUBMITTED');
    } else {
      expect(submitRes.status).toBe(400);
      expect(extractErrorCode(submitRes.body)).toBe('ERR_PROGRAM_REVIEW_REQUIRED');
      const t1 = await getTradeIn(program.program_id, tradein_id, ops);
      expect(t1.tradein_status).toBe('DRAFT');
    }

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
  });

  test('TRD_004: if customer has balance_due_cents>0, trade-in submit withholds provisional credit', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tSeed = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tSeed, 201);
    const tSeedId = tSeed.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tSeedId, c1Ctx), 200);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    const oSpend = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 25000 });
    expectSuccess(await submitOrder(program.program_id, oSpend.order_id, c1Ctx, false), 200);

    expectSuccess(await markInboundTradeIn(program.program_id, tSeedId, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tSeedId, opsCtx, { accepted: true, final_credit_cents: 24000 }), 200);

    const cDebt = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cDebt.credit_balance_cents).toBe(0);
    expect(cDebt.balance_due_cents).toBe(1000);

    const submitRes = await submitTradeIn(program.program_id, tradein_id, c1Ctx);
    if (submitRes.status === 200) {
      const t1 = await getTradeIn(program.program_id, tradein_id, ops);
      expect(t1.tradein_status).toBe('SUBMITTED');
    } else {
      expect(submitRes.status).toBe(400);
      expect(extractErrorCode(submitRes.body)).toBe('ERR_CUSTOMER_NOT_ELIGIBLE');
      const t1 = await getTradeIn(program.program_id, tradein_id, ops);
      expect(t1.tradein_status).toBe('DRAFT');
    }

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(1000);
  });

  test('TRD_005: appraisal lower than provisional creates balance_due without negative credit; customer becomes LIMITED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const oSpend = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, oSpend.order_id, c1Ctx, false), 200);

    const cMid = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cMid.credit_balance_cents).toBe(5000);
    expect(cMid.balance_due_cents).toBe(0);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    const appr = await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 15000 });
    expectSuccess(appr, 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('CREDITED');
    expect(t1.final_credit_cents).toBe(15000);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(5000);
    expect(cAfter.customer_status).toBe('LIMITED');
  });

  test('TRD_006: appraisal higher than provisional increases credit balance by the difference', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 20000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const cMid = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cMid.credit_balance_cents).toBe(20000);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('CREDITED');
    expect(t1.final_credit_cents).toBe(25000);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(25000);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('ACTIVE');
  });

  test('TRD_007: rejected appraisal converts provisional to balance due, locks customer, and holds unshipped orders', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 25000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const oSubmitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(oSubmitted.order_status).toBe('SUBMITTED');

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: false, final_credit_cents: 0 }), 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('APPRAISED');
    expect(t1.final_credit_cents).toBe(0);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(25000);
    expect(cAfter.customer_status).toBe('LOCKED');

    const oHeld = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHeld.order_status).toBe('ON_HOLD');

    const alerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(alerts.alerts.length).toBeGreaterThanOrEqual(1);
  });

  test('TRD_008: reverse_credit locks customer if reversal exceeds remaining credit and holds unshipped orders', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);
    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 15000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const cMid = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cMid.credit_balance_cents).toBe(10000);

    const reverseRes = await reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'fraud review');
    expectSuccess(reverseRes, 200);

    const t1 = await getTradeIn(program.program_id, tradein_id, ops);
    expect(t1.tradein_status).toBe('REVERSED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(15000);
    expect(cAfter.customer_status).toBe('LOCKED');

    const oHeld = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHeld.order_status).toBe('ON_HOLD');

    const a = await listAlerts(program.program_id, ops, {
      alert_type: 'TRADEIN_REVERSAL',
      alert_status: 'OPEN',
      tradein_id,
      customer_id: c1.customer_id
    });
    expect(a.alerts.length).toBe(1);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('TRD_009: shipping an ON_HOLD order fails ERR_ORDER_ON_HOLD and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);
    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 15000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const beforeShip = await getOrder(program.program_id, o1.order_id, ops);
    const payment_id = beforeShip.payment_id as string;
    expect(beforeShip.order_status).toBe('SUBMITTED');
    expect(payment_id).toBeTruthy();

    expectSuccess(await reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'fraud review'), 200);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    expect(held.device_id).toBeNull();

    const pmBefore = await getPayment(program.program_id, payment_id, ops);
    expect(['AUTHORIZED', 'VOIDED']).toContain(pmBefore.payment_status);
    const paymentStatusBeforeShip = pmBefore.payment_status;

    const lotBefore = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotBefore.build_lot_status).toBe('AVAILABLE');

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SNX',
      build_tag: 'B99Z'
    });
    expectError(shipRes, 400, 'ERR_ORDER_ON_HOLD');

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('ON_HOLD');
    expect(after.device_id).toBeNull();

    const pmAfter = await getPayment(program.program_id, payment_id, ops);
    expect(pmAfter.payment_status).toBe(paymentStatusBeforeShip);
    expect(['CAPTURED', 'REFUNDED']).not.toContain(pmAfter.payment_status);

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('AVAILABLE');
  });

  test('TRD_010: refund completion returns credit balance-due-first (no credit minted while balance_due>0)', async () => {
    const program = await createProgram();

    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);
    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const o2 = await createDeliveredOrder({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      use_credit_cents: 10000
    });

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.paid_by_credit_cents).toBe(10000);
    const o2PaymentId = o2After.payment_id as string;
    expect(o2PaymentId).toBeTruthy();

    const o2PaidByCard = o2After.paid_by_card_cents;

    const rCreate = await createReturn(program.program_id, o2.order_id, c1Ctx, 'REFUND');
    expectSuccess(rCreate, 201);
    const return_id = rCreate.body.return_id as string;

    expectSuccess(await approveReturn(program.program_id, return_id, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, return_id, supCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, return_id, opsCtx, 'SCRAP'), 200);

    const rReceived = await getReturn(program.program_id, return_id, ops);
    expect(rReceived.return_status).toBe('RECEIVED');

    const o3 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 15000 });
    expectSuccess(await submitOrder(program.program_id, o3.order_id, c1Ctx, false), 200);

    const cSpent = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cSpent.credit_balance_cents).toBe(0);

    expectSuccess(await reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'fraud review'), 200);

    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.balance_due_cents).toBe(25000);
    expect(cLocked.credit_balance_cents).toBe(0);

    const complete = await completeReturn(program.program_id, return_id, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(complete, 200);

    const rDone = await getReturn(program.program_id, return_id, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_credit_cents).toBe(0);

    if (o2PaidByCard > 0) {
      expect(rDone.refunded_to_card_cents).toBeGreaterThan(0);
    }

    const o2Final = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Final.order_status).toBe('REFUNDED');

    const pm2Final = await getPayment(program.program_id, o2PaymentId, ops);
    expect(pm2Final.payment_status).toBe('REFUNDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(15000);
    expect(cAfter.credit_balance_cents).toBe(0);
  });

  test('TRDALRT_001: unlock then resolve acknowledged trade-in reversal alert (trade-in remains REVERSED)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const cWithCredit = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cWithCredit.credit_balance_cents).toBe(25000);
    expect(cWithCredit.balance_due_cents).toBe(0);

    const clawback = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 10000);
    expectSuccess(clawback, 201);
    const adjustmentId = clawback.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, adjustmentId, supCtx), 200);

    const cAfterClawback = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfterClawback.credit_balance_cents).toBe(15000);
    expect(cAfterClawback.balance_due_cents).toBe(0);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const tCredited = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tCredited.tradein_status).toBe('CREDITED');
    expect(tCredited.final_credit_cents).toBe(25000);

    expectSuccess(await reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'policy correction'), 200);

    const tReversed = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tReversed.tradein_status).toBe('REVERSED');
    const finalCreditBefore = tReversed.final_credit_cents;

    const openReversal = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', alert_status: 'OPEN', tradein_id });
    expect(openReversal.alerts.length).toBe(1);
    const alertId = openReversal.alerts[0].alert_id;

    expectSuccess(await acknowledgeAlert(program.program_id, alertId, opsCtx), 200);

    const alertAfterAck = await getAlert(program.program_id, alertId, ops);
    expect(alertAfterAck.alert_status).toBe('ACKNOWLEDGED');

    const cOwes = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cOwes.balance_due_cents).toBeGreaterThan(0);
    await settleBalanceDue(program.program_id, c1.customer_id, supCtx, cOwes.balance_due_cents);

    await runOps(program.program_id, opsCtx);

    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');
    expect(cLocked.balance_due_cents).toBe(0);
    expect(cLocked.credit_balance_cents).toBe(0);

    const unlockRes = await post(`/programs/${program.program_id}/customers/${c1.customer_id}/unlock`, {}, opsCtx);
    if (unlockRes.status === 200) {
      expect(unlockRes.body.customer_status).toBe('ACTIVE');
      expect(unlockRes.body.balance_due_cents).toBe(0);
      expect(unlockRes.body.credit_balance_cents).toBe(0);

      const cAfterUnlock = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cAfterUnlock.customer_status).toBe('ACTIVE');
      expect(cAfterUnlock.balance_due_cents).toBe(0);
      expect(cAfterUnlock.credit_balance_cents).toBe(0);

      expectSuccess(await resolveAlert(program.program_id, alertId, opsCtx), 200);
      const a1 = await getAlert(program.program_id, alertId, ops);
      expect(a1.alert_status).toBe('RESOLVED');

      const tAfter = await getTradeIn(program.program_id, tradein_id, ops);
      expect(tAfter.tradein_status).toBe('REVERSED');
      expect(tAfter.final_credit_cents).toBe(finalCreditBefore);
    } else {
      expect(unlockRes.status).toBe(400);
      expect(extractErrorCode(unlockRes.body)).toBe('ERR_PROGRAM_REVIEW_REQUIRED');

      const cStillLocked = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cStillLocked.customer_status).toBe('LOCKED');
      expect(cStillLocked.balance_due_cents).toBe(0);
      expect(cStillLocked.credit_balance_cents).toBe(0);

      const alertStillAck = await getAlert(program.program_id, alertId, ops);
      expect(alertStillAck.alert_status).toBe('ACKNOWLEDGED');

      const tStillReversed = await getTradeIn(program.program_id, tradein_id, ops);
      expect(tStillReversed.tradein_status).toBe('REVERSED');
      expect(tStillReversed.final_credit_cents).toBe(finalCreditBefore);

      const resolveRes = await resolveAlert(program.program_id, alertId, opsCtx);
      expectError(resolveRes, 400, 'ERR_ALERT_NOT_RESOLVABLE');
    }
  });

  test('TRDDED_001: cannot reverse credit twice; reversal alerts are deduplicated', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 25000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    expectSuccess(await reverseTradeInCredit(program.program_id, tradein_id, supCtx, 'retry'), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');
    expect(cLocked.credit_balance_cents).toBe(0);
    expect(cLocked.balance_due_cents).toBeGreaterThan(0);

    const open1 = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', alert_status: 'OPEN', tradein_id });
    expect(open1.alerts.length).toBe(1);
    const alertId = open1.alerts[0].alert_id;

    const reverseAgain = await reverseTradeInCredit(program.program_id, tradein_id, supCtx, 'retry');
    expectError(reverseAgain, 400, 'ERR_INVALID_STATE_TRANSITION');

    const tAfter = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tAfter.tradein_status).toBe('REVERSED');

    const open2 = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', alert_status: 'OPEN', tradein_id });
    expect(open2.alerts.length).toBe(1);
    expect(open2.alerts[0].alert_id).toBe(alertId);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBeGreaterThan(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('TRDFRZ_001: trade-in submit is blocked while PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    const freeze = await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect(freeze.program_posture).toBe('PROGRAM_FROZEN');

    const submitRes = await submitTradeIn(program.program_id, tradein_id, c1Ctx);
    expectError(submitRes, 400, 'ERR_PROGRAM_FROZEN');

    const tAfter = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tAfter.tradein_status).toBe('DRAFT');
    expect(tAfter.final_credit_cents).toBeNull();

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('TRDSTAND_001: locked customer cannot submit a new trade-in', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;

    await createAndApplyBalanceDue(program.program_id, c1.customer_id, supCtx, 5000);

    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');
    expect(cLocked.balance_due_cents).toBe(5000);
    expect(cLocked.credit_balance_cents).toBe(0);

    const submitRes = await submitTradeIn(program.program_id, tradein_id, c1Ctx);

    expect(submitRes.status).toBe(400);
    expect(['ERR_CUSTOMER_LOCKED', 'ERR_PROGRAM_REVIEW_REQUIRED']).toContain(extractErrorCode(submitRes.body));

    const tAfter = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tAfter.tradein_status).toBe('DRAFT');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
    expect(cAfter.balance_due_cents).toBe(5000);
    expect(cAfter.credit_balance_cents).toBe(0);
  });

  test('TRD_011: reversing spent trade-in credit locks customer, holds unshipped order, opens alert, program guarded', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 25000);
    expectSuccess(tCreate, 201);
    const tradein_id = tCreate.body.tradein_id as string;
    expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 25000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const o1Submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Submitted.order_status).toBe('SUBMITTED');
    expect(o1Submitted.payment_id).toBeTruthy();
    const paymentId = o1Submitted.payment_id as string;
    const pmBefore = await getPayment(program.program_id, paymentId, ops);
    expect(pmBefore.payment_status).toBe('AUTHORIZED');

    const cSpent = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cSpent.credit_balance_cents).toBe(0);

    expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
    expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 25000 }), 200);

    const reverseRes = await reverseTradeInCredit(program.program_id, tradein_id, supCtx, 'policy correction');
    expectSuccess(reverseRes, 200);

    const tAfter = await getTradeIn(program.program_id, tradein_id, ops);
    expect(tAfter.tradein_status).toBe('REVERSED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBeGreaterThan(0);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('ON_HOLD');

    const pmAfter = await getPayment(program.program_id, paymentId, ops);
    expect(['AUTHORIZED', 'VOIDED']).toContain(pmAfter.payment_status);
    expect(['CAPTURED', 'REFUNDED']).not.toContain(pmAfter.payment_status);

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', alert_status: 'OPEN', tradein_id });
    expect(alerts.alerts.length).toBe(1);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });
});
