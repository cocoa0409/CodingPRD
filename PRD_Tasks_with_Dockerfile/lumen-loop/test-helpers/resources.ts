import { v4 as uuidv4 } from 'uuid';
import { get, post } from './api-client';
import { expectError, expectSuccess } from './assertions';
import { ActorType } from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export type Program = {
  program_id: string;
  display_name: string;
  program_posture: 'PROGRAM_ACTIVE' | 'PROGRAM_GUARDED' | 'PROGRAM_FROZEN' | 'PROGRAM_CLOSED';
  ops_run_index: number;
  available_to_commit_units: number;
};

export type Session = {
  session_id: string;
  actor_id: string;
  actor_type: ActorType;
  session_status: 'ACTIVE' | 'ENDED' | 'REVOKED';
};

export type Customer = {
  customer_id: string;
  display_name: string;
  customer_status: 'ACTIVE' | 'LIMITED' | 'LOCKED' | 'CLOSED';
  credit_balance_cents: number;
  balance_due_cents: number;

  fenced_credit_cents: number;
  available_credit_cents: number;
};

export type BuildLot = {
  build_lot_id: string;
  build_tag: string;
  build_lot_status: 'AVAILABLE' | 'QUARANTINED' | 'CONSUMED';
};

export type Order = {
  order_id: string;
  customer_id: string;

  capacity_pool_id?: string | null;
  order_status: 'DRAFT' | 'SUBMITTED' | 'ON_HOLD' | 'SHIPPED' | 'DELIVERED' | 'CANCELED' | 'EXPIRED' | 'REFUNDED';
  model_code: string;
  unit_price_cents: number;
  care_plan_price_cents: number;
  paid_by_credit_cents: number;
  paid_by_card_cents: number;
  payment_id: string | null;
  device_id: string | null;
  care_plan_id: string | null;
  tradein_id: string | null;

  supply_commitment_status?: 'COMMITTED' | 'RELEASED';
};

export type CarePlan = {
  care_plan_id: string;
  order_id: string;
  customer_id: string;
  device_id: string | null;
  care_plan_status: 'PENDING_ACTIVATION' | 'ACTIVE' | 'PAUSED' | 'CANCELED' | 'VOIDED';
};

export type Payment = {
  payment_id: string;
  order_id: string;
  payment_status: 'AUTHORIZED' | 'CAPTURED' | 'VOIDED' | 'REFUNDED' | 'DISPUTED' | 'CHARGEBACK_LOST';
  amount_cents: number;
};

export type Device = {
  device_id: string;
  order_id: string;
  customer_id: string;
  serial_number: string;
  build_tag: string;
  device_status: 'PROVISIONED' | 'SHIPPED' | 'ACTIVE' | 'QUARANTINED' | 'RETURNED' | 'SCRAPPED';
};

export type Adjustment = {
  adjustment_id: string;
  customer_id: string;
  adjustment_type: 'GOODWILL_CREDIT' | 'WRITE_OFF' | 'CREDIT_CLAWBACK';
  adjustment_status: 'PENDING' | 'APPLIED' | 'VOIDED';
  amount_cents: number;
};

export type QualityCampaign = {
  quality_campaign_id: string;
  campaign_type: 'SHIP_HOLD' | 'RECALL';
  campaign_status: 'OPEN' | 'CONTAINED' | 'RESOLVED' | 'CLOSED';
  build_tag_prefix: string;
};

export type Alert = {
  alert_id: string;
  alert_type:
    | 'PAYMENT_DISPUTED'
    | 'CHARGEBACK_LOST'
    | 'TRADEIN_REVERSAL'
    | 'SUPPLY_SHORTFALL'
    | 'RECALL_ACTIVE'
    | 'AFTERCARE_OVERDUE'
    | 'CUSTOMER_LOCKED';
  alert_status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';
  opened_ops_run_index: number;
  customer_id: string | null;
  order_id: string | null;
  device_id: string | null;
  payment_id: string | null;
  tradein_id: string | null;
  quality_campaign_id: string | null;
  claim_id: string | null;
};

export type Claim = {
  claim_id: string;
  order_id: string;
  device_id: string;
  customer_id: string;
  claim_status: 'OPEN' | 'APPROVED' | 'INBOUND' | 'RECEIVED' | 'ADVANCE_SHIPPED' | 'COMPLETED' | 'CANCELED' | 'EXPIRED';
  claim_type: 'WARRANTY' | 'CARE_PLAN' | 'RECALL';
  claim_resolution: 'REPLACEMENT' | 'ADVANCE_REPLACEMENT' | null;
  inspection_outcome: 'REFURB' | 'SCRAP' | null;
  replacement_device_id: string | null;
};

export type TradeIn = {
  tradein_id: string;
  customer_id: string;
  tradein_status: 'DRAFT' | 'SUBMITTED' | 'INBOUND' | 'APPRAISED' | 'CREDITED' | 'REVERSED' | 'EXPIRED';
  quoted_credit_cents: number;
  final_credit_cents: number | null;
};

export type Return = {
  return_id: string;
  order_id: string;
  device_id: string;
  customer_id: string;
  return_status: 'REQUESTED' | 'APPROVED' | 'INBOUND' | 'RECEIVED' | 'COMPLETED' | 'REJECTED';
  resolution_preference: 'REFUND' | 'REPLACEMENT';
  inspection_outcome: null | 'RESTOCK' | 'REFURB' | 'SCRAP';
  refunded_to_card_cents: number;
  refunded_to_credit_cents: number;
  replacement_device_id: string | null;
};

export async function createProgram(overrides?: Partial<{ display_name: string; unit_price_cents: number; care_plan_price_cents: number }>): Promise<Program> {
  const body = {
    display_name: overrides?.display_name ?? `Program-${uniqueId('prog')}`,
    unit_price_cents: overrides?.unit_price_cents ?? 79900,
    care_plan_price_cents: overrides?.care_plan_price_cents ?? 9900
  };
  const res = await post('/programs', body, { actor_id: `system-${uniqueId('sys')}`, actor_type: 'System' });
  expectSuccess(res, 201);
  return res.body as Program;
}

export async function getProgram(program_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Program> {
  const res = await get(`/programs/${program_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Program;
}

export async function createSession(program_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Session> {
  const res = await post(`/programs/${program_id}/sessions`, { actor_id: actor.actor_id, actor_type: actor.actor_type }, actor);
  expectSuccess(res, 201);
  return res.body as Session;
}

export async function endSession(program_id: string, session_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }): Promise<Session> {
  const res = await post(`/programs/${program_id}/sessions/${session_id}/end`, {}, actor);
  expectSuccess(res, 200);
  return res.body as Session;
}

export async function runOps(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, idempotency_key?: string): Promise<Program> {
  const res = await post(`/programs/${program_id}/run_ops`, {}, { ...actor, idempotency_key });
  expectSuccess(res, 200);
  return res.body as Program;
}

export async function freezeProgram(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, reason = 'ops containment'): Promise<Program> {
  const res = await post(`/programs/${program_id}/freeze`, { reason }, actor);
  expectSuccess(res, 200);
  return res.body as Program;
}

export async function unfreezeProgram(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/unfreeze`, {}, actor);
}

export async function closeProgram(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/close`, {}, actor);
}

export async function createCustomer(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, overrides?: Partial<{ display_name: string }>): Promise<Customer> {
  const res = await post(`/programs/${program_id}/customers`, { display_name: overrides?.display_name ?? `Customer-${uniqueId('cust')}` }, actor);
  expectSuccess(res, 201);
  return res.body as Customer;
}

export async function getCustomer(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Customer> {
  const res = await get(`/programs/${program_id}/customers/${customer_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Customer;
}

export async function lockCustomer(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, reason = 'risk'): Promise<Customer> {
  const res = await post(`/programs/${program_id}/customers/${customer_id}/lock`, { reason }, actor);
  expectSuccess(res, 200);
  return res.body as Customer;
}

export async function unlockCustomer(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }): Promise<Customer> {
  const res = await post(`/programs/${program_id}/customers/${customer_id}/unlock`, {}, actor);
  expectSuccess(res, 200);
  return res.body as Customer;
}

export async function settleBalanceDue(
  program_id: string,
  customer_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  amount_cents: number
): Promise<Customer> {
  const res = await post(`/programs/${program_id}/customers/${customer_id}/settle_balance_due`, { amount_cents }, actor);
  expectSuccess(res, 200);
  return res.body as Customer;
}

export async function createBuildLot(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, build_tag: string, units: number): Promise<BuildLot> {
  const res = await post(`/programs/${program_id}/build_lots`, { build_tag, units }, actor);
  expectSuccess(res, 201);
  return res.body as BuildLot;
}

export async function getBuildLot(program_id: string, build_lot_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<BuildLot> {
  const res = await get(`/programs/${program_id}/build_lots/${build_lot_id}`, actor);
  expectSuccess(res, 200);
  return res.body as BuildLot;
}

export async function createOrder(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, overrides?: Partial<{ model_code: string; use_credit_cents: number; tradein_id: string | null }>): Promise<Order> {
  const body = {
    model_code: overrides?.model_code ?? 'LUMENPHONE_G1',
    use_credit_cents: overrides?.use_credit_cents ?? 0,
    tradein_id: overrides?.tradein_id ?? null
  };
  const res = await post(`/programs/${program_id}/customers/${customer_id}/orders`, body, actor);
  expectSuccess(res, 201);
  return res.body as Order;
}

export async function getOrder(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Order> {
  const res = await get(`/programs/${program_id}/orders/${order_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Order;
}

export async function listOrders(
  program_id: string,
  actor: { actor_id: string; actor_type: ActorType },
  query: { customer_id?: string; order_status?: Order['order_status'] }
): Promise<{ orders: Order[] }> {
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  const path = qs.length > 0 ? `/programs/${program_id}/orders?${qs}` : `/programs/${program_id}/orders`;
  const res = await get(path, actor);
  expectSuccess(res, 200);
  return res.body as { orders: Order[] };
}

export async function submitOrder(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, include_care_plan: boolean, idempotency_key?: string) {
  return post(`/programs/${program_id}/orders/${order_id}/submit`, { include_care_plan }, { ...actor, idempotency_key });
}

export async function refreshPayment(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, idempotency_key?: string) {
  return post(`/programs/${program_id}/orders/${order_id}/refresh_payment`, {}, { ...actor, idempotency_key });
}

export async function cancelOrder(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, reason = 'cancel') {
  return post(`/programs/${program_id}/orders/${order_id}/cancel`, { reason }, actor);
}

export async function shipOrder(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, body: { build_lot_id: string; serial_number: string; build_tag: string }) {
  const res = await post(`/programs/${program_id}/orders/${order_id}/ship`, body, actor);
  return res;
}

export async function markDelivered(program_id: string, order_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/orders/${order_id}/mark_delivered`, {}, actor);
  return res;
}

export async function createDeliveredOrder(args: {
  program_id: string;
  customer_id: string;
  customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string };
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  build_lot_id: string;
  build_tag: string;
  serial_number?: string;
  include_care_plan: boolean;
  use_credit_cents?: number;
}): Promise<Order> {
  const opsActor = { actor_id: args.opsCtx.actor_id, actor_type: args.opsCtx.actor_type };
  const order = await createOrder(args.program_id, args.customer_id, args.customerCtx, { use_credit_cents: args.use_credit_cents ?? 0 });
  expectSuccess(await submitOrder(args.program_id, order.order_id, args.customerCtx, args.include_care_plan), 200);
  expectSuccess(
    await shipOrder(args.program_id, order.order_id, args.opsCtx, {
      build_lot_id: args.build_lot_id,
      serial_number: args.serial_number ?? `SN-${uniqueId('sn')}`,
      build_tag: args.build_tag
    }),
    200
  );
  expectSuccess(await markDelivered(args.program_id, order.order_id, args.opsCtx), 200);
  const delivered = await getOrder(args.program_id, order.order_id, opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.device_id).toBeTruthy();
  return delivered;
}

export async function getPayment(program_id: string, payment_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Payment> {
  const res = await get(`/programs/${program_id}/payments/${payment_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Payment;
}

export async function getCarePlan(program_id: string, care_plan_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<CarePlan> {
  const res = await get(`/programs/${program_id}/care_plans/${care_plan_id}`, actor);
  expectSuccess(res, 200);
  return res.body as CarePlan;
}

export async function disputePayment(program_id: string, payment_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/payments/${payment_id}/dispute`, {}, actor);
  return res;
}

export async function resolveDispute(program_id: string, payment_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, outcome: 'CHARGEBACK_LOST' | 'REFUNDED') {
  const res = await post(`/programs/${program_id}/payments/${payment_id}/resolve_dispute`, { outcome }, actor);
  return res;
}

export async function createTradeIn(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, quoted_credit_cents: number) {
  return post(`/programs/${program_id}/customers/${customer_id}/tradeins`, { quoted_credit_cents }, actor);
}

export async function getTradeIn(program_id: string, tradein_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<TradeIn> {
  const res = await get(`/programs/${program_id}/tradeins/${tradein_id}`, actor);
  expectSuccess(res, 200);
  return res.body as TradeIn;
}

export async function submitTradeIn(program_id: string, tradein_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/tradeins/${tradein_id}/submit`, {}, actor);
}

export async function markInboundTradeIn(program_id: string, tradein_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/tradeins/${tradein_id}/mark_inbound`, {}, actor);
}

export async function appraiseTradeIn(
  program_id: string,
  tradein_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  body: { accepted: boolean; final_credit_cents: number }
) {
  return post(`/programs/${program_id}/tradeins/${tradein_id}/appraise`, body, actor);
}

export async function reverseTradeInCredit(program_id: string, tradein_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, reason: string) {
  return post(`/programs/${program_id}/tradeins/${tradein_id}/reverse_credit`, { reason }, actor);
}

export async function createReturn(
  program_id: string,
  order_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  resolution_preference: 'REFUND' | 'REPLACEMENT'
) {
  return post(`/programs/${program_id}/orders/${order_id}/returns`, { resolution_preference }, actor);
}

export async function getReturn(program_id: string, return_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Return> {
  const res = await get(`/programs/${program_id}/returns/${return_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Return;
}

export async function approveReturn(program_id: string, return_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/returns/${return_id}/approve`, {}, actor);
}

export async function markInboundReturn(program_id: string, return_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/returns/${return_id}/mark_inbound`, {}, actor);
}

export async function receiveReturn(
  program_id: string,
  return_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  inspection_outcome: 'RESTOCK' | 'REFURB' | 'SCRAP'
) {
  return post(`/programs/${program_id}/returns/${return_id}/receive`, { inspection_outcome }, actor);
}

export async function completeReturn(
  program_id: string,
  return_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  body: { resolution: 'REFUND' | 'REPLACEMENT'; replacement_build_lot_id: string | null; replacement_serial_number: string | null; replacement_build_tag: string | null }
) {
  return post(`/programs/${program_id}/returns/${return_id}/complete`, body, actor);
}

export async function createAdjustment(program_id: string, customer_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, adjustment_type: Adjustment['adjustment_type'], amount_cents: number) {
  const res = await post(`/programs/${program_id}/customers/${customer_id}/adjustments`, { adjustment_type, amount_cents }, actor);
  return res;
}

export async function getAdjustment(program_id: string, adjustment_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Adjustment> {
  const res = await get(`/programs/${program_id}/adjustments/${adjustment_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Adjustment;
}

export async function applyAdjustment(program_id: string, adjustment_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/adjustments/${adjustment_id}/apply`, {}, actor);
}

export async function voidAdjustment(program_id: string, adjustment_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/adjustments/${adjustment_id}/void`, {}, actor);
}

export async function createQualityCampaign(program_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, campaign_type: QualityCampaign['campaign_type'], build_tag_prefix: string) {
  const res = await post(`/programs/${program_id}/quality_campaigns`, { campaign_type, build_tag_prefix }, actor);
  return res;
}

export async function getQualityCampaign(program_id: string, quality_campaign_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<QualityCampaign> {
  const res = await get(`/programs/${program_id}/quality_campaigns/${quality_campaign_id}`, actor);
  expectSuccess(res, 200);
  return res.body as QualityCampaign;
}

export async function resolveQualityCampaign(program_id: string, quality_campaign_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/quality_campaigns/${quality_campaign_id}/resolve`, {}, actor);
  return res;
}

export async function closeQualityCampaign(program_id: string, quality_campaign_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/quality_campaigns/${quality_campaign_id}/close`, {}, actor);
  return res;
}

export async function escalateQualityCampaign(program_id: string, quality_campaign_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/quality_campaigns/${quality_campaign_id}/escalate`, {}, actor);
  return res;
}

export async function listAlerts(program_id: string, actor: { actor_id: string; actor_type: ActorType }, query: Record<string, string | number | null | undefined> = {}): Promise<{ alerts: Alert[] }> {
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  const path = qs.length > 0 ? `/programs/${program_id}/alerts?${qs}` : `/programs/${program_id}/alerts`;
  const res = await get(path, actor);
  expectSuccess(res, 200);
  return res.body as { alerts: Alert[] };
}

export async function getAlert(program_id: string, alert_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Alert> {
  const res = await get(`/programs/${program_id}/alerts/${alert_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Alert;
}

export async function acknowledgeAlert(program_id: string, alert_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/alerts/${alert_id}/acknowledge`, {}, actor);
  return res;
}

export async function resolveAlert(program_id: string, alert_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  const res = await post(`/programs/${program_id}/alerts/${alert_id}/resolve`, {}, actor);
  return res;
}

export async function getDevice(program_id: string, device_id: string, actor: { actor_id: string; actor_type: ActorType }): Promise<Device> {
  const res = await get(`/programs/${program_id}/devices/${device_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Device;
}

export async function activateDevice(program_id: string, device_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/devices/${device_id}/activate`, {}, actor);
}

export async function remediateDevice(program_id: string, device_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, note: string) {
  return post(`/programs/${program_id}/devices/${device_id}/remediate`, { note }, actor);
}

export async function createClaim(program_id: string, device_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, claim_type: Claim['claim_type']) {
  const res = await post(`/programs/${program_id}/devices/${device_id}/claims`, { claim_type }, actor);
  return res;
}

export async function approveClaim(program_id: string, claim_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, resolution: 'REPLACEMENT' | 'ADVANCE_REPLACEMENT') {
  const res = await post(`/programs/${program_id}/claims/${claim_id}/approve`, { resolution }, actor);
  return res;
}

export async function cancelClaim(program_id: string, claim_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, reason: string) {
  const res = await post(`/programs/${program_id}/claims/${claim_id}/cancel`, { reason }, actor);
  return res;
}

export async function getClaim(program_id: string, claim_id: string, actor: { actor_id: string; actor_type: ActorType }) {
  const res = await get(`/programs/${program_id}/claims/${claim_id}`, actor);
  expectSuccess(res, 200);
  return res.body as Claim;
}

export async function markInboundClaim(program_id: string, claim_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }) {
  return post(`/programs/${program_id}/claims/${claim_id}/mark_inbound`, {}, actor);
}

export async function receiveClaim(
  program_id: string,
  claim_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  inspection_outcome: 'REFURB' | 'SCRAP'
) {
  return post(`/programs/${program_id}/claims/${claim_id}/receive`, { inspection_outcome }, actor);
}

export async function completeClaim(
  program_id: string,
  claim_id: string,
  actor: { actor_id: string; actor_type: ActorType; session_id: string },
  body: { replacement_build_lot_id: string | null; replacement_serial_number: string | null; replacement_build_tag: string | null }
) {
  return post(`/programs/${program_id}/claims/${claim_id}/complete`, body, actor);
}

export async function shipAdvanceReplacement(program_id: string, claim_id: string, actor: { actor_id: string; actor_type: ActorType; session_id: string }, body: { replacement_build_lot_id: string; replacement_serial_number: string; replacement_build_tag: string }, idempotency_key?: string) {
  const res = await post(`/programs/${program_id}/claims/${claim_id}/ship_advance_replacement`, body, { ...actor, idempotency_key });
  return res;
}

export function expectErrorCode(response: any, status: number, code: string) {
  expectError(response, status, code);
}

export async function createOpsCtx(program_id: string) {
  const actor = { actor_id: uniqueId('ops'), actor_type: 'Ops' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

export async function createSupportCtx(program_id: string) {
  const actor = { actor_id: uniqueId('sup'), actor_type: 'Support' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

export async function createCustomerCtx(program_id: string, customer_id: string) {
  const actor = { actor_id: customer_id, actor_type: 'Customer' as const };
  const session = await createSession(program_id, actor);
  return { actor, ctx: { ...actor, session_id: session.session_id } };
}

export async function runOpsTo(program_id: string, opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string }, target: number) {
  let current = await getProgram(program_id, { actor_id: opsCtx.actor_id, actor_type: opsCtx.actor_type });
  while (current.ops_run_index < target) {
    current = await runOps(program_id, opsCtx);
  }
  return current;
}

export async function createDeliveredOrderWithDevice(args: {
  program_id: string;
  opsActor: { actor_id: string; actor_type: 'Ops' };
  opsCtx: { actor_id: string; actor_type: 'Ops'; session_id: string };
  build_tag: string;
  units: number;
  include_care_plan: boolean;
  activate: boolean;
}) {
  const lot = await createBuildLot(args.program_id, args.opsCtx, args.build_tag, args.units);
  expect(lot.build_lot_status).toBe('AVAILABLE');

  const customer = await createCustomer(args.program_id, args.opsCtx);
  const { ctx: customerCtx } = await createCustomerCtx(args.program_id, customer.customer_id);

  const order = await createOrder(args.program_id, customer.customer_id, customerCtx);
  expectSuccess(await submitOrder(args.program_id, order.order_id, customerCtx, args.include_care_plan), 200);

  expectSuccess(
    await shipOrder(args.program_id, order.order_id, args.opsCtx, {
      build_lot_id: lot.build_lot_id,
      serial_number: `SN-${uniqueId('sn')}`,
      build_tag: lot.build_tag
    }),
    200
  );
  expectSuccess(await markDelivered(args.program_id, order.order_id, args.opsCtx), 200);

  const delivered = await getOrder(args.program_id, order.order_id, args.opsActor);
  expect(delivered.order_status).toBe('DELIVERED');
  expect(delivered.device_id).toBeTruthy();
  expect(delivered.payment_id).toBeTruthy();

  const deviceId = delivered.device_id as string;
  const carePlanId = delivered.care_plan_id as string | null;
  const paymentId = delivered.payment_id as string;

  const pm = await getPayment(args.program_id, paymentId, args.opsActor);
  expect(pm.payment_status).toBe('CAPTURED');

  if (args.activate) {
    expectSuccess(await activateDevice(args.program_id, deviceId, customerCtx), 200);
    const d = await getDevice(args.program_id, deviceId, args.opsActor);
    expect(d.device_status).toBe('ACTIVE');
  } else {
    const d = await getDevice(args.program_id, deviceId, args.opsActor);
    expect(d.device_status).toBe('SHIPPED');
  }

  return { customer, customerCtx, delivered, deviceId, carePlanId, paymentId, lot };
}

export async function createSubmittedOrder(args: { program_id: string; customer_id: string; customerCtx: { actor_id: string; actor_type: 'Customer'; session_id: string } }) {
  const order = await createOrder(args.program_id, args.customer_id, args.customerCtx);
  expectSuccess(await submitOrder(args.program_id, order.order_id, args.customerCtx, false), 200);
  return order.order_id;
}

export async function createAndApplyBalanceDue(program_id: string, customer_id: string, supportCtx: { actor_id: string; actor_type: 'Support'; session_id: string }, amount_cents: number) {
  const createRes = await createAdjustment(program_id, customer_id, supportCtx, 'CREDIT_CLAWBACK', amount_cents);
  expectSuccess(createRes, 201);
  const adjustment_id = createRes.body.adjustment_id as string;
  expectSuccess(await applyAdjustment(program_id, adjustment_id, supportCtx), 200);
}
