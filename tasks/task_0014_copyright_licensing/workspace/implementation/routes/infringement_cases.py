"""InfringementCase routes."""
from flask import Blueprint

from clock import format_iso, get_now
from common import check_version, get_json_body, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import append_audit, append_rights_chain
from services.works import is_owner_or_co_owner

bp = Blueprint("infringement_cases", __name__)


@bp.route("/infringement-cases", methods=["POST"])
def create_case():
    user_id, role = require_roles(["RightsHolder"])
    body = get_json_body()

    work_id = body.get("work_id")
    alleged_infringer_id = body.get("alleged_infringer_id")
    evidence_doc_ids = body.get("evidence_doc_ids")

    if not work_id:
        raise api_error("ERR_VALIDATION", "work_id required")
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    if not alleged_infringer_id or alleged_infringer_id not in db.rights_holders:
        raise api_error("ERR_NOT_FOUND", "alleged_infringer not found")

    # Caller must be primary or co-owner of the work.
    if not is_owner_or_co_owner(work, user_id):
        raise api_error("ERR_FORBIDDEN",
                        "reporter must be primary_owner or co_owner of the work")

    if work.get("registration_status") != "REGISTERED":
        raise api_error("ERR_WORK_NOT_REGISTERED",
                        "Work must be REGISTERED to file an infringement case")

    if not isinstance(evidence_doc_ids, list) or len(evidence_doc_ids) == 0:
        raise api_error("ERR_EVIDENCE_MISSING", "evidence_doc_ids must be non-empty array")

    case = {
        "work_id": work_id,
        "reporter_id": user_id,
        "alleged_infringer_id": alleged_infringer_id,
        "evidence_doc_ids": list(evidence_doc_ids),
        "response_text": None,
        "review_stage": "REPORTED",
        "takedown_issued_at": None,
        "compensation_cents": None,
        "pinned_certificate_id": None,
    }
    stamp_new(case)
    db.infringement_cases[case["id"]] = case

    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 None, {"review_stage": "REPORTED"})

    return success(case, status=201)


@bp.route("/infringement-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    return success(case)


@bp.route("/infringement-cases/<case_id>/verify-ownership", methods=["POST"])
def verify_ownership(case_id):
    user_id, role = require_roles(["PlatformAdmin"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    body = get_json_body()
    check_version(case, body)

    if case.get("review_stage") != "REPORTED":
        raise api_error("ERR_INVALID_STATE",
                        "case must be REPORTED to verify ownership")

    work = db.works.get(case.get("work_id"))
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    if work.get("registration_status") != "REGISTERED":
        raise api_error("ERR_WORK_NOT_REGISTERED",
                        "Work must be REGISTERED")
    if not case.get("evidence_doc_ids"):
        raise api_error("ERR_EVIDENCE_MISSING", "evidence_doc_ids missing")

    before = {"review_stage": case["review_stage"], "pinned_certificate_id": case.get("pinned_certificate_id")}
    case["review_stage"] = "OWNERSHIP_VERIFIED"
    case["pinned_certificate_id"] = work.get("certificate_id")
    stamp_update(case)
    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 before,
                 {"review_stage": "OWNERSHIP_VERIFIED",
                  "pinned_certificate_id": case["pinned_certificate_id"]})

    return success(case)


@bp.route("/infringement-cases/<case_id>/respond", methods=["POST"])
def respond(case_id):
    user_id, role = require_roles(["RightsHolder"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    body = get_json_body()
    check_version(case, body)

    if case.get("review_stage") != "OWNERSHIP_VERIFIED":
        raise api_error("ERR_INVALID_STATE",
                        "case must be OWNERSHIP_VERIFIED to respond")

    if user_id != case.get("alleged_infringer_id"):
        raise api_error("ERR_FORBIDDEN", "only alleged_infringer may respond")

    work = db.works.get(case.get("work_id"))
    if not work or work.get("certificate_id") != case.get("pinned_certificate_id"):
        raise api_error("ERR_PINNED_CERTIFICATE_STALE",
                        "Work.certificate_id drifted from pinned_certificate_id")

    response_text = body.get("response_text")
    if response_text is None:
        raise api_error("ERR_VALIDATION", "response_text required")

    before = {"review_stage": case["review_stage"], "response_text": case.get("response_text")}
    case["review_stage"] = "RESPONSE_RECEIVED"
    case["response_text"] = response_text
    stamp_update(case)
    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 before,
                 {"review_stage": "RESPONSE_RECEIVED", "response_text": response_text})
    return success(case)


@bp.route("/infringement-cases/<case_id>/escalate", methods=["POST"])
def escalate(case_id):
    user_id, role = require_roles(["RightsHolder"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    body = get_json_body()
    check_version(case, body)

    if case.get("review_stage") != "RESPONSE_RECEIVED":
        raise api_error("ERR_INVALID_STATE",
                        "case must be RESPONSE_RECEIVED to escalate")

    if user_id != case.get("reporter_id"):
        raise api_error("ERR_FORBIDDEN", "only reporter may escalate")

    before = {"review_stage": case["review_stage"]}
    case["review_stage"] = "UNDER_ARBITRATION"
    case["takedown_issued_at"] = format_iso(get_now())
    stamp_update(case)

    # Takedown cascade: terminate matching EFFECTIVE licenses and their EFFECTIVE contracts.
    work_id = case.get("work_id")
    alleged_id = case.get("alleged_infringer_id")
    for lic in list(db.licenses.values()):
        if (lic.get("status") == "EFFECTIVE"
                and lic.get("work_id") == work_id
                and lic.get("licensee_id") == alleged_id):
            lic_before = {"status": lic["status"]}
            lic["status"] = "TERMINATED"
            stamp_update(lic)
            append_audit("system", "License", lic["id"], "LICENSE_CHANGED",
                         lic_before, {"status": "TERMINATED"})
            append_rights_chain(work_id, "LICENSE_TERMINATED", "system",
                                "License", lic["id"],
                                {"reason": "TAKEDOWN", "case_id": case["id"]})
            # Cascade contracts for this license.
            for c in list(db.contracts.values()):
                if c.get("license_id") == lic["id"] and c.get("status") == "EFFECTIVE":
                    cbefore = {"status": c["status"]}
                    c["status"] = "TERMINATED"
                    stamp_update(c)
                    append_audit("system", "Contract", c["id"], "CONTRACT_AMENDED",
                                 cbefore, {"status": "TERMINATED"})

    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 before,
                 {"review_stage": "UNDER_ARBITRATION",
                  "takedown_issued_at": case["takedown_issued_at"]})
    return success(case)


@bp.route("/infringement-cases/<case_id>/resolve", methods=["POST"])
def resolve(case_id):
    user_id, role = require_roles(["RightsHolder"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    body = get_json_body()
    check_version(case, body)

    if case.get("review_stage") != "UNDER_ARBITRATION":
        raise api_error("ERR_INVALID_STATE",
                        "case must be UNDER_ARBITRATION to resolve")
    if user_id != case.get("reporter_id"):
        raise api_error("ERR_FORBIDDEN", "only reporter may resolve")

    compensation = body.get("compensation_cents")
    if compensation is None or not isinstance(compensation, int) or compensation < 0:
        raise api_error("ERR_COMPENSATION_INVALID",
                        "compensation_cents must be non-negative integer")

    before = {"review_stage": case["review_stage"]}
    case["review_stage"] = "RESOLVED"
    case["compensation_cents"] = int(compensation)
    stamp_update(case)
    append_rights_chain(case.get("work_id"), "INFRINGEMENT_RESOLVED", user_id,
                        "InfringementCase", case["id"],
                        {"compensation_cents": int(compensation)})
    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 before,
                 {"review_stage": "RESOLVED", "compensation_cents": int(compensation)})
    return success(case)


@bp.route("/infringement-cases/<case_id>/dismiss", methods=["POST"])
def dismiss(case_id):
    user_id, role = require_roles(["RightsHolder"])
    case = db.infringement_cases.get(case_id)
    if not case:
        raise api_error("ERR_NOT_FOUND", "case not found")
    body = get_json_body()
    check_version(case, body)

    if case.get("review_stage") not in ("REPORTED", "UNDER_ARBITRATION"):
        raise api_error("ERR_INVALID_STATE",
                        "case may only be dismissed from REPORTED or UNDER_ARBITRATION")
    if user_id != case.get("reporter_id"):
        raise api_error("ERR_FORBIDDEN", "only reporter may dismiss")

    before = {"review_stage": case["review_stage"]}
    case["review_stage"] = "DISMISSED"
    stamp_update(case)
    append_audit(user_id, "InfringementCase", case["id"], "DISPUTE_LOGGED",
                 before, {"review_stage": "DISMISSED"})
    return success(case)
