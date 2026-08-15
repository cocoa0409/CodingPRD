"""Medical certificates and the drug-test program (PRD 3.5)."""

from flask import Blueprint, g, request

from db import store
from errors import err
from helpers import (
    get_body,
    opt_list,
    paginate,
    req_dt,
    req_enum,
    require_roles,
    scope_mariner_id,
    sorted_items,
)
from response import success
from serialize import ser_drug_test, ser_medical_certificate
from services import recompute_mariner_with_cascade

bp = Blueprint("medical", __name__)

CERT_TYPES = ("USCG_MEDICAL", "FLAG_STATE_MEDICAL", "FIT_FOR_DUTY")
TEST_TYPES = (
    "PRE_EMPLOYMENT",
    "PERIODIC",
    "RANDOM",
    "REASONABLE_CAUSE",
    "RETURN_TO_DUTY",
)
TEST_RESULTS = ("NEGATIVE", "POSITIVE", "REFUSAL")

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def _get_mariner(mariner_id):
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    return m


def _get_cert_under_mariner(mariner_id, cert_id):
    c = store.medical_certificates.get(cert_id)
    if c is None or c["mariner_id"] != mariner_id:
        raise err(
            "ERR_MEDICAL_CERTIFICATE_NOT_FOUND",
            "Medical certificate %s not found" % cert_id,
        )
    return c


def _get_test_under_mariner(mariner_id, test_id):
    t = store.drug_tests.get(test_id)
    if t is None or t["mariner_id"] != mariner_id:
        raise err("ERR_DRUG_TEST_NOT_FOUND", "Drug test %s not found" % test_id)
    return t


# ---------------------------------------------------------------------------
# Medical certificates
# ---------------------------------------------------------------------------


@bp.route("/mariners/<mariner_id>/medical-certificates", methods=["POST"])
@require_roles("CredentialingOfficer")
def create_certificate(mariner_id):
    m = _get_mariner(mariner_id)
    body = get_body()
    cert_type = req_enum(body, "cert_type", CERT_TYPES)
    issue_date = req_dt(body, "issue_date")
    expiry_date = req_dt(body, "expiry_date")
    limitations = opt_list(body, "limitations", default=[])
    c = {
        "mariner_id": m["id"],
        "cert_type": cert_type,
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "limitations": list(limitations),
        "status": "VALID",
    }
    store.stamp(c)
    store.medical_certificates[c["id"]] = c
    recompute_mariner_with_cascade(m)
    return success(ser_medical_certificate(c), code=201)


@bp.route("/mariners/<mariner_id>/medical-certificates", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_certificates(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [
        c for c in store.medical_certificates.values() if c["mariner_id"] == m["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_medical_certificate(c) for c in page],
        response_type="array",
        pagination=meta,
    )


@bp.route(
    "/mariners/<mariner_id>/medical-certificates/<cert_id>/suspend", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def suspend_certificate(mariner_id, cert_id):
    m = _get_mariner(mariner_id)
    c = _get_cert_under_mariner(mariner_id, cert_id)
    if c["status"] != "VALID":
        raise err(
            "ERR_MEDICAL_CERT_NOT_VALID",
            "Only a VALID certificate can be suspended",
        )
    c["status"] = "SUSPENDED"
    store.bump(c)
    recompute_mariner_with_cascade(m)
    return success(ser_medical_certificate(c))


@bp.route(
    "/mariners/<mariner_id>/medical-certificates/<cert_id>/reinstate", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def reinstate_certificate(mariner_id, cert_id):
    m = _get_mariner(mariner_id)
    c = _get_cert_under_mariner(mariner_id, cert_id)
    if c["status"] != "SUSPENDED":
        raise err(
            "ERR_MEDICAL_CERT_NOT_VALID",
            "Only a SUSPENDED certificate can be reinstated",
        )
    c["status"] = "VALID"
    store.bump(c)
    recompute_mariner_with_cascade(m)
    return success(ser_medical_certificate(c))


# ---------------------------------------------------------------------------
# Drug tests
# ---------------------------------------------------------------------------


@bp.route("/mariners/<mariner_id>/drug-tests", methods=["POST"])
@require_roles("CredentialingOfficer")
def create_drug_test(mariner_id):
    m = _get_mariner(mariner_id)
    body = get_body()
    test_type = req_enum(body, "test_type", TEST_TYPES)
    scheduled = req_dt(body, "scheduled_date")
    t = {
        "mariner_id": m["id"],
        "test_type": test_type,
        "scheduled_date": scheduled,
        "collected_date": None,
        "result": None,
        "status": "PENDING",
        "recorded_by_user_id": None,
    }
    store.stamp(t)
    store.drug_tests[t["id"]] = t
    return success(ser_drug_test(t), code=201)


@bp.route("/mariners/<mariner_id>/drug-tests", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_drug_tests(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [t for t in store.drug_tests.values() if t["mariner_id"] == m["id"]]
    status = request.args.get("status")
    result = request.args.get("result")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if result is not None:
        items = [t for t in items if t["result"] == result]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_drug_test(t) for t in page], response_type="array", pagination=meta
    )


@bp.route(
    "/mariners/<mariner_id>/drug-tests/<test_id>/record-result", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def record_result(mariner_id, test_id):
    m = _get_mariner(mariner_id)
    t = _get_test_under_mariner(mariner_id, test_id)
    body = get_body()
    # Schema (pipeline step 6) precedes the state check (step 9).
    result = req_enum(body, "result", TEST_RESULTS)
    collected = req_dt(body, "collected_date")
    if t["status"] != "PENDING":
        raise err(
            "ERR_DRUG_TEST_NOT_PENDING", "Only a PENDING test can record a result"
        )
    t["status"] = "COMPLETED"
    t["result"] = result
    t["collected_date"] = collected
    t["recorded_by_user_id"] = g.user_id
    store.bump(t)
    recompute_mariner_with_cascade(m)
    return success(ser_drug_test(t))
