"""License issuance and renewal endpoints (PRD section 3.6, 2.7)."""
from flask import Blueprint

import db
from db import db as store
from db import LICENSE_CLASSES
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services import calculations as calc
from services.common import (
    new_common, touch, get_json_body, require_fields, require_int, opt_bool,
)
from services.lookup import fetch

bp = Blueprint("licenses", __name__)


def _has_renewal_fee(record_id, fee_cents):
    """Most-recent CAPTURED RENEWAL payment with amount >= fee_cents."""
    candidates = [
        f for f in store.fee_payments.values()
        if f["driver_record_id"] == record_id
        and f["purpose"] == "RENEWAL"
        and f["status"] == "CAPTURED"
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda f: (f["created_at"], f["id"]))
    most_recent = candidates[-1]
    return most_recent["amount_cents"] >= fee_cents


def _current_issued_license(record_id):
    issued = [
        l for l in store.licenses.values()
        if l["driver_record_id"] == record_id and l["status"] == "ISSUED"
    ]
    if not issued:
        return None
    issued.sort(key=lambda l: (l["created_at"], l["id"]))
    return issued[-1]


@bp.post("/licenses")
def issue_license():
    user_id, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "road_test_appointment_id", "license_class"])
    driver_record_id = body["driver_record_id"]
    appt_id = body["road_test_appointment_id"]
    record = fetch(store.driver_records, driver_record_id)
    appt = fetch(store.road_test_appointments, appt_id)
    license_class = body["license_class"]
    if license_class not in LICENSE_CLASSES:
        raise err("ERR_INVALID_REQUEST", "invalid license_class")
    is_real_id = opt_bool(body, "is_real_id", False)

    # state (priority 5): record must be ELIGIBLE
    if record["licensing_status"] != "ELIGIBLE":
        raise err("ERR_RECORD_NOT_ELIGIBLE", "License issuance requires ELIGIBLE record")
    # business-safety (priority 6+): road test passed
    if appt.get("outcome") != "PASS":
        raise err("ERR_ROAD_TEST_NOT_PASSED", "Referenced road test outcome is not PASS")
    # segregation of duties
    if user_id == appt.get("scored_by_examiner_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Examiner who scored the test cannot issue its license")
    # REAL ID
    if is_real_id and record["real_id_status"] != "APPROVED":
        raise err("ERR_REAL_ID_NOT_VERIFIED", "REAL ID requires real_id_status == APPROVED")
    # fee — fee_cents with days_late=0 on first issuance
    age = calc.applicant_age(record["date_of_birth"])
    fee_cents = calc.renewal_fee(license_class, age, is_real_id,
                                 store.current_period, None)
    if not _has_renewal_fee(driver_record_id, fee_cents):
        raise err("ERR_RENEWAL_FEE_UNPAID", "No captured RENEWAL fee >= fee_cents")

    issued_period = store.current_period
    lic = new_common(
        driver_record_id=driver_record_id,
        road_test_appointment_id=appt_id,
        license_class=license_class,
        is_real_id=is_real_id,
        issued_period=issued_period,
        expiry_period=issued_period + db.LICENSE_TERM_PERIODS,
        fee_cents=fee_cents,
        status="ISSUED",
    )
    store.licenses[lic["id"]] = lic
    record["licensing_status"] = "ACTIVE"
    touch(record)
    return success(serialize.license_obj(lic), 201, "object")


@bp.post("/licenses/renew")
def renew_license():
    user_id, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["driver_record_id", "license_class",
                          "expected_driver_record_version"])
    driver_record_id = body["driver_record_id"]
    record = fetch(store.driver_records, driver_record_id)
    license_class = body["license_class"]
    if license_class not in LICENSE_CLASSES:
        raise err("ERR_INVALID_REQUEST", "invalid license_class")
    is_real_id = opt_bool(body, "is_real_id", False)
    expected_version = require_int(body, "expected_driver_record_version")

    # OCC (priority 4) — before any business logic
    if expected_version != record["version"]:
        raise err("ERR_STALE_RECORD_VERSION",
                  "expected_driver_record_version does not match record version")
    # REAL ID
    if is_real_id and record["real_id_status"] != "APPROVED":
        raise err("ERR_REAL_ID_NOT_VERIFIED", "REAL ID requires real_id_status == APPROVED")
    # fee with days_late from prior current license expiry
    prior = _current_issued_license(driver_record_id)
    prior_expiry = prior["expiry_period"] if prior is not None else None
    age = calc.applicant_age(record["date_of_birth"])
    fee_cents = calc.renewal_fee(license_class, age, is_real_id,
                                 store.current_period, prior_expiry)
    if not _has_renewal_fee(driver_record_id, fee_cents):
        raise err("ERR_RENEWAL_FEE_UNPAID", "No captured RENEWAL fee >= fee_cents")

    issued_period = store.current_period
    lic = new_common(
        driver_record_id=driver_record_id,
        road_test_appointment_id=None,
        license_class=license_class,
        is_real_id=is_real_id,
        issued_period=issued_period,
        expiry_period=issued_period + db.LICENSE_TERM_PERIODS,
        fee_cents=fee_cents,
        status="ISSUED",
    )
    store.licenses[lic["id"]] = lic
    if prior is not None:
        prior["status"] = "RENEWED"
        touch(prior)
    touch(record)
    return success(serialize.license_obj(lic), 201, "object")
