"""Target-market lending measurement and recertification."""
import calc
import services as svc
import shape
from auth import authenticate, scope
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, db, fmt_dt, now, ordered, parse_dt, touch

bp = Blueprint("measurements", __name__)

BASES = ("DOLLAR_WEIGHTED", "COUNT_WEIGHTED")
READ_ROLES = ("InstitutionOfficer", "ComplianceAnalyst", "CertificationReviewer")
LIST_ROLES = ("ComplianceAnalyst", "CertificationReviewer")
OVERLAP_STATES = ("DRAFT", "FINALIZED")


@bp.post("/institutions/<institution_id>/compliance-measurements")
def create_measurement(institution_id):
    authenticate(("ComplianceAnalyst",))
    svc.get_institution(institution_id)
    data = shape.body()
    start_raw, start = shape.req_dt(data, "period_start")
    end_raw, end = shape.req_dt(data, "period_end")
    basis = shape.req_enum(data, "weighting_basis", BASES)
    # The per-basis overlap test runs BEFORE the bounds-ordering test (PRD 2.8).
    for other in db.measurements.values():
        if other["institution_id"] != institution_id:
            continue
        if other["weighting_basis"] != basis:
            continue
        if other["state"] not in OVERLAP_STATES:
            continue
        other_start = parse_dt(other["period_start"])
        other_end = parse_dt(other["period_end"])
        if start < other_end and other_start < end:
            fail("ERR_MEASUREMENT_PERIOD_OVERLAP")
    if not end > start:
        fail("ERR_PERIOD_BOUNDS_INVALID")
    if end > now():
        fail("ERR_PERIOD_END_IN_FUTURE")
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "period_start": start_raw,
        "period_end": end_raw,
        "weighting_basis": basis,
        "state": "DRAFT",
        "measured_loan_count": 0,
        "target_market_loan_count": 0,
        "measured_principal_cents": 0,
        "target_market_principal_cents": 0,
        "dollar_weighted_pct": None,
        "count_weighted_pct": None,
        "selected_pct": None,
        "verdict": "PENDING",
        "void_reason": None,
        "finalized_at": None,
    })
    db.measurements[row["id"]] = row
    return created(row)


def _filter(rows):
    for name in ("weighting_basis", "state", "verdict"):
        value = qs(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return rows


@bp.get("/institutions/<institution_id>/compliance-measurements")
def list_institution_measurements(institution_id):
    caller = authenticate(READ_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = ordered([m for m in db.measurements.values()
                    if m["institution_id"] == institution_id])
    return page(_filter(rows), limit, offset)


@bp.get("/compliance-measurements")
def list_measurements():
    authenticate(LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.measurements.values())
    institution_id = qs("institution_id")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    return page(_filter(rows), limit, offset)


@bp.get("/compliance-measurements/<measurement_id>")
def read_measurement(measurement_id):
    caller = authenticate(READ_ROLES)
    existing = db.measurements.get(measurement_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_measurement(measurement_id))


@bp.post("/compliance-measurements/<measurement_id>/finalize")
def finalize_measurement(measurement_id):
    authenticate(("ComplianceAnalyst",))
    row = svc.get_measurement(measurement_id)
    if row["state"] != "DRAFT":
        fail("ERR_MEASUREMENT_NOT_DRAFT")
    start = parse_dt(row["period_start"])
    end = parse_dt(row["period_end"])
    measured = []
    for loan in svc.institution_loans(row["institution_id"]):
        stamp = parse_dt(loan["first_disbursed_on"])
        if stamp is None:
            continue
        # Half-open window; servicing_state is deliberately not filtered.
        if start <= stamp < end:
            measured.append(loan)
    if not measured:
        fail("ERR_NO_MEASURABLE_LOANS")
    in_market = [l for l in measured
                 if l["borrower_in_target_market_at_origination"]]
    measured_principal = sum(l["principal_disbursed_cents"] for l in measured)
    market_principal = sum(l["principal_disbursed_cents"] for l in in_market)
    row["measured_loan_count"] = len(measured)
    row["target_market_loan_count"] = len(in_market)
    row["measured_principal_cents"] = measured_principal
    row["target_market_principal_cents"] = market_principal
    row["dollar_weighted_pct"] = calc.weighted_pct(market_principal,
                                                   measured_principal)
    row["count_weighted_pct"] = calc.weighted_pct(len(in_market), len(measured))
    selected = (row["dollar_weighted_pct"]
                if row["weighting_basis"] == "DOLLAR_WEIGHTED"
                else row["count_weighted_pct"])
    row["selected_pct"] = selected
    row["verdict"] = ("PASS" if selected >= calc.TARGET_MARKET_THRESHOLD_PCT
                      else "FAIL")
    row["state"] = "FINALIZED"
    row["finalized_at"] = fmt_dt(now())
    touch(row)
    inst = svc.get_institution(row["institution_id"])
    inst["target_market_lending_pct"] = selected
    svc.apply_measurement_verdict(inst, row)
    touch(inst)
    return ok(row)


@bp.post("/compliance-measurements/<measurement_id>/void")
def void_measurement(measurement_id):
    authenticate(("ComplianceAnalyst",))
    row = svc.get_measurement(measurement_id)
    data = shape.body()
    reason = shape.req_str(data, "void_reason", 1)
    if row["state"] != "DRAFT":
        fail("ERR_MEASUREMENT_NOT_DRAFT")
    row["state"] = "VOIDED"
    row["void_reason"] = reason
    touch(row)
    return ok(row)
