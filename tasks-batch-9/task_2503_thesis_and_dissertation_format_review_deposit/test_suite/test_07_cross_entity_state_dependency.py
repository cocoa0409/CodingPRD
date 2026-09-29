"""Operations gated by state that lives on a sibling entity, not on the target.

A format acceptance is refused because an integrity screening is under referral,
and a deposit is refused because an embargo request is still undecided; in both
cases resolving the sibling row is what unblocks the original act.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import create_repository_deposit_payload, format_review_decision_payload
from test_helpers.test_users import (
    DEAN_TWO_USER_ID,
    INTEGRITY_OFFICER_ONE_USER_ID,
    INTEGRITY_OFFICER_TWO_USER_ID,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


def _pending_cycle_under_integrity_referral() -> dict:
    """Cycle 1 awaits a decision while a flagged screening sits under referral."""
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        with_screening=False,
        thesis_overrides={"title": "Referred Before Acceptance"},
    )
    world["screening"] = fx.record_screening(
        world, similarity_pct=22.5, excluded_quoted_pct=4.5
    )
    world["screening"] = fx.act_on_screening(
        world,
        world["screening"],
        "REFER",
        resolution_note="Overlap concentrated in the literature review",
        officer_user_id=INTEGRITY_OFFICER_ONE_USER_ID,
    )
    fx.set_clock("2026-10-12T09:00:00Z")
    return world


def test_referred_screening_blocks_the_format_acceptance(api: ApiClient) -> None:
    """A document under integrity review cannot have its format accepted.

    PRD §3.5: "The document must not be under an integrity cloud: an `integrity_state` of `SCREEN_FLAGGED`, `UNDER_INTEGRITY_REVIEW` or `INTEGRITY_UPHELD` is refused with `ERR_INTEGRITY_HOLD_ACTIVE` (HTTP 409), which leaves `SCREEN_CLEARED` and `INTEGRITY_CLEARED` as the only admissible integrity states."

    Design: Difficulty/cross_entity_state_dependency/format_accept_blocked_by_referred_integrity_screening
    """
    world = _pending_cycle_under_integrity_referral()

    validate_error(
        api.decide_format_review(
            world["format_review"]["id"],
            format_review_decision_payload("ACCEPT", 0, 0, 0),
            ANALYST_ONE,
        ),
        "ERR_INTEGRITY_HOLD_ACTIVE",
        409,
    )

    cycle = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert cycle["status"] == "PENDING_REVIEW"
    assert cycle["decided_at"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "UNDER_FORMAT_REVIEW"
    assert thesis["integrity_state"] == "UNDER_INTEGRITY_REVIEW"


def test_dismissing_the_referral_admits_the_same_acceptance(api: ApiClient) -> None:
    """Dismissal restores an admissible integrity state and the accept then passes.

    PRD §3.6: "An `action` of `DISMISS` is legal only while the screening is `REFERRED`; it moves the screening `REFERRED → DISMISSED`, writes `resolved_by_user_id`, drives `integrity_state` to `INTEGRITY_CLEARED`, and recomputes clearance with the integrity item satisfied again."

    Design: Difficulty/cross_entity_state_dependency/format_accept_blocked_by_referred_integrity_screening
    """
    world = _pending_cycle_under_integrity_referral()
    validate_error(
        api.decide_format_review(
            world["format_review"]["id"],
            format_review_decision_payload("ACCEPT", 0, 0, 0),
            ANALYST_ONE,
        ),
        "ERR_INTEGRITY_HOLD_ACTIVE",
        409,
    )

    dismissed = fx.act_on_screening(
        world,
        world["screening"],
        "DISMISS",
        resolution_note="Panel found the overlap correctly quoted and cited",
        officer_user_id=INTEGRITY_OFFICER_TWO_USER_ID,
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["resolved_by_user_id"] == INTEGRITY_OFFICER_TWO_USER_ID

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "INTEGRITY_CLEARED"

    cycle = fx.decide_format_review(world, world["format_review"], decision="ACCEPT")
    assert cycle["status"] == "ACCEPTED"
    assert cycle["severity_weighted_defect_score"] == pytest.approx(0.0, abs=0.001)
    assert cycle["turnaround_bdays"] == 5

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "FORMAT_ACCEPTED"
    assert_instant(thesis["accepted_at"], "2026-10-12T09:00:00Z", "accepted_at")


def _accepted_document_with_an_undecided_embargo() -> dict:
    """An accepted document whose embargo request is waiting for more information."""
    world = fx.setup_passed_defense(
        thesis_overrides={"title": "Sensor Design Embargo"}
    )
    world["embargo"] = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Provisional patent filed on the sensor design",
    )
    world["embargo"] = fx.decide_embargo(
        world,
        world["embargo"],
        decision="REQUEST_INFO",
        decision_note="Attach the filing receipt",
        dean_user_id=DEAN_TWO_USER_ID,
    )
    world["format_review"] = fx.open_format_cycle(world, clock="2026-10-05T09:00:00Z")
    fx.record_screening(world, similarity_pct=25.0, excluded_quoted_pct=7.5)
    world["format_review"] = fx.decide_format_review(
        world,
        world["format_review"],
        decision="ACCEPT",
        critical_defect_count=1,
        major_defect_count=1,
        minor_defect_count=1,
        clock="2026-10-12T09:00:00Z",
    )
    fx.set_clock("2026-12-04T10:00:00Z")
    return world


def _deposit_payload(thesis_id: str) -> dict:
    """The deposit the analyst tenders once the access posture is settled."""
    payload = create_repository_deposit_payload(
        thesis_id,
        abstract_word_count=200,
        subject_keywords=["sensors", "design", "patents"],
        late_fee_paid_cents=0,
    )
    payload["advisor_name"] = "Cara Cho"
    payload["department_code"] = "ECE"
    return payload


def test_undecided_embargo_blocks_the_deposit(api: ApiClient) -> None:
    """A request pushed back for more information is still undecided.

    PRD §3.8: "An embargo request for the document still sitting at `REQUESTED` or `MORE_INFO_REQUIRED` is `ERR_EMBARGO_UNDECIDED` (HTTP 409) — the repository will not publish a document whose access posture is unsettled."

    Design: Difficulty/cross_entity_state_dependency/deposit_blocked_by_undecided_embargo_request
    """
    world = _accepted_document_with_an_undecided_embargo()

    assert world["embargo"]["status"] == "MORE_INFO_REQUIRED"
    assert world["embargo"]["info_request_count"] == 1
    assert world["embargo"]["decided_at"] is None

    validate_error(
        api.create_repository_deposit(
            _deposit_payload(world["thesis"]["id"]), ANALYST_TWO
        ),
        "ERR_EMBARGO_UNDECIDED",
        409,
    )
    assert (
        get_success_data(
            api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
        )
        == []
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "FORMAT_ACCEPTED"


def test_denied_embargo_no_longer_blocks_the_deposit(api: ApiClient) -> None:
    """Supplementing and then denying the request opens the way to open access.

    PRD §3.7: "`DENY` moves the request to the terminal `DENIED` and sets `approved_months` to 0, writes `decided_at` and `decided_by_user_id`, and recomputes clearance; a denied request no longer blocks the deposit."

    Design: Difficulty/cross_entity_state_dependency/deposit_blocked_by_undecided_embargo_request
    """
    world = _accepted_document_with_an_undecided_embargo()
    validate_error(
        api.create_repository_deposit(
            _deposit_payload(world["thesis"]["id"]), ANALYST_TWO
        ),
        "ERR_EMBARGO_UNDECIDED",
        409,
    )

    resupplied = fx.supplement_embargo(
        world,
        world["embargo"],
        "Filing receipt 63/123456 attached; examiner has not yet published",
    )
    assert resupplied["status"] == "REQUESTED"

    denied = fx.decide_embargo(
        world,
        world["embargo"],
        decision="DENY",
        decision_note="Publication already discloses the design",
        dean_user_id=DEAN_TWO_USER_ID,
    )
    assert denied["status"] == "DENIED"
    assert denied["approved_months"] == 0
    assert denied["release_date"] is None
    assert denied["release_anchor"] is None
    assert denied["info_request_count"] == 1

    deposit = get_success_data(
        api.create_repository_deposit(
            _deposit_payload(world["thesis"]["id"]), ANALYST_TWO
        ),
        201,
    )
    assert deposit["status"] == "DEPOSITED"
    assert deposit["access_level"] == "OPEN_ACCESS"
    assert deposit["embargo_release_date"] is None
    assert deposit["late_fee_cents"] == 0
    assert_instant(deposit["deposited_at"], "2026-12-04T10:00:00Z", "deposited_at")

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEPOSITED"
    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "CLEARED"
