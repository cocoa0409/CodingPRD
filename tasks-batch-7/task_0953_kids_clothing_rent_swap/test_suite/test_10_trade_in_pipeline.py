"""Pipeline T: from an outgrown garment to spendable account credit."""

from test_helpers import (
    ADMIN,
    BILLING,
    LOGISTICS,
    PLANNER,
    ApiErrorId,
    assert_garment_unit,
    assert_same_instant,
    assert_trade_in_item,
    assert_trade_in_submission,
    add_trade_in_item,
    create_active_member,
    create_open_cycle,
    create_style,
    create_trade_in_submission,
    find_charge,
    finalize_trade_in,
    get_charge_entry,
    get_credit_entry,
    get_cycle,
    get_member,
    get_style,
    get_submission,
    get_trade_in_item,
    grade_trade_in_item,
    list_credit_entries,
    make_member_headers,
    open_trade_in_assessment,
    set_clock,
    setup_credited_trade_in,
    setup_paused_member,
    setup_plan_and_member,
    setup_received_trade_in,
    submit_grade,
    confirm_grade,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubmissionIntake:
    def test_a_declared_garment_starts_on_both_initial_axis_values(self, api):
        """PRD §3.9: "A trade-in garment is born with `grading_status` `PENDING`
        and `disposition_status` `NONE`, `assessed_grade` null, `demand_band`
        `MEDIUM`, `absorbed_unit_id` null, and `credit_cents` and
        `granted_credit_cents` at 0."
        PRD §3.9: "A new submission is `DRAFT` with `inbound_shipment_id` null,
        `credited_total_cents` and `uncapped_total_cents` at 0, and
        `election_deadline_at` null."

        Design: Corner/entities/corner_trade_in_item_starts_on_both_initial_axis_values
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        submission = create_trade_in_submission(member["id"], 3)
        assert_trade_in_submission(submission)

        item = validate_success(
            api.add_trade_in_item(submission["id"],
                                  {"declared_brand_tier": "VALUE",
                                   "declared_size_code": "6"},
                                  make_member_headers(member["id"])),
            201,
        )
        assert_trade_in_item(item)
        assert item["grading_status"] == "PENDING"
        assert item["disposition_status"] == "NONE"
        assert item["credit_cents"] == 0
        assert item["granted_credit_cents"] == 0
        assert item["assessed_grade"] is None

        after = get_submission(submission["id"])
        assert after["status"] == "DRAFT"
        assert after["credited_total_cents"] == 0

    def test_declaring_fewer_than_three_garments_is_refused(self, api):
        """PRD §3.9: "The household opens one by naming its own `member_id` and a
        `declared_item_count`; that count must be at least
        `TRADEIN_MIN_ITEMS_PER_SUBMISSION`, three, and at most
        `TRADEIN_MAX_ITEMS_PER_SUBMISSION`, twelve. A count outside those
        bounds, adding more garments than declared, or issuing a label while the
        number of created garment rows does not equal `declared_item_count`, is
        refused with `ERR_TRADE_IN_ITEM_COUNT_INVALID` (HTTP 422)."

        Design: Corner/validations/corner_val_trade_in_below_the_minimum_item_count_is_rejected
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})

        resp = api.create_trade_in_submission(
            {"member_id": member["id"], "declared_item_count": 2},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_IN_ITEM_COUNT_INVALID.value, 422)
        _, meta = validate_paginated(api.list_trade_in_submissions(
            ADMIN, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_a_paused_household_is_told_intake_is_blocked_not_that_it_is_paused(self, api):
        """PRD §2.6 rung 18: "The member's `status` is not `PAUSED` for a
        Pipeline T intake write. Otherwise `ERR_INTAKE_BLOCKED_WHILE_PAUSED`
        (409). Applies to `POST /kidswear/trade-in-submissions`,
        `POST /kidswear/trade-in-submissions/{submission_id}/items` and
        `POST /kidswear/trade-in-submissions/{submission_id}/issue-label`. Note
        that the two pause rungs carry *different* error identifiers: a paused
        household that tries to circulate garments and a paused household that
        tries to send garments in are told apart."

        Design: Corner/validations/corner_val_paused_member_cannot_start_a_trade_in_intake
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        setup_paused_member(member["id"], "2026-05-05T00:00:00Z", 10)

        resp = api.create_trade_in_submission(
            {"member_id": member["id"], "declared_item_count": 3},
            make_member_headers(member["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_INTAKE_BLOCKED_WHILE_PAUSED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_MEMBER_PAUSED.value
        _, meta = validate_paginated(api.list_trade_in_submissions(
            ADMIN, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_finalising_a_submission_that_never_reached_grading_is_refused(self, api):
        """PRD §3.9: "Finalisation is a `BillingAgent` action moving the
        submission `GRADING → CREDITED`, and it requires **every** garment in
        the batch to have a `grading_status` of `GRADED` or `REJECTED` — no
        garment may still be `PENDING`."
        PRD §3.9: "Any trade-in transition attempted from an undeclared
        from-state on the addressed axis is refused with
        `ERR_TRADE_IN_INVALID_STATE`."

        Design: Corner/state_machines/corner_sm_trade_in_finalize_before_grading_is_rejected
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        intake = setup_received_trade_in(member, 3, "VALUE", "6")

        resp = api.finalize_trade_in_submission(intake["submission"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_TRADE_IN_INVALID_STATE.value, 409)

        after = get_submission(intake["submission"]["id"])
        assert after["status"] == "RECEIVED"
        assert after["credited_total_cents"] == 0
        assert get_member(member["id"])["credit_balance_cents"] == 0

    def test_the_coordinator_who_issues_the_label_may_not_grant_the_credit(self, api):
        """PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.9: "Finalisation is a `BillingAgent` action moving the submission
        `GRADING → CREDITED`, and it requires **every** garment in the batch to
        have a `grading_status` of `GRADED` or `REJECTED` — no garment may still
        be `PENDING`."

        Design: Corner/rbac/corner_rbac_logistics_coordinator_cannot_finalize_a_trade_in
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "6", "auto_apply_credit": False}
        )
        intake = setup_received_trade_in(member, 3, "STANDARD", "6")
        for item in intake["items"]:
            grade_trade_in_item(item["id"], "B", grader_id="grader-r8",
                                planner_id="planner-r8")

        resp = api.finalize_trade_in_submission(intake["submission"]["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)

        after = get_submission(intake["submission"]["id"])
        assert after["status"] == "GRADING"
        assert after["credited_total_cents"] == 0
        assert get_member(member["id"])["credit_balance_cents"] == 0


class TestPerGarmentCredit:
    def test_the_credit_is_the_product_of_three_declared_tables(self, api):
        """PRD §3.9: "The grade base comes from `TRADEIN_GRADE_BASE_CENTS`: 1400
        cents for `A`, 900 for `B`, 450 for `C` and 0 for `D`. The brand
        multiplier comes from `BRAND_TIER_MULTIPLIER`: 1.40 for `PREMIUM`, 1.00
        for `STANDARD`, 0.70 for `VALUE`. The size-demand multiplier comes from
        `SIZE_DEMAND_BAND_MULTIPLIER`: 1.25 for `HIGH`, 1.00 for `MEDIUM`, 0.80
        for `LOW`. `credit_cents` is the grade base multiplied by the brand
        multiplier multiplied by the demand multiplier, rounded once at the
        end."
        PRD §3.9: "The candidate set is every `ACTIVE` garment style whose
        `size_code` equals the garment's `declared_size_code`. If that set is
        empty the band is `MEDIUM`."
        PRD §3.9: "A confirmed grade whose ordinal is at most 3 — that is, `A`,
        `B`, `C` or `D` — moves the grading axis `PENDING → GRADED`, resolves
        `demand_band`, and computes `credit_cents`."

        Design: Corner/calculations/corner_calc_tradein_item_credit_three_factor_product
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "8", "auto_apply_credit": False}
        )
        create_style(sku="SKU-K11-8", name="Low Demand Eight", size_code="8",
                     retail_price_cents=4000, season="ALL_SEASON", demand_band="LOW")
        intake = setup_received_trade_in(member, 3, "STANDARD", "8")
        first = intake["items"][0]
        assessment = open_trade_in_assessment(first["id"], "grader-11")
        submit_grade(assessment["id"], "C", grader_id="grader-11")

        confirm_grade(assessment["id"], planner_id="planner-11")

        after = get_trade_in_item(first["id"])
        assert after["assessed_grade"] == "C"
        assert after["demand_band"] == "LOW"
        assert after["credit_cents"] == 360
        assert after["grading_status"] == "GRADED"
        assert after["granted_credit_cents"] == 0


class TestSubmissionCapWaterfalls:
    def _three_premium_size_six(self, tier, sku, email):
        plan, member = setup_plan_and_member(
            plan={"tier": tier, "slots_per_box": 1, "swaps_per_cycle": 1,
                  "monthly_fee_cents": 5000, "discount_pct": 0},
            member={"child_size_code": "6", "auto_apply_credit": False, "email": email},
        )
        create_style(sku=sku, name="Demand Marker", brand_tier="PREMIUM",
                     retail_price_cents=5200, size_code="6", season="ALL_SEASON",
                     category="TOP", demand_band="HIGH")
        return plan, member

    def test_the_sequential_waterfall_pays_the_top_garments_in_full(self, api):
        """PRD §3.9: "Under the **sequential** waterfall — which applies whenever
        the plan's `tier` is not `CAPSULE_PLUS` — a running remainder starts at
        6000 and each garment in the pinned order receives the smaller of its
        own `credit_cents` and whatever remains, with the remainder reduced by
        what it just granted; the highest-value garments are paid in full and
        the tail is truncated to zero, so the cap falls entirely on the cheapest
        pieces."
        PRD §3.9: "`uncapped_total_cents` is the sum of the already-rounded
        per-garment `credit_cents`, exposed on the submission precisely so the
        cap's effect is observable."

        Design: Difficulty/dual_variant_calc/tradein_submission_cap_sequential_truncates_tail
        """
        _, member = self._three_premium_size_six("CORE", "SKU-DEM-6H", "seq@kidswear.test")
        scenario = setup_credited_trade_in(member, ["A", "A", "A"], "PREMIUM", "6")

        submission = scenario["submission"]
        assert submission["uncapped_total_cents"] == 7350
        assert submission["credited_total_cents"] == 6000
        first, second = scenario["items"][0], scenario["items"][1]
        assert get_trade_in_item(first["id"])["credit_cents"] == 2450
        assert get_trade_in_item(first["id"])["granted_credit_cents"] == 2450
        assert get_trade_in_item(second["id"])["granted_credit_cents"] == 2450

    def test_the_sequential_waterfall_truncates_the_cheapest_tail_garment(self, api):
        """PRD §3.9: "the highest-value garments are paid in full and the tail is
        truncated to zero, so the cap falls entirely on the cheapest pieces."
        PRD §3.9: "Finalisation also moves every `GRADED` garment's grading axis
        to `CREDITED`, creates **one** credit ledger entry for the batch with
        `status` `AVAILABLE`, `amount_cents` and `remaining_cents` equal to
        `credited_total_cents`, `source_submission_id` pointing at the batch,
        `granted_at` at the logical clock and `expires_at` derived; recomputes
        the member's `credit_balance_cents`"
        PRD §3.9: "Finalisation walks the batch's `GRADED` garments ordered by
        `credit_cents` **descending**, ties broken by `created_at` ascending."

        Design: Difficulty/dual_variant_calc/tradein_submission_cap_sequential_truncates_tail
        """
        _, member = self._three_premium_size_six("CORE", "SKU-DEM-6H2", "seq2@kidswear.test")
        scenario = setup_credited_trade_in(member, ["A", "A", "A"], "PREMIUM", "6")

        third = get_trade_in_item(scenario["items"][2]["id"])
        assert third["granted_credit_cents"] == 1100
        assert third["grading_status"] == "CREDITED"
        assert get_member(member["id"])["credit_balance_cents"] == 6000

    def test_the_pro_rata_waterfall_scales_every_garment(self, api):
        """PRD §3.9: "Under the **pro-rata** waterfall — which applies when the
        plan's `tier` is `CAPSULE_PLUS` — a single factor is computed as the
        smaller of 1 and the cap divided by `uncapped_total_cents`, and every
        garment's `granted_credit_cents` is its own `credit_cents` multiplied by
        that factor, rounded half up per garment; no garment is zeroed."
        PRD §3.9: "The per-submission cap is
        `TRADEIN_CREDIT_CAP_PER_SUBMISSION_CENTS`, 6000 cents, and it is applied
        by one of **two waterfalls chosen by the plan's tier**."

        Design: Difficulty/dual_variant_calc/tradein_submission_cap_pro_rata_scales_every_item
        """
        _, member = self._three_premium_size_six("CAPSULE_PLUS", "SKU-DEM-6P",
                                                 "prorata@kidswear.test")
        scenario = setup_credited_trade_in(member, ["A", "A", "A"], "PREMIUM", "6")

        for item in scenario["items"]:
            assert get_trade_in_item(item["id"])["granted_credit_cents"] == 2000

    def test_the_pro_rata_waterfall_zeroes_no_garment_and_still_totals_the_cap(self, api):
        """PRD §3.9: "`credited_total_cents` is the sum of the granted amounts;
        per-garment rounding happens first and the rounded amounts are then
        summed."
        PRD §3.9: "The two waterfalls split identical inputs differently, which
        is the whole point of offering the second one."

        Design: Difficulty/dual_variant_calc/tradein_submission_cap_pro_rata_scales_every_item
        """
        _, member = self._three_premium_size_six("CAPSULE_PLUS", "SKU-DEM-6P2",
                                                 "prorata2@kidswear.test")
        scenario = setup_credited_trade_in(member, ["A", "A", "A"], "PREMIUM", "6")

        submission = scenario["submission"]
        assert submission["uncapped_total_cents"] == 7350
        assert submission["credited_total_cents"] == 6000
        assert get_member(member["id"])["credit_balance_cents"] == 6000


class TestFinalisationCascade:
    def _delinquent_household_with_a_graded_batch(self, sku, email):
        plan, member = setup_plan_and_member(
            plan={"tier": "PLUS", "slots_per_box": 1, "swaps_per_cycle": 1,
                  "monthly_fee_cents": 20000, "discount_pct": 0},
            member={"child_size_code": "6", "protection_enrolled": False,
                    "auto_apply_credit": True, "email": email},
        )
        create_style(sku=sku, name="Demand Marker 6C", brand_tier="PREMIUM",
                     retail_price_cents=5200, size_code="6", season="ALL_SEASON",
                     category="TOP", demand_band="HIGH")
        intake = setup_received_trade_in(member, 3, "PREMIUM", "6")
        for item in intake["items"]:
            grade_trade_in_item(item["id"], "A", grader_id="grader-06",
                                planner_id="planner-06")
        cycle = create_open_cycle(member["id"])
        return {"member": member, "submission": intake["submission"],
                "items": intake["items"], "cycle": cycle}

    def test_finalisation_grants_credit_and_auto_applies_it_to_the_plan_charge(self, api):
        """PRD §3.9: "Finalisation also moves every `GRADED` garment's grading
        axis to `CREDITED`, creates **one** credit ledger entry for the batch
        with `status` `AVAILABLE`, `amount_cents` and `remaining_cents` equal to
        `credited_total_cents`, `source_submission_id` pointing at the batch,
        `granted_at` at the logical clock and `expires_at` derived; recomputes
        the member's `credit_balance_cents`; applies the new credit immediately
        to the member's open charges under the standing waterfall when
        `auto_apply_credit` is true; and sets `election_deadline_at` to the
        finalisation instant plus `TRADEIN_DISPOSITION_ELECTION_DAYS`, seven
        days."
        PRD §3.11: "A charge whose `net_due_cents` reaches zero becomes
        `SETTLED`; a charge that received some credit but still owes becomes
        `PARTIALLY_SETTLED`; a charge that received nothing stays `ASSESSED`."

        Design: Difficulty/transitive_cascade/tradein_finalize_cascades_seven_hops_to_clearing_delinquency
        """
        world = self._delinquent_household_with_a_graded_batch("SKU-DEM-6C",
                                                               "credit@kidswear.test")
        plan_charge = find_charge(world["member"]["id"], "PLAN_CHARGE")
        assert plan_charge["amount_cents"] == 18000
        assert get_member(world["member"]["id"])["status"] == "DELINQUENT"

        finalize_trade_in(world["submission"]["id"])

        submission = get_submission(world["submission"]["id"])
        assert submission["status"] == "CREDITED"
        assert submission["credited_total_cents"] == 6000
        assert get_trade_in_item(world["items"][0]["id"])["grading_status"] == "CREDITED"

        entries = list_credit_entries(member_id=world["member"]["id"],
                                      source_submission_id=world["submission"]["id"])
        assert len(entries) == 1
        entry = get_credit_entry(entries[0]["id"])
        assert entry["amount_cents"] == 6000
        assert entry["remaining_cents"] == 0
        assert entry["status"] == "APPLIED"

        after_charge = get_charge_entry(plan_charge["id"])
        assert after_charge["credit_applied_cents"] == 6000
        assert after_charge["net_due_cents"] == 12000
        assert after_charge["status"] == "PARTIALLY_SETTLED"

    def test_the_auto_application_clears_delinquency_and_reopens_the_held_cycle(self, api):
        """PRD §3.11: "The member's `outstanding_balance_cents` is recomputed
        afterwards and the member may return `DELINQUENT → ACTIVE`."
        PRD §3.1: "A `DELINQUENT` member whose outstanding balance falls
        **strictly below** 15000 cents returns to `ACTIVE`."
        PRD §3.1: "Recovering to `ACTIVE` reverses the hold: every `HELD` cycle
        returns to the status implied by the current clock — `OPEN` while the
        clock is on or before `swap_by_at`, `SWAP_CLOSED` while it is on or
        before `return_due_at`, `RETURN_DUE` while it is on or before
        `grace_ends_at`, and `GRACE` thereafter — and the member's `version`
        increments again."

        Design: Difficulty/transitive_cascade/tradein_finalize_cascades_seven_hops_to_clearing_delinquency
        """
        world = self._delinquent_household_with_a_graded_batch("SKU-DEM-6C2",
                                                               "credit2@kidswear.test")
        assert get_cycle(world["cycle"]["id"])["status"] == "HELD"

        finalize_trade_in(world["submission"]["id"])

        member = get_member(world["member"]["id"])
        assert member["credit_balance_cents"] == 0
        assert member["outstanding_balance_cents"] == 12000
        assert member["status"] == "ACTIVE"
        assert get_cycle(world["cycle"]["id"])["status"] == "OPEN"


class TestDispositionAxis:
    def test_absorption_mints_house_stock_at_the_assessed_grade(self, api):
        """PRD §3.9: "Absorption mints a new `GarmentUnit` with
        `acquisition_source` `TRADE_IN_ABSORBED`, `state` `IN_STOCK` and
        `current_grade` equal to the garment's `assessed_grade`, writes
        `absorbed_unit_id` back onto the trade-in garment, moves its disposition
        axis `NONE → ABSORBED`, and increments the chosen style's
        `units_ever_acquired` by 1."
        PRD §3.9: "Absorption requires the garment's `grading_status` to have
        reached `CREDITED`, so a rejected garment is never absorbed."

        Design: Corner/state_machines/corner_sm_trade_in_absorption_transfers_ownership_into_rental_stock
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "6", "auto_apply_credit": False}
        )
        target = create_style(sku="SKU-SM17-6", name="Absorb Target", brand_tier="PREMIUM",
                              retail_price_cents=5200, size_code="6", season="ALL_SEASON",
                              category="TOP", demand_band="MEDIUM")
        scenario = setup_credited_trade_in(member, ["B", "B", "B"], "PREMIUM", "6")
        first = scenario["items"][0]

        new_unit = validate_success(
            api.absorb_trade_in_item(first["id"], {"style_id": target["id"]}, PLANNER), 201
        )
        assert_garment_unit(new_unit)
        assert new_unit["acquisition_source"] == "TRADE_IN_ABSORBED"
        assert new_unit["state"] == "IN_STOCK"
        assert new_unit["current_grade"] == "B"
        assert new_unit["style_id"] == target["id"]

        after_item = get_trade_in_item(first["id"])
        assert after_item["disposition_status"] == "ABSORBED"
        assert after_item["grading_status"] == "CREDITED"
        assert after_item["absorbed_unit_id"] == new_unit["id"]
        assert after_item["credit_cents"] == 1260
        assert get_style(target["id"])["units_ever_acquired"] == 1
        assert get_submission(scenario["submission"]["id"])["credited_total_cents"] == 3780

    def test_absorbing_into_a_style_of_another_size_is_refused(self, api):
        """PRD §2.6 rung 57: "Absorption requires a `GarmentStyle` whose `status`
        is `ACTIVE` and whose `size_code` equals the item's
        `declared_size_code`. Otherwise `ERR_ABSORB_STYLE_MISMATCH` (409).
        Applies to `POST /kidswear/trade-in-items/{trade_in_item_id}/absorb`."
        PRD §3.9: "A **credited** garment may be **absorbed** into house rental
        stock by a `MerchandisePlanner`, who supplies a `style_id`; that style
        must be `ACTIVE` and its `size_code` must equal the garment's
        `declared_size_code`, and any other style is refused with
        `ERR_ABSORB_STYLE_MISMATCH`."

        Design: Corner/errors/corner_err_absorb_into_a_mismatched_size_style_is_rejected
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "6", "auto_apply_credit": False}
        )
        wrong = create_style(sku="SKU-Y11-10", name="Wrong Size Target",
                             retail_price_cents=4000, size_code="10",
                             season="ALL_SEASON", category="TOP")
        scenario = setup_credited_trade_in(member, ["B", "B", "B"], "STANDARD", "6")
        first = scenario["items"][0]

        resp = api.absorb_trade_in_item(first["id"], {"style_id": wrong["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_ABSORB_STYLE_MISMATCH.value, 409)

        after = get_trade_in_item(first["id"])
        assert after["disposition_status"] == "NONE"
        assert after["absorbed_unit_id"] is None
        assert get_style(wrong["id"])["units_ever_acquired"] == 0
        _, meta = validate_paginated(api.list_garment_units(PLANNER,
                                                            {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_electing_a_disposition_on_an_ungraded_garment_is_refused(self, api):
        """PRD §3.9: "an election attempted on a garment whose
        `disposition_status` is not `AWAITING_ELECTION` is refused with
        `ERR_TRADE_IN_ITEM_NOT_REJECTED`."
        PRD §3.9: "A **rejected** garment sits in `AWAITING_ELECTION` until the
        household elects a `disposition`."

        Design: Corner/errors/corner_err_election_on_an_item_that_was_not_rejected_is_refused
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        intake = setup_received_trade_in(member, 3, "STANDARD", "6")
        first = intake["items"][0]

        resp = api.elect_disposition(first["id"], {"disposition": "DONATE"},
                                     make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TRADE_IN_ITEM_NOT_REJECTED.value, 409)

        after = get_trade_in_item(first["id"])
        assert after["disposition_status"] == "NONE"
        assert after["grading_status"] == "PENDING"

    def test_the_default_disposition_may_not_be_forced_before_the_deadline(self, api):
        """PRD §3.9: "Once the deadline has passed, a `PlatformAdmin` applies
        `TRADEIN_DEFAULT_DISPOSITION`, which is `DONATE`, without any member
        election and without any `SHIPPING_FEE`; applying the default at or
        before the deadline is refused with `ERR_ELECTION_NOT_DUE`."
        PRD §3.9: "A confirmed grade of `RETIRE` instead moves the grading axis
        `PENDING → REJECTED`, sets `credit_cents` to 0, and simultaneously moves
        the disposition axis `NONE → AWAITING_ELECTION`, because a garment the
        service will not take must go somewhere."

        Design: Corner/errors/corner_err_default_disposition_applied_before_the_deadline_is_refused
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "6", "auto_apply_credit": False}
        )
        scenario = setup_credited_trade_in(member, ["RETIRE", "B", "B"], "STANDARD", "6")
        rejected = scenario["items"][0]

        resp = api.apply_default_disposition(rejected["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ELECTION_NOT_DUE.value, 409)

        submission = get_submission(scenario["submission"]["id"])
        assert_same_instant(submission["election_deadline_at"], "2026-05-08T00:00:00.000Z",
                            "TradeInSubmission.election_deadline_at")
        assert submission["credited_total_cents"] == 1800
        after = get_trade_in_item(rejected["id"])
        assert after["grading_status"] == "REJECTED"
        assert after["disposition_status"] == "AWAITING_ELECTION"

    def test_an_election_after_the_seven_day_window_is_refused(self, api):
        """PRD §2.6 rung 41: "A disposition election is accepted only while the
        logical clock is on or before the submission's `election_deadline_at`;
        the boundary is **inclusive**. Otherwise
        `ERR_ELECTION_DEADLINE_PASSED` (409). Applies to
        `POST /kidswear/trade-in-items/{trade_in_item_id}/elect-disposition`."
        PRD §3.9: "Electing `RETURN_TO_MEMBER` ships the garment back and raises
        a charge ledger entry of `charge_type` `SHIPPING_FEE` for
        `TRADEIN_RETURN_SHIP_FEE_CENTS`, 1200 cents — the household pays to have
        its own rejected garment sent home."

        Design: Corner/errors/corner_err_disposition_elected_after_the_deadline_is_rejected
        """
        _, member = setup_plan_and_member(
            member={"child_size_code": "6", "auto_apply_credit": False}
        )
        scenario = setup_credited_trade_in(member, ["RETIRE", "B", "B"], "STANDARD", "6")
        rejected = scenario["items"][0]
        set_clock("2026-05-09T00:00:00Z")

        resp = api.elect_disposition(rejected["id"], {"disposition": "RETURN_TO_MEMBER"},
                                     make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ELECTION_DEADLINE_PASSED.value, 409)

        submission = get_submission(scenario["submission"]["id"])
        assert_same_instant(submission["election_deadline_at"], "2026-05-08T00:00:00.000Z",
                            "TradeInSubmission.election_deadline_at")
        assert get_trade_in_item(rejected["id"])["disposition_status"] == "AWAITING_ELECTION"
        assert get_member(member["id"])["outstanding_balance_cents"] == 0
