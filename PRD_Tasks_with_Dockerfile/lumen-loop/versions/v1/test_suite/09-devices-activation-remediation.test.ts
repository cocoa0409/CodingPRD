import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
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
  freezeProgram,
  getBuildLot,
  getCarePlan,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  lockCustomer,
  markDelivered,
  markInboundClaim,
  markInboundReturn,
  receiveClaim,
  receiveReturn,
  remediateDevice,
  shipOrder,
  submitOrder,
  uniqueId,
  approveReturn
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

async function createDeliveredOrderWithDevice(args: {
  program_id: string;
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  opsActor: { actor_id: string; actor_type: 'Ops' };
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  build_lot_id: string;
  build_tag: string;
  include_care_plan: boolean;
  use_credit_cents?: number;
  serial_number: string;
}) {
  const o = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: args.use_credit_cents ?? 0 });
  expectSuccess(await submitOrder(args.program_id, o.order_id, args.customerCtx, args.include_care_plan), 200);

  const shipRes = await shipOrder(args.program_id, o.order_id, args.opsCtx, {
    build_lot_id: args.build_lot_id,
    serial_number: args.serial_number,
    build_tag: args.build_tag
  });
  expectSuccess(shipRes, 200);

  expectSuccess(await markDelivered(args.program_id, o.order_id, args.opsCtx), 200);

  const delivered = await getOrder(args.program_id, o.order_id, args.opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.device_id).toBeTruthy();

  return delivered;
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
  const o = await createOrder(args.program_id, args.customer_id, args.customerCtx);
  expectSuccess(await submitOrder(args.program_id, o.order_id, args.customerCtx, args.include_care_plan), 200);

  const shipRes = await shipOrder(args.program_id, o.order_id, args.opsCtx, {
    build_lot_id: args.build_lot_id,
    serial_number: args.serial_number,
    build_tag: args.build_tag
  });
  expectSuccess(shipRes, 200);

  const shipped = await getOrder(args.program_id, o.order_id, args.opsActor);
  expect(shipped.order_status).toBe('SHIPPED');
  expect(shipped.device_id).toBeTruthy();
  return shipped;
}

describe('Feature 9: Devices: Activation & Remediation (v1)', () => {
  test('DEV_001: activation sets device ACTIVE and care plan ACTIVE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const carePlanId = delivered.care_plan_id as string;

    const cp0 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp0.care_plan_status).toBe('PENDING_ACTIVATION');

    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectSuccess(act, 200);

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('ACTIVE');

    const cp1 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp1.care_plan_status).toBe('ACTIVE');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });

  test('DEV_002: activation when order SHIPPED but not DELIVERED fails ERR_DEVICE_NOT_ACTIVATABLE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const shipped = await createShippedNotDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = shipped.device_id as string;
    const carePlanId = shipped.care_plan_id as string;

    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectError(act, 400, 'ERR_DEVICE_NOT_ACTIVATABLE');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const cp = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp.care_plan_status).toBe('PENDING_ACTIVATION');
  });

  test('DEV_003: activation blocked in PROGRAM_FROZEN (manual freeze) with ERR_PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
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

    const freezeRes = await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect(freezeRes.program_posture).toBe('PROGRAM_FROZEN');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');

    const deviceId = delivered.device_id as string;
    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectError(act, 400, 'ERR_PROGRAM_FROZEN');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });

  test('DEV_004: activation on recall-quarantined device fails ERR_DEVICE_QUARANTINED (precedence over frozen)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const carePlanId = delivered.care_plan_id as string;

    const qc = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qc, 201);

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectError(act, 400, 'ERR_DEVICE_QUARANTINED');

    const dStill = await getDevice(program.program_id, deviceId, ops);
    expect(dStill.device_status).toBe('QUARANTINED');

    const cpStill = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpStill.care_plan_status).toBe('PAUSED');
  });

  test('DEV_005: Ops remediate clears quarantine and resumes ACTIVE care plan for previously-active device', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const carePlanId = delivered.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const dActive = await getDevice(program.program_id, deviceId, ops);
    expect(dActive.device_status).toBe('ACTIVE');
    const cpActive = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpActive.care_plan_status).toBe('ACTIVE');

    const qc = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qc, 201);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');
    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const rem = await remediateDevice(program.program_id, deviceId, opsCtx, 'field fix applied');
    expectSuccess(rem, 200);

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('ACTIVE');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('ACTIVE');
  });

  test('DEV_007: locked customer activation fails ERR_CUSTOMER_LOCKED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
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

    const locked = await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'risk');
    expect(locked.customer_status).toBe('LOCKED');

    const deviceId = delivered.device_id as string;
    const act = await activateDevice(program.program_id, deviceId, c1Ctx);
    expectError(act, 400, 'ERR_CUSTOMER_LOCKED');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });

  test('DEV_008: Support cannot remediate device (ERR_FORBIDDEN_FOR_ACTOR)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;

    const qc = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qc, 201);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const carePlanId = delivered.care_plan_id as string;
    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const rem = await remediateDevice(program.program_id, deviceId, supCtx, 'attempted fix');
    expectError(rem, 403, 'ERR_FORBIDDEN_FOR_ACTOR');

    const dStill = await getDevice(program.program_id, deviceId, ops);
    expect(dStill.device_status).toBe('QUARANTINED');

    const cpStill = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpStill.care_plan_status).toBe('PAUSED');
  });

  test('DEV_009: remediation restores never-activated QUARANTINED device to SHIPPED and plan to PENDING_ACTIVATION', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const carePlanId = delivered.care_plan_id as string;

    const cp0 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp0.care_plan_status).toBe('PENDING_ACTIVATION');

    const qc = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qc, 201);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');
    expect(cpPaused.device_id).toBe(deviceId);

    const rem = await remediateDevice(program.program_id, deviceId, opsCtx, 'verified safe');
    expectSuccess(rem, 200);

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('SHIPPED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('PENDING_ACTIVATION');
    expect(cpAfter.device_id).toBe(deviceId);
  });

  test('DEV_010: program frozen due recall blocks activation for non-quarantined device with ERR_PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c2 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c2.customer_id,
      customerCtx: c2Ctx,
      build_lot_id: lotB99.build_lot_id,
      build_tag: lotB99.build_tag,
      include_care_plan: false,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const d0 = await getDevice(program.program_id, deviceId, ops);
    expect(d0.build_tag).toBe('B99Z');

    const qc = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qc, 201);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const act = await activateDevice(program.program_id, deviceId, c2Ctx);
    expectError(act, 400, 'ERR_PROGRAM_FROZEN');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('SHIPPED');

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
  });

  test('DEV_011: duplicate serial within a program is invalid; second ship fails ERR_INVALID_REQUEST and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c2 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c2Actor = { actor_id: c2.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c2Session = await createSession(program.program_id, c2Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };
    const c2Ctx = { ...c2Actor, session_id: c2Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    const o2 = await createOrder(program.program_id, c2.customer_id, c2Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c2Ctx, false), 200);

    const o1Submitted = await getOrder(program.program_id, o1.order_id, ops);
    const pm1 = o1Submitted.payment_id as string;
    expect(pm1).toBeTruthy();

    const before2 = await getOrder(program.program_id, o2.order_id, ops);
    expect(before2.order_status).toBe('SUBMITTED');
    const pm2 = before2.payment_id as string;
    expect(pm2).toBeTruthy();

    const pBefore = await getProgram(program.program_id, ops);

    const ship1 = await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: 'SN-DUPE-1', build_tag: 'B99Z' });
    expectSuccess(ship1, 200);

    const shipped1 = await getOrder(program.program_id, o1.order_id, ops);
    expect(shipped1.order_status).toBe('SHIPPED');
    expect(shipped1.device_id).toBeTruthy();

    const pm1After = await getPayment(program.program_id, pm1, ops);
    expect(pm1After.payment_status).toBe('CAPTURED');

    const d1 = await getDevice(program.program_id, shipped1.device_id as string, ops);
    expect(d1.serial_number).toBe('SN-DUPE-1');
    expect(d1.device_status).toBe('SHIPPED');

    const ship2 = await shipOrder(program.program_id, o2.order_id, opsCtx, { build_lot_id: lot.build_lot_id, serial_number: 'SN-DUPE-1', build_tag: 'B99Z' });
    expectError(ship2, 400, 'ERR_INVALID_REQUEST');

    const after2 = await getOrder(program.program_id, o2.order_id, ops);
    expect(after2.order_status).toBe('SUBMITTED');
    expect(after2.device_id).toBeNull();

    const pm2After = await getPayment(program.program_id, pm2, ops);
    expect(pm2After.payment_status).toBe('AUTHORIZED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('DEV_012: same serial_number can be used across different programs', async () => {
    const p1 = await createProgram();
    const p2 = await createProgram();

    const ops1 = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const ops2 = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const s1 = await createSession(p1.program_id, ops1);
    const s2 = await createSession(p2.program_id, ops2);
    const ops1Ctx = { ...ops1, session_id: s1.session_id };
    const ops2Ctx = { ...ops2, session_id: s2.session_id };

    const lot1 = await createBuildLot(p1.program_id, ops1Ctx, 'B99Z', 6);
    const lot2 = await createBuildLot(p2.program_id, ops2Ctx, 'B99Z', 6);

    const c1 = await createCustomer(p1.program_id, ops1Ctx);
    const c2 = await createCustomer(p2.program_id, ops2Ctx);

    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c2Actor = { actor_id: c2.customer_id, actor_type: 'Customer' as const };
    const cs1 = await createSession(p1.program_id, c1Actor);
    const cs2 = await createSession(p2.program_id, c2Actor);
    const c1Ctx = { ...c1Actor, session_id: cs1.session_id };
    const c2Ctx = { ...c2Actor, session_id: cs2.session_id };

    const o1 = await createOrder(p1.program_id, c1.customer_id, c1Ctx);
    const o2 = await createOrder(p2.program_id, c2.customer_id, c2Ctx);
    expectSuccess(await submitOrder(p1.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(await submitOrder(p2.program_id, o2.order_id, c2Ctx, false), 200);

    expectSuccess(await shipOrder(p1.program_id, o1.order_id, ops1Ctx, { build_lot_id: lot1.build_lot_id, serial_number: 'SN-SHARED', build_tag: 'B99Z' }), 200);
    expectSuccess(await shipOrder(p2.program_id, o2.order_id, ops2Ctx, { build_lot_id: lot2.build_lot_id, serial_number: 'SN-SHARED', build_tag: 'B99Z' }), 200);

    const shipped1 = await getOrder(p1.program_id, o1.order_id, ops1);
    const shipped2 = await getOrder(p2.program_id, o2.order_id, ops2);

    expect(shipped1.order_status).toBe('SHIPPED');
    expect(shipped2.order_status).toBe('SHIPPED');

    const d1 = await getDevice(p1.program_id, shipped1.device_id as string, ops1);
    const d2 = await getDevice(p2.program_id, shipped2.device_id as string, ops2);

    expect(d1.serial_number).toBe('SN-SHARED');
    expect(d2.serial_number).toBe('SN-SHARED');
  });

  test('DEV_013: return replacement cannot create a device with an existing serial_number (ERR_INVALID_REQUEST)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c2 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);

    const o2 = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c2.customer_id,
      customerCtx: c2Ctx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const pm2 = await getPayment(program.program_id, o2.payment_id as string, ops);
    expect(pm2.payment_status).toBe('CAPTURED');

    const rCreate = await createReturn(program.program_id, o2.order_id, c2Ctx, 'REPLACEMENT');
    expectSuccess(rCreate, 201);
    const return_id = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, return_id, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, return_id, supCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, return_id, opsCtx, 'SCRAP'), 200);

    const rReceived = await getReturn(program.program_id, return_id, ops);
    expect(rReceived.return_status).toBe('RECEIVED');
    expect(rReceived.inspection_outcome).toBe('SCRAP');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const ship1 = await shipOrder(program.program_id, o1.order_id, opsCtx, { build_lot_id: shipLot.build_lot_id, serial_number: 'SN-SERIAL-1', build_tag: 'B99Z' });
    expectSuccess(ship1, 200);

    const shipped1 = await getOrder(program.program_id, o1.order_id, ops);
    const dShip = await getDevice(program.program_id, shipped1.device_id as string, ops);
    expect(dShip.serial_number).toBe('SN-SERIAL-1');
    expect(dShip.device_status).toBe('SHIPPED');

    const complete = await completeReturn(program.program_id, return_id, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-SERIAL-1',
      replacement_build_tag: 'B99Z'
    });
    expectError(complete, 400, 'ERR_INVALID_REQUEST');

    const rAfter = await getReturn(program.program_id, return_id, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('DELIVERED');
    expect(o2After.device_id).toBe(o2.device_id);

    const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
    expect(repLotAfter.build_lot_status).toBe('AVAILABLE');

    const pm2After = await getPayment(program.program_id, o2.payment_id as string, ops);
    expect(pm2After.payment_status).toBe('CAPTURED');
  });

  test('DEV_014: claim completion cannot create replacement device with an existing serial_number (ERR_INVALID_REQUEST)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const d1Id = delivered.device_id as string;
    expectSuccess(await activateDevice(program.program_id, d1Id, c1Ctx), 200);

    const d1 = await getDevice(program.program_id, d1Id, ops);
    expect(d1.device_status).toBe('ACTIVE');

    const pm1 = await getPayment(program.program_id, delivered.payment_id as string, ops);
    expect(pm1.payment_status).toBe('CAPTURED');

    const clCreate = await createClaim(program.program_id, d1Id, supCtx, 'WARRANTY');
    expectSuccess(clCreate, 201);
    const claimId = clCreate.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, supCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, supCtx, 'SCRAP'), 200);

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('RECEIVED');
    expect(cl.replacement_device_id).toBeNull();

    const c2 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);
    const oExist = await createOrder(program.program_id, c2.customer_id, c2Ctx);
    expectSuccess(await submitOrder(program.program_id, oExist.order_id, c2Ctx, false), 200);

    const shipRes = await shipOrder(program.program_id, oExist.order_id, opsCtx, {
      build_lot_id: shipLot.build_lot_id,
      serial_number: 'SN-SERIAL-CLM',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const shipped = await getOrder(program.program_id, oExist.order_id, ops);
    const dExist = await getDevice(program.program_id, shipped.device_id as string, ops);
    expect(dExist.serial_number).toBe('SN-SERIAL-CLM');
    expect(dExist.device_status).toBe('SHIPPED');

    const complete = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-SERIAL-CLM',
      replacement_build_tag: 'B99Z'
    });
    expectError(complete, 400, 'ERR_INVALID_REQUEST');

    const clAfter = await getClaim(program.program_id, claimId, ops);
    expect(clAfter.claim_status).toBe('RECEIVED');
    expect(clAfter.replacement_device_id).toBeNull();

    const o1After = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1After.order_status).toBe('DELIVERED');
    expect(o1After.device_id).toBe(d1Id);

    const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
    expect(repLotAfter.build_lot_status).toBe('AVAILABLE');

    const pm1After = await getPayment(program.program_id, delivered.payment_id as string, ops);
    expect(pm1After.payment_status).toBe('CAPTURED');
  });

  test('DEV_015: remediate on non-quarantined ACTIVE device fails ERR_INVALID_STATE_TRANSITION and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 20);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const delivered = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsCtx,
      opsActor: ops,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      serial_number: `SN-${uniqueId('sn')}`
    });

    const deviceId = delivered.device_id as string;
    const carePlanId = delivered.care_plan_id as string;

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const d0 = await getDevice(program.program_id, deviceId, ops);
    expect(d0.device_status).toBe('ACTIVE');

    const cp0 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp0.care_plan_status).toBe('ACTIVE');
    expect(cp0.device_id).toBe(deviceId);

    const rem = await remediateDevice(program.program_id, deviceId, opsCtx, 'no quarantine to clear');
    expectError(rem, 400, 'ERR_INVALID_STATE_TRANSITION');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('ACTIVE');

    const cp1 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp1.care_plan_status).toBe('ACTIVE');
    expect(cp1.device_id).toBe(deviceId);

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_ACTIVE');
  });
});
