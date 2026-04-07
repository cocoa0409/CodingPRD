import { expectError, expectErrorOneOf, expectSuccess } from '../../../test-helpers/assertions';
import {
  acknowledgeAlert,
  applyAdjustment,
  cancelOrder,
  createAdjustment,
  createBuildLot,
  createCustomer,
  createOrder,
  createProgram,
  createSession,
  createTradeIn,
  disputePayment,
  freezeProgram,
  getAdjustment,
  getCustomer,
  getOrder,
  getPayment,
  getProgram,
  getTradeIn,
  listAlerts,
  markDelivered,
  markInboundTradeIn,
  resolveDispute,
  runOps,
  shipOrder,
  submitOrder,
  submitTradeIn,
  uniqueId,
  voidAdjustment
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

async function createDeliveredPaymentAlertToGuardProgram(program_id: string, opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }, supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string }) {
  const opsActor = { actor_id: opsCtx.actor_id, actor_type: 'Ops' as const };

  const lot = await createBuildLot(program_id, opsCtx, 'B99Z', 20);

  const c = await createCustomer(program_id, opsCtx);
  const { ctx: cCtx } = await createCustomerCtx(program_id, c.customer_id);

  const o = await createOrder(program_id, c.customer_id, cCtx);
  expectSuccess(await submitOrder(program_id, o.order_id, cCtx, false), 200);

  expectSuccess(
    await shipOrder(program_id, o.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: `SN-${uniqueId('sn')}`,
      build_tag: lot.build_tag
    }),
    200
  );
  expectSuccess(await markDelivered(program_id, o.order_id, opsCtx), 200);

  const delivered = await getOrder(program_id, o.order_id, opsActor);
  const payment_id = delivered.payment_id as string;

  expectSuccess(await disputePayment(program_id, payment_id, supportCtx), 200);

  const a = await listAlerts(program_id, opsActor, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
  expect(a.alerts.length).toBe(1);

  const p = await getProgram(program_id, opsActor);
  expect(p.program_posture).toBe('PROGRAM_GUARDED');

  return { alert_id: a.alerts[0].alert_id };
}

async function createLimitedCustomerWithBalanceDue(program_id: string, opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }) {
  const opsActor = { actor_id: opsCtx.actor_id, actor_type: 'Ops' as const };

  await createBuildLot(program_id, opsCtx, 'B99Z', 20);

  const c1 = await createCustomer(program_id, opsCtx);
  const { ctx: c1Ctx } = await createCustomerCtx(program_id, c1.customer_id);

  const tCreate = await createTradeIn(program_id, c1.customer_id, c1Ctx, 10000);
  expectSuccess(tCreate, 201);
  const tradein_id = tCreate.body.tradein_id as string;

  expectSuccess(await submitTradeIn(program_id, tradein_id, c1Ctx), 200);

  const oSpend = await createOrder(program_id, c1.customer_id, c1Ctx, { use_credit_cents: 8000 });
  expectSuccess(await submitOrder(program_id, oSpend.order_id, c1Ctx, false), 200);

  expectSuccess(await markInboundTradeIn(program_id, tradein_id, opsCtx), 200);
  expectSuccess(await (await import('../../../test-helpers/resources')).appraiseTradeIn(program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 0 }), 200);

  const after = await getCustomer(program_id, c1.customer_id, opsActor);
  expect(after.credit_balance_cents).toBe(0);
  expect(after.balance_due_cents).toBe(8000);
  expect(after.customer_status).toBe('LIMITED');

  return { customer_id: c1.customer_id, customerCtx: c1Ctx };
}

describe('Feature 8: Adjustments: Apply/Void Ledger Corrections (v1)', () => {
  test('ADJ_001: apply GOODWILL_CREDIT in ACTIVE program credits customer and leaves posture unchanged', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;
    expect(adjCreate.body.adjustment_status).toBe('PENDING');

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(applyRes, 200);
    expect(applyRes.body.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(10000);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('ACTIVE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('ADJ_002: applying GOODWILL_CREDIT in PROGRAM_GUARDED fails ERR_PROGRAM_REVIEW_REQUIRED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createDeliveredPaymentAlertToGuardProgram(program.program_id, opsCtx, supCtx);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectError(applyRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const adj = await getAdjustment(program.program_id, adjId, ops);
    expect(adj.adjustment_status).toBe('PENDING');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);
  });

  test('ADJ_003: applying GOODWILL_CREDIT for LIMITED customer fails ERR_CUSTOMER_NOT_ELIGIBLE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { customer_id } = await createLimitedCustomerWithBalanceDue(program.program_id, opsCtx);

    const cBefore = await getCustomer(program.program_id, customer_id, ops);
    const creditBefore = cBefore.credit_balance_cents;

    const adjCreate = await createAdjustment(program.program_id, customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);

    expectErrorOneOf(applyRes, 400, ['ERR_CUSTOMER_NOT_ELIGIBLE', 'ERR_ADJUSTMENT_NOT_ELIGIBLE']);

    const adj = await getAdjustment(program.program_id, adjId, ops);
    expect(adj.adjustment_status).toBe('PENDING');

    const cAfter = await getCustomer(program.program_id, customer_id, ops);
    expect(cAfter.customer_status).toBe('LIMITED');
    expect(cAfter.balance_due_cents).toBeGreaterThan(0);

    expect(cAfter.credit_balance_cents).toBe(creditBefore);
  });

  test('ADJ_004: WRITE_OFF is allowed in PROGRAM_FROZEN and reduces balance due to zero', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const claw = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(claw, 201);
    const clawId = claw.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, clawId, supCtx), 200);

    const cDebt = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cDebt.balance_due_cents).toBe(5000);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const writeoff = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'WRITE_OFF', 5000);
    expectSuccess(writeoff, 201);
    const woId = writeoff.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, woId, supCtx);
    expectSuccess(applyRes, 200);
    expect(applyRes.body.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.credit_balance_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('ADJ_005: CREDIT_CLAWBACK can create balance due, locks customer, holds unshipped orders, guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 3000);
    expectSuccess(tCreate, 201);
    const tId = tCreate.body.tradein_id as string;
    expectSuccess(await submitTradeIn(program.program_id, tId, c1Ctx), 200);

    const cCredited = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cCredited.credit_balance_cents).toBe(3000);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const oSubmitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(oSubmitted.order_status).toBe('SUBMITTED');

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(applyRes, 200);
    expect(applyRes.body.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(2000);
    expect(cAfter.customer_status).toBe('LOCKED');

    const oHeld = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHeld.order_status).toBe('ON_HOLD');

    const openAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(openAlerts.alerts.length).toBeGreaterThanOrEqual(1);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ADJ_006: voiding an APPLIED goodwill credit within void window removes credit without creating balance due', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    expectSuccess(await applyAdjustment(program.program_id, adjId, supCtx), 200);

    const cCredited = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cCredited.credit_balance_cents).toBe(10000);
    expect(cCredited.balance_due_cents).toBe(0);

    const voidRes = await voidAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(voidRes, 200);
    expect(voidRes.body.adjustment_status).toBe('VOIDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('ACTIVE');
  });

  test('ADJ_007: voiding after next ops run closes fails ERR_ADJUSTMENT_NOT_VOIDABLE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    expectSuccess(await applyAdjustment(program.program_id, adjId, supCtx), 200);

    await runOps(program.program_id, opsCtx);

    const voidRes = await voidAdjustment(program.program_id, adjId, supCtx);
    expectError(voidRes, 400, 'ERR_ADJUSTMENT_NOT_VOIDABLE');

    const adj = await getAdjustment(program.program_id, adjId, ops);
    expect(adj.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(10000);
    expect(cAfter.balance_due_cents).toBe(0);
  });

  test('ADJ_008: voiding goodwill credit after partial spend creates balance due, locks customer, holds other orders, guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, adjId, supCtx), 200);

    const oSpend = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 8000 });
    expectSuccess(await submitOrder(program.program_id, oSpend.order_id, c1Ctx, false), 200);

    const cMid = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cMid.credit_balance_cents).toBe(2000);

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);

    const o2Submitted = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Submitted.order_status).toBe('SUBMITTED');

    const voidRes = await voidAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(voidRes, 200);
    expect(voidRes.body.adjustment_status).toBe('VOIDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(8000);
    expect(cAfter.customer_status).toBe('LOCKED');

    const o2Held = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Held.order_status).toBe('ON_HOLD');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');

    const openAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(openAlerts.alerts.length).toBeGreaterThanOrEqual(1);
  });

  test('ADJ_009: WRITE_OFF removes balance due but does not auto-unlock customer', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const claw = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(claw, 201);
    const clawId = claw.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(program.program_id, clawId, supCtx), 200);

    const writeoff = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'WRITE_OFF', 5000);
    expectSuccess(writeoff, 201);
    const woId = writeoff.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, woId, supCtx);
    expectSuccess(applyRes, 200);

    const adjAfter = await getAdjustment(program.program_id, woId, ops);
    expect(adjAfter.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('LOCKED');

    expect(cAfter.credit_balance_cents).toBe(0);
  });

  test('ADJ_010: CREDIT_CLAWBACK is allowed in PROGRAM_FROZEN and reduces credit balance', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 10000);
    expectSuccess(tCreate, 201);
    const tId = tCreate.body.tradein_id as string;
    expectSuccess(await submitTradeIn(program.program_id, tId, c1Ctx), 200);

    const cCredited = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cCredited.credit_balance_cents).toBe(10000);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(applyRes, 200);
    expect(applyRes.body.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(5000);
    expect(cAfter.balance_due_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('ADJ_011: WRITE_OFF applies in GUARDED and does not resolve unrelated OPEN alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { alert_id: aOtherId } = await createDeliveredPaymentAlertToGuardProgram(program.program_id, opsCtx, supCtx);

    const c1 = await createCustomer(program.program_id, opsCtx);

    const claw = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(claw, 201);
    expectSuccess(await applyAdjustment(program.program_id, claw.body.adjustment_id as string, supCtx), 200);

    const writeoff = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'WRITE_OFF', 5000);
    expectSuccess(writeoff, 201);
    const woId = writeoff.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, woId, supCtx);
    expectSuccess(applyRes, 200);

    const adj = await getAdjustment(program.program_id, woId, ops);
    expect(adj.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.customer_status).toBe('LOCKED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');

    const still = await (await import('../../../test-helpers/resources')).getAlert(program.program_id, aOtherId, ops);
    expect(still.alert_status).toBe('OPEN');
  });

  test('ADJ_012: CREDIT_CLAWBACK applies in GUARDED; locks customer and holds order; unrelated alert stays OPEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 3000);
    expectSuccess(tCreate, 201);
    const tId = tCreate.body.tradein_id as string;
    expectSuccess(await submitTradeIn(program.program_id, tId, c1Ctx), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const { alert_id: aOtherId } = await createDeliveredPaymentAlertToGuardProgram(program.program_id, opsCtx, supCtx);

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'CREDIT_CLAWBACK', 5000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectSuccess(applyRes, 200);

    const adj = await getAdjustment(program.program_id, adjId, ops);
    expect(adj.adjustment_status).toBe('APPLIED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(2000);
    expect(cAfter.customer_status).toBe('LOCKED');

    const oHeld = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHeld.order_status).toBe('ON_HOLD');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');

    const still = await (await import('../../../test-helpers/resources')).getAlert(program.program_id, aOtherId, ops);
    expect(still.alert_status).toBe('OPEN');
  });

  test('ADJ_013: applying GOODWILL_CREDIT in PROGRAM_FROZEN fails ERR_PROGRAM_FROZEN and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const adjCreate = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 10000);
    expectSuccess(adjCreate, 201);
    const adjId = adjCreate.body.adjustment_id as string;

    const applyRes = await applyAdjustment(program.program_id, adjId, supCtx);
    expectError(applyRes, 400, 'ERR_PROGRAM_FROZEN');

    const adj = await getAdjustment(program.program_id, adjId, ops);
    expect(adj.adjustment_status).toBe('PENDING');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(0);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.customer_status).toBe('ACTIVE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });
});
