import { expectError, expectErrorOneOf, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  cancelClaim,
  completeClaim,
  createAndApplyBalanceDue,
  createBuildLot,
  createClaim,
  createCustomerCtx,
  createDeliveredOrderWithDevice,
  createOpsCtx,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSubmittedOrder,
  createSupportCtx,
  disputePayment,
  freezeProgram,
  getCarePlan,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  markInboundClaim,
  receiveClaim,
  runOps,
  runOpsTo,
  settleBalanceDue,
  shipAdvanceReplacement
} from '../../../test-helpers/resources';

describe('Feature 12: Claims: Warranty, Care Plan, Recall & Advance Replacement (v1)', () => {
  test('CLAIM_017: WARRANTY claim on non-activated device returns ERR_CLAIM_NOT_ELIGIBLE and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { actor: sup, ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: false
    });

    const p0 = await getProgram(program.program_id, ops);
    const o0 = await getOrder(program.program_id, delivered.order_id, ops);
    const d0 = await getDevice(program.program_id, deviceId, ops);

    const res = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectError(res, 400, 'ERR_CLAIM_NOT_ELIGIBLE');

    expect(res.body?.claim_id).toBeUndefined();

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');
    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    const p1 = await getProgram(program.program_id, ops);
    expect(p1.ops_run_index).toBe(p0.ops_run_index);
    expect(p1.program_posture).toBe(p0.program_posture);

    expect(o0.order_status).toBe('DELIVERED');
    expect(d0.device_status).toBe('SHIPPED');
    expect(sup.actor_type).toBe('Support');
  });

  test('CLAIM_018: CARE_PLAN claim while plan is PENDING_ACTIVATION returns ERR_CLAIM_NOT_ELIGIBLE and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { actor: sup, ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, carePlanId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: true,
      activate: false
    });
    expect(carePlanId).toBeTruthy();

    const cp0 = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp0.care_plan_status).toBe('PENDING_ACTIVATION');

    const res = await createClaim(program.program_id, deviceId, supCtx, 'CARE_PLAN');
    expectError(res, 400, 'ERR_CLAIM_NOT_ELIGIBLE');

    expect(res.body?.claim_id).toBeUndefined();

    const cp1 = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp1.care_plan_status).toBe('PENDING_ACTIVATION');

    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(sup.actor_type).toBe('Support');
  });

  test("CLM_001: claim creation blocked by existing non-terminal return with ERR_CLAIM_NOT_ELIGIBLE", async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, customerCtx } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: false
    });

    const retRes = await createReturn(program.program_id, delivered.order_id, customerCtx, 'REFUND');
    expectSuccess(retRes, 201);
    const returnId = retRes.body.return_id as string;

    const r0 = await getReturn(program.program_id, returnId, ops);
    expect(r0.return_status).toBe('REQUESTED');

    expectSuccess(await activateDevice(program.program_id, deviceId, customerCtx), 200);
    const dActive = await getDevice(program.program_id, deviceId, ops);
    expect(dActive.device_status).toBe('ACTIVE');

    const claimRes = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectError(claimRes, 400, 'ERR_CLAIM_NOT_ELIGIBLE');

    const r1 = await getReturn(program.program_id, returnId, ops);
    expect(r1.return_status).toBe('REQUESTED');
    expect(claimRes.body?.claim_id).toBeUndefined();
  });

  test('CLM_002: second non-terminal claim creation blocked with ERR_CLAIM_NOT_ELIGIBLE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: true,
      activate: true
    });

    const c1 = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(c1, 201);
    const claimId = c1.body.claim_id as string;

    const second = await createClaim(program.program_id, deviceId, supCtx, 'CARE_PLAN');
    expectError(second, 400, 'ERR_CLAIM_NOT_ELIGIBLE');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('OPEN');
    expect(cl.replacement_device_id).toBeNull();
  });

  test('CLM_003: warranty claim at ops_run_index=14 (activated at 3) succeeds', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, customerCtx } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: false
    });

    await runOpsTo(program.program_id, opsCtx, 3);
    expectSuccess(await activateDevice(program.program_id, deviceId, customerCtx), 200);
    await runOpsTo(program.program_id, opsCtx, 14);

    const res = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(res, 201);
    expect(res.body.claim_status).toBe('OPEN');
    expect(res.body.claim_type).toBe('WARRANTY');
    expect(res.body.device_id).toBe(deviceId);
    expect(res.body.customer_id).toBe(customer.customer_id);
  });

  test('CLM_004: warranty claim at ops_run_index=15 (activated at 3) fails ERR_CLAIM_NOT_ELIGIBLE', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customerCtx } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: false
    });

    await runOpsTo(program.program_id, opsCtx, 3);
    expectSuccess(await activateDevice(program.program_id, deviceId, customerCtx), 200);
    await runOpsTo(program.program_id, opsCtx, 15);

    const res = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectError(res, 400, 'ERR_CLAIM_NOT_ELIGIBLE');
    expect(res.body?.claim_id).toBeUndefined();
  });

  test('CLM_005: approved REPLACEMENT claim without inbound expires on next ops run close', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, paymentId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: true
    });

    const createRes = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(createRes, 201);
    const claimId = createRes.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);

    await runOps(program.program_id, opsCtx);

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('EXPIRED');
    expect(cl.replacement_device_id).toBeNull();

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');
  });

  test('CLM_006: inbound claim that is not received expires at the second close after inbound', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: true
    });

    const createRes = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(createRes, 201);
    const claimId = createRes.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);

    await runOps(program.program_id, opsCtx);

    await runOps(program.program_id, opsCtx);

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('EXPIRED');
    expect(cl.replacement_device_id).toBeNull();

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });

  test('CLM_007: canceling an OPEN claim succeeds and has no balance side effects', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: true
    });

    const before = await getCustomer(program.program_id, customer.customer_id, ops);

    const createRes = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(createRes, 201);
    const claimId = createRes.body.claim_id as string;

    const cancelRes = await cancelClaim(program.program_id, claimId, supCtx, 'duplicate request');
    expectSuccess(cancelRes, 200);
    expect(cancelRes.body.claim_status).toBe('CANCELED');
    expect(cancelRes.body.replacement_device_id).toBeNull();

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('CANCELED');
    expect(cl.replacement_device_id).toBeNull();

    const after = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(after.balance_due_cents).toBe(before.balance_due_cents);
    expect(after.credit_balance_cents).toBe(before.credit_balance_cents);
  });

  test('CLM_008: canceling ADVANCE_SHIPPED claim fails ERR_INVALID_STATE_TRANSITION and preserves deposit + replacement', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, delivered, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 10,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const createRes = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(createRes, 201);
    const claimId = createRes.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN999',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);
    expect(shipRes.body.claim_status).toBe('ADVANCE_SHIPPED');
    const replacementDeviceId = shipRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const custAfterShip = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(custAfterShip.customer_status).toBe('LIMITED');
    expect(custAfterShip.balance_due_cents).toBeGreaterThanOrEqual(15000);

    const cancelRes = await cancelClaim(program.program_id, claimId, supCtx, 'cannot cancel after shipment');
    expectError(cancelRes, 400, 'ERR_INVALID_STATE_TRANSITION');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
    expect(cl.replacement_device_id).toBe(replacementDeviceId);

    const custAfterCancel = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(custAfterCancel.balance_due_cents).toBe(custAfterShip.balance_due_cents);

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });

  test('CLMPOST_001: completing a claim while PROGRAM_GUARDED returns ERR_PROGRAM_REVIEW_REQUIRED and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: true
    });

    expectSuccess(await disputePayment(program.program_id, delivered.payment_id as string, supCtx), 200);
    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');
    const availableBefore = pGuarded.available_to_commit_units;

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const cl0 = await getClaim(program.program_id, claimId, ops);
    expect(cl0.claim_status).toBe('RECEIVED');
    expect(cl0.replacement_device_id).toBeNull();

    const o0 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o0.order_status).toBe('DELIVERED');
    expect(o0.device_id).toBe(deviceId);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-CLM-G',
      replacement_build_tag: 'B99Z'
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

    const cl1 = await getClaim(program.program_id, claimId, ops);
    expect(cl1.claim_status).toBe('RECEIVED');
    expect(cl1.replacement_device_id).toBeNull();

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(deviceId);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_GUARDED');
    expect(p1.available_to_commit_units).toBe(availableBefore);
  });

  test('CLMPOST_002: completing a claim while PROGRAM_FROZEN (manual) returns ERR_PROGRAM_FROZEN and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: true,
      activate: true
    });

    const freeze = await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect(freeze.program_posture).toBe('PROGRAM_FROZEN');
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');
    const availableBefore = pFrozen.available_to_commit_units;

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'CARE_PLAN');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'REFURB'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-CLM-F',
      replacement_build_tag: 'B99Z'
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_FROZEN');

    const cl1 = await getClaim(program.program_id, claimId, ops);
    expect(cl1.claim_status).toBe('RECEIVED');
    expect(cl1.replacement_device_id).toBeNull();

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(deviceId);

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_FROZEN');
    expect(p1.available_to_commit_units).toBe(availableBefore);
  });

  test('CLM_009: shipping advance replacement applies deposit, holds other orders, updates delivered order device_id, and keeps program frozen', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, delivered, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: true,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    const o2Id = await createSubmittedOrder({ program_id: program.program_id, customer_id: customer.customer_id, customerCtx: (await createCustomerCtx(program.program_id, customer.customer_id)).ctx });
    const o2Before = await getOrder(program.program_id, o2Id, ops);
    expect(o2Before.order_status).toBe('SUBMITTED');

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');
    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN999',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);
    expect(shipRes.body.claim_status).toBe('ADVANCE_SHIPPED');
    const replacementDeviceId = shipRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
    expect(cl.replacement_device_id).toBe(replacementDeviceId);

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(replacementDeviceId);

    const cAfter = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(15000);
    expect(cAfter.customer_status).toBe('LIMITED');

    const o2After = await getOrder(program.program_id, o2Id, ops);
    expect(o2After.order_status).toBe('ON_HOLD');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('CLM_010: advance replacements do not expire on first ops run close after shipping; no overdue alert yet', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);
    expectSuccess(
      await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: replacementLot.build_lot_id,
        replacement_serial_number: 'SN-ADV-1',
        replacement_build_tag: 'B99Z'
      }),
      200
    );

    const cl0 = await getClaim(program.program_id, claimId, ops);
    expect(cl0.claim_status).toBe('ADVANCE_SHIPPED');

    await runOps(program.program_id, opsCtx);

    const cl1 = await getClaim(program.program_id, claimId, ops);
    expect(cl1.claim_status).toBe('ADVANCE_SHIPPED');

    const c1 = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(c1.customer_status).toBe('LIMITED');

    const overdue = await listAlerts(program.program_id, ops, { alert_type: 'AFTERCARE_OVERDUE', alert_status: 'OPEN', claim_id: claimId, customer_id: customer.customer_id });
    expect(overdue.alerts.length).toBe(0);
  });

  test('CLM_011: second ops run close after advance shipment locks customer and opens AFTERCARE_OVERDUE alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);
    expectSuccess(
      await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: replacementLot.build_lot_id,
        replacement_serial_number: 'SN-ADV-2',
        replacement_build_tag: 'B99Z'
      }),
      200
    );

    await runOps(program.program_id, opsCtx);

    await runOps(program.program_id, opsCtx);

    const c1 = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(c1.customer_status).toBe('LOCKED');
    expect(c1.balance_due_cents).toBeGreaterThanOrEqual(15000);

    const overdue = await listAlerts(program.program_id, ops, { alert_type: 'AFTERCARE_OVERDUE', alert_status: 'OPEN', claim_id: claimId, customer_id: customer.customer_id });
    expect(overdue.alerts.length).toBe(1);
    expect(overdue.alerts[0].claim_id).toBe(claimId);
    expect(overdue.alerts[0].customer_id).toBe(customer.customer_id);

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
  });

  test('CLM_012: completing RECEIVED advance replacement releases deposit to balance_due first and does not auto-unlock', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);
    expectSuccess(
      await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: replacementLot.build_lot_id,
        replacement_serial_number: 'SN-ADV-3',
        replacement_build_tag: 'B99Z'
      }),
      200
    );

    await runOps(program.program_id, opsCtx);
    await runOps(program.program_id, opsCtx);

    await createAndApplyBalanceDue(program.program_id, customer.customer_id, supCtx, 5000);
    const cPre = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(cPre.balance_due_cents).toBe(20000);
    expect(cPre.customer_status).toBe('LOCKED');

    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);
    const clReceived = await getClaim(program.program_id, claimId, ops);
    expect(clReceived.claim_status).toBe('RECEIVED');

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);
    expect(completeRes.body.claim_status).toBe('COMPLETED');

    const cPost = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(cPost.balance_due_cents).toBe(5000);
    expect(cPost.credit_balance_cents).toBe(0);
    expect(cPost.customer_status).toBe('LOCKED');

    const overdue = await listAlerts(program.program_id, ops, { alert_type: 'AFTERCARE_OVERDUE', alert_status: 'OPEN', claim_id: claimId, customer_id: customer.customer_id });
    expect(overdue.alerts.length).toBe(1);
  });

  test('CLM_013: completing claim replacement uses reserve when available_to_commit_units=0 and care plan follows to PENDING_ACTIVATION', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, carePlanId, lot, paymentId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: true,
      activate: true
    });
    expect(carePlanId).toBeTruthy();

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const cp0 = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp0.care_plan_status).toBe('ACTIVE');

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-R-1',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(completeRes, 200);
    expect(completeRes.body.claim_status).toBe('COMPLETED');
    const replacementDeviceId = completeRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('COMPLETED');
    expect(cl.replacement_device_id).toBe(replacementDeviceId);

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(replacementDeviceId);

    const dOld = await getDevice(program.program_id, deviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN-R-1');
    expect(dNew.build_tag).toBe('B99Z');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const cp1 = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp1.device_id).toBe(replacementDeviceId);
    expect(cp1.care_plan_status).toBe('PENDING_ACTIVATION');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(0);
  });

  test('CLM_014: once reserve depleted, completing claim replacement either consumes sale inventory (available_to_commit_units decreases) or fails with ERR_OUT_OF_STOCK', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId: initialDeviceId, carePlanId, lot, customerCtx } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 8,
      include_care_plan: true,
      activate: true
    });
    expect(carePlanId).toBeTruthy();

    let currentDeviceId = initialDeviceId;
    for (let i = 0; i < 5; i++) {
      const c = await createClaim(program.program_id, currentDeviceId, supCtx, 'WARRANTY');
      expectSuccess(c, 201);
      const claimId = c.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
      expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
      expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

      const repRes = await completeClaim(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: lot.build_lot_id,
        replacement_serial_number: `SN-BURN-${i}`,
        replacement_build_tag: 'B99Z'
      });
      expectSuccess(repRes, 200);
      currentDeviceId = repRes.body.replacement_device_id as string;
      expect(currentDeviceId).toBeTruthy();
      expectSuccess(await activateDevice(program.program_id, currentDeviceId, customerCtx), 200);
    }

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(2);

    const claimCreate = await createClaim(program.program_id, currentDeviceId, supCtx, 'CARE_PLAN');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'REFURB'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-R-2',
      replacement_build_tag: 'B99Z'
    });

    if (completeRes.status === 200) {

      const replacementDeviceId = completeRes.body.replacement_device_id as string;
      expect(replacementDeviceId).toBeTruthy();

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(1);

      const o1 = await getOrder(program.program_id, delivered.order_id, ops);
      expect(o1.order_status).toBe('DELIVERED');
      expect(o1.device_id).toBe(replacementDeviceId);

      const pm = await getPayment(program.program_id, delivered.payment_id as string, ops);
      expect(pm.payment_status).toBe('CAPTURED');

      const cl = await getClaim(program.program_id, claimId, ops);
      expect(cl.claim_status).toBe('COMPLETED');
      expect(cl.replacement_device_id).toBe(replacementDeviceId);
    } else {

      expectError(completeRes, 400, 'ERR_OUT_OF_STOCK');

      const cl = await getClaim(program.program_id, claimId, ops);
      expect(cl.claim_status).toBe('RECEIVED');
      expect(cl.replacement_device_id).toBeNull();

      const o1 = await getOrder(program.program_id, delivered.order_id, ops);
      expect(o1.order_status).toBe('DELIVERED');
      expect(o1.device_id).toBe(currentDeviceId);

      const pm = await getPayment(program.program_id, delivered.payment_id as string, ops);
      expect(pm.payment_status).toBe('CAPTURED');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(2);
    }
  });

  test('CLM_015: warranty follows replacement device; claim on replacement succeeds even if original warranty expired', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customerCtx, carePlanId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 10,
      include_care_plan: true,
      activate: false
    });
    expect(carePlanId).toBeTruthy();

    await runOpsTo(program.program_id, opsCtx, 3);
    expectSuccess(await activateDevice(program.program_id, deviceId, customerCtx), 200);

    await runOpsTo(program.program_id, opsCtx, 15);

    const cp = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp.care_plan_status).toBe('ACTIVE');

    const claim1 = await createClaim(program.program_id, deviceId, supCtx, 'CARE_PLAN');
    expectSuccess(claim1, 201);
    const claim1Id = claim1.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claim1Id, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claim1Id, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claim1Id, opsCtx, 'REFURB'), 200);
    const complete1 = await completeClaim(program.program_id, claim1Id, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-REP-15',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(complete1, 200);
    const d2 = complete1.body.replacement_device_id as string;
    expect(d2).toBeTruthy();

    expectSuccess(await activateDevice(program.program_id, d2, customerCtx), 200);

    await runOpsTo(program.program_id, opsCtx, 26);

    const claim2 = await createClaim(program.program_id, d2, supCtx, 'WARRANTY');
    expectSuccess(claim2, 201);
    expect(claim2.body.claim_status).toBe('OPEN');
    expect(claim2.body.claim_type).toBe('WARRANTY');
    expect(claim2.body.device_id).toBe(d2);
  });

  test('CLM_016: if deposit is already settled, completion releases deposit as credit and does not change standing automatically', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, customerCtx, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);
    expectSuccess(
      await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: replacementLot.build_lot_id,
        replacement_serial_number: 'SN-ADV-SETTLE',
        replacement_build_tag: 'B99Z'
      }),
      200
    );

    const c1 = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(c1.customer_status).toBe('LIMITED');
    expect(c1.balance_due_cents).toBe(15000);
    expect(c1.credit_balance_cents).toBe(0);

    const settled = await settleBalanceDue(program.program_id, customer.customer_id, customerCtx, 15000);
    expect(settled.balance_due_cents).toBe(0);
    const cAfterSettle = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(cAfterSettle.balance_due_cents).toBe(0);
    expect(cAfterSettle.customer_status).toBe('LIMITED');

    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);
    expect(completeRes.body.claim_status).toBe('COMPLETED');

    const cFinal = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(cFinal.balance_due_cents).toBe(0);
    expect(cFinal.credit_balance_cents).toBe(15000);
    expect(cFinal.customer_status).toBe('LIMITED');
  });

  test('CLM_019: PROGRAM_FROZEN (recall) blocks completing a non-recall replacement claim with ERR_PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, paymentId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 12,
      include_care_plan: false,
      activate: true
    });

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-NONRECALL-CLM-1',
      replacement_build_tag: 'B99Z'
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_FROZEN');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('RECEIVED');
    expect(cl.replacement_device_id).toBeNull();

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(deviceId);

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');
  });

  test('CLM_021: ship_advance_replacement on APPROVED REPLACEMENT claim fails ERR_INVALID_STATE_TRANSITION and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId, customer, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    const o2Id = await createSubmittedOrder({ program_id: program.program_id, customer_id: customer.customer_id, customerCtx: (await createCustomerCtx(program.program_id, customer.customer_id)).ctx });
    const o2Before = await getOrder(program.program_id, o2Id, ops);
    expect(o2Before.order_status).toBe('SUBMITTED');

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    const approved = await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT');
    expectSuccess(approved, 200);
    expect(approved.body.claim_resolution).toBe('REPLACEMENT');

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN-NO-ADV-1',
      replacement_build_tag: 'B99Z'
    });
    expectError(shipRes, 400, 'ERR_INVALID_STATE_TRANSITION');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('APPROVED');
    expect(cl.claim_resolution).toBe('REPLACEMENT');
    expect(cl.replacement_device_id).toBeNull();

    const c1 = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(c1.balance_due_cents).toBe(0);
    expect(c1.customer_status).toBe('ACTIVE');

    const o2After = await getOrder(program.program_id, o2Id, ops);
    expect(o2After.order_status).toBe('SUBMITTED');
  });

  test('CLM_023: recall REPLACEMENT workflow completes without deposit effects; order device switches; care plan stays PAUSED; program stays FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, carePlanId, customer, paymentId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: true,
      activate: true
    });
    expect(carePlanId).toBeTruthy();
    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    const o2Id = await createSubmittedOrder({ program_id: program.program_id, customer_id: customer.customer_id, customerCtx: (await createCustomerCtx(program.program_id, customer.customer_id)).ctx });
    const o2Before = await getOrder(program.program_id, o2Id, ops);
    expect(o2Before.order_status).toBe('SUBMITTED');

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;

    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN-RECALL-NOADV-1',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(completeRes, 200);
    const replacementDeviceId = completeRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('COMPLETED');
    expect(cl.replacement_device_id).toBe(replacementDeviceId);

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(replacementDeviceId);
    expect(o1.payment_id).toBe(paymentId);

    const dOld = await getDevice(program.program_id, deviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN-RECALL-NOADV-1');
    expect(dNew.build_tag).toBe('B99Z');

    const c1 = await getCustomer(program.program_id, customer.customer_id, ops);
    expect(c1.balance_due_cents).toBe(0);
    expect(c1.customer_status).toBe('ACTIVE');

    const o2After = await getOrder(program.program_id, o2Id, ops);
    expect(o2After.order_status).toBe('SUBMITTED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cpAfter.device_id).toBe(replacementDeviceId);
    expect(cpAfter.care_plan_status).toBe('PAUSED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('CLM_024: completing a CARE_PLAN replacement with REFURB sets original device RETURNED, updates order+care plan, and preserves capacity when available_to_commit_units=0', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, carePlanId, paymentId, lot } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: true,
      activate: true
    });
    expect(carePlanId).toBeTruthy();

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'CARE_PLAN');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'REFURB'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN-CLM-REFURB-1',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(completeRes, 200);
    const replacementDeviceId = completeRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('COMPLETED');
    expect(cl.replacement_device_id).toBe(replacementDeviceId);
    expect(cl.inspection_outcome).toBe('REFURB');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
    expect(o1.device_id).toBe(replacementDeviceId);
    expect(o1.payment_id).toBe(paymentId);

    const dOld = await getDevice(program.program_id, deviceId, ops);
    expect(dOld.device_status).toBe('RETURNED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN-CLM-REFURB-1');
    expect(dNew.build_tag).toBe('B99Z');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cpAfter.device_id).toBe(replacementDeviceId);
    expect(cpAfter.care_plan_status).toBe('PENDING_ACTIVATION');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(0);
  });

  test('CLMFRZ_001: run_ops in PROGRAM_FROZEN expires stale APPROVED claim and keeps program frozen', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: true
    });

    const p0 = await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect(p0.program_posture).toBe('PROGRAM_FROZEN');
    const n = p0.ops_run_index;

    const createRes = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(createRes, 201);
    const claimId = createRes.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);

    const pAfter = await runOps(program.program_id, opsCtx);
    expect(pAfter.ops_run_index).toBe(n + 1);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('EXPIRED');
    expect(cl.replacement_device_id).toBeNull();

    const o = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o.order_status).toBe('DELIVERED');
    expect(o.device_id).toBe(deviceId);
  });

  test('WARR_001: warranty window is ops-run based; valid through 31 after activation at 20, then ineligible at 32', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { delivered, deviceId, customerCtx } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'B99Z',
      units: 6,
      include_care_plan: false,
      activate: false
    });

    await runOpsTo(program.program_id, opsCtx, 20);
    expectSuccess(await activateDevice(program.program_id, deviceId, customerCtx), 200);
    const dActive = await getDevice(program.program_id, deviceId, ops);
    expect(dActive.device_status).toBe('ACTIVE');

    await runOpsTo(program.program_id, opsCtx, 31);

    const claimCreate = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expect(claimCreate.body.claim_status).toBe('OPEN');
    expect(claimCreate.body.claim_type).toBe('WARRANTY');
    expect(claimCreate.body.device_id).toBe(deviceId);

    const cancelRes = await cancelClaim(program.program_id, claimId, supCtx, 'test cleanup');
    expectSuccess(cancelRes, 200);
    expect(cancelRes.body.claim_status).toBe('CANCELED');

    const p32 = await runOps(program.program_id, opsCtx);
    expect(p32.ops_run_index).toBe(32);

    const res2 = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectError(res2, 400, 'ERR_CLAIM_NOT_ELIGIBLE');

    const pFinal = await getProgram(program.program_id, ops);
    expect(pFinal.ops_run_index).toBe(32);
    const dFinal = await getDevice(program.program_id, deviceId, ops);
    expect(dFinal.device_status).toBe('ACTIVE');

    const o1 = await getOrder(program.program_id, delivered.order_id, ops);
    expect(o1.order_status).toBe('DELIVERED');
  });
});
