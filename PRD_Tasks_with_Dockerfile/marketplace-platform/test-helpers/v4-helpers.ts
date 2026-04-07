import { CONSTANTS } from './constants';
import { calculateMinimumReservation } from './calculations';
import {
  acceptAssignment,
  cancelPayout,
  CapacityPoolInput,
  completeAssignment,
  createRating,
  ListingInput,
  TenantInput,
  WorkerInput,
  advanceClock,
  bringAssignmentToCompleted,
  createAssignment,
  createCapacityPool,
  createOrder,
  createPayout,
  createPublishedListing,
  createTenant,
  createWorker,
  getAssignments,
  getListings,
  getOrder,
  getTenant,
  getWorker,
  moderateRating,
  postAs,
  processPayoutToCleared,
  startAssignment,
  updateTenant
} from './resources';

export interface PendingPayoutRecord {
  worker: any;
  order: any;
  assignment: any;
  payout: any;
}

export interface UnderfundedSetupOptions {
  tenantConfig?: Partial<TenantInput>;
  listingBasePriceCents?: number;
  workerConfig?: Partial<WorkerInput>;
  reservedCents?: number | ((minimumReservation: number) => number);
}

export interface PoolTenantSetupOptions {
  tenantConfig?: Partial<TenantInput>;
  poolConfig?: Partial<CapacityPoolInput>;
  listingConfig?: Partial<ListingInput>;
}

export interface BasicSetupOptions {
  tenantConfig?: Partial<TenantInput>;
  workerConfig?: Partial<WorkerInput>;
  listingConfig?: Partial<ListingInput>;
}

export interface PoolSetupOptions extends BasicSetupOptions {
  poolConfig?: Partial<CapacityPoolInput>;
}

export interface UnderfundedAssignmentOptions {
  reservedCents?: number | ((minimumReservation: number) => number);
  allowZeroReservation?: boolean;
}

export interface HoldAssignmentContext {
  tenant: any;
  listing: any;
  worker: any;
  order: any;
  assignment: any;
}

export interface HoldAssignmentOptions {
  reservationAmount?: number;
  tenantOverrides?: Partial<TenantInput>;
  listingOverrides?: Partial<ListingInput>;
}

export interface WorkerCapSetup {
  tenant: any;
  worker: any;
  blockingAssignments: { order: any; assignment: any }[];
}

export interface LiquidityHoldContext {
  tenant: any;
  pool: any;
  listing: any;
  worker: any;
  pendingPayouts: PendingPayoutRecord[];
}

export interface TopUpPromotionContext {
  tenant: any;
  pool: any;
  listing: any;
  workerTopUp: any;
  workerAwaiting: any;
  orderTopUp: any;
  assignmentTopUp: any;
  minimumReservation: number;
  topUpAmount: number;
  orderAwaiting: any;
  awaitingAssignment: any;
  pendingRecords: PendingPayoutRecord[];
}

export interface WorkerCapHoldContext {
  tenant: any;
  worker: any;
  blockingAssignments: { order: any; assignment: any }[];
  holdListing: any;
  holdOrder: any;
  awaitingAssignment: any;
}

export interface PoolExhaustionContext {
  tenant: any;
  pool: any;
  listingsInPool: any[];
  otherListing: any;
}

export async function setTenantPayoutAvailable(tenantId: string, desiredAvailableCents: number) {
  const snapshot = await getTenant(tenantId);
  const recovered = snapshot.recovered_clawbacks_cents ?? 0;
  const newLimit =
    desiredAvailableCents + snapshot.payout_consumed_cents + snapshot.payout_reserved_cents - recovered;
  await updateTenant(tenantId, { payout_credit_limit_cents: newLimit });
  const refreshed = await getTenant(tenantId);
  expect(refreshed.payout_available_cents).toBe(desiredAvailableCents);
  return refreshed;
}

export async function advancePastSlaBreach(tenantId: string, orderId: string) {
  const tenantState = await getTenant(tenantId);
  const orderState = await getOrder(tenantId, orderId);
  const delta =
    orderState.expected_completion_period_index -
    tenantState.current_period_index +
    CONSTANTS.sla.LATE_COMPLETION_MIN_PERIODS +
    2;
  await advanceClock(tenantId, Math.max(1, delta));
}

export async function consumeWorkerWeeklyCap(tenantId: string, workerId: string, amount: number) {
  const listing = await createPublishedListing(tenantId, { base_price_cents: Math.max(amount, 2000) });
  const order = await createOrder(tenantId, listing.id);
  const reservation = Math.max(amount, calculateMinimumReservation(order.worker_earnings_cap_cents));
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
  await processPayoutToCleared(tenantId, workerId, assignment.id, amount);
}

export async function induceWorkerRiskHold(tenantId: string, listingId: string, workerId: string) {
  const required = CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY;
  const maxIterations = required + 3;
  for (let i = 0; i < maxIterations; i += 1) {
    const order = await createOrder(tenantId, listingId);
    const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await createAssignment(tenantId, order.id, workerId, minimumReservation);
    await acceptAssignment(tenantId, order.id, assignment.id, workerId);
    await startAssignment(tenantId, order.id, assignment.id, workerId);

    const tenantState = await getTenant(tenantId);
    const orderState = await getOrder(tenantId, order.id);
    const advanceBy = Math.max(
      1,
      orderState.expected_completion_period_index -
        tenantState.current_period_index +
        CONSTANTS.sla.LATE_COMPLETION_MIN_PERIODS +
        1
    );
    await advanceClock(tenantId, advanceBy);
    await completeAssignment(tenantId, order.id, assignment.id, workerId);

    const rating = await createRating(tenantId, order.id, {
      worker_id: workerId,
      rating_value: 1,
      comment: 'Induce risk hold'
    });
    await moderateRating(tenantId, order.id, rating.id, 'PUBLISH');

    const workerAfter = await getWorker(tenantId, workerId);
    if (workerAfter.status === 'RISK_HOLD') {
      return;
    }
  }

  throw new Error('Unable to induce worker risk hold');
}

export async function cancelPayoutRecords(tenantId: string, records: PendingPayoutRecord[]) {
  for (const record of records) {
    await cancelPayout(tenantId, record.worker.id, record.payout.id);
  }
}

export async function expectListingStatuses(
  tenantId: string,
  listingIds: string[],
  expectedStatus: 'PUBLISHED' | 'PAUSED'
) {
  const listings = await getListings(tenantId);
  const statusMap = new Map(listings.map(listing => [listing.id, listing.status]));
  listingIds.forEach(id => {
    expect(statusMap.get(id)).toBe(expectedStatus);
  });
}

export async function createAssignmentWithReservation(
  tenantId: string,
  order: any,
  workerId: string,
  reservationAmount: number,
  sharePercentage?: number
) {
  const expectedEarnings =
    sharePercentage !== undefined
      ? Math.floor((order.worker_earnings_cap_cents * sharePercentage) / 100)
      : order.worker_earnings_cap_cents;
  const minimumReservation = calculateMinimumReservation(expectedEarnings);
  expect(minimumReservation).toBeLessThanOrEqual(reservationAmount);
  return createAssignment(tenantId, order.id, workerId, reservationAmount, sharePercentage);
}

export async function fetchAssignment(tenantId: string, orderId: string, assignmentId: string) {
  const assignments = await getAssignments(tenantId, orderId);
  const assignment = assignments.find(a => a.id === assignmentId);
  expect(assignment).toBeDefined();
  return assignment!;
}

export async function createPendingPayoutRecord(
  tenantId: string,
  listingId: string,
  payoutAmount: number
): Promise<PendingPayoutRecord> {
  const worker = await createWorker(tenantId);
  const order = await createOrder(tenantId, listingId);
  const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  const reservationAmount = Math.max(payoutAmount, minimumReservation);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, worker.id, reservationAmount);
  const payout = await createPayout(tenantId, worker.id, assignment.id, payoutAmount);
  return { worker, order, assignment, payout };
}

export async function createPendingPayouts(
  tenantId: string,
  listingId: string,
  amounts: number[]
): Promise<PendingPayoutRecord[]> {
  const records: PendingPayoutRecord[] = [];
  for (const amount of amounts) {
    records.push(await createPendingPayoutRecord(tenantId, listingId, amount));
  }
  return records;
}

export async function createClearedPayout(tenantId: string, amount: number, basePriceCents = 10000) {
  const listing = await createPublishedListing(tenantId, { base_price_cents: basePriceCents });
  const worker = await createWorker(tenantId);
  const order = await createOrder(tenantId, listing.id);
  const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  const reservation = Math.max(amount, minimumReservation);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, worker.id, reservation);
  await processPayoutToCleared(tenantId, worker.id, assignment.id, amount);
}

export async function setupUnderfundedAssignment(options: UnderfundedSetupOptions = {}) {
  const tenant = await createTenant(options.tenantConfig || {});
  const listing = await createPublishedListing(tenant.id, {
    base_price_cents: options.listingBasePriceCents ?? 10000
  });
  const worker = await createWorker(tenant.id, options.workerConfig || {});
  const order = await createOrder(tenant.id, listing.id);
  const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  let reservedAmount: number;
  if (typeof options.reservedCents === 'function') {
    reservedAmount = options.reservedCents(minimumReservation);
  } else if (typeof options.reservedCents === 'number') {
    reservedAmount = options.reservedCents;
  } else {
    reservedAmount = Math.floor(minimumReservation / 2);
  }
  const assignment = await createAssignment(tenant.id, order.id, worker.id, reservedAmount);
  return { tenant, listing, worker, order, assignment, minimumReservation };
}

export async function createPendingPayoutForUTU(
  tenantId: string,
  listingId: string,
  workerId: string,
  requestedAmountCents: number
) {
  const order = await createOrder(tenantId, listingId);
  const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
  return createPayout(tenantId, workerId, assignment.id, requestedAmountCents, 'NORMAL');
}

export async function setupTenantPoolAndListing(options: PoolTenantSetupOptions = {}) {
  const tenant = await createTenant({
    use_capacity_pools: true,
    use_pool_budgets: true,
    ...options.tenantConfig
  });
  const pool = await createCapacityPool(tenant.id, {
    max_active_assignments: options.poolConfig?.max_active_assignments ?? 10,
    payout_credit_limit_cents: options.poolConfig?.payout_credit_limit_cents,
    name: options.poolConfig?.name
  });
  const listing = await createPublishedListing(tenant.id, {
    capacity_pool_id: pool.id,
    ...options.listingConfig
  });
  return { tenant, pool, listing };
}

export async function createPendingPayoutForPPB(
  tenantId: string,
  listingId: string,
  workerId: string,
  reservationAmount: number,
  payoutAmount: number
) {
  const order = await createOrder(tenantId, listingId);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservationAmount);
  return createPayout(tenantId, workerId, assignment.id, payoutAmount);
}

export async function setupTenantPoolListing(options: PoolTenantSetupOptions = {}) {
  const tenant = await createTenant({
    use_capacity_pools: true,
    use_pool_budgets: true,
    auto_pause_underfunded_listings: true,
    auto_top_up_underfunded_assignments: true,
    auto_pause_pool_budget_exhausted: true,
    ...options.tenantConfig
  });
  const pool = await createCapacityPool(tenant.id, {
    name: options.poolConfig?.name,
    max_active_assignments: options.poolConfig?.max_active_assignments ?? 10,
    payout_credit_limit_cents: options.poolConfig?.payout_credit_limit_cents ?? 20000
  });
  const listing = await createPublishedListing(tenant.id, {
    capacity_pool_id: pool.id,
    base_price_cents: options.listingConfig?.base_price_cents ?? 10000,
    ...options.listingConfig
  });
  return { tenant, pool, listing };
}

export async function createUnderfundedAssignment(
  tenantId: string,
  listingId: string,
  workerId: string,
  options: UnderfundedAssignmentOptions = {}
): Promise<{ order: any; assignment: any; minimumReservation: number; reservedAmount: number }> {
  const order = await createOrder(tenantId, listingId);
  const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  let reserved: number;
  if (typeof options.reservedCents === 'function') {
    reserved = options.reservedCents(minimumReservation);
  } else if (typeof options.reservedCents === 'number') {
    reserved = options.reservedCents;
  } else {
    reserved = Math.floor(minimumReservation * 0.4);
  }
  reserved = options.allowZeroReservation ? Math.max(0, Math.floor(reserved)) : Math.max(1, Math.floor(reserved));
  const assignment = await createAssignment(tenantId, order.id, workerId, reserved);
  return { order, assignment, minimumReservation, reservedAmount: reserved };
}

export async function seedPoolConsumption(tenantId: string, poolId: string, amount: number) {
  if (!amount || amount <= 0) {
    return;
  }
  const safeBasePrice = Math.max(1000, Math.floor(amount / CONSTANTS.budget.MINIMUM_FACTOR) - 25);
  const tempListing = await createPublishedListing(tenantId, {
    capacity_pool_id: poolId,
    base_price_cents: safeBasePrice
  });
  const worker = await createWorker(tenantId);
  const order = await createOrder(tenantId, tempListing.id);
  const expectedEarnings = order.worker_earnings_cap_cents;
  const minReservation = calculateMinimumReservation(expectedEarnings);
  const reservation = Math.max(minReservation, amount);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, worker.id, reservation);
  const payoutAmount = Math.min(amount, expectedEarnings);
  await processPayoutToCleared(tenantId, worker.id, assignment.id, payoutAmount);
}

export async function createPendingPayoutForListing(
  tenantId: string,
  listingId: string,
  workerId: string,
  reservationAmount: number,
  payoutAmount: number
) {
  const order = await createOrder(tenantId, listingId);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservationAmount);
  return createPayout(tenantId, workerId, assignment.id, payoutAmount);
}

export async function setupTenantListingWorker(options: BasicSetupOptions = {}) {
  const tenant = await createTenant({
    auto_pause_underfunded_listings: true,
    ...options.tenantConfig
  });
  const listing = await createPublishedListing(tenant.id, {
    ...options.listingConfig
  });
  const worker = await createWorker(tenant.id, {
    weekly_payout_cap_cents: options.workerConfig?.weekly_payout_cap_cents ?? 20000,
    ...options.workerConfig
  });
  return { tenant, listing, worker };
}

export async function setupTenantPoolListingForWWC(options: PoolSetupOptions = {}) {
  const tenant = await createTenant({
    use_capacity_pools: true,
    use_pool_budgets: true,
    ...options.tenantConfig
  });
  const pool = await createCapacityPool(tenant.id, {
    max_active_assignments: options.poolConfig?.max_active_assignments ?? 10,
    payout_credit_limit_cents: options.poolConfig?.payout_credit_limit_cents,
    name: options.poolConfig?.name
  });
  const listing = await createPublishedListing(tenant.id, {
    capacity_pool_id: pool.id,
    ...options.listingConfig
  });
  return { tenant, pool, listing };
}

export async function setupTenantWithLiquidityPressure() {
  const tenant = await createTenant({
    payout_credit_limit_cents: 60000,
    payout_liquidity_buffer_ratio: 0,
    auto_pause_underfunded_listings: true
  });
  await createClearedPayout(tenant.id, 10000);
  await createClearedPayout(tenant.id, 10000);
  const payoutListing = await createPublishedListing(tenant.id, { base_price_cents: 8000 });
  await createPendingPayouts(tenant.id, payoutListing.id, [8000]);
  await updateTenant(tenant.id, { payout_liquidity_buffer_ratio: 0.5 });
  const assignmentListing = await createPublishedListing(tenant.id, { base_price_cents: 6000 });
  const worker = await createWorker(tenant.id);
  const order = await createOrder(tenant.id, assignmentListing.id);
  const assignment = await createAssignment(tenant.id, order.id, worker.id, 2000);
  return { tenant, payoutListing, assignmentListing, worker, order, assignment };
}

export async function createAwaitingAssignmentDueToTenantBudget(
  options: HoldAssignmentOptions = {}
): Promise<HoldAssignmentContext> {
  const { reservationAmount = 5000, tenantOverrides = {}, listingOverrides = {} } = options;
  const tenant = await createTenant({
    payout_credit_limit_cents: tenantOverrides.payout_credit_limit_cents ?? 3000,
    auto_pause_underfunded_listings: tenantOverrides.auto_pause_underfunded_listings ?? true,
    enable_assignment_budget_hold: tenantOverrides.enable_assignment_budget_hold ?? true,
    ...tenantOverrides
  });
  const listingPayload: Partial<ListingInput> = {
    base_price_cents: reservationAmount,
    budget_hold_mode: 'enabled',
    ...listingOverrides
  };
  const listing = await createPublishedListing(tenant.id, listingPayload);
  const worker = await createWorker(tenant.id);
  const order = await createOrder(tenant.id, listing.id);
  const assignment = await createAssignment(tenant.id, order.id, worker.id, reservationAmount);
  expect(assignment.status).toBe('AWAITING_FUNDS');
  return { tenant, listing, worker, order, assignment };
}

export async function createWorkerCapSetup(): Promise<WorkerCapSetup> {
  const tenant = await createTenant({
    payout_credit_limit_cents: 60000,
    auto_pause_underfunded_listings: true,
    enable_assignment_budget_hold: true
  });
  const worker = await createWorker(tenant.id, { weekly_payout_cap_cents: 10000 });
  const listing = await createPublishedListing(tenant.id, { base_price_cents: 6000 });

  const orderA = await createOrder(tenant.id, listing.id);
  const assignmentA = await createAssignment(tenant.id, orderA.id, worker.id, 6000);

  const orderB = await createOrder(tenant.id, listing.id);
  const assignmentB = await createAssignment(tenant.id, orderB.id, worker.id, 3000);

  return {
    tenant,
    worker,
    blockingAssignments: [
      { order: orderA, assignment: assignmentA },
      { order: orderB, assignment: assignmentB }
    ]
  };
}

export async function setupLiquidityHoldBase(): Promise<LiquidityHoldContext> {
  const tenant = await createTenant({
    payout_credit_limit_cents: 22000,
    auto_pause_underfunded_listings: true,
    enable_assignment_budget_hold: true,
    use_capacity_pools: true,
    use_pool_budgets: true,
    default_worker_weekly_payout_cap_cents: 10000,
    payout_liquidity_buffer_ratio: 0.5
  });
  const pool = await createCapacityPool(tenant.id, {
    max_active_assignments: 20,
    payout_credit_limit_cents: 22000
  });
  const listing = await createPublishedListing(tenant.id, {
    capacity_pool_id: pool.id,
    base_price_cents: 6000,
    budget_hold_mode: 'enabled'
  });
  const worker = await createWorker(tenant.id);

  const seedWorker = await createWorker(tenant.id);
  const seedOrder = await createOrder(tenant.id, listing.id);
  await createAssignment(tenant.id, seedOrder.id, seedWorker.id, 6600);

  const payoutListing = await createPublishedListing(tenant.id, { base_price_cents: 6000 });
  const pendingPayouts = await createPendingPayouts(tenant.id, payoutListing.id, [6000]);

  return { tenant, pool, listing, worker, pendingPayouts };
}

export async function attemptCreationIntoHold(context: LiquidityHoldContext, reservedAmount: number) {
  const order = await createOrder(context.tenant.id, context.listing.id);
  const response = await postAs(
    `/tenants/${context.tenant.id}/orders/${order.id}/assignments`,
    {
      worker_id: context.worker.id,
      reserved_earnings_initial_cents: reservedAmount
    },
    'Dispatcher'
  );
  expect(response.status).toBe(201);
  const awaiting = response.body.data;
  expect(awaiting.status).toBe('AWAITING_FUNDS');
  return { order, assignment: awaiting };
}

export async function seedPoolReservation(tenantId: string, listingId: string, totalAmount: number) {
  let remaining = totalAmount;
  while (remaining > 0) {
    const chunk = Math.max(1, Math.min(remaining, 6000));
    const worker = await createWorker(tenantId, { weekly_payout_cap_cents: chunk + 5000 });
    const order = await createOrder(tenantId, listingId);
    await createAssignment(tenantId, order.id, worker.id, chunk);
    remaining -= chunk;
  }
}

export async function setupTopUpPromotionScenario(): Promise<TopUpPromotionContext> {
  const tenant = await createTenant({
    payout_credit_limit_cents: 50000,
    auto_pause_underfunded_listings: true,
    auto_top_up_underfunded_assignments: true,
    use_capacity_pools: true,
    use_pool_budgets: true,
    enable_assignment_budget_hold: true,
    payout_liquidity_buffer_ratio: 0.5
  });
  const pool = await createCapacityPool(tenant.id, {
    max_active_assignments: 20,
    payout_credit_limit_cents: 20000
  });
  const listing = await createPublishedListing(tenant.id, {
    capacity_pool_id: pool.id,
    base_price_cents: 10000,
    budget_hold_mode: 'enabled'
  });

  const workerTopUp = await createWorker(tenant.id, { weekly_payout_cap_cents: 20000 });
  const orderTopUp = await createOrder(tenant.id, listing.id);
  const minimumReservation = calculateMinimumReservation(orderTopUp.worker_earnings_cap_cents);
  const reservedAmount = minimumReservation - 5000;
  const assignmentTopUp = await createAssignment(tenant.id, orderTopUp.id, workerTopUp.id, reservedAmount);
  expect(assignmentTopUp.requires_adjustment).toBe(true);
  const topUpAmount = minimumReservation - assignmentTopUp.reserved_earnings_current_cents;
  expect(topUpAmount).toBeGreaterThan(0);

  const targetReserved = tenant.payout_credit_limit_cents - 11000;
  let tenantState = await getTenant(tenant.id);
  const additionalNeeded = Math.max(0, targetReserved - tenantState.payout_reserved_cents);
  if (additionalNeeded > 0) {
    await seedPoolReservation(tenant.id, listing.id, additionalNeeded);
  }

  tenantState = await getTenant(tenant.id);
  expect(tenantState.payout_available_cents).toBe(11000);

  const payoutListing = await createPublishedListing(tenant.id, { base_price_cents: 8000 });
  const pendingRecords = await createPendingPayouts(tenant.id, payoutListing.id, [14000, 6000]);
  tenantState = await getTenant(tenant.id);
  expect(tenantState.total_pending_payouts_cents).toBe(20000);
  expect(tenantState.payout_liquidity_required_cents).toBe(10000);
  expect(tenantState.payout_liquidity_headroom_cents).toBe(1000);

  const workerAwaiting = await createWorker(tenant.id, { weekly_payout_cap_cents: 20000 });
  const orderAwaiting = await createOrder(tenant.id, listing.id);
  const awaitingResponse = await postAs(
    `/tenants/${tenant.id}/orders/${orderAwaiting.id}/assignments`,
    {
      worker_id: workerAwaiting.id,
      reserved_earnings_initial_cents: 9000
    },
    'Dispatcher'
  );
  expect(awaitingResponse.status).toBe(201);
  const awaitingAssignment = awaitingResponse.body.data;
  expect(awaitingAssignment.status).toBe('AWAITING_FUNDS');
  expect(awaitingAssignment.budget_hold_reason).toBe('PAYOUT_LIQUIDITY');

  const grace = CONSTANTS.budget.UNDERFUNDING_GRACE_PERIODS;
  for (let i = 0; i < grace; i += 1) {
    await advanceClock(tenant.id, 1);
  }

  return {
    tenant,
    pool,
    listing,
    workerTopUp,
    workerAwaiting,
    orderTopUp,
    assignmentTopUp,
    minimumReservation,
    topUpAmount,
    orderAwaiting,
    awaitingAssignment,
    pendingRecords
  };
}

export async function setupWorkerCapHoldScenario(): Promise<WorkerCapHoldContext> {
  const tenant = await createTenant({
    payout_credit_limit_cents: 60000,
    auto_pause_underfunded_listings: true,
    enable_assignment_budget_hold: true,
    auto_suspend_capped_workers: true
  });
  const worker = await createWorker(tenant.id, { weekly_payout_cap_cents: 10000 });
  const blockingListing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });

  const orderA = await createOrder(tenant.id, blockingListing.id);
  const assignmentA = await createAssignment(tenant.id, orderA.id, worker.id, 6000);
  const orderB = await createOrder(tenant.id, blockingListing.id);
  const assignmentB = await createAssignment(tenant.id, orderB.id, worker.id, 4000);

  const holdListing = await createPublishedListing(tenant.id, { base_price_cents: 4000, budget_hold_mode: 'enabled' });
  const holdOrder = await createOrder(tenant.id, holdListing.id);
  const response = await postAs(
    `/tenants/${tenant.id}/orders/${holdOrder.id}/assignments`,
    {
      worker_id: worker.id,
      reserved_earnings_initial_cents: 4000
    },
    'Dispatcher'
  );
  expect(response.status).toBe(201);
  const awaitingAssignment = response.body.data;
  expect(awaitingAssignment.status).toBe('AWAITING_FUNDS');
  expect(awaitingAssignment.budget_hold_reason).toBe('WORKER_CAP');

  return {
    tenant,
    worker,
    blockingAssignments: [
      { order: orderA, assignment: assignmentA },
      { order: orderB, assignment: assignmentB }
    ],
    holdListing,
    holdOrder,
    awaitingAssignment
  };
}

export async function setupPoolExhaustionScenario(): Promise<PoolExhaustionContext> {
  const tenant = await createTenant({
    payout_credit_limit_cents: 30000,
    use_capacity_pools: true,
    use_pool_budgets: true,
    auto_pause_pool_budget_exhausted: true,
    payout_liquidity_buffer_ratio: 0.5,
    auto_pause_underfunded_listings: true
  });
  const pool = await createCapacityPool(tenant.id, {
    max_active_assignments: 10,
    payout_credit_limit_cents: 10000
  });
  const listingA = await createPublishedListing(tenant.id, { capacity_pool_id: pool.id, base_price_cents: 6000 });
  const listingB = await createPublishedListing(tenant.id, { capacity_pool_id: pool.id, base_price_cents: 4000 });
  const otherListing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });

  const workerA = await createWorker(tenant.id, { weekly_payout_cap_cents: 15000 });
  const reserveOrder = await createOrder(tenant.id, listingA.id);
  await createAssignment(tenant.id, reserveOrder.id, workerA.id, 6600);

  const workerB = await createWorker(tenant.id, { weekly_payout_cap_cents: 15000 });
  const consumeOrder = await createOrder(tenant.id, listingB.id);
  const consumeAssignment = await bringAssignmentToCompleted(tenant.id, consumeOrder.id, workerB.id, 4400);
  await processPayoutToCleared(tenant.id, workerB.id, consumeAssignment.id, 4000);

  const payoutListing = await createPublishedListing(tenant.id, { base_price_cents: 6000 });
  await createPendingPayouts(tenant.id, payoutListing.id, [6000, 6000]);

  return {
    tenant,
    pool,
    listingsInPool: [listingA, listingB],
    otherListing
  };
}
