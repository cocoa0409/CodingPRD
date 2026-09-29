"""Chamber scheduling, energy testing, certification and revocation (PRD 3.3 / 3.4)."""

from datetime import timedelta

from flask import Blueprint

import serialize
from calculations import energy_limit_daily_kwh, energy_use_index
from db import db, new_row, rows
from errors import (
    ERR_CASE_MODEL_REVISION_STALE,
    ERR_CHAMBER_CLASS_UNSUPPORTED,
    ERR_CHAMBER_TDA_EXCEEDED,
    ERR_CHAMBER_WINDOW_CONFLICT,
    ERR_DUPLICATE_CODE,
    ERR_GWP_EXCEEDS_STANDARD,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CASE_MODEL_VERSION,
    ERR_STANDARD_NOT_APPLICABLE,
    fail,
)
from middleware import ALL_ROLES, roles_required, user_id
from response import created, ok, ok_list
from services import (
    apply_compliance_hold_cascade,
    clear_compliance_hold_cascade,
    get_case_model,
    get_compliance_label,
    get_energy_standard,
    get_energy_test,
    get_test_chamber,
    touch,
)
from validation import (
    filter_enum,
    filter_value,
    get_body,
    paginate,
    pagination,
    req_datetime,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("testing", __name__)

TEST_STATUSES = ["SCHEDULED", "RUNNING", "COMPLETED_PASS", "COMPLETED_FAIL", "INVALIDATED"]
LABEL_STATUSES = ["ISSUED", "SUPERSEDED", "REVOKED"]


def _check_revision(test, model):
    """Rank 14."""
    if test["pinned_design_revision"] != model["design_revision"]:
        fail(ERR_CASE_MODEL_REVISION_STALE,
             "Test pinned design revision %s no longer matches the model's %s"
             % (test["pinned_design_revision"], model["design_revision"]))


# --------------------------------------------------------------------------
@bp.post("/energy-tests")
@roles_required("TestLabTechnician")
def create_energy_test():
    body = get_body()
    case_model_id = req_string(body, "case_model_id")
    test_chamber_id = req_string(body, "test_chamber_id")
    energy_standard_id = req_string(body, "energy_standard_id")
    window_start_raw, window_start = req_datetime(body, "window_start")
    window_end_raw, window_end = req_datetime(body, "window_end")
    test_ambient_c = req_number(body, "test_ambient_c")
    store_ambient_c = req_number(body, "store_ambient_c")
    expected_version = req_int(body, "expected_case_model_version")

    model = get_case_model(case_model_id)             # rank 6
    chamber = get_test_chamber(test_chamber_id)
    standard = get_energy_standard(energy_standard_id)

    if expected_version != model["version"]:          # rank 8
        fail(ERR_STALE_CASE_MODEL_VERSION,
             "Case model version is %s, not %s" % (model["version"], expected_version))

    # rank 13
    if standard["temperature_class"] != model["temperature_class"]:
        fail(ERR_STANDARD_NOT_APPLICABLE,
             "Standard covers %s cases, not %s"
             % (standard["temperature_class"], model["temperature_class"]))
    if standard["system_type_scope"] != "ANY" \
            and standard["system_type_scope"] != model["system_type"]:
        fail(ERR_STANDARD_NOT_APPLICABLE,
             "Standard scope %s does not cover a %s circuit"
             % (standard["system_type_scope"], model["system_type"]))
    if window_start < standard["_effective_date"]:
        fail(ERR_STANDARD_NOT_APPLICABLE,
             "Test window begins before the standard's effective date")

    # rank 22
    if model["temperature_class"] not in chamber["supported_temperature_classes"]:
        fail(ERR_CHAMBER_CLASS_UNSUPPORTED,
             "Chamber %s does not support %s"
             % (chamber["chamber_code"], model["temperature_class"]))

    # rank 23
    if model["tda_sqft"] > chamber["max_tda_sqft"]:
        fail(ERR_CHAMBER_TDA_EXCEEDED,
             "Chamber %s accepts at most %s sqft"
             % (chamber["chamber_code"], chamber["max_tda_sqft"]))

    # rank 24
    _check_chamber_availability(chamber, window_start, window_end)

    # rank 29
    if window_end <= window_start:
        fail(ERR_INVALID_INTERVAL, "window_end must be strictly after window_start")

    row = new_row()
    row.update({
        "case_model_id": case_model_id,
        "test_chamber_id": test_chamber_id,
        "energy_standard_id": energy_standard_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "_window_start": window_start,
        "_window_end": window_end,
        "test_ambient_c": test_ambient_c,
        "store_ambient_c": store_ambient_c,
        "pinned_design_revision": model["design_revision"],
        "pinned_tda_sqft": model["tda_sqft"],
        "pinned_defrost_cycles_per_day": model["defrost_cycles_per_day"],
        "limit_daily_kwh": energy_limit_daily_kwh(standard, model["tda_sqft"]),
        "measured_kwh_24h": None,
        "measured_defrost_cycles": None,
        "lab_rated_index": None,
        "field_projected_daily_kwh": None,
        "field_projected_index": None,
        "field_exceedance": None,
        "status": "SCHEDULED",
    })
    db.energy_tests[row["id"]] = row

    touch(model)  # scheduling bumps the case model's version
    return created(serialize.dump("EnergyTest", row))


def _check_chamber_availability(chamber, window_start, window_end):
    buffer_ = timedelta(hours=chamber["turnaround_hours"])
    for other in rows(db.energy_tests):
        if other["test_chamber_id"] != chamber["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        blocked_start = other["_window_start"] - buffer_
        blocked_end = other["_window_end"] + buffer_
        if window_start < blocked_end and blocked_start < window_end:
            fail(ERR_CHAMBER_WINDOW_CONFLICT,
                 "Chamber %s is occupied over the requested window"
                 % chamber["chamber_code"])

    closed_start = chamber.get("_closed_window_start")
    closed_end = chamber.get("_closed_window_end")
    if closed_start is not None and closed_end is not None:
        # closure is a closed interval on both ends
        if window_start <= closed_end and closed_start < window_end:
            fail(ERR_CHAMBER_WINDOW_CONFLICT,
                 "Chamber %s is closed for maintenance over the requested window"
                 % chamber["chamber_code"])


@bp.post("/energy-tests/<test_id>/start")
@roles_required("TestLabTechnician")
def start_energy_test(test_id):
    get_body()
    test = get_energy_test(test_id)

    if test["status"] != "SCHEDULED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a SCHEDULED test may be started")

    model = db.case_models.get(test["case_model_id"])
    _check_revision(test, model)       # rank 14

    if model["status"] != "SUBMITTED_FOR_TEST":
        fail(ERR_INVALID_STATE_TRANSITION,
             "The case model must still be SUBMITTED_FOR_TEST")

    test["status"] = "RUNNING"
    touch(test)
    return ok(serialize.dump("EnergyTest", test))


@bp.post("/energy-tests/<test_id>/complete")
@roles_required("TestLabTechnician")
def complete_energy_test(test_id):
    body = get_body()
    measured_kwh_24h = req_number(body, "measured_kwh_24h", minimum=0)
    measured_defrost_cycles = req_int(body, "measured_defrost_cycles", minimum=0)

    test = get_energy_test(test_id)

    if test["status"] != "RUNNING":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION, "Only a RUNNING test may be completed")

    model = db.case_models.get(test["case_model_id"])
    _check_revision(test, model)     # rank 14

    if model["status"] != "SUBMITTED_FOR_TEST":
        fail(ERR_INVALID_STATE_TRANSITION,
             "The case model must still be SUBMITTED_FOR_TEST")

    test["measured_kwh_24h"] = measured_kwh_24h
    test["measured_defrost_cycles"] = measured_defrost_cycles
    energy_use_index(test)

    if measured_kwh_24h <= test["limit_daily_kwh"]:
        test["status"] = "COMPLETED_PASS"
        model["status"] = "TESTED_PASS"
    else:
        test["status"] = "COMPLETED_FAIL"
        model["status"] = "TESTED_FAIL"

    touch(test)
    touch(model)
    return ok(serialize.dump("EnergyTest", test))


@bp.get("/energy-tests/<test_id>")
@roles_required(*ALL_ROLES)
def read_energy_test(test_id):
    return ok(serialize.dump("EnergyTest", get_energy_test(test_id)))


@bp.get("/energy-tests")
@roles_required(*ALL_ROLES)
def list_energy_tests():
    limit, offset = pagination()
    case_model_id = filter_value("case_model_id")
    test_chamber_id = filter_value("test_chamber_id")
    energy_standard_id = filter_value("energy_standard_id")
    status = filter_enum("status", TEST_STATUSES)

    items = rows(db.energy_tests)
    if case_model_id is not None:
        items = [r for r in items if r["case_model_id"] == case_model_id]
    if test_chamber_id is not None:
        items = [r for r in items if r["test_chamber_id"] == test_chamber_id]
    if energy_standard_id is not None:
        items = [r for r in items if r["energy_standard_id"] == energy_standard_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("EnergyTest", page), limit, offset, total)


# --------------------------------------------------------------------------
# compliance labels
# --------------------------------------------------------------------------
@bp.post("/compliance-labels")
@roles_required("ComplianceOfficer")
def issue_compliance_label():
    body = get_body()
    case_model_id = req_string(body, "case_model_id")
    energy_test_id = req_string(body, "energy_test_id")
    label_code = req_string(body, "label_code", 1, 32)

    model = get_case_model(case_model_id)     # rank 6
    test = get_energy_test(energy_test_id)

    # rank 7
    if model["status"] != "TESTED_PASS":
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a TESTED_PASS case model may be certified")
    if test["case_model_id"] != model["id"]:
        fail(ERR_INVALID_STATE_TRANSITION,
             "The energy test does not belong to this case model")
    if test["status"] != "COMPLETED_PASS":
        fail(ERR_INVALID_STATE_TRANSITION,
             "A label may only be issued from a COMPLETED_PASS test")

    # rank 9
    if model.get("submitted_by_user_id") is not None \
            and model["submitted_by_user_id"] == user_id():
        fail(ERR_SEGREGATION_OF_DUTIES,
             "The issuing officer may not be the engineer who submitted the design")

    standard = db.energy_standards.get(test["energy_standard_id"])
    refrigerant = db.refrigerants.get(model["refrigerant_id"])

    # rank 12
    if refrigerant["gwp_100yr"] > standard["max_gwp"]:
        fail(ERR_GWP_EXCEEDS_STANDARD,
             "Refrigerant GWP %d exceeds the standard ceiling of %d"
             % (refrigerant["gwp_100yr"], standard["max_gwp"]))

    _check_revision(test, model)  # rank 14

    for existing in db.compliance_labels.values():  # rank 21
        if existing["label_code"] == label_code:
            fail(ERR_DUPLICATE_CODE, "label_code '%s' already exists" % label_code)

    row = new_row()
    row.update({
        "case_model_id": case_model_id,
        "energy_test_id": energy_test_id,
        "label_code": label_code,
        "pinned_design_revision": model["design_revision"],
        "pinned_lab_rated_index": test["lab_rated_index"],
        "pinned_standard_code": standard["standard_code"],
        "issued_by_user_id": user_id(),
        "label_status": "ISSUED",
        "revocation_reason": None,
    })
    db.compliance_labels[row["id"]] = row

    model["status"] = "CERTIFIED"
    touch(model)

    clear_compliance_hold_cascade(model)
    return created(serialize.dump("ComplianceLabel", row))


@bp.post("/compliance-labels/<label_id>/revoke")
@roles_required("ComplianceOfficer")
def revoke_compliance_label(label_id):
    body = get_body()
    revocation_reason = req_string(body, "revocation_reason")

    label = get_compliance_label(label_id)

    if label["label_status"] != "ISSUED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION, "Only an ISSUED label may be revoked")

    model = db.case_models.get(label["case_model_id"])
    if model is None or model["status"] != "CERTIFIED":
        fail(ERR_INVALID_STATE_TRANSITION,
             "The labelled case model must be CERTIFIED to be decertified")

    # hop 1
    label["label_status"] = "REVOKED"
    label["revocation_reason"] = revocation_reason
    touch(label)

    # hop 2
    model["status"] = "DECERTIFIED"
    touch(model)

    # hops 3, 4 and 5
    apply_compliance_hold_cascade(model)

    return ok(serialize.dump("ComplianceLabel", label))


@bp.get("/compliance-labels/<label_id>")
@roles_required(*ALL_ROLES)
def read_compliance_label(label_id):
    return ok(serialize.dump("ComplianceLabel", get_compliance_label(label_id)))


@bp.get("/compliance-labels")
@roles_required(*ALL_ROLES)
def list_compliance_labels():
    limit, offset = pagination()
    case_model_id = filter_value("case_model_id")
    energy_test_id = filter_value("energy_test_id")
    label_status = filter_enum("label_status", LABEL_STATUSES)

    items = rows(db.compliance_labels)
    if case_model_id is not None:
        items = [r for r in items if r["case_model_id"] == case_model_id]
    if energy_test_id is not None:
        items = [r for r in items if r["energy_test_id"] == energy_test_id]
    if label_status is not None:
        items = [r for r in items if r["label_status"] == label_status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("ComplianceLabel", page), limit, offset, total)
