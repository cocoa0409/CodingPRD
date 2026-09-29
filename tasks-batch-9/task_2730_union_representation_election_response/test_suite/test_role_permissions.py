"""Who may act on a representation case: role authorization, self-scoped supervisor
reads, segregation of duties between a message's author and its legal reviewer, and
header authentication.
"""
import pytest

from test_helpers import (
    ANALYST,
    BOARD,
    COUNSEL,
    COUNSEL_TWO,
    DIRECTOR,
    TEST_DEFAULTS,
    TRAINER,
    UNION,
    ApiErrorId,
    accuracy_review,
    add_classification,
    add_voter_entry,
    api_client,
    assert_instant_equals,
    build_user_headers,
    create_campaign_message,
    create_election_agreement,
    create_petition,
    create_poll_session,
    create_voter_list,
    latest_round,
    make_director_headers,
    make_plant_supervisor_headers,
    open_scope_analysis,
    read_petition,
    register_supervisor,
    score_and_rule,
    set_clock,
    stipulate_agreement,
    submit_message_for_review,
    submit_voter_list,
    train_supervisor,
    validate_error,
    validate_paginated,
    validate_success,
    verify_showing,
)

# The two undisputed classifications of the voting unit: 60 plus 30 heads, so a
# valid card count of 30 is a 33.33 percent showing once both are ruled in.
UNIT_ROSTER = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
    {
        "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
        "avg_hourly_wage_cents": 3200, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
        "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
    },
]

CARD_AUDIT = {
    "submitted_card_count": 40,
    "duplicate_card_count": 3,
    "undated_card_count": 2,
    "stale_card_count": 2,
    "nonunit_card_count": 3,
}

APPROVAL_CLOCK = "2026-08-20T15:00:00Z"
FILING_CLOCK = "2026-08-21T10:00:00Z"
SHARED_USER_ID = "user-shared-9"


def _docketed_case():
    """A petition docketed and moved into scope analysis."""
    set_clock(TEST_DEFAULTS["CLOCK"])
    petition = create_petition()
    return open_scope_analysis(petition["id"])


def _case_with_a_fully_ruled_roster():
    """Scope analysis with both classifications scored by the employer and ruled in."""
    petition = _docketed_case()
    classifications = [
        add_classification(petition["id"], ANALYST, **spec) for spec in UNIT_ROSTER
    ]
    for classification in classifications:
        score_and_rule(classification["id"], "INCLUDED")
    return read_petition(petition["id"]), classifications


def _case_with_the_election_set():
    """A verified showing, a stipulated arrangement approved on a Thursday, round 1."""
    petition, classifications = _case_with_a_fully_ruled_roster()
    petition = verify_showing(petition["id"], **CARD_AUDIT)
    agreement = create_election_agreement(petition["id"])
    set_clock(APPROVAL_CLOCK)
    agreement = stipulate_agreement(agreement["id"])
    return {
        "petition": read_petition(petition["id"]),
        "classifications": classifications,
        "agreement": agreement,
        "round": latest_round(petition["id"]),
    }


def _case_with_a_draft_list_built_by_the_analyst():
    """Three complete voter entries assembled by the analyst, clock inside the window."""
    ctx = _case_with_the_election_set()
    voter_list = create_voter_list(
        ctx["petition"]["id"], ctx["agreement"]["id"], headers=ANALYST
    )
    production, maintenance = ctx["classifications"]
    entries = [
        add_voter_entry(voter_list["id"], production["id"], ANALYST,
                        full_name="Ana Ruiz", hire_date="2024-03-11",
                        personal_email="ana@example.com"),
        add_voter_entry(voter_list["id"], production["id"], ANALYST,
                        full_name="Ben Okafor", hire_date="2023-07-01",
                        personal_email="ben@example.com"),
        add_voter_entry(voter_list["id"], maintenance["id"], ANALYST,
                        full_name="Cara Lindqvist", hire_date="2022-11-28",
                        personal_email="cara@example.com"),
    ]
    set_clock(FILING_CLOCK)
    ctx["voter_list"] = voter_list
    ctx["entries"] = entries
    return ctx


def _case_with_sessions_and_a_draft_message():
    """Two polling sessions at different locations, one supervisor, one email draft."""
    ctx = _case_with_the_election_set()
    ctx["sessions"] = [
        create_poll_session(ctx["round"]["id"], location_code="GATE_A"),
        create_poll_session(ctx["round"]["id"], location_code="GATE_B"),
    ]
    ctx["supervisor"] = register_supervisor(
        ctx["petition"]["id"], TRAINER, full_name="Marta Chen",
        job_title="Line Lead", span_of_control=14,
    )
    set_clock(FILING_CLOCK)
    ctx["message"] = create_campaign_message(
        ctx["petition"]["id"], DIRECTOR, channel="EMAIL", audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-26T13:00:00Z",
    )
    return ctx


def _message_awaiting_legal_review():
    """An email message drafted by one shared user identity and sent into legal review."""
    ctx = _case_with_the_election_set()
    author = make_director_headers(SHARED_USER_ID)
    message = create_campaign_message(
        ctx["petition"]["id"], author, channel="EMAIL", audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-26T13:00:00Z",
    )
    accuracy_review(message["id"], ANALYST, material_claim_count=2,
                    unsupported_material_claim_count=0)
    ctx["author_headers"] = author
    ctx["message"] = submit_message_for_review(message["id"], author)
    return ctx


def _case_with_two_supervisors_and_a_meeting_message():
    """Marta Chen trained, Omar Diaz untrained, and a meeting message Marta presents."""
    ctx = _case_with_the_election_set()
    trained = register_supervisor(
        ctx["petition"]["id"], TRAINER, full_name="Marta Chen", job_title="Line Lead",
        span_of_control=14, has_hire_fire_authority=False,
    )
    untrained = register_supervisor(
        ctx["petition"]["id"], DIRECTOR, full_name="Omar Diaz",
        job_title="Shift Supervisor", span_of_control=22, has_hire_fire_authority=True,
    )
    ctx["trained"] = train_supervisor(trained["id"])
    ctx["untrained"] = untrained
    ctx["message"] = create_campaign_message(
        ctx["petition"]["id"], DIRECTOR, channel="SMALL_GROUP_MEETING",
        audience_scope="CLASSIFICATION", planned_delivery_at="2026-08-26T13:00:00Z",
        duration_minutes=30, presenter_supervisor_id=trained["id"],
    )
    return ctx


@pytest.mark.parametrize(
    "caller",
    [DIRECTOR, ANALYST, UNION],
    ids=["director", "analyst", "union_representative"],
)
def test_the_showing_of_interest_audit_is_closed_to_the_parties(caller):
    """Neither the employer's director, nor the data analyst, nor the union's
    representative may run the card audit that only the Board performs.

    PRD: "A request from a role not listed in the final column is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/the_board_s_neutral_determinations_are_closed_to_every_party_role
    """
    petition, _ = _case_with_a_fully_ruled_roster()

    resp = api_client.verify_showing(petition["id"], dict(CARD_AUDIT), caller)

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    assert read_petition(petition["id"])["case_status"] == "SCOPE_ANALYSIS"


def test_certification_by_the_employer_is_refused_on_authorization_not_on_state():
    """Certifying is a Board act, so the director's attempt is answered on
    authorization even though the case has no round to certify and the named round
    does not exist.

    PRD: "Checks run in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status:"

    PRD: "2. **Endpoint authorization** — the acting role appears on the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/the_board_s_neutral_determinations_are_closed_to_every_party_role
    """
    petition, classifications = _case_with_a_fully_ruled_roster()

    resp = api_client.certify_petition(
        petition["id"], {"election_round_id": classifications[0]["id"]}, DIRECTOR
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    assert read_petition(petition["id"])["case_status"] == "SCOPE_ANALYSIS"


def test_scoring_and_reconsideration_admit_only_the_roles_that_hold_them():
    """Scoring is shared with counsel but is closed to the analyst who created the
    classification, and reconsideration is the Board's alone; a refused call leaves
    the ruling standing.

    PRD: "A request from a role not listed in the final column is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/the_board_s_neutral_determinations_are_closed_to_every_party_role
    """
    _, classifications = _case_with_a_fully_ruled_roster()
    production = classifications[0]

    refused_reconsider = api_client.reconsider_classification(
        production["id"], {"reconsideration_note": "Reversed on review"}, COUNSEL
    )
    refused_score = api_client.score_classification(
        production["id"], {"scoring_standard": "TRADITIONAL"}, ANALYST
    )

    validate_error(refused_reconsider, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    validate_error(refused_score, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    read_back = validate_success(api_client.get_classification(production["id"], ANALYST))
    assert read_back["scope_ruling"] == "INCLUDED"


def test_the_board_agent_verifies_the_showing_against_the_ruled_headcount():
    """The same audit body the parties were refused succeeds for a BoardAgent and
    advances the case on a sufficient showing.

    PRD: "`showing_of_interest_pct` is the valid card count multiplied by 100, divided by the selected denominator, rounded half-up to two decimals."

    PRD: "On a `SUFFICIENT` verdict the case advances from `SCOPE_ANALYSIS` to `SOI_VERIFIED`, writing `valid_card_count`, `showing_of_interest_pct`, `showing_headcount_basis` and `showing_verdict`."

    Design: Corner/rbac/the_board_s_neutral_determinations_are_closed_to_every_party_role
    """
    petition, _ = _case_with_a_fully_ruled_roster()

    resp = api_client.verify_showing(petition["id"], dict(CARD_AUDIT), BOARD)

    verified = validate_success(resp)
    assert verified["valid_card_count"] == 30
    assert float(verified["showing_of_interest_pct"]) == pytest.approx(33.33, abs=0.005)
    assert verified["showing_verdict"] == "SUFFICIENT"
    assert verified["case_status"] == "SOI_VERIFIED"


@pytest.mark.parametrize(
    "caller",
    [ANALYST, TRAINER, UNION],
    ids=["analyst", "trainer", "union_representative"],
)
def test_attesting_the_voter_list_is_refused_to_everyone_but_the_director(caller):
    """The analyst who assembled every row still cannot sign the list, and neither can
    the trainer or the petitioner; the list stays in draft.

    PRD: "Filing the list is the director's act, and it is an attestation: the submission payload carries the `attested_by_title` of the attesting official and, when the list is going in late on purpose, an explicit `late_submission_ack`."

    Design: Corner/rbac/the_analyst_builds_the_list_but_may_neither_attest_nor_review_it
    """
    ctx = _case_with_a_draft_list_built_by_the_analyst()

    resp = api_client.submit_voter_list(
        ctx["voter_list"]["id"], {"attested_by_title": "Manager, HR Analytics"}, caller
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    still_drafting = validate_success(
        api_client.get_voter_list(ctx["voter_list"]["id"], BOARD)
    )
    assert still_drafting["status"] == "DRAFT"


def test_the_analyst_may_cure_an_entry_that_counsel_may_only_read():
    """Curing a voter entry belongs to the analyst who built it; counsel reads entries
    but may not edit them.

    PRD: "An entry may also be updated later — to cure missing statutory content or to correct employment data — and an update accepts `home_address`, `personal_email`, `personal_phone`, `shift_code`, `work_location`, `termination_date` and `on_leave_type`."

    PRD: "A request from a role not listed in the final column is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/the_analyst_builds_the_list_but_may_neither_attest_nor_review_it
    """
    ctx = _case_with_a_draft_list_built_by_the_analyst()
    entry_id = ctx["entries"][0]["id"]

    refused = api_client.update_voter_list_entry(entry_id, {"shift_code": "B"}, COUNSEL)
    allowed = api_client.update_voter_list_entry(entry_id, {"shift_code": "B"}, ANALYST)

    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    assert validate_success(allowed)["shift_code"] == "B"


@pytest.mark.parametrize(
    "caller",
    [DIRECTOR, UNION],
    ids=["director", "union_representative"],
)
def test_disposing_of_a_filed_list_is_refused_to_both_parties(caller):
    """The director who attested the list cannot accept it and the petitioner has no
    role in the review at all; the filed list keeps waiting on the Board.

    PRD: "Board review of a filed list is a `BoardAgent` disposition carrying `disposition` and optional `noted_defects` codes, and the three dispositions have different grade prerequisites."

    Design: Corner/rbac/the_analyst_builds_the_list_but_may_neither_attest_nor_review_it
    """
    ctx = _case_with_a_draft_list_built_by_the_analyst()
    submit_voter_list(ctx["voter_list"]["id"])

    resp = api_client.review_voter_list(
        ctx["voter_list"]["id"], {"disposition": "ACCEPT"}, caller
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    unreviewed = validate_success(
        api_client.get_voter_list(ctx["voter_list"]["id"], BOARD)
    )
    assert unreviewed["status"] == "SUBMITTED"


def test_the_director_attests_the_list_and_the_board_accepts_it():
    """The lifecycle completes only when each act is taken by the role that holds it:
    the director's attestation records their own identity and the Board's acceptance
    closes the list.

    PRD: "On success the list moves to `SUBMITTED`, `submitted_at` is stamped with the logical clock, `submitted_by_user_id` records the attesting director's `X-User-ID`, and the title is stored."

    PRD: "`ACCEPT` moves the list to `ACCEPTED` and is only available when `list_grade` is `COMPLIANT` or `MINOR_DEFECT`; it stamps `reviewed_at` and leaves both `cure_window_hours` and `cure_deadline_at` absent."

    Design: Corner/rbac/the_analyst_builds_the_list_but_may_neither_attest_nor_review_it
    """
    ctx = _case_with_a_draft_list_built_by_the_analyst()

    filed = api_client.submit_voter_list(
        ctx["voter_list"]["id"],
        {"attested_by_title": "Director of Labor Relations"},
        DIRECTOR,
    )
    filed_data = validate_success(filed)
    accepted = api_client.review_voter_list(
        ctx["voter_list"]["id"], {"disposition": "ACCEPT"}, BOARD
    )

    assert filed_data["status"] == "SUBMITTED"
    assert filed_data["submitted_by_user_id"] == "user-director-1"
    assert validate_success(accepted)["status"] == "ACCEPTED"


def test_the_petitioner_may_read_the_list_it_may_not_touch():
    """The union representative is barred from every write on the list yet reads both
    the list and all three of its entries.

    PRD: "**`UnionRepresentative`** — the petitioning labor organization's representative, who may demand a hearing, seat union observers, file objections and unfair labor practice charges, and read the public case record."

    Design: Corner/rbac/the_analyst_builds_the_list_but_may_neither_attest_nor_review_it
    """
    ctx = _case_with_a_draft_list_built_by_the_analyst()

    read = api_client.get_voter_list(ctx["voter_list"]["id"], UNION)
    listed = api_client.list_voter_list_entries(
        UNION, {"voter_list_id": ctx["voter_list"]["id"]}
    )

    assert validate_success(read)["id"] == ctx["voter_list"]["id"]
    rows, meta = validate_paginated(listed)
    assert len(rows) == 3
    assert meta["total_count"] == 3


@pytest.mark.parametrize(
    "caller",
    [ANALYST, TRAINER, COUNSEL],
    ids=["analyst", "trainer", "counsel"],
)
def test_seating_an_observer_admits_no_role_beyond_the_declared_three(caller):
    """Observer designation names exactly three roles, so the analyst, the trainer and
    counsel are all turned away.

    PRD: "Observers are seated one at a time, and three roles may do the seating — the `LaborRelationsDirector` for the employer, the `UnionRepresentative` for the union, and a `BoardAgent` in either capacity."

    Design: Corner/rbac/shared_operations_admit_exactly_the_declared_co_holders_and_no_others
    """
    ctx = _case_with_sessions_and_a_draft_message()

    resp = api_client.designate_observer(
        ctx["sessions"][0]["id"], {"party": "EMPLOYER", "observer_name": "Grace Hall"}, caller
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    seated = validate_success(
        api_client.get_poll_session(ctx["sessions"][0]["id"], BOARD)
    )
    assert seated["employer_observer_count"] == 0


def test_each_declared_co_holder_may_seat_the_observer_it_speaks_for():
    """The employer seats an employer observer, the union seats a union observer, and
    the Board may seat for a party at another session.

    PRD: "A successful designation increments either `employer_observer_count` or `union_observer_count` according to the party, and appends an entry to `observer_roster` recording the party, the observer name and the supervisor identifier, in designation order."

    Design: Corner/rbac/shared_operations_admit_exactly_the_declared_co_holders_and_no_others
    """
    ctx = _case_with_sessions_and_a_draft_message()
    first, second = ctx["sessions"]

    by_employer = api_client.designate_observer(
        first["id"], {"party": "EMPLOYER", "observer_name": "Grace Hall"}, DIRECTOR
    )
    by_union = api_client.designate_observer(
        first["id"], {"party": "UNION", "observer_name": "Ivan Petrov"}, UNION
    )
    by_board = api_client.designate_observer(
        second["id"], {"party": "EMPLOYER", "observer_name": "Jae Kim"}, BOARD
    )

    validate_success(by_employer)
    both_parties = validate_success(by_union)
    assert both_parties["employer_observer_count"] == 1
    assert both_parties["union_observer_count"] == 1
    assert validate_success(by_board)["employer_observer_count"] == 1
    union_read = validate_success(api_client.get_poll_session(first["id"], UNION))
    assert union_read["union_observer_count"] == 1


def test_the_accuracy_pass_is_shared_with_the_analyst_and_closed_to_counsel():
    """The role that later dispositions legal review is excluded from the factual
    accuracy pass, which the analyst shares with the director.

    PRD: "The factual-accuracy review is performed by the director or by an `HRDataAnalyst`, and it is the step that computes the message's risk."

    PRD: "The review stamps `accuracy_reviewed_at` with the logical clock and writes `risk_score` and `peerless_plywood_violation`."

    Design: Corner/rbac/shared_operations_admit_exactly_the_declared_co_holders_and_no_others
    """
    ctx = _case_with_sessions_and_a_draft_message()
    payload = {"material_claim_count": 3, "unsupported_material_claim_count": 0}

    refused = api_client.accuracy_review_communication(ctx["message"]["id"], payload, COUNSEL)
    allowed = api_client.accuracy_review_communication(ctx["message"]["id"], payload, ANALYST)

    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    reviewed = validate_success(allowed)
    assert_instant_equals(reviewed["accuracy_reviewed_at"], FILING_CLOCK)
    assert reviewed["unsupported_material_claim_count"] == 0


@pytest.mark.parametrize(
    "caller",
    [ANALYST, UNION],
    ids=["analyst", "union_representative"],
)
def test_the_single_supervisor_read_is_withheld_from_the_analyst_and_the_union(caller):
    """Sharing is per endpoint rather than per entity: two roles that read almost
    everything else cannot read one supervisor's record.

    PRD: "A request from a role not listed in the final column is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/shared_operations_admit_exactly_the_declared_co_holders_and_no_others
    """
    ctx = _case_with_sessions_and_a_draft_message()

    resp = api_client.get_supervisor(ctx["supervisor"]["id"], caller)

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_the_supervisor_collection_stays_open_to_the_analyst_barred_from_one_row():
    """The same analyst refused the single-supervisor read still lists the case's
    supervisors, and the trainer reads the row itself.

    PRD: "A newly registered supervisor begins at `training_status` `UNTRAINED`, with `modules_completed` and `quiz_score` absent, `training_attempt_count` and `violation_count` at 0, and no `certified_at` or `last_violation_code`."

    Design: Corner/rbac/shared_operations_admit_exactly_the_declared_co_holders_and_no_others
    """
    ctx = _case_with_sessions_and_a_draft_message()

    listed = api_client.list_supervisors(ANALYST, {"petition_id": ctx["petition"]["id"]})
    read = api_client.get_supervisor(ctx["supervisor"]["id"], TRAINER)

    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["supervisor"]["id"]
    assert validate_success(read)["training_status"] == "UNTRAINED"


@pytest.mark.parametrize(
    "payload",
    [
        {"disposition": "APPROVE"},
        {"disposition": "REQUEST_REVISION", "review_note": "Tone down"},
    ],
    ids=["approve", "request_revision"],
)
def test_the_drafting_user_may_not_disposition_the_review_in_another_hat(payload):
    """The identity that drafted the message wearing the director hat is refused when
    the same person returns wearing the counsel hat, whichever disposition they attempt.

    PRD: "A campaign message records the `X-User-ID` of whoever drafted it, and the user who dispositions its legal review may never be that same user — even when both users hold `EmploymentCounsel`."

    PRD: "A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_author_of_a_message_may_never_be_its_legal_reviewer
    """
    ctx = _message_awaiting_legal_review()
    author_as_counsel = build_user_headers(SHARED_USER_ID, "EmploymentCounsel")

    resp = api_client.review_communication(ctx["message"]["id"], payload, author_as_counsel)

    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    untouched = validate_success(
        api_client.get_campaign_communication(ctx["message"]["id"], BOARD)
    )
    assert untouched["status"] == "PENDING_LEGAL_REVIEW"
    assert untouched.get("reviewed_by_user_id") is None
    assert untouched["revision_round"] == 0


def test_the_author_in_the_wrong_role_is_answered_on_authorization_first():
    """The author who tries to review while still wearing the director hat is refused
    for the role, not for the duties they would also have breached.

    PRD: "Checks run in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status:"

    PRD: "2. **Endpoint authorization** — the acting role appears on the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/the_author_of_a_message_may_never_be_its_legal_reviewer
    """
    ctx = _message_awaiting_legal_review()

    resp = api_client.review_communication(
        ctx["message"]["id"], {"disposition": "APPROVE"}, ctx["author_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_a_second_counsel_who_did_not_draft_the_message_may_approve_it():
    """Clearance arrives only from a genuinely different user identity, and approval
    records that reviewer while the recorded author stands.

    PRD: "Role membership alone therefore does not authorize a review; the acting user identity must differ from the recorded author."

    PRD: "A disposition of `APPROVE` moves the message to `APPROVED` and records the acting user in `reviewed_by_user_id`; it additionally requires `peerless_plywood_violation` to be false and the escalation acknowledgement described above when the score is elevated."

    Design: Corner/rbac/the_author_of_a_message_may_never_be_its_legal_reviewer
    """
    ctx = _message_awaiting_legal_review()

    resp = api_client.review_communication(
        ctx["message"]["id"], {"disposition": "APPROVE"}, COUNSEL_TWO
    )

    approved = validate_success(resp)
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "user-counsel-2"
    assert approved["authored_by_user_id"] == SHARED_USER_ID


def _read_a_colleagues_record(headers, colleague_id, _petition_id, _message_id):
    return api_client.get_supervisor(colleague_id, headers)


def _list_a_colleagues_assignments(headers, colleague_id, _petition_id, _message_id):
    return api_client.list_campaign_communications(
        headers, {"presenter_supervisor_id": colleague_id}
    )


@pytest.mark.parametrize(
    "probe",
    [_read_a_colleagues_record, _list_a_colleagues_assignments],
    ids=["supervisor_record", "presenter_filtered_messages"],
)
def test_a_supervisor_reaching_past_their_own_identity_is_a_mismatch(probe):
    """The supervisor's X-User-ID is the row they are, so addressing a colleague's
    record or filtering messages to a colleague's presenter id is refused.

    PRD: "A `PlantSupervisor` reading a single supervisor record may only address their own row, and a `PlantSupervisor` listing campaign messages must filter to `presenter_supervisor_id` equal to their own `X-User-ID`; addressing another supervisor's row, or filtering by a presenter identifier that is not their own, is rejected with `ERR_SUPERVISOR_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/a_supervisor_sees_only_their_own_record_and_their_own_assignments
    """
    ctx = _case_with_two_supervisors_and_a_meeting_message()
    acting = make_plant_supervisor_headers(ctx["trained"]["id"])

    resp = probe(acting, ctx["untrained"]["id"], ctx["petition"]["id"], ctx["message"]["id"])

    validate_error(resp, ApiErrorId.ERR_SUPERVISOR_IDENTITY_MISMATCH)


def test_a_supervisor_reads_their_own_record_and_their_own_assignments():
    """The same two reads succeed for the supervisor whose identity they address: their
    training record and the single meeting they are scheduled to present.

    PRD: "When `X-User-Role` is `PlantSupervisor`, `X-User-ID` is the `id` of the acting `Supervisor` row."

    PRD: "A qualifying attempt increments `training_attempt_count`, records the score and the modules, stamps `certified_at` with the logical clock, and moves `training_status` from `UNTRAINED` to `TRAINED`."

    Design: Corner/rbac/a_supervisor_sees_only_their_own_record_and_their_own_assignments
    """
    ctx = _case_with_two_supervisors_and_a_meeting_message()
    acting = make_plant_supervisor_headers(ctx["trained"]["id"])

    own_record = api_client.get_supervisor(ctx["trained"]["id"], acting)
    own_assignments = api_client.list_campaign_communications(
        acting, {"presenter_supervisor_id": ctx["trained"]["id"]}
    )

    record = validate_success(own_record)
    assert record["training_status"] == "TRAINED"
    assert record["quiz_score"] == 88
    rows, meta = validate_paginated(own_assignments)
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [ctx["message"]["id"]]


def _read_one_message(ctx, headers):
    return api_client.get_campaign_communication(ctx["message"]["id"], headers)


def _list_the_whole_supervisor_roster(ctx, headers):
    return api_client.list_supervisors(headers, {"petition_id": ctx["petition"]["id"]})


def _record_a_training_attempt(ctx, headers):
    return api_client.train_supervisor(
        ctx["trained"]["id"],
        {
            "modules_completed": ["TIPS_BOUNDARIES", "PROHIBITED_CONDUCT", "SOLICITATION_RULES"],
            "quiz_score": 88,
        },
        headers,
    )


@pytest.mark.parametrize(
    "probe",
    [_read_one_message, _list_the_whole_supervisor_roster, _record_a_training_attempt],
    ids=["single_message_read", "supervisor_collection_read", "training_write"],
)
def test_the_supervisor_is_turned_away_from_endpoints_that_never_name_the_role(probe):
    """Where the role is simply absent from the endpoint the answer is the
    authorization error rather than the identity error, even for the supervisor's own
    training row.

    PRD: "Checks run in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status:"

    PRD: "2. **Endpoint authorization** — the acting role appears on the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/a_supervisor_sees_only_their_own_record_and_their_own_assignments
    """
    ctx = _case_with_two_supervisors_and_a_meeting_message()
    acting = make_plant_supervisor_headers(ctx["trained"]["id"])

    resp = probe(ctx, acting)

    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_the_colleagues_own_read_of_the_row_that_was_refused_succeeds():
    """The identical path is a refusal for one supervisor and a success for the
    supervisor it belongs to, while counsel reads either row.

    PRD: "**`PlantSupervisor`** — a front-line supervisor acting as themselves, with read access to their own training record and to the campaign messages they are scheduled to present."

    PRD: "A `SupervisorTrainer` or a `LaborRelationsDirector` registers a supervisor against a case with a payload naming the `petition_id`, the supervisor's `full_name` and `job_title`, the `span_of_control` giving how many unit employees report to them, and `has_hire_fire_authority` recording whether they hold Section 2(11) hire-and-fire authority, which defaults to false."

    Design: Corner/rbac/a_supervisor_sees_only_their_own_record_and_their_own_assignments
    """
    ctx = _case_with_two_supervisors_and_a_meeting_message()
    colleague = ctx["untrained"]

    own = api_client.get_supervisor(
        colleague["id"], make_plant_supervisor_headers(colleague["id"])
    )
    by_counsel = api_client.get_supervisor(colleague["id"], COUNSEL)

    assert validate_success(own)["id"] == colleague["id"]
    assert validate_success(by_counsel)["has_hire_fire_authority"] is True


@pytest.mark.parametrize(
    "headers",
    [
        {"X-User-ID": "user-director-1", "Content-Type": "application/json"},
        {"X-User-Role": "LaborRelationsDirector", "Content-Type": "application/json"},
        build_user_headers("user-clerk-1", "PayrollClerk"),
    ],
    ids=["no_role_header", "no_user_id_header", "unrecognised_role"],
)
def test_an_absent_or_unknown_role_header_is_unauthenticated(headers):
    """A missing header of either kind, and a syntactically valid role that the system
    does not declare, are all rejected as unauthenticated rather than as forbidden.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/a_missing_or_unrecognised_role_header_is_401_before_anything_else
    """
    _docketed_case()

    resp = api_client.raw_get("/labor-relations/petitions", headers)

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_header_authentication_answers_before_the_body_is_examined():
    """A create whose body is missing every required field but one still answers on the
    headers, and the very same body answers on the schema once the headers are present.

    PRD: "This check precedes everything else, including the existence of the resource addressed by the path."

    PRD: "**Request schema** — the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset."

    Design: Corner/rbac/a_missing_or_unrecognised_role_header_is_401_before_anything_else
    """
    _docketed_case()
    partial_body = {"case_number": "07-RC-340607"}

    unauthenticated = api_client.raw_post(
        "/labor-relations/petitions",
        partial_body,
        {"X-User-ID": "user-director-1", "Content-Type": "application/json"},
    )
    malformed = api_client.create_petition(partial_body, DIRECTOR)

    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED)
    validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_petitions(DIRECTOR))
    assert meta["total_count"] == 1


def test_the_trainers_declared_reads_stop_short_of_the_voter_list():
    """Once the headers are accepted the answer turns on the endpoint's own role list:
    the trainer reads petitions but not voter lists.

    PRD: "2. **Endpoint authorization** — the acting role appears on the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    PRD: "A request from a role not listed in the final column is refused with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/a_missing_or_unrecognised_role_header_is_401_before_anything_else
    """
    petition = _docketed_case()

    refused = api_client.list_voter_lists(TRAINER, {"petition_id": petition["id"]})
    allowed = api_client.list_petitions(TRAINER)

    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    rows, meta = validate_paginated(allowed)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == petition["id"]


def test_the_pagination_floor_is_a_schema_failure_and_the_defaults_hold():
    """A page size of zero is refused rather than clamped, and a request naming no
    pagination at all is served with the declared defaults.

    PRD: "`limit` controls page size: it defaults to 10, may not be lower than 1, and may not exceed 100."

    PRD: "A `limit` outside the 1-to-100 range, or a negative `offset`, is a schema failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 422) rather than being silently clamped."

    Design: Corner/rbac/a_missing_or_unrecognised_role_header_is_401_before_anything_else
    """
    _docketed_case()

    refused = api_client.list_petitions(DIRECTOR, {"limit": 0})
    defaulted = api_client.list_petitions(DIRECTOR)

    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(defaulted)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
