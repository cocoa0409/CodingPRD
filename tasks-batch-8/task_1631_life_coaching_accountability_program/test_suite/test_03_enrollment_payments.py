"""Enrollment creation, installment schedules, activation, and the payment
dimension's delinquency cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_enrollment,
    create_client,
    create_coach,
    create_fit_approved_enrollment,
    create_tier,
    get_enrollment,
    get_success_data,
    make_client_headers,
    reset_clock,
    set_clock,
    setup_active_enrollment,
    setup_coach_pair,
    simulate_payment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["practice_manager_headers"]


def _installments(api, enrollment_id):
    resp = api.list_enrollment_installments(enrollment_id, PM)
    data, _meta = validate_paginated(resp)
    return sorted(data, key=lambda r: r["sequence_no"])


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / installment_schedule_remainder_to_last
# ---------------------------------------------------------------------------

def _setup_three_installment_enrollment(api):
    """Coach pair + client + PKG-8 tier + fit-approved enrollment with
    installment_count 3, still PENDING_PAYMENT."""
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    enrollment = create_fit_approved_enrollment(
        client, coach_a, coach_b, tier, installment_count=3)
    return client, tier, enrollment


def test_installment_schedule_remainder_to_last_amounts(api):
    """PRD §3.3: "The per-installment base is the pinned price divided by the
    number of installments, rounded down to a whole cent; the remainder — the
    price minus the base multiplied by the installment count — lands entirely
    on the final installment, so every installment but the last carries
    exactly the base."

    Design: Difficulty/combinatorial_formula/installment_schedule_remainder_to_last
    """
    _client, _tier, enrollment = _setup_three_installment_enrollment(api)
    rows = _installments(api, enrollment["id"])
    assert [r["amount_cents"] for r in rows] == [26666, 26666, 26668], (
        f"80000/3 must split as base 26666 with the +2 remainder on the LAST "
        f"installment; got {[r['amount_cents'] for r in rows]}"
    )
    assert [r["sequence_no"] for r in rows] == [1, 2, 3]


def test_installment_schedule_remainder_total_conserved(api):
    """PRD §3.3: "The per-installment base is the pinned price divided by the
    number of installments, rounded down to a whole cent; the remainder — the
    price minus the base multiplied by the installment count — lands entirely
    on the final installment". PRD §2.6: "derived totals are exact integer
    sums of stored rows".

    Design: Difficulty/combinatorial_formula/installment_schedule_remainder_to_last
    """
    _client, _tier, enrollment = _setup_three_installment_enrollment(api)
    rows = _installments(api, enrollment["id"])
    assert sum(r["amount_cents"] for r in rows) == 80000, \
        "the schedule total must equal the pinned price basis exactly"
    last = rows[-1]
    assert last["sequence_no"] == 3 and last["amount_cents"] == 26668
    assert all(r["installment_status"] == "PENDING" for r in rows)


def test_installment_due_dates_step_30_days_from_activation(api):
    """PRD §3.3: "its `due_on` resolves only at activation: the first
    installment falls due on the activation date itself, and each later
    installment falls due thirty days after its predecessor."
    PRD §3.3: "When the enrollment still stands `PENDING_PAYMENT` and the
    successful payment satisfies the first installment (which, on a
    pay-in-full plan, is the entire price), activation fires:
    `lifecycle_status` becomes `ACTIVE`, `activated_at` is stamped with the
    current time, installment one stands `PAID`, and `paid_cents` — the
    running sum of `PAID` installment amounts — is recomputed, with the
    enrollment's `version` advancing."

    Design: Corner/calculations/installment_due_dates_step_30_days_from_activation
    """
    _client, _tier, enrollment = _setup_three_installment_enrollment(api)
    enrollment = activate_enrollment(enrollment["id"], "2026-08-03T00:00:00Z")
    assert enrollment["lifecycle_status"] == "ACTIVE"
    rows = _installments(api, enrollment["id"])
    assert [r["due_on"] for r in rows] == ["2026-08-03", "2026-09-02", "2026-10-02"], \
        f"installment k is due activation + (k-1)*30 days; got {[r['due_on'] for r in rows]}"
    assert rows[0]["installment_status"] == "PAID"
    assert rows[1]["installment_status"] == "PENDING"
    assert rows[2]["installment_status"] == "PENDING"
    assert enrollment["paid_cents"] == 26666


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / enrollment_parallel_dims_delinquency_cycle
# ---------------------------------------------------------------------------

def _setup_installment_plan_active(api):
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    enrollment = create_fit_approved_enrollment(
        client, coach_a, coach_b, tier, installment_count=3)
    enrollment = activate_enrollment(enrollment["id"], "2026-08-03T00:00:00Z")
    return client, enrollment


def test_overdue_installment_flips_payment_status_only(api):
    """PRD §3.3: "The payment dimension runs in parallel to the lifecycle, and
    it cycles. When any `PENDING` installment's `due_on` falls behind the
    current UTC date, the enrollment turns `DELINQUENT` and the overdue
    installments turn `LATE`, with the enrollment's `version` advancing."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_dims_delinquency_cycle
    """
    _client, enrollment = _setup_installment_plan_active(api)
    set_clock("2026-09-03T09:00:00Z")  # installment 2 (due 2026-09-02) overdue
    data = get_enrollment(enrollment["id"])
    assert data["lifecycle_status"] == "ACTIVE"
    assert data["payment_status"] == "DELINQUENT"


def test_settling_late_installments_closes_delinquency_cycle(api):
    """PRD §3.3: "A successful settlement of all `LATE` installments returns
    the dimension to `CURRENT`, marks those installments `PAID`, and
    recomputes `paid_cents`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_dims_delinquency_cycle
    """
    _client, enrollment = _setup_installment_plan_active(api)
    set_clock("2026-09-03T09:00:00Z")
    data = get_enrollment(enrollment["id"])
    assert data["payment_status"] == "DELINQUENT"
    validate_success(
        api.simulate_payment(simulate_payment_payload(enrollment["id"]), ADMIN))
    data = get_enrollment(enrollment["id"])
    assert data["lifecycle_status"] == "ACTIVE"
    assert data["payment_status"] == "CURRENT", \
        "settlement returns the payment dimension to CURRENT while lifecycle stays ACTIVE"


# ---------------------------------------------------------------------------
# Corner instances: capacity, payment-plan shape, tier retirement, computed
# fields on creation.
# ---------------------------------------------------------------------------

def test_activation_beyond_coach_capacity_rejected(api):
    """PRD §3.3: "Coach capacity is enforced at two points — here at creation
    and again at activation: when the coach already carries
    `max_concurrent_clients` enrollments in `ACTIVE` lifecycle, the request
    fails with `ERR_COACH_CAPACITY_FULL`."

    Design: Corner/validations/activation_beyond_coach_capacity_rejected
    """
    coach_a, coach_b = setup_coach_pair()
    coach_cap = create_coach(max_concurrent_clients=1)
    client_1 = create_client()
    client_2 = create_client()
    tier = create_tier()
    enr_1 = create_fit_approved_enrollment(
        client_1, coach_cap, coach_b, tier,
        scheduled_start="2026-08-02T09:00:00Z", duration_minutes=30)
    enr_2 = create_fit_approved_enrollment(
        client_2, coach_cap, coach_b, tier,
        scheduled_start="2026-08-02T10:00:00Z", duration_minutes=30)
    activate_enrollment(enr_1["id"], "2026-08-03T00:00:00Z")
    resp = api.simulate_payment(simulate_payment_payload(enr_2["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_COACH_CAPACITY_FULL)
    data = get_enrollment(enr_2["id"])
    assert data["lifecycle_status"] == "PENDING_PAYMENT"


def test_installment_count_above_tier_allowance_rejected(api):
    """PRD §3.3: "The requested `installment_count` must sit between 1 and the
    tier's `installment_count_allowed` inclusive, else
    `ERR_PAYMENT_PLAN_INVALID`."

    Design: Corner/validations/installment_count_above_tier_allowance_rejected
    """
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    from test_helpers import complete_discovery_call_with_fit, create_enrollment_payload
    fa = complete_discovery_call_with_fit(client, coach_a, coach_b)
    resp = api.create_enrollment(
        create_enrollment_payload(
            client["id"], coach_a["id"], tier["id"], fa["_call"]["id"],
            installment_count=4),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_PLAN_INVALID)


def test_retire_tier_blocks_new_enrollment(api):
    """PRD §3.3: "a `PlatformAdmin` may later retire it, moving `tier_status`
    to `RETIRED`, after which it refuses new enrollments with
    `ERR_TIER_RETIRED` while enrollments already running on it are untouched."

    Design: Corner/consistency_model/retire_tier_blocks_new_enrollment
    """
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier(
        tier_code="PKG-OLD", session_count=4, price_cents=40000,
        duration_days=28, installment_count_allowed=1, reschedule_cap=1)
    from test_helpers import complete_discovery_call_with_fit, create_enrollment_payload
    fa = complete_discovery_call_with_fit(client, coach_a, coach_b)
    resp = api.retire_program_tier(tier["id"], ADMIN)
    retired = validate_success(resp)
    assert retired["tier_status"] == "RETIRED"
    resp = api.create_enrollment(
        create_enrollment_payload(
            client["id"], coach_a["id"], tier["id"], fa["_call"]["id"],
            installment_count=1),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIER_RETIRED)


def test_enrollment_creation_computed_fields_input_ignored(api):
    """PRD §2.10: "Derived fields are never accepted from clients."
    PRD §3.3: "A new enrollment opens in `PENDING_PAYMENT` with
    `payment_status` `CURRENT` and `activated_at` unset."
    PRD §3.3: "It copies `sessions_total` from the tier's `session_count`
    and pins `sessions_total_price_basis` to the tier's `price_cents` at
    that moment; the pinned basis is what installment schedules and
    pro-rata refund quotes divide against, immune to later tier price
    edits."

    Design: Corner/entities/enrollment_creation_computed_fields_input_ignored
    """
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    tier = create_tier()
    from test_helpers import complete_discovery_call_with_fit
    fa = complete_discovery_call_with_fit(client, coach_a, coach_b)
    payload = {
        "client_id": client["id"],
        "coach_id": coach_a["id"],
        "program_tier_id": tier["id"],
        "discovery_call_id": fa["_call"]["id"],
        "installment_count": 1,
        "sessions_consumed": 99,
        "paid_cents": 999999,
    }
    resp = api.create_enrollment(payload, make_client_headers(client["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["sessions_consumed"] == 0
    assert data["paid_cents"] == 0
    assert data["lifecycle_status"] == "PENDING_PAYMENT"
    assert data["payment_status"] == "CURRENT"
    assert data["sessions_total"] == 8
    assert data["sessions_total_price_basis"] == 80000
    assert data["activated_at"] is None
