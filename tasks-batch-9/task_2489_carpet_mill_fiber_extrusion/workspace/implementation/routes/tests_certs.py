"""Product testing and certification, including segregation of duties (PRD 3.8)."""

from flask import Blueprint

import calc
from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok
from services import compliance
from validators import (
    bad,
    json_body,
    opt_enum,
    req_enum,
    req_instant,
    req_num,
    req_str,
    req_str_list,
)

bp = Blueprint("tests_certs", __name__)

TEST_TYPES = ("WEAR_TARR", "STAIN_AATCC175", "FLAMMABILITY_PILL")
VERDICTS = ("PASS", "FAIL")
CERT_TYPES = ("DOC_FF_1_70", "NSF_140", "GREEN_LABEL_PLUS")
ACCOUNTING_BASES = ("MASS_BALANCE", "PHYSICAL_SEGREGATION", "NOT_APPLICABLE")
NSF_BASES = ("MASS_BALANCE", "PHYSICAL_SEGREGATION")
CERT_STATUSES = ("ACTIVE", "LAPSED", "REVOKED", "SUPERSEDED")

TEST_WRITE_ROLES = ("QALabTechnician", "PlantAdmin")
TEST_READ_ROLES = (
    "QALabTechnician",
    "CertificationOfficer",
    "MillPlanner",
    "PlantAdmin",
)
CERT_WRITE_ROLES = ("CertificationOfficer", "PlantAdmin")
CERT_READ_ROLES = (
    "CertificationOfficer",
    "MillPlanner",
    "QALabTechnician",
    "PlantAdmin",
)


# ---- product tests --------------------------------------------------------

@bp.post("/mill/product-tests")
def record_test():
    actor = authenticate(TEST_WRITE_ROLES)
    body = json_body()
    style_id = req_str(body, "style_id")
    roll_good_id = req_str(body, "roll_good_id")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    result_value = req_num(body, "result_value", 1, gt=0)

    # Rung 6 — body reference existence.
    fetch("styles", style_id)
    fetch("roll_goods", roll_good_id)

    test = insert(
        store.product_tests,
        {
            "style_id": style_id,
            "roll_good_id": roll_good_id,
            "test_type": test_type,
            "result_value": result_value,
            "verdict": calc.product_test_verdict(test_type, result_value),
            "tested_by_user_id": actor.user_id,
            "tested_at_utc": store.clock_raw,
        },
        versioned=False,
    )
    return created("product_test", test)


@bp.get("/mill/product-tests/<product_test_id>")
def read_test(product_test_id):
    authenticate(TEST_READ_ROLES)
    return ok("product_test", fetch("product_tests", product_test_id))


@bp.get("/mill/product-tests")
def list_tests():
    authenticate(TEST_READ_ROLES)
    return listing(
        "product_test",
        "product_tests",
        enum_filters={"test_type": TEST_TYPES, "verdict": VERDICTS},
        value_filters=("style_id", "roll_good_id"),
    )


# ---- certifications -------------------------------------------------------

def _has_pass(tests, test_type):
    return any(t["test_type"] == test_type and t["verdict"] == "PASS" for t in tests)


@bp.post("/mill/certifications")
def issue_certification():
    actor = authenticate(CERT_WRITE_ROLES)
    body = json_body()
    style_id = req_str(body, "style_id")
    cert_type = req_enum(body, "cert_type", CERT_TYPES)
    source_test_ids = req_str_list(body, "source_test_ids")
    expires_dt, expires_raw = req_instant(body, "expires_at_utc")
    accounting_basis = opt_enum(
        body, "accounting_basis", ACCOUNTING_BASES, default="NOT_APPLICABLE"
    )

    # Rung 4 — the accounting-basis rule and the expiry ordering.
    if cert_type == "NSF_140" and accounting_basis not in NSF_BASES:
        bad("accounting_basis must be MASS_BALANCE or PHYSICAL_SEGREGATION for NSF_140")
    if cert_type != "NSF_140" and accounting_basis != "NOT_APPLICABLE":
        bad("accounting_basis is only valid on an NSF_140 certificate")
    if not expires_dt > store.clock_dt:
        bad("expires_at_utc must be strictly later than the issuance instant")

    # Rung 6 — body reference existence, left to right.
    style = fetch("styles", style_id)
    cited = [fetch("product_tests", test_id) for test_id in source_test_ids]

    # Rung 12 — segregation of duties.
    for test in cited:
        if test["tested_by_user_id"] == actor.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The issuing officer recorded cited test %s" % test["id"],
            )

    # Rung 13 — the cited evidence must support the certificate.
    for test in cited:
        if test["style_id"] != style_id:
            raise ApiError(
                "ERR_CERT_EVIDENCE_MISSING",
                "Cited test %s belongs to another style" % test["id"],
            )
    if cert_type == "DOC_FF_1_70":
        if not cited or not _has_pass(cited, "FLAMMABILITY_PILL"):
            raise ApiError(
                "ERR_CERT_EVIDENCE_MISSING",
                "DOC_FF_1_70 requires a passing FLAMMABILITY_PILL test",
            )
    elif cert_type == "GREEN_LABEL_PLUS":
        if (
            not cited
            or not _has_pass(cited, "STAIN_AATCC175")
            or not _has_pass(cited, "WEAR_TARR")
        ):
            raise ApiError(
                "ERR_CERT_EVIDENCE_MISSING",
                "GREEN_LABEL_PLUS requires a passing STAIN_AATCC175 and WEAR_TARR test",
            )

    # Rung 14 — recycled content, only for NSF_140.
    recorded_pct = None
    if cert_type == "NSF_140":
        pct = compliance.recycled_pct_for_basis(style_id, accounting_basis)
        if not compliance.nsf_140_eligible(pct):
            raise ApiError(
                "ERR_RECYCLED_CONTENT_INSUFFICIENT",
                "Recycled content of %.2f percent is below the NSF 140 minimum" % pct,
            )
        recorded_pct = pct

    cert = insert(
        store.certifications,
        {
            "style_id": style_id,
            "cert_type": cert_type,
            "accounting_basis": accounting_basis,
            "source_test_ids": list(source_test_ids),
            "recorded_recycled_content_pct": recorded_pct,
            "certified_by_user_id": actor.user_id,
            "issued_at_utc": store.clock_raw,
            "expires_at_utc": expires_raw,
            "_expires_dt": expires_dt,
            "status": "ACTIVE",
        },
    )

    # A style holds at most one live certificate per type.
    for other in compliance.certifications_of_style(style_id):
        if other["id"] == cert["id"]:
            continue
        if other["cert_type"] == cert_type and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)

    # Cascade: a suspended style regaining flammability cover reopens.
    if cert_type == "DOC_FF_1_70":
        compliance.reactivate_style_if_certified(style)

    return created("certification", cert)


@bp.post("/mill/certifications/<certification_id>/revoke")
def revoke_certification(certification_id):
    authenticate(CERT_WRITE_ROLES)
    body = json_body()
    from validators import opt_str

    opt_str(body, "reason")

    cert = fetch("certifications", certification_id)
    if cert["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE certificate may be revoked")

    cert["status"] = "REVOKED"
    touch(cert)

    style = store.styles.get(cert["style_id"])
    if style is not None:
        compliance.suspend_style_if_uncertified(style)
    return ok("certification", cert)


@bp.get("/mill/certifications/<certification_id>")
def read_certification(certification_id):
    authenticate(CERT_READ_ROLES)
    return ok("certification", fetch("certifications", certification_id))


@bp.get("/mill/certifications")
def list_certifications():
    authenticate(CERT_READ_ROLES)
    return listing(
        "certification",
        "certifications",
        enum_filters={"cert_type": CERT_TYPES, "status": CERT_STATUSES},
        value_filters=("style_id",),
    )
