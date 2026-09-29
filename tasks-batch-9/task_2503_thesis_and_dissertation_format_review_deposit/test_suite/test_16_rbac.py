"""Role gates, entity-backed ownership, chair identity and the two duty-segregation pairs.

Every test pairs the denial with the caller the PRD does authorise, so the assertion
isolates the header or the identifier that made the difference rather than the payload.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.factories import (
    create_committee_payload,
    create_repository_deposit_payload,
    create_thesis_payload,
)
from test_helpers.test_users import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    DEAN_ONE_USER_ID,
    DEAN_TWO_USER_ID,
    TEST_USERS,
    make_faculty_member_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]
DEAN_ONE = TEST_USERS["dean_headers"]
DEAN_TWO = TEST_USERS["dean_two_headers"]
INTEGRITY_OFFICER = TEST_USERS["integrity_officer_headers"]


def test_only_the_dean_may_rule_on_a_submitted_composition(api: ApiClient) -> None:
    """Candidate and registrar are both refused on the role check, then the dean approves.

    PRD §2.1: "If the headers are well-formed but the declared role is not listed for the requested operation in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/student_and_registrar_cannot_decide_committee_composition
    """
    world = fx.setup_submitted_committee(thesis_overrides={"title": "Role Gated Ruling"})
    committee_id = world["committee"]["id"]

    validate_error(
        api.decide_committee(
            committee_id, {"decision": "APPROVE"}, world["student_headers"]
        ),
        "ERR_UNAUTHORIZED_ROLE",
        403,
    )
    validate_error(
        api.decide_committee(committee_id, {"decision": "APPROVE"}, REGISTRAR),
        "ERR_UNAUTHORIZED_ROLE",
        403,
    )

    still_submitted = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["approved_by_user_id"] is None

    approved = get_success_data(
        api.decide_committee(committee_id, {"decision": "APPROVE"}, DEAN_ONE), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == DEAN_ONE_USER_ID

    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "COMMITTEE_APPROVED"
    )


def test_the_outcome_endpoint_denies_the_wrong_role_and_the_wrong_faculty(
    api: ApiClient,
) -> None:
    """The analyst fails the role check; a seated member fails the chair identity check.

    PRD §2.1: "Recording a defense outcome additionally requires that this identifier be the `faculty_id` of the `CONFIRMED` `CHAIR` seat of the `APPROVED` committee of the thesis being defended; anyone else is refused with `ERR_NOT_COMMITTEE_CHAIR` (HTTP 403)."

    Design: Corner/rbac/outcome_endpoint_rejects_the_analyst_role_then_the_non_chair_faculty
    """
    world = fx.setup_announced_defense(thesis_overrides={"title": "Chair Only Outcome"})
    event_id = world["defense_event"]["id"]
    fx.set_clock("2026-09-25T16:30:00Z")

    validate_error(
        api.record_defense_outcome(event_id, {"outcome": "PASS"}, ANALYST_ONE),
        "ERR_UNAUTHORIZED_ROLE",
        403,
    )
    validate_error(
        api.record_defense_outcome(
            event_id,
            {"outcome": "PASS"},
            make_faculty_member_headers(world["member_1"]["id"]),
        ),
        "ERR_NOT_COMMITTEE_CHAIR",
        403,
    )

    assert (
        get_success_data(api.get_defense_event(event_id, REGISTRAR))["status"]
        == "ANNOUNCED"
    )
    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "DEFENSE_ANNOUNCED"
    )

    held = get_success_data(
        api.record_defense_outcome(
            event_id,
            {"outcome": "PASS", "outcome_note": "Unanimous pass"},
            world["chair_headers"],
        ),
        200,
    )
    # PRD §3.4 enumerates the DefenseEvent's own fields as `announced_at`,
    # `announcement_lead_bdays`, `outcome_note` and `cancellation_reason`; `outcome`
    # appears only as the request-body input, and the recorded result is carried by
    # `status`. No PRD sentence makes `outcome` a response-visible attribute, so only
    # the status transition is asserted here.
    assert held["status"] == "HELD_PASS"

    assert (
        get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))[
            "workflow_state"
        ]
        == "DEFENSE_PASSED"
    )
    assert (
        get_success_data(api.get_thesis_committee(world["thesis"]["id"], REGISTRAR))[0][
            "status"
        ]
        == "APPROVED"
    )


def test_a_candidate_may_not_borrow_another_candidates_thesis(api: ApiClient) -> None:
    """Ownership is compared against the targeted row, on the body key and through the path.

    PRD §2.1: "In practice that means the acting student's identifier must equal the `student_id` of the thesis the request targets, whether the thesis is named directly in the body or reached through the `Committee`, `CommitteeMember`, `FormatReview` or `EmbargoRequest` named in the path; a mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/other_student_cannot_act_on_another_candidates_thesis
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    term = fx.create_term()
    ada = fx.create_student()
    ben = fx.create_student(full_name="Ben Ruiz", email="ben@u.edu")
    ada_headers = make_student_headers(ada["id"])
    ben_headers = make_student_headers(ben["id"])
    payload = create_thesis_payload(ada["id"], term["id"], title="Ownership Probe")

    validate_error(
        api.create_thesis(payload, ben_headers), "ERR_NOT_RESOURCE_OWNER", 403
    )
    rows, _ = validate_paginated(api.list_theses(REGISTRAR))
    assert rows == []

    thesis = get_success_data(api.create_thesis(payload, ada_headers), 201)
    assert thesis["student_id"] == ada["id"]

    validate_error(
        api.create_committee(create_committee_payload(thesis["id"]), ben_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    assert get_success_data(api.get_thesis_committee(thesis["id"], REGISTRAR)) == []

    committee = get_success_data(
        api.create_committee(create_committee_payload(thesis["id"]), ada_headers), 201
    )
    assert committee["thesis_id"] == thesis["id"]
    assert committee["status"] == "DRAFT"


def test_the_analyst_who_accepted_the_format_may_not_deposit_it(api: ApiClient) -> None:
    """Same role, same payload — only the operator identifier differs.

    PRD §2.8: "The analyst who performs a repository deposit must not be the analyst whose `X-User-ID` was captured as `decided_by_user_id` on the `ACCEPTED` `FormatReview` of that thesis."

    Design: Corner/rbac/depositing_analyst_who_signed_the_acceptance_is_rejected
    """
    world = fx.setup_format_accepted_thesis(
        cycle_clock="2026-10-05T09:00:00Z",
        similarity_pct=5.0,
        excluded_quoted_pct=None,
        decision_clock="2026-10-12T09:00:00Z",
        accepting_analyst_user_id=ANALYST_ONE_USER_ID,
        thesis_overrides={"title": "Segregated Deposit"},
    )
    thesis_id = world["thesis"]["id"]
    fx.set_clock("2026-11-02T10:00:00Z")
    payload = create_repository_deposit_payload(
        thesis_id,
        abstract_word_count=150,
        subject_keywords=["a", "b", "c"],
        late_fee_paid_cents=0,
        advisor_name="Cara Cho",
        department_code="CS",
    )

    validate_error(
        api.create_repository_deposit(payload, ANALYST_ONE),
        "ERR_DUTY_SEGREGATION_VIOLATION",
        403,
    )
    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))["workflow_state"]
        == "FORMAT_ACCEPTED"
    )
    assert get_success_data(api.get_thesis_repository_deposit(thesis_id, REGISTRAR)) == []

    deposit = get_success_data(api.create_repository_deposit(payload, ANALYST_TWO), 201)
    assert deposit["depositor_user_id"] == ANALYST_TWO_USER_ID
    assert deposit["status"] == "DEPOSITED"

    review = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert review["decided_by_user_id"] == ANALYST_ONE_USER_ID
    assert (
        get_success_data(api.get_thesis(thesis_id, REGISTRAR))["workflow_state"]
        == "DEPOSITED"
    )


def test_the_dean_who_approved_the_committee_may_not_rule_on_the_embargo(
    api: ApiClient,
) -> None:
    """The second segregation pair keys on the committee's approver, not the format review.

    PRD §2.8: "The dean who rules on a thesis's embargo request must not be the dean whose `X-User-ID` was captured as `approved_by_user_id` on that thesis's `Committee`."

    Design: Corner/rbac/dean_who_approved_the_committee_cannot_decide_the_embargo
    """
    world = fx.setup_passed_defense(
        dean_user_id=DEAN_ONE_USER_ID, thesis_overrides={"title": "Segregated Embargo"}
    )
    embargo = fx.request_embargo(
        world,
        reason_code="PUBLISHER_AGREEMENT",
        requested_months=6,
        justification="Publisher requires a six month hold.",
    )

    validate_error(
        api.decide_embargo_request(embargo["id"], {"decision": "APPROVE"}, DEAN_ONE),
        "ERR_DUTY_SEGREGATION_VIOLATION",
        403,
    )
    untouched = get_success_data(api.get_embargo_request(embargo["id"], REGISTRAR))
    assert untouched["status"] == "REQUESTED"
    assert untouched["decided_by_user_id"] is None

    approved = get_success_data(
        api.decide_embargo_request(
            embargo["id"],
            {"decision": "APPROVE", "decision_note": "Publisher agreement on file."},
            DEAN_TWO,
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_months"] == 6
    assert approved["decided_by_user_id"] == DEAN_TWO_USER_ID

    committee = get_success_data(
        api.get_thesis_committee(world["thesis"]["id"], REGISTRAR)
    )[0]
    assert committee["approved_by_user_id"] == DEAN_ONE_USER_ID


def test_all_six_roles_read_the_same_thesis_detail(api: ApiClient) -> None:
    """The read is shared, so even a candidate who owns nothing here still gets 200.

    PRD §4: "| GET | `/graduate-school/theses/{id}` | Read a thesis with both state dimensions and every derived counter | `Student`, `FacultyMember`, `GradSchoolAnalyst`, `GraduateDean`, `IntegrityOfficer`, `Registrar` |"

    Design: Corner/rbac/every_role_can_read_the_thesis_detail_shared_operation
    """
    world = fx.setup_draft_thesis(thesis_overrides={"title": "Shared Read"})
    stranger = fx.add_student(world, full_name="Ben Ruiz", email="ben@u.edu")
    thesis_id = world["thesis"]["id"]

    readers = [
        make_student_headers(stranger["id"]),
        make_faculty_member_headers(world["chair"]["id"]),
        ANALYST_ONE,
        TEST_USERS["dean_headers"],
        INTEGRITY_OFFICER,
        REGISTRAR,
    ]
    for headers in readers:
        thesis = get_success_data(api.get_thesis(thesis_id, headers), 200)
        assert thesis["id"] == thesis_id
        assert thesis["student_id"] == world["student"]["id"]
        assert thesis["workflow_state"] == "DRAFT"
        assert thesis["version"] == 1
