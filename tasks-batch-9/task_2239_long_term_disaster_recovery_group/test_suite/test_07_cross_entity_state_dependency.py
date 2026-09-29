"""Writes whose legality is decided by the state of a record they only reference.

In both scenarios the target record is perfectly ready; the request is refused
because a second entity — the meeting, or the construction phase — is not.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_allocation_lines,
    assert_case_presentation,
    assert_disbursement,
    assert_funding_source_conservation,
    assert_table_session,
    assert_version_unchanged,
    create_funding_source,
    create_project,
    open_session,
    queue_presentation,
    read_funding_source,
    read_presentation,
    request_disbursement,
    schedule_session,
    seat_member_org,
    setup_assessed_case,
    setup_awarded_case,
    transition_project,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["unmet_needs_chair_headers"]
ADMIN = TEST_USERS["ltrg_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


def _setup_queued_presentation_on_a_scheduled_session() -> Dict[str, Any]:
    """An assessed case queued onto a meeting that has not been opened yet."""
    scenario = setup_assessed_case(damage=[("STRUCTURE", 900_000)])
    scenario["member_org"] = seat_member_org(
        org_name="Trinity Episcopal Outreach", annual_pledge_cap_cents=1_000_000
    )
    scenario["session"] = schedule_session(
        session_label="UNT 2026-09-10", quorum_min_member_orgs=1
    )
    scenario["presentation"] = queue_presentation(
        scenario["case"]["id"], scenario["session"]["id"], scenario["assessment"]["id"]
    )
    return scenario


def test_queueing_onto_a_meeting_that_is_only_scheduled_is_allowed(api):
    """PRD §3.4: "The target session's `status` must be `SCHEDULED` or `IN_SESSION`, or
    `ERR_SESSION_NOT_ACCEPTING_QUEUE` results."

    Design: Difficulty/cross_entity_state_dependency/present_requires_table_session_in_session_not_merely_scheduled
    """
    scenario = _setup_queued_presentation_on_a_scheduled_session()

    presentation = read_presentation(scenario["presentation"]["id"])

    assert_case_presentation(presentation)
    assert presentation["status"] == "QUEUED"
    assert presentation["queue_position"] == 1
    session = validate_success(api.get_table_session(scenario["session"]["id"], CHAIR))
    assert_table_session(session)
    assert session["status"] == "SCHEDULED"
    assert session["queued_count"] == 1


def test_calling_a_presentation_before_the_meeting_opens_is_refused(api):
    """PRD §3.4: "Calling a presentation moves it `QUEUED → PRESENTING`. It is the
    chair's act, it requires the session to be `IN_SESSION` — otherwise
    `ERR_SESSION_NOT_IN_SESSION` — and it requires the presentation to be at the head of
    the queue: `queue_position` must be exactly 1, and calling any other presentation is
    refused with `ERR_NOT_AT_QUEUE_HEAD`."

    Design: Difficulty/cross_entity_state_dependency/present_requires_table_session_in_session_not_merely_scheduled
    """
    scenario = _setup_queued_presentation_on_a_scheduled_session()
    before = read_presentation(scenario["presentation"]["id"])

    response = api.present_case_presentation(before["id"], {}, CHAIR)

    # The presentation itself is at the head of the queue; only the meeting is unready.
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_IN_SESSION.value, 409)
    after = read_presentation(before["id"])
    assert after["status"] == "QUEUED"
    assert after["queue_position"] == 1
    assert_version_unchanged(before, after)


def test_opening_the_meeting_unblocks_the_identical_call(api):
    """PRD §3.4: "On success `queue_position` becomes 0, the remaining `QUEUED`
    presentations of the session are re-ranked, and the session's `queued_count`
    decrements."

    Design: Difficulty/cross_entity_state_dependency/present_requires_table_session_in_session_not_merely_scheduled
    """
    scenario = _setup_queued_presentation_on_a_scheduled_session()
    validate_error(
        api.present_case_presentation(scenario["presentation"]["id"], {}, CHAIR),
        ApiErrorId.ERR_SESSION_NOT_IN_SESSION.value,
        409,
    )
    opened = open_session(scenario["session"]["id"], [scenario["member_org"]["id"]])
    assert opened["status"] == "IN_SESSION"
    assert opened["attending_member_org_ids"] == [scenario["member_org"]["id"]]

    called = validate_success(
        api.present_case_presentation(scenario["presentation"]["id"], {}, CHAIR)
    )

    assert called["status"] == "PRESENTING"
    assert called["queue_position"] == 0
    session = validate_success(api.get_table_session(scenario["session"]["id"], CHAIR))
    assert session["queued_count"] == 0


def _setup_cleared_payment_against_a_scoped_phase() -> Dict[str, Any]:
    """A cleared 1000000 structure payment naming a phase still at SCOPED.

    The grant is large enough and forbids administrative retention, so the only thing
    standing between the row and approval is the phase's own status.
    """
    scenario = setup_awarded_case(
        damage=[("STRUCTURE", 2_000_000)],
        orgs=[{"org_name": "Copper Ridge Foundation", "annual_pledge_cap_cents": 3_000_000}],
        pledges=[(0, 2_000_000, "STRUCTURE_REPAIR")],
    )
    scenario["source"] = create_funding_source(
        label="Structure repair grant",
        source_type="GOVERNMENT_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=2_000_000,
        admin_retention_allowed=False,
    )
    project = create_project(
        scenario["case"]["id"], required_trade_hours={"FRAMING": 200, "DRYWALL": 100}
    )
    scenario["project"] = project
    scenario["requested"] = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        1_000_000,
        project_id=project["id"],
        commitment_id=scenario["commitments"][0]["id"],
    )
    return scenario


def test_approving_a_structure_payment_against_a_scoped_phase_is_refused(api):
    """PRD §3.6: "When `purpose_code` is `STRUCTURE_REPAIR`, the named construction
    project's `status` must be `PERMITTED`, `IN_PROGRESS` or `PUNCHLIST`, or
    `ERR_PROJECT_NOT_PAYABLE` results."

    Design: Difficulty/cross_entity_state_dependency/structure_repair_approval_requires_project_permitted_not_scoped
    """
    scenario = _setup_cleared_payment_against_a_scoped_phase()
    assert scenario["project"]["status"] == "SCOPED"
    assert scenario["requested"]["status"] == "DOB_CLEARED"

    response = api.approve_disbursement(
        scenario["requested"]["id"], {"approval_note": "Approve rebuild payment"}, ADMIN
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_PAYABLE.value, 409)
    row = validate_success(api.get_disbursement(scenario["requested"]["id"], OFFICER))
    assert row["status"] == "DOB_CLEARED"
    assert row["allocation_lines"] == []
    source = read_funding_source(scenario["source"]["id"])
    assert source["committed_cents"] == 0
    assert source["available_cents"] == 2_000_000
    assert_funding_source_conservation(source)


def test_permitting_the_phase_unblocks_the_identical_approval(api):
    """PRD §3.6: "The line's retention is three and one-half percent of the line's net,
    rounded half up to the nearest cent, when the source permits retention, and 0 when
    it does not."

    Design: Difficulty/cross_entity_state_dependency/structure_repair_approval_requires_project_permitted_not_scoped
    """
    scenario = _setup_cleared_payment_against_a_scoped_phase()
    validate_error(
        api.approve_disbursement(
            scenario["requested"]["id"], {"approval_note": "Approve rebuild payment"}, ADMIN
        ),
        ApiErrorId.ERR_PROJECT_NOT_PAYABLE.value,
        409,
    )
    permitted = transition_project(
        scenario["project"]["id"], "PERMIT", permit_number="PB-3319"
    )
    assert permitted["status"] == "PERMITTED"

    approved = validate_success(
        api.approve_disbursement(
            scenario["requested"]["id"], {"approval_note": "Approve rebuild payment"}, ADMIN
        )
    )

    assert_disbursement(approved)
    assert approved["status"] == "APPROVED"
    assert len(approved["allocation_lines"]) == 1
    assert approved["allocation_lines"][0]["funding_source_id"] == scenario["source"]["id"]
    assert_allocation_lines(approved["allocation_lines"], 1_000_000, retention_allowed=False)
    assert approved["net_cents"] == 1_000_000
    assert approved["admin_retained_cents"] == 0
    assert approved["gross_cents"] == 1_000_000
    source = read_funding_source(scenario["source"]["id"])
    assert source["committed_cents"] == 1_000_000
    assert source["available_cents"] == 1_000_000
    assert source["status"] == "OPEN"
    assert_funding_source_conservation(source)
