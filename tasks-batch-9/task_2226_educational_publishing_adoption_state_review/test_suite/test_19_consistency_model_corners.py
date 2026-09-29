"""Read-your-write consistency of the derived fields on a submission.

Every counter, coverage percentage and compliance number the adoption record
carries is maintained by the write that affects it, so the response body of a
write is already the final state of the record. The filing of a submission is
the densest example: one call sets the content pin, both coverage variants, the
compliance score, the adoption block and the filing instant at once.
"""

import pytest

from test_helpers import (
    REVIEW_STATUS_FILED,
    assert_decimal_equals,
    is_iso8601_timestamp,
    validate_success,
)
from test_helpers.fixtures import seed_draft_submission, seed_open_cycle

#: The derived fields the filing must have settled before it answers.
DERIVED_FILING_FIELDS = (
    "review_status",
    "pinned_content_revision",
    "content_pin_stale",
    "self_reported_coverage_pct",
    "verified_coverage_pct",
    "compliance_score",
    "adoption_blocked",
    "filed_at",
)


def test_filing_response_already_carries_every_derived_field(api, publisher_editor_headers):
    """PRD 2.7: "Nothing in the system is ever recomputed lazily at read time. Counters such as `submission_count`, `scheduled_submission_count`, `adopted_count`, `reserved_minutes`, `compliance_score`, `self_reported_coverage_pct` and `verified_coverage_pct` are maintained eagerly by the writes that affect them, and a read simply reports the stored value."

    PRD 3.5: "A successful filing moves `review_status` from `DRAFT` to `FILED` and performs the **content pin**: `pinned_content_revision` is set to the edition's current `content_revision` and `content_pin_stale` is set to false, capturing exactly which revision of the edition the state is being asked to review. `filed_at` records the logical clock instant of the filing. The cycle's `submission_count` increases by 1, and `compliance_score` and `adoption_blocked` are recomputed."

    PRD 3.4: "The **self-reported** variant accepts entries whose `reviewer_verdict` is `PENDING` or `ACCEPTED` — the publisher's own claim, which counts evidence the committee has not yet looked at — and is stored in `self_reported_coverage_pct`; it is the gate at filing time. The **committee-verified** variant accepts only entries whose `reviewer_verdict` is `ACCEPTED`, discarding both `PENDING` and `INSUFFICIENT` evidence, and is stored in `verified_coverage_pct`; it is the gate at adoption time."

    The single grade-four standard of weight four is cited once at MASTERY and
    has drawn no committee verdict, so the filing answers with a self-reported
    coverage of 100.00 against a verified coverage of 0.00, an undocked
    compliance score and the pin on revision 1. A follow-up read repeats every
    one of those values unchanged.

    Design: Corner/consistency_model/filing_response_already_carries_every_derived_field
    """
    world = seed_open_cycle(
        api,
        "TX",
        subject="MATH",
        grade=4,
        standard_code="TX.M.4.1",
        standard_weight=4,
        title_overrides={
            "content_tags": ["FRACTION_MODELS"],
            "page_count": 290,
            "list_price_cents": 8800,
        },
    )
    submission_id = seed_draft_submission(api, world)

    filed = validate_success(api.file_submission(submission_id, publisher_editor_headers))

    assert filed["review_status"] == REVIEW_STATUS_FILED
    assert filed["pinned_content_revision"] == 1
    assert filed["content_pin_stale"] is False
    assert_decimal_equals(
        filed["self_reported_coverage_pct"], "100.00", "self_reported_coverage_pct"
    )
    assert_decimal_equals(filed["verified_coverage_pct"], "0.00", "verified_coverage_pct")
    assert filed["compliance_score"] == 100
    assert filed["adoption_blocked"] is False
    assert is_iso8601_timestamp(filed["filed_at"])
    assert filed["filed_at"].startswith("2026-09-15T00:00:00"), (
        f"filed_at must record the logical clock instant, got {filed['filed_at']!r}"
    )

    read_back = validate_success(api.get_submission(submission_id, publisher_editor_headers))
    for field in DERIVED_FILING_FIELDS:
        assert read_back[field] == filed[field], (
            f"{field} differs between the filing response and a follow-up read: "
            f"{filed[field]!r} then {read_back[field]!r}"
        )

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 1
