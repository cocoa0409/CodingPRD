"""RegistrationRequest endpoints: CRUD, submit/approve/return-deficient/deny/withdraw, estimate."""
from flask import Blueprint, request

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_invalid_state, err_stale_version, err_sod, err_regulatory_gate,
    err_invalid_request,
)
from timeutil import now, today
from services import (
    CATEGORY_EXAMS, MAX_DEFICIENCIES, fee_components, cascade_request_withdrawn,
    fingerprint_required,
)

bp = Blueprint("registration_requests", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
CATEGORIES = {"RR", "IA", "PRINCIPAL"}


def req_out(r):
    return serialize(r)


def _yes_disclosures(req_id):
    return [
        d for d in store.background_disclosures.values()
        if d["registration_request_id"] == req_id and d["answer"] is True
    ]


def _check_explanations(req_id):
    for d in _yes_disclosures(req_id):
        text = d.get("explanation_text")
        if not isinstance(text, str) or len(text) < 20:
            raise err_invalid_request(
                "every disclosure with answer true requires explanation_text of at least 20 characters"
            )


@bp.post("/registration-desk/registration-requests")
def create_request():
    auth("RegistrationPrincipal")
    data = body()
    # Priority 3: body FK existence, input order (applicant_id, firm_id).
    applicant = fk_or_404(store.applicants, data.get("applicant_id"))
    firm = fk_or_404(store.firms, data.get("firm_id"))
    # Priority 9: field shape.
    required(data, "applicant_id")
    required(data, "firm_id")
    category = require_enum(required(data, "registration_category"), CATEGORIES, "registration_category")
    r = new_entity()
    r.update({
        "applicant_id": applicant["id"],
        "firm_id": firm["id"],
        "registration_category": category,
        "status": "DRAFT",
        "deficiency_count": 0,
        "submitted_at": None,
        "approved_at": None,
        "submitter_user_id": None,
    })
    store.registration_requests[r["id"]] = r
    return success_obj(req_out(r), 201)


@bp.get("/registration-desk/registration-requests/<id>")
def get_request(id):
    auth(*READ_ROLES)
    r = get_or_404(store.registration_requests, id)
    return success_obj(req_out(r), 200)


@bp.get("/registration-desk/registration-requests")
def list_requests():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.registration_requests,
        (
            ("applicant_id", "applicant_id", str),
            ("firm_id", "firm_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([req_out(r) for r in page], limit, offset, total)


@bp.patch("/registration-desk/registration-requests/<id>")
def patch_request(id):
    auth("RegistrationPrincipal")
    r = get_or_404(store.registration_requests, id)
    data = body()
    # Priority 5: editable only while DRAFT or DEFICIENT.
    if r["status"] not in ("DRAFT", "DEFICIENT"):
        raise err_invalid_state("registration request is editable only while DRAFT or DEFICIENT")
    # Priority 6: OCC on expected_registration_request_version.
    expected = data.get("expected_registration_request_version")
    if expected is None:
        raise err_invalid_request("expected_registration_request_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected != r["version"]:
        raise err_stale_version()
    # Priority 9: field shape of the editable field.
    if "registration_category" in data and data["registration_category"] is not None:
        category = require_enum(data["registration_category"], CATEGORIES, "registration_category")
        r["registration_category"] = category
    touch(r)
    return success_obj(req_out(r), 200)


@bp.post("/registration-desk/registration-requests/<id>/submit")
def submit_request(id):
    uid, _ = auth("RegistrationPrincipal")
    r = get_or_404(store.registration_requests, id)
    if r["status"] not in ("DRAFT", "DEFICIENT"):
        raise err_invalid_state("only a DRAFT or DEFICIENT request may be submitted")
    if r["status"] == "DRAFT":
        has_selected = any(
            s["registration_request_id"] == r["id"] and s["status"] == "SELECTED"
            for s in store.jurisdiction_selections.values()
        )
        if not has_selected:
            raise err_invalid_state(
                "at least one jurisdiction selection with status SELECTED is required to submit"
            )
    _check_explanations(r["id"])
    first_submit = r["status"] == "DRAFT"
    r["submitted_at"] = now()
    r["submitter_user_id"] = uid
    r["status"] = "SUBMITTED"
    if first_submit:
        for code in CATEGORY_EXAMS[r["registration_category"]]:
            er = new_entity()
            er.update({
                "registration_request_id": r["id"],
                "exam_code": code,
                "status": "REQUIRED",
                "pass_recorded_at": None,
                "credit_expiry_at": None,
            })
            store.exam_requirements[er["id"]] = er
    touch(r)
    return success_obj(req_out(r), 200)


@bp.post("/registration-desk/registration-requests/<id>/approve")
def approve_request(id):
    uid, _ = auth("ComplianceOfficer")
    r = get_or_404(store.registration_requests, id)
    # Priority 5: state legality.
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("only a SUBMITTED request may be approved")
    # Priority 7: segregation of duties.
    if uid == r["submitter_user_id"]:
        raise err_sod()
    # Priority 8: regulatory gate.
    for er in store.exam_requirements.values():
        if er["registration_request_id"] == r["id"] and er["status"] not in ("PASSED", "WAIVED"):
            raise err_regulatory_gate("every exam requirement must be PASSED or WAIVED")
    has_cleared_fp = any(
        fs["registration_request_id"] == r["id"] and fs["status"] == "CLEARED"
        for fs in store.fingerprint_submissions.values()
    )
    if not has_cleared_fp:
        raise err_regulatory_gate("a CLEARED fingerprint submission is required")
    for d in _yes_disclosures(r["id"]):
        if d["review_status"] != "CLEARED":
            raise err_regulatory_gate("every YES disclosure answer must be CLEARED")
    if fingerprint_required(r["applicant_id"]):
        raise err_regulatory_gate("applicant fingerprint requirement is not satisfied")
    # Side effects.
    r["approved_at"] = now()
    r["status"] = "APPROVED"
    for sel in store.jurisdiction_selections.values():
        if sel["registration_request_id"] == r["id"] and sel["status"] == "SELECTED":
            sel["status"] = "APPROVED"
            touch(sel)
    touch(r)
    return success_obj(req_out(r), 200)


@bp.post("/registration-desk/registration-requests/<id>/return-deficient")
def return_deficient(id):
    uid, _ = auth("ComplianceOfficer")
    r = get_or_404(store.registration_requests, id)
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("only a SUBMITTED request may be returned deficient")
    if uid == r["submitter_user_id"]:
        raise err_sod()
    r["deficiency_count"] += 1
    if r["deficiency_count"] >= MAX_DEFICIENCIES:
        # Auto-withdraw on the third return.
        r["status"] = "WITHDRAWN"
        cascade_request_withdrawn(r)
    else:
        r["status"] = "DEFICIENT"
    touch(r)
    return success_obj(req_out(r), 200)


@bp.post("/registration-desk/registration-requests/<id>/deny")
def deny_request(id):
    uid, _ = auth("ComplianceOfficer")
    r = get_or_404(store.registration_requests, id)
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("only a SUBMITTED request may be denied")
    has_flagged = any(
        d["registration_request_id"] == r["id"] and d["review_status"] == "FLAGGED"
        for d in store.background_disclosures.values()
    )
    has_expired = any(
        er["registration_request_id"] == r["id"] and er["status"] == "EXPIRED"
        for er in store.exam_requirements.values()
    )
    if not (has_flagged or has_expired):
        raise err_invalid_state(
            "denial requires a FLAGGED disclosure or an EXPIRED exam requirement"
        )
    if uid == r["submitter_user_id"]:
        raise err_sod()
    r["status"] = "DENIED"
    for sel in store.jurisdiction_selections.values():
        if sel["registration_request_id"] == r["id"] and sel["status"] == "SELECTED":
            sel["status"] = "REJECTED"
            touch(sel)
    touch(r)
    return success_obj(req_out(r), 200)


@bp.post("/registration-desk/registration-requests/<id>/withdraw")
def withdraw_request(id):
    auth("RegistrationPrincipal")
    r = get_or_404(store.registration_requests, id)
    if r["status"] not in ("DRAFT", "DEFICIENT", "SUBMITTED"):
        raise err_invalid_state("only a DRAFT, DEFICIENT, or SUBMITTED request may be withdrawn")
    r["status"] = "WITHDRAWN"
    cascade_request_withdrawn(r)
    touch(r)
    return success_obj(req_out(r), 200)


@bp.get("/registration-desk/registration-requests/<id>/renewal-estimate")
def renewal_estimate(id):
    auth("RegistrationPrincipal", "FinanceClerk", "ComplianceOfficer")
    r = get_or_404(store.registration_requests, id)
    raw = request.args.get("cycle_year")
    if raw is None:
        raise err_invalid_request("cycle_year is required")
    try:
        cycle_year = int(raw)
    except ValueError:
        raise err_invalid_request("cycle_year must be an integer")
    if cycle_year < 2026 or cycle_year > 2100:
        raise err_invalid_request("cycle_year must be between 2026 and 2100")
    j, base, surcharge, total = fee_components(r, cycle_year, today())
    return success_obj({
        "estimated_total_cents": total,
        "jurisdiction_fee_cents": j,
        "base_fee_cents": base,
        "late_surcharge_cents": surcharge,
    }, 200)
