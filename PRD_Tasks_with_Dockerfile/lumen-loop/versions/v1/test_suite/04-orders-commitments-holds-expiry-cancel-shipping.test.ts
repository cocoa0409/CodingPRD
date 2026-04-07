import { expectError, expectErrorOneOf, expectSuccess } from '../../../test-helpers/assertions';
import {
  applyAdjustment,
  cancelOrder,
  createAdjustment,
  createBuildLot,
  createCustomer,
  createOrder,
  createProgram,
  createSession,
  disputePayment,
  freezeProgram,
  getCarePlan,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  lockCustomer,
  refreshPayment,
  runOps,
  shipOrder,
  submitOrder,
  uniqueId,
  getBuildLot,
  markDelivered
} from '../../../test-helpers/resources';

async function createAndApplyAdjustment(args: {
  program_id: string;
  customer_id: string;
  supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
  adjustment_type: 'GOODWILL_CREDIT' | 'WRITE_OFF' | 'CREDIT_CLAWBACK';
  amount_cents: number;
}) {
  const adjRes = await createAdjustment(args.program_id, args.customer_id, args.supportCtx, args.adjustment_type, args.amount_cents);
  expectSuccess(adjRes, 201);
  const adjustment_id = adjRes.body.adjustment_id as string;

  const applyRes = await applyAdjustment(args.program_id, adjustment_id, args.supportCtx);
  expectSuccess(applyRes, 200);

  return { adjustment_id };
}

describe('Feature 4: Orders: Commitments, Holds, Expiry, Cancel & Shipping (v1)', () => {
  test('ORD_001: submit commits unit, debits credit, authorizes remainder, creates pending care plan', async () => {
    const program = await createProgram({ unit_price_cents: 79900, care_plan_price_cents: 9900 });

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 30000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, true);
    expectSuccess(submitRes, 200);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SUBMITTED');
    expect(oAfter.paid_by_credit_cents).toBe(20000);
    expect(oAfter.paid_by_card_cents).toBe(69800);
    expect(oAfter.payment_id).toBeTruthy();
    expect(oAfter.care_plan_id).toBeTruthy();

    const pm = await getPayment(program.program_id, oAfter.payment_id as string, ops);
    expect(pm.payment_status).toBe('AUTHORIZED');
    expect(pm.amount_cents).toBe(69800);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(10000);
    expect(cAfter.balance_due_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);

    const cp = await getCarePlan(program.program_id, oAfter.care_plan_id as string, ops);
    expect(cp.care_plan_status).toBe('PENDING_ACTIVATION');
  });

  test('ORD_002: submit fails with ERR_OUT_OF_STOCK and makes no changes', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(0);

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectError(submitRes, 400, 'ERR_OUT_OF_STOCK');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();
    expect(oAfter.paid_by_credit_cents).toBe(0);
    expect(oAfter.paid_by_card_cents).toBe(0);
    expect(oAfter.care_plan_id).toBeNull();
    expect(oAfter.device_id).toBeNull();

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(20000);
    expect(cAfter.balance_due_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('ORD_003: locked customer cannot submit (ERR_CUSTOMER_LOCKED) and no changes occur', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk');

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(1);

    const cBefore = await getCustomer(program.program_id, c1.customer_id, ops);

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);

    expectErrorOneOf(submitRes, 400, ['ERR_CUSTOMER_LOCKED', 'ERR_PROGRAM_REVIEW_REQUIRED']);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DRAFT');
    expect(oAfter.payment_id).toBeNull();
    expect(oAfter.paid_by_credit_cents).toBe(0);
    expect(oAfter.paid_by_card_cents).toBe(0);
    expect(oAfter.care_plan_id).toBeNull();

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(cBefore.credit_balance_cents);
    expect(cAfter.balance_due_cents).toBe(cBefore.balance_due_cents);
  });

  test('ORD_004: run_ops moves unshipped SUBMITTED order to ON_HOLD and voids authorization', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = submitted.payment_id as string;
    expect(pmId).toBeTruthy();

    const pBefore = await getProgram(program.program_id, ops);
    const base = pBefore.ops_run_index;

    const pAfterRun = await runOps(program.program_id, opsCtx);
    expect(pAfterRun.ops_run_index).toBe(base + 1);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('ON_HOLD');

    const pmAfter = await getPayment(program.program_id, pmId, ops);
    expect(pmAfter.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('ORD_005: second run_ops expires payment-refresh ON_HOLD, releases commitment, returns credit, voids care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);

    const p0 = await getProgram(program.program_id, ops);
    const base = p0.ops_run_index;

    await runOps(program.program_id, opsCtx);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const pmOld = await getPayment(program.program_id, held.payment_id as string, ops);
    expect(pmOld.payment_status).toBe('VOIDED');

    await runOps(program.program_id, opsCtx);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.ops_run_index).toBe(base + 2);
    expect(pAfter.available_to_commit_units).toBe(1);

    const expired = await getOrder(program.program_id, o1.order_id, ops);
    expect(expired.order_status).toBe('EXPIRED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(20000);
    expect(cAfter.balance_due_cents).toBe(0);

    const pmStill = await getPayment(program.program_id, held.payment_id as string, ops);
    expect(pmStill.payment_status).toBe('VOIDED');

    const cp = await getCarePlan(program.program_id, expired.care_plan_id as string, ops);
    expect(cp.care_plan_status).toBe('VOIDED');
  });

  test('ORD_006: refresh_payment reauthorizes with new payment and returns order to SUBMITTED', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const expectedCardAmount = submitted.paid_by_card_cents;

    await runOps(program.program_id, opsCtx);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const oldPaymentId = held.payment_id as string;
    expect(oldPaymentId).toBeTruthy();
    expect((await getPayment(program.program_id, oldPaymentId, ops)).payment_status).toBe('VOIDED');

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectSuccess(refreshRes, 200);

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('SUBMITTED');
    expect(after.payment_id).toBeTruthy();
    expect(after.payment_id).not.toBe(oldPaymentId);

    const oldPmAfter = await getPayment(program.program_id, oldPaymentId, ops);
    expect(oldPmAfter.payment_status).toBe('VOIDED');

    const newPm = await getPayment(program.program_id, after.payment_id as string, ops);
    expect(newPm.payment_status).toBe('AUTHORIZED');

    expect(newPm.amount_cents).toBe(expectedCardAmount);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('ORD_007: refresh_payment blocked in PROGRAM_GUARDED (ERR_PROGRAM_REVIEW_REQUIRED) and no new auth is created', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const holdOrder = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, holdOrder.order_id, c1Ctx, false), 200);
    await runOps(program.program_id, opsCtx);

    const held = await getOrder(program.program_id, holdOrder.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const heldPaymentId = held.payment_id as string;
    expect((await getPayment(program.program_id, heldPaymentId, ops)).payment_status).toBe('VOIDED');

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 6);
    const shippedOrder = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, shippedOrder.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, shippedOrder.order_id, opsCtx, {
        build_lot_id: saleLot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: saleLot.build_tag
      }),
      200
    );

    const shipped = await getOrder(program.program_id, shippedOrder.order_id, ops);
    const payToDispute = shipped.payment_id as string;
    expect(payToDispute).toBeTruthy();

    expectSuccess(await disputePayment(program.program_id, payToDispute, supportCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const refreshRes = await refreshPayment(program.program_id, holdOrder.order_id, c1Ctx);
    expectError(refreshRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const heldAfter = await getOrder(program.program_id, holdOrder.order_id, ops);
    expect(heldAfter.order_status).toBe('ON_HOLD');
    expect(heldAfter.payment_id).toBe(heldPaymentId);

    const pmStill = await getPayment(program.program_id, heldPaymentId, ops);
    expect(pmStill.payment_status).toBe('VOIDED');
  });

  test('ORD_008: cancel SUBMITTED unwinds payment, credit, commitment and voids care plan', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'customer requested');
    expectSuccess(cancelRes, 200);

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('CANCELED');

    const pm = await getPayment(program.program_id, submitted.payment_id as string, ops);
    expect(pm.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(20000);

    const cp = await getCarePlan(program.program_id, submitted.care_plan_id as string, ops);
    expect(cp.care_plan_status).toBe('VOIDED');
  });

  test('ORD_009: cancel is allowed while PROGRAM_FROZEN for unshipped orders', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'containment cleanup');
    expectSuccess(cancelRes, 200);

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('CANCELED');

    const pm = await getPayment(program.program_id, after.payment_id as string, ops);
    expect(pm.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);

    expect(cAfter.credit_balance_cents).toBe(20000);
  });

  test('ORD_010: cancel fails with ERR_ORDER_NOT_CANCELABLE once SHIPPED (even if frozen)', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: (await createBuildLot(program.program_id, opsCtx, 'B99Z', 1)).build_lot_id,
      serial_number: `SN-${uniqueId('sn')}`,
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const shipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped.order_status).toBe('SHIPPED');

    const pmId = shipped.payment_id as string;
    const deviceId = shipped.device_id as string;

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');

    const pBefore = await getProgram(program.program_id, ops);

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'too late');
    expectError(cancelRes, 400, 'ERR_ORDER_NOT_CANCELABLE');

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('SHIPPED');
    expect(after.device_id).toBe(deviceId);

    const pm = await getPayment(program.program_id, pmId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('ORD_011: ship captures payment and creates a SHIPPED device with matching build info', async () => {
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
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const before = await getProgram(program.program_id, ops);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SN123',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const shipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped.order_status).toBe('SHIPPED');
    expect(shipped.device_id).toBeTruthy();

    const pm = await getPayment(program.program_id, shipped.payment_id as string, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const d = await getDevice(program.program_id, shipped.device_id as string, ops);
    expect(d.device_status).toBe('SHIPPED');
    expect(d.serial_number).toBe('SN123');
    expect(d.build_tag).toBe('B99Z');

    const after = await getProgram(program.program_id, ops);
    expect(after.available_to_commit_units).toBe(before.available_to_commit_units);
  });

  test('ORD_012: mark_delivered moves order to DELIVERED without activating device', async () => {
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
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: 'B99Z'
      }),
      200
    );

    const shipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped.order_status).toBe('SHIPPED');

    const before = await getProgram(program.program_id, ops);

    const deliveredRes = await markDelivered(program.program_id, o1.order_id, opsCtx);
    expectSuccess(deliveredRes, 200);

    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    expect(delivered.order_status).toBe('DELIVERED');

    const pm = await getPayment(program.program_id, delivered.payment_id as string, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const d = await getDevice(program.program_id, delivered.device_id as string, ops);
    expect(d.device_status).toBe('SHIPPED');

    const after = await getProgram(program.program_id, ops);
    expect(after.available_to_commit_units).toBe(before.available_to_commit_units);
  });

  test('ORD_013: cancel returns credit balance-due-first and does not auto-unlock customer', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = submitted.payment_id as string;

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 15000
    });

    const cBeforeCancel = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cBeforeCancel.customer_status).toBe('LOCKED');
    expect(cBeforeCancel.credit_balance_cents).toBe(0);
    expect(cBeforeCancel.balance_due_cents).toBe(15000);

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(0);

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cleanup');
    expectSuccess(cancelRes, 200);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('CANCELED');

    const pm = await getPayment(program.program_id, pmId, ops);
    expect(pm.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.credit_balance_cents).toBe(5000);
    expect(cAfter.customer_status).toBe('LOCKED');
  });

  test('ORD_014: run_ops expiration returns credit balance-due-first', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    await runOps(program.program_id, opsCtx);
    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const pmId = held.payment_id as string;
    expect((await getPayment(program.program_id, pmId, ops)).payment_status).toBe('VOIDED');

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 15000
    });

    const cBefore = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cBefore.balance_due_cents).toBe(15000);
    expect(cBefore.credit_balance_cents).toBe(0);

    const pBefore = await getProgram(program.program_id, ops);
    const base = pBefore.ops_run_index;

    await runOps(program.program_id, opsCtx);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.ops_run_index).toBe(base + 1);
    expect(pAfter.available_to_commit_units).toBe(1);

    const expired = await getOrder(program.program_id, o1.order_id, ops);
    expect(expired.order_status).toBe('EXPIRED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.credit_balance_cents).toBe(5000);

    const pmStill = await getPayment(program.program_id, pmId, ops);
    expect(pmStill.payment_status).toBe('VOIDED');
  });

  test('ORD_015: credit-only submit creates no payment and ship creates device without payment', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 79900
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 79900 });

    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectSuccess(submitRes, 200);

    const oAfterSubmit = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfterSubmit.order_status).toBe('SUBMITTED');
    expect(oAfterSubmit.paid_by_credit_cents).toBe(79900);
    expect(oAfterSubmit.paid_by_card_cents).toBe(0);
    expect(oAfterSubmit.payment_id).toBeNull();

    const cAfterSubmit = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfterSubmit.credit_balance_cents).toBe(0);

    const pAfterSubmit = await getProgram(program.program_id, ops);
    expect(pAfterSubmit.available_to_commit_units).toBe(0);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SN-CREDIT-1',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const oAfterShip = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfterShip.order_status).toBe('SHIPPED');
    expect(oAfterShip.device_id).toBeTruthy();
    expect(oAfterShip.payment_id).toBeNull();

    const d = await getDevice(program.program_id, oAfterShip.device_id as string, ops);
    expect(d.device_status).toBe('SHIPPED');
    expect(d.serial_number).toBe('SN-CREDIT-1');
    expect(d.build_tag).toBe('B99Z');
  });

  test('ORD_016: locked customer cannot refresh_payment (ERR_CUSTOMER_LOCKED) and order/payment unchanged', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    await runOps(program.program_id, opsCtx);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');
    const pmOld = held.payment_id as string;
    expect((await getPayment(program.program_id, pmOld, ops)).payment_status).toBe('VOIDED');

    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'seed locked');

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectError(refreshRes, 400, 'ERR_CUSTOMER_LOCKED');

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('ON_HOLD');
    expect(after.payment_id).toBe(pmOld);

    const pmStill = await getPayment(program.program_id, pmOld, ops);
    expect(pmStill.payment_status).toBe('VOIDED');
  });

  test('ORD_017: run_ops does not alter credit-only SUBMITTED order with no payment authorization', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 79900
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 79900 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const beforeOrder = await getOrder(program.program_id, o1.order_id, ops);
    expect(beforeOrder.order_status).toBe('SUBMITTED');
    expect(beforeOrder.payment_id).toBeNull();

    const pBefore = await getProgram(program.program_id, ops);
    const base = pBefore.ops_run_index;

    const pAfterRun = await runOps(program.program_id, opsCtx);
    expect(pAfterRun.ops_run_index).toBe(base + 1);
    expect(pAfterRun.program_posture).toBe('PROGRAM_ACTIVE');

    const afterOrder = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterOrder.order_status).toBe('SUBMITTED');
    expect(afterOrder.payment_id).toBeNull();

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('ORD_018: refresh_payment then ship captures new auth, creates device, consumes 1-unit lot', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 5);
    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    await runOps(program.program_id, opsCtx);

    const held = await getOrder(program.program_id, o1.order_id, ops);
    expect(held.order_status).toBe('ON_HOLD');

    const pmOld = held.payment_id as string;
    const oldPm = await getPayment(program.program_id, pmOld, ops);
    expect(oldPm.payment_status).toBe('VOIDED');

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectSuccess(refreshRes, 200);

    const afterRefresh = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterRefresh.order_status).toBe('SUBMITTED');
    const pmNew = afterRefresh.payment_id as string;
    expect(pmNew).toBeTruthy();
    expect(pmNew).not.toBe(pmOld);

    const newPm = await getPayment(program.program_id, pmNew, ops);
    expect(newPm.payment_status).toBe('AUTHORIZED');
    expect(newPm.amount_cents).toBe(59900);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: shipLot.build_lot_id,
      serial_number: 'SN-RF-1',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const shipped = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped.order_status).toBe('SHIPPED');
    expect(shipped.payment_id).toBe(pmNew);
    expect(shipped.device_id).toBeTruthy();

    const pmCaptured = await getPayment(program.program_id, pmNew, ops);
    expect(pmCaptured.payment_status).toBe('CAPTURED');

    const d = await getDevice(program.program_id, shipped.device_id as string, ops);
    expect(d.device_status).toBe('SHIPPED');
    expect(d.serial_number).toBe('SN-RF-1');
    expect(d.build_tag).toBe('B99Z');

    const lotAfter = await getBuildLot(program.program_id, shipLot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('CONSUMED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('ORD_019: credit-only + care plan submit creates care plan and cancel voids it (no payment ever exists)', async () => {
    const program = await createProgram({ unit_price_cents: 79900, care_plan_price_cents: 9900 });

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 89800
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 89800 });

    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true), 200);

    const afterSubmit = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterSubmit.order_status).toBe('SUBMITTED');
    expect(afterSubmit.paid_by_credit_cents).toBe(89800);
    expect(afterSubmit.paid_by_card_cents).toBe(0);
    expect(afterSubmit.payment_id).toBeNull();
    expect(afterSubmit.care_plan_id).toBeTruthy();

    const cAfterSubmit = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfterSubmit.credit_balance_cents).toBe(0);

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'changed mind');
    expectSuccess(cancelRes, 200);

    const afterCancel = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterCancel.order_status).toBe('CANCELED');
    expect(afterCancel.payment_id).toBeNull();

    const cAfterCancel = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfterCancel.credit_balance_cents).toBe(89800);
    expect(cAfterCancel.balance_due_cents).toBe(0);

    const cp = await getCarePlan(program.program_id, afterSubmit.care_plan_id as string, ops);
    expect(cp.care_plan_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);
  });

  test('ORD_020: ship with mismatched build_tag: accepts server-derived tag or rejects with no state change', async () => {

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
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = submitted.payment_id as string;

    const lotBefore = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotBefore.build_lot_status).toBe('AVAILABLE');

    const pBefore = await getProgram(program.program_id, ops);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SN-MISMATCH-1',
      build_tag: 'C01X'
    });

    if (shipRes.status === 200) {

      const shipped = await getOrder(program.program_id, o1.order_id, ops);
      expect(shipped.order_status).toBe('SHIPPED');
      expect(shipped.device_id).toBeTruthy();

      const d = await getDevice(program.program_id, shipped.device_id as string, ops);
      expect(d.device_status).toBe('SHIPPED');

      expect(d.build_tag).toBe(lot.build_tag);

      const pm = await getPayment(program.program_id, pmId, ops);
      expect(pm.payment_status).toBe('CAPTURED');
    } else {

      expect(shipRes.status).toBe(400);

      const afterOrder = await getOrder(program.program_id, o1.order_id, ops);
      expect(afterOrder.order_status).toBe('SUBMITTED');
      expect(afterOrder.device_id).toBeNull();

      const pm = await getPayment(program.program_id, pmId, ops);
      expect(pm.payment_status).toBe('AUTHORIZED');

      const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
      expect(lotAfter.build_lot_status).toBe('AVAILABLE');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
    }
  });

  test('ORD_021: canceling a DRAFT order is allowed and does not affect program capacity or customer balances', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(1);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const cancelRes = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'draft cleanup');
    expectSuccess(cancelRes, 200);

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('CANCELED');
    expect(after.payment_id).toBeNull();
    expect(after.device_id).toBeNull();
    expect(after.care_plan_id).toBeNull();
    expect(after.paid_by_credit_cents).toBe(0);
    expect(after.paid_by_card_cents).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(20000);
    expect(cAfter.balance_due_cents).toBe(0);
  });

  test('ORDCHK_001: ops run voids stale auth even while GUARDED; refresh_payment fails ERR_PROGRAM_REVIEW_REQUIRED with no new auth', async () => {
    const program = await createProgram({ unit_price_cents: 79900, care_plan_price_cents: 9900 });

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const o1Submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Submitted.order_status).toBe('SUBMITTED');
    expect(o1Submitted.payment_id).toBeTruthy();
    const pm1Id = o1Submitted.payment_id as string;

    const pm1Before = await getPayment(program.program_id, pm1Id, ops);
    expect(pm1Before.payment_status).toBe('AUTHORIZED');

    const c2 = await createCustomer(program.program_id, opsCtx);
    const c2Actor = { actor_id: c2.customer_id, actor_type: 'Customer' as const };
    const c2Session = await createSession(program.program_id, c2Actor);
    const c2Ctx = { ...c2Actor, session_id: c2Session.session_id };

    const o2 = await createOrder(program.program_id, c2.customer_id, c2Ctx);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c2Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o2.order_id, opsCtx, {
        build_lot_id: (await createBuildLot(program.program_id, opsCtx, 'B88X', 6)).build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: 'B88X'
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o2.order_id, opsCtx), 200);

    const o2Delivered = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Delivered.order_status).toBe('DELIVERED');
    expect(o2Delivered.payment_id).toBeTruthy();
    expectSuccess(await disputePayment(program.program_id, o2Delivered.payment_id as string, supportCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const n = pGuarded.ops_run_index;
    const afterOps = await runOps(program.program_id, opsCtx);
    expect(afterOps.ops_run_index).toBe(n + 1);
    expect(afterOps.program_posture).toBe('PROGRAM_GUARDED');

    const pm1AfterOps = await getPayment(program.program_id, pm1Id, ops);
    expect(pm1AfterOps.payment_status).toBe('VOIDED');

    const o1AfterOps = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1AfterOps.order_status).toBe('ON_HOLD');
    expect(o1AfterOps.payment_id).toBe(pm1Id);

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectError(refreshRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const o1AfterAttempt = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1AfterAttempt.order_status).toBe('ON_HOLD');
    expect(o1AfterAttempt.payment_id).toBe(pm1Id);

    const pm1AfterAttempt = await getPayment(program.program_id, pm1Id, ops);
    expect(pm1AfterAttempt.payment_status).toBe('VOIDED');
  });

  test('ORDREF_001: refresh_payment blocked in PROGRAM_FROZEN (ERR_PROGRAM_FROZEN) and order/payment unchanged', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    await runOps(program.program_id, opsCtx);
    const oHold = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHold.order_status).toBe('ON_HOLD');
    expect(oHold.payment_id).toBeTruthy();
    const pOld = oHold.payment_id as string;

    const pmOld = await getPayment(program.program_id, pOld, ops);
    expect(pmOld.payment_status).toBe('VOIDED');

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const refreshRes = await refreshPayment(program.program_id, o1.order_id, c1Ctx);
    expectError(refreshRes, 400, 'ERR_PROGRAM_FROZEN');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('ON_HOLD');
    expect(oAfter.payment_id).toBe(pOld);

    const pmAfter = await getPayment(program.program_id, pOld, ops);
    expect(pmAfter.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });
});
