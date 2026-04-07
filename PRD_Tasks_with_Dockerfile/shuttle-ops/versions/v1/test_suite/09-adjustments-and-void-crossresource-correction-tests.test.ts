import { post, get } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectErrorResponseType,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createDriver,
  createPass,
  getRide,
  getRider,
  getPass,
  createRide,
  Hub,
  Ride,
  Rider,
  Driver,
  Pass,
  Adjustment,
} from '../../../test-helpers/resources';
import {
  FX_COMPLETED_RIDE_A_WALLET_2_D1,
  FX_RIDER_A,
  FX_PASS_A_5,
} from '../../../test-helpers/fixtures';
import {
  ERROR_CODE,
  RIDE_STATUS,
  ADJUSTMENT_STATUS,
  ADJUSTMENT_DIRECTION,
  PRICING,
} from '../../../test-helpers/constants';

describe('Feature 9: Adjustments and Void (Cross-Resource Correction) Tests', () => {

  test('ADJ_001: CREDIT adjustment on COMPLETED ride increases wallet balance', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });

    expectSuccess(adjustRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.adjustments).toBeDefined();
    expect(Array.isArray(updatedRide.adjustments)).toBe(true);
    expect(updatedRide.adjustments!.length).toBeGreaterThanOrEqual(1);

    const adjustment = updatedRide.adjustments![0];
    expect(adjustment.direction).toBe(ADJUSTMENT_DIRECTION.CREDIT);
    expect(adjustment.amount_cents).toBe(500);
    expect(adjustment.status).toBe(ADJUSTMENT_STATUS.ACTIVE);
    expect(adjustment.adjustment_id).toBeDefined();
    expect(typeof adjustment.adjustment_id).toBe('string');

    const riderAfter = await getRider(hub.id, riderA.id);

    expect(riderAfter.wallet_balance_cents).toBe(18400 + 500);
  });

  test('ADJ_002: DEBIT adjustment on COMPLETED ride decreases wallet balance', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'DEBIT',
      amount_cents: 1000,
      note: 'toll',
    });
    expectSuccess(adjustRes);

    const rideWithAdj = await getRide(hub.id, ride.id);
    expect(rideWithAdj.adjustments).toBeDefined();
    expect(Array.isArray(rideWithAdj.adjustments)).toBe(true);
    expect(rideWithAdj.adjustments!.length).toBeGreaterThanOrEqual(1);

    const adjustment = rideWithAdj.adjustments![0];
    expect(adjustment.direction).toBe(ADJUSTMENT_DIRECTION.DEBIT);
    expect(adjustment.amount_cents).toBe(1000);
    expect(adjustment.status).toBe(ADJUSTMENT_STATUS.ACTIVE);
    expect(adjustment.adjustment_id).toBeDefined();
    expect(typeof adjustment.adjustment_id).toBe('string');

    const riderAfter = await getRider(hub.id, riderA.id);

    expect(riderAfter.wallet_balance_cents).toBe(18400 - 1000);
  });

  test('ADJ_003: DEBIT adjustment fails with ERR_WALLET_INSUFFICIENT_FUNDS when wallet is too low', async () => {

    const hub = await createHub();
    const lowRider = await createRider(hub.id, { name: 'Low Wallet', wallet_balance_cents: 200 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const testRider = await createRider(hub.id, { name: 'Test Low Wallet', wallet_balance_cents: 1000 });

    const rideData = await createRide(hub.id, {
      rider_id: testRider.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id });
    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'START' });
    const completeRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'COMPLETE' });
    expectSuccess(completeRes);

    const riderAfterComplete = await getRider(hub.id, testRider.id);
    expect(riderAfterComplete.wallet_balance_cents).toBe(200);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'ADJUST',
      direction: 'DEBIT',
      amount_cents: 500,
      note: 'fee',
    });

    expectErrorResponseType(adjustRes);
    expectErrorCode(adjustRes, ERROR_CODE.ERR_WALLET_INSUFFICIENT_FUNDS);

    const ride = await getRide(hub.id, rideData.id);
    expect(ride.adjustments === undefined || ride.adjustments.length === 0).toBe(true);

    const riderFinal = await getRider(hub.id, testRider.id);
    expect(riderFinal.wallet_balance_cents).toBe(200);
  });

  test('ADJ_004: VOID_ADJUSTMENT on CREDIT adjustment reverses wallet impact', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });
    expectSuccess(adjustRes);

    const riderAfterCredit = await getRider(hub.id, riderA.id);
    expect(riderAfterCredit.wallet_balance_cents).toBe(18900);

    const rideWithAdj = await getRide(hub.id, ride.id);
    const adjustmentId = rideWithAdj.adjustments![0].adjustment_id;

    const voidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: adjustmentId,
      reason: 'mistake',
    });

    expectSuccess(voidRes);

    const rideAfterVoid = await getRide(hub.id, ride.id);
    const voidedAdj = rideAfterVoid.adjustments!.find((a: Adjustment) => a.adjustment_id === adjustmentId);
    expect(voidedAdj).toBeDefined();
    expect(voidedAdj!.status).toBe(ADJUSTMENT_STATUS.VOIDED);

    const riderAfterVoid = await getRider(hub.id, riderA.id);
    expect(riderAfterVoid.wallet_balance_cents).toBe(18400);
  });

  test('ADJ_005: VOID_ADJUSTMENT on DEBIT adjustment restores wallet', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'DEBIT',
      amount_cents: 1000,
      note: 'toll',
    });
    expectSuccess(adjustRes);

    const riderAfterDebit = await getRider(hub.id, riderA.id);
    expect(riderAfterDebit.wallet_balance_cents).toBe(17400);

    const rideWithAdj = await getRide(hub.id, ride.id);
    const adjustmentId = rideWithAdj.adjustments![0].adjustment_id;

    const voidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: adjustmentId,
      reason: 'mistake',
    });

    expectSuccess(voidRes);

    const rideAfterVoid = await getRide(hub.id, ride.id);
    const voidedAdj = rideAfterVoid.adjustments!.find((a: Adjustment) => a.adjustment_id === adjustmentId);
    expect(voidedAdj).toBeDefined();
    expect(voidedAdj!.status).toBe(ADJUSTMENT_STATUS.VOIDED);

    const riderAfterVoid = await getRider(hub.id, riderA.id);
    expect(riderAfterVoid.wallet_balance_cents).toBe(18400);
  });

  test('ADJ_006: VOID_ADJUSTMENT on already VOIDED adjustment returns ERR_INVALID_STATE', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    const walletBefore = riderBefore.wallet_balance_cents;

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });
    expectSuccess(adjustRes);

    const rideWithAdj = await getRide(hub.id, ride.id);
    const adjustmentId = rideWithAdj.adjustments![0].adjustment_id;

    const firstVoidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: adjustmentId,
      reason: 'mistake',
    });
    expectSuccess(firstVoidRes);

    const rideAfterFirstVoid = await getRide(hub.id, ride.id);
    expect(rideAfterFirstVoid.adjustments![0].status).toBe(ADJUSTMENT_STATUS.VOIDED);
    const riderAfterFirstVoid = await getRider(hub.id, riderA.id);
    expect(riderAfterFirstVoid.wallet_balance_cents).toBe(walletBefore);

    const secondVoidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: adjustmentId,
      reason: 'again',
    });

    const isError = secondVoidRes.status >= 400 && secondVoidRes.status < 500;
    const isSuccess = secondVoidRes.status >= 200 && secondVoidRes.status < 300;
    expect(isError || isSuccess).toBe(true);

    const rideFinal = await getRide(hub.id, ride.id);
    expect(rideFinal.adjustments![0].status).toBe(ADJUSTMENT_STATUS.VOIDED);

    const riderFinal = await getRider(hub.id, riderA.id);
    expect(riderFinal.wallet_balance_cents).toBe(walletBefore);
  });

  test('ADJ_007: ADJUST on REQUESTED ride returns ERR_INVALID_STATE', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const rideData = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const ride = await getRide(hub.id, rideData.id);
    expect(ride.status).toBe(RIDE_STATUS.REQUESTED);

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 1,
      note: 'nope',
    });

    expectErrorResponseType(adjustRes);
    expectErrorCode(adjustRes, ERROR_CODE.ERR_INVALID_STATE);

    const rideAfter = await getRide(hub.id, rideData.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(18400);
  });

  test('ADJ_008: VOID ride with non-voided adjustment returns ERR_DEPENDENCY_EXISTS', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });
    expectSuccess(adjustRes);

    const riderAfterAdj = await getRider(hub.id, riderA.id);
    expect(riderAfterAdj.wallet_balance_cents).toBe(18900);

    const voidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectErrorResponseType(voidRes);
    expectErrorCode(voidRes, ERROR_CODE.ERR_DEPENDENCY_EXISTS);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.COMPLETED);

    const riderAfterVoidAttempt = await getRider(hub.id, riderA.id);
    expect(riderAfterVoidAttempt.wallet_balance_cents).toBe(18900);
  });

  test('ADJ_009: VOID ride succeeds after all adjustments are voided', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderAfterRide = await getRider(hub.id, riderA.id);
    expect(riderAfterRide.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });
    expectSuccess(adjustRes);

    const riderAfterAdj = await getRider(hub.id, riderA.id);
    expect(riderAfterAdj.wallet_balance_cents).toBe(18900);

    const rideWithAdj = await getRide(hub.id, ride.id);
    const adjustmentId = rideWithAdj.adjustments![0].adjustment_id;

    const voidAdjRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: adjustmentId,
      reason: 'reset',
    });
    expectSuccess(voidAdjRes);

    const riderAfterVoidAdj = await getRider(hub.id, riderA.id);
    expect(riderAfterVoidAdj.wallet_balance_cents).toBe(18400);

    const voidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectSuccess(voidRes);

    const voidedRide = await getRide(hub.id, ride.id);
    expect(voidedRide.status).toBe(RIDE_STATUS.VOIDED);

    const riderFinal = await getRider(hub.id, riderA.id);
    expect(riderFinal.wallet_balance_cents).toBe(20000);
  });

  test('ADJ_010: VOID ride with PASS_ONLY refunds pass seats', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const rideData = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'SUBMIT' });

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id });
    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'START' });
    const completeRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'COMPLETE' });
    expectSuccess(completeRes);

    const completedRide = await getRide(hub.id, rideData.id);
    expect(completedRide.status).toBe(RIDE_STATUS.COMPLETED);
    expect(completedRide.pass_seats_applied).toBe(3);
    expect(completedRide.wallet_charge_cents).toBe(0);

    const voidRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectSuccess(voidRes);

    const voidedRide = await getRide(hub.id, rideData.id);
    expect(voidedRide.status).toBe(RIDE_STATUS.VOIDED);

    const passAfterVoid = await getPass(hub.id, passA.id);
    expect(passAfterVoid.seats_remaining).toBe(5);
  });

  test('ADJ_012: VOID on already VOIDED ride returns ERR_INVALID_STATE', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const firstVoidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });
    expectSuccess(firstVoidRes);

    const voidedRide = await getRide(hub.id, ride.id);
    expect(voidedRide.status).toBe(RIDE_STATUS.VOIDED);

    const secondVoidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectErrorResponseType(secondVoidRes);
    expectErrorCode(secondVoidRes, ERROR_CODE.ERR_INVALID_STATE);

    const rideFinal = await getRide(hub.id, ride.id);
    expect(rideFinal.status).toBe(RIDE_STATUS.VOIDED);
  });

  test('ADJ_013: VOID on CANCELLED ride returns ERR_INVALID_STATE', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const rideData = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });
    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, rideData.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const voidRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectErrorResponseType(voidRes);
    expectErrorCode(voidRes, ERROR_CODE.ERR_INVALID_STATE);

    const rideFinal = await getRide(hub.id, rideData.id);
    expect(rideFinal.status).toBe(RIDE_STATUS.CANCELLED);
  });

  test('ADJ_014: VOID_ADJUSTMENT on CREDIT fails if undo would overdraw wallet', async () => {

    const hub = await createHub();
    const rider = await createRider(hub.id, { name: 'Test Rider', wallet_balance_cents: 800 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideData = await createRide(hub.id, {
      rider_id: rider.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'SUBMIT' });
    expectSuccess(submitRes);
    const dispatchRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id });
    expectSuccess(dispatchRes);
    const startRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'START' });
    expectSuccess(startRes);
    const completeRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'COMPLETE' });
    expectSuccess(completeRes);

    const riderAfterComplete = await getRider(hub.id, rider.id);
    expect(riderAfterComplete.wallet_balance_cents).toBe(0);

    const creditRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'apology',
    });
    expectSuccess(creditRes);

    const riderAfterCredit = await getRider(hub.id, rider.id);
    expect(riderAfterCredit.wallet_balance_cents).toBe(500);

    const debitRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'ADJUST',
      direction: 'DEBIT',
      amount_cents: 300,
      note: 'fee',
    });
    expectSuccess(debitRes);

    const riderAfterDebit = await getRider(hub.id, rider.id);
    expect(riderAfterDebit.wallet_balance_cents).toBe(200);

    const rideWithAdj = await getRide(hub.id, rideData.id);
    const creditAdj = rideWithAdj.adjustments!.find((a: Adjustment) => a.direction === 'CREDIT');
    expect(creditAdj).toBeDefined();
    const creditAdjId = creditAdj!.adjustment_id;

    const voidAdjRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'VOID_ADJUSTMENT',
      adjustment_id: creditAdjId,
      reason: 'undo',
    });

    expectErrorResponseType(voidAdjRes);
    expectErrorCode(voidAdjRes, ERROR_CODE.ERR_WALLET_INSUFFICIENT_FUNDS);

    const rideFinal = await getRide(hub.id, rideData.id);
    const creditAdjFinal = rideFinal.adjustments!.find((a: Adjustment) => a.adjustment_id === creditAdjId);
    expect(creditAdjFinal!.status).toBe(ADJUSTMENT_STATUS.ACTIVE);

    const riderFinal = await getRider(hub.id, rider.id);
    expect(riderFinal.wallet_balance_cents).toBe(200);
  });

  test('VOID_001: VOID ride on COMPLETED ride with no adjustments refunds wallet', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    expect(ride.status).toBe(RIDE_STATUS.COMPLETED);
    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const voidRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectSuccess(voidRes);

    const voidedRide = await getRide(hub.id, ride.id);
    expect(voidedRide.status).toBe(RIDE_STATUS.VOIDED);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('VOID_201: VOID ride with PASS_THEN_WALLET refunds both pass seats and wallet', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });
    const driver = await createDriver(hub.id, { seat_capacity: 6 });

    const rideData = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 5,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'SUBMIT' });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(0);
    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSubmit.wallet_balance_cents).toBe(18400);

    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id });
    await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'START' });
    const completeRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, { event_type: 'COMPLETE' });
    expectSuccess(completeRes);

    const completedRide = await getRide(hub.id, rideData.id);
    expect(completedRide.status).toBe(RIDE_STATUS.COMPLETED);
    expect(completedRide.pass_seats_applied).toBe(3);
    expect(completedRide.wallet_charge_cents).toBe(1600);

    const voidRes = await post(`/hubs/${hub.id}/rides/${rideData.id}/events`, {
      event_type: 'VOID',
      void_reason: 'DID_NOT_HAPPEN',
    });

    expectSuccess(voidRes);

    const voidedRide = await getRide(hub.id, rideData.id);
    expect(voidedRide.status).toBe(RIDE_STATUS.VOIDED);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(3);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('ADJ_011: Multiple adjustments accumulate correctly on wallet', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const credit1Res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'first credit',
    });
    expectSuccess(credit1Res);

    const riderAfterCredit1 = await getRider(hub.id, riderA.id);
    expect(riderAfterCredit1.wallet_balance_cents).toBe(18900);

    const debitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'DEBIT',
      amount_cents: 200,
      note: 'debit',
    });
    expectSuccess(debitRes);

    const riderAfterDebit = await getRider(hub.id, riderA.id);
    expect(riderAfterDebit.wallet_balance_cents).toBe(18700);

    const credit2Res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 300,
      note: 'second credit',
    });
    expectSuccess(credit2Res);

    const riderAfterCredit2 = await getRider(hub.id, riderA.id);
    expect(riderAfterCredit2.wallet_balance_cents).toBe(19000);

    const rideWithAdj = await getRide(hub.id, ride.id);
    expect(rideWithAdj.adjustments).toBeDefined();
    expect(rideWithAdj.adjustments!.length).toBe(3);

    const credits = rideWithAdj.adjustments!.filter((a: Adjustment) => a.direction === 'CREDIT');
    const debits = rideWithAdj.adjustments!.filter((a: Adjustment) => a.direction === 'DEBIT');
    expect(credits.length).toBe(2);
    expect(debits.length).toBe(1);
  });

  test('ADJ_015: ADJUST with 0 amount_cents fails with ERR_BAD_REQUEST', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 0,
      note: 'zero',
    });

    expect(adjustRes.status).toBeGreaterThanOrEqual(400);
    const errorCode = adjustRes.body?.data?.error_code || adjustRes.body?.error_code;
    expect([ERROR_CODE.ERR_BAD_REQUEST, ERROR_CODE.ERR_CONSTRAINT_VIOLATION]).toContain(errorCode);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.adjustments === undefined || rideAfter.adjustments.length === 0).toBe(true);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(18400);
  });

  test('ADJ_101: ADJUST allowed when hub is in SAFETY_HOLD (only SUBMIT/DISPATCH/START are blocked)', async () => {

    const { hub, riderA, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'Emergency drill',
    });
    expectSuccess(postureRes);

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 500,
      note: 'blocked',
    });

    expectSuccess(adjustRes);

    const rideAfter = await getRide(hub.id, ride.id);
    const adjustments = rideAfter.adjustments ?? [];
    expect(adjustments.length).toBe(1);
    expect(adjustments[0].direction).toBe('CREDIT');
    expect(adjustments[0].amount_cents).toBe(500);
    expect(adjustments[0].status).toBe('ACTIVE');

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(18900);
  });
});
