"""Employers, tax agencies, agency-account registrations and employees (PRD 3.1)."""

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_ANALYST, R_AUDITOR, R_EMPLOYER, R_OFFICER, READ6, AGENCY_CODE_RE,
    FEIN_RE, JURISDICTION_RE, LAST4_RE, STATE_RE, ALL_ROLES,
    authenticate, cents, db, fail, get_account, get_agency, get_employee, get_employer,
    get_body, matches, new_row, now, ok, OPEN_ENDED_ORDINAL, pagination, paginate,
    period_ordinal, qs, qs_bool, qs_int, require_state, sorted_rows, touch, validate,
)
from serializers import account_json, agency_json, employee_json, employer_json

bp = Blueprint("reference", __name__)


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

EMPLOYER_CREATE = {
    "legal_name": F("string", True, min_len=1, max_len=120),
    "fein": F("string", True, pattern=FEIN_RE),
    "deposit_schedule": F("string", True, enum=("MONTHLY", "SEMIWEEKLY")),
    "authorization_limit_cents": cents(True),
}

EMPLOYER_PATCH = {
    "deposit_schedule": F("string", False, enum=("MONTHLY", "SEMIWEEKLY")),
    "authorization_limit_cents": cents(False),
}


@bp.post("/employers")
def create_employer():
    authenticate((R_ADMIN,))
    body = get_body()
    data = validate(body, EMPLOYER_CREATE)
    for row in db.employers.values():
        if row["fein"] == data["fein"]:
            fail("ERR_DUPLICATE_EMPLOYER_FEIN", "fein is already registered")
    row = new_row({
        "legal_name": data["legal_name"],
        "fein": data["fein"],
        "deposit_schedule": data["deposit_schedule"],
        "authorization_limit_cents": data["authorization_limit_cents"],
        "open_exposure_cents": 0,
        "open_remediation_count": 0,
        "granted_abatement_count": 0,
    })
    db.employers[row["id"]] = row
    return ok(employer_json(row), 201)


@bp.get("/employers/<employer_id>")
def read_employer(employer_id):
    actor = authenticate(READ6)
    row = get_employer(employer_id)
    actor.require_employer(row["id"])
    return ok(employer_json(row))


@bp.get("/employers")
def list_employers():
    authenticate((R_ADMIN, R_ANALYST, R_OFFICER, R_AUDITOR))
    limit, offset = pagination()
    filters = {"fein": qs("fein"), "deposit_schedule": qs("deposit_schedule")}
    rows = [r for r in sorted_rows(db.employers.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, employer_json)


@bp.patch("/employers/<employer_id>")
def patch_employer(employer_id):
    authenticate((R_ADMIN,))
    row = get_employer(employer_id)
    body = get_body()
    data = validate(body, EMPLOYER_PATCH)
    for field in ("deposit_schedule", "authorization_limit_cents"):
        if field in data:
            row[field] = data[field]
    touch(row)
    return ok(employer_json(row))


# ---------------------------------------------------------------------------
# Tax agencies
# ---------------------------------------------------------------------------

AGENCY_CREATE = {
    "agency_code": F("string", True, pattern=AGENCY_CODE_RE),
    "level": F("string", True, enum=("FEDERAL", "STATE", "LOCAL")),
    "jurisdiction_code": F("string", True, pattern=JURISDICTION_RE),
    "interest_rate_bps_annual": F("integer", True, minimum=0, maximum=10000),
    "interest_method": F("string", True, enum=("STATUTORY_DAILY", "DEPOSIT_WEIGHTED")),
    "penalty_multiplier_bps": F("integer", True, minimum=0, maximum=20000),
    "min_days_between_amendments": F("integer", True, minimum=0),
    "amendment_window_days": F("integer", True, minimum=1),
    "requires_registration": F("boolean", False),
}


@bp.post("/tax-agencies")
def create_agency():
    authenticate((R_ADMIN,))
    body = get_body()
    data = validate(body, AGENCY_CREATE)
    for row in db.tax_agencies.values():
        if row["agency_code"] == data["agency_code"]:
            fail("ERR_DUPLICATE_AGENCY_CODE", "agency_code is already registered")
    row = new_row({
        "agency_code": data["agency_code"],
        "level": data["level"],
        "jurisdiction_code": data["jurisdiction_code"],
        "interest_rate_bps_annual": data["interest_rate_bps_annual"],
        "interest_method": data["interest_method"],
        "penalty_multiplier_bps": data["penalty_multiplier_bps"],
        "min_days_between_amendments": data["min_days_between_amendments"],
        "amendment_window_days": data["amendment_window_days"],
        "requires_registration": data.get("requires_registration", False),
    })
    db.tax_agencies[row["id"]] = row
    return ok(agency_json(row), 201)


@bp.get("/tax-agencies/<tax_agency_id>")
def read_agency(tax_agency_id):
    authenticate(READ6)
    return ok(agency_json(get_agency(tax_agency_id)))


@bp.get("/tax-agencies")
def list_agencies():
    authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "level": qs("level"),
        "jurisdiction_code": qs("jurisdiction_code"),
        "interest_method": qs("interest_method"),
    }
    rows = [r for r in sorted_rows(db.tax_agencies.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, agency_json)


# ---------------------------------------------------------------------------
# Agency accounts (registration coverage)
# ---------------------------------------------------------------------------

ACCOUNT_CREATE = {
    "employer_id": F("string", True),
    "agency_id": F("string", True),
    "account_number": F("string", False, min_len=1, max_len=64),
    "effective_from_tax_year": F("integer", True, minimum=2000, maximum=2100),
    "effective_from_quarter": F("integer", True, minimum=1, maximum=4),
    "effective_to_tax_year": F("integer", False, minimum=2000, maximum=2100),
    "effective_to_quarter": F("integer", False, minimum=1, maximum=4),
    "retroactive": F("boolean", False),
}


def _overlap_check(employer_id, agency_id, from_ord, to_ord, skip_id=None):
    for row in db.agency_accounts.values():
        if row["employer_id"] != employer_id or row["agency_id"] != agency_id:
            continue
        if skip_id is not None and row["id"] == skip_id:
            continue
        if row["registration_status"] not in calc.OCCUPYING_ACCOUNT_STATES:
            continue
        if from_ord <= row["to_period_ordinal"] and row["from_period_ordinal"] <= to_ord:
            fail("ERR_ACCOUNT_PERIOD_OVERLAP",
                 "coverage overlaps an existing registration for this employer and agency")


@bp.post("/agency-accounts")
def create_account():
    actor = authenticate((R_ADMIN, R_ANALYST))
    body = get_body()
    employer = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    data = validate(body, ACCOUNT_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])

    from_ord = period_ordinal(data["effective_from_tax_year"], data["effective_from_quarter"])
    to_year = data.get("effective_to_tax_year")
    to_quarter = data.get("effective_to_quarter")
    if to_year is None:
        to_ord = OPEN_ENDED_ORDINAL
        to_quarter = None
    else:
        if to_quarter is None:
            fail("ERR_INVALID_REQUEST",
                 "effective_to_quarter is required when effective_to_tax_year is supplied")
        to_ord = period_ordinal(to_year, to_quarter)

    _overlap_check(data["employer_id"], data["agency_id"], from_ord, to_ord)

    retroactive = data.get("retroactive", False)
    row = new_row({
        "employer_id": data["employer_id"],
        "agency_id": data["agency_id"],
        "account_number": data.get("account_number"),
        "effective_from_tax_year": data["effective_from_tax_year"],
        "effective_from_quarter": data["effective_from_quarter"],
        "effective_to_tax_year": to_year,
        "effective_to_quarter": to_quarter,
        "retroactive": retroactive,
        "registration_status": "RETRO_PENDING" if retroactive else "PENDING",
        "from_period_ordinal": from_ord,
        "to_period_ordinal": to_ord,
        "activated_at": None,
    })
    db.agency_accounts[row["id"]] = row
    return ok(account_json(row), 201)


@bp.get("/agency-accounts/<agency_account_id>")
def read_account(agency_account_id):
    actor = authenticate(READ6)
    row = get_account(agency_account_id)
    actor.require_employer(row["employer_id"])
    return ok(account_json(row))


@bp.get("/agency-accounts")
def list_accounts():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "agency_id": qs("agency_id"),
        "registration_status": qs("registration_status"),
        "retroactive": qs_bool("retroactive"),
    }
    rows = [r for r in sorted_rows(db.agency_accounts.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, account_json)


@bp.post("/agency-accounts/<agency_account_id>/activate")
def activate_account(agency_account_id):
    authenticate((R_ADMIN, R_ANALYST))
    row = get_account(agency_account_id)
    body = get_body()
    data = validate(body, {"account_number": F("string", True, min_len=1, max_len=64)})
    require_state(row["registration_status"], ("PENDING", "RETRO_PENDING"), ("CLOSED",))

    row["account_number"] = data["account_number"]
    row["activated_at"] = now()
    row["registration_status"] = "RETRO_ACTIVE" if row["registration_status"] == "RETRO_PENDING" else "ACTIVE"
    touch(row)

    # Succession: activating a directly-adjacent successor retires the predecessor.
    for other in sorted_rows(db.agency_accounts.values()):
        if other["id"] == row["id"]:
            continue
        if other["employer_id"] != row["employer_id"] or other["agency_id"] != row["agency_id"]:
            continue
        if other["registration_status"] != "ACTIVE":
            continue
        if other["to_period_ordinal"] == OPEN_ENDED_ORDINAL:
            continue
        if row["from_period_ordinal"] == other["to_period_ordinal"] + 1:
            other["registration_status"] = "CLOSED"
            touch(other)
    return ok(account_json(row))


@bp.post("/agency-accounts/<agency_account_id>/close")
def close_account(agency_account_id):
    authenticate((R_ADMIN,))
    row = get_account(agency_account_id)
    body = get_body()
    data = validate(body, {
        "effective_to_tax_year": F("integer", True, minimum=2000, maximum=2100),
        "effective_to_quarter": F("integer", True, minimum=1, maximum=4),
    })
    require_state(row["registration_status"], ("ACTIVE", "RETRO_ACTIVE"), ("CLOSED",))
    row["effective_to_tax_year"] = data["effective_to_tax_year"]
    row["effective_to_quarter"] = data["effective_to_quarter"]
    row["to_period_ordinal"] = period_ordinal(data["effective_to_tax_year"],
                                              data["effective_to_quarter"])
    row["registration_status"] = "CLOSED"
    touch(row)
    return ok(account_json(row))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

EMPLOYEE_CREATE = {
    "employer_id": F("string", True),
    "full_name": F("string", True, min_len=1, max_len=120),
    "national_id_last4": F("string", True, pattern=LAST4_RE),
    "mailing_state_code": F("string", True, pattern=STATE_RE),
}


@bp.post("/employees")
def create_employee():
    actor = authenticate((R_ADMIN, R_ANALYST, R_EMPLOYER))
    body = get_body()
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        get_employer(body["employer_id"])
    data = validate(body, EMPLOYEE_CREATE)
    actor.require_employer(data["employer_id"])
    row = new_row({
        "employer_id": data["employer_id"],
        "full_name": data["full_name"],
        "national_id_last4": data["national_id_last4"],
        "mailing_state_code": data["mailing_state_code"],
        "active_statement_count": 0,
    })
    db.employees[row["id"]] = row
    return ok(employee_json(row), 201)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    actor = authenticate(ALL_ROLES)
    row = get_employee(employee_id)
    actor.require_employer(row["employer_id"])
    actor.require_employee(row["id"])
    return ok(employee_json(row))


@bp.get("/employees")
def list_employees():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "mailing_state_code": qs("mailing_state_code"),
    }
    rows = [r for r in sorted_rows(db.employees.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, employee_json)
