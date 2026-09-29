"""Placement offer, confirmation and termination (PRD 3.6)."""

from flask import Blueprint, request

import db
from db import (
    BILLING_STATUSES,
    CLAIM_STATUSES,
    HANDOFF_STATUSES,
    INVOICE_STATUSES,
    MILESTONE_TYPES,
    OPEN_CLAIM_STATUSES,
    PLACEMENT_MIN_SCORE,
    PLACEMENT_STATUSES,
    REMEDIES,
    TERMINAL_PLACEMENT,
    serialize,
    sort_by_sequence,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CANDIDATE,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import created_response, list_response, object_response
from services import calc, domain
from timeutil import add_days, format_date, parse_date
from validation import (
    apply_filters,
    body_of,
    check_date,
    check_enum,
    check_int,
    list_params,
    require_present,
    require_string,
)

bp = Blueprint("placements", __name__)

MONEY_COMPONENTS = (
    "base_salary_cents",
    "guaranteed_bonus_cents",
    "accommodation_imputed_cents",
    "overtime_allowance_cents",
)


@bp.post("/placements")
def create_placement():
    user_id, _role = authenticate({PLACEMENT_CONSULTANT})
    body = body_of(request)

    require_present(
        body, "requisition_id", "candidate_id", "start_date",
        *MONEY_COMPONENTS, "expected_requisition_version",
    )
    components = {name: check_int(body, name, minimum=0) for name in MONEY_COMPONENTS}
    start_date = check_date(body, "start_date")

    requisition = domain.resolve("requisitions", body["requisition_id"])
    candidate = domain.resolve("candidates", body["candidate_id"])

    pairing_trials = [
        t for t in domain.children("trial_engagements", "requisition_id", requisition["id"])
        if t["candidate_id"] == candidate["id"]
    ]
    if not pairing_trials:
        fail("ERR_ENTITY_RELATIONSHIP_MISMATCH")

    if body["expected_requisition_version"] != requisition["version"]:
        fail("ERR_STALE_REQUISITION_VERSION")

    if requisition["status"] not in ("TRIALING", "OFFER_PENDING"):
        fail("ERR_INVALID_STATE_TRANSITION")

    client = domain.resolve("clients", requisition["client_id"])
    domain.guard_client_not_suspended(client)

    if candidate["vetting_status"] != "CLEARED":
        fail("ERR_CANDIDATE_NOT_VETTED")

    incumbent = None
    for placement in domain.children("placements", "requisition_id", requisition["id"]):
        if placement["placement_status"] == "PENDING_ACCEPTANCE":
            incumbent = placement
            break

    availability = candidate["availability_status"]
    if availability == "ON_TRIAL":
        pass
    elif availability == "OFFER_HELD" and incumbent is not None and incumbent["candidate_id"] == candidate["id"]:
        pass
    else:
        fail("ERR_CANDIDATE_UNAVAILABLE")

    if candidate["placement_ready_score"] < PLACEMENT_MIN_SCORE:
        fail("ERR_CANDIDATE_SCORE_BELOW_THRESHOLD")

    if candidate["longest_contiguous_months"] < domain.chain_requirement(requisition["role_type"]):
        fail("ERR_REFERENCE_CHAIN_TOO_SHORT")

    if not any(t["status"] == "PASSED" for t in pairing_trials):
        fail("ERR_NO_PASSED_TRIAL")

    domain.guard_credit_hold(client)

    fee_percent_bps = requisition["fee_percent_bps"]
    guarantee_window_days = requisition["guarantee_window_days"]
    if fee_percent_bps is None or guarantee_window_days is None:
        fail("ERR_NO_FEE_SCHEDULE_MATCH")

    # The supersede path voids the incumbent offer first; the requisition does
    # not fall back to SOURCING because a fresh offer replaces it immediately.
    if incumbent is not None:
        domain.void_placement(
            incumbent,
            "SUPERSEDED_BY_NEW_OFFER",
            client,
            requisition,
            restore_candidate=True,
            requisition_fallback=False,
        )

    actual = sum(components[name] for name in MONEY_COMPONENTS)
    row = {
        "requisition_id": requisition["id"],
        "candidate_id": candidate["id"],
        "client_id": client["id"],
        "snapshot_fee_schedule_id": requisition["resolved_fee_schedule_id"],
        "start_date": body["start_date"],
        "base_salary_cents": components["base_salary_cents"],
        "guaranteed_bonus_cents": components["guaranteed_bonus_cents"],
        "accommodation_imputed_cents": components["accommodation_imputed_cents"],
        "overtime_allowance_cents": components["overtime_allowance_cents"],
        "actual_first_year_compensation_cents": actual,
        "fee_variant": "PROVISIONAL",
        "fee_percent_bps": fee_percent_bps,
        "fee_cents": calc.provisional_fee_cents(
            requisition["first_year_compensation_cents"], fee_percent_bps
        ),
        "guarantee_window_days": guarantee_window_days,
        "guarantee_expires_on": format_date(add_days(start_date, guarantee_window_days)),
        "placement_status": "PENDING_ACCEPTANCE",
        "billing_status": "UNBILLED",
        "separation_date": None,
        "void_reason": None,
        "created_by_user_id": user_id,
    }
    db.stamp_new(row)
    store.placements[row["id"]] = row

    domain.create_milestones(row)

    if candidate["availability_status"] != "OFFER_HELD":
        candidate["availability_status"] = "OFFER_HELD"
        touch(candidate)

    if requisition["status"] != "OFFER_PENDING":
        requisition["status"] = "OFFER_PENDING"
    touch(requisition)

    domain.recompute_client_derived(client)

    return created_response(serialize(row))


@bp.get("/placements/<placement_id>")
def get_placement(placement_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT, CANDIDATE,
    })
    row = domain.resolve("placements", placement_id)
    return object_response(serialize(row))


@bp.get("/placements")
def list_placements():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={
            "placement_status": PLACEMENT_STATUSES,
            "billing_status": BILLING_STATUSES,
        },
        plain_filters=("requisition_id", "candidate_id", "client_id", "snapshot_fee_schedule_id"),
    )
    rows = apply_filters(list(store.placements.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/placements/<placement_id>/confirm-start")
def confirm_start(placement_id):
    authenticate({AGENCY_PRINCIPAL})
    body_of(request)

    placement = domain.resolve("placements", placement_id)
    domain.guard_terminal(placement["placement_status"], TERMINAL_PLACEMENT)
    if placement["placement_status"] != "PENDING_ACCEPTANCE":
        fail("ERR_INVALID_STATE_TRANSITION")

    requisition = domain.resolve("requisitions", placement["requisition_id"])
    client = domain.resolve("clients", placement["client_id"])
    candidate = domain.resolve("candidates", placement["candidate_id"])

    # The band is re-resolved against the actual package before the
    # accommodation gate is examined (PRD 2.11 ranks 64 above 85).
    schedule = calc.resolve_fee_schedule(
        requisition["role_type"], placement["actual_first_year_compensation_cents"]
    )
    if schedule is None:
        fail("ERR_NO_FEE_SCHEDULE_MATCH")

    accepted = [
        t for t in domain.children("accommodation_terms", "requisition_id", requisition["id"])
        if t["candidate_id"] == placement["candidate_id"] and t["status"] == "ACCEPTED"
    ]
    if not accepted:
        fail("ERR_ACCOMMODATION_NOT_ACCEPTED")

    placement["snapshot_fee_schedule_id"] = schedule["id"]
    placement["fee_percent_bps"] = schedule["fee_percent_bps"]
    placement["guarantee_window_days"] = schedule["guarantee_window_days"]
    placement["fee_variant"] = "FINAL"
    placement["fee_cents"] = calc.final_fee_cents(placement, schedule["fee_percent_bps"])
    placement["guarantee_expires_on"] = format_date(
        add_days(parse_date(placement["start_date"]), schedule["guarantee_window_days"])
    )
    placement["placement_status"] = "ACTIVE"
    touch(placement)

    domain.reallocate_milestones(placement)

    if candidate["availability_status"] == "OFFER_HELD":
        candidate["availability_status"] = "PLACED"
        touch(candidate)

    if requisition["status"] == "OFFER_PENDING":
        requisition["status"] = "PLACED"
        touch(requisition)

    domain.recompute_client_derived(client)

    return object_response(serialize(placement))


@bp.post("/placements/<placement_id>/terminate")
def terminate_placement(placement_id):
    authenticate({PLACEMENT_CONSULTANT, CLIENT})
    body = body_of(request)

    require_present(body, "separation_date")
    require_string(body, "reason", 0, 100000, required=False)
    separation_date = check_date(body, "separation_date")

    placement = domain.resolve("placements", placement_id)
    domain.guard_terminal(placement["placement_status"], TERMINAL_PLACEMENT)
    if placement["placement_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_NOT_ACTIVE")

    start_date = parse_date(placement["start_date"])
    if separation_date < start_date or separation_date > store.today():
        fail("ERR_INVALID_SEPARATION_DATE")

    placement["placement_status"] = "TERMINATED_NO_REMEDY"
    placement["separation_date"] = body["separation_date"]
    touch(placement)

    candidate = store.candidates.get(placement["candidate_id"])
    if candidate is not None:
        domain.start_cooling_off(candidate)

    client = store.clients.get(placement["client_id"])
    if client is not None:
        domain.recompute_client_derived(client)

    return object_response(serialize(placement))


# ---------------------------------------------------------------------------
# Nested reads
# ---------------------------------------------------------------------------
@bp.get("/placements/<placement_id>/fee-milestones")
def list_placement_milestones(placement_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={"invoice_status": INVOICE_STATUSES, "milestone_type": MILESTONE_TYPES},
    )
    placement = domain.resolve("placements", placement_id)
    rows = apply_filters(domain.milestones_of(placement["id"]), filters)
    # Fee milestones are pinned to sequence_no ascending (PRD 2.3).
    data, total = domain.page(rows, limit, offset, ordered=sort_by_sequence(rows))
    return list_response(data, limit, offset, total)


@bp.get("/placements/<placement_id>/replacement-claims")
def list_placement_claims(placement_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": CLAIM_STATUSES, "requested_remedy": REMEDIES},
    )
    placement = domain.resolve("placements", placement_id)
    rows = apply_filters(domain.claims_of(placement["id"]), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.get("/placements/<placement_id>/payroll-handoffs")
def list_placement_handoffs(placement_id):
    authenticate({AGENCY_PRINCIPAL, BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT})
    limit, offset, filters = list_params(request, enum_filters={"status": HANDOFF_STATUSES})
    placement = domain.resolve("placements", placement_id)
    rows = apply_filters(domain.handoffs_of(placement["id"]), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Nested creates
# ---------------------------------------------------------------------------
@bp.post("/placements/<placement_id>/replacement-claims")
def create_replacement_claim(placement_id):
    authenticate({CLIENT, PLACEMENT_CONSULTANT})
    body = body_of(request)

    require_present(body, "requested_remedy", "separation_date", "narrative", "expected_placement_version")
    narrative = require_string(body, "narrative", 1, 2000)
    requested_remedy = check_enum(body, "requested_remedy", REMEDIES)
    separation_date = check_date(body, "separation_date")

    placement = domain.resolve("placements", placement_id)

    if body["expected_placement_version"] != placement["version"]:
        fail("ERR_STALE_PLACEMENT_VERSION")

    expires_on = parse_date(placement["guarantee_expires_on"]) if placement["guarantee_expires_on"] else None
    if placement["placement_status"] == "GUARANTEE_EXPIRED":
        fail("ERR_GUARANTEE_WINDOW_EXPIRED")
    if expires_on is not None and store.today() >= expires_on:
        fail("ERR_GUARANTEE_WINDOW_EXPIRED")

    start_date = parse_date(placement["start_date"])
    if separation_date < start_date or separation_date > store.today():
        fail("ERR_INVALID_SEPARATION_DATE")

    existing_claims = domain.claims_of(placement["id"])
    if any(c["status"] in OPEN_CLAIM_STATUSES for c in existing_claims):
        fail("ERR_OPEN_CLAIM_EXISTS")

    for claim in db.sort_rows(existing_claims):
        if claim["status"] == "DENIED":
            claim["status"] = "SUPERSEDED"
            touch(claim)

    row = {
        "placement_id": placement["id"],
        "requested_remedy": requested_remedy,
        "separation_date": body["separation_date"],
        "narrative": narrative,
        "status": "SUBMITTED",
        "info_request_round": 0,
        "elapsed_days": None,
        "unused_days": None,
        "gross_refund_cents": None,
        "retained_admin_fee_cents": None,
        "net_refund_cents": None,
        "decision_note": None,
    }
    db.stamp_new(row)
    store.replacement_claims[row["id"]] = row

    touch(placement)
    return created_response(serialize(row))


@bp.post("/placements/<placement_id>/payroll-handoffs")
def create_payroll_handoff(placement_id):
    authenticate({COMPLIANCE_OFFICER})
    body = body_of(request)

    provider_name = require_string(body, "provider_name", 1, 120)
    guidance_packet_version = require_string(body, "guidance_packet_version", 1, 32)
    ein_status = check_enum(body, "ein_status", db.EIN_STATUSES, required=False, default="NOT_APPLIED")

    placement = domain.resolve("placements", placement_id)

    if domain.handoffs_of(placement["id"]):
        fail("ERR_PAYROLL_HANDOFF_EXISTS")

    row = {
        "placement_id": placement["id"],
        "provider_name": provider_name,
        "ein_status": ein_status,
        "guidance_packet_version": guidance_packet_version,
        "status": "PREPARED",
        "attested_by_name": None,
        "attested_at": None,
    }
    db.stamp_new(row)
    store.payroll_handoffs[row["id"]] = row
    return created_response(serialize(row))
