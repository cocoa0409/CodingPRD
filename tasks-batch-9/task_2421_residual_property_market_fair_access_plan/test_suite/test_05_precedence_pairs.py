"""Requests that break two rules at once and must report the higher-precedence one.

Each scenario is arranged so that two independent gates are both violated by the
same call. The reported error identifies which rung the server evaluated first,
and the lower rung's error must never surface.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_BINDABLE,
    ERR_BIND_DEADLINE_PASSED,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_OFFER_NOT_COMPARABLE,
    ERR_ZONE_CLOSED,
    ERR_ZONE_EXPOSURE_CAP_EXCEEDED,
)
from test_helpers.assertions import assert_cents, assert_field_equals, assert_ratio
from test_helpers.constants import (
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_BOUND,
    CONSTRUCTION_MASONRY,
    COVERAGE_STATUS_IN_FORCE,
    DEPOP_STATUS_NOT_OFFERED,
    MEMBER_STATUS_RUNOFF,
    ZONE_STATUS_CLOSED,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    bind,
    bind_exposure,
    build_bindable_application,
    build_in_force_policy,
    pin_clock,
    read_member,
    read_zone,
)
from test_helpers.test_users import (
    admin_headers,
    binder_headers,
    make_member_insurer_headers,
    third_underwriter_headers,
)

PAST_DEADLINE_CLOCK = "2026-10-02T00:00:00Z"
PAST_DEADLINE_DATE = "2026-10-02"
BOUND_ANNUAL_PREMIUM_CENTS = 577_125
FULL_ZONE_ANNUAL_PREMIUM_CENTS = 810_000
UNCOMPARABLE_OFFER_CENTS = 900_000


def _bound_policy_past_its_bind_deadline(
    foundations: Foundations,
) -> ApplicationChain:
    """The application is BOUND and the clock has run past its bind window."""
    chain = build_bindable_application(foundations.client, foundations)
    bind(chain)
    pin_clock(foundations.client, PAST_DEADLINE_CLOCK)
    chain.refresh_application()
    return chain


def _closed_zone_with_one_more_bindable_application(
    foundations: Foundations,
) -> ApplicationChain:
    """The territory is full and CLOSED, with one more risk waiting to bind."""
    bind_exposure(
        foundations.client,
        foundations,
        dwelling_limit_cents=100_000_000,
        address_line="1 Shore Rd",
        construction_type=CONSTRUCTION_MASONRY,
        condition_score=88,
        observed_condition_score=88,
        replacement_cost_cents=100_000_000,
    )
    return build_bindable_application(
        foundations.client,
        foundations,
        observed_condition_score=88,
        applicant_overrides={"full_name": "Bo Owner", "email": "bo@example.com"},
        property_overrides={
            "address_line": "2 Shore Rd",
            "construction_type": CONSTRUCTION_MASONRY,
            "roof_age_years": 4,
            "replacement_cost_cents": 20_000_000,
            "condition_score": 88,
        },
        application_overrides={"requested_dwelling_limit_cents": 10_000_000},
    )


def _in_force_policy_and_a_runoff_carrier(
    foundations: Foundations,
) -> ApplicationChain:
    """Carrier One walks ACTIVE to RUNOFF while the policy stays in force."""
    chain = build_in_force_policy(foundations.client, foundations)
    response = foundations.client.update_member_insurer(
        foundations.members[0]["id"],
        f.member_status_payload(MEMBER_STATUS_RUNOFF),
        admin_headers(),
    )
    assert response.status_code == 200, response.text
    return chain


# ---------------------------------------------------------------------------
# Bindability outranks the bind window
# ---------------------------------------------------------------------------


def test_rebinding_a_bound_application_reports_the_state_error(
    foundations: Foundations,
) -> None:
    """Both gates are broken, and only the earlier rung is reported.

    PRD: "Where more than one rule could reject a request, the plan evaluates them in a fixed precedence so that the reported error is deterministic."

    PRD: "Application bindability: status `APPROVED_TO_BIND`, or `ERR_APPLICATION_NOT_BINDABLE` (409)."

    PRD: "The bind clock instant must be at or before the application's `bind_deadline_at`, or `ERR_BIND_DEADLINE_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/rebind_state_error_precedes_bind_deadline_error
    """
    chain = _bound_policy_past_its_bind_deadline(foundations)

    response = foundations.client.bind_policy(
        f.bind_payload(chain.application_id, PAST_DEADLINE_DATE),
        third_underwriter_headers(),
    )

    error = validate_error(response, ERR_APPLICATION_NOT_BINDABLE)
    assert error["error_id"] != ERR_BIND_DEADLINE_PASSED


def test_refused_rebind_leaves_exactly_one_policy_on_the_application(
    foundations: Foundations,
) -> None:
    """The rejected second bind writes nothing at all.

    PRD: "Binding is the `Underwriter`'s act of turning an approved application into a plan policy, and it is the most heavily gated operation in the system."

    PRD: "`BOUND`, `DECLINED` and `WITHDRAWN` are the terminal application states."

    Design: Difficulty/priority_pair_validation_conflict/rebind_state_error_precedes_bind_deadline_error
    """
    chain = _bound_policy_past_its_bind_deadline(foundations)

    response = foundations.client.bind_policy(
        f.bind_payload(chain.application_id, PAST_DEADLINE_DATE),
        third_underwriter_headers(),
    )
    validate_error(response, ERR_APPLICATION_NOT_BINDABLE)

    assert_field_equals(chain.refresh_application(), "status", APP_STATUS_BOUND)
    policies, meta = validate_paginated(
        foundations.client.list_policies(admin_headers(), {"limit": 100})
    )
    assert_field_equals(meta, "total_count", 1)
    assert_cents(
        policies[0]["annual_premium_cents"],
        BOUND_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )


# ---------------------------------------------------------------------------
# A closed territory outranks the exposure cap
# ---------------------------------------------------------------------------


def test_binding_into_a_full_territory_reports_the_closed_status(
    foundations: Foundations,
) -> None:
    """The territory is both `CLOSED` and out of headroom; closure is reported.

    PRD: "Territory not closed for binding or renewal, or `ERR_ZONE_CLOSED` (409)."

    PRD: "Finally, the territory must have headroom: its `aggregate_insured_value_cents` plus this policy's `exposure_value_cents` must be no greater than its `exposure_cap_cents`, or `ERR_ZONE_EXPOSURE_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_zone_error_precedes_exposure_cap_error
    """
    chain = _closed_zone_with_one_more_bindable_application(foundations)

    response = foundations.client.bind_policy(
        f.bind_payload(chain.application_id), binder_headers()
    )

    error = validate_error(response, ERR_ZONE_CLOSED)
    assert error["error_id"] != ERR_ZONE_EXPOSURE_CAP_EXCEEDED


def test_refused_bind_leaves_the_territory_and_the_application_unchanged(
    foundations: Foundations,
) -> None:
    """Nothing is written: the ratio stays at 1.0000 and the application waits.

    PRD: "The property's territory must not be `CLOSED`, or `ERR_ZONE_CLOSED`."

    PRD: "Both thresholds are inclusive, so a ratio of exactly 0.8500 is `RESTRICTED` and a ratio of exactly 1.0000 is `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_zone_error_precedes_exposure_cap_error
    """
    chain = _closed_zone_with_one_more_bindable_application(foundations)

    response = foundations.client.bind_policy(
        f.bind_payload(chain.application_id), binder_headers()
    )
    validate_error(response, ERR_ZONE_CLOSED)

    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        100_000_000,
        "aggregate_insured_value_cents",
    )
    assert_ratio(zone["concentration_ratio"], "1.0000", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_CLOSED)
    assert_field_equals(
        chain.refresh_application(), "status", APP_STATUS_APPROVED_TO_BIND
    )
    _policies, meta = validate_paginated(
        foundations.client.list_policies(admin_headers(), {"limit": 100})
    )
    assert_field_equals(meta, "total_count", 1)


# ---------------------------------------------------------------------------
# Member standing outranks offer comparability
# ---------------------------------------------------------------------------


def test_offer_from_a_runoff_carrier_reports_the_standing_error(
    foundations: Foundations,
) -> None:
    """A run-off carrier's uncomparable offer fails on standing, not on price.

    PRD: "Member standing, or `ERR_MEMBER_NOT_ACTIVE` (409), on take-out offer creation and allocation payment."

    PRD: "For the offer to be a genuine alternative rather than a price trap, `comparable_coverage_flag` must be true **and** `offered_premium_cents` must be no greater than the plan's `annual_premium_cents` multiplied by 1.15 and rounded half up to whole cents; either failure is refused with `ERR_OFFER_NOT_COMPARABLE`."

    Design: Difficulty/priority_pair_validation_conflict/member_not_active_error_precedes_offer_not_comparable_error
    """
    chain = _in_force_policy_and_a_runoff_carrier(foundations)
    carrier_id = foundations.members[0]["id"]

    response = foundations.client.create_takeout_offer(
        chain.policy_id,
        f.takeout_offer_payload(
            member_insurer_id=carrier_id,
            offered_premium_cents=UNCOMPARABLE_OFFER_CENTS,
            comparable_coverage_flag=False,
        ),
        make_member_insurer_headers(carrier_id),
    )

    error = validate_error(response, ERR_MEMBER_NOT_ACTIVE)
    assert error["error_id"] != ERR_OFFER_NOT_COMPARABLE
    assert_field_equals(
        read_member(foundations.client, carrier_id), "status", MEMBER_STATUS_RUNOFF
    )


def test_refused_offer_leaves_the_policy_undepopulated(
    foundations: Foundations,
) -> None:
    """No offer row is created and the depopulation dimension does not move.

    PRD: "Making an offer requires the target policy's `coverage_status` to be `IN_FORCE` (otherwise `ERR_POLICY_NOT_IN_FORCE`) and its `depopulation_status` to be `NOT_OFFERED` (otherwise `ERR_OFFER_ALREADY_OUTSTANDING`), and the offering carrier's membership `status` to be `ACTIVE` — a carrier in `RUNOFF` or `WITHDRAWN` may not offer, and is refused with `ERR_MEMBER_NOT_ACTIVE`."

    PRD: "Moving `ACTIVE → RUNOFF` requires the carrier to currently be `ACTIVE`; a carrier in run-off **remains assessable** and stays inside the eligible member set used by allocation runs, but it may no longer create take-out offers."

    Design: Difficulty/priority_pair_validation_conflict/member_not_active_error_precedes_offer_not_comparable_error
    """
    chain = _in_force_policy_and_a_runoff_carrier(foundations)
    carrier_id = foundations.members[0]["id"]

    response = foundations.client.create_takeout_offer(
        chain.policy_id,
        f.takeout_offer_payload(
            member_insurer_id=carrier_id,
            offered_premium_cents=UNCOMPARABLE_OFFER_CENTS,
            comparable_coverage_flag=False,
        ),
        make_member_insurer_headers(carrier_id),
    )
    validate_error(response, ERR_MEMBER_NOT_ACTIVE)

    policy = chain.refresh_policy()
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    assert_field_equals(policy, "depopulation_status", DEPOP_STATUS_NOT_OFFERED)
    _offers, meta = validate_paginated(
        foundations.client.list_takeout_offers(admin_headers(), {"limit": 100})
    )
    assert_field_equals(meta, "total_count", 0)
