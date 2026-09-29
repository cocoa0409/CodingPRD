"""Claim intake, the documentation cycle, bench assessments and adjudication."""

from flask import Blueprint

import calc
import services as svc
from core import (
    db, fail, get_body, iso, new_row, now, ordered, page, pagination, q_bool,
    q_str, require, respond, respond_list, set_fields, v_enum, v_int, v_string,
)

bp = Blueprint("claims", __name__)

CLAIM_STATES = (
    "DRAFT", "SUBMITTED", "INFO_REQUESTED", "UNDER_ASSESSMENT", "WARRANTY_APPROVED",
    "REPLACEMENT_AUTHORIZED", "PAID_REPAIR_OFFERED", "WEAR_DENIED", "CLOSED_FULFILLED",
    "CLOSED_REPLACED", "CLOSED_DECLINED",
)
DECISIONS = ("WARRANTY_REPAIR", "WARRANTY_REPLACE", "PAID_REPAIR_OFFERED", "WEAR_DENIED")
INTAKE_KINDS = ("WARRANTY_CLAIM", "PAID_REPAIR_REQUEST")
WARRANTY_OUTCOMES = ("WARRANTY_REPAIR", "WARRANTY_REPLACE")


# --------------------------------------------------------------------------- #
# Intake
# --------------------------------------------------------------------------- #

@bp.post("/warranty-claims")
def create_claim():
    ctx = require("Customer", "ServiceAgent")
    body = get_body()

    # check 5 -- a Customer may only file against their own unit
    if ctx.is_customer:
        candidate = body.get("gear_item_id")
        if isinstance(candidate, str) and candidate in db.gear_items:
            svc.guard_owner(ctx, db.gear_items[candidate])

    # check 7 -- body references resolve
    center = svc.fk(body, "service_center_id", db.service_centers, "ERR_SERVICE_CENTER_NOT_FOUND")
    item = svc.fk(body, "gear_item_id", db.gear_items, "ERR_GEAR_ITEM_NOT_FOUND")

    # check 9 -- shape
    if center is None:
        fail("ERR_INVALID_REQUEST", "Field 'service_center_id' is required.")
    if item is None:
        fail("ERR_INVALID_REQUEST", "Field 'gear_item_id' is required.")
    intake_kind = v_enum(body, "intake_kind", INTAKE_KINDS, default="WARRANTY_CLAIM")
    defect_type = v_enum(body, "reported_defect_type", calc.DEFECT_TYPES, required=True)
    narrative = v_string(body, "customer_narrative", min_len=1, max_len=2000)

    row = new_row()
    row.update({
        "service_center_id": center["id"],
        "gear_item_id": item["id"],
        "intake_kind": intake_kind,
        "reported_defect_type": defect_type,
        "customer_narrative": narrative,
        "status": "DRAFT",
        "proof_verified": svc.proof_verified(item),
        "submitted_at": None,
        "info_request_count": 0,
        "assessment_count": 0,
        "latest_determination": None,
        "latest_repair_cost_cents": None,
        "decision": None,
        "decision_threshold_pct": None,
        "repair_ratio_pct": None,
        "decision_by_role": None,
        "decided_at": None,
    })
    db.warranty_claims[row["id"]] = row
    return respond(svc.ser(row), 201)


@bp.get("/warranty-claims/<claim_id>")
def read_claim(claim_id):
    ctx = require("Customer", "ServiceAgent", "RepairTechnician", "ProgramAdmin")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_claim(claim))
    return respond(svc.ser(claim))


@bp.get("/warranty-claims")
def list_claims():
    require("Customer", "ServiceAgent", "RepairTechnician", "ProgramAdmin")
    center_id = q_str("service_center_id")
    item_id = q_str("gear_item_id")
    status = q_str("status")
    if status is not None and status not in CLAIM_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    decision = q_str("decision")
    if decision is not None and decision not in DECISIONS:
        fail("ERR_INVALID_REQUEST", "Query parameter 'decision' is not a recognised value.")
    intake_kind = q_str("intake_kind")
    if intake_kind is not None and intake_kind not in INTAKE_KINDS:
        fail("ERR_INVALID_REQUEST", "Query parameter 'intake_kind' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for claim in ordered(db.warranty_claims):
        if center_id is not None and claim["service_center_id"] != center_id:
            continue
        if item_id is not None and claim["gear_item_id"] != item_id:
            continue
        if status is not None and claim["status"] != status:
            continue
        if decision is not None and claim["decision"] != decision:
            continue
        if intake_kind is not None and claim["intake_kind"] != intake_kind:
            continue
        rows.append(claim)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


# --------------------------------------------------------------------------- #
# Documentation cycle
# --------------------------------------------------------------------------- #

@bp.post("/warranty-claims/<claim_id>/submit")
def submit_claim(claim_id):
    ctx = require("Customer", "ServiceAgent")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    item = svc.item_behind_claim(claim)
    svc.guard_owner(ctx, item)
    get_body()

    # check 11
    if claim["status"] != "DRAFT":
        fail("ERR_INVALID_CLAIM_STATE")
    # check 17 -- the unit itself must not be terminal
    if item is not None and item["disposition_status"] in calc.ITEM_TERMINAL:
        fail("ERR_ALREADY_TERMINAL")

    warranty_intake = claim["intake_kind"] == "WARRANTY_CLAIM"
    svc.refresh_item(item)
    # check 31
    if warranty_intake and item["warranty_state"] == "EXPIRED":
        fail("ERR_WARRANTY_EXPIRED")
    # check 36
    verified = svc.proof_verified(item)
    if warranty_intake and not verified:
        fail("ERR_PROOF_OF_PURCHASE_MISSING")

    set_fields(
        claim,
        status="SUBMITTED",
        submitted_at=iso(now()),
        proof_verified=verified,
    )
    if item["disposition_status"] == "WITH_CUSTOMER":
        set_fields(item, disposition_status="AT_CENTER")
    owner = svc.owner_of_item(item)
    if owner is not None:
        set_fields(owner, lifetime_claim_count=owner["lifetime_claim_count"] + 1)

    return respond(svc.ser(claim))


@bp.post("/warranty-claims/<claim_id>/info-requests")
def request_info(claim_id):
    require("ServiceAgent")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    v_string(body, "reason", required=True, min_len=1, max_len=2000)

    # check 11
    if claim["status"] not in ("SUBMITTED", "UNDER_ASSESSMENT"):
        fail("ERR_INVALID_CLAIM_STATE")
    # check 37
    if claim["info_request_count"] >= calc.MAX_INFO_REQUESTS:
        fail("ERR_INFO_REQUEST_LIMIT")

    set_fields(
        claim,
        status="INFO_REQUESTED",
        info_request_count=claim["info_request_count"] + 1,
    )
    return respond(svc.ser(claim))


@bp.post("/warranty-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    ctx = require("Customer", "ServiceAgent")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    item = svc.item_behind_claim(claim)
    svc.guard_owner(ctx, item)
    body = get_body()
    proof_type = v_enum(body, "proof_of_purchase_type", calc.PROOF_TYPES)
    proof_ref = v_string(body, "proof_of_purchase_ref", max_len=200)
    narrative = v_string(body, "customer_narrative", min_len=1, max_len=2000)

    # check 11
    if claim["status"] != "INFO_REQUESTED":
        fail("ERR_INVALID_CLAIM_STATE")

    if item is not None and (proof_type is not None or proof_ref is not None):
        updates = {}
        if proof_type is not None:
            updates["proof_of_purchase_type"] = proof_type
        if proof_ref is not None:
            updates["proof_of_purchase_ref"] = proof_ref
        if updates.get("proof_of_purchase_type") == "NONE":
            updates["proof_of_purchase_ref"] = None
        set_fields(item, **updates)

    claim_updates = {
        "status": "SUBMITTED",
        "submitted_at": iso(now()),
        "proof_verified": svc.proof_verified(item) if item is not None else False,
    }
    if narrative is not None:
        claim_updates["customer_narrative"] = narrative
    set_fields(claim, **claim_updates)
    return respond(svc.ser(claim))


# --------------------------------------------------------------------------- #
# Bench assessments
# --------------------------------------------------------------------------- #

def _validate_work_types(raw):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'required_work_types' must be a non-empty array.")
    seen = []
    for value in raw:
        if value not in calc.WORK_TYPES:
            fail("ERR_INVALID_REQUEST", "Field 'required_work_types' holds an unknown work type.")
        if value in seen:
            fail("ERR_INVALID_REQUEST", "Field 'required_work_types' must not repeat a value.")
        seen.append(value)
    return seen


def _validate_estimated_labor_lines(raw, required_work_types):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'estimated_labor_lines' must be a non-empty array.")
    lines = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each labour line must be an object.")
        work_type = entry.get("work_type")
        minutes = entry.get("minutes")
        if work_type not in calc.WORK_TYPES:
            fail("ERR_INVALID_REQUEST", "Labour line 'work_type' is not recognised.")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1 or minutes > 600:
            fail("ERR_INVALID_REQUEST", "Labour line 'minutes' must be an integer 1..600.")
        if work_type in seen:
            fail("ERR_INVALID_REQUEST", "Exactly one labour line per work type is allowed.")
        seen.add(work_type)
        lines.append({"work_type": work_type, "minutes": minutes})
    if seen != set(required_work_types):
        fail(
            "ERR_INVALID_REQUEST",
            "The labour lines must cover exactly the required work types.",
        )
    return lines


@bp.post("/warranty-claims/<claim_id>/assessments")
def create_assessment(claim_id):
    ctx = require("RepairTechnician")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()

    # check 9 -- shape
    expected_version = v_int(body, "expected_claim_version", required=True, min_value=1)
    determination = v_enum(body, "determination", calc.DETERMINATIONS, required=True)
    notes = v_string(body, "defect_notes", min_len=1, max_len=2000)
    if "required_work_types" not in body or body["required_work_types"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'required_work_types' is required.")
    required_work_types = _validate_work_types(body["required_work_types"])
    if "estimated_labor_lines" not in body or body["estimated_labor_lines"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'estimated_labor_lines' is required.")
    labor_lines = _validate_estimated_labor_lines(
        body["estimated_labor_lines"], required_work_types
    )
    parts_cents = v_int(body, "estimated_parts_cents", required=True, min_value=0)

    # check 11
    if claim["status"] not in ("SUBMITTED", "UNDER_ASSESSMENT"):
        fail("ERR_INVALID_CLAIM_STATE")
    # check 18 -- optimistic concurrency on the claim
    if expected_version != claim["version"]:
        fail("ERR_STALE_CLAIM_VERSION")
    # check 20
    technician = ctx.actor
    if technician["status"] != "ACTIVE":
        fail("ERR_TECHNICIAN_NOT_ACTIVE")
    # check 21 -- certified for every required lane
    for work_type in required_work_types:
        level = svc.cert_level(technician, work_type)
        if level is None or level < calc.WORK_TYPE_MIN_LEVEL[work_type]:
            fail("ERR_TECHNICIAN_NOT_CERTIFIED")
    # check 25
    if technician["service_center_id"] != claim["service_center_id"]:
        fail("ERR_TECHNICIAN_CENTER_MISMATCH")

    cost = calc.assessment_repair_cost(labor_lines, parts_cents)

    for earlier in svc.claim_assessments_of(claim["id"]):
        if not earlier["is_superseded"]:
            earlier["is_superseded"] = True

    row = new_row(common=False)
    row.update({
        "warranty_claim_id": claim["id"],
        "assessor_technician_id": technician["id"],
        "determination": determination,
        "defect_notes": notes,
        "required_work_types": required_work_types,
        "estimated_labor_lines": labor_lines,
        "estimated_parts_cents": parts_cents,
        "estimated_repair_cost_cents": cost,
        "is_superseded": False,
    })
    db.claim_assessments[row["id"]] = row

    set_fields(
        claim,
        status="UNDER_ASSESSMENT",
        assessment_count=claim["assessment_count"] + 1,
        latest_determination=determination,
        latest_repair_cost_cents=cost,
    )
    return respond(svc.ser(row), 201)


@bp.get("/claim-assessments/<assessment_id>")
def read_assessment(assessment_id):
    require("ServiceAgent", "RepairTechnician", "ProgramAdmin")
    assessment = svc.need(db.claim_assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    return respond(svc.ser(assessment))


@bp.get("/claim-assessments")
def list_assessments():
    require("ServiceAgent", "RepairTechnician", "ProgramAdmin")
    claim_id = q_str("warranty_claim_id")
    technician_id = q_str("assessor_technician_id")
    determination = q_str("determination")
    if determination is not None and determination not in calc.DETERMINATIONS:
        fail("ERR_INVALID_REQUEST", "Query parameter 'determination' is not a recognised value.")
    superseded = q_bool("is_superseded")
    limit, offset = pagination()

    rows = []
    for assessment in ordered(db.claim_assessments):
        if claim_id is not None and assessment["warranty_claim_id"] != claim_id:
            continue
        if technician_id is not None and assessment["assessor_technician_id"] != technician_id:
            continue
        if determination is not None and assessment["determination"] != determination:
            continue
        if superseded is not None and assessment["is_superseded"] != superseded:
            continue
        rows.append(assessment)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


# --------------------------------------------------------------------------- #
# Adjudication
# --------------------------------------------------------------------------- #

@bp.post("/warranty-claims/<claim_id>/decision")
def adjudicate(claim_id):
    ctx = require("ServiceAgent", "ProgramAdmin")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    v_string(body, "decision_note", min_len=1, max_len=2000)

    # check 11
    if claim["status"] != "UNDER_ASSESSMENT":
        fail("ERR_INVALID_CLAIM_STATE")

    item = svc.item_behind_claim(claim)
    svc.refresh_item(item)
    model = svc.model_of_item(item)
    center = svc.center_of(claim)
    live = svc.live_assessment(claim)
    determination = live["determination"] if live is not None else "INCONCLUSIVE"

    threshold = calc.decision_threshold_pct(model, item["age_months"])
    ratio = calc.repair_ratio_pct(
        claim["latest_repair_cost_cents"] or 0, item["replacement_value_successor_cents"]
    )
    outcome = calc.adjudicate(
        determination, item["warranty_state"], model["parts_support_status"], ratio, threshold
    )

    # check 23 -- a frozen centre refuses both warranty outcomes
    if outcome in WARRANTY_OUTCOMES and center["liability_posture"] == "FROZEN":
        fail("ERR_CENTER_LIABILITY_FROZEN")
    # check 24 -- a constrained centre needs an admin for a replacement
    if (
        outcome == "WARRANTY_REPLACE"
        and center["liability_posture"] == "CONSTRAINED"
        and ctx.role != "ProgramAdmin"
    ):
        fail("ERR_REPLACEMENT_REQUIRES_OVERRIDE")
    # check 38
    if outcome is None:
        fail("ERR_ASSESSMENT_INCONCLUSIVE")

    status_by_outcome = {
        "WARRANTY_REPAIR": "WARRANTY_APPROVED",
        "WARRANTY_REPLACE": "REPLACEMENT_AUTHORIZED",
        "PAID_REPAIR_OFFERED": "PAID_REPAIR_OFFERED",
        "WEAR_DENIED": "WEAR_DENIED",
    }
    set_fields(
        claim,
        status=status_by_outcome[outcome],
        decision=outcome,
        decision_threshold_pct=threshold,
        repair_ratio_pct=ratio,
        decision_by_role=ctx.role,
        decided_at=iso(now()),
    )

    if outcome == "WARRANTY_REPAIR":
        amount = min(
            claim["latest_repair_cost_cents"] or 0,
            item["replacement_value_depreciated_cents"],
        )
        svc.open_liability_entry(claim, "REPAIR", "DEPRECIATED_PURCHASE", amount)
        svc.recompute_center_liability(center)
        svc.bump_model_counter(model, "defect_claim_count")
    elif outcome == "WARRANTY_REPLACE":
        svc.open_liability_entry(
            claim, "REPLACEMENT", "SUCCESSOR_MSRP",
            item["replacement_value_successor_cents"],
        )
        svc.recompute_center_liability(center)
        set_fields(item, disposition_status="IRREPARABLE_HOLD")
        svc.bump_model_counter(model, "defect_claim_count")
    elif outcome == "WEAR_DENIED":
        svc.bump_model_counter(model, "wear_denial_count")

    return respond(svc.ser(claim))


@bp.get("/warranty-claims/<claim_id>/liability-entries")
def list_liability_entries(claim_id):
    require("ServiceAgent", "ProgramAdmin")
    claim = svc.need(db.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    status = q_str("status")
    if status is not None and status not in ("OPEN", "RELEASED"):
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    basis = q_str("basis")
    if basis is not None and basis not in ("REPAIR", "REPLACEMENT"):
        fail("ERR_INVALID_REQUEST", "Query parameter 'basis' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for entry in svc.claim_liability_entries(claim["id"]):
        if status is not None and entry["status"] != status:
            continue
        if basis is not None and entry["basis"] != basis:
            continue
        rows.append(entry)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)
