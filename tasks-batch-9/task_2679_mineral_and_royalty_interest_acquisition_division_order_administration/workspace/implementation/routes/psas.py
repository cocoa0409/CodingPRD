"""Purchase and sale agreements: papering, the curative period, funding and
deed recording (PRD 3.4, 3.5, 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import response
import serializers
from db import db, stamp_new, touch
from errors import ApiError
from guards import (authorize, body, body_ref, get_psa, opt_int, pagination,
                    paginate, parse_date_str, req_date, req_int, req_num,
                    req_str)
from services import cascade

bp = Blueprint("psas", __name__)

BLOCKING_POSTURES = ("EXECUTED", "TERMINATED")


def _defects_of(psa_id):
    return [d for d in db.title_defects.values() if d["psa_id"] == psa_id]


@bp.route("/psas", methods=["POST"])
def create_psa():
    user_id, _role = authorize("AcquisitionManager")
    payload = body()
    # rung 6
    offer = body_ref(payload, "offer_letter_id", db.offer_letters,
                     "ERR_OFFER_LETTER_NOT_FOUND")
    # rung 7
    if offer is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'offer_letter_id' is required.")
    effective_date, effective_dt = req_date(payload, "effective_date")
    individual_defect_threshold = req_num(payload, "individual_defect_threshold", 2, minimum=0)
    aggregate_defect_basket = req_num(payload, "aggregate_defect_basket", 2, minimum=0)
    expected_version = req_int(payload, "expected_mineral_interest_version")
    curative_days = opt_int(payload, "curative_days", minimum=1, maximum=180, default=45)

    interest = db.mineral_interests.get(offer["mineral_interest_id"])
    if interest is None:
        raise ApiError("ERR_MINERAL_INTEREST_NOT_FOUND")
    # rung 9
    if expected_version != interest["version"]:
        raise ApiError("ERR_STALE_INTEREST_VERSION")
    # priority 23
    if interest["interest_status"] != "OFFERED":
        raise ApiError("ERR_INTEREST_STATE_INVALID")
    # priority 25
    if offer["offer_status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_STATE_INVALID")

    curative_dt = calc.add_days(effective_dt, curative_days)
    window_end_dt = calc.add_days(curative_dt, calc.PSA_WINDOW_BUFFER_DAYS)
    curative_deadline = calc.date_to_str(curative_dt)
    window_end_with_buffer = calc.date_to_str(window_end_dt)

    # priority 65: the buffered, closed occupancy window on the tract is exclusive
    for other in db.psas.values():
        if other["tract_id"] != interest["tract_id"]:
            continue
        if other["psa_status"] not in BLOCKING_POSTURES:
            continue
        other_from = parse_date_str(other["effective_date"])
        other_to = parse_date_str(other["window_end_with_buffer"])
        if other_from is None or other_to is None:
            continue
        if effective_dt <= other_to and other_from <= window_end_dt:
            raise ApiError("ERR_PSA_WINDOW_CONFLICT")

    row = {
        "offer_letter_id": offer["id"],
        "mineral_interest_id": interest["id"],
        "tract_id": interest["tract_id"],
        "purchase_price": offer["current_amount"],
        "effective_date": effective_date,
        "curative_days": curative_days,
        "curative_deadline": curative_deadline,
        "window_end_with_buffer": window_end_with_buffer,
        "individual_defect_threshold": individual_defect_threshold,
        "aggregate_defect_basket": aggregate_defect_basket,
        "defect_adjustment_amount": Decimal("0.00"),
        "adjusted_purchase_price": offer["current_amount"],
        "curative_status": "CURATIVE_OPEN",
        "funding_status": "UNFUNDED",
        "psa_status": "EXECUTED",
        "wire_reference": None,
        "recording_county": None,
        "recorded_book_page": None,
        "recording_date": None,
        "created_by_user_id": user_id,
    }
    stamp_new(row)
    cascade.recompute_psa_status(row)
    db.psas[row["id"]] = row
    interest["interest_status"] = "UNDER_PSA"
    touch(interest)
    return response.created(serializers.psa_out(row))


@bp.route("/psas/<psa_id>", methods=["GET"])
def read_psa(psa_id):
    authorize("TitleAnalyst", "AcquisitionManager")
    row = get_psa(psa_id)
    return response.ok(serializers.psa_out(row))


@bp.route("/psas", methods=["GET"])
def list_psas():
    authorize("TitleAnalyst", "AcquisitionManager")
    limit, offset = pagination()
    rows = list(db.psas.values())
    for field in ("offer_letter_id", "mineral_interest_id", "tract_id",
                  "psa_status", "curative_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.psa_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# curative period
# --------------------------------------------------------------------------
DEFECT_TYPES = ("MISSING_HEIR", "UNRELEASED_LEASE", "TAX_SALE_GAP",
                "OVERCONVEYANCE", "UNLOCATABLE_OWNER")


@bp.route("/psas/<psa_id>/title-defects", methods=["POST"])
def raise_defect(psa_id):
    user_id, _role = authorize("TitleAnalyst")
    psa = get_psa(psa_id)
    payload = body()
    from guards import req_enum
    defect_type = req_enum(payload, "defect_type", DEFECT_TYPES)
    affected_nma = req_num(payload, "affected_nma", 4, minimum=0, exclusive_min=True)
    description = req_str(payload, "description")

    if psa["curative_status"] != "CURATIVE_OPEN":       # priority 26
        raise ApiError("ERR_CURATIVE_PERIOD_CLOSED")

    interest = db.mineral_interests.get(psa["mineral_interest_id"])
    if interest is None:
        raise ApiError("ERR_MINERAL_INTEREST_NOT_FOUND")
    if affected_nma > interest["net_mineral_acres"]:    # priority 84
        raise ApiError("ERR_DEFECT_ACREAGE_EXCEEDS_INTEREST")

    allocated_value, net_defect_value = calc.defect_values(psa, interest, affected_nma)
    row = {
        "psa_id": psa["id"],
        "defect_type": defect_type,
        "affected_nma": affected_nma,
        "description": description,
        "allocated_value": allocated_value,
        "net_defect_value": net_defect_value,
        "defect_status": "RAISED",
        "cure_round_count": 0,
        "cure_instrument_book_page": None,
        "raised_by_user_id": user_id,
        "waived_by_user_id": None,
        "decision_note": None,
        "waiver_note": None,
    }
    stamp_new(row)
    db.title_defects[row["id"]] = row
    return response.created(serializers.defect_out(row))


@bp.route("/psas/<psa_id>/title-defects", methods=["GET"])
def list_defects(psa_id):
    authorize("TitleAnalyst", "AcquisitionManager", "RoyaltyOwner")
    psa = get_psa(psa_id)
    limit, offset = pagination()
    defect_status = request.args.get("defect_status")
    rows = _defects_of(psa["id"])
    if defect_status is not None:
        rows = [d for d in rows if d["defect_status"] == defect_status]
    rows.sort(key=lambda d: d["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.defect_out(r) for r in page],
                            limit, offset, total)


@bp.route("/psas/<psa_id>/close-curative", methods=["POST"])
def close_curative(psa_id):
    authorize("AcquisitionManager")
    psa = get_psa(psa_id)
    if psa["curative_status"] != "CURATIVE_OPEN":       # priority 26
        raise ApiError("ERR_CURATIVE_PERIOD_CLOSED")

    interest = db.mineral_interests.get(psa["mineral_interest_id"])
    if interest is None:
        raise ApiError("ERR_MINERAL_INTEREST_NOT_FOUND")

    # sweep every unresolved defect to UNCURED
    unresolved = [d for d in _defects_of(psa["id"])
                  if d["defect_status"] in ("RAISED", "CURE_SUBMITTED", "CURE_REJECTED")]
    unresolved.sort(key=lambda d: d["_seq"])
    for defect in unresolved:
        defect["defect_status"] = "UNCURED"
        touch(defect)

    uncured = [d for d in _defects_of(psa["id"]) if d["defect_status"] == "UNCURED"]
    adjustment, ceiling = calc.defect_price_adjustment(psa, interest, uncured)
    psa["defect_adjustment_amount"] = adjustment
    psa["adjusted_purchase_price"] = calc.q2(psa["purchase_price"] - adjustment)

    if adjustment <= ceiling:
        psa["curative_status"] = "CURATIVE_CLOSED"
        cascade.recompute_psa_status(psa)
        touch(psa)
    else:
        psa["curative_status"] = "CURATIVE_TERMINATED"
        cascade.recompute_psa_status(psa)
        touch(psa)
        cascade.curative_termination_cascade(psa)
    return response.ok(serializers.psa_out(psa))


@bp.route("/psas/<psa_id>/fund", methods=["POST"])
def fund_psa(psa_id):
    authorize("AcquisitionManager")
    psa = get_psa(psa_id)
    payload = body()
    wire_amount = req_num(payload, "wire_amount", 2, minimum=0)
    wire_reference = req_str(payload, "wire_reference")

    if psa["curative_status"] != "CURATIVE_CLOSED":     # priority 27
        raise ApiError("ERR_CURATIVE_PERIOD_OPEN")
    if psa["funding_status"] != "UNFUNDED":             # priority 28
        raise ApiError("ERR_PSA_ALREADY_FUNDED")
    if wire_amount != psa["adjusted_purchase_price"]:   # priority 83
        raise ApiError("ERR_FUNDING_AMOUNT_MISMATCH")

    psa["funding_status"] = "FUNDED"
    psa["wire_reference"] = wire_reference
    cascade.recompute_psa_status(psa)
    touch(psa)
    return response.ok(serializers.psa_out(psa))


@bp.route("/psas/<psa_id>/record-deed", methods=["POST"])
def record_deed(psa_id):
    authorize("TitleAnalyst")
    psa = get_psa(psa_id)
    payload = body()
    recording_county = req_str(payload, "recording_county")
    recorded_book_page = req_str(payload, "recorded_book_page")
    recording_date, recording_dt = req_date(payload, "recording_date")

    if psa["curative_status"] != "CURATIVE_CLOSED":     # priority 27
        raise ApiError("ERR_CURATIVE_PERIOD_OPEN")
    if psa["funding_status"] != "FUNDED":               # priority 28
        raise ApiError("ERR_PSA_ALREADY_FUNDED")
    if psa["recorded_book_page"] is not None:           # priority 29
        raise ApiError("ERR_DEED_ALREADY_RECORDED")
    effective_dt = parse_date_str(psa["effective_date"])
    if effective_dt is not None and recording_dt < effective_dt:   # priority 62
        raise ApiError("ERR_RECORDING_DATE_BEFORE_EFFECTIVE")

    psa["recording_county"] = recording_county
    psa["recorded_book_page"] = recorded_book_page
    psa["recording_date"] = recording_date
    cascade.recompute_psa_status(psa)
    touch(psa)
    cascade.recording_cascade(psa)
    return response.ok(serializers.psa_out(psa))
