"""Infusion claim endpoints (PRD 3.6): synchronous adjudication with the
dose-tolerance fork, medical override, denial, and payment with ledger sync."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_AUTH_NOT_APPROVED, ERR_DRUG_AUTH_MISMATCH,
    ERR_JCODE_MISMATCH, ERR_SERVICE_DATE_OUT_OF_WINDOW, ERR_FUTURE_SERVICE_DATE,
    ERR_SOURCING_VIOLATION, ERR_SITE_OF_CARE_VIOLATION, ERR_JW_MODIFIER_REQUIRED,
    ERR_JW_WITHOUT_WASTE, ERR_WASTE_NOT_PAYABLE_MULTIDOSE, ERR_WASTE_EXCEEDS_VIAL,
    ERR_NO_ASP_RATE, ERR_DOSE_EXCEEDS_APPROVED, ERR_CLAIM_NOT_PENDED,
    ERR_CLAIM_NOT_PAYABLE, ERR_PROVIDER_RECOUPMENT_HOLD,
    ERR_PROVIDER_SCOPE_VIOLATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, check_single_scope, get_body, get_or_404, list_response,
    opt_bool, opt_int, public, read_all, req_date, req_enum, req_int, req_str,
    stamp_new,
)
from services.pricing import asp_schedule_for, find_accepted_redirection, price_claim, touch
from util import CLOCK, new_id, pdate

bp = Blueprint("claims", __name__)

SITE_VALUES = ("HOPD", "OFFICE", "HOME", "AMBULATORY")
SOURCING_PATHS = ("BUY_AND_BILL", "WHITE_BAG")
CLAIM_FILTER_FIELDS = ["auth_id", "drug_id", "provider_account_id", "status", "asp_schedule_id_used"]


def _debit_administration(auth: dict):
    """CASCADE hop 1->2 then 2->3: increment and auto-exhaust at the cap."""
    auth["administrations_used"] += 1
    if auth["administrations_used"] >= auth["max_administrations"]:
        auth["status"] = "EXHAUSTED"
    touch(auth)


@bp.post("/api/claims")
def create_claim():
    caller = authorized(["ProviderRep"])
    body = get_body()
    # ---- shape (stage 4) ----
    auth_id = req_str(body, "auth_id")
    drug_id = req_str(body, "drug_id")
    service_date = req_date(body, "service_date")
    site_of_care = req_enum(body, "site_of_care", SITE_VALUES)
    sourcing_path = req_enum(body, "sourcing_path", SOURCING_PATHS)
    j_code_billed = req_str(body, "j_code_billed")
    billed_units = req_int(body, "billed_units", min_v=1)
    waste_units = opt_int(body, "waste_units", 0, min_v=0)
    jw_modifier = opt_bool(body, "jw_modifier", False)
    # ---- existence (stage 5): body FKs in declared order ----
    auth = db["prior_authorizations"].get(auth_id)
    if auth is None:
        raise_error(ERR_NOT_FOUND, f"prior authorization {auth_id} does not exist")
    drug = db["drugs"].get(drug_id)
    if drug is None:
        raise_error(ERR_NOT_FOUND, f"drug {drug_id} does not exist")
    # ---- cross-entity state (stage 8) ----
    if auth["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED, "claim requires an APPROVED authorization")
    # ---- clinical safety: JW / waste rules (stage 9) ----
    if waste_units > 0 and not jw_modifier:
        raise_error(ERR_JW_MODIFIER_REQUIRED, "waste_units > 0 requires jw_modifier = true")
    if jw_modifier and waste_units == 0:
        raise_error(ERR_JW_WITHOUT_WASTE, "jw_modifier = true with waste_units = 0")
    if waste_units > 0 and not drug["single_dose_vial"]:
        raise_error(ERR_WASTE_NOT_PAYABLE_MULTIDOSE, "waste is not payable on a multi-dose vial")
    if waste_units >= drug["vial_size_mg"] // drug["billing_unit_mg"]:
        # a whole vial or more can never be waste (strictly-less boundary)
        raise_error(ERR_WASTE_EXCEEDS_VIAL, "waste_units must be < vial_size_mg / billing_unit_mg")
    # ---- referential coherence (stage 10) ----
    if drug_id != auth["drug_id"]:
        raise_error(ERR_DRUG_AUTH_MISMATCH, "claim drug_id does not match the authorization's drug")
    if j_code_billed != drug["j_code"]:
        raise_error(ERR_JCODE_MISMATCH, "j_code_billed does not match the drug's catalog j_code")
    # ---- temporal (stage 11) ----
    if service_date > CLOCK.today():
        raise_error(ERR_FUTURE_SERVICE_DATE, "service_date is after the current date")
    if not (pdate(auth["validity_start"]) <= service_date <= pdate(auth["validity_end"])):
        raise_error(ERR_SERVICE_DATE_OUT_OF_WINDOW, "service_date is outside the authorization window")
    # ---- sourcing decision and site program (stage 12) ----
    if drug["sourcing_rule"] == "BUY_AND_BILL_ONLY" and sourcing_path != "BUY_AND_BILL":
        raise_error(ERR_SOURCING_VIOLATION, "drug is BUY_AND_BILL_ONLY")
    if drug["sourcing_rule"] == "SPECIALTY_PHARMACY_ONLY" and sourcing_path == "BUY_AND_BILL":
        raise_error(ERR_SOURCING_VIOLATION, "drug is SPECIALTY_PHARMACY_ONLY")
    red = find_accepted_redirection(auth["id"])
    if red is not None and site_of_care != red["accepted_site"]:
        raise_error(ERR_SITE_OF_CARE_VIOLATION, "site_of_care must equal the accepted redirection site")
    # ---- fiscal gates (stage 13): rate existence, then dose tolerance ----
    sched = asp_schedule_for(drug["id"], service_date)
    if sched is None:
        raise_error(ERR_NO_ASP_RATE, "no ASP rate effective on the service date")
    administered_mg = billed_units * drug["billing_unit_mg"]  # excludes waste
    approved_dose = auth["approved_dose_mg"]
    if administered_mg * 10 > approved_dose * 11:
        # beyond the inclusive 110% tolerance: rejected outright (equality still pends)
        raise_error(ERR_DOSE_EXCEEDS_APPROVED, "administered dose exceeds the 110% tolerance")
    # ---- pricing (per-component pinned rounding) ----
    claim_like = {
        "auth_id": auth["id"],
        "drug_id": drug["id"],
        "site_of_care": site_of_care,
        "billed_units": billed_units,
        "waste_units": waste_units,
        "jw_modifier": jw_modifier,
    }
    res = price_claim(drug, claim_like, sched["asp_rate_cents"], service_date)
    pended = administered_mg > approved_dose
    rec = {
        "id": new_id(),
        "auth_id": auth["id"],
        "drug_id": drug["id"],
        "provider_account_id": caller.user_id,  # stamped from the creating ProviderRep
        "service_date": service_date.isoformat(),
        "site_of_care": site_of_care,
        "sourcing_path": sourcing_path,
        "j_code_billed": j_code_billed,
        "billed_units": billed_units,
        "waste_units": waste_units,
        "jw_modifier": jw_modifier,
        # SUBMITTED is transient: adjudication lands directly in one of these
        "status": "PENDED" if pended else "APPROVED_FOR_PAYMENT",
        "pend_reason": "DOSE_REVIEW" if pended else None,
        "administered_mg": administered_mg,
        "payable_waste_units": res["payable_waste"],
        "asp_schedule_id_used": sched["id"],
        "asp_rate_cents": sched["asp_rate_cents"],
        "addon_pct_applied": float(res["addon"]),
        "allowed_amount_cents": res["allowed"],
        "member_cost_share_cents": res["mcs"],
        "override_by": None,
        "denial_reason": None,
        "paid_at": None,
    }
    stamp_new(rec)
    db["claims"][rec["id"]] = rec
    if not pended:
        _debit_administration(auth)
    return success_object(public(rec), 201)


@bp.get("/api/claims")
def list_claims():
    caller = read_all()
    items = list(db["claims"].values())
    if caller.role == "ProviderRep":
        pfilter = request.args.get("provider_account_id")
        if pfilter is not None and pfilter != caller.user_id:
            raise_error(ERR_PROVIDER_SCOPE_VIOLATION, "provider_account_id filter is foreign")
        afilter = request.args.get("auth_id")
        if afilter is not None:
            a = db["prior_authorizations"].get(afilter)
            if a is not None and a["provider_account_id"] != caller.user_id:
                raise_error(ERR_PROVIDER_SCOPE_VIOLATION, "auth_id filter is foreign")
        # silently scoped to the caller's own account
        items = [c for c in items if c["provider_account_id"] == caller.user_id]
    items = apply_filters(items, CLAIM_FILTER_FIELDS)
    return list_response(items)


@bp.get("/api/claims/<claimId>")
def get_claim(claimId):
    caller = read_all()
    claim = get_or_404("claims", claimId)
    check_single_scope(caller, claim["provider_account_id"])
    return success_object(public(claim))


@bp.post("/api/claims/<claimId>/override-approve")
def override_approve(claimId):
    caller = authorized(["MedicalPolicyOfficer"])
    get_body()
    claim = get_or_404("claims", claimId)
    # ---- target state (stage 7) ----
    if claim["status"] != "PENDED":
        raise_error(ERR_CLAIM_NOT_PENDED, "override-approve requires a PENDED claim")
    # ---- cross-entity state (stage 8) ----
    auth = db["prior_authorizations"][claim["auth_id"]]
    if auth["status"] != "APPROVED":
        # an APPROVED auth always has administration headroom (cap auto-exhausts)
        raise_error(ERR_AUTH_NOT_APPROVED, "override-approve requires an APPROVED authorization")
    # price is fixed at adjudication: override deliberately does not re-price
    claim["status"] = "APPROVED_FOR_PAYMENT"
    claim["pend_reason"] = None
    claim["override_by"] = caller.user_id  # divergent branch marker
    touch(claim)
    _debit_administration(auth)
    return success_object(public(claim))


@bp.post("/api/claims/<claimId>/deny")
def deny_claim(claimId):
    authorized(["MedicalPolicyOfficer"])
    body = get_body()
    reason = req_str(body, "reason")
    claim = get_or_404("claims", claimId)
    if claim["status"] != "PENDED":
        raise_error(ERR_CLAIM_NOT_PENDED, "deny requires a PENDED claim")
    claim["status"] = "DENIED"
    claim["pend_reason"] = None
    claim["denial_reason"] = reason
    touch(claim)
    return success_object(public(claim))


@bp.post("/api/claims/<claimId>/pay")
def pay_claim(claimId):
    authorized(["PlanAdmin"])
    get_body()
    claim = get_or_404("claims", claimId)
    # ---- target state (stage 7) ----
    if claim["status"] != "APPROVED_FOR_PAYMENT":
        raise_error(ERR_CLAIM_NOT_PAYABLE, "pay requires an APPROVED_FOR_PAYMENT claim")
    # ---- cross-entity state (stage 8) ----
    prov = db["provider_accounts"].get(claim["provider_account_id"])
    if prov is None:
        raise_error(ERR_NOT_FOUND, "provider account does not exist")
    if prov["status"] != "ACTIVE":
        raise_error(ERR_PROVIDER_RECOUPMENT_HOLD, "provider is on RECOUPMENT_HOLD")
    claim["status"] = "PAID"
    claim["paid_at"] = CLOCK.ts()
    touch(claim)
    # LEDGER SYNC: credit the provider (atomic with the payment)
    prov["cumulative_paid_cents"] += claim["allowed_amount_cents"]
    touch(prov)
    return success_object(public(claim))
