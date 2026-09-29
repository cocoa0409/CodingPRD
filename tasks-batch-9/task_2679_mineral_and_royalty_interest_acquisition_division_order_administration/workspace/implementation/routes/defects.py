"""Title defect curative loop: cures, adjudication and waivers (PRD 3.5)."""

from flask import Blueprint

import response
import serializers
from db import clock_date, db, touch
from errors import ApiError
from guards import (authorize, body, get_defect, opt_str, parse_date_str,
                    req_enum, req_str)

bp = Blueprint("defects", __name__)

DECISIONS = ("ACCEPTED", "REJECTED")


def _psa_of(defect):
    return db.psas.get(defect["psa_id"])


def _interest_of(psa):
    if psa is None:
        return None
    return db.mineral_interests.get(psa["mineral_interest_id"])


def _require_owner(defect, user_id):
    """Rung 4: only the seller of record on the interest may cure."""
    interest = _interest_of(_psa_of(defect))
    if interest is None or interest["seller_owner_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return interest


def _require_curative_open(psa):
    if psa is None or psa["curative_status"] != "CURATIVE_OPEN":   # priority 26
        raise ApiError("ERR_CURATIVE_PERIOD_CLOSED")


def _require_deadline(psa):
    deadline = parse_date_str(psa["curative_deadline"])
    if deadline is not None and clock_date() > deadline:           # priority 61
        raise ApiError("ERR_CURATIVE_DEADLINE_PASSED")


@bp.route("/title-defects/<defect_id>", methods=["GET"])
def read_defect(defect_id):
    authorize("TitleAnalyst", "AcquisitionManager", "RoyaltyOwner")
    row = get_defect(defect_id)
    return response.ok(serializers.defect_out(row))


@bp.route("/title-defects/<defect_id>/submit-cure", methods=["POST"])
def submit_cure(defect_id):
    user_id, _role = authorize("RoyaltyOwner")
    defect = get_defect(defect_id)
    _require_owner(defect, user_id)
    payload = body()
    cure_instrument_book_page = req_str(payload, "cure_instrument_book_page")

    psa = _psa_of(defect)
    _require_curative_open(psa)
    if defect["defect_status"] not in ("RAISED", "CURE_REJECTED"):  # priority 30
        raise ApiError("ERR_DEFECT_STATE_INVALID")
    _require_deadline(psa)

    defect["cure_instrument_book_page"] = cure_instrument_book_page
    defect["cure_round_count"] = defect["cure_round_count"] + 1
    defect["defect_status"] = "CURE_SUBMITTED"
    touch(defect)
    return response.ok(serializers.defect_out(defect))


@bp.route("/title-defects/<defect_id>/cure-decision", methods=["POST"])
def cure_decision(defect_id):
    authorize("TitleAnalyst")
    defect = get_defect(defect_id)
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    decision_note = opt_str(payload, "decision_note")

    psa = _psa_of(defect)
    _require_curative_open(psa)
    if defect["defect_status"] != "CURE_SUBMITTED":                 # priority 30
        raise ApiError("ERR_DEFECT_STATE_INVALID")
    # deliberately not gated on curative_deadline (PRD 3.5)

    defect["defect_status"] = "CURED" if decision == "ACCEPTED" else "CURE_REJECTED"
    if decision_note is not None:
        defect["decision_note"] = decision_note
    touch(defect)
    return response.ok(serializers.defect_out(defect))


@bp.route("/title-defects/<defect_id>/waive", methods=["POST"])
def waive_defect(defect_id):
    user_id, _role = authorize("AcquisitionManager")
    defect = get_defect(defect_id)
    payload = body()
    waiver_note = opt_str(payload, "waiver_note")

    psa = _psa_of(defect)
    _require_curative_open(psa)
    if defect["defect_status"] not in ("RAISED", "CURE_SUBMITTED", "CURE_REJECTED"):
        raise ApiError("ERR_DEFECT_STATE_INVALID")                 # priority 30
    _require_deadline(psa)

    defect["defect_status"] = "WAIVED"
    defect["waived_by_user_id"] = user_id
    if waiver_note is not None:
        defect["waiver_note"] = waiver_note
    touch(defect)
    return response.ok(serializers.defect_out(defect))
