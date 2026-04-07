import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  acknowledgeAlert,
  activateDevice,
  appraiseTradeIn,
  approveClaim,
  cancelOrder,
  closeQualityCampaign,
  completeClaim,
  createBuildLot,
  createClaim,
  createCustomer,
  createOrder,
  createProgram,
  createQualityCampaign,
  createSession,
  createTradeIn,
  disputePayment,
  getAlert,
  getBuildLot,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getQualityCampaign,
  listAlerts,
  markDelivered,
  markInboundClaim,
  markInboundTradeIn,
  receiveClaim,
  remediateDevice,
  resolveAlert,
  resolveDispute,
  resolveQualityCampaign,
  reverseTradeInCredit,
  runOps,
  shipAdvanceReplacement,
  shipOrder,
  settleBalanceDue,
  submitOrder,
  submitTradeIn,
  unfreezeProgram,
  unlockCustomer,
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

  expectSuccess(
    await shipOrder(args.program_id, order.order_id, args.opsCtx, {
      build_lot_id: args.build_lot_id,
      serial_number: `SN-${uniqueId('sn')}`,
      build_tag: args.build_tag
    }),
    200
  );
  expectSuccess(await markDelivered(args.program_id, order.order_id, args.opsCtx), 200);

  const delivered = await getOrder(args.program_id, order.order_id, opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.payment_id).toBeTruthy();

  const payment = await getPayment(args.program_id, delivered.payment_id as string, opsActor);
  expect(payment.payment_status).toBe('CAPTURED');
  return { order_id: delivered.order_id, payment_id: payment.payment_id };
}

async function disputeAndGetPaymentDisputedAlertId(program_id: string, payment_id: string, supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string }, opsActor: { actor_id: string; actor_type: 'Ops' }) {
  expectSuccess(await disputePayment(program_id, payment_id, supportCtx), 200);
  const alerts = await listAlerts(program_id, opsActor, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
  expect(alerts.alerts.length).toBe(1);
  return alerts.alerts[0].alert_id;
}

async function createSupplyShortfallOpen(program_id: string, opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }, customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string }) {
  const opsActor = { actor_id: opsCtx.actor_id, actor_type: 'Ops' as const };
  const lot = await createBuildLot(program_id, opsCtx, 'A17B', 6);
  const order = await createOrder(program_id, customerCtx.actor_id, customerCtx);
  expectSuccess(await submitOrder(program_id, order.order_id, customerCtx, false), 200);

  const qcRes = await createQualityCampaign(program_id, opsCtx, 'SHIP_HOLD', 'A17');
  expectSuccess(qcRes, 201);
  const qcId = qcRes.body.quality_campaign_id as string;

  let alerts = await listAlerts(program_id, opsActor, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
  if (alerts.alerts.length === 0) {
    await runOps(program_id, opsCtx);
    alerts = await listAlerts(program_id, opsActor, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
  }
  expect(alerts.alerts.length).toBe(1);
  return { alert_id: alerts.alerts[0].alert_id, lot, order_id: order.order_id, quality_campaign_id: qcId };
}

async function createActivatedDeliveredDevice(args: {
  program_id: string;
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  build_tag: string;
  units: number;
}) {
  const opsActor = { actor_id: args.opsCtx.actor_id, actor_type: 'Ops' as const };
  const lot = await createBuildLot(args.program_id, args.opsCtx, args.build_tag, args.units);
  const order = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: 0 });
  expectSuccess(await submitOrder(args.program_id, order.order_id, args.customerCtx, false), 200);
  expectSuccess(
    await shipOrder(args.program_id, order.order_id, args.opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: `SN-${uniqueId('sn')}`,
      build_tag: lot.build_tag
    }),
    200
  );
  expectSuccess(await markDelivered(args.program_id, order.order_id, args.opsCtx), 200);

  const delivered = await getOrder(args.program_id, order.order_id, opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  const deviceId = delivered.device_id as string;
  expect(deviceId).toBeTruthy();

  expectSuccess(await activateDevice(args.program_id, deviceId, args.customerCtx), 200);
  const d = await getDevice(args.program_id, deviceId, opsActor);
  expect(d.device_status).toBe('ACTIVE');

  return { order_id: delivered.order_id, device_id: deviceId, lot };
}

async function createAftercareOverdueOpen(args: { program_id: string; opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }; supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string } }) {
  const opsActor = { actor_id: args.opsCtx.actor_id, actor_type: 'Ops' as const };
  const customer = await createCustomer(args.program_id, args.opsCtx);
  const { ctx: cCtx } = await createCustomerCtx(args.program_id, customer.customer_id);

  const { device_id } = await createActivatedDeliveredDevice({
    program_id: args.program_id,
    opsCtx: args.opsCtx,
    customer_id: customer.customer_id,
    customerCtx: cCtx,
    build_tag: 'A17B',
    units: 12
  });

  const qcCreate = await createQualityCampaign(args.program_id, args.opsCtx, 'RECALL', 'A17');
  expectSuccess(qcCreate, 201);
  const qcId = qcCreate.body.quality_campaign_id as string;

  const recallAlerts = await listAlerts(args.program_id, opsActor, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN', quality_campaign_id: qcId });
  expect(recallAlerts.alerts.length).toBe(1);
  const recallAlertId = recallAlerts.alerts[0].alert_id;

  const replacementLot = await createBuildLot(args.program_id, args.opsCtx, 'RPL', 3);
  const claimCreate = await createClaim(args.program_id, device_id, args.supportCtx, 'RECALL');
  expectSuccess(claimCreate, 201);
  const claimId = claimCreate.body.claim_id as string;
  expectSuccess(await approveClaim(args.program_id, claimId, args.supportCtx, 'ADVANCE_REPLACEMENT'), 200);
  expectSuccess(
    await shipAdvanceReplacement(args.program_id, claimId, args.supportCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: `SN-ADV-${uniqueId('adv')}`,
      replacement_build_tag: replacementLot.build_tag
    }),
    200
  );

  expectSuccess(await remediateDevice(args.program_id, device_id, args.opsCtx, 'remediated for campaign closure'), 200);

  expectSuccess(await resolveQualityCampaign(args.program_id, qcId, args.opsCtx), 200);
  expectSuccess(await closeQualityCampaign(args.program_id, qcId, args.opsCtx), 200);

  expectSuccess(await resolveAlert(args.program_id, recallAlertId, args.opsCtx), 200);

  await runOps(args.program_id, args.opsCtx);
  const unfreezeRes = await unfreezeProgram(args.program_id, args.opsCtx);
  expectSuccess(unfreezeRes, 200);

  await runOps(args.program_id, args.opsCtx);

  const overdue = await listAlerts(args.program_id, opsActor, {
    alert_type: 'AFTERCARE_OVERDUE',
    alert_status: 'OPEN',
    claim_id: claimId,
    customer_id: customer.customer_id
  });
  expect(overdue.alerts.length).toBe(1);

  const cAfter = await getCustomer(args.program_id, customer.customer_id, opsActor);
  expect(cAfter.customer_status).toBe('LOCKED');
  expect(cAfter.balance_due_cents).toBeGreaterThanOrEqual(15000);

  const cl = await getClaim(args.program_id, claimId, opsActor);
  expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
  expect(cl.claim_type).toBe('RECALL');

  return { customer_id: customer.customer_id, customerCtx: cCtx, claim_id: claimId, alert_id: overdue.alerts[0].alert_id };
}

describe('Feature 14: Alerts: Operational Queue & Resolve Rules (v1)', () => {
  test('ALRTX_001: ship-hold creates shortfall alert; guarded blocks submit until alert resolved; closing campaign releases lots', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    let openSf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    if (openSf.alerts.length === 0) {
      await runOps(program.program_id, opsCtx);
      openSf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    }
    expect(openSf.alerts.length).toBe(1);
    const aSf = openSf.alerts[0].alert_id;

    const pAfterHold = await getProgram(program.program_id, ops);
    expect(pAfterHold.program_posture).toBe('PROGRAM_GUARDED');

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);

    const lotReleased = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotReleased.build_lot_status).toBe('AVAILABLE');

    const aStill = await getAlert(program.program_id, aSf, ops);
    expect(aStill.alert_status).toBe('OPEN');

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const pAfterSupply = await getProgram(program.program_id, ops);
    expect(pAfterSupply.available_to_commit_units).toBe(6);

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const submitBlocked = await submitOrder(program.program_id, o2.order_id, c1Ctx, false);
    expectError(submitBlocked, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const o2AfterFail = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2AfterFail.order_status).toBe('DRAFT');
    expect(o2AfterFail.payment_id).toBeNull();

    const pStill = await getProgram(program.program_id, ops);
    expect(pStill.available_to_commit_units).toBe(6);

    expectSuccess(await resolveAlert(program.program_id, aSf, opsCtx), 200);
    const aResolved = await getAlert(program.program_id, aSf, ops);
    expect(aResolved.alert_status).toBe('RESOLVED');

    const pActive = await getProgram(program.program_id, ops);
    expect(pActive.program_posture).toBe('PROGRAM_ACTIVE');

    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);
    const o2Submitted = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2Submitted.order_status).toBe('SUBMITTED');

    const pAfterCommit = await getProgram(program.program_id, ops);
    expect(pAfterCommit.available_to_commit_units).toBe(5);
  });

  test('ALRT_001: acknowledging OPEN alert keeps program GUARDED', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    const guarded = await getProgram(program.program_id, ops);
    expect(guarded.program_posture).toBe('PROGRAM_GUARDED');

    const ack = await acknowledgeAlert(program.program_id, a1, opsCtx);
    expectSuccess(ack, 200);
    expect(ack.body.alert_status).toBe('ACKNOWLEDGED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_002: cannot resolve CHARGEBACK_LOST while customer still has balance due', async () => {
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

    expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST'), 200);

    const cb = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', customer_id: c1.customer_id, payment_id });
    expect(cb.alerts.length).toBe(1);
    const a1 = cb.alerts[0].alert_id;

    const ack = await acknowledgeAlert(program.program_id, a1, opsCtx);
    expectSuccess(ack, 200);
    expect(ack.body.alert_status).toBe('ACKNOWLEDGED');

    const cBefore = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cBefore.balance_due_cents).toBeGreaterThan(0);

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(cBefore.balance_due_cents);

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_003: resolving CHARGEBACK_LOST after settlement + explicit unlock returns program to ACTIVE', async () => {
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

    expectSuccess(await disputePayment(program.program_id, payment_id, supCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST'), 200);

    const payDispOpen = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id });
    const payDispAck = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'ACKNOWLEDGED', payment_id });
    for (const a of [...payDispOpen.alerts, ...payDispAck.alerts]) {
      expectSuccess(await resolveAlert(program.program_id, a.alert_id, opsCtx), 200);
    }

    const cb = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', customer_id: c1.customer_id });
    expect(cb.alerts.length).toBe(1);
    const a1 = cb.alerts[0].alert_id;
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const cBefore = await getCustomer(program.program_id, c1.customer_id, ops);
    if (cBefore.balance_due_cents > 0) {
      await settleBalanceDue(program.program_id, c1.customer_id, opsCtx, cBefore.balance_due_cents);
    }
    const cSettled = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cSettled.balance_due_cents).toBe(0);

    await runOps(program.program_id, opsCtx);

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectSuccess(res, 200);
    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const pAfterResolve = await getProgram(program.program_id, ops);
    expect(pAfterResolve.program_posture).toBe('PROGRAM_ACTIVE');

    await unlockCustomer(program.program_id, c1.customer_id, opsCtx);
    const cUnlocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cUnlocked.customer_status).toBe('ACTIVE');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('ALRT_004: cannot resolve TRADEIN_REVERSAL while customer still LOCKED', async () => {
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
    expectSuccess(await reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'fraud review'), 200);

    const a = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', alert_status: 'OPEN', tradein_id, customer_id: c1.customer_id });
    expect(a.alerts.length).toBe(1);
    const a1 = a.alerts[0].alert_id;
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_005: cannot resolve SUPPLY_SHORTFALL while shortfall condition still exists', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { alert_id } = await createSupplyShortfallOpen(program.program_id, opsCtx, c1Ctx);
    const res = await resolveAlert(program.program_id, alert_id, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const a = await getAlert(program.program_id, alert_id, ops);
    expect(a.alert_status).toBe('OPEN');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_006: OPEN alert staleness across two ops runs escalates program to FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { alert_id } = await createSupplyShortfallOpen(program.program_id, opsCtx, c1Ctx);

    const pBaseline = await getProgram(program.program_id, ops);
    const baseline = pBaseline.ops_run_index;

    const p1 = await runOps(program.program_id, opsCtx);
    expect(p1.ops_run_index).toBe(baseline + 1);
    const aStill = await getAlert(program.program_id, alert_id, ops);
    expect(aStill.alert_status).toBe('OPEN');

    const p2 = await runOps(program.program_id, opsCtx);
    expect(p2.ops_run_index).toBe(baseline + 2);
    expect(p2.program_posture).toBe('PROGRAM_FROZEN');

    const aAfter = await getAlert(program.program_id, alert_id, ops);
    expect(aAfter.alert_status).toBe('OPEN');
  });

  test('ALRT_007: run_ops dedupes OPEN SUPPLY_SHORTFALL alerts (no duplicates)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { lot } = await createSupplyShortfallOpen(program.program_id, opsCtx, c1Ctx);
    await runOps(program.program_id, opsCtx);

    const open = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(open.alerts.length).toBe(1);

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');
    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_008: resolving the last ACKNOWLEDGED alert returns program to ACTIVE', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED'), 200);

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectSuccess(res, 200);

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('ALRT_009: ACKNOWLEDGED alert does not cause frozen escalation across ops runs', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const p0 = await getProgram(program.program_id, ops);
    const n = p0.ops_run_index;

    await runOps(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    const p2 = await getProgram(program.program_id, ops);
    expect(p2.ops_run_index).toBe(n + 2);
    expect(p2.program_posture).toBe('PROGRAM_GUARDED');

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');
  });

  test('ALRT_010: cannot resolve PAYMENT_DISPUTED while payment is still DISPUTED', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('DISPUTED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_011: resolving dispute then resolving alert returns program to ACTIVE', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const resolved = await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED');
    expectSuccess(resolved, 200);
    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectSuccess(res, 200);
    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('ALRT_012: cannot resolve AFTERCARE_OVERDUE while claim not completed and deposit not released', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { customer_id, claim_id, alert_id } = await createAftercareOverdueOpen({ program_id: program.program_id, opsCtx, supportCtx: supCtx });
    expectSuccess(await acknowledgeAlert(program.program_id, alert_id, opsCtx), 200);

    const c1 = await getCustomer(program.program_id, customer_id, ops);
    expect(c1.customer_status).toBe('LOCKED');
    expect(c1.balance_due_cents).toBeGreaterThanOrEqual(15000);

    const cl = await getClaim(program.program_id, claim_id, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');

    const res = await resolveAlert(program.program_id, alert_id, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const aAfter = await getAlert(program.program_id, alert_id, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');

    const clAfter = await getClaim(program.program_id, claim_id, ops);
    expect(clAfter.claim_status).toBe('ADVANCE_SHIPPED');

    const cAfter = await getCustomer(program.program_id, customer_id, ops);
    expect(cAfter.balance_due_cents).toBeGreaterThanOrEqual(15000);
  });

  test('ALRT_013: resolving AFTERCARE_OVERDUE after claim completed keeps customer LOCKED and returns program to ACTIVE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { customer_id, claim_id, alert_id } = await createAftercareOverdueOpen({ program_id: program.program_id, opsCtx, supportCtx: supCtx });

    expectSuccess(await markInboundClaim(program.program_id, claim_id, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claim_id, opsCtx, 'SCRAP'), 200);
    const completeRes = await completeClaim(program.program_id, claim_id, supCtx, {
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);
    expect(completeRes.body.claim_status).toBe('COMPLETED');

    expectSuccess(await acknowledgeAlert(program.program_id, alert_id, opsCtx), 200);

    const res = await resolveAlert(program.program_id, alert_id, opsCtx);
    expectSuccess(res, 200);

    const aAfter = await getAlert(program.program_id, alert_id, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');

    const cAfter = await getCustomer(program.program_id, customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
  });

  test('ALRT_014: cannot resolve RECALL_ACTIVE until campaign is CLOSED (RESOLVED is not enough)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_status).toBe('RESOLVED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN', quality_campaign_id: qcId });
    expect(alerts.alerts.length).toBe(1);
    const a1 = alerts.alerts[0].alert_id;
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectError(res, 400, 'ERR_ALERT_NOT_RESOLVABLE');

    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('ACKNOWLEDGED');
    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('RESOLVED');
    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('ALRT_015: resolving RECALL_ACTIVE after campaign CLOSED does not auto-unfreeze program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);
    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_status).toBe('CLOSED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN', quality_campaign_id: qcId });
    expect(alerts.alerts.length).toBe(1);
    const a1 = alerts.alerts[0].alert_id;
    expectSuccess(await acknowledgeAlert(program.program_id, a1, opsCtx), 200);

    const res = await resolveAlert(program.program_id, a1, opsCtx);
    expectSuccess(res, 200);
    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('ALRT_016: resolving SUPPLY_SHORTFALL after new supply restores ACTIVE and preserves capacity math', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { alert_id } = await createSupplyShortfallOpen(program.program_id, opsCtx, c1Ctx);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const pMid = await getProgram(program.program_id, ops);
    expect(pMid.available_to_commit_units).toBe(4);

    const res = await resolveAlert(program.program_id, alert_id, opsCtx);
    expectSuccess(res, 200);
    const aAfter = await getAlert(program.program_id, alert_id, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_ACTIVE');
    expect(pAfter.available_to_commit_units).toBe(4);
  });

  test('ALRT_017: resolving SUPPLY_SHORTFALL leaves available_to_commit_units unchanged', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const { alert_id } = await createSupplyShortfallOpen(program.program_id, opsCtx, c1Ctx);
    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const pBefore = await getProgram(program.program_id, ops);
    const before = pBefore.available_to_commit_units;

    expectSuccess(await resolveAlert(program.program_id, alert_id, opsCtx), 200);

    const aAfter = await getAlert(program.program_id, alert_id, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_ACTIVE');
    expect(pAfter.available_to_commit_units).toBe(before);
  });

  test('ALRT_018: resolving PAYMENT_DISPUTED does not affect other OPEN alerts or posture', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 12);

    const cPay = await createCustomer(program.program_id, opsCtx);
    const { ctx: cPayCtx } = await createCustomerCtx(program.program_id, cPay.customer_id);
    const { payment_id } = await createDeliveredOrderWithCapturedPayment({
      program_id: program.program_id,
      build_lot_id: lotA17.build_lot_id,
      build_tag: lotA17.build_tag,
      customer_id: cPay.customer_id,
      customerCtx: cPayCtx,
      opsCtx
    });

    const cSf = await createCustomer(program.program_id, opsCtx);
    const { ctx: cSfCtx } = await createCustomerCtx(program.program_id, cSf.customer_id);
    const oSf = await createOrder(program.program_id, cSf.customer_id, cSfCtx);
    expectSuccess(await submitOrder(program.program_id, oSf.order_id, cSfCtx, false), 200);

    const aPay = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED'), 200);
    expectSuccess(await acknowledgeAlert(program.program_id, aPay, opsCtx), 200);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);
    let sf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    if (sf.alerts.length === 0) {
      await runOps(program.program_id, opsCtx);
      sf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    }
    expect(sf.alerts.length).toBe(1);
    const aSf = sf.alerts[0].alert_id;

    const lotAfter = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_GUARDED');

    const res = await resolveAlert(program.program_id, aPay, opsCtx);
    expectSuccess(res, 200);
    const aPayAfter = await getAlert(program.program_id, aPay, ops);
    expect(aPayAfter.alert_status).toBe('RESOLVED');

    const aSfAfter = await getAlert(program.program_id, aSf, ops);
    expect(aSfAfter.alert_status).toBe('OPEN');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');
  });

  test('ALRT_019: run_ops does not create duplicate AFTERCARE_OVERDUE OPEN alert for same claim', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { customer_id, claim_id, alert_id } = await createAftercareOverdueOpen({ program_id: program.program_id, opsCtx, supportCtx: supCtx });

    const p0 = await getProgram(program.program_id, ops);
    const n = p0.ops_run_index;

    const a0 = await getAlert(program.program_id, alert_id, ops);
    expect(a0.alert_status).toBe('OPEN');

    await runOps(program.program_id, opsCtx);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.ops_run_index).toBe(n + 1);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');

    const overdue = await listAlerts(program.program_id, ops, { alert_type: 'AFTERCARE_OVERDUE', alert_status: 'OPEN', claim_id, customer_id });
    expect(overdue.alerts.length).toBe(1);

    const cl = await getClaim(program.program_id, claim_id, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');

    const c = await getCustomer(program.program_id, customer_id, ops);
    expect(c.customer_status).toBe('LOCKED');
  });

  test('ALRT_020: resolving shortfall alert allows new submissions; new shortfall later creates alert and guards program', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    expect((await getProgram(program.program_id, ops)).available_to_commit_units).toBe(1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    let openSf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    if (openSf.alerts.length === 0) {
      await runOps(program.program_id, opsCtx);
      openSf = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    }
    expect(openSf.alerts.length).toBe(1);
    const a1 = openSf.alerts[0].alert_id;
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_GUARDED');

    expectSuccess(await cancelOrder(program.program_id, o1.order_id, opsCtx, 'cleanup'), 200);
    expectSuccess(await resolveAlert(program.program_id, a1, opsCtx), 200);
    expect((await getAlert(program.program_id, a1, ops)).alert_status).toBe('RESOLVED');
    expect((await getProgram(program.program_id, ops)).program_posture).toBe('PROGRAM_ACTIVE');

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);

    const qc2 = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qc2, 201);

    let openAfter = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    if (openAfter.alerts.length === 0) {
      await runOps(program.program_id, opsCtx);
      openAfter = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    }
    expect(openAfter.alerts.length).toBe(1);

    expect((await getAlert(program.program_id, a1, ops)).alert_status).toBe('RESOLVED');

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const o2After = await getOrder(program.program_id, o2.order_id, ops);

    expect(['SUBMITTED', 'ON_HOLD']).toContain(o2After.order_status);
  });

  test('ALRT_021: resolving alert before second ops run prevents frozen escalation', async () => {
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

    const a1 = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);
    const p0 = await getProgram(program.program_id, ops);
    const n = p0.ops_run_index;
    expect(p0.program_posture).toBe('PROGRAM_GUARDED');

    await runOps(program.program_id, opsCtx);
    const p1 = await getProgram(program.program_id, ops);
    expect(p1.ops_run_index).toBe(n + 1);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');

    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'REFUNDED'), 200);
    expectSuccess(await resolveAlert(program.program_id, a1, opsCtx), 200);

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('REFUNDED');
    const aAfter = await getAlert(program.program_id, a1, ops);
    expect(aAfter.alert_status).toBe('RESOLVED');
    const pActive = await getProgram(program.program_id, ops);
    expect(pActive.program_posture).toBe('PROGRAM_ACTIVE');

    await runOps(program.program_id, opsCtx);
    const p2 = await getProgram(program.program_id, ops);
    expect(p2.ops_run_index).toBe(n + 2);
    expect(p2.program_posture).toBe('PROGRAM_ACTIVE');
  });

  test('ALRT_022: resolving PAYMENT_DISPUTED does not affect CHARGEBACK_LOST alert or customer lock', async () => {
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

    const aDisp = await disputeAndGetPaymentDisputedAlertId(program.program_id, payment_id, supCtx, ops);

    expectSuccess(await resolveDispute(program.program_id, payment_id, supCtx, 'CHARGEBACK_LOST'), 200);

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('CHARGEBACK_LOST');
    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');

    const cb = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', payment_id, customer_id: c1.customer_id });
    expect(cb.alerts.length).toBe(1);
    const aCb = cb.alerts[0].alert_id;

    expectSuccess(await resolveAlert(program.program_id, aDisp, opsCtx), 200);
    const aDispAfter = await getAlert(program.program_id, aDisp, ops);
    expect(aDispAfter.alert_status).toBe('RESOLVED');

    const pmAfter = await getPayment(program.program_id, payment_id, ops);
    expect(pmAfter.payment_status).toBe('CHARGEBACK_LOST');

    const aCbAfter = await getAlert(program.program_id, aCb, ops);
    expect(aCbAfter.alert_status).toBe('OPEN');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.customer_status).toBe('LOCKED');
  });
});
