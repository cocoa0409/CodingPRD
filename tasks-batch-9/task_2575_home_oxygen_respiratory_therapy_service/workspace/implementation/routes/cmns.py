"""Certificate of medical necessity endpoints.

The certificate lifecycle is cyclic (DRAFT -> SUBMITTED -> RETURNED_FOR_CORRECTION
-> DRAFT) and every write that lands on the patient's most-recently-created
certificate re-derives the Patient.current_cmn_status mirror.
"""
from decimal import Decimal

from flask import Blueprint

from calc import (
    DOC_SCORE_PASS,
    documentation_score,
    recert_due_date,
    test_is_stale,
)
from core import (
    CLINICAL_READERS,
    ROLE_AUDITOR,
    ROLE_INTAKE,
    ROLE_PHYSICIAN,
    ApiError,
    actor,
    authenticate,
    base_row,
    db,
    enum_filter,
    order_key,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    today,
    touch,
)
from domain import (
    get_cmn,
    get_patient,
    get_qualifying_test,
    rederive_cmn_mirror,
    suspend_contracts_for_cmn,
)
from serial import cmn_out
from validate import Field, validate

bp = Blueprint("cmns", __name__)

FORM_TYPES = ("INITIAL", "RECERTIFICATION", "REVISED")
CMN_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "PHYSICIAN_SIGNED",
    "RETURNED_FOR_CORRECTION",
    "ACTIVE",
    "EXPIRED",
    "VOIDED",
    "SUPERSEDED",
)
MAX_REVISION_ROUNDS = 3

CREATE_FIELDS = [
    Field("patient_id", "string", required=True, min_len=1),
    Field("qualifying_test_id", "string", required=True, min_len=1),
    Field("form_type", "enum", required=True, enum=FORM_TYPES),
    Field("prescribed_lpm", "number", required=True, minimum="0.5", maximum="15.0"),
    Field("hours_per_day", "integer", required=True, minimum=1, maximum=24),
    Field("portable_prescribed", "boolean", default=False),
    Field("length_of_need_months", "integer", required=True, minimum=1, maximum=99),
    Field("narrative_element_count", "integer", default=0, minimum=0, maximum=3),
    Field("expected_patient_version", "integer", required=True, minimum=0),
]

PATCH_FIELDS = [
    Field("prescribed_lpm", "number", minimum="0.5", maximum="15.0"),
    Field("hours_per_day", "integer", minimum=1, maximum=24),
    Field("portable_prescribed", "boolean"),
    Field("length_of_need_months", "integer", minimum=1, maximum=99),
    Field("narrative_element_count", "integer", minimum=0, maximum=3),
]

RETURN_FIELDS = [Field("correction_notes", "string", required=True)]

VOID_FIELDS = [Field("void_reason", "string", required=True, min_len=1)]

EDITABLE = (
    "prescribed_lpm",
    "hours_per_day",
    "portable_prescribed",
    "length_of_need_months",
    "narrative_element_count",
)


def _rescore(cmn):
    """Recompute documentation_score from the live certificate + study + patient."""
    test = db.qualifying_tests.get(cmn["qualifying_test_id"])
    patient = db.patients.get(cmn["patient_id"])
    cmn["documentation_score"] = documentation_score(cmn, test, patient)
    return cmn["documentation_score"]


@bp.post("/cmns")
def create_cmn():
    authenticate((ROLE_INTAKE,))
    data = validate(CREATE_FIELDS)
    patient = get_patient(data["patient_id"])
    test = get_qualifying_test(data["qualifying_test_id"])
    if data["expected_patient_version"] != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    if test["qualifying_group"] == "NON_QUALIFYING":
        raise ApiError("ERR_TEST_NON_QUALIFYING")
    if test["patient_id"] != patient["id"]:
        raise ApiError("ERR_TEST_PATIENT_MISMATCH")
    row = base_row()
    row.update(
        {
            "patient_id": patient["id"],
            "qualifying_test_id": test["id"],
            "form_type": data["form_type"],
            "prescribed_lpm": data["prescribed_lpm"],
            "hours_per_day": data["hours_per_day"],
            "portable_prescribed": data["portable_prescribed"],
            "length_of_need_months": data["length_of_need_months"],
            "narrative_element_count": data["narrative_element_count"],
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "signed_by_user_id": None,
            "audited_by_user_id": None,
            "physician_signature_date": None,
            "initial_date": None,
            "recert_due_date": None,
            "revision_round": 0,
            "correction_notes": None,
            "void_reason": None,
            "documentation_score": Decimal("0.00"),
        }
    )
    db.cmns[row["id"]] = row
    _rescore(row)
    patient["current_cmn_status"] = "DRAFT"
    touch(patient)
    return respond(cmn_out(row), 201)


@bp.get("/cmns")
def list_cmns():
    authenticate(CLINICAL_READERS)
    patient_id = str_filter("patient_id")
    test_id = str_filter("qualifying_test_id")
    status = enum_filter("status", CMN_STATUSES)
    form_type = enum_filter("form_type", FORM_TYPES)
    limit, offset = pagination()
    rows = sorted_rows(db.cmns.values())
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if test_id is not None:
        rows = [r for r in rows if r["qualifying_test_id"] == test_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if form_type is not None:
        rows = [r for r in rows if r["form_type"] == form_type]
    return paginate(rows, limit, offset, cmn_out)


@bp.get("/cmns/<cmn_id>")
def read_cmn(cmn_id):
    authenticate(CLINICAL_READERS)
    return respond(cmn_out(get_cmn(cmn_id)))


@bp.patch("/cmns/<cmn_id>")
def patch_cmn(cmn_id):
    """RETURNED_FOR_CORRECTION -> DRAFT; closes the revision cycle."""
    authenticate((ROLE_INTAKE,))
    cmn = get_cmn(cmn_id)
    data = validate(PATCH_FIELDS)
    if cmn["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError("ERR_INVALID_STATE")
    for key in EDITABLE:
        if key in data:
            cmn[key] = data[key]
    _rescore(cmn)
    cmn["submitted_by_user_id"] = None
    cmn["status"] = "DRAFT"
    touch(cmn)
    patient = get_patient(cmn["patient_id"])
    rederive_cmn_mirror(patient, (cmn["id"],))
    return respond(cmn_out(cmn))


@bp.post("/cmns/<cmn_id>/submit")
def submit_cmn(cmn_id):
    authenticate((ROLE_INTAKE,))
    cmn = get_cmn(cmn_id)
    if cmn["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    patient = get_patient(cmn["patient_id"])
    if patient["status"] != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE")
    test = db.qualifying_tests.get(cmn["qualifying_test_id"])
    if test is not None and test_is_stale(test):
        raise ApiError("ERR_QUALIFYING_TEST_STALE")
    if _rescore(cmn) < DOC_SCORE_PASS:
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
    cmn["submitted_by_user_id"] = actor()
    cmn["status"] = "SUBMITTED"
    touch(cmn)
    rederive_cmn_mirror(patient, (cmn["id"],))
    return respond(cmn_out(cmn))


@bp.post("/cmns/<cmn_id>/sign")
def sign_cmn(cmn_id):
    authenticate((ROLE_PHYSICIAN,))
    cmn = get_cmn(cmn_id)
    if cmn["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    cmn["signed_by_user_id"] = actor()
    cmn["physician_signature_date"] = today().isoformat()
    cmn["status"] = "PHYSICIAN_SIGNED"
    touch(cmn)
    rederive_cmn_mirror(get_patient(cmn["patient_id"]), (cmn["id"],))
    return respond(cmn_out(cmn))


@bp.post("/cmns/<cmn_id>/approve")
def approve_cmn(cmn_id):
    """PHYSICIAN_SIGNED -> ACTIVE with segregation of duties and supersession."""
    authenticate((ROLE_AUDITOR,))
    cmn = get_cmn(cmn_id)
    user = actor()
    if user is not None and user in (
        cmn["submitted_by_user_id"],
        cmn["signed_by_user_id"],
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if cmn["status"] != "PHYSICIAN_SIGNED":
        raise ApiError("ERR_INVALID_STATE")
    if _rescore(cmn) < DOC_SCORE_PASS:
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
    test = db.qualifying_tests.get(cmn["qualifying_test_id"])
    group = test["qualifying_group"] if test else "GROUP_I"
    initial = today()
    cmn["audited_by_user_id"] = user
    cmn["initial_date"] = initial.isoformat()
    cmn["recert_due_date"] = recert_due_date(
        initial, group, cmn["length_of_need_months"]
    ).isoformat()
    touched = [cmn["id"]]
    others = [
        row
        for row in db.cmns.values()
        if row["patient_id"] == cmn["patient_id"]
        and row["id"] != cmn["id"]
        and row["status"] == "ACTIVE"
    ]
    for other in sorted(others, key=order_key):
        other["status"] = "SUPERSEDED"
        touch(other)
        touched.append(other["id"])
    cmn["status"] = "ACTIVE"
    touch(cmn)
    rederive_cmn_mirror(get_patient(cmn["patient_id"]), touched)
    return respond(cmn_out(cmn))


@bp.post("/cmns/<cmn_id>/return-for-correction")
def return_cmn(cmn_id):
    authenticate((ROLE_AUDITOR,))
    cmn = get_cmn(cmn_id)
    data = validate(RETURN_FIELDS)
    if cmn["status"] not in ("SUBMITTED", "PHYSICIAN_SIGNED"):
        raise ApiError("ERR_INVALID_STATE")
    if cmn["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")
    cmn["revision_round"] += 1
    cmn["correction_notes"] = data["correction_notes"]
    cmn["signed_by_user_id"] = None
    cmn["physician_signature_date"] = None
    cmn["status"] = "RETURNED_FOR_CORRECTION"
    touch(cmn)
    rederive_cmn_mirror(get_patient(cmn["patient_id"]), (cmn["id"],))
    return respond(cmn_out(cmn))


@bp.post("/cmns/<cmn_id>/void")
def void_cmn(cmn_id):
    authenticate((ROLE_AUDITOR,))
    cmn = get_cmn(cmn_id)
    data = validate(VOID_FIELDS)
    if cmn["status"] not in ("ACTIVE", "DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_INVALID_STATE")
    was_active = cmn["status"] == "ACTIVE"
    cmn["void_reason"] = data["void_reason"]
    cmn["status"] = "VOIDED"
    touch(cmn)
    if was_active:
        suspend_contracts_for_cmn(cmn, "CMN_VOIDED")
    rederive_cmn_mirror(get_patient(cmn["patient_id"]), (cmn["id"],))
    return respond(cmn_out(cmn))
