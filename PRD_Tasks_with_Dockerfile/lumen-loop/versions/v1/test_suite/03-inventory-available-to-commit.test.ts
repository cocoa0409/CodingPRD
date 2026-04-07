import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  approveReturn,
  cancelOrder,
  completeClaim,
  completeReturn,
  createBuildLot,
  createClaim,
  createCustomer,
  createCustomerCtx,
  createDeliveredOrder,
  createOrder,
  createOpsCtx,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSession,
  createSupportCtx,
  getBuildLot,
  getClaim,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  markInboundClaim,
  markInboundReturn,
  receiveClaim,
  receiveReturn,
  shipOrder,
  submitOrder,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 3: Inventory & Available-to-Commit Units (v1)', () => {
  async function burnReserveWithWarrantyReplacements(args: {
    program_id: string;
    opsActor: { actor_id: string; actor_type: 'Ops' };
    opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
    supCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
    customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
    starting_device_id: string;
    replacement_build_lot_id: string;
    replacement_build_tag: string;
    count: number;
  }) {
    let currentDeviceId = args.starting_device_id;
    for (let i = 0; i < args.count; i++) {
      const c = await createClaim(args.program_id, currentDeviceId, args.supCtx, 'WARRANTY');
      expectSuccess(c, 201);
      const claimId = c.body.claim_id as string;
      expectSuccess(await approveClaim(args.program_id, claimId, args.supCtx, 'REPLACEMENT'), 200);
      expectSuccess(await markInboundClaim(args.program_id, claimId, args.opsCtx), 200);
      expectSuccess(await receiveClaim(args.program_id, claimId, args.opsCtx, 'SCRAP'), 200);

      const repRes = await completeClaim(args.program_id, claimId, args.supCtx, {
        replacement_build_lot_id: args.replacement_build_lot_id,
        replacement_serial_number: `SN-BURN-${i}-${uniqueId('sn')}`,
        replacement_build_tag: args.replacement_build_tag
      });
      expectSuccess(repRes, 200);
      currentDeviceId = repRes.body.replacement_device_id as string;
      expect(currentDeviceId).toBeTruthy();

      expectSuccess(await activateDevice(args.program_id, currentDeviceId, args.customerCtx), 200);
      const d = await getDevice(args.program_id, currentDeviceId, args.opsActor);
      expect(d.device_status).toBe('ACTIVE');
    }
    return currentDeviceId;
  }

  test('INV_001: 5 units of raw supply yields available_to_commit_units=0 due to 5-unit reserve', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'B01', 5);
    expect(lot.build_lot_status).toBe('AVAILABLE');

    const p = await getProgram(program.program_id, ops);
    expect(p.available_to_commit_units).toBe(0);
  });

  test('INV_002: reserve is program-wide across lots (3 + 3 supply => available_to_commit_units=1)', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    await createBuildLot(program.program_id, opsCtx, 'B02', 3);
    await createBuildLot(program.program_id, opsCtx, 'B03', 3);

    const p = await getProgram(program.program_id, ops);
    expect(p.available_to_commit_units).toBe(1);
  });

  test('INV_003: SHIP_HOLD quarantines matching lots and removes them from available_to_commit_units', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const lB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const before = await getProgram(program.program_id, ops);
    expect(before.available_to_commit_units).toBe(15);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const lotA = await getBuildLot(program.program_id, lA17.build_lot_id, ops);
    const lotB = await getBuildLot(program.program_id, lB99.build_lot_id, ops);
    expect(lotA.build_lot_status).toBe('QUARANTINED');
    expect(lotB.build_lot_status).toBe('AVAILABLE');

    const after = await getProgram(program.program_id, ops);
    expect(after.available_to_commit_units).toBe(5);
  });

  test('INV_004: shipping from a quarantined build lot returns ERR_BUILD_LOT_QUARANTINED and makes no changes', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    const lotB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    expect(submitted.payment_id).toBeTruthy();

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const lotAAfter = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    const lotBAfter = await getBuildLot(program.program_id, lotB99.build_lot_id, ops);
    expect(lotAAfter.build_lot_status).toBe('QUARANTINED');
    expect(lotBAfter.build_lot_status).toBe('AVAILABLE');

    const pBefore = await getProgram(program.program_id, ops);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lotA17.build_lot_id,
      serial_number: 'SN123',
      build_tag: 'A17B'
    });
    expectError(shipRes, 400, 'ERR_BUILD_LOT_QUARANTINED');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SUBMITTED');
    expect(oAfter.device_id).toBeNull();

    const pm = await getPayment(program.program_id, submitted.payment_id as string, ops);
    expect(pm.payment_status).toBe('AUTHORIZED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('INV_005: quarantining all supply while a SUBMITTED order exists creates SUPPLY_SHORTFALL alert and guards program', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const p2 = await getProgram(program.program_id, ops);
    expect(p2.available_to_commit_units).toBe(0);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const p = await getProgram(program.program_id, ops);
    expect(p.program_posture).toBe('PROGRAM_GUARDED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBeGreaterThanOrEqual(1);
  });

  test('INV_006: canceling committed order in shortfall releases commitment but stays guarded while alert OPEN', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    const payment_id = submitted.payment_id as string;

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');

    const cancelRes = await cancelOrder(program.program_id, o1.order_id, opsCtx, 'containment cleanup');
    expectSuccess(cancelRes, 200);
    expect(cancelRes.body.order_status).toBe('CANCELED');

    const pm = await getPayment(program.program_id, payment_id, ops);
    expect(pm.payment_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBeGreaterThanOrEqual(1);
  });

  test('INV_007: adding supply recomputes available_to_commit_units but remains guarded until alert resolved', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    await createBuildLot(program.program_id, opsCtx, 'A17B', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_GUARDED');
    expect(p0.available_to_commit_units).toBe(0);

    const alertsBefore = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(alertsBefore.alerts.length).toBeGreaterThanOrEqual(1);

    await createBuildLot(program.program_id, opsCtx, 'C01X', 10);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(4);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');

    const alertsAfter = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(alertsAfter.alerts.length).toBeGreaterThanOrEqual(1);
  });

  test('INV_008: shipping from a 1-unit lot consumes it; available_to_commit_units unchanged by shipping', async () => {
    const program = await createProgram();

    const ops = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
    const opsSession = await createSession(program.program_id, ops);
    const opsCtx = { ...ops, session_id: opsSession.session_id };

    const l1 = await createBuildLot(program.program_id, opsCtx, 'D01', 1);
    await createBuildLot(program.program_id, opsCtx, 'D02', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const c1Actor = { actor_id: c1.customer_id, actor_type: 'Customer' as const };
    const c1Session = await createSession(program.program_id, c1Actor);
    const c1Ctx = { ...c1Actor, session_id: c1Session.session_id };

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const beforeShip = await getProgram(program.program_id, ops);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: l1.build_lot_id,
      serial_number: 'SN-L1-001',
      build_tag: 'D01'
    });
    expectSuccess(shipRes, 200);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('SHIPPED');
    expect(oAfter.device_id).toBeTruthy();

    const pm = await getPayment(program.program_id, oAfter.payment_id as string, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const lotAfter = await getBuildLot(program.program_id, l1.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('CONSUMED');

    const afterShip = await getProgram(program.program_id, ops);
    expect(afterShip.available_to_commit_units).toBe(beforeShip.available_to_commit_units);
  });

  test('INVHOLD_001: SHIP_HOLD triggers SUPPLY_SHORTFALL hold; shipping ON_HOLD order fails ERR_ORDER_ON_HOLD and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    expect(lot.build_lot_status).toBe('AVAILABLE');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

    const submitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(submitted.order_status).toBe('SUBMITTED');
    expect(submitted.payment_id).toBeTruthy();
    expect(submitted.device_id).toBeNull();

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');
    expect(p0.available_to_commit_units).toBe(0);

    const preAlerts = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(preAlerts.alerts.length).toBe(0);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcRes, 201);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');
    expect(p1.available_to_commit_units).toBe(0);

    const lotAfter = await getBuildLot(program.program_id, lot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const stillSubmitted = await getOrder(program.program_id, o1.order_id, ops);
    expect(stillSubmitted.order_status).toBe('SUBMITTED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'SUPPLY_SHORTFALL', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);

    const shipRes = await shipOrder(program.program_id, o1.order_id, opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: 'SN-SF-1',
      build_tag: 'A17B'
    });
    expectError(shipRes, 400, 'ERR_ORDER_ON_HOLD');

    const afterFail = await getOrder(program.program_id, o1.order_id, ops);
    expect(afterFail.order_status).toBe('ON_HOLD');
    expect(afterFail.device_id).toBeNull();

    const pm = await getPayment(program.program_id, submitted.payment_id as string, ops);
    expect(pm.payment_status).toBe('AUTHORIZED');

    const p2 = await getProgram(program.program_id, ops);
    expect(p2.available_to_commit_units).toBe(0);
  });

  test('INVRES_001: completing a replacement return fails ERR_OUT_OF_STOCK once reserve is depleted and available_to_commit_units=0', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 8);

    const cBase = await createCustomer(program.program_id, opsCtx);
    const { ctx: cBaseCtx } = await createCustomerCtx(program.program_id, cBase.customer_id);
    const oBase = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: cBase.customer_id,
      customerCtx: cBaseCtx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false
    });
    const baseDeviceId = oBase.device_id as string;
    expectSuccess(await activateDevice(program.program_id, baseDeviceId, cBaseCtx), 200);
    await burnReserveWithWarrantyReplacements({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      supCtx,
      customerCtx: cBaseCtx,
      starting_device_id: baseDeviceId,
      replacement_build_lot_id: lot.build_lot_id,
      replacement_build_tag: lot.build_tag,
      count: 5
    });

    const pAfterBurn = await getProgram(program.program_id, ops);
    expect(pAfterBurn.available_to_commit_units).toBe(2);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false
    });
    const deviceId = o1.device_id as string;

    const pm1 = await getPayment(program.program_id, o1.payment_id as string, ops);
    expect(pm1.payment_status).toBe('CAPTURED');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const cCommit = await createCustomer(program.program_id, opsCtx);
    const { ctx: cCommitCtx } = await createCustomerCtx(program.program_id, cCommit.customer_id);
    const oCommit = await createOrder(program.program_id, cCommit.customer_id, cCommitCtx);
    expectSuccess(await submitOrder(program.program_id, oCommit.order_id, cCommitCtx, false), 200);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const retCreate = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REPLACEMENT');
    expectSuccess(retCreate, 201);
    const returnId = retCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const r0 = await getReturn(program.program_id, returnId, ops);
    expect(r0.return_status).toBe('RECEIVED');
    expect(r0.inspection_outcome).toBe('SCRAP');
    expect(r0.replacement_device_id).toBeNull();

    const o1Pre = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1Pre.order_status).toBe('DELIVERED');
    expect(o1Pre.device_id).toBe(deviceId);

    const complete = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-NO-STOCK',
      replacement_build_tag: lot.build_tag
    });
    expectError(complete, 400, 'ERR_OUT_OF_STOCK');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const o1After = await getOrder(program.program_id, o1.order_id, ops);
    expect(o1After.order_status).toBe('DELIVERED');
    expect(o1After.device_id).toBe(deviceId);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('INVX_001: RESTOCK increases capacity; reserve-depleted claim replacement outcome depends on whether sale inventory consumption is allowed', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const burnLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 7);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: burnLot.build_lot_id,
      build_tag: burnLot.build_tag,
      include_care_plan: false
    });
    const paymentId = o1.payment_id as string;
    expect(paymentId).toBeTruthy();
    const initialDeviceId = o1.device_id as string;
    expectSuccess(await activateDevice(program.program_id, initialDeviceId, c1Ctx), 200);

    const lastDeviceId = await burnReserveWithWarrantyReplacements({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      supCtx,
      customerCtx: c1Ctx,
      starting_device_id: initialDeviceId,
      replacement_build_lot_id: burnLot.build_lot_id,
      replacement_build_tag: burnLot.build_tag,
      count: 5
    });

    const clCreate = await createClaim(program.program_id, lastDeviceId, supCtx, 'WARRANTY');
    expectSuccess(clCreate, 201);
    const claimId = clCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const clReady = await getClaim(program.program_id, claimId, ops);
    expect(clReady.claim_status).toBe('RECEIVED');
    expect(clReady.replacement_device_id).toBeNull();

    const cSale = await createCustomer(program.program_id, opsCtx);
    const { ctx: cSaleCtx } = await createCustomerCtx(program.program_id, cSale.customer_id);
    const oSale = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: cSale.customer_id,
      customerCtx: cSaleCtx,
      opsCtx,
      build_lot_id: burnLot.build_lot_id,
      build_tag: burnLot.build_tag,
      include_care_plan: false
    });
    const dSale = await getDevice(program.program_id, oSale.device_id as string, ops);
    expect(dSale.device_status).toBe('SHIPPED');

    const retCreate = await createReturn(program.program_id, oSale.order_id, cSaleCtx, 'REFUND');
    expectSuccess(retCreate, 201);
    const returnId = retCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, supCtx), 200);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);
    const cCommit = await createCustomer(program.program_id, opsCtx);
    const { ctx: cCommitCtx } = await createCustomerCtx(program.program_id, cCommit.customer_id);
    const oCommit = await createOrder(program.program_id, cCommit.customer_id, cCommitCtx);
    expectSuccess(await submitOrder(program.program_id, oCommit.order_id, cCommitCtx, false), 200);

    const pPre = await getProgram(program.program_id, ops);
    expect(pPre.available_to_commit_units).toBe(0);

    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK'), 200);

    const retReceived = await getReturn(program.program_id, returnId, ops);
    expect(retReceived.return_status).toBe('RECEIVED');
    expect(retReceived.inspection_outcome).toBe('RESTOCK');

    const pAfterReceive = await getProgram(program.program_id, ops);
    expect(pAfterReceive.available_to_commit_units).toBe(1);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-SALE-INV-1',
      replacement_build_tag: 'B99Z'
    });

    if (completeRes.status === 200) {

      const replacementDeviceId = completeRes.body.replacement_device_id as string;
      expect(replacementDeviceId).toBeTruthy();

      const clDone = await getClaim(program.program_id, claimId, ops);
      expect(clDone.claim_status).toBe('COMPLETED');
      expect(clDone.replacement_device_id).toBe(replacementDeviceId);

      const o1After = await getOrder(program.program_id, o1.order_id, ops);
      expect(o1After.order_status).toBe('DELIVERED');
      expect(o1After.device_id).toBe(replacementDeviceId);

      const pmAfter = await getPayment(program.program_id, paymentId, ops);
      expect(pmAfter.payment_status).toBe('CAPTURED');

      const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
      expect(repLotAfter.build_lot_status).toBe('CONSUMED');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(0);
    } else {

      expect(completeRes.status).toBe(400);

      const errorCode = completeRes.body?.error?.code;
      expect(['ERR_OUT_OF_STOCK', 'ERR_CLAIM_NOT_RESOLVABLE', 'ERR_CLAIM_NOT_ELIGIBLE']).toContain(errorCode);

      const clAfter = await getClaim(program.program_id, claimId, ops);
      expect(clAfter.claim_status).toBe('RECEIVED');
      expect(clAfter.replacement_device_id).toBeNull();

      const o1After = await getOrder(program.program_id, o1.order_id, ops);
      expect(o1After.order_status).toBe('DELIVERED');
      expect(o1After.device_id).toBe(lastDeviceId);

      const pmAfter = await getPayment(program.program_id, paymentId, ops);
      expect(pmAfter.payment_status).toBe('CAPTURED');

      const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
      expect(repLotAfter.build_lot_status).toBe('AVAILABLE');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(1);
    }
  });
});
