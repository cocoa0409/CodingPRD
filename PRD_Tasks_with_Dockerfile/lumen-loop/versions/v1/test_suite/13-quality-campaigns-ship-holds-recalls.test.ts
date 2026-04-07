import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import {
  activateDevice,
  approveClaim,
  closeQualityCampaign,
  createBuildLot,
  createClaim,
  createCustomer,
  createCustomerCtx,
  createDeliveredOrderWithDevice,
  createOpsCtx,
  createOrder,
  createProgram,
  createQualityCampaign,
  createSupportCtx,
  escalateQualityCampaign,
  getBuildLot,
  getCarePlan,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getQualityCampaign,
  freezeProgram,
  listAlerts,
  remediateDevice,
  resolveQualityCampaign,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 13: Quality Campaigns: Ship Holds & Recalls (v1)', () => {
  test('QUALSHIP_001: ship-hold blocks affected lots but allows shipping from unaffected lots', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const lotB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

    await createBuildLot(program.program_id, opsCtx, 'C00X', 10);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const lotA17Q = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotA17Q.build_lot_status).toBe('QUARANTINED');

    const customer = await createCustomer(program.program_id, opsCtx);
    const { ctx: customerCtx } = await createCustomerCtx(program.program_id, customer.customer_id);
    const order = await createOrder(program.program_id, customer.customer_id, customerCtx);
    expectSuccess(await submitOrder(program.program_id, order.order_id, customerCtx, false), 200);

    const oSubmitted = await getOrder(program.program_id, order.order_id, ops);
    expect(oSubmitted.order_status).toBe('SUBMITTED');
    expect(oSubmitted.payment_id).toBeTruthy();
    const paymentId = oSubmitted.payment_id as string;

    const pm0 = await getPayment(program.program_id, paymentId, ops);
    expect(pm0.payment_status).toBe('AUTHORIZED');

    const pBefore = await getProgram(program.program_id, ops);
    const availableBefore = pBefore.available_to_commit_units;

    const shipRes = await shipOrder(program.program_id, order.order_id, opsCtx, {
      build_lot_id: lotB99.build_lot_id,
      serial_number: 'SN-OK-1',
      build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);

    const oAfter = await getOrder(program.program_id, order.order_id, ops);
    expect(oAfter.order_status).toBe('SHIPPED');
    expect(oAfter.device_id).toBeTruthy();

    const pm1 = await getPayment(program.program_id, paymentId, ops);
    expect(pm1.payment_status).toBe('CAPTURED');

    const device = await getDevice(program.program_id, oAfter.device_id as string, ops);
    expect(device.device_status).toBe('SHIPPED');
    expect(device.build_tag).toBe('B99Z');

    const lotB99After = await getBuildLot(program.program_id, lotB99.build_lot_id, ops);
    expect(lotB99After.build_lot_status).toBe('CONSUMED');

    const lotA17After = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotA17After.build_lot_status).toBe('QUARANTINED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(availableBefore);

    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('SHIP_HOLD');
    expect(qc.campaign_status).toBe('OPEN');
  });

  test('QUAL_001: opening ship-hold quarantines matching lots but does not quarantine already shipped devices', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const customer = await createCustomer(program.program_id, opsCtx);
    const { ctx: customerCtx } = await createCustomerCtx(program.program_id, customer.customer_id);
    const order = await createOrder(program.program_id, customer.customer_id, customerCtx);
    expectSuccess(await submitOrder(program.program_id, order.order_id, customerCtx, false), 200);

    expectSuccess(
      await shipOrder(program.program_id, order.order_id, opsCtx, {
        build_lot_id: lotA17.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: 'A17B'
      }),
      200
    );

    const oShipped = await getOrder(program.program_id, order.order_id, ops);
    const deviceId = oShipped.device_id as string;
    const d1 = await getDevice(program.program_id, deviceId, ops);
    expect(d1.device_status).toBe('SHIPPED');

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);

    const qcId = qcCreate.body.quality_campaign_id as string;
    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('SHIP_HOLD');
    expect(qc.campaign_status).toBe('OPEN');

    const lotA17Q = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotA17Q.build_lot_status).toBe('QUARANTINED');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(['SHIPPED', 'ACTIVE']).toContain(dAfter.device_status);
  });

  test('QUAL_002: escalating ship-hold to recall freezes program, quarantines devices, pauses care plans', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { customer, customerCtx, deviceId, carePlanId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: true,
      activate: true
    });
    expect(carePlanId).toBeTruthy();

    const cp0 = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cp0.care_plan_status).toBe('ACTIVE');

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const esc = await escalateQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(esc, 200);

    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('RECALL');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const cpPaused = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cpPaused.care_plan_status).toBe('PAUSED');

    const activateAgain = await activateDevice(program.program_id, deviceId, customerCtx);
    expectError(activateAgain, 400, 'ERR_DEVICE_QUARANTINED');

    const d1Again = await getDevice(program.program_id, deviceId, ops);
    expect(d1Again.device_status).toBe('QUARANTINED');
    expect(customer.customer_status).not.toBe('LOCKED');
  });

  test('QUAL_003: opening RECALL freezes program immediately without ops-run increment and opens RECALL_ACTIVE alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const p0 = await getProgram(program.program_id, ops);
    const opsRunBefore = p0.ops_run_index;

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('RECALL');
    expect(qc.campaign_status).toBe('OPEN');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_FROZEN');
    expect(p1.ops_run_index).toBe(opsRunBefore);

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].quality_campaign_id).toBe(qcId);
  });

  test('QUAL_004: cannot resolve OPEN recall while affected devices remain quarantined', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const resolveRes = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectError(resolveRes, 400, 'ERR_INVALID_REQUEST');

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('OPEN');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('QUAL_005: resolving recall after remediation marks campaign RESOLVED but program stays FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const dQuarantined = await getDevice(program.program_id, deviceId, ops);
    expect(dQuarantined.device_status).toBe('QUARANTINED');

    const resolveBeforeRemediation = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectError(resolveBeforeRemediation, 400, 'ERR_INVALID_REQUEST');

    expectSuccess(await remediateDevice(program.program_id, deviceId, opsCtx, 'verified safe'), 200);

    const dRemediated = await getDevice(program.program_id, deviceId, ops);
    expect(dRemediated.device_status).toBe('ACTIVE');

    const resolveRes = await resolveQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(resolveRes, 200);

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('RESOLVED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('QUAL_006: closing RESOLVED recall does not auto-resolve RECALL_ACTIVE alert; program remains FROZEN', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    expectSuccess(await remediateDevice(program.program_id, deviceId, opsCtx, 'verified safe'), 200);
    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);

    const closeRes = await closeQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(closeRes, 200);

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('CLOSED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].quality_campaign_id).toBe(qcId);
  });

  test('QUAL_007: recall claim replacement device can be activated while program is frozen due to recall; original remains quarantined', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
    const { ctx: supCtx } = await createSupportCtx(program.program_id);

    const { deviceId: originalDeviceId, customer, customerCtx, carePlanId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: true,
      activate: true
    });

    const replacementLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 3);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');

    const dQ = await getDevice(program.program_id, originalDeviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const claimCreate = await createClaim(program.program_id, originalDeviceId, supCtx, 'RECALL');
    expectSuccess(claimCreate, 201);
    const claimId = claimCreate.body.claim_id as string;
    expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

    const shipRes = await shipAdvanceReplacement(program.program_id, claimId, supCtx, {
      replacement_build_lot_id: replacementLot.build_lot_id,
      replacement_serial_number: 'SN-REM-1',
      replacement_build_tag: 'B99Z'
    });
    expectSuccess(shipRes, 200);
    const replacementDeviceId = shipRes.body.replacement_device_id as string;
    expect(replacementDeviceId).toBeTruthy();

    const d2Before = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(d2Before.device_status).toBe('SHIPPED');

    const activateRes = await activateDevice(program.program_id, replacementDeviceId, customerCtx);
    expectSuccess(activateRes, 200);

    const d2After = await getDevice(program.program_id, replacementDeviceId, ops);
    expect(d2After.device_status).toBe('ACTIVE');

    if (carePlanId) {
      const cp = await getCarePlan(program.program_id, carePlanId, ops);
      expect(cp.care_plan_status).toBe('ACTIVE');
      expect(cp.device_id).toBe(replacementDeviceId);
    }

    const activateOriginal = await activateDevice(program.program_id, originalDeviceId, customerCtx);
    expectError(activateOriginal, 400, 'ERR_DEVICE_QUARANTINED');

    const d1After = await getDevice(program.program_id, originalDeviceId, ops);
    expect(d1After.device_status).toBe('QUARANTINED');
    expect(customer.customer_status).not.toBe('LOCKED');
  });

  test('QUAL_008: closing RESOLVED ship-hold releases lots and restores available_to_commit_units', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(15);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(5);

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    const closeRes = await closeQualityCampaign(program.program_id, qcId, opsCtx);
    expectSuccess(closeRes, 200);

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('CLOSED');

    const lotAfter = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('AVAILABLE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(15);
  });

  test('QUAL_009: closing resolved ship-hold does not release lot if an OPEN recall also applies', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const hold = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(hold, 201);
    const holdId = hold.body.quality_campaign_id as string;
    expectSuccess(await resolveQualityCampaign(program.program_id, holdId, opsCtx), 200);

    const recall = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(recall, 201);

    const lotQ = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotQ.build_lot_status).toBe('QUARANTINED');

    const pBefore = await getProgram(program.program_id, ops);
    const availBefore = pBefore.available_to_commit_units;

    const closeHold = await closeQualityCampaign(program.program_id, holdId, opsCtx);
    expectSuccess(closeHold, 200);

    const holdAfter = await getQualityCampaign(program.program_id, holdId, ops);
    expect(holdAfter.campaign_status).toBe('CLOSED');

    const lotAfter = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter.build_lot_status).toBe('QUARANTINED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.available_to_commit_units).toBe(availBefore);
  });

  test('QUAL_010: cannot close OPEN recall while affected devices remain quarantined', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { deviceId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: false,
      activate: true
    });

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const closeRes = await closeQualityCampaign(program.program_id, qcId, opsCtx);
    expectError(closeRes, 400, 'ERR_INVALID_REQUEST');

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('OPEN');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
  });

  test('QUAL_011: while PROGRAM_FROZEN (manual), opening ship-hold is allowed and reduces available_to_commit_units', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const lotB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    expect(lotB99.build_lot_status).toBe('AVAILABLE');

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.available_to_commit_units).toBe(15);
    const opsRun = p0.ops_run_index;

    const freeze = await freezeProgram(program.program_id, opsCtx, 'manual containment');
    expect(freeze.program_posture).toBe('PROGRAM_FROZEN');

    const pFrozen = await getProgram(program.program_id, ops);
    expect(pFrozen.program_posture).toBe('PROGRAM_FROZEN');
    expect(pFrozen.ops_run_index).toBe(opsRun);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('SHIP_HOLD');
    expect(qc.campaign_status).toBe('OPEN');
    expect(qc.build_tag_prefix).toBe('A17');

    const lotA17After = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotA17After.build_lot_status).toBe('QUARANTINED');

    const lotB99After = await getBuildLot(program.program_id, lotB99.build_lot_id, ops);
    expect(lotB99After.build_lot_status).toBe('AVAILABLE');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.ops_run_index).toBe(opsRun);
    expect(pAfter.available_to_commit_units).toBe(5);
  });

  test('QUAL_012: opening recall quarantines matching lots, freezes program immediately, and opens RECALL_ACTIVE alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    const lotB99 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');
    expect(p0.available_to_commit_units).toBe(15);
    const opsRun = p0.ops_run_index;

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.ops_run_index).toBe(opsRun);
    expect(pAfter.available_to_commit_units).toBe(5);

    const a17 = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(a17.build_lot_status).toBe('QUARANTINED');
    const b99 = await getBuildLot(program.program_id, lotB99.build_lot_id, ops);
    expect(b99.build_lot_status).toBe('AVAILABLE');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].quality_campaign_id).toBe(qcId);
  });

  test('QUAL_013: escalating ship-hold to recall quarantines shipped device and pauses pending care plan; order stays SHIPPED', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 3);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const customer = await createCustomer(program.program_id, opsCtx);
    const { ctx: customerCtx } = await createCustomerCtx(program.program_id, customer.customer_id);
    const order = await createOrder(program.program_id, customer.customer_id, customerCtx);
    expectSuccess(await submitOrder(program.program_id, order.order_id, customerCtx, true), 200);

    expectSuccess(
      await shipOrder(program.program_id, order.order_id, opsCtx, {
        build_lot_id: lotA17.build_lot_id,
        serial_number: `SN-${uniqueId('sn')}`,
        build_tag: 'A17B'
      }),
      200
    );

    const oShipped = await getOrder(program.program_id, order.order_id, ops);
    expect(oShipped.order_status).toBe('SHIPPED');
    expect(oShipped.device_id).toBeTruthy();
    expect(oShipped.care_plan_id).toBeTruthy();

    const deviceId = oShipped.device_id as string;
    const carePlanId = oShipped.care_plan_id as string;

    const cp0 = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cp0.care_plan_status).toBe('PENDING_ACTIVATION');

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    expectSuccess(await escalateQualityCampaign(program.program_id, qcId, opsCtx), 200);

    const qc = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qc.campaign_type).toBe('RECALL');

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');

    const dAfter = await getDevice(program.program_id, deviceId, ops);
    expect(dAfter.device_status).toBe('QUARANTINED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId, ops);
    expect(cpAfter.care_plan_status).toBe('PAUSED');

    const oAfter = await getOrder(program.program_id, order.order_id, ops);
    expect(oAfter.order_status).toBe('SHIPPED');
  });

  test('QUAL_014: closing overlapping ship-holds only releases lots once all matching holds are closed', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const lotA17 = await createBuildLot(program.program_id, opsCtx, 'A17B', 10);
    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);

    const qcWide = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A');
    expectSuccess(qcWide, 201);
    const wideId = qcWide.body.quality_campaign_id as string;

    const qcNarrow = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcNarrow, 201);
    const narrowId = qcNarrow.body.quality_campaign_id as string;

    expectSuccess(await resolveQualityCampaign(program.program_id, wideId, opsCtx), 200);
    expectSuccess(await resolveQualityCampaign(program.program_id, narrowId, opsCtx), 200);

    const lotQ = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotQ.build_lot_status).toBe('QUARANTINED');

    expectSuccess(await closeQualityCampaign(program.program_id, narrowId, opsCtx), 200);
    const narrowAfter = await getQualityCampaign(program.program_id, narrowId, ops);
    expect(narrowAfter.campaign_status).toBe('CLOSED');

    const lotAfter1 = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter1.build_lot_status).toBe('QUARANTINED');

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.available_to_commit_units).toBe(5);

    expectSuccess(await closeQualityCampaign(program.program_id, wideId, opsCtx), 200);
    const wideAfter = await getQualityCampaign(program.program_id, wideId, ops);
    expect(wideAfter.campaign_status).toBe('CLOSED');

    const lotAfter2 = await getBuildLot(program.program_id, lotA17.build_lot_id, ops);
    expect(lotAfter2.build_lot_status).toBe('AVAILABLE');

    const p2 = await getProgram(program.program_id, ops);
    expect(p2.available_to_commit_units).toBe(15);
  });

  test('QUAL_015: opening recall quarantines active devices, pauses care plans, freezes program, and opens RECALL_ACTIVE alert', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    const { delivered, deviceId, carePlanId } = await createDeliveredOrderWithDevice({
      program_id: program.program_id,
      opsActor: ops,
      opsCtx,
      build_tag: 'A17B',
      units: 12,
      include_care_plan: true,
      activate: true
    });
    expect(delivered.order_status).toBe('DELIVERED');
    expect(carePlanId).toBeTruthy();

    const p0 = await getProgram(program.program_id, ops);
    expect(p0.ops_run_index).toBe(0);
    expect(p0.program_posture).toBe('PROGRAM_ACTIVE');

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const pAfter = await getProgram(program.program_id, ops);
    expect(pAfter.program_posture).toBe('PROGRAM_FROZEN');
    expect(pAfter.ops_run_index).toBe(0);

    const dQ = await getDevice(program.program_id, deviceId, ops);
    expect(dQ.device_status).toBe('QUARANTINED');

    const cpAfter = await getCarePlan(program.program_id, carePlanId as string, ops);
    expect(cpAfter.care_plan_status).toBe('PAUSED');

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].quality_campaign_id).toBe(qcId);
  });

  test('QUAL_016: lots created during OPEN ship-hold are quarantined and released on close; capacity recomputes', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const p0 = await getProgram(program.program_id, ops);
    expect(p0.ops_run_index).toBe(0);
    expect(p0.available_to_commit_units).toBe(5);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'SHIP_HOLD', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const lNew = await createBuildLot(program.program_id, opsCtx, 'A17C', 10);
    expect(lNew.build_lot_status).toBe('QUARANTINED');

    const pAfterLot = await getProgram(program.program_id, ops);
    expect(pAfterLot.available_to_commit_units).toBe(5);

    expectSuccess(await resolveQualityCampaign(program.program_id, qcId, opsCtx), 200);
    expectSuccess(await closeQualityCampaign(program.program_id, qcId, opsCtx), 200);

    const qcAfter = await getQualityCampaign(program.program_id, qcId, ops);
    expect(qcAfter.campaign_status).toBe('CLOSED');

    const lNewAfter = await getBuildLot(program.program_id, lNew.build_lot_id, ops);
    expect(lNewAfter.build_lot_status).toBe('AVAILABLE');

    const pAfterClose = await getProgram(program.program_id, ops);
    expect(pAfterClose.available_to_commit_units).toBe(15);
  });

  test('QUAL_017: lots created during OPEN recall are quarantined; capacity stays constant; RECALL_ACTIVE alert references campaign', async () => {
    const program = await createProgram();
    const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

    await createBuildLot(program.program_id, opsCtx, 'B99Z', 10);
    const p0 = await getProgram(program.program_id, ops);
    expect(p0.ops_run_index).toBe(0);
    expect(p0.available_to_commit_units).toBe(5);

    const qcCreate = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', 'A17');
    expectSuccess(qcCreate, 201);
    const qcId = qcCreate.body.quality_campaign_id as string;

    const p1 = await getProgram(program.program_id, ops);
    expect(p1.program_posture).toBe('PROGRAM_FROZEN');
    expect(p1.ops_run_index).toBe(0);
    expect(p1.available_to_commit_units).toBe(5);

    const lNew = await createBuildLot(program.program_id, opsCtx, 'A17C', 10);
    expect(lNew.build_lot_status).toBe('QUARANTINED');

    const p2 = await getProgram(program.program_id, ops);
    expect(p2.available_to_commit_units).toBe(5);

    const alerts = await listAlerts(program.program_id, ops, { alert_type: 'RECALL_ACTIVE', alert_status: 'OPEN' });
    expect(alerts.alerts.length).toBe(1);
    expect(alerts.alerts[0].quality_campaign_id).toBe(qcId);
  });
});
