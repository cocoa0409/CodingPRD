import { v4 as uuidv4 } from 'uuid';
import { getAs, postAs, putAs } from './api-client';
import { Role, CONSTANTS } from './constants';
import { calculateMinimumReservation } from './calculations';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export { getAs, postAs, putAs };

export interface TenantInput {
  name?: string;
  payout_credit_limit_cents: number;
  auto_sla_enforcement?: boolean;
  auto_dispute_expiry?: boolean;
  auto_payout_recovery?: boolean;
  freeze_payouts_during_disputes?: boolean;
  use_dynamic_listing_priority?: boolean;
  auto_release_surplus_on_close?: boolean;
  auto_pause_underfunded_listings?: boolean;
  allow_initial_underfunding_without_autopause?: boolean;
  auto_top_up_underfunded_assignments?: boolean;

  enforce_listing_capacity?: boolean;
  auto_pause_over_capacity_listings?: boolean;
  refunds_reduce_payout_entitlements?: boolean;
  tiered_refund_allocation?: boolean;
  auto_adjust_worker_capacity?: boolean;
  use_capacity_pools?: boolean;
  auto_pause_pool_overcapacity?: boolean;
  allow_capacity_borrowing_across_listings?: boolean;
  low_rating_risk_escalation?: boolean;

  use_pool_budgets?: boolean;
  auto_pause_pool_budget_exhausted?: boolean;
  auto_suspend_capped_workers?: boolean;
  enable_assignment_budget_hold?: boolean;
  auto_pause_when_payout_liquidity_negative?: boolean;
  payout_liquidity_buffer_ratio?: number;
  default_worker_weekly_payout_cap_cents?: number | null;
}

export async function createTenant(input: Partial<TenantInput> = {}): Promise<any> {
  const data: TenantInput = {
    name: input.name || `Test Tenant ${uniqueId()}`,
    payout_credit_limit_cents: input.payout_credit_limit_cents ?? 100000,
    auto_sla_enforcement: input.auto_sla_enforcement,
    auto_dispute_expiry: input.auto_dispute_expiry,
    auto_payout_recovery: input.auto_payout_recovery,
    freeze_payouts_during_disputes: input.freeze_payouts_during_disputes,
    use_dynamic_listing_priority: input.use_dynamic_listing_priority,
    auto_release_surplus_on_close: input.auto_release_surplus_on_close,
    auto_pause_underfunded_listings: input.auto_pause_underfunded_listings,
    allow_initial_underfunding_without_autopause: input.allow_initial_underfunding_without_autopause,
    auto_top_up_underfunded_assignments: input.auto_top_up_underfunded_assignments,

    enforce_listing_capacity: input.enforce_listing_capacity,
    auto_pause_over_capacity_listings: input.auto_pause_over_capacity_listings,
    refunds_reduce_payout_entitlements: input.refunds_reduce_payout_entitlements,
    tiered_refund_allocation: input.tiered_refund_allocation,
    auto_adjust_worker_capacity: input.auto_adjust_worker_capacity,
    use_capacity_pools: input.use_capacity_pools,
    auto_pause_pool_overcapacity: input.auto_pause_pool_overcapacity,
    allow_capacity_borrowing_across_listings: input.allow_capacity_borrowing_across_listings,
    low_rating_risk_escalation: input.low_rating_risk_escalation,
    use_pool_budgets: input.use_pool_budgets,
    auto_pause_pool_budget_exhausted: input.auto_pause_pool_budget_exhausted,
    auto_suspend_capped_workers: input.auto_suspend_capped_workers,
    enable_assignment_budget_hold: input.enable_assignment_budget_hold,
    auto_pause_when_payout_liquidity_negative: input.auto_pause_when_payout_liquidity_negative,
    payout_liquidity_buffer_ratio: input.payout_liquidity_buffer_ratio,
    default_worker_weekly_payout_cap_cents: input.default_worker_weekly_payout_cap_cents
  };
  const response = await postAs('/tenants', data, 'PlatformAdmin');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getTenant(tenantId: string): Promise<any> {
  const response = await getAs(`/tenants/${tenantId}`, 'PlatformAdmin');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function updateTenant(tenantId: string, updates: Partial<TenantInput>): Promise<any> {
  const response = await putAs(`/tenants/${tenantId}`, updates, 'PlatformAdmin');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function advanceClock(tenantId: string, byPeriods: number = 1): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/clock/advance`, { by_periods: byPeriods }, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface ListingInput {
  title?: string;
  category?: 'DELIVERY' | 'HOME_SERVICE' | 'RIDESHARE' | 'TASK';
  base_price_cents?: number;
  surge_multiplier?: number;
  customer_sla_periods?: number;
  max_parallel_assignments?: number;

  platform_fee_percent?: number;
  priority_tier?: number;
  capacity_pool_id?: string;
  budget_hold_mode?: 'inherit' | 'enabled' | 'disabled' | 'INHERIT' | 'ENABLED' | 'DISABLED';
}

export async function createListing(tenantId: string, input: Partial<ListingInput> = {}): Promise<any> {
  const data: any = {
    title: input.title || `Test Listing ${uniqueId()}`,
    category: input.category || 'DELIVERY',
    base_price_cents: input.base_price_cents ?? 10000,
    surge_multiplier: input.surge_multiplier ?? 1.0,
    customer_sla_periods: input.customer_sla_periods ?? 5,
    max_parallel_assignments: input.max_parallel_assignments ?? 10
  };

  if (input.platform_fee_percent !== undefined) {
    data.platform_fee_percent = input.platform_fee_percent;
  }
  if (input.priority_tier !== undefined) {
    data.priority_tier = input.priority_tier;
  }
  if (input.capacity_pool_id !== undefined) {
    data.capacity_pool_id = input.capacity_pool_id;
  }
  if (input.budget_hold_mode !== undefined) {
    data.budget_hold_mode = input.budget_hold_mode;
  }
  const response = await postAs(`/tenants/${tenantId}/listings`, data, 'TenantManager');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getListing(tenantId: string, listingId: string): Promise<any> {
  const response = await getAs(`/tenants/${tenantId}/listings/${listingId}`, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function publishListing(tenantId: string, listingId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/listings/${listingId}/publish`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function createPublishedListing(tenantId: string, input: Partial<ListingInput> = {}): Promise<any> {
  const listing = await createListing(tenantId, input);
  return await publishListing(tenantId, listing.id);
}

export async function pauseListing(tenantId: string, listingId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/listings/${listingId}/pause`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function resumeListing(tenantId: string, listingId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/listings/${listingId}/resume`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function getListings(tenantId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/listings`, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface CapacityPoolInput {
  name?: string;
  max_active_assignments: number;
  payout_credit_limit_cents?: number | null;
}

export async function createCapacityPool(tenantId: string, input: CapacityPoolInput): Promise<any> {
  const data: { name: string; max_active_assignments: number; payout_credit_limit_cents?: number | null } = {
    name: input.name || `Test Pool ${uniqueId()}`,
    max_active_assignments: input.max_active_assignments
  };
  if (input.payout_credit_limit_cents !== undefined) {
    data.payout_credit_limit_cents = input.payout_credit_limit_cents;
  }
  const response = await postAs(`/tenants/${tenantId}/capacity-pools`, data, 'TenantManager');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getCapacityPool(tenantId: string, poolId: string): Promise<any> {
  const response = await getAs(`/tenants/${tenantId}/capacity-pools/${poolId}`, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function getCapacityPools(tenantId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/capacity-pools`, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function updateCapacityPool(tenantId: string, poolId: string, updates: Partial<CapacityPoolInput>): Promise<any> {
  const response = await putAs(`/tenants/${tenantId}/capacity-pools/${poolId}`, updates, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface BenefitsConfig {
  enabled: boolean;
  deduction_cents_per_payout: number;
}

export interface WorkerInput {
  name?: string;
  skills?: ('DELIVERY' | 'HOME_SERVICE' | 'RIDESHARE' | 'TASK')[];
  certifications?: { certification_type: string; certified_period_index: number; expiry_period_index: number }[];
  max_active_assignments?: number;
  signup_bonus_debt_cents?: number;
  benefits_config?: BenefitsConfig;
  weekly_payout_cap_cents?: number | null;
}

export async function createWorker(tenantId: string, input: Partial<WorkerInput> = {}): Promise<any> {
  const data: any = {
    name: input.name || `Test Worker ${uniqueId()}`,
    skills: input.skills || ['DELIVERY', 'TASK'],
    certifications: input.certifications || [],
    max_active_assignments: input.max_active_assignments,
    signup_bonus_debt_cents: input.signup_bonus_debt_cents
  };
  if (input.benefits_config !== undefined) {
    data.benefits_config = input.benefits_config;
  }
  if (input.weekly_payout_cap_cents !== undefined) {
    data.weekly_payout_cap_cents = input.weekly_payout_cap_cents;
  }
  const response = await postAs(`/tenants/${tenantId}/workers`, data, 'TenantManager');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getWorker(tenantId: string, workerId: string): Promise<any> {
  const response = await getAs(`/tenants/${tenantId}/workers/${workerId}`, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface OrderInput {
  listing_id: string;
  external_customer_id?: string;
}

export async function createOrder(tenantId: string, listingId: string, input: Partial<Omit<OrderInput, 'listing_id'>> = {}): Promise<any> {
  const data = {
    listing_id: listingId,
    external_customer_id: input.external_customer_id || `customer-${uniqueId()}`
  };
  const response = await postAs(`/tenants/${tenantId}/orders`, data, 'Dispatcher');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getOrder(tenantId: string, orderId: string): Promise<any> {
  const response = await getAs(`/tenants/${tenantId}/orders/${orderId}`, 'Dispatcher');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface AssignmentInput {
  worker_id: string;
  share_percentage?: number;
  reserved_earnings_initial_cents: number;
}

export async function createAssignment(
  tenantId: string,
  orderId: string,
  workerId: string,
  reservedEarningsInitialCents: number,
  sharePercentage?: number
): Promise<any> {
  const data: any = {
    worker_id: workerId,
    reserved_earnings_initial_cents: reservedEarningsInitialCents
  };
  if (sharePercentage !== undefined) {
    data.share_percentage = sharePercentage;
  }
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/assignments`, data, 'Dispatcher');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getAssignments(tenantId: string, orderId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/orders/${orderId}/assignments`, 'Dispatcher');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function acceptAssignment(tenantId: string, orderId: string, assignmentId: string, workerId: string): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/assignments/${assignmentId}/accept`,
    {},
    'WorkerApp',
    undefined,
    workerId
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function startAssignment(tenantId: string, orderId: string, assignmentId: string, workerId: string): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/assignments/${assignmentId}/start`,
    {},
    'WorkerApp',
    undefined,
    workerId
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function completeAssignment(tenantId: string, orderId: string, assignmentId: string, workerId: string): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/assignments/${assignmentId}/complete`,
    {},
    'WorkerApp',
    undefined,
    workerId
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function releaseAssignmentSurplus(tenantId: string, orderId: string, assignmentId: string, releaseAmountCents: number): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/assignments/${assignmentId}/release-surplus`,
    { release_amount_cents: releaseAmountCents },
    'TenantManager'
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function cancelAssignment(tenantId: string, orderId: string, assignmentId: string, workerId: string): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/assignments/${assignmentId}/cancel`,
    {},
    'WorkerApp',
    undefined,
    workerId
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface PayoutInput {
  assignment_id: string;
  requested_amount_cents: number;
  payout_type: 'NORMAL' | 'INSTANT' | 'ADJUSTMENT' | 'FINAL';
}

export async function createPayout(
  tenantId: string,
  workerId: string,
  assignmentId: string,
  requestedAmountCents: number,
  payoutType: PayoutInput['payout_type'] = 'NORMAL',
  idempotencyKey?: string
): Promise<any> {
  const data = {
    assignment_id: assignmentId,
    requested_amount_cents: requestedAmountCents,
    payout_type: payoutType
  };
  const headers = {
    'Idempotency-Key': idempotencyKey || `idem-${uniqueId()}`
  };
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/payouts`, data, 'FinanceOfficer', headers);
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getPayouts(tenantId: string, workerId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/workers/${workerId}/payouts`, 'FinanceOfficer');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function approvePayout(tenantId: string, workerId: string, payoutId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/payouts/${payoutId}/approve`, {}, 'FinanceOfficer');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function sendPayout(tenantId: string, workerId: string, payoutId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/payouts/${payoutId}/send`, {}, 'FinanceOfficer');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function confirmPayoutCleared(tenantId: string, workerId: string, payoutId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/payouts/${payoutId}/confirm-cleared`, {}, 'FinanceOfficer');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function cancelPayout(tenantId: string, workerId: string, payoutId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/payouts/${payoutId}/cancel`, {}, 'FinanceOfficer');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface DisputeInput {
  assignment_id?: string;
  raised_by: 'CUSTOMER' | 'WORKER';
  reason: string;
}

export async function createDispute(tenantId: string, orderId: string, input: DisputeInput): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/disputes`, input, 'CustomerSupport');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getDisputes(tenantId: string, orderId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/orders/${orderId}/disputes`, 'CustomerSupport');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function startDisputeReview(tenantId: string, orderId: string, disputeId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/disputes/${disputeId}/start-review`, {}, 'CustomerSupport');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function resolveDisputeForCustomer(
  tenantId: string,
  orderId: string,
  disputeId: string,
  refundAmountCents: number,
  workerPenaltyCents: number
): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/disputes/${disputeId}/resolve-customer`,
    { refund_amount_cents: refundAmountCents, worker_penalty_cents: workerPenaltyCents },
    'CustomerSupport'
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function resolveDisputeForWorker(tenantId: string, orderId: string, disputeId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/disputes/${disputeId}/resolve-worker`, {}, 'CustomerSupport');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function withdrawDispute(tenantId: string, orderId: string, disputeId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/disputes/${disputeId}/withdraw`, {}, 'CustomerSupport');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function closeOrder(tenantId: string, orderId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/close`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export interface RatingInput {
  worker_id: string;
  rating_value: number;
  comment?: string;
}

export async function createRating(tenantId: string, orderId: string, input: RatingInput): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/orders/${orderId}/ratings`, input, 'Dispatcher');
  expect(response.status).toBe(201);
  return response.body.data;
}

export async function getRatings(tenantId: string, orderId: string): Promise<any[]> {
  const response = await getAs(`/tenants/${tenantId}/orders/${orderId}/ratings`, 'Dispatcher');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function moderateRating(
  tenantId: string,
  orderId: string,
  ratingId: string,
  action: 'HIDE' | 'PUBLISH' | 'REMOVE'
): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/ratings/${ratingId}/moderate`,
    { action },
    'TenantManager'
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function suspendWorker(tenantId: string, workerId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/suspend`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function reinstateWorker(tenantId: string, workerId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/reinstate`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function updateWorker(tenantId: string, workerId: string, updates: Partial<WorkerInput>): Promise<any> {
  const response = await putAs(`/tenants/${tenantId}/workers/${workerId}`, updates, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function suspendTenant(tenantId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/suspend`, {}, 'PlatformAdmin');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function reinstateTenant(tenantId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/reinstate`, {}, 'PlatformAdmin');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function cancelOrder(
  tenantId: string,
  orderId: string,
  cancelledBy: 'CUSTOMER' | 'SYSTEM',
  reason?: string
): Promise<any> {
  const response = await postAs(
    `/tenants/${tenantId}/orders/${orderId}/cancel`,
    { cancelled_by: cancelledBy, reason: reason || 'Test cancellation' },
    'Dispatcher'
  );
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function clearWorkerRiskHold(tenantId: string, workerId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/risk-hold/clear`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function deactivateWorker(tenantId: string, workerId: string): Promise<any> {
  const response = await postAs(`/tenants/${tenantId}/workers/${workerId}/deactivate`, {}, 'TenantManager');
  expect(response.status).toBe(200);
  return response.body.data;
}

export async function createBasicScenario(options: {
  payoutCreditLimitCents?: number;
  basePriceCents?: number;
  workerDebt?: number;
} = {}): Promise<{
  tenant: any;
  listing: any;
  worker: any;
  order: any;
}> {
  const tenant = await createTenant({ payout_credit_limit_cents: options.payoutCreditLimitCents ?? 100000 });
  const listing = await createPublishedListing(tenant.id, { base_price_cents: options.basePriceCents ?? 10000 });
  const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: options.workerDebt });
  const order = await createOrder(tenant.id, listing.id);
  return { tenant, listing, worker, order };
}

export async function bringAssignmentToCompleted(
  tenantId: string,
  orderId: string,
  workerId: string,
  reservedEarningsInitialCents: number,
  sharePercentage?: number
): Promise<any> {
  const assignment = await createAssignment(tenantId, orderId, workerId, reservedEarningsInitialCents, sharePercentage);
  await acceptAssignment(tenantId, orderId, assignment.id, workerId);
  await startAssignment(tenantId, orderId, assignment.id, workerId);
  const completion = await completeAssignment(tenantId, orderId, assignment.id, workerId);

  return completion?.assignment ?? completion;
}

export async function processPayoutToCleared(
  tenantId: string,
  workerId: string,
  assignmentId: string,
  requestedAmountCents: number,
  payoutType: PayoutInput['payout_type'] = 'NORMAL'
): Promise<any> {
  const payout = await createPayout(tenantId, workerId, assignmentId, requestedAmountCents, payoutType);
  await approvePayout(tenantId, workerId, payout.id);
  await sendPayout(tenantId, workerId, payout.id);
  return await confirmPayoutCleared(tenantId, workerId, payout.id);
}

export async function completeOrderWithAssignment(
  tenantId: string,
  listingId: string,
  workerId: string
): Promise<{ order: any; assignment: any }> {
  const order = await createOrder(tenantId, listingId);
  const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
  const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
  return { order, assignment };
}

export async function cancelOrderWithAssignment(
  tenantId: string,
  listingId: string,
  workerId: string,
  reason: string = 'Test cancel'
): Promise<{ order: any; assignment?: any }> {

  const order = await createOrder(tenantId, listingId);
  await cancelOrder(tenantId, order.id, 'CUSTOMER', reason);
  return { order };
}
