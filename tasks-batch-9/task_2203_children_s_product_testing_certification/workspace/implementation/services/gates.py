"""The four laboratory-integrity gates (PRD 2.10)."""

import clock
import db
from errors import ApiError


def require_not_barred(laboratory):
    if laboratory["operational_state"] == "BARRED":
        raise ApiError("ERR_LAB_BARRED")


def require_attestation_current(laboratory):
    now = clock.now()
    valid_through = laboratory["influence_attestation_valid_through"]
    if laboratory["influence_attestation_state"] != "CURRENT":
        raise ApiError("ERR_UNDUE_INFLUENCE_ATTESTATION_MISSING")
    if valid_through is None or valid_through < now:
        raise ApiError("ERR_UNDUE_INFLUENCE_ATTESTATION_MISSING")


def find_covering_accreditation(laboratory_id, test_method_code):
    now = clock.now()
    for row in db.all_rows("lab_accreditations"):
        if row["laboratory_id"] != laboratory_id:
            continue
        if row["test_method_code"] != test_method_code:
            continue
        if row["accreditation_state"] != "ACCREDITED":
            continue
        if row["valid_from"] <= now <= row["valid_through"]:
            return row
    return None


def require_method_accreditation(laboratory, rule):
    row = find_covering_accreditation(laboratory["id"], rule["test_method_code"])
    if row is None:
        raise ApiError("ERR_LAB_METHOD_NOT_ACCREDITED")
    return row


def require_not_manufacturer_owned(laboratory):
    if laboratory["independence_class"] == "MANUFACTURER_OWNED":
        raise ApiError("ERR_MANUFACTURER_OWNED_LAB_FORBIDDEN")
