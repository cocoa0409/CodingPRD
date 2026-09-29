"""Cascades that travel several hops from the row the client actually wrote.

Adding one seat to an approved committee unwinds the dean's grant, the document's
state, the defense occupation and the room counter; upholding an integrity
referral runs the same kind of chain backwards through a completed workflow.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ONE_USER_ID,
    INTEGRITY_OFFICER_TWO_USER_ID,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _seat_added_to_an_approved_committee() -> dict:
    """A fourth member joins after the dean approved and the defense was announced."""
    world = fx.setup_announced_defense()
    world["fourth_faculty"] = fx.add_faculty_member(
        world,
        full_name="Fay Ortiz",
        email="fay@u.edu",
        appointment_type="ADJUNCT",
    )
    world["fourth_seat"] = fx.seat_member(world, world["fourth_faculty"], "MEMBER")
    return world


def test_added_seat_voids_the_grant_and_cancels_the_announced_defense(
    api: ApiClient,
) -> None:
    """The composition change cancels the occupation with the fixed reason string.

    PRD §3.3: "Third, because the document has left `DEFENSE_SCHEDULED` or `DEFENSE_ANNOUNCED`, every `DefenseEvent` for it whose `status` is `DRAFT` or `ANNOUNCED` is moved to `CANCELLED` with `cancellation_reason` set to the fixed string `COMMITTEE_COMPOSITION_CHANGED`."

    Design: Difficulty/transitive_cascade/seat_added_to_approved_committee_cancels_defense_and_releases_room_minutes
    """
    world = _seat_added_to_an_approved_committee()

    assert world["fourth_seat"]["status"] == "CONFIRMED"

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "SUBMITTED"
    assert committee["approved_by_user_id"] is None
    assert committee["approved_at"] is None
    assert committee["member_count"] == 4
    assert committee["external_member_count"] == 0

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "COMMITTEE_PENDING"

    event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert event["status"] == "CANCELLED"
    assert event["cancellation_reason"] == "COMMITTEE_COMPOSITION_CHANGED"

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 0


def test_added_seat_returns_the_candidate_to_blocked_without_losing_chair_load(
    api: ApiClient,
) -> None:
    """The same request recomputes clearance and chair load in one pass.

    PRD §3.3: "The candidate's clearance and the `active_chair_load` of every chair and co-chair seat are recomputed as part of the same request, and because the document is once again in a pre-approval state the committee-approval clearance item is no longer satisfied."

    Design: Difficulty/transitive_cascade/seat_added_to_approved_committee_cancels_defense_and_releases_room_minutes
    """
    world = _seat_added_to_an_approved_committee()

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "BLOCKED"

    student = get_success_data(api.get_student(world["student"]["id"], REGISTRAR))
    assert student["graduation_clearance_state"] == "BLOCKED"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 1


def _post_deposit_allegation_upheld() -> dict:
    """A deposited document is screened again, referred and then upheld."""
    world = fx.setup_deposited_thesis(
        critical_defect_count=1,
        major_defect_count=1,
        minor_defect_count=1,
        deposit_clock="2026-12-04T10:00:00Z",
        deposit_overrides={
            "abstract_word_count": 200,
            "subject_keywords": ["ethics", "citation", "review"],
            "late_fee_paid_cents": 0,
        },
        thesis_overrides={"title": "Post-Deposit Allegation"},
    )
    world["allegation"] = fx.record_screening(
        world, similarity_pct=21.4, excluded_quoted_pct=3.4
    )
    fx.act_on_screening(
        world,
        world["allegation"],
        "REFER",
        resolution_note="Allegation received from the external reviewer",
        officer_user_id=INTEGRITY_OFFICER_ONE_USER_ID,
    )
    world["allegation"] = fx.act_on_screening(
        world,
        world["allegation"],
        "UPHOLD",
        resolution_note="Panel upheld the finding on chapter 2",
        officer_user_id=INTEGRITY_OFFICER_TWO_USER_ID,
    )
    return world


def test_upheld_finding_terminates_the_document_and_withdraws_the_deposit(
    api: ApiClient,
) -> None:
    """Upholding drives both state dimensions terminal and withdraws the deposit.

    PRD §3.6: "Because the document is now `TERMINATED`, every one of its format review cycles whose `status` is `PENDING_REVIEW` or `REVISIONS_REQUIRED` is moved to `VOID`, and any `RepositoryDeposit` for it whose `status` is `DEPOSITED` is moved to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/integrity_uphold_terminates_thesis_withdraws_deposit_and_withholds_degree
    """
    world = _post_deposit_allegation_upheld()

    upheld = world["allegation"]
    assert upheld["status"] == "UPHELD"
    assert upheld["adjusted_similarity_pct"] == pytest.approx(18.00, abs=0.001)
    assert upheld["resolved_by_user_id"] == INTEGRITY_OFFICER_TWO_USER_ID

    earlier = get_success_data(
        api.list_thesis_integrity_screenings(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert earlier["status"] == "SUPERSEDED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "INTEGRITY_UPHELD"
    assert thesis["workflow_state"] == "TERMINATED"

    deposit = get_success_data(
        api.get_thesis_repository_deposit(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert deposit["status"] == "WITHDRAWN"
    assert deposit["late_fee_cents"] == 0
    assert deposit["handle"] == world["deposit"]["handle"]


def test_upheld_finding_withholds_the_degree_and_writes_the_fixed_notation(
    api: ApiClient,
) -> None:
    """The clearance and the candidate carry the fixed withhold reason and notation.

    PRD §3.6: "Because the deposit was withdrawn and the document terminated, the candidate's `GraduationClearance` moves to `WITHHELD` with `withheld_reason` set to the fixed string `ACADEMIC_INTEGRITY_FINDING` and `transcript_notation` set to the fixed string `Degree withheld pending academic integrity resolution`, and `cleared_at` is reset to null if the clearance had previously been `CLEARED`."

    Design: Difficulty/transitive_cascade/integrity_uphold_terminates_thesis_withdraws_deposit_and_withholds_degree
    """
    world = _post_deposit_allegation_upheld()

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "WITHHELD"
    assert clearance["withheld_reason"] == "ACADEMIC_INTEGRITY_FINDING"
    assert (
        clearance["transcript_notation"]
        == "Degree withheld pending academic integrity resolution"
    )
    assert clearance["cleared_at"] is None

    student = get_success_data(api.get_student(world["student"]["id"], REGISTRAR))
    assert student["graduation_clearance_state"] == "WITHHELD"
    assert (
        student["transcript_notation"]
        == "Degree withheld pending academic integrity resolution"
    )
    assert student["degree_conferred"] is False
