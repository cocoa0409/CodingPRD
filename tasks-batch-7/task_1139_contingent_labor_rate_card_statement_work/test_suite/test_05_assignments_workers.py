"""Assignment booking guards (fiscal rails, markup caps, temporal and
referential gates), tenure limits, double-booking, worker lifecycle and the
engagement-close cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_assignment,
    assert_worker,
    create_active_rate_card,
    create_assignment_payload,
    create_engagement_in_open,
    create_worker_payload,
    get_assignment,
    get_engagement,
    get_success_data,
    get_supplier,
    get_worker,
    make_supplier_coordinator_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    setup_bookable,
    setup_sow_engagement,
    setup_staffed_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]


class TestFiscalRails:
    def test_bill_above_ceiling_rejected_and_pay_below_floor_rejected(self, api):
        """PRD: "`bill_rate_cents` may not exceed the card's
        `bill_rate_ceiling_cents` — exactly equal is allowed — else
        `ERR_RATE_ABOVE_CEILING` (422)"
        PRD: "and `pay_rate_cents` must be at least the card's
        `pay_rate_floor_cents`, else `ERR_PAY_BELOW_FLOOR` (422)."
        PRD: "and within the fiscal tier the bill-rate ceiling is checked
        first, then markup, then the pay floor."

        Design: Corner/errors/rate_ceiling_and_pay_floor_violations
        """
        ctx = setup_bookable()
        payload = create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"],
        )
        over = api.create_assignment({**payload, "bill_rate_cents": 12001}, ADMIN)
        validate_error(over, ApiErrorId.ERR_RATE_ABOVE_CEILING)
        # Pay-floor probe must violate ONLY the floor guard: PRD runs the
        # fiscal tier ceiling -> markup -> pay floor, so the bill rate here
        # must stay within the markup cap (bill 5000 vs pay 4999 is ~0.02%,
        # far under the 25% cap) or the markup guard fires first.
        under = api.create_assignment(
            {**payload, "bill_rate_cents": 5000, "pay_rate_cents": 4999}, ADMIN
        )
        validate_error(under, ApiErrorId.ERR_PAY_BELOW_FLOOR)

    def test_in_range_rates_booked_with_same_offer_after_failures(self, api):
        """PRD: "A successfully booked assignment starts `PENDING`; its
        `supplier_id` is copied from the offer; the referenced offer moves
        `ACCEPTED` → `CONSUMED`; and the supplier's `offers_filled_count`
        increases by one."
        PRD: "`bill_rate_cents` may not exceed the card's
        `bill_rate_ceiling_cents` — exactly equal is allowed — else
        `ERR_RATE_ABOVE_CEILING` (422)"

        Design: Corner/errors/rate_ceiling_and_pay_floor_violations
        """
        ctx = setup_bookable()
        payload = create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"],
        )
        validate_error(
            api.create_assignment({**payload, "bill_rate_cents": 12001}, ADMIN),
            ApiErrorId.ERR_RATE_ABOVE_CEILING,
        )
        booked = validate_success(
            api.create_assignment(
                {**payload, "bill_rate_cents": 9600, "pay_rate_cents": 8000}, ADMIN
            ),
            expected_status=201,
        )
        assert_assignment(booked)
        assert booked["status"] == "PENDING"
        assert booked["supplier_id"] == ctx["supplier"]["id"]
        offer_after = get_success_data(
            api.get_distribution_offer(ctx["offer"]["id"], ADMIN)
        )
        assert offer_after["status"] == "CONSUMED", (
            "failed attempts never consume the offer; the successful booking does"
        )
        assert get_supplier(ctx["supplier"]["id"])["offers_filled_count"] == 1


class TestMarkupCardCapBinds:
    def test_markup_above_card_cap_rejected(self, api):
        """PRD: "The markup transparency check compares the booked rates
        against the tighter of two caps: the smaller of the card's
        `max_markup_pct` and the supplier's tier cap — 25% for `PREFERRED`,
        20% for `APPROVED`, 15% for `PROBATION`."
        PRD: "the markup transparency check must pass, else
        `ERR_MARKUP_ABOVE_CAP` (422)"

        Design: Corner/calculations/markup_card_cap_binds_below_tier_cap
        """
        ctx = setup_bookable(card_overrides={"max_markup_pct": 0.15})
        payload = create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"], start_date="2026-05-01", end_date="2026-06-30",
        )
        resp = api.create_assignment(
            {**payload, "bill_rate_cents": 9500, "pay_rate_cents": 8000}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_MARKUP_ABOVE_CAP)
        # markup 0.1875 > min(0.15 card cap, 0.25 PREFERRED tier cap) = 0.15

    def test_markup_within_card_cap_accepted_with_same_offer(self, api):
        """PRD: "the booking is allowed only when the bill rate in cents
        multiplied by ten thousand is less than or equal to the pay rate in
        cents multiplied by ten thousand plus the applicable cap expressed in
        basis points — the cap fraction multiplied by ten thousand and rounded
        to a whole number."
        PRD: "A successfully booked assignment starts `PENDING`; its
        `supplier_id` is copied from the offer; the referenced offer moves
        `ACCEPTED` → `CONSUMED`; and the supplier's `offers_filled_count`
        increases by one."

        Design: Corner/calculations/markup_card_cap_binds_below_tier_cap
        """
        ctx = setup_bookable(card_overrides={"max_markup_pct": 0.15})
        payload = create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"], start_date="2026-05-01", end_date="2026-06-30",
        )
        validate_error(
            api.create_assignment(
                {**payload, "bill_rate_cents": 9500, "pay_rate_cents": 8000}, ADMIN
            ),
            ApiErrorId.ERR_MARKUP_ABOVE_CAP,
        )
        offer_mid = get_success_data(api.get_distribution_offer(ctx["offer"]["id"], ADMIN))
        assert offer_mid["status"] == "ACCEPTED", (
            "a rejected booking leaves the offer ACCEPTED"
        )
        booked = validate_success(
            api.create_assignment(
                {**payload, "bill_rate_cents": 9120, "pay_rate_cents": 8000}, ADMIN
            ),
            expected_status=201,
        )
        assert booked["status"] == "PENDING", (
            "markup 0.14 <= 0.15 passes the card cap"
        )


def test_rate_card_window_not_covering_start_returns_422(api):
    """PRD: "the governing card's half-open window must contain the
    assignment's `start_date`, else `ERR_CARD_NOT_EFFECTIVE` (422)"

    Design: Corner/errors/rate_card_window_not_covering_start_returns_422
    """
    ctx = setup_bookable(
        card_overrides={"effective_from": "2026-06-01", "effective_to": "2027-01-01"}
    )
    resp = api.create_assignment(
        create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"], start_date="2026-05-01", end_date="2026-08-31",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_EFFECTIVE)
    # start 2026-05-01 lies before the half-open window [2026-06-01, 2027-01-01)


def test_retired_rate_card_rejected_on_assignment(api):
    """PRD: "the referenced `rate_card_id` must be an `ACTIVE` card whose key
    matches the engagement's `role_code`, `skill_code` and `geo_code`, else
    `ERR_RATE_CARD_INACTIVE` (422)"
    PRD: "Retirement moves a card `ACTIVE` → `RETIRED`; `RETIRED` is terminal,
    and a retired card never governs anything again."

    Design: Corner/errors/retired_rate_card_rejected_on_assignment
    """
    ctx = setup_bookable()
    get_success_data(api.retire_rate_card(ctx["rate_card"]["id"], ADMIN))
    resp = api.create_assignment(
        create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_INACTIVE)


def test_declined_offer_cannot_source_assignment(api):
    """PRD: "the offer must be `ACCEPTED` and must belong to the named
    engagement, else `ERR_OFFER_NOT_ACCEPTED` (422)"

    Design: Corner/errors/declined_offer_cannot_source_assignment
    """
    ctx = setup_bookable(respond_action="DECLINE")
    assert ctx["offer"]["status"] == "DECLINED"
    resp = api.create_assignment(
        create_assignment_payload(
            ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
            ctx["rate_card"]["id"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)


def test_worker_supplier_mismatch_rejected(api):
    """PRD: "the worker's `supplier_id` must equal the offer's `supplier_id`,
    else `ERR_WORKER_SUPPLIER_MISMATCH` (422)."

    Design: Corner/errors/worker_supplier_mismatch_rejected
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    rate_card = create_active_rate_card()
    s1 = onboard_supplier(tier="PREFERRED", name="Mismatch One", supplier_code="SUP-MM1")
    s2 = onboard_supplier(tier="APPROVED", name="Mismatch Two", supplier_code="SUP-MM2")
    engagement = create_engagement_in_open(title="Mismatch")
    offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
    o1 = pick_offer_for_supplier(offers, s1["id"])
    o2 = pick_offer_for_supplier(offers, s2["id"])
    get_success_data(
        api.respond_to_offer(
            o1["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s1["id"])
        )
    )
    o2 = get_success_data(
        api.respond_to_offer(
            o2["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s2["id"])
        )
    )
    worker = get_success_data(
        api.create_worker(
            create_worker_payload(s1["id"], full_name="Worker One",
                                  email="w1@example.com"),
            make_supplier_coordinator_headers(s1["id"]),
        )
    )
    resp = api.create_assignment(
        create_assignment_payload(
            worker["id"], engagement["id"], o2["id"], rate_card["id"]
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_WORKER_SUPPLIER_MISMATCH)


def test_assignment_on_sow_engagement_rejected(api):
    """PRD: "the engagement must be of type `REQUISITION` — booking against
    an `SOW` engagement yields `ERR_ENGAGEMENT_TYPE_MISMATCH` (422)"

    Design: Corner/errors/assignment_on_sow_engagement_rejected
    """
    rate_card = create_active_rate_card()
    sow = setup_sow_engagement()
    worker = get_success_data(
        api.create_worker(
            create_worker_payload(sow["supplier"]["id"], full_name="Worker One",
                                  email="w1@example.com"),
            make_supplier_coordinator_headers(sow["supplier"]["id"]),
        )
    )
    resp = api.create_assignment(
        create_assignment_payload(
            worker["id"], sow["engagement"]["id"], sow["offer"]["id"], rate_card["id"]
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_TYPE_MISMATCH)


class TestWorkerDoubleBooking:
    def _setup_worker_with_active_assignment_and_second_offer(self, api):
        ctx = setup_staffed_assignment(start_date="2026-05-01", end_date="2026-06-30")
        engagement2 = create_engagement_in_open(title="E2", duration_months=4,
                                                budget_cents=2_000_000)
        offers = get_success_data(api.distribute_engagement(engagement2["id"], ADMIN))
        offer2 = pick_offer_for_supplier(offers, ctx["supplier"]["id"])
        offer2 = get_success_data(
            api.respond_to_offer(
                offer2["id"], {"action": "ACCEPT"},
                make_supplier_coordinator_headers(ctx["supplier"]["id"]),
            )
        )
        return ctx, engagement2, offer2

    def test_single_shared_day_is_double_booking(self, api):
        """PRD: "the new assignment's closed interval must not share even a
        single day with any other non-terminal assignment of the worker — a
        single touching day is a conflict and yields
        `ERR_WORKER_DOUBLE_BOOKED` (409)"

        Design: Difficulty/resource_temporal_overlap/worker_closed_interval_double_booking
        """
        ctx, engagement2, offer2 = (
            self._setup_worker_with_active_assignment_and_second_offer(api)
        )
        resp = api.create_assignment(
            create_assignment_payload(
                ctx["worker"]["id"], engagement2["id"], offer2["id"],
                ctx["rate_card"]["id"], start_date="2026-06-30", end_date="2026-08-31",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_DOUBLE_BOOKED)
        # closed intervals [2026-05-01, 2026-06-30] and [2026-06-30, 2026-08-31]
        # share the single day 2026-06-30 — touching IS overlap here.
        a1 = get_assignment(ctx["assignment"]["id"])
        assert a1["status"] == "ACTIVE"
        assert a1["start_date"] == "2026-05-01" and a1["end_date"] == "2026-06-30"

    def test_next_day_start_books_with_same_offer(self, api):
        """PRD: "the new assignment's closed interval must not share even a
        single day with any other non-terminal assignment of the worker — a
        single touching day is a conflict and yields
        `ERR_WORKER_DOUBLE_BOOKED` (409)"
        PRD: "A successfully booked assignment starts `PENDING`; its
        `supplier_id` is copied from the offer; the referenced offer moves
        `ACCEPTED` → `CONSUMED`; and the supplier's `offers_filled_count`
        increases by one."

        Design: Difficulty/resource_temporal_overlap/worker_closed_interval_double_booking
        """
        ctx, engagement2, offer2 = (
            self._setup_worker_with_active_assignment_and_second_offer(api)
        )
        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    ctx["worker"]["id"], engagement2["id"], offer2["id"],
                    ctx["rate_card"]["id"],
                    start_date="2026-06-30", end_date="2026-08-31",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_WORKER_DOUBLE_BOOKED,
        )
        booked = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    ctx["worker"]["id"], engagement2["id"], offer2["id"],
                    ctx["rate_card"]["id"],
                    start_date="2026-07-01", end_date="2026-08-31",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert booked["status"] == "PENDING", (
            "starting the day after the existing interval ends shares no day"
        )
        assert get_supplier(ctx["supplier"]["id"])["offers_filled_count"] == 2


class TestTenureExtendBoundary:
    def test_extend_projected_729_days_succeeds(self, api):
        """PRD: "An `ACTIVE` assignment may be extended in place by supplying
        a `new_end_date` strictly later than the current `end_date`; the
        extension is rejected with `ERR_TENURE_LIMIT_EXCEEDED` when the tenure
        projection to `new_end_date` reaches or exceeds 730 days, and on
        success the assignment's `end_date` simply becomes `new_end_date`"

        Design: Difficulty/boundary_precision_check/tenure_extend_exactly_730_rejected
        """
        ctx = setup_staffed_assignment(
            tenure_carryover_days=698,
            start_date="2026-04-02",
            end_date="2026-05-01",
        )
        # current tenure: 698 + 30 days (2026-04-02..2026-05-01 inclusive) = 728
        extended = validate_success(
            api.extend_assignment(
                ctx["assignment"]["id"], {"new_end_date": "2026-05-02"}, ADMIN
            )
        )
        assert extended["end_date"] == "2026-05-02", (
            "projected 698 + 31 = 729 < 730, so the extension succeeds"
        )
        assert extended["status"] == "ACTIVE", "the assignment stays ACTIVE throughout"

    def test_extend_projected_730_days_rejected(self, api):
        """PRD: "a projection landing on exactly 730 days is rejected with
        `ERR_TENURE_LIMIT_EXCEEDED` (422), the boundary is inclusive of
        rejection"

        Design: Difficulty/boundary_precision_check/tenure_extend_exactly_730_rejected
        """
        ctx = setup_staffed_assignment(
            tenure_carryover_days=699,
            start_date="2026-04-02",
            end_date="2026-05-01",
        )
        # current tenure: 699 + 30 = 729; projected to 2026-05-02: 699 + 31 = 730
        resp = api.extend_assignment(
            ctx["assignment"]["id"], {"new_end_date": "2026-05-02"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_TENURE_LIMIT_EXCEEDED)
        after = get_assignment(ctx["assignment"]["id"])
        assert after["end_date"] == "2026-05-01", "rejection leaves end_date unchanged"


class TestSuspendedSupplierOutranksReferential:
    def _setup_suspended_supplier_and_retired_card(self, api):
        ctx = setup_bookable()
        get_success_data(api.suspend_supplier(ctx["supplier"]["id"], ADMIN))
        get_success_data(api.retire_rate_card(ctx["rate_card"]["id"], ADMIN))
        return ctx

    def test_suspended_supplier_error_outranks_retired_card(self, api):
        """PRD: "These outrank the referential and fiscal failures below — a
        suspended supplier, for instance, surfaces `ERR_SUPPLIER_SUSPENDED`
        even when the same request would also have failed a referential
        check."
        PRD: "While a supplier is `SUSPENDED`, three operations are refused
        with `ERR_SUPPLIER_SUSPENDED` (422): accepting an offer through the
        supplier response flow, booking an assignment that would engage the
        supplier, and delivering a milestone."

        Design: Difficulty/priority_pair_validation_conflict/assignment_create_safety_before_referential
        """
        ctx = self._setup_suspended_supplier_and_retired_card(api)
        resp = api.create_assignment(
            create_assignment_payload(
                ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
                ctx["rate_card"]["id"],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_SUSPENDED)
        assert resp.json()["data"]["error_id"] != "ERR_RATE_CARD_INACTIVE", (
            "business_safety outranks business_referential even though the card "
            "is RETIRED"
        )

    def test_rejected_booking_persists_no_assignment(self, api):
        """PRD: "While a supplier is `SUSPENDED`, three operations are refused
        with `ERR_SUPPLIER_SUSPENDED` (422): accepting an offer through the
        supplier response flow, booking an assignment that would engage the
        supplier, and delivering a milestone. Consistent with §2.7, this
        refusal outranks referential and fiscal failures on the same request."

        Design: Difficulty/priority_pair_validation_conflict/assignment_create_safety_before_referential
        """
        ctx = self._setup_suspended_supplier_and_retired_card(api)
        validate_error(
            api.create_assignment(
                create_assignment_payload(
                    ctx["worker"]["id"], ctx["engagement"]["id"], ctx["offer"]["id"],
                    ctx["rate_card"]["id"],
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_SUPPLIER_SUSPENDED,
        )
        _, meta = validate_paginated(
            api.list_assignments(ADMIN, params={"worker_id": ctx["worker"]["id"]})
        )
        assert meta["total_count"] == 0, "the refused booking persists nothing"


def test_worker_carryover_and_tenure_defaults(api):
    """PRD: "an optional `tenure_carryover_days` crediting prior service
    toward the tenure limit (default 0)."
    PRD: "A worker is born `ONBOARDING` with `conversion_status` `NONE`, and
    exposes a computed `cumulative_tenure_days` on read."

    Design: Corner/entities/worker_carryover_and_tenure_defaults
    """
    supplier = onboard_supplier(tier="APPROVED", name="Defaults Co",
                                supplier_code="SUP-DF")
    worker = validate_success(
        api.create_worker(
            {"supplier_id": supplier["id"], "full_name": "No Carry",
             "email": "nc@example.com"},
            make_supplier_coordinator_headers(supplier["id"]),
        ),
        expected_status=201,
    )
    assert_worker(worker)
    assert worker["tenure_carryover_days"] == 0, "default 0 applied"
    assert worker["cumulative_tenure_days"] == 0, (
        "carryover 0 plus an empty assignment set sums to 0"
    )
    assert worker["status"] == "ONBOARDING"
    assert worker["conversion_status"] == "NONE"


def test_worker_rehire_cycle_valid(api):
    """PRD: "as a bubble-up, a worker who was `ONBOARDING` or `OFFBOARDING`
    becomes `ACTIVE`"
    PRD: "Completion moves `ACTIVE` → `COMPLETED`, stamping `actual_end_date`
    from the logical clock date, incrementing the supplier's
    `completed_assignments_count`, and cascading the worker to `OFFBOARDING`
    when no `PENDING` or `ACTIVE` assignment remains."
    PRD: "a `ProgramAdmin` may complete offboarding for an `OFFBOARDING`
    worker — moving the worker to `EXITED` — and may rehire an `EXITED`
    worker, which returns the worker to `ONBOARDING`; the worker lifecycle is
    deliberately cyclic."

    Design: Corner/state_machines/worker_rehire_cycle_valid
    """
    ctx = setup_staffed_assignment(start_date="2026-05-01", end_date="2026-06-30")
    worker_id = ctx["worker"]["id"]
    assert get_worker(worker_id)["status"] == "ACTIVE", (
        "activation bubbled the ONBOARDING worker to ACTIVE"
    )
    get_success_data(api.complete_assignment(ctx["assignment"]["id"], ADMIN))
    assert get_worker(worker_id)["status"] == "OFFBOARDING", (
        "no remaining PENDING/ACTIVE assignment cascades the worker to OFFBOARDING"
    )
    exited = get_success_data(api.offboard_complete_worker(worker_id, ADMIN))
    assert exited["status"] == "EXITED"
    rehired = validate_success(api.rehire_worker(worker_id, ADMIN))
    assert rehired["status"] == "ONBOARDING", "the EXITED -> ONBOARDING cycle arc works"


class TestEngagementCloseCascade:
    def _setup_two_engagements_shared_worker(self, api):
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card()
        s1 = onboard_supplier(tier="PREFERRED", name="Sup One", supplier_code="SUP-1")
        s2 = onboard_supplier(tier="APPROVED", name="Sup Two", supplier_code="SUP-2")

        e1 = create_engagement_in_open(title="E1", duration_months=4,
                                       budget_cents=3_000_000)
        offers1 = get_success_data(api.distribute_engagement(e1["id"], ADMIN))
        o1 = pick_offer_for_supplier(offers1, s1["id"])
        o2 = pick_offer_for_supplier(offers1, s2["id"])
        get_success_data(
            api.respond_to_offer(
                o1["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s1["id"])
            )
        )
        get_success_data(
            api.respond_to_offer(
                o2["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s2["id"])
            )
        )
        w1 = get_success_data(
            api.create_worker(
                create_worker_payload(s1["id"], full_name="Worker One",
                                      email="w1@example.com"),
                make_supplier_coordinator_headers(s1["id"]),
            )
        )
        w2 = get_success_data(
            api.create_worker(
                create_worker_payload(s2["id"], full_name="Worker Two",
                                      email="w2@example.com"),
                make_supplier_coordinator_headers(s2["id"]),
            )
        )
        a1 = get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    w1["id"], e1["id"], o1["id"], rate_card["id"],
                    start_date="2026-05-01", end_date="2026-06-30"),
                ADMIN,
            )
        )
        get_success_data(api.activate_assignment(a1["id"], ADMIN))
        a2 = get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    w2["id"], e1["id"], o2["id"], rate_card["id"],
                    start_date="2026-05-01", end_date="2026-06-30"),
                ADMIN,
            )
        )
        get_success_data(api.activate_assignment(a2["id"], ADMIN))

        e2 = create_engagement_in_open(title="E2", duration_months=5,
                                       budget_cents=3_000_000)
        offers2 = get_success_data(api.distribute_engagement(e2["id"], ADMIN))
        o3 = pick_offer_for_supplier(offers2, s2["id"])
        get_success_data(
            api.respond_to_offer(
                o3["id"], {"action": "ACCEPT"}, make_supplier_coordinator_headers(s2["id"])
            )
        )
        a3 = get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    w2["id"], e2["id"], o3["id"], rate_card["id"],
                    start_date="2026-07-01", end_date="2026-09-30"),
                ADMIN,
            )
        )
        get_success_data(api.activate_assignment(a3["id"], ADMIN))
        return {"s1": s1, "s2": s2, "e1": e1, "e2": e2, "w1": w1, "w2": w2,
                "a1": a1, "a2": a2, "a3": a3}

    def test_close_terminates_assignments_with_engagement_closed_reason(self, api):
        """PRD: "From `ACTIVE` the cascade is the full chain: every `PENDING`
        or `ACTIVE` assignment becomes `TERMINATED` with `termination_reason`
        `ENGAGEMENT_CLOSED` and `actual_end_date` set to the logical clock
        date"

        Design: Difficulty/transitive_cascade/engagement_close_assignment_worker_chain
        """
        ctx = self._setup_two_engagements_shared_worker(api)
        closed = validate_success(api.close_engagement(ctx["e1"]["id"], HM))
        assert closed["status"] == "CLOSED"
        for key in ("a1", "a2"):
            assignment = get_assignment(ctx[key]["id"])
            assert assignment["status"] == "TERMINATED"
            assert assignment["termination_reason"] == "ENGAGEMENT_CLOSED"
            assert assignment["actual_end_date"] == "2026-05-01", (
                "actual_end_date stamps from the logical clock date"
            )
        assert get_worker(ctx["w1"]["id"])["status"] == "OFFBOARDING", (
            "W1 has no remaining PENDING/ACTIVE assignment"
        )

    def test_worker_with_remaining_assignment_stays_active(self, api):
        """PRD: "for each terminated assignment, if its worker has no
        remaining assignment in `PENDING` or `ACTIVE`, the worker moves to
        `OFFBOARDING`"

        Design: Difficulty/transitive_cascade/engagement_close_assignment_worker_chain
        """
        ctx = self._setup_two_engagements_shared_worker(api)
        validate_success(api.close_engagement(ctx["e1"]["id"], HM))
        assert get_worker(ctx["w2"]["id"])["status"] == "ACTIVE", (
            "W2 still has ACTIVE assignment A3 on engagement E2, so the cascade "
            "does not offboard"
        )
        a3 = get_assignment(ctx["a3"]["id"])
        assert a3["status"] == "ACTIVE", (
            "assignments on other engagements are untouched by the close"
        )
        assert get_engagement(ctx["e2"]["id"])["status"] == "ACTIVE"
