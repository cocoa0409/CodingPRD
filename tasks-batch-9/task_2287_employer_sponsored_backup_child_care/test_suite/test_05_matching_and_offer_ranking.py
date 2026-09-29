"""The ranking expression, the offer cycle and the empty-candidate-pool fallback."""

from typing import Any, Dict

import pytest
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_match_offer,
    assert_offer_ordering,
    assert_rank_components,
    create_capacity_block,
    create_reservation,
    find_offer_for_provider,
    match_reservation,
    read_entitlement,
    read_offers_for_reservation,
    read_reservation,
    reject_offer,
    selected_offer,
    set_network_status,
    setup_credentialed_provider,
    setup_enrolled_employee,
    setup_offered_reservation,
    substantiated_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]

BLOCK_START = "2026-08-10T08:00:00Z"
BLOCK_END = "2026-08-10T18:00:00Z"
CARE_START = "2026-08-10T09:00:00Z"
CARE_END = "2026-08-10T13:00:00Z"


def _three_provider_world(api) -> Dict[str, Any]:
    """Alpha on probation at quality 100, Beta in-home at 88, Gamma centre at 96."""
    world = setup_enrolled_employee(
        api, dependent_count=1, plan_overrides={"annual_use_limit_days": 10}
    )

    alpha = setup_credentialed_provider(
        api,
        provider_name="Alpha Center",
        owner_user_id="u_pm_a",
        care_mode="CENTER_BASED",
        market_code="MKT-BOS",
        postal_code="02110",
        daily_capacity_slots=10,
        max_concurrent_assignments=1,
    )
    alpha_block = create_capacity_block(
        api, alpha["provider"]["id"], BLOCK_START, BLOCK_END, total_slots=10
    )
    set_network_status(api, alpha["provider"]["id"], "PROBATION", reason_code="QA_WATCHLIST")

    beta = setup_credentialed_provider(
        api,
        provider_name="Beta Home Aides",
        owner_user_id="u_pm_b",
        care_mode="IN_HOME",
        market_code="MKT-BOS",
        postal_code="02112",
        daily_capacity_slots=1,
        max_concurrent_assignments=1,
    )
    beta_block = create_capacity_block(
        api, beta["provider"]["id"], BLOCK_START, BLOCK_END, total_slots=1
    )
    substantiated_incident(
        api,
        beta["provider"]["id"],
        "MODERATE",
        filer_user_id="u_cc_b",
        category="CONDUCT",
        narrative="Aide arrived 40 minutes late without notice.",
        resolution_reason_code="COACHING_ISSUED",
    )

    gamma = setup_credentialed_provider(
        api,
        provider_name="Gamma Center",
        owner_user_id="u_pm_c",
        care_mode="CENTER_BASED",
        market_code="MKT-BOS",
        postal_code="02113",
        daily_capacity_slots=2,
        max_concurrent_assignments=1,
    )
    gamma_block = create_capacity_block(
        api, gamma["provider"]["id"], BLOCK_START, BLOCK_END, total_slots=2
    )
    substantiated_incident(
        api,
        gamma["provider"]["id"],
        "MINOR",
        filer_user_id="u_cc_c",
        category="DOCUMENTATION",
        narrative="Immunisation record filed one day late.",
        resolution_reason_code="PAPERWORK_CORRECTED",
    )

    reservation = create_reservation(
        api,
        world["employee"]["id"],
        world["dependent_ids"],
        CARE_START,
        CARE_END,
        market_code="MKT-BOS",
        requested_care_mode="EITHER",
    )
    world.update(
        {
            "alpha": alpha["provider"],
            "alpha_block": alpha_block,
            "beta": beta["provider"],
            "beta_block": beta_block,
            "gamma": gamma["provider"],
            "gamma_block": gamma_block,
            "reservation": reservation,
        }
    )
    return world


class TestRankScoreCombinesFourComponents:
    def test_probation_halving_sends_the_quality_100_provider_to_last_place(self, api):
        """Alpha's perfect quality is not enough once the multiplier is applied.

        PRD 3.5: "The stored `rank_score` is that base multiplied by one half when
        the provider's `network_status` is `PROBATION` and by 1.0 otherwise, rounded
        to four decimal places; when the halving applies,
        `probation_penalty_applied` is stamped true on the offer."

        Design: Difficulty/combinatorial_formula/rank_score_probation_factor_demotes_highest_quality_provider_to_last
        """
        world = _three_provider_world(api)

        matched = match_reservation(api, world["reservation"]["id"])
        assert matched["fulfillment_status"] == "OFFERED"
        assert matched["matched_provider_id"] == world["gamma"]["id"]

        offers = read_offers_for_reservation(api, world["reservation"]["id"])
        assert len(offers) == 3
        assert_offer_ordering(offers)
        for offer in offers:
            assert_match_offer(offer)

        alpha_offer = find_offer_for_provider(offers, world["alpha"]["id"])
        beta_offer = find_offer_for_provider(offers, world["beta"]["id"])
        gamma_offer = find_offer_for_provider(offers, world["gamma"]["id"])

        assert gamma_offer["rank_score"] == pytest.approx(0.8820, abs=0.0001)
        assert gamma_offer["rank_position"] == 1
        assert gamma_offer["offer_status"] == "SELECTED"

        assert beta_offer["rank_score"] == pytest.approx(0.6360, abs=0.0001)
        assert beta_offer["rank_position"] == 2
        assert beta_offer["offer_status"] == "PROPOSED"

        assert alpha_offer["rank_score"] == pytest.approx(0.4500, abs=0.0001)
        assert alpha_offer["rank_position"] == 3
        assert alpha_offer["probation_penalty_applied"] is True
        assert gamma_offer["probation_penalty_applied"] is False

    def test_each_of_the_four_components_is_persisted_on_its_offer(self, api):
        """Quality, clamped capacity, the EITHER-mode branch and continuity are stored.

        PRD 3.5: "`capacity_component` is the remaining figure divided by twice the
        seats figure — or by 1 when twice the seats figure would be smaller than 1 —
        capped at 1.0 and rounded to four decimal places."

        Design: Difficulty/combinatorial_formula/rank_score_probation_factor_demotes_highest_quality_provider_to_last
        """
        world = _three_provider_world(api)
        match_reservation(api, world["reservation"]["id"])
        offers = read_offers_for_reservation(api, world["reservation"]["id"])

        alpha_offer = find_offer_for_provider(offers, world["alpha"]["id"])
        beta_offer = find_offer_for_provider(offers, world["beta"]["id"])
        gamma_offer = find_offer_for_provider(offers, world["gamma"]["id"])

        # Alpha: 10 seats free against 1 needed, clamped to 1.0; centre under EITHER.
        assert_rank_components(alpha_offer, 1.0, 1.0, 1.0, 0.0, probation=True)
        assert alpha_offer["remaining_slots_at_offer"] == 10

        # Beta: in-home, one seat of one, so 1 / (2 * 1) = 0.5, and 0.6 for mode.
        assert_rank_components(beta_offer, 0.88, 0.5, 0.6, 0.0, probation=False)
        assert beta_offer["remaining_slots_at_offer"] == 1

        # Gamma: 2 seats free against 1 needed, so 2 / 2 = 1.0 exactly.
        assert_rank_components(gamma_offer, 0.96, 1.0, 1.0, 0.0, probation=False)
        assert gamma_offer["remaining_slots_at_offer"] == 2

    def test_the_ranking_never_consults_quality_score_alone(self, api):
        """Provider quality order and offer rank order deliberately disagree.

        PRD 3.5: "Candidates are sorted by `rank_score` descending; where scores
        tie, the higher `quality_score` wins; where those tie as well, the earlier
        `created_at` wins."

        Design: Difficulty/combinatorial_formula/rank_score_probation_factor_demotes_highest_quality_provider_to_last
        """
        world = _three_provider_world(api)
        match_reservation(api, world["reservation"]["id"])
        offers = read_offers_for_reservation(api, world["reservation"]["id"])

        alpha = validate_success(api.get_provider(world["alpha"]["id"], NETWORK_ADMIN))
        beta = validate_success(api.get_provider(world["beta"]["id"], NETWORK_ADMIN))
        gamma = validate_success(api.get_provider(world["gamma"]["id"], NETWORK_ADMIN))

        assert alpha["quality_score"] == pytest.approx(100.00, abs=0.01)
        assert beta["quality_score"] == pytest.approx(88.00, abs=0.01)
        assert gamma["quality_score"] == pytest.approx(96.00, abs=0.01)

        by_quality = [alpha["id"], gamma["id"], beta["id"]]
        by_rank = [offer["provider_id"] for offer in offers]
        assert by_rank == [gamma["id"], beta["id"], alpha["id"]]
        assert by_rank != by_quality

        # Alpha holds the best quality score and the worst rank position.
        assert find_offer_for_provider(offers, alpha["id"])["rank_position"] == 3


class TestOfferRejectionCycle:
    """OFFERED to MATCHING and back, terminating on the exclusion list."""

    @staticmethod
    def _two_provider_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(
            api, dependent_count=1, plan_overrides={"annual_use_limit_days": 10}
        )
        providers = {}
        for key, name, owner, postal in (
            ("pa", "Harbor Center A", "u_pm_ha", "02115"),
            ("pb", "Harbor Center B", "u_pm_hb", "02116"),
        ):
            bundle = setup_credentialed_provider(
                api,
                provider_name=name,
                owner_user_id=owner,
                care_mode="CENTER_BASED",
                market_code="MKT-BOS",
                postal_code=postal,
                daily_capacity_slots=4,
                max_concurrent_assignments=1,
            )
            create_capacity_block(
                api, bundle["provider"]["id"], BLOCK_START, BLOCK_END, total_slots=4
            )
            providers[key] = bundle["provider"]

        substantiated_incident(
            api,
            providers["pb"]["id"],
            "MINOR",
            filer_user_id="u_cc_hb",
            category="DOCUMENTATION",
            narrative="Allergy card not posted in the classroom.",
            resolution_reason_code="PAPERWORK_CORRECTED",
        )
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            CARE_START,
            CARE_END,
            market_code="MKT-BOS",
            requested_care_mode="CENTER_BASED",
        )
        world.update({"pa": providers["pa"], "pb": providers["pb"], "reservation": reservation})
        return world

    def test_rejecting_the_leader_hands_the_reservation_to_the_runner_up(self, api):
        """The loop runs OFFERED to MATCHING to OFFERED with a new leader.

        PRD 3.5: "Rejection moves the reservation `OFFERED → MATCHING`: the named
        offer becomes `REJECTED` with the supplied reason code, its provider is
        appended to `excluded_provider_ids` and can never be offered for this
        reservation again".

        Design: Difficulty/non_linear_state_machine/reservation_reenters_offered_after_rejection_then_exhausts_pool
        """
        world = self._two_provider_world(api)
        reservation_id = world["reservation"]["id"]

        first = match_reservation(api, reservation_id)
        assert first["fulfillment_status"] == "OFFERED"
        assert first["matched_provider_id"] == world["pa"]["id"]
        offer_a = selected_offer(api, reservation_id)
        assert offer_a["rank_score"] == pytest.approx(0.9000, abs=0.0001)

        rejected = reject_offer(
            api, reservation_id, offer_a["id"], reason_code="FAMILY_DECLINED_LOCATION"
        )
        assert rejected["fulfillment_status"] == "MATCHING"
        assert rejected["matched_provider_id"] is None
        assert rejected["excluded_provider_ids"] == [world["pa"]["id"]]

        second = match_reservation(api, reservation_id)
        assert second["fulfillment_status"] == "OFFERED"
        assert second["matched_provider_id"] == world["pb"]["id"]

        offer_b = selected_offer(api, reservation_id)
        assert offer_b["provider_id"] == world["pb"]["id"]
        assert offer_b["rank_score"] == pytest.approx(0.8820, abs=0.0001)
        assert offer_b["rank_position"] == 1

    def test_exhausting_the_pool_lands_in_unfulfilled_which_is_not_terminal(self, api):
        """Two rejections empty the pool and the third match returns 200.

        PRD 2.9: "Its terminal states are `COMPLETED`, `CANCELLED` and `NO_SHOW`;
        `UNFULFILLED` is explicitly **not** terminal, because a coordinator may
        re-run matching and lift the reservation back to `OFFERED`."

        Design: Difficulty/non_linear_state_machine/reservation_reenters_offered_after_rejection_then_exhausts_pool
        """
        world = self._two_provider_world(api)
        reservation_id = world["reservation"]["id"]

        match_reservation(api, reservation_id)
        offer_a = selected_offer(api, reservation_id)
        reject_offer(api, reservation_id, offer_a["id"], reason_code="FAMILY_DECLINED_LOCATION")

        match_reservation(api, reservation_id)
        offer_b = selected_offer(api, reservation_id)
        after_second = reject_offer(
            api, reservation_id, offer_b["id"], reason_code="FAMILY_DECLINED_LOCATION"
        )
        assert after_second["fulfillment_status"] == "MATCHING"

        response = api.match_reservation(reservation_id, CARE_COORDINATOR)
        exhausted = validate_success(response)
        assert response.status_code == 200
        assert exhausted["fulfillment_status"] == "UNFULFILLED"
        assert exhausted["unfulfilled_reason_code"] == "NO_ELIGIBLE_PROVIDER"
        assert exhausted["matched_provider_id"] is None
        assert exhausted["excluded_provider_ids"] == [world["pa"]["id"], world["pb"]["id"]]

    def test_the_batch_leaves_exactly_three_offers_in_three_end_states(self, api):
        """Two rejections plus one batch-closed expiry, and no entitlement moved.

        PRD 3.5: "every other `PROPOSED` offer of the batch becomes `EXPIRED` with
        `reason_code` `OFFER_BATCH_CLOSED`, `matched_provider_id` is cleared to
        null, and `billing_status` is left untouched at `NOT_BILLABLE`."

        Design: Difficulty/non_linear_state_machine/reservation_reenters_offered_after_rejection_then_exhausts_pool
        """
        world = self._two_provider_world(api)
        reservation_id = world["reservation"]["id"]

        match_reservation(api, reservation_id)
        offer_a1 = selected_offer(api, reservation_id)
        reject_offer(api, reservation_id, offer_a1["id"], reason_code="FAMILY_DECLINED_LOCATION")
        match_reservation(api, reservation_id)
        offer_b2 = selected_offer(api, reservation_id)
        reject_offer(api, reservation_id, offer_b2["id"], reason_code="FAMILY_DECLINED_LOCATION")
        match_reservation(api, reservation_id)

        offers = read_offers_for_reservation(api, reservation_id)
        assert len(offers) == 3
        by_id = {offer["id"]: offer for offer in offers}
        assert by_id[offer_a1["id"]]["offer_status"] == "REJECTED"
        assert by_id[offer_a1["id"]]["reason_code"] == "FAMILY_DECLINED_LOCATION"
        assert by_id[offer_b2["id"]]["offer_status"] == "REJECTED"

        batch_one_runner_up = [
            offer
            for offer in offers
            if offer["id"] not in (offer_a1["id"], offer_b2["id"])
        ]
        assert len(batch_one_runner_up) == 1
        assert batch_one_runner_up[0]["provider_id"] == world["pb"]["id"]
        assert batch_one_runner_up[0]["offer_status"] == "EXPIRED"
        assert batch_one_runner_up[0]["reason_code"] == "OFFER_BATCH_CLOSED"

        final = read_reservation(api, reservation_id)
        assert final["billing_status"] == "NOT_BILLABLE"
        assert read_entitlement(api, world["employee"]["id"])["days_reserved"] == pytest.approx(
            0, abs=0.01
        )


class TestEmptyCandidatePool:
    def test_a_market_with_no_provider_returns_200_and_unfulfilled(self, api):
        """Zero candidates is a successful outcome, not a client error.

        PRD 3.5: "An empty candidate pool is not an error."

        Design: Difficulty/boundary_precision_check/match_with_zero_candidates_returns_200_unfulfilled
        """
        world = setup_enrolled_employee(api, dependent_count=1)
        bundle = setup_credentialed_provider(
            api,
            provider_name="Bay State Center",
            owner_user_id="u_pm_bos",
            care_mode="CENTER_BASED",
            market_code="MKT-BOS",
            postal_code="02110",
        )
        create_capacity_block(api, bundle["provider"]["id"], BLOCK_START, BLOCK_END, total_slots=4)

        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            CARE_START,
            CARE_END,
            market_code="MKT-PHX",
        )
        assert reservation["fulfillment_status"] == "INTAKE"

        response = api.match_reservation(reservation["id"], CARE_COORDINATOR)
        matched = validate_success(response)
        assert response.status_code == 200
        assert matched["fulfillment_status"] == "UNFULFILLED"
        assert matched["unfulfilled_reason_code"] == "NO_ELIGIBLE_PROVIDER"
        assert matched["matched_provider_id"] is None
        assert matched["matched_capacity_block_id"] is None

    def test_an_empty_pool_creates_no_offers_and_moves_no_entitlement(self, api):
        """The offer collection stays at cardinality zero.

        PRD 3.5: "In every case an empty pool sets `unfulfilled_reason_code` to
        `NO_ELIGIBLE_PROVIDER`, creates zero offers, leaves `matched_provider_id`
        null, and returns 200."

        Design: Difficulty/boundary_precision_check/match_with_zero_candidates_returns_200_unfulfilled
        """
        world = setup_enrolled_employee(api, dependent_count=1)
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            CARE_START,
            CARE_END,
            market_code="MKT-PHX",
        )
        match_reservation(api, reservation["id"])

        rows, meta = validate_paginated(
            api.list_match_offers(CARE_COORDINATOR, params={"reservation_id": reservation["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        after = read_reservation(api, reservation["id"])
        assert after["days_charged_provisional"] == pytest.approx(0, abs=0.01)
        assert after["billing_status"] == "NOT_BILLABLE"
        assert read_entitlement(api, world["employee"]["id"])["days_reserved"] == pytest.approx(
            0, abs=0.01
        )


class TestOfferOwnership:
    def test_rejecting_another_reservations_offer_touches_neither_reservation(self, api):
        """The named offer must belong to the path reservation.

        PRD 3.5: "The named offer must belong to the path reservation
        (`ERR_OFFER_RESERVATION_MISMATCH`) and must currently be `SELECTED`
        (`ERR_OFFER_NOT_SELECTED`)".

        Design: Corner/endpoints/corner_reject_offer_with_foreign_offer_id_rejected
        """
        world = setup_offered_reservation(
            api,
            care_start_utc="2026-08-18T09:00:00Z",
            care_end_utc="2026-08-18T15:00:00Z",
            block_start_utc="2026-08-18T08:00:00Z",
            block_end_utc="2026-08-18T18:00:00Z",
            market_code="MKT-TPA",
        )
        r1_id = world["reservation"]["id"]
        provider_id = world["provider"]["id"]

        create_capacity_block(
            api,
            provider_id,
            "2026-08-19T08:00:00Z",
            "2026-08-19T18:00:00Z",
            total_slots=4,
        )
        r2 = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-19T09:00:00Z",
            "2026-08-19T15:00:00Z",
            market_code="MKT-TPA",
        )
        r2 = match_reservation(api, r2["id"])
        assert r2["fulfillment_status"] == "OFFERED"

        offer_1 = selected_offer(api, r1_id)
        offer_2 = selected_offer(api, r2["id"])
        assert offer_2["offer_expires_at"].startswith("2026-08-03T00:00:00")

        validate_error(
            api.reject_offer(
                r1_id, {"match_offer_id": offer_2["id"], "reason_code": "WRONG_LOCATION"},
                CARE_COORDINATOR,
            ),
            ApiErrorId.ERR_OFFER_RESERVATION_MISMATCH.value,
        )
        assert read_reservation(api, r1_id)["fulfillment_status"] == "OFFERED"
        assert read_reservation(api, r2["id"])["fulfillment_status"] == "OFFERED"

        legitimate = reject_offer(api, r1_id, offer_1["id"], reason_code="WRONG_LOCATION")
        assert legitimate["fulfillment_status"] == "MATCHING"
        assert legitimate["matched_provider_id"] is None
        assert legitimate["excluded_provider_ids"] == [provider_id]

        exhausted = match_reservation(api, r1_id)
        assert exhausted["fulfillment_status"] == "UNFULFILLED"
        assert exhausted["unfulfilled_reason_code"] == "NO_ELIGIBLE_PROVIDER"

        # The foreign reservation was never touched.
        assert selected_offer(api, r2["id"])["id"] == offer_2["id"]
        assert read_reservation(api, r2["id"])["fulfillment_status"] == "OFFERED"
