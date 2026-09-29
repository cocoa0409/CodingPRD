"""The cumulative improvement ledger and determination cases."""

from flask import Blueprint

from db import db, iso, iso_now, now, plus_days, sort_rows, to_dt, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (as_bool, body, fk, lookup, opt_bool, opt_dt, opt_num,
                        opt_str, pagination, paginate, query_filters, req_dt,
                        req_enum, req_int, req_str)

bp = Blueprint("ledger", __name__)

_APPEAL_DECISIONS = ("SUSTAIN", "DENY")


# ------------------------------------------------------- ImprovementRecord


@bp.post("/improvement-records")
def create_record():
    require("FloodplainAdministrator")
    data = body()
    structure_id = fk(data, "structure_id", "structure")
    record_type = req_enum(data, "record_type", calc.RECORD_TYPES)
    is_reversal = record_type == "REVERSAL"
    # A reversal copies the target's event_date, so the field is optional there.
    event_date = opt_dt(data, "event_date") if is_reversal else req_dt(data, "event_date")
    cost = opt_num(data, "cost_usd", minimum=0)
    if not is_reversal and cost is None:
        fail("ERR_INVALID_REQUEST", "cost_usd is required for a non-reversal record.")
    claim_paid = opt_num(data, "claim_paid_amount_usd", default=calc.ZERO, minimum=0)
    code_only = opt_bool(data, "is_code_compliance_only", default=False)
    target_id = data.get("reverses_record_id")
    if target_id is not None and (not isinstance(target_id, str) or not target_id.strip()):
        fail("ERR_INVALID_REQUEST", "reverses_record_id must be a non-empty string.")

    structure = lookup("structure", structure_id)
    target = None
    if target_id is not None:
        target = lookup("record", target_id)

    if is_reversal:
        if target is None:
            fail("ERR_REVERSAL_TARGET_INVALID")
        if target["structure_id"] != structure_id:
            fail("ERR_REVERSAL_TARGET_INVALID")
    elif target is not None:
        fail("ERR_REVERSAL_TARGET_INVALID")

    if is_reversal:
        cost = target["cost_usd"]
        claim_paid = target["claim_paid_amount_usd"]
        event_date = to_dt(target["event_date"])
        code_only = False

    if event_date > now():
        fail("ERR_EVENT_DATE_IN_FUTURE")

    if is_reversal and target["reversed"]:
        fail("ERR_RECORD_ALREADY_REVERSED")

    source = "REVERSAL_ADJUSTMENT" if is_reversal else "ADMIN_ADJUSTMENT"
    row = engine.create_record(structure, record_type, source, event_date, cost,
                               claim_paid, is_code_compliance_only=code_only,
                               reverses_record_id=target["id"] if target else None)
    if is_reversal:
        row["counted_in_cumulative"] = False
        target["reversed"] = True

    engine.ledger_effects(structure, row, reversed_target=target if is_reversal else None)
    return object_response(row, 201)


@bp.get("/improvement-records/<record_id>")
def read_record(record_id):
    require(*ALL_ROLES)
    return object_response(lookup("record", record_id))


@bp.get("/improvement-records")
def list_records():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.records.values()), {
        "structure_id": ("structure_id", None),
        "permit_id": ("permit_id", None),
        "inspection_id": ("inspection_id", None),
        "reverses_record_id": ("reverses_record_id", None),
        "record_type": ("record_type", None),
        "counted_in_cumulative": ("counted_in_cumulative", as_bool),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ------------------------------------------------------- DeterminationCase


@bp.post("/determination-cases")
def create_case():
    require("FloodplainAdministrator")
    data = body()
    structure_id = fk(data, "structure_id", "structure")
    method = req_enum(data, "method", calc.METHODS)
    expected = req_int(data, "expected_structure_version")
    structure = lookup("structure", structure_id)

    if expected != structure["version"]:
        fail("ERR_STALE_STRUCTURE_VERSION")

    reverted = False
    prior = [c for c in engine.cases_of(structure_id)
             if c["status"] in ("OPEN", "DETERMINED")]
    for case in sort_rows(prior):
        was_determined = case["status"] == "DETERMINED"
        case["status"] = "WITHDRAWN"
        touch(case)
        if was_determined and structure["substantial_status"] != "NONE":
            structure["substantial_status"] = "NONE"
            reverted = True

    row = engine.new_case(structure, method, "ADMIN")
    touch(structure)
    if reverted:
        engine.recompute_permits_for_structure(structure)
    return object_response(row, 201)


@bp.get("/determination-cases/<case_id>")
def read_case(case_id):
    require(*ALL_ROLES)
    return object_response(lookup("case", case_id))


@bp.get("/determination-cases")
def list_cases():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.cases.values()), {
        "structure_id": ("structure_id", None),
        "anchor_record_id": ("anchor_record_id", None),
        "status": ("status", None),
        "method": ("method", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/determination-cases/<case_id>/determine")
def determine_case(case_id):
    user_id, _role = require("FloodplainAdministrator")
    case = lookup("case", case_id)
    if case["status"] != "OPEN":
        fail("ERR_DETERMINATION_NOT_OPEN")

    structure = db.structures.get(case["structure_id"])
    if case["anchor_record_id"] is None or structure is None:
        ratio = calc.r2(0)
    elif case["method"] == "SINGLE_EVENT":
        ratio = structure["single_event_improvement_pct"]
    else:
        ratio = structure["cumulative_improvement_pct"]

    case["computed_ratio_pct"] = calc.r2(ratio)
    case["threshold_pct"] = calc.r2(calc.SI_THRESHOLD_PCT)
    substantial = calc.dec(ratio) >= calc.dec(case["threshold_pct"])
    case["outcome"] = "SUBSTANTIAL" if substantial else "NOT_SUBSTANTIAL"
    case["status"] = "DETERMINED"
    case["determined_by_user_id"] = user_id
    case["determined_at"] = iso_now()
    case["appeal_deadline_at"] = iso(plus_days(now(), calc.APPEAL_WINDOW_DAYS))
    touch(case)

    if structure is not None:
        engine.set_substantial_status(
            structure, case["determination_type"] if substantial else "NONE")
    return object_response(case)


@bp.post("/determination-cases/<case_id>/appeal")
def appeal_case(case_id):
    user_id, role = require("PropertyOwner")
    case = lookup("case", case_id)
    structure = db.structures.get(case["structure_id"])
    if role == "PropertyOwner" and structure is not None and user_id != structure["property_id"]:
        fail("ERR_NOT_PROPERTY_OWNER")

    data = body()
    req_str(data, "appeal_basis")

    if case["status"] != "DETERMINED":
        fail("ERR_DETERMINATION_NOT_DETERMINED")
    deadline = case["appeal_deadline_at"]
    if deadline is not None and now() > to_dt(deadline):
        fail("ERR_APPEAL_WINDOW_CLOSED")

    case["status"] = "APPEALED"
    case["appealed_at"] = iso_now()
    touch(case)
    return object_response(case)


@bp.post("/determination-cases/<case_id>/appeal-decision")
def decide_appeal(case_id):
    user_id, _role = require("AppealsBoardMember")
    case = lookup("case", case_id)
    data = body()
    decision = req_enum(data, "decision", _APPEAL_DECISIONS)
    opt_str(data, "decision_note")

    if case["status"] != "APPEALED":
        fail("ERR_APPEAL_NOT_PENDING")
    if case["determined_by_user_id"] is not None and user_id == case["determined_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    case["appeal_decided_by_user_id"] = user_id
    if decision == "SUSTAIN":
        case["status"] = "APPEAL_SUSTAINED"
        case["outcome"] = "NOT_SUBSTANTIAL"
        touch(case)
        structure = db.structures.get(case["structure_id"])
        if structure is not None:
            engine.set_substantial_status(structure, "NONE")
    else:
        case["status"] = "APPEAL_DENIED"
        touch(case)
    return object_response(case)
