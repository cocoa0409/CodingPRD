"""Clock, compliance sweep, parties and laboratories."""

from flask import Blueprint

import db
import response
import validation as V
from middleware import ALL_ROLES, actor_id, endpoint
from routes.common import apply_filter, fetch
from services import derive
from services.constants import (
    AT_RISK_GRACE_DAYS,
    PARTY_TYPES,
)
from services.serialize import dump_laboratory, dump_party

bp = Blueprint("admin", __name__)


# ------------------------------------------------------------------ clock


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_clock():
    body = V.json_body()
    parsed = V.datetime_field(body, "current_utc", required=True)
    raw = body.get("current_utc")
    db.set_now(parsed)
    return response.object_response({"current_utc": raw})


# ---------------------------------------------------------- compliance sweep


@bp.post("/compliance-sweeps")
@endpoint(["StateAgencyReviewer"])
def compliance_sweep():
    body = V.json_body()
    as_of = V.date_field(body, "as_of_date", required=True)
    raw_as_of = body.get("as_of_date")
    site_id = V.id_field(body, "site_id", required=False)
    scoped_site = fetch("sites", site_id) if site_id is not None else None

    swept = 0
    at_risk_count = 0
    lapsed_count = 0
    stale_count = 0
    forfeited_count = 0
    frozen_count = 0

    touched = []

    def mark(protection):
        if protection["id"] not in [p["id"] for p in touched]:
            touched.append(protection)

    for obligation in db.ordered(db.all_rows("continuing_obligations")):
        protection = db.get("liability_protections",
                            obligation["liability_protection_id"])
        if protection is None:
            continue
        if scoped_site is not None and protection["site_id"] != scoped_site["id"]:
            continue
        due = db.parse_date(obligation["due_date"])
        status = obligation["status"]
        new_status = None
        if status in ("CURRENT", "AT_RISK") and as_of > due:
            new_status = "LAPSED"
        elif status in ("CURRENT", "SATISFIED"):
            delta = (due - as_of).days
            if 0 <= delta <= AT_RISK_GRACE_DAYS:
                new_status = "AT_RISK"
        if new_status is None:
            continue
        obligation["status"] = new_status
        db.touch(obligation)
        swept += 1
        if new_status == "LAPSED":
            lapsed_count += 1
        else:
            at_risk_count += 1
        mark(protection)

    for protection in db.ordered(db.all_rows("liability_protections")):
        if scoped_site is not None and protection["site_id"] != scoped_site["id"]:
            continue
        site = db.get("sites", protection["site_id"])
        expires = protection.get("aai_expires_on")
        if (protection["inquiry_state"] == "AAI_COMPLETE"
                and site is not None
                and site["acquisition_status"] == "UNDER_CONTRACT"
                and expires is not None
                and as_of > db.parse_date(expires)):
            protection["inquiry_state"] = "AAI_STALE"
            stale_count += 1
            mark(protection)

    for protection in touched:
        site = db.get("sites", protection["site_id"])
        newly_forfeited = derive.recompute_protection(protection, site)
        db.touch(protection)
        if newly_forfeited:
            forfeited_count += 1
        if site is not None:
            changed, posture_changed = derive.recompute_posture(site)
            if changed:
                db.touch(site)
            if posture_changed and site["cleanup_posture"] == "FROZEN":
                frozen_count += 1
            if newly_forfeited:
                derive.revoke_letters_and_rescind_awards(site, "BFPP_FORFEITED")

    return response.object_response({
        "as_of_date": raw_as_of,
        "swept_obligation_count": swept,
        "at_risk_count": at_risk_count,
        "lapsed_count": lapsed_count,
        "stale_inquiry_count": stale_count,
        "forfeited_protection_count": forfeited_count,
        "frozen_site_count": frozen_count,
    })


# ----------------------------------------------------------------- parties


@bp.post("/parties")
@endpoint(["ProgramAdmin"])
def create_party():
    body = V.json_body()
    legal_name = V.string_field(body, "legal_name", True, 1, 160)
    party_type = V.enum_field(body, "party_type", PARTY_TYPES, True)
    state_code = V.string_field(body, "state_code", True, 2, 2)
    if not state_code.isalpha() or state_code != state_code.upper():
        V.fail("Field state_code must be exactly 2 uppercase letters.")
    licence_number = V.string_field(body, "licence_number", False, 1, None)
    if party_type in ("CONSULTANT", "INSURER") and licence_number is None:
        V.fail("Field licence_number is required for %s parties." % party_type)
    row = db.insert("parties", {
        "legal_name": legal_name,
        "party_type": party_type,
        "state_code": state_code,
        "licence_number": licence_number,
    })
    return response.created(dump_party(row))


@bp.get("/parties")
@endpoint(ALL_ROLES)
def list_parties():
    rows = db.ordered(db.all_rows("parties"))
    rows = apply_filter(rows, "party_type", V.query_enum("party_type", PARTY_TYPES))
    return response.list_response(rows, dump_party)


@bp.get("/parties/<party_id>")
@endpoint(ALL_ROLES)
def get_party(party_id):
    return response.object_response(dump_party(fetch("parties", party_id)))


# ------------------------------------------------------------- laboratories


@bp.post("/laboratories")
@endpoint(["ProgramAdmin"])
def create_laboratory():
    body = V.json_body()
    row = db.insert("laboratories", {
        "lab_name": V.string_field(body, "lab_name", True, 1, 120),
        "certification_code": V.string_field(body, "certification_code", True, 1, 32),
        "concurrent_capacity": V.int_field(body, "concurrent_capacity", True, 1, 10),
    })
    return response.created(dump_laboratory(row))


@bp.get("/laboratories")
@endpoint(["ProgramAdmin", "StateAgencyReviewer", "EnvironmentalConsultant",
           "Redeveloper"])
def list_laboratories():
    rows = db.ordered(db.all_rows("laboratories"))
    rows = apply_filter(rows, "certification_code",
                        V.query_string("certification_code"))
    return response.list_response(rows, dump_laboratory)


@bp.get("/laboratories/<lab_id>")
@endpoint(["ProgramAdmin", "StateAgencyReviewer", "EnvironmentalConsultant",
           "Redeveloper"])
def get_laboratory(lab_id):
    return response.object_response(dump_laboratory(fetch("laboratories", lab_id)))
