import { post } from '../../../test-helpers/api-client';
import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  approveReturn,
  cancelClaim,
  completeClaim,
  completeReturn,
  createBuildLot,
  createClaim,
  createCustomer,
  createCustomerCtx,
  createOpsCtx,
  createOrder,
  createProgram,
  createSupportCtx,
  createQualityCampaign,
  getBuildLot,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  markDelivered,
  markInboundClaim,
  markInboundReturn,
  receiveClaim,
  receiveReturn,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  createReturn,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 17: Replacement Shipping & Build Lots (v1)', () => {
  test('LOTERR_001: completing replacement return from QUARANTINED lot fails ERR_BUILD_LOT_QUARANTINED with no side effects', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const quarantinedLot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17'), 201);
    const qLot = await getBuildLot(program.program_id, quarantinedLot.build_lot_id, ops);
    expect(qLot.build_lot_status).toBe('QUARANTINED');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
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
    expect(delivered.order_status).toBe('DELIVERED');
    const deviceId = delivered.device_id as string;

    const rCreate = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REPLACEMENT');
    expectSuccess(rCreate, 201);
    const returnId = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, opsCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const deviceBefore = await getDevice(program.program_id, deviceId, ops);
    const capBefore = await getProgram(program.program_id, ops);

    const res = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: quarantinedLot.build_lot_id,
      replacement_serial_number: 'SN-BAD-LOT-1',
      replacement_build_tag: quarantinedLot.build_tag
    });
    expectError(res, 400, 'ERR_BUILD_LOT_QUARANTINED');

    const rAfter = await getReturn(program.program_id, returnId, ops);
    expect(rAfter.return_status).toBe('RECEIVED');
    expect(rAfter.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(deviceId);

    const deviceAfter = await getDevice(program.program_id, deviceId, ops);
    expect(deviceAfter.device_status).toBe(deviceBefore.device_status);

    const lotAfter = await getBuildLot(program.program_id, quarantinedLot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const capAfter = await getProgram(program.program_id, ops);
    expect(capAfter.available_to_commit_units).toBe(capBefore.available_to_commit_units);
  });

  test('LOTERR_002: completing claim replacement from QUARANTINED lot fails ERR_BUILD_LOT_QUARANTINED with no side effects', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
    const quarantinedLot = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17'), 201);
    const qLot = await getBuildLot(program.program_id, quarantinedLot.build_lot_id, ops);
    expect(qLot.build_lot_status).toBe('QUARANTINED');

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
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
    const deviceId = delivered.device_id as string;
    const pmId = delivered.payment_id as string;
    const pmBefore = await getPayment(program.program_id, pmId, ops);
    expect(pmBefore.payment_status).toBe('CAPTURED');

    expectSuccess(await activateDevice(program.program_id, deviceId, c1Ctx), 200);

    const create = await createClaim(program.program_id, deviceId, supCtx, 'WARRANTY');
    expectSuccess(create, 201);
    const claimId = create.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const capBefore = await getProgram(program.program_id, ops);

    const res = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: quarantinedLot.build_lot_id,
      replacement_serial_number: 'SN-BAD-CLM-1',
      replacement_build_tag: quarantinedLot.build_tag
    });
    expectError(res, 400, 'ERR_BUILD_LOT_QUARANTINED');

    const clAfter = await getClaim(program.program_id, claimId, ops);
    expect(clAfter.claim_status).toBe('RECEIVED');
    expect(clAfter.replacement_device_id).toBeNull();

    const oAfter = await getOrder(program.program_id, o1.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(deviceId);

    const pmAfter = await getPayment(program.program_id, pmId, ops);
    expect(pmAfter.payment_status).toBe('CAPTURED');

    const lotAfter = await getBuildLot(program.program_id, quarantinedLot.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const capAfter = await getProgram(program.program_id, ops);
    expect(capAfter.available_to_commit_units).toBe(capBefore.available_to_commit_units);
  });

  test('LOTERR_003: ship_advance_replacement from QUARANTINED lot fails ERR_BUILD_LOT_QUARANTINED even while PROGRAM_FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 7);
    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lotA17.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lotA17.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    expect(delivered.order_status).toBe('DELIVERED');
    const deviceId = delivered.device_id as string;

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17'), 201);
    const lotQ = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotQ.build_lot_status).toBe('QUARANTINED');
    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const create = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(create, 201);
    const claimId = create.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: lotA17.build_lot_id,
      replacement_serial_number: 'SN-BAD-ADV-1',
      replacement_build_tag: lotA17.build_tag
    });
    expectError(shipRes, 400, 'ERR_BUILD_LOT_QUARANTINED');

    const clAfter = await getClaim(program.program_id, claimId, ops);
    expect(clAfter.claim_status).toBe('APPROVED');
    expect(clAfter.replacement_device_id).toBeNull();

    const cust = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cust.customer_status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(0);

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('SUBMITTED');

    const lotAfter = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('LOTERR_004: replacement_build_tag mismatch with lot either fails or succeeds with device.build_tag matching lot', async () => {

    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'B88X', 6);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
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
    const originalDeviceId = delivered.device_id as string;

    const rCreate = await createReturn(program.program_id, delivered.order_id, c1Ctx, 'REPLACEMENT');
    expectSuccess(rCreate, 201);
    const returnId = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, opsCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const capBefore = await getProgram(program.program_id, ops);

    const res = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-TAG-MISMATCH-1',
      replacement_build_tag: 'C01X'
    });

    if (res.status === 400) {

      expect(res.body?.error?.code).toBe('ERR_INVALID_REQUEST');

      const rAfter = await getReturn(program.program_id, returnId, ops);
      expect(rAfter.return_status).toBe('RECEIVED');
      expect(rAfter.replacement_device_id).toBeNull();

      const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
      expect(oAfter.order_status).toBe('DELIVERED');
      expect(oAfter.device_id).toBe(originalDeviceId);

      const lotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
      expect(lotAfter.build_lot_status).toBe('AVAILABLE');

      const capAfter = await getProgram(program.program_id, ops);
      expect(capAfter.available_to_commit_units).toBe(capBefore.available_to_commit_units);
    } else {

      expect(res.status).toBe(200);

      const rAfter = await getReturn(program.program_id, returnId, ops);
      expect(rAfter.return_status).toBe('COMPLETED');
      expect(rAfter.replacement_device_id).toBeTruthy();

      const replacementDeviceId = rAfter.replacement_device_id as string;
      const replacementDevice = await getDevice(program.program_id, replacementDeviceId, ops);

      expect(replacementDevice.build_tag).toBe(repLot.build_tag);
      expect(replacementDevice.serial_number).toBe('SN-TAG-MISMATCH-1');

      const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
      expect(oAfter.order_status).toBe('DELIVERED');
      expect(oAfter.device_id).toBe(replacementDeviceId);
    }
  });

  test('LOTREP_001: return replacement ships from lot and consumes it; order stays DELIVERED; capacity stays 0', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 5);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
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
    expect(delivered.order_status).toBe('DELIVERED');
    const oldDeviceId = delivered.device_id as string;

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    const rCreate = await createReturn(program.program_id, delivered.order_id, c1Ctx, 'REPLACEMENT');
    expectSuccess(rCreate, 201);
    const returnId = rCreate.body.return_id as string;
    expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
    expectSuccess(await markInboundReturn(program.program_id, returnId, opsCtx), 200);
    expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeReturn(program.program_id, returnId, supCtx, {
      resolution: 'REPLACEMENT',
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-REP-LOT-1',
      replacement_build_tag: repLot.build_tag
    });
    expectSuccess(completeRes, 200);

    const rDone = await getReturn(program.program_id, returnId, ops);
    expect(rDone.return_status).toBe('COMPLETED');
    expect(rDone.replacement_device_id).toBeTruthy();
    expect(rDone.refunded_to_card_cents).toBe(0);
    expect(rDone.refunded_to_credit_cents).toBe(0);

    const replacementId = rDone.replacement_device_id as string;

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementId);

    const dOld = await getDevice(program.program_id, oldDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');

    const dNew = await getDevice(program.program_id, replacementId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.build_tag).toBe('B99Z');
    expect(dNew.serial_number).toBe('SN-REP-LOT-1');

    const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
    expect(repLotAfter.build_lot_status).toBe('CONSUMED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('LOTREP_002: claim replacement ships from lot and consumes it; payment stays CAPTURED; capacity stays 0', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const saleLot = await createBuildLot(program.program_id, opsCtx, 'C01X', 5);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
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
    const oldDeviceId = delivered.device_id as string;
    const pmId = delivered.payment_id as string;
    const pm = await getPayment(program.program_id, pmId, ops);
    expect(pm.payment_status).toBe('CAPTURED');

    expectSuccess(await activateDevice(program.program_id, oldDeviceId, c1Ctx), 200);

    const create = await createClaim(program.program_id, oldDeviceId, supCtx, 'WARRANTY');
    expectSuccess(create, 201);
    const claimId = create.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
    expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
    expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

    const completeRes = await completeClaim(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-CLM-LOT-1',
      replacement_build_tag: repLot.build_tag
    });
    expectSuccess(completeRes, 200);

    const clDone = await getClaim(program.program_id, claimId, ops);
    expect(clDone.claim_status).toBe('COMPLETED');
    expect(clDone.replacement_device_id).toBeTruthy();
    const replacementId = clDone.replacement_device_id as string;

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementId);

    const dOld = await getDevice(program.program_id, oldDeviceId, ops);
    expect(dOld.device_status).toBe('SCRAPPED');

    const dNew = await getDevice(program.program_id, replacementId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN-CLM-LOT-1');
    expect(dNew.build_tag).toBe('B99Z');

    const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
    expect(repLotAfter.build_lot_status).toBe('CONSUMED');

    const pmAfter = await getPayment(program.program_id, pmId, ops);
    expect(pmAfter.payment_status).toBe('CAPTURED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(0);
  });

  test('LOTREP_003: advance replacement ships in PROGRAM_FROZEN (recall) and applies deposit + holds once', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 6);
    const repLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

    const c1 = await createCustomer(program.program_id, opsCtx);
    const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

    const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);

    const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
    expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
    expectSuccess(
      await shipOrder(program.program_id, o1.order_id, opsCtx, {
        build_lot_id: lotA17.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: lotA17.build_tag
      }),
      200
    );
    expectSuccess(await markDelivered(program.program_id, o1.order_id, opsCtx), 200);
    const delivered = await getOrder(program.program_id, o1.order_id, ops);
    const deviceId = delivered.device_id as string;
    expect(delivered.order_status).toBe('DELIVERED');

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(0);

    expectSuccess(await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17'), 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const create = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
    expectSuccess(create, 201);
    const claimId = create.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: repLot.build_lot_id,
      replacement_serial_number: 'SN-ADV-LOT-1',
      replacement_build_tag: repLot.build_tag
    });
    expectSuccess(shipRes, 200);

    const cl = await getClaim(program.program_id, claimId, ops);
    expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
    expect(cl.replacement_device_id).toBeTruthy();
    const replacementId = cl.replacement_device_id as string;

    const oAfter = await getOrder(program.program_id, delivered.order_id, ops);
    expect(oAfter.order_status).toBe('DELIVERED');
    expect(oAfter.device_id).toBe(replacementId);

    const cust = await getCustomer(program.program_id, c1.customer_id, ops);
    expect(cust.customer_status).toBe('LIMITED');
    expect(cust.balance_due_cents).toBe(15000);

    const o2After = await getOrder(program.program_id, o2.order_id, ops);
    expect(o2After.order_status).toBe('ON_HOLD');

    const dNew = await getDevice(program.program_id, replacementId, ops);
    expect(dNew.device_status).toBe('SHIPPED');
    expect(dNew.serial_number).toBe('SN-ADV-LOT-1');
    expect(dNew.build_tag).toBe('B99Z');

    const repLotAfter = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
    expect(repLotAfter.build_lot_status).toBe('CONSUMED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.available_to_commit_units).toBe(0);
  });
});
