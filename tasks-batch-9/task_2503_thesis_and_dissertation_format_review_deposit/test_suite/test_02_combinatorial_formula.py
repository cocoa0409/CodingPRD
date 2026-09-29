"""Multi-input formulas whose pinned evaluation order changes the answer.

The severity-weighted defect score rounds each severity subtotal on its own
before summing, and the late fee spends its grace allowance exactly once, in the
step that shifts the deadline.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import create_repository_deposit_payload
from test_helpers.test_users import ANALYST_ONE_USER_ID, TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


def _returned_cycle_on_a_101_page_document() -> tuple:
    """Cycle 1 of a 101-page document, returned with one, two and four defects."""
    world = fx.setup_open_format_cycle(cycle_clock="2026-10-05T09:00:00Z")
    review = fx.decide_format_review(
        world,
        world["format_review"],
        decision="RETURN_REVISIONS",
        critical_defect_count=1,
        major_defect_count=2,
        minor_defect_count=4,
        clock="2026-10-12T09:00:00Z",
        review_note="Margins, pagination and caption style",
    )
    return world, review


def test_defect_score_rounds_each_severity_subtotal_before_summing(
    api: ApiClient,
) -> None:
    """One, two and four defects at density 1.0100 publish 8.17, not 8.18.

    PRD §3.5: "Rounding once at the end instead of per severity is not the sanctioned order and yields a different published score."

    Design: Difficulty/combinatorial_formula/defect_score_rounds_per_severity_before_summing
    """
    world, review = _returned_cycle_on_a_101_page_document()

    assert review["severity_weighted_defect_score"] == pytest.approx(8.17, abs=0.001)
    assert review["severity_weighted_defect_score"] != pytest.approx(8.18, abs=0.001)
    assert review["status"] == "REVISIONS_REQUIRED"
    assert review["cycle_number"] == 1
    assert review["decision"] == "RETURN_REVISIONS"
    assert review["decided_by_user_id"] == ANALYST_ONE_USER_ID
    assert_instant(review["decided_at"], "2026-10-12T09:00:00Z", "decided_at")

    stored = get_success_data(api.get_format_review(review["id"], REGISTRAR))
    assert stored["severity_weighted_defect_score"] == pytest.approx(8.17, abs=0.001)


def test_returned_cycle_one_window_and_turnaround_accompany_the_score(
    api: ApiClient,
) -> None:
    """The same decision fixes a ten-business-day window and a five-day turnaround.

    PRD §3.5: "The base revision window is 10 business days for cycle 1, 7 business days for cycle 2, and 5 business days for cycle 3 or any later cycle; a long document — one whose `page_count` is at least 300 — earns 2 additional business days on top of whichever base applies."

    Design: Difficulty/combinatorial_formula/defect_score_rounds_per_severity_before_summing
    """
    world, review = _returned_cycle_on_a_101_page_document()

    assert review["turnaround_bdays"] == 5
    assert_instant(review["revision_due_at"], "2026-10-26T09:00:00Z", "revision_due_at")

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "FORMAT_REVISIONS_REQUIRED"
    assert thesis["analyst_turnaround_bdays_total"] == 5
    assert thesis["format_cycle_count"] == 1


def _document_with_fifteen_business_days_of_turnaround() -> dict:
    """Two decided cycles totalling fifteen business days of analyst turnaround."""
    world = fx.setup_open_format_cycle(cycle_clock="2026-10-05T09:00:00Z")
    world["cycle_one"] = fx.decide_format_review(
        world,
        world["format_review"],
        decision="RETURN_REVISIONS",
        minor_defect_count=1,
        clock="2026-10-26T09:00:00Z",
        review_note="One caption to renumber",
    )
    world["cycle_two"] = fx.open_format_cycle(world, clock="2026-10-27T09:00:00Z")
    world["cycle_two"] = fx.decide_format_review(
        world, world["cycle_two"], decision="ACCEPT"
    )
    return world


def test_grace_shifts_the_deadline_and_two_chargeable_days_are_charged(
    api: ApiClient,
) -> None:
    """Fifteen turnaround days buy five grace days, leaving two days chargeable.

    PRD §3.8: "Second, a grace allowance is selected from it: 5 business days when the total is at least 15 business days, otherwise 3 business days when the total is at least 10 business days, otherwise none."

    Design: Difficulty/combinatorial_formula/late_fee_grace_applied_once_not_twice
    """
    world = _document_with_fifteen_business_days_of_turnaround()

    assert world["cycle_one"]["turnaround_bdays"] == 15
    assert_instant(
        world["cycle_one"]["revision_due_at"], "2026-11-09T09:00:00Z", "revision_due_at"
    )
    assert world["cycle_two"]["turnaround_bdays"] == 0

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["analyst_turnaround_bdays_total"] == 15

    fx.set_clock("2026-12-15T10:00:00Z")
    readiness = get_success_data(
        api.get_deposit_readiness(world["thesis"]["id"], REGISTRAR)
    )
    assert readiness["projected_late_fee_cents"] == 5000

    deposit = fx.deposit_thesis(
        world,
        abstract_word_count=200,
        subject_keywords=["compilers", "types", "proofs"],
        late_fee_paid_cents=5000,
    )
    assert deposit["late_fee_cents"] == 5000


def test_tendering_the_doubly_graced_amount_is_refused(api: ApiClient) -> None:
    """Subtracting the grace a second time would tender nothing, which is refused.

    PRD §3.8: "Fifth, the chargeable days are exactly those days late — the grace was already consumed in shifting the deadline and is **not** subtracted a second time."

    Design: Difficulty/combinatorial_formula/late_fee_grace_applied_once_not_twice
    """
    world = _document_with_fifteen_business_days_of_turnaround()
    fx.set_clock("2026-12-15T10:00:00Z")

    payload = create_repository_deposit_payload(
        world["thesis"]["id"],
        abstract_word_count=200,
        subject_keywords=["compilers", "types", "proofs"],
        late_fee_paid_cents=0,
    )
    payload["advisor_name"] = "Cara Cho"
    payload["department_code"] = "CS"
    validate_error(
        api.create_repository_deposit(payload, ANALYST_TWO),
        "ERR_LATE_FEE_MISMATCH",
        402,
    )
    assert get_success_data(
        api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
    ) == []

    deposit = fx.deposit_thesis(
        world,
        abstract_word_count=200,
        subject_keywords=["compilers", "types", "proofs"],
        late_fee_paid_cents=5000,
    )
    assert deposit["late_fee_cents"] == 5000
    assert deposit["access_level"] == "OPEN_ACCESS"
    assert deposit["embargo_release_date"] is None
    assert deposit["metadata_completeness_score"] == pytest.approx(1.0, abs=0.0001)

    cycle_one = get_success_data(
        api.get_format_review(world["cycle_one"]["id"], REGISTRAR)
    )
    assert cycle_one["status"] == "SUPERSEDED"
    cycle_two = get_success_data(
        api.get_format_review(world["cycle_two"]["id"], REGISTRAR)
    )
    assert cycle_two["status"] == "ACCEPTED"
    assert cycle_two["severity_weighted_defect_score"] == pytest.approx(0.0, abs=0.001)

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEPOSITED"
    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "CLEARED"
