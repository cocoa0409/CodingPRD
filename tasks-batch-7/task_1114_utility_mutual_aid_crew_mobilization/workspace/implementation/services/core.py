"""Common helpers: common fields, derived fields, lookups."""
from datetime import timezone

import db
from errors import not_found


def touch(entity):
    """Refresh updated_at and bump version on every mutation."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


def base_fields():
    now = db.now_iso()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def get_or_404(table, id_, label="resource"):
    obj = table.get(id_)
    if obj is None:
        raise not_found(f"{label} {id_} not found")
    return obj


# ----- cross-entity lookups -----

def crews_of_request(request_id):
    return [c for c in db.crews.values() if c["request_id"] == request_id]


def request_of_crew(crew):
    return db.assistance_requests.get(crew["request_id"])


def event_of_request(request):
    return db.events.get(request["event_id"]) if request else None


def event_of_crew(crew):
    req = request_of_crew(crew)
    return event_of_request(req)


# ----- derived counters -----

def recompute_request_counts(request):
    crews = crews_of_request(request["id"])
    committed = sum(
        1 for c in crews
        if c["mobility_status"] in ("COMMITTED", "ARRIVED", "DEMOBILIZING")
    )
    deployable = sum(
        1 for c in crews
        if c["mobility_status"] == "ARRIVED" and c["readiness_status"] == "CLEARED_TO_WORK"
    )
    request["committed_crew_count"] = committed
    request["deployable_crew_count"] = deployable


def recompute_request_certified_direct(request):
    crews = crews_of_request(request["id"])
    crew_ids = {c["id"] for c in crews}
    ts_total = sum(
        t["certified_amount_cents"] or 0
        for t in db.timesheets.values()
        if t["crew_id"] in crew_ids and t["status"] == "CERTIFIED"
    )
    pd_total = sum(
        p["amount_cents"] or 0
        for p in db.per_diem_claims.values()
        if p["crew_id"] in crew_ids and p["status"] == "APPROVED"
    )
    request["certified_direct_cents"] = ts_total + pd_total


def recompute_request_invoiced_total(request):
    inv = next(
        (
            i for i in db.invoices.values()
            if i["request_id"] == request["id"]
            and i["status"] not in ("DRAFT", "VOID")
        ),
        None,
    )
    request["invoiced_total_cents"] = inv["final_total_cents"] if inv else 0


def recompute_event_open_request_count(event):
    n = sum(
        1 for r in db.assistance_requests.values()
        if r["event_id"] == event["id"] and r["status"] in ("SUBMITTED", "COUNTERED")
    )
    event["open_request_count"] = n


def recompute_event_intake_posture(event):
    if event["status"] in ("DEMOBILIZING", "CLOSED"):
        event["intake_posture"] = "SEALED"
    elif event.get("open_request_count", 0) >= 3:
        event["intake_posture"] = "RESTRICTED"
    else:
        event["intake_posture"] = "ACCEPTING"


def recompute_event_totals(event):
    reqs = [r for r in db.assistance_requests.values() if r["event_id"] == event["id"]]
    req_ids = {r["id"] for r in reqs}
    crews = [c for c in db.crews.values() if c["request_id"] in req_ids]
    crew_ids = {c["id"] for c in crews}

    ts_total = sum(
        t["certified_amount_cents"] or 0
        for t in db.timesheets.values()
        if t["crew_id"] in crew_ids and t["status"] == "CERTIFIED"
    )
    pd_total = sum(
        p["amount_cents"] or 0
        for p in db.per_diem_claims.values()
        if p["crew_id"] in crew_ids and p["status"] == "APPROVED"
    )
    event["total_certified_direct_cents"] = ts_total + pd_total

    event["total_invoiced_cents"] = sum(
        i["final_total_cents"] or 0
        for i in db.invoices.values()
        if i["request_id"] in req_ids
        and i["status"] in ("SUBMITTED", "DISPUTED", "CREDIT_PROPOSED", "ESCALATED", "APPROVED", "PAID")
    )
    event["total_paid_cents"] = sum(
        i["amount_paid_cents"] or 0
        for i in db.invoices.values()
        if i["request_id"] in req_ids and i["status"] == "PAID"
    )


def recompute_block_assigned_rooms(block):
    total = sum(
        a["room_count"]
        for a in db.lodging_assignments.values()
        if a["block_id"] == block["id"] and a["status"] in ("RESERVED", "OCCUPIED")
    )
    block["assigned_rooms"] = total


def recompute_invoice_outstanding(invoice):
    invoice["outstanding_cents"] = (
        (invoice.get("final_total_cents") or 0)
        - (invoice.get("applied_credit_total_cents") or 0)
        - (invoice.get("amount_paid_cents") or 0)
    )


# ----- cascades -----

def maybe_transition_request_on_deployable(request):
    """Handle FULFILLED<->IN_PROGRESS based on deployable count."""
    deployable = request.get("deployable_crew_count", 0)
    required = request.get("required_minimum_crews", 0)
    if request["status"] == "IN_PROGRESS" and deployable >= required:
        request["status"] = "FULFILLED"
        touch(request)
    elif request["status"] == "FULFILLED" and deployable < required:
        request["status"] = "IN_PROGRESS"
        touch(request)


def recompute_request_full(request):
    """Recompute derived counts and possibly flip request state."""
    recompute_request_counts(request)
    recompute_request_certified_direct(request)
    maybe_transition_request_on_deployable(request)


def crew_release_check_request(crew):
    """If all crews of the request are in terminal mobility, release the request."""
    req = request_of_crew(crew)
    if req is None:
        return
    crews = crews_of_request(req["id"])
    if crews and all(
        c["mobility_status"] in ("RETURNED", "WITHDRAWN") for c in crews
    ):
        if req["status"] in ("IN_PROGRESS", "FULFILLED"):
            req["status"] = "RELEASED"
            touch(req)


def recompute_event_full(event):
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    recompute_event_totals(event)


# ----- serialization -----

def serialize_company(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "company_code": c["company_code"],
        "role_capability": c["role_capability"],
        "home_region": c["home_region"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "event_name": e["event_name"],
        "host_utility_id": e["host_utility_id"],
        "event_type": e["event_type"],
        "declared_start_date": e["declared_start_date"],
        "premium_window_start": e["premium_window_start"],
        "premium_window_end": e["premium_window_end"],
        "mobilization_deadline": e["mobilization_deadline"],
        "status": e["status"],
        "demobilized_at": e.get("demobilized_at"),
        "open_request_count": e.get("open_request_count", 0),
        "total_certified_direct_cents": e.get("total_certified_direct_cents", 0),
        "total_invoiced_cents": e.get("total_invoiced_cents", 0),
        "total_paid_cents": e.get("total_paid_cents", 0),
        "intake_posture": e.get("intake_posture", "ACCEPTING"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_schedule(s):
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "responding_utility_id": s["responding_utility_id"],
        "supersedes_schedule_id": s.get("supersedes_schedule_id"),
        "effective_start_date": s["effective_start_date"],
        "effective_end_date": s["effective_end_date"],
        "rate_lines": s["rate_lines"],
        "ot_multiplier_bps": s["ot_multiplier_bps"],
        "dt_multiplier_bps": s["dt_multiplier_bps"],
        "ot_threshold_minutes": s["ot_threshold_minutes"],
        "dt_threshold_minutes": s["dt_threshold_minutes"],
        "storm_premium_bps": s["storm_premium_bps"],
        "per_diem_rate_cents": s["per_diem_rate_cents"],
        "per_diem_method": s["per_diem_method"],
        "mobilization_fee_tiers": s["mobilization_fee_tiers"],
        "status": s["status"],
        "published_at": s.get("published_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_request(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "responding_utility_id": r["responding_utility_id"],
        "requested_crews": r["requested_crews"],
        "required_minimum_crews": r["required_minimum_crews"],
        "earliest_start_date": r["earliest_start_date"],
        "latest_end_date": r["latest_end_date"],
        "status": r["status"],
        "amendment_round": r.get("amendment_round", 0),
        "counter_terms": r.get("counter_terms"),
        "committed_crew_count": r.get("committed_crew_count", 0),
        "deployable_crew_count": r.get("deployable_crew_count", 0),
        "certified_direct_cents": r.get("certified_direct_cents", 0),
        "invoiced_total_cents": r.get("invoiced_total_cents", 0),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_crew(c):
    return {
        "id": c["id"],
        "request_id": c["request_id"],
        "owning_utility_id": c["owning_utility_id"],
        "crew_type": c["crew_type"],
        "home_base": c["home_base"],
        "roster": c["roster"],
        "roster_size": c["roster_size"],
        "equipment_units": c["equipment_units"],
        "equipment_daily_total_cents": c["equipment_daily_total_cents"],
        "mobility_status": c["mobility_status"],
        "readiness_status": c["readiness_status"],
        "last_suspended_at": c.get("last_suspended_at"),
        "arrived_at": c.get("arrived_at"),
        "released_at": c.get("released_at"),
        "returned_at": c.get("returned_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_briefing(b):
    return {
        "id": b["id"],
        "crew_id": b["crew_id"],
        "event_id": b["event_id"],
        "conductor_operator_ref": b["conductor_operator_ref"],
        "host_rules_version": b["host_rules_version"],
        "topics": b["topics"],
        "conducted_at": b["conducted_at"],
        "supervisor_operator_ref": b.get("supervisor_operator_ref"),
        "acknowledged_at": b.get("acknowledged_at"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_timesheet(t):
    return {
        "id": t["id"],
        "crew_id": t["crew_id"],
        "work_date": t["work_date"],
        "day_classification": t["day_classification"],
        "reported_work_minutes": t.get("reported_work_minutes", 0),
        "reported_travel_minutes": t.get("reported_travel_minutes", 0),
        "submitted_by_operator_ref": t.get("submitted_by_operator_ref"),
        "certified_by_operator_ref": t.get("certified_by_operator_ref"),
        "certified_schedule_id": t.get("certified_schedule_id"),
        "certified_amount_cents": t.get("certified_amount_cents"),
        "billed_invoice_id": t.get("billed_invoice_id"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_lodging_block(b):
    return {
        "id": b["id"],
        "event_id": b["event_id"],
        "hotel_name": b["hotel_name"],
        "block_code": b["block_code"],
        "total_rooms": b["total_rooms"],
        "nightly_rate_cents": b["nightly_rate_cents"],
        "assigned_rooms": b.get("assigned_rooms", 0),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_lodging_assignment(a):
    return {
        "id": a["id"],
        "block_id": a["block_id"],
        "crew_id": a["crew_id"],
        "room_count": a["room_count"],
        "check_in_date": a["check_in_date"],
        "check_out_date": a["check_out_date"],
        "actual_check_out_date": a.get("actual_check_out_date"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_per_diem_claim(p):
    return {
        "id": p["id"],
        "crew_id": p["crew_id"],
        "claim_date": p["claim_date"],
        "member_count": p["member_count"],
        "meals_provided_count": p["meals_provided_count"],
        "day_factor_type": p["day_factor_type"],
        "receipts_total_cents": p.get("receipts_total_cents"),
        "method_applied": p.get("method_applied"),
        "lodging_covered": p.get("lodging_covered", False),
        "amount_cents": p.get("amount_cents"),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_invoice(i):
    return {
        "id": i["id"],
        "request_id": i["request_id"],
        "rate_schedule_id": i["rate_schedule_id"],
        "billing_period_start": i["billing_period_start"],
        "billing_period_end": i["billing_period_end"],
        "provisional_subtotal_cents": i.get("provisional_subtotal_cents"),
        "provisional_fee_cents": i.get("provisional_fee_cents"),
        "provisional_total_cents": i.get("provisional_total_cents"),
        "labor_subtotal_cents": i.get("labor_subtotal_cents"),
        "per_diem_subtotal_cents": i.get("per_diem_subtotal_cents"),
        "mobilization_fee_cents": i.get("mobilization_fee_cents"),
        "final_total_cents": i.get("final_total_cents"),
        "dispute_reason": i.get("dispute_reason"),
        "disputed_amount_cents": i.get("disputed_amount_cents"),
        "proposed_credit_cents": i.get("proposed_credit_cents"),
        "applied_credit_total_cents": i.get("applied_credit_total_cents", 0),
        "amount_paid_cents": i.get("amount_paid_cents", 0),
        "outstanding_cents": i.get("outstanding_cents"),
        "approved_by_operator_ref": i.get("approved_by_operator_ref"),
        "status": i["status"],
        "submitted_at": i.get("submitted_at"),
        "paid_at": i.get("paid_at"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_aar(a):
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "summary": a["summary"],
        "lessons_learned": a.get("lessons_learned"),
        "total_crew_days": a.get("total_crew_days", 0),
        "as_certified_total_cents": a.get("as_certified_total_cents", 0),
        "as_billed_total_cents": a.get("as_billed_total_cents", 0),
        "variance_cents": a.get("variance_cents", 0),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
