"""Lab tests: schedule, list, read, record result (FAIL on SOURCE_RAW suspends the permit)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, touch, by_creation, logical_date
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    as_date,
    as_datetime,
    create_lab_test,
    get_body,
    get_or_404,
    raise_shape,
    suspend_permit,
    test_json,
)

bp = Blueprint("labtests", __name__)

QAO = ["QAOfficer"]

SUBJECT_FIELD = {
    "SOURCE_RAW": "subject_permit_id",
    "FINISHED_PRODUCT": "subject_lot_id",
    "BOTTLE_SANITATION": "subject_wash_batch_id",
}
SUBJECT_COLLECTION = {
    "subject_permit_id": ("permits", "permit"),
    "subject_lot_id": ("lots", "production lot"),
    "subject_wash_batch_id": ("wash_batches", "wash batch"),
}
DEFAULT_DUE_DAYS = {"SOURCE_RAW": 7, "FINISHED_PRODUCT": 2, "BOTTLE_SANITATION": 1}


def _subject_plant(field, entity):
    if field == "subject_permit_id":
        return entity["plant_id"]
    if field == "subject_wash_batch_id":
        return entity["plant_id"]
    if field == "subject_lot_id":
        line = store.lines.get(entity["line_id"])
        return line["plant_id"] if line else None
    return None


@bp.post("/api/plants/<plant_id>/lab-tests")
@auth(QAO)
def create_test(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()

    # Rung 3 — existence of every supplied subject FK.
    supplied = {}
    for field, (coll_name, what) in SUBJECT_COLLECTION.items():
        sid = body.get(field)
        if sid is not None:
            entity = getattr(store, coll_name).get(sid) if isinstance(sid, str) else None
            if entity is None:
                raise ApiError("ERR_NOT_FOUND", f"{field} does not reference an existing {what}", 404)
            supplied[field] = entity

    test_type = body.get("test_type")
    type_ok = test_type in SUBJECT_FIELD

    # Rung 8 — cross-plant reference first, then subject/type matching.
    if type_ok:
        for field, entity in supplied.items():
            if _subject_plant(field, entity) != plant["id"]:
                raise ApiError(
                    "ERR_CROSS_PLANT_REFERENCE",
                    "the referenced subject belongs to a different plant",
                    409,
                )
        expected = SUBJECT_FIELD[test_type]
        extra = [f for f in SUBJECT_FIELD.values() if f != expected and f in supplied]
        if expected not in supplied or extra:
            raise ApiError(
                "ERR_SUBJECT_TYPE_MISMATCH",
                "exactly one subject FK matching test_type is required",
                409,
            )

    # Rung 11 — input shape.
    errs = []
    if not type_ok:
        errs.append("test_type must be SOURCE_RAW, FINISHED_PRODUCT, or BOTTLE_SANITATION")
    due_raw = body.get("due_date")
    if due_raw is not None:
        due, ok_due = as_date(due_raw)
        if not ok_due:
            errs.append("due_date must be a valid ISO date")
    else:
        due = None
    raise_shape(errs)

    if due is None:
        due = logical_date() + timedelta(days=DEFAULT_DUE_DAYS[test_type])
        due_raw = due.isoformat()

    field = SUBJECT_FIELD[test_type]
    t = create_lab_test(plant["id"], test_type, field, body.get(field), due, "MANUAL")
    t["due_date"] = due_raw
    return ok_object(test_json(t), 201)


@bp.get("/api/lab-tests")
@auth(ALL_ROLES)
def list_tests():
    items = list(store.lab_tests.values())
    filters = (
        ("plant_id", "plant_id"),
        ("subject_permit_id", "subject_permit_id"),
        ("subject_lot_id", "subject_lot_id"),
        ("subject_wash_batch_id", "subject_wash_batch_id"),
        ("test_type", "test_type"),
        ("status", "status"),
    )
    for qp, field in filters:
        val = request.args.get(qp)
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    return ok_list([test_json(t) for t in by_creation(items)])


@bp.get("/api/lab-tests/<test_id>")
@auth(ALL_ROLES)
def get_test(test_id):
    t = get_or_404(store.lab_tests, test_id, "lab test")
    return ok_object(test_json(t))


@bp.post("/api/lab-tests/<test_id>/record-result")
@auth(QAO)
def record_result(test_id):
    t = get_or_404(store.lab_tests, test_id, "lab test")
    if t["status"] not in ("SCHEDULED", "DUE", "OVERDUE"):
        raise err_invalid_state("the test has already been completed")
    body = get_body()

    result = body.get("result")
    collected, ok_col = as_datetime(body.get("collected_at"))
    errs = []
    if result not in ("PASS", "FAIL"):
        errs.append("result must be PASS or FAIL")
    if not ok_col:
        errs.append("collected_at must be a valid ISO 8601 datetime")
    raise_shape(errs)

    t["result"] = result
    t["status"] = "COMPLETED_PASS" if result == "PASS" else "COMPLETED_FAIL"
    t["collected_at"] = body.get("collected_at")
    t["_collected"] = collected
    touch(t)

    # A failing raw-source test suspends the subject permit (cascade).
    if result == "FAIL" and t["test_type"] == "SOURCE_RAW":
        permit = store.permits.get(t.get("subject_permit_id"))
        if permit is not None:
            suspend_permit(permit, "SOURCE_TEST_FAIL")
    return ok_object(test_json(t))
