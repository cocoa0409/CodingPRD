"""ExemptionDesignation endpoints: request, approve, deny, review, revoke."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import (
    REVIEW_PERIOD_DAYS,
    now_iso,
    stamp_new,
    store,
    today,
    touch,
)
from errors import (
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DUPLICATE_ACTIVE_EXEMPTION,
    ERR_EXEMPTION_NOT_FOUND,
    ERR_EXEMPTION_PHASE_MISMATCH,
    ERR_INVALID_STATE_TRANSITION,
    ERR_OPEN_ALERT_BLOCKS_EXEMPTION,
    ERR_PHASE_II_INELIGIBLE,
    ERR_PHASE_I_BASIS_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ApiError,
)
from middleware import (
    authenticate,
    body,
    f_enum,
    f_str,
    f_str_opt,
    f_version,
    sorted_page,
)
from response import ok, ok_list
from serializers import serialize_exemption
from services.audit import add_fx, main_event
from services.domain import phase_ii_eligibility, recompute_trailing_45

bp = Blueprint("exemptions", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]
PHASE_I_TYPES = ("BANK", "GOVERNMENT_AGENCY", "BUSINESS_LISTED")
PHASE_II_TYPES = ("BUSINESS_NONLISTED", "PAYROLL_CUSTOMER")
LIVE_DESIGNATION_STATUSES = ("PENDING_REVIEW", "ACTIVE", "REVIEW_DUE")


def get_exemption_or_404(exemption_id):
    d = store.exemptions.get(exemption_id)
    if d is None:
        raise ApiError(ERR_EXEMPTION_NOT_FOUND, "Exemption designation not found", 404)
    return d


def has_open_alert(customer_id):
    return any(
        a["customer_id"] == customer_id and a["status"] in ("OPEN", "UNDER_REVIEW")
        for a in store.alerts.values()
    )


def check_phase_i_basis(designation, customer):
    """PHASE_I basis: type in {BANK, GOVERNMENT_AGENCY, BUSINESS_LISTED} and a
    BUSINESS_LISTED customer must carry a non-null stock_exchange."""
    if customer["customer_type"] not in PHASE_I_TYPES:
        raise ApiError(
            ERR_PHASE_I_BASIS_INVALID,
            "Customer type is not eligible for a Phase I designation",
            422,
        )
    if customer["customer_type"] == "BUSINESS_LISTED" and not designation["stock_exchange"]:
        raise ApiError(
            ERR_PHASE_I_BASIS_INVALID,
            "BUSINESS_LISTED customers require a stock_exchange",
            422,
        )


@bp.post("/customers/<customer_id>/exemption-designations")
def create_designation(customer_id):
    authenticate(["BSAOfficer"])
    b = body()
    phase = f_enum(b, "phase", ("PHASE_I", "PHASE_II"))
    stock_exchange = f_str_opt(b, "stock_exchange")
    note = f_str_opt(b, "note")
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer not found", 404)
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Customer is not ACTIVE", 409)
    if phase == "PHASE_I" and customer["customer_type"] not in PHASE_I_TYPES:
        raise ApiError(
            ERR_EXEMPTION_PHASE_MISMATCH,
            "PHASE_I is available only to BANK, GOVERNMENT_AGENCY, or BUSINESS_LISTED customers",
            422,
        )
    if phase == "PHASE_II" and customer["customer_type"] not in PHASE_II_TYPES:
        raise ApiError(
            ERR_EXEMPTION_PHASE_MISMATCH,
            "PHASE_II is available only to BUSINESS_NONLISTED or PAYROLL_CUSTOMER customers",
            422,
        )
    for existing in store.exemptions.values():
        if (
            existing["customer_id"] == customer_id
            and existing["status"] in LIVE_DESIGNATION_STATUSES
        ):
            raise ApiError(
                ERR_DUPLICATE_ACTIVE_EXEMPTION,
                "Customer already has a designation in PENDING_REVIEW, ACTIVE, or REVIEW_DUE",
                422,
            )
    if phase == "PHASE_I":
        covers_in = True
        covers_out = True
    else:
        covers_in = customer["customer_type"] == "BUSINESS_NONLISTED"
        covers_out = customer["customer_type"] == "PAYROLL_CUSTOMER"
    designation = {
        "customer_id": customer_id,
        "phase": phase,
        "covers_cash_in": covers_in,
        "covers_cash_out": covers_out,
        "stock_exchange": stock_exchange,
        "note": note,
        "status": "PENDING_REVIEW",
        "requested_by_id": g.user_id,
        "designated_by_officer_id": None,
        "designated_at": None,
        "last_reviewed_at": None,
        "review_due_date": None,
        "revocation_reason": None,
        "eligibility_snapshot": None,
    }
    stamp_new(designation)
    store.exemptions[designation["id"]] = designation
    main_event(
        "POST /customers/{customer_id}/exemption-designations",
        "ExemptionDesignation",
        designation["id"],
        None,
        serialize_exemption(designation),
    )
    return ok(serialize_exemption(designation), status=201)


@bp.get("/exemption-designations")
def list_designations():
    authenticate(ALL_ROLES)
    items = list(store.exemptions.values())
    for param in ("customer_id", "status", "phase"):
        value = request.args.get(param)
        if value is not None:
            items = [d for d in items if d[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_exemption(d) for d in page], limit, offset, total)


@bp.get("/exemption-designations/<exemption_id>")
def get_designation(exemption_id):
    authenticate(ALL_ROLES)
    return ok(serialize_exemption(get_exemption_or_404(exemption_id)))


@bp.post("/exemption-designations/<exemption_id>/approve")
def approve_designation(exemption_id):
    authenticate(["BSAOfficer"])
    designation = get_exemption_or_404(exemption_id)
    if designation["status"] != "PENDING_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Designation is not PENDING_REVIEW", 409
        )
    # Business safety: open-alert gate before segregation of duties.
    if has_open_alert(designation["customer_id"]):
        raise ApiError(
            ERR_OPEN_ALERT_BLOCKS_EXEMPTION,
            "Customer has a structuring alert in OPEN or UNDER_REVIEW",
            422,
        )
    if g.user_id == designation["requested_by_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The approving officer must differ from the requesting officer",
            422,
        )
    customer = store.customers.get(designation["customer_id"])
    snapshot = None
    if designation["phase"] == "PHASE_I":
        check_phase_i_basis(designation, customer)
    else:
        passed, snapshot = phase_ii_eligibility(customer, "initial_designation")
        if not passed:
            raise ApiError(
                ERR_PHASE_II_INELIGIBLE,
                "Phase II initial-designation eligibility failed",
                422,
            )
    before = serialize_exemption(designation)
    designation["status"] = "ACTIVE"
    designation["designated_at"] = now_iso()
    designation["last_reviewed_at"] = now_iso()
    designation["designated_by_officer_id"] = g.user_id
    designation["review_due_date"] = (today() + timedelta(days=REVIEW_PERIOD_DAYS)).isoformat()
    designation["eligibility_snapshot"] = snapshot
    touch(designation)
    if customer is not None:
        customer["active_exemption_id"] = designation["id"]
        touch(customer)
    # Now-covered days void their live DRAFT/VALIDATED CTRs.
    recompute_trailing_45(designation["customer_id"])
    main_event(
        "POST /exemption-designations/{id}/approve",
        "ExemptionDesignation",
        designation["id"],
        before,
        serialize_exemption(designation),
    )
    return ok(serialize_exemption(designation))


@bp.post("/exemption-designations/<exemption_id>/deny")
def deny_designation(exemption_id):
    authenticate(["BSAOfficer"])
    b = body()
    reason = f_str(b, "reason")
    designation = get_exemption_or_404(exemption_id)
    if designation["status"] != "PENDING_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Designation is not PENDING_REVIEW", 409
        )
    if g.user_id == designation["requested_by_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The denying officer must differ from the requesting officer",
            422,
        )
    before = serialize_exemption(designation)
    designation["status"] = "DENIED"
    touch(designation)
    add_fx({"type": "denial_reason", "value": reason})
    main_event(
        "POST /exemption-designations/{id}/deny",
        "ExemptionDesignation",
        designation["id"],
        before,
        serialize_exemption(designation),
    )
    return ok(serialize_exemption(designation))


@bp.post("/exemption-designations/<exemption_id>/complete-review")
def complete_review(exemption_id):
    authenticate(["BSAOfficer"])
    b = body()
    outcome = f_enum(b, "outcome", ("PASS", "FAIL"))
    expected = f_version(b, "expected_exemption_version")
    review_note = f_str_opt(b, "review_note")
    designation = get_exemption_or_404(exemption_id)
    # OCC before state checks.
    if expected != designation["version"]:
        raise ApiError(ERR_STALE_VERSION, "Exemption designation version mismatch", 412)
    if designation["status"] != "REVIEW_DUE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Designation is not REVIEW_DUE", 409
        )
    if g.user_id == designation["designated_by_officer_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The reviewing officer must differ from the designating officer",
            422,
        )
    customer = store.customers.get(designation["customer_id"])
    if review_note is not None:
        add_fx({"type": "review_note", "value": review_note})
    before = serialize_exemption(designation)
    if outcome == "PASS":
        snapshot = None
        if designation["phase"] == "PHASE_I":
            check_phase_i_basis(designation, customer)
        else:
            passed, snapshot = phase_ii_eligibility(customer, "annual_review")
            if not passed:
                raise ApiError(
                    ERR_PHASE_II_INELIGIBLE,
                    "Phase II annual-review eligibility failed",
                    422,
                )
        designation["status"] = "ACTIVE"
        designation["last_reviewed_at"] = now_iso()
        designation["review_due_date"] = (
            today() + timedelta(days=REVIEW_PERIOD_DAYS)
        ).isoformat()
        designation["eligibility_snapshot"] = snapshot
        touch(designation)
        if customer is not None:
            customer["active_exemption_id"] = designation["id"]
            touch(customer)
        # Now-covered days void their live DRAFT/VALIDATED CTRs.
        recompute_trailing_45(designation["customer_id"])
    else:  # FAIL
        designation["status"] = "REVOKED"
        designation["revocation_reason"] = "REVIEW_FAILED"
        touch(designation)
        # Newly-required days get auto-created DRAFT CTRs.
        recompute_trailing_45(designation["customer_id"])
    main_event(
        "POST /exemption-designations/{id}/complete-review",
        "ExemptionDesignation",
        designation["id"],
        before,
        serialize_exemption(designation),
    )
    return ok(serialize_exemption(designation))


@bp.post("/exemption-designations/<exemption_id>/revoke")
def revoke_designation(exemption_id):
    authenticate(["BSAOfficer"])
    b = body()
    reason = f_str(b, "reason")
    designation = get_exemption_or_404(exemption_id)
    if designation["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Designation is not ACTIVE", 409)
    before = serialize_exemption(designation)
    designation["status"] = "REVOKED"
    designation["revocation_reason"] = "MANUAL_REVOKE"
    touch(designation)
    customer = store.customers.get(designation["customer_id"])
    if customer is not None and customer.get("active_exemption_id") == designation["id"]:
        customer["active_exemption_id"] = None
        touch(customer)
    add_fx({"type": "revocation_input_reason", "value": reason})
    # Newly-required days get auto-created DRAFT CTRs.
    recompute_trailing_45(designation["customer_id"])
    main_event(
        "POST /exemption-designations/{id}/revoke",
        "ExemptionDesignation",
        designation["id"],
        before,
        serialize_exemption(designation),
    )
    return ok(serialize_exemption(designation))
