"""Prior authorization endpoints (PRD 3.4): submission, approval gates, and the
SUBMITTED/APPROVED/DENIED/SUSPENDED/EXPIRED/CANCELLED/EXHAUSTED lifecycle."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_AUTH_NOT_PENDING,
    ERR_AUTH_NOT_APPROVED, ERR_AUTH_NOT_SUSPENDED, ERR_AUTH_NOT_CANCELLABLE,
    ERR_NO_ACTIVE_POLICY, ERR_MISSING_WEIGHT_OR_DOSE, ERR_START_DATE_IN_PAST,
    ERR_DIAGNOSIS_NOT_COVERED, ERR_STEP_THERAPY_REQUIRED,
    ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED, ERR_DOSE_EXCEEDS_MAX,
    ERR_AUTH_WINDOW_OVERLAP, ERR_PROVIDER_SCOPE_VIOLATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, check_single_scope, get_body, get_or_404, is_num,
    list_response, opt_bool, public, read_all, req_date, req_int, req_str,
    stamp_new,
)
from services.pricing import dose_optimization, touch
from util import CLOCK, dec, new_id, pdate

bp = Blueprint("authorizations", __name__)

AUTH_VALIDITY_DAYS = 180
AUTH_READ_FILTER_FIELDS = ["drug_id", "member_id", "status", "provider_account_id", "policy_id"]


def _active_policy_for(drug_id: str):
    for p in db["clinical_policies"].values():
        if p["drug_id"] == drug_id and p["status"] == "ACTIVE":
            return p
    return None


def _mandatory_biosimilar_blocks(drug_id: str, start_date) -> bool:
    """True iff an ACTIVE biosimilar policy references this drug and its
    half-open window covers the requested start date."""
    for bp_ in db["biosimilar_policies"].values():
        if bp_["status"] != "ACTIVE" or bp_["reference_drug_id"] != drug_id:
            continue
        if pdate(bp_["effective_start"]) <= start_date < pdate(bp_["effective_end"]):
            return True
    return False


@bp.post("/api/prior-authorizations")
def create_auth():
    caller = authorized(["ProviderRep"])
    body = get_body()
    # ---- shape (stage 4) ----
    drug_id = req_str(body, "drug_id")
    member_id = req_str(body, "member_id")
    diagnosis_code = req_str(body, "diagnosis_code")
    requested_start_date = req_date(body, "requested_start_date")
    requested_dose_mg = body.get("requested_dose_mg")
    weight_kg = body.get("weight_kg")
    if requested_dose_mg is not None and not is_num(requested_dose_mg):
        raise_error(ERR_INVALID_REQUEST, "requested_dose_mg must be a number")
    if weight_kg is not None and not is_num(weight_kg):
        raise_error(ERR_INVALID_REQUEST, "weight_kg must be a number")
    step_therapy_completed = opt_bool(body, "step_therapy_completed", False)
    # ---- existence (stage 5) ----
    if drug_id not in db["drugs"]:
        raise_error(ERR_NOT_FOUND, f"drug {drug_id} does not exist")
    drug = db["drugs"][drug_id]
    # ---- clinical safety (stage 9): dosing input completeness + dose cap ----
    if drug["weight_based_dosing"]:
        if weight_kg is None:
            raise_error(ERR_MISSING_WEIGHT_OR_DOSE, "weight_kg is required for a weight-based drug")
    else:
        if requested_dose_mg is None:
            raise_error(ERR_MISSING_WEIGHT_OR_DOSE, "requested_dose_mg is required for a non-weight-based drug")
    if requested_dose_mg is not None and dec(requested_dose_mg) > dec(drug["max_single_dose_mg"]):
        # inclusive cap: exactly equal passes, one milligram above fails
        raise_error(ERR_DOSE_EXCEEDS_MAX, "requested_dose_mg exceeds max_single_dose_mg")
    # ---- temporal (stage 11) ----
    if requested_start_date < CLOCK.today():
        raise_error(ERR_START_DATE_IN_PAST, "requested_start_date is before the current date")
    rec = {
        "id": new_id(),
        "drug_id": drug_id,
        "member_id": member_id,
        "provider_account_id": caller.user_id,  # stamped from the creating ProviderRep
        "diagnosis_code": diagnosis_code,
        "requested_dose_mg": requested_dose_mg,
        "weight_kg": weight_kg,
        "requested_start_date": requested_start_date.isoformat(),
        "step_therapy_completed": step_therapy_completed,
        "status": "SUBMITTED",
        "approved_dose_mg": None,
        "validity_start": None,
        "validity_end": None,
        "max_administrations": None,
        "administrations_used": 0,
        "policy_id": None,
        "policy_version_no": None,
        "denial_reason": None,
    }
    stamp_new(rec)
    db["prior_authorizations"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/prior-authorizations")
def list_auths():
    caller = read_all()
    items = list(db["prior_authorizations"].values())
    if caller.role == "ProviderRep":
        pfilter = request.args.get("provider_account_id")
        if pfilter is not None and pfilter != caller.user_id:
            raise_error(ERR_PROVIDER_SCOPE_VIOLATION, "provider_account_id filter is foreign")
        # silently scoped to the caller's own account
        items = [a for a in items if a["provider_account_id"] == caller.user_id]
    items = apply_filters(items, AUTH_READ_FILTER_FIELDS)
    return list_response(items)


@bp.get("/api/prior-authorizations/<authId>")
def get_auth(authId):
    caller = read_all()
    auth = get_or_404("prior_authorizations", authId)
    check_single_scope(caller, auth["provider_account_id"])
    return success_object(public(auth))


@bp.post("/api/prior-authorizations/<authId>/approve")
def approve_auth(authId):
    authorized(["MedicalPolicyOfficer"])
    body = get_body()
    # ---- shape (stage 4) ----
    max_administrations = req_int(body, "max_administrations", min_v=1)
    # ---- existence (stage 5) ----
    auth = get_or_404("prior_authorizations", authId)
    # ---- target state (stage 7) ----
    if auth["status"] != "SUBMITTED":
        raise_error(ERR_AUTH_NOT_PENDING, "approve requires a SUBMITTED authorization")
    # ---- approval gates in their fixed order (PRD 3.4) ----
    drug = db["drugs"][auth["drug_id"]]
    policy = _active_policy_for(auth["drug_id"])
    if policy is None:
        raise_error(ERR_NO_ACTIVE_POLICY, "no ACTIVE clinical policy for the drug")
    if auth["diagnosis_code"] not in policy["covered_diagnoses"]:
        raise_error(ERR_DIAGNOSIS_NOT_COVERED, "diagnosis_code is not covered by the ACTIVE policy")
    if policy["step_therapy_required"] and not auth["step_therapy_completed"]:
        raise_error(ERR_STEP_THERAPY_REQUIRED, "policy requires step therapy")
    requested_start = pdate(auth["requested_start_date"])
    if policy["biosimilar_substitution"] == "MANDATORY" and _mandatory_biosimilar_blocks(
        auth["drug_id"], requested_start
    ):
        raise_error(
            ERR_BIOSIMILAR_SUBSTITUTION_REQUIRED,
            "MANDATORY substitution: an ACTIVE biosimilar policy covers the requested start date",
        )
    approved_dose = dose_optimization(drug, auth)
    if approved_dose > drug["max_single_dose_mg"]:
        raise_error(ERR_DOSE_EXCEEDS_MAX, "computed dose exceeds max_single_dose_mg")
    validity_start = requested_start
    validity_end = requested_start + timedelta(days=AUTH_VALIDITY_DAYS)
    for other in db["prior_authorizations"].values():
        if (
            other["id"] != auth["id"]
            and other["member_id"] == auth["member_id"]
            and other["drug_id"] == auth["drug_id"]
            and other["status"] in ("APPROVED", "SUSPENDED")
            and validity_start <= pdate(other["validity_end"])
            and pdate(other["validity_start"]) <= validity_end
        ):
            # closed-interval overlap: touching dates DO overlap
            raise_error(ERR_AUTH_WINDOW_OVERLAP, "overlapping APPROVED/SUSPENDED authorization exists")
    # ---- commit ----
    auth["status"] = "APPROVED"
    auth["approved_dose_mg"] = approved_dose
    auth["validity_start"] = validity_start.isoformat()
    auth["validity_end"] = validity_end.isoformat()
    auth["max_administrations"] = max_administrations
    auth["administrations_used"] = 0
    auth["policy_id"] = policy["id"]
    auth["policy_version_no"] = policy["version_no"]
    touch(auth)
    if policy["requires_site_of_care_redirection"] and drug["site_of_care_eligible"]:
        red = {
            "id": new_id(),
            "auth_id": auth["id"],
            "from_site": "HOPD",
            "candidate_sites": ["OFFICE", "HOME", "AMBULATORY"],
            "accepted_site": None,
            "member_incentive_cents": 0,
            "status": "OFFERED",
        }
        stamp_new(red)
        db["redirections"][red["id"]] = red
    return success_object(public(auth))


@bp.post("/api/prior-authorizations/<authId>/deny")
def deny_auth(authId):
    authorized(["MedicalPolicyOfficer"])
    body = get_body()
    reason = req_str(body, "reason")
    auth = get_or_404("prior_authorizations", authId)
    if auth["status"] != "SUBMITTED":
        raise_error(ERR_AUTH_NOT_PENDING, "deny requires a SUBMITTED authorization")
    auth["status"] = "DENIED"
    auth["denial_reason"] = reason
    touch(auth)
    return success_object(public(auth))


@bp.post("/api/prior-authorizations/<authId>/suspend")
def suspend_auth(authId):
    authorized(["MedicalPolicyOfficer"])
    get_body()
    auth = get_or_404("prior_authorizations", authId)
    if auth["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED, "suspend requires an APPROVED authorization")
    auth["status"] = "SUSPENDED"
    touch(auth)
    # cascade: unpaid approved claims of this auth are pended (AUTH_SUSPENDED)
    for c in db["claims"].values():
        if c["auth_id"] == auth["id"] and c["status"] == "APPROVED_FOR_PAYMENT":
            c["status"] = "PENDED"
            c["pend_reason"] = "AUTH_SUSPENDED"
            touch(c)
    return success_object(public(auth))


@bp.post("/api/prior-authorizations/<authId>/reinstate")
def reinstate_auth(authId):
    authorized(["MedicalPolicyOfficer"])
    get_body()
    auth = get_or_404("prior_authorizations", authId)
    if auth["status"] != "SUSPENDED":
        raise_error(ERR_AUTH_NOT_SUSPENDED, "reinstate requires a SUSPENDED authorization")
    auth["status"] = "APPROVED"
    touch(auth)
    # cascade: exactly the AUTH_SUSPENDED-pended claims return; DOSE_REVIEW stays
    for c in db["claims"].values():
        if (
            c["auth_id"] == auth["id"]
            and c["status"] == "PENDED"
            and c["pend_reason"] == "AUTH_SUSPENDED"
        ):
            c["status"] = "APPROVED_FOR_PAYMENT"
            c["pend_reason"] = None
            touch(c)
    return success_object(public(auth))


@bp.post("/api/prior-authorizations/<authId>/cancel")
def cancel_auth(authId):
    authorized(["MedicalPolicyOfficer"])
    get_body()
    auth = get_or_404("prior_authorizations", authId)
    if auth["status"] not in ("SUBMITTED", "APPROVED", "SUSPENDED"):
        raise_error(ERR_AUTH_NOT_CANCELLABLE, "cancel requires a non-terminal authorization")
    auth["status"] = "CANCELLED"
    touch(auth)
    # side effect: an OFFERED redirection for this auth is withdrawn
    for r in db["redirections"].values():
        if r["auth_id"] == auth["id"] and r["status"] == "OFFERED":
            r["status"] = "EXPIRED"
            touch(r)
    return success_object(public(auth))
