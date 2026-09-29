"""PRD 3.1 recruitment / licensing, 3.8 revenue read, 3.9 network exit, plus provider reads."""
from flask import Blueprint

import auth
import calculations as calc
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("providers", __name__)

COUNTY_TIERS = ("HIGH_NEED", "STANDARD")


def _scoped_provider(actor, provider_id):
    """Ownership scope (ladder 4) before path existence (ladder 5): a Provider
    actor's own id is known without loading the row."""
    auth.scope_provider(actor, provider_id)
    return services.provider_or_404(provider_id)


# --- 3.1 application and licensing ----------------------------------------

@bp.post("/fccn/providers/apply")
def apply_to_network():
    auth.allow_anonymous()
    body = v.get_body()
    v.reject_unversioned(body)
    legal_name = v.req_str(body, "legal_name", 1, 120)
    county_tier = v.opt_enum(body, "county_tier", COUNTY_TIERS, "STANDARD")
    # Volunteered licensing details are shape-checked and then discarded: PRD 3.1 says
    # all three stay null until the network verifies the license.
    v.opt_str(body, "license_number")
    v.opt_instant(body, "license_expires_on")
    v.opt_int(body, "capacity_slots", None, 1, 12)
    fixed_monthly_cost_cents = v.opt_int(body, "fixed_monthly_cost_cents", 180000, 0)

    row = db.make_row(
        legal_name=legal_name,
        county_tier=county_tier,
        license_number=None,
        license_expires_on=None,
        capacity_slots=None,
        fixed_monthly_cost_cents=fixed_monthly_cost_cents,
        membership_status="APPLICANT",
        network_posture="FROZEN",
        network_fee_pct=0,
        quality_score=0,
        quality_tier="UNRATED",
        quality_variant_applied="NONE",
        open_finding_count=0,
        projected_monthly_revenue_cents=0,
        exit_reason=None,
    )
    services.register_new(row)
    db.providers[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/providers/<provider_id>/license-verification")
def license_verification(provider_id):
    auth.require_auth(("NetworkAdmin",))
    provider = services.provider_or_404(provider_id)
    body = v.get_body()
    v.reject_unversioned(body)
    license_number = v.req_str(body, "license_number")
    license_expires_on = v.req_instant(body, "license_expires_on")
    capacity_slots = v.opt_int(body, "capacity_slots", None, 1, 12)
    effective_capacity = capacity_slots if capacity_slots is not None else provider["capacity_slots"]
    if not isinstance(effective_capacity, int) or not 1 <= effective_capacity <= 12:
        v.bad("Licensed capacity_slots must be between 1 and 12.")

    if provider["membership_status"] != "APPLICANT":
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE",
            "License verification is only accepted while the provider is APPLICANT.",
        )
    if clock.parse_instant(license_expires_on) <= clock.now():
        raise ApiError(
            "ERR_LICENSE_EXPIRED",
            "The verified license expiry must fall strictly later than the logical clock.",
        )

    provider["license_number"] = license_number
    provider["license_expires_on"] = license_expires_on
    provider["capacity_slots"] = effective_capacity
    services.set_membership_status(provider, "PENDING_AGREEMENT")
    return response.ok(provider)


# --- 3.7 reinstatement (inverse of the escalation cascade) -----------------

@bp.post("/fccn/providers/<provider_id>/reinstate")
def reinstate(provider_id):
    auth.require_auth(("NetworkAdmin",))
    provider = services.provider_or_404(provider_id)
    if provider["membership_status"] != "PROBATION":
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE", "Only a provider on PROBATION may be reinstated."
        )
    if provider["open_finding_count"] != 0:
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE",
            "Probation may only be lifted once open_finding_count has fallen to zero.",
        )
    services.reinstatement_cascade(provider)
    return response.ok(provider)


# --- 3.9 network exit ------------------------------------------------------

@bp.post("/fccn/providers/<provider_id>/exit-network")
def exit_network(provider_id):
    auth.require_auth(("NetworkAdmin",))
    provider = services.provider_or_404(provider_id)
    body = v.get_body()
    v.reject_unversioned(body)
    exit_reason = v.req_str(body, "exit_reason")
    if provider["membership_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE",
            "A network exit may only begin from ACTIVE or PROBATION.",
        )
    provider["exit_reason"] = exit_reason
    services.set_membership_status(provider, "EXITING")
    services.exit_cascade(provider)
    return response.ok(provider)


@bp.post("/fccn/providers/<provider_id>/complete-exit")
def complete_exit(provider_id):
    auth.require_auth(("NetworkAdmin",))
    provider = services.provider_or_404(provider_id)
    if provider["membership_status"] != "EXITING":
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE", "Only an EXITING provider's exit may be finalized."
        )
    pending = [
        e for e in services.provider_children(db.enrollments, provider_id)
        if e["status"] in ("ENROLLED", "TRANSITION_PENDING")
    ]
    if pending:
        raise ApiError(
            "ERR_EXIT_TRANSITIONS_PENDING",
            "Every family must be transferred or withdrawn before the exit is finalized.",
        )
    services.set_membership_status(provider, "EXITED")
    services.terminate_contracts(provider)
    return response.ok(provider)


# --- reads -----------------------------------------------------------------

@bp.get("/fccn/providers")
def list_providers():
    auth.require_auth(("NetworkAdmin", "FiscalOfficer", "QualityCoach"))
    limit, offset = v.pagination()
    rows = v.filtered(
        db.providers.values(),
        county_tier="county_tier",
        membership_status="membership_status",
        quality_tier="quality_tier",
    )
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/providers/<provider_id>")
def read_provider(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "QualityCoach", "Provider"))
    provider = _scoped_provider(actor, provider_id)
    return response.ok(provider)


@bp.get("/fccn/providers/<provider_id>/revenue-model")
def read_revenue_model(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    provider = _scoped_provider(actor, provider_id)
    return response.ok(calc.revenue_model(provider))


def _child_list(actor, provider_id, collection, **filters):
    provider = _scoped_provider(actor, provider_id)
    limit, offset = v.pagination()
    rows = v.filtered(services.provider_children(collection, provider["id"]), **filters)
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/fccn/providers/<provider_id>/membership-agreements")
def list_provider_agreements(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "Provider"))
    return _child_list(actor, provider_id, db.agreements, status="status")


@bp.get("/fccn/providers/<provider_id>/subsidy-contracts")
def list_provider_contracts(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return _child_list(actor, provider_id, db.contracts, status="status")


@bp.get("/fccn/providers/<provider_id>/food-program-claims")
def list_provider_food_claims(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return _child_list(
        actor, provider_id, db.food_claims, period_month="period_month", status="status"
    )


@bp.get("/fccn/providers/<provider_id>/coaching-visits")
def list_provider_visits(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "QualityCoach", "Provider"))
    return _child_list(actor, provider_id, db.visits, status="status")


@bp.get("/fccn/providers/<provider_id>/compliance-reviews")
def list_provider_reviews(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "QualityCoach", "Provider"))
    return _child_list(actor, provider_id, db.reviews, status="status")


@bp.get("/fccn/providers/<provider_id>/group-purchase-orders")
def list_provider_orders(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "Provider"))
    return _child_list(actor, provider_id, db.orders, category="category", status="status")


@bp.get("/fccn/providers/<provider_id>/substitute-assignments")
def list_provider_assignments(provider_id):
    actor = auth.require_auth(("NetworkAdmin", "FiscalOfficer", "Provider"))
    return _child_list(
        actor,
        provider_id,
        db.assignments,
        staffing_status="staffing_status",
        billing_status="billing_status",
    )
