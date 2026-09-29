"""Derived numbers: defect scores, business-day windows, metadata and fees.

Each test drives the pipeline to the exact instant the arithmetic runs and reads
the published figure back, so a wrong rounding point or a wrong input set shows up
as a wrong number rather than as a wrong status.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_format_review,
    assert_handle_format,
    assert_instant,
    assert_integrity_screening,
    assert_repository_deposit,
)
from test_helpers.factories import (
    create_committee_payload,
    create_integrity_screening_payload,
    create_repository_deposit_payload,
    format_review_decision_payload,
)
from test_helpers.test_users import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    TEST_USERS,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


def test_a_clean_acceptance_scores_zero_and_freezes_a_five_day_turnaround(
    api: ApiClient,
) -> None:
    """Zero defects publish 0.00, leave the revision deadline null and count 5 days.

    PRD §3.5: "When all four pass, the cycle moves `PENDING_REVIEW → ACCEPTED` with `decision` recorded as `ACCEPT`, `decided_at` and `decided_by_user_id` written, the score and `turnaround_bdays` written, `revision_due_at` left null, `analyst_turnaround_bdays_total` recomputed, the document advanced `UNDER_FORMAT_REVIEW → FORMAT_ACCEPTED` with `accepted_at` set to the current logical instant, and clearance recomputed with the format-acceptance item satisfied under both variants."

    Design: Corner/calculations/format_accept_with_zero_defects_scores_zero_and_records_turnaround
    """
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        thesis_overrides={"title": "Clean Format"},
    )
    fx.set_clock("2026-10-12T09:00:00Z")

    review = get_success_data(
        api.decide_format_review(
            world["format_review"]["id"],
            format_review_decision_payload(
                "ACCEPT", 0, 0, 0, review_note="Template compliant"
            ),
            ANALYST_ONE,
        ),
        200,
    )
    assert_format_review(review)

    assert review["severity_weighted_defect_score"] == pytest.approx(0.00, abs=0.001)
    assert review["status"] == "ACCEPTED"
    assert review["cycle_number"] == 1
    assert_instant(review["opened_at"], "2026-10-05T09:00:00Z", "opened_at")
    assert_instant(review["decided_at"], "2026-10-12T09:00:00Z", "decided_at")
    assert review["decided_by_user_id"] == ANALYST_ONE_USER_ID
    assert review["turnaround_bdays"] == 5
    assert review["revision_due_at"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["analyst_turnaround_bdays_total"] == 5
    assert thesis["format_cycle_count"] == 1
    assert thesis["workflow_state"] == "FORMAT_ACCEPTED"
    assert_instant(thesis["accepted_at"], "2026-10-12T09:00:00Z", "accepted_at")

    screenings = get_success_data(
        api.list_thesis_integrity_screenings(world["thesis"]["id"], REGISTRAR)
    )
    assert screenings[0]["status"] == "CLEARED"


def test_the_long_document_window_is_clamped_to_the_term_deposit_deadline(
    api: ApiClient,
) -> None:
    """Twelve business days would overrun the term, so the deadline wins with its 17:00.

    PRD §3.5: "The decision instant is advanced by the sum of the base window and the long-document bonus, and `revision_due_at` becomes the **earlier** of that result and the term's `format_review_deposit_deadline`."

    Design: Corner/calculations/revision_due_at_clamped_to_term_deposit_deadline
    """
    world = fx.setup_open_format_cycle(
        scheduled_start="2026-11-10T14:00:00Z",
        scheduled_end="2026-11-10T16:00:00Z",
        outcome_clock="2026-11-10T16:30:00Z",
        cycle_clock="2026-11-30T09:00:00Z",
        with_screening=False,
        thesis_overrides={"title": "Long Document", "page_count": 300},
    )
    fx.set_clock("2026-12-01T09:00:00Z")

    review = get_success_data(
        api.decide_format_review(
            world["format_review"]["id"],
            format_review_decision_payload(
                "RETURN_REVISIONS",
                1,
                1,
                1,
                review_note="Margins, captions and pagination",
            ),
            ANALYST_ONE,
        ),
        200,
    )

    assert review["severity_weighted_defect_score"] == pytest.approx(16.20, abs=0.001)
    assert review["status"] == "REVISIONS_REQUIRED"
    assert review["turnaround_bdays"] == 1
    assert_instant(
        review["revision_due_at"], "2026-12-04T17:00:00Z", "revision_due_at"
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "FORMAT_REVISIONS_REQUIRED"
    assert thesis["analyst_turnaround_bdays_total"] == 1
    assert thesis["format_cycle_count"] == 1


def test_a_lead_of_exactly_ten_business_days_across_two_holidays_is_accepted(
    api: ApiClient,
) -> None:
    """Thanksgiving drops out of the count, leaving the lead exactly at the minimum.

    PRD §3.4: "The gate is the announcement lead, measured as the number of business days between the current logical instant and the event's `scheduled_start`, and the announcement is refused when that count is fewer than the term's `announcement_lead_business_days`; a lead of exactly the required number of business days passes."

    Design: Corner/calculations/announcement_lead_of_exactly_ten_business_days_across_holidays_passes
    """
    world = fx.setup_scheduled_defense(
        term_overrides={
            "defense_deadline": "2026-12-11T23:59:59Z",
            "format_review_deposit_deadline": "2026-12-24T17:00:00Z",
            "degree_conferral_date": "2027-01-08T00:00:00Z",
        },
        scheduled_start="2026-12-02T14:00:00Z",
        scheduled_end="2026-12-02T16:00:00Z",
        thesis_overrides={"title": "Holiday Lead"},
    )
    fx.set_clock("2026-11-16T09:00:00Z")

    event = get_success_data(
        api.announce_defense_event(world["defense_event"]["id"], ANALYST_ONE), 200
    )
    assert event["status"] == "ANNOUNCED"
    assert event["announcement_lead_bdays"] == 10
    assert_instant(event["announced_at"], "2026-11-16T09:00:00Z", "announced_at")

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_ANNOUNCED"


def test_an_over_generous_exclusion_floors_the_adjusted_similarity_at_zero(
    api: ApiClient,
) -> None:
    """Five per cent less seven and a half stores 0.00 rather than a negative figure.

    PRD §3.6: "The **adjusted similarity** is the raw `similarity_pct` less `excluded_quoted_pct`, rounded half-up to two decimal places, and floored at 0.00 so that an over-generous exclusion can never produce a negative figure."

    Design: Corner/calculations/adjusted_similarity_clamped_to_zero_when_exclusions_exceed_similarity
    """
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        with_screening=False,
        thesis_overrides={"title": "Heavy Quoting"},
    )

    screening = get_success_data(
        api.create_integrity_screening(
            create_integrity_screening_payload(
                world["thesis"]["id"], 5.0, excluded_quoted_pct=7.5
            ),
            ANALYST_ONE,
        ),
        201,
    )
    assert_integrity_screening(screening)

    assert screening["adjusted_similarity_pct"] == pytest.approx(0.00, abs=0.001)
    assert screening["status"] == "CLEARED"
    assert_instant(screening["screened_at"], "2026-10-05T09:00:00Z", "screened_at")
    assert screening["referred_at"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "SCREEN_CLEARED"


def test_chair_load_ignores_draft_committees_and_rises_with_each_submission(
    api: ApiClient,
) -> None:
    """The same chair carries 0, then 1, then 2 as each composition is submitted.

    PRD §3.3: "Committees that are `DRAFT`, `REJECTED` or `DISSOLVED` contribute nothing, which is why a chair seated on a `DRAFT` committee carries no load at all until the composition is submitted."

    Design: Corner/calculations/faculty_active_chair_load_counts_only_submitted_and_approved_committees
    """
    world = fx.setup_committee_with_seats(thesis_overrides={"title": "Load A"})

    second_student = fx.add_student(
        world,
        full_name="Ben Ruiz",
        email="ben@u.edu",
        degree_level="MASTERS",
        program_code="CS",
    )
    second_headers = make_student_headers(second_student["id"])
    second_thesis = fx.open_thesis(second_student, world["term"], title="Load B")
    second_committee = get_success_data(
        api.create_committee(create_committee_payload(second_thesis["id"]), second_headers),
        201,
    )
    for faculty, role in (
        (world["chair"], "CHAIR"),
        (world["member_1"], "MEMBER"),
        (world["member_2"], "MEMBER"),
    ):
        fx.seat_member(world, faculty, role, second_committee, second_headers)

    def chair_load() -> int:
        return get_success_data(
            api.get_faculty_member(world["chair"]["id"], REGISTRAR)
        )["active_chair_load"]

    assert chair_load() == 0

    first = get_success_data(
        api.submit_committee(world["committee"]["id"], world["student_headers"]), 200
    )
    assert first["status"] == "SUBMITTED"
    assert chair_load() == 1

    second = get_success_data(
        api.submit_committee(second_committee["id"], second_headers), 200
    )
    assert second["status"] == "SUBMITTED"
    assert chair_load() == 2

    for member in (world["member_1"], world["member_2"]):
        row = get_success_data(api.get_faculty_member(member["id"], REGISTRAR))
        assert row["active_chair_load"] == 0


def test_a_metadata_score_of_exactly_the_floor_wins_the_first_handle(
    api: ApiClient,
) -> None:
    """Abstract, keywords and advisor alone reach 0.8500, and the floor is inclusive.

    PRD §3.8: "The contributions are summed, divided by the total weight of 1.00, and rounded half-up to four decimal places to give `metadata_completeness_score`. The repository requires at least 0.8500, so exactly 0.8500 passes and anything lower is refused with `ERR_METADATA_INCOMPLETE` (HTTP 422)."

    Design: Corner/calculations/metadata_completeness_score_exactly_at_minimum_passes
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        thesis_overrides={"title": "Boundary Metadata"},
    )
    fx.set_clock("2026-11-02T10:00:00Z")

    deposit = get_success_data(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                world["thesis"]["id"],
                abstract_word_count=150,
                subject_keywords=["formatting", "graduate education", "metadata"],
                late_fee_paid_cents=0,
                advisor_name="Cara Cho",
            ),
            ANALYST_TWO,
        ),
        201,
    )
    assert_repository_deposit(deposit)

    assert deposit["metadata_completeness_score"] == pytest.approx(0.8500, abs=0.0001)
    assert deposit["status"] == "DEPOSITED"
    assert_handle_format(deposit["handle"], "2026FA", 1)
    assert deposit["access_level"] == "OPEN_ACCESS"
    assert deposit["embargo_release_date"] is None
    assert_instant(deposit["deposited_at"], "2026-11-02T10:00:00Z", "deposited_at")
    assert deposit["depositor_user_id"] == ANALYST_TWO_USER_ID
    assert deposit["late_fee_cents"] == 0
    assert deposit["department_code"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEPOSITED"


def test_a_ten_day_turnaround_buys_three_grace_days_before_the_fee_starts(
    api: ApiClient,
) -> None:
    """The shifted deadline leaves two chargeable days, so the fee is 5000 cents.

    PRD §3.8: "Second, a grace allowance is selected from it: 5 business days when the total is at least 15 business days, otherwise 3 business days when the total is at least 10 business days, otherwise none."

    Design: Corner/calculations/late_fee_uses_mid_tier_grace_of_three_business_days
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-19T09:00:00Z",
        thesis_overrides={"title": "Mid Tier Grace"},
    )

    review = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert review["turnaround_bdays"] == 10

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["analyst_turnaround_bdays_total"] == 10

    fx.set_clock("2026-12-11T10:00:00Z")
    deposit = get_success_data(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                world["thesis"]["id"],
                abstract_word_count=220,
                subject_keywords=["deadlines", "late fees", "deposit", "grace"],
                late_fee_paid_cents=5000,
                advisor_name="Cara Cho",
                department_code="CS",
            ),
            ANALYST_TWO,
        ),
        201,
    )

    assert deposit["late_fee_cents"] == 5000
    assert deposit["metadata_completeness_score"] == pytest.approx(1.0000, abs=0.0001)
    assert_instant(deposit["deposited_at"], "2026-12-11T10:00:00Z", "deposited_at")
    assert deposit["status"] == "DEPOSITED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEPOSITED"


def test_a_deposit_fifty_eight_business_days_late_pays_only_the_capped_fee(
    api: ApiClient,
) -> None:
    """The raw 145000 cents is truncated to the 50000-cent ceiling.

    PRD §3.8: "Sixth, the fee is the chargeable days multiplied by 2,500 cents per day, capped at 50,000 cents, which is reached at twenty chargeable days."

    Design: Corner/calculations/late_fee_capped_at_fifty_thousand_cents
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        thesis_overrides={"title": "Capped Fee"},
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["analyst_turnaround_bdays_total"] == 5

    fx.set_clock("2027-03-01T10:00:00Z")
    deposit = get_success_data(
        api.create_repository_deposit(
            create_repository_deposit_payload(
                world["thesis"]["id"],
                abstract_word_count=300,
                subject_keywords=["late", "cap", "fee"],
                late_fee_paid_cents=50000,
                advisor_name="Cara Cho",
                department_code="CS",
            ),
            ANALYST_TWO,
        ),
        201,
    )

    assert deposit["late_fee_cents"] == 50000
    assert_instant(deposit["deposited_at"], "2027-03-01T10:00:00Z", "deposited_at")
    assert deposit["status"] == "DEPOSITED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEPOSITED"
