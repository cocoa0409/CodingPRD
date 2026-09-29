"""Requests whose outcome is decided by a second entity's state, not their own.

Each pair of calls is identical in everything the request itself controls; what
diverges is the state of a related record — a territory's derived posture, a
carrier's membership standing, an agent's appointment — so the same payload is
refused in one arrangement and honoured in the other.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_MEMBER_NOT_ACTIVE,
    ERR_PRODUCER_NOT_APPOINTED,
    ERR_ZONE_RESTRICTED_INELIGIBLE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_field_equals,
    assert_field_null,
    assert_instant_equals,
    assert_ratio,
)
from test_helpers.constants import (
    AGREEMENT_STATUS_APPOINTED,
    AGREEMENT_STATUS_SUSPENDED,
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_DRAFT,
    APP_STATUS_SUBMITTED,
    CLOCK_BASE,
    CONSTRUCTION_FRAME,
    CONSTRUCTION_MASONRY,
    COVERAGE_STATUS_IN_FORCE,
    DEPOP_STATUS_NOT_OFFERED,
    DEPOP_STATUS_OFFER_OUTSTANDING,
    MEMBER_STATUS_RUNOFF,
    OFFER_STATUS_OUTSTANDING,
    PRODUCER_ACTION_REINSTATE,
    PRODUCER_ACTION_SUSPEND,
    ZONE_STATUS_RESTRICTED,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    add_three_declinations,
    bind,
    bind_exposure,
    build_bindable_application,
    build_in_force_policy,
    create_draft_application,
    read_application,
    read_producer,
    read_zone,
    submit,
)
from test_helpers.test_users import (
    admin_headers,
    binder_headers,
    make_member_insurer_headers,
)

RESTRICTED_BASE_PREMIUM_CENTS = 90_000
RESTRICTED_SURCHARGE_CENTS = 10_125
RESTRICTED_ANNUAL_PREMIUM_CENTS = 90_112
SMALL_DWELLING_LIMIT_CENTS = 10_000_000
HARDENED_CONDITION_SCORE = 88
QUOTED_ANNUAL_PREMIUM_CENTS = 546_750
OFFERED_PREMIUM_CENTS = 600_000


def _restricted_zone_with_two_waiting_risks(
    foundations: Foundations,
) -> tuple:
    """A territory at exactly 0.8500, plus a FRAME and a MASONRY risk to bind."""
    bind_exposure(
        foundations.client,
        foundations,
        dwelling_limit_cents=85_000_000,
        address_line="1 Shore Rd",
        construction_type=CONSTRUCTION_MASONRY,
        observed_condition_score=HARDENED_CONDITION_SCORE,
    )
    frame_chain = build_bindable_application(
        foundations.client,
        foundations,
        observed_condition_score=HARDENED_CONDITION_SCORE,
        applicant_overrides={"full_name": "Fay Frame", "email": "fay@example.com"},
        property_overrides={
            "address_line": "2 Shore Rd",
            "construction_type": CONSTRUCTION_FRAME,
        },
        application_overrides={
            "requested_dwelling_limit_cents": SMALL_DWELLING_LIMIT_CENTS
        },
    )
    masonry_chain = build_bindable_application(
        foundations.client,
        foundations,
        observed_condition_score=HARDENED_CONDITION_SCORE,
        applicant_overrides={"full_name": "Mel Masonry", "email": "mel@example.com"},
        property_overrides={
            "address_line": "3 Shore Rd",
            "construction_type": CONSTRUCTION_MASONRY,
        },
        application_overrides={
            "requested_dwelling_limit_cents": SMALL_DWELLING_LIMIT_CENTS
        },
    )
    return frame_chain, masonry_chain


def _in_force_policy_with_one_carrier_in_runoff(
    foundations: Foundations,
) -> ApplicationChain:
    """Carrier One steps back to RUNOFF; Carrier Two keeps its ACTIVE standing."""
    chain = build_in_force_policy(foundations.client, foundations)
    response = foundations.client.update_member_insurer(
        foundations.members[0]["id"],
        f.member_status_payload(MEMBER_STATUS_RUNOFF),
        admin_headers(),
    )
    assert response.status_code == 200, response.text
    return chain


def _draft_application_of_a_suspended_producer(
    foundations: Foundations,
) -> ApplicationChain:
    """The application is complete and DRAFT; only its agent has been suspended."""
    chain = create_draft_application(foundations.client, foundations)
    add_three_declinations(chain)
    response = foundations.client.producer_status_action(
        foundations.producer_id,
        f.producer_status_action_payload(PRODUCER_ACTION_SUSPEND),
        admin_headers(),
    )
    assert response.status_code == 200, response.text
    return chain


# ---------------------------------------------------------------------------
# A policy's fate hangs on its territory's derived posture
# ---------------------------------------------------------------------------


def test_restricted_territory_refuses_a_frame_risk(
    foundations: Foundations,
) -> None:
    """The application is faultless; the territory's posture is what refuses it.

    PRD: "Where the territory is `RESTRICTED`, the plan writes only hardened risks: the property's `construction_type` must be `MASONRY` **and** the rating condition score — the chosen inspection's `observed_condition_score` at bind — must be at least the territory's `restricted_min_condition_score`; failing either condition yields `ERR_ZONE_RESTRICTED_INELIGIBLE`."

    PRD: "Both thresholds are inclusive, so a ratio of exactly 0.8500 is `RESTRICTED` and a ratio of exactly 1.0000 is `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/bind_in_restricted_zone_depends_on_zone_status_and_construction
    """
    frame_chain, _masonry_chain = _restricted_zone_with_two_waiting_risks(foundations)
    zone = read_zone(foundations.client, foundations.zone_id)
    assert_ratio(zone["concentration_ratio"], "0.8500", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_RESTRICTED)

    response = foundations.client.bind_policy(
        f.bind_payload(frame_chain.application_id), binder_headers()
    )

    validate_error(response, ERR_ZONE_RESTRICTED_INELIGIBLE)
    assert_field_equals(
        frame_chain.refresh_application(), "status", APP_STATUS_APPROVED_TO_BIND
    )


def test_restricted_territory_admits_a_hardened_masonry_risk(
    foundations: Foundations,
) -> None:
    """The same territory takes the MASONRY twin, surcharged on the posted ratio.

    PRD: "Read the territory's `concentration_ratio` **before** this policy's own exposure is added to the territory."

    PRD: "The `coverage_status` starts at `IN_FORCE` when the `effective_date` is on or before the bind clock date, and at `BOUND` when the policy is future-dated."

    Design: Difficulty/cross_entity_state_dependency/bind_in_restricted_zone_depends_on_zone_status_and_construction
    """
    _frame_chain, masonry_chain = _restricted_zone_with_two_waiting_risks(foundations)

    policy = bind(masonry_chain)

    assert_cents(
        policy["base_premium_cents"],
        RESTRICTED_BASE_PREMIUM_CENTS,
        "base_premium_cents",
    )
    assert_cents(
        policy["cat_surcharge_cents"], RESTRICTED_SURCHARGE_CENTS, "cat_surcharge_cents"
    )
    assert_cents(
        policy["annual_premium_cents"],
        RESTRICTED_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)

    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        95_000_000,
        "aggregate_insured_value_cents",
    )
    assert_ratio(zone["concentration_ratio"], "0.9500", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_RESTRICTED)


# ---------------------------------------------------------------------------
# An offer's fate hangs on the offering carrier's membership standing
# ---------------------------------------------------------------------------


def test_offer_from_the_runoff_carrier_is_refused(
    foundations: Foundations,
) -> None:
    """A perfectly comparable offer fails purely on the carrier's standing.

    PRD: "Making an offer requires the target policy's `coverage_status` to be `IN_FORCE` (otherwise `ERR_POLICY_NOT_IN_FORCE`) and its `depopulation_status` to be `NOT_OFFERED` (otherwise `ERR_OFFER_ALREADY_OUTSTANDING`), and the offering carrier's membership `status` to be `ACTIVE` — a carrier in `RUNOFF` or `WITHDRAWN` may not offer, and is refused with `ERR_MEMBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/takeout_offer_creation_depends_on_member_insurer_status
    """
    chain = _in_force_policy_with_one_carrier_in_runoff(foundations)
    runoff_carrier = foundations.members[0]["id"]

    response = foundations.client.create_takeout_offer(
        chain.policy_id,
        f.takeout_offer_payload(
            member_insurer_id=runoff_carrier,
            offered_premium_cents=OFFERED_PREMIUM_CENTS,
        ),
        make_member_insurer_headers(runoff_carrier),
    )

    validate_error(response, ERR_MEMBER_NOT_ACTIVE)
    assert_field_equals(chain.refresh_policy(), "depopulation_status", DEPOP_STATUS_NOT_OFFERED)
    _offers, meta = validate_paginated(
        foundations.client.list_takeout_offers(admin_headers(), {"limit": 100})
    )
    assert_field_equals(meta, "total_count", 0)


def test_identical_offer_from_the_active_carrier_is_created(
    foundations: Foundations,
) -> None:
    """The same price and terms from an ACTIVE carrier flip the second dimension.

    PRD: "The offer is created in `status` `OUTSTANDING` with `elected_at`, `withdrawal_reason` null and `credit_units_granted` at 0, and the policy's second state dimension moves `NOT_OFFERED → OFFER_OUTSTANDING` with the policy's `version` incremented by one."

    PRD: "The coverage dimension is completely untouched by this move — `depopulation_status` and `coverage_status` are independent dimensions carried on the same policy record."

    Design: Difficulty/cross_entity_state_dependency/takeout_offer_creation_depends_on_member_insurer_status
    """
    chain = _in_force_policy_with_one_carrier_in_runoff(foundations)
    active_carrier = foundations.members[1]["id"]

    response = foundations.client.create_takeout_offer(
        chain.policy_id,
        f.takeout_offer_payload(
            member_insurer_id=active_carrier,
            offered_premium_cents=OFFERED_PREMIUM_CENTS,
        ),
        make_member_insurer_headers(active_carrier),
    )
    offer = validate_success(response, 201)

    assert_field_equals(offer, "status", OFFER_STATUS_OUTSTANDING)
    assert_field_equals(offer, "member_insurer_id", active_carrier)
    assert_field_equals(offer, "credit_units_granted", 0)
    policy = chain.refresh_policy()
    assert_field_equals(policy, "depopulation_status", DEPOP_STATUS_OFFER_OUTSTANDING)
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    _offers, meta = validate_paginated(
        foundations.client.list_takeout_offers(
            admin_headers(), {"limit": 100, "policy_id": chain.policy_id}
        )
    )
    assert_field_equals(meta, "total_count", 1)


# ---------------------------------------------------------------------------
# A submission's fate hangs on its agent's appointment
# ---------------------------------------------------------------------------


def test_suspended_producer_cannot_submit_the_application(
    roomy_foundations: Foundations,
) -> None:
    """Nothing about the application changed; its agent's standing did.

    PRD: "An `action` of `SUSPEND` requires `APPOINTED` and moves the agreement `APPOINTED → SUSPENDED`; while suspended the agent may neither create nor submit applications, and no policy may be bound on an application of theirs, but existing policies are left completely untouched and `ytd_commission_cents` does not move."

    PRD: "The producer's agreement must be `APPOINTED`, and an approved rate must exist for the property's territory and the requested package with an `effective_date` on or before the current clock date, selected by the rule in §3.2."

    Design: Difficulty/cross_entity_state_dependency/application_submission_depends_on_producer_agreement_status
    """
    chain = _draft_application_of_a_suspended_producer(roomy_foundations)
    assert_field_equals(
        read_producer(roomy_foundations.client, roomy_foundations.producer_id),
        "agreement_status",
        AGREEMENT_STATUS_SUSPENDED,
    )

    response = roomy_foundations.client.submit_application(
        chain.application_id, {}, chain.producer_headers
    )

    validate_error(response, ERR_PRODUCER_NOT_APPOINTED)
    application = read_application(roomy_foundations.client, chain.application_id)
    assert_field_equals(application, "status", APP_STATUS_DRAFT)
    assert_field_null(application, "submitted_at")


def test_reinstated_producer_submits_the_very_same_application(
    roomy_foundations: Foundations,
) -> None:
    """Reinstatement alone carries the untouched draft through to SUBMITTED.

    PRD: "An `action` of `REINSTATE` requires `SUSPENDED` and moves it back `SUSPENDED → APPOINTED`, retaining the `commission_rate_bps` written at agreement execution rather than recomputing it — the suspend-and-reinstate loop may repeat any number of times."

    PRD: "Whatever the outcome, a successful submission writes `submitted_at` to the current logical clock, writes `declination_count` from the sufficiency test just described, pins `quote_rate_filing_id` to the filing that rate selection chose, writes the three quote fields, and increments the application's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/application_submission_depends_on_producer_agreement_status
    """
    chain = _draft_application_of_a_suspended_producer(roomy_foundations)
    refused = roomy_foundations.client.submit_application(
        chain.application_id, {}, chain.producer_headers
    )
    validate_error(refused, ERR_PRODUCER_NOT_APPOINTED)

    reinstated = validate_success(
        roomy_foundations.client.producer_status_action(
            roomy_foundations.producer_id,
            f.producer_status_action_payload(PRODUCER_ACTION_REINSTATE, reason=None),
            admin_headers(),
        )
    )
    assert_field_equals(reinstated, "agreement_status", AGREEMENT_STATUS_APPOINTED)

    application = submit(chain)
    assert_field_equals(application, "status", APP_STATUS_SUBMITTED)
    assert_field_equals(application, "declination_count", 3)
    assert_cents(
        application["quoted_annual_premium_cents"],
        QUOTED_ANNUAL_PREMIUM_CENTS,
        "quoted_annual_premium_cents",
    )
    assert_instant_equals(application["submitted_at"], CLOCK_BASE, "submitted_at")
