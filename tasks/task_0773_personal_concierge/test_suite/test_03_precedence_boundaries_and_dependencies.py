"""Validation precedence, numeric boundaries, cross-entity state gates, and
temporal-overlap rules.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
Corner queue: validations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_membership,
    setup_time_logged,
    intake_request,
    accept_request,
    get_open_cycle,
    create_vendor,
    propose_engagement,
    confirm_engagement,
    api_client,
)

AM = TEST_USERS["account_manager_headers"]
AGENT = TEST_USERS["concierge_agent_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


# ─── Difficulty/priority_pair_validation_conflict/membership_state_beats_category_eligibility ─
def test_paused_membership_beats_travel_eligibility(api):
    """PRD §3.3: "Intake requires the membership to be `ACTIVE`; against a non-active
    membership it is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409)."
    PRD §3.3: "Between these two state checks, the active-membership requirement is
    evaluated before category eligibility."

    Design: Difficulty/priority_pair_validation_conflict/membership_state_beats_category_eligibility
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    api.pause_membership(ctx["ms_id"], AM)
    # STANDARD is ineligible for TRAVEL AND the membership is PAUSED; state check wins.
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "TRAVEL", "title": "flight"}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_paused_membership_beats_gift_eligibility(api):
    """PRD §3.3: "Intake requires the membership to be `ACTIVE`; against a non-active
    membership it is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409)."
    PRD §3.3: "Between these two state checks, the active-membership requirement is
    evaluated before category eligibility."

    Design: Difficulty/priority_pair_validation_conflict/membership_state_beats_category_eligibility
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    api.pause_membership(ctx["ms_id"], AM)
    # STANDARD is ineligible for GIFT AND the membership is PAUSED; state check still wins.
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "GIFT", "title": "present"}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


# ─── Difficulty/boundary_precision_check/overage_boundary_at_included_minutes ─
def test_overage_zero_at_exactly_included_minutes(api):
    """PRD §3.5: "The overage minutes are the consumed minutes minus the cycle's
    `included_minutes`, floored at zero, so that consuming exactly the included allotment
    yields zero overage while consuming one minute beyond it yields the first overage minute."

    Design: Difficulty/boundary_precision_check/overage_boundary_at_included_minutes
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=600)
    cycle = validate_success(api.get_billing_cycle(s["cycle_id"], AM))
    assert cycle["consumed_minutes"] == 600, f"expected 600, got {cycle['consumed_minutes']}"
    assert cycle["overage_minutes"] == 0, f"expected 0, got {cycle['overage_minutes']}"
    assert cycle["overage_charge_cents"] == 0, f"expected 0, got {cycle['overage_charge_cents']}"


def test_overage_first_minute_just_beyond_included(api):
    """PRD §3.5: "The overage minutes are the consumed minutes minus the cycle's
    `included_minutes`, floored at zero, so that consuming exactly the included allotment
    yields zero overage while consuming one minute beyond it yields the first overage minute."

    Design: Difficulty/boundary_precision_check/overage_boundary_at_included_minutes
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=601)
    cycle = validate_success(api.get_billing_cycle(s["cycle_id"], AM))
    assert cycle["consumed_minutes"] == 601, f"expected 601, got {cycle['consumed_minutes']}"
    assert cycle["overage_minutes"] == 1, f"expected 1, got {cycle['overage_minutes']}"


# ─── Difficulty/boundary_precision_check/satisfaction_empty_set_returns_null ─
def test_satisfaction_summary_null_with_no_ratings(api):
    """PRD §3.8: "When a membership has no ratings at all — a `rating_count` of zero — both
    `lifetime_average` and `current_standing` are null, and the stored `satisfaction_score`
    is null."

    Design: Difficulty/boundary_precision_check/satisfaction_empty_set_returns_null
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    data = validate_success(api.get_membership_satisfaction(ctx["ms_id"], AM))
    assert data["rating_count"] == 0, f"expected 0, got {data['rating_count']}"
    assert data["lifetime_average"] is None, f"expected null, got {data['lifetime_average']}"
    assert data["current_standing"] is None, f"expected null, got {data['current_standing']}"


def test_membership_satisfaction_score_null_with_no_ratings(api):
    """PRD §3.8: "When a membership has no ratings at all — a `rating_count` of zero — both
    `lifetime_average` and `current_standing` are null, and the stored `satisfaction_score`
    is null."

    Design: Difficulty/boundary_precision_check/satisfaction_empty_set_returns_null
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    ms = validate_success(api.get_membership(ctx["ms_id"], AM))
    assert ms["satisfaction_score"] is None, f"expected null, got {ms['satisfaction_score']}"


# ─── Difficulty/cross_entity_state_dependency/request_intake_requires_membership_active ─
def test_intake_rejected_on_paused_membership(api):
    """PRD §3.3: "Intake requires the membership to be `ACTIVE`; against a non-active
    membership it is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_intake_requires_membership_active
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    api.pause_membership(ctx["ms_id"], AM)
    # ERRAND is eligible for any tier, isolating the membership-active dependency.
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "ERRAND", "title": "task"}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_intake_rejected_on_cancelled_membership(api):
    """PRD §3.3: "Intake requires the membership to be `ACTIVE`; against a non-active
    membership it is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_intake_requires_membership_active
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    api.cancel_membership(ctx["ms_id"], AM)  # no active requests → cancellation succeeds
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "ERRAND", "title": "task"}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


# ─── Difficulty/cross_entity_state_dependency/engagement_confirm_requires_vendor_active ─
def test_confirm_rejected_when_vendor_suspended_markup(api):
    """PRD §3.6: "Confirmation requires the vendor to be `ACTIVE`, or it is rejected with
    `ERR_VENDOR_INACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/engagement_confirm_requires_vendor_active
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="reserve")
    eng = propose_engagement(sr["id"], vendor["id"], "MARKUP", [1000],
                             "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z", markup_pct=0.10)
    api.suspend_vendor(vendor["id"], AM)
    resp = api.confirm_engagement(eng["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_VENDOR_INACTIVE.value)


def test_confirm_rejected_when_vendor_suspended_pass_through(api):
    """PRD §3.6: "Confirmation requires the vendor to be `ACTIVE`, or it is rejected with
    `ERR_VENDOR_INACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/engagement_confirm_requires_vendor_active
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="reserve")
    eng = propose_engagement(sr["id"], vendor["id"], "PASS_THROUGH", [1000],
                             "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z")
    api.suspend_vendor(vendor["id"], AM)
    resp = api.confirm_engagement(eng["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_VENDOR_INACTIVE.value)


# ─── Difficulty/resource_temporal_overlap/member_schedule_half_open_overlap ─
def test_member_schedule_true_overlap_rejected(api):
    """PRD §3.4: "Acceptance also checks for schedule collisions: no other request of the
    same membership that is currently `IN_PROGRESS` or `ON_HOLD` may have a half-open
    window overlapping the proposed one."
    PRD §3.4: "Two windows that merely touch — one ending exactly when the other begins —
    do not overlap and are allowed; any true overlap is rejected with
    `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_overlap
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    r1 = intake_request(ctx, category="ERRAND", title="r1")
    accept_request(r1["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    r2 = intake_request(ctx, category="ERRAND", title="r2")
    resp = api.accept_service_request(
        r2["id"], {"scheduled_start": "2026-03-02T09:30:00Z", "scheduled_end": "2026-03-02T10:30:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_MEMBER_SCHEDULE_CONFLICT.value)


def test_member_schedule_touching_window_allowed(api):
    """PRD §3.4: "Two windows that merely touch — one ending exactly when the other begins —
    do not overlap and are allowed; any true overlap is rejected with
    `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/member_schedule_half_open_overlap
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    r1 = intake_request(ctx, category="ERRAND", title="r1")
    accept_request(r1["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    r2 = intake_request(ctx, category="ERRAND", title="r2")
    accepted = validate_success(api.accept_service_request(
        r2["id"], {"scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"}, AGENT))
    assert accepted["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {accepted['status']}"


# ─── Difficulty/resource_temporal_overlap/vendor_buffer_closed_interval_overlap ─
def _two_booking_engagements(ctx, vendor, w1, w2):
    sr1 = intake_request(ctx, category="BOOKING", title="r1")
    e1 = propose_engagement(sr1["id"], vendor["id"], "MARKUP", [1000], w1[0], w1[1], markup_pct=0.10)
    confirm_engagement(e1["id"])
    sr2 = intake_request(ctx, category="BOOKING", title="r2")
    e2 = propose_engagement(sr2["id"], vendor["id"], "MARKUP", [1000], w2[0], w2[1], markup_pct=0.10)
    return e2


def test_vendor_buffer_conflict_within_30_minutes(api):
    """PRD §3.6: "It also enforces a vendor buffer: no other engagement of the same vendor
    already in `CONFIRMED` or `RECONCILED` may have a closed service window within 30
    minutes of this engagement's window; a collision is rejected with
    `ERR_VENDOR_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vendor_buffer_closed_interval_overlap
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    e2 = _two_booking_engagements(
        ctx, vendor,
        ("2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z"),
        ("2026-03-06T11:15:00Z", "2026-03-06T12:15:00Z"))  # 15-min gap < 30
    resp = api.confirm_engagement(e2["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_VENDOR_WINDOW_CONFLICT.value)


def test_vendor_buffer_allows_gap_beyond_30_minutes(api):
    """PRD §3.6: "It also enforces a vendor buffer: no other engagement of the same vendor
    already in `CONFIRMED` or `RECONCILED` may have a closed service window within 30
    minutes of this engagement's window; a collision is rejected with
    `ERR_VENDOR_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vendor_buffer_closed_interval_overlap
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    e2 = _two_booking_engagements(
        ctx, vendor,
        ("2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z"),
        ("2026-03-06T11:45:00Z", "2026-03-06T12:45:00Z"))  # 45-min gap > 30
    confirmed = validate_success(api.confirm_engagement(e2["id"], AGENT))
    assert confirmed["status"] == "CONFIRMED", f"expected CONFIRMED, got {confirmed['status']}"


# ─── Corner/validations/category_not_eligible_travel_for_standard_tier ──────
def test_travel_not_eligible_for_standard(api):
    """PRD §3.3: "A `TRAVEL` request requires a `vip_tier` of `GOLD` or `PLATINUM`."
    PRD §3.3: "A request whose membership tier is not eligible for its category is rejected
    with `ERR_CATEGORY_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/category_not_eligible_travel_for_standard_tier
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "TRAVEL", "title": "flight"}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_ELIGIBLE.value)


# ─── Corner/validations/passthrough_line_over_limit_returns_422 ─────────────
def test_pass_through_line_over_limit_rejected(api):
    """PRD §3.6: "Under `PASS_THROUGH`, no markup is permitted: `markup_pct` must be zero or
    absent, or the request is rejected with `ERR_MARKUP_ON_PASS_THROUGH` (HTTP 422);
    additionally, every estimated cost line must be no greater than the plan's
    `max_pass_through_cents`, or the request is rejected with
    `ERR_PASS_THROUGH_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/passthrough_line_over_limit_returns_422
    """
    ctx = setup_membership(vip_tier="GOLD", plan_kind="GOLD")  # max_pass_through 50000
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="r")
    resp = api.create_engagement(sr["id"], {
        "vendor_id": vendor["id"], "billing_mode": "PASS_THROUGH",
        "estimated_cost_lines": [60000],
        "service_start": "2026-03-06T10:00:00Z", "service_end": "2026-03-06T11:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_PASS_THROUGH_LIMIT_EXCEEDED.value)


# ─── Corner/validations/markup_on_pass_through_returns_422 ──────────────────
def test_markup_on_pass_through_rejected(api):
    """PRD §3.6: "Under `PASS_THROUGH`, no markup is permitted: `markup_pct` must be zero or
    absent, or the request is rejected with `ERR_MARKUP_ON_PASS_THROUGH` (HTTP 422);
    additionally, every estimated cost line must be no greater than the plan's
    `max_pass_through_cents`, or the request is rejected with
    `ERR_PASS_THROUGH_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/markup_on_pass_through_returns_422
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="r")
    resp = api.create_engagement(sr["id"], {
        "vendor_id": vendor["id"], "billing_mode": "PASS_THROUGH", "markup_pct": 0.10,
        "estimated_cost_lines": [1000],
        "service_start": "2026-03-06T10:00:00Z", "service_end": "2026-03-06T11:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_MARKUP_ON_PASS_THROUGH.value)


# ─── Corner/validations/accept_invalid_window_returns_400 ───────────────────
def test_accept_zero_length_window_rejected(api):
    """PRD §3.4: "The window must be valid — `scheduled_end` strictly after
    `scheduled_start` — or the accept is rejected with `ERR_INVALID_WINDOW` (HTTP 400)."

    Design: Corner/validations/accept_invalid_window_returns_400
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t")
    resp = api.accept_service_request(
        sr["id"], {"scheduled_start": "2026-03-02T09:00:00Z", "scheduled_end": "2026-03-02T09:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ─── Corner/validations/rate_non_fulfilled_request_returns_409 ──────────────
def test_rate_submitted_request_rejected(api):
    """PRD §3.8: "A rating is only permitted on a request in `FULFILLED` status; rating any
    other request is rejected with `ERR_RATING_NOT_ALLOWED` (HTTP 409)."

    Design: Corner/validations/rate_non_fulfilled_request_returns_409
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t")
    resp = api.create_rating(sr["id"], {"score": 5}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_RATING_NOT_ALLOWED.value)


# ─── Corner/validations/generate_on_non_standing_returns_422 ────────────────
def test_generate_on_non_standing_request_rejected(api):
    """PRD §3.4: "Generation is valid only on a request whose `is_standing` is true;
    invoked on a non-standing request it is rejected with `ERR_NOT_STANDING` (HTTP 422)."

    Design: Corner/validations/generate_on_non_standing_returns_422
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t", is_standing=False)
    resp = api.generate_service_request(sr["id"], {}, ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_STANDING.value)


# ─── Corner/validations/duplicate_member_email_returns_409 ──────────────────
def test_duplicate_member_email_rejected(api):
    """PRD §3.1: "The `email` is the login identity and must be unique across all members;
    a create that reuses an existing address is rejected with `ERR_DUPLICATE_EMAIL`
    (HTTP 409)."

    Design: Corner/validations/duplicate_member_email_returns_409
    """
    api.create_member({"full_name": "First", "email": "dup@x.com"}, AM)
    resp = api.create_member({"full_name": "Second", "email": "dup@x.com"}, AM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


# ─── Corner/validations/membership_create_on_pending_member_returns_409 ─────
def test_membership_create_on_pending_member_rejected(api):
    """PRD §3.1: "Activation is a prerequisite for commercial activity: no membership may be
    opened for a member who is not `ACTIVE`."
    PRD §2.8: "In particular, on membership creation the member's ACTIVE status
    (`ERR_MEMBER_NOT_ACTIVE`) is checked before the optimistic-concurrency version match
    (`ERR_STALE_MEMBER_VERSION`)."

    Design: Corner/validations/membership_create_on_pending_member_returns_409
    """
    member = validate_success(api.create_member({"full_name": "Pend", "email": "pend@x.com"}, AM),
                              expected_status=201)
    plan = validate_success(api.create_retainer_plan({
        "name": "Std", "monthly_retainer_cents": 100000, "included_hours": 5,
        "overage_rate_cents_per_hour": 6000, "default_markup_pct": 0.10,
        "max_pass_through_cents": 40000}, AM), expected_status=201)
    resp = api.create_membership(member["id"], {
        "plan_id": plan["id"], "vip_tier": "STANDARD",
        "expected_member_version": member["version"]}, AM)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)
