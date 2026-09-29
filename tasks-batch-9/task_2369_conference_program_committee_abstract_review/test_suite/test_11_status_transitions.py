"""Status movement across the program pipeline, legal and illegal.

Eight postures of the pipeline's state machines are exercised here:

* **opening the call for abstracts** — a draft conference with a category on file
  and the clock still short of the submission cut-off moves into an open call,
  and the opening is not a deadline extension;
* **the invited-member starting posture** — a freshly recruited reviewer or chair
  begins invited, with a pending conflict posture, an empty load ledger and the
  declared load and calibration defaults;
* **illegal phase jumps** — the conference lifecycle is a chain, so a request
  that skips several phases at once is a state failure that writes nothing;
* **withdrawal being terminal** — a withdrawn abstract cannot be resurrected by a
  confirmation, even with the author registered and decisions already out;
* **a second decline on one review** — declining is not idempotent, and the
  second attempt must not move the reviewer's load ledger a second time;
* **activation without a conflict declaration** — the one precondition on
  becoming active, and the fact that its side effect cannot fire on a rejection;
* **slot creation updating the session ledger** — one placement writes the slot,
  the abstract and four derived places on the session at once;
* **an early embargo release** — a release posted before the embargo instant is
  a legal move with a punitive landing that reaches the author's sanction ladder.
"""

from test_helpers import (
    ADMIN,
    PRESS,
    api_client,
    create_committee_member_payload,
    create_conference,
    create_category,
    create_session,
    create_session_slot_payload,
    decline_review_as,
    decline_review_payload,
    get_success_data,
    make_reviewer_headers,
    member_of,
    open_call_for_abstracts,
    open_review_phase,
    press_action_payload,
    refresh_conference,
    register_author,
    release_decisions,
    set_clock,
    setup_conference_with_committee,
    setup_confirmed_abstract,
    setup_decided_abstract,
    setup_embargoed_abstract,
    status_transition_payload,
    submit_abstract,
    validate_error,
    validate_success,
    assign_review,
)

ORIGINAL_ABSTRACT_DEADLINE = "2026-03-01T23:59:00Z"
EMBARGO_INSTANT = "2026-08-20T00:00:00Z"
OUTLET = "Northline Daily"
FIRST_DECLINE_REASON = "outside my subspecialty"


# ─── Opening the call for abstracts ──────────────────────────────────────


def _draft_conference_with_one_category() -> dict:
    """A DRAFT conference carrying one category, clock before the cut-off."""
    set_clock("2026-01-05T00:00:00Z")
    conference = create_conference()
    create_category(conference["id"])
    return conference


def test_opening_the_call_moves_a_draft_conference_to_cfa_open():
    """The conference lifecycle runs `DRAFT` → `CFA_OPEN` → `CFA_CLOSED` →
    `REVIEW_OPEN` → `REVIEW_CLOSED` → `DECISIONS_RELEASED` → `PROGRAM_PUBLISHED`,
    and every move is driven by operations staff naming a `to_status`. Opening the
    call — `DRAFT` to `CFA_OPEN` — requires that at least one category exist for
    this conference and that the logical clock still be earlier than
    `abstract_deadline_utc`.

    All resources except conflict declarations additionally carry:
    - `updated_at` — an ISO 8601 UTC timestamp with three fractional digits,
      refreshed on every mutation of the row, including mutations that only touch
      derived counters.
    - `version` — an integer that starts at 1 on creation and increases by exactly
      one on every mutation of that row.

    Design: Corner/state_machines/conference_draft_to_cfa_open_opens_the_call_for_abstracts
    """
    conference = _draft_conference_with_one_category()
    assert conference["status"] == "DRAFT"
    version_before = conference["version"]

    res = api_client.transition_conference(
        conference["id"], status_transition_payload("CFA_OPEN"), ADMIN
    )
    opened = validate_success(res)

    assert opened["status"] == "CFA_OPEN"
    assert opened["version"] == version_before + 1


def test_opening_the_call_is_not_a_deadline_extension():
    """Opening the call — `DRAFT` to `CFA_OPEN` — requires that at least one
    category exist for this conference and that the logical clock still be earlier
    than `abstract_deadline_utc`.

    A newly created conference starts in `DRAFT`, with `accepted_oral_count`,
    `accepted_poster_count`, `accepted_workshop_count`, `waitlisted_count`,
    `cme_minutes_allocated`, `cfa_extension_count`, `review_reopen_count` and
    `abstract_sequence` all at zero, and `cme_minutes_available` equal to
    `cme_minutes_pool_total`.

    On success the conference's `abstract_deadline_utc` is replaced by that
    instant, `cfa_extension_count` rises to one, and `version` advances.

    Design: Corner/state_machines/conference_draft_to_cfa_open_opens_the_call_for_abstracts
    """
    conference = _draft_conference_with_one_category()
    assert conference["cfa_extension_count"] == 0

    opened = validate_success(
        api_client.transition_conference(
            conference["id"], status_transition_payload("CFA_OPEN"), ADMIN
        )
    )

    assert opened["cfa_extension_count"] == 0
    assert opened["abstract_deadline_utc"] == ORIGINAL_ABSTRACT_DEADLINE


# ─── The invited-member starting posture ─────────────────────────────────


def _recruit_reviewer_payload(conference_id: str) -> dict:
    """A recruitment payload that omits both tunable optional inputs."""
    payload = create_committee_member_payload(
        conference_id,
        member_role="REVIEWER",
        full_name="Rui Alvarez",
        email="rui@panel.example",
        expertise_keywords=["oncology", "imaging"],
    )
    payload.pop("max_review_load")
    payload.pop("calibration_bias")
    return payload


def test_recruited_member_starts_invited_with_a_pending_conflict_posture():
    """A new member starts with `status` `INVITED`, `coi_declaration_status`
    `PENDING`, `current_review_load` zero and `chaired_session_count` zero.

    Design: Corner/state_machines/committee_member_starts_invited_with_a_pending_coi_and_zero_load
    """
    set_clock("2026-01-05T00:00:00Z")
    conference = create_conference()

    res = api_client.create_committee_member(
        _recruit_reviewer_payload(conference["id"]), ADMIN
    )
    member = validate_success(res, 201)

    assert member["status"] == "INVITED"
    assert member["coi_declaration_status"] == "PENDING"
    assert member["current_review_load"] == 0
    assert member["chaired_session_count"] == 0


def test_recruited_member_takes_the_declared_load_and_calibration_defaults():
    """Two optional inputs tune the member's behaviour: `max_review_load`,
    defaulting to 4 and constrained to between 1 and 20, is the ceiling on
    concurrently assigned reviews, and `calibration_bias`, defaulting to 0.00 and
    constrained to between minus 1.00 and plus 1.00 at two decimals, is the offset
    carried over from prior conferences that is added to every rubric total this
    member produces.

    Design: Corner/state_machines/committee_member_starts_invited_with_a_pending_coi_and_zero_load
    """
    set_clock("2026-01-05T00:00:00Z")
    conference = create_conference()

    member = validate_success(
        api_client.create_committee_member(
            _recruit_reviewer_payload(conference["id"]), ADMIN
        ),
        201,
    )

    assert member["max_review_load"] == 4
    assert float(member["calibration_bias"]) == 0.00


# ─── Illegal phase jumps ─────────────────────────────────────────────────


def test_conference_cannot_jump_from_draft_straight_to_review_closed():
    """The conference lifecycle runs `DRAFT` → `CFA_OPEN` → `CFA_CLOSED` →
    `REVIEW_OPEN` → `REVIEW_CLOSED` → `DECISIONS_RELEASED` → `PROGRAM_PUBLISHED`,
    and every move is driven by operations staff naming a `to_status`.

    Conference status gate — the owning conference is in a status that permits the
    operation. Otherwise `ERR_CONFERENCE_STATE_INVALID` (409).

    Later violations are never reported, and no partial write ever survives a
    rejection.

    Design: Corner/state_machines/conference_jump_from_draft_to_review_closed_is_rejected
    """
    conference = _draft_conference_with_one_category()
    version_before = conference["version"]

    res = api_client.transition_conference(
        conference["id"], status_transition_payload("REVIEW_CLOSED"), ADMIN
    )
    validate_error(res, "ERR_CONFERENCE_STATE_INVALID")

    after = get_success_data(api_client.get_conference(conference["id"], ADMIN))
    assert after["status"] == "DRAFT"
    assert after["version"] == version_before


# ─── Withdrawal being terminal ───────────────────────────────────────────


def _withdrawn_abstract_after_decisions_released() -> dict:
    """An ORAL-accepted abstract withdrawn by its registered author, with the
    conference already at DECISIONS_RELEASED."""
    world = setup_decided_abstract(decision="ORAL")
    release_decisions(world)
    register_author(world["authors"]["ada"]["id"], True)
    world["abstracts"][0] = get_success_data(
        api_client.transition_abstract(
            world["abstracts"][0]["id"],
            status_transition_payload("WITHDRAWN", reason="conflicting publication"),
            world["author_headers"],
        )
    )
    assert world["abstracts"][0]["status"] == "WITHDRAWN"
    return world


def test_confirmation_of_a_withdrawn_abstract_is_rejected():
    """Its `status` tracks the review and decision lifecycle across `SUBMITTED`,
    `UNDER_REVIEW`, `SCORED`, `REVISION_REQUESTED`, `ACCEPTED`, `WAITLISTED`,
    `REJECTED`, `CONFIRMED`, `SCHEDULED`, `PRESENTED`, `NO_SHOW` and `WITHDRAWN`,
    of which `REJECTED`, `PRESENTED`, `NO_SHOW` and `WITHDRAWN` are terminal.

    An author converts an acceptance into a commitment by moving their abstract
    from `ACCEPTED` to `CONFIRMED`. Only the submitting author may do so; the
    conference must be `DECISIONS_RELEASED` or `PROGRAM_PUBLISHED`; the author's
    `is_registered` must be true, or the request fails with
    `ERR_AUTHOR_NOT_REGISTERED`; and the author's `sanction_status` must not be
    `BARRED`, or it fails with `ERR_AUTHOR_BARRED`.

    Acted-on resource state — a transition to the requested target exists from the
    resource's current state, and dependent operations find their prerequisites in
    the required state. This band also covers terminal-state lockdown and the
    second attempt at an operation that already succeeded.

    Design: Corner/state_machines/withdrawn_abstract_cannot_be_confirmed_afterwards
    """
    world = _withdrawn_abstract_after_decisions_released()
    abstract_id = world["abstracts"][0]["id"]

    res = api_client.transition_abstract(
        abstract_id, status_transition_payload("CONFIRMED"), world["author_headers"]
    )
    validate_error(res, "ERR_ABSTRACT_STATE_INVALID")

    after = get_success_data(api_client.get_abstract(abstract_id, ADMIN))
    assert after["status"] == "WITHDRAWN"

    author = get_success_data(
        api_client.get_author(world["authors"]["ada"]["id"], ADMIN)
    )
    assert author["is_registered"] is True


def test_withdrawal_releases_the_oral_slot_it_had_consumed():
    """In parallel, if the withdrawn abstract carried a non-null `decision`, the
    conference's matching accepted count drops by one and its `version` advances,
    and the freed capacity immediately runs waitlist promotion for that format,
    which re-increments the same counter if a promotable abstract exists.

    When the eligible pool is empty the slot simply stays free and no error is
    raised.

    Design: Corner/state_machines/withdrawn_abstract_cannot_be_confirmed_afterwards
    """
    world = _withdrawn_abstract_after_decisions_released()

    conference = refresh_conference(world)
    assert conference["accepted_oral_count"] == 0


# ─── A second decline on one review ──────────────────────────────────────


def _one_assigned_review() -> tuple:
    """An UNDER_REVIEW abstract holding a single ASSIGNED review for Rui."""
    world = setup_conference_with_committee()
    open_call_for_abstracts(world)
    abstract = submit_abstract(world)
    open_review_phase(world)
    review = assign_review(world, abstract["id"], world["members"]["rui"]["id"])
    return world, abstract, review


def test_first_decline_moves_the_review_to_declined_and_frees_the_load():
    """Declining is the reviewer's escape hatch. Only the assigned reviewer may
    decline, only while the conference is `REVIEW_OPEN`, and a `decline_reason` is
    mandatory. The review moves from `ASSIGNED` to `DECLINED` and the reviewer's
    `current_review_load` falls by one.

    A committee member's `current_review_load` always equals the number of that
    member's review rows whose `status` is `ASSIGNED`, and it must never be
    negative nor exceed that member's `max_review_load`.

    Design: Corner/state_machines/second_decline_on_the_same_review_is_rejected
    """
    world, _abstract, review = _one_assigned_review()
    assert review["status"] == "ASSIGNED"

    res = api_client.decline_review(
        review["id"],
        decline_review_payload(FIRST_DECLINE_REASON, auto_reassign=False),
        make_reviewer_headers(world["members"]["rui"]["id"]),
    )
    declined = validate_success(res)

    assert declined["status"] == "DECLINED"
    assert member_of(world, "rui")["current_review_load"] == 0


def test_second_decline_on_the_same_review_is_rejected():
    """`SUBMITTED`, `DECLINED` and `VOIDED` are all terminal for a review.

    Acted-on resource state — a transition to the requested target exists from the
    resource's current state, and dependent operations find their prerequisites in
    the required state. Otherwise one of `ERR_ABSTRACT_STATE_INVALID`,
    `ERR_REVIEW_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`,
    `ERR_CASE_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`,
    `ERR_SLOT_STATE_INVALID`, `ERR_ACCREDITATION_STATE_INVALID`,
    `ERR_DISCLOSURE_STATE_INVALID` or `ERR_CHANGE_REQUEST_STATE_INVALID` (409).
    This band also covers terminal-state lockdown and the second attempt at an
    operation that already succeeded.

    A committee member's `current_review_load` always equals the number of that
    member's review rows whose `status` is `ASSIGNED`, and it must never be
    negative nor exceed that member's `max_review_load`.

    Later violations are never reported, and no partial write ever survives a
    rejection.

    Design: Corner/state_machines/second_decline_on_the_same_review_is_rejected
    """
    world, abstract, review = _one_assigned_review()
    first = decline_review_as(
        world,
        review,
        "rui",
        decline_reason=FIRST_DECLINE_REASON,
        auto_reassign=False,
    )
    assert first["status"] == "DECLINED"

    res = api_client.decline_review(
        review["id"],
        decline_review_payload("declining again", auto_reassign=False),
        make_reviewer_headers(world["members"]["rui"]["id"]),
    )
    validate_error(res, "ERR_REVIEW_STATE_INVALID")

    after = get_success_data(api_client.get_review(review["id"], ADMIN))
    assert after["status"] == "DECLINED"
    assert after["decline_reason"] == FIRST_DECLINE_REASON
    assert member_of(world, "rui")["current_review_load"] == 0

    abstract_after = get_success_data(api_client.get_abstract(abstract["id"], ADMIN))
    assert abstract_after["status"] == "UNDER_REVIEW"
    assert abstract_after["submitted_review_count"] == 0


# ─── Activation without a conflict declaration ───────────────────────────


def test_member_activation_without_a_conflict_declaration_is_rejected():
    """Membership status runs `INVITED` → `ACTIVE`, with `SUSPENDED` as a
    reversible detour and `RESIGNED` as the terminal exit. Activation requires at
    least one conflict declaration already on file for that member; without one
    the attempt fails with `ERR_COI_NOT_DECLARED`. Activation sets the member's
    `coi_declaration_status` to `SUBMITTED`, which is what the reviewer selector
    and the assignment rules actually test.

    Later violations are never reported, and no partial write ever survives a
    rejection.

    Design: Corner/state_machines/member_activation_without_a_conflict_declaration_is_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    conference = create_conference()
    member = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                conference["id"],
                member_role="REVIEWER",
                full_name="Rui Alvarez",
                email="rui@panel.example",
            ),
            ADMIN,
        )
    )

    res = api_client.transition_committee_member(
        member["id"],
        status_transition_payload("ACTIVE"),
        make_reviewer_headers(member["id"]),
    )
    validate_error(res, "ERR_COI_NOT_DECLARED")

    after = get_success_data(api_client.get_committee_member(member["id"], ADMIN))
    assert after["status"] == "INVITED"
    assert after["coi_declaration_status"] == "PENDING"


# ─── Slot creation updating the session ledger ───────────────────────────


def _planned_session_holding_no_slots() -> tuple:
    """A PLANNED 60-minute oral session and one CONFIRMED abstract to place."""
    world = setup_confirmed_abstract(decision="ORAL")
    session = create_session(world)
    live = get_success_data(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert live["status"] == "PLANNED"
    assert live["slot_count"] == 0
    assert live["committed_minutes"] == 0
    return world, live


def _place_one_thirty_minute_slot(world: dict, session: dict):
    return api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            world["abstracts"][0]["id"],
            world["authors"]["ada"]["id"],
            1,
            30,
            session["version"],
        ),
        world["chair_headers"],
    )


def test_slot_creation_schedules_the_confirmed_abstract():
    """A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`,
    raises the session's `slot_count` by one, recomputes `committed_minutes`,
    `accredited_credit_total` and `accreditation_posture`, and advances the
    session's `version`. The slot itself starts in `SCHEDULED` status with
    `swapped_with_slot_id` null.

    Design: Corner/state_machines/slot_creation_syncs_the_session_ledger_and_schedules_the_abstract
    """
    world, session = _planned_session_holding_no_slots()
    assert world["abstracts"][0]["status"] == "CONFIRMED"

    slot = validate_success(_place_one_thirty_minute_slot(world, session), 201)

    assert slot["status"] == "SCHEDULED"
    assert slot["position"] == 1
    assert slot["duration_minutes"] == 30
    assert slot["swapped_with_slot_id"] is None

    abstract = get_success_data(
        api_client.get_abstract(world["abstracts"][0]["id"], ADMIN)
    )
    assert abstract["status"] == "SCHEDULED"


def test_slot_creation_syncs_the_session_packing_ledger():
    """A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`,
    raises the session's `slot_count` by one, recomputes `committed_minutes`,
    `accredited_credit_total` and `accreditation_posture`, and advances the
    session's `version`.

    A session's `committed_minutes` is the sum of `duration_minutes` over its
    counted slots plus a five-minute changeover allowance for each gap between
    consecutive counted slots — that is, five minutes multiplied by one less than
    the number of counted slots, and zero when there are no slots at all.

    A session's `accreditation_posture` follows from it: `NOT_APPLICABLE` whenever
    `cme_designated` is false, otherwise `COMPLIANT` when `accredited_credit_total`
    is at least 0.50 and `NON_COMPLIANT` when it is below that.

    Design: Corner/state_machines/slot_creation_syncs_the_session_ledger_and_schedules_the_abstract
    """
    world, session = _planned_session_holding_no_slots()
    version_before = session["version"]

    validate_success(_place_one_thirty_minute_slot(world, session), 201)

    after = get_success_data(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert after["slot_count"] == 1
    assert after["committed_minutes"] == 30
    assert after["version"] == version_before + 1
    assert float(after["accredited_credit_total"]) == 0.00
    assert after["accreditation_posture"] == "NOT_APPLICABLE"


# ─── An early embargo release ────────────────────────────────────────────


def _embargoed_accepted_abstract() -> dict:
    """A newsworthy ACCEPTED abstract under an embargo that has not expired."""
    world = setup_embargoed_abstract(embargo_until_utc=EMBARGO_INSTANT)
    assert world["abstracts"][0]["embargo_status"] == "EMBARGOED"
    return world


def test_release_before_the_embargo_instant_breaches_the_embargo():
    """Setting an embargo moves the abstract's `embargo_status` from `NONE` to
    `EMBARGOED` and requires that the abstract's `is_newsworthy` be true —
    otherwise the attempt fails with `ERR_NOT_NEWSWORTHY` — that the abstract's
    `status` be `ACCEPTED`, `CONFIRMED` or `SCHEDULED`, and that the supplied
    `embargo_until_utc` be present, strictly later than the logical clock, and at
    or before the conference's `event_end_utc`; a missing or out-of-window instant is
    `ERR_EMBARGO_WINDOW_INVALID`.

    When the logical clock is strictly earlier than `embargo_until_utc`, the very
    same request instead records `press_outlet_name` and lands in `BREACHED`,
    running Cascade E: the submitting author's `embargo_breach_count` is
    recomputed and their `sanction_status` is re-derived, which can bar an author
    who has also missed a presentation.

    The two dimensions evolve independently: an abstract whose embargo has been
    breached keeps whatever review or decision status it had, and a breach never
    blocks a scheduling operation on its own.

    Design: Corner/state_machines/embargo_release_before_the_instant_breaches_and_warns_the_author
    """
    world = _embargoed_accepted_abstract()

    res = api_client.press_action(
        world["abstracts"][0]["id"],
        press_action_payload("RELEASE", outlet_name=OUTLET),
        PRESS,
    )
    released = validate_success(res)

    assert released["embargo_status"] == "BREACHED"
    assert released["press_outlet_name"] == OUTLET
    assert released["status"] == "ACCEPTED"


def test_breached_embargo_warns_the_submitting_author():
    """When the logical clock is strictly earlier than `embargo_until_utc`, the
    very same request instead records `press_outlet_name` and lands in `BREACHED`,
    running Cascade E: the submitting author's `embargo_breach_count` is
    recomputed and their `sanction_status` is re-derived, which can bar an author
    who has also missed a presentation.

    The `sanction_status` ladder is derived from their sum: a combined count of
    zero leaves the author at `NONE`, a combined count of exactly one moves them
    to `WARNED`, and a combined count of two or more moves them to `BARRED`.

    Design: Corner/state_machines/embargo_release_before_the_instant_breaches_and_warns_the_author
    """
    world = _embargoed_accepted_abstract()
    author_id = world["authors"]["ada"]["id"]

    before = get_success_data(api_client.get_author(author_id, ADMIN))
    assert before["embargo_breach_count"] == 0
    assert before["sanction_status"] == "NONE"

    validate_success(
        api_client.press_action(
            world["abstracts"][0]["id"],
            press_action_payload("RELEASE", outlet_name=OUTLET),
            PRESS,
        )
    )

    after = get_success_data(api_client.get_author(author_id, ADMIN))
    assert after["embargo_breach_count"] == 1
    assert after["no_show_strikes"] == 0
    assert after["sanction_status"] == "WARNED"
