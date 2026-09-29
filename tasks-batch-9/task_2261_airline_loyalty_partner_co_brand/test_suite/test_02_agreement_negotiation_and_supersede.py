"""Mile sale agreement negotiation laps and the superseding-ratification cascade.

Each test drives the real negotiation endpoints from an empty database, because
the service is restarted before every individual test.
"""
from test_helpers import (
    CONTRACTS_OFFICER_USER_ID,
    PARTNER_MANAGER,
    PARTNER_MANAGER_USER_ID,
    activate_agreement,
    assert_co_brand_issuer,
    assert_mile_sale_agreement,
    counter_agreement,
    create_issuer,
    create_order,
    create_program,
    draft_agreement,
    issue_order,
    ratify_agreement,
    read_agreement,
    read_program,
    revise_agreement,
    submit_agreement,
    tier_schedule,
    validate_success,
)


def _agreement_after_one_completed_lap():
    """Programme, issuer and an agreement back in DRAFT after one full lap.

    The lap runs DRAFT -> ISSUER_REVIEW -> COUNTERED -> DRAFT, so the returned
    agreement has already been countered once and revised once.
    """
    program = create_program(name="SkyMiles Negotiation", current_period="2026-08")
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=10_000_000,
    )
    agreement = draft_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=6_000_000,
        tier_schedule=tier_schedule((0, 170), (2_000_000, 155)),
    )
    submit_agreement(agreement["id"])
    counter_agreement(
        agreement["id"], issuer["id"], 150, 5_000_000, note="first counter"
    )
    revise_agreement(
        agreement["id"],
        5_500_000,
        tier_schedule((0, 165), (2_000_000, 150)),
    )
    return program, issuer, agreement


def _second_lap_then_ratify(agreement_id, issuer_id):
    """Run a second counter/revise lap and ratify the third submission."""
    submit_agreement(agreement_id)
    counter_agreement(
        agreement_id, issuer_id, 145, 4_800_000, note="second counter"
    )
    revise_agreement(
        agreement_id,
        5_000_000,
        tier_schedule((0, 160), (2_000_000, 148)),
    )
    submit_agreement(agreement_id)
    return ratify_agreement(agreement_id)


class TestNegotiationRoundCycle:
    """The agreement returns to DRAFT twice before it is ratified."""

    def test_each_completed_lap_increments_the_negotiation_round(self):
        """PRD §3.2: "A drafted agreement starts in `DRAFT` with `negotiation_round` at 1, both counter fields (`countered_price_per_mile_centicents` and `countered_committed_volume_miles`) null, `ratified_by_user_id` null, and `drawn_miles` and `prepayment_balance_miles` at zero."
        PRD §3.2: "The airline answers a counter by revising, which returns the agreement `COUNTERED → DRAFT`, replaces `tier_schedule` and `committed_volume_miles` wholesale from the request, increases `negotiation_round` by exactly one, and re-stamps `negotiated_by_user_id` with the revising `PartnerManager`."
        PRD §3.2: "Each lap of `DRAFT → ISSUER_REVIEW → COUNTERED → DRAFT` therefore leaves an audit trail in `negotiation_round`, and the round counter never resets."
        PRD §3.2: "A `ContractsOfficer` ratifies an agreement sitting in `ISSUER_REVIEW`, advancing it `ISSUER_REVIEW → RATIFIED`."

        Design: Difficulty/non_linear_state_machine/mile_sale_agreement_counter_revise_negotiation_cycle
        """
        _, issuer, agreement = _agreement_after_one_completed_lap()

        after_one_lap = read_agreement(agreement["id"])
        assert after_one_lap["negotiation_round"] == 2, (
            "one completed lap lifts negotiation_round from 1 to 2, got "
            f"{after_one_lap['negotiation_round']}"
        )
        assert after_one_lap["status"] == "DRAFT", (
            f"revising returns the agreement to DRAFT, got {after_one_lap['status']}"
        )

        ratified = _second_lap_then_ratify(agreement["id"], issuer["id"])

        assert_mile_sale_agreement(ratified)
        assert ratified["negotiation_round"] == 3, (
            "a second lap lifts negotiation_round to exactly 3, got "
            f"{ratified['negotiation_round']}"
        )
        assert ratified["status"] == "RATIFIED", (
            "the third submission is ratified out of ISSUER_REVIEW, got "
            f"{ratified['status']}"
        )
        assert ratified["committed_volume_miles"] == 5000000, (
            "the last revision replaced committed_volume_miles wholesale with "
            f"5000000, got {ratified['committed_volume_miles']}"
        )

    def test_the_last_counter_and_both_actor_stamps_survive_ratification(self):
        """PRD §3.2: "The issuer's own representative may then push back, advancing `ISSUER_REVIEW → COUNTERED` and stamping `countered_price_per_mile_centicents` and `countered_committed_volume_miles` from the request's `counter_price_per_mile_centicents` and `counter_committed_volume_miles`, with an optional free-text `note`."
        PRD §3.2: "It stamps `negotiated_by_user_id` with the submitting operator's `X-User-ID` — the value against which segregation of duties will later be measured."
        PRD §3.2: "When ratification proceeds it stamps `ratified_by_user_id` from `X-User-ID` and then propagates in three hops."

        Design: Difficulty/non_linear_state_machine/mile_sale_agreement_counter_revise_negotiation_cycle
        """
        _, issuer, agreement = _agreement_after_one_completed_lap()

        ratified = _second_lap_then_ratify(agreement["id"], issuer["id"])

        assert ratified["countered_committed_volume_miles"] == 4800000, (
            "the second counter's volume of 4800000 miles stays stamped on the row, "
            f"got {ratified['countered_committed_volume_miles']}"
        )
        assert ratified["countered_price_per_mile_centicents"] == 145, (
            "the second counter's price of 145 centicents stays stamped on the row, "
            f"got {ratified['countered_price_per_mile_centicents']}"
        )
        assert ratified["negotiated_by_user_id"] == PARTNER_MANAGER_USER_ID, (
            "negotiated_by_user_id carries the submitting partner manager "
            f"{PARTNER_MANAGER_USER_ID}, got {ratified['negotiated_by_user_id']}"
        )
        assert ratified["ratified_by_user_id"] == CONTRACTS_OFFICER_USER_ID, (
            "ratified_by_user_id carries the ratifying contracts officer "
            f"{CONTRACTS_OFFICER_USER_ID}, got {ratified['ratified_by_user_id']}"
        )

    def test_ratification_lifts_the_issuer_aggregate_without_suspending_it(self, api):
        """PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."
        PRD §3.2: "The third hop, caused by the second, tests the newly recomputed aggregate against a utilisation alarm set at 9000 basis points of the cap, that is at ninety percent of `annual_mile_purchase_cap_miles` after rounding half up, with the boundary inclusive: when the recomputed `aggregate_committed_miles` reaches or exceeds that figure, the issuer's `status` becomes `SUSPENDED` and its `suspension_reason` becomes `CAP_BREACH`."

        Design: Difficulty/non_linear_state_machine/mile_sale_agreement_counter_revise_negotiation_cycle
        """
        _, issuer, agreement = _agreement_after_one_completed_lap()

        before = validate_success(api.get_co_brand_issuer(issuer["id"], PARTNER_MANAGER))
        assert before["aggregate_committed_miles"] == 0, (
            "a DRAFT agreement does not count toward the issuer's aggregate, got "
            f"{before['aggregate_committed_miles']}"
        )

        _second_lap_then_ratify(agreement["id"], issuer["id"])

        after = validate_success(api.get_co_brand_issuer(issuer["id"], PARTNER_MANAGER))
        assert_co_brand_issuer(after)
        assert after["aggregate_committed_miles"] == 5000000, (
            "the ratified agreement's 5000000 committed miles are the whole aggregate, "
            f"got {after['aggregate_committed_miles']}"
        )
        assert after["status"] == "ACTIVE", (
            "5000000 miles is below ninety percent of the 10000000-mile cap, so the "
            f"issuer stays ACTIVE, got {after['status']}"
        )


class TestSupersedingRatificationCascade:
    """Ratifying a successor terminates, sweeps, recomputes and suspends."""

    def _predecessor_and_successor(self):
        program = create_program(name="SkyMiles Supersede", current_period="2026-08")
        issuer = create_issuer(
            program["id"],
            name="Northbank Card Services",
            annual_mile_purchase_cap_miles=7_500_000,
        )
        first = draft_agreement(
            issuer["id"],
            term_start_date="2026-09-01",
            term_end_date="2027-08-31",
            committed_volume_miles=6_000_000,
            tier_schedule=tier_schedule((0, 150)),
        )
        submit_agreement(first["id"])
        ratify_agreement(first["id"])
        activated = activate_agreement(first["id"])
        order = create_order(first["id"], 1_000_000, activated["version"])
        issue_order(order["id"])

        second = draft_agreement(
            issuer["id"],
            term_start_date="2027-09-01",
            term_end_date="2028-08-31",
            committed_volume_miles=7_000_000,
            supersedes_agreement_id=first["id"],
            tier_schedule=tier_schedule((0, 140)),
        )
        submit_agreement(second["id"])
        return program, issuer, first, second, order

    def test_ratifying_the_successor_terminates_and_sweeps_the_predecessor(self):
        """PRD §3.2: "The first hop applies only when `supersedes_agreement_id` is set: the superseded agreement transitions `ACTIVE → TERMINATED`."
        PRD §3.2: "The second hop, caused by the first, moves the terminated agreement's entire `prepayment_balance_miles` onto the ratifying agreement and sets the terminated agreement's balance to zero — miles the issuer has already paid for survive the contract change — and recomputes the issuer's `aggregate_committed_miles` over agreements whose `status` is `RATIFIED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/agreement_ratification_supersede_cascade
        """
        _, _, first, second, _ = self._predecessor_and_successor()

        ratified = ratify_agreement(second["id"])

        assert_mile_sale_agreement(ratified)
        assert ratified["status"] == "RATIFIED", (
            f"the successor lands in RATIFIED, got {ratified['status']}"
        )
        assert ratified["prepayment_balance_miles"] == 1000000, (
            "the predecessor's 1000000 prepaid miles are swept onto the successor, got "
            f"{ratified['prepayment_balance_miles']}"
        )

        predecessor = read_agreement(first["id"])
        assert predecessor["status"] == "TERMINATED", (
            "the superseded agreement moves ACTIVE -> TERMINATED, got "
            f"{predecessor['status']}"
        )
        assert predecessor["prepayment_balance_miles"] == 0, (
            "the terminated agreement's prepayment balance is set to zero, got "
            f"{predecessor['prepayment_balance_miles']}"
        )

    def test_the_recomputed_aggregate_crosses_the_alarm_and_suspends_the_issuer(self, api):
        """PRD §3.2: "The third hop, caused by the second, tests the newly recomputed aggregate against a utilisation alarm set at 9000 basis points of the cap, that is at ninety percent of `annual_mile_purchase_cap_miles` after rounding half up, with the boundary inclusive: when the recomputed `aggregate_committed_miles` reaches or exceeds that figure, the issuer's `status` becomes `SUSPENDED` and its `suspension_reason` becomes `CAP_BREACH`."
        PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."

        Design: Difficulty/transitive_cascade/agreement_ratification_supersede_cascade
        """
        _, issuer, _, second, _ = self._predecessor_and_successor()

        before = validate_success(api.get_co_brand_issuer(issuer["id"], PARTNER_MANAGER))
        assert before["aggregate_committed_miles"] == 6000000, (
            "only the active predecessor counts before ratification, got "
            f"{before['aggregate_committed_miles']}"
        )
        assert before["status"] == "ACTIVE", (
            "6000000 miles sits below the 6750000-mile alarm, so the issuer is still "
            f"ACTIVE, got {before['status']}"
        )

        ratify_agreement(second["id"])

        after = validate_success(api.get_co_brand_issuer(issuer["id"], PARTNER_MANAGER))
        assert_co_brand_issuer(after)
        assert after["aggregate_committed_miles"] == 7000000, (
            "the terminated predecessor drops out and the ratified successor's "
            f"7000000 miles remain, got {after['aggregate_committed_miles']}"
        )
        assert after["status"] == "SUSPENDED", (
            "7000000 miles reaches ninety percent of the 7500000-mile cap, so the "
            f"issuer is suspended, got {after['status']}"
        )
        assert after["suspension_reason"] == "CAP_BREACH", (
            "an automatic suspension records CAP_BREACH, got "
            f"{after['suspension_reason']}"
        )

    def test_the_predecessor_draw_and_the_programme_ledger_are_left_alone(self):
        """PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."
        PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."

        Design: Difficulty/transitive_cascade/agreement_ratification_supersede_cascade
        """
        program, _, first, second, order = self._predecessor_and_successor()

        assert order["gross_amount_cents"] == 1500000, (
            "1000000 miles at 150 centicents is 1500000 cents, got "
            f"{order['gross_amount_cents']}"
        )

        ratify_agreement(second["id"])

        predecessor = read_agreement(first["id"])
        assert predecessor["drawn_miles"] == 1000000, (
            "the cascade sweeps the prepayment balance but leaves the 1000000 drawn "
            f"miles on the terminated agreement, got {predecessor['drawn_miles']}"
        )
        assert read_program(program["id"])["deferred_revenue_cents"] == 1500000, (
            "the 1500000 cents credited at issuance stay in programme deferred revenue"
        )
