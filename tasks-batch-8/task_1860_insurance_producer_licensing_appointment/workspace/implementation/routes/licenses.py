"""License endpoints (PRD 3.1, 3.3): creation, renewal, reinstatement."""

from decimal import Decimal

from flask import Blueprint

from core import calc, constants as K
from core.clock import add_days, add_months
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, opt_number, producer_scope, req_dt, req_enum, req_int,
    req_loa_list, req_str, require_exactly_one_subject, resolve,
    resolve_subject_refs, subject_ids,
)
from core.serialize import license_ as serialize_license
from core.store import db, new_row, bump

bp = Blueprint("licenses", __name__)

_READ_ROLES = (
    "LicensingCoordinator", "ComplianceOfficer", "FinanceOps",
    "CarrierAdmin", "Producer",
)
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


@bp.route("/api/licenses", methods=["POST"])
def create_license():
    ctx = authorize("LicensingCoordinator")
    # Malformed-request checks (ERR_INVALID_REQUEST).
    producer_id, agency_id = subject_ids(ctx)
    state_code = req_str(ctx.body, "state_code")
    license_class = req_enum(ctx.body, "license_class", K.LICENSE_CLASSES)
    loas = req_loa_list(ctx.body, "lines_of_authority")
    issue_date = req_dt(ctx.body, "issue_date")
    expiration_date = req_dt(ctx.body, "expiration_date")
    if not expiration_date > issue_date:
        fail("ERR_INVALID_REQUEST", "expiration_date must be strictly after issue_date.")
    ce_required = opt_number(ctx.body, "ce_required_hours", K.DEFAULT_REQUIRED_HOURS)
    ce_ethics_required = opt_number(
        ctx.body, "ce_ethics_required_hours", K.DEFAULT_ETHICS_HOURS
    )
    if ce_required < 0 or ce_ethics_required < 0:
        fail("ERR_INVALID_REQUEST", "CE hour requirements must be non-negative.")
    # Existence of body FK references, left to right.
    resolve_subject_refs(ctx, producer_id, agency_id)
    # Subject exclusivity (section 2.6).
    require_exactly_one_subject(producer_id, agency_id)
    # One non-terminal license per (subject, state).
    subject_field = "producer_id" if producer_id is not None else "agency_id"
    subject_id = producer_id if producer_id is not None else agency_id
    for lic in calc.licenses_of_subject(subject_field, subject_id, state_code):
        if lic["status"] != "REVOKED":
            fail(
                "ERR_DUPLICATE_LICENSE",
                "A non-terminal license already exists for this subject and state.",
            )
    row = new_row("licenses", {
        "producer_id": producer_id,
        "agency_id": agency_id,
        "state_code": state_code,
        "license_class": license_class,
        "lines_of_authority": loas,
        "status": "ACTIVE",
        "issue_date": issue_date,
        "expiration_date": expiration_date,
        "ce_period_start": issue_date,
        "ce_period_end": expiration_date,
        "ce_required_hours": ce_required,
        "ce_ethics_required_hours": ce_ethics_required,
        "ce_completed_hours": Decimal("0"),
        "ce_ethics_completed_hours": Decimal("0"),
        "renewed_count": 0,
    })
    return object_response(serialize_license(row), 201)


@bp.route("/api/licenses/<licenseId>", methods=["GET"])
def get_license(licenseId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("licenses", licenseId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_license(row), 200)


@bp.route("/api/licenses", methods=["GET"])
def list_licenses():
    authorize(*_LIST_ROLES)
    rows = db.ordered("licenses")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "agency_id")
    rows = filter_exact(rows, "state_code")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_license)


@bp.route("/api/licenses/<licenseId>/renew", methods=["POST"])
def renew_license(licenseId):
    ctx = authorize("LicensingCoordinator")
    lic = resolve("licenses", licenseId)
    expected = req_int(ctx.body, "expected_license_version")
    # State precondition: only ACTIVE and EXPIRED have renew transitions.
    if lic["status"] not in ("ACTIVE", "EXPIRED"):
        fail("ERR_INVALID_STATE", "License in status {} cannot be renewed.".format(lic["status"]))
    # Preconditions in the PRD 3.3 order: OCC, then window, then CE.
    if expected != lic["version"]:
        fail("ERR_STALE_VERSION", "expected_license_version does not match the license version.")
    now = db.now
    expiration = lic["expiration_date"]
    if lic["status"] == "ACTIVE":
        window_open = add_days(expiration, -K.RENEWAL_WINDOW_DAYS_BEFORE)
        if not (window_open <= now <= expiration):
            fail("ERR_RENEWAL_WINDOW_CLOSED", "Renewal window is not open.")
    else:
        grace_close = add_days(expiration, K.RENEWAL_GRACE_DAYS_AFTER)
        if not (expiration < now <= grace_close):
            fail("ERR_RENEWAL_WINDOW_CLOSED", "Renewal grace window is not open.")
    compliant, _, _ = calc.ce_determination(lic)
    if not compliant:
        fail("ERR_CE_INCOMPLETE", "CE compliance determination is not COMPLIANT.")
    prior_period_end = lic["ce_period_end"]
    new_expiration = add_months(expiration, K.RENEWAL_EXTENSION_MONTHS)
    lic["expiration_date"] = new_expiration
    lic["ce_period_start"] = prior_period_end
    lic["ce_period_end"] = new_expiration
    lic["ce_completed_hours"] = Decimal("0")
    lic["ce_ethics_completed_hours"] = Decimal("0")
    lic["renewed_count"] = lic["renewed_count"] + 1
    if lic["status"] == "EXPIRED":
        lic["status"] = "ACTIVE"
    bump(lic)
    return object_response(serialize_license(lic), 200)


@bp.route("/api/licenses/<licenseId>/reinstate", methods=["POST"])
def reinstate_license(licenseId):
    authorize("ComplianceOfficer")
    lic = resolve("licenses", licenseId)
    if lic["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a SUSPENDED license can be reinstated.")
    lic["status"] = "ACTIVE"
    bump(lic)
    return object_response(serialize_license(lic), 200)
