"""Closure/consolidation negotiation: counter cycle, round cap, direction rules,
segregation of duties, and locality ownership (PRD §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_closure_agreement,
    create_closure_agreement_payload,
    create_locality,
    create_proposed_agreement,
    get_success_data,
    make_local_authority_headers,
    make_officer_headers,
    setup_locality_and_crossing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _counter(api, agreement_id, cents, headers):
    return api.counter_closure_agreement(
        agreement_id, {"proposed_incentive_cents": cents}, headers
    )


class TestCounterCycle:
    def test_proposed_countered_proposed_cycle_advances_round(
        self, api, admin_headers
    ):
        """PRD §3.5: "A valid counter sets `current_offer_cents` to the proposed
        amount, increments `negotiation_round` by 1, updates `last_offer_by_party`
        and `last_offer_by_user_id`, and flips the state — `PROPOSED` to
        `COUNTERED` or `COUNTERED` back to `PROPOSED`."

        Design: Difficulty/non_linear_state_machine/closure_agreement_counter_cycle
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400001",
                "highway_functional_class": "ARTERIAL",
                "annual_train_count": 3650,
                "train_speed_max_mph": 40,
                "aadt": 2000,
                "school_bus_count": 4,
                "sight_distance_rating": 4,
                "warning_device_class": "GATES",
            }
        )
        # Exposure 20.00 -> computed incentive 250000 + 20*5000 = 350000
        agreement = create_proposed_agreement(crossing["id"], locality["id"])
        assert agreement["computed_incentive_cents"] == 350_000
        assert agreement["negotiation_round"] == 1
        assert agreement["current_offer_cents"] == 350_000

        loc_headers = make_local_authority_headers(locality["id"])
        countered = get_success_data(_counter(api, agreement["id"], 400_000, loc_headers))
        assert countered["status"] == "COUNTERED"
        assert countered["negotiation_round"] == 2
        assert countered["current_offer_cents"] == 400_000
        assert countered["last_offer_by_party"] == "LOCALITY"

        officer2 = make_officer_headers("officer-2")
        cycled = get_success_data(_counter(api, agreement["id"], 375_000, officer2))
        assert cycled["status"] == "PROPOSED", "the PROPOSED<->COUNTERED cycle closes"
        assert cycled["negotiation_round"] == 3
        assert cycled["current_offer_cents"] == 375_000
        assert cycled["computed_incentive_cents"] == 350_000, (
            "computed minimum is fixed at creation and unchanged by counters"
        )

    def test_dot_counter_must_lower_but_never_below_computed_minimum(
        self, api, admin_headers
    ):
        """PRD §3.5: "a DOT counter must *lower* the offer, landing strictly below
        `current_offer_cents` but never below `computed_incentive_cents` (either
        failure is `ERR_INCENTIVE_REGRESSION`)".

        Design: Difficulty/non_linear_state_machine/closure_agreement_counter_cycle
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400003",
                "highway_functional_class": "ARTERIAL",
                "annual_train_count": 3650,
                "train_speed_max_mph": 40,
                "aadt": 2000,
                "school_bus_count": 4,
                "sight_distance_rating": 4,
                "warning_device_class": "GATES",
            }
        )
        agreement = create_proposed_agreement(crossing["id"], locality["id"])
        loc_headers = make_local_authority_headers(locality["id"])
        get_success_data(_counter(api, agreement["id"], 400_000, loc_headers))

        # DOT counter at exactly the computed minimum (350000) is allowed.
        officer2 = make_officer_headers("officer-2")
        lowered = get_success_data(_counter(api, agreement["id"], 350_000, officer2))
        assert lowered["current_offer_cents"] == 350_000
        assert lowered["status"] == "PROPOSED"

        # Now the locality raises again, then DOT tries to counter at or above
        # the standing offer (regression) — rejected.
        get_success_data(_counter(api, agreement["id"], 360_000, loc_headers))
        resp = _counter(api, agreement["id"], 360_000, officer2)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_REGRESSION, expected_status=422)


class TestNegotiationRoundCap:
    def test_sixth_counter_succeeds_seventh_rejected(self, api, admin_headers):
        """PRD §3.5: "the `negotiation_round` must still be below the cap of 6
        rounds (else `ERR_NEGOTIATION_ROUND_LIMIT`)".

        Design: Corner/state_machines/agreement_negotiation_round_cap
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020061"}
        )
        # Exposure 5.00 -> computed incentive 250000 + 5*5000 = 275000
        officer1 = make_officer_headers("officer-1")
        agreement = create_proposed_agreement(crossing["id"], locality["id"])
        assert agreement["computed_incentive_cents"] == 275_000
        loc_headers = make_local_authority_headers(locality["id"])

        # Five alternating counters take the round from 1 to 6.
        moves = [
            (400_000, loc_headers),
            (375_000, officer1),
            (390_000, loc_headers),
            (380_000, officer1),
            (385_000, loc_headers),
        ]
        current = agreement
        for cents, headers in moves:
            current = get_success_data(_counter(api, agreement["id"], cents, headers))
        assert current["negotiation_round"] == 6
        assert current["status"] == "COUNTERED"

        # The next counter arrives at round 6 — the cap rejects it.
        resp = _counter(api, agreement["id"], 384_000, officer1)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT, expected_status=409)
        after = get_success_data(api.get_closure_agreement(agreement["id"], ADMIN))
        assert after["negotiation_round"] == 6
        assert after["status"] == "COUNTERED"
        assert after["current_offer_cents"] == 385_000


class TestCounterPartyRules:
    def test_party_that_tabled_offer_may_not_counter_it(self, api, admin_headers):
        """PRD §3.5: "turns strictly alternate, so the party that tabled the
        current offer may not counter their own offer (else `ERR_COUNTER_TURN`)".

        Design: Corner/validations/counter_wrong_party_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040101"}
        )
        agreement = create_proposed_agreement(crossing["id"], locality["id"])
        # DOT tabled the opening offer; a DOT counter is out of turn.
        resp = _counter(
            api, agreement["id"], 260_000, make_officer_headers("officer-2")
        )
        validate_error(resp, ApiErrorId.ERR_COUNTER_TURN, expected_status=403)
        after = get_success_data(api.get_closure_agreement(agreement["id"], ADMIN))
        assert after["status"] == "PROPOSED"
        assert after["negotiation_round"] == 1

    def test_locality_counter_above_cap_and_regression_rejected(
        self, api, admin_headers
    ):
        """PRD §3.5: "a locality counter must *raise* the offer, landing strictly
        above `current_offer_cents` and at or below the hard cap of 1,000,000
        cents (a counter that fails to raise is `ERR_INCENTIVE_REGRESSION`, one
        above the cap is `ERR_INCENTIVE_CAP_EXCEEDED`)".

        Design: Corner/validations/counter_cap_and_regression
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040111"}
        )
        # Exposure 5.00 -> computed incentive 275000
        agreement = create_proposed_agreement(crossing["id"], locality["id"])
        loc_headers = make_local_authority_headers(locality["id"])

        resp = _counter(api, agreement["id"], 1_000_001, loc_headers)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_CAP_EXCEEDED, expected_status=422)

        resp2 = _counter(api, agreement["id"], 200_000, loc_headers)
        validate_error(resp2, ApiErrorId.ERR_INCENTIVE_REGRESSION, expected_status=422)

        after = get_success_data(api.get_closure_agreement(agreement["id"], ADMIN))
        assert after["negotiation_round"] == 1, "rejected counters never advance the round"
        assert after["current_offer_cents"] == 275_000


class TestSegregationOfDuties:
    def test_officer_who_tabled_dot_offer_cannot_accept_it(self, api, admin_headers):
        """PRD §3.5: "Moving `PROPOSED` or `COUNTERED` to `DOT_ACCEPTED` is a
        `RailSafetyOfficer` action, but when the current offer was tabled by the
        DOT, the accepting officer must not be the same user who tabled it — the
        officer whose `X-User-ID` equals `last_offer_by_user_id` is rejected with
        `ERR_SELF_ACCEPT_FORBIDDEN`. Acceptance records `dot_accepted_by_user_id`."

        Design: Corner/rbac/closure_self_accept_forbidden
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-060021"}
        )
        agreement = create_proposed_agreement(
            crossing["id"], locality["id"], creator_user_id="officer-1"
        )

        resp = api.transition_closure_agreement(
            agreement["id"],
            {"to_status": "DOT_ACCEPTED"},
            make_officer_headers("officer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_ACCEPT_FORBIDDEN, expected_status=403)

        accepted = get_success_data(
            api.transition_closure_agreement(
                agreement["id"],
                {"to_status": "DOT_ACCEPTED"},
                make_officer_headers("officer-2"),
            )
        )
        assert accepted["status"] == "DOT_ACCEPTED"
        assert accepted["dot_accepted_by_user_id"] == "officer-2"

    def test_ratify_requires_owning_locality(self, api, admin_headers):
        """PRD §3.5: "The locality then ratifies: a `LocalAuthority` caller whose
        `X-User-ID` equals the agreement's `locality_id` (else
        `ERR_LOCALITY_MISMATCH`) moves `DOT_ACCEPTED` → `LOCALITY_RATIFIED`."

        Design: Corner/rbac/ratify_wrong_locality_rejected
        """
        loc1 = create_locality(locality_name="Ratify One")
        loc2 = create_locality(locality_name="Ratify Two")
        from test_helpers import create_crossing

        crossing = create_crossing(loc1["id"], dot_crossing_number="DOT-060031")
        agreement = create_proposed_agreement(crossing["id"], loc1["id"])
        get_success_data(
            api.transition_closure_agreement(
                agreement["id"],
                {"to_status": "DOT_ACCEPTED"},
                make_officer_headers("officer-2"),
            )
        )

        resp = api.transition_closure_agreement(
            agreement["id"],
            {"to_status": "LOCALITY_RATIFIED"},
            make_local_authority_headers(loc2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOCALITY_MISMATCH, expected_status=403)
        after = get_success_data(api.get_closure_agreement(agreement["id"], ADMIN))
        assert after["status"] == "DOT_ACCEPTED"


class TestConsolidationIncentiveAndSelfConsolidation:
    def test_consolidation_incentive_computed_at_creation(self, api, admin_headers):
        """PRD §3.5: "`computed_incentive_cents` is a base of 250,000 cents for a
        `CLOSURE` or 175,000 cents for a `CONSOLIDATION`, plus 5,000 cents for
        each point of the crossing's snapshot `exposure_index` with the exposure
        contribution capped at 50 points, all in whole cents. The negotiable
        `current_offer_cents` starts equal to that computed minimum, and the
        `negotiation_round` starts at 0 while the agreement sits in `DRAFT`."

        Design: Corner/calculations/consolidation_incentive_computed
        """
        locality = create_locality(locality_name="Incentive City")
        from test_helpers import create_crossing

        subject = create_crossing(
            locality["id"],
            dot_crossing_number="DOT-030021",
            annual_train_count=730,
            aadt=5000,
        )  # exposure 10.00
        target = create_crossing(locality["id"], dot_crossing_number="DOT-030022")

        resp = api.create_closure_agreement(
            create_closure_agreement_payload(
                crossing_id=subject["id"],
                locality_id=locality["id"],
                closure_type="CONSOLIDATION",
                consolidation_target_crossing_id=target["id"],
            ),
            make_officer_headers("officer-1"),
        )
        data = validate_success(resp, expected_status=201)
        assert_closure_agreement(data)
        assert data["computed_incentive_cents"] == 175_000 + 10 * 5_000 == 225_000
        assert data["current_offer_cents"] == 225_000
        assert data["negotiation_round"] == 0
        assert data["status"] == "DRAFT"

    def test_self_consolidation_rejected(self, api, admin_headers):
        """PRD §3.5: "it must differ from the crossing being closed (a
        self-reference is rejected with `ERR_SELF_CONSOLIDATION`)".

        Design: Corner/validations/self_consolidation_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040001"}
        )
        resp = api.create_closure_agreement(
            create_closure_agreement_payload(
                crossing_id=crossing["id"],
                locality_id=locality["id"],
                closure_type="CONSOLIDATION",
                consolidation_target_crossing_id=crossing["id"],
            ),
            make_officer_headers("officer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_CONSOLIDATION, expected_status=422)
