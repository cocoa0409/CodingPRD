"""Rental offers: fee schedule, negotiation cycle, OCC, ownership, and SoD settle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_rental_offer,
    assert_rental_offer,
    assert_version_incremented,
    counter_rental_offer,
    create_partner_company,
    create_production,
    create_rental_offer,
    create_rental_offer_payload,
    decline_rental_offer,
    get_production,
    get_rental_offer,
    make_partner_representative_headers,
    make_production_manager_headers,
    revise_rental_offer,
    send_rental_offer,
    set_clock,
    set_partner_standing,
    setup_sent_offer,
    validate_error,
    validate_success,
)

PM = TEST_USERS["production_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestRentalFeeSchedule:
    def test_rental_fee_below_threshold_no_surcharge(self, api):
        """PRD §3.9: "The `fee_base_cents` is the `performances_count` times the `per_performance_fee_cents`. The `surcharge_pct` keys on the fee base only, never on the total: it is 0 when the fee base is below 5,000,000 cents and 8 once the fee base reaches 5,000,000 cents. The `total_fee_cents` is the fee base plus the fee base times the surcharge percentage divided by one hundred, rounded half up to whole cents at this final step."

        7 performances @ 700,000 -> fee base 4,900,000, below the threshold, so
        the surcharge is 0 and the total equals the base exactly.

        Design: Difficulty/combinatorial_formula/rental_fee_tier_keyed_on_base_not_total
        """
        scenario = setup_sent_offer(performances_count=7, per_performance_fee_cents=700_000)
        offer = scenario["offer"]
        assert offer["fee_base_cents"] == 4_900_000, "7 * 700,000"
        assert offer["surcharge_pct"] == 0, "fee base below the 5,000,000 threshold"
        assert offer["total_fee_cents"] == 4_900_000, "tier keyed on base, not total"

    def test_rental_fee_at_threshold_applies_surcharge(self, api):
        """PRD §3.9: "The `surcharge_pct` keys on the fee base only, never on the total: it is 0 when the fee base is below 5,000,000 cents and 8 once the fee base reaches 5,000,000 cents. The `total_fee_cents` is the fee base plus the fee base times the surcharge percentage divided by one hundred, rounded half up to whole cents at this final step."

        8 performances @ 700,000 -> fee base 5,600,000, at/above the threshold,
        so the surcharge is 8 and the total is 5,600,000 + 448,000 = 6,048,000.

        Design: Difficulty/combinatorial_formula/rental_fee_tier_keyed_on_base_not_total
        """
        scenario = setup_sent_offer(performances_count=8, per_performance_fee_cents=700_000)
        offer = scenario["offer"]
        assert offer["fee_base_cents"] == 5_600_000, "8 * 700,000"
        assert offer["surcharge_pct"] == 8, "fee base reaches the 5,000,000 threshold"
        assert offer["total_fee_cents"] == 6_048_000, (
            "5,600,000 + round_half_up(5,600,000 * 8 / 100)"
        )


class TestNegotiationCycle:
    def test_negotiation_cycle_two_full_rounds(self, api):
        """PRD §3.9: "Countering — `SENT` → `COUNTERED` — submits a `countered_fee_cents` total and is allowed only while `negotiation_rounds` is below the hard cap of five; a counter at the cap is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422). The manager answers a counter by revising: submitting a new `per_performance_fee_cents` moves `COUNTERED` back to `SENT`, increments `negotiation_rounds` by one, and recomputes the whole fee schedule from the revised per-performance fee."

        Two full SENT -> COUNTERED -> SENT loops leave the offer SENT with
        negotiation_rounds 2; the revised fee 7 * 650,000 = 4,550,000 stays
        below the surcharge threshold.

        Design: Difficulty/non_linear_state_machine/rental_offer_negotiation_cycle
        """
        scenario = setup_sent_offer(performances_count=7, per_performance_fee_cents=700_000)
        offer = scenario["offer"]
        renter = scenario["renter"]

        counter_rental_offer(offer["id"], renter["id"], 4_200_000)
        revise_rental_offer(offer["id"], 650_000)
        counter_rental_offer(offer["id"], renter["id"], 4_300_000)
        revised = revise_rental_offer(offer["id"], 650_000)

        assert revised["status"] == "SENT", "after two full SENT->COUNTERED->SENT loops"
        assert revised["negotiation_rounds"] == 2, "incremented by revise only"
        assert revised["total_fee_cents"] == 4_550_000, (
            "7 * 650,000 base, below threshold, no surcharge"
        )

    def test_counter_does_not_increment_negotiation_rounds(self, api):
        """PRD §3.9: "A new offer is a `DRAFT`."
        PRD §3.9: "the offer's `negotiation_rounds` starts at zero"
        PRD §3.9: "The manager answers a counter by revising: submitting a new `per_performance_fee_cents` moves `COUNTERED` back to `SENT`, increments `negotiation_rounds` by one, and recomputes the whole fee schedule from the revised per-performance fee."

        The counter itself moves SENT -> COUNTERED without touching the round
        counter; only the revise increments it.

        Design: Difficulty/non_linear_state_machine/rental_offer_negotiation_cycle
        """
        scenario = setup_sent_offer(performances_count=7, per_performance_fee_cents=700_000)
        offer = scenario["offer"]
        renter = scenario["renter"]
        assert offer["negotiation_rounds"] == 0, "rounds start at zero"

        countered = counter_rental_offer(offer["id"], renter["id"], 4_200_000)
        assert countered["status"] == "COUNTERED"
        assert countered["negotiation_rounds"] == 0, (
            "countering does not increment negotiation_rounds"
        )
        assert countered["countered_fee_cents"] == 4_200_000

        revised = revise_rental_offer(offer["id"], 650_000)
        assert revised["negotiation_rounds"] == 1, "the revise increments the counter"


class TestNegotiationRoundCap:
    def test_rental_negotiation_round_limit_rejected(self, api):
        """PRD §3.9: "Countering — `SENT` → `COUNTERED` — submits a `countered_fee_cents` total and is allowed only while `negotiation_rounds` is below the hard cap of five; a counter at the cap is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422)."

        Five full counter/revise rounds succeed; the sixth counter, attempted
        while negotiation_rounds == 5, is rejected.

        Design: Corner/calculations/rental_negotiation_round_limit_rejected
        """
        scenario = setup_sent_offer(performances_count=5, per_performance_fee_cents=500_000)
        offer = scenario["offer"]
        renter = scenario["renter"]

        counters = [2_200_000, 2_250_000, 2_300_000, 2_350_000, 2_400_000]
        fees = [490_000, 480_000, 470_000, 460_000, 450_000]
        for countered_fee, revised_fee in zip(counters, fees):
            counter_rental_offer(offer["id"], renter["id"], countered_fee)
            revise_rental_offer(offer["id"], revised_fee)

        current = get_rental_offer(offer["id"])
        assert current["negotiation_rounds"] == 5, "five revise rounds completed"
        assert current["status"] == "SENT"

        resp = api.counter_rental_offer(
            offer["id"], 2_450_000, make_partner_representative_headers(renter["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)


class TestAcceptStandingGate:
    def test_accept_rejected_at_watch_then_succeeds_at_good(self, api):
        """PRD §3.9: "The renter may instead accept — `SENT` → `ACCEPTED` — which additionally requires the renter company's `standing` to be `GOOD`, else `ERR_RENTER_STANDING_NOT_GOOD` (HTTP 409), or decline — `SENT` → `DECLINED`, or from a countered offer `COUNTERED` → `DECLINED`."
        PRD §3.1: "Standing is a simple administrative flag that a `PlatformAdmin` moves among `GOOD`, `WATCH`, and `BARRED` by submitting a `to_state` to the standing-change action; all three values are reachable from any other."

        Design: Difficulty/cross_entity_state_dependency/rental_accept_requires_renter_good_standing
        """
        scenario = setup_sent_offer()
        offer = scenario["offer"]
        renter = scenario["renter"]
        renter_headers = make_partner_representative_headers(renter["id"])

        set_partner_standing(renter["id"], "WATCH")
        resp = api.accept_rental_offer(offer["id"], renter_headers)
        validate_error(resp, ApiErrorId.ERR_RENTER_STANDING_NOT_GOOD)

        set_partner_standing(renter["id"], "GOOD")
        resp = api.accept_rental_offer(offer["id"], renter_headers)
        accepted = validate_success(resp, 200)
        assert accepted["status"] == "ACCEPTED"

    def test_accept_rejected_at_barred(self, api):
        """PRD §3.1: "Standing has exactly one business consequence: a renter whose standing is not `GOOD` cannot accept a rental offer (§3.9)."
        PRD §3.9: "The renter may instead accept — `SENT` → `ACCEPTED` — which additionally requires the renter company's `standing` to be `GOOD`, else `ERR_RENTER_STANDING_NOT_GOOD` (HTTP 409), or decline — `SENT` → `DECLINED`, or from a countered offer `COUNTERED` → `DECLINED`."

        Design: Difficulty/cross_entity_state_dependency/rental_accept_requires_renter_good_standing
        """
        scenario = setup_sent_offer()
        offer = scenario["offer"]
        renter = scenario["renter"]

        set_partner_standing(renter["id"], "BARRED")
        resp = api.accept_rental_offer(
            offer["id"], make_partner_representative_headers(renter["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_STANDING_NOT_GOOD)
        after = get_rental_offer(offer["id"])
        assert after["status"] == "SENT", "rejected accept leaves the offer SENT"


class TestTerminalLockdown:
    def test_declined_offer_terminal_lockdown_rejected(self, api):
        """PRD §3.9: "Every one of these renter actions enforces ownership, rejecting a mismatched caller with `ERR_RENTER_OWNERSHIP_MISMATCH`; and any offer action attempted from a status that does not support it — sending a non-`DRAFT`, countering or accepting or declining a non-`SENT`, settling a non-`ACCEPTED` — is rejected with `ERR_OFFER_NOT_ACTIONABLE` (HTTP 409)."
        PRD §3.9: "`DECLINED`, `WITHDRAWN`, and `SUPERSEDED` are likewise terminal."

        Design: Corner/state_machines/declined_offer_terminal_lockdown_rejected
        """
        scenario = setup_sent_offer(performances_count=4, per_performance_fee_cents=500_000)
        offer = scenario["offer"]
        renter = scenario["renter"]
        decline_rental_offer(offer["id"], renter["id"])

        resp = api.send_rental_offer(offer["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ACTIONABLE)
        after = get_rental_offer(offer["id"])
        assert after["status"] == "DECLINED", "terminal state is not disturbed"


class TestSupersede:
    def test_new_offer_supersedes_prior_sent_offer(self, api):
        """PRD §3.9: "Creation has three side effects beyond the offer row itself: the production's `version` increments by one; any prior offer for the same production and the same renter still sitting in `SENT` or `COUNTERED` is automatically moved to `SUPERSEDED` by the system; and the offer's `negotiation_rounds` starts at zero while `created_by_user_id` records the creating manager's `X-User-ID`."

        Design: Corner/state_machines/new_offer_supersedes_prior_sent_offer
        """
        scenario = setup_sent_offer(performances_count=4, per_performance_fee_cents=500_000)
        offer_a = scenario["offer"]
        renter = scenario["renter"]
        production = scenario["production"]

        before = get_production(production["id"])
        offer_b = create_rental_offer(
            production["id"], renter["id"],
            window_start="2026-10-01T00:00:00Z", window_end="2026-10-31T00:00:00Z",
            performances_count=6, per_performance_fee_cents=600_000,
        )
        assert_rental_offer(offer_b)
        assert offer_b["status"] == "DRAFT"

        after_a = get_rental_offer(offer_a["id"])
        assert after_a["status"] == "SUPERSEDED", (
            "the prior SENT offer is superseded by the system"
        )

        production_after = get_production(production["id"])
        assert_version_incremented(production_after["version"], before["version"], 1)
        assert production_after["version"] == before["version"] + 1, (
            "the production's version increments by exactly one per offer create"
        )


class TestOptimisticConcurrency:
    def test_rental_offer_create_stale_version_rejected(self, api):
        """PRD §2.7: "The request must carry `expected_production_version`, a non-optional field holding the client's last observed `version` of the target production. If the value does not match the production's current `version` — because another writer has advanced the production since the client last read it, for example by creating an offer for the same renter, which legitimately supersedes the prior open offer and advances the production's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "any prior offer for the same production and the same renter still sitting in `SENT` or `COUNTERED` is automatically moved to `SUPERSEDED` by the system"

        Offer A stays DRAFT, so no supersede fires; the stale create is rejected
        and the refreshed create succeeds.

        Design: Corner/cross_cutting_layers/rental_offer_create_stale_version_rejected
        """
        renter = create_partner_company(name="TourCo", partner_kind="RENTER")
        production = create_production(title="Nutcracker", build_budget_cents=40_000_000)
        stale_version = production["version"]

        offer_a = create_rental_offer(production["id"], renter["id"],
                                      performances_count=4,
                                      per_performance_fee_cents=500_000)

        payload = create_rental_offer_payload(
            production["id"], renter["id"],
            expected_production_version=stale_version,
            window_start="2026-10-01T00:00:00Z", window_end="2026-10-31T00:00:00Z",
            performances_count=6, per_performance_fee_cents=600_000,
        )
        resp = api.create_rental_offer(payload, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_production(production["id"])
        payload["expected_production_version"] = fresh["version"]
        resp = api.create_rental_offer(payload, PM)
        offer_b = validate_success(resp, 201)
        assert offer_b["status"] == "DRAFT"

        after_a = get_rental_offer(offer_a["id"])
        assert after_a["status"] == "DRAFT", (
            "offer A was never SENT or COUNTERED, so no supersede fired"
        )


class TestRenterOwnership:
    def test_renter_ownership_mismatch_rejected(self, api):
        """PRD §2.1: "The remaining role is entity-backed: when `X-User-Role` is `PartnerRepresentative`, `X-User-ID` is the `id` of the acting `PartnerCompany`, and ownership checks on any resource that references a `PartnerCompany` compare the resource's foreign-key field — `renter_company_id` on a rental offer — to `X-User-ID`. A `PartnerRepresentative` whose `X-User-ID` does not equal the offer's `renter_company_id` is rejected with `ERR_RENTER_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/renter_ownership_mismatch_rejected
        """
        scenario = setup_sent_offer(performances_count=4, per_performance_fee_cents=500_000,
                                    renter_name="TourCo A")
        offer = scenario["offer"]
        renter_b = create_partner_company(name="TourCo B", partner_kind="RENTER")

        resp = api.counter_rental_offer(
            offer["id"], 1_800_000, make_partner_representative_headers(renter_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_OWNERSHIP_MISMATCH)
        after = get_rental_offer(offer["id"])
        assert after["status"] == "SENT", "mismatched caller cannot move the offer"


class TestSettleSegregationOfDuties:
    def test_sod_settle_same_user_forbidden(self, api):
        """PRD §2.10: "Settling an accepted rental offer must be performed by a `ProductionManager` whose `X-User-ID` differs from the `created_by_user_id` recorded on the offer. Either violation is rejected with `ERR_SOD_SAME_USER_FORBIDDEN` (HTTP 403)."
        PRD §3.9: "The `final_settlement_cents` is the `countered_fee_cents` when at least one negotiation round occurred — that is, whenever `negotiation_rounds` is above zero — and the `total_fee_cents` when none did; the offer lands in its `SETTLED` terminal state."

        Manager pm-1 creates the offer; with the window ended, pm-1's settle is
        rejected and pm-2's succeeds at the full fee (no counter rounds):
        5 * 500,000 = 2,500,000.

        Design: Corner/rbac/sod_settle_same_user_forbidden
        """
        scenario = setup_sent_offer(performances_count=5, per_performance_fee_cents=500_000,
                                    manager_user_id="pm-1")
        offer = scenario["offer"]
        renter = scenario["renter"]

        accept_rental_offer(offer["id"], renter["id"])
        set_clock("2026-10-01T00:00:00Z")

        pm1 = make_production_manager_headers("pm-1")
        pm2 = make_production_manager_headers("pm-2")
        resp = api.settle_rental_offer(offer["id"], pm1)
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_USER_FORBIDDEN)

        resp = api.settle_rental_offer(offer["id"], pm2)
        settled = validate_success(resp, 200)
        assert settled["status"] == "SETTLED"
        assert settled["final_settlement_cents"] == 2_500_000, (
            "no negotiation rounds: final settlement is the total fee 5 * 500,000"
        )
