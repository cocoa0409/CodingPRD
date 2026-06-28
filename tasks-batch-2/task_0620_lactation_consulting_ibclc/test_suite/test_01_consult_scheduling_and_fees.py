"""Consult scheduling: dual-variant fee, reschedule loop, calendar conflicts,
client-active precondition, and immediate fee visibility.

Depth instances (queue A): dual_variant_calc, non_linear_state_machine,
cross_entity_state_dependency, resource_temporal_overlap; plus corner-design
breadth for the sliding-scale calculation and consistency model.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    create_completed_consult,  # noqa: F401  (re-exported convenience)
    setup_practice_with_consultant_and_client, create_consult, create_tier,
    create_package, setup_suspended_client,
    create_consultant, create_client,
    create_practice, set_clock,
    create_consult_payload,
    TEST_USERS,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── dual_variant_calc / consult_fee_self_pay_vs_package_redemption ──────────

def test_self_pay_consult_gets_sliding_scale_discounted_fee(api):
    """PRD §3.3: "When `pay_method` is `SELF_PAY`, the sliding-scale fee calculation
    runs at scheduling time and sets `fee_cents`; the package credit balance is
    untouched."
    PRD §3.3: "`fee_cents` is the consultant's `standard_rate_cents` multiplied by
    the quantity one hundred minus the discount percent, divided by one hundred,
    with the result rounded half-up to a whole number of cents."

    A SELF_PAY consult at rate 20000 with a qualifying 40% tier yields
    20000 * (100 - 40) / 100 = 12000.

    Design: Difficulty/dual_variant_calc/consult_fee_self_pay_vs_package_redemption
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"standard_rate_cents": 20000},
        client_overrides={"household_income_cents": 4800000})
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    create_tier(prac["id"], "TIER_A", income_ceiling_cents=5000000, discount_pct=40)

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z",
        consult_type="TELEHEALTH", pay_method="SELF_PAY"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["fee_cents"] == 12000, f"expected 12000, got {consult['fee_cents']}"


def test_package_consult_fee_zero_and_credit_not_yet_redeemed(api):
    """PRD §3.3: "When `pay_method` is `PACKAGE`, `fee_cents` is set to 0 because a
    package credit will stand in for payment, and the sliding scale is never
    evaluated; the credit itself is not committed at scheduling but at completion."

    The PACKAGE consult charges fee_cents == 0 and package_credit_redeemed stays
    false at scheduling time, distinct from the SELF_PAY discounted-fee branch.

    Design: Difficulty/dual_variant_calc/consult_fee_self_pay_vs_package_redemption
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"standard_rate_cents": 20000},
        client_overrides={"household_income_cents": 4800000})
    prac, cons = ctx["practice"], ctx["consultant"]
    create_tier(prac["id"], "TIER_A", income_ceiling_cents=5000000, discount_pct=40)
    pkg = create_package(prac["id"], "THREE_VISIT", included_visits=3, price_cents=30000)
    pkg_client = create_client(prac["id"], household_income_cents=4800000,
                               package_id=pkg["id"])

    resp = api.create_consult(create_consult_payload(
        prac["id"], pkg_client["id"], cons["id"],
        "2026-06-10T17:00:00Z", "2026-06-10T18:00:00Z",
        consult_type="TELEHEALTH", pay_method="PACKAGE"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["fee_cents"] == 0, f"expected 0, got {consult['fee_cents']}"
    assert consult["package_credit_redeemed"] is False, (
        "package credit must not be committed at scheduling")


# ─── non_linear_state_machine / consult_reschedule_cycle_loop ───────────────

def test_reschedule_twice_returns_to_scheduled_with_count_two(api):
    """PRD §3.5: "A reschedule passes through a brief holding state, advancing
    `SCHEDULED → RESCHEDULED` and then, within the same request, automatically
    re-confirming `RESCHEDULED → SCHEDULED`."
    PRD §3.5: "Its side effects replace `scheduled_start_utc` and
    `scheduled_end_utc` with the new values and add one to `reschedule_count`."

    Two reschedules loop back to SCHEDULED each time, leaving reschedule_count == 2.

    Design: Difficulty/non_linear_state_machine/consult_reschedule_cycle_loop
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    r1 = api.reschedule_consult(consult["id"], {
        "scheduled_start_utc": "2026-06-11T15:00:00Z",
        "scheduled_end_utc": "2026-06-11T16:00:00Z"}, FRONT_DESK)
    validate_success(r1, 200)
    r2 = api.reschedule_consult(consult["id"], {
        "scheduled_start_utc": "2026-06-12T15:00:00Z",
        "scheduled_end_utc": "2026-06-12T16:00:00Z"}, FRONT_DESK)
    after = validate_success(r2, 200)

    assert after["status"] == "SCHEDULED", f"expected SCHEDULED, got {after['status']}"
    assert after["reschedule_count"] == 2, (
        f"expected reschedule_count 2, got {after['reschedule_count']}")


def test_reschedule_replaces_window(api):
    """PRD §3.5: "Its side effects replace `scheduled_start_utc` and
    `scheduled_end_utc` with the new values and add one to `reschedule_count`."

    After one reschedule the consult carries the new window and reschedule_count 1.

    Design: Difficulty/non_linear_state_machine/consult_reschedule_cycle_loop
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    resp = api.reschedule_consult(consult["id"], {
        "scheduled_start_utc": "2026-06-11T15:00:00Z",
        "scheduled_end_utc": "2026-06-11T16:00:00Z"}, FRONT_DESK)
    after = validate_success(resp, 200)
    assert after["scheduled_start_utc"][:19] == "2026-06-11T15:00:00"
    assert after["reschedule_count"] == 1


# ─── cross_entity_state_dependency / consult_schedule_requires_client_active ─

def test_schedule_consult_for_suspended_client_rejected(api):
    """PRD §3.3: "The target client must be `ACTIVE`; a suspended client cannot have
    new consults booked and the attempt is rejected with `ERR_CLIENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/consult_schedule_requires_client_active
    """
    ctx = setup_suspended_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-20T15:00:00Z", "2026-06-20T16:00:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value)


def test_suspended_client_status_is_suspended_before_booking(api):
    """PRD §3.6: "when the freshly incremented strike count reaches three or more,
    the client's `status` is set to `SUSPENDED`. The boundary is inclusive — the
    third strike suspends, while two strikes do not."

    Confirms the cross-entity precondition's premise: the client reached SUSPENDED,
    so a later booking is governed by ERR_CLIENT_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/consult_schedule_requires_client_active
    """
    ctx = setup_suspended_client()
    client = get_success_data(api.get_client(
        ctx["client"]["id"], TEST_USERS["front_desk_headers"]))
    assert client["status"] == "SUSPENDED", f"expected SUSPENDED, got {client['status']}"


# ─── resource_temporal_overlap / consultant_in_home_travel_buffer_overlap ───

def test_in_home_consult_buffer_overlap_rejected(api):
    """PRD §3.4: "An `IN_HOME` consult occupies the half-open interval running from
    its start minus the consultant's `travel_buffer_minutes` up to (but not
    including) its end plus that same buffer".
    PRD §3.4: "if such an overlap exists the booking is rejected with
    `ERR_CONSULTANT_DOUBLE_BOOKED`."

    Existing IN_HOME 10:00-11:00 with a 60-min buffer occupies 09:00-12:00; a
    second IN_HOME at 11:30-12:30 (occupying 10:30-13:30) overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/consultant_in_home_travel_buffer_overlap
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"travel_buffer_minutes": 60})
    prac, cons, client_a = ctx["practice"], ctx["consultant"], ctx["client"]
    client_b = create_client(prac["id"], full_name="Parent B")
    create_consult(prac["id"], client_a["id"], cons["id"],
                   "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z", consult_type="IN_HOME")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client_b["id"], cons["id"],
        "2026-06-10T11:30:00Z", "2026-06-10T12:30:00Z", consult_type="IN_HOME"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CONSULTANT_DOUBLE_BOOKED.value)


# ─── resource_temporal_overlap / client_bare_interval_adjacency_allowed ─────

def test_client_adjacent_consults_do_not_conflict(api):
    """PRD §3.4: "Because the interval is half-open, two adjacent appointments that
    merely touch at an instant — one ending exactly when the next begins — do not
    conflict."

    Two TELEHEALTH consults for the same client at 15:00-16:00 and 16:00-17:00
    (on distinct consultants) are adjacent and both succeed.

    Design: Difficulty/resource_temporal_overlap/client_bare_interval_adjacency_allowed
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons1, client = ctx["practice"], ctx["consultant"], ctx["client"]
    cons2 = create_consultant(prac["id"], full_name="Bea IBCLC")
    create_consult(prac["id"], client["id"], cons1["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons2["id"],
        "2026-06-10T16:00:00Z", "2026-06-10T17:00:00Z"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["status"] == "SCHEDULED", f"expected SCHEDULED, got {consult['status']}"


def test_telehealth_consults_back_to_back_on_consultant_succeed(api):
    """PRD §3.4: "a `PRENATAL` or `TELEHEALTH` consult occupies only its bare
    half-open interval from start up to (but not including) end."
    PRD §3.4: "Two intervals overlap exactly when the first one's padded start is
    strictly before the second one's padded end and the second one's padded start is
    strictly before the first one's padded end".

    Because TELEHEALTH reserves no travel buffer, two back-to-back TELEHEALTH
    consults on the SAME consultant (15:00-16:00 then 16:00-17:00) merely touch at
    16:00 and both succeed — the buffer-padded conflict the IN_HOME case triggers
    does not arise.

    Design: Difficulty/resource_temporal_overlap/consultant_in_home_travel_buffer_overlap
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"travel_buffer_minutes": 60})
    prac, cons, client_a = ctx["practice"], ctx["consultant"], ctx["client"]
    client_b = create_client(prac["id"], full_name="Parent B")
    create_consult(prac["id"], client_a["id"], cons["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z", consult_type="TELEHEALTH")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client_b["id"], cons["id"],
        "2026-06-10T16:00:00Z", "2026-06-10T17:00:00Z", consult_type="TELEHEALTH"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["status"] == "SCHEDULED", f"expected SCHEDULED, got {consult['status']}"


def test_client_overlapping_consults_conflict(api):
    """PRD §3.4: "The new consult's bare half-open interval from `scheduled_start_utc`
    up to (but not including) `scheduled_end_utc` must not overlap any non-terminal
    consult for the same client".
    PRD §3.4: "A genuine overlap is rejected with `ERR_CLIENT_DOUBLE_BOOKED`."

    Complement to the adjacency case: a genuinely overlapping pair on the client
    axis (15:00-16:00 then 15:30-16:30, on distinct consultants) does conflict, so
    sharing an instant is the only non-conflicting case.

    Design: Difficulty/resource_temporal_overlap/client_bare_interval_adjacency_allowed
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons1, client = ctx["practice"], ctx["consultant"], ctx["client"]
    cons2 = create_consultant(prac["id"], full_name="Bea IBCLC")
    create_consult(prac["id"], client["id"], cons1["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons2["id"],
        "2026-06-10T15:30:00Z", "2026-06-10T16:30:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CLIENT_DOUBLE_BOOKED.value)


# ─── Corner: calculations / sliding_scale_no_qualifying_tier_full_rate ──────

def test_sliding_scale_no_qualifying_tier_full_rate(api):
    """PRD §3.3: "If no tier qualifies, the discount percent is 0 and the client
    pays the full rate."

    A SELF_PAY consult for a client (income 9900000) above every tier ceiling
    (5000000) pays the full standard rate 20000.

    Design: Corner/calculations/sliding_scale_no_qualifying_tier_full_rate
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"standard_rate_cents": 20000},
        client_overrides={"household_income_cents": 9900000})
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    create_tier(prac["id"], "TIER_A", income_ceiling_cents=5000000, discount_pct=40)

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["fee_cents"] == 20000, f"expected 20000, got {consult['fee_cents']}"


# ─── Corner: calculations / sliding_scale_income_equals_ceiling_inclusive ───

def test_sliding_scale_income_equal_to_ceiling_qualifies(api):
    """PRD §3.3: "It gathers every `SlidingScaleTier` belonging to the consult's
    practice whose `income_ceiling_cents` is greater than or equal to the client's
    `household_income_cents`".
    PRD §3.3: "the system picks the tier with the smallest `income_ceiling_cents`
    (the tightest matching bracket)".

    Income exactly 9000000 equals TIER_B ceiling 9000000 (>= inclusive); TIER_B's
    20% discount applies: 20000 * 80 / 100 = 16000.

    Design: Corner/calculations/sliding_scale_income_equals_ceiling_inclusive
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"standard_rate_cents": 20000},
        client_overrides={"household_income_cents": 9000000})
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    create_tier(prac["id"], "TIER_A", income_ceiling_cents=5000000, discount_pct=40)
    create_tier(prac["id"], "TIER_B", income_ceiling_cents=9000000, discount_pct=20)

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["fee_cents"] == 16000, f"expected 16000, got {consult['fee_cents']}"


# ─── Corner: consistency_model / immediate_fee_visible_in_create_response ───

def test_fee_present_in_create_response_immediately(api):
    """PRD §3.3: "When `pay_method` is `SELF_PAY`, the sliding-scale fee calculation
    runs at scheduling time and sets `fee_cents`".

    The computed fee_cents (12000 for a 40% tier on rate 20000) is in the same
    POST /consults response body — no second GET needed.

    Design: Corner/consistency_model/immediate_fee_visible_in_create_response
    """
    ctx = setup_practice_with_consultant_and_client(
        consultant_overrides={"standard_rate_cents": 20000},
        client_overrides={"household_income_cents": 4800000})
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    create_tier(prac["id"], "TIER_A", income_ceiling_cents=5000000, discount_pct=40)

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"), FRONT_DESK)
    consult = validate_success(resp, 201)
    assert consult["fee_cents"] == 12000, (
        f"fee must be present immediately; got {consult.get('fee_cents')}")


# ─── Corner: errors / client_double_booked_returns_409 ──────────────────────

def test_client_double_booked_overlap_rejected(api):
    """PRD §3.4: "The new consult's bare half-open interval from `scheduled_start_utc`
    up to (but not including) `scheduled_end_utc` must not overlap any non-terminal
    consult for the same client".
    PRD §3.4: "A genuine overlap is rejected with `ERR_CLIENT_DOUBLE_BOOKED`."

    Client's existing 15:00-16:00 consult overlaps a new 15:30-16:30 (on a distinct
    consultant) -> ERR_CLIENT_DOUBLE_BOOKED.

    Design: Corner/errors/client_double_booked_returns_409
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons1, client = ctx["practice"], ctx["consultant"], ctx["client"]
    cons2 = create_consultant(prac["id"], full_name="Bea IBCLC")
    create_consult(prac["id"], client["id"], cons1["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons2["id"],
        "2026-06-10T15:30:00Z", "2026-06-10T16:30:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CLIENT_DOUBLE_BOOKED.value)
