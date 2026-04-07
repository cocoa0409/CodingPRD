import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  approveReturn,
  applyAdjustment,
  completeClaim,
  completeReturn,
  createAdjustment,
  createBuildLot,
  createClaim,
  createCustomer,
  createCustomerCtx,
  createDeliveredOrder,
  createOpsCtx,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSupportCtx,
  disputePayment,
  freezeProgram,
  getAlert,
  getCarePlan,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  listOrders,
  lockCustomer,
  markInboundClaim,
  markInboundReturn,
  receiveClaim,
  receiveReturn,
  runOps,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 11: Returns: Workflow, Refund Allocation & Replacement Inventory (v1)', () => {
  async function createAndApplyAdjustment(args: {
    program_id: string;
    customer_id: string;
    supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
    adjustment_type: 'GOODWILL_CREDIT' | 'WRITE_OFF' | 'CREDIT_CLAWBACK';
    amount_cents: number;
  }) {
    const createRes = await createAdjustment(args.program_id, args.customer_id, args.supportCtx, args.adjustment_type, args.amount_cents);
    expectSuccess(createRes, 201);
    const adjustmentId = createRes.body.adjustment_id as string;
    expectSuccess(await applyAdjustment(args.program_id, adjustmentId, args.supportCtx), 200);
    return adjustmentId;
  }

  async function createReturnToInbound(args: {
    program_id: string;
    order_id: string;
    createCtx: { actor_id: string; actor_type: 'Customer' | 'Support'; session_id: string };
    supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
    resolution_preference: 'REFUND' | 'REPLACEMENT';
  }) {
    const rCreate = await createReturn(args.program_id, args.order_id, args.createCtx, args.resolution_preference);
    expectSuccess(rCreate, 201);
    const returnId = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(args.program_id, returnId, args.supportCtx), 200);
    expectSuccess(await markInboundReturn(args.program_id, returnId, args.supportCtx), 200);
    return returnId;
  }

  async function createReturnToReceived(args: {
    program_id: string;
    order_id: string;
    createCtx: { actor_id: string; actor_type: 'Customer' | 'Support'; session_id: string };
    supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string };
    opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
    resolution_preference: 'REFUND' | 'REPLACEMENT';
    inspection_outcome: 'RESTOCK' | 'REFURB' | 'SCRAP';
  }) {
    const returnId = await createReturnToInbound({
      program_id: args.program_id,
      order_id: args.order_id,
      createCtx: args.createCtx,
      supportCtx: args.supportCtx,
      resolution_preference: args.resolution_preference
    });
    expectSuccess(await receiveReturn(args.program_id, returnId, args.opsCtx, args.inspection_outcome), 200);
    return returnId;
  }

  test('RET_001: delivered + not-activated device can request REFUND return (inventory unchanged)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
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
    const pBefore = await getProgram(program.program_id, ops);

    const res = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectSuccess(res, 201);
    const r1 = res.body;
    expect(r1.return_status).toBe('REQUESTED');
    expect(r1.order_id).toBe(o1.order_id);
    expect(r1.device_id).toBe(deviceId);
    expect(r1.customer_id).toBe(c1.customer_id);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('RET_002: activated non-quarantined device cannot request return (ERR_RETURN_NOT_ELIGIBLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
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
    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const res = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectError(res, 400, 'ERR_RETURN_NOT_ELIGIBLE');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('ACTIVE');

    const res2 = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectError(res2, 400, 'ERR_RETURN_NOT_ELIGIBLE');
  });

  test('RET_003: recall-quarantined device can request return even if activated; program stays FROZEN and device stays QUARANTINED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
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
    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const res = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectSuccess(res, 201);
    expect(res.body.return_status).toBe('REQUESTED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');
  });

  test('RET_004: cannot create a second non-terminal return for the same order (ERR_RETURN_NOT_ELIGIBLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
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

    const r1 = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REFUND');
    expectSuccess(r1, 201);
    const returnId = r1.body.return_id as string;
    const before = await getReturn(program.program_id, returnId, ops);
    expect(before.return_status).toBe('REQUESTED');

    const r2 = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REPLACEMENT');
    expectError(r2, 400, 'ERR_RETURN_NOT_ELIGIBLE');

    const after = await getReturn(program.program_id, returnId, ops);
    expect(after.return_status).toBe('REQUESTED');
  });

  test('RET_005: receiving an eligible return as RESTOCK moves to RECEIVED and increases available_to_commit_units by 1', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
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

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const returnId = await createReturnToInbound({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      resolution_preference: 'REFUND'
    });

    const res = await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK');
    expectSuccess(res, 200);

    const r = await getReturn(program.program_id, returnId, ops);
    expect(r.return_status).toBe('RECEIVED');
    expect(r.inspection_outcome).toBe('RESTOCK');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(1);
  });

  test('RET_006: receiving RESTOCK on an activated device is invalid (ERR_INVALID_REQUEST) and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
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

    const returnId = await createReturnToInbound({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      resolution_preference: 'REFUND'
    });

    expectSuccess(await activateDevice(program.program_id, o1.device_id as string, c1Ctx), 200);

    const p0 = await getProgram(program.program_id, ops);
    const res = await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK');
    expectError(res, 400, 'ERR_INVALID_REQUEST');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('INBOUND');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(p0.available_to_commit_units);
  });

  test('RET_007: receiving RESTOCK on a quarantined device is invalid (ERR_INVALID_REQUEST) and makes no changes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
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

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const returnId = await createReturnToInbound({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      resolution_preference: 'REFUND'
    });

    const p0 = await getProgram(program.program_id, ops);
    const res = await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK');
    expectError(res, 400, 'ERR_INVALID_REQUEST');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('INBOUND');
    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(p0.available_to_commit_units);
  });

  test('RETCAP_001: RESTOCK at receive increases available_to_commit once; completing refund does not increase it again', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false,
      use_credit_cents: 20000
    });
    expect(o1.paid_by_credit_cents).toBe(20000);
    expect(o1.paid_by_card_cents).toBe(59900);
    const paymentId = o1.payment_id as string;
    const deviceId = o1.device_id as string;

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const returnId = await createReturnToInbound({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      resolution_preference: 'REFUND'
    });

    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'RESTOCK'), 200);
    const rAfterReceive = await getReturn(program.program_id, returnId, ops);
    expect(rAfterReceive.return_status).toBe('RECEIVED');
    expect(rAfterReceive.inspection_outcome).toBe('RESTOCK');
    const pAfterReceive = await getProgram(program.program_id, ops);
    expect(pAfterReceive.available_to_commit_units).toBe(1);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(59900);
    expect(rDone.refunded_to_credit_cents).toBe(20000);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('REFUNDED');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('RETURNED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);
  });

  test('RETCLM_001: open claim blocks return creation (ERR_RETURN_NOT_ELIGIBLE) and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
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

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);
    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const claimRes = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimRes, 201);
    const claimId = claimRes.body.claim_id as string;

    const attempt = await createReturn(program.program_id, o1.order_id, supCtx, 'REFUND');
    expectError(attempt, 400, 'ERR_RETURN_NOT_ELIGIBLE');

    const clAfter = await getClaim(program.program_id, claimId, ops);
    expect(clAfter.claim_status).toBe('OPEN');
    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');

    const list = await listOrders(program.program_id, ops, { customer_id: c1.customer_id, order_status: 'DELIVERED' });
    expect(list.orders.length).toBe(1);
    expect(list.orders[0].order_id).toBe(o1.order_id);
  });

  test('RETPOST_001: completing refund while PROGRAM_FROZEN (manual) is allowed cleanup; refunds and voids care plan', async () => {

    const program = await createProgram({ care_plan_price_cents: 0 });
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      use_credit_cents: 20000
    });
    expect(o1.paid_by_credit_cents).toBe(20000);
    expect(o1.paid_by_card_cents).toBe(59900);
    const carePlanId = o1.care_plan_id as string;
    const paymentId = o1.payment_id as string;
    const deviceId = o1.device_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });

    const freezeRes = await freezeProgram(program.program_id, opsCtx, 'manual freeze');
    expect(freezeRes.program_posture).toBe('PROGRAM_FROZEN');

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(59900);
    expect(rDone.refunded_to_credit_cents).toBe(20000);

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('REFUNDED');

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('REFUNDED');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('RETURNED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('VOIDED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('RET_008: refund returns credit balance-due-first and records only minted credit as refunded_to_credit_cents', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: true,
      use_credit_cents: 20000
    });
    expect(o1.paid_by_credit_cents).toBe(20000);
    expect(o1.paid_by_card_cents).toBe(69800);
    const paymentId = o1.payment_id as string;
    const deviceId = o1.device_id as string;
    const carePlanId = o1.care_plan_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'CREDIT_CLAWBACK',
      amount_cents: 10000
    });
    const cBefore = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cBefore.balance_due_cents).toBe(10000);
    expect(cBefore.credit_balance_cents).toBe(0);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(69800);
    expect(rDone.refunded_to_credit_cents).toBe(10000);

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('REFUNDED');
    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('REFUNDED');

    const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cAfter.balance_due_cents).toBe(0);
    expect(cAfter.credit_balance_cents).toBe(10000);

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('RETURNED');
    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('VOIDED');
  });

  test('RET_009: replacement completion ships new device, scraps original on SCRAP, keeps payment CAPTURED, and preserves capacity (reserve)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false
    });
    const origDeviceId = o1.device_id as string;
    const paymentId = o1.payment_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const pBefore = await getProgram(program.program_id, ops);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN999',
      replacement_build_tag: repLot.build_tag
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.replacement_device_id).toBeTruthy();
    expect(rDone.refunded_to_card_cents).toBe(0);
    expect(rDone.refunded_to_credit_cents).toBe(0);
    const replacementDeviceId = rDone.replacement_device_id as string;

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementDeviceId);

    const dOld = await getDevice(program.program_id, origDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN999');

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('RET_010: cannot complete replacement when inspection_outcome=RESTOCK (ERR_RETURN_NOT_RESOLVABLE)', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false
    });

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'RESTOCK'
    });
    const p0 = await getProgram(program.program_id, ops);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN900',
      replacement_build_tag: repLot.build_tag
    });
    expectError(completeRes, 400, 'ERR_RETURN_NOT_RESOLVABLE');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.device_id).toBe(o1.device_id);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(p0.available_to_commit_units);
  });

  test('RET_011: replacement can succeed at available_to_commit_units=0 while reserve remains; capacity stays 0', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
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
    const origDeviceId = o1.device_id as string;
    const paymentId = o1.payment_id as string;
    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN901',
      replacement_build_tag: lot.build_tag
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.replacement_device_id).toBeTruthy();
    const replacementDeviceId = rDone.replacement_device_id as string;

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementDeviceId);

    const dOld = await getDevice(program.program_id, origDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN901');
    expect(dNew.build_tag).toBe(lot.build_tag);

    const pm = await getPayment(program.program_id, paymentId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('RET_012: once reserve depleted, replacement consumes sale inventory and decreases available_to_commit_units by 1', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 9);

    const cBurn = await createCustomer(program.program_id, opsCtx);
    const { ctx: cBurnCtx } = await createCustomerCtx(program.program_id, cBurn.customer_id);
    const oBurn = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: cBurn.customer_id,
      customerCtx: cBurnCtx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false
    });
    let currentDeviceId = oBurn.device_id as string;
    expectSuccess(await activateDevice(program.program_id, currentDeviceId, cBurnCtx), 200);
    for (let i = 0; i < 5; i++) {
      const c = await createClaim(program.program_id, currentDeviceId, supCtx, 'WARRANTY');
      expectSuccess(c, 201);
      const claimId = c.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
      expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
      expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

      const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
        replacement_build_lot_id: lot.build_lot_id,
        replacement_serial_number: `SN-BURN-${i}-${uniqueId('sn')}`,
        replacement_build_tag: lot.build_tag
      });
      expectSuccess(completeRes, 200);
      currentDeviceId = completeRes.body.replacement_device_id as string;
      expect(currentDeviceId).toBeTruthy();
      expectSuccess(await activateDevice(program.program_id, currentDeviceId, cBurnCtx), 200);
    }

    const pAfterBurn = await getProgram(program.program_id, ops);
    expect(pAfterBurn.available_to_commit_units).toBe(3);

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
    const origDeviceId = o1.device_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const pBefore = await getProgram(program.program_id, ops);
    expect(pBefore.available_to_commit_units).toBe(2);

    const complete = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: lot.build_lot_id,
      replacement_serial_number: 'SN902',
      replacement_build_tag: lot.build_tag
    });
    expectSuccess(complete, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(0);
    expect(rDone.refunded_to_credit_cents).toBe(0);
    const replacementDeviceId = rDone.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementDeviceId);

    const dOld = await getDevice(program.program_id, origDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(1);
  });

  test('RET_013: completing recall replacement keeps program frozen; care plan stays PAUSED and follows to replacement device', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: true
    });
    const origDeviceId = o1.device_id as string;
    const carePlanId = o1.care_plan_id as string;
    expectSuccess(await activateDevice(program.program_id, origDeviceId, c1Ctx), 200);

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);

    const dQ = await getDevice(program.program_id, origDeviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');
    const cpPaused = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-REC-REP-1',
      replacement_build_tag: repLot.build_tag
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(0);
    expect(rDone.refunded_to_credit_cents).toBe(0);
    const replacementDeviceId = rDone.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementDeviceId);

    const dOld = await getDevice(program.program_id, origDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');
    const dNew = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(dNew.device_status).toBe('SHIPPED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.device_id).toBe(replacementDeviceId);
    expect(cpAfter.care_plan_status).toBe('PAUSED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('RET_014: completing refund while PROGRAM_GUARDED preserves unrelated OPEN alert and does not change capacity for REFURB', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 30);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 20000
    });
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false,
      use_credit_cents: 20000
    });
    expect(o1.paid_by_card_cents).toBe(59900);
    expect(o1.paid_by_credit_cents).toBe(20000);

    const c2 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);
    const oG = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c2.customer_id,
      customerCtx: c2Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false
    });
    const pmG = oG.payment_id as string;
    expect(pmG).toBeTruthy();
    expectSuccess(await disputePayment(program.program_id, pmG, supCtx), 200);

    const pGuarded = await getProgram(program.program_id, ops);
    expect(pGuarded.program_posture).toBe('PROGRAM_GUARDED');
    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'PAYMENT_DISPUTED', alert_status: 'OPEN', payment_id: pmG });
    expect(alerts.alerts.length).toBe(1);
    const alertId = alerts.alerts[0].alert_id;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });

    const pBefore = await getProgram(program.program_id, ops);
    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(59900);
    expect(rDone.refunded_to_credit_cents).toBe(20000);
    expect(rDone.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('REFUNDED');

    const pm1 = await getPayment(program.program_id, o1.payment_id as string, ops);
    expect(pm1.payment_status).toBe('REFUNDED');

    const custAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.credit_balance_cents).toBe(20000);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_GUARDED');
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);

    const alertAfter = await getAlert(program.program_id, alertId, ops);
    expect(alertAfter.alert_status).toBe('OPEN');
  });

  test('RET_015: refund on credit-only order returns credit and does not require a payment_id', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    await createAndApplyAdjustment({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      supportCtx: supCtx,
      adjustment_type: 'GOODWILL_CREDIT',
      amount_cents: 79900
    });

    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: lot.build_lot_id,
      build_tag: lot.build_tag,
      include_care_plan: false,
      use_credit_cents: 79900
    });
    expect(o1.paid_by_credit_cents).toBe(79900);
    expect(o1.paid_by_card_cents).toBe(0);
    expect(o1.payment_id).toBeNull();

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REFUND',
      inspection_outcome: 'REFURB'
    });
    const pBefore = await getProgram(program.program_id, ops);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REFUND',
      replacement_build_lot_id: null,
      replacement_serial_number: null,
      replacement_build_tag: null
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.refunded_to_card_cents).toBe(0);
    expect(rDone.refunded_to_credit_cents).toBe(79900);
    expect(rDone.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('REFUNDED');
    expect(oAfter.payment_id).toBeNull();

    const custAfter = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.credit_balance_cents).toBe(79900);

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(pBefore.available_to_commit_units);
  });

  test('RET_016: completing replacement while PROGRAM_FROZEN for unrelated recall fails ERR_PROGRAM_FROZEN and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false
    });
    const deviceId = o1.device_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');
    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-NONRECALL-1',
      replacement_build_tag: repLot.build_tag
    });
    expectError(completeRes, 400, 'ERR_PROGRAM_FROZEN');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(deviceId);

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('SHIPPED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('RET_017: completing replacement for a LOCKED customer fails ERR_CUSTOMER_LOCKED and preserves invariants', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const shipLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
    const o1 = await createDeliveredOrder({
      program_id: program.program_id,
      customer_id: c1.customer_id,
      customerCtx: c1Ctx,
      opsCtx,
      build_lot_id: shipLot.build_lot_id,
      build_tag: shipLot.build_tag,
      include_care_plan: false
    });
    const deviceId = o1.device_id as string;
    const paymentId = o1.payment_id as string;

    const returnId = await createReturnToReceived({
      program_id: program.program_id,
      order_id: o1.order_id,
      createCtx: c1Ctx,
      supportCtx: supCtx,
      opsCtx,
      resolution_preference: 'REPLACEMENT',
      inspection_outcome: 'SCRAP'
    });

    await lockCustomer(program.program_id, c1.customer_id, opsCtx, 'seed locked');
    const cLocked = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cLocked.customer_status).toBe('LOCKED');

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-LOCK-REP-1',
      replacement_build_tag: repLot.build_tag
    });
    expectError(completeRes, 400, 'ERR_CUSTOMER_LOCKED');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(deviceId);

    const pmAfter = await getPayment(program.program_id, paymentId, ops);
    expect(pmAfter.payment_status).toBe('CAPTURED');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('SHIPPED');
  });

  test('EXCL_001: approved-but-not-inbound recall claim expires at next ops run, allowing return creation under recall freeze', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lot = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
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

    const qcRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcRes, 201);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const claimRes = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(claimRes, 201);
    const claimId = claimRes.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);

    const clApproved = await getClaim(program.program_id, claimId, ops);
    expect(clApproved.claim_status).toBe('APPROVED');
    expect(clApproved.replacement_device_id).toBeNull();

    await runOps(program.program_id, opsCtx);
    const clExpired = await getClaim(program.program_id, claimId, ops);
    expect(clExpired.claim_status).toBe('EXPIRED');
    expect(clExpired.replacement_device_id).toBeNull();

    const retRes = await createReturn(program.program_id, o1.order_id, supCtx, 'REFUND');
    expectSuccess(retRes, 201);
    expect(retRes.body.return_status).toBe('REQUESTED');
    expect(retRes.body.order_id).toBe(o1.order_id);
    expect(retRes.body.device_id).toBe(deviceId);
    expect(retRes.body.customer_id).toBe(c1.customer_id);

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');
    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });
});
