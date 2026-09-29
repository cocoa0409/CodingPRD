"""Non-linear lifecycles and transitive cascades.

Two families of behaviour live here.

The first is non-linear movement inside one entity: the interference-coordination
negotiation that cycles `REQUESTED` -> `REVISION_REQUESTED` -> `REQUESTED` and is
terminated by a round counter rather than by a status, and the account that
carries a commercial dimension (`service_status`) and a traffic-shaping dimension
(`usage_priority`) which advance independently of each other.

The second is transitive cascades, where each hop is caused by the hop before it:
a transport circuit falling out of `ACCEPTED` ends up expiring a qualification
four records away, and an install completion ends up setting the account's
monthly equipment charge four records away.

Every test builds its own plant, account and paperwork from scratch — the harness
restarts the server with an empty database before each test.
"""

from datetime import datetime

import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.assertions import assert_no_mutation
from test_helpers.factories import revision_payload
from test_helpers.fixtures import (
    advance_clock,
    change_circuit_state,
    change_subscriber_status,
    close_cycle,
    complete_work_order,
    get_assignment_for_subscriber,
    get_capacity_hold,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    get_tower,
    ingest_usage,
    setup_active_subscriber,
    setup_coordination,
    setup_coordination_at_round,
    setup_coordination_in_revision_requested,
    setup_held_reservation,
    setup_work_order_in_state,
)
from test_helpers.test_users import make_network_engineer_headers

# The neighbour's operator and the requester's operator are two different people
# here purely for readability; coordination carries no two-person control.
REQUESTING_OPERATOR = make_network_engineer_headers("eng-requester-3001")
NEIGHBOUR_OPERATOR = make_network_engineer_headers("eng-neighbour-4001")

COORDINATION_ROUND_LIMIT = 3


def _read(response) -> dict:
    """Read one resource through the standard success envelope."""
    return validate_success(response)


def _same_instant(actual, expected: str) -> bool:
    """True when two ISO 8601 UTC stamps denote the same instant.

    The fractional-second form of a stamp is not what any of these tests is
    about, so instants are compared as instants.
    """
    assert isinstance(actual, str) and actual, f"expected an ISO 8601 instant, got {actual!r}"

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return parse(actual) == parse(expected)


# ==========================================================================
# The interference-coordination negotiation loop (PRD 3.4)
# ==========================================================================


class TestCoordinationNegotiationLoop:
    """`REQUESTED` -> `REVISION_REQUESTED` -> `REQUESTED`, bounded by a counter."""

    def test_neighbour_counter_offer_opens_a_new_round_without_touching_the_proposal(
        self, api, network_engineer
    ):
        """PRD §3.4: "Requesting a revision moves the coordination `REQUESTED → REVISION_REQUESTED`, which is not terminal, and is the neighbour's counter-offer."
        PRD §3.4: "When `revised_channel_center_mhz` or `revised_eirp_dbm` are supplied they are recorded as the neighbour's counter-proposal inside `decision_note`; they are advisory text and do **not** overwrite the coordination's proposal fields and do **not** touch either sector."
        PRD §3.4: "Every response, whatever its outcome, stamps `last_response_at` with the current logical clock and records `decided_by_user_id` as the responding operator's identifier."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination(
            proposed_channel_center_mhz=3570.0,
            proposed_channel_width_mhz=20.0,
            proposed_eirp_dbm=42.0,
            guard_band_mhz=1.0,
        )
        coordination = pair["coordination"]
        requesting_sector_before = get_sector(pair["local"]["sector"]["id"])
        neighbor_sector_before = get_sector(pair["neighbor"]["sector"]["id"])

        response = api.respond_to_coordination(
            coordination["id"],
            {
                "decision": "REQUEST_REVISION",
                "revised_channel_center_mhz": 3610.0,
                "revised_eirp_dbm": 38.0,
                "note": "Please drop power toward our sector",
            },
            NEIGHBOUR_OPERATOR,
        )
        countered = validate_success(response)

        assert countered["status"] == "REVISION_REQUESTED", (
            f"a counter-offer moves the coordination to REVISION_REQUESTED, got {countered['status']!r}"
        )
        assert countered["proposed_channel_center_mhz"] == 3570.0, (
            "the revised centre is advisory text and must not overwrite "
            f"proposed_channel_center_mhz, got {countered['proposed_channel_center_mhz']}"
        )
        assert countered["proposed_channel_width_mhz"] == 20.0
        assert countered["proposed_eirp_dbm"] == 42.0, (
            "the revised power is advisory text and must not overwrite "
            f"proposed_eirp_dbm, got {countered['proposed_eirp_dbm']}"
        )
        assert countered["decided_by_user_id"] == "eng-neighbour-4001", (
            "decided_by_user_id records the responding operator's identifier, got "
            f"{countered.get('decided_by_user_id')!r}"
        )
        assert _same_instant(countered["last_response_at"], "2026-08-01T00:00:00Z"), (
            f"last_response_at is stamped from the logical clock, got {countered['last_response_at']!r}"
        )

        assert_no_mutation(
            requesting_sector_before,
            get_sector(requesting_sector_before["id"]),
            "requesting sector",
        )
        assert_no_mutation(
            neighbor_sector_before,
            get_sector(neighbor_sector_before["id"]),
            "neighbour sector",
        )

    def test_revision_returns_the_coordination_to_requested_and_advances_the_round(
        self, api, network_engineer
    ):
        """PRD §3.4: "From `REVISION_REQUESTED`, the requester submits a fresh proposal consisting of `proposed_channel_center_mhz`, `proposed_channel_width_mhz`, `proposed_eirp_dbm` and `guard_band_mhz`, moving the coordination back to `REQUESTED` — this is the cycle that lets a negotiation iterate."
        PRD §3.4: "On success the four proposal fields are overwritten with the new values and `round_number` is increased by one."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination_in_revision_requested(
            proposed_channel_center_mhz=3570.0,
            proposed_channel_width_mhz=20.0,
            proposed_eirp_dbm=42.0,
            guard_band_mhz=1.0,
        )
        countered = pair["coordination"]
        assert countered["status"] == "REVISION_REQUESTED", "setup failed to counter the proposal"
        round_before = countered["round_number"]

        revised = validate_success(
            api.revise_coordination(
                countered["id"],
                {
                    "proposed_channel_center_mhz": 3585.0,
                    "proposed_channel_width_mhz": 10.0,
                    "proposed_eirp_dbm": 40.0,
                    "guard_band_mhz": 2.0,
                },
                REQUESTING_OPERATOR,
            )
        )

        assert revised["status"] == "REQUESTED", (
            f"a revision moves the coordination back to REQUESTED, got {revised['status']!r}"
        )
        assert revised["round_number"] == round_before + 1, (
            "round_number is increased by one on a revision, expected "
            f"{round_before + 1}, got {revised['round_number']}"
        )
        assert revised["proposed_channel_center_mhz"] == 3585.0
        assert revised["proposed_channel_width_mhz"] == 10.0
        assert revised["proposed_eirp_dbm"] == 40.0
        assert revised["guard_band_mhz"] == 2.0

    def test_revision_refused_while_the_coordination_is_still_requested(
        self, api, network_engineer
    ):
        """PRD §3.4: "The coordination must be in `REVISION_REQUESTED` status, else `ERR_COORDINATION_NOT_OPEN`, and `round_number` must be strictly below 3, else `ERR_COORDINATION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination()
        coordination = pair["coordination"]
        assert coordination["status"] == "REQUESTED", "setup failed to open the coordination"

        response = api.revise_coordination(
            coordination["id"], revision_payload(), REQUESTING_OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_COORDINATION_NOT_OPEN.value)

        after = _read(api.get_coordination(coordination["id"], network_engineer))
        assert after["status"] == "REQUESTED"
        assert_no_mutation(coordination, after, "coordination")

    def test_response_refused_once_the_coordination_has_left_requested(
        self, api, network_engineer
    ):
        """PRD §3.4: "The coordination must be in `REQUESTED` status for any response to be entertained; a response addressed to a coordination in any other status is refused with `ERR_COORDINATION_NOT_OPEN`."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination_in_revision_requested()
        coordination = pair["coordination"]
        assert coordination["status"] == "REVISION_REQUESTED", "setup failed to counter the proposal"

        response = api.respond_to_coordination(
            coordination["id"],
            {"decision": "ACCEPT", "note": "Agreed after all"},
            NEIGHBOUR_OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_COORDINATION_NOT_OPEN.value)

        after = _read(api.get_coordination(coordination["id"], network_engineer))
        assert after["status"] == "REVISION_REQUESTED", (
            f"the refused response must not advance the coordination, got {after['status']!r}"
        )
        assert_no_mutation(coordination, after, "coordination")

    def test_further_revision_request_refused_once_the_round_limit_is_reached(
        self, api, network_engineer
    ):
        """PRD §3.4: "It is permitted only while `round_number` is strictly below the coordination round limit of 3; at or beyond it the response is refused with `ERR_COORDINATION_ROUND_LIMIT`."
        PRD §3.4: "Because the limit is checked before the increment, and because both the revision and the revision-request paths consume rounds, a negotiation can traverse at most rounds 1, 2 and 3 before further movement is refused."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination_at_round(COORDINATION_ROUND_LIMIT)
        coordination = pair["coordination"]
        assert coordination["round_number"] == COORDINATION_ROUND_LIMIT, (
            f"setup failed to reach round {COORDINATION_ROUND_LIMIT}"
        )
        assert coordination["status"] == "REQUESTED", "setup failed to leave the coordination open"
        requesting_sector_before = get_sector(pair["local"]["sector"]["id"])

        response = api.respond_to_coordination(
            coordination["id"],
            {"decision": "REQUEST_REVISION", "note": "Fourth bite at the apple"},
            NEIGHBOUR_OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_COORDINATION_ROUND_LIMIT.value)

        after = _read(api.get_coordination(coordination["id"], network_engineer))
        assert after["round_number"] == COORDINATION_ROUND_LIMIT, (
            "the exhausted negotiation is neither advanced nor rolled back, "
            f"round_number is {after['round_number']}"
        )
        assert after["status"] == "REQUESTED", (
            f"the refused response leaves the coordination in REQUESTED, got {after['status']!r}"
        )
        assert after["proposed_eirp_dbm"] == coordination["proposed_eirp_dbm"]
        assert after["proposed_channel_center_mhz"] == coordination["proposed_channel_center_mhz"]
        assert_no_mutation(coordination, after, "coordination")
        assert_no_mutation(
            requesting_sector_before,
            get_sector(requesting_sector_before["id"]),
            "requesting sector",
        )

    def test_neighbour_may_still_accept_the_proposal_at_the_round_limit(
        self, api, network_engineer
    ):
        """PRD §3.4: "Accepting moves the coordination `REQUESTED → ACCEPTED`, which is terminal, and **applies the proposal to the requesting sector**: its `channel_center_mhz` becomes `proposed_channel_center_mhz`, its `channel_width_mhz` becomes `proposed_channel_width_mhz`, and its `tx_power_dbm` becomes `proposed_eirp_dbm` less that sector's own `antenna_gain_dbi` — the negotiation is conducted in radiated terms but the radio is configured in conducted terms."
        PRD §3.4: "Note that the derived `eirp_dbm` after application therefore equals the agreed `proposed_eirp_dbm`."

        Design: Difficulty/non_linear_state_machine/coordination_negotiation_loop_bounded_at_three_rounds
        """
        pair = setup_coordination_at_round(COORDINATION_ROUND_LIMIT)
        coordination = pair["coordination"]
        assert coordination["round_number"] == COORDINATION_ROUND_LIMIT, (
            f"setup failed to reach round {COORDINATION_ROUND_LIMIT}"
        )
        sector_before = get_sector(pair["local"]["sector"]["id"])
        gain = sector_before["antenna_gain_dbi"]

        accepted = validate_success(
            api.respond_to_coordination(
                coordination["id"],
                {"decision": "ACCEPT", "note": "Coordinated at the third round"},
                NEIGHBOUR_OPERATOR,
            )
        )
        assert accepted["status"] == "ACCEPTED", (
            "the round limit bounds only the revision loop, so an acceptance at round "
            f"{COORDINATION_ROUND_LIMIT} still succeeds, got {accepted['status']!r}"
        )

        sector_after = get_sector(sector_before["id"])
        assert sector_after["channel_center_mhz"] == pytest.approx(
            coordination["proposed_channel_center_mhz"], abs=0.01
        ), "the accepted proposal's channel centre is applied to the requesting sector"
        assert sector_after["channel_width_mhz"] == pytest.approx(
            coordination["proposed_channel_width_mhz"], abs=0.01
        )
        assert sector_after["tx_power_dbm"] == pytest.approx(
            coordination["proposed_eirp_dbm"] - gain, abs=0.01
        ), "tx_power_dbm becomes proposed_eirp_dbm less the sector's own antenna_gain_dbi"
        assert sector_after["eirp_dbm"] == pytest.approx(
            coordination["proposed_eirp_dbm"], abs=0.01
        ), "the derived eirp_dbm after application equals the agreed proposed_eirp_dbm"
        assert sector_after["lower_edge_mhz"] == pytest.approx(
            coordination["proposed_channel_center_mhz"]
            - coordination["proposed_channel_width_mhz"] / 2,
            abs=0.01,
        )
        assert sector_after["upper_edge_mhz"] == pytest.approx(
            coordination["proposed_channel_center_mhz"]
            + coordination["proposed_channel_width_mhz"] / 2,
            abs=0.01,
        )


# ==========================================================================
# The account's two independent state dimensions (PRD 3.8)
# ==========================================================================

# The reference plan is 50 Mbps downstream with a 600.0 GB soft cap and a
# deprioritization factor of 0.25, so shaping lands on 50 * 0.25 = 12.5 Mbps.
PLAN_SOFT_CAP_GB = 600.0
PLAN_DOWNSTREAM_MBPS = 50.0
SHAPED_DOWNSTREAM_MBPS = 12.5


def _setup_account_at_the_cap():
    """An ACTIVE account whose open cycle carries exactly the plan's soft cap.

    The clock is first moved to 2026-08-06 so every metered day is in the past
    and any shaping stamp is unambiguously the clock rather than a usage date.
    """
    scenario = setup_active_subscriber()
    subscriber = scenario["subscriber"]
    assert subscriber["service_status"] == "ACTIVE", (
        f"Setup failed: account is {subscriber['service_status']!r}, expected ACTIVE"
    )
    assert scenario["plan"]["soft_cap_gb"] == PLAN_SOFT_CAP_GB, "Setup failed: unexpected soft cap"
    scenario["now"] = advance_clock(days=5)
    ingest_usage(subscriber["id"], "2026-08-02", 300.0)
    ingest_usage(subscriber["id"], "2026-08-03", 250.0, 50.0)
    scenario["subscriber"] = get_subscriber(subscriber["id"])
    return scenario


def _setup_deprioritized_account():
    """The same account pushed one tenth of a gigabyte past the cap."""
    scenario = _setup_account_at_the_cap()
    ingest_usage(scenario["subscriber"]["id"], "2026-08-04", 0.5)
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    assert scenario["subscriber"]["usage_priority"] == "DEPRIORITIZED", (
        "Setup failed: the account did not shape after breaching the cap"
    )
    return scenario


class TestAccountDimensionsAdvanceIndependently:
    """`service_status` and `usage_priority` neither constrain nor drive each other."""

    def test_breaching_the_cap_shapes_the_account_and_leaves_it_commercially_active(
        self, api, billing_admin
    ):
        """PRD §3.8: "The cycle is breached when `cycle_usage_gb` is **strictly greater** than the plan's `soft_cap_gb`; usage landing exactly on the cap is not a breach."
        PRD §3.8: "`usage_priority` is then `DEPRIORITIZED` when either the current cycle is breached or `sticky_deprioritization_active` is true, and `STANDARD` otherwise."
        PRD §3.8: "The transition stamps `deprioritized_at` with the current logical clock and recomputes `effective_downstream_mbps`."

        Design: Difficulty/non_linear_state_machine/subscriber_service_status_and_usage_priority_advance_independently
        """
        scenario = _setup_account_at_the_cap()
        at_cap = scenario["subscriber"]

        assert at_cap["cycle_usage_gb"] == pytest.approx(PLAN_SOFT_CAP_GB, abs=0.001), (
            f"the two metered days total exactly the cap, got {at_cap['cycle_usage_gb']}"
        )
        assert at_cap["usage_priority"] == "STANDARD", (
            "usage landing exactly on the cap is not a breach, got "
            f"{at_cap['usage_priority']!r}"
        )
        assert at_cap["effective_downstream_mbps"] == pytest.approx(PLAN_DOWNSTREAM_MBPS, abs=0.01)
        assert at_cap.get("deprioritized_at") is None, (
            "an unbreached account carries no deprioritization stamp, got "
            f"{at_cap.get('deprioritized_at')!r}"
        )

        record = ingest_usage(at_cap["id"], "2026-08-04", 0.5)
        assert record["total_gb"] == pytest.approx(0.5, abs=0.001)
        assert record["in_current_cycle"] is True
        assert record["ingest_sequence"] == 3, (
            f"the third metered day carries ingest_sequence 3, got {record['ingest_sequence']}"
        )

        breached = get_subscriber(at_cap["id"])
        assert breached["cycle_usage_gb"] == pytest.approx(600.5, abs=0.001), (
            f"expected 600.5 GB accumulated over the cycle, got {breached['cycle_usage_gb']}"
        )
        assert breached["usage_priority"] == "DEPRIORITIZED", (
            "one tenth past the cap is strictly greater than it and therefore a breach, got "
            f"{breached['usage_priority']!r}"
        )
        assert breached["effective_downstream_mbps"] == pytest.approx(
            SHAPED_DOWNSTREAM_MBPS, abs=0.01
        ), (
            "shaping is the plan's 50 Mbps times the 0.25 factor, got "
            f"{breached['effective_downstream_mbps']}"
        )
        assert _same_instant(breached["deprioritized_at"], "2026-08-06T00:00:00Z"), (
            "deprioritized_at is stamped from the logical clock, not from the usage date, got "
            f"{breached['deprioritized_at']!r}"
        )
        assert breached["service_status"] == "ACTIVE", (
            "the shaping dimension moved on its own; the commercial dimension must not follow, "
            f"got {breached['service_status']!r}"
        )
        assert breached["consecutive_breach_cycles"] == 0, (
            "the breach counter only rolls at a cycle close, got "
            f"{breached['consecutive_breach_cycles']}"
        )
        assert breached["sticky_deprioritization_active"] is False

    def test_suspending_a_shaped_account_leaves_the_shaping_posture_untouched(
        self, api, billing_admin
    ):
        """PRD §3.8: "A live account carries **two independent state dimensions**."
        PRD §3.8: "Neither dimension constrains the other's value: a `SUSPENDED` account may perfectly well be `DEPRIORITIZED`, and returning it to `ACTIVE` does not reset its shaping posture."

        Design: Difficulty/non_linear_state_machine/subscriber_service_status_and_usage_priority_advance_independently
        """
        scenario = _setup_deprioritized_account()
        shaped = scenario["subscriber"]

        suspended = change_subscriber_status(shaped["id"], "SUSPENDED", reason="Non-payment")

        assert suspended["service_status"] == "SUSPENDED", (
            f"expected the commercial dimension to move to SUSPENDED, got {suspended['service_status']!r}"
        )
        assert suspended["usage_priority"] == "DEPRIORITIZED", (
            "a SUSPENDED account may perfectly well be DEPRIORITIZED, got "
            f"{suspended['usage_priority']!r}"
        )
        assert suspended["effective_downstream_mbps"] == pytest.approx(
            SHAPED_DOWNSTREAM_MBPS, abs=0.01
        )
        assert _same_instant(suspended["deprioritized_at"], "2026-08-06T00:00:00Z"), (
            "the suspension does not restamp the shaping transition, got "
            f"{suspended['deprioritized_at']!r}"
        )
        assert suspended["cycle_usage_gb"] == pytest.approx(600.5, abs=0.001)

    def test_reinstating_a_shaped_account_does_not_reset_its_shaping_posture(
        self, api, billing_admin
    ):
        """PRD §3.8: "Neither dimension constrains the other's value: a `SUSPENDED` account may perfectly well be `DEPRIORITIZED`, and returning it to `ACTIVE` does not reset its shaping posture."
        PRD §3.8: "`SUSPENDED → ACTIVE` reinstates it."

        Design: Difficulty/non_linear_state_machine/subscriber_service_status_and_usage_priority_advance_independently
        """
        scenario = _setup_deprioritized_account()
        shaped = scenario["subscriber"]
        change_subscriber_status(shaped["id"], "SUSPENDED", reason="Non-payment")

        restored = change_subscriber_status(shaped["id"], "ACTIVE", reason="Balance settled")

        assert restored["service_status"] == "ACTIVE", (
            f"expected reinstatement to ACTIVE, got {restored['service_status']!r}"
        )
        assert restored["usage_priority"] == "DEPRIORITIZED", (
            "returning the account to ACTIVE does not reset its shaping posture, got "
            f"{restored['usage_priority']!r}"
        )
        assert restored["effective_downstream_mbps"] == pytest.approx(
            SHAPED_DOWNSTREAM_MBPS, abs=0.01
        ), (
            "the shaped rate survives a round trip through SUSPENDED, got "
            f"{restored['effective_downstream_mbps']}"
        )
        assert _same_instant(restored["deprioritized_at"], "2026-08-06T00:00:00Z")

    def test_shaping_oscillates_across_two_closes_while_the_account_stays_active(
        self, api, billing_admin
    ):
        """PRD §3.8: "`usage_priority` has no terminal value and can oscillate for the whole life of the account."
        PRD §3.8: "**A breached cycle on a `DEPRIORITIZED` account** keeps it `DEPRIORITIZED`. `consecutive_breach_cycles` is increased by one, and once that counter reaches the sticky threshold of 2, `sticky_deprioritization_active` is set to true — which is what makes the shaping survive the next cycle: the account opens the following window already `DEPRIORITIZED` even at zero metered usage, and only a clean cycle can clear it. `cycle_start_date` advances by 30 days and `cycle_usage_gb` and `effective_downstream_mbps` are recomputed over the new window."
        PRD §3.8: "**A clean cycle on a `DEPRIORITIZED` account** moves it `DEPRIORITIZED → STANDARD`, provided the closing cycle's `cycle_usage_gb` was at or below `soft_cap_gb` and `consecutive_breach_cycles` after the close is strictly below the sticky threshold of 2. `consecutive_breach_cycles` is set to zero, `sticky_deprioritization_active` is set to false, `deprioritized_at` is cleared, `cycle_start_date` advances by 30 days, and `cycle_usage_gb` is recomputed over the new window with `effective_downstream_mbps` restored to the plan's `downstream_mbps`."

        Design: Difficulty/non_linear_state_machine/subscriber_service_status_and_usage_priority_advance_independently
        """
        scenario = _setup_deprioritized_account()
        subscriber_id = scenario["subscriber"]["id"]
        assert scenario["subscriber"]["cycle_start_date"] == "2026-08-01", (
            f"Setup failed: unexpected cycle start {scenario['subscriber']['cycle_start_date']!r}"
        )

        after_breached_close = close_cycle(subscriber_id)

        # The posture immediately after this first breached close is left
        # unasserted: "keeps it DEPRIORITIZED" and "`cycle_usage_gb` and
        # `effective_downstream_mbps` are recomputed over the new window" (with
        # the sticky flag still false, and the general rule that the posture is
        # `DEPRIORITIZED` only "when either the current cycle is breached or
        # `sticky_deprioritization_active` is true") point in opposite
        # directions, so the PRD does not fix a single value here. Only the
        # counter, the flag and the rolled window are pinned.
        assert after_breached_close["consecutive_breach_cycles"] == 1, (
            "the breach counter is increased by one, got "
            f"{after_breached_close['consecutive_breach_cycles']}"
        )
        assert after_breached_close["sticky_deprioritization_active"] is False, (
            "one breach is short of the sticky threshold of 2, got "
            f"{after_breached_close['sticky_deprioritization_active']}"
        )
        assert after_breached_close["cycle_start_date"] == "2026-08-31", (
            "cycle_start_date advances by 30 days, got "
            f"{after_breached_close['cycle_start_date']!r}"
        )
        assert after_breached_close["cycle_usage_gb"] == pytest.approx(0.0, abs=0.001), (
            "cycle_usage_gb is recomputed over the new window, got "
            f"{after_breached_close['cycle_usage_gb']}"
        )
        assert after_breached_close["service_status"] == "ACTIVE", (
            "closing a cycle is not a commercial event, got "
            f"{after_breached_close['service_status']!r}"
        )

        after_clean_close = close_cycle(subscriber_id)

        assert after_clean_close["usage_priority"] == "STANDARD", (
            "a clean cycle on a DEPRIORITIZED account moves it back to STANDARD, got "
            f"{after_clean_close['usage_priority']!r}"
        )
        assert after_clean_close["consecutive_breach_cycles"] == 0, (
            f"the counter is set to zero, got {after_clean_close['consecutive_breach_cycles']}"
        )
        assert after_clean_close["sticky_deprioritization_active"] is False
        assert after_clean_close.get("deprioritized_at") is None, (
            f"deprioritized_at is cleared, got {after_clean_close.get('deprioritized_at')!r}"
        )
        assert after_clean_close["cycle_start_date"] == "2026-09-30", (
            f"cycle_start_date advances by another 30 days, got {after_clean_close['cycle_start_date']!r}"
        )
        assert after_clean_close["effective_downstream_mbps"] == pytest.approx(
            PLAN_DOWNSTREAM_MBPS, abs=0.01
        ), (
            "effective_downstream_mbps is restored to the plan's downstream_mbps, got "
            f"{after_clean_close['effective_downstream_mbps']}"
        )
        assert after_clean_close["service_status"] == "ACTIVE", (
            "the commercial dimension never moved throughout the oscillation, got "
            f"{after_clean_close['service_status']!r}"
        )


# ==========================================================================
# The transport cascade: circuit -> tower -> sector -> reservation -> enquiry
# (PRD 2.10, PRD 3.1, PRD 3.3, PRD 3.5)
# ==========================================================================

# The reference plant: a 500 Mbps committed circuit, a 25 Mbps sector with an
# 8.0 ceiling (so 200 Mbps of allowance) and one 50 Mbps reservation on it.
REFERENCE_CIRCUIT_MBPS = 500
REFERENCE_SECTOR_ALLOWANCE_MBPS = 200
REFERENCE_HELD_MBPS = 50


def _setup_reservation_then_degrade_transport():
    """Active plant + QUALIFIED enquiry + HELD reservation, then the circuit falls.

    Returns the scenario dict with pre-degradation copies under "before" and the
    freshly read records under "circuit", "tower", "sector", "hold" and "request".
    """
    scenario = setup_held_reservation()
    assert scenario["hold"]["status"] == "HELD", (
        f"Setup failed: reservation is {scenario['hold']['status']!r}, expected HELD"
    )
    assert scenario["request"]["status"] == "QUALIFIED", (
        f"Setup failed: enquiry is {scenario['request']['status']!r}, expected QUALIFIED"
    )
    assert scenario["sector"]["held_mbps"] == REFERENCE_HELD_MBPS, (
        f"Setup failed: sector holds {scenario['sector']['held_mbps']} Mbps"
    )
    scenario["before"] = {
        "tower": get_tower(scenario["tower"]["id"]),
        "sector": get_sector(scenario["sector"]["id"]),
        "hold": get_capacity_hold(scenario["hold"]["id"]),
        "request": get_serviceability_request(scenario["request"]["id"]),
    }

    scenario["circuit"] = change_circuit_state(
        scenario["circuit"]["id"], "DEGRADED", note="Carrier reports a fibre cut"
    )
    scenario["tower"] = get_tower(scenario["tower"]["id"])
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    scenario["hold"] = get_capacity_hold(scenario["hold"]["id"])
    scenario["request"] = get_serviceability_request(scenario["request"]["id"])
    return scenario


class TestBackhaulDegradationCascade:
    """One degraded circuit expires a qualification four records away."""

    def test_first_hop_the_tower_loses_all_accepted_transport(self, api, network_engineer):
        """PRD §3.1: "A tower's `backhaul_accepted_mbps` is the `committed_mbps` of the circuit on that tower whose `state` is `ACCEPTED`, and it is zero whenever no circuit on the tower is `ACCEPTED`."
        PRD §3.1: "`ACCEPTED → DEGRADED` stamps `degraded_since` with the clock and, when `measured_mbps` is supplied, overwrites it with the fresh reading; it then drives the transport cascade described below."
        PRD §3.1: "When a circuit falls from `ACCEPTED` to `DEGRADED`, the tower's `backhaul_accepted_mbps` becomes zero; because there is no accepted transport, every sector on the tower recomputes and lands on `FROZEN`; because those sectors are frozen, every capacity reservation still `HELD` on them moves to `RELEASED` with a `release_reason` of `BACKHAUL_DEGRADED` and the sectors' `held_mbps` fall accordingly; and because those reservations are gone, every qualification they were reserving for that sits in `QUALIFIED` or `CAPACITY_DEFERRED` moves to `EXPIRED`."

        Design: Difficulty/transitive_cascade/backhaul_degradation_cascade_freezes_sector_releases_hold_expires_request
        """
        scenario = _setup_reservation_then_degrade_transport()

        assert scenario["circuit"]["state"] == "DEGRADED", (
            f"expected the circuit to fall to DEGRADED, got {scenario['circuit']['state']!r}"
        )
        assert _same_instant(scenario["circuit"]["degraded_since"], "2026-08-01T00:00:00Z"), (
            f"degraded_since is stamped from the clock, got {scenario['circuit']['degraded_since']!r}"
        )
        assert scenario["before"]["tower"]["backhaul_accepted_mbps"] == REFERENCE_CIRCUIT_MBPS, (
            "Setup failed: the tower did not carry its circuit's committed rate"
        )
        assert scenario["tower"]["backhaul_accepted_mbps"] == 0, (
            "with no ACCEPTED circuit left the tower's accepted transport is zero, got "
            f"{scenario['tower']['backhaul_accepted_mbps']}"
        )
        assert scenario["tower"]["status"] == "ACTIVE", (
            "the cascade freezes capacity but does not move the site through its own "
            f"lifecycle, got {scenario['tower']['status']!r}"
        )

    def test_second_hop_every_sector_on_the_tower_freezes(self, api, network_engineer):
        """PRD §3.3: "Otherwise, if the parent tower's `backhaul_accepted_mbps` is zero — that is, no circuit on the tower is in `ACCEPTED` state — the posture is `FROZEN`."
        PRD §3.1: "because there is no accepted transport, every sector on the tower recomputes and lands on `FROZEN`"
        PRD §3.1: "A tower's `active_sector_count` is at all times the number of its sectors whose `status` is `ACTIVE`"

        Design: Difficulty/transitive_cascade/backhaul_degradation_cascade_freezes_sector_releases_hold_expires_request
        """
        scenario = _setup_reservation_then_degrade_transport()
        sector = scenario["sector"]

        assert scenario["before"]["sector"]["capacity_posture"] == "OPEN", (
            "Setup failed: the sector was not OPEN before the circuit fell, it was "
            f"{scenario['before']['sector']['capacity_posture']!r}"
        )
        assert sector["capacity_posture"] == "FROZEN", (
            "a sector on a tower with no accepted transport is FROZEN, got "
            f"{sector['capacity_posture']!r}"
        )
        assert sector["status"] == "ACTIVE", (
            "the posture freezes; the sector's own status is untouched, got "
            f"{sector['status']!r}"
        )
        assert scenario["tower"]["active_sector_count"] == 1, (
            "the sector is still ACTIVE, so it is still counted, got "
            f"{scenario['tower']['active_sector_count']}"
        )

    def test_third_hop_the_held_reservation_is_released_as_backhaul_degraded(
        self, api, capacity_planner
    ):
        """PRD §3.6: "Three further paths reach `RELEASED`, and they are distinguished purely by `release_reason`. When the sector's posture recomputes to `FROZEN` because its tower has lost its accepted transport, the reservation is released with `BACKHAUL_DEGRADED`."
        PRD §3.1: "because those sectors are frozen, every capacity reservation still `HELD` on them moves to `RELEASED` with a `release_reason` of `BACKHAUL_DEGRADED` and the sectors' `held_mbps` fall accordingly"
        PRD §3.3: "`held_mbps` is the sum of `held_mbps` over every reservation on this sector whose `status` is `HELD`. Reservations in `CONSUMED`, `RELEASED` or `EXPIRED` status contribute nothing."

        Design: Difficulty/transitive_cascade/backhaul_degradation_cascade_freezes_sector_releases_hold_expires_request
        """
        scenario = _setup_reservation_then_degrade_transport()
        hold = scenario["hold"]
        sector = scenario["sector"]

        assert hold["status"] == "RELEASED", (
            f"the frozen sector releases its reservation, got {hold['status']!r}"
        )
        assert hold["release_reason"] == "BACKHAUL_DEGRADED", (
            "the release is distinguished purely by its reason, got "
            f"{hold.get('release_reason')!r}"
        )
        assert hold["held_mbps"] == REFERENCE_HELD_MBPS, (
            "the reservation still records what it was holding, got "
            f"{hold['held_mbps']}"
        )
        assert sector["held_mbps"] == 0, (
            f"a RELEASED reservation contributes nothing to held_mbps, got {sector['held_mbps']}"
        )
        assert sector["sold_mbps"] == 0, (
            f"no account was ever opened on this sector, got {sector['sold_mbps']}"
        )
        assert sector["committed_mbps"] == 0, (
            f"committed_mbps is sold_mbps plus held_mbps, got {sector['committed_mbps']}"
        )
        assert sector["oversubscription_ratio"] == pytest.approx(0.0, abs=0.0005), (
            f"nothing is committed, so the ratio is 0.000, got {sector['oversubscription_ratio']}"
        )
        assert sector["remaining_allowance_mbps"] == REFERENCE_SECTOR_ALLOWANCE_MBPS, (
            "the whole 200 Mbps allowance is handed back, got "
            f"{sector['remaining_allowance_mbps']}"
        )

    def test_fourth_hop_the_qualification_expires_and_forgets_its_sector(
        self, api, sales_agent
    ):
        """PRD §3.1: "and because those reservations are gone, every qualification they were reserving for that sits in `QUALIFIED` or `CAPACITY_DEFERRED` moves to `EXPIRED`"
        PRD §3.5: "`QUALIFIED` does move to `EXPIRED`, but only as a consequence of its reservation leaving `HELD` without being consumed, and that transition clears `qualified_sector_id` so the enquiry no longer points at a sector it has no claim on."

        Design: Difficulty/transitive_cascade/backhaul_degradation_cascade_freezes_sector_releases_hold_expires_request
        """
        scenario = _setup_reservation_then_degrade_transport()
        request = scenario["request"]

        assert scenario["before"]["request"]["qualified_sector_id"] == scenario["sector"]["id"], (
            "Setup failed: the enquiry was not qualified against the frozen sector"
        )
        assert request["status"] == "EXPIRED", (
            "the enquiry expires because its reservation left HELD without being consumed, got "
            f"{request['status']!r}"
        )
        assert request.get("qualified_sector_id") is None, (
            "the transition clears qualified_sector_id, got "
            f"{request.get('qualified_sector_id')!r}"
        )

    def test_restoring_transport_reverses_the_first_two_hops_only(self, api, network_engineer):
        """PRD §3.1: "Restoring the circuit to `ACCEPTED` recomputes `backhaul_accepted_mbps` and the sector postures, but reservations already `RELEASED` are **not** restored and expired qualifications do **not** come back."
        PRD §3.1: "`DEGRADED → ACCEPTED` is the restore: it requires `measured_mbps` (again `ERR_VALIDATION` when absent), stores it, clears `degraded_since`, and leaves `accepted_at` at its original first-acceptance value rather than re-stamping it."

        Design: Difficulty/transitive_cascade/backhaul_degradation_cascade_freezes_sector_releases_hold_expires_request
        """
        scenario = _setup_reservation_then_degrade_transport()

        restored = change_circuit_state(
            scenario["circuit"]["id"],
            "ACCEPTED",
            measured_mbps=498.0,
            note="Splice repaired",
        )

        assert restored["state"] == "ACCEPTED", (
            f"expected the circuit back in ACCEPTED, got {restored['state']!r}"
        )
        assert restored.get("degraded_since") is None, (
            f"the restore clears degraded_since, got {restored.get('degraded_since')!r}"
        )
        assert restored["measured_mbps"] == pytest.approx(498.0, abs=0.01), (
            f"the restore stores the fresh reading, got {restored.get('measured_mbps')}"
        )

        tower = get_tower(scenario["tower"]["id"])
        assert tower["backhaul_accepted_mbps"] == REFERENCE_CIRCUIT_MBPS, (
            "accepted transport is recomputed from the circuit's committed rate, got "
            f"{tower['backhaul_accepted_mbps']}"
        )
        sector = get_sector(scenario["sector"]["id"])
        assert sector["capacity_posture"] == "OPEN", (
            "with transport back and nothing committed the posture recomputes to OPEN, got "
            f"{sector['capacity_posture']!r}"
        )
        assert sector["held_mbps"] == 0, (
            f"the released reservation is not resurrected, got {sector['held_mbps']}"
        )

        hold = get_capacity_hold(scenario["hold"]["id"])
        assert hold["status"] == "RELEASED", (
            f"reservations already RELEASED are not restored, got {hold['status']!r}"
        )
        assert hold["release_reason"] == "BACKHAUL_DEGRADED"
        request = get_serviceability_request(scenario["request"]["id"])
        assert request["status"] == "EXPIRED", (
            f"expired qualifications do not come back, got {request['status']!r}"
        )
        assert request.get("qualified_sector_id") is None


# ==========================================================================
# The activation chain: work order -> account -> equipment -> monthly charge
# (PRD 2.10, PRD 3.7)
# ==========================================================================

# 9900 labour for a NON_PEN_ROOF_TRIPOD + 8750 for five half-metre sections of a
# 2.5 m mast + 9900 trip = 28550 subtotal; 3000 discount at the 20000 tier gives
# 25550 net; 3.25 % of 25550 is 830.375, rounded to 830; total 26380.
INSTALL_INVOICE_TOTAL_CENTS = 26380
RENTAL_MONTHLY_CENTS = 1000
INSTALLED_AT = "2026-08-02T00:00:00Z"


def _setup_completed_install(equipment_mode: str = "RENTAL"):
    """A MOUNT_APPROVED truck roll completed on the day after the clock's start.

    Returns the scenario dict with pre-completion copies under "before" and the
    freshly read records under "work_order", "subscriber" and "assignment".
    """
    scenario = setup_work_order_in_state("MOUNT_APPROVED", equipment_mode=equipment_mode)
    work_order = scenario["work_order"]
    assert work_order["status"] == "MOUNT_APPROVED", (
        f"Setup failed: work order is {work_order['status']!r}, expected MOUNT_APPROVED"
    )
    scenario["before"] = {
        "subscriber": get_subscriber(scenario["subscriber"]["id"]),
        "assignment": get_assignment_for_subscriber(scenario["subscriber"]["id"]),
    }
    assert scenario["before"]["subscriber"]["service_status"] == "PENDING_INSTALL", (
        "Setup failed: the account is not awaiting its install"
    )
    assert scenario["before"]["assignment"]["status"] == "ASSIGNED", (
        f"Setup failed: equipment record is {scenario['before']['assignment']['status']!r}"
    )

    scenario["now"] = advance_clock(days=1)
    scenario["work_order"] = complete_work_order(
        work_order["id"], installed_mast_height_m=2.5, radio_serial="RAD-0001"
    )
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    return scenario


class TestInstallCompletionActivationChain:
    """One completion drives the account live and starts the recurring charge."""

    def test_first_hop_the_work_order_reaches_installed_and_prices_the_visit(
        self, api, field_tech
    ):
        """PRD §3.7: "On success the work order moves `MOUNT_APPROVED → INSTALLED`, which is terminal, storing `installed_mast_height_m`, `radio_serial` and an `installed_at` stamp taken from the logical clock, and computing `install_invoice_total_cents`."
        PRD §3.7: "Begin with a labour charge selected by `approved_mounting_type`: 4900 cents for a `WALL_BRACKET`, 9900 for a `NON_PEN_ROOF_TRIPOD`, 19900 for a `ROOF_MAST_GUYED`, and 34900 for a `GROUND_POLE_MAST`. Add a mast kit charge of 1750 cents per half-metre section, where the number of sections is `installed_mast_height_m` divided by 0.5 and rounded **upward** to a whole number — a 2.6 metre mast bills six sections. Add the fixed trip charge of 9900 cents. The sum of trip charge, labour and mast kit is the subtotal."
        PRD §3.7: "A volume discount is then read off the **subtotal only**, with inclusive lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above 20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns nothing. The net amount is the subtotal less that discount. A regulatory cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded half up to whole cents, and `install_invoice_total_cents` is the net amount plus that fee."

        Design: Difficulty/transitive_cascade/install_completion_cascade_activates_account_deploys_radio_and_sets_monthly_charge
        """
        scenario = _setup_completed_install()
        work_order = scenario["work_order"]

        assert work_order["status"] == "INSTALLED", (
            f"expected the truck roll to reach INSTALLED, got {work_order['status']!r}"
        )
        assert work_order["approved_mounting_type"] == "NON_PEN_ROOF_TRIPOD", (
            "Setup expected the tripod band, got "
            f"{work_order.get('approved_mounting_type')!r}"
        )
        assert work_order["installed_mast_height_m"] == pytest.approx(2.5, abs=0.01), (
            f"the erected mast height is stored, got {work_order.get('installed_mast_height_m')}"
        )
        assert work_order["radio_serial"] == "RAD-0001", (
            f"the reported serial is stored, got {work_order.get('radio_serial')!r}"
        )
        assert _same_instant(work_order["installed_at"], INSTALLED_AT), (
            f"installed_at is taken from the logical clock, got {work_order['installed_at']!r}"
        )
        assert work_order["install_invoice_total_cents"] == INSTALL_INVOICE_TOTAL_CENTS, (
            "9900 labour + 8750 mast kit + 9900 trip = 28550 subtotal, less the 3000 discount "
            "is 25550 net, plus the 830-cent regulatory fee is 26380, got "
            f"{work_order.get('install_invoice_total_cents')}"
        )

    def test_second_hop_the_account_goes_live_and_opens_its_first_cycle(self, api, field_tech):
        """PRD §3.7: "The account moves `PENDING_INSTALL → ACTIVE`, with `service_start_date` set from the logical clock and `cycle_start_date` set to the calendar date of that same instant, which opens the account's first billing cycle."
        PRD §3.7: "Completing an install is the event that turns a signed-up household into a live one, and it fires a chain of three."

        Design: Difficulty/transitive_cascade/install_completion_cascade_activates_account_deploys_radio_and_sets_monthly_charge
        """
        scenario = _setup_completed_install()
        subscriber = scenario["subscriber"]

        assert subscriber["service_status"] == "ACTIVE", (
            "the completion is what makes the household live, got "
            f"{subscriber['service_status']!r}"
        )
        assert _same_instant(subscriber["service_start_date"], INSTALLED_AT), (
            "service_start_date is set from the logical clock, got "
            f"{subscriber.get('service_start_date')!r}"
        )
        assert subscriber["cycle_start_date"] == "2026-08-02", (
            "cycle_start_date is the calendar date of that same instant, got "
            f"{subscriber.get('cycle_start_date')!r}"
        )
        assert scenario["before"]["subscriber"].get("cycle_start_date") is None, (
            "no billing cycle existed before the install, got "
            f"{scenario['before']['subscriber'].get('cycle_start_date')!r}"
        )
        assert subscriber["cycle_usage_gb"] == pytest.approx(0.0, abs=0.001), (
            f"the freshly opened cycle carries no traffic, got {subscriber['cycle_usage_gb']}"
        )
        assert subscriber["usage_priority"] == "STANDARD", (
            f"an unbreached new cycle is STANDARD, got {subscriber['usage_priority']!r}"
        )
        assert subscriber["effective_downstream_mbps"] == pytest.approx(
            PLAN_DOWNSTREAM_MBPS, abs=0.01
        ), (
            "while STANDARD the effective rate is the plan's downstream_mbps, got "
            f"{subscriber['effective_downstream_mbps']}"
        )

    def test_third_hop_the_radio_is_deployed_carrying_the_reported_serial(
        self, api, field_tech
    ):
        """PRD §3.7: "And the account's equipment record moves `ASSIGNED → DEPLOYED`, with `deployed_at` stamped from the clock and its `radio_serial` copied from the `radio_serial` reported on the completion, so that the unit on the wall and the record of it agree."

        Design: Difficulty/transitive_cascade/install_completion_cascade_activates_account_deploys_radio_and_sets_monthly_charge
        """
        scenario = _setup_completed_install()
        assignment = scenario["assignment"]

        assert assignment["status"] == "DEPLOYED", (
            f"the equipment record moves ASSIGNED to DEPLOYED, got {assignment['status']!r}"
        )
        assert _same_instant(assignment["deployed_at"], INSTALLED_AT), (
            f"deployed_at is stamped from the clock, got {assignment.get('deployed_at')!r}"
        )
        assert assignment["radio_serial"] == "RAD-0001", (
            "the record carries the serial reported on the completion, got "
            f"{assignment.get('radio_serial')!r}"
        )
        assert assignment["radio_serial"] == scenario["work_order"]["radio_serial"], (
            "the unit on the wall and the record of it must agree"
        )

    @pytest.mark.parametrize(
        "equipment_mode,expected_monthly_cents",
        [("RENTAL", RENTAL_MONTHLY_CENTS), ("PURCHASE", 0)],
    )
    def test_fourth_hop_the_recurring_charge_begins_only_once_the_radio_is_deployed(
        self, api, field_tech, equipment_mode, expected_monthly_cents
    ):
        """PRD §3.7: "The account's `equipment_monthly_charge_cents` is then recomputed and becomes the equipment record's `monthly_rental_cents` — 1000 cents for a rental, zero for a purchase — because the recurring charge only begins once the radio is deployed."

        Design: Difficulty/transitive_cascade/install_completion_cascade_activates_account_deploys_radio_and_sets_monthly_charge
        """
        scenario = _setup_completed_install(equipment_mode=equipment_mode)

        assert scenario["before"]["subscriber"]["equipment_monthly_charge_cents"] == 0, (
            "nothing recurs while the radio is merely ASSIGNED, got "
            f"{scenario['before']['subscriber']['equipment_monthly_charge_cents']}"
        )
        assignment = scenario["assignment"]
        assert assignment["acquisition_mode"] == equipment_mode, (
            f"Setup failed: equipment record is {assignment['acquisition_mode']!r}"
        )
        assert assignment["monthly_rental_cents"] == expected_monthly_cents, (
            f"a {equipment_mode} record rents at {expected_monthly_cents} cents, got "
            f"{assignment['monthly_rental_cents']}"
        )
        assert scenario["subscriber"]["equipment_monthly_charge_cents"] == expected_monthly_cents, (
            "the account's charge becomes the equipment record's monthly_rental_cents, got "
            f"{scenario['subscriber']['equipment_monthly_charge_cents']}"
        )

    def test_every_record_the_chain_touches_is_versioned_in_its_own_right(
        self, api, field_tech
    ):
        """PRD §2.10: "Cascades are **immediate and synchronous**: by the time a response is returned, every downstream record has already reached its new state, and any derived roll-up has already been recomputed. Each record touched by a cascade has its `updated_at` refreshed and its `version` incremented in its own right, exactly as if it had been written directly."
        PRD §2.10: "The **activation chain** starts when an install is completed. The work order reaches its terminal installed state; because of that, the account leaves its pending state and becomes live; because the account is live, its equipment assignment moves from assigned to deployed; and because the assignment is deployed, the account's derived monthly equipment charge is recalculated from the assignment's rental rate."

        Design: Difficulty/transitive_cascade/install_completion_cascade_activates_account_deploys_radio_and_sets_monthly_charge
        """
        scenario = _setup_completed_install()

        subscriber_before = scenario["before"]["subscriber"]
        subscriber_after = scenario["subscriber"]
        assert subscriber_after["version"] > subscriber_before["version"], (
            "the account was touched by the cascade and must be versioned for it, "
            f"version stayed at {subscriber_after['version']}"
        )
        assert subscriber_after["updated_at"] != subscriber_before["updated_at"], (
            "the account's updated_at must be refreshed by the cascade"
        )

        assignment_before = scenario["before"]["assignment"]
        assignment_after = scenario["assignment"]
        assert assignment_after["version"] > assignment_before["version"], (
            "the equipment record was touched by the cascade and must be versioned for it, "
            f"version stayed at {assignment_after['version']}"
        )
        assert assignment_after["updated_at"] != assignment_before["updated_at"], (
            "the equipment record's updated_at must be refreshed by the cascade"
        )
