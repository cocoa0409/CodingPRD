"""Submission intake, sorting, image capture and purchase data (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from middleware import ALL_ROLES
from services import calc, domain

bp = Blueprint("intake", __name__)

SUBMISSION_SPEC = {
    "retailer_id": {"type": "string", "required": True, "min_len": 1},
    "channel": {"type": "enum", "required": True, "values": ["MAIL", "ELECTRONIC"]},
    "declared_count": {"type": "integer", "required": True, "min": 0, "max": 1000000},
    "postmark_window_start": {"type": "date", "required": True},
    "postmark_window_end": {"type": "date", "required": True},
}

CHANNEL_CAPABILITY = {
    "MAIL_ONLY": ("MAIL",),
    "ELECTRONIC_ONLY": ("ELECTRONIC",),
    "BOTH": ("MAIL", "ELECTRONIC"),
}


@bp.route("/submissions", methods=["POST"])
def create_submission():
    ctx = mw.authenticate(["Retailer", "IntakeClerk"])
    values = validate.parse(mw.body(), SUBMISSION_SPEC)
    start = db.parse_date(values["postmark_window_start"])
    end = db.parse_date(values["postmark_window_end"])
    if start >= end:
        validate.fail("postmark_window_start must be strictly before postmark_window_end")
    retailer = mw.fetch("retailers", values["retailer_id"], "ERR_RETAILER_NOT_FOUND")
    mw.own_retailer(ctx, retailer["id"])
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    for other in db.db.submissions.values():
        if other["retailer_id"] != retailer["id"]:
            continue
        if other["intake_status"] == "CLOSED":
            continue
        other_start = db.parse_date(other["postmark_window_start"])
        other_end = db.parse_date(other["postmark_window_end"])
        if start < other_end and other_start < end:
            raise ApiError(
                "ERR_POSTMARK_WINDOW_OVERLAP",
                "Postmark window overlaps an open submission",
            )
    if values["channel"] not in CHANNEL_CAPABILITY[retailer["channel_capability"]]:
        raise ApiError(
            "ERR_CHANNEL_NOT_SUPPORTED",
            "Retailer cannot accept the %s channel" % values["channel"],
        )
    row = db.base_row()
    row.update(
        {
            "retailer_id": retailer["id"],
            "channel": values["channel"],
            "declared_count": values["declared_count"],
            "verified_count": 0,
            "count_variance_pct": calc.ZERO_2,
            "postmark_window_start": values["postmark_window_start"],
            "postmark_window_end": values["postmark_window_end"],
            "intake_status": "RECEIVED",
            "settlement_status": "PENDING",
            "hold_reason": None,
            "sorted_lot_count": 0,
            "rejected_lot_count": 0,
            "declared_face_value_cents": 0,
            "adjudicated_face_value_cents": 0,
            "accepted_item_face_value_cents": 0,
            "rejected_item_face_value_cents": 0,
            "settled_gross_face_value_cents": 0,
            "settled_handling_fee_cents": 0,
            "valuation_method": "FULL_COUNT",
        }
    )
    db.db.submissions[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/submissions/<sid>", methods=["GET"])
def get_submission(sid):
    ctx = mw.authenticate(ALL_ROLES)
    row = mw.fetch("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    mw.own_retailer(ctx, row["retailer_id"])
    return response.object_response(row)


@bp.route("/submissions", methods=["GET"])
def list_submissions():
    mw.authenticate(ALL_ROLES)
    limit, offset = mw.pagination()
    retailer_id = mw.str_arg("retailer_id")
    intake_status = mw.str_arg("intake_status")
    settlement_status = mw.str_arg("settlement_status")
    rows = [
        s
        for s in db.db.submissions.values()
        if (retailer_id is None or s["retailer_id"] == retailer_id)
        and (intake_status is None or s["intake_status"] == intake_status)
        and (settlement_status is None or s["settlement_status"] == settlement_status)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/submissions/<sid>/valuation", methods=["GET"])
def submission_valuation(sid):
    mw.authenticate(["FraudAnalyst", "SettlementOfficer", "ClearinghouseAdmin"])
    submission = mw.fetch("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    lots = domain.lots_of_submission(submission["id"])
    full_count_total = 0
    sampled_total = 0
    for lot in lots:
        face = domain.offer_of_lot(lot)["face_value_cents"]
        full_count_total += calc.lot_valuation(
            "FULL_COUNT", lot["accepted_qty"], lot["counted_qty"],
            lot["sample_size"], face,
        )[1]
        sampled_total += calc.lot_valuation(
            "SAMPLED_EXTRAPOLATION", lot["accepted_qty"], lot["counted_qty"],
            lot["sample_size"], face,
        )[1]
    return response.object_response(
        {
            "submission_id": submission["id"],
            "valuation_method": submission["valuation_method"],
            "full_count_gross_face_value_cents": full_count_total,
            "sampled_gross_face_value_cents": sampled_total,
            "settled_gross_face_value_cents": submission[
                "settled_gross_face_value_cents"
            ],
            "settled_handling_fee_cents": submission["settled_handling_fee_cents"],
            "lot_count": len(lots),
        }
    )


@bp.route("/submissions/<sid>/verify-count", methods=["POST"])
def verify_count(sid):
    mw.authenticate(["IntakeClerk"])
    submission = mw.fetch("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    values = validate.parse(
        mw.body(),
        {"verified_count": {"type": "integer", "required": True, "min": 0,
                            "max": 1000000}},
    )
    if submission["intake_status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a RECEIVED submission can be count-verified",
        )
    retailer = domain.retailer_of_submission(submission)
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    if submission["declared_count"] < 1:
        raise ApiError(
            "ERR_COUNT_VARIANCE_EXCEEDED",
            "Count variance is undefined for a zero declared count",
        )
    variance = calc.count_variance_pct(
        values["verified_count"], submission["declared_count"]
    )
    if variance > calc.COUNT_VARIANCE_TOLERANCE_PCT:
        raise ApiError(
            "ERR_COUNT_VARIANCE_EXCEEDED",
            "Count variance %s%% exceeds tolerance" % variance,
        )
    submission["verified_count"] = values["verified_count"]
    submission["count_variance_pct"] = variance
    submission["intake_status"] = "COUNT_VERIFIED"
    touch(submission)
    return response.object_response(submission)


# ---------------------------------------------------------------- sorting
LOT_SPEC = {
    "offer_id": {"type": "string", "required": True, "min_len": 1},
    "manufacturer_id": {"type": "string", "required": True, "min_len": 1},
    "counted_qty": {"type": "integer", "required": True, "min": 1, "max": 1000000},
}


@bp.route("/submissions/<sid>/lots", methods=["POST"])
def create_lot(sid):
    mw.authenticate(["IntakeClerk"])
    submission = mw.fetch("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    values = validate.parse(mw.body(), LOT_SPEC)
    manufacturer = mw.fetch(
        "manufacturers", values["manufacturer_id"], "ERR_MANUFACTURER_NOT_FOUND"
    )
    offer = mw.fetch("offers", values["offer_id"], "ERR_OFFER_NOT_FOUND")
    if submission["intake_status"] != "COUNT_VERIFIED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Lots may only be sorted on a COUNT_VERIFIED submission",
        )
    retailer = domain.retailer_of_submission(submission)
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    issuer = db.db.manufacturers[offer["manufacturer_id"]]
    if issuer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Issuing manufacturer is suspended")
    if manufacturer["id"] != offer["manufacturer_id"]:
        raise ApiError(
            "ERR_OFFER_MANUFACTURER_MISMATCH",
            "Offer does not belong to the supplied manufacturer",
        )
    if offer["status"] not in ("ACTIVE", "EXPIRED"):
        raise ApiError(
            "ERR_OFFER_NOT_CLEARABLE",
            "Offer in %s cannot be cleared" % offer["status"],
        )
    grace_end = db.add_days(
        db.parse_date(offer["expiration_date"]), offer["redemption_grace_days"]
    )
    if db.today() > grace_end:
        raise ApiError(
            "ERR_SUBMISSION_PAST_GRACE", "Redemption grace period has elapsed"
        )
    existing = domain.lots_of_submission(submission["id"])
    running = sum(l["counted_qty"] for l in existing)
    if running + values["counted_qty"] > submission["verified_count"]:
        raise ApiError(
            "ERR_LOT_COUNT_OVERFLOW",
            "Sorted quantity would exceed the verified count",
        )
    sample_size, variant = calc.sample_plan(values["counted_qty"])
    row = db.base_row()
    row.update(
        {
            "submission_id": submission["id"],
            "offer_id": offer["id"],
            "manufacturer_id": manufacturer["id"],
            "counted_qty": values["counted_qty"],
            "sample_size": sample_size,
            "captured_item_count": 0,
            "accepted_qty": 0,
            "rejected_qty": 0,
            "projected_accepted_units": 0,
            "valuation_variant": variant,
            "gross_face_value_cents": 0,
            "handling_fee_cents": 0,
            "status": "SORTED",
            "reject_reason": None,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
        }
    )
    db.db.lots[row["id"]] = row
    domain.recompute_sorted_lot_count(submission)
    domain.recompute_declared_face_value(submission)
    if running + values["counted_qty"] == submission["verified_count"]:
        submission["intake_status"] = "SORTED"
    touch(submission)
    return response.object_response(row, 201)


@bp.route("/submission-lots/<lid>", methods=["GET"])
def get_lot(lid):
    ctx = mw.authenticate(ALL_ROLES)
    lot = mw.fetch("lots", lid, "ERR_LOT_NOT_FOUND")
    mw.own_retailer(ctx, domain.submission_of_lot(lot)["retailer_id"])
    mw.own_manufacturer(ctx, lot["manufacturer_id"])
    return response.object_response(lot)


@bp.route("/submission-lots", methods=["GET"])
def list_lots():
    mw.authenticate(ALL_ROLES)
    limit, offset = mw.pagination()
    submission_id = mw.str_arg("submission_id")
    offer_id = mw.str_arg("offer_id")
    manufacturer_id = mw.str_arg("manufacturer_id")
    status = mw.str_arg("status")
    rows = [
        l
        for l in db.db.lots.values()
        if (submission_id is None or l["submission_id"] == submission_id)
        and (offer_id is None or l["offer_id"] == offer_id)
        and (manufacturer_id is None or l["manufacturer_id"] == manufacturer_id)
        and (status is None or l["status"] == status)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# ----------------------------------------------------------- image capture
ITEM_ELEMENT_KEYS = (
    "scanned_barcode",
    "serial_number",
    "image_uri",
    "redeemed_at",
    "pos_transaction_ref",
    "claimed_units",
)

ITEM_ELEMENT_SPEC = {
    "scanned_barcode": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 64,
        "digits": True,
    },
    "serial_number": {"type": "string", "min_len": 1, "max_len": 32, "default": None},
    "redeemed_at": {"type": "date", "required": True},
    "claimed_units": {"type": "integer", "min": 1, "max": 5, "default": 1},
}


@bp.route("/submission-lots/<lid>/items", methods=["POST"])
def capture_items(lid):
    mw.authenticate(["IntakeClerk"])
    lot = mw.fetch("lots", lid, "ERR_LOT_NOT_FOUND")
    payload = mw.body()
    validate.check_unknown(payload, {"items": True})
    if "items" not in payload or payload["items"] is None:
        validate.fail("Field 'items' is required")
    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        validate.fail("Field 'items' must be an array")

    parsed = []
    for element in raw_items:
        if not isinstance(element, dict):
            validate.fail("Each entry of 'items' must be an object")
        for key in element.keys():
            if key not in ITEM_ELEMENT_KEYS:
                validate.fail("Unknown field '%s'" % key)
        values = validate.parse(
            dict((k, v) for k, v in element.items() if k in ITEM_ELEMENT_SPEC),
            ITEM_ELEMENT_SPEC,
        )
        image = element.get("image_uri")
        if image is not None:
            if not isinstance(image, str):
                validate.fail("Field 'image_uri' must be a string")
            if image.strip() != "" and len(image) > 300:
                validate.fail("Field 'image_uri' must be at most 300 characters")
        pos_ref = element.get("pos_transaction_ref")
        if pos_ref is not None:
            if not isinstance(pos_ref, str):
                validate.fail("Field 'pos_transaction_ref' must be a string")
            if pos_ref.strip() == "":
                validate.fail("Field 'pos_transaction_ref' must not be blank")
            if len(pos_ref) < 1 or len(pos_ref) > 40:
                validate.fail("Field 'pos_transaction_ref' must be 1..40 characters")
        values["image_uri"] = image
        values["pos_transaction_ref"] = pos_ref
        parsed.append(values)

    if lot["status"] != "SORTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Images may only be captured on a SORTED lot",
        )
    submission = domain.submission_of_lot(lot)
    retailer = domain.retailer_of_submission(submission)
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    for values in parsed:
        image = values["image_uri"]
        if image is None or image.strip() == "":
            raise ApiError("ERR_IMAGE_REQUIRED", "Every item requires an image_uri")
    if submission["channel"] == "ELECTRONIC":
        for values in parsed:
            if values["pos_transaction_ref"] is None:
                raise ApiError(
                    "ERR_POS_REF_REQUIRED",
                    "Electronic submissions require pos_transaction_ref on every item",
                )
    if lot["captured_item_count"] + len(parsed) > lot["sample_size"]:
        raise ApiError(
            "ERR_LOT_CAPTURE_COMPLETE",
            "Capture would exceed the lot's sample size",
        )

    created = []
    base_instant = db.now()
    for index, values in enumerate(parsed):
        stamp = db.fmt_instant(base_instant + timedelta(milliseconds=index))
        row = db.base_row(created_at=stamp)
        row.update(
            {
                "lot_id": lot["id"],
                "scanned_barcode": values["scanned_barcode"],
                "serial_number": values["serial_number"],
                "image_uri": values["image_uri"],
                "redeemed_at": values["redeemed_at"],
                "pos_transaction_ref": values["pos_transaction_ref"],
                "claimed_units": values["claimed_units"],
                "status": "CAPTURED",
                "reject_code": None,
                "duplicate_of_item_id": None,
                "matched_purchase_record_id": None,
                "adjudicated_at": None,
            }
        )
        db.db.items[row["id"]] = row
        created.append(row)
    lot["captured_item_count"] = lot["captured_item_count"] + len(created)
    touch(lot)
    return response.array_response(created, 201)


# ------------------------------------------------------- purchase data 3.3
PURCHASE_SPEC = {
    "retailer_id": {"type": "string", "required": True, "min_len": 1},
    "offer_id": {"type": "string", "required": True, "min_len": 1},
    "pos_transaction_ref": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 40,
    },
    "transaction_date": {"type": "date", "required": True},
    "qualifying_units": {"type": "integer", "required": True, "min": 0, "max": 1000},
}


@bp.route("/purchase-data-records", methods=["POST"])
def create_purchase_record():
    ctx = mw.authenticate(["Retailer", "IntakeClerk"])
    values = validate.parse(mw.body(), PURCHASE_SPEC)
    retailer = mw.fetch("retailers", values["retailer_id"], "ERR_RETAILER_NOT_FOUND")
    mw.own_retailer(ctx, retailer["id"])
    offer = mw.fetch("offers", values["offer_id"], "ERR_OFFER_NOT_FOUND")
    row = db.base_row(versioned=False)
    row.update(
        {
            "retailer_id": retailer["id"],
            "offer_id": offer["id"],
            "pos_transaction_ref": values["pos_transaction_ref"],
            "transaction_date": values["transaction_date"],
            "qualifying_units": values["qualifying_units"],
        }
    )
    db.db.purchase_records[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/purchase-data-records/<pid>", methods=["GET"])
def get_purchase_record(pid):
    ctx = mw.authenticate(ALL_ROLES)
    row = mw.fetch("purchase_records", pid, "ERR_PURCHASE_RECORD_NOT_FOUND")
    mw.own_retailer(ctx, row["retailer_id"])
    return response.object_response(row)


@bp.route("/purchase-data-records", methods=["GET"])
def list_purchase_records():
    mw.authenticate(ALL_ROLES)
    limit, offset = mw.pagination()
    retailer_id = mw.str_arg("retailer_id")
    offer_id = mw.str_arg("offer_id")
    pos_ref = mw.str_arg("pos_transaction_ref")
    rows = [
        r
        for r in db.db.purchase_records.values()
        if (retailer_id is None or r["retailer_id"] == retailer_id)
        and (offer_id is None or r["offer_id"] == offer_id)
        and (pos_ref is None or r["pos_transaction_ref"] == pos_ref)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)
