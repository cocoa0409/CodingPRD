import { post } from '../../../test-helpers/api-client';
import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  applyAdjustment,
  cancelOrder,
  createAdjustment,
  createBuildLot,
  createCustomer,
  createOrder,
  createProgram,
  createSession,
  createTradeIn,
  freezeProgram,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  listAlerts,
  lockCustomer,
  markDelivered,
  markInboundTradeIn,
  resolveAlert,
  runOps,
  settleBalanceDue,
  shipOrder,
  submitOrder,
  submitTradeIn,
  unlockCustomer,
  uniqueId,
  appraiseTradeIn
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

async function createAndApplyAdjustment(args: {
  program_id: string;
  customer_id: string;
  supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
  adjustment_type: 'GOODWILL_CREDIT' | 'WRITE_OFF' | 'CREDIT_CLAWBACK';
  amount_cents: number;
}) {
  const createRes = await createAdjustment(args.program_id, args.customer_id, args.supportCtx, args.adjustment_type, args.amount_cents);
  expectSuccess(createRes, 201);
  const adjustment_id = createRes.body.adjustment_id as string;

  const applyRes = await applyAdjustment(args.program_id, adjustment_id, args.supportCtx);
  expectSuccess(applyRes, 200);

  return adjustment_id;
}

async function resolveAllOpenAlertsForCustomer(program_id: string, customer_id: string, opsActor: { actor_id: string; actor_type: 'Ops' }, opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }) {
  const open = await listAlerts(program_id, opsActor, { alert_status: 'OPEN', customer_id });
  for (const a of open.alerts) {
    const res = await resolveAlert(program_id, a.alert_id, opsCtx);
    expectSuccess(res, 200);
  }
}

async function unlockRaw(program_id: string, customer_id: string, ctx: { actor_id: string; actor_type: 'Ops' | 'Support' | 'Customer'; session_id: string }) {
  return post(`/programs/${program_id}/customers/${customer_id}/unlock`, {}, ctx);
}

async function settleBalanceDueRaw(program_id: string, customer_id: string, ctx: { actor_id: string; actor_type: 'Ops' | 'Support' | 'Customer'; session_id: string }, amount_cents: number) {
  return post(`/programs/${program_id}/customers/${customer_id}/settle_balance_due`, { amount_cents }, ctx);
}

async function createDeliveredOrder(args: {
  program_id: string;
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  opsActor: { actor_id: string; actor_type: 'Ops' };
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  build_lot_id: string;
  build_tag: string;
}) {
  const o1 = await createOrder(args.program_id, args.customer_id, args.customerCtx);
  expectSuccess(await submitOrder(args.program_id, o1.order_id, args.customerCtx, false), 200);

  const shipRes = await shipOrder(args.program_id, o1.order_id, args.opsCtx, {
    build_lot_id: args.build_lot_id,
    serial_number: `SN-${uniqueId('sn')}`,
    build_tag: args.build_tag
  });
  expectSuccess(shipRes, 200);

  const deliveredRes = await markDelivered(args.program_id, o1.order_id, args.opsCtx);
  expectSuccess(deliveredRes, 200);

  const delivered = await getOrder(args.program_id, o1.order_id, args.opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.device_id).toBeTruthy();
  return { order_id: delivered.order_id, device_id: delivered.device_id as string };
}

async function makeCustomerLimitedWithBalanceDue(args: {
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

  const trSubmit = await submitTradeIn(args.program_id, tradein_id, args.customerCtx);
  expectSuccess(trSubmit, 200);

  const spendOrder = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: args.spend_credit_cents });
  expectSuccess(await submitOrder(args.program_id, spendOrder.order_id, args.customerCtx, false), 200);

  expectSuccess(await markInboundTradeIn(args.program_id, tradein_id, args.opsCtx), 200);

  const appr = await appraiseTradeIn(args.program_id, tradein_id, args.opsCtx, { accepted: true, final_credit_cents: args.final_credit_cents });
  expectSuccess(appr, 200);

  return getCustomer(args.program_id, args.customer_id, args.opsActor);
}

describe('Feature 6: Customers: Standing, Balance Due, Settlement & Unlock (v1)', () => {
  test('CUST_001: settle_balance_due allowed in PROGRAM_FROZEN; does not auto-return standing', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 20000
    });

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const before = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(before.customer_status).toBe('LOCKED');
    expect(before.balance_due_cents).toBe(20000);
    expect(before.credit_balance_cents).toBe(0);

    const settleRes = await settleBalanceDueRaw(program.program_id, c1.customer_id, supCtx, 20000);
    expectSuccess(settleRes, 200);
    expect(settleRes.body.balance_due_cents).toBe(0);
    expect(settleRes.body.credit_balance_cents).toBe(0);

    const after = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(after.balance_due_cents).toBe(0);
    expect(after.credit_balance_cents).toBe(0);
    expect(after.customer_status).toBe('LOCKED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('CUST_002: unlock fails when customer has positive balance due', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const limited = await makeCustomerLimitedWithBalanceDue({
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
    expect(limited.balance_due_cents).toBe(5000);

    const unlockRes = await unlockRaw(program.program_id, c1.customer_id, opsCtx);
    expectError(unlockRes, 400, 'ERR_CUSTOMER_NOT_ELIGIBLE');

    const after = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(after.customer_status).toBe('LIMITED');
    expect(after.balance_due_cents).toBe(5000);
  });

  test('CUST_003: unlock fails until at least one ops run closes after settlement', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 2000
    });

    const settled = await settleBalanceDue(program.program_id, c1.customer_id, supCtx, 2000);
    expect(settled.balance_due_cents).toBe(0);

    const unlockRes = await unlockRaw(program.program_id, c1.customer_id, opsCtx);

    expectError(unlockRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const after = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(after.customer_status).toBe('LOCKED');
    expect(after.balance_due_cents).toBe(0);
  });

  test('CUST_004: unlock succeeds after balance_due=0 and a closed ops run since settlement', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 2000
    });

    expect((await getCustomer(program.program_id, c1.customer_id, ops)).customer_status).toBe('LOCKED');

    expect((await settleBalanceDue(program.program_id, c1.customer_id, supCtx, 2000)).balance_due_cents).toBe(0);

    await runOps(program.program_id, opsCtx);

    await resolveAllOpenAlertsForCustomer(program.program_id, c1.customer_id, ops, opsCtx);

    const pActive = await getProgram(program.program_id, ops);
    expect(pActive.program_posture).toBe('PROGRAM_ACTIVE');

    const unlocked = await unlockCustomer(program.program_id, c1.customer_id, opsCtx);
    expect(unlocked.customer_status).toBe('ACTIVE');
    expect(unlocked.balance_due_cents).toBe(0);

    const after = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(after.customer_status).toBe('ACTIVE');
    expect(after.balance_due_cents).toBe(0);
  });

  test('CUST_005: LIMITED customer cannot submit a new order (ERR_CUSTOMER_NOT_ELIGIBLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expect(o1.order_status).toBe('DRAFT');

    const limited = await makeCustomerLimitedWithBalanceDue({
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
    expect(limited.balance_due_cents).toBe(5000);

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBeGreaterThanOrEqual(1);

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectError(submitRes, 400, 'ERR_CUSTOMER_NOT_ELIGIBLE');

    const afterOrder = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterOrder.order_status).toBe('DRAFT');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('CUST_006: locked customer cannot activate device (ERR_CUSTOMER_LOCKED)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { order_id, device_id } = await createDeliveredOrder({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag
    });

    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk');

    const activateRes = await activateDevice(program.program_id, device_id, c1Ctx);
    expectError(activateRes, 400, 'ERR_CUSTOMER_LOCKED');

    const d1 = await getDevice(program.program_id, device_id, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const oAfter = await getOrder(program.program_id, order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
  });

  test('CUST_007: locked customer can cancel an ON_HOLD order as cleanup', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const pCommitted = await getProgram(program.program_id, ops);
    expect(pCommitted.available_to_commit_units).toBe(0);

    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk containment');

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const paymentId = held.payment_id as string;
    expect(paymentId).toBeTruthy();

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cleanup while restricted');
    expectSuccess(cancelRes, 200);
    expect(cancelRes.body.order_status).toBe('CANCELED');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);
  });

  test('CUST_008: locking customer moves SUBMITTED orders to ON_HOLD, opens alert, guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const locked = await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk containment');
    expect(locked.customer_status).toBe('LOCKED');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('ON_HOLD');

    const alerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(alerts.alerts.length).toBeGreaterThanOrEqual(1);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('CUST_009: LIMITED settles balance due; after ops run close, unlock returns to ACTIVE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');
    const N = p0.ops_run_index;

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const limited = await makeCustomerLimitedWithBalanceDue({
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
    expect(limited.balance_due_cents).toBe(5000);
    expect(limited.credit_balance_cents).toBe(0);

    const openAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(openAlerts.alerts.length).toBe(0);

    const afterSettle = await settleBalanceDue(program.program_id, c1.customer_id, c1Ctx, 5000);
    expect(afterSettle.balance_due_cents).toBe(0);
    expect(afterSettle.credit_balance_cents).toBe(0);
    expect(afterSettle.customer_status).toBe('LIMITED');

    const p1 = await runOps(program.program_id, opsCtx);
    expect(p1.ops_run_index).toBe(N + 1);

    const unlocked = await unlockCustomer(program.program_id, c1.customer_id, opsCtx);
    expect(unlocked.customer_status).toBe('ACTIVE');
    expect(unlocked.balance_due_cents).toBe(0);
    expect(unlocked.credit_balance_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('CUST_010: unlock is blocked in PROGRAM_FROZEN (ERR_PROGRAM_FROZEN) even if otherwise eligible', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const c1 = await createCustomer(program.program_id, opsCtx);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 1000
    });

    expect((await settleBalanceDue(program.program_id, c1.customer_id, supCtx, 1000)).balance_due_cents).toBe(0);

    const pAfterRun = await runOps(program.program_id, opsCtx);

    await resolveAllOpenAlertsForCustomer(program.program_id, c1.customer_id, ops, opsCtx);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');
    expect(pFrozen.ops_run_index).toBe(pAfterRun.ops_run_index);

    const unlockRes = await unlockRaw(program.program_id, c1.customer_id, opsCtx);
    expectError(unlockRes, 400, 'ERR_PROGRAM_FROZEN');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
    expect(cAfter.balance_due_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.ops_run_index).toBe(pFrozen.ops_run_index);
  });
});
