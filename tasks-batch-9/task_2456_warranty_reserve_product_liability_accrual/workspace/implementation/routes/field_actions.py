"""FieldAction and RemedyOption endpoints (two independent state dimensions)."""

from datetime import timedelta

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import (
    Field,
    no_body,
    paginate,
    pagination,
    parse_date,
    query_filter,
    validate_body,
)

bp = Blueprint("field_actions", __name__)

READ_ROLES = ("QualityEngineer", "ReserveController", "WarrantyAnalyst", "Actuary")
ACTION_TYPES = ("SERVICE_CAMPAIGN", "SAFETY_RECALL", "FIELD_BULLETIN")
REMEDY_CLASSES = ("PERMANENT_REPAIR", "INTERIM_REPAIR", "PART_REPLACEMENT", "BUYBACK")
EXECUTION_STATES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETED")
DECISIONS = ("APPROVED", "REJECTED")

BUFFER = timedelta(days=calc.FIELD_ACTION_QUIET_BUFFER_DAYS)


@bp.post("/warranty/field-actions")
def create_field_action():
    authenticate(("QualityEngineer",))
    values, _ = validate_body(
        [
            Field("family_id", "id"),
            Field("action_code", "str"),
            Field("action_type", "enum", enum=ACTION_TYPES),
            Field("affected_build_start_date", "date"),
            Field("affected_build_end_date", "date"),
            Field("affected_unit_count", "int", minimum=1),
            Field("regulatory_notice_filed", "bool", required=False, default=False),
        ]
    )
    if values["affected_build_end_date"] < values["affected_build_start_date"]:
        fail(
            "ERR_INVALID_REQUEST",
            "affected_build_end_date must not precede affected_build_start_date.",
        )
    lookups.require_family(values["family_id"])
    if any(a["action_code"] == values["action_code"] for a in store.all_rows("field_actions")):
        fail("ERR_DUPLICATE_CODE")

    new_start = parse_date(values["affected_build_start_date"])
    new_end = parse_date(values["affected_build_end_date"])
    for existing in store.all_rows("field_actions"):
        if existing["family_id"] != values["family_id"]:
            continue
        if existing["approval_state"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
            continue
        existing_start = parse_date(existing["affected_build_start_date"])
        existing_end = parse_date(existing["affected_build_end_date"])
        # CLOSED interval geometry with a 30-day quiet buffer on both sides of the
        # EXISTING window; adjacency and any gap of 30 days or less conflict.
        if new_start <= existing_end + BUFFER and existing_start - BUFFER <= new_end:
            fail("ERR_FIELD_ACTION_WINDOW_CONFLICT")

    row = store.insert(
        "field_actions",
        {
            "_kind": "FieldAction",
            "family_id": values["family_id"],
            "action_code": values["action_code"],
            "action_type": values["action_type"],
            "is_safety_recall": values["action_type"] == "SAFETY_RECALL",
            "affected_build_start_date": values["affected_build_start_date"],
            "affected_build_end_date": values["affected_build_end_date"],
            "affected_unit_count": values["affected_unit_count"],
            "regulatory_notice_filed": bool(values["regulatory_notice_filed"]),
            "selected_remedy_option_id": None,
            "specific_accrual_cents": 0,
            "executed_cost_cents": 0,
            "approval_state": "DRAFT",
            "execution_state": "NOT_STARTED",
            "approved_period_id": None,
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
        },
    )
    return object_response(dump(row), 201)


@bp.get("/warranty/field-actions/<field_action_id>")
def read_field_action(field_action_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require_field_action(field_action_id)))


@bp.get("/warranty/field-actions")
def list_field_actions():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("field_actions")
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    option_id = query_filter("selected_remedy_option_id")
    if option_id is not None:
        rows = [r for r in rows if r["selected_remedy_option_id"] == option_id]
    approved_period_id = query_filter("approved_period_id")
    if approved_period_id is not None:
        rows = [r for r in rows if r["approved_period_id"] == approved_period_id]
    approval_state = query_filter("approval_state")
    if approval_state is not None:
        rows = [r for r in rows if r["approval_state"] == approval_state]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# RemedyOption
# ---------------------------------------------------------------------------
@bp.post("/warranty/field-actions/<field_action_id>/remedy-options")
def create_remedy_option(field_action_id):
    authenticate(("QualityEngineer",))
    action = lookups.require_field_action(field_action_id)
    values, _ = validate_body(
        [
            Field("option_code", "str"),
            Field("remedy_class", "enum", enum=REMEDY_CLASSES),
            Field("parts_cost_cents", "int", minimum=0),
            Field("labor_hours_centi", "int", minimum=0),
            Field("admin_cost_cents", "int", minimum=0),
            Field("expected_take_rate_bps", "int", minimum=0, maximum=10000),
            Field("is_engineering_approved", "bool", required=False, default=False),
        ]
    )
    for existing in calc.remedy_options_of_action(action["id"]):
        if existing["option_code"] == values["option_code"]:
            fail("ERR_DUPLICATE_CODE")

    row = store.insert(
        "remedy_options",
        {
            "_kind": "RemedyOption",
            "field_action_id": field_action_id,
            "option_code": values["option_code"],
            "remedy_class": values["remedy_class"],
            "parts_cost_cents": values["parts_cost_cents"],
            "labor_hours_centi": values["labor_hours_centi"],
            "admin_cost_cents": values["admin_cost_cents"],
            "expected_take_rate_bps": values["expected_take_rate_bps"],
            "is_engineering_approved": bool(values["is_engineering_approved"]),
            "per_unit_expected_cents": 0,
        },
    )
    row["per_unit_expected_cents"] = calc.option_per_unit_expected_cents(row)
    return object_response(dump(row), 201)


@bp.get("/warranty/field-actions/<field_action_id>/remedy-options")
def list_remedy_options(field_action_id):
    authenticate(READ_ROLES)
    action = lookups.require_field_action(field_action_id)
    limit, offset = pagination()
    rows = calc.remedy_options_of_action(action["id"])
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/field-actions/<field_action_id>/select-remedy")
def select_remedy(field_action_id):
    authenticate(("QualityEngineer",))
    action = lookups.require_field_action(field_action_id)
    values, present = validate_body(
        [
            Field("expected_field_action_version", "int"),
            Field("remedy_option_id", "id", required=False, nullable=True),
        ]
    )
    explicit = values["remedy_option_id"] if "remedy_option_id" in present else None
    if explicit is not None:
        candidate = store.get("remedy_options", explicit)
        if candidate is None:
            fail("ERR_REMEDY_OPTION_NOT_FOUND")
    else:
        candidate = None

    if values["expected_field_action_version"] != action["version"]:
        fail("ERR_STALE_FIELD_ACTION_VERSION")
    if action["approval_state"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    if candidate is not None:
        # Rung 17 answers before rung 20 when a candidate violates both.
        if action["is_safety_recall"] and candidate["remedy_class"] != "PERMANENT_REPAIR":
            fail("ERR_SAFETY_REMEDY_REQUIRED")
        if candidate["field_action_id"] != action["id"]:
            fail("ERR_REMEDY_OPTION_MISMATCH")
        selected = candidate
    else:
        selected = calc.select_cheapest_eligible_option(action)
        if selected is None:
            # Nothing is mutated and version is NOT incremented.
            fail("ERR_NO_ELIGIBLE_REMEDY_OPTION")

    action["selected_remedy_option_id"] = selected["id"]
    if calc.apply_specific_accrual(action, selected):
        store.touch(selected)
    if action["approval_state"] == "REJECTED":
        action["approval_state"] = "DRAFT"
        action["submitted_by_user_id"] = None
        action["decided_by_user_id"] = None
    store.touch(action)
    return object_response(dump(action))


@bp.post("/warranty/field-actions/<field_action_id>/submit")
def submit_field_action(field_action_id):
    user_id, _ = authenticate(("QualityEngineer",))
    action = lookups.require_field_action(field_action_id)
    no_body()
    if action["approval_state"] != "DRAFT" or action["selected_remedy_option_id"] is None:
        fail("ERR_INVALID_STATE_TRANSITION")
    if action["is_safety_recall"]:
        option = store.get("remedy_options", action["selected_remedy_option_id"])
        if option is None or option["remedy_class"] != "PERMANENT_REPAIR":
            fail("ERR_SAFETY_REMEDY_REQUIRED")

    action["approval_state"] = "SUBMITTED"
    action["submitted_by_user_id"] = user_id
    store.touch(action)
    return object_response(dump(action))


@bp.post("/warranty/field-actions/<field_action_id>/decision")
def decide_field_action(field_action_id):
    user_id, _ = authenticate(("ReserveController",))
    action = lookups.require_field_action(field_action_id)
    values, _ = validate_body([Field("decision", "enum", enum=DECISIONS)])
    decision = values["decision"]

    if action["approval_state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if decision == "APPROVED" and action["is_safety_recall"]:
        if not action["regulatory_notice_filed"]:
            fail("ERR_REGULATORY_NOTICE_MISSING")
    if user_id == action["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    period = None
    if decision == "APPROVED":
        period = calc.booking_period()
        if period is None:
            fail("ERR_NO_OPEN_PERIOD")

    if decision == "REJECTED":
        action["approval_state"] = "REJECTED"
        action["decided_by_user_id"] = user_id
        action["specific_accrual_cents"] = 0
        store.touch(action)
        return object_response(dump(action))

    # HOP 1
    action["approval_state"] = "APPROVED"
    action["decided_by_user_id"] = user_id
    action["approved_period_id"] = period["id"]
    option = store.get("remedy_options", action["selected_remedy_option_id"])
    if option is not None:
        if calc.apply_specific_accrual(action, option):
            store.touch(option)
    store.touch(action)

    # HOP 2 and HOP 3
    family = store.get("families", action["family_id"])
    if family is not None:
        if calc.apply_balance_and_posture(family):
            store.touch(family)
        # HOP 4 — single pass, created_at ASC, never iterated to a fixed point.
        if family["reserve_posture"] == "CONSTRAINED":
            vintage_ids = calc.vintage_ids_of_family(family["id"])
            for accrual in store.all_rows("accruals"):
                if accrual["vintage_id"] not in vintage_ids:
                    continue
                if accrual["status"] != "PROPOSED":
                    continue
                accrual["status"] = "DRAFT"
                accrual["revision_index"] += 1
                accrual["proposed_by_user_id"] = None
                store.touch(accrual)
    return object_response(dump(action))


@bp.post("/warranty/field-actions/<field_action_id>/execution-progress")
def execution_progress(field_action_id):
    authenticate(("QualityEngineer",))
    action = lookups.require_field_action(field_action_id)
    values, _ = validate_body(
        [
            Field("to_execution_state", "enum", enum=EXECUTION_STATES),
            Field("incurred_cost_cents", "int", required=False, minimum=0, default=0),
        ]
    )
    target = values["to_execution_state"]
    current = action["execution_state"]
    declared = (current == "NOT_STARTED" and target == "IN_PROGRESS") or (
        current == "IN_PROGRESS" and target == "COMPLETED"
    )
    if not declared:
        fail("ERR_INVALID_STATE_TRANSITION")
    if current == "NOT_STARTED" and action["approval_state"] != "APPROVED":
        fail("ERR_EXECUTION_BEFORE_APPROVAL")

    action["execution_state"] = target
    action["executed_cost_cents"] += values["incurred_cost_cents"] or 0
    store.touch(action)
    if target == "COMPLETED":
        family = store.get("families", action["family_id"])
        if family is not None and calc.apply_balance_and_posture(family):
            store.touch(family)
    return object_response(dump(action))
