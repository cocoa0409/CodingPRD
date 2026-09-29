"""Qualifying test endpoints. Rows are immutable: no updated_at, no version."""
from flask import Blueprint

from calc import qualifying_group_determination
from core import (
    CLINICAL_READERS,
    ROLE_INTAKE,
    ApiError,
    authenticate,
    base_row,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    parse_datetime,
    respond,
    sorted_rows,
    str_filter,
)
from domain import get_patient, get_qualifying_test
from serial import qualifying_test_out
from validate import Field, validate

bp = Blueprint("qualifying_tests", __name__)

TEST_TYPES = (
    "RESTING_ROOM_AIR",
    "EXERCISE",
    "NOCTURNAL_OVERNIGHT_OXIMETRY",
    "SLEEP_STUDY",
)
QUALIFYING_GROUPS = ("GROUP_I", "GROUP_II", "NON_QUALIFYING")

CREATE_FIELDS = [
    Field("patient_id", "string", required=True, min_len=1),
    Field("test_type", "enum", required=True, enum=TEST_TYPES),
    Field("spo2_percent", "integer", nullable=True, default=None, minimum=50, maximum=100),
    Field("pao2_mmhg", "integer", nullable=True, default=None, minimum=20, maximum=120),
    Field("desat_minutes", "integer", default=0, minimum=0, maximum=1440),
    Field("cor_pulmonale_or_edema", "boolean", default=False),
    Field("tested_at", "datetime", required=True),
    Field("ordering_physician_npi", "string", required=True, pattern=r"^\d{10}$"),
]


@bp.post("/qualifying-tests")
def create_qualifying_test():
    authenticate((ROLE_INTAKE,))
    data = validate(CREATE_FIELDS)
    patient = get_patient(data["patient_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    tested_at = parse_datetime(data["tested_at"])
    if tested_at > now():
        raise ApiError("ERR_TEST_DATE_IN_FUTURE")
    group, validity_days, expires_at = qualifying_group_determination(
        data["test_type"],
        data["spo2_percent"],
        data["pao2_mmhg"],
        data["desat_minutes"],
        data["cor_pulmonale_or_edema"],
        tested_at,
    )
    row = base_row(versioned=False)
    row.update(
        {
            "patient_id": patient["id"],
            "test_type": data["test_type"],
            "spo2_percent": data["spo2_percent"],
            "pao2_mmhg": data["pao2_mmhg"],
            "desat_minutes": data["desat_minutes"],
            "cor_pulmonale_or_edema": data["cor_pulmonale_or_edema"],
            "tested_at": tested_at,
            "ordering_physician_npi": data["ordering_physician_npi"],
            "qualifying_group": group,
            "validity_days": validity_days,
            "test_validity_expires_at": expires_at,
        }
    )
    db.qualifying_tests[row["id"]] = row
    return respond(qualifying_test_out(row), 201)


@bp.get("/qualifying-tests")
def list_qualifying_tests():
    authenticate(CLINICAL_READERS)
    patient_id = str_filter("patient_id")
    test_type = enum_filter("test_type", TEST_TYPES)
    group = enum_filter("qualifying_group", QUALIFYING_GROUPS)
    limit, offset = pagination()
    rows = sorted_rows(db.qualifying_tests.values())
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if test_type is not None:
        rows = [r for r in rows if r["test_type"] == test_type]
    if group is not None:
        rows = [r for r in rows if r["qualifying_group"] == group]
    return paginate(rows, limit, offset, qualifying_test_out)


@bp.get("/qualifying-tests/<test_id>")
def read_qualifying_test(test_id):
    authenticate(CLINICAL_READERS)
    return respond(qualifying_test_out(get_qualifying_test(test_id)))
