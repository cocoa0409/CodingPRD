"""Scholarship money: sources, awards, encumbrance, disbursement and release."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ONE_USER_ID,
    OFFICER_TWO_USER_ID,
    api_client,
    assert_funding_ledger_conservation,
    confirm_enrollment,
    create_active_participant,
    create_award,
    create_confirmed_enrollment,
    create_fee_band,
    create_funding_source,
    create_open_session,
    create_period,
    disburse_award,
    encumber_award,
    funding_source_version,
    make_funding_officer_headers,
    move_posture,
    read_award,
    read_enrollment,
    read_funding_source,
    read_session,
    release_award,
    request_enrollment,
    validate_error,
    validate_success,
    withdraw_enrollment,
)
from test_helpers.fixtures import OFFICER


def _withdrawal_cascade_fixture():
    """Two confirmed places, one waitlisted candidate holding a 7000-cent award
    that will drain the grant, and a third enrolment whose award then lapses."""
    period = create_period()
    create_fee_band(income_band="BAND_C", per_session_cents=8000, series_cents=48000)
    create_fee_band(income_band="BAND_A", per_session_cents=4000, series_cents=24000)
    source = create_funding_source(
        period["id"],
        name="Inclusion Grant",
        source_kind="RESTRICTED_GRANT",
        priority_rank=1,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=7000,
        total_budget_cents=7000,
    )
    _program, session = create_open_session(
        program_overrides={"name": "Inclusive Fitness"}, slot_capacity=2
    )
    holder = create_active_participant(household_id="HH-A", income_band="BAND_C")
    subsidised = create_active_participant(
        legal_name="Cleo Vance", date_of_birth="2008-11-02", household_id="HH-C",
        weight_kg=50, income_band="BAND_A",
    )
    waiting = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-B",
        weight_kg=45, income_band="BAND_C",
    )

    holder_enrollment = create_confirmed_enrollment(holder["participant"]["id"], session["id"])
    subsidised_enrollment = create_confirmed_enrollment(
        subsidised["participant"]["id"], session["id"]
    )
    waiting_enrollment = request_enrollment(waiting["participant"]["id"], session["id"])
    waiting_enrollment = confirm_enrollment(waiting_enrollment["id"], on_full="WAITLIST")

    waiting_award = create_award(
        waiting_enrollment["id"], source["id"], requested_amount_cents=7000
    )
    subsidised_award = create_award(
        subsidised_enrollment["id"], source["id"], requested_amount_cents=3000
    )
    return {
        "session": session,
        "source": source,
        "holder_enrollment": holder_enrollment,
        "subsidised_enrollment": subsidised_enrollment,
        "waiting_enrollment": waiting_enrollment,
        "waiting_award": waiting_award,
        "subsidised_award": subsidised_award,
    }


def test_withdrawal_promotes_the_waitlisted_row_and_encumbers_its_award():
    """PRD §3.4: "Hop 3, caused by the slot freed in hop 2, promotes the
    top-ranked waitlisted candidate that independently satisfies all six
    sub-gates. Hop 4, caused by hop 3, encumbers that promoted enrolment's
    `PROPOSED` award. Hop 5, caused by hop 4, moves the award amount out of that
    source's `available_cents` and into its `encumbered_cents`. Hop 6, caused by
    hop 5, moves the source from `OPEN` to `EXHAUSTED` when its `available_cents`
    has reached exactly 0."
    PRD §3.4: "The winner moves from `WAITLISTED` to `CONFIRMED`, has
    `promoted_at` stamped with the logical clock instant, and receives exactly
    the same counter, award, charge-recomputation and booking side effects as a
    client-driven confirmation, with its own `version` and the session's
    `version` each rising by one."

    Design: Difficulty/transitive_cascade/withdrawal_cascade_promotes_encumbers_exhausts_lapses_and_demotes
    """
    state = _withdrawal_cascade_fixture()

    withdraw_enrollment(state["holder_enrollment"]["id"])

    assert read_enrollment(state["holder_enrollment"]["id"])["enrollment_status"] == "WITHDRAWN"
    promoted = read_enrollment(state["waiting_enrollment"]["id"])
    assert promoted["enrollment_status"] == "CONFIRMED"
    assert promoted["promoted_at"] is not None
    assert promoted["funding_status"] == "ENCUMBERED"

    award = read_award(state["waiting_award"]["id"])
    assert award["status"] == "ENCUMBERED"
    assert award["encumbered_cents"] == 7000

    source = read_funding_source(state["source"]["id"])
    assert source["available_cents"] == 0
    assert source["encumbered_cents"] == 7000
    assert source["status"] == "EXHAUSTED"
    assert_funding_ledger_conservation(source)


def test_the_exhausted_grant_lapses_a_third_award_and_demotes_its_enrollment():
    """PRD §3.4: "Hop 7, caused by hop 6, lapses every award on that
    now-exhausted source whose status is `PROPOSED` to `LAPSED_NO_FUNDS`. Hop 8,
    caused by hop 7, moves each lapsed award's enrolment `funding_status` to
    `UNFUNDED` and — when that enrolment is `CONFIRMED` and its participant's
    `income_band` is `BAND_A` or `BAND_B` — demotes it from `CONFIRMED` back to
    `WAITLISTED`."
    PRD §3.4: "A demotion frees `slots_committed` and, for a one-to-one
    participant, `one_to_one_committed`, restores the matching available
    counters, recomputes `required_group_staff_planned` and `staffing_gap`,
    recomputes that row's `waitlist_score`, and raises the enrolment's and the
    session's `version` by one each."

    Design: Difficulty/transitive_cascade/withdrawal_cascade_promotes_encumbers_exhausts_lapses_and_demotes
    """
    state = _withdrawal_cascade_fixture()

    withdraw_enrollment(state["holder_enrollment"]["id"])

    lapsed = read_award(state["subsidised_award"]["id"])
    assert lapsed["status"] == "LAPSED_NO_FUNDS"
    assert lapsed["encumbered_cents"] == 0

    demoted = read_enrollment(state["subsidised_enrollment"]["id"])
    assert demoted["funding_status"] == "UNFUNDED"
    assert demoted["enrollment_status"] == "WAITLISTED"

    session = read_session(state["session"]["id"])
    assert session["slots_committed"] == 1
    assert session["slots_available"] == 1


def _proposed_award_by_officer_one():
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        period["id"],
        name="General Fund",
        source_kind="GENERAL_FUND",
        priority_rank=2,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=3000,
        total_budget_cents=20000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    award = create_award(
        enrollment["id"], source["id"], requested_amount_cents=3000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    return source, enrollment, award


def test_segregation_of_duties_pre_empts_the_wrong_source_state_on_disburse():
    """PRD §2.10 rung 8: "On award disbursement only, the acting `X-User-ID`
    differs from the award's `awarded_by_user_id` — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §2.1: "The `FundingOfficer` whose `X-User-ID` was stamped onto a
    scholarship award as `awarded_by_user_id` may never be the one who disburses
    it; an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Difficulty/priority_pair_validation_conflict/auth_rung_8_beats_state_rung_26_on_disburse
    """
    _source, _enrollment, award = _proposed_award_by_officer_one()
    assert award["status"] == "PROPOSED", "disburse has no legal from-state here"
    assert award["awarded_by_user_id"] == OFFICER_ONE_USER_ID

    validate_error(
        api_client.disburse_award(
            award["id"], {"amount_cents": 3000},
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )


def test_the_refused_disbursement_moves_no_cents_and_never_reports_invalid_state():
    """PRD §2.10: "**Error precedence where two rungs could both fire.** The rule
    is always the lower rung number wins, and it resolves every ambiguity in this
    document."
    PRD §2.10 rung 26: "On every state-transition endpoint, the target row is in
    a declared source state for the requested transition — otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.8: "A successful creation files the award in `status` `PROPOSED` with
    `amount_cents` pinned, `encumbered_cents` 0, `disbursed_cents` 0,
    `awarded_by_user_id` stamped with the acting officer's `X-User-ID`, and
    `disbursed_by_user_id` null."

    Design: Difficulty/priority_pair_validation_conflict/auth_rung_8_beats_state_rung_26_on_disburse
    """
    source, _enrollment, award = _proposed_award_by_officer_one()

    error = validate_error(
        api_client.disburse_award(
            award["id"], {"amount_cents": 3000},
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    after_award = read_award(award["id"])
    assert after_award["disbursed_cents"] == 0
    assert after_award["disbursed_by_user_id"] is None
    after_source = read_funding_source(source["id"])
    assert after_source["available_cents"] == 20000
    assert_funding_ledger_conservation(after_source)


def _award_on_a_source_whose_own_period_is_closing():
    """A PROPOSED award drawn on a source that sits in an earlier period which
    has since moved to CLOSING, while the current period stays OPEN."""
    old_period = create_period(name="FY26 Q1", starts_on="2026-01-01", ends_on="2026-03-31")
    current_period = create_period(
        name="FY26 Q2-Q4", starts_on="2026-04-01", ends_on="2026-12-31"
    )
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        old_period["id"],
        name="Q1 Carryover Grant",
        source_kind="RESTRICTED_GRANT",
        priority_rank=1,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=3000,
        total_budget_cents=20000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    award = create_award(
        enrollment["id"], source["id"], requested_amount_cents=3000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    move_posture(old_period["id"], "CLOSING")
    return current_period, source, enrollment, award


def test_encumber_is_blocked_by_its_sources_own_closing_operating_period():
    """PRD §2.10 rung 56: "**Sub-gate F, head rung.** On award creation and award
    encumbrance, the named funding source's `status` is not `CLOSED` and its
    operating period's `status` is `OPEN` — otherwise `ERR_FUNDING_PERIOD_CLOSED`
    (409)."
    PRD §3.8: "Moving an award from `PROPOSED` to `ENCUMBERED` — whether an
    officer asks for it or enrolment confirmation does it automatically —
    requires that the source is not `CLOSED`, that its operating period's
    `status` is `OPEN`, and that its `available_cents` is at least the award's
    `amount_cents`; the first two failures report `ERR_FUNDING_PERIOD_CLOSED` and
    the third `ERR_INSUFFICIENT_FUNDS`."

    Design: Difficulty/cross_entity_state_dependency/award_encumber_blocked_by_its_sources_closing_operating_period
    """
    _current_period, _source, _enrollment, award = (
        _award_on_a_source_whose_own_period_is_closing()
    )

    validate_error(
        api_client.encumber_award(
            award["id"], make_funding_officer_headers(OFFICER_TWO_USER_ID)
        ),
        ApiErrorId.ERR_FUNDING_PERIOD_CLOSED.value,
        expected_status=409,
    )


def test_the_blocked_encumbrance_leaves_the_award_source_and_enrollment_untouched():
    """PRD §3.1: "From `CLOSING` a period may either be abandoned back to `OPEN` —
    in which case no funding source anywhere is touched — or completed to
    `CLOSED`."
    PRD §3.8: "The source is created `OPEN` with `available_cents` equal to
    `total_budget_cents`, `encumbered_cents` 0 and `disbursed_cents` 0."
    PRD §2.5: "When no row qualifies at all — including the case where no period
    has ever been created — there is no current period and neither the global
    write gate nor the financial-write gate fires."

    Design: Difficulty/cross_entity_state_dependency/award_encumber_blocked_by_its_sources_closing_operating_period
    """
    current_period, source, enrollment, award = (
        _award_on_a_source_whose_own_period_is_closing()
    )

    validate_error(
        api_client.encumber_award(
            award["id"], make_funding_officer_headers(OFFICER_TWO_USER_ID)
        ),
        ApiErrorId.ERR_FUNDING_PERIOD_CLOSED.value,
        expected_status=409,
    )

    after_award = read_award(award["id"])
    assert after_award["status"] == "PROPOSED"
    assert after_award["encumbered_cents"] == 0
    after_source = read_funding_source(source["id"])
    assert after_source["available_cents"] == 20000
    assert after_source["encumbered_cents"] == 0
    assert after_source["status"] == "OPEN"
    assert read_enrollment(enrollment["id"])["funding_status"] == "QUOTED"
    assert validate_success(
        api_client.get_operating_period(current_period["id"], OFFICER)
    )["status"] == "OPEN", "the current period is OPEN, so no write gate fired"


def _encumbered_award_of_five_thousand():
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        period["id"],
        name="Access Fund",
        source_kind="GENERAL_FUND",
        priority_rank=2,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=5000,
        total_budget_cents=10000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    award = create_award(
        enrollment["id"], source["id"], requested_amount_cents=5000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    encumber_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    return source, enrollment, award


def test_partial_disbursement_then_release_conserves_the_funding_ledger():
    """PRD §2.11: "**Funding ledger.** For every funding source,
    `total_budget_cents` equals `available_cents` plus `encumbered_cents` plus
    `disbursed_cents`, and the source's `encumbered_cents` equals the sum, over
    its awards whose status is `ENCUMBERED` or `PARTIALLY_DISBURSED`, of each
    award's `encumbered_cents` minus its `disbursed_cents`."
    PRD §3.8: "In every case the award's `disbursed_cents` rises by the paid
    amount, the source's `encumbered_cents` falls by it and its `disbursed_cents`
    rises by it, and `disbursed_by_user_id` is stamped with the paying officer's
    `X-User-ID`."

    Design: Difficulty/compensating_invariant/partial_disbursement_then_release_conserves_the_funding_ledger
    """
    source, _enrollment, award = _encumbered_award_of_five_thousand()

    after_encumbrance = read_funding_source(source["id"])
    assert after_encumbrance["available_cents"] == 5000
    assert after_encumbrance["encumbered_cents"] == 5000
    assert after_encumbrance["disbursed_cents"] == 0
    assert_funding_ledger_conservation(after_encumbrance)

    disburse_award(award["id"], 2000, officer_id=OFFICER_TWO_USER_ID)
    mid = read_funding_source(source["id"])
    assert mid["available_cents"] == 5000
    assert mid["encumbered_cents"] == 3000
    assert mid["disbursed_cents"] == 2000
    assert_funding_ledger_conservation(mid)

    release_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    end = read_funding_source(source["id"])
    assert end["available_cents"] == 8000
    assert end["encumbered_cents"] == 0
    assert end["disbursed_cents"] == 2000
    assert_funding_ledger_conservation(end)


def test_the_remainder_release_never_touches_the_cents_already_paid_out():
    """PRD §3.8: "From `PARTIALLY_DISBURSED`, the `REMAINDER` variant releases
    only `encumbered_cents` minus `disbursed_cents` — the not-yet-paid part — and
    leaves `encumbered_cents` sitting at `disbursed_cents`."
    PRD §3.8: "In both variants the source's `encumbered_cents` falls by the
    released amount and its `available_cents` rises by the same, and
    **`disbursed_cents` is never touched by a release**, on either the award or
    the source."
    PRD §3.8: "A payment strictly smaller than the outstanding encumbrance moves
    an `ENCUMBERED` award to `PARTIALLY_DISBURSED`; a payment exactly equal to
    the outstanding encumbrance moves an `ENCUMBERED` award straight to
    `DISBURSED`, and moves a `PARTIALLY_DISBURSED` award to `DISBURSED`."

    Design: Difficulty/compensating_invariant/partial_disbursement_then_release_conserves_the_funding_ledger
    """
    _source, enrollment, award = _encumbered_award_of_five_thousand()

    partial = disburse_award(award["id"], 2000, officer_id=OFFICER_TWO_USER_ID)
    assert partial["status"] == "PARTIALLY_DISBURSED"
    assert partial["disbursed_cents"] == 2000

    released = release_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    assert released["status"] == "RELEASED"
    assert released["encumbered_cents"] == 2000, (
        "the remainder release leaves encumbered_cents sitting at disbursed_cents; "
        f"got {released['encumbered_cents']}"
    )
    assert released["disbursed_cents"] == 2000
    assert read_enrollment(enrollment["id"])["funding_status"] == "RELEASED"


def test_funding_source_returns_to_open_after_the_encumbrance_is_released():
    """PRD §3.8: "It goes from `OPEN` to `EXHAUSTED` the instant an encumbrance
    leaves its `available_cents` at exactly 0, and that move lapses every award
    on it whose `status` is `PROPOSED` to `LAPSED_NO_FUNDS`. It returns from
    `EXHAUSTED` to `OPEN` the instant a release lifts `available_cents` above
    0 — and **already-lapsed awards are not revived by that return**; recovering
    them requires creating fresh awards."
    PRD §3.8: "On success the award's `encumbered_cents` is set to its
    `amount_cents`, the source's `available_cents` falls by that amount and its
    `encumbered_cents` rises by it, the source may in consequence move to
    `EXHAUSTED`, the enrolment's `funding_status` advances from `QUOTED` to
    `ENCUMBERED`, and the enrolment's charge is recomputed."

    Design: Corner/state_machines/funding_source_returns_to_open_after_the_encumbrance_is_released
    """
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        period["id"],
        name="Small Grant",
        source_kind="RESTRICTED_GRANT",
        priority_rank=1,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=5000,
        total_budget_cents=5000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    award = create_award(
        enrollment["id"], source["id"], requested_amount_cents=5000,
        officer_id=OFFICER_ONE_USER_ID,
    )

    encumber_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    exhausted = read_funding_source(source["id"])
    assert exhausted["status"] == "EXHAUSTED"
    assert exhausted["available_cents"] == 0
    assert exhausted["encumbered_cents"] == 5000
    assert read_enrollment(enrollment["id"])["funding_status"] == "ENCUMBERED"

    released = release_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    reopened = read_funding_source(source["id"])
    assert reopened["status"] == "OPEN"
    assert reopened["available_cents"] == 5000
    assert reopened["encumbered_cents"] == 0
    assert released["status"] == "RELEASED"
    assert released["encumbered_cents"] == 0
    assert read_enrollment(enrollment["id"])["funding_status"] == "RELEASED"


def test_funding_selector_prefers_the_restricted_grant_by_priority_rank():
    """PRD §3.8: "The candidate set is every source whose `status` is `OPEN`,
    whose `available_cents` is strictly above 0, and whose operating period's
    `status` is `OPEN`. Candidates are ranked by `priority_rank` ascending; ties
    are broken first by `available_cents` descending and then by `created_at`
    ascending."
    PRD §3.8: "When `requested_amount_cents` is omitted and the source's
    `award_mode` is `NEED_PCT`, take net need multiplied by `award_pct_bp`,
    divided by 10000, rounded half up — then clip that raw figure down to the
    source's `available_cents` if it exceeds it."
    PRD §3.8: "Net need for an enrolment is its charge's `program_fee_cents` —
    the sliding-scale programme fee before any scholarship, and deliberately not
    the transport-inclusive family total."

    Design: Corner/calculations/funding_selector_prefers_the_restricted_grant_by_priority_rank
    """
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    restricted = create_funding_source(
        period["id"],
        name="Inclusion Grant",
        source_kind="RESTRICTED_GRANT",
        priority_rank=1,
        award_mode="NEED_PCT",
        award_pct_bp=6000,
        flat_award_cents=0,
        total_budget_cents=50000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    general = create_funding_source(
        period["id"],
        name="General Fund",
        source_kind="GENERAL_FUND",
        priority_rank=2,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=8000,
        total_budget_cents=90000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])

    selection = validate_success(
        api_client.get_funding_selection(OFFICER, params={"enrollment_id": enrollment["id"]})
    )
    assert selection["funding_source_id"] == restricted["id"], (
        f"the rank-1 restricted grant wins, never {general['id']}"
    )
    assert selection["net_need_cents"] == 8000
    assert selection["projected_award_cents"] == 4800, (
        f"8000 at 6000 basis points is 4800; got {selection['projected_award_cents']}"
    )

    award = create_award(
        enrollment["id"],
        selection["funding_source_id"],
        expected_funding_source_version=selection["funding_source_version"],
        officer_id=OFFICER_ONE_USER_ID,
    )
    assert award["amount_cents"] == 4800
    assert award["status"] == "PROPOSED"
    assert award["awarded_by_user_id"] == OFFICER_ONE_USER_ID
    assert read_funding_source(restricted["id"])["available_cents"] == 50000, (
        "a PROPOSED award moves no cents"
    )


def test_funding_rungs_reject_over_balance_over_need_and_over_encumbrance():
    """PRD §2.10 rung 57: "**Sub-gate F, continued.** On award creation and award
    encumbrance, the award amount is at least 1 cent and the source's
    `available_cents` is at least that amount; when no source was named, the
    funding selector returned a non-empty candidate set — otherwise
    `ERR_INSUFFICIENT_FUNDS` (409)."
    PRD §2.10 rung 58: "**Sub-gate F, continued.** On award creation, a supplied
    `requested_amount_cents` does not exceed the enrolment's `program_fee_cents`
    — otherwise `ERR_AWARD_EXCEEDS_NEED` (422)."
    PRD §2.10 rung 59: "On award disbursement, the supplied `amount_cents` is at
    least 1 and no greater than the award's `encumbered_cents` minus its
    `disbursed_cents` — otherwise `ERR_DISBURSEMENT_EXCEEDS_ENCUMBRANCE` (422)."

    Design: Corner/validations/funding_rungs_reject_over_need_over_balance_and_over_encumbrance
    """
    source, enrollment, award = _encumbered_award_of_five_thousand_on_twenty_thousand()

    stable_version = funding_source_version(source["id"])
    validate_error(
        api_client.create_scholarship_award(
            {
                "enrollment_id": enrollment["id"],
                "funding_source_id": source["id"],
                "expected_funding_source_version": stable_version,
                "requested_amount_cents": 25000,
            },
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_INSUFFICIENT_FUNDS.value,
        expected_status=409,
    )

    validate_error(
        api_client.create_scholarship_award(
            {
                "enrollment_id": enrollment["id"],
                "funding_source_id": source["id"],
                "expected_funding_source_version": stable_version,
                "requested_amount_cents": 8500,
            },
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_AWARD_EXCEEDS_NEED.value,
        expected_status=422,
    )

    validate_error(
        api_client.disburse_award(
            award["id"], {"amount_cents": 6000},
            make_funding_officer_headers(OFFICER_TWO_USER_ID),
        ),
        ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_ENCUMBRANCE.value,
        expected_status=422,
    )

    after = read_funding_source(source["id"])
    assert after["available_cents"] == 15000
    assert after["encumbered_cents"] == 5000
    assert after["disbursed_cents"] == 0
    assert_funding_ledger_conservation(after)
    unchanged = read_award(award["id"])
    assert unchanged["status"] == "ENCUMBERED"
    assert unchanged["disbursed_cents"] == 0


def _encumbered_award_of_five_thousand_on_twenty_thousand():
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        period["id"],
        name="Access Fund",
        source_kind="GENERAL_FUND",
        priority_rank=2,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=5000,
        total_budget_cents=20000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    _program, session = create_open_session(program_overrides={"name": "Inclusive Fitness"})
    who = create_active_participant()
    enrollment = request_enrollment(who["participant"]["id"], session["id"])
    award = create_award(
        enrollment["id"], source["id"], requested_amount_cents=5000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    encumber_award(award["id"], officer_id=OFFICER_TWO_USER_ID)
    return source, enrollment, award


def test_stale_funding_source_version_rejects_the_second_award():
    """PRD §2.9: "Creating a scholarship award
    (`POST /recreation/scholarship-awards`) must carry
    `expected_funding_source_version` matching the current `version` of the
    `FundingSource` it draws on. The amount an award may claim is bounded by that
    source's `available_cents`, which moves on every encumbrance, disbursement
    and release."
    PRD §2.6: "Creating a transport booking bumps the `TransportRun`. Creating
    a scholarship award bumps the `FundingSource`."

    Design: Corner/cross_cutting_complexity_layers/stale_funding_source_version_rejects_the_second_award
    """
    period = create_period()
    create_fee_band(per_session_cents=8000, series_cents=48000)
    source = create_funding_source(
        period["id"],
        name="Access Fund",
        source_kind="GENERAL_FUND",
        priority_rank=2,
        award_mode="FLAT_CAP",
        award_pct_bp=0,
        flat_award_cents=3000,
        total_budget_cents=20000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    stale_version = source["version"]
    _program, session = create_open_session(
        program_overrides={"name": "Inclusive Fitness"}, slot_capacity=3
    )
    first = create_active_participant()
    second = create_active_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    first_enrollment = request_enrollment(first["participant"]["id"], session["id"])
    second_enrollment = request_enrollment(second["participant"]["id"], session["id"])

    accepted = validate_success(
        api_client.create_scholarship_award(
            {
                "enrollment_id": first_enrollment["id"],
                "funding_source_id": source["id"],
                "expected_funding_source_version": stale_version,
                "requested_amount_cents": 3000,
            },
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        expected_status=201,
    )
    assert accepted["amount_cents"] == 3000

    validate_error(
        api_client.create_scholarship_award(
            {
                "enrollment_id": second_enrollment["id"],
                "funding_source_id": source["id"],
                "expected_funding_source_version": stale_version,
                "requested_amount_cents": 3000,
            },
            make_funding_officer_headers(OFFICER_ONE_USER_ID),
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    retry = create_award(
        second_enrollment["id"], source["id"], requested_amount_cents=3000,
        officer_id=OFFICER_ONE_USER_ID,
    )
    assert retry["amount_cents"] == 3000
    assert read_funding_source(source["id"])["available_cents"] == 20000, (
        "both awards are still PROPOSED, so no cents have moved"
    )
