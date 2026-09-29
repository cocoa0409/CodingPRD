"""Declared initial states, single valid transitions, refused transitions, and
the multi-entity cascades each successful transition drives."""

import pytest

from test_helpers import (
    CALL_MANAGER,
    JURY_CHAIR_A,
    JURY_CHAIR_B,
    JURY_CHAIR_B_USER_ID,
    REGISTRAR,
    REGISTRAR_USER_ID,
    ApiErrorId,
    assert_same_instant,
    create_artwork_payload,
    create_condition_report_payload,
    create_entry_payload,
    fixtures,
    make_artist_headers,
    make_juror_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 4,500-cent base line discounted 0.175 and rounded half up.
MEMBER_BASE_LINE_CENTS = 3713
LATER_IN_THE_CALL = "2026-09-10T00:00:00Z"

AWARD_PRIZE_CENTS = 100000

HONORARIUM_CENTS = 50000
EQUAL_SHARE_CENTS = 25000
LONG_SESSION_MINUTES = 240
SHORT_SESSION_MINUTES = 120
# floor(50000 * 240 / 360) is 33,333 and the single remainder cent goes to the
# earlier `created_at`; floor(50000 * 120 / 360) is 16,666.
LONG_SESSION_SHARE_CENTS = 33334
SHORT_SESSION_SHARE_CENTS = 16666

DAY_ONE_START = "2026-10-06T09:00:00Z"
DAY_ONE_END = "2026-10-06T13:00:00Z"
DAY_TWO_START = "2026-10-07T09:00:00Z"
DAY_TWO_END = "2026-10-07T13:00:00Z"
SHORT_SESSION_START = "2026-10-07T09:00:00Z"
SHORT_SESSION_END = "2026-10-07T11:00:00Z"

SINGLE_WORK_INSURED_CENTS = 400000
PREMIUM_FLOOR_CENTS = 25000
CLAIM_DEADLINE_AT = "2027-01-12T00:00:00Z"

TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]


def _jurying_show_with_confirmed_juror(works=None):
    """A `JURYING` exhibition with one `CONFIRMED` juror and a `PENDING` round."""
    exhibition = fixtures.open_call()
    artworks = []
    if works:
        artist = fixtures.register_artist(member_status="MEMBER")
        _, artworks = fixtures.setup_submitted_entry(
            exhibition["id"], artist, works
        )
    fixtures.enter_jurying(exhibition["id"])
    juror = fixtures.invite_and_confirm_juror(honorarium_cents=HONORARIUM_CENTS)
    jury_round = fixtures.create_jury_round(exhibition["id"], quorum_required=1)
    return exhibition, juror, jury_round, artworks


# ─── Declared initial states ──────────────────────────

def test_a_new_entry_and_its_first_work_start_on_both_declared_axes(api):
    """PRD §3.2: "Each accepted work is created with `status` `DRAFT` on its
    jury-and-logistics axis and `placement_status` `UNPLACED` on its physical
    axis, with `wall_segment_id`, `span_start_cm` and `span_end_cm` all null, and
    with `storage_fee_cents` at 0."

    Design: Corner/state_machines/entry_and_artwork_start_in_declared_initial_states
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    headers = make_artist_headers(artist["id"])

    entry = validate_success(
        api.create_entry(
            create_entry_payload(exhibition["id"], artist["id"]), headers
        ),
        201,
    )
    assert entry["status"] == "DRAFT"
    assert entry["entry_fee_cents"] == 0
    assert entry["fee_paid_cents"] == 0
    assert entry["fee_waived"] is False
    assert entry["submitted_at"] is None

    artwork = validate_success(
        api.attach_artwork(entry["id"], create_artwork_payload(), headers), 201
    )
    assert artwork["status"] == "DRAFT"
    assert artwork["placement_status"] == "UNPLACED"
    assert artwork["wall_segment_id"] is None
    assert artwork["span_start_cm"] is None
    assert artwork["span_end_cm"] is None
    assert artwork["storage_fee_cents"] == 0
    assert artwork["valid_score_count"] == 0
    assert artwork["provisional_mean_score"] is None


# ─── A single declared advance ────────────────────────

def test_opening_the_call_bumps_the_version_and_leaves_the_other_axis_alone(api):
    """PRD §3.1: "Every successful advance increments the exhibition's `version`
    by 1 and refreshes its `updated_at`."

    Design: Corner/state_machines/exhibition_draft_to_open_for_entries_valid_transition
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)
    exhibition = fixtures.create_exhibition()
    assert exhibition["status"] == "DRAFT"
    assert exhibition["version"] == 1

    opened = validate_success(
        api.advance_exhibition_phase(
            exhibition["id"], {"target_status": "OPEN_FOR_ENTRIES"}, CALL_MANAGER
        )
    )

    assert opened["status"] == "OPEN_FOR_ENTRIES"
    assert opened["version"] == 2
    assert opened["settlement_status"] == "NOT_STARTED", "the other axis is idle"
    assert opened["accepted_count"] == 0
    assert opened["insurance_premium_cents"] == 0


def test_paying_the_frozen_fee_cascades_both_draft_works_to_submitted(api):
    """PRD §3.3: "A successful payment records `fee_paid_cents`, advances the
    entry `PENDING_FEE → SUBMITTED`, and cascades: every work of the entry whose
    `status` is `DRAFT` advances to `SUBMITTED`, each such work's own `version`
    incrementing by 1 alongside the entry's."

    Design: Corner/state_machines/fee_payment_cascades_every_draft_artwork_to_submitted
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, TWO_WORKS
    )

    submitted = fixtures.submit_entry(entry["id"], artist)
    assert submitted["status"] == "PENDING_FEE"
    assert submitted["entry_fee_cents"] == MEMBER_BASE_LINE_CENTS, (
        "both works fall inside works_included_in_base, so only the base line "
        "is charged"
    )
    assert_same_instant(submitted["submitted_at"], fixtures.CLOCK_CALL_OPEN)

    paid = validate_success(
        api.pay_entry_fee(
            entry["id"], {"amount_cents": MEMBER_BASE_LINE_CENTS},
            make_artist_headers(artist["id"]),
        )
    )
    assert paid["status"] == "SUBMITTED"
    assert paid["fee_paid_cents"] == MEMBER_BASE_LINE_CENTS

    for artwork in artworks:
        cascaded = fixtures.read_artwork(artwork["id"])
        assert cascaded["status"] == "SUBMITTED"
        assert cascaded["placement_status"] == "UNPLACED", (
            "the payment cascade touches only the jury-and-logistics axis"
        )


# ─── Refused transitions ──────────────────────────────

def test_a_round_with_no_jurors_booked_cannot_open(api):
    """PRD §3.5: "`PENDING → OPEN` requires the exhibition to be `JURYING` and
    requires at least one `BOOKED` assignment to exist for the round — a round
    with no jurors booked cannot open."

    Design: Corner/state_machines/jury_round_open_without_a_booked_assignment_rejected
    """
    _, juror, jury_round, _ = _jurying_show_with_confirmed_juror(
        works=[fixtures.WORK_RIDGE_LINE]
    )

    refused = api.set_jury_round_status(
        jury_round["id"], {"target_status": "OPEN"}, JURY_CHAIR_A
    )
    validate_error(refused, ApiErrorId.ERR_JURY_ROUND_STATE_INVALID.value, 409)

    unchanged = fixtures.read_jury_round(jury_round["id"])
    assert unchanged["status"] == "PENDING"
    assert unchanged["reopen_count"] == 0

    _, meta = validate_paginated(
        api.list_juror_assignments(
            JURY_CHAIR_A, params={"jury_round_id": jury_round["id"]}
        )
    )
    assert meta["total_count"] == 0

    fixtures.book_session(jury_round["id"], juror, DAY_ONE_START, DAY_ONE_END)
    opened = fixtures.set_round_status(jury_round["id"], "OPEN")
    assert opened["status"] == "OPEN", "the same call succeeds once a juror sits"


def test_placement_actions_on_an_unplaced_work_are_all_state_invalid(api):
    """PRD §2.10: "**Target state** — the target record is in a state from which
    the requested transition is declared, else the state code for that record
    type: `ERR_ENTRY_STATE_INVALID`, `ERR_ARTWORK_STATE_INVALID`,
    `ERR_JURY_ROUND_STATE_INVALID`, `ERR_AWARD_STATE_INVALID`,
    `ERR_SALE_STATE_INVALID`, or `ERR_ASSIGNMENT_STATE_INVALID`, all HTTP 409.
    Applies to every action endpoint."

    Design: Corner/state_machines/artwork_install_from_unplaced_returns_state_invalid
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry = fixtures.open_entry(exhibition["id"], artist)
    artwork = fixtures.attach_work(entry["id"], artist, with_primary_image=False)

    for response in (
        api.install_artwork(artwork["id"], REGISTRAR),
        api.deinstall_artwork(artwork["id"], REGISTRAR),
        api.complete_return(artwork["id"], REGISTRAR),
    ):
        validate_error(response, ApiErrorId.ERR_ARTWORK_STATE_INVALID.value, 409)

    after = fixtures.read_artwork(artwork["id"])
    assert after["placement_status"] == "UNPLACED"
    assert after["wall_segment_id"] is None
    assert after["span_start_cm"] is None
    assert after["span_end_cm"] is None
    assert after["version"] == 1, "no refused trigger bumped the row"


def test_submitting_an_entry_twice_does_not_refreeze_the_fee(api):
    """PRD §3.3: "An artist first submits the entry, advancing it `DRAFT →
    PENDING_FEE`, which freezes the assessed fee and stamps `submitted_at` with
    the logical clock."

    Design: Corner/state_machines/entry_submit_twice_second_attempt_rejected
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, [fixtures.WORK_RIDGE_LINE]
    )

    first = fixtures.submit_entry(entry["id"], artist)
    assert first["status"] == "PENDING_FEE"
    assert first["entry_fee_cents"] == MEMBER_BASE_LINE_CENTS
    assert_same_instant(first["submitted_at"], fixtures.CLOCK_CALL_OPEN)

    fixtures.set_clock(LATER_IN_THE_CALL)
    second = api.submit_entry(entry["id"], make_artist_headers(artist["id"]))
    validate_error(second, ApiErrorId.ERR_ENTRY_STATE_INVALID.value, 409)

    after = fixtures.read_entry(entry["id"])
    assert after["status"] == "PENDING_FEE"
    assert after["entry_fee_cents"] == MEMBER_BASE_LINE_CENTS
    assert_same_instant(
        after["submitted_at"], fixtures.CLOCK_CALL_OPEN,
        "the refused second submission did not re-stamp the frozen instant",
    )
    assert fixtures.read_artwork(artworks[0]["id"])["status"] == "DRAFT", (
        "the cascade belongs to fee payment, not to submission"
    )


def test_a_rescinded_award_refuses_both_confirmation_and_rescission(api):
    """PRD §3.8: "An award that is not `PROPOSED` when confirmation is requested,
    or not `CONFIRMED` when rescission is requested, is refused with
    `ERR_AWARD_STATE_INVALID`."

    Design: Corner/state_machines/award_rescinded_terminal_state_rejects_further_confirm
    """
    ctx = fixtures.setup_results_published_show()
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["acceptance_result"]["accepted_artwork_ids"][0]

    award = fixtures.propose_award(
        exhibition_id, artwork_id, "BEST_IN_SHOW", AWARD_PRIZE_CENTS
    )
    fixtures.confirm_award(award["id"], exhibition_id)
    rescinded = validate_success(
        api.rescind_award(
            award["id"], {"reason": "Withdrawn by the panel."}, JURY_CHAIR_B
        )
    )
    assert rescinded["status"] == "RESCINDED"
    assert fixtures.read_exhibition(exhibition_id)["award_committed_cents"] == 0

    version = fixtures.exhibition_version(exhibition_id)
    validate_error(
        api.confirm_award(
            award["id"], {"expected_exhibition_version": version}, JURY_CHAIR_B
        ),
        ApiErrorId.ERR_AWARD_STATE_INVALID.value,
        409,
    )
    validate_error(
        api.rescind_award(
            award["id"], {"reason": "Second rescission attempt."}, JURY_CHAIR_B
        ),
        ApiErrorId.ERR_AWARD_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_award(award["id"])
    assert after["status"] == "RESCINDED"
    assert after["confirmed_by_user_id"] == JURY_CHAIR_B_USER_ID, (
        "the identity of the confirmation that did happen is retained"
    )
    assert fixtures.read_exhibition(exhibition_id)["award_committed_cents"] == 0


# ─── Cascades driven by a successful transition ───────

def test_resignation_cancels_every_booking_and_unwinds_the_ledger(api):
    """PRD §3.4: "Resignation is the bulk form of the same cascade and runs five
    hops. Every assignment of the resigning juror whose `status` is `BOOKED`
    moves to `CANCELLED`; each cancellation re-runs the proration over the
    juror's remaining assignments; the juror's `honorarium_committed_cents` is
    recomputed; the `jury_cost_committed_cents` of every affected exhibition is
    recomputed; and the `quorum_shortfall_count` of every affected round is
    recomputed, which may leave a round uncompletable until other jurors fill the
    gap."

    Design: Corner/state_machines/juror_resignation_cascades_to_assignments_and_reprorates_honorarium
    """
    exhibition, juror, jury_round, _ = _jurying_show_with_confirmed_juror(
        works=[fixtures.WORK_RIDGE_LINE]
    )
    first = fixtures.book_session(
        jury_round["id"], juror, DAY_ONE_START, DAY_ONE_END
    )
    second = fixtures.book_session(
        jury_round["id"], juror, DAY_TWO_START, DAY_TWO_END
    )

    assert fixtures.read_assignment(first["id"])["honorarium_share_cents"] == (
        EQUAL_SHARE_CENTS
    )
    assert second["honorarium_share_cents"] == EQUAL_SHARE_CENTS
    assert fixtures.read_juror(juror["id"])["honorarium_committed_cents"] == (
        HONORARIUM_CENTS
    )
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == HONORARIUM_CENTS

    resigned = validate_success(
        api.resign_juror(juror["id"], make_juror_headers(juror["id"]))
    )
    assert resigned["status"] == "RESIGNED"

    for assignment_id in (first["id"], second["id"]):
        cancelled = fixtures.read_assignment(assignment_id)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["honorarium_share_cents"] == 0

    juror_after = fixtures.read_juror(juror["id"])
    assert juror_after["honorarium_committed_cents"] == 0
    assert juror_after["assignment_count"] == 0
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == 0

    round_after = fixtures.read_jury_round(jury_round["id"])
    assert round_after["quorum_shortfall_count"] == 1, (
        "the round is now uncompletable"
    )
    assert round_after["status"] == "PENDING"


def test_closing_the_round_completes_its_bookings_and_retains_their_shares(api):
    """PRD §3.5: "`SCORING_COMPLETE → CLOSED` finishes the round for good and
    cascades every assignment of that round whose `status` is `BOOKED` to
    `COMPLETED`, retaining each one's `honorarium_share_cents`."

    Design: Corner/state_machines/round_close_bubbles_booked_assignments_to_completed
    """
    exhibition, juror, jury_round, artworks = _jurying_show_with_confirmed_juror(
        works=[fixtures.WORK_RIDGE_LINE]
    )
    assignment = fixtures.book_session(
        jury_round["id"], juror, DAY_ONE_START, DAY_ONE_END
    )
    fixtures.set_round_status(jury_round["id"], "OPEN")
    fixtures.set_clock(fixtures.CLOCK_SCORING)
    fixtures.submit_score(jury_round["id"], juror, artworks[0]["id"], 8, 8, 8)
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")

    before = fixtures.read_assignment(assignment["id"])
    assert before["status"] == "BOOKED"
    assert before["session_minutes"] == LONG_SESSION_MINUTES
    assert before["honorarium_share_cents"] == HONORARIUM_CENTS
    assert before["scores_submitted_count"] == 1

    closed = fixtures.set_round_status(jury_round["id"], "CLOSED")
    assert closed["status"] == "CLOSED"

    after = fixtures.read_assignment(assignment["id"])
    assert after["status"] == "COMPLETED"
    assert after["honorarium_share_cents"] == HONORARIUM_CENTS, (
        "unlike a cancellation, the completed sitting keeps its share"
    )

    juror_after = fixtures.read_juror(juror["id"])
    assert juror_after["honorarium_committed_cents"] == HONORARIUM_CENTS
    assert juror_after["honorarium_paid_cents"] == 0
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == HONORARIUM_CENTS

    artwork = fixtures.read_artwork(artworks[0]["id"])
    assert artwork["status"] == "SHORTLISTED"
    assert artwork["certified_mean_score"] == pytest.approx(8.00, abs=0.01)


def test_an_intake_report_writes_the_work_the_report_and_the_insurance(api):
    """PRD §3.7: "An `INTAKE` report is the event that acknowledges delivery: it
    carries the work `ACCEPTED → DELIVERED`, requires the exhibition to be in
    `INSTALLATION`, and requires the clock to lie inside the closed
    `[delivery_window_start_at, delivery_window_end_at]` interval, else
    `ERR_DELIVERY_WINDOW_INVALID`."

    PRD §3.7: "When `insured_value_total_cents` is greater than zero,
    `insurance_premium_cents` is the greater of 25,000 cents and the raw premium,
    so an insured total of 4,900,000 cents charges 25,000 rather than its raw
    17,150."

    Design: Corner/state_machines/intake_condition_report_cross_entity_updates_exhibition_insurance
    """
    ctx = fixtures.setup_installation_show()
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["acceptance_result"]["accepted_artwork_ids"][0]

    before = fixtures.read_exhibition(exhibition_id)
    assert before["insured_value_total_cents"] == 0
    assert before["insurance_premium_cents"] == 0

    report = validate_success(
        api.file_condition_report(
            artwork_id,
            create_condition_report_payload(
                "INTAKE", "B", photo_count=4,
                damage_notes="Minor frame scuff, lower left.",
            ),
            REGISTRAR,
        ),
        201,
    )
    assert report["stage"] == "INTAKE"
    assert report["condition_grade"] == "B"
    assert report["photo_count"] == 4
    assert report["reported_by_user_id"] == REGISTRAR_USER_ID

    artwork = fixtures.read_artwork(artwork_id)
    assert artwork["status"] == "DELIVERED"
    assert artwork["intake_condition_grade"] == "B"

    after = fixtures.read_exhibition(exhibition_id)
    assert after["insured_value_total_cents"] == SINGLE_WORK_INSURED_CENTS
    assert after["insurance_premium_cents"] == PREMIUM_FLOOR_CENTS, (
        "four insured units raise a raw premium of 1,400, so the floor wins"
    )

    _, meta = validate_paginated(
        api.list_condition_reports(
            artwork_id, REGISTRAR, params={"stage": "INTAKE"}
        )
    )
    assert meta["total_count"] == 1


def test_each_booking_reprorates_and_pushes_the_total_up_two_levels(api):
    """PRD §3.4: "Because truncation loses cents, a remainder is computed as the
    juror's `honorarium_cents` minus the sum of the truncated shares, and that
    remainder is distributed one cent at a time to the active assignments taken
    in order of `created_at` ascending — never by identifier — until it is
    exhausted."

    PRD §3.10: "Alongside it, `jury_cost_committed_cents` records what the jury
    has cost — the sum of `honorarium_share_cents` over the `BOOKED` and
    `COMPLETED` assignments of every round belonging to this exhibition."

    Design: Corner/state_machines/assignment_booking_syncs_juror_and_exhibition_jury_cost_ledger
    """
    exhibition, juror, jury_round, _ = _jurying_show_with_confirmed_juror()

    first = fixtures.book_session(
        jury_round["id"], juror, DAY_ONE_START, DAY_ONE_END
    )
    assert first["session_minutes"] == LONG_SESSION_MINUTES
    assert first["honorarium_share_cents"] == HONORARIUM_CENTS
    assert fixtures.read_juror(juror["id"])["honorarium_committed_cents"] == (
        HONORARIUM_CENTS
    )
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == HONORARIUM_CENTS

    second = fixtures.book_session(
        jury_round["id"], juror, SHORT_SESSION_START, SHORT_SESSION_END
    )
    assert second["session_minutes"] == SHORT_SESSION_MINUTES
    assert second["honorarium_share_cents"] == SHORT_SESSION_SHARE_CENTS

    reprorated = fixtures.read_assignment(first["id"])
    assert reprorated["honorarium_share_cents"] == LONG_SESSION_SHARE_CENTS
    assert (
        reprorated["honorarium_share_cents"] + second["honorarium_share_cents"]
        == HONORARIUM_CENTS
    )

    juror_after = fixtures.read_juror(juror["id"])
    assert juror_after["honorarium_committed_cents"] == HONORARIUM_CENTS
    assert juror_after["assignment_count"] == 2
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == HONORARIUM_CENTS, "re-derived from the active set, not double-counted"


def test_the_show_cannot_open_while_one_delivered_work_is_only_planned(api):
    """PRD §3.7: "Advancing `INSTALLATION → ON_VIEW` requires that **every**
    artwork of the exhibition whose `status` is `ACCEPTED` or `DELIVERED` have
    `placement_status` `INSTALLED`, else `ERR_INSTALLATION_INCOMPLETE`, and
    requires the clock to have reached `opening_at`, else
    `ERR_PHASE_TIME_NOT_REACHED`."

    Design: Corner/state_machines/on_view_advance_requires_every_accepted_work_installed
    """
    ctx = fixtures.setup_installation_show(works=TWO_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    first, second = ctx["acceptance_result"]["accepted_artwork_ids"]

    for artwork_id in (first, second):
        fixtures.file_condition_report(artwork_id, "INTAKE", "A")
    fixtures.plan_span(first, ctx["wall"], 0.0, 100.0)
    fixtures.plan_span(second, ctx["wall"], 200.0, 300.0)
    fixtures.install_artwork(first)

    fixtures.set_clock(fixtures.CLOCK_OPENING)
    refused = api.advance_exhibition_phase(
        exhibition_id, {"target_status": "ON_VIEW"}, CALL_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_INSTALLATION_INCOMPLETE.value, 409)

    assert fixtures.read_exhibition(exhibition_id)["status"] == "INSTALLATION"
    for artwork_id in (first, second):
        assert fixtures.read_artwork(artwork_id)["status"] == "DELIVERED"

    fixtures.install_artwork(second)
    opened = fixtures.advance_phase(exhibition_id, "ON_VIEW")
    assert opened["status"] == "ON_VIEW"

    for artwork_id in (first, second):
        hung = fixtures.read_artwork(artwork_id)
        assert hung["status"] == "ON_VIEW"
        assert hung["placement_status"] == "INSTALLED"
    assert fixtures.read_wall(ctx["wall"]["id"])["occupied_cm"] == 200.0


def test_closing_the_show_returns_the_on_view_work_and_skips_the_sold_one(api):
    """PRD §3.10: "`ON_VIEW → CLOSED` cascades four hops. First, every work whose
    `status` is `ON_VIEW` moves to `RETURN_PENDING`, and its `claim_deadline_at`
    is stamped as the exhibition's `closing_at` plus `claim_deadline_days` days."

    Design: Corner/state_machines/closed_cascade_returns_only_on_view_works_and_leaves_sold_untouched
    """
    ctx = fixtures.setup_sold_show(works=TWO_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    sold_id = ctx["sold_artwork_id"]
    other_id = ctx["accepted_artwork_ids"][1]

    assert fixtures.read_artwork(sold_id)["status"] == "SOLD"
    assert fixtures.read_artwork(other_id)["status"] == "ON_VIEW"
    assert fixtures.read_wall(ctx["wall"]["id"])["occupied_cm"] == 200.0

    closed = fixtures.close_show(exhibition_id)
    assert closed["status"] == "CLOSED"

    returned = fixtures.read_artwork(other_id)
    assert returned["status"] == "RETURN_PENDING"
    assert returned["placement_status"] == "DEINSTALLED"
    assert_same_instant(returned["claim_deadline_at"], CLAIM_DEADLINE_AT)

    kept = fixtures.read_artwork(sold_id)
    assert kept["status"] == "SOLD", "the cascade skipped the sold work"
    assert kept["placement_status"] == "INSTALLED"
    assert kept["claim_deadline_at"] is None

    wall = fixtures.read_wall(ctx["wall"]["id"])
    assert wall["occupied_cm"] == 100.0
    assert wall["available_cm"] == 500.0

    after = fixtures.read_exhibition(exhibition_id)
    assert after["insured_value_total_cents"] == SINGLE_WORK_INSURED_CENTS, (
        "the sold work stays inside coverage"
    )
    assert after["insurance_premium_cents"] == PREMIUM_FLOOR_CENTS
