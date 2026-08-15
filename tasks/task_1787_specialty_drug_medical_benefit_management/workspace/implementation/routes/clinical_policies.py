"""Clinical policy endpoints (PRD 3.2): versioned, create-with-supersede,
OCC-guarded on the governing drug's version."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_POLICY_NOT_DRAFT, ERR_STALE_DRUG_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, get_body, get_or_404, list_response, public, read_all,
    req_bool, req_enum, req_int, req_list_str, req_str, stamp_new,
)
from services.pricing import touch
from util import new_id

bp = Blueprint("clinical_policies", __name__)

BIOSIMILAR_STANCES = ("DISABLED", "PREFERRED", "MANDATORY")
POLICY_CREATE_STATUSES = ("DRAFT", "ACTIVE")


def _next_version_no(drug_id: str) -> int:
    existing = [p["version_no"] for p in db["clinical_policies"].values() if p["drug_id"] == drug_id]
    return (max(existing) + 1) if existing else 1


def _supersede_prior_active(drug_id: str, keep_id: str):
    for p in db["clinical_policies"].values():
        if p["drug_id"] == drug_id and p["id"] != keep_id and p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            touch(p)


def _check_occ(body, drug):
    expected = req_int(body, "expected_drug_version")
    # OCC is deliberately evaluated before any business rule (PRD 2.7/2.8)
    if expected != drug["version"]:
        raise_error(
            ERR_STALE_DRUG_VERSION,
            f"expected_drug_version {expected} != current drug version {drug['version']}",
        )


@bp.post("/api/clinical-policies")
def create_policy():
    authorized(["MedicalPolicyOfficer"])
    body = get_body()
    # ---- shape (stage 4) ----
    drug_id = req_str(body, "drug_id")
    status = req_enum(body, "status", POLICY_CREATE_STATUSES)
    covered_diagnoses = req_list_str(body, "covered_diagnoses", non_empty=True)
    step_therapy_required = req_bool(body, "step_therapy_required")
    requires_site_of_care_redirection = req_bool(body, "requires_site_of_care_redirection")
    biosimilar_substitution = req_enum(body, "biosimilar_substitution", BIOSIMILAR_STANCES)
    # ---- existence (stage 5) ----
    if drug_id not in db["drugs"]:
        raise_error(ERR_NOT_FOUND, f"drug {drug_id} does not exist")
    drug = db["drugs"][drug_id]
    # ---- OCC (stage 6) ----
    _check_occ(body, drug)
    rec = {
        "id": new_id(),
        "drug_id": drug_id,
        "covered_diagnoses": covered_diagnoses,
        "step_therapy_required": step_therapy_required,
        "requires_site_of_care_redirection": requires_site_of_care_redirection,
        "biosimilar_substitution": biosimilar_substitution,
        "version_no": _next_version_no(drug_id),
        "status": status,
    }
    stamp_new(rec)
    db["clinical_policies"][rec["id"]] = rec
    if status == "ACTIVE":
        _supersede_prior_active(drug_id, rec["id"])
    # every policy creation advances the drug's version by one
    touch(drug)
    return success_object(public(rec), 201)


@bp.get("/api/clinical-policies")
def list_policies():
    read_all()
    items = list(db["clinical_policies"].values())
    items = apply_filters(items, ["drug_id", "status"])
    return list_response(items)


@bp.get("/api/clinical-policies/<policyId>")
def get_policy(policyId):
    read_all()
    policy = get_or_404("clinical_policies", policyId)
    return success_object(public(policy))


@bp.post("/api/clinical-policies/<policyId>/activate")
def activate_policy(policyId):
    authorized(["MedicalPolicyOfficer"])
    body = get_body()
    policy = get_or_404("clinical_policies", policyId)
    drug = db["drugs"][policy["drug_id"]]
    # ---- OCC (stage 6, before the DRAFT business rule) ----
    _check_occ(body, drug)
    # ---- target state (stage 7) ----
    if policy["status"] != "DRAFT":
        raise_error(ERR_POLICY_NOT_DRAFT, "activate requires a DRAFT clinical policy")
    policy["status"] = "ACTIVE"
    touch(policy)
    _supersede_prior_active(policy["drug_id"], policy["id"])
    touch(drug)
    return success_object(public(policy))
