import type { Db } from "../db";
import { getCustomerOrThrow, getProgramOrThrow, recomputeAvailability, recomputePosture } from "../domain";

export function programResponse(db: Db, programId: string) {
  recomputeAvailability(db, programId);
  recomputePosture(db, programId);
  const program = getProgramOrThrow(db, programId);
  return {
    program_id: program.program_id,
    display_name: program.display_name,
    program_posture: program.program_posture,
    ops_run_index: program.ops_run_index,
    available_to_commit_units: program.available_to_commit_units,
  };
}

export function customerResponse(db: Db, programId: string, customerId: string) {
  const c = getCustomerOrThrow(db, programId, customerId);
  return {
    customer_id: c.customer_id,
    display_name: c.display_name,
    customer_status: c.customer_status,
    credit_balance_cents: c.credit_balance_cents,
    balance_due_cents: c.balance_due_cents,
  };
}

export function sessionResponse(row: { session_id: string; actor_id: string; actor_type: string; session_status: string }) {
  return {
    session_id: row.session_id,
    actor_id: row.actor_id,
    actor_type: row.actor_type,
    session_status: row.session_status,
  };
}

export function buildLotResponse(row: { build_lot_id: string; build_tag: string; build_lot_status: string }) {
  return {
    build_lot_id: row.build_lot_id,
    build_tag: row.build_tag,
    build_lot_status: row.build_lot_status,
  };
}

export function orderResponse(row: any) {
  return {
    order_id: row.order_id,
    customer_id: row.customer_id,
    order_status: row.order_status,
    model_code: row.model_code,
    unit_price_cents: row.unit_price_cents,
    care_plan_price_cents: row.care_plan_price_cents,
    paid_by_credit_cents: row.paid_by_credit_cents,
    paid_by_card_cents: row.paid_by_card_cents,
    payment_id: row.payment_id ?? null,
    device_id: row.device_id ?? null,
    care_plan_id: row.care_plan_id ?? null,
    tradein_id: row.tradein_id ?? null,
  };
}

export function paymentResponse(row: any) {
  return {
    payment_id: row.payment_id,
    order_id: row.order_id,
    payment_status: row.payment_status,
    amount_cents: row.amount_cents,
  };
}

export function deviceResponse(row: any) {
  return {
    device_id: row.device_id,
    order_id: row.order_id,
    customer_id: row.customer_id,
    serial_number: row.serial_number,
    build_tag: row.build_tag,
    device_status: row.device_status,
  };
}

export function carePlanResponse(row: any) {
  return {
    care_plan_id: row.care_plan_id,
    order_id: row.order_id,
    customer_id: row.customer_id,
    device_id: row.device_id ?? null,
    care_plan_status: row.care_plan_status,
  };
}

export function tradeinResponse(row: any) {
  return {
    tradein_id: row.tradein_id,
    customer_id: row.customer_id,
    tradein_status: row.tradein_status,
    quoted_credit_cents: row.quoted_credit_cents,
    final_credit_cents: row.final_credit_cents ?? null,
  };
}

export function returnResponse(row: any) {
  return {
    return_id: row.return_id,
    order_id: row.order_id,
    device_id: row.device_id,
    customer_id: row.customer_id,
    return_status: row.return_status,
    resolution_preference: row.resolution_preference,
    inspection_outcome: row.inspection_outcome ?? null,
    refunded_to_card_cents: row.refunded_to_card_cents,
    refunded_to_credit_cents: row.refunded_to_credit_cents,
    replacement_device_id: row.replacement_device_id ?? null,
  };
}

export function claimResponse(row: any) {
  return {
    claim_id: row.claim_id,
    order_id: row.order_id,
    device_id: row.device_id,
    customer_id: row.customer_id,
    claim_status: row.claim_status,
    claim_type: row.claim_type,
    claim_resolution: row.claim_resolution ?? null,
    inspection_outcome: row.inspection_outcome ?? null,
    replacement_device_id: row.replacement_device_id ?? null,
  };
}

export function adjustmentResponse(row: any) {
  return {
    adjustment_id: row.adjustment_id,
    customer_id: row.customer_id,
    adjustment_type: row.adjustment_type,
    adjustment_status: row.adjustment_status,
    amount_cents: row.amount_cents,
  };
}

export function qualityCampaignResponse(row: any) {
  return {
    quality_campaign_id: row.quality_campaign_id,
    campaign_type: row.campaign_type,
    campaign_status: row.campaign_status,
    build_tag_prefix: row.build_tag_prefix,
  };
}

export function alertResponse(row: any) {
  return {
    alert_id: row.alert_id,
    alert_type: row.alert_type,
    alert_status: row.alert_status,
    opened_ops_run_index: row.opened_ops_run_index,
    customer_id: row.customer_id ?? null,
    order_id: row.order_id ?? null,
    device_id: row.device_id ?? null,
    payment_id: row.payment_id ?? null,
    tradein_id: row.tradein_id ?? null,
    quality_campaign_id: row.quality_campaign_id ?? null,
    claim_id: row.claim_id ?? null,
  };
}
