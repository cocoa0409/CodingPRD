"""Initial states, legal transitions, refused transitions and terminal lockdowns.

Each test drives one governed entity across the boundary the state machine draws
and reads back both the entity and whatever the transition was supposed to touch.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import create_committee_payload
from test_helpers.test_users import (
    ANALYST_ONE_USER_ID,
    DEAN_TWO_USER_ID,
    INTEGRITY_OFFICER_ONE_USER_ID,
    TEST_USERS,
    make_integrity_officer_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
DEAN_ONE = TEST_USERS["dean_headers"]


def test_committee_opens_in_draft_and_the_first_seat_is_confirmed(
    api: ApiClient,
) -> None:
    """The container is born empty and the chair seat lifts only the member count.

    PRD §3.3: "It is born `DRAFT`, with `member_count` and `external_member_count` at 0 and with `approved_by_user_id`, `approved_at` and `rejection_note` all null."

    Design: Corner/state_machines/committee_and_seat_initial_states_on_create
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Initial States"})

    committee = get_success_data(
        api.create_committee(
            create_committee_payload(world["thesis"]["id"]), world["student_headers"]
        ),
        201,
    )
    assert committee["status"] == "DRAFT"
    assert committee["member_count"] == 0
    assert committee["approved_by_user_id"] is None
    assert committee["approved_at"] is None

    world["committee"] = committee
    seat = fx.seat_member(world, world["chair"], "CHAIR")
    assert seat["status"] == "CONFIRMED"
    assert seat["withdrawal_reason"] is None

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["member_count"] == 1
    assert committee["external_member_count"] == 0
    assert committee["status"] == "DRAFT"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 0

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DRAFT"


def test_dean_cannot_rule_on_a_composition_that_was_never_submitted(
    api: ApiClient,
) -> None:
    """An APPROVE against a DRAFT committee is refused and grants nothing.

    PRD §3.3: "The same identifier guards the other three committee operations whose source status is constrained: seating a member is refused with `ERR_COMMITTEE_STATE_INVALID` when the committee is `DISSOLVED`, submitting the composition when the committee is not `DRAFT` or `REJECTED`, and the dean's ruling when the committee is not `SUBMITTED`."

    Design: Corner/state_machines/committee_decision_on_draft_committee_rejected
    """
    world = fx.setup_committee_with_seats(
        thesis_overrides={"title": "Premature Decision"}
    )

    validate_error(
        api.decide_committee(
            world["committee"]["id"], {"decision": "APPROVE"}, DEAN_ONE
        ),
        "ERR_COMMITTEE_STATE_INVALID",
        409,
    )

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "DRAFT"
    assert committee["approved_by_user_id"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DRAFT"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 0


def test_rejecting_the_composition_sends_the_document_back_to_draft(
    api: ApiClient,
) -> None:
    """The note is stored verbatim and the chair's load falls out of the counted set.

    PRD §3.3: "A `REJECT` moves the committee to `REJECTED`, stores the supplied note as `rejection_note`, sends the document back from `COMMITTEE_PENDING` to `DRAFT`, recomputes `active_chair_load` for every `CONFIRMED` chair and co-chair seat because `REJECTED` has left the counted set, and recomputes clearance."

    Design: Corner/state_machines/committee_reject_reverts_thesis_to_draft_and_stores_rejection_note
    """
    world = fx.setup_submitted_committee(
        thesis_overrides={"title": "Rejected Composition"}
    )

    rejected = get_success_data(
        api.decide_committee(
            world["committee"]["id"],
            {
                "decision": "REJECT",
                "rejection_note": "Second reader must hold a graduate appointment",
            },
            DEAN_ONE,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert (
        rejected["rejection_note"]
        == "Second reader must hold a graduate appointment"
    )
    assert rejected["approved_by_user_id"] is None
    assert rejected["approved_at"] is None
    assert rejected["member_count"] == 3

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DRAFT"

    chair = get_success_data(api.get_faculty_member(world["chair"]["id"], REGISTRAR))
    assert chair["active_chair_load"] == 0

    clearance = get_success_data(
        api.list_student_graduation_clearances(world["student"]["id"], REGISTRAR)
    )[0]
    assert clearance["status"] == "BLOCKED"


def test_outcome_recorded_an_hour_early_is_refused(api: ApiClient) -> None:
    """The clock has not reached the scheduled end, so the chair may not report yet.

    PRD §3.4: "The act is legal only while the event is `ANNOUNCED` and the document is `DEFENSE_ANNOUNCED`, and only once the logical clock has reached or passed the event's `scheduled_end`; an early recording, like any illegal source status, is `ERR_DEFENSE_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/defense_outcome_before_scheduled_end_rejected
    """
    world = fx.setup_announced_defense(thesis_overrides={"title": "Early Outcome"})
    fx.set_clock("2026-09-25T15:00:00Z")

    validate_error(
        api.record_defense_outcome(
            world["defense_event"]["id"], {"outcome": "PASS"}, world["chair_headers"]
        ),
        "ERR_DEFENSE_STATE_INVALID",
        409,
    )

    event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert event["status"] == "ANNOUNCED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_ANNOUNCED"

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 120


def test_a_failed_document_can_never_enter_format_review(api: ApiClient) -> None:
    """DEFENSE_FAILED is terminal, so no format cycle may be opened from it.

    PRD §3.5: "It is legal only while the document is `DEFENSE_PASSED`, `DEFENSE_PASSED_WITH_REVISIONS` or `FORMAT_REVISIONS_REQUIRED` — any other `workflow_state` is refused with `ERR_THESIS_STATE_INVALID` — and only while the governing term is still `OPEN`."

    Design: Corner/state_machines/terminal_defense_failed_thesis_rejects_format_submission
    """
    world = fx.setup_held_defense(
        outcome="FAIL",
        outcome_note="Methodology not defended",
        thesis_overrides={"title": "Failed Defense"},
    )

    validate_error(
        api.create_format_submission(
            world["thesis"]["id"], world["student_headers"]
        ),
        "ERR_THESIS_STATE_INVALID",
        409,
    )

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_FAILED"
    assert thesis["format_cycle_count"] == 0

    reviews = get_success_data(
        api.list_thesis_format_reviews(world["thesis"]["id"], REGISTRAR)
    )
    assert reviews == []

    event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert event["status"] == "HELD_FAIL"

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["status"] == "DISSOLVED"


def test_the_information_loop_counts_one_request_and_then_approves_the_full_term(
    api: ApiClient,
) -> None:
    """Out of the queue, back into it, then granted — with the count raised exactly once.

    PRD §3.7: "`REQUEST_INFO` moves the request `REQUESTED → MORE_INFO_REQUIRED`, increments `info_request_count` by one, records the supplied `decision_note`, and deliberately leaves `decided_at` null because nothing has been decided."

    PRD §3.7: "`APPROVE` moves the request to the terminal `APPROVED`, sets `approved_months` to the `requested_months` the candidate asked for, writes `decided_at` as the current logical instant and `decided_by_user_id` as the acting dean's `X-User-ID`, and recomputes clearance with the embargo-decision item satisfied."

    Design: Corner/state_machines/embargo_information_loop_returns_to_requested_and_counts_the_request
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Patent Pending Work"})
    world["embargo"] = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Provisional patent application filed",
    )

    pushed_back = fx.decide_embargo(
        world,
        world["embargo"],
        decision="REQUEST_INFO",
        decision_note="Attach the filing receipt",
        dean_user_id=DEAN_TWO_USER_ID,
    )
    assert pushed_back["status"] == "MORE_INFO_REQUIRED"
    assert pushed_back["info_request_count"] == 1
    assert pushed_back["decided_at"] is None
    assert pushed_back["decision_note"] == "Attach the filing receipt"

    supplemented = fx.supplement_embargo(
        world, world["embargo"], "Filing receipt 63/123456 attached"
    )
    assert supplemented["status"] == "REQUESTED"
    assert supplemented["justification"] == "Filing receipt 63/123456 attached"
    assert supplemented["info_request_count"] == 1

    approved = fx.decide_embargo(
        world,
        world["embargo"],
        decision="APPROVE",
        decision_note="Full 12 months granted",
        dean_user_id=DEAN_TWO_USER_ID,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_months"] == 12
    assert approved["decided_by_user_id"] == DEAN_TWO_USER_ID
    assert_instant(approved["decided_at"], "2026-09-25T16:30:00Z", "decided_at")
    assert approved["release_date"] is None
    assert approved["release_anchor"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "DEFENSE_PASSED"


def test_a_replacement_embargo_request_supersedes_the_undecided_one(
    api: ApiClient,
) -> None:
    """Exactly one non-terminal request survives, and the parent version advanced.

    PRD §3.7: "Creating it moves every existing request for the same document whose `status` is `REQUESTED` or `MORE_INFO_REQUIRED` to `SUPERSEDED`, and each superseded row keeps its accumulated `info_request_count` for audit."

    Design: Corner/state_machines/second_embargo_request_supersedes_the_pending_first_one
    """
    world = fx.setup_passed_defense(thesis_overrides={"title": "Superseded Request"})

    version_before_first = fx.thesis_version(world["thesis"]["id"])
    first = fx.request_embargo(
        world,
        reason_code="PATENT_PENDING",
        requested_months=12,
        justification="Provisional patent application filed",
    )
    version_before_second = fx.thesis_version(world["thesis"]["id"])
    assert version_before_second > version_before_first

    second = fx.request_embargo(
        world,
        reason_code="PUBLISHER_AGREEMENT",
        requested_months=6,
        justification="Publisher requires a six month hold",
    )

    superseded = get_success_data(api.get_embargo_request(first["id"], REGISTRAR))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["approved_months"] is None

    survivor = get_success_data(api.get_embargo_request(second["id"], REGISTRAR))
    assert survivor["status"] == "REQUESTED"
    assert survivor["reason_code"] == "PUBLISHER_AGREEMENT"
    assert survivor["requested_months"] == 6
    assert survivor["info_request_count"] == 0

    rows = get_success_data(
        api.list_thesis_embargo_requests(world["thesis"]["id"], REGISTRAR)
    )
    assert len(rows) == 2


def test_deficient_record_counts_for_nothing_until_it_is_accepted(
    api: ApiClient,
) -> None:
    """The dossier tally only credits the record once the analyst accepts it.

    PRD §3.5: "Every ruling captures the acting analyst's `X-User-ID` as `reviewed_by_user_id`, then recomputes the document's `documented_permission_count` — the count of its permission records whose `status` is `ACCEPTED` or `WAIVED`, so a `DEFICIENT` record contributes nothing and a `WAIVED` one counts as fully documented — and recomputes clearance."

    Design: Corner/state_machines/permission_record_deficient_then_accepted_reaches_terminal_state
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Reused Figure", "third_party_item_count": 1}
    )
    record = fx.document_permission(
        world,
        material_type="FIGURE",
        rights_basis="WRITTEN_PERMISSION",
        page_reference="p. 42",
        document_uri="https://repo.u.edu/permissions/fig-42.pdf",
    )

    deficient = fx.review_permission(
        world, record, decision="DEFICIENT", review_note="Letter is unsigned"
    )
    assert deficient["status"] == "DEFICIENT"
    assert deficient["review_note"] == "Letter is unsigned"
    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["documented_permission_count"] == 0

    accepted = fx.review_permission(
        world, record, decision="ACCEPT", review_note="Signed letter received"
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["review_note"] == "Signed letter received"
    assert accepted["reviewed_by_user_id"] == ANALYST_ONE_USER_ID

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["documented_permission_count"] == 1
    assert thesis["workflow_state"] == "DRAFT"


def test_an_accepted_permission_record_cannot_be_reopened(api: ApiClient) -> None:
    """ACCEPTED is terminal, so a second review changes neither status nor tally.

    PRD §3.5: "`ACCEPT` and `WAIVE` are legal from either `SUBMITTED` or `DEFICIENT`, whereas `DEFICIENT` is legal only from `SUBMITTED` — marking an already-deficient record deficient again, or reviewing a record that has reached the terminal `ACCEPTED` or `WAIVED`, is refused with `ERR_PERMISSION_RECORD_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/review_of_accepted_permission_record_rejected
    """
    world = fx.setup_draft_thesis(
        thesis_overrides={"title": "Accepted Permission", "third_party_item_count": 1}
    )
    record = fx.document_permission(
        world,
        material_type="TABLE",
        rights_basis="OPEN_LICENSE",
        page_reference="p. 12",
    )
    fx.review_permission(
        world, record, decision="ACCEPT", review_note="CC BY licence verified"
    )

    validate_error(
        api.review_permission_record(
            record["id"],
            {"decision": "DEFICIENT", "review_note": "Reopened by mistake"},
            ANALYST_ONE,
        ),
        "ERR_PERMISSION_RECORD_STATE_INVALID",
        409,
    )

    rows = get_success_data(
        api.list_thesis_permission_records(world["thesis"]["id"], REGISTRAR)
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "ACCEPTED"
    assert rows[0]["review_note"] == "CC BY licence verified"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["documented_permission_count"] == 1


def test_a_cleared_screening_cannot_be_referred(api: ApiClient) -> None:
    """An adjusted similarity below the tolerance leaves nothing to refer.

    PRD §3.6: "An `action` of `REFER` is legal only while the screening is `FLAGGED` and the document's `integrity_state` is `SCREEN_FLAGGED`; it moves the screening `FLAGGED → REFERRED`, writes `referred_at` as the current logical instant and `referred_by_user_id` as the acting officer's `X-User-ID`, drives `integrity_state` to `UNDER_INTEGRITY_REVIEW`, and recomputes clearance with the integrity item now unsatisfied."

    Design: Corner/state_machines/refer_action_on_cleared_screening_rejected
    """
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=25.0,
        excluded_quoted_pct=7.5,
        thesis_overrides={"title": "Cleared Screening"},
    )

    validate_error(
        api.act_on_integrity_screening(
            world["screening"]["id"],
            {"action": "REFER", "resolution_note": "Escalating anyway"},
            make_integrity_officer_headers(INTEGRITY_OFFICER_ONE_USER_ID),
        ),
        "ERR_SCREENING_STATE_INVALID",
        409,
    )

    screenings = get_success_data(
        api.list_thesis_integrity_screenings(world["thesis"]["id"], REGISTRAR)
    )
    assert len(screenings) == 1
    assert screenings[0]["adjusted_similarity_pct"] == pytest.approx(17.50, abs=0.001)
    assert screenings[0]["status"] == "CLEARED"
    assert screenings[0]["referred_at"] is None
    assert screenings[0]["referred_by_user_id"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "SCREEN_CLEARED"

    cycle = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert cycle["status"] == "PENDING_REVIEW"
