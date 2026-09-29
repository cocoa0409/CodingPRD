"""Rounding order, evaluation order and band selection inside the formulas."""

from test_helpers import (
    ADMIN,
    ADMIN_2,
    assert_budget_conserved,
    assert_capital_project,
    assert_dues_waterfall_consistent,
    assert_invoice_components,
    assert_pool_split,
    assert_reservation_state,
    assert_satisfaction_survey,
    assert_settlement_derived_from_quota,
    assert_waitlisted_debits_nothing,
    book_member_stay,
    book_transient_stay,
    cancel,
    check_in,
    check_out,
    completed_stay,
    create_active_agreement,
    create_affiliate_open_park,
    create_classic_tier,
    create_member,
    create_open_park,
    create_park,
    create_president_tier,
    create_tier,
    list_invoices,
    make_capital_project_payload,
    make_park_manager_headers,
    make_reservation_payload,
    make_transfer_request_payload,
    propose_project,
    read_agreement,
    read_membership,
    read_park,
    read_project,
    read_reservation,
    reset_clock,
    sell_membership,
    sell_membership_to_new_member,
    set_clock,
    submit_survey,
    validate_error,
    validate_success,
)


def test_the_loyalty_band_keys_off_the_subtotal_across_three_tiers(api):
    """Three dues figures, three subtotals, and only the 62,640 subtotal earns a credit.

    PRD §3.1: "Step four selects a loyalty percentage from the **subtotal**, not
    from the base dues: it is 10 percent when the subtotal is at least 60,000
    cents (six hundred dollars) *and* the membership's `tenure_years` is at least
    5; 5 percent when the subtotal is at least 60,000 cents but tenure is below 5
    years; 3 percent when tenure is at least 5 years but the subtotal is below
    60,000 cents; and 0 percent otherwise."

    Design: Corner/calculations/dues_invoice_component_breakdown_is_correct_for_three_tiers
    """
    reset_clock(api)
    classic = create_classic_tier(api)
    select = create_tier(
        api,
        name="Select Membership",
        tier_rank=2,
        upfront_cost_cents=1250000,
        annual_dues_cents=50000,
        entitlement_nights_class_a=7,
        entitlement_nights_class_b=14,
        entitlement_nights_class_c=21,
        annual_total_night_cap=35,
        advance_window_days=90,
        max_consecutive_stay_nights=14,
        min_out_nights_between_stays=2,
        affiliate_access_enabled=True,
        resale_allowed=True,
        transfer_fee_cents=75000,
    )
    president = create_president_tier(api)

    expected = {
        classic["id"]: (42000, 3360, 0, 45360),
        select["id"]: (50000, 4000, 0, 54000),
        president["id"]: (58000, 4640, 3132, 59508),
    }
    holders = {}
    for tier_id, upfront, name, email in (
        (classic["id"], 795000, "Ada Lindqvist", "ada.lindqvist@example.com"),
        (select["id"], 1250000, "Bo Achterberg", "bo.achterberg@example.com"),
        (president["id"], 1850000, "Cai Rodrigues", "cai.rodrigues@example.com"),
    ):
        member = create_member(api, full_name=name, email=email)
        holders[tier_id] = sell_membership(
            api, member["id"], tier_id, upfront_paid_cents=upfront
        )

    for tier_id, (base, capital, loyalty, amount) in expected.items():
        membership = holders[tier_id]
        invoices = list_invoices(api, membership["id"])
        assert len(invoices) == 1, "selling a contract issues exactly one dues invoice"
        invoice = invoices[0]
        assert_invoice_components(
            invoice,
            base_dues_cents=base,
            capital_assessment_cents=capital,
            loyalty_credit_cents=loyalty,
            amount_cents=amount,
        )
        assert_dues_waterfall_consistent(invoice)
        assert invoice["cycle_year"] == 2026
        assert invoice["status"] == "OPEN"
        assert invoice["late_fee_cents"] == 0
        assert invoice["paid_amount_cents"] == 0
        assert invoice["days_past_due"] == 0
        assert invoice["due_date"] == "2026-08-31", "the logical date plus the 30-day net term"
        assert read_membership(api, membership["id"])["dues_balance_cents"] == amount

    select_invoice = list_invoices(api, holders[select["id"]]["id"])[0]
    assert select_invoice["loyalty_credit_cents"] == 0, (
        "a 54,000 subtotal sits below the 60,000 band even though 5 percent of it would be 2,700"
    )
    president_invoice = list_invoices(api, holders[president["id"]]["id"])[0]
    assert president_invoice["loyalty_credit_cents"] == 3132, (
        "the 58,000 base sits below the band while its 62,640 subtotal sits above it"
    )


def test_priority_score_counts_only_stayed_nights(api):
    """Four completed nights move the score; four cancelled and four confirmed do not.

    PRD §3.9: "Those stayed member nights are the sum of
    `entitlement_nights_charged` over reservations at that park whose `status` is
    `CHECKED_IN`, `EXTENSION_REVIEW` or `COMPLETED` and whose `arrival_date`
    falls in the current calendar year; `CONFIRMED`, `CANCELLED`, `WAITLISTED`
    and `EXPIRED` nights are excluded, so a cancelled stay never inflates a
    park's score."

    Design: Corner/calculations/capital_priority_score_counts_only_stayed_nights_not_cancelled_or_confirmed_ones
    """
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    manager = make_park_manager_headers(park["id"])
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )

    stayed = completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-08-05",
        "2026-08-09",
        check_in_instant="2026-08-05T15:00:00Z",
        check_out_instant="2026-08-09T10:00:00Z",
    )
    assert_reservation_state(stayed, "COMPLETED", entitlement_nights_charged=4)
    doomed = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-11", "2026-08-15"
    )
    standing = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-17", "2026-08-21"
    )
    cancel(api, doomed["id"], holder["headers"])

    project = validate_success(
        api.create_capital_project(
            make_capital_project_payload(
                park["id"],
                title="Replace the shore-power pedestals",
                category="UTILITY",
                requested_cost_cents=4500000,
                fiscal_year=2026,
            ),
            manager,
        ),
        201,
    )

    assert_capital_project(project)
    assert project["status"] == "PROPOSED"
    assert project["funded_amount_cents"] == 0
    assert project["requested_by_user_id"] == manager["X-User-ID"]
    # 1.20 UTILITY * 1.00 COMPLIANT * (1 + 1.50 gap) * (1 + 0.0033) * 1.20 cost = 3.61188
    assert project["priority_score"] == 3612
    assert project["priority_score"] != 3624, "the still-CONFIRMED four nights are not stayed nights"
    assert project["priority_score"] != 3636, "nor are the cancelled four nights"

    assert_reservation_state(
        read_reservation(api, doomed["id"]), "CANCELLED", entitlement_nights_charged=0
    )
    assert_reservation_state(
        read_reservation(api, standing["id"]), "CONFIRMED", entitlement_nights_charged=4
    )


def test_the_reinvestment_walk_continues_past_an_unaffordable_leader(api):
    """The 3500-score project is deferred whole and the 2400-score project is funded.

    PRD §3.9: "Starting with the full budget as the remaining amount, the run
    walks the ordered list: when a project's `requested_cost_cents` is no greater
    than the remaining amount, the project becomes `FUNDED`, its
    `funded_amount_cents` is set to its `requested_cost_cents`, and the remaining
    amount is reduced by that figure; when it is greater, the project becomes
    `DEFERRED` with `funded_amount_cents` left at 0 and **the walk continues to
    the next candidate**."

    Design: Corner/calculations/reinvestment_run_funds_by_priority_and_keeps_walking_past_the_unaffordable_leader
    """
    reset_clock(api)
    elk = create_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    pine = create_park(
        api,
        name="Pine Crest Campground",
        park_class="CLASS_C",
        total_sites=20,
        member_allocation_pct=50,
    )
    assert elk["park_status"] == "SEASONAL_CLOSED", "a closed park is still a funding candidate"

    utility = propose_project(
        api,
        elk["id"],
        ADMIN,
        title="Rebuild the water main",
        category="UTILITY",
        requested_cost_cents=4500000,
        fiscal_year=2026,
    )
    safety = propose_project(
        api,
        elk["id"],
        ADMIN,
        title="Replace the fire suppression loop",
        category="SAFETY",
        requested_cost_cents=12000000,
        fiscal_year=2026,
    )
    expansion = propose_project(
        api,
        pine["id"],
        ADMIN,
        title="Add twelve pull-through pads",
        category="EXPANSION",
        requested_cost_cents=3000000,
        fiscal_year=2026,
    )
    # 1.20 * 2.50 * 1.20, 1.40 * 2.50 * 1.00 and 0.80 * 2.50 * 1.20, all scaled by 1000.
    assert utility["priority_score"] == 3600
    assert safety["priority_score"] == 3500
    assert expansion["priority_score"] == 2400

    for project, park_id in (
        (utility, elk["id"]),
        (safety, elk["id"]),
        (expansion, pine["id"]),
    ):
        validate_success(
            api.decide_capital_project(
                project["id"],
                {"decision": "APPROVE", "expected_park_version": read_park(api, park_id)["version"]},
                ADMIN_2,
            ),
            200,
        )

    result = validate_success(
        api.run_reinvestment({"fiscal_year": 2026, "budget_cents": 15000000}, ADMIN), 200
    )

    assert result["allocated_cents"] == 7500000
    assert result["unallocated_cents"] == 7500000
    assert result["funded_project_count"] == 2
    assert result["deferred_project_count"] == 1
    assert_budget_conserved(result)

    funded_utility = read_project(api, utility["id"])
    assert funded_utility["status"] == "FUNDED"
    assert funded_utility["funded_amount_cents"] == 4500000

    deferred_safety = read_project(api, safety["id"])
    assert deferred_safety["status"] == "DEFERRED"
    assert deferred_safety["funded_amount_cents"] == 0, "there is no partial funding"

    funded_expansion = read_project(api, expansion["id"])
    assert funded_expansion["status"] == "FUNDED", (
        "a cheap low-priority project is funded after an expensive leader is skipped"
    )
    assert funded_expansion["funded_amount_cents"] == 3000000

    assert read_park(api, elk["id"])["funded_capital_cents_ytd"] == 4500000
    assert read_park(api, pine["id"])["funded_capital_cents_ytd"] == 3000000


def test_a_stay_landing_exactly_on_the_quota_is_admitted(api):
    """Three nights inflate to five and fill a quota of exactly five.

    PRD §3.2: "Before any such debit is written, the club checks headroom: the
    agreement's current `nights_consumed_ytd` plus the quota nights this stay
    would consume must be no greater than `annual_member_night_quota`."

    Design: Corner/calculations/affiliate_quota_admits_the_stay_that_lands_exactly_on_the_annual_cap
    """
    agreement, park, holder = _partner_park_with_a_five_night_quota(api)

    reservation = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-10", "2026-08-13"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(reservation, "CONFIRMED", entitlement_nights_charged=3)
    assert reservation["affiliate_nights_charged"] == 5, (
        "3 * 1.5 is 4.5 and the ceiling takes it to 5, never a half-up 4"
    )

    after = read_agreement(api, agreement["id"])
    assert after["nights_consumed_ytd"] == 5 == agreement["annual_member_night_quota"]
    assert after["settlement_owed_cents"] == 7500, "5 quota nights at 1500 cents each"
    assert_settlement_derived_from_quota(after)


def test_the_stay_that_would_exceed_the_quota_by_one_night_debits_nothing(api):
    """The refused stay leaves the tally and the settlement byte-identical.

    PRD §3.2: "Landing exactly on the quota is permitted; exceeding it by even
    one night is refused with `ERR_AFFILIATE_QUOTA_EXHAUSTED`."

    Design: Corner/calculations/affiliate_quota_admits_the_stay_that_lands_exactly_on_the_annual_cap
    """
    agreement, park, holder = _partner_park_with_a_five_night_quota(api)
    book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-10", "2026-08-13"
    )
    before = read_agreement(api, agreement["id"])
    assert before["nights_consumed_ytd"] == 5

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-15", "2026-08-16"
        ),
        holder["headers"],
    )
    # 5 + ceil(1 * 1.5) is 7, so the quota gate is the rule that fires.
    validate_error(response, "ERR_AFFILIATE_QUOTA_EXHAUSTED", 422)

    after = read_agreement(api, agreement["id"])
    assert after["nights_consumed_ytd"] == 5, "the refused stay consumed no quota night"
    assert after["settlement_owed_cents"] == 7500, "nor did it move the settlement owed"
    assert read_membership(api, holder["membership_id"])["nights_used_class_b"] == 3, (
        "the entitlement ledger is untouched by the refusal"
    )


def _partner_park_with_a_five_night_quota(api):
    """An ACTIVE agreement whose annual quota is exactly five nights."""
    reset_clock(api)
    tier = create_president_tier(api)
    agreement = create_active_agreement(
        api,
        partner_name="Timberline Partner Network",
        annual_member_night_quota=5,
        reciprocity_ratio=1.5,
        min_tier_rank=2,
        advance_window_cap_days=45,
        per_stay_night_cap=7,
        settlement_rate_cents_per_night=1500,
    )
    park = create_affiliate_open_park(
        api,
        agreement["id"],
        name="Timberline Ridge Partner Park",
        park_class="CLASS_B",
        total_sites=30,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    return agreement, park, holder


def test_the_recency_weight_drops_from_one_to_point_six_on_day_ninety_one(api):
    """One glowing survey walks the 90-day edge and the quotient is rounded once.

    PRD §3.8: "Each survey is weighted by its age in whole days from
    `submitted_at` to the current logical date: a survey aged at most 90 days
    weighs 1.0, one aged at most 365 days weighs 0.6, and anything older weighs
    0.3."

    Design: Corner/calculations/park_rating_decay_weight_drops_at_ninety_one_days_and_the_quotient_is_rounded_once
    """
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    holders = [
        sell_membership_to_new_member(
            api,
            tier["id"],
            member_overrides={"full_name": name, "email": email},
            upfront_paid_cents=1850000,
        )
        for name, email in (
            ("Dana Whitlock", "dana.whitlock@example.com"),
            ("Sergio Alvarado", "sergio.alvarado@example.com"),
            ("Priya Raghavan", "priya.raghavan@example.com"),
        )
    ]
    stay_a = book_member_stay(
        api, holders[0]["headers"], park["id"], holders[0]["membership_id"],
        "2026-08-08", "2026-08-10",
    )
    stay_b = book_member_stay(
        api, holders[1]["headers"], park["id"], holders[1]["membership_id"],
        "2026-11-06", "2026-11-08",
    )
    stay_c = book_member_stay(
        api, holders[2]["headers"], park["id"], holders[2]["membership_id"],
        "2026-11-07", "2026-11-09",
    )

    check_in(api, stay_a["id"], holders[0]["headers"], "2026-08-08T14:00:00Z")
    check_out(api, stay_a["id"], holders[0]["headers"], "2026-08-10", "2026-08-10T09:00:00Z")
    survey_a = submit_survey(
        api,
        stay_a["id"],
        holders[0]["headers"],
        overall_rating=5,
        cleanliness_rating=5,
        staff_rating=5,
        value_rating=5,
    )
    assert_satisfaction_survey(survey_a)
    assert survey_a["weighted_score"] == 5.00
    assert read_park(api, park["id"])["rating_score"] == 5.00, (
        "a lone survey is its own weighted mean whatever its weight"
    )

    check_in(api, stay_b["id"], holders[1]["headers"], "2026-11-06T14:00:00Z")
    check_in(api, stay_c["id"], holders[2]["headers"], "2026-11-07T14:00:00Z")
    check_out(api, stay_b["id"], holders[1]["headers"], "2026-11-08", "2026-11-08T09:00:00Z")
    survey_b = submit_survey(
        api,
        stay_b["id"],
        holders[1]["headers"],
        overall_rating=2,
        cleanliness_rating=3,
        staff_rating=2,
        value_rating=1,
    )
    # 0.40*2 + 0.25*3 + 0.20*2 + 0.15*1 = 2.10, one half-up rounding of the sum.
    assert survey_b["weighted_score"] == 2.10
    assert read_park(api, park["id"])["rating_score"] == 3.55, (
        "on 2026-11-08 survey A is exactly 90 days old, so it still weighs 1.0"
    )

    check_out(api, stay_c["id"], holders[2]["headers"], "2026-11-09", "2026-11-09T09:00:00Z")
    survey_c = submit_survey(
        api,
        stay_c["id"],
        holders[2]["headers"],
        overall_rating=5,
        cleanliness_rating=5,
        staff_rating=5,
        value_rating=5,
    )

    assert survey_c["weighted_score"] == 5.00
    decayed = read_park(api, park["id"])["rating_score"]
    # (0.6*5.00 + 1.0*2.10 + 1.0*5.00) / 2.6 == 3.884615..., rounded half up once.
    assert decayed == 3.88, "on 2026-11-09 survey A is 91 days old and drops to weight 0.6"
    assert decayed != 4.03, "an unweighted lifetime mean of 5.00, 2.10 and 5.00 would read 4.03"


def test_waitlist_promotion_orders_by_created_at_not_by_arrival_date(api):
    """The later-arriving stay is promoted because it was created first.

    PRD §3.6: "Candidates are ordered by `created_at` ascending, and where two
    share the same `created_at` the earlier `arrival_date` wins."

    Design: Corner/calculations/waitlist_promotion_picks_the_earliest_created_waitlisted_stay_not_the_earliest_arrival
    """
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Pine Crest Campground",
        park_class="CLASS_C",
        total_sites=3,
        member_allocation_pct=60,
    )
    # floor(3 * 60 / 100) is one member pad; the other two sites are the transient pool.
    assert_pool_split(park, member_sites=1, transient_sites=2)
    holders = [
        sell_membership_to_new_member(
            api,
            tier["id"],
            member_overrides={"full_name": name, "email": email},
            upfront_paid_cents=1850000,
        )
        for name, email in (
            ("Dana Whitlock", "dana.whitlock@example.com"),
            ("Sergio Alvarado", "sergio.alvarado@example.com"),
            ("Priya Raghavan", "priya.raghavan@example.com"),
        )
    ]
    seated, early_arrival, early_created = holders

    walk_up = book_transient_stay(
        api, park["id"], "2026-08-09", "2026-08-13", guest_name="Walk-up guest Nolan"
    )
    assert_reservation_state(walk_up, "CONFIRMED", pool_charged="TRANSIENT_POOL")

    holder_stay = book_member_stay(
        api, seated["headers"], park["id"], seated["membership_id"], "2026-08-10", "2026-08-13"
    )
    assert_reservation_state(
        holder_stay, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )

    set_clock(api, "2026-08-01T02:00:00Z")
    first_created = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], early_created["membership_id"], "2026-08-10", "2026-08-13"
            ),
            early_created["headers"],
        ),
        201,
    )
    assert_waitlisted_debits_nothing(first_created)

    set_clock(api, "2026-08-01T06:00:00Z")
    earliest_arrival = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], early_arrival["membership_id"], "2026-08-09", "2026-08-13"
            ),
            early_arrival["headers"],
        ),
        201,
    )
    assert_waitlisted_debits_nothing(earliest_arrival)

    released = validate_success(
        api.cancel_reservation(holder_stay["id"], seated["headers"]), 200
    )
    assert_reservation_state(
        released, "CANCELLED", pool_charged="NONE", entitlement_nights_charged=0
    )

    promoted = read_reservation(api, first_created["id"])
    assert_reservation_state(
        promoted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )
    assert read_membership(api, early_created["membership_id"])["nights_used_class_c"] == 3

    skipped = read_reservation(api, earliest_arrival["id"])
    assert_waitlisted_debits_nothing(skipped)
    assert skipped["status"] != "EXPIRED", "the promotion sweep never expires anyone"
    assert read_membership(api, early_arrival["membership_id"])["nights_used_class_c"] == 0


def test_the_three_transfer_types_price_off_one_tier_fee(api):
    """A gift halves the fee, an estate zeroes it, and a resale adds its own rounding.

    PRD §3.8: "The base component is the tier's `transfer_fee_cents` multiplied by
    that type multiplier, rounded half up to whole cents. The resale surcharge is
    the submitted `sale_price_cents` multiplied by the resale surcharge rate of 6
    percent, rounded half up to whole cents, and is 0 for any transfer type other
    than `RESALE`."

    Design: Corner/calculations/transfer_fee_type_multiplier_and_resale_surcharge_are_rounded_independently
    """
    reset_clock(api)
    tier = create_president_tier(api)
    gift_holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    resale_holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Sergio Alvarado", "email": "sergio.alvarado@example.com"},
        upfront_paid_cents=1850000,
    )
    estate_holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Priya Raghavan", "email": "priya.raghavan@example.com"},
        upfront_paid_cents=1850000,
    )
    receivers = [
        create_member(api, full_name=name, email=email)
        for name, email in (
            ("Nathan Boyle", "nathan.boyle@example.com"),
            ("Grace Okafor", "grace.okafor@example.com"),
            ("Tomas Iglesias", "tomas.iglesias@example.com"),
        )
    ]
    # One day past purchased_at plus the 730-day resale hold, so a RESALE is admissible.
    set_clock(api, "2028-08-01T00:00:00Z")

    gift = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                gift_holder["membership_id"], receivers[0]["id"], "GIFT", 1
            ),
            gift_holder["headers"],
        ),
        201,
    )
    resale = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                resale_holder["membership_id"],
                receivers[1]["id"],
                "RESALE",
                1,
                sale_price_cents=1200000,
            ),
            resale_holder["headers"],
        ),
        201,
    )
    estate = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                estate_holder["membership_id"], receivers[2]["id"], "ESTATE", 1
            ),
            estate_holder["headers"],
        ),
        201,
    )

    assert gift["transfer_fee_cents"] == 47500, "round_half_up(95000 * 0.50) and no surcharge"
    assert resale["transfer_fee_cents"] == 167000, (
        "95000 from the full multiplier plus a separately rounded 72000 surcharge"
    )
    assert estate["transfer_fee_cents"] == 0, "an estate succession is free of the base fee"

    for request, holder, receiver in (
        (gift, gift_holder, receivers[0]),
        (resale, resale_holder, receivers[1]),
        (estate, estate_holder, receivers[2]),
    ):
        assert request["status"] == "SUBMITTED"
        assert request["from_member_id"] == holder["member_id"]
        assert request["to_member_id"] == receiver["id"]
        assert request["successor_membership_id"] is None
        frozen = read_membership(api, holder["membership_id"])
        assert frozen["membership_status"] == "TRANSFER_PENDING"
        assert frozen["version"] == 2, "a submission increments the membership version by exactly 1"
