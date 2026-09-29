"""The two evidentiary families: chain of title and waste-in verification."""

from decimal import Decimal

from flask import Blueprint

import constants as K
import derive
import logical_clock
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from numeric import frac
from routes import common

bp = Blueprint("evidence", __name__)

ZERO = Decimal("0.00")
OPEN_END = logical_clock.parse_day(K.OPEN_END_DATE)


def _effective_end(period):
    """An empty end_date means the party still holds title, and for all interval
    arithmetic such an open period is treated as ending on 9999-12-31."""
    return period["end_date"] or OPEN_END


def _site_prp(site, prp_id):
    prp = store.prps.get(prp_id)
    if prp is None or prp["site_id"] != site["id"]:
        raise ApiError("ERR_PRP_NOT_FOUND")
    return prp


@bp.post("/sites/<site_id>/ownership-periods")
def create_ownership_period(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    prp_id = shape.str_field(body, "prp_id")
    start_date = shape.date_field(body, "start_date")
    end_date = shape.date_field(body, "end_date", required=False)
    acquisition_type = shape.enum_field(body, "acquisition_type", K.ACQUISITION_TYPES)
    site = common.get_site(site_id)
    prp = _site_prp(site, prp_id)
    common.require_phase(site, K.PHASE_LISTED_OR_LATER)

    end_effective = end_date or OPEN_END
    # Site-wide, across any pair of parties; touching endpoints do not conflict.
    for existing in derive.site_periods(site["id"]):
        other_end = _effective_end(existing)
        if start_date < other_end and existing["start_date"] < end_effective:
            raise ApiError("ERR_OWNERSHIP_PERIOD_OVERLAP")

    period = common.new_record(
        {
            "site_id": site["id"],
            "prp_id": prp["id"],
            "start_date": start_date,
            "end_date": end_date,
            "acquisition_type": acquisition_type,
            "ownership_days": (end_effective - start_date).days,
        },
        mutable=False,
    )
    store.ownership_periods[period["id"]] = period
    derive.recompute_ownership_days_total(prp)
    derive.recompute_drafting_rounds(site)
    return common.respond(period, serialize.ownership_period, 201)


@bp.post("/sites/<site_id>/waste-in-records")
def create_waste_in_record(site_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    prp_id = shape.str_field(body, "prp_id")
    volume = shape.num_field(body, "volume_tons", scale=2, strictly_positive=True)
    toxicity_class = shape.enum_field(body, "toxicity_class", K.TOXICITY_CLASSES)
    evidence_grade = shape.enum_field(body, "evidence_grade", K.EVIDENCE_GRADES)
    disposal_year = shape.int_field(body, "disposal_year", lo=1940, hi=2026)
    transporter = shape.str_field(body, "transporter_name", required=False)
    site = common.get_site(site_id)
    prp = _site_prp(site, prp_id)
    common.require_phase(site, K.PHASE_LISTED_OR_LATER)

    record = common.new_record(
        {
            "site_id": site["id"],
            "prp_id": prp["id"],
            "volume_tons": volume,
            "toxicity_class": toxicity_class,
            "evidence_grade": evidence_grade,
            "disposal_year": disposal_year,
            "transporter_name": transporter,
            "status": "SUBMITTED",
            "verified_volume_tons": None,
            "effective_volume_tons": volume,
            "verified_by_user_id": None,
        }
    )
    store.waste_in_records[record["id"]] = record
    derive.recompute_prp_volumes(prp)
    derive.recompute_drafting_rounds(site)
    return common.respond(record, serialize.waste_in_record, 201)


@bp.post("/waste-in-records/<record_id>/verification")
def verify_waste_in_record(record_id):
    actor = require(K.ROLE_RPM)
    body = shape.get_body()
    decision = shape.enum_field(body, "decision", K.VERIFY_DECISIONS)
    verified = shape.num_field(body, "verified_volume_tons", required=False, scale=2)
    shape.str_field(body, "verification_note", required=False)
    record = common.get_waste(record_id)
    site = store.sites[record["site_id"]]
    prp = store.prps[record["prp_id"]]
    common.state(record["status"] == "SUBMITTED")
    common.deny_deleted(site)

    # Priority 35: a figure above the claim, a non-positive figure, or a figure
    # supplied alongside a rejection all report the same error.
    if decision == "VERIFIED":
        if verified is None or frac(verified) <= 0 or frac(verified) > frac(record["volume_tons"]):
            raise ApiError("ERR_VERIFIED_VOLUME_EXCEEDS_CLAIM")
    elif verified is not None:
        raise ApiError("ERR_VERIFIED_VOLUME_EXCEEDS_CLAIM")

    txn.watch(record)
    record["verified_by_user_id"] = actor.user_id
    if decision == "VERIFIED":
        record["status"] = "VERIFIED"
        record["verified_volume_tons"] = verified
        record["effective_volume_tons"] = verified
    else:
        record["status"] = "REJECTED"
        record["effective_volume_tons"] = ZERO
    derive.after_waste_change(site, prp)
    return common.respond(record, serialize.waste_in_record)
