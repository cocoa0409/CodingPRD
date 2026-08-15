"""Routes: clock, statute profiles, payees, guardianship cases."""

from flask import Blueprint, request

from db import DB, CLOCK, base_entity, touch, parse_date, clock_date_iso
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_STATE_PROFILE_NOT_FOUND,
    ERR_DUPLICATE_STATE_PROFILE,
    ERR_GUARDIANSHIP_INVALID_STATE,
    ERR_GUARDIANSHIP_OVERLAP,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, opt_field, as_string, as_int, as_bool, as_positive_int,
    as_nonnegative_int, as_date, as_iso8601, parse_pagination,
)
from response import success_object, success_list
from services import (
    pub, list_view, find_profile_by_state, compute_is_minor,
    active_guardianship,
)
from sweep import run_clock_sweep

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/annuity/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_roles(caller, {"PlatformAdmin"})
    body = get_json_body()
    # domain guards: none
    check_unknown_fields(body, {"to_iso8601"})
    to_v = as_iso8601(require_field(body, "to_iso8601"), "to_iso8601")
    CLOCK.set(to_v)
    fired = run_clock_sweep()
    return success_object({
        "current_utc": CLOCK.now().strftime("%Y-%m-%dT%H:%M:%S.") + f"{CLOCK.now().microsecond // 1000:03d}Z",
        "transitions_fired": fired,
    })


# ---------------------------------------------------------------------------
# StateStatuteProfile
# ---------------------------------------------------------------------------

PROFILE_FIELDS = {
    "state_code", "age_of_majority", "sspa_max_discount_rate_bps",
    "disclosure_cooling_off_days", "ipa_required", "dormancy_years",
    "commutation_permitted",
}


def profile_view(p):
    return pub(p)


@bp.route("/annuity/state-statute-profiles", methods=["POST"])
def create_profile():
    caller = get_caller()
    require_roles(caller, {"PlatformAdmin"})
    body = get_json_body()
    state_code = body.get("state_code")
    # business: duplicate check runs before shape checks on other fields but
    # state_code presence is needed for the duplicate check; treat presence of
    # state_code as shape and the duplicate as uniqueness (priority 15).
    if state_code is not None and isinstance(state_code, str):
        if find_profile_by_state(state_code) is not None:
            raise ApiError(ERR_DUPLICATE_STATE_PROFILE, "A StateStatuteProfile for this state_code already exists", 409)
    check_unknown_fields(body, PROFILE_FIELDS)
    state_code = as_string(require_field(body, "state_code"), "state_code")
    age_of_majority = as_int(require_field(body, "age_of_majority"), "age_of_majority")
    if age_of_majority < 18 or age_of_majority > 21:
        raise ApiError(ERR_INVALID_REQUEST, "age_of_majority must be in 18..21", 400)
    sspa_cap = as_positive_int(require_field(body, "sspa_max_discount_rate_bps"), "sspa_max_discount_rate_bps")
    cooling = as_nonnegative_int(require_field(body, "disclosure_cooling_off_days"), "disclosure_cooling_off_days")
    ipa = as_bool(require_field(body, "ipa_required"), "ipa_required")
    dormancy = as_int(require_field(body, "dormancy_years"), "dormancy_years")
    if dormancy < 1:
        raise ApiError(ERR_INVALID_REQUEST, "dormancy_years must be >= 1", 400)
    comm_perm = as_bool(require_field(body, "commutation_permitted"), "commutation_permitted")

    e = base_entity()
    e.update({
        "state_code": state_code,
        "age_of_majority": age_of_majority,
        "sspa_max_discount_rate_bps": sspa_cap,
        "disclosure_cooling_off_days": cooling,
        "ipa_required": ipa,
        "dormancy_years": dormancy,
        "commutation_permitted": comm_perm,
    })
    DB.state_statute_profiles[e["id"]] = e
    return success_object(profile_view(e), status=201)


@bp.route("/annuity/state-statute-profiles", methods=["GET"])
def list_profiles():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.state_statute_profiles.values())
    sc = request.args.get("state_code")
    if sc is not None:
        items = [p for p in items if p["state_code"] == sc]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/state-statute-profiles/<profileId>", methods=["GET"])
def get_profile(profileId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    p = DB.state_statute_profiles.get(profileId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "StateStatuteProfile not found", 404)
    return success_object(profile_view(p))


# ---------------------------------------------------------------------------
# Payee
# ---------------------------------------------------------------------------

PAYEE_FIELDS = {
    "full_name", "date_of_birth", "tax_id", "address_line1", "address_city",
    "address_state_code", "address_postal_code", "phone", "email",
}


def payee_view(p):
    d = pub(p)
    d["is_minor"] = compute_is_minor(p)
    return d


@bp.route("/annuity/payees", methods=["POST"])
def create_payee():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    # existence: address_state_code must resolve
    asc = body.get("address_state_code")
    if asc is not None and isinstance(asc, str):
        if find_profile_by_state(asc) is None:
            raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for address_state_code", 404)
    check_unknown_fields(body, PAYEE_FIELDS)
    full_name = as_string(require_field(body, "full_name"), "full_name")
    dob = as_date(require_field(body, "date_of_birth"), "date_of_birth")
    if dob >= CLOCK.today():
        raise ApiError(ERR_INVALID_REQUEST, "date_of_birth must be strictly before the current clock date", 400)
    tax_id = as_string(require_field(body, "tax_id"), "tax_id")
    al1 = as_string(require_field(body, "address_line1"), "address_line1")
    city = as_string(require_field(body, "address_city"), "address_city")
    asc = as_string(require_field(body, "address_state_code"), "address_state_code")
    if find_profile_by_state(asc) is None:
        raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for address_state_code", 404)
    postal = as_string(require_field(body, "address_postal_code"), "address_postal_code")
    phone = opt_field(body, "phone")
    if phone is not None:
        as_string(phone, "phone")
    email = opt_field(body, "email")
    if email is not None:
        as_string(email, "email")

    e = base_entity()
    e.update({
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "tax_id": tax_id,
        "address_line1": al1,
        "address_city": city,
        "address_state_code": asc,
        "address_postal_code": postal,
        "phone": phone,
        "email": email,
        "status": "ACTIVE",
        "deceased_date": None,
    })
    DB.payees[e["id"]] = e
    return success_object(payee_view(e), status=201)


@bp.route("/annuity/payees", methods=["GET"])
def list_payees():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.payees.values())
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    asc = request.args.get("address_state_code")
    if asc is not None:
        items = [p for p in items if p["address_state_code"] == asc]
    sorted_items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    return success_list([payee_view(p) for p in page], limit, offset, total)


@bp.route("/annuity/payees/<payeeId>", methods=["GET"])
def get_payee(payeeId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    p = DB.payees.get(payeeId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    return success_object(payee_view(p))


# ---------------------------------------------------------------------------
# GuardianshipCase
# ---------------------------------------------------------------------------

GUARDIANSHIP_FIELDS = {"payee_id", "court_state_code", "guardian_full_name", "effective_from_date"}


def guardianship_view(g):
    return pub(g)


def _guardianship_overlap(payee_id, effective_from, exclude_id=None):
    """Check overlap of [effective_from, infinity) with other PENDING_REVIEW /
    ACTIVE cases' [effective_from_date, terminated_at_date or infinity)."""
    new_start = effective_from
    for g in DB.guardianship_cases.values():
        if g["payee_id"] != payee_id:
            continue
        if g["status"] not in ("PENDING_REVIEW", "ACTIVE"):
            continue
        if exclude_id is not None and g["id"] == exclude_id:
            continue
        g_start = parse_date(g["effective_from_date"])
        g_end = parse_date(g["terminated_at_date"]) if g.get("terminated_at_date") else None
        # half-open [g_start, g_end or inf) intersect [new_start, inf)
        # intersect iff g_start < inf and new_start < (g_end or inf)
        if g_end is None:
            intersect = True
        else:
            intersect = new_start < g_end
        if intersect:
            return True
    return False


@bp.route("/annuity/guardianship-cases", methods=["POST"])
def create_guardianship():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    # existence: payee_id must resolve
    payee_id = body.get("payee_id")
    payee = None
    if payee_id is not None and isinstance(payee_id, str):
        payee = DB.payees.get(payee_id)
        if payee is None:
            raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    # business: overlap (priority 14)
    eff = body.get("effective_from_date")
    if payee is not None and isinstance(eff, str):
        try:
            eff_d = parse_date(eff)
            if _guardianship_overlap(payee["id"], eff_d):
                raise ApiError(ERR_GUARDIANSHIP_OVERLAP, "Guardianship intervals intersect for the same payee", 409)
        except ValueError:
            pass
    check_unknown_fields(body, GUARDIANSHIP_FIELDS)
    payee_id = as_string(require_field(body, "payee_id"), "payee_id")
    payee = DB.payees.get(payee_id)
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    csc = as_string(require_field(body, "court_state_code"), "court_state_code")
    gname = as_string(require_field(body, "guardian_full_name"), "guardian_full_name")
    eff = as_date(require_field(body, "effective_from_date"), "effective_from_date")

    e = base_entity()
    e.update({
        "payee_id": payee_id,
        "court_state_code": csc,
        "guardian_full_name": gname,
        "effective_from_date": eff.isoformat(),
        "terminated_at_date": None,
        "status": "PENDING_REVIEW",
    })
    DB.guardianship_cases[e["id"]] = e
    return success_object(guardianship_view(e), status=201)


@bp.route("/annuity/guardianship-cases", methods=["GET"])
def list_guardianships():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.guardianship_cases.values())
    pid = request.args.get("payee_id")
    if pid is not None:
        items = [g for g in items if g["payee_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/guardianship-cases/<caseId>", methods=["GET"])
def get_guardianship(caseId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    g = DB.guardianship_cases.get(caseId)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "GuardianshipCase not found", 404)
    return success_object(guardianship_view(g))


@bp.route("/annuity/guardianship-cases/<caseId>/activate", methods=["POST"])
def activate_guardianship(caseId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    g = DB.guardianship_cases.get(caseId)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "GuardianshipCase not found", 404)
    if g["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_GUARDIANSHIP_INVALID_STATE, "Guardianship case not PENDING_REVIEW", 409)
    if _guardianship_overlap(g["payee_id"], parse_date(g["effective_from_date"]), exclude_id=g["id"]):
        raise ApiError(ERR_GUARDIANSHIP_OVERLAP, "Guardianship intervals intersect for the same payee", 409)
    get_json_body()  # tolerate empty body
    g["status"] = "ACTIVE"
    touch(g)
    return success_object(guardianship_view(g))


@bp.route("/annuity/guardianship-cases/<caseId>/revoke", methods=["POST"])
def revoke_guardianship(caseId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    g = DB.guardianship_cases.get(caseId)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "GuardianshipCase not found", 404)
    if g["status"] != "ACTIVE":
        raise ApiError(ERR_GUARDIANSHIP_INVALID_STATE, "Guardianship case not ACTIVE", 409)
    get_json_body()
    g["status"] = "REVOKED"
    g["terminated_at_date"] = clock_date_iso()
    touch(g)
    return success_object(guardianship_view(g))
