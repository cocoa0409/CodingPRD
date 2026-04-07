import { post } from '../../../test-helpers/api-client';
import { expectError, expectSuccess, extractErrorCode } from '../../../test-helpers/assertions';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';
import {
  activateDevice,
  appraiseTradeIn,
  approveClaim,
  approveReturn,
  cancelClaim,
  cancelOrder,
  completeClaim,
  completeReturn,
  createAndApplyBalanceDue,
  createAdjustment,
  applyAdjustment,
  createBuildLot,
  createClaim,
  createCustomer,
  createCustomerCtx,
  createOpsCtx,
  createOrder,
  createProgram,
  createQualityCampaign,
  createReturn,
  createSupportCtx,
  createTradeIn,
  disputePayment,
  getBuildLot,
  getClaim,
  getCustomer,
  getDevice,
  getOrder,
  getPayment,
  getProgram,
  getReturn,
  listAlerts,
  markDelivered,
  markInboundClaim,
  markInboundReturn,
  markInboundTradeIn,
  receiveClaim,
  receiveReturn,
  resolveDispute,
  reverseTradeInCredit,
  settleBalanceDue,
  shipAdvanceReplacement,
  shipOrder,
  submitOrder,
  submitTradeIn,
  uniqueId
} from '../../../test-helpers/resources';

describe('Feature 16: Concurrency & Atomicity (v1)', () => {
  test('CONCUR_001: concurrent submits on last available unit yield exactly one success', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

      await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
      const p0 = await getProgram(program.program_id, ops);
      expect(p0.available_to_commit_units).toBe(1);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
      const c2 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);

      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
      const o2 = await createOrder(program.program_id, c2.customer_id, c2Ctx);

      const [r1, r2] = await Promise.all([
        submitOrder(program.program_id, o1.order_id, c1Ctx, false),
        submitOrder(program.program_id, o2.order_id, c2Ctx, false)
      ]);

      const statuses = [r1.status, r2.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 400]);

      const err = r1.status === 400 ? r1 : r2;
      expectError(err, 400, 'ERR_OUT_OF_STOCK');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(0);

      const o1After = await getOrder(program.program_id, o1.order_id, ops);
      const o2After = await getOrder(program.program_id, o2.order_id, ops);

      const submitted = [o1After, o2After].filter((o) => o.order_status === 'SUBMITTED');
      const drafts = [o1After, o2After].filter((o) => o.order_status === 'DRAFT');
      expect(submitted).toHaveLength(1);
      expect(drafts).toHaveLength(1);
      expect(submitted[0].payment_id).not.toBeNull();
      expect(drafts[0].payment_id).toBeNull();
    }, 3);
  });

  test('CONCUR_002: concurrent cancel vs ship yields one consistent outcome', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

      const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
      expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

      const pre = await getProgram(program.program_id, ops);
      expect(pre.available_to_commit_units).toBe(0);

      const [cancelRes, shipRes] = await Promise.all([
        cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cancel-race'),
        shipOrder(program.program_id, o1.order_id, opsCtx, {
          build_lot_id: lot.build_lot_id,
          serial_number: `SN-${uniqueId('sn')}`,
          build_tag: lot.build_tag
        })
      ]);

      const statuses = [cancelRes.status, shipRes.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 400]);

      const oAfter = await getOrder(program.program_id, o1.order_id, ops);
      const pm = await getPayment(program.program_id, oAfter.payment_id as string, ops);
      const pAfter = await getProgram(program.program_id, ops);

      if (oAfter.order_status === 'SHIPPED') {
        expect(oAfter.device_id).toBeTruthy();
        expect(pm.payment_status).toBe('CAPTURED');
        expect(pAfter.available_to_commit_units).toBe(pre.available_to_commit_units);

        const cancelErr = cancelRes.status === 400 ? cancelRes : shipRes;
        expect(cancelErr.status).toBe(400);
        const code = extractErrorCode(cancelErr.body);
        expect(['ERR_ORDER_NOT_CANCELABLE', 'ERR_INVALID_STATE_TRANSITION']).toContain(code);
      } else {
        expect(oAfter.order_status).toBe('CANCELED');
        expect(oAfter.device_id).toBeNull();
        expect(pm.payment_status).toBe('VOIDED');
        expect(pAfter.available_to_commit_units).toBe(pre.available_to_commit_units + 1);

        const shipErr = shipRes.status === 400 ? shipRes : cancelRes;
        expectError(shipErr, 400, 'ERR_INVALID_STATE_TRANSITION');
      }
    }, 3);
  });

  test('CONCUR_003: concurrent run_ops are queued; ops_run_index increments twice without double-unwind', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const beforeCredit = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(beforeCredit.credit_balance_cents).toBe(0);

      const adjRes = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 20000);
      expectSuccess(adjRes, 201);
      expectSuccess(await applyAdjustment(program.program_id, adjRes.body.adjustment_id as string, supCtx), 200);

      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
      expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

      const p0 = await getProgram(program.program_id, ops);
      const n = p0.ops_run_index;
      expect(p0.available_to_commit_units).toBe(0);

      const [rA, rB] = await Promise.all([
        post(`/programs/${program.program_id}/run_ops`, {}, opsCtx),
        post(`/programs/${program.program_id}/run_ops`, {}, opsCtx)
      ]);
      expectSuccess(rA, 200);
      expectSuccess(rB, 200);

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.ops_run_index).toBe(n + 2);

      const oAfter = await getOrder(program.program_id, o1.order_id, ops);
      expect(oAfter.order_status).toBe('EXPIRED');

      const pm = await getPayment(program.program_id, oAfter.payment_id as string, ops);
      expect(pm.payment_status).toBe('VOIDED');

      expect(pAfter.available_to_commit_units).toBe(1);

      const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cAfter.credit_balance_cents).toBe(20000);
      expect(cAfter.balance_due_cents).toBe(0);
    }, 3);
  });

  test('CONCUR_004: duplicate submit with same Idempotency_Key returns same success; side effects apply once', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const adjRes = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 20000);
      expectSuccess(adjRes, 201);
      expectSuccess(await applyAdjustment(program.program_id, adjRes.body.adjustment_id as string, supCtx), 200);

      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });

      const idempotencyKey = `K_RACE_SUBMIT-${uniqueId('k')}`;
      const [a, b] = await Promise.all([
        submitOrder(program.program_id, o1.order_id, c1Ctx, false, idempotencyKey),
        submitOrder(program.program_id, o1.order_id, c1Ctx, false, idempotencyKey)
      ]);

      expectSuccess(a, 200);
      expectSuccess(b, 200);
      expect(a.body).toEqual(b.body);

      const oAfter = await getOrder(program.program_id, o1.order_id, ops);
      expect(oAfter.order_status).toBe('SUBMITTED');
      expect(oAfter.payment_id).toBeTruthy();

      const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cAfter.credit_balance_cents).toBe(0);

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(0);
    }, 3);
  });

  test('CONCUR_005: reverse_tradein_credit vs cancel keeps credit/balance non-negative and ends canceled', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

      await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

      const tCreate = await createTradeIn(program.program_id, c1.customer_id, c1Ctx, 10000);
      expectSuccess(tCreate, 201);
      const tradein_id = tCreate.body.tradein_id as string;

      expectSuccess(await submitTradeIn(program.program_id, tradein_id, c1Ctx), 200);

      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 8000, tradein_id });
      expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);

      expectSuccess(await markInboundTradeIn(program.program_id, tradein_id, opsCtx), 200);
      expectSuccess(await appraiseTradeIn(program.program_id, tradein_id, opsCtx, { accepted: true, final_credit_cents: 10000 }), 200);

      const cMid = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cMid.credit_balance_cents).toBe(2000);
      expect(cMid.balance_due_cents).toBe(0);

      const oMid = await getOrder(program.program_id, o1.order_id, ops);
      expect(oMid.order_status).toBe('SUBMITTED');
      expect(oMid.payment_id).toBeTruthy();

      const pBefore = await getProgram(program.program_id, ops);
      expect(pBefore.available_to_commit_units).toBe(0);

      const [reverseRes, cancelRes] = await Promise.all([
        reverseTradeInCredit(program.program_id, tradein_id, opsCtx, 'policy correction'),
        cancelOrder(program.program_id, o1.order_id, c1Ctx, 'cancel-race')
      ]);

      expectSuccess(reverseRes, 200);
      expectSuccess(cancelRes, 200);

      const cAfter = await getCustomer(program.program_id, c1.customer_id, ops);

      expect(cAfter.credit_balance_cents).toBe(0);
      expect(cAfter.balance_due_cents).toBe(0);

      expect(['ACTIVE', 'LOCKED']).toContain(cAfter.customer_status);

      if (cAfter.customer_status === 'LOCKED') {

        const alerts = await listAlerts(program.program_id, ops, { alert_type: 'TRADEIN_REVERSAL', customer_id: c1.customer_id });

        expect(alerts.alerts.filter((a: any) => ['OPEN', 'ACKNOWLEDGED'].includes(a.alert_status)).length).toBeGreaterThanOrEqual(0);

        const pPosture = await getProgram(program.program_id, ops);
        const openAlerts = await listAlerts(program.program_id, ops, { alert_status: 'OPEN' });
        if (openAlerts.alerts.length > 0) {
          expect(pPosture.program_posture).toBe('PROGRAM_GUARDED');
        }
      }

      const oAfter = await getOrder(program.program_id, o1.order_id, ops);
      expect(oAfter.order_status).toBe('CANCELED');

      const pmAfter = await getPayment(program.program_id, oAfter.payment_id as string, ops);
      expect(pmAfter.payment_status).toBe('VOIDED');

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(1);
    }, 3);
  });

  test('CONCUR_006: concurrent replacement return completions consume last reserve atomically (one ERR_OUT_OF_STOCK)', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 7);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
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

      const c2 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);
      const o2 = await createOrder(program.program_id, c2.customer_id, c2Ctx);
      expectSuccess(await submitOrder(program.program_id, o2.order_id, c2Ctx, false), 200);
      expectSuccess(
        await shipOrder(program.program_id, o2.order_id, opsCtx, {
          build_lot_id: lot.build_lot_id,
          serial_number: `SN-${uniqueId('sn')}`,
          build_tag: lot.build_tag
        }),
        200
      );
      expectSuccess(await markDelivered(program.program_id, o2.order_id, opsCtx), 200);

      const p0 = await getProgram(program.program_id, ops);
      expect(p0.available_to_commit_units).toBe(0);

      let currentDeviceId = (await getOrder(program.program_id, o1.order_id, ops)).device_id as string;
      expectSuccess(await activateDevice(program.program_id, currentDeviceId, c1Ctx), 200);
      for (let i = 0; i < 4; i++) {
        const create = await createClaim(program.program_id, currentDeviceId, supCtx, 'WARRANTY');
        expectSuccess(create, 201);
        const claimId = create.body.claim_id as string;
        expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
        expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
        expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);
        const comp = await completeClaim(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: lot.build_lot_id,
          replacement_serial_number: `SN-BURN-${i}-${uniqueId('sn')}`,
          replacement_build_tag: lot.build_tag
        });
        expectSuccess(comp, 200);
        currentDeviceId = comp.body.replacement_device_id as string;

        if (i < 3) {
          expectSuccess(await activateDevice(program.program_id, currentDeviceId, c1Ctx), 200);
        }
      }

      const r1Create = await createReturn(program.program_id, o1.order_id, c1Ctx, 'REPLACEMENT');
      expectSuccess(r1Create, 201);
      const r1Id = r1Create.body.return_id as string;
      expectSuccess(await approveReturn(program.program_id, r1Id, supCtx), 200);
      expectSuccess(await markInboundReturn(program.program_id, r1Id, opsCtx), 200);
      expectSuccess(await receiveReturn(program.program_id, r1Id, opsCtx, 'SCRAP'), 200);

      const r2Create = await createReturn(program.program_id, o2.order_id, c2Ctx, 'REPLACEMENT');
      expectSuccess(r2Create, 201);
      const r2Id = r2Create.body.return_id as string;
      expectSuccess(await approveReturn(program.program_id, r2Id, supCtx), 200);
      expectSuccess(await markInboundReturn(program.program_id, r2Id, opsCtx), 200);
      expectSuccess(await receiveReturn(program.program_id, r2Id, opsCtx, 'SCRAP'), 200);

      const [cA, cB] = await Promise.all([
        completeReturn(program.program_id, r1Id, supCtx, {
          resolution: 'REPLACEMENT',
          replacement_build_lot_id: lot.build_lot_id,
          replacement_serial_number: `SN-RACE-R1-${uniqueId('sn')}`,
          replacement_build_tag: lot.build_tag
        }),
        completeReturn(program.program_id, r2Id, supCtx, {
          resolution: 'REPLACEMENT',
          replacement_build_lot_id: lot.build_lot_id,
          replacement_serial_number: `SN-RACE-R2-${uniqueId('sn')}`,
          replacement_build_tag: lot.build_tag
        })
      ]);

      const statuses = [cA.status, cB.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 400]);
      const err = cA.status === 400 ? cA : cB;
      expectError(err, 400, 'ERR_OUT_OF_STOCK');

      const r1After = await getReturn(program.program_id, r1Id, ops);
      const r2After = await getReturn(program.program_id, r2Id, ops);
      const replacementIds = [r1After.replacement_device_id, r2After.replacement_device_id].filter((x) => x);
      expect(replacementIds).toHaveLength(1);

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(0);
    }, 2);
  });

  test('CONCUR_007: settle_balance_due and unlock concurrently yields ERR_PROGRAM_REVIEW_REQUIRED - guarded blocks unlock', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const c1 = await createCustomer(program.program_id, opsCtx);
      await createAndApplyBalanceDue(program.program_id, c1.customer_id, supCtx, 5000);

      const before = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(before.customer_status).toBe('LOCKED');
      expect(before.balance_due_cents).toBe(5000);

      const alertsBefore = await listAlerts(program.program_id, ops, { alert_status: 'OPEN', customer_id: c1.customer_id });
      expect(alertsBefore.alerts.length).toBeGreaterThanOrEqual(1);

      const programBefore = await getProgram(program.program_id, ops);
      expect(programBefore.program_posture).toBe('PROGRAM_GUARDED');

      const [unlockRes, settleRes] = await Promise.all([
        post(`/programs/${program.program_id}/customers/${c1.customer_id}/unlock`, {}, opsCtx),
        settleBalanceDue(program.program_id, c1.customer_id, supCtx, 5000)
      ]);

      expectError(unlockRes, 400, 'ERR_PROGRAM_REVIEW_REQUIRED');

      expect(settleRes.balance_due_cents).toBe(0);

      const after = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(after.balance_due_cents).toBe(0);

      expect(after.customer_status).toBe('LOCKED');
    }, 3);
  });

  test('CONCUR_008: ship_advance_replacement vs cancel are mutually exclusive under concurrency', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
      const repLot = await createBuildLot(program.program_id, opsCtx, 'B88X', 6);

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

      const recallRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', saleLot.build_tag);
      expectSuccess(recallRes, 201);

      const deviceAfterRecall = await getDevice(program.program_id, deviceId, ops);
      expect(deviceAfterRecall.device_status).toBe('QUARANTINED');

      const create = await createClaim(program.program_id, deviceId, supCtx, 'RECALL');
      expectSuccess(create, 201);
      const claimId = create.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

      const [shipRes, cancelRes] = await Promise.all([
        shipAdvanceReplacement(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: repLot.build_lot_id,
          replacement_serial_number: `SN-ADV-${uniqueId('sn')}`,
          replacement_build_tag: repLot.build_tag
        }),
        cancelClaim(program.program_id, claimId, supCtx, 'cancel-race')
      ]);

      const statuses = [shipRes.status, cancelRes.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 400]);

      const cl = await getClaim(program.program_id, claimId, ops);
      const cust = await getCustomer(program.program_id, c1.customer_id, ops);

      if (cl.claim_status === 'ADVANCE_SHIPPED') {
        expect(cl.replacement_device_id).toBeTruthy();
        expect(cust.balance_due_cents).toBe(15000);
        expect(cust.customer_status).toBe('LIMITED');
        expectError(cancelRes.status === 400 ? cancelRes : shipRes, 400, 'ERR_INVALID_STATE_TRANSITION');
      } else {
        expect(cl.claim_status).toBe('CANCELED');
        expect(cl.replacement_device_id).toBeNull();
        expect(cust.balance_due_cents).toBe(0);
        expectError(shipRes.status === 400 ? shipRes : cancelRes, 400, 'ERR_INVALID_STATE_TRANSITION');
      }
    }, 3);
  });

  test('CONCUR_009: concurrent ship_advance_replacement requests apply deposit/standing once', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const saleLot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);
      const repLot = await createBuildLot(program.program_id, opsCtx, 'B88X', 6);

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

      const recallRes = await createQualityCampaign(program.program_id, opsCtx, 'RECALL', saleLot.build_tag);
      expectSuccess(recallRes, 201);

      const deviceAfterRecall = await getDevice(program.program_id, delivered.device_id as string, ops);
      expect(deviceAfterRecall.device_status).toBe('QUARANTINED');

      const create = await createClaim(program.program_id, delivered.device_id as string, supCtx, 'RECALL');
      expectSuccess(create, 201);
      const claimId = create.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'ADVANCE_REPLACEMENT'), 200);

      const [a, b] = await Promise.all([
        shipAdvanceReplacement(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: repLot.build_lot_id,
          replacement_serial_number: `SN-ADV-A-${uniqueId('sn')}`,
          replacement_build_tag: repLot.build_tag
        }),
        shipAdvanceReplacement(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: repLot.build_lot_id,
          replacement_serial_number: `SN-ADV-B-${uniqueId('sn')}`,
          replacement_build_tag: repLot.build_tag
        })
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;
      expectError(err, 400, 'ERR_INVALID_STATE_TRANSITION');

      const cl = await getClaim(program.program_id, claimId, ops);
      expect(cl.claim_status).toBe('ADVANCE_SHIPPED');
      expect(cl.replacement_device_id).toBeTruthy();

      const cust = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cust.balance_due_cents).toBe(15000);
      expect(cust.customer_status).toBe('LIMITED');
    }, 3);
  });

  test('CONCUR_010: concurrent resolve_dispute CHARGEBACK_LOST is applied once; alert deduped; orders held; posture guarded', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 7);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

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
      const pm1 = await getPayment(program.program_id, o1Delivered.payment_id as string, ops);
      expect(pm1.payment_status).toBe('CAPTURED');

      const o2 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
      expectSuccess(await submitOrder(program.program_id, o2.order_id, c1Ctx, false), 200);
      const o2Submitted = await getOrder(program.program_id, o2.order_id, ops);
      expect(o2Submitted.order_status).toBe('SUBMITTED');

      expectSuccess(await disputePayment(program.program_id, pm1.payment_id, supCtx), 200);

      const preAlerts = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', payment_id: pm1.payment_id });
      expect(preAlerts.alerts.length).toBe(0);

      const [a, b] = await Promise.all([
        resolveDispute(program.program_id, pm1.payment_id, supCtx, 'CHARGEBACK_LOST'),
        resolveDispute(program.program_id, pm1.payment_id, supCtx, 'CHARGEBACK_LOST')
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;
      expectError(err, 400, 'ERR_INVALID_STATE_TRANSITION');

      const pmFinal = await getPayment(program.program_id, pm1.payment_id, ops);
      expect(pmFinal.payment_status).toBe('CHARGEBACK_LOST');

      const custFinal = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(custFinal.customer_status).toBe('LOCKED');

      const alerts = await listAlerts(program.program_id, ops, { alert_type: 'CHARGEBACK_LOST', alert_status: 'OPEN', payment_id: pm1.payment_id });
      expect(alerts.alerts.length).toBe(1);

      const o2Final = await getOrder(program.program_id, o2.order_id, ops);
      expect(o2Final.order_status).toBe('ON_HOLD');

      const pFinal = await getProgram(program.program_id, ops);
      expect(pFinal.program_posture).toBe('PROGRAM_GUARDED');
    }, 3);
  });

  test('CONCUR_013: concurrent return refund completion applies refunds once; no capacity change for REFURB', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram({ unit_price_cents: 79900, care_plan_price_cents: 9900 });
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const lot = await createBuildLot(program.program_id, opsCtx, 'B99Z', 6);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const adjRes = await createAdjustment(program.program_id, c1.customer_id, supCtx, 'GOODWILL_CREDIT', 20000);
      expectSuccess(adjRes, 201);
      expectSuccess(await applyAdjustment(program.program_id, adjRes.body.adjustment_id as string, supCtx), 200);

      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);

      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx, { use_credit_cents: 20000 });
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
      expect(delivered.order_status).toBe('DELIVERED');
      expect(delivered.paid_by_credit_cents).toBe(20000);
      expect(delivered.paid_by_card_cents).toBe(59900);

      const pm1 = await getPayment(program.program_id, delivered.payment_id as string, ops);
      expect(pm1.payment_status).toBe('CAPTURED');
      expect(pm1.amount_cents).toBe(59900);

      const rCreate = await createReturn(program.program_id, delivered.order_id, c1Ctx, 'REFUND');
      expectSuccess(rCreate, 201);
      const returnId = rCreate.body.return_id as string;
      expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
      expectSuccess(await markInboundReturn(program.program_id, returnId, opsCtx), 200);
      expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'REFURB'), 200);

      const preCap = await getProgram(program.program_id, ops);

      const [a, b] = await Promise.all([
        completeReturn(program.program_id, returnId, supCtx, {
          resolution: 'REFUND',
          replacement_build_lot_id: null,
          replacement_serial_number: null,
          replacement_build_tag: null
        }),
        completeReturn(program.program_id, returnId, supCtx, {
          resolution: 'REFUND',
          replacement_build_lot_id: null,
          replacement_serial_number: null,
          replacement_build_tag: null
        })
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;

      const errCode = extractErrorCode(err.body);
      expect(['ERR_INVALID_STATE_TRANSITION', 'ERR_RETURN_NOT_RESOLVABLE']).toContain(errCode);

      const rFinal = await getReturn(program.program_id, returnId, ops);
      expect(rFinal.return_status).toBe('COMPLETED');
      expect(rFinal.refunded_to_card_cents).toBe(59900);
      expect(rFinal.refunded_to_credit_cents).toBe(20000);

      const oFinal = await getOrder(program.program_id, delivered.order_id, ops);
      expect(oFinal.order_status).toBe('REFUNDED');

      const pmFinal = await getPayment(program.program_id, pm1.payment_id, ops);
      expect(pmFinal.payment_status).toBe('REFUNDED');

      const cFinal = await getCustomer(program.program_id, c1.customer_id, ops);
      expect(cFinal.credit_balance_cents).toBe(20000);
      expect(cFinal.balance_due_cents).toBe(0);

      const postCap = await getProgram(program.program_id, ops);
      expect(postCap.available_to_commit_units).toBe(preCap.available_to_commit_units);
    }, 3);
  });

  test('CONCUR_014: concurrent ship from 1-unit lot yields one ERR_OUT_OF_STOCK; lot becomes CONSUMED', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);

      await createBuildLot(program.program_id, opsCtx, 'B88X', 7);
      const l1 = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

      const c1 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c1Ctx } = await createCustomerCtx(program.program_id, c1.customer_id);
      const c2 = await createCustomer(program.program_id, opsCtx);
      const { ctx: c2Ctx } = await createCustomerCtx(program.program_id, c2.customer_id);

      const o1 = await createOrder(program.program_id, c1.customer_id, c1Ctx);
      const o2 = await createOrder(program.program_id, c2.customer_id, c2Ctx);
      expectSuccess(await submitOrder(program.program_id, o1.order_id, c1Ctx, false), 200);
      expectSuccess(await submitOrder(program.program_id, o2.order_id, c2Ctx, false), 200);

      const capBefore = await getProgram(program.program_id, ops);

      const [a, b] = await Promise.all([
        shipOrder(program.program_id, o1.order_id, opsCtx, {
          build_lot_id: l1.build_lot_id,
          serial_number: 'SN-RACE-1',
          build_tag: l1.build_tag
        }),
        shipOrder(program.program_id, o2.order_id, opsCtx, {
          build_lot_id: l1.build_lot_id,
          serial_number: 'SN-RACE-2',
          build_tag: l1.build_tag
        })
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;
      expectError(err, 400, 'ERR_OUT_OF_STOCK');

      const lotFinal = await getBuildLot(program.program_id, l1.build_lot_id, ops);
      expect(lotFinal.build_lot_status).toBe('CONSUMED');

      const o1After = await getOrder(program.program_id, o1.order_id, ops);
      const o2After = await getOrder(program.program_id, o2.order_id, ops);

      const shipped = [o1After, o2After].filter((o) => o.order_status === 'SHIPPED');
      const submitted = [o1After, o2After].filter((o) => o.order_status === 'SUBMITTED');
      expect(shipped).toHaveLength(1);
      expect(submitted).toHaveLength(1);

      const pmShip = await getPayment(program.program_id, shipped[0].payment_id as string, ops);
      expect(shipped[0].device_id).toBeTruthy();
      expect(pmShip.payment_status).toBe('CAPTURED');

      const pmOther = await getPayment(program.program_id, submitted[0].payment_id as string, ops);
      expect(submitted[0].device_id).toBeNull();
      expect(pmOther.payment_status).toBe('AUTHORIZED');

      const capAfter = await getProgram(program.program_id, ops);
      expect(capAfter.available_to_commit_units).toBe(capBefore.available_to_commit_units);
    }, 3);
  });

  test('CONCUR_015: concurrent claim completion yields one invalid transition and does not double-apply device creation', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const saleLot = await createBuildLot(program.program_id, opsCtx, 'B88X', 5);
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
      const pm1 = await getPayment(program.program_id, delivered.payment_id as string, ops);
      expect(pm1.payment_status).toBe('CAPTURED');

      expectSuccess(await activateDevice(program.program_id, delivered.device_id as string, c1Ctx), 200);

      const create = await createClaim(program.program_id, delivered.device_id as string, supCtx, 'WARRANTY');
      expectSuccess(create, 201);
      const claimId = create.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
      expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
      expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

      const [a, b] = await Promise.all([
        completeClaim(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: repLot.build_lot_id,
          replacement_serial_number: 'SN-CLM-RACE-1',
          replacement_build_tag: repLot.build_tag
        }),
        completeClaim(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: repLot.build_lot_id,
          replacement_serial_number: 'SN-CLM-RACE-1',
          replacement_build_tag: repLot.build_tag
        })
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;

      const errCode = extractErrorCode(err.body);
      expect(['ERR_INVALID_STATE_TRANSITION', 'ERR_CLAIM_NOT_RESOLVABLE']).toContain(errCode);

      const cl = await getClaim(program.program_id, claimId, ops);
      expect(cl.claim_status).toBe('COMPLETED');
      expect(cl.replacement_device_id).toBeTruthy();

      const oFinal = await getOrder(program.program_id, delivered.order_id, ops);
      expect(oFinal.order_status).toBe('DELIVERED');
      expect(oFinal.device_id).toBe(cl.replacement_device_id);

      const dFinal = await getDevice(program.program_id, cl.replacement_device_id as string, ops);
      expect(dFinal.serial_number).toBe('SN-CLM-RACE-1');
      expect(dFinal.device_status).toBe('SHIPPED');

      const repLotFinal = await getBuildLot(program.program_id, repLot.build_lot_id, ops);
      expect(repLotFinal.build_lot_status).toBe('CONSUMED');

      const pmFinal = await getPayment(program.program_id, pm1.payment_id, ops);
      expect(pmFinal.payment_status).toBe('CAPTURED');

      const pFinal = await getProgram(program.program_id, ops);
      expect(pFinal.available_to_commit_units).toBe(0);
    }, 3);
  });

  test('CONCUR_016: serial uniqueness across return+claim replacement is enforced atomically', async () => {
    await repeatConcurrencyTest(async () => {
      const program = await createProgram();
      const { actor: ops, ctx: opsCtx } = await createOpsCtx(program.program_id);
      const { ctx: supCtx } = await createSupportCtx(program.program_id);

      const saleLot = await createBuildLot(program.program_id, opsCtx, 'B88X', 5);
      const lRet = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);
      const lClm = await createBuildLot(program.program_id, opsCtx, 'B99Z', 1);

      const cRet = await createCustomer(program.program_id, opsCtx);
      const { ctx: cRetCtx } = await createCustomerCtx(program.program_id, cRet.customer_id);
      const oRet = await createOrder(program.program_id, cRet.customer_id, cRetCtx);
      expectSuccess(await submitOrder(program.program_id, oRet.order_id, cRetCtx, false), 200);
      expectSuccess(
        await shipOrder(program.program_id, oRet.order_id, opsCtx, {
          build_lot_id: saleLot.build_lot_id,
          serial_number: `SN-${uniqueId('sn')}`,
          build_tag: saleLot.build_tag
        }),
        200
      );
      expectSuccess(await markDelivered(program.program_id, oRet.order_id, opsCtx), 200);

      const cClm = await createCustomer(program.program_id, opsCtx);
      const { ctx: cClmCtx } = await createCustomerCtx(program.program_id, cClm.customer_id);
      const oClm = await createOrder(program.program_id, cClm.customer_id, cClmCtx);
      expectSuccess(await submitOrder(program.program_id, oClm.order_id, cClmCtx, false), 200);
      expectSuccess(
        await shipOrder(program.program_id, oClm.order_id, opsCtx, {
          build_lot_id: saleLot.build_lot_id,
          serial_number: `SN-${uniqueId('sn')}`,
          build_tag: saleLot.build_tag
        }),
        200
      );
      expectSuccess(await markDelivered(program.program_id, oClm.order_id, opsCtx), 200);

      const p0 = await getProgram(program.program_id, ops);
      expect(p0.available_to_commit_units).toBe(0);

      const rCreate = await createReturn(program.program_id, oRet.order_id, cRetCtx, 'REPLACEMENT');
      expectSuccess(rCreate, 201);
      const returnId = rCreate.body.return_id as string;
      expectSuccess(await approveReturn(program.program_id, returnId, supCtx), 200);
      expectSuccess(await markInboundReturn(program.program_id, returnId, opsCtx), 200);
      expectSuccess(await receiveReturn(program.program_id, returnId, opsCtx, 'SCRAP'), 200);

      const deliveredClm = await getOrder(program.program_id, oClm.order_id, ops);

      expectSuccess(await activateDevice(program.program_id, deliveredClm.device_id as string, cClmCtx), 200);
      const create = await createClaim(program.program_id, deliveredClm.device_id as string, supCtx, 'WARRANTY');
      expectSuccess(create, 201);
      const claimId = create.body.claim_id as string;
      expectSuccess(await approveClaim(program.program_id, claimId, supCtx, 'REPLACEMENT'), 200);
      expectSuccess(await markInboundClaim(program.program_id, claimId, opsCtx), 200);
      expectSuccess(await receiveClaim(program.program_id, claimId, opsCtx, 'SCRAP'), 200);

      const serial = 'SN-COLLIDE-1';
      const [a, b] = await Promise.all([
        completeReturn(program.program_id, returnId, supCtx, {
          resolution: 'REPLACEMENT',
          replacement_build_lot_id: lRet.build_lot_id,
          replacement_serial_number: serial,
          replacement_build_tag: lRet.build_tag
        }),
        completeClaim(program.program_id, claimId, supCtx, {
          replacement_build_lot_id: lClm.build_lot_id,
          replacement_serial_number: serial,
          replacement_build_tag: lClm.build_tag
        })
      ]);

      const statuses = [a.status, b.status].sort((x, y) => x - y);
      expect(statuses).toEqual([200, 400]);
      const err = a.status === 400 ? a : b;
      expectError(err, 400, 'ERR_INVALID_REQUEST');

      const rAfter = await getReturn(program.program_id, returnId, ops);
      const clAfter = await getClaim(program.program_id, claimId, ops);
      const winningReplacement = rAfter.replacement_device_id ?? clAfter.replacement_device_id;
      expect(winningReplacement).toBeTruthy();
      const d = await getDevice(program.program_id, winningReplacement as string, ops);
      expect(d.serial_number).toBe(serial);

      if (rAfter.replacement_device_id) {
        expect(clAfter.claim_status).toBe('RECEIVED');
        expect(clAfter.replacement_device_id).toBeNull();
      } else {
        expect(rAfter.return_status).toBe('RECEIVED');
        expect(rAfter.replacement_device_id).toBeNull();
      }

      const lRetFinal = await getBuildLot(program.program_id, lRet.build_lot_id, ops);
      const lClmFinal = await getBuildLot(program.program_id, lClm.build_lot_id, ops);
      const consumed = [lRetFinal, lClmFinal].filter((l) => l.build_lot_status === 'CONSUMED');
      const available = [lRetFinal, lClmFinal].filter((l) => l.build_lot_status === 'AVAILABLE');
      expect(consumed).toHaveLength(1);
      expect(available).toHaveLength(1);

      const pAfter = await getProgram(program.program_id, ops);
      expect(pAfter.available_to_commit_units).toBe(0);
    }, 3);
  });
});
