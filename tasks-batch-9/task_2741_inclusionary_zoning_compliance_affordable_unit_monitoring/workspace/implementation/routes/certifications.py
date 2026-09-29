"""Income certifications and monitoring reviews."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError, invalid
from services import calc, lookup, project_svc

bp = Blueprint("certifications", __name__)

BROAD_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
                    mw.DEVELOPER, mw.RESIDENT, mw.FUND_AUDITOR)
REVIEW_READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
                     mw.DEVELOPER, mw.FUND_AUDITOR)

OPEN_REVIEW_STATES = ("FINDING_ISSUED", "CURE_SUBMITTED", "ESCALATED")


def _scan_period_overlap(unit, new_start_date, skip_ids=()):
    """Closed-interval collision scan; OWNERSHIP units are never scanned."""
    if unit.get("tenure") == "OWNERSHIP":
        return
    new_end_date = new_start_date + timedelta(days=calc.CERT_TERM_DAYS)
    for existing in lookup.unit_certifications(unit["id"]):
        if existing["id"] in skip_ids:
            continue
        if existing.get("state") != "CERTIFIED":
            continue
        if not existing.get("expires_at"):
            continue
        e_start = db.parse_date_loose(existing.get("effective_date"))
        e_end = db.parse_date_loose(existing.get("expires_at"))
        if e_start is None or e_end is None:
            continue
        if calc.periods_collide(new_start_date, new_end_date, e_start, e_end):
            raise ApiError("ERR_CERTIFICATION_PERIOD_OVERLAP")


def _cascade_certification(cert, unit, household):
    """Occupancy, household, lottery round and project cascades of a new
    CERTIFIED certification."""
    occupancy = unit.get("occupancy_status")
    if occupancy == "RESERVED":
        unit["occupancy_status"] = "OCCUPIED"
    elif occupancy in ("PLANNED", "VACANT"):
        unit["occupancy_status"] = "OCCUPIED"
        unit["occupant_household_id"] = cert["household_id"]
    # An already OCCUPIED unit performs no occupancy transition and keeps its
    # occupant: the incoming buyer is moved in by the resale close cascade.
    unit["current_rent_cents"] = cert["contract_rent_cents"]
    unit["max_allowed_rent_cents"] = cert["max_rent_cents"]
    db.touch(unit)

    if household.get("state") in ("REGISTERED", "SELECTED"):
        household["state"] = "CERTIFIED"
        db.touch(household)

    event = lookup.maybe("lottery_event", household.get("lottery_event_id"))
    if event is not None and event.get("state") == "DRAWN":
        selected = event.get("selected_household_ids") or []
        if selected:
            everyone = True
            for household_id in selected:
                member = lookup.maybe("household", household_id)
                if member is None or member.get("state") != "CERTIFIED":
                    everyone = False
                    break
            if everyone:
                event["state"] = "COMPLETED"
                db.touch(event)

    project = lookup.maybe("project", unit.get("project_id"))
    if project is not None and project.get("state") == "AGREEMENT_RECORDED":
        project["state"] = "MONITORING"
        project_svc.refresh(project)


# --------------------------------------------------------------------------
@bp.route("/iz-compliance/income-certifications", methods=["POST"])
def create_certification():
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    household_id = mw.take_str(payload, "household_id")
    unit_id = mw.take_str(payload, "unit_id")
    certified_income = mw.take_int(payload, "certified_income_cents", lo=0)
    contract_rent = mw.take_int(payload, "contract_rent_cents", lo=0)
    effective_date = mw.take_date(payload, "effective_date")

    # rung 4 -- an OWNERSHIP unit carries no contract rent
    probe = lookup.maybe("unit", unit_id)
    if probe is not None and probe.get("tenure") == "OWNERSHIP" and contract_rent != 0:
        raise invalid("Field 'contract_rent_cents' must be 0 for an OWNERSHIP unit.")

    # rung 6
    household = lookup.fetch("household", household_id)
    unit = lookup.fetch("unit", unit_id)

    # rung 15
    if household.get("state") not in ("REGISTERED", "SELECTED"):
        raise ApiError("ERR_HOUSEHOLD_STATE_INVALID",
                       "Certification requires a REGISTERED or SELECTED household.")
    # rung 27
    ami = calc.select_ami_schedule()

    # rung 35
    _scan_period_overlap(unit, db.parse_date(effective_date))

    # rung 41
    income_limit_cents = calc.income_limit(ami, household.get("household_size"),
                                          unit.get("affordability_level_bps"))
    if certified_income > income_limit_cents:
        raise ApiError("ERR_HOUSEHOLD_NOT_ELIGIBLE",
                       "The certified income exceeds the unit's income limit.")
    if (unit.get("occupancy_status") == "RESERVED"
            and unit.get("occupant_household_id") != household_id):
        raise ApiError("ERR_HOUSEHOLD_NOT_ELIGIBLE",
                       "The unit is reserved for a different household.")

    if unit.get("tenure") == "OWNERSHIP":
        max_rent = 0
    else:
        max_rent = calc.max_allowed_rent(ami, unit.get("bedrooms"),
                                        unit.get("affordability_level_bps"))

    cert = db.insert(db.certifications, {
        "household_id": household_id,
        "unit_id": unit_id,
        "ami_schedule_year": int(ami.get("effective_year")),
        "certified_income_cents": certified_income,
        "contract_rent_cents": contract_rent,
        "income_limit_cents": income_limit_cents,
        "max_rent_cents": max_rent,
        "ami_pct_bps": calc.ami_pct_bps(ami, household.get("household_size"),
                                       certified_income),
        "effective_date": effective_date,
        "expires_at": calc.certification_expiry(effective_date, unit.get("tenure")),
        "state": "CERTIFIED",
        "certified_by_user_id": user_id,
        "is_recertification": False,
    })

    _cascade_certification(cert, unit, household)
    return response.created(db.public(cert))


@bp.route("/iz-compliance/income-certifications/<certification_id>", methods=["GET"])
def get_certification(certification_id):
    mw.auth(*BROAD_READ_ROLES)
    return response.ok(db.public(lookup.fetch("certification", certification_id)))


@bp.route("/iz-compliance/income-certifications", methods=["GET"])
def list_certifications():
    mw.auth(*BROAD_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.certifications,
                       ("household_id", "unit_id", "state", "is_recertification"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/income-certifications/<certification_id>/recertify",
          methods=["POST"])
def recertify(certification_id):
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    certified_income = mw.take_int(payload, "certified_income_cents", lo=0)
    contract_rent = mw.take_int(payload, "contract_rent_cents", lo=0)

    predecessor = lookup.fetch("certification", certification_id)
    unit = lookup.maybe("unit", predecessor.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")
    household = lookup.maybe("household", predecessor.get("household_id"))
    if household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")

    # rung 4 -- an OWNERSHIP unit carries no contract rent
    if unit.get("tenure") == "OWNERSHIP" and contract_rent != 0:
        raise invalid("Field 'contract_rent_cents' must be 0 for an OWNERSHIP unit.")

    # rung 16
    if predecessor.get("state") != "CERTIFIED":
        raise ApiError("ERR_CERTIFICATION_NOT_ACTIVE")
    # rung 27
    ami = calc.select_ami_schedule()

    expires_at = predecessor.get("expires_at")
    if expires_at:
        expiry_date = db.parse_date_loose(expires_at)
        new_start = expiry_date + timedelta(days=1)
        # rung 35 -- the successor abuts the predecessor without touching it
        _scan_period_overlap(unit, new_start, skip_ids=(predecessor["id"],))
        # rung 36
        window_opens = db.parse_dt(db.fmt_date(expiry_date)) - timedelta(
            days=calc.RECERT_WINDOW_DAYS)
        if db.logical_now() < window_opens:
            raise ApiError("ERR_RECERT_WINDOW_NOT_OPEN")
    else:
        # rung 57 -- an OWNERSHIP certification carries no term
        raise ApiError("ERR_RECERT_NOT_APPLICABLE")

    max_rent = calc.max_allowed_rent(ami, unit.get("bedrooms"),
                                    unit.get("affordability_level_bps"))
    income_limit_cents = calc.income_limit(ami, household.get("household_size"),
                                          unit.get("affordability_level_bps"))
    effective_date = new_start.isoformat()

    predecessor["state"] = "SUPERSEDED"
    db.touch(predecessor)

    successor = db.insert(db.certifications, {
        "household_id": predecessor["household_id"],
        "unit_id": predecessor["unit_id"],
        "ami_schedule_year": int(ami.get("effective_year")),
        "certified_income_cents": certified_income,
        "contract_rent_cents": contract_rent,
        "income_limit_cents": income_limit_cents,
        "max_rent_cents": max_rent,
        "ami_pct_bps": calc.ami_pct_bps(ami, household.get("household_size"),
                                       certified_income),
        "effective_date": effective_date,
        "expires_at": calc.certification_expiry(effective_date, unit.get("tenure")),
        "state": "CERTIFIED",
        "certified_by_user_id": user_id,
        "is_recertification": True,
    })

    unit["current_rent_cents"] = contract_rent
    unit["max_allowed_rent_cents"] = max_rent
    db.touch(unit)

    return response.created(db.public(successor))


# --------------------------------------------------------------------------
# Monitoring reviews
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/monitoring-reviews", methods=["POST"])
def create_review():
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    unit_id = mw.take_str(payload, "unit_id")
    review_year = mw.take_int(payload, "review_year", lo=2000, hi=2100)
    reported_rent = mw.take_int(payload, "reported_rent_cents", lo=0)
    reported_income = mw.take_int(payload, "reported_income_cents", lo=0)
    occupancy_verified = mw.take_bool(payload, "occupancy_verified")

    unit = lookup.fetch("unit", unit_id)

    # rung 29
    for existing in lookup.unit_reviews(unit_id):
        if int(existing.get("review_year")) == review_year:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A review for %s already exists on this unit." % review_year)

    occupant = lookup.maybe("household", unit.get("occupant_household_id"))
    ami = calc.active_ami_or_none()
    inputs = {
        "reported_rent_cents": reported_rent,
        "reported_income_cents": reported_income,
        "occupancy_verified": occupancy_verified,
    }
    findings = calc.monitoring_findings(unit, inputs, occupant, ami)
    overcharge = calc.overcharge_monthly(reported_rent, unit.get("max_allowed_rent_cents"))

    row = {
        "unit_id": unit_id,
        "review_year": review_year,
        "reported_rent_cents": reported_rent,
        "reported_income_cents": reported_income,
        "occupancy_verified": occupancy_verified,
        "state": "RECORDED",
        "finding_types": findings,
        "overcharge_monthly_cents": overcharge,
        "penalty_at_base_cents": 0,
        "cure_extension_days": 0,
        "cure_deadline": None,
        "penalty_final_cents": None,
        "finding_issued_at": None,
        "issued_by_user_id": None,
        "cure_submitted_at": None,
        "cleared_by_user_id": None,
        "corrected_rent_cents": None,
    }

    if findings:
        issued_at = db.fmt_dt(db.logical_now())
        base = calc.penalty_at_base(overcharge)
        extension = calc.cure_extension_for(base)
        row["state"] = "FINDING_ISSUED"
        row["finding_issued_at"] = issued_at
        row["issued_by_user_id"] = user_id
        row["penalty_at_base_cents"] = base
        row["cure_extension_days"] = extension
        row["cure_deadline"] = calc.cure_deadline(issued_at, extension)
    else:
        row["state"] = "COMPLIANT"

    review = db.insert(db.monitoring_reviews, row)

    if findings and unit.get("compliance_status") == "COMPLIANT":
        unit["compliance_status"] = "FINDING_OPEN"
        db.touch(unit)

    return response.created(db.public(review))


@bp.route("/iz-compliance/monitoring-reviews/<monitoring_review_id>", methods=["GET"])
def get_review(monitoring_review_id):
    mw.auth(*REVIEW_READ_ROLES)
    return response.ok(db.public(lookup.fetch("monitoring_review", monitoring_review_id)))


@bp.route("/iz-compliance/monitoring-reviews", methods=["GET"])
def list_reviews():
    mw.auth(*REVIEW_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.monitoring_reviews, ("unit_id", "state", "review_year"))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/monitoring-reviews/<monitoring_review_id>/submit-cure",
          methods=["POST"])
def submit_cure(monitoring_review_id):
    user_id, role = mw.auth(mw.DEVELOPER)
    payload = mw.body()
    corrected_rent = mw.take_int(payload, "corrected_rent_cents", lo=0)

    review = lookup.fetch("monitoring_review", monitoring_review_id)
    unit = lookup.maybe("unit", review.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")
    lookup.require_unit_owner_developer(unit, user_id, role)

    # rung 17
    previous_state = review.get("state")
    if previous_state not in ("FINDING_ISSUED", "ESCALATED"):
        raise ApiError("ERR_REVIEW_STATE_INVALID",
                       "A cure is submitted only from FINDING_ISSUED or ESCALATED.")

    now = db.logical_now()
    submitted_at = db.fmt_dt(now)
    review["cure_submitted_at"] = submitted_at
    review["corrected_rent_cents"] = corrected_rent
    review["penalty_final_cents"] = calc.penalty_final(
        review.get("overcharge_monthly_cents") or 0,
        review.get("finding_issued_at"), submitted_at)

    project = lookup.maybe("project", unit.get("project_id"))
    deadline = db.parse_dt(review.get("cure_deadline"))
    late = previous_state == "FINDING_ISSUED" and deadline is not None and now > deadline

    if previous_state == "FINDING_ISSUED" and not late:
        review["state"] = "CURE_SUBMITTED"
        db.touch(review)
        if unit.get("compliance_status") == "FINDING_OPEN":
            unit["compliance_status"] = "CURE_PENDING"
        unit["current_rent_cents"] = corrected_rent
        db.touch(unit)
    elif previous_state == "FINDING_ISSUED":
        review["state"] = "ESCALATED"
        db.touch(review)
        if unit.get("compliance_status") == "FINDING_OPEN":
            unit["compliance_status"] = "OUT_OF_COMPLIANCE"
            db.touch(unit)
            if project is not None:
                project_svc.refresh_posture(project)
    else:  # previous_state == ESCALATED -- re-enter the cure pipeline
        review["state"] = "CURE_SUBMITTED"
        db.touch(review)
        if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
            unit["compliance_status"] = "CURE_PENDING"
        unit["current_rent_cents"] = corrected_rent
        db.touch(unit)
        if project is not None:
            project_svc.refresh_posture(project)

    return response.ok(db.public(review))


@bp.route("/iz-compliance/monitoring-reviews/<monitoring_review_id>/clear-cure",
          methods=["POST"])
def clear_cure(monitoring_review_id):
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    mw.body()

    review = lookup.fetch("monitoring_review", monitoring_review_id)
    unit = lookup.maybe("unit", review.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")

    # rung 17
    if review.get("state") != "CURE_SUBMITTED":
        raise ApiError("ERR_REVIEW_STATE_INVALID",
                       "A cure is cleared only from CURE_SUBMITTED.")
    # rung 21
    if user_id == review.get("issued_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who issued the finding may not clear its cure.")
    # rung 23
    if int(review.get("corrected_rent_cents") or 0) > int(unit.get("max_allowed_rent_cents") or 0):
        raise ApiError("ERR_CURE_INSUFFICIENT")

    review["state"] = "CURED"
    review["cleared_by_user_id"] = user_id
    db.touch(review)

    if unit.get("compliance_status") == "CURE_PENDING":
        unit["compliance_status"] = "COMPLIANT"
        db.touch(unit)
        project = lookup.maybe("project", unit.get("project_id"))
        if project is not None:
            project_svc.refresh_posture(project)

    return response.ok(db.public(review))


@bp.route("/iz-compliance/monitoring-reviews/<monitoring_review_id>/escalate",
          methods=["POST"])
def escalate(monitoring_review_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    mw.body()

    review = lookup.fetch("monitoring_review", monitoring_review_id)
    unit = lookup.maybe("unit", review.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")

    # rung 17
    if review.get("state") != "CURE_SUBMITTED":
        raise ApiError("ERR_REVIEW_STATE_INVALID",
                       "A review is escalated only from CURE_SUBMITTED.")

    review["state"] = "ESCALATED"
    db.touch(review)

    if unit.get("compliance_status") == "CURE_PENDING":
        unit["compliance_status"] = "OUT_OF_COMPLIANCE"
        db.touch(unit)
        project = lookup.maybe("project", unit.get("project_id"))
        if project is not None:
            project_svc.refresh_posture(project)

    return response.ok(db.public(review))
