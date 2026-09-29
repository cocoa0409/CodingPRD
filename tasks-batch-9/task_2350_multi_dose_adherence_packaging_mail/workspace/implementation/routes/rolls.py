"""The pouch bench: packing, imaging, verification and rework."""

from flask import Blueprint

import calc
import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("rolls", __name__)

IMAGERS = ("PackagingTechnician", "VerifyingPharmacist")


@bp.post("/pouch-rolls/<roll_id>/pack")
def pack(roll_id):
    user_id, _role = middleware.authenticate(("PackagingTechnician",))
    roll = middleware.lookup("pouch_roll", roll_id)

    if roll["verification_status"] != "BUILT":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    if not engine.pouches_of_roll(roll_id):
        raise ApiError("ERR_INVALID_ROLL_STATE")

    roll["verification_status"] = "PACKED"
    roll["packed_by_user_id"] = user_id
    roll["packed_at"] = clock.now_iso()
    store.touch(roll)

    cycle = db.fill_cycles[roll["cycle_id"]]
    if cycle["packaging_status"] == "ROLL_GENERATED":
        cycle["packaging_status"] = "PACKED"
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(roll))


@bp.post("/pouches/<pouch_id>/verification-image")
def image_pouch(pouch_id):
    user_id, _role = middleware.authenticate(IMAGERS)
    body = validators.json_body()
    detected_pill_count = validators.integer(body, "detected_pill_count", minimum=0)
    image_confidence_pct = validators.integer(
        body, "image_confidence_pct", minimum=0, maximum=100
    )

    pouch = middleware.lookup("pouch", pouch_id)
    roll = db.pouch_rolls[pouch["roll_id"]]

    if roll["verification_status"] != "PACKED":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    if pouch["verification_result"] != "PENDING":
        raise ApiError("ERR_IMAGE_ALREADY_CAPTURED")
    if user_id == roll["packed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    _record_image(pouch, user_id, detected_pill_count, image_confidence_pct)
    store.touch(pouch)

    engine.recompute_mismatch_count(roll)
    store.touch(roll)

    store.commit()
    return response.object_response(store.serialize(pouch))


@bp.post("/pouch-rolls/<roll_id>/verification-images")
def image_roll(roll_id):
    user_id, _role = middleware.authenticate(IMAGERS)
    body = validators.json_body()
    image_confidence_pct = validators.integer(
        body, "image_confidence_pct", minimum=0, maximum=100
    )
    raw_overrides = validators.object_array(
        body, "overrides", required=False, default=None
    )
    overrides = {}
    for element in raw_overrides or []:
        pouch_index = validators.integer(element, "pouch_index", minimum=1)
        overrides[pouch_index] = (
            validators.integer(element, "detected_pill_count", minimum=0),
            validators.integer(
                element,
                "image_confidence_pct",
                required=False,
                default=None,
                minimum=0,
                maximum=100,
            ),
        )

    roll = middleware.lookup("pouch_roll", roll_id)

    if roll["verification_status"] != "PACKED":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    if user_id == roll["packed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for pouch in engine.pouches_of_roll(roll_id):
        if pouch["verification_result"] != "PENDING":
            continue
        detected = pouch["expected_pill_count"]
        confidence = image_confidence_pct
        if pouch["pouch_index"] in overrides:
            override_count, override_confidence = overrides[pouch["pouch_index"]]
            detected = override_count
            if override_confidence is not None:
                confidence = override_confidence
        _record_image(pouch, user_id, detected, confidence)
        store.touch(pouch)

    engine.recompute_mismatch_count(roll)
    store.touch(roll)

    store.commit()
    return response.object_response(store.serialize(roll))


def _record_image(pouch, user_id, detected_pill_count, image_confidence_pct):
    pouch["detected_pill_count"] = detected_pill_count
    pouch["image_confidence_pct"] = image_confidence_pct
    pouch["verification_result"] = calc.imaging_result(
        image_confidence_pct, detected_pill_count, pouch["expected_pill_count"]
    )
    pouch["imaged_by_user_id"] = user_id
    pouch["imaged_at"] = clock.now_iso()


@bp.post("/pouch-rolls/<roll_id>/verify")
def verify(roll_id):
    user_id, _role = middleware.authenticate(("VerifyingPharmacist",))
    roll = middleware.lookup("pouch_roll", roll_id)

    if roll["verification_status"] != "PACKED":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    pouches = engine.pouches_of_roll(roll_id)
    if any(pouch["verification_result"] == "PENDING" for pouch in pouches):
        raise ApiError("ERR_INVALID_ROLL_STATE")
    if user_id == roll["packed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    cycle = db.fill_cycles[roll["cycle_id"]]
    roll["verified_by_user_id"] = user_id
    roll["verified_at"] = clock.now_iso()

    if roll["mismatch_pouch_count"] == 0:
        roll["verification_status"] = "PASSED"
        if cycle["packaging_status"] == "PACKED":
            cycle["packaging_status"] = "VERIFIED"
    else:
        roll["verification_status"] = "FAILED_QUARANTINED"
        if cycle["packaging_status"] == "PACKED":
            cycle["packaging_status"] = "ROLL_GENERATED"
        engine.issue_memo(
            engine.patient_of_cycle(cycle),
            cycle["id"],
            "FAILED_VERIFICATION",
            enums.FAILED_VERIFICATION_CREDIT_CENTS,
        )

    store.touch(roll)
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(roll))


@bp.post("/pouch-rolls/<roll_id>/rework")
def rework(roll_id):
    middleware.authenticate(("VerifyingPharmacist",))
    roll = middleware.lookup("pouch_roll", roll_id)

    if roll["verification_status"] != "FAILED_QUARANTINED":
        raise ApiError("ERR_INVALID_ROLL_STATE")
    if roll["rework_count"] >= enums.REWORK_LIMIT:
        raise ApiError("ERR_REWORK_LIMIT_REACHED")

    roll["verification_status"] = "BUILT"
    roll["rework_count"] += 1
    roll["packed_by_user_id"] = None
    roll["packed_at"] = None
    roll["verified_by_user_id"] = None
    roll["verified_at"] = None
    roll["mismatch_pouch_count"] = 0
    store.touch(roll)

    for pouch in engine.pouches_of_roll(roll_id):
        if pouch["verification_result"] == "VOID":
            continue
        pouch["verification_result"] = "PENDING"
        pouch["detected_pill_count"] = None
        pouch["image_confidence_pct"] = None
        pouch["imaged_by_user_id"] = None
        pouch["imaged_at"] = None
        store.touch(pouch)

    store.commit()
    return response.object_response(store.serialize(roll))
