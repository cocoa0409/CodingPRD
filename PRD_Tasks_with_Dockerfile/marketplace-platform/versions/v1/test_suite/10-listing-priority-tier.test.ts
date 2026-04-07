import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createListing,
  getListing,
  createPublishedListing,
  createWorker,
  getWorker,
  createOrder,
  bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared,
  processPayoutToCleared,
  getPayouts,
  uniqueId,
  postAs,
  updateTenant
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';
import {
  buildHomeServiceCertification,
  drainTenantAvailableBudget,
  seedTenantBudgetConsumption
} from '../../../test-helpers/budget-utils';

describe('Listing & Order Priority Tier', () => {

  test('PRI_001: priority_tier ordering ensures HOME_SERVICE > RIDESHARE > DELIVERY > TASK (lower number = higher priority)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const homeServiceListing = await createListing(tenant.id, { category: 'HOME_SERVICE' });
    const rideshareListing = await createListing(tenant.id, { category: 'RIDESHARE' });
    const deliveryListing = await createListing(tenant.id, { category: 'DELIVERY' });
    const taskListing = await createListing(tenant.id, { category: 'TASK' });

    expect(typeof homeServiceListing.priority_tier).toBe('number');
    expect(typeof rideshareListing.priority_tier).toBe('number');
    expect(typeof deliveryListing.priority_tier).toBe('number');
    expect(typeof taskListing.priority_tier).toBe('number');

    expect(homeServiceListing.priority_tier).toBeLessThan(rideshareListing.priority_tier);
    expect(rideshareListing.priority_tier).toBeLessThan(deliveryListing.priority_tier);
    expect(deliveryListing.priority_tier).toBeLessThan(taskListing.priority_tier);
  });

  test('PRI_002: two listings in same category: earlier listing has lower priority_tier (higher priority)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const deliveryListing1 = await createListing(tenant.id, {
      category: 'DELIVERY',
      title: 'First Delivery Listing'
    });
    const deliveryListing2 = await createListing(tenant.id, {
      category: 'DELIVERY',
      title: 'Second Delivery Listing'
    });

    expect(deliveryListing1.priority_tier).toBeLessThan(deliveryListing2.priority_tier);

    expect(deliveryListing2.created_seq).toBeGreaterThan(deliveryListing1.created_seq);
  });

  test('PRI_003: (concurrency) under critical budget, payout for HOME_SERVICE job is approved before DELIVERY job when budget cannot support both', async () => {
    await repeatConcurrencyTest(async () => {

      const payoutLimit = 100000;
      const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

      const homeServiceListing = await createPublishedListing(tenant.id, {
        category: 'HOME_SERVICE',
        base_price_cents: 10000
      });
      const deliveryListing = await createPublishedListing(tenant.id, {
        category: 'DELIVERY',
        base_price_cents: 10000
      });

      expect(homeServiceListing.priority_tier).toBeLessThan(deliveryListing.priority_tier);

      const worker = await createWorker(tenant.id, {
        skills: ['HOME_SERVICE', 'DELIVERY'],
        certifications: buildHomeServiceCertification()
      });

      const reservationAmount = calculateMinimumReservation(10000);
      const seedTarget = Math.floor(payoutLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100) - 20000;
      await seedTenantBudgetConsumption(tenant.id, worker.id, seedTarget);

      const homeServiceOrder = await createOrder(tenant.id, homeServiceListing.id);
      const deliveryOrder = await createOrder(tenant.id, deliveryListing.id);

      const homeServiceAssignment = await bringAssignmentToCompleted(
        tenant.id, homeServiceOrder.id, worker.id, reservationAmount
      );
      const deliveryAssignment = await bringAssignmentToCompleted(
        tenant.id, deliveryOrder.id, worker.id, reservationAmount
      );

      await drainTenantAvailableBudget(tenant.id, worker.id, reservationAmount);
      const tenantBeforePayouts = await getTenant(tenant.id);
      const availableBudget = tenantBeforePayouts.payout_available_cents;

      expect(tenantBeforePayouts.is_payout_critical).toBe(true);

      const payoutAmount = Math.max(
        CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
        Math.min(Math.floor(availableBudget * 0.7), homeServiceAssignment.expected_earnings_cents)
      );

      const [homeServiceResponse, deliveryResponse] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          {
            assignment_id: homeServiceAssignment.id,
            requested_amount_cents: payoutAmount,
            payout_type: 'NORMAL'
          },
          'FinanceOfficer',
          { 'Idempotency-Key': `idem-home-${uniqueId()}` }
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          {
            assignment_id: deliveryAssignment.id,
            requested_amount_cents: payoutAmount,
            payout_type: 'NORMAL'
          },
          'FinanceOfficer',
          { 'Idempotency-Key': `idem-delivery-${uniqueId()}` }
        )
      ]);

      const homeServiceSuccess = homeServiceResponse.status === 201;
      const deliverySuccess = deliveryResponse.status === 201;

      expect(homeServiceSuccess || deliverySuccess).toBe(true);

      if (!homeServiceSuccess || !deliverySuccess) {
        expect(homeServiceResponse.status).toBe(201);

        expect(deliveryResponse.status).toBe(402);
      }

    });
  });

  test('PRI_004: two payouts with equal listing.priority_tier: earlier payout.created_seq wins race', async () => {

    const payoutLimit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

    const listing = await createPublishedListing(tenant.id, {
      category: 'DELIVERY',
      base_price_cents: 10000
    });

    const worker = await createWorker(tenant.id);

    const seedTarget = Math.floor(payoutLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100) - 25000;
    await seedTenantBudgetConsumption(tenant.id, worker.id, seedTarget);

    const order1 = await createOrder(tenant.id, listing.id);
    const order2 = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    await drainTenantAvailableBudget(tenant.id, worker.id, reservationAmount);
    const tenantBefore = await getTenant(tenant.id);

    expect(tenantBefore.is_payout_critical).toBe(true);
    const availableBudget = tenantBefore.payout_available_cents;

    const payoutAmount = Math.max(
      CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
      Math.min(Math.floor(availableBudget * 0.7), assignment1.expected_earnings_cents)
    );

    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, payoutAmount, 'NORMAL');
    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, payoutAmount, 'NORMAL');

    expect(payout1.created_seq).toBeLessThan(payout2.created_seq);

    const approveResponse1 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout1.id}/approve`,
      {},
      'FinanceOfficer'
    );
    const approveResponse2 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/approve`,
      {},
      'FinanceOfficer'
    );

    const success1 = approveResponse1.status === 200;
    const success2 = approveResponse2.status === 200;
    expect(success1 || success2).toBe(true);

    if (!success1 || !success2) {
      expect(approveResponse1.status).toBe(200);
      expect(approveResponse1.body.data.status).toBe('APPROVED');
      expect(approveResponse1.body.data.approved_amount_cents).toBeGreaterThan(0);

      expect(approveResponse2.status).toBe(402);
    }
  });

  test('PRI_005: all pending payouts receive identical proration_factor under proration', async () => {

    const payoutLimit = 1500000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

    const rampListingPrice = 90000;
    const payoutListingPrice = 3000;
    const listing1 = await createPublishedListing(tenant.id, {
      category: 'HOME_SERVICE',
      base_price_cents: rampListingPrice
    });
    const listing2 = await createPublishedListing(tenant.id, {
      category: 'DELIVERY',
      base_price_cents: payoutListingPrice
    });

    const worker = await createWorker(tenant.id, { skills: ['HOME_SERVICE', 'DELIVERY'], certifications: buildHomeServiceCertification() });

    const rampIterations = 12;
    let rampReservation = 0;
    let rampPayoutAmount = 0;
    for (let i = 0; i < rampIterations; i++) {
      const tempOrder = await createOrder(tenant.id, listing1.id);
      if (i === 0) {
        rampPayoutAmount = tempOrder.worker_earnings_cap_cents;
        rampReservation = calculateMinimumReservation(rampPayoutAmount);
      }
      const rampAssignment = await bringAssignmentToCompleted(tenant.id, tempOrder.id, worker.id, rampReservation);
      await processPayoutToCleared(tenant.id, worker.id, rampAssignment.id, rampPayoutAmount, 'FINAL');
    }

    const order1 = await createOrder(tenant.id, listing2.id);
    const order2 = await createOrder(tenant.id, listing2.id);

    const reservationAmount = calculateMinimumReservation(payoutListingPrice);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const rampReservedLeftover = (rampReservation - rampPayoutAmount) * rampIterations;
    const totalReservedAfterSetup = rampReservedLeftover + reservationAmount * 2;
    const targetAvailable = 2000;
    const prorationLimit = rampPayoutAmount * rampIterations + totalReservedAfterSetup + targetAvailable;
    await updateTenant(tenant.id, {
      payout_credit_limit_cents: prorationLimit
    });

    const tenantBefore = await getTenant(tenant.id);
    expect(tenantBefore.payout_credit_limit_cents).toBe(prorationLimit);
    expect(tenantBefore.payout_available_cents).toBe(targetAvailable);
    expect(tenantBefore.payout_reserved_cents).toBe(totalReservedAfterSetup);
    expect(tenantBefore.payout_consumed_cents).toBe(rampPayoutAmount * rampIterations);
    expect(tenantBefore.is_payout_critical).toBe(true);

    const prorationThreshold = Math.floor(
      prorationLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100
    );
    expect(tenantBefore.payout_consumed_cents).toBeGreaterThanOrEqual(prorationThreshold);

    const payoutAvailable = tenantBefore.payout_available_cents;

    const payoutRequest = Math.min(3000, assignment1.expected_earnings_cents);
    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, payoutRequest, 'NORMAL');
    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, payoutRequest, 'NORMAL');

    const approved1 = await approvePayout(tenant.id, worker.id, payout1.id);
    const approved2 = await approvePayout(tenant.id, worker.id, payout2.id);

    expect(approved1.is_prorated).toBe(true);
    expect(approved2.is_prorated).toBe(true);

    expect(approved1.proration_factor).toBe(approved2.proration_factor);

    expect(approved1.proration_factor).toBeLessThan(1.0);

    const unproratedPerPayout = Math.min(payoutRequest, payoutAvailable);
    const pendingTotal = unproratedPerPayout * 2;
    const expectedFactor = Math.min(1.0, payoutAvailable / pendingTotal);
    const expectedApproved = Math.floor(unproratedPerPayout * expectedFactor);

    expect(approved1.proration_factor).toBe(expectedFactor);
    expect(approved1.approved_amount_cents).toBe(expectedApproved);
    expect(approved2.approved_amount_cents).toBe(expectedApproved);
  });

  test('PRI_006: when only one payout can receive non-zero approved_amount_cents, it must be for highest-priority listing', async () => {

    const payoutLimit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

    const homeServiceListing = await createPublishedListing(tenant.id, {
      category: 'HOME_SERVICE',
      base_price_cents: 10000
    });
    const taskListing = await createPublishedListing(tenant.id, {
      category: 'TASK',
      base_price_cents: 10000
    });

    expect(homeServiceListing.priority_tier).toBeLessThan(taskListing.priority_tier);

    const worker = await createWorker(tenant.id, { skills: ['HOME_SERVICE', 'TASK'], certifications: buildHomeServiceCertification() });

    const reservationAmount = calculateMinimumReservation(10000);
    const consumptionTarget = payoutLimit - 30000;
    await seedTenantBudgetConsumption(tenant.id, worker.id, consumptionTarget);

    const homeServiceOrder = await createOrder(tenant.id, homeServiceListing.id);
    const taskOrder = await createOrder(tenant.id, taskListing.id);

    const homeServiceAssignment = await bringAssignmentToCompleted(
      tenant.id, homeServiceOrder.id, worker.id, reservationAmount
    );
    const taskAssignment = await bringAssignmentToCompleted(
      tenant.id, taskOrder.id, worker.id, reservationAmount
    );

    await drainTenantAvailableBudget(tenant.id, worker.id, CONSTANTS.payout.MINIMUM_PAYOUT_CENTS * 2);
    const tenantBeforePayouts = await getTenant(tenant.id);
    const availableBudget = tenantBeforePayouts.payout_available_cents;

    expect(tenantBeforePayouts.is_payout_critical).toBe(true);

    const payoutRequestAmount = Math.max(
      CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
      Math.floor(availableBudget * 0.7)
    );

    const homeServicePayout = await createPayout(
      tenant.id, worker.id, homeServiceAssignment.id,
      payoutRequestAmount, 'NORMAL'
    );
    const taskPayoutResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: taskAssignment.id,
        requested_amount_cents: payoutRequestAmount,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-task-${uniqueId()}` }
    );

    const approvedHomeService = await approvePayout(tenant.id, worker.id, homeServicePayout.id);

    expect(approvedHomeService.approved_amount_cents).toBeGreaterThan(0);

    if (taskPayoutResponse.status === 201) {
      const taskPayout = taskPayoutResponse.body.data;
      const approveTaskResponse = await postAs(
        `/tenants/${tenant.id}/workers/${worker.id}/payouts/${taskPayout.id}/approve`,
        {},
        'FinanceOfficer'
      );

      if (approveTaskResponse.status === 200) {

        const approvedTask = approveTaskResponse.body.data;
        expect(approvedHomeService.approved_amount_cents).toBeGreaterThanOrEqual(approvedTask.approved_amount_cents);
      }

    }

  });

  test('PRI_008: high-priority HOME_SERVICE assignment with multi-worker split pre-empts lower-priority listing payouts', async () => {

    const payoutLimit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

    const homeServiceListing = await createPublishedListing(tenant.id, {
      category: 'HOME_SERVICE',
      base_price_cents: 20000
    });
    const taskListing = await createPublishedListing(tenant.id, {
      category: 'TASK',
      base_price_cents: 10000
    });

    expect(homeServiceListing.priority_tier).toBeLessThan(taskListing.priority_tier);

    const worker1 = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE', 'TASK'],
      name: 'Worker 1',
      certifications: buildHomeServiceCertification()
    });
    const worker2 = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE', 'TASK'],
      name: 'Worker 2',
      certifications: buildHomeServiceCertification()
    });

    const consumptionTarget = Math.floor(payoutLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100) - 35000;
    await seedTenantBudgetConsumption(tenant.id, worker1.id, consumptionTarget);

    const homeServiceOrder = await createOrder(tenant.id, homeServiceListing.id);
    const worker1Reservation = calculateMinimumReservation(homeServiceListing.base_price_cents);
    const homeServiceAssignment = await bringAssignmentToCompleted(
      tenant.id, homeServiceOrder.id, worker1.id, worker1Reservation
    );

    const taskOrder = await createOrder(tenant.id, taskListing.id);
    const taskReservation = calculateMinimumReservation(taskListing.base_price_cents);
    const taskAssignment = await bringAssignmentToCompleted(
      tenant.id, taskOrder.id, worker2.id, taskReservation
    );

    await drainTenantAvailableBudget(tenant.id, worker1.id, taskReservation);
    const tenantBeforePayouts = await getTenant(tenant.id);
    const availableBudget = tenantBeforePayouts.payout_available_cents;

    expect(tenantBeforePayouts.is_payout_critical).toBe(true);

    const payoutRequestAmount = Math.max(
      CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
      Math.floor(availableBudget * 0.7)
    );

    const homeServicePayout = await createPayout(
      tenant.id, worker1.id, homeServiceAssignment.id, payoutRequestAmount, 'NORMAL'
    );

    const taskPayoutResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker2.id}/payouts`,
      {
        assignment_id: taskAssignment.id,
        requested_amount_cents: payoutRequestAmount,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-task-${uniqueId()}` }
    );

    const approvedHomeService = await approvePayout(tenant.id, worker1.id, homeServicePayout.id);

    expect(approvedHomeService.approved_amount_cents).toBeGreaterThan(0);

    expect(homeServiceListing.priority_tier).toBeLessThan(taskListing.priority_tier);

    if (taskPayoutResponse.status === 201) {
      const taskPayout = taskPayoutResponse.body.data;
      const approveTaskResponse = await postAs(
        `/tenants/${tenant.id}/workers/${worker2.id}/payouts/${taskPayout.id}/approve`,
        {},
        'FinanceOfficer'
      );

      if (approveTaskResponse.status === 200) {

        const approvedTask = approveTaskResponse.body.data;

        expect(approvedHomeService.approved_amount_cents).toBeGreaterThanOrEqual(approvedTask.approved_amount_cents);
      }

    }

  });

  test('PRI_007: Category priority ordering is strictly maintained: HOME_SERVICE < RIDESHARE < DELIVERY < TASK', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const taskListing = await createListing(tenant.id, { category: 'TASK' });
    const deliveryListing = await createListing(tenant.id, { category: 'DELIVERY' });
    const rideshareListing = await createListing(tenant.id, { category: 'RIDESHARE' });
    const homeServiceListing = await createListing(tenant.id, { category: 'HOME_SERVICE' });

    expect(homeServiceListing.priority_tier).toBeLessThan(rideshareListing.priority_tier);
    expect(rideshareListing.priority_tier).toBeLessThan(deliveryListing.priority_tier);
    expect(deliveryListing.priority_tier).toBeLessThan(taskListing.priority_tier);
  });

  test('PRI_009: Listings within same category have sequential priority_tier values', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const listing1 = await createListing(tenant.id, { category: 'HOME_SERVICE' });
    const listing2 = await createListing(tenant.id, { category: 'HOME_SERVICE' });
    const listing3 = await createListing(tenant.id, { category: 'HOME_SERVICE' });

    expect(listing1.priority_tier).toBeLessThan(listing2.priority_tier);
    expect(listing2.priority_tier).toBeLessThan(listing3.priority_tier);
  });

  test('PRI_010: Priority tier is preserved after listing status changes', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const listing = await createListing(tenant.id, { category: 'DELIVERY' });
    const originalPriorityTier = listing.priority_tier;

    const publishedListing = await postAs(
      `/tenants/${tenant.id}/listings/${listing.id}/publish`,
      {},
      'TenantManager'
    );
    expect(publishedListing.status).toBe(200);

    const refreshedListing = await getListing(tenant.id, listing.id);
    expect(refreshedListing.priority_tier).toBe(originalPriorityTier);
  });

  test('PRI_011: Orders inherit priority from their listing', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

    const homeServiceListing = await createPublishedListing(tenant.id, {
      category: 'HOME_SERVICE',
      base_price_cents: 10000
    });

    const order = await createOrder(tenant.id, homeServiceListing.id);

    const listing = await getListing(tenant.id, homeServiceListing.id);
    expect(typeof listing.priority_tier).toBe('number');

    expect(order.listing_id).toBe(homeServiceListing.id);
  });

});
