"""Two different interval rules probed at the day where they stop colliding.

A policy term is a half-open interval on a property, so a successor may start on
the very day its predecessor ends. A rate filing's quiet buffer is a closed
thirty-day window on a territory-and-package pair, so the thirtieth day clears
and the twenty-ninth does not.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import FairPlanApiClient
from test_helpers.api_errors import (
    ERR_FILING_WINDOW_CONFLICT,
    ERR_POLICY_TERM_OVERLAP,
)
from test_helpers.assertions import (
    assert_cents,
    assert_date_equals,
    assert_field_equals,
    assert_field_null,
    assert_ratio,
    shift_date,
)
from test_helpers.constants import (
    COVERAGE_STATUS_BOUND,
    COVERAGE_STATUS_IN_FORCE,
    FILING_STATUS_APPROVED,
    FILING_STATUS_FILED,
    FILING_STATUS_SUPERSEDED,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    build_in_force_policy,
    create_zone,
    file_rate,
    pin_clock,
    read_filing,
    read_policy,
    read_producer,
    renew_policy,
    review_filing,
)
from test_helpers.test_users import admin_headers, binder_headers, regulator_headers

TERM_EFFECTIVE_DATE = "2026-09-01"
TERM_EXPIRATION_DATE = "2027-09-01"
OVERLAPPING_RENEWAL_DATE = "2027-08-31"
TOUCHING_RENEWAL_DATE = "2027-09-01"
TERM_ANNUAL_PREMIUM_CENTS = 577_125
CONDITION_SCORE_AT_BIND = 72
TWO_TERM_YTD_COMMISSION_CENTS = 115_426

INCUMBENT_EFFECTIVE_DATE = "2026-08-01"
INSIDE_BUFFER_EFFECTIVE_DATE = "2026-08-30"
BUFFER_CLEARING_EFFECTIVE_DATE = "2026-08-31"
ROOMY_CAP_CENTS = 900_000_000


def _in_force_term_on_one_property(foundations: Foundations) -> ApplicationChain:
    """One IN_FORCE policy occupying [2026-09-01, 2027-09-01) on its property."""
    chain = build_in_force_policy(foundations.client, foundations)
    policy = chain.refresh_policy()
    assert_date_equals(policy["effective_date"], TERM_EFFECTIVE_DATE, "effective_date")
    assert_date_equals(
        policy["expiration_date"], TERM_EXPIRATION_DATE, "expiration_date"
    )
    return chain


def _one_approved_filing_and_two_candidates(client: FairPlanApiClient) -> tuple:
    """An APPROVED incumbent plus two FILED candidates astride its quiet buffer."""
    pin_clock(client)
    zone = create_zone(client, exposure_cap_cents=ROOMY_CAP_CENTS)
    incumbent = file_rate(client, zone["id"], effective_date=INCUMBENT_EFFECTIVE_DATE)
    incumbent = review_filing(client, incumbent["id"])
    inside_buffer = file_rate(
        client, zone["id"], effective_date=INSIDE_BUFFER_EFFECTIVE_DATE
    )
    clears_buffer = file_rate(
        client, zone["id"], effective_date=BUFFER_CLEARING_EFFECTIVE_DATE
    )
    return incumbent, inside_buffer, clears_buffer


# ---------------------------------------------------------------------------
# The half-open policy term on a property
# ---------------------------------------------------------------------------


def test_renewal_starting_a_day_early_intersects_the_running_term(
    roomy_foundations: Foundations,
) -> None:
    """2027-08-31 falls inside [2026-09-01, 2027-09-01) and so collides.

    PRD: "The new half-open term must not intersect the term of any policy on the same `property_id` whose `coverage_status` is `BOUND` or `IN_FORCE` — touching endpoints, where the new `effective_date` equals an existing `expiration_date`, do not collide — or `ERR_POLICY_TERM_OVERLAP`."

    PRD: "A policy term is a **half-open interval** running from its `effective_date` up to but not including its `expiration_date`."

    Design: Difficulty/resource_temporal_overlap/policy_term_half_open_interval_on_the_same_property
    """
    chain = _in_force_term_on_one_property(roomy_foundations)

    response = roomy_foundations.client.renew_policy(
        chain.policy_id, f.renewal_payload(OVERLAPPING_RENEWAL_DATE), binder_headers()
    )

    validate_error(response, ERR_POLICY_TERM_OVERLAP)
    incumbent = read_policy(roomy_foundations.client, chain.policy_id)
    assert_field_equals(incumbent, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    _policies, meta = validate_paginated(
        roomy_foundations.client.list_policies(
            admin_headers(), {"limit": 100, "property_id": chain.property_id}
        )
    )
    assert_field_equals(meta, "total_count", 1)


def test_renewal_starting_on_the_expiration_day_touches_without_colliding(
    roomy_foundations: Foundations,
) -> None:
    """2027-09-01 is the excluded end of the running term, so the successor stands.

    PRD: "That is what makes a successor term starting exactly on the day a predecessor term ends legal rather than overlapping."

    PRD: "The successor is created with `predecessor_policy_id` pointing at the policy being renewed, its `condition_score_at_bind` carried forward from the predecessor, its premium computed under the `RENEWAL_FINAL` variant, its exposure added to the territory with the concentration ratio recomputed and the status re-derived, and producer commission credited on the successor."

    PRD: "The `effective_date` comes from the request and the `expiration_date` is set to three hundred sixty-five days after it, marking the exclusive end of the term."

    Design: Difficulty/resource_temporal_overlap/policy_term_half_open_interval_on_the_same_property
    """
    chain = _in_force_term_on_one_property(roomy_foundations)

    successor = renew_policy(chain, effective_date=TOUCHING_RENEWAL_DATE)

    assert_date_equals(
        successor["effective_date"], TOUCHING_RENEWAL_DATE, "effective_date"
    )
    assert_date_equals(
        successor["expiration_date"],
        shift_date(TOUCHING_RENEWAL_DATE, 365),
        "expiration_date",
    )
    assert_field_equals(successor, "predecessor_policy_id", chain.policy_id)
    assert_field_equals(
        successor, "condition_score_at_bind", CONDITION_SCORE_AT_BIND
    )
    assert_cents(successor["cat_surcharge_cents"], 0, "cat_surcharge_cents")
    assert_cents(
        successor["annual_premium_cents"],
        TERM_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(successor, "coverage_status", COVERAGE_STATUS_BOUND)

    _policies, meta = validate_paginated(
        roomy_foundations.client.list_policies(
            admin_headers(), {"limit": 100, "property_id": chain.property_id}
        )
    )
    assert_field_equals(meta, "total_count", 2)


def test_renewal_credits_commission_on_the_successor_as_well(
    roomy_foundations: Foundations,
) -> None:
    """The agent's conserved ledger carries both terms of the same property.

    PRD: "A producer's `ytd_commission_cents` is a conserved quantity recomputed after every credit and every return: it is the sum, over **all** policies whose `producer_id` is that producer, of `commission_credited_cents` minus `commission_returned_cents`."

    PRD: "The predecessor is left untouched by the renewal itself."

    Design: Difficulty/resource_temporal_overlap/policy_term_half_open_interval_on_the_same_property
    """
    chain = _in_force_term_on_one_property(roomy_foundations)

    renew_policy(chain, effective_date=TOUCHING_RENEWAL_DATE)

    producer = read_producer(roomy_foundations.client, roomy_foundations.producer_id)
    assert_cents(
        producer["ytd_commission_cents"],
        TWO_TERM_YTD_COMMISSION_CENTS,
        "ytd_commission_cents",
    )
    incumbent = read_policy(roomy_foundations.client, chain.policy_id)
    assert_date_equals(
        incumbent["expiration_date"], TERM_EXPIRATION_DATE, "expiration_date"
    )
    assert_field_equals(incumbent, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    assert_field_null(incumbent, "predecessor_policy_id")


# ---------------------------------------------------------------------------
# The thirty-day quiet buffer on a territory-and-package pair
# ---------------------------------------------------------------------------


def test_approval_inside_the_quiet_buffer_collides(
    client: FairPlanApiClient,
) -> None:
    """Day twenty-nine after the incumbent is still inside the buffer.

    PRD: "Approval carries one further temporal gate: filings on the same territory-and-package pair must be separated by a **thirty-day quiet buffer**, so the filing being approved must have an `effective_date` no earlier than the `effective_date` of the latest already-`APPROVED` filing on that pair plus thirty days."

    PRD: "An `effective_date` that lands anywhere inside that buffer — including exactly the twenty-ninth day after the incumbent's effective date — collides and is rejected with `ERR_FILING_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rate_filing_buffered_quiet_window_on_zone_and_package
    """
    incumbent, inside_buffer, _clears = _one_approved_filing_and_two_candidates(client)

    response = client.review_rate_filing(
        inside_buffer["id"], f.filing_review_payload(), regulator_headers()
    )

    validate_error(response, ERR_FILING_WINDOW_CONFLICT)
    refused = read_filing(client, inside_buffer["id"])
    assert_field_equals(refused, "status", FILING_STATUS_FILED)
    assert_field_null(refused, "reviewed_by_user_id")
    assert_field_equals(
        read_filing(client, incumbent["id"]), "status", FILING_STATUS_APPROVED
    )


def test_approval_on_the_thirtieth_day_clears_and_supersedes(
    client: FairPlanApiClient,
) -> None:
    """Day thirty exactly satisfies the buffer and retires the incumbent.

    PRD: "`FILED → APPROVED` writes the reviewer fields and increments the filing's `version` by one; it then transitions the previously `APPROVED` filing on the same territory-and-package pair, if one exists, from `APPROVED` to the terminal `SUPERSEDED` (that supersede applies when the newly approved filing has a strictly later `effective_date`, and increments the superseded filing's `version` by one); and finally it increments the territory's `version` by one, because the territory's rate posture has changed."

    PRD: "A `Regulator` reviews a filing by supplying a `decision` of either `APPROVE` or `DISAPPROVE` together with an optional `note`, which is stored as `review_note`; the reviewer's `X-User-ID` is stored as `reviewed_by_user_id`."

    Design: Difficulty/resource_temporal_overlap/rate_filing_buffered_quiet_window_on_zone_and_package
    """
    incumbent, _inside, clears_buffer = _one_approved_filing_and_two_candidates(client)

    approved = validate_success(
        client.review_rate_filing(
            clears_buffer["id"],
            f.filing_review_payload(review_note="30-day buffer satisfied"),
            regulator_headers(),
        )
    )

    assert_field_equals(approved, "status", FILING_STATUS_APPROVED)
    assert_field_equals(approved, "reviewed_by_user_id", "reg-1")
    assert_ratio(approved["differential_pct"], "0.1250", "differential_pct")
    assert_field_equals(
        read_filing(client, incumbent["id"]), "status", FILING_STATUS_SUPERSEDED
    )
