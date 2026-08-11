"""Plans, household registration, the size ladder and standing."""

from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    assert_member,
    assert_plan,
    assert_same_instant,
    create_member_payload,
    create_plan_payload,
)
from test_helpers import (
    activate_member,
    create_active_member,
    create_cycle,
    create_member,
    create_plan,
    create_style,
    create_unit,
    get_entitlements,
    get_member,
    make_member_headers,
    set_clock,
    setup_allocated_box,
    setup_plan_and_member,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanAuthoring:
    def test_plan_creation_echoes_its_declared_commercial_terms(self, api):
        """PRD §3.1: "A plan carries a `tier`, which is one of `STARTER`, `CORE`,
        `PLUS` or `CAPSULE_PLUS`; a `slots_per_box` count of at least 1 and at
        most 8, which fixes how many garments a box carries; a `swaps_per_cycle`
        entitlement of at least 0 and at most 6; and a `monthly_fee_cents` of at
        least 0, the base plan charge before proration, discount, credit and
        surcharge."
        PRD §3.1: "Every plan is born with `status` `ACTIVE` and may later be
        moved to `RETIRED`."
        PRD §3.1: "A `discount_pct` fraction defaults to 0 and may not exceed
        0.50; it discounts the plan charge *and*, by a deliberate coupling
        described in §3.10, the net protection fee as well."
        PRD §2.4: "`version` starts at 1 when the row is created and increases
        by exactly 1 on every mutation of that row, and `updated_at` is
        refreshed to the logical clock on the same mutation."

        Design: Corner/entities/corner_plan_creation_returns_declared_fields
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_plan(
            create_plan_payload(tier="STARTER", slots_per_box=3,
                                swaps_per_cycle=1, monthly_fee_cents=4900),
            ADMIN,
        )
        plan = validate_success(resp, 201)
        assert_plan(plan)
        assert plan["tier"] == "STARTER"
        assert plan["slots_per_box"] == 3
        assert plan["monthly_fee_cents"] == 4900
        assert plan["status"] == "ACTIVE"
        assert plan["version"] == 1
        assert plan["discount_pct"] == 0

    def test_plan_listing_pages_with_total_count_and_has_more(self, api):
        """PRD §2.3: "`limit` defaults to 10, may not be smaller than 1, and may
        not be larger than 100. `offset` defaults to 0 and counts rows to skip
        from the front of the ordered result."
        PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count` — the number of rows matching the filters before
        `limit` and `offset` are applied — and `has_more`, which is true exactly
        when `offset` plus the number of returned rows is strictly less than
        `total_count`."

        Design: Corner/entities/corner_plan_listing_returns_pagination_envelope
        """
        create_plan(tier="STARTER", slots_per_box=2, swaps_per_cycle=0, monthly_fee_cents=3900)
        create_plan(tier="CORE", slots_per_box=3, swaps_per_cycle=1, monthly_fee_cents=5900)
        create_plan(tier="PLUS", slots_per_box=5, swaps_per_cycle=2, monthly_fee_cents=8900)

        rows, meta = validate_paginated(api.list_plans(ADMIN, {"limit": 1, "offset": 1}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(rows) == 1
        body = api.list_plans(ADMIN, {"limit": 1, "offset": 1}).json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_pagination_limit_above_one_hundred_is_refused(self, api):
        """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is
        a field-shape failure and is refused with `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/endpoints/corner_ep_pagination_limit_above_the_maximum_is_rejected
        """
        create_plan()
        resp = api.list_plans(ADMIN, {"limit": 101, "offset": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)

    def test_registering_against_an_unknown_plan_is_not_found(self, api):
        """PRD §3.1: "A `plan_id` that does not resolve is refused with
        `ERR_PLAN_NOT_FOUND`, and registering against — or activating on — a
        plan whose `status` is `RETIRED` is refused with `ERR_PLAN_RETIRED`."

        Design: Corner/errors/corner_err_plan_not_found_on_member_registration
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_member(
            {
                "plan_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "email": "ghost@kidswear.test",
                "display_name": "Ghost",
                "child_size_code": "5",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)

    def test_registration_on_a_retired_plan_is_refused(self, api):
        """PRD §3.1: "A `plan_id` that does not resolve is refused with
        `ERR_PLAN_NOT_FOUND`, and registering against — or activating on — a
        plan whose `status` is `RETIRED` is refused with `ERR_PLAN_RETIRED`."
        PRD §3.1: "Only `discount_pct` and `status` may be updated after
        creation, and an administrator changing `discount_pct` should understand
        that it changes what the damage waiver is worth on every cycle opened
        afterwards."

        Design: Corner/errors/corner_err_registration_on_a_retired_plan_is_rejected
        """
        plan = create_plan()
        incumbent = create_member(plan["id"], email="incumbent@kidswear.test",
                                  display_name="Incumbent")
        validate_success(api.update_plan(plan["id"], {"status": "RETIRED"}, ADMIN))

        resp = api.create_member(
            create_member_payload(plan["id"], email="latecomer@kidswear.test",
                                  display_name="Latecomer"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_RETIRED.value, 409)
        assert validate_success(api.get_plan(plan["id"], ADMIN))["status"] == "RETIRED"
        assert get_member(incumbent["id"])["status"] == "PENDING"


class TestHouseholdRegistration:
    def test_unknown_member_id_is_not_found(self, api):
        """PRD §2.6 rung 6: "The `Member` identifier in the path or body
        resolves. Otherwise `ERR_MEMBER_NOT_FOUND` (404). Applies to every
        endpoint carrying a member identifier."

        Design: Corner/entities/corner_member_get_with_unknown_id_returns_not_found
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_member("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)
        assert resp.json()["response_type"] == "error"

    def test_registration_without_child_size_is_a_field_shape_failure(self, api):
        """PRD §3.1: "The registration payload carries `plan_id`, `email`,
        `display_name` and `child_size_code`, and may optionally carry
        `protection_enrolled`, which defaults to false, and `auto_apply_credit`,
        which defaults to true."
        PRD §2.9: "A body field that is required and missing, is null where a
        value is required, carries the wrong JSON type, or falls outside a
        declared numeric bound is refused with `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/entities/corner_member_creation_missing_child_size_is_rejected
        """
        plan = create_plan()
        resp = api.create_member(
            {"plan_id": plan["id"], "email": "nosize@kidswear.test",
             "display_name": "No Size"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)
        _, meta = validate_paginated(api.list_members(ADMIN, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_optional_registration_switches_take_their_declared_defaults(self, api):
        """PRD §3.1: "The registration payload carries `plan_id`, `email`,
        `display_name` and `child_size_code`, and may optionally carry
        `protection_enrolled`, which defaults to false, and `auto_apply_credit`,
        which defaults to true."
        PRD §3.1: "A new member begins in `status` `PENDING` with
        `size_effective_at` set to the logical clock at registration."
        PRD §3.1: "`credit_balance_cents` is the sum of `remaining_cents` across
        the member's credit entries whose `status` is `AVAILABLE` or
        `PARTIALLY_APPLIED`, and `outstanding_balance_cents` is the sum of
        `net_due_cents` across the member's charge entries whose `status` is
        `ASSESSED` or `PARTIALLY_SETTLED`."

        Design: Corner/entities/corner_member_defaults_applied_when_optionals_omitted
        """
        plan = create_plan()
        member = validate_success(
            api.create_member(
                create_member_payload(plan["id"], email="defaults@kidswear.test",
                                      display_name="Defaults", child_size_code="4T"),
                ADMIN,
            ),
            201,
        )
        assert_member(member)
        assert member["protection_enrolled"] is False
        assert member["auto_apply_credit"] is True
        assert member["status"] == "PENDING"
        assert member["credit_balance_cents"] == 0
        assert member["outstanding_balance_cents"] == 0
        assert member["completed_cycles"] == 0

    def test_size_effective_at_is_stamped_from_the_logical_clock(self, api):
        """PRD §3.1: "A new member begins in `status` `PENDING` with
        `size_effective_at` set to the logical clock at registration."
        PRD §2.4: "Every persisted resource carries a server-minted `id` that is
        a UUID string with no type prefix, and a `created_at` instant."

        Design: Corner/entities/corner_member_system_fields_generated_and_client_input_ignored
        """
        set_clock("2026-04-10T00:00:00Z")
        plan = create_plan()
        member = create_member(plan["id"], email="sysfields@kidswear.test",
                               display_name="Sys Fields", child_size_code="6")
        assert_same_instant(member["size_effective_at"], "2026-04-10T00:00:00.000Z",
                            "Member.size_effective_at")
        assert member["status"] == "PENDING"
        assert member["version"] == 1
        assert not member["id"].startswith("member")
        assert len(member["id"]) == 36 and member["id"].count("-") == 4

    def test_off_ladder_child_size_routes_to_the_enum_error(self, api):
        """PRD §2.9: "A value outside a declared member set routes to
        `ERR_INVALID_ENUM` (HTTP 422) for exactly these fields and **no
        others**: a plan's `tier`, `proration_basis` and `late_fee_mode`; a
        member's `child_size_code`; a garment style's `brand_tier`, `size_code`,
        `season` and `demand_band`; a shipment's `direction`; a shipping label's
        `direction`; a condition assessment's `pipeline` and `grade`; a
        processing job's `post_repair_grade`; a trade-in item's
        `declared_brand_tier` and `declared_size_code`; the `disposition` body
        field of a disposition election; the `quote_variant` body field of a
        buy-out quote request; a capsule's `season`; the `reason` supplied to
        unit retirement, which is a `retired_reason` value; a swap request's
        `rejection_reason`; and a pause request's `denial_reason`."

        Design: Corner/entities/corner_member_invalid_size_enum_is_rejected
        """
        plan = create_plan()
        resp = api.create_member(
            create_member_payload(plan["id"], email="badenum@kidswear.test",
                                  display_name="Bad Enum", child_size_code="16"),
            ADMIN,
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value

    def test_duplicate_household_email_is_refused(self, api):
        """PRD §2.9: "A member whose `email` duplicates an existing member's is
        refused with `ERR_DUPLICATE_EMAIL` (HTTP 409), and a garment style whose
        `sku` duplicates an existing style's is refused with `ERR_DUPLICATE_SKU`
        (HTTP 409)."

        Design: Corner/entities/corner_member_duplicate_email_is_rejected
        """
        plan = create_plan()
        create_member(plan["id"], email="dup@kidswear.test", display_name="First")
        resp = api.create_member(
            create_member_payload(plan["id"], email="dup@kidswear.test",
                                  display_name="Second"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value, 409)

    def test_second_activation_is_an_invalid_transition(self, api):
        """PRD §3.1: "Activation by a `PlatformAdmin` moves the member `PENDING
        → ACTIVE`. It requires that the member is still `PENDING` and that the
        referenced plan is `ACTIVE`; on success it sets `size_effective_at` to
        the current logical clock and increments the member's `version` by 1.
        Attempting the transition from any other state is refused with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/corner_sm_member_second_activation_is_rejected
        """
        plan = create_plan()
        member = create_member(plan["id"])
        activated = activate_member(member["id"])
        first_version = activated["version"]

        resp = api.activate_member(member["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = get_member(member["id"])
        assert after["status"] == "ACTIVE"
        assert after["version"] == first_version

    def test_logical_clock_starts_at_the_declared_default_instant(self, api):
        """PRD §2.4: "Before any client sets it, the logical clock reads exactly
        `2026-05-01T00:00:00Z` — the platform default recorded as
        `DEFAULT_CLOCK_UTC` — and it never falls back to real time."
        PRD §3.1: "A new member begins in `status` `PENDING` with
        `size_effective_at` set to the logical clock at registration."

        Design: Corner/endpoints/corner_ep_logical_clock_defaults_to_the_declared_instant
        """
        plan = create_plan()
        member = create_member(plan["id"], email="e1@kidswear.test",
                               display_name="Clock Default")
        assert_same_instant(member["size_effective_at"], "2026-05-01T00:00:00.000Z",
                            "Member.size_effective_at")
        assert_same_instant(member["created_at"], "2026-05-01T00:00:00.000Z",
                            "Member.created_at")


class TestSizeLadder:
    def test_size_up_of_four_rungs_exceeds_the_per_event_maximum(self, api):
        """PRD §3.1: "The event is valid only if it moves **up** the ladder by at
        least one rung and by no more than `SIZE_UP_MAX_STEPS_PER_EVENT`, which
        is 2 rungs; a move down the ladder, a move of zero rungs, or a move of
        three or more rungs is refused with `ERR_SIZE_UP_INVALID_STEP` (HTTP
        422)."
        PRD §3.1: "The eleven rungs of `SIZE_LADDER`, in order, are `2T`, `3T`,
        `4T`, `5`, `6`, `6X`, `7`, `8`, `10`, `12` and `14`, and their ordinals
        under `SIZE_LADDER_ORDINALS` run from 0 for `2T` to 10 for `14`."

        Design: Corner/calculations/corner_calc_size_up_of_four_rungs_is_rejected
        """
        _, member = setup_plan_and_member(member={"child_size_code": "5"})
        set_clock("2026-06-05T00:00:00Z")

        resp = api.size_up_member(member["id"], {"new_size_code": "8"},
                                  make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SIZE_UP_INVALID_STEP.value, 422)

        after = get_member(member["id"])
        assert after["child_size_code"] == "5"
        assert_same_instant(after["size_effective_at"], "2026-05-01T00:00:00.000Z",
                            "Member.size_effective_at")

    def test_size_up_inside_the_thirty_day_spacing_window_is_too_soon(self, api):
        """PRD §3.1: "Independently, at least
        `SIZE_UP_MIN_DAYS_BETWEEN_EVENTS` — thirty days — must have elapsed
        since the member's `size_effective_at`, and a sooner attempt is refused
        with `ERR_SIZE_UP_TOO_SOON`."

        Design: Corner/calculations/corner_calc_size_up_inside_the_spacing_window_is_rejected
        """
        _, member = setup_plan_and_member(member={"child_size_code": "5"})
        set_clock("2026-05-10T00:00:00Z")

        resp = api.size_up_member(member["id"], {"new_size_code": "6"},
                                  make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SIZE_UP_TOO_SOON.value, 409)
        assert get_member(member["id"])["child_size_code"] == "5"


class TestStandingGates:
    def test_a_member_may_not_act_on_another_households_account(self, api):
        """PRD §2.6 rung 4: "For an entity-backed role, `X-User-ID` equals the
        `id` of the `Member` that owns the addressed resource, reached directly
        or through `member_id`, through `cycle_id` to the cycle's owner, through
        `box_id` to the box's owner, or through `submission_id` to the
        submission's owner. Otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to
        every member-scoped endpoint."

        Design: Corner/validations/corner_val_member_cannot_act_on_another_members_pause
        """
        plan = create_plan()
        member_a = create_active_member(plan["id"], email="v1a@kidswear.test")
        member_b = create_active_member(plan["id"], email="v1b@kidswear.test")

        resp = api.create_pause_request(
            member_b["id"],
            {"start_at": "2026-05-05T00:00:00Z", "days_requested": 10},
            make_member_headers(member_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        _, meta = validate_paginated(api.list_pause_requests(ADMIN, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_a_pending_household_cannot_have_a_cycle_scheduled(self, api):
        """PRD §2.6 rung 15: "The owning member's `status` is not `PENDING`.
        Otherwise `ERR_MEMBER_NOT_ACTIVATED` (409). Applies to cycle, box, swap,
        buy-out, capsule and trade-in write endpoints."

        Design: Corner/validations/corner_val_pending_member_cannot_open_a_cycle
        """
        plan = create_plan()
        member = create_member(plan["id"])

        resp = api.create_cycle({"member_id": member["id"],
                                 "start_at": "2026-05-01T00:00:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVATED.value, 409)
        assert get_member(member["id"])["status"] == "PENDING"

    def test_a_cancelled_household_is_blocked_and_its_credit_revoked(self, api):
        """PRD §2.6 rung 14: "The owning member's `status` is not `CANCELLED`.
        Otherwise `ERR_MEMBER_CANCELLED` (409). Applies to every member-scoped
        write."
        PRD §3.1: "From `ACTIVE`, cancellation revokes every credit entry whose
        `status` is `AVAILABLE` or `PARTIALLY_APPLIED`, recording
        `MEMBER_CANCELLED` as the entry's `revoke_reason`, closes every
        `SCHEDULED` cycle of the member, and increments the member's `version`
        by 1."

        Design: Corner/validations/corner_val_cancelled_member_cannot_start_a_new_cycle
        """
        plan = create_plan()
        member = create_active_member(plan["id"], auto_apply_credit=False)
        credit = validate_success(
            api.create_credit_adjustment(member["id"],
                                         {"amount_cents": 2500, "reason": "goodwill"},
                                         BILLING),
            201,
        )
        validate_success(api.cancel_member(member["id"], make_member_headers(member["id"])))

        resp = api.create_cycle({"member_id": member["id"],
                                 "start_at": "2026-05-01T00:00:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_CANCELLED.value, 409)

        after = get_member(member["id"])
        assert after["status"] == "CANCELLED"
        assert after["credit_balance_cents"] == 0
        entry = validate_success(api.get_credit_entry(credit["id"], BILLING))
        assert entry["status"] == "REVOKED"


class TestEntitlementsAndListing:
    def test_entitlements_read_summarises_slots_swaps_and_pause_budgets(self, api):
        """PRD §3.1: "It answers with `slots_total`, taken from the plan's
        `slots_per_box`; `slots_occupied`, the occupied-slot count over the
        member's non-closed box; `slots_permanently_consumed`, taken from the
        member's `permanent_slots_consumed`; `swaps_remaining` for the member's
        open cycle; `pause_days_remaining_period` and
        `pause_days_remaining_lifetime`; and the two money aggregates
        `credit_balance_cents` and `outstanding_balance_cents`."
        PRD §3.10: "The member's `pause_days_used_period` — the sum of
        `days_requested` over the member's pauses whose `status` is `ACTIVE` or
        `ENDED` and whose `start_at` falls inside the trailing
        `PAUSE_PERIOD_LENGTH_DAYS` window of 365 days — plus this request's
        `days_requested` must not exceed thirty, or the activation is refused
        with `ERR_PAUSE_PERIOD_CAP_EXCEEDED`."

        Design: Corner/endpoints/corner_ep_entitlements_summary_reflects_slots_and_swaps
        """
        _, member = setup_plan_and_member(
            plan={"slots_per_box": 2, "swaps_per_cycle": 1, "monthly_fee_cents": 5000},
            member={"auto_apply_credit": False},
        )
        style = create_style(size_code="5")
        unit = create_unit(style["id"])
        setup_allocated_box(member, units=[unit])

        summary = get_entitlements(member["id"])
        assert summary["slots_total"] == 2
        assert summary["slots_occupied"] == 1
        assert summary["slots_permanently_consumed"] == 0
        assert summary["swaps_remaining"] == 1
        assert summary["pause_days_remaining_period"] == 30
        assert summary["pause_days_remaining_lifetime"] == 90
        assert summary["credit_balance_cents"] == 0
        assert summary["outstanding_balance_cents"] == 5000

    def test_cycle_list_filtered_by_member_returns_only_that_households_cycles(self, api):
        """PRD §2.3: "Filter parameters named on each list endpoint in §4 are all
        optional; supplying several narrows the result by conjunction."
        PRD §4: "List cycles, optionally filtered by member."

        Design: Corner/entities/corner_cycles_filtered_list_resolves_the_member_fk_in_reverse
        """
        plan = create_plan()
        member_one = create_active_member(plan["id"], email="fk1@kidswear.test")
        member_two = create_active_member(plan["id"], email="fk2@kidswear.test")
        cycle_one = create_cycle(member_one["id"])
        create_cycle(member_two["id"])

        rows, meta = validate_paginated(
            api.list_cycles(ADMIN, {"member_id": member_one["id"], "limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == cycle_one["id"]

        _, all_meta = validate_paginated(api.list_cycles(ADMIN, {"limit": 10, "offset": 0}))
        assert all_meta["total_count"] == 2
