"""Copay assistance matching and release."""

from datetime import date

from flask import Blueprint

from db import store, new_id, now_iso, logical_today
from errors import (
    ApiError,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_STALE_VERSION,
    ERR_NO_ELIGIBLE_FOUNDATION,
    ERR_ALREADY_TERMINAL,
    ERR_SEGREGATION_OF_DUTY,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, req_enum, req_int,
    get_enrollment_or_404, get_assistance_or_404,
    pagination_params, paginate, touch,
)
from services.calc import (
    serialize_assistance, assistances_for_enrollment,
    nonterminal_assistance, release_assistance,
    schedule_cleared_shipments,
)

bp = Blueprint("assistance", __name__)


@bp.post("/hub/enrollments/<eid>/copay-assistance/match")
def match_assistance(eid):
    user_id, _ = require_roles("FinancialCounselor")
    e = get_enrollment_or_404(eid)
    data = body()
    assistance_type = req_enum(data, "assistance_type", ("COPAY_CARD", "FOUNDATION"))
    expected_version = req_int(data, "expected_enrollment_version")

    # State validity: terminal enrollment rejects child-mutating ops.
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    # OCC check (priority: state stage, ERR_STALE_VERSION is 412).
    if expected_version != e["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_enrollment_version does not match the "
                       "enrollment's current version.", 412)

    # Funding capacity: FOUNDATION match requires an eligible pool.
    selected_pool = None
    if assistance_type == "FOUNDATION":
        selected_pool = _select_foundation_pool(e)
        if selected_pool is None:
            # No assistance created, no pool mutated, version NOT incremented.
            raise ApiError(ERR_NO_ELIGIBLE_FOUNDATION,
                           "No eligible foundation pool for this enrollment.",
                           422)

    # Supersede any existing non-terminal assistance.
    existing = nonterminal_assistance(eid)
    if existing is not None:
        release_assistance(existing)

    # FOUNDATION: debit the selected pool.
    if selected_pool is not None:
        selected_pool["remaining_balance_cents"] -= selected_pool["grant_amount_cents"]
        touch(selected_pool)

    program = store.drug_programs[e["program_id"]]
    ts = now_iso()
    if assistance_type == "COPAY_CARD":
        per_fill_cap = program["copay_card_per_fill_cap_cents"]
        coverage_pct = None
        annual_cap = program["copay_card_annual_cap_cents"]
        pool_id = None
    else:
        per_fill_cap = None
        coverage_pct = selected_pool["coverage_pct"]
        annual_cap = selected_pool["grant_amount_cents"]
        pool_id = selected_pool["id"]

    initial_status = "ACTIVE" if e["status"] in ("APPROVED", "ACTIVE") else "RESERVED"
    a = {
        "id": new_id(),
        "enrollment_id": eid,
        "assistance_type": assistance_type,
        "foundation_pool_id": pool_id,
        "matched_by_user_id": user_id,
        "status": initial_status,
        "per_fill_cap_cents": per_fill_cap,
        "coverage_pct": coverage_pct,
        "annual_benefit_cap_cents": annual_cap,
        "remaining_annual_benefit_cents": annual_cap,
        "disbursed_cents": 0,
        "returned_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.copay_assistances[a["id"]] = a

    # Successful match increments enrollment.version by 1.
    touch(e)

    # When born ACTIVE on an APPROVED/ACTIVE enrollment, clearance opens:
    # REQUESTED shipments move to SCHEDULED.
    if a["status"] == "ACTIVE":
        schedule_cleared_shipments(e)

    return success_object(serialize_assistance(a), 201)


def _select_foundation_pool(enrollment):
    """assistance_match_selector: eligibility filter + ranking.

    Eligible: diagnosis_code exact match; clock date within [start, end]
    inclusive; remaining_balance_cents >= grant_amount_cents.
    Ranking: coverage_pct DESC, then earliest start_date, then created_at ASC.
    """
    today = logical_today()
    candidates = []
    for pool in store.foundation_pools.values():
        if pool["diagnosis_code"] != enrollment["diagnosis_code"]:
            continue
        start_d = date.fromisoformat(pool["start_date"])
        end_d = date.fromisoformat(pool["end_date"])
        if not (start_d <= today <= end_d):
            continue
        if pool["remaining_balance_cents"] < pool["grant_amount_cents"]:
            continue
        candidates.append(pool)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (
        -p["coverage_pct"],
        date.fromisoformat(p["start_date"]),
        p["created_at"],
    ))
    return candidates[0]


@bp.post("/hub/copay-assistances/<aid>/release")
def release(aid):
    user_id, _ = require_roles("FinancialCounselor")
    a = get_assistance_or_404(aid)
    if a["status"] == "RELEASED":
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "Copay assistance is already released.", 409)
    # Segregation of duties: releaser must differ from the matcher.
    if user_id == a["matched_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTY,
                       "The releasing user must differ from the user who "
                       "matched the assistance.", 403)
    release_assistance(a)
    return success_object(serialize_assistance(a), 200)


@bp.get("/hub/enrollments/<eid>/copay-assistances")
def list_enrollment_assistances(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(assistances_for_enrollment(eid), limit, offset)
    return success_array([serialize_assistance(a) for a in page],
                         limit, offset, total, 200)
