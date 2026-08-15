"""Case priority scoring, score variants, deposit exposure, and case lifecycle
gates (PRD §2.7, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case,
    assert_instant_equal,
    create_case_payload,
    get_case,
    get_session,
    move_case_in_progress,
    open_case,
    setup_hotline,
    start_active_session,
    transition_case_ok,
    validate_error,
    validate_success,
    verify_case,
)

# Facts scoring 75 at the default clock: eviction d=4 -> 50, habitability h=17
# in (14, 28] -> 15, deposit 200000 over cap 150000 -> 10. notice_served_at makes
# the VERIFIED variant halve the eviction component (served 2 days < 3 statutory).
DUAL_VARIANT_FACTS = {
    "eviction_notice_date": "2026-08-05",
    "notice_served_at": "2026-08-03T00:00:00Z",
    "habitability_reported_at": "2026-07-15T00:00:00Z",
    "deposit_amount_cents": 200000,
    "monthly_rent_cents": 150000,
}


def test_provisional_score_at_intake(api):
    """PRD §3.6: "The case starts `OPEN` with `score_variant` `PROVISIONAL`, and
    `priority_score`, `urgency_tier`, `required_follow_up_count`, and
    `deposit_exposure_cents` are computed in the same request."
    PRD §3.6: "`PROVISIONAL` — scored at intake and on every fact edit before
    verification — is built on self-reported facts alone: it ignores
    `notice_served_at` (no defective-notice halving) and ignores
    `escalation_level`."

    Design: Difficulty/dual_variant_calc/case_score_provisional_vs_verified
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, **DUAL_VARIANT_FACTS)
    assert_case(case)
    # 50 (eviction d=4 <= 5) + 15 (habitability h=17 in (14, 28]) + 10 (over cap)
    assert case["priority_score"] == 75
    assert case["urgency_tier"] == "CRITICAL"
    assert case["score_variant"] == "PROVISIONAL"
    assert case["required_follow_up_count"] == 3


def test_verify_recomputes_under_verified_variant(api):
    """PRD §3.6: "A `Counselor` or `HotlineSupervisor` whose identifier differs from
    `opened_by_counselor_id` verifies the case — segregation of duties, enforced as
    `ERR_SCRIPT_REVIEWER_CONFLICT` — which records the verifier in
    `verified_by_counselor_id`, flips `score_variant` to `VERIFIED`, and immediately
    recomputes the score under the verified variant."
    PRD §3.6: "Under the `VERIFIED` variant only, a defective-notice halving then
    applies to that contribution: when `notice_served_at` is set, the notice period
    actually given is the whole days between the served date and the stated
    deadline, and if that period is shorter than the jurisdiction's
    `eviction_notice_days`, the eviction contribution is halved, rounding down to a
    whole number of points."

    Design: Difficulty/dual_variant_calc/case_score_provisional_vs_verified
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, **DUAL_VARIANT_FACTS)
    assert case["priority_score"] == 75

    verified = verify_case(bundle, case)
    # Served 2026-08-03, deadline 2026-08-05 -> 2 days given < 3 statutory ->
    # eviction component halved: floor(50/2) = 25; total 25 + 15 + 10 = 50.
    assert verified["priority_score"] == 50
    assert verified["urgency_tier"] == "ELEVATED"
    assert verified["score_variant"] == "VERIFIED"
    assert verified["verified_by_counselor_id"] == bundle["reviewer"]["id"]


def test_habitability_strict_double_boundary(api):
    """PRD §3.6: "Second, the habitability component, which applies when
    `habitability_reported_at` is set: if the issue has stood unremedied for
    strictly more than twice the jurisdiction's `habitability_repair_days`, 25
    points are added; if it has stood for strictly more than the repair period but
    at most twice that period, 15 points are added."

    Design: Difficulty/combinatorial_formula/priority_score_tiered_branching
    """
    bundle = setup_hotline()  # habitability_repair_days = 14
    caller, session_a = start_active_session(bundle)
    case_a = open_case(bundle, caller, session_a,
                       habitability_reported_at="2026-07-03T00:00:00Z")
    # h = 29 days > 2*14 -> +25
    assert case_a["priority_score"] == 25
    assert case_a["urgency_tier"] == "STANDARD"

    _, session_b = start_active_session(bundle, caller=caller)
    case_b = open_case(bundle, caller, session_b,
                       habitability_reported_at="2026-07-04T00:00:00Z")
    # h = 28 days: strictly-more-than 2*14 fails, > 14 holds -> +15
    assert case_b["priority_score"] == 15
    assert case_b["urgency_tier"] == "STANDARD"


def test_three_component_score_assembly(api):
    """PRD §3.6: "Third, the deposit component: when both `deposit_amount_cents` and
    `monthly_rent_cents` are set and the deposit exceeds the monthly rent multiplied
    by the jurisdiction's `deposit_cap_months`, 10 points are added."
    PRD §3.6: "the number of whole calendar days from the current date to the stated
    deadline — which may be negative when the deadline has already passed — selects
    a tier: five days or fewer contributes 50 points; more than five but at most
    fourteen days contributes 30 points; more than fourteen but at most thirty days
    contributes 15 points; and more than thirty days contributes nothing."
    PRD §3.6: "The **urgency tier** maps the score immediately, in the same request:
    a score of at least 70 is `CRITICAL`, at least 40 is `ELEVATED`, and anything
    lower is `STANDARD`."

    Design: Difficulty/combinatorial_formula/priority_score_tiered_branching
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(
        bundle, caller, session,
        habitability_reported_at="2026-07-03T00:00:00Z",  # h=29 -> +25
        deposit_amount_cents=200000, monthly_rent_cents=150000,  # over cap -> +10
        eviction_notice_date="2026-08-21",  # d=20 in (14, 30] -> +15
    )
    assert case["priority_score"] == 50
    assert case["urgency_tier"] == "ELEVATED"


def test_deposit_exposure_rounding_order(api):
    """PRD §2.7: "The deposit-exposure estimate rounds each of its components
    half-up to whole cents before summation, and that rounding order is pinned:
    summing unrounded components and rounding once at the end is non-conformant and
    yields different cents."
    PRD §3.6: "Rounding is pinned per component, each rounded half-up to whole cents
    before any summation: the statutory cap in cents is the monthly rent multiplied
    by the jurisdiction's `deposit_cap_months`, rounded half-up; the over-cap
    portion is the excess of the deposit over that cap, floored at zero; interest
    applies only when the jurisdiction's `deposit_interest_required` is true,
    computed as the deposit times the jurisdiction's `deposit_interest_rate_pct`
    times `deposit_days_held`, divided by 36500 and rounded half-up; and the penalty
    portion is the over-cap portion multiplied by 1.5, rounded half-up.
    `deposit_exposure_cents` is the sum of the over-cap portion, the interest, and
    the penalty."

    Design: Difficulty/combinatorial_formula/deposit_exposure_rounding_order
    """
    bundle = setup_hotline(
        categories=("DEPOSIT",),
        jurisdiction_overrides={
            "deposit_cap_months": 1.5,
            "deposit_interest_required": True,
            "deposit_interest_rate_pct": 5.0,
        },
    )
    caller, session = start_active_session(bundle, category="DEPOSIT")
    case = open_case(
        bundle, caller, session,
        issue_category="DEPOSIT",
        deposit_amount_cents=225111, monthly_rent_cents=100000,
        deposit_days_held=100,
    )
    # cap = round(100000*1.5) = 150000; over = 75111;
    # interest = round(225111*5.0*100/36500) = round(3083.7123...) = 3084;
    # penalty = round(75111*1.5) = round(112666.5) = 112667;
    # total = 75111 + 3084 + 112667 = 190862 (sum-then-round would give 190861).
    assert case["deposit_exposure_cents"] == 190862


def test_deposit_exposure_reread_and_score(api):
    """PRD §3.6: "`deposit_exposure_cents` is the sum of the over-cap portion, the
    interest, and the penalty."
    PRD §3.6: "Third, the deposit component: when both `deposit_amount_cents` and
    `monthly_rent_cents` are set and the deposit exceeds the monthly rent multiplied
    by the jurisdiction's `deposit_cap_months`, 10 points are added."

    Design: Difficulty/combinatorial_formula/deposit_exposure_rounding_order
    """
    bundle = setup_hotline(
        categories=("DEPOSIT",),
        jurisdiction_overrides={
            "deposit_cap_months": 1.5,
            "deposit_interest_required": True,
            "deposit_interest_rate_pct": 5.0,
        },
    )
    caller, session = start_active_session(bundle, category="DEPOSIT")
    case = open_case(
        bundle, caller, session,
        issue_category="DEPOSIT",
        deposit_amount_cents=225111, monthly_rent_cents=100000,
        deposit_days_held=100,
    )
    reread = get_case(bundle, case["id"])
    assert reread["deposit_exposure_cents"] == 190862
    # Only the deposit component contributes to the score: +10 -> STANDARD.
    assert reread["priority_score"] == 10
    assert reread["urgency_tier"] == "STANDARD"


def test_eviction_day5_inclusive_boundary(api):
    """PRD §3.6: "the number of whole calendar days from the current date to the
    stated deadline — which may be negative when the deadline has already passed —
    selects a tier: five days or fewer contributes 50 points; more than five but at
    most fourteen days contributes 30 points; more than fourteen but at most thirty
    days contributes 15 points; and more than thirty days contributes nothing."

    Design: Difficulty/boundary_precision_check/eviction_day5_vs_day6
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, eviction_notice_date="2026-08-06")
    # d = 5: the <= 5 tier is inclusive -> +50, ELEVATED (>= 40).
    assert case["priority_score"] == 50
    assert case["urgency_tier"] == "ELEVATED"


def test_eviction_day6_drops_tier(api):
    """PRD §3.6: "the number of whole calendar days from the current date to the
    stated deadline — which may be negative when the deadline has already passed —
    selects a tier: five days or fewer contributes 50 points; more than five but at
    most fourteen days contributes 30 points; more than fourteen but at most thirty
    days contributes 15 points; and more than thirty days contributes nothing."
    PRD §3.6: "Boundaries are inclusive-up — exactly 70 is `CRITICAL`, exactly 40 is
    `ELEVATED`, exactly 39 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/eviction_day5_vs_day6
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, eviction_notice_date="2026-08-07")
    # d = 6 falls to the (5, 14] tier -> +30, below ELEVATED.
    assert case["priority_score"] == 30
    assert case["urgency_tier"] == "STANDARD"


def test_tier_boundary_40(api):
    """PRD §3.6: "The **urgency tier** maps the score immediately, in the same
    request: a score of at least 70 is `CRITICAL`, at least 40 is `ELEVATED`, and
    anything lower is `STANDARD`. Boundaries are inclusive-up — exactly 70 is
    `CRITICAL`, exactly 40 is `ELEVATED`, exactly 39 is `STANDARD`."

    Design: Corner/calculations/tier_boundary_40
    """
    bundle = setup_hotline()
    caller, session_a = start_active_session(bundle)
    case_a = open_case(
        bundle, caller, session_a,
        eviction_notice_date="2026-08-07",  # d=6 -> +30
        deposit_amount_cents=200000, monthly_rent_cents=150000,  # +10
    )
    # 30 + 10 = 40 -> ELEVATED at the inclusive boundary.
    assert case_a["priority_score"] == 40
    assert case_a["urgency_tier"] == "ELEVATED"

    _, session_b = start_active_session(bundle, caller=caller)
    case_b = open_case(bundle, caller, session_b, eviction_notice_date="2026-08-07")
    assert case_b["priority_score"] == 30
    assert case_b["urgency_tier"] == "STANDARD"


def test_patch_case_recomputes_provisional(api):
    """PRD §3.6: "Fact edits arrive through a case update carrying any subset of the
    fact fields; each edit recomputes score, tier, cadence, and exposure under the
    variant currently in force and increments the case's `version`."

    Design: Corner/endpoints/patch_case_recomputes_provisional
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    assert case["priority_score"] == 0
    assert case["urgency_tier"] == "STANDARD"
    assert case["version"] == 1

    patched = validate_success(api.update_case(
        case["id"], {"eviction_notice_date": "2026-08-06"},
        bundle["worker_headers"],
    ))
    assert patched["priority_score"] == 50, "d=5 <= 5 -> +50 in the same request"
    assert patched["urgency_tier"] == "ELEVATED"
    assert patched["version"] == 2
    assert patched["score_variant"] == "PROVISIONAL"


def test_case_create_extra_field_rejected(api):
    """PRD §2.10: "Required fields must be present, unknown payload fields are
    rejected, enums must be members, and types must match — otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/case_create_extra_field_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    payload = create_case_payload(
        caller["id"], session["id"], bundle["jurisdiction"]["id"], "EVICTION"
    )
    payload["priority_score"] = 999  # computed fields are never client-writable
    resp = api.create_case(payload, bundle["worker_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_case_in_progress_without_script_rejected(api):
    """PRD §3.7: "Moving a case `OPEN` → `IN_PROGRESS` requires a `PUBLISHED` rights
    script for the case's (`jurisdiction_id`, `issue_category`) pair — there is no
    counseling without current, accurate information, and its absence is rejected
    with `ERR_SCRIPT_NOT_PUBLISHED`."
    PRD §3.2: "A `HotlineSupervisor` may retire a `PUBLISHED` script, which runs the
    same second and third cascade links — linked `CURRENT` resources become
    `OUTDATED` and their `PROPOSED` referrals cancel with `SCRIPT_OUTDATED` — while
    call sessions that already pinned the script keep their `pinned_script_id`
    unchanged, grandfathered for audit."

    Design: Corner/state_machines/case_in_progress_without_script_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)

    validate_success(api.transition_script(
        bundle["script"]["id"], {"to_status": "RETIRED"},
        TEST_USERS["supervisor_headers"],
    ))
    resp = api.transition_case(
        case["id"], {"to_status": "IN_PROGRESS"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_SCRIPT_NOT_PUBLISHED)
    assert get_case(bundle, case["id"])["status"] == "OPEN"

    session_now = get_session(bundle, session["id"])
    assert session_now["pinned_script_id"] == bundle["script"]["id"], (
        "retirement does not rewrite the already-pinned script"
    )


def test_case_closed_lockdown(api):
    """PRD §3.6: "Edits to a `CLOSED` case are rejected with `ERR_INVALID_STATE`,
    with one carve-out: a `legal_hold`-only toggle is permitted on a closed case,
    because litigation holds legitimately attach after closure."
    PRD §3.7: "Closure is supervisor-only in both its forms: `RESOLVED` → `CLOSED`
    after resolution, and `OPEN` → `CLOSED` as a no-merit close; either way
    `closed_at` is stamped from the logical clock, anchoring retention eligibility."

    Design: Corner/state_machines/case_closed_lockdown
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    move_case_in_progress(bundle, case)
    transition_case_ok(bundle, case["id"], "RESOLVED")
    closed = transition_case_ok(
        bundle, case["id"], "CLOSED", headers=TEST_USERS["supervisor_headers"]
    )
    assert closed["status"] == "CLOSED"
    assert_instant_equal(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

    resp = api.update_case(
        case["id"], {"eviction_notice_date": "2026-08-06"},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
