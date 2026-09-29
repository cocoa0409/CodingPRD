"""Customers, age attestation and identity pre-verification checks."""
from decimal import Decimal

from flask import Blueprint, g

from db import (
    GLOBAL_MIN_ATTESTATION_AGE_YEARS,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    CUSTOMER,
    PLATFORM_ADMIN,
    auth,
    fetch,
    scope_if,
)
from response import created, listing, ok, pagination, public
from services.calc import identity_confidence
from services.parties import rederive_latest_identity_result
from util import add_days, completed_years, fmt_dt, parse_date, parse_dt
import validate as v

bp = Blueprint("customers", __name__)

ATTESTATION_CHANNELS = ("WEB_CHECKBOX", "MOBILE_APP", "PHONE_AGENT")
ATTESTATION_STATES = ("NOT_ATTESTED", "ATTESTED", "ATTESTATION_REJECTED")
IDENTITY_RESULTS = ("NONE", "MATCH", "PARTIAL", "NO_MATCH")
PROVIDERS = ("STATE_DMV_GATEWAY", "NATIONAL_ID_VENDOR", "TELCO_VERIFY")
SIGNAL_TYPES = ("GOVERNMENT_ID_DB", "CREDIT_BUREAU", "MOBILE_CARRIER", "WATCHLIST_NEGATIVE")
CHECK_STATUSES = ("VALID", "EXPIRED", "SUPERSEDED")


@bp.post("/customers")
def create_customer():
    auth(PLATFORM_ADMIN)
    body = v.body()
    full_name = v.req_str(body, "full_name")
    email = v.req_str(body, "email")
    jurisdiction_id = body.get("jurisdiction_id")
    if not isinstance(jurisdiction_id, str) or jurisdiction_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "jurisdiction_id is required")
    fetch("jurisdictions", jurisdiction_id)
    for existing in db.customers.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_CODE", "email is already in use")
    row = new_row(
        full_name=full_name,
        email=email,
        jurisdiction_id=jurisdiction_id,
        attested_dob=None,
        attestation_at=None,
        attestation_channel=None,
        attestation_state="NOT_ATTESTED",
        latest_identity_check_result="NONE",
        refusal_strikes=0,
        blocked_until=None,
    )
    db.customers[row["id"]] = row
    return created(public(row))


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, CUSTOMER)
    scope_if(CUSTOMER, customer_id)
    return ok(public(fetch("customers", customer_id)))


@bp.get("/customers")
def list_customers():
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER)
    jurisdiction_id = v.str_filter("jurisdiction_id")
    attestation_state = v.enum_filter("attestation_state", ATTESTATION_STATES)
    identity_result = v.enum_filter("latest_identity_check_result", IDENTITY_RESULTS)
    email = v.str_filter("email")
    limit, offset = pagination()
    rows = list(db.customers.values())
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if attestation_state is not None:
        rows = [r for r in rows if r["attestation_state"] == attestation_state]
    if identity_result is not None:
        rows = [r for r in rows if r["latest_identity_check_result"] == identity_result]
    if email is not None:
        rows = [r for r in rows if r["email"] == email]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


@bp.post("/customers/<customer_id>/age-attestation")
def attest_age(customer_id):
    """Recording an under-age attestation is a legitimate outcome, not an error."""
    auth(CUSTOMER)
    scope_if(CUSTOMER, customer_id)
    customer = fetch("customers", customer_id)
    body = v.body()
    attested_dob = v.req_date(body, "attested_dob")
    channel = v.req_enum(body, "attestation_channel", ATTESTATION_CHANNELS)
    stamp = now()
    age = completed_years(attested_dob, stamp.date())
    customer["attested_dob"] = attested_dob.isoformat()
    customer["attestation_channel"] = channel
    customer["attestation_at"] = fmt_dt(stamp)
    customer["attestation_state"] = (
        "ATTESTED" if age >= GLOBAL_MIN_ATTESTATION_AGE_YEARS else "ATTESTATION_REJECTED"
    )
    touch(customer)
    return ok(public(customer))


@bp.post("/customers/<customer_id>/identity-checks")
def create_identity_check(customer_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER)
    customer = fetch("customers", customer_id)
    body = v.body()
    expected_version = v.opt_int(body, "expected_customer_version")
    provider = v.req_enum(body, "provider", PROVIDERS)
    provided_dob = v.req_date(body, "provided_dob")
    source_dob = v.req_date(body, "source_dob")
    signals = v.req_signal_list(body, "source_signals", SIGNAL_TYPES)
    validity_days = v.req_int(body, "validity_days", 1, 365)

    # tier 8 -- a repeated source_type inside one body
    seen = set()
    for signal in signals:
        if signal["source_type"] in seen:
            raise ApiError("ERR_INCONSISTENT_FIELDS", "source_signals repeats a source_type")
        seen.add(signal["source_type"])

    # tier 9 -- optimistic concurrency on the parent customer
    if expected_version is not None and expected_version != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION")

    confidence, result, verified_dob = identity_confidence(signals, provided_dob, source_dob)

    # Every earlier VALID check of this customer is superseded.
    for existing in sorted(db.identity_checks.values(), key=sort_key):
        if existing["customer_id"] != customer_id:
            continue
        if existing["status"] == "VALID":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_row(
        customer_id=customer_id,
        provider=provider,
        provided_dob=provided_dob.isoformat(),
        source_dob=source_dob.isoformat(),
        source_signals=[dict(s) for s in signals],
        confidence=confidence,
        result=result,
        verified_dob=verified_dob.isoformat() if verified_dob is not None else None,
        status="VALID",
        validity_days=validity_days,
        expires_at=None,
    )
    row["expires_at"] = fmt_dt(add_days(parse_dt(row["created_at"]), validity_days))
    db.identity_checks[row["id"]] = row

    customer["latest_identity_check_result"] = result
    touch(customer)
    return created(public(row))


@bp.get("/customers/<customer_id>/identity-checks")
def list_identity_checks(customer_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER)
    fetch("customers", customer_id)
    status = v.enum_filter("status", CHECK_STATUSES)
    result = v.enum_filter("result", IDENTITY_RESULTS[1:])
    limit, offset = pagination()
    rows = [c for c in db.identity_checks.values() if c["customer_id"] == customer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)
