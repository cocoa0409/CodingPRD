"""Member endpoints: enrollment, lifecycle PATCH (incl. the death cascade),
the computed benefit estimate, and member-scoped list endpoints."""

from flask import Blueprint, request

from db import store, make_entity, touch, public, sort_key
from errors import err_not_found, err_invalid_request, err_invalid_state
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_str,
    pagination,
    check_member_path,
    check_member_view,
)
from response import ok, ok_list
from services import calcs, cascades
from utils import parse_date

bp = Blueprint("members", __name__)

ALL_ROLES = {
    "FundAdmin",
    "MemberServicesAnalyst",
    "BenefitApprover",
    "MedicalReviewer",
    "EmployerClerk",
    "Member",
    "SurvivorClaimant",
}

MEMBER_STATUSES = {"ACTIVE", "INACTIVE", "RETIRED", "SUSPENDED_RTW", "DECEASED"}
# PATCH /members/{id} drives exactly these two status transitions:
PATCH_STATUS_TRANSITIONS = {("ACTIVE", "INACTIVE"), ("INACTIVE", "ACTIVE")}
# Death may be recorded from any non-terminal member state:
DEATH_FROM_STATES = {"ACTIVE", "INACTIVE", "RETIRED", "SUSPENDED_RTW"}


def get_member(member_id):
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    return member


def serialize_member(m):
    out = public(m)
    out["total_service_years"] = float(m["total_service_years"])
    return out


@bp.post("/members")
def create_member():
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    data = body()
    employer_id = req_field(data, "employer_id")
    if not isinstance(employer_id, str):
        raise err_invalid_request("employer_id must be a string")
    full_name = as_str(req_field(data, "full_name"), "full_name")
    dob = parse_date(req_field(data, "date_of_birth"))
    if dob is None:
        raise err_invalid_request("date_of_birth must be an ISO date")
    hire = parse_date(req_field(data, "hire_date"))
    if hire is None:
        raise err_invalid_request("hire_date must be an ISO date")
    if employer_id not in store.employers:
        raise err_not_found("Employer not found")
    # Computed/system fields in the payload are ignored: status starts ACTIVE,
    # total_service_years 0, current_annual_salary_cents null.
    member = make_entity(
        {
            "employer_id": employer_id,
            "full_name": full_name,
            "date_of_birth": dob.isoformat(),
            "hire_date": hire.isoformat(),
            "status": "ACTIVE",
            "total_service_years": calcs.round_half_up_2dp(calcs.Decimal("0")),
            "current_annual_salary_cents": None,
            "deceased_at": None,
            "_dob": dob,
            "_hire_date": hire,
        }
    )
    store.members[member["id"]] = member
    return ok(serialize_member(member), 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    ctx = auth()
    require_roles(ctx, ALL_ROLES)
    check_member_path(ctx, member_id)
    member = get_member(member_id)
    check_member_view(ctx, member)
    return ok(serialize_member(member))


@bp.patch("/members/<member_id>")
def update_member(member_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    member = get_member(member_id)
    data = body()

    deceased_at = data.get("deceased_at")
    status = data.get("status")

    if deceased_at is not None:
        # Recording the member's death: DECEASED from any non-terminal state,
        # then the shared death cascade (§3.7).
        if member["status"] not in DEATH_FROM_STATES:
            raise err_invalid_state("Member is already DECEASED")
        d = parse_date(deceased_at)
        if d is None:
            raise err_invalid_request("deceased_at must be an ISO date")
        member["deceased_at"] = d.isoformat()
        member["status"] = "DECEASED"
        touch(member)
        cascades.death_cascade(member)
    elif status is not None:
        if not isinstance(status, str) or status not in MEMBER_STATUSES:
            raise err_invalid_request("Unknown member status: %s" % status)
        if (member["status"], status) not in PATCH_STATUS_TRANSITIONS:
            raise err_invalid_state(
                "Cannot move member from %s to %s" % (member["status"], status)
            )
        member["status"] = status
        touch(member)

    return ok(serialize_member(member))


@bp.get("/members/<member_id>/benefit-estimate")
def benefit_estimate(member_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst", "BenefitApprover"})
    check_member_path(ctx, member_id)
    member = get_member(member_id)
    variant = request.args.get("variant")
    if variant is None:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            variant = data.get("variant")
    if variant is None:
        variant = "FINAL"
    if variant not in ("FINAL", "PROVISIONAL"):
        raise err_invalid_request("variant must be FINAL or PROVISIONAL")
    est = calcs.benefit_estimate(member, variant)
    return ok(
        {
            "fas_cents": est["fas_cents"],
            "service_years": float(est["service_years"]),
            "multiplier": float(est["multiplier"]),
            "monthly_single_life_cents": est["monthly_cents"],
            "variant": variant,
        }
    )


# ---------------------------------------------------------------------------
# Member-scoped list endpoints
# ---------------------------------------------------------------------------

def _member_scoped_list(ctx, member_id, roles, items):
    require_roles(ctx, roles)
    check_member_view(ctx, get_member(member_id))
    limit, offset = pagination()
    items = sorted(items, key=sort_key)
    page = items[offset:offset + limit]
    return ok_list([public(i) for i in page], limit, offset, len(items))


@bp.get("/members/<member_id>/contribution-lines")
def list_member_lines(member_id):
    ctx = auth()
    require_roles(ctx, {"FundAdmin", "MemberServicesAnalyst", "EmployerClerk", "Member"})
    member = get_member(member_id)
    check_member_view(ctx, member)
    limit, offset = pagination()
    fy_raw = request.args.get("fiscal_year")
    if fy_raw is None:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            fy_raw = data.get("fiscal_year")
    lines = [l for l in store.lines.values() if l["member_id"] == member_id]
    if fy_raw is not None:
        try:
            fy = int(fy_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("fiscal_year must be an integer")
        lines = [l for l in lines if l["fiscal_year"] == fy]
    lines.sort(key=sort_key)
    page = lines[offset:offset + limit]
    return ok_list([public(l) for l in page], limit, offset, len(lines))


@bp.get("/members/<member_id>/service-purchases")
def list_member_purchases(member_id):
    ctx = auth()
    purchases = [p for p in store.purchases.values() if p["member_id"] == member_id]
    result = _member_scoped_list(
        ctx, member_id, {"FundAdmin", "MemberServicesAnalyst", "Member"}, purchases
    )
    return result


@bp.get("/members/<member_id>/retirement-applications")
def list_member_retirement_apps(member_id):
    ctx = auth()
    apps = [a for a in store.retirement_apps.values() if a["member_id"] == member_id]
    return _member_scoped_list(
        ctx,
        member_id,
        {"FundAdmin", "MemberServicesAnalyst", "BenefitApprover", "Member"},
        apps,
    )


@bp.get("/members/<member_id>/disability-applications")
def list_member_disability_apps(member_id):
    ctx = auth()
    apps = [a for a in store.disability_apps.values() if a["member_id"] == member_id]
    return _member_scoped_list(
        ctx,
        member_id,
        {"FundAdmin", "MemberServicesAnalyst", "MedicalReviewer", "Member"},
        apps,
    )


@bp.get("/members/<member_id>/benefits")
def list_member_benefits(member_id):
    ctx = auth()
    benefits = [b for b in store.benefits.values() if b["member_id"] == member_id]
    return _member_scoped_list(
        ctx,
        member_id,
        {"FundAdmin", "MemberServicesAnalyst", "BenefitApprover", "Member",
         "SurvivorClaimant"},
        benefits,
    )


@bp.get("/members/<member_id>/beneficiaries")
def list_member_beneficiaries(member_id):
    ctx = auth()
    bens = [b for b in store.beneficiaries.values() if b["member_id"] == member_id]
    return _member_scoped_list(
        ctx,
        member_id,
        {"FundAdmin", "MemberServicesAnalyst", "BenefitApprover", "Member",
         "SurvivorClaimant"},
        bens,
    )
