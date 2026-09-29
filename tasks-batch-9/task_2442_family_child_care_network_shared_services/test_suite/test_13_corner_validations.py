"""Aggregate ceilings, per-day caps and the order gates fire in."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    NETWORK_ADMIN_HEADERS,
    NOT_FOUND_UUID,
    ApiErrorId,
    active_provider,
    api_client,
    claim_line,
    contract_version,
    create_claim_payload,
    create_enrollment,
    create_enrollment_payload,
    create_food_claim_payload,
    meal_line,
    provider_with_contract,
)

# Local setup builders


def _home_with_one_private_child(capacity_slots):
    """An ACTIVE home of the given licensed capacity holding one private child."""
    ctx = active_provider(
        apply_overrides={"capacity_slots": capacity_slots},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
    )["id"]
    return ctx


def _enroll(ctx, **overrides):
    """Raw enrollment request from the home itself, returning the HTTP response."""
    return api_client.create_enrollment(
        create_enrollment_payload(ctx["provider_id"], **overrides), ctx["headers"]
    )


# Aggregate ceilings


def test_the_second_child_at_a_one_child_home_is_refused(api):
    """A licensed capacity of one is already used up, so the next enrollment is refused.

    The count of enrollments in ENROLLED or TRANSITION_PENDING status must stay strictly
    below the licensed capacity, and it is already equal to it. The refused request leaves
    exactly one enrollment on file and the projection unchanged at the single family's
    90000 cents.

    PRD: "Then the aggregate constraints: the count of the provider's enrollments in
    `ENROLLED` or `TRANSITION_PENDING` status must be strictly less than the provider's
    licensed `capacity_slots`, otherwise `ERR_CAPACITY_EXCEEDED` is returned, and the
    supplied `child_ref` must not already be in use by any non-terminal enrollment of the
    same provider, otherwise `ERR_DUPLICATE_CHILD_REF` is returned."

    Design: Corner/Validations/enrollment_beyond_capacity_returns_capacity_exceeded
    """
    ctx = _home_with_one_private_child(1)

    validate_error(
        _enroll(
            ctx,
            child_ref="CH-2",
            family_name="Brody",
            days_per_week=5,
            private_monthly_tuition_cents=90000,
            subsidy_certified=False,
        ),
        ApiErrorId.CAPACITY_EXCEEDED.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 90000


def test_the_second_child_at_a_two_child_home_is_accepted(api):
    """One below the licensed capacity the same request succeeds, proving the test is strict.

    The pre-insert count of one is strictly below the licensed two, so the enrollment is
    created in ENROLLED status. Both families now contribute their tuition, so the
    projection doubles to 180000.

    PRD: "Then the aggregate constraints: the count of the provider's enrollments in
    `ENROLLED` or `TRANSITION_PENDING` status must be strictly less than the provider's
    licensed `capacity_slots`, otherwise `ERR_CAPACITY_EXCEEDED` is returned, and the
    supplied `child_ref` must not already be in use by any non-terminal enrollment of the
    same provider, otherwise `ERR_DUPLICATE_CHILD_REF` is returned."

    Design: Corner/Validations/enrollment_one_below_capacity_succeeds
    """
    ctx = _home_with_one_private_child(2)

    created = validate_success(
        _enroll(
            ctx,
            child_ref="CH-2",
            family_name="Brody",
            days_per_week=5,
            private_monthly_tuition_cents=90000,
            subsidy_certified=False,
        ),
        201,
    )
    assert created["status"] == "ENROLLED"

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert provider["projected_monthly_revenue_cents"] == 180000


def test_two_lawful_meal_lines_can_still_break_the_daily_cap_together(api):
    """Each line carries one breakfast and one lunch, but the day totals four meals.

    Neither line on its own exceeds anything, and every individual count sits inside its
    permitted range. The cap is on the child-and-date pair, so the aggregate of two meals
    plus two meals is refused and the month is left unclaimed.

    PRD: "Per-child daily meal caps are absolute: for a single `child_ref` on a single
    `service_date`, the sum of `breakfasts` and `lunches` may not exceed two meals and
    `snacks` may not exceed one, and a violation returns `ERR_MEAL_CAP_EXCEEDED`."

    Design: Corner/Validations/meal_lines_each_valid_but_daily_cap_exceeded_in_aggregate
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "FOOD_PROGRAM"]},
    )
    create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=90000,
        subsidy_certified=False,
    )

    validate_error(
        api.create_food_claim(
            create_food_claim_payload(
                ctx["provider_id"],
                "2026-08",
                [
                    meal_line("CH-1", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1),
                    meal_line("CH-1", "2026-08-03T00:00:00Z", breakfasts=1, lunches=1),
                ],
            ),
            ctx["headers"],
        ),
        ApiErrorId.MEAL_CAP_EXCEEDED.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_provider_food_claims(ctx["provider_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_the_slot_gate_only_stops_the_subsidy_certified_child(api):
    """With the only contracted slot taken, a private child still enrolls and a subsidy one cannot.

    The private request never touches the slot ledger, so it is accepted with
    `slot_committed` false. The subsidy request needs a slot the contract does not have and
    is refused, leaving the ledger at one committed and none available and only two
    enrollments on file.

    PRD: "If that contract has no available slot left, the enrollment is refused with
    `ERR_SUBSIDY_SLOTS_EXHAUSTED`, and because this is the last check in the ladder, a
    request that is simultaneously over capacity and out of slots reports the capacity
    failure."

    Design: Corner/Validations/subsidy_slot_gate_applies_only_to_subsidy_certified_children
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 1,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )

    private = validate_success(
        _enroll(
            ctx,
            child_ref="CH-2",
            family_name="Brody",
            days_per_week=5,
            private_monthly_tuition_cents=90000,
            subsidy_certified=False,
        ),
        201,
    )
    assert private["slot_committed"] is False

    validate_error(
        _enroll(
            ctx,
            child_ref="CH-3",
            family_name="Cortez",
            days_per_week=5,
            private_monthly_tuition_cents=0,
            subsidy_certified=True,
        ),
        ApiErrorId.SUBSIDY_SLOTS_EXHAUSTED.value,
        409,
    )

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["committed_slots"] == 1
    assert contract["available_slots"] == 0

    _, meta = validate_paginated(
        api.list_enrollments({"provider_id": ctx["provider_id"]}, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2


def test_a_claim_line_naming_a_missing_enrollment_reports_the_missing_row(api):
    """The unknown foreign key is a 404, never the 422 the coherence rule would raise.

    The coherence rule can only compare providers once the enrollment row has been loaded,
    so a line naming an identifier that resolves to nothing fails the earlier existence
    check. No claim is created.

    PRD: "Every foreign key supplied in the request body exists — `provider_id`,
    `contract_id`, `substitute_id` or `requested_substitute_id`, each `enrollment_id` named
    inside claim lines, and `receiving_provider_id`."

    Design: Corner/Validations/unknown_enrollment_in_claim_line_is_caught_before_the_coherence_check
    """
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-08-01T00:00:00Z",
        },
    )
    enrollment = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )

    response = api.create_claim(
        create_claim_payload(
            ctx["contract_id"],
            "2026-08",
            [
                claim_line(enrollment["id"], 20, 0),
                claim_line(NOT_FOUND_UUID, 20, 0),
            ],
            contract_version(ctx["contract_id"]),
        ),
        ctx["headers"],
    )
    validate_error(response, ApiErrorId.ENROLLMENT_NOT_FOUND.value, 404)
    assert response.status_code != 422

    _, meta = validate_paginated(
        api.list_contract_claims(ctx["contract_id"], None, NETWORK_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0
