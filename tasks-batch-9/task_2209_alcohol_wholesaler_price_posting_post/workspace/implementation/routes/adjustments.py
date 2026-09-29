"""Competitive hold amendments and clerical error corrections (PRD section 3.6)."""

from flask import Blueprint

import calc
import services
from auth import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FILING_AGENT,
    authenticate,
    require_scope,
)
from envelope import object_response
from errors import raise_err
from serialize import out
from store import bump, db, new_record, now_dt
from validators import Field, collection_response, must_find, validate_body

bp = Blueprint("adjustments", __name__)

AMENDMENT_STATUSES = ("PENDING", "ACCEPTED", "REJECTED", "REVOKED")
CORRECTION_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")

FRIVOLOUS_PENALTY_THRESHOLD = 3
REPEAT_CORRECTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# hold amendments
# ---------------------------------------------------------------------------
@bp.post("/hold-amendments")
def create_hold_amendment():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("amending_item_id", "string"),
            Field("reference_item_id", "string"),
            Field("new_case_price_cents", "int", minimum=1),
            Field("new_unit_price_cents", "int", minimum=1),
            Field("expected_schedule_version", "int"),
        ]
    )
    amending_item = must_find("price_schedule_item", values["amending_item_id"])
    reference_item = must_find("price_schedule_item", values["reference_item_id"])
    amending_schedule = services.schedule_of_item(amending_item)
    require_scope(actor, amending_schedule["wholesaler_id"])

    # Priority 7 -- optimistic concurrency on the amending item's schedule.
    if values["expected_schedule_version"] != amending_schedule["version"]:
        raise_err("ERR_STALE_SCHEDULE_VERSION")

    # Priority 8 -- only a posted item may be amended.
    if amending_item["status"] != "POSTED":
        raise_err("ERR_INVALID_STATE")

    # Priority 11 -- the reference must belong to a competitor.
    reference_schedule = services.schedule_of_item(reference_item)
    if reference_schedule["wholesaler_id"] == amending_schedule["wholesaler_id"]:
        raise_err("ERR_SELF_REFERENCE_NOT_ALLOWED")

    # Priority 12 -- the post-and-hold window must still be open.
    if not calc.hold_window_is_open(amending_schedule, now_dt()):
        raise_err("ERR_HOLD_WINDOW_CLOSED")

    # Priority 17 -- the reduction test precedes the reference test.
    if not calc.is_reduction(
        values["new_case_price_cents"], amending_item["case_price_cents"]
    ):
        raise_err("ERR_AMENDMENT_NOT_A_REDUCTION")
    if not calc.is_at_or_above_reference(
        values["new_case_price_cents"], reference_item["case_price_cents"]
    ):
        raise_err("ERR_AMENDMENT_BELOW_REFERENCE")

    record = new_record(
        {
            "amending_item_id": amending_item["id"],
            "reference_item_id": reference_item["id"],
            "new_case_price_cents": values["new_case_price_cents"],
            "new_unit_price_cents": values["new_unit_price_cents"],
            "status": "PENDING",
            "prior_case_price_cents": None,
            "prior_unit_price_cents": None,
            "rejection_reason": None,
            "revocation_reason": None,
        }
    )
    db.hold_amendments[record["id"]] = record
    bump(amending_schedule)
    return object_response(out(record), 201)


@bp.post("/hold-amendments/<record_id>/accept")
def accept_hold_amendment(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    amendment = must_find("hold_amendment", record_id)
    if amendment["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE")

    item = db.price_schedule_items[amendment["amending_item_id"]]
    schedule = services.schedule_of_item(item)

    # Priority 12 -- the window is re-tested at adjudication time.
    if not calc.hold_window_is_open(schedule, now_dt()):
        raise_err("ERR_HOLD_WINDOW_CLOSED")

    amendment["prior_case_price_cents"] = item["case_price_cents"]
    amendment["prior_unit_price_cents"] = item["unit_price_cents"]
    amendment["status"] = "ACCEPTED"
    bump(amendment)

    item["case_price_cents"] = amendment["new_case_price_cents"]
    item["unit_price_cents"] = amendment["new_unit_price_cents"]
    item["amendment_count"] += 1
    bump(item)

    services.recompute_active_tiers(item)
    services.recompute_combos_after_amendment_accepted(item)
    return object_response(out(amendment))


@bp.post("/hold-amendments/<record_id>/reject")
def reject_hold_amendment(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    amendment = must_find("hold_amendment", record_id)
    values = validate_body([Field("rejection_reason", "string")])
    if amendment["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE")

    amendment["status"] = "REJECTED"
    amendment["rejection_reason"] = values["rejection_reason"]
    bump(amendment)

    item = db.price_schedule_items[amendment["amending_item_id"]]
    schedule = services.schedule_of_item(item)
    wholesaler = db.wholesalers[schedule["wholesaler_id"]]
    program = services.program_of_schedule(schedule)

    wholesaler["frivolous_amendment_count"] += 1
    if wholesaler["frivolous_amendment_count"] >= FRIVOLOUS_PENALTY_THRESHOLD:
        wholesaler["amendment_penalty_accrued_cents"] += program[
            "frivolous_amendment_penalty_cents"
        ]
    services.recompute_exposure(wholesaler)
    bump(wholesaler)
    return object_response(out(amendment))


@bp.post("/hold-amendments/<record_id>/revoke")
def revoke_hold_amendment(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    amendment = must_find("hold_amendment", record_id)
    values = validate_body([Field("revocation_reason", "string")])
    if amendment["status"] != "ACCEPTED":
        raise_err("ERR_INVALID_STATE")

    amendment["status"] = "REVOKED"
    amendment["revocation_reason"] = values["revocation_reason"]
    bump(amendment)

    item = db.price_schedule_items[amendment["amending_item_id"]]
    item["case_price_cents"] = amendment["prior_case_price_cents"]
    item["unit_price_cents"] = amendment["prior_unit_price_cents"]
    item["amendment_count"] -= 1
    bump(item)

    services.recompute_active_tiers(item)
    services.recompute_combos_after_amendment_revoked(item)
    return object_response(out(amendment))


@bp.get("/hold-amendments/<record_id>")
def get_hold_amendment(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("hold_amendment", record_id)))


@bp.get("/hold-amendments")
def list_hold_amendments():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.hold_amendments.values()),
        {
            "amending_item_id": None,
            "reference_item_id": None,
            "status": AMENDMENT_STATUSES,
        },
        out,
    )


# ---------------------------------------------------------------------------
# error corrections
# ---------------------------------------------------------------------------
@bp.post("/error-corrections")
def create_error_correction():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("item_id", "string"),
            Field("corrected_case_price_cents", "int", minimum=1),
            Field("corrected_unit_price_cents", "int", minimum=1),
            Field("reason", "string"),
        ]
    )
    item = must_find("price_schedule_item", values["item_id"])
    schedule = services.schedule_of_item(item)
    require_scope(actor, schedule["wholesaler_id"])

    # Priority 8 -- only a certified item may be corrected.
    if item["status"] not in ("POSTED", "EFFECTIVE"):
        raise_err("ERR_INVALID_STATE")

    program = services.program_of_schedule(schedule)
    variance = calc.correction_variance_pct(
        item["case_price_cents"], values["corrected_case_price_cents"]
    )

    # Priority 17 -- a rewrite is not a clerical error.
    if calc.exceeds_clerical_limit(variance):
        raise_err("ERR_CORRECTION_EXCEEDS_CLERICAL_LIMIT")

    # Priority 20 -- the correction window must still be open.
    if not calc.correction_window_is_open(schedule, program, now_dt()):
        raise_err("ERR_CORRECTION_WINDOW_CLOSED")

    record = new_record(
        {
            "item_id": item["id"],
            "corrected_case_price_cents": values["corrected_case_price_cents"],
            "corrected_unit_price_cents": values["corrected_unit_price_cents"],
            "reason": values["reason"],
            "status": "SUBMITTED",
            "prior_case_price_cents": item["case_price_cents"],
            "prior_unit_price_cents": item["unit_price_cents"],
            "variance_pct": float(variance),
            "denial_reason": None,
        }
    )
    db.error_corrections[record["id"]] = record
    return object_response(out(record), 201)


@bp.post("/error-corrections/<record_id>/approve")
def approve_error_correction(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    correction = must_find("error_correction", record_id)
    if correction["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE")

    item = db.price_schedule_items[correction["item_id"]]
    schedule = services.schedule_of_item(item)
    program = services.program_of_schedule(schedule)

    # Priority 18 -- the schedule's approved-correction quota.
    if schedule["correction_count"] >= program["max_corrections_per_schedule"]:
        raise_err("ERR_CORRECTION_LIMIT_EXCEEDED")

    correction["status"] = "APPROVED"
    bump(correction)

    item["case_price_cents"] = correction["corrected_case_price_cents"]
    item["unit_price_cents"] = correction["corrected_unit_price_cents"]
    item["correction_count"] += 1
    bump(item)

    schedule["correction_count"] += 1
    bump(schedule)

    services.recompute_active_tiers(item)

    if schedule["correction_count"] == REPEAT_CORRECTION_THRESHOLD:
        wholesaler = db.wholesalers[schedule["wholesaler_id"]]
        wholesaler["correction_penalty_accrued_cents"] += program[
            "repeat_correction_penalty_cents"
        ]
        services.recompute_exposure(wholesaler)
        bump(wholesaler)

    return object_response(out(correction))


@bp.post("/error-corrections/<record_id>/deny")
def deny_error_correction(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    correction = must_find("error_correction", record_id)
    values = validate_body([Field("denial_reason", "string")])
    if correction["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE")
    correction["status"] = "DENIED"
    correction["denial_reason"] = values["denial_reason"]
    bump(correction)
    return object_response(out(correction))


@bp.get("/error-corrections/<record_id>")
def get_error_correction(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("error_correction", record_id)))


@bp.get("/error-corrections")
def list_error_corrections():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.error_corrections.values()),
        {"item_id": None, "status": CORRECTION_STATUSES},
        out,
    )
