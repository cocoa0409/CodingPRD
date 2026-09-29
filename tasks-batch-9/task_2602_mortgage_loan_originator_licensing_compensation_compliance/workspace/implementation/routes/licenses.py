"""State licence filing, activation, the renewal cycle, reinstatement, the three
retiring actions and sponsorship claims."""
from datetime import timedelta

from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import (filters, gate, get_or_404, get_referenced, listing,
                           matches)
from services import audit, authority, calc, cascade, ce
from validators import Body, STATE_RE, body_fk, raw_body

bp = Blueprint("licenses", __name__)

UNRETIRED_STATUSES = ("PENDING", "ACTIVE", "RENEWAL_PENDING", "EXPIRED")
STATUS_ACTIONS = ("SURRENDER", "REVOKE", "REINSTATE")
RENEWAL_TERM_DAYS = 365
REINSTATEMENT_TERM_DAYS = 365
REINSTATEMENT_WINDOW_DAYS = 305
REINSTATEMENT_LIMIT = 2


@bp.route("/license-registrations", methods=["POST"])
@endpoint("LicensingAnalyst")
def file_license():
    raw = raw_body()
    originator_ref = body_fk(raw, "originator_id")
    originator = None
    if originator_ref is not None:
        originator = get_referenced(db.originators, originator_ref)
    body = Body(raw)
    body.string("originator_id")
    state_code = body.string("state_code", pattern=STATE_RE)
    license_number = body.string("license_number", min_len=4, max_len=32)
    issue_date = body.datetime("issue_date")
    expiration_date = body.datetime("expiration_date")
    renewal_window_opens_at = body.datetime("renewal_window_opens_at")
    ce_reporting_year = body.integer("ce_reporting_year", minimum=2020, maximum=2100)
    required_ce_hours = body.integer("required_ce_hours", required=False, default=8,
                                     minimum=8, maximum=20)
    if not expiration_date > issue_date:
        raise bad_request("expiration_date must fall strictly after issue_date.")
    if not renewal_window_opens_at < expiration_date:
        raise bad_request("renewal_window_opens_at must fall strictly before expiration_date.")

    for row in db.license_registrations.values():
        if (row["originator_id"] == originator["id"]
                and row["state_code"] == state_code
                and row["status"] in UNRETIRED_STATUSES):
            raise ApiError("ERR_DUPLICATE_KEY")

    row = create(db.license_registrations, {
        "originator_id": originator["id"],
        "state_code": state_code,
        "license_number": license_number,
        "issue_date": issue_date,
        "expiration_date": expiration_date,
        "renewal_window_opens_at": renewal_window_opens_at,
        "status": "PENDING",
        "authority_effective_at": None,
        "required_ce_hours": required_ce_hours,
        "ce_hours_applied": 0,
        "ce_reporting_year": ce_reporting_year,
        "ce_satisfied": False,
        "active_sponsoring_institution_code": None,
        "active_sponsorship_effective_at": None,
        "reinstatement_count": 0,
    })
    return created(serializers.license_registration(row))


@bp.route("/license-registrations", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_licenses():
    active = filters("originator_id", "state_code", "status")
    rows = listing(db.license_registrations, lambda r: matches(r, active))
    return paginated(rows, serializers.license_registration)


@bp.route("/license-registrations/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_license(row_id):
    row = get_or_404(db.license_registrations, row_id)
    return ok(serializers.license_registration(row))


@bp.route("/license-registrations/<row_id>/activations", methods=["POST"])
@endpoint("LicensingAnalyst")
def activate_license(row_id):
    lic = get_or_404(db.license_registrations, row_id)
    gate("LicenseRegistration", lic, ("PENDING",))
    originator = db.originators[lic["originator_id"]]
    if originator["employment_status"] != "EMPLOYED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not db.clock < lic["expiration_date"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    lic["status"] = "ACTIVE"
    lic["authority_effective_at"] = db.clock
    touch(lic)
    audit.append("LicenseRegistration", lic["id"], "LICENSE_STATUS_CHANGED",
                 {"status": "ACTIVE", "authority_effective_at": True})
    return ok(serializers.license_registration(lic))


@bp.route("/license-registrations/<row_id>/renewal-requests", methods=["POST"])
@endpoint("LicensingAnalyst")
def request_renewal(row_id):
    lic = get_or_404(db.license_registrations, row_id)
    gate("LicenseRegistration", lic, ("ACTIVE",))
    if not (lic["renewal_window_opens_at"] <= db.clock < lic["expiration_date"]):
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED")
    lic["status"] = "RENEWAL_PENDING"
    touch(lic)
    # RENEWAL_PENDING authorises exactly as ACTIVE does, so authority is unchanged.
    ce.recompute_license_ce(lic, calc.CALENDAR_YEAR_ATTRIBUTION)
    audit.append("LicenseRegistration", lic["id"], "LICENSE_STATUS_CHANGED",
                 {"status": "RENEWAL_PENDING"})
    return ok(serializers.license_registration(lic))


@bp.route("/license-registrations/<row_id>/renewal-completions", methods=["POST"])
@endpoint("LicensingAnalyst")
def complete_renewal(row_id):
    lic = get_or_404(db.license_registrations, row_id)
    gate("LicenseRegistration", lic, ("RENEWAL_PENDING",))
    # The recompute happens BEFORE the gate is evaluated.
    ce.recompute_license_ce(lic, calc.MAKEUP_ATTRIBUTION)
    if not lic["ce_satisfied"] or ce.voided_credit_counted_toward(lic):
        raise ApiError("ERR_CE_HOURS_INSUFFICIENT")
    lic["status"] = "ACTIVE"
    lic["expiration_date"] = lic["expiration_date"] + timedelta(days=RENEWAL_TERM_DAYS)
    lic["renewal_window_opens_at"] = (lic["renewal_window_opens_at"]
                                      + timedelta(days=RENEWAL_TERM_DAYS))
    lic["ce_reporting_year"] = lic["ce_reporting_year"] + 1
    lic["ce_hours_applied"] = 0
    lic["ce_satisfied"] = False
    touch(lic)
    # authority_effective_at is deliberately left alone: authority never lapsed.
    ce.recompute_license_ce(lic, calc.MAKEUP_ATTRIBUTION)
    audit.append("LicenseRegistration", lic["id"], "LICENSE_STATUS_CHANGED",
                 {"status": "ACTIVE", "ce_reporting_year": lic["ce_reporting_year"]})
    return ok(serializers.license_registration(lic))


@bp.route("/license-registrations/<row_id>/status-actions", methods=["POST"])
@endpoint("LicensingAnalyst")
def license_status_action(row_id):
    lic = get_or_404(db.license_registrations, row_id)
    body = Body(raw_body())
    action = body.enum("action", STATUS_ACTIONS)
    note = body.string("note", required=False, default=None, max_len=2000)
    detail = {"action": action}
    if note is not None:
        detail["note"] = note

    if action == "SURRENDER":
        gate("LicenseRegistration", lic, ("ACTIVE", "RENEWAL_PENDING"))
        for loan in db.loan_applications.values():
            if (loan["originator_id"] == lic["originator_id"]
                    and loan["state_code"] == lic["state_code"]
                    and loan["status"] in ("TAKEN", "LOCKED")):
                raise ApiError("ERR_OPEN_PIPELINE_BLOCKS_SURRENDER")
        lic["status"] = "SURRENDERED"
        touch(lic)
        detail["status"] = "SURRENDERED"
        cascade.authority_lapse(lic, full=False, system=False, detail=detail)
        return ok(serializers.license_registration(lic))

    if action == "REVOKE":
        gate("LicenseRegistration", lic, ("ACTIVE", "RENEWAL_PENDING", "EXPIRED"))
        lic["status"] = "REVOKED"
        touch(lic)
        detail["status"] = "REVOKED"
        cascade.authority_lapse(lic, full=True, system=False, detail=detail)
        return ok(serializers.license_registration(lic))

    gate("LicenseRegistration", lic, ("EXPIRED",))
    if not lic["ce_satisfied"]:
        raise ApiError("ERR_CE_HOURS_INSUFFICIENT")
    if lic["reinstatement_count"] >= REINSTATEMENT_LIMIT:
        raise ApiError("ERR_REINSTATEMENT_LIMIT_REACHED")
    originator = db.originators[lic["originator_id"]]
    if originator["employment_status"] != "EMPLOYED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    lic["status"] = "ACTIVE"
    lic["reinstatement_count"] = lic["reinstatement_count"] + 1
    lic["expiration_date"] = db.clock + timedelta(days=REINSTATEMENT_TERM_DAYS)
    lic["renewal_window_opens_at"] = db.clock + timedelta(days=REINSTATEMENT_WINDOW_DAYS)
    # Re-stamped, so the pre-lapse interval never retroactively authorises.
    lic["authority_effective_at"] = db.clock
    touch(lic)
    detail["status"] = "ACTIVE"
    audit.append("LicenseRegistration", lic["id"], "LICENSE_STATUS_CHANGED", detail)
    return ok(serializers.license_registration(lic))


@bp.route("/license-registrations/<row_id>/sponsorship-transfers", methods=["POST"])
@endpoint("LicensingAnalyst")
def claim_sponsorship(row_id):
    lic = get_or_404(db.license_registrations, row_id)
    body = Body(raw_body())
    institution_code = body.string("sponsoring_institution_code", min_len=4, max_len=12)
    effective_at = body.datetime("effective_at")
    expected_version = body.integer("expected_license_registration_version")

    if expected_version != lic["version"]:
        raise ApiError("ERR_STALE_LICENSE_VERSION")

    existing = authority.transfers_of(lic["id"])
    for row in existing:
        if row["status"] in ("RELINQUISHED", "SUPERSEDED"):
            if (row["effective_at"] <= effective_at
                    and row["relinquished_at"] is not None
                    and row["relinquished_at"] > effective_at):
                raise ApiError("ERR_SPONSORSHIP_PERIOD_OVERLAP")
        if effective_at < row["effective_at"]:
            raise ApiError("ERR_SPONSORSHIP_PERIOD_OVERLAP")

    previous = authority.active_transfer(lic["id"])
    row = create(db.sponsorship_transfers, {
        "license_registration_id": lic["id"],
        "sponsoring_institution_code": institution_code,
        "effective_at": effective_at,
        "relinquished_at": None,
        "status": "ACTIVE",
        "superseded_by_created_at": None,
    })
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["relinquished_at"] = effective_at
        previous["superseded_by_created_at"] = row["created_at"]
        touch(previous)
        audit.append("SponsorshipTransfer", previous["id"], "SPONSORSHIP_CHANGED",
                     {"status": "SUPERSEDED",
                      "superseded_by_sponsorship_transfer_id": row["id"],
                      "license_registration_id": lic["id"]})
    lic["active_sponsoring_institution_code"] = institution_code
    lic["active_sponsorship_effective_at"] = effective_at
    touch(lic)
    return created(serializers.sponsorship_transfer(row))
