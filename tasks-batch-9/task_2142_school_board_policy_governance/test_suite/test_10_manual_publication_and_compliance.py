"""Publishing the manual, the legal update feed and the governance compliance sweep."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjourn_meeting,
    api_client,
    assert_instant_equals,
    assert_manual_publication,
    charter_committee,
    draft_version,
    file_disclosure,
    file_mandate,
    legal_mandate_payload,
    manual_publication_payload,
    publish_edition,
    read_board_member,
    read_committee,
    read_disclosure,
    read_edition,
    read_mandate,
    read_policy,
    read_policy_version,
    register_policy,
    run_sweep,
    seat_board,
    seat_on_committee,
    set_clock,
    setup_active_committee,
    setup_emergency_adoption,
    setup_policy_with_draft,
    start_edition,
    superintendent_evaluation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["policy_analyst_headers"]
LUS = TEST_USERS["legal_update_service_headers"]
CLERK = TEST_USERS["board_clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]


def _emergency_adopted_policy(code="BP-4119", section="4000.19"):
    members = seat_board(3)
    policy, version = setup_policy_with_draft(code=code, manual_section=section)
    meeting, item = setup_emergency_adoption(members, version["id"])
    return members, policy, version, meeting


def test_publishing_a_second_edition_supersedes_the_first():
    """PRD 3.9: "Every other edition already in `PUBLISHED` status moves to `SUPERSEDED`
    with `superseded_by_label` set to this edition's `publication_label`, keeping its own
    `pinned_entries` verbatim as the historical record of what the manual said at that time."
    PRD 3.9: "Those entries become `pinned_entries`, `entry_count` becomes their number,
    `compliance_gap_count` becomes the number of entries whose policy's `compliance_state`
    is anything other than `COMPLIANT`, `certification_state` becomes `CERTIFIED` when that
    gap count is zero and `LAPSED` otherwise, `published_at` is stamped from the logical
    clock, and the edition moves `BUILDING → PUBLISHED`."

    Design: Corner/state_machines/publishing_a_second_edition_supersedes_the_first
    """
    _members, policy, _version, _meeting = _emergency_adopted_policy()
    first = start_edition("2026-FALL", "2026-08-02T18:00:00Z")
    publish_edition(first["id"])
    second = start_edition("2027-SPRING", "2026-08-03T00:00:00Z")

    published = validate_success(api_client.publish_manual_publication(second["id"], ANALYST), 200)
    assert_manual_publication(published)
    assert published["status"] == "PUBLISHED"
    assert published["entry_count"] == 1
    assert published["compliance_gap_count"] == 0
    assert published["certification_state"] == "CERTIFIED"
    assert published["superseded_by_label"] is None

    older = read_edition(first["id"])
    assert older["status"] == "SUPERSEDED"
    assert older["superseded_by_label"] == "2027-SPRING"
    assert older["entry_count"] == 1
    assert older["pinned_entries"][0]["version_no"] == 1


def test_the_snapshot_orders_entries_by_manual_section_then_code():
    """PRD 3.9: "The entries are ordered by ascending `manual_section` and, within an equal
    section, by ascending `code`, both compared lexicographically with case sensitivity, and
    a policy's `id` never participates in the ordering. Each entry is an object recording the
    policy's identifier under `policy_id`, its `code` under `policy_code`, the
    `adopted_version_no` current at that instant under `version_no`, and its `manual_section`."
    PRD 3.7: "`effective_date` equals `adopted_at` exactly, with no delay, because an
    emergency adoption takes force immediately."

    Design: Corner/calculations/manual_snapshot_orders_entries_by_manual_section_then_code
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    from test_helpers import (
        add_agenda_item,
        open_meeting,
        post_notice,
        record_vote,
        schedule_meeting,
    )

    first_policy, first_version = setup_policy_with_draft(
        "BP-1000", "Board Bylaws", "GOVERNANCE", "LOCAL_DISCRETION", "1000.10",
        body_text="Bylaws text.", summary_of_change="Initial draft",
    )
    second_policy, second_version = setup_policy_with_draft(
        "BP-0900", "Board Mission", "GOVERNANCE", "LOCAL_DISCRETION", "0900.10",
        body_text="Mission text.", summary_of_change="Initial draft",
    )
    meeting = schedule_meeting(
        title="Emergency Board Meeting",
        meeting_type="EMERGENCY",
        scheduled_start_utc="2026-08-02T18:00:00Z",
    )
    first_item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="POLICY_FIRST_READING",
        title="Emergency first reading BP-1000",
        policy_version_id=first_version["id"],
    )
    second_item = add_agenda_item(
        meeting["id"],
        first_item["meeting_version_after"],
        item_type="POLICY_FIRST_READING",
        title="Emergency first reading BP-0900",
        policy_version_id=second_version["id"],
    )
    post_notice(meeting["id"])
    set_clock("2026-08-02T18:00:00Z")
    open_meeting(meeting["id"], ids, ids[0])
    record_vote(first_item["id"], ids[0], yes_member_ids=ids)
    record_vote(second_item["id"], ids[0], yes_member_ids=ids)

    edition = start_edition("2026-FALL", "2026-08-02T18:00:00Z")
    published = publish_edition(edition["id"])

    assert published["entry_count"] == 2
    assert published["pinned_entries"][0]["policy_code"] == "BP-0900"
    assert published["pinned_entries"][0]["manual_section"] == "0900.10"
    assert published["pinned_entries"][0]["version_no"] == 1
    assert published["pinned_entries"][1]["policy_code"] == "BP-1000"
    assert published["compliance_gap_count"] == 0
    assert published["certification_state"] == "CERTIFIED"
    assert_instant_equals(
        read_policy_version(first_version["id"])["effective_date"],
        "2026-08-02T18:00:00Z",
        "PolicyVersion.effective_date",
    )


def test_an_edition_with_nothing_adopted_cannot_be_published():
    """PRD 3.9: "Publishing freezes a snapshot. It is permitted only on an edition whose
    `status` is `BUILDING` — otherwise `ERR_PUBLICATION_ALREADY_PUBLISHED` — and only when
    at least one policy has `status` `ADOPTED`, otherwise `ERR_NO_ADOPTED_POLICIES`."
    PRD 3.9: "The edition opens `BUILDING` with `certification_state` `PENDING`,
    `pinned_entries` an empty array, `entry_count` and `compliance_gap_count` 0, and
    `published_at` and `superseded_by_label` null."

    Design: Corner/validations/publishing_with_no_adopted_policies_returns_no_adopted_policies
    """
    register_policy()
    edition = start_edition("2026-FALL", "2026-08-01T00:00:00Z")

    response = api_client.publish_manual_publication(edition["id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_NO_ADOPTED_POLICIES.value)
    assert response.status_code == 422

    row = read_edition(edition["id"])
    assert row["status"] == "BUILDING"
    assert row["certification_state"] == "PENDING"
    assert row["entry_count"] == 0


def test_publishing_an_already_published_edition_is_refused():
    """PRD 3.9: "Publishing freezes a snapshot. It is permitted only on an edition whose
    `status` is `BUILDING` — otherwise `ERR_PUBLICATION_ALREADY_PUBLISHED` — and only when
    at least one policy has `status` `ADOPTED`, otherwise `ERR_NO_ADOPTED_POLICIES`."

    Design: Corner/errors/publishing_an_already_published_edition_returns_already_published
    """
    _members, policy, _version, _meeting = _emergency_adopted_policy()
    edition = start_edition("2026-FALL", "2026-08-02T18:00:00Z")
    publish_edition(edition["id"])
    set_clock("2026-08-09T00:00:00Z")

    response = api_client.publish_manual_publication(edition["id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_PUBLICATION_ALREADY_PUBLISHED.value)
    assert response.status_code == 409

    row = read_edition(edition["id"])
    assert_instant_equals(
        row["published_at"], "2026-08-02T18:00:00Z", "ManualPublication.published_at"
    )
    assert row["status"] == "PUBLISHED"
    assert row["entry_count"] == 1


def test_an_open_mandate_moves_the_policy_to_action_required_without_going_overdue():
    """PRD 3.3: "A filed mandate opens `OPEN` with `satisfied_by_version_no` null and
    `days_past_deadline` 0, and its arrival immediately drives the policy-scoped recompute
    so that the target policy's `open_mandate_count` and `compliance_state` are correct the
    moment the notice lands."
    PRD 2.9: "`open_mandate_count` becomes the number of that policy's mandates in `OPEN` or
    `IN_PROGRESS`; `overdue_mandate_count` becomes the number in `OVERDUE`;
    `active_waiver_count` becomes the number of that policy's waiver requests in `GRANTED`
    whose `granted_end_date` is strictly after the logical clock."

    Design: Corner/calculations/open_legal_mandate_moves_policy_to_action_required_without_going_overdue
    """
    policy = register_policy(
        "BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10"
    )
    response = api_client.create_legal_mandate(
        legal_mandate_payload(
            policy["id"],
            notice_code="LUS-2026-030",
            citation="GC 54954",
            issued_on="2026-08-01T00:00:00Z",
            compliance_deadline="2026-12-01T00:00:00Z",
            required_action="ADOPT_NEW",
        ),
        LUS,
    )
    mandate = validate_success(response, 201)
    assert mandate["status"] == "OPEN"
    assert mandate["days_past_deadline"] == 0
    assert mandate["satisfied_by_version_no"] is None

    policy_row = read_policy(policy["id"])
    assert policy_row["open_mandate_count"] == 1
    assert policy_row["overdue_mandate_count"] == 0
    assert policy_row["compliance_state"] == "ACTION_REQUIRED"


def test_drafting_a_version_moves_every_open_mandate_to_in_progress():
    """PRD 3.3: "Drafting also moves the legal record: every legal mandate on that policy
    whose `status` is `OPEN` transitions to `IN_PROGRESS`, signalling that the board has
    started work. That transition changes nothing in `open_mandate_count`, because `OPEN`
    and `IN_PROGRESS` both count as open."

    Design: Corner/calculations/drafting_a_version_moves_open_mandates_to_in_progress
    """
    policy = register_policy(
        "BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10"
    )
    mandate = file_mandate(
        policy["id"],
        notice_code="LUS-2026-030",
        citation="GC 54954",
        issued_on="2026-08-01T00:00:00Z",
        compliance_deadline="2026-12-01T00:00:00Z",
        required_action="ADOPT_NEW",
    )
    refreshed = read_policy(policy["id"])
    version = draft_version(
        policy["id"],
        refreshed["version"],
        body_text="First draft responding to LUS-2026-030.",
        summary_of_change="Respond to mandate",
    )

    assert read_mandate(mandate["id"])["status"] == "IN_PROGRESS"
    policy_row = read_policy(policy["id"])
    assert policy_row["open_mandate_count"] == 1
    assert policy_row["overdue_mandate_count"] == 0
    assert policy_row["compliance_state"] == "ACTION_REQUIRED"
    assert read_policy_version(version["id"])["status"] == "DRAFT"


def test_term_expiry_removes_committee_seats_but_leaves_the_disclosure_standing():
    """PRD 3.9: "and expires every trustee whose `status` is `SEATED` and whose
    `term_end_date` the clock has reached or passed, taking them `SEATED → TERM_EXPIRED`,
    moving every committee seat they hold in `ACTIVE` or `RECUSED` status to `REMOVED`, and
    letting each affected committee recompute its seat counters and posture — while
    pointedly leaving their `RECUSAL_REQUIRED` disclosures alone."
    PRD 3.2: "Note the deliberate asymmetry between the two ways a trustee can leave the
    board. A resignation clears that trustee's `RECUSAL_REQUIRED` disclosures; a term expiry
    does not, because an expired term does not retroactively dissolve a disclosed interest."

    Design: Corner/state_machines/term_expiry_sweep_removes_seats_but_leaves_disclosures_standing
    """
    members = seat_board(3, term_end_dates=[None, "2026-08-05T00:00:00Z", None])
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-3312", "Purchasing", "BUSINESS", "RECOMMENDED", "3000.12")
    disclosure = file_disclosure(
        members[1]["id"], policy["id"], "FINANCIAL", "Family firm bids on district contracts."
    )
    set_clock("2026-08-06T00:00:00Z")

    result = validate_success(api_client.run_compliance_sweep(CLERK), 200)
    assert result["members_term_expired"] == 1

    assert read_board_member(members[1]["id"])["status"] == "TERM_EXPIRED"
    chair_seat = validate_success(
        api_client.get_committee_assignment(committee_setup["chair_assignment"]["id"], CLERK), 200
    )
    assert chair_seat["status"] == "REMOVED"

    committee = read_committee(committee_setup["committee"]["id"])
    assert committee["status"] == "INQUORATE"
    assert committee["filled_seat_count"] == 1
    assert committee["vacant_seat_count"] == 2

    assert read_disclosure(disclosure["id"])["status"] == "RECUSAL_REQUIRED"
    assert read_board_member(members[1]["id"])["open_recusal_count"] == 1
    assert read_board_member(members[0]["id"])["status"] == "SEATED"


def test_a_sweep_with_nothing_to_do_still_answers_with_five_counters():
    """PRD 3.9: "The sweep answers with five counters, and their semantics differ in a way
    worth stating precisely. `mandates_marked_overdue` counts the mandates **this** sweep
    moved into `OVERDUE`. `waivers_expired` counts the waivers this sweep moved into
    `EXPIRED`. `members_term_expired` counts the trustees this sweep moved into
    `TERM_EXPIRED`. `policies_recomputed` counts every policy whose phase-2 block ran, which
    is all of them. `publications_lapsed`, uniquely, is not a delta: it counts every
    `PUBLISHED` edition whose `certification_state` is `LAPSED` **after** the sweep finishes,
    whether or not this sweep is what flipped it."

    Design: Corner/endpoints/compliance_sweep_on_an_empty_board_returns_all_zero_counters
    """
    policy = register_policy(
        "BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10"
    )
    result = validate_success(api_client.run_compliance_sweep(LUS), 200)

    assert result["mandates_marked_overdue"] == 0
    assert result["waivers_expired"] == 0
    assert result["members_term_expired"] == 0
    assert result["policies_recomputed"] == 1
    assert result["publications_lapsed"] == 0
    assert read_policy(policy["id"])["compliance_state"] == "COMPLIANT"


def test_a_repeated_sweep_at_the_same_clock_reports_no_new_transitions():
    """PRD 3.9: "`mandates_marked_overdue` counts the mandates **this** sweep moved into
    `OVERDUE`."
    PRD 2.9: "*Phase 1 — mandate refresh.* For each legal mandate on the policy: if the
    mandate is `OPEN` or `IN_PROGRESS` and the logical clock has reached or passed its
    `compliance_deadline`, it becomes `OVERDUE`. Then `days_past_deadline` is set — to 0 if
    the mandate is `SATISFIED`; otherwise, if the clock is at or past the deadline, to the
    whole number of days between the deadline and the clock; otherwise to 0."

    Design: Corner/cross_cutting_complexity_layers/repeating_the_sweep_at_the_same_clock_position_reports_no_new_transitions
    """
    policy = register_policy(
        "BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10"
    )
    mandate = file_mandate(
        policy["id"],
        notice_code="LUS-2026-030",
        citation="GC 54954",
        issued_on="2026-08-01T00:00:00Z",
        compliance_deadline="2026-08-10T00:00:00Z",
        required_action="ADOPT_NEW",
    )
    set_clock("2026-08-11T00:00:00Z")

    first = validate_success(api_client.run_compliance_sweep(CLERK), 200)
    assert first["mandates_marked_overdue"] == 1

    second = validate_success(api_client.run_compliance_sweep(CLERK), 200)
    assert second["mandates_marked_overdue"] == 0
    assert second["policies_recomputed"] == 1

    mandate_row = read_mandate(mandate["id"])
    assert mandate_row["status"] == "OVERDUE"
    assert mandate_row["days_past_deadline"] == 1
    policy_row = read_policy(policy["id"])
    assert policy_row["overdue_mandate_count"] == 1
    assert policy_row["compliance_state"] == "NON_COMPLIANT"


def test_three_independent_uniqueness_scopes_each_raise_their_own_conflict():
    """PRD 3.3: "Each notice carries a globally unique `notice_code` such as `LUS-2026-014`
    — a repeat is refused with `ERR_DUPLICATE_NOTICE_CODE` — the `policy_id` it targets, the
    statutory `citation` it rests on, the `issued_on` instant the service published it, the
    `compliance_deadline` by which the board must act, and the `required_action` it compels,
    which is one of `ADOPT_NEW`, `REVISE_EXISTING` and `RESCIND`."
    PRD 3.9: "An analyst starts a new edition with a `publication_label` such as
    `2026-FALL`, globally unique across all editions and otherwise refused with
    `ERR_DUPLICATE_PUBLICATION_LABEL`, and an `as_of_date` stating the instant the edition
    claims to describe."
    PRD 3.9: "A cycle is opened by the clerk and carries a `cycle_year` between 2020 and
    2100 that must be unique across all cycles — a repeat is refused with
    `ERR_DUPLICATE_EVALUATION_CYCLE`"

    Design: Corner/errors/duplicate_notice_code_publication_label_and_cycle_year_each_conflict
    """
    policy = register_policy(
        "BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10"
    )
    file_mandate(
        policy["id"],
        notice_code="LUS-2026-030",
        citation="GC 54954",
        issued_on="2026-08-01T00:00:00Z",
        compliance_deadline="2026-12-01T00:00:00Z",
        required_action="ADOPT_NEW",
    )
    start_edition("2026-FALL", "2026-08-01T00:00:00Z")
    validate_success(
        api_client.create_superintendent_evaluation(
            superintendent_evaluation_payload(cycle_year=2027), CLERK
        ),
        201,
    )

    notice_clash = api_client.create_legal_mandate(
        legal_mandate_payload(
            policy["id"],
            notice_code="LUS-2026-030",
            citation="GC 54960",
            issued_on="2026-08-01T00:00:00Z",
            compliance_deadline="2026-12-15T00:00:00Z",
            required_action="REVISE_EXISTING",
        ),
        LUS,
    )
    validate_error(notice_clash, ApiErrorId.ERR_DUPLICATE_NOTICE_CODE.value)
    assert notice_clash.status_code == 409

    label_clash = api_client.create_manual_publication(
        manual_publication_payload(publication_label="2026-FALL", as_of_date="2026-08-05T00:00:00Z"),
        ANALYST,
    )
    validate_error(label_clash, ApiErrorId.ERR_DUPLICATE_PUBLICATION_LABEL.value)
    assert label_clash.status_code == 409

    cycle_clash = api_client.create_superintendent_evaluation(
        superintendent_evaluation_payload(
            cycle_year=2027,
            window_start_date="2026-09-01T00:00:00Z",
            window_end_date="2027-07-31T00:00:00Z",
            midyear_checkpoint_date="2027-02-15T00:00:00Z",
            goal_count=3,
            weight_instructional=0.25,
            weight_fiscal=0.25,
            weight_community=0.25,
            weight_governance=0.25,
        ),
        CLERK,
    )
    validate_error(cycle_clash, ApiErrorId.ERR_DUPLICATE_EVALUATION_CYCLE.value)
    assert cycle_clash.status_code == 409

    _rows, meta = validate_paginated(
        api_client.list_legal_mandates(LUS, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1


def _phase_order_scenario():
    """A CERTIFIED edition pinning a COMPLIANT policy, then a mandate whose deadline the
    clock has just passed."""
    members = seat_board(3)
    policy, version = setup_policy_with_draft()
    setup_emergency_adoption(members, version["id"])
    edition = start_edition("2026-FALL", "2026-08-02T18:00:00Z")
    publish_edition(edition["id"])

    mandate = file_mandate(
        policy["id"],
        notice_code="LUS-2026-014",
        citation="EC 35291",
        issued_on="2026-08-02T18:00:00Z",
        compliance_deadline="2026-08-10T00:00:00Z",
        required_action="REVISE_EXISTING",
    )
    set_clock("2026-08-11T00:00:00Z")
    result = validate_success(api_client.run_compliance_sweep(CLERK), 200)
    return policy, mandate, edition, result


def test_the_sweep_marks_the_mandate_overdue_and_recomputes_the_policy_posture():
    """PRD 2.9: "*Phase 1 — mandate refresh.* For each legal mandate on the policy: if the
    mandate is `OPEN` or `IN_PROGRESS` and the logical clock has reached or passed its
    `compliance_deadline`, it becomes `OVERDUE`. Then `days_past_deadline` is set — to 0 if
    the mandate is `SATISFIED`; otherwise, if the clock is at or past the deadline, to the
    whole number of days between the deadline and the clock; otherwise to 0."
    PRD 3.9: "A mandate that becomes `OVERDUE` drives a three-hop cascade of its own:
    `days_past_deadline` is recomputed, the policy's `overdue_mandate_count` is recomputed
    and its `compliance_state` becomes `NON_COMPLIANT`, and every `PUBLISHED` edition
    pinning that policy recomputes `compliance_gap_count` and flips `certification_state`
    from `CERTIFIED` to `LAPSED`."

    Design: Difficulty/combinatorial_formula/compliance_phase_order_publication_recertification
    """
    policy, mandate, edition, result = _phase_order_scenario()

    mandate_row = read_mandate(mandate["id"])
    assert mandate_row["status"] == "OVERDUE"
    assert mandate_row["days_past_deadline"] == 1

    policy_row = read_policy(policy["id"])
    assert policy_row["overdue_mandate_count"] == 1
    assert policy_row["compliance_state"] == "NON_COMPLIANT"
    assert result["mandates_marked_overdue"] == 1


def test_phase_three_lapses_the_published_edition_that_pinned_the_policy():
    """PRD 2.9: "*Phase 3 — publication reconciliation, reading only phase-2 output.* For
    every manual edition in `PUBLISHED` whose pinned entries include this policy,
    `compliance_gap_count` becomes the number of its pinned entries whose policy's
    `compliance_state` is anything other than `COMPLIANT`, and `certification_state` becomes
    `CERTIFIED` when that count is zero and `LAPSED` otherwise."
    PRD 3.9: "`publications_lapsed`, uniquely, is not a delta: it counts every `PUBLISHED`
    edition whose `certification_state` is `LAPSED` **after** the sweep finishes, whether or
    not this sweep is what flipped it."

    Design: Difficulty/combinatorial_formula/compliance_phase_order_publication_recertification
    """
    policy, mandate, edition, result = _phase_order_scenario()

    edition_row = read_edition(edition["id"])
    assert edition_row["compliance_gap_count"] == 1
    assert edition_row["certification_state"] == "LAPSED"
    assert edition_row["pinned_entries"][0]["version_no"] == 1
    assert edition_row["entry_count"] == 1
    assert result["publications_lapsed"] == 1
