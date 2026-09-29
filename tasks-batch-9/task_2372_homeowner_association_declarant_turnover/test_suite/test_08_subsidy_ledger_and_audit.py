"""The subsidy ledger's reversal cascade and the closed-interval audit calendar."""

from typing import Any, Dict

import pytest
from test_helpers import (
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    DECLARANT_USER_ID,
    ERR_AUDIT_PERIOD_OVERLAP,
    FINDING_CLEAN,
    FINDING_EXCEPTION_NOTED,
    SUBSIDY_DIRECTION_REVERSAL,
    ApiClient,
    assert_instant,
    audit_engagement_payload,
    do_issue_engagement,
    do_reverse_entry,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    seed_association,
    seed_audit_engagement,
    seed_subsidy_entry,
    seed_turnover_case,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Ivywood: reversing an audited accrual ─────────────────────────────


@pytest.fixture
def ivywood(api: ApiClient) -> Dict[str, Any]:
    """Two in-window accruals and an issued clean audit over both of them."""
    association = seed_association(
        api,
        name="Ivywood",
        total_planned_lots=20,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-04-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=500000,
        reserve_claim_pool_cents=1000000,
        declarant_monthly_subsidy_cents=150000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    first = seed_subsidy_entry(api, association["id"], "ACCRUAL", 900000, "2026-05")
    second = seed_subsidy_entry(api, association["id"], "ACCRUAL", 600000, "2026-06")
    engagement = seed_audit_engagement(
        api, association["id"], "2026-05-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    engagement = do_issue_engagement(api, engagement["id"])
    return {
        "association": association,
        "case": case,
        "first": first,
        "second": second,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestReversalCascade:
    """Four hops: the target, the mirror, the audit finding, the settlement latch."""

    def test_the_reversal_returns_the_target_and_mints_a_discoverable_mirror(
        self, api: ApiClient, ivywood: Dict[str, Any]
    ) -> None:
        """The mirror copies the amount and period and points back at the target.

        "The target's `status` becomes `REVERSED`, and the server creates a new
        entry carrying `direction` `REVERSAL` with the same `amount_cents` and
        `period_month`, `status` `POSTED`, `posted_by_user_id` from the acting
        user, and `reverses_entry_id` pointing at the target — discoverable
        afterwards by filtering the ledger on `reverses_entry_id`."

        Design: Difficulty/transitive_cascade/subsidy_reversal_four_hop_cascade_blocks_settlement
        """
        committee = ivywood["committee_headers"]
        target_id = ivywood["second"]["id"]

        reversed_entry = do_reverse_entry(
            api, target_id, reason="June accrual double-counted in the declarant ledger"
        )
        assert reversed_entry["id"] == target_id, (
            "The response returns the reversed target entry, not the mirror"
        )
        assert reversed_entry["status"] == "REVERSED"

        mirrors, meta = validate_paginated(
            api.list_subsidy_entries(committee, {"reverses_entry_id": target_id})
        )
        assert meta["total_count"] == 1
        mirror = mirrors[0]
        assert mirror["direction"] == SUBSIDY_DIRECTION_REVERSAL
        assert mirror["amount_cents"] == 600000
        assert mirror["period_month"] == "2026-06"
        assert mirror["status"] == "POSTED"
        assert mirror["posted_by_user_id"] == DECLARANT_USER_ID
        assert mirror["reverses_entry_id"] == target_id

        untouched = validate_success(
            api.get_subsidy_entry(ivywood["first"]["id"], committee)
        )
        assert untouched["status"] == "POSTED", "Only the named entry is reversed"

    def test_the_frozen_snapshot_turns_the_dropped_receivable_into_an_exception(
        self, api: ApiClient, ivywood: Dict[str, Any]
    ) -> None:
        """The receivable falls to 900,000 while the snapshot stays at 1,500,000.

        "Because the snapshot never moves, an entry posted outside the audited
        window, or a post-issuance reversal of an in-window entry, shows up as a
        non-zero delta and flips the engagement to `EXCEPTION_NOTED`."

        Design: Difficulty/transitive_cascade/subsidy_reversal_four_hop_cascade_blocks_settlement
        """
        association_id = ivywood["association"]["id"]
        committee = ivywood["committee_headers"]

        assert ivywood["engagement"]["audited_receivable_snapshot_cents"] == 1500000
        assert ivywood["engagement"]["unreconciled_delta_cents"] == 0
        assert ivywood["engagement"]["finding_status"] == FINDING_CLEAN
        assert ivywood["engagement"]["issued_by_user_id"] == AUDITOR_USER_ID

        do_reverse_entry(
            api,
            ivywood["second"]["id"],
            reason="June accrual double-counted in the declarant ledger",
        )

        association = read_association(api, association_id)
        assert association["subsidy_receivable_cents"] == 900000

        rows, _meta = validate_paginated(
            api.list_audit_engagements(association_id, committee)
        )
        engagement = next(
            row for row in rows if row["id"] == ivywood["engagement"]["id"]
        )
        assert engagement["audited_receivable_snapshot_cents"] == 1500000, (
            "That snapshot is frozen once and never recomputed"
        )
        assert engagement["unreconciled_delta_cents"] == -600000
        assert engagement["finding_status"] == FINDING_EXCEPTION_NOTED

    def test_the_exception_latches_the_settlement_block_on_the_case(
        self, api: ApiClient, ivywood: Dict[str, Any]
    ) -> None:
        """The fourth hop reaches an entity the request never named.

        "Whenever any `ISSUED` engagement of the association stands at
        `EXCEPTION_NOTED`, the association's turnover case has
        `settlement_blocked` set to true; once latched, that flag is not cleared
        by any later ledger movement, and it bars settlement."

        Design: Difficulty/transitive_cascade/subsidy_reversal_four_hop_cascade_blocks_settlement
        """
        case_id = ivywood["case"]["id"]
        assert ivywood["case"]["settlement_blocked"] is False

        do_reverse_entry(
            api,
            ivywood["second"]["id"],
            reason="June accrual double-counted in the declarant ledger",
        )

        case = read_turnover_case(api, case_id)
        assert case["settlement_blocked"] is True

        seed_subsidy_entry(
            api, ivywood["association"]["id"], "ACCRUAL", 600000, "2026-06"
        )
        relatched = read_turnover_case(api, case_id)
        assert relatched["settlement_blocked"] is True, (
            "Once latched, the flag is not cleared by any later ledger movement"
        )


# ─── Thornwood: audit periods that merely touch ────────────────────────


@pytest.fixture
def thornwood(api: ApiClient) -> Dict[str, Any]:
    """One engaged first-quarter audit period."""
    association = seed_association(
        api,
        name="Thornwood",
        total_planned_lots=16,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-03-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=300000,
        declarant_monthly_subsidy_cents=25000,
    )
    first_quarter = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    return {
        "association": association,
        "first_quarter": first_quarter,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestAuditPeriodsAreClosedIntervals:
    """Touching at an endpoint is already a collision."""

    def test_a_period_starting_on_the_existing_end_date_collides(
        self, api: ApiClient, thornwood: Dict[str, Any]
    ) -> None:
        """A start of 2026-03-31 shares exactly one instant with the first quarter.

        "Periods of one association may not overlap: the new interval is compared
        as a closed interval, including both endpoints, against every engagement
        of that association whose `status` is `ENGAGED` or `ISSUED`, so two
        periods that merely touch at an endpoint already collide, and the
        rejection is `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_periods_collide_as_closed_intervals_when_endpoints_touch
        """
        association_id = thornwood["association"]["id"]

        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(
                    association_id, "2026-03-31T00:00:00Z", "2026-06-30T00:00:00Z"
                ),
                AUDITOR_HEADERS,
            ),
            ERR_AUDIT_PERIOD_OVERLAP,
        )

        rows, meta = validate_paginated(
            api.list_audit_engagements(association_id, thornwood["committee_headers"])
        )
        assert meta["total_count"] == 1, "The refused engagement created nothing"
        assert_instant(rows[0]["period_end"], "2026-03-31T00:00:00Z", "period_end")

    def test_the_next_day_is_accepted_and_becomes_the_new_obstacle(
        self, api: ApiClient, thornwood: Dict[str, Any]
    ) -> None:
        """The accepted second quarter then collides with a period touching its end.

        "A new engagement starts `ENGAGED`, with `finding_status` `CLEAN`,
        `unreconciled_delta_cents` 0, `audited_receivable_snapshot_cents` 0 and
        `issued_by_user_id` null."

        Design: Difficulty/resource_temporal_overlap/audit_periods_collide_as_closed_intervals_when_endpoints_touch
        """
        association_id = thornwood["association"]["id"]

        second_quarter = validate_success(
            api.create_audit_engagement(
                audit_engagement_payload(
                    association_id, "2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z"
                ),
                AUDITOR_HEADERS,
            ),
            expected_status=201,
        )
        assert second_quarter["status"] == "ENGAGED"
        assert second_quarter["finding_status"] == FINDING_CLEAN
        assert second_quarter["unreconciled_delta_cents"] == 0
        assert second_quarter["audited_receivable_snapshot_cents"] == 0
        assert second_quarter["issued_by_user_id"] is None

        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(
                    association_id, "2026-06-30T00:00:00Z", "2026-09-30T00:00:00Z"
                ),
                AUDITOR_HEADERS,
            ),
            ERR_AUDIT_PERIOD_OVERLAP,
        )

        _rows, meta = validate_paginated(
            api.list_audit_engagements(association_id, thornwood["committee_headers"])
        )
        assert meta["total_count"] == 2
