"""Dealer repair claims: submission, audit and reversal."""
from flask import Blueprint, g, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import base_record, parse_date, parse_instant, sorted_records, store, touch
from db import UTC
from errors import ApiError
from response import collection, single

bp = Blueprint("claims", __name__)


@bp.post("/repair-claims")
@require_roles("DealerServiceManager")
def create_claim():
    payload = v.body()
    av_id = v.req_str(payload, "affected_vehicle_id")
    dealer_id = v.req_str(payload, "dealer_id")
    labor_operation_id = v.req_str(payload, "labor_operation_id")
    repair_raw, repair_date = v.req_date_str(payload, "repair_date")
    claimed_hours = v.req_decimal(payload, "claimed_labor_hours", gt=0)
    parts_used_qty = v.req_int(payload, "parts_used_qty", minimum=1)

    dealer = h.get_dealer(dealer_id)
    labor_op = h.get_labor_op(labor_operation_id)
    av = h.get_av(av_id)

    if dealer_id != g.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")
    if av["dealer_id"] is not None and av["dealer_id"] != g.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")

    campaign = store.campaigns.get(av["campaign_id"])
    h.assert_campaign_writable(campaign)
    if av["remedy_status"] not in ("UNREPAIRED", "SCHEDULED", "REMEDIED"):
        raise ApiError("ERR_VEHICLE_NOT_REPAIRABLE")

    h.assert_remedy_available(campaign)

    if not (parse_date(labor_op["effective_from"]) <= repair_date
            <= parse_date(labor_op["effective_to"])):
        raise ApiError("ERR_LABOR_OP_NOT_EFFECTIVE")
    if labor_op["campaign_id"] != av["campaign_id"]:
        raise ApiError("ERR_PART_CAMPAIGN_MISMATCH")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED")

    released = parse_instant(campaign["remedy_released_at"]) \
        if campaign["remedy_released_at"] else None
    if released is not None and repair_date < released.astimezone(UTC).date():
        raise ApiError("ERR_REPAIR_DATE_BEFORE_REMEDY")

    for other in store.repair_claims.values():
        if (other["affected_vehicle_id"] == av["id"]
                and other["repair_date"] == repair_raw
                and other["status"] in ("SUBMITTED", "APPROVED")):
            raise ApiError("ERR_DUPLICATE_REPAIR_CLAIM")

    allocation = calc.pick_allocation(dealer["id"], av["campaign_id"])
    if allocation is None:
        raise ApiError("ERR_NO_PARTS_AVAILABLE")

    if claimed_hours > labor_op["flat_hours"] * calc.CLAIM_HOURS_TOLERANCE:
        raise ApiError("ERR_LABOR_HOURS_EXCEED_CAP")

    part = calc.campaign_first_part(av["campaign_id"])
    claim = base_record()
    claim.update({
        "campaign_id": av["campaign_id"],
        "affected_vehicle_id": av["id"],
        "dealer_id": dealer["id"],
        "labor_operation_id": labor_op["id"],
        "parts_allocation_id": allocation["id"],
        "repair_date": repair_raw,
        "claimed_labor_hours": calc.q2(claimed_hours),
        "parts_used_qty": parts_used_qty,
        "provisional_amount_cents": calc.provisional_amount_cents(
            calc.q2(claimed_hours), parts_used_qty, dealer, part),
        "final_amount_cents": None,
        "is_repeat_repair": calc.approved_claim_count(av["id"]) >= 1,
        "status": "SUBMITTED",
        "audit_note": None,
        "reversal_reason": None,
    })
    store.repair_claims[claim["id"]] = claim
    return single(h.claim_out(claim), 201)


@bp.get("/repair-claims")
@require_roles(*ALL_ROLES)
def list_claims():
    status = v.query_enum("status", v.CLAIM_STATUSES)
    filters = {
        "campaign_id": request.args.get("campaign_id"),
        "dealer_id": request.args.get("dealer_id"),
        "affected_vehicle_id": request.args.get("affected_vehicle_id"),
        "labor_operation_id": request.args.get("labor_operation_id"),
        "parts_allocation_id": request.args.get("parts_allocation_id"),
    }
    rows = list(store.repair_claims.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(sorted_records(rows), h.claim_out)


@bp.get("/repair-claims/<claim_id>")
@require_roles(*ALL_ROLES)
def get_claim(claim_id):
    return single(h.claim_out(h.get_claim(claim_id)))


@bp.post("/repair-claims/<claim_id>/audit")
@require_roles("ClaimsAuditor")
def audit_claim(claim_id):
    claim = h.get_claim(claim_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", v.DECISIONS_CLAIM)
    audit_note = v.opt_str(payload, "audit_note")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    campaign = store.campaigns.get(claim["campaign_id"])
    av = store.affected_vehicles.get(claim["affected_vehicle_id"])
    dealer = store.dealers.get(claim["dealer_id"])
    labor_op = store.labor_operations.get(claim["labor_operation_id"])
    allocation = store.allocations.get(claim["parts_allocation_id"])
    part = calc.campaign_first_part(claim["campaign_id"])

    if decision == "REJECT":
        claim["status"] = "REJECTED"
        claim["audit_note"] = audit_note
        touch(claim)
        return single(h.claim_out(claim))

    h.assert_remedy_available(campaign)

    if (allocation is None or allocation["status"] != "ALLOCATED"
            or (allocation["allocated_qty"] - allocation["consumed_qty"])
            < calc.PARTS_PER_REPAIR_MAX):
        raise ApiError("ERR_NO_PARTS_AVAILABLE")

    claim["final_amount_cents"] = calc.final_amount_cents(
        claim, dealer, labor_op, part, campaign)
    claim["audit_note"] = audit_note
    claim["status"] = "APPROVED"
    touch(claim)

    if av is not None:
        if av["remedy_status"] in ("SCHEDULED", "UNREPAIRED"):
            av["remedy_status"] = "REMEDIED"
        touch(av)

    allocation["consumed_qty"] = allocation["consumed_qty"] + calc.PARTS_PER_REPAIR_MAX
    touch(allocation)
    source_part = store.remedy_parts.get(allocation["remedy_part_id"])
    if source_part is not None:
        source_part["consumed_qty"] = source_part["consumed_qty"] + calc.PARTS_PER_REPAIR_MAX
        touch(source_part)

    # PRD 3.7 / 3.9 - the effectiveness score is recomputed on every approval.
    h.recompute_effectiveness(campaign)
    touch(campaign)
    return single(h.claim_out(claim))


@bp.post("/repair-claims/<claim_id>/reverse")
@require_roles("ClaimsAuditor")
def reverse_claim(claim_id):
    claim = h.get_claim(claim_id)
    payload = v.body()
    reversal_reason = v.req_str(payload, "reversal_reason")

    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    campaign = store.campaigns.get(claim["campaign_id"])
    av = store.affected_vehicles.get(claim["affected_vehicle_id"])
    allocation = store.allocations.get(claim["parts_allocation_id"])

    claim["status"] = "REVERSED"
    claim["reversal_reason"] = reversal_reason
    touch(claim)

    # PRD 2.9 - the freed unit goes back to the live allocation when it still
    # exists, otherwise straight to the part's unallocated pool.
    if allocation is not None:
        part = store.remedy_parts.get(allocation["remedy_part_id"])
        if part is not None:
            part["consumed_qty"] = part["consumed_qty"] - calc.PARTS_PER_REPAIR_MAX
        if allocation["status"] == "ALLOCATED":
            allocation["consumed_qty"] = allocation["consumed_qty"] - calc.PARTS_PER_REPAIR_MAX
            touch(allocation)
        elif part is not None:
            part["unallocated_qty"] = part["unallocated_qty"] + calc.PARTS_PER_REPAIR_MAX
        if part is not None:
            touch(part)

    if av is not None:
        if calc.approved_claim_count(av["id"]) == 0 and av["remedy_status"] == "REMEDIED":
            av["remedy_status"] = "UNREPAIRED"
        touch(av)

    # PRD 3.9 - the effectiveness score is recomputed on every reversal.
    h.recompute_effectiveness(campaign)

    if av is not None:
        h.followup_wave_autoschedule(campaign, av)

    touch(campaign)
    return single(h.claim_out(claim))
