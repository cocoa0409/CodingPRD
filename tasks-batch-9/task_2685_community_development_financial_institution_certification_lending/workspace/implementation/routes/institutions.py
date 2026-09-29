"""Logical clock, institution registration/reads and the servicing checkpoint."""
from decimal import Decimal

import calc
import services as svc
import shape
from auth import authenticate, scope
from envelope import created, empty, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import EIN_RE, base_row, db, fmt_dt, now, ordered, set_clock, touch

bp = Blueprint("institutions", __name__)

CLOCK_ROLES = ("ComplianceAnalyst", "CertificationReviewer", "AwardAdministrator",
               "CreditUnderwriter", "CreditCommittee", "InstitutionOfficer")
READ_INSTITUTION_ROLES = ("InstitutionOfficer", "CertificationReviewer",
                          "ComplianceAnalyst", "AwardAdministrator",
                          "CreditUnderwriter", "CreditCommittee")
LIST_INSTITUTION_ROLES = ("CertificationReviewer", "ComplianceAnalyst",
                          "AwardAdministrator")
ENTITY_TYPES = ("LOAN_FUND", "CREDIT_UNION", "BANK_HOLDING", "VENTURE_FUND")
RESERVE_METHODS = ("MIGRATION_ANALYSIS", "STATIC_POOL")
CERTIFICATION_STATES = ("UNCERTIFIED", "CERTIFIED", "RECERT_DUE", "DECERTIFIED")
POSTURES = ("COMPLIANT", "WATCH", "PROBATION")
MISSION_MIN_LEN = 40


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(CLOCK_ROLES)
    data = shape.body()
    _, parsed = shape.req_dt(data, "to_iso8601")
    set_clock(parsed)
    return empty()


@bp.post("/institutions")
def register_institution():
    # Registration is the single exemption from the institution-scope check:
    # the institution has no id to compare against until this call succeeds.
    authenticate(("InstitutionOfficer",))
    data = shape.body()
    legal_name = shape.req_str(data, "legal_name", 1)
    ein = shape.req_str(data, "ein")
    if not EIN_RE.match(ein):
        fail("ERR_INVALID_REQUEST")
    entity_type = shape.req_enum(data, "entity_type", ENTITY_TYPES)
    mission = shape.req_str(data, "primary_mission_statement", MISSION_MIN_LEN)
    asset_size = shape.req_int(data, "asset_size_cents", minimum=0)
    reserve_method = shape.opt_enum(data, "reserve_method", RESERVE_METHODS,
                                    default="MIGRATION_ANALYSIS")
    balance = shape.opt_int(data, "loss_reserve_balance_cents", minimum=0, default=0)
    for other in db.institutions.values():
        if other["ein"] == ein:
            fail("ERR_DUPLICATE_EIN")
    row = base_row()
    row.update({
        "legal_name": legal_name,
        "ein": ein,
        "entity_type": entity_type,
        "primary_mission_statement": mission,
        "asset_size_cents": asset_size,
        "loss_reserve_balance_cents": balance,
        "reserve_method": reserve_method,
        "certification_state": "UNCERTIFIED",
        "compliance_posture": "COMPLIANT",
        "accountability_score": Decimal("0.0000"),
        "accountability_satisfied": False,
        "governing_seats_active": 0,
        "advisory_seats_active": 0,
        "portfolio_principal_outstanding_cents": 0,
        "portfolio_principal_disbursed_cents": 0,
        "loss_reserve_required_migration_cents": 0,
        "loss_reserve_required_static_cents": 0,
        "loss_reserve_required_cents": 0,
        "reserve_coverage_ratio": calc.EMPTY_PORTFOLIO_RATIO,
        "reserve_deficit_cents": 0,
        "target_market_lending_pct": Decimal("0.00"),
        "jobs_created_total": 0,
        "jobs_retained_total": 0,
        "housing_units_total": 0,
        "businesses_financed_total": 0,
        "certified_at": None,
        "recertification_due_at": None,
    })
    db.institutions[row["id"]] = row
    return created(row)


@bp.get("/institutions/<institution_id>")
def read_institution(institution_id):
    caller = authenticate(READ_INSTITUTION_ROLES)
    scope(caller, institution_id)
    return ok(svc.get_institution(institution_id))


@bp.get("/institutions")
def list_institutions():
    authenticate(LIST_INSTITUTION_ROLES)
    limit, offset = pagination()
    rows = ordered(db.institutions.values())
    state = qs("certification_state")
    posture = qs("compliance_posture")
    if state is not None:
        rows = [r for r in rows if r["certification_state"] == state]
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    return page(rows, limit, offset)


@bp.post("/institutions/<institution_id>/servicing-runs")
def servicing_run(institution_id):
    """Ages the book in created_at order, evaluates the certification clock and
    recomputes the reserve -- in that order (PRD 3.6)."""
    authenticate(("ComplianceAnalyst",))
    inst = svc.get_institution(institution_id)
    clock = now()
    for loan in svc.institution_loans(institution_id):
        if loan["servicing_state"] in ("NOT_DISBURSED", "CHARGED_OFF", "PAID_OFF"):
            continue
        from store import parse_dt
        days = calc.whole_days_past_due(parse_dt(loan["next_payment_due_on"]), clock)
        bucket = calc.bucket_for(days)
        changed = loan["days_past_due"] != days
        # days_past_due is recomputed for every loan the run processes; the
        # figure is truncated toward zero and floored at 0, so a loan that is
        # not yet past due records 0.
        loan["days_past_due"] = days
        if bucket is not None:
            current_rank = calc.BUCKET_ORDER.get(loan["servicing_state"], 0)
            # The assignment never moves a loan to a lower bucket.
            if calc.BUCKET_ORDER[bucket] > current_rank:
                loan["servicing_state"] = bucket
                changed = True
        if changed:
            touch(loan)
    if (inst["certification_state"] == "CERTIFIED"
            and inst["recertification_due_at"] is not None):
        from store import parse_dt
        due = parse_dt(inst["recertification_due_at"])
        if due is not None and clock >= due:
            inst["certification_state"] = "RECERT_DUE"
    svc.recompute_reserve(inst)
    touch(inst)
    return ok(inst)
