"""Contacts, the reassigned-number check and the revocation reverse lookup (§3.1)."""

from flask import Blueprint

import lookup
import validation as v
from calculations import RND_VALIDITY_DAYS
from db import base_row, by_created_at, db, now_iso, public
from derive import contact_view, revocations_of_contact, touch_contact
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import parse_date

bp = Blueprint("contacts", __name__)

ALL_ROLES = ["PlatformAdmin", "ComplianceOfficer", "CampaignManager", "DialerOperator", "Consumer"]
PHONE_TYPES = ("WIRELESS", "LANDLINE", "UNKNOWN")


@bp.post("/compliance/contacts")
@endpoint(["PlatformAdmin"])
def import_contact():
    body = payload()
    phone_number = v.req_phone(body, "phone_number")
    state_code = v.req_state(body, "state_code")
    utc_offset_minutes = v.req_int(body, "utc_offset_minutes", -720, 840)
    time_zone_label = v.req_str(body, "time_zone_label")
    phone_type = v.opt_enum(body, "phone_type", PHONE_TYPES, "UNKNOWN")
    attempt_budget_total = v.opt_int(body, "attempt_budget_total", 3, 1, 20)

    for existing in db.contacts.values():
        if existing["phone_number"] == phone_number:
            raise ApiError(
                "ERR_DUPLICATE_PHONE_NUMBER", "Another contact already holds this phone number."
            )

    row = base_row()
    row.update(
        {
            "phone_number": phone_number,
            "state_code": state_code,
            "utc_offset_minutes": utc_offset_minutes,
            "time_zone_label": time_zone_label,
            "phone_type": phone_type,
            "attempt_budget_total": attempt_budget_total,
            "attempts_charged": 0,
            "attempt_budget_remaining": attempt_budget_total,
            "internal_dnc_status": "CLEAR",
            "risk_tier": "LOW",
            "active_consent_count": 0,
            "suspended_consent_count": 0,
            "revoked_consent_count": 0,
            "superseded_consent_count": 0,
            "total_consent_count": 0,
            "rnd_result": "NOT_CHECKED",
            "rnd_checked_at": None,
            "rnd_claimed_consent_date": None,
            "rnd_safe_harbor_eligible": False,
            "overdue_propagation_count": 0,
        }
    )
    db.contacts[row["id"]] = row
    return created(public(row))


@bp.get("/compliance/contacts/<contact_id>")
@endpoint(ALL_ROLES)
def read_contact(contact_id):
    contact = lookup.contact(contact_id)
    return ok(contact_view(contact))


@bp.post("/compliance/contacts/<contact_id>/number-status-check")
@endpoint(["DialerOperator", "CampaignManager", "ComplianceOfficer"])
def number_status_check(contact_id):
    body = payload()
    claimed = v.req_date(body, "claimed_consent_date")
    contact = lookup.contact(contact_id)

    seeded = db.rnd_records.get(contact["phone_number"])
    if seeded is None:
        result = "NO_DATA"
    elif parse_date(seeded) > parse_date(claimed):
        result = "REASSIGNED"
    else:
        result = "NO_MATCH"

    contact["rnd_result"] = result
    contact["rnd_checked_at"] = now_iso()
    contact["rnd_claimed_consent_date"] = claimed
    contact["rnd_safe_harbor_eligible"] = result == "NO_DATA"
    touch_contact(contact)
    return ok(public(contact))


@bp.get("/compliance/contacts/<contact_id>/revocation-requests")
@endpoint(["ComplianceOfficer", "DialerOperator", "Consumer"])
def list_contact_revocations(contact_id):
    limit, offset = v.pagination()
    intake_status = v.query_enum("intake_status", ("RECEIVED", "VALIDATED", "REJECTED"))
    propagation_status = v.query_enum(
        "propagation_status", ("NOT_STARTED", "IN_PROGRESS", "PROPAGATED", "OVERDUE")
    )
    lookup.contact(contact_id)

    matches = revocations_of_contact(contact_id)
    if intake_status is not None:
        matches = [r for r in matches if r["intake_status"] == intake_status]
    if propagation_status is not None:
        matches = [r for r in matches if r["propagation_status"] == propagation_status]
    matches = by_created_at(matches)
    matches.sort(key=lambda r: r["received_at"], reverse=True)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(r) for r in page], limit, offset, total)


def rnd_check_is_current(contact, stamp):
    checked_at = contact["rnd_checked_at"]
    if checked_at is None or contact["rnd_result"] == "NOT_CHECKED":
        return False
    from util import add_days, dt_of

    return stamp < add_days(dt_of(checked_at), RND_VALIDITY_DAYS)
