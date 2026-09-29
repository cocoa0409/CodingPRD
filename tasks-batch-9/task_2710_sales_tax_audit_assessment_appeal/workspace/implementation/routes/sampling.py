"""SamplingAgreement and SampleUnit endpoints (PRD 3.3, 3.4)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import (
    bad,
    body,
    guard,
    opt_int,
    present,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_str,
)
from routes.common import (
    AGREEMENT_STATUSES,
    CONFIDENCE_LEVELS,
    ERROR_CLASSES,
    METHODOLOGIES,
    apply_filter,
    body_fk,
    listing,
    one,
    path_get,
)
from services import calc, derive

bp = Blueprint("sampling", __name__)

NEEDS_AMOUNT = ("UNREPORTED_TAXABLE_SALE", "RATE_ERROR")


def _parse_strata(raw):
    """Tier-5 shape validation of the strata array; returns normalized rows."""
    if not isinstance(raw, list) or isinstance(raw, bool):
        bad("strata must be an array.")
    if len(raw) < 1 or len(raw) > 12:
        bad("strata must hold between 1 and 12 entries.")
    rows = []
    for entry in raw:
        if not isinstance(entry, dict):
            bad("each stratum must be an object.")
        start = db.parse_date(entry.get("period_start"))
        end = db.parse_date(entry.get("period_end"))
        if start is None or end is None:
            bad("each stratum needs a parseable period_start and period_end.")
        if start > end:
            bad("stratum period_start may not be later than period_end.")
        base = entry.get("population_base_amount_cents")
        units = entry.get("population_unit_count")
        for value, name in ((base, "population_base_amount_cents"), (units, "population_unit_count")):
            if not isinstance(value, int) or isinstance(value, bool):
                bad("stratum %s must be an integer." % name)
            if value < 0:
                bad("stratum %s may not be negative." % name)
        rows.append(
            {
                "period_start": db.format_date(start),
                "period_end": db.format_date(end),
                "population_base_amount_cents": int(base),
                "population_unit_count": int(units),
            }
        )
    return rows


def _check_geometry(strata, audit):
    """Tier-11 interval geometry: the strata must tile the audit scope exactly."""
    scope_start = db.parse_date(audit.get("scope_period_start"))
    scope_end = db.parse_date(audit.get("scope_period_end"))
    ordered = sorted(strata, key=lambda s: s["period_start"])
    for index in range(1, len(ordered)):
        prev_end = db.parse_date(ordered[index - 1]["period_end"])
        this_start = db.parse_date(ordered[index]["period_start"])
        if this_start < prev_end:
            raise ApiError("ERR_STRATUM_OVERLAP")
    for index in range(1, len(ordered)):
        prev_end = db.parse_date(ordered[index - 1]["period_end"])
        this_start = db.parse_date(ordered[index]["period_start"])
        if this_start > prev_end:
            raise ApiError("ERR_STRATUM_GAP")
    if scope_start is None or scope_end is None:
        raise ApiError("ERR_INVALID_STATE")
    first_start = db.parse_date(ordered[0]["period_start"])
    last_end = db.parse_date(ordered[-1]["period_end"])
    if first_start != scope_start:
        raise ApiError("ERR_STRATUM_GAP")
    if last_end != db.add_days(scope_end, 1):
        raise ApiError("ERR_STRATUM_GAP")


# ------------------------------------------------------------- agreements
@bp.post("/sampling-agreements")
@guard("FieldAuditor")
def create_agreement():
    data = body()
    audit_id = req_id(data, "audit_id")
    expected_version = req_int(data, "expected_audit_version", 0)
    methodology = req_enum(data, "methodology", METHODOLOGIES)
    confidence = req_int(data, "confidence_level_bp", 0, 10000)
    minimum = req_int(data, "minimum_sample_size", 1)
    if "strata" not in data:
        bad("strata is required.")
    strata = _parse_strata(data.get("strata"))
    supersedes_id = data.get("supersedes_agreement_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        bad("supersedes_agreement_id must be a string.")
    if confidence not in CONFIDENCE_LEVELS:
        bad("confidence_level_bp must be one of 9000, 9500, 9900.")

    audit = body_fk("audits", audit_id)
    superseded = body_fk("sampling_agreements", supersedes_id) if supersedes_id is not None else None

    if expected_version != audit["version"]:
        raise ApiError("ERR_STALE_AUDIT_VERSION")
    if audit["status"] != "SCOPED":
        raise ApiError("ERR_INVALID_STATE")
    _check_geometry(strata, audit)

    rec = db.new_record(
        {
            "audit_id": audit["id"],
            "supersedes_agreement_id": superseded["id"] if superseded else None,
            "status": "PROPOSED",
            "methodology": methodology,
            "confidence_level_bp": confidence,
            "minimum_sample_size": minimum,
            "round_number": 1,
            "strata": strata,
            "population_base_amount_cents": 0,
            "population_unit_count": 0,
            "examined_unit_count": 0,
            "counter_note": None,
            "requested_minimum_sample_size": None,
            "agreed_by_name": None,
        }
    )
    db.insert("sampling_agreements", rec)
    if superseded is not None and superseded["status"] in ("PROPOSED", "COUNTERED"):
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    # PRD 2.10: "On success the audit's `version` increments by one."
    db.touch(audit)
    return one("sampling_agreements", rec, 201)


@bp.get("/sampling-agreements")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def list_agreements():
    rows = db.all_of("sampling_agreements")
    rows = apply_filter(rows, "audit_id")
    rows = apply_filter(rows, "supersedes_agreement_id")
    rows = apply_filter(rows, "status", AGREEMENT_STATUSES)
    rows = apply_filter(rows, "methodology", METHODOLOGIES)
    return listing("sampling_agreements", rows)


@bp.get("/sampling-agreements/<aid>")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def read_agreement(aid):
    return one("sampling_agreements", path_get("sampling_agreements", aid))


@bp.post("/sampling-agreements/<aid>/counter")
@guard("Taxpayer")
def counter_agreement(aid):
    agreement = path_get("sampling_agreements", aid)
    data = body()
    note = req_str(data, "counter_note", 1, None)
    requested = opt_int(data, "requested_minimum_sample_size", 1)

    if agreement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")
    audit = db.get("audits", agreement["audit_id"])
    if audit is None or audit["status"] != "SCOPED":
        raise ApiError("ERR_INVALID_STATE")

    agreement["status"] = "COUNTERED"
    agreement["counter_note"] = note
    if requested is not None:
        agreement["requested_minimum_sample_size"] = requested
    db.touch(agreement)
    return one("sampling_agreements", agreement)


@bp.post("/sampling-agreements/<aid>/revise")
@guard("FieldAuditor")
def revise_agreement(aid):
    agreement = path_get("sampling_agreements", aid)
    data = body()
    methodology = None
    confidence = None
    minimum = None
    strata = None
    if present(data, "methodology"):
        methodology = req_enum(data, "methodology", METHODOLOGIES)
    if present(data, "confidence_level_bp"):
        confidence = req_int(data, "confidence_level_bp", 0, 10000)
        if confidence not in CONFIDENCE_LEVELS:
            bad("confidence_level_bp must be one of 9000, 9500, 9900.")
    if present(data, "minimum_sample_size"):
        minimum = req_int(data, "minimum_sample_size", 1)
    if present(data, "strata"):
        strata = _parse_strata(data.get("strata"))

    if agreement["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE")
    audit = db.get("audits", agreement["audit_id"])
    if strata is not None:
        _check_geometry(strata, audit)
    if agreement["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    if methodology is not None:
        agreement["methodology"] = methodology
    if confidence is not None:
        agreement["confidence_level_bp"] = confidence
    if minimum is not None:
        agreement["minimum_sample_size"] = minimum
    if strata is not None:
        agreement["strata"] = strata
    agreement["status"] = "PROPOSED"
    agreement["round_number"] = agreement["round_number"] + 1
    db.touch(agreement)
    return one("sampling_agreements", agreement)


@bp.post("/sampling-agreements/<aid>/agree")
@guard("Taxpayer")
def agree_agreement(aid):
    agreement = path_get("sampling_agreements", aid)
    data = body()
    agreed_by = req_str(data, "agreed_by_name", 1, None)

    if agreement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")
    audit = db.get("audits", agreement["audit_id"])
    if audit is None or audit["status"] != "SCOPED":
        raise ApiError("ERR_INVALID_STATE")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")

    agreement["status"] = "AGREED"
    agreement["agreed_by_name"] = agreed_by
    db.touch(agreement)
    for other in derive.agreements_of_audit(audit["id"]):
        if other["id"] != agreement["id"] and other["status"] in ("PROPOSED", "COUNTERED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)
    audit["agreed_agreement_id"] = agreement["id"]
    audit["status"] = "FIELDWORK"
    db.touch(audit)
    return one("sampling_agreements", agreement)


# ------------------------------------------------------------ sample units
def _audit_of_agreement(agreement):
    return db.get("audits", agreement["audit_id"])


@bp.post("/sample-units")
@guard("FieldAuditor")
def create_unit():
    data = body()
    agreement_id = req_id(data, "sampling_agreement_id")
    stratum_index = req_int(data, "stratum_index", 0)
    invoice_reference = req_str(data, "invoice_reference", 1, None)
    invoice_date = req_date(data, "invoice_date")
    invoice_amount = req_int(data, "invoice_amount_cents", 1)
    exempt_amount = opt_int(data, "exempt_sale_amount_cents", 0)
    if exempt_amount is None:
        exempt_amount = 0
    error_class = "PENDING"
    if present(data, "error_class"):
        error_class = req_enum(data, "error_class", ERROR_CLASSES)
    declared = None
    declared_given = present(data, "declared_error_amount_cents")
    if declared_given:
        declared = req_int(data, "declared_error_amount_cents", 0)
        if error_class not in NEEDS_AMOUNT:
            bad("declared_error_amount_cents is only accepted for "
                "UNREPORTED_TAXABLE_SALE and RATE_ERROR.")
    if exempt_amount > invoice_amount:
        bad("exempt_sale_amount_cents may not exceed invoice_amount_cents.")

    agreement = body_fk("sampling_agreements", agreement_id)
    audit = _audit_of_agreement(agreement)

    if audit is None or audit.get("agreed_agreement_id") != agreement["id"]:
        raise ApiError("ERR_AGREEMENT_NOT_AGREED")
    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")

    strata = agreement.get("strata") or []
    if stratum_index >= len(strata):
        raise ApiError("ERR_STRATUM_INDEX_INVALID")
    stratum = strata[stratum_index]
    start = db.parse_date(stratum["period_start"])
    end = db.parse_date(stratum["period_end"])
    if invoice_date < start or invoice_date >= end:
        raise ApiError("ERR_INVOICE_DATE_OUT_OF_STRATUM")

    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")

    if error_class in NEEDS_AMOUNT and declared is None:
        raise ApiError("ERR_ERROR_AMOUNT_REQUIRED")

    rec = db.new_record(
        {
            "sampling_agreement_id": agreement["id"],
            "stratum_index": stratum_index,
            "invoice_reference": invoice_reference,
            "invoice_date": db.format_date(invoice_date),
            "invoice_amount_cents": invoice_amount,
            "exempt_sale_amount_cents": exempt_amount,
            "error_class": error_class,
            "declared_error_amount_cents": declared,
            "error_amount_cents": calc.unit_error_amount(error_class, exempt_amount, declared),
            "redetermination_count": 0,
        }
    )
    db.insert("sample_units", rec)
    derive.mark_projection_stale(audit)
    db.touch(audit)
    return one("sample_units", rec, 201)


@bp.get("/sample-units/<uid>")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def read_unit(uid):
    return one("sample_units", path_get("sample_units", uid))


@bp.get("/sampling-agreements/<aid>/sample-units")
@guard("FieldAuditor", "AuditSupervisor", "Taxpayer")
def list_units_of_agreement(aid):
    agreement = path_get("sampling_agreements", aid)
    rows = derive.units_of_agreement(agreement["id"])
    rows = apply_filter(rows, "stratum_index", None, int)
    rows = apply_filter(rows, "error_class", ERROR_CLASSES)
    return listing("sample_units", rows)


@bp.post("/sample-units/<uid>/redetermine")
@guard("FieldAuditor")
def redetermine_unit(uid):
    unit = path_get("sample_units", uid)
    data = body()
    error_class = req_enum(data, "error_class", ERROR_CLASSES)
    declared = None
    if present(data, "declared_error_amount_cents"):
        declared = req_int(data, "declared_error_amount_cents", 0)
        if error_class not in NEEDS_AMOUNT:
            bad("declared_error_amount_cents is only accepted for "
                "UNREPORTED_TAXABLE_SALE and RATE_ERROR.")

    agreement = db.get("sampling_agreements", unit["sampling_agreement_id"])
    audit = _audit_of_agreement(agreement) if agreement else None
    if audit is None or audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")
    if error_class in NEEDS_AMOUNT and declared is None:
        raise ApiError("ERR_ERROR_AMOUNT_REQUIRED")

    unit["error_class"] = error_class
    unit["declared_error_amount_cents"] = declared
    unit["error_amount_cents"] = calc.unit_error_amount(
        error_class, unit["exempt_sale_amount_cents"], declared
    )
    unit["redetermination_count"] = unit["redetermination_count"] + 1
    db.touch(unit)
    derive.mark_projection_stale(audit)
    db.touch(audit)
    return one("sample_units", unit)
