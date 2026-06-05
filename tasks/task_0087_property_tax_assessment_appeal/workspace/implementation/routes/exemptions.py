"""Exemption endpoints: claim, approve, deny (PRD §3.4)."""
from datetime import date, datetime

from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import object_response
from services.assessment import recompute_exemptions
from services.calc import exemption_deduction
from services.common import get_body, require_fields, lookup
from services.serialize import serialize

bp = Blueprint("exemptions", __name__)

EXEMPTION_TYPES = {"HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"}


def _parse_date(value):
    """Parse the date portion of an ISO birth_date string."""
    s = str(value)
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _age_in_years(birth_date_str, ref=None):
    bd = _parse_date(birth_date_str)
    if bd is None:
        return None
    ref = ref or datetime.utcnow().date()
    years = ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))
    return years


@bp.post("/exemptions")
def claim_exemption():
    require_roles(["Assessor", "Taxpayer"])
    body = get_body()
    require_fields(body, ["assessment_id", "exemption_type"])
    assessment_id = body["assessment_id"]
    exemption_type = body["exemption_type"]
    if not isinstance(assessment_id, str):
        raise err("ERR_INVALID_REQUEST", "assessment_id must be a string")
    if exemption_type not in EXEMPTION_TYPES:
        raise err("ERR_INVALID_REQUEST", "exemption_type invalid")

    with db.LOCK:
        a = lookup(db.assessments, assessment_id)
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Parent assessment is not DRAFT")
        record = {
            "assessment_id": assessment_id,
            "exemption_type": exemption_type,
            "claimed_amount": 0,
            "status": "CLAIMED",
        }
        db.init_common(record)
        db.exemptions[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/exemptions/<exemption_id>")
def get_exemption(exemption_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    return object_response(serialize(lookup(db.exemptions, exemption_id)), 200)


@bp.post("/exemptions/<exemption_id>/approve")
def approve_exemption(exemption_id):
    require_roles(["Reviewer"])
    with db.LOCK:
        e = lookup(db.exemptions, exemption_id)
        if e["status"] != "CLAIMED":
            raise err("ERR_INVALID_STATE", "Exemption is not CLAIMED")
        a = db.assessments[e["assessment_id"]]
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Parent assessment is not DRAFT")

        parcel = db.parcels[a["parcel_id"]]
        owner = db.owners[parcel["owner_id"]]
        roll = db.tax_rolls[a["tax_roll_id"]]
        etype = e["exemption_type"]

        # Eligibility (PRD §3.4)
        eligible = False
        if etype == "HOMESTEAD":
            eligible = bool(parcel["is_primary_residence"])
        elif etype == "SENIOR":
            age = _age_in_years(owner["birth_date"])
            eligible = age is not None and age >= roll["senior_age_threshold"]
        elif etype == "VETERAN":
            eligible = bool(owner["is_veteran"])
        elif etype == "DISABILITY":
            eligible = owner["disability_pct"] >= 1
        if not eligible:
            raise err("ERR_EXEMPTION_INELIGIBLE", "Owner/parcel not eligible for this type")

        # No other APPROVED exemption of the same type on this assessment.
        for other in db.exemptions.values():
            if (other["assessment_id"] == a["id"]
                    and other["id"] != e["id"]
                    and other["exemption_type"] == etype
                    and other["status"] == "APPROVED"):
                raise err("ERR_DUPLICATE_EXEMPTION", "Type already approved on this assessment")

        # Compute deduction against the pre-exemption assessed_value.
        e["claimed_amount"] = exemption_deduction(etype, a["assessed_value"], owner)
        e["status"] = "APPROVED"
        db.touch(e)

        # Fold into the assessment running total (recompute from all APPROVED).
        recompute_exemptions(a)
        db.touch(a)
    return object_response(serialize(e), 200)


@bp.post("/exemptions/<exemption_id>/deny")
def deny_exemption(exemption_id):
    require_roles(["Reviewer"])
    with db.LOCK:
        e = lookup(db.exemptions, exemption_id)
        if e["status"] != "CLAIMED":
            raise err("ERR_INVALID_STATE", "Exemption is not CLAIMED")
        a = db.assessments[e["assessment_id"]]
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Parent assessment is not DRAFT")
        e["claimed_amount"] = 0
        e["status"] = "DENIED"
        db.touch(e)
        # No change to Assessment.exemption_total (PRD §3.4).
    return object_response(serialize(e), 200)
