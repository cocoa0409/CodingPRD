import { getRequest } from '../../../test-helpers/api-client';
import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  approveClaim,
  createBuildLot,
  createClaim,
  createCustomer,
  createOrder,
  createProgram,
  createQualityCampaign,
  createSession,
  disputePayment,
  endSession,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  listAlerts,
  markDelivered,
  runOps,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 2: Context Headers, Sessions & Idempotency (v1)', () => {
  test('AUTH_001: missing X_Actor_Type returns ERR_MISSING_OR_INVALID_CONTEXT_HEADER', async () => {
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
    const before = await getProgram(program.program_id, ops);

    const res = await getRequest()
      .post(`/programs/${program.program_id}/orders/${o1.order_id}/submit`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Session_Id: c1Session.session_id })
      .send({ include_care_plan: false });

    expectError(res, 400, 'ERR_MISSING_OR_INVALID_CONTEXT_HEADER');

    const afterOrder = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterOrder.order_status).toBe('DRAFT');
    expect(afterOrder.payment_id).toBeNull();

    const afterProg = await getProgram(program.program_id, ops);
    expect(afterProg.ops_run_index).toBe(before.ops_run_index);
  });

  test('AUTH_002: Customer submit missing X_Session_Id returns ERR_MISSING_OR_INVALID_CONTEXT_HEADER', async () => {
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

    const progBefore = await getProgram(program.program_id, ops);

    const res = await getRequest()
      .post(`/programs/${program.program_id}/orders/${o1.order_id}/submit`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Actor_Type: c1Actor.actor_type })
      .send({ include_care_plan: false });

    expectError(res, 400, 'ERR_MISSING_OR_INVALID_CONTEXT_HEADER');

    const after = await getOrder(program.program_id, o1.order_id, ops);
    expect(after.order_status).toBe('DRAFT');
    expect(after.payment_id).toBeNull();

    const progAfter = await getProgram(program.program_id, ops);
    expect(progAfter.available_to_commit_units).toBe(progBefore.available_to_commit_units);
  });

  test('AUTH_003: provided but ENDED session returns ERR_SESSION_NOT_ACTIVE', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const c1 = await createCustomer(program.program_id, opsCtx);
    const before = await getCustomer(program.program_id, c1.customer_id, ops);

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const ended = await endSession(program.program_id, supportSession.session_id, { ...support, session_id: supportSession.session_id });
    expect(ended.session_status).toBe('ENDED');

    const res = await getRequest()
      .post(`/programs/${program.program_id}/customers/${c1.customer_id}/adjustments`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: ended.session_id })
      .send({ adjustment_type: 'WRITE_OFF', amount_cents: 1000 });

    expectError(res, 400, 'ERR_SESSION_NOT_ACTIVE');

    expect(res.body.adjustment_id).toBeUndefined();

    const after = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(after.balance_due_cents).toBe(before.balance_due_cents);
    expect(after.credit_balance_cents).toBe(before.credit_balance_cents);
  });

  test('AUTH_004: Ops-only endpoint called by Support returns ERR_FORBIDDEN_FOR_ACTOR', async () => {
    const program = await createProgram();

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);

    const before = await getProgram(program.program_id, support);

    const res = await getRequest()
      .post(`/programs/${program.program_id}/build_lots`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({ build_tag: 'A17B', units: 10 });

    expectError(res, 403, 'ERR_FORBIDDEN_FOR_ACTOR');

    expect(res.body.build_lot_id).toBeUndefined();

    const after = await getProgram(program.program_id, support);
    expect(after.available_to_commit_units).toBe(before.available_to_commit_units);
  });

  test('AUTH_005: idempotent submit returns identical response and applies side effects once', async () => {
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

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(1);

    const c1Before = await getCustomer(program.program_id, c1.customer_id, ops);

    const r1 = await submitOrder(program.program_id, o1.order_id, c1Ctx, false, 'K_SUBMIT_1');
    expectSuccess(r1, 200);
    const r2 = await submitOrder(program.program_id, o1.order_id, c1Ctx, false, 'K_SUBMIT_1');
    expectSuccess(r2, 200);

    expect(r2.body).toEqual(r1.body);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('SUBMITTED');
    expect(o1After.payment_id).toBeTruthy();

    const payment = await getPayment(program.program_id, o1After.payment_id as string, ops);
    expect(payment.payment_status).toBe('AUTHORIZED');

    const c1After = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(c1After.credit_balance_cents).toBe(c1Before.credit_balance_cents);
    expect(c1After.balance_due_cents).toBe(c1Before.balance_due_cents);
  });

  test('AUTH_006: reusing Idempotency_Key with different payload returns ERR_IDEMPOTENCY_CONFLICT', async () => {
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

    const r1 = await submitOrder(program.program_id, o1.order_id, c1Ctx, true, 'K_SUBMIT_2');
    expectSuccess(r1, 200);
    expect(r1.body.care_plan_id).toBeTruthy();

    const r2 = await submitOrder(program.program_id, o1.order_id, c1Ctx, false, 'K_SUBMIT_2');
    expectError(r2, 400, 'ERR_IDEMPOTENCY_CONFLICT');

    const o = await getOrder(program.program_id, o1.order_id, ops);
    expect(o.order_status).toBe('SUBMITTED');
    expect(o.care_plan_id).toBeTruthy();

    const p = await getProgram(program.program_id, ops);
    expect(p.available_to_commit_units).toBe(0);
  });

  test('AUTH_007: idempotency keys are scoped per program', async () => {
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };

    const p1 = await createProgram({ display_name: `P1-${uniqueId('p')}` });
    const p2 = await createProgram({ display_name: `P2-${uniqueId('p')}` });

    const opsSession1 = await createSession(p1.program_id, ops);
    const opsCtx1 = { ...ops, session_id: opsSession1.session_id };
    const opsSession2 = await createSession(p2.program_id, ops);
    const opsCtx2 = { ...ops, session_id: opsSession2.session_id };

    await createBuildLot(p1.program_id, opsCtx1, `TAG-${uniqueId('t')}`, 6);
    await createBuildLot(p2.program_id, opsCtx2, `TAG-${uniqueId('t')}`, 6);

    const c1 = await createCustomer(p1.program_id, opsCtx1);
    const c2 = await createCustomer(p2.program_id, opsCtx2);

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c2Actor = { actor_id: c2.customer_id, actor_type: 'Customer' as const };

    const c1Session = await createSession(p1.program_id, c1Actor);
    const c2Session = await createSession(p2.program_id, c2Actor);

    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };
    const c2Ctx = { ...c2Actor, session_id: c2Session.session_id };

    const o1 = await createOrder(p1.program_id, c1.customer_id, c1Ctx);
    const o2 = await createOrder(p2.program_id, c2.customer_id, c2Ctx);

    const r1 = await submitOrder(p1.program_id, o1.order_id, c1Ctx, false, 'K_SHARED');
    expectSuccess(r1, 200);
    const r2 = await submitOrder(p2.program_id, o2.order_id, c2Ctx, false, 'K_SHARED');
    expectSuccess(r2, 200);

    const p1After = await getProgram(p1.program_id, ops);
    const p2After = await getProgram(p2.program_id, ops);
    expect(p1After.available_to_commit_units).toBe(0);
    expect(p2After.available_to_commit_units).toBe(0);

    const o1After = await getOrder(p1.program_id, o1.order_id, ops);
    const o2After = await getOrder(p2.program_id, o2.order_id, ops);
    expect(o1After.order_status).toBe('SUBMITTED');
    expect(o1After.payment_id).toBeTruthy();
    expect(o2After.order_status).toBe('SUBMITTED');
    expect(o2After.payment_id).toBeTruthy();
  });

  test('AUTH_008: missing context headers win before idempotency conflict', async () => {
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
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, true, 'K_HDR_PRECEDENCE'), 200);

    const progBefore = await getProgram(program.program_id, ops);
    const o1Before = await getOrder(program.program_id, o1.order_id, ops);

    const res = await getRequest()
      .post(`/programs/${program.program_id}/orders/${o1.order_id}/submit`)
      .set({

        X_Actor_Type: 'Customer',
        X_Session_Id: c1Session.session_id,
        Idempotency_Key: 'K_HDR_PRECEDENCE'
      })
      .send({ include_care_plan: false });

    expectError(res, 400, 'ERR_MISSING_OR_INVALID_CONTEXT_HEADER');

    const progAfter = await getProgram(program.program_id, ops);
    expect(progAfter.available_to_commit_units).toBe(progBefore.available_to_commit_units);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe(o1Before.order_status);
    expect(o1After.payment_id).toBe(o1Before.payment_id);
  });

  test('IDEMP_009: idempotent run_ops applies checkpoint once', async () => {
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
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const o1Sub = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = o1Sub.payment_id as string;

    const pBefore = await getProgram(program.program_id, ops);
    const base = pBefore.ops_run_index;

    const r1 = await runOps(program.program_id, opsCtx, 'K_OPS_1');
    expect(r1.ops_run_index).toBe(base + 1);

    const r2 = await runOps(program.program_id, opsCtx, 'K_OPS_1');
    expect(r2).toEqual(r1);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.ops_run_index).toBe(base + 1);

    const o1Held = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Held.order_status).toBe('ON_HOLD');

    const pm = await getPayment(program.program_id, pmId, ops);
    expect(pm.payment_status).toBe('VOIDED');
  });

  test('IDEMP_010: idempotent ship_advance_replacement does not duplicate deposit/holds', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: saleLot.build_lot_id,
        serial_number: 'SN-ORIG-1',
        build_tag: saleLot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const o1Delivered = await getOrder(program.program_id, o1.order_id, ops);
    const origDeviceId = o1Delivered.device_id as string;

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'B99');
    expectSuccess(qcCreate, 201);

    const origDevice = await getDevice(program.program_id, origDeviceId, ops);
    expect(origDevice.device_status).toBe('QUARANTINED');

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const claimCreateRes = await createClaim(program.program_id, origDeviceId, supportCtx, 'RECALL');
    expectSuccess(claimCreateRes, 201);
    const claimId = claimCreateRes.body.claim_id as string;

    const approveRes = await approveClaim(program.program_id, claimId, supportCtx, 'ADVANCE_REPLACEMENT');
    expectSuccess(approveRes, 200);

    const r1 = await shipAdvanceReplacement(
      program.program_id,
      claimId,
      supportCtx,
      { replacement_build_lot_id: replacementLot.build_lot_id, replacement_serial_number: 'SN-ADV-1', replacement_build_tag: replacementLot.build_tag },
      'K_ADV_1'
    );
    expectSuccess(r1, 200);

    const r2 = await shipAdvanceReplacement(
      program.program_id,
      claimId,
      supportCtx,
      { replacement_build_lot_id: replacementLot.build_lot_id, replacement_serial_number: 'SN-ADV-1', replacement_build_tag: replacementLot.build_tag },
      'K_ADV_1'
    );
    expectSuccess(r2, 200);
    expect(r2.body).toEqual(r1.body);

    const alerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBeGreaterThanOrEqual(1);

    const c1After = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(c1After.balance_due_cents).toBe(15000);
    expect(c1After.customer_status).toBe('LIMITED');

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('ON_HOLD');

    const claim = await getRequest()
      .get(`/programs/${program.program_id}/claims/${claimId}`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type });
    expectSuccess(claim, 200);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('DELIVERED');
    expect(o1After.device_id).toBe(claim.body.replacement_device_id);
  });
});
