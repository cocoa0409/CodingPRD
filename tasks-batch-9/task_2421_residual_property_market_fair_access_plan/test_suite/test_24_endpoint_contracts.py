"""Endpoint contracts: a partial update, a batch capability and a reverse lookup.

These tests cover the shapes of the surface rather than the arithmetic behind it:
what a partial membership update writes and leaves alone, what the nightly batch
reports and skips, and how a reverse lookup scopes its rows.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_date_equals,
    assert_field_equals,
    assert_pct,
)
from test_helpers.constants import (
    CLOCK_BASE,
    COVERAGE_STATUS_BOUND,
    COVERAGE_STATUS_IN_FORCE,
    MEMBER_STATUS_RUNOFF,
)
from test_helpers.fixtures import (
    add_three_declinations,
    build_bound_policy,
    build_foundations,
    create_draft_application,
    create_member_insurer,
    pin_clock,
    read_application,
    read_member,
    read_policy,
    read_zone,
    run_sweep,
)
from test_helpers.test_users import admin_headers


def test_member_insurer_patch_restates_basis_weights_and_moves_into_runoff(client):
    """One partial update writes both supplied fields, keeps the omitted one, bumps once.

    PRD: "An administrator moves a carrier along that path, or restates its assessment
    basis weights, through the same membership update operation, which accepts an
    optional new `status`, an optional new `market_share_pct` and an optional new
    `written_premium_share_pct`."

    PRD: "Moving `ACTIVE → RUNOFF` requires the carrier to currently be `ACTIVE`; a
    carrier in run-off **remains assessable** and stays inside the eligible member
    set used by allocation runs, but it may no longer create take-out offers."

    PRD: "Most records additionally carry two mutation-tracking fields: `updated_at`,
    an ISO 8601 UTC timestamp with three fractional digits refreshed on every
    change to the record, and `version`, an integer that begins at 1 when the
    record is created and increases by exactly one on every mutation of that
    record."

    Design: Corner/endpoints/member_insurer_patch_restates_basis_weights_and_moves_into_runoff
    """
    pin_clock(client, CLOCK_BASE)
    member = create_member_insurer(
        client, market_share_pct=30.00, written_premium_share_pct=10.00
    )
    assert_field_equals(member, "version", 1)

    response = client.update_member_insurer(
        member["id"],
        f.member_status_payload(status=MEMBER_STATUS_RUNOFF, market_share_pct=25.00),
        admin_headers(),
    )

    updated = validate_success(response, 200)
    assert_field_equals(updated, "status", MEMBER_STATUS_RUNOFF)
    assert_pct(updated["market_share_pct"], "25.00", "market_share_pct")
    assert_pct(
        updated["written_premium_share_pct"], "10.00", "written_premium_share_pct"
    )
    assert_field_equals(updated, "version", 2)
    stored = read_member(client, member["id"])
    assert_field_equals(stored, "status", MEMBER_STATUS_RUNOFF)
    assert_pct(stored["market_share_pct"], "25.00", "stored market_share_pct")
    assert_pct(
        stored["written_premium_share_pct"], "10.00", "stored written_premium_share_pct"
    )
    assert_field_equals(stored, "version", 2)


def test_expiration_sweep_activates_only_policies_whose_effective_date_has_arrived(
    roomy_foundations,
):
    """The batch skips a future-dated policy and activates it once its date arrives.

    PRD: "First, any policy whose `coverage_status` is `BOUND` and whose
    `effective_date` is on or before the clock date moves `BOUND → IN_FORCE`; the
    territory's `aggregate_insured_value_cents` does **not** change on this move,
    because a `BOUND` policy was already counted in the exposure, and only the
    policy's `version` increments."

    PRD: "**The nightly sweep** is an administrator-only batch capability that advances
    every time-driven transition in the plan at once and reports four counters:
    `activated_policy_count`, `expired_policy_count`, `expired_offer_count` and
    `withdrawn_application_count`."

    Design: Corner/endpoints/expiration_sweep_activates_only_policies_whose_effective_date_has_arrived
    """
    client = roomy_foundations.client
    chain = build_bound_policy(
        client, roomy_foundations, effective_date="2026-09-15"
    )
    early = run_sweep(client)
    assert_field_equals(early, "activated_policy_count", 0)
    assert_field_equals(early, "expired_policy_count", 0)
    assert_field_equals(early, "expired_offer_count", 0)
    assert_field_equals(early, "withdrawn_application_count", 0)
    assert_field_equals(
        read_policy(client, chain.policy_id), "coverage_status", COVERAGE_STATUS_BOUND
    )
    pin_clock(client, "2026-09-15T00:00:00Z")

    response = client.run_expiration_sweep({}, admin_headers())

    counters = validate_success(response, 200)
    assert_field_equals(counters, "activated_policy_count", 1)
    assert_field_equals(counters, "expired_policy_count", 0)
    assert_field_equals(counters, "expired_offer_count", 0)
    assert_field_equals(counters, "withdrawn_application_count", 0)
    policy = read_policy(client, chain.policy_id)
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    assert_date_equals(policy["expiration_date"], "2027-09-15", "expiration_date")
    zone = read_zone(client, roomy_foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        54_000_000,
        "aggregate_insured_value_cents",
    )


def test_member_insurer_declinations_reverse_lookup_returns_only_that_carriers_rows(
    client,
):
    """The carrier reverse lookup is member-scoped, not application-scoped.

    PRD: "Two reverse lookups hang off a carrier: the declinations it has issued, and
    the assessment allocations charged to it (the latter filterable by allocation
    `status`)."

    PRD: "Each declination names the `member_insurer_id` of the voluntary carrier that
    turned the risk down, the `declined_on` date on which it did so, a
    `reason_code` drawn from `CAT_EXPOSURE`, `CONDITION`, `LOSS_HISTORY`,
    `NON_RENEWAL` and `APPETITE`, and an `evidence_reference` locating the written
    declination, which must be a non-empty string."

    PRD: "A fresh application sits in `status` `DRAFT` with `declination_count` at 0;
    `quoted_annual_premium_cents` and `voluntary_equivalent_premium_cents` at 0;
    `voluntary_market_comparison_pct` at 0.0; and `quote_rate_filing_id`,
    `submitted_at`, `eligibility_hold_reason`, `decline_reason`,
    `eligibility_reviewer_user_id`, `approved_to_bind_at` and `bind_deadline_at`
    all null."

    Design: Corner/endpoints/member_insurer_declinations_reverse_lookup_returns_only_that_carriers_rows
    """
    foundations = build_foundations(
        client, zone_overrides={"exposure_cap_cents": 900_000_000}
    )
    chain = create_draft_application(client, foundations)
    declinations = add_three_declinations(chain, declined_on="2026-07-03")

    rows, meta = validate_paginated(
        client.list_member_insurer_declinations(
            foundations.member_ids[0], admin_headers(), {"limit": 10}
        )
    )

    assert_field_equals(meta, "total_count", 1)
    assert_field_equals(meta, "has_more", False)
    assert_count(rows, 1, "declinations for the first carrier")
    row = rows[0]
    assert_field_equals(row, "id", declinations[0]["id"])
    assert_field_equals(row, "member_insurer_id", foundations.member_ids[0])
    assert_field_equals(row, "application_id", chain.application_id)
    assert_field_equals(row, "evidence_reference", "DEC-1")
    assert_date_equals(row["declined_on"], "2026-07-03", "declined_on")
    assert_field_equals(
        read_application(client, chain.application_id), "declination_count", 0
    )
