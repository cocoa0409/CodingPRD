"""Filings, line items, review, correction and supersession (PRD §3.4, §3.5)."""

from flask import Blueprint, g

import clock
import constants
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_EMPTY_SUBMISSION,
    ERR_CORRECTION_WINDOW_CLOSED,
    ERR_DUPLICATE_SUBMISSION,
    ERR_FOREIGN_REPORTING_ENTITY,
    ERR_FORBIDDEN_PURCHASE_TYPE_ELEMENT,
    ERR_FORWARD_DELIVERY_INTERVAL_INVALID,
    ERR_INVALID_SUBMISSION_STATE,
    ERR_LINE_ITEM_CLASS_MISMATCH,
    ERR_MISSING_PURCHASE_TYPE_ELEMENT,
    ERR_REGISTRATION_NOT_ACTIVE,
    ERR_RESUBMISSION_LIMIT_REACHED,
    ERR_SPECIES_CLASS_MISMATCH,
    ERR_STALE_WINDOW_VERSION,
    ERR_SUBMISSION_NOT_EDITABLE,
    ERR_SUPERSEDE_TARGET_NOT_ACCEPTED,
    ERR_SUPERSEDE_TARGET_PLANT_MISMATCH,
    ERR_WHOLESALE_NOT_AUTHORIZED,
    ERR_WINDOW_NOT_OPEN,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPORTER_AGENT,
    is_reporter_agent,
    roles,
)
from numeric import dec, money, round_half_up
from services import calculations, cascades

bp = Blueprint("submissions", __name__)

READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
)

LIVE_LINE_CLASS = "LIVE_ANIMAL"
WHOLESALE_CLASSES = ("BOXED_BEEF", "WHOLESALE_CUTS")

REQUIRED_ELEMENTS = {
    "FORMULA": ("formula_base_reference",),
    "NEGOTIATED_GRID": ("grid_premium_discount_per_cwt",),
    "FORWARD_CONTRACT": ("forward_delivery_start", "forward_delivery_end"),
}
FORBIDDEN_ELEMENTS = {
    "NEGOTIATED": (
        "formula_base_reference",
        "grid_premium_discount_per_cwt",
        "forward_delivery_start",
        "forward_delivery_end",
    ),
    "PACKER_OWNED": (
        "formula_base_reference",
        "grid_premium_discount_per_cwt",
        "forward_delivery_start",
        "forward_delivery_end",
    ),
    "FORMULA": ("grid_premium_discount_per_cwt",),
}


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------
def _owning_entity_id(sub):
    plant = db.plants.get(sub["plant_id"])
    return plant["reporting_entity_id"] if plant else None


def _require_ownership_of_plant(plant):
    if is_reporter_agent() and g.user_id != plant["reporting_entity_id"]:
        raise ApiError(
            ERR_FOREIGN_REPORTING_ENTITY,
            "A reporter may only act for its own plants.",
        )


def _require_ownership(sub):
    if is_reporter_agent() and g.user_id != _owning_entity_id(sub):
        raise ApiError(
            ERR_FOREIGN_REPORTING_ENTITY,
            "A reporter may only act on its own filings.",
        )


def _require_state(sub, *allowed):
    if sub["status"] not in allowed:
        raise ApiError(
            ERR_INVALID_SUBMISSION_STATE,
            "A filing in status %s does not permit this action." % sub["status"],
        )


def _require_editable(sub):
    if sub["status"] not in constants.SUBMISSION_EDITABLE_STATUSES:
        raise ApiError(
            ERR_SUBMISSION_NOT_EDITABLE,
            "Line items may be appended only while the filing is DRAFT or UNDER_CORRECTION.",
        )


def _require_active_registration(sub, window):
    entity_id = _owning_entity_id(sub)
    year = window["_period_start"].year
    active = any(
        r["reporting_entity_id"] == entity_id
        and r["determination_year"] == year
        and r["determination_outcome"] == "MANDATORY"
        and r["status"] == "ACTIVE"
        for r in db.registrations.values()
    )
    if not active:
        raise ApiError(
            ERR_REGISTRATION_NOT_ACTIVE,
            "The firm has no ACTIVE mandatory registration for the window's program year.",
        )


def _require_non_empty(sub, window):
    if window["report_class"] == LIVE_LINE_CLASS:
        has_lines = any(
            t["submission_id"] == sub["id"] for t in db.transaction_records.values()
        )
    else:
        has_lines = any(l["submission_id"] == sub["id"] for l in db.wholesale_lots.values())
    if not has_lines:
        raise ApiError(
            ERR_EMPTY_SUBMISSION,
            "The filing carries no line item of the window's reporting class.",
        )


# ---------------------------------------------------------------------------
# Filing creation
# ---------------------------------------------------------------------------
@bp.post("/submissions")
@roles(ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)
def create_submission():
    payload = V.body()
    plant_id = V.get_string(payload, "plant_id")
    window_id = V.get_string(payload, "reporting_window_id")
    expected_version = V.get_int(payload, "expected_window_version")
    supersedes_id = V.get_string(payload, "supersedes_submission_id", required=False)

    plant = lookup.plant(plant_id)
    window = lookup.reporting_window(window_id)
    target = lookup.submission(supersedes_id) if supersedes_id is not None else None

    _require_ownership_of_plant(plant)

    if int(window["version"]) != int(expected_version):
        raise ApiError(
            ERR_STALE_WINDOW_VERSION,
            "The reporting window has advanced past the supplied expected_window_version.",
        )

    if window["status"] != "OPEN":
        raise ApiError(ERR_WINDOW_NOT_OPEN, "The reporting window is no longer OPEN.")

    if target is not None:
        if target["plant_id"] != plant_id or target["reporting_window_id"] != window_id:
            raise ApiError(
                ERR_SUPERSEDE_TARGET_PLANT_MISMATCH,
                "The supersede target belongs to another plant or window.",
            )
        if target["status"] != "ACCEPTED":
            raise ApiError(
                ERR_SUPERSEDE_TARGET_NOT_ACCEPTED,
                "Only an ACCEPTED filing may be superseded.",
            )

    if plant["species"] != window["species"]:
        raise ApiError(
            ERR_SPECIES_CLASS_MISMATCH,
            "The plant's species does not match the window's species.",
        )

    siblings = [
        s
        for s in db.submissions.values()
        if s["plant_id"] == plant_id and s["reporting_window_id"] == window_id
    ]
    for sibling in siblings:
        if sibling["status"] in ("DRAFT", "SUBMITTED", "UNDER_CORRECTION", "RESUBMITTED"):
            raise ApiError(
                ERR_DUPLICATE_SUBMISSION,
                "The plant already holds a live filing for this window.",
            )
        if sibling["status"] == "ACCEPTED" and sibling["id"] != supersedes_id:
            raise ApiError(
                ERR_DUPLICATE_SUBMISSION,
                "An accepted filing for this plant and window must be named as the "
                "supersede target.",
            )

    rec = db.insert(
        db.submissions,
        {
            "plant_id": plant_id,
            "reporting_window_id": window_id,
            "supersedes_submission_id": supersedes_id,
            "status": "DRAFT",
            "submitted_at": None,
            "accepted_at": None,
            "lateness_minutes": 0,
            "is_late": False,
            "days_late": 0,
            "reported_head": 0,
            "reported_cwt": money(0),
            "reported_value_dollars": money(0),
            "reported_pounds": money(0),
            "reported_load_count": 0,
            "resubmission_count": 0,
            "correction_reason": None,
            "review_note": None,
        },
    )
    db.touch(window)
    return response.object_response(serializers.submission(rec), 201)


# ---------------------------------------------------------------------------
# Transaction lines
# ---------------------------------------------------------------------------
@bp.post("/submissions/<submission_id>/transactions")
@roles(ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)
def add_transaction(submission_id):
    payload = V.body()
    purchase_type = V.get_enum(payload, "purchase_type", V.PURCHASE_TYPES)
    head_count = V.get_int(payload, "head_count", minimum=1)
    price = V.get_decimal(payload, "avg_net_price_per_cwt", exclusive_minimum=0)
    weight = V.get_decimal(payload, "avg_carcass_weight_cwt", exclusive_minimum=0)
    formula_base = V.get_string(payload, "formula_base_reference", required=False)
    grid_premium = V.get_decimal(payload, "grid_premium_discount_per_cwt", required=False)
    start_raw, start_dt = V.get_datetime(payload, "forward_delivery_start", required=False)
    end_raw, end_dt = V.get_datetime(payload, "forward_delivery_end", required=False)

    sub = lookup.submission(submission_id)
    _require_ownership(sub)
    _require_editable(sub)

    if start_dt is not None and end_dt is not None and start_dt > end_dt:
        raise ApiError(
            ERR_FORWARD_DELIVERY_INTERVAL_INVALID,
            "forward_delivery_start must be no later than forward_delivery_end.",
        )

    window = db.reporting_windows[sub["reporting_window_id"]]
    if window["report_class"] != LIVE_LINE_CLASS:
        raise ApiError(
            ERR_LINE_ITEM_CLASS_MISMATCH,
            "Transaction lines belong only to LIVE_ANIMAL windows.",
        )

    for field in REQUIRED_ELEMENTS.get(purchase_type, ()):
        if not V.present(payload, field):
            raise ApiError(
                ERR_MISSING_PURCHASE_TYPE_ELEMENT,
                "A %s line requires '%s'." % (purchase_type, field),
            )
    for field in FORBIDDEN_ELEMENTS.get(purchase_type, ()):
        if V.present(payload, field):
            raise ApiError(
                ERR_FORBIDDEN_PURCHASE_TYPE_ELEMENT,
                "A %s line must not carry '%s'." % (purchase_type, field),
            )

    plant = db.plants[sub["plant_id"]]
    if purchase_type == "FORWARD_CONTRACT":
        calculations.check_forward_commitment_peak(plant, start_dt, end_dt, head_count)

    line_value = round_half_up(dec(head_count) * dec(weight) * dec(price), 2)

    rec = db.insert(
        db.transaction_records,
        {
            "submission_id": sub["id"],
            "purchase_type": purchase_type,
            "head_count": head_count,
            "avg_net_price_per_cwt": money(price),
            "avg_carcass_weight_cwt": money(weight),
            "formula_base_reference": formula_base,
            "grid_premium_discount_per_cwt": money(grid_premium) if grid_premium is not None else None,
            "forward_delivery_start": start_raw,
            "_forward_delivery_start": start_dt,
            "forward_delivery_end": end_raw,
            "_forward_delivery_end": end_dt,
            "line_value_dollars": line_value,
        },
        versioned=False,
    )

    cascades.recompute_submission_totals(sub)
    db.touch(sub)
    return response.object_response(serializers.transaction_record(rec), 201)


@bp.get("/submissions/<submission_id>/transactions")
@roles(*READ_ROLES)
def list_transactions(submission_id):
    limit, offset = V.pagination()
    purchase_type = V.query_str("purchase_type")

    sub = lookup.submission(submission_id)
    records = db.ordered(
        [t for t in db.transaction_records.values() if t["submission_id"] == sub["id"]]
    )
    if purchase_type is not None:
        records = [t for t in records if t["purchase_type"] == purchase_type]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.transaction_record(r) for r in page], limit, offset, total
    )


# ---------------------------------------------------------------------------
# Wholesale lots
# ---------------------------------------------------------------------------
@bp.post("/submissions/<submission_id>/wholesale-lots")
@roles(ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)
def add_wholesale_lot(submission_id):
    payload = V.body()
    product_class = V.get_enum(payload, "product_class", V.PRODUCT_CLASSES)
    sale_type = V.get_enum(payload, "sale_type", V.SALE_TYPES)
    load_count = V.get_int(payload, "load_count", minimum=1)
    total_pounds = V.get_decimal(payload, "total_pounds", exclusive_minimum=0)
    price = V.get_decimal(payload, "price_per_cwt", exclusive_minimum=0)

    sub = lookup.submission(submission_id)
    _require_ownership(sub)
    _require_editable(sub)

    plant = db.plants[sub["plant_id"]]
    if not plant.get("wholesale_reporting_required"):
        raise ApiError(
            ERR_WHOLESALE_NOT_AUTHORIZED,
            "The plant is not authorized to report wholesale product lines.",
        )

    window = db.reporting_windows[sub["reporting_window_id"]]
    if window["report_class"] not in WHOLESALE_CLASSES:
        raise ApiError(
            ERR_LINE_ITEM_CLASS_MISMATCH,
            "Wholesale lots belong only to BOXED_BEEF or WHOLESALE_CUTS windows.",
        )

    lot_value = round_half_up(dec(total_pounds) / dec(100) * dec(price), 2)

    rec = db.insert(
        db.wholesale_lots,
        {
            "submission_id": sub["id"],
            "product_class": product_class,
            "sale_type": sale_type,
            "load_count": load_count,
            "total_pounds": money(total_pounds),
            "price_per_cwt": money(price),
            "lot_value_dollars": lot_value,
        },
        versioned=False,
    )

    cascades.recompute_submission_totals(sub)
    db.touch(sub)
    return response.object_response(serializers.wholesale_lot(rec), 201)


@bp.get("/submissions/<submission_id>/wholesale-lots")
@roles(*READ_ROLES)
def list_wholesale_lots(submission_id):
    limit, offset = V.pagination()
    product_class = V.query_str("product_class")

    sub = lookup.submission(submission_id)
    records = db.ordered(
        [l for l in db.wholesale_lots.values() if l["submission_id"] == sub["id"]]
    )
    if product_class is not None:
        records = [l for l in records if l["product_class"] == product_class]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.wholesale_lot(r) for r in page], limit, offset, total
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@bp.post("/submissions/<submission_id>/submit")
@roles(ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)
def submit(submission_id):
    sub = lookup.submission(submission_id)
    _require_ownership(sub)
    _require_state(sub, "DRAFT")

    window = db.reporting_windows[sub["reporting_window_id"]]
    if window["status"] != "OPEN":
        raise ApiError(ERR_WINDOW_NOT_OPEN, "The reporting window is no longer OPEN.")

    _require_active_registration(sub, window)
    _require_non_empty(sub, window)

    sub["submitted_at"] = clock.iso_now()
    calculations.apply_lateness(sub, window)
    sub["status"] = "SUBMITTED"
    db.touch(sub)
    return response.object_response(serializers.submission(sub))


@bp.post("/submissions/<submission_id>/review")
@roles(ROLE_MARKET_ANALYST, ROLE_PROGRAM_ADMIN)
def review(submission_id):
    payload = V.body()
    decision = V.get_enum(payload, "decision", V.DECISIONS)
    review_note = V.get_string(payload, "review_note", required=False, max_len=4000)

    sub = lookup.submission(submission_id)
    _require_state(sub, "SUBMITTED", "RESUBMITTED")

    window = db.reporting_windows[sub["reporting_window_id"]]

    if decision == "REJECT":
        sub["status"] = "REJECTED"
        sub["review_note"] = review_note
        db.touch(sub)
        return response.object_response(serializers.submission(sub))

    target = None
    if sub["supersedes_submission_id"] is not None:
        target = db.submissions.get(sub["supersedes_submission_id"])
        if target is None or target["status"] != "ACCEPTED":
            raise ApiError(
                ERR_SUPERSEDE_TARGET_NOT_ACCEPTED,
                "The supersede target is no longer in ACCEPTED status.",
            )

    sub["status"] = "ACCEPTED"
    sub["accepted_at"] = clock.iso_now()
    sub["review_note"] = review_note
    db.touch(sub)

    if target is not None:
        target["status"] = "SUPERSEDED"
        db.touch(target)

    cascades.submission_acceptance_changed(window)
    return response.object_response(serializers.submission(sub))


@bp.post("/submissions/<submission_id>/open-correction")
@roles(ROLE_COMPLIANCE_AUDITOR, ROLE_PROGRAM_ADMIN)
def open_correction(submission_id):
    payload = V.body()
    correction_reason = V.get_string(payload, "correction_reason", max_len=4000)

    sub = lookup.submission(submission_id)
    _require_state(sub, "ACCEPTED")

    window = db.reporting_windows[sub["reporting_window_id"]]
    if clock.now() > window["_correction_deadline_utc"]:
        raise ApiError(
            ERR_CORRECTION_WINDOW_CLOSED,
            "The window's correction deadline has passed.",
        )

    if int(sub["resubmission_count"] or 0) >= constants.RESUBMISSION_LIMIT:
        raise ApiError(
            ERR_RESUBMISSION_LIMIT_REACHED,
            "The filing has already been resubmitted the maximum number of times.",
        )

    sub["correction_reason"] = correction_reason
    sub["status"] = "UNDER_CORRECTION"
    db.touch(sub)

    cascades.submission_acceptance_changed(window)
    return response.object_response(serializers.submission(sub))


@bp.post("/submissions/<submission_id>/resubmit")
@roles(ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)
def resubmit(submission_id):
    sub = lookup.submission(submission_id)
    _require_ownership(sub)
    _require_state(sub, "UNDER_CORRECTION")

    window = db.reporting_windows[sub["reporting_window_id"]]
    _require_active_registration(sub, window)
    _require_non_empty(sub, window)

    sub["resubmission_count"] = int(sub["resubmission_count"] or 0) + 1
    sub["submitted_at"] = clock.iso_now()
    calculations.apply_lateness(sub, window)
    sub["status"] = "RESUBMITTED"
    db.touch(sub)
    return response.object_response(serializers.submission(sub))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/submissions/<submission_id>")
@roles(*READ_ROLES)
def get_submission(submission_id):
    sub = lookup.submission(submission_id)
    return response.object_response(serializers.submission(sub))


@bp.get("/submissions")
@roles(*READ_ROLES)
def list_submissions():
    limit, offset = V.pagination()
    plant_id = V.query_str("plant_id")
    window_id = V.query_str("reporting_window_id")
    supersedes_id = V.query_str("supersedes_submission_id")
    status = V.query_str("status")
    is_late = V.query_bool("is_late")

    records = db.ordered(db.submissions.values())
    if plant_id is not None:
        records = [s for s in records if s["plant_id"] == plant_id]
    if window_id is not None:
        records = [s for s in records if s["reporting_window_id"] == window_id]
    if supersedes_id is not None:
        records = [s for s in records if s["supersedes_submission_id"] == supersedes_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    if is_late is not None:
        records = [s for s in records if bool(s["is_late"]) == is_late]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.submission(r) for r in page], limit, offset, total
    )
