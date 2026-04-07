import { getRequest } from '../../../test-helpers/api-client';
import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  acknowledgeAlert,
  activateDevice,
  approveClaim,
  cancelOrder,
  closeQualityCampaign,
  closeProgram,
  createBuildLot,
  createClaim,
  createCustomer,
  createOrder,
  createProgram,
  createQualityCampaign,
  createSession,
  createAdjustment,
  disputePayment,
  freezeProgram,
  getAlert,
  getQualityCampaign,
  getAdjustment,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  listAlerts,
  lockCustomer,
  markDelivered,
  remediateDevice,
  resolveQualityCampaign,
  resolveAlert,
  runOps,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  unfreezeProgram,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 1: Program Lifecycle & Ops Runs (v1)', () => {
  async function createOpsCtx(program_id: string) {
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program_id, ops);
    return { ops, opsCtx: { ...ops, session_id: opsSession.session_id } };
  }

  async function createSupportCtx(program_id: string) {
    const sup = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supSession = await createSession(program_id, sup);
    return { sup, supCtx: { ...sup, session_id: supSession.session_id } };
  }

  async function createCustomerCtx(program_id: string, customer_id: string) {
    const cActor = { actor_id: customer_id, actor_type: 'Customer' as const };
    const cSession = await createSession(program_id, cActor);
    return { cActor, cCtx: { ...cActor, session_id: cSession.session_id } };
  }

  async function createClosedProgramAtOps7Avail3() {
    const program = await createProgram();
    const { ops, opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, `BL-${uniqueId('bl')}`, 8);
    const beforeOps = await getProgram(program.program_id, ops);
    expect(beforeOps.available_to_commit_units).toBe(3);

    for (let i = 0; i < 7; i++) await runOps(program.program_id, opsCtx);
    const at7 = await getProgram(program.program_id, ops);
    expect(at7.ops_run_index).toBe(7);
    expect(at7.available_to_commit_units).toBe(3);

    const closeRes = await closeProgram(program.program_id, opsCtx);
    expectSuccess(closeRes, 200);
    const closed = await getProgram(program.program_id, ops);
    expect(closed.program_posture).toBe('PROGRAM_CLOSED');
    expect(closed.ops_run_index).toBe(7);
    expect(closed.available_to_commit_units).toBe(3);

    return { program, ops, opsCtx };
  }

  test('PROG_001: run_ops increments ops_run_index by 1', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const res = await runOps(program.program_id, opsCtx);

    expect(res.ops_run_index).toBe(1);
    expect(res.program_posture).toBe('PROGRAM_ACTIVE');
    expect(res.available_to_commit_units).toBe(0);
  });

  test('PROG_002: freeze sets posture to PROGRAM_FROZEN without incrementing ops_run_index', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await runOps(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);
    const before = await getProgram(program.program_id, ops);
    expect(before.ops_run_index).toBe(3);
    const availableBefore = before.available_to_commit_units;

    const frozen = await freezeProgram(program.program_id, opsCtx, 'ops containment');
    expect(frozen.program_posture).toBe('PROGRAM_FROZEN');
    expect(frozen.ops_run_index).toBe(3);
    expect(frozen.available_to_commit_units).toBe(availableBefore);
  });

  test('PROG_003: unfreeze fails without a cool-off ops run', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    for (let i = 0; i < 5; i++) await runOps(program.program_id, opsCtx);
    await freezeProgram(program.program_id, opsCtx);

    const res = await unfreezeProgram(program.program_id, opsCtx);
    expectError(res, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');
    expect(p.ops_run_index).toBe(5);
  });

  test('PROG_004: unfreeze succeeds after cool-off ops run when no open alerts/campaigns', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const beforeFreeze = await getProgram(program.program_id, ops);
    const availableBefore = beforeFreeze.available_to_commit_units;

    for (let i = 0; i < 5; i++) await runOps(program.program_id, opsCtx);
    await freezeProgram(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    const res = await unfreezeProgram(program.program_id, opsCtx);
    expectSuccess(res, 200);
    expect(res.body.program_posture).toBe('PROGRAM_ACTIVE');
    expect(res.body.ops_run_index).toBe(6);
    expect(res.body.available_to_commit_units).toBe(availableBefore);
  });

  test('PROG_005: run_ops in frozen posture applies payment staleness (AUTHORIZED→VOIDED, SUBMITTED→ON_HOLD)', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, `BL-${uniqueId('tag')}`, 6);
    const c1 = await createCustomer(program.program_id, opsCtx, { display_name: `C-${uniqueId('cust')}` });
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const submitRes = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectSuccess(submitRes, 200);

    const o1Submitted = await getOrder(program.program_id, o1.order_id, c1Actor);
    expect(o1Submitted.order_status).toBe('SUBMITTED');
    expect(o1Submitted.payment_id).not.toBeNull();

    const pBefore = await getProgram(program.program_id, ops);

    await freezeProgram(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    const o1Held = await getOrder(program.program_id, o1.order_id, c1Actor);
    expect(o1Held.order_status).toBe('ON_HOLD');

    const payment = await getPayment(program.program_id, o1Submitted.payment_id as string, ops);
    expect(payment.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('PROG_006: close fails when program is PROGRAM_GUARDED', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const c1 = await createCustomer(program.program_id, opsCtx);
    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'manual lock');

    const guarded = await getProgram(program.program_id, ops);
    expect(guarded.program_posture).toBe('PROGRAM_GUARDED');

    const res = await closeProgram(program.program_id, opsCtx);
    expectError(res, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const after = await getProgram(program.program_id, ops);
    expect(after.program_posture).toBe('PROGRAM_GUARDED');
    expect(after.ops_run_index).toBe(0);
  });

  test('PROG_007: close fails when any order is DELIVERED', async () => {
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

    const res = await closeProgram(program.program_id, opsCtx);
    expectError(res, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('DELIVERED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('PROG_008: close fails when a return is APPROVED', async () => {
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

    const retReq = await getRequest()
      .post(`/programs/${program.program_id}/orders/${o1.order_id}/returns`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Actor_Type: c1Actor.actor_type, X_Session_Id: c1Session.session_id })
      .send({ resolution_preference: 'REFUND' });
    expectSuccess(retReq, 201);
    const return_id = retReq.body.return_id as string;

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);

    const approveRes = await getRequest()
      .post(`/programs/${program.program_id}/returns/${return_id}/approve`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({});
    expectSuccess(approveRes, 200);
    expect(approveRes.body.return_status).toBe('APPROVED');

    const closeRes = await closeProgram(program.program_id, opsCtx);
    expectError(closeRes, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const retGet = await getRequest()
      .get(`/programs/${program.program_id}/returns/${return_id}`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type });
    expectSuccess(retGet, 200);
    expect(retGet.body.return_status).toBe('APPROVED');
  });

  test('CLOSED_001: POST /programs/{program_id}/run_ops in PROGRAM_CLOSED returns ERR_PROGRAM_CLOSED and preserves invariants', async () => {
    const { program, ops, opsCtx } = await createClosedProgramAtOps7Avail3();

    const res = await getRequest()
      .post(`/programs/${program.program_id}/run_ops`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsCtx.session_id })
      .send({});
    expectError(res, 400, 'ERR_PROGRAM_CLOSED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_CLOSED');
    expect(pAfter.ops_run_index).toBe(7);
    expect(pAfter.available_to_commit_units).toBe(3);
  });

  test('CLOSED_002: re-canceling a CANCELED order returns ERR_INVALID_STATE_TRANSITION even when PROGRAM_CLOSED; invariants preserved', async () => {
    const program = await createProgram({ unit_price_cents: 59900, care_plan_price_cents: 0 });
    const { ops, opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, `BL-${uniqueId('bl')}`, 8);
    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(3);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { cActor: c1Actor, cCtx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    expect(submitted.paid_by_card_cents).toBe(59900);
    expect(submitted.paid_by_credit_cents).toBe(0);
    expect(submitted.payment_id).toBeTruthy();
    expect(submitted.device_id).toBeNull();
    const pmId = submitted.payment_id as string;

    const cancel0 = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'first cancel');
    expectSuccess(cancel0, 200);
    const canceled = await getOrder(program.program_id, o1.order_id, ops);
    expect(canceled.order_status).toBe('CANCELED');
    expect(canceled.payment_id).toBe(pmId);
    expect(canceled.device_id).toBeNull();

    const pmVoided = await getPayment(program.program_id, pmId, ops);
    expect(pmVoided.payment_status).toBe('VOIDED');
    expect(pmVoided.amount_cents).toBe(59900);

    for (let i = 0; i < 7; i++) await runOps(program.program_id, opsCtx);
    expectSuccess(await closeProgram(program.program_id, opsCtx), 200);

    const cancelAgain = await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'retry');
    expectError(cancelAgain, 400, 'ERR_INVALID_STATE_TRANSITION');

    const oAfter = await getOrder(program.program_id, o1.order_id, c1Actor);
    expect(oAfter.order_status).toBe('CANCELED');
    expect(oAfter.payment_id).toBe(pmId);
    expect(oAfter.device_id).toBeNull();

    const pmAfter = await getPayment(program.program_id, pmId, ops);
    expect(pmAfter.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_CLOSED');
    expect(pAfter.ops_run_index).toBe(7);
    expect(pAfter.available_to_commit_units).toBe(3);
  });

  test('CLOSED_003: disputing a VOIDED payment returns ERR_PAYMENT_NOT_DISPUTABLE even when PROGRAM_CLOSED; no alert created', async () => {
    const program = await createProgram({ unit_price_cents: 59900, care_plan_price_cents: 0 });
    const { ops, opsCtx } = await createOpsCtx(program.program_id);
    const { supCtx } = await createSupportCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, `BL-${uniqueId('bl')}`, 8);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { cCtx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 0 });
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pmId = submitted.payment_id as string;
    expect(pmId).toBeTruthy();
    expectSuccess(await cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cancel'), 200);
    const pmVoided = await getPayment(program.program_id, pmId, ops);
    expect(pmVoided.payment_status).toBe('VOIDED');

    const noDisputeBefore = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmId });
    expect(noDisputeBefore.alerts.length).toBe(0);

    for (let i = 0; i < 7; i++) await runOps(program.program_id, opsCtx);
    expectSuccess(await closeProgram(program.program_id, opsCtx), 200);

    const disputeRes = await disputePayment(program.program_id, pmId, supCtx);
    expectError(disputeRes, 400, 'ERR_PAYMENT_NOT_DISPUTABLE');

    const pmAfter = await getPayment(program.program_id, pmId, ops);
    expect(pmAfter.payment_status).toBe('VOIDED');

    const noDisputeAfter = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmId });
    expect(noDisputeAfter.alerts.length).toBe(0);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_CLOSED');
    expect(pAfter.ops_run_index).toBe(7);
  });

  test('UNFRZ_001: unfreeze fails when recall is closed and alerts resolved but no cool-off ops run since entering PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { ops, opsCtx } = await createOpsCtx(program.program_id);

    for (let i = 0; i < 5; i++) await runOps(program.program_id, opsCtx);
    const at5 = await getProgram(program.program_id, ops);
    expect(at5.ops_run_index).toBe(5);
    expect(at5.program_posture).toBe('PROGRAM_ACTIVE');

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);
    const qcId = qcRes.body.quality_campaign_id as string;
    expect(qcId).toBeTruthy();

    const frozen = await getProgram(program.program_id, ops);
    expect(frozen.program_posture).toBe('PROGRAM_FROZEN');
    expect(frozen.ops_run_index).toBe(5);

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);
    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('CLOSED');

    const recallAlerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN', quality_campaign_id: qcId });
    expect(recallAlerts.alerts.length).toBe(1);
    const recallAlertId = recallAlerts.alerts[0].alert_id;
    expectSuccess(await resolveAlert(program.program_id, recallAlertId, opsCtx), 200);
    const aAfter = await getAlert(program.program_id, recallAlertId, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const unfreezeRes = await unfreezeProgram(program.program_id, opsCtx);
    expectError(unfreezeRes, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.ops_run_index).toBe(5);
    expect((await getQualityCampaign(program.program_id, qcId, ops)).campaign_status).toBe('CLOSED');
  });

  test('UNFRZ_002: recall freeze + cool-off ops run + close recall + resolve alert allows unfreeze back to PROGRAM_ACTIVE', async () => {
    const program = await createProgram();
    const { ops, opsCtx } = await createOpsCtx(program.program_id);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');
    const N = p0.ops_run_index;

    const openBefore = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(openBefore.alerts.length).toBe(0);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);
    const qcId = qcRes.body.quality_campaign_id as string;

    const after1 = await getProgram(program.program_id, ops);
    expect(after1.program_posture).toBe('PROGRAM_FROZEN');
    expect(after1.ops_run_index).toBe(N);

    const after2 = await runOps(program.program_id, opsCtx);
    expect(after2.program_posture).toBe('PROGRAM_FROZEN');
    expect(after2.ops_run_index).toBe(N + 1);

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);
    const qcClosed = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcClosed.campaign_status).toBe('CLOSED');

    const recallAlerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN', quality_campaign_id: qcId });
    expect(recallAlerts.alerts.length).toBe(1);
    const recallAlertId = recallAlerts.alerts[0].alert_id;
    expectSuccess(await resolveAlert(program.program_id, recallAlertId, opsCtx), 200);
    const aAfter = await getAlert(program.program_id, recallAlertId, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const unfreezeRes = await unfreezeProgram(program.program_id, opsCtx);
    expectSuccess(unfreezeRes, 200);
    expect(unfreezeRes.body.program_posture).toBe('PROGRAM_ACTIVE');
    expect(unfreezeRes.body.ops_run_index).toBe(N + 1);

    const pFinal = await getProgram(program.program_id, ops);
    expect(pFinal.program_posture).toBe('PROGRAM_ACTIVE');
    expect(pFinal.ops_run_index).toBe(N + 1);
  });

  test('PROG_009: close fails when a claim is INBOUND', async () => {
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

    const o1Delivered = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Delivered.device_id).not.toBeNull();

    const activateRes = await activateDevice(program.program_id, o1Delivered.device_id as string, c1Ctx);
    expectSuccess(activateRes, 200);

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const claimCreateRes = await createClaim(program.program_id, o1Delivered.device_id as string, supportCtx, 'WARRANTY');
    expectSuccess(claimCreateRes, 201);
    const claim_id = claimCreateRes.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claim_id, supportCtx, 'REPLACEMENT'), 200);

    const markInboundRes = await getRequest()
      .post(`/programs/${program.program_id}/claims/${claim_id}/mark_inbound`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({});
    expectSuccess(markInboundRes, 200);
    expect(markInboundRes.body.claim_status).toBe('INBOUND');

    const closeRes = await closeProgram(program.program_id, opsCtx);
    expectError(closeRes, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const cl = await getClaim(program.program_id, claim_id, ops);
    expect(cl.claim_status).toBe('INBOUND');
  });

  test('PROG_010: close succeeds when program is eligible', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const res = await closeProgram(program.program_id, opsCtx);
    expectSuccess(res, 200);
    expect(res.body.program_posture).toBe('PROGRAM_CLOSED');
    expect(res.body.ops_run_index).toBe(0);
    expect(res.body.available_to_commit_units).toBe(0);
  });

  test('PROG_011: unfreeze fails when any alert is OPEN', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    for (let i = 0; i < 5; i++) await runOps(program.program_id, opsCtx);
    await freezeProgram(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    const c1 = await createCustomer(program.program_id, opsCtx);
    await lockCustomer(program.program_id, c1.customer_id, opsCtx);

    const openAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(openAlerts.alerts.length).toBeGreaterThan(0);
    const alertId = openAlerts.alerts[0].alert_id;

    const res = await unfreezeProgram(program.program_id, opsCtx);
    expectError(res, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');
    expect(p.ops_run_index).toBe(6);

    const alertAfter = await getAlert(program.program_id, alertId, ops);
    expect(alertAfter.alert_status).toBe('OPEN');
  });

  test('PROG_012: unfreeze fails while a RECALL campaign is not CLOSED', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', `PX-${uniqueId('px')}`);
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const resolveRes = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(resolveRes, 200);
    expect(resolveRes.body.campaign_status).toBe('RESOLVED');

    await runOps(program.program_id, opsCtx);

    const openAlertsNow = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    for (const a of openAlertsNow.alerts) {
      expectSuccess(await acknowledgeAlert(program.program_id, a.alert_id, opsCtx), 200);
    }

    const noOpenAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(noOpenAlerts.alerts.length).toBe(0);

    const res = await unfreezeProgram(program.program_id, opsCtx);
    expectError(res, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');

    const qcGet = await getRequest()
      .get(`/programs/${program.program_id}/quality_campaigns/${qcId}`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type });
    expectSuccess(qcGet, 200);
    expect(qcGet.body.campaign_status).toBe('RESOLVED');
  });

  test('PROG_013: run_ops freezes program when 5+ customers are LOCKED at run close', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const baseProg = await getProgram(program.program_id, ops);
    const baseOpsRunIndex = baseProg.ops_run_index;
    expect(baseProg.program_posture).not.toBe('PROGRAM_FROZEN');

    const customers = [] as Array<{ customer_id: string }>;
    for (let i = 0; i < 5; i++) {
      const c = await createCustomer(program.program_id, opsCtx, { display_name: `C${i}-${uniqueId('cust')}` });
      customers.push(c);
      await lockCustomer(program.program_id, c.customer_id, opsCtx, 'lock for threshold');
    }

    const beforeRun = await getProgram(program.program_id, ops);
    expect(beforeRun.program_posture).toBe('PROGRAM_GUARDED');

    const p = await runOps(program.program_id, opsCtx);
    expect(p.ops_run_index).toBe(baseOpsRunIndex + 1);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');

    for (const c of customers) {
      const got = await getCustomer(program.program_id, c.customer_id, ops);
      expect(got.customer_status).toBe('LOCKED');
    }
  });

  test('PROG_014: close fails when any adjustment is PENDING', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const c1 = await createCustomer(program.program_id, opsCtx);
    const adjRes = await createAdjustment(program.program_id, c1.customer_id, supportCtx, 'WRITE_OFF', 1000);
    expectSuccess(adjRes, 201);
    expect(adjRes.body.adjustment_status).toBe('PENDING');
    const adjustmentId = adjRes.body.adjustment_id as string;

    const closeRes = await closeProgram(program.program_id, opsCtx);
    expectError(closeRes, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');

    const adjAfter = await getAdjustment(program.program_id, adjustmentId, ops);
    expect(adjAfter.adjustment_status).toBe('PENDING');
  });

  test('PROG_015: close fails when any quality campaign is not CLOSED', async () => {
    const program = await createProgram();
    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', `ZZ-${uniqueId('p')}`);
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const qcResolve = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(qcResolve, 200);
    expect(qcResolve.body.campaign_status).toBe('RESOLVED');

    const closeRes = await closeProgram(program.program_id, opsCtx);
    expectError(closeRes, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');

    const qcGet = await getRequest()
      .get(`/programs/${program.program_id}/quality_campaigns/${qcId}`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type });
    expectSuccess(qcGet, 200);
    expect(qcGet.body.campaign_status).toBe('RESOLVED');
  });

  test('PROG_017: OPEN alert across two ops runs freezes; cool-off run required to unfreeze', async () => {
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
    const pmId = delivered.payment_id as string;
    expect(pmId).toBeTruthy();

    const disputeRes = await getRequest()
      .post(`/programs/${program.program_id}/payments/${pmId}/dispute`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({});
    expectSuccess(disputeRes, 200);

    const aList = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmId });
    expect(aList.alerts.length).toBe(1);
    const alertId = aList.alerts[0].alert_id;

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_GUARDED');
    const base = p0.ops_run_index;

    await runOps(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.ops_run_index).toBe(base + 2);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const alertStillOpen = await getAlert(program.program_id, alertId, ops);
    expect(alertStillOpen.alert_status).toBe('OPEN');

    const resolveDisputeRes = await getRequest()
      .post(`/programs/${program.program_id}/payments/${pmId}/resolve_dispute`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({ outcome: 'REFUNDED' });
    expectSuccess(resolveDisputeRes, 200);

    expectSuccess(await resolveAlert(program.program_id, alertId, opsCtx), 200);

    const pm = await getPayment(program.program_id, pmId, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const alertResolved = await getAlert(program.program_id, alertId, ops);
    expect(alertResolved.alert_status).toBe('RESOLVED');

    const unfreezeTooSoon = await unfreezeProgram(program.program_id, opsCtx);
    expectError(unfreezeTooSoon, 400, 'ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE');

    await runOps(program.program_id, opsCtx);
    const unfreezeOk = await unfreezeProgram(program.program_id, opsCtx);
    expectSuccess(unfreezeOk, 200);

    const pActive = await getProgram(program.program_id, ops);
    expect(pActive.ops_run_index).toBe(base + 3);
    expect(pActive.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('PROG_018: second ops run after advance replacement ships locks customer, opens AFTERCARE_OVERDUE, and freezes at 5 locked', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);
    const supportCtx = { ...support, session_id: supportSession.session_id };

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 10);

    const c5 = await createCustomer(program.program_id, opsCtx);
    const c5Actor = { actor_id: c5.customer_id, actor_type: 'Customer' as const };
    const c5Session = await createSession(program.program_id, c5Actor);
    const c5Ctx = { ...c5Actor, session_id: c5Session.session_id };

    const o1 = await createOrder(program.program_id, c5.customer_id, c5Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c5Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: saleLot.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: saleLot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    const origDeviceId = delivered.device_id as string;

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'B99');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const d0 = await getDevice(program.program_id, origDeviceId, ops);
    expect(d0.device_status).toBe('QUARANTINED');

    const claimCreate = await createClaim(program.program_id, origDeviceId, supportCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claimId, supportCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipAdv = await shipAdvanceReplacement(
      program.program_id,
      claimId,
      supportCtx,
      {
        replacement_build_lot_id: replacementLot.build_lot_id,
        replacement_serial_number: 'SN-ADV-PROG18',
        replacement_build_tag: replacementLot.build_tag
      }
    );
    expectSuccess(shipAdv, 200);

    expectSuccess(await remediateDevice(program.program_id, origDeviceId, opsCtx, 'field fix for test'), 200);
    const dRemediated = await getDevice(program.program_id, origDeviceId, ops);
    expect(dRemediated.device_status).not.toBe('QUARANTINED');

    const qcResolve = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(qcResolve, 200);

    const qcClose = await getRequest()
      .post(`/programs/${program.program_id}/quality_campaigns/${qcId}/close`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({});
    expectSuccess(qcClose, 200);
    expect(qcClose.body.campaign_status).toBe('CLOSED');

    const openRecallAlerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    for (const a of openRecallAlerts.alerts) {
      expectSuccess(await resolveAlert(program.program_id, a.alert_id, opsCtx), 200);
    }

    const pAfterFirstRun = await runOps(program.program_id, opsCtx);

    const unfreezeRes = await unfreezeProgram(program.program_id, opsCtx);
    expectSuccess(unfreezeRes, 200);

    const pActive = await getProgram(program.program_id, ops);
    expect(pActive.program_posture).toBe('PROGRAM_ACTIVE');
    const N = pAfterFirstRun.ops_run_index;
    expect(pActive.ops_run_index).toBe(N);

    const lockedIds: string[] = [];
    for (let i = 0; i < 4; i++) {
      const c = await createCustomer(program.program_id, opsCtx);
      lockedIds.push(c.customer_id);
      await lockCustomer(program.program_id, c.customer_id, opsCtx, 'seed locked');

      const alerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c.customer_id });
      for (const a of alerts.alerts) {
        expectSuccess(await resolveAlert(program.program_id, a.alert_id, opsCtx), 200);
      }

      const got = await getCustomer(program.program_id, c.customer_id, ops);
      expect(got.customer_status).toBe('LOCKED');
    }

    const c5Before = await getCustomer(program.program_id, c5.customer_id, ops);
    expect(c5Before.customer_status).toBe('LIMITED');
    expect(c5Before.balance_due_cents).toBe(15000);

    const beforeAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
    expect(beforeAlerts.alerts.length).toBe(0);

    const p2 = await runOps(program.program_id, opsCtx);
    expect(p2.ops_run_index).toBe(N + 1);
    expect(p2.program_posture).toBe('PROGRAM_FROZEN');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');

    const c5After = await getCustomer(program.program_id, c5.customer_id, ops);
    expect(c5After.customer_status).toBe('LOCKED');
    expect(c5After.balance_due_cents).toBe(15000);

    const overdueAlerts = await listAlerts(program.program_id, ops, { alert_type: 'AFTERCARE_OVERDUE', alert_status: 'OPEN', claim_id: claimId });
    expect(overdueAlerts.alerts.length).toBe(1);

    for (const id of lockedIds) {
      const got = await getCustomer(program.program_id, id, ops);
      expect(got.customer_status).toBe('LOCKED');
    }
  });

  test('OPS_006: run_ops expires ON_HOLD order in frozen, releases commitment and unwinds credit', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, `TAG-${uniqueId('t')}`, 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const trRes = await getRequest()
      .post(`/programs/${program.program_id}/customers/${c1.customer_id}/tradeins`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Actor_Type: c1Actor.actor_type, X_Session_Id: c1Session.session_id })
      .send({ quoted_credit_cents: 20000 });
    expectSuccess(trRes, 201);
    const tradein_id = trRes.body.tradein_id as string;

    const trSubmit = await getRequest()
      .post(`/programs/${program.program_id}/tradeins/${tradein_id}/submit`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Actor_Type: c1Actor.actor_type, X_Session_Id: c1Session.session_id })
      .send({});
    expectSuccess(trSubmit, 200);

    const cCredited = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cCredited.credit_balance_cents).toBe(20000);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
    const submit = await submitOrder(program.program_id, o1.order_id, c1Ctx, false);
    expectSuccess(submit, 200);

    await runOps(program.program_id, opsCtx);

    const oHeld = await getOrder(program.program_id, o1.order_id, ops);
    expect(oHeld.order_status).toBe('ON_HOLD');
    expect(oHeld.paid_by_credit_cents).toBe(20000);
    expect(oHeld.payment_id).toBeTruthy();

    const pmOld = await getPayment(program.program_id, oHeld.payment_id as string, ops);
    expect(pmOld.payment_status).toBe('VOIDED');

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    const p1 = await runOps(program.program_id, opsCtx);

    expect(p1.program_posture).toBe('PROGRAM_FROZEN');
    expect(p1.available_to_commit_units).toBe(1);

    const oExpired = await getOrder(program.program_id, o1.order_id, ops);
    expect(oExpired.order_status).toBe('EXPIRED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.credit_balance_cents).toBe(20000);
    expect(cAfter.balance_due_cents).toBe(0);

    const pmStill = await getPayment(program.program_id, oHeld.payment_id as string, ops);
    expect(pmStill.payment_status).toBe('VOIDED');
  });

  test('OPS_007: returns receive RESTOCK is allowed in frozen and increases available_to_commit_units', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const support = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
    const supportSession = await createSession(program.program_id, support);

    const lot = await createBuildLot(program.program_id, opsCtx, `TAG-${uniqueId('t')}`, 6);
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
        build_tag: lot.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);

    const retCreate = await getRequest()
      .post(`/programs/${program.program_id}/orders/${o1.order_id}/returns`)
      .set({ X_Actor_Id: c1Actor.actor_id, X_Actor_Type: c1Actor.actor_type, X_Session_Id: c1Session.session_id })
      .send({ resolution_preference: 'REFUND' });
    expectSuccess(retCreate, 201);
    const return_id = retCreate.body.return_id as string;

    const retApprove = await getRequest()
      .post(`/programs/${program.program_id}/returns/${return_id}/approve`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({});
    expectSuccess(retApprove, 200);

    const retInbound = await getRequest()
      .post(`/programs/${program.program_id}/returns/${return_id}/mark_inbound`)
      .set({ X_Actor_Id: support.actor_id, X_Actor_Type: support.actor_type, X_Session_Id: supportSession.session_id })
      .send({});
    expectSuccess(retInbound, 200);
    expect(retInbound.body.return_status).toBe('INBOUND');

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    const frozen = await getProgram(program.program_id, ops);
    expect(frozen.program_posture).toBe('PROGRAM_FROZEN');

    const receive = await getRequest()
      .post(`/programs/${program.program_id}/returns/${return_id}/receive`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type, X_Session_Id: opsSession.session_id })
      .send({ inspection_outcome: 'RESTOCK' });
    expectSuccess(receive, 200);

    const retGet = await getRequest()
      .get(`/programs/${program.program_id}/returns/${return_id}`)
      .set({ X_Actor_Id: ops.actor_id, X_Actor_Type: ops.actor_type });
    expectSuccess(retGet, 200);
    expect(retGet.body.return_status).toBe('RECEIVED');
    expect(retGet.body.inspection_outcome).toBe('RESTOCK');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_FROZEN');
    expect(p1.available_to_commit_units).toBe(1);

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('DELIVERED');
  });
});
