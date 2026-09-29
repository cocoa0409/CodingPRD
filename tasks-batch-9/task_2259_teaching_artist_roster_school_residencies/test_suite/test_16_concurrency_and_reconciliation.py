"""Planning against an out-of-date read: the three version-guarded writes, and
the derived counters a school-side cancellation has to roll back."""
from test_helpers import (
    ApiErrorId,
    FISCAL_OFFICER_USER_ID,
    OBSERVER_USER_ID,
    PROGRAM_DIRECTOR_USER_ID,
    TEST_USERS,
    api_client,
    assert_version_incremented,
    attach_observation_rubric,
    cancel_session_as_liaison,
    confirm_session_as_liaison,
    create_delivered_session,
    create_reassign_payload,
    create_session_payload,
    create_submitted_voucher,
    create_voucher_review_payload,
    make_fiscal_officer_headers,
    make_program_director_headers,
    read_residency,
    read_school,
    read_session,
    read_voucher,
    schedule_session,
    set_clock_to_default,
    setup_active_residency,
    setup_second_artist,
    validate_error,
    validate_success,
)

RC = TEST_USERS["roster_coordinator_headers"]


def _attempt_session(
    residency_id: str,
    assigned_artist_id: str,
    expected_residency_version: int,
    lesson_plan_id: str,
    session_date: str,
):
    """Post a session creation and hand back the raw response for inspection."""
    payload = create_session_payload(
        residency_id,
        assigned_artist_id,
        expected_residency_version,
        session_date=session_date,
        start_time="09:00",
        end_time="10:00",
        lesson_plan_id=lesson_plan_id,
    )
    return api_client.create_session(payload, RC)


def _attempt_reassign(
    session_id: str, substitute_artist_id: str, expected_session_version: int
):
    """Post a substitute swap and hand back the raw response."""
    payload = create_reassign_payload(
        substitute_artist_id, expected_session_version
    )
    return api_client.reassign_session(session_id, payload, RC)


def _attempt_review_pass(
    voucher_id: str, review_track: str, expected_version: int, headers: dict
):
    """Close one voucher review track with a PASS, returning the raw response."""
    payload = create_voucher_review_payload(
        review_track, "PASS", expected_version
    )
    return api_client.review_payment_voucher(voucher_id, payload, headers)


# ==========================================================================
# The residency version, bumped by the sibling session collection
# ==========================================================================
def _active_residency_ready_to_schedule() -> dict:
    """An ACTIVE residency with one aligned plan and nothing on the calendar."""
    set_clock_to_default()
    return setup_active_residency()


def test_replaying_a_residency_version_after_the_first_create_is_refused(api):
    """PRD §2.6: "In each case the version field is a **required** input, not an
    optional hint, and the request is rejected outright when the value does not
    equal the parent's current `version`."
    PRD §2.6: "A mismatch is rejected with `ERR_STALE_RESIDENCY_VERSION` and HTTP
    412."
    PRD §3.6: "Creating the session updates the residency's ledger: a `REGULAR`
    session subtracts one from `sessions_unscheduled_count`, while a `MAKEUP`
    session leaves that counter alone and instead sets `makeup_consumed` to true
    on its origin session and subtracts one from `makeup_credits_outstanding`."
    PRD §3.6: "Either way `sessions_open_count` gains one, `projected_cost_cents`
    is recomputed, and the residency's `version` increments."

    Design: Corner/Cross-Cutting Complexity Layers/stale_residency_version_blocks_a_second_session_create
    """
    scenario = _active_residency_ready_to_schedule()
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]
    plan_id = scenario["lesson_plan"]["id"]

    # The coordinator reads the residency once and plans two sessions off it.
    observed = read_residency(residency_id)["version"]
    first = validate_success(
        _attempt_session(residency_id, artist_id, observed, plan_id, "2026-09-15"),
        expected_status=201,
    )
    assert first["status"] == "PLANNED"
    assert read_residency(residency_id)["version"] == observed + 1, (
        "the accepted create is itself a mutation of the residency row, so it "
        "bumps the very version the client is still holding"
    )

    refused = _attempt_session(
        residency_id, artist_id, observed, plan_id, "2026-09-22"
    )
    validate_error(
        refused, ApiErrorId.ERR_STALE_RESIDENCY_VERSION.value, expected_status=412
    )

    after_refusal = read_residency(residency_id)
    assert after_refusal["version"] == observed + 1, (
        "a refused write mutates nothing, so the current version is still the "
        f"one the accepted create left behind, got {after_refusal['version']}"
    )
    assert after_refusal["sessions_open_count"] == 1, (
        f"only the first create opened a session, got "
        f"{after_refusal['sessions_open_count']}"
    )
    assert after_refusal["sessions_unscheduled_count"] == 9, (
        "one REGULAR session drew one unit of the ten-session allotment, got "
        f"{after_refusal['sessions_unscheduled_count']}"
    )

    # Refreshing the version is all the retry needs — two sessions a week apart
    # are perfectly legal, so nothing else was ever wrong with the request.
    second = validate_success(
        _attempt_session(
            residency_id,
            artist_id,
            after_refusal["version"],
            plan_id,
            "2026-09-22",
        ),
        expected_status=201,
    )
    assert second["status"] == "PLANNED"
    assert second["session_date"] == "2026-09-22"

    final = read_residency(residency_id)
    assert_version_incremented(final["version"], after_refusal["version"])
    assert final["version"] == observed + 2, (
        "two accepted creates bump the residency twice and the refusal not at "
        f"all, got {final['version']} against an opening {observed}"
    )
    assert final["sessions_open_count"] == 2, (
        f"both sessions are PLANNED and therefore open, got "
        f"{final['sessions_open_count']}"
    )
    assert final["sessions_unscheduled_count"] == 8, (
        f"ten contracted less two scheduled, got "
        f"{final['sessions_unscheduled_count']}"
    )
    assert read_session(first["id"])["status"] == "PLANNED"


# ==========================================================================
# The session version, bumped by the confirmation the client did not see
# ==========================================================================
def _confirmed_session_with_a_standby_substitute() -> dict:
    """One CONFIRMED 60-minute session held by the lead artist, plus a second
    cleared artist capable of the same residency frame."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["substitute"] = setup_second_artist()
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    # The version the coordinator observed before the school confirmed.
    scenario["observed_session_version"] = read_session(session["id"])["version"]
    scenario["session"] = confirm_session_as_liaison(
        session["id"], scenario["school"]["id"]
    )
    return scenario


def test_reassigning_against_the_pre_confirmation_session_version_is_refused(api):
    """PRD §2.6: "In each case the version field is a **required** input, not an
    optional hint, and the request is rejected outright when the value does not
    equal the parent's current `version`."
    PRD §2.6: "Session reassignment must carry `expected_session_version`,
    matching the current `version` of the addressed session."
    PRD §2.6: "A mismatch is rejected with `ERR_STALE_SESSION_VERSION` and HTTP
    412."
    PRD §3.6: "Confirmation also recomputes `projected_cost_cents` and increments
    both the session's and the residency's `version`."

    Design: Corner/Cross-Cutting Complexity Layers/stale_session_version_blocks_a_reassignment_then_the_swap_succeeds
    """
    scenario = _confirmed_session_with_a_standby_substitute()
    session_id = scenario["session"]["id"]
    observed = scenario["observed_session_version"]
    assert scenario["session"]["status"] == "CONFIRMED"
    assert scenario["session"]["encumbered_cents"] == 13974, (
        "the lead artist at the APPRENTICE tier teaching a bilingual DANCE "
        "G3_5 residency for the full 60 minutes holds 13974, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    refused = _attempt_reassign(
        session_id, scenario["substitute"]["id"], observed
    )
    validate_error(
        refused, ApiErrorId.ERR_STALE_SESSION_VERSION.value, expected_status=412
    )

    session = read_session(session_id)
    assert session["version"] == observed + 1, (
        "the confirmation had already bumped the session once and the refused "
        f"swap bumped it not at all, got {session['version']}"
    )
    assert session["assigned_artist_id"] == scenario["artist"]["id"], (
        "the refused swap must leave the assignment exactly where it was"
    )
    assert session["is_substitute"] is False
    assert session["status"] == "CONFIRMED"
    assert read_residency(scenario["residency"]["id"])["encumbered_cents"] == 13974, (
        "the residency still holds the lead artist's full-length fee, because "
        "the refused swap released and re-committed nothing"
    )


def test_the_substitute_swap_replaces_the_encumbrance_rather_than_stacking_it(api):
    """PRD §3.7: "The second form swaps the artist without ever vacating the
    slot: `CONFIRMED → CONFIRMED`."
    PRD §3.7: "On success, the outgoing artist's identifier is copied into
    `vacated_artist_id`, `assigned_artist_id` becomes the substitute, and
    `is_substitute` becomes true; the held amount is swapped for the
    substitute-rate figure and the residency's `encumbered_cents`,
    `available_cents`, and `projected_cost_cents` are recomputed."
    PRD §3.7: "If the session's `is_substitute` flag is true, multiply that sum
    by 0.85 and round; otherwise multiply by 1.00 and round."
    PRD §2.12: "The **money ledger** partitions the budget across three accounts:
    `encumbered_cents`, the sum of the amounts currently held by this residency's
    sessions; `disbursed_cents`, the sum of `total_cents` over this residency's
    `APPROVED` vouchers; and `available_cents`, which is `budget_cents` less
    encumbered less disbursed."

    Design: Corner/Cross-Cutting Complexity Layers/stale_session_version_blocks_a_reassignment_then_the_swap_succeeds
    """
    scenario = _confirmed_session_with_a_standby_substitute()
    session_id = scenario["session"]["id"]
    substitute = scenario["substitute"]
    assert substitute["roster_status"] == "ACTIVE"
    assert substitute["roster_tier_effective"] == "TEACHING_ARTIST", (
        "an artist off probation with no deliveries yet simply keeps the "
        f"assigned tier, got {substitute['roster_tier_effective']}"
    )
    assert "es" in substitute["languages"], (
        "the substitute must speak the instruction language, otherwise the "
        f"language premium drops out, got {substitute['languages']}"
    )

    validate_error(
        _attempt_reassign(
            session_id, substitute["id"], scenario["observed_session_version"]
        ),
        ApiErrorId.ERR_STALE_SESSION_VERSION.value,
        expected_status=412,
    )

    swapped = validate_success(
        _attempt_reassign(
            session_id, substitute["id"], read_session(session_id)["version"]
        )
    )
    assert swapped["status"] == "CONFIRMED", (
        f"the slot is never vacated by this form, got {swapped['status']}"
    )
    assert swapped["assigned_artist_id"] == substitute["id"]
    assert swapped["is_substitute"] is True
    assert swapped["vacated_artist_id"] == scenario["artist"]["id"], (
        "the outgoing artist's identifier is copied into vacated_artist_id, got "
        f"{swapped['vacated_artist_id']}"
    )
    assert swapped["encumbered_cents"] == 11985, (
        "12600 graded and tiered at TEACHING_ARTIST, no lead premium for the "
        "substitute, plus the 1500 language premium, times 0.85 rounds to "
        f"11985, got {swapped['encumbered_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 11985, (
        "the lead's 13974 was released rather than stacked on top of the "
        f"substitute rate, got {residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 188015, (
        f"200000 budget less the single 11985 hold, got "
        f"{residency['available_cents']}"
    )
    assert residency["disbursed_cents"] == 0


# ==========================================================================
# The voucher version, bumped by the other review track
# ==========================================================================
def _submitted_voucher_for_one_delivery() -> dict:
    """One evaluated delivery of 13974 cents claimed by a submitted voucher."""
    set_clock_to_default()
    scenario = setup_active_residency()
    delivered = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    attach_observation_rubric(delivered["id"], OBSERVER_USER_ID, 4, 3, 4)
    scenario["session"] = delivered
    scenario["voucher"] = create_submitted_voucher(scenario, [delivered["id"]])
    return scenario


def test_the_second_review_track_cannot_close_from_the_version_the_first_used(api):
    """PRD §2.6: "Voucher review must carry `expected_payment_voucher_version`,
    matching the current `version` of the addressed voucher."
    PRD §2.6: "A mismatch is rejected with `ERR_STALE_VOUCHER_VERSION` and HTTP
    412."
    PRD §2.6: "Because the two review tracks are independent, a reviewer closing
    the program track from the same observed version that another reviewer used
    to close the fiscal track would legitimately succeed under the state machine;
    the version check forces the second reviewer to re-read the voucher — and
    therefore the first track's outcome and the recomputed total — before closing
    their own track."
    PRD §3.8: "A `PASS` that closes only the first of the two tracks leaves the
    voucher in `SUBMITTED`: the addressed track becomes `PASSED`, its reviewer
    field records the acting operator, and the voucher's `version` increments."

    Design: Corner/Cross-Cutting Complexity Layers/stale_voucher_version_blocks_the_second_review_track
    """
    scenario = _submitted_voucher_for_one_delivery()
    voucher_id = scenario["voucher"]["id"]
    assert scenario["voucher"]["status"] == "SUBMITTED"
    assert scenario["voucher"]["total_cents"] == 13974, (
        "the single claimed delivery earned 13974 with no travel or materials, "
        f"got {scenario['voucher']['total_cents']}"
    )

    # Both reviewers read the voucher at the same moment, before either acts.
    observed = read_voucher(voucher_id)["version"]

    after_fiscal = validate_success(
        _attempt_review_pass(
            voucher_id,
            "FISCAL",
            observed,
            make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID),
        )
    )
    assert after_fiscal["status"] == "SUBMITTED", (
        f"one closed track is not the join, got {after_fiscal['status']}"
    )
    assert after_fiscal["fiscal_review_status"] == "PASSED"
    assert after_fiscal["program_review_status"] == "PENDING"

    refused = _attempt_review_pass(
        voucher_id,
        "PROGRAM",
        observed,
        make_program_director_headers(PROGRAM_DIRECTOR_USER_ID),
    )
    validate_error(
        refused, ApiErrorId.ERR_STALE_VOUCHER_VERSION.value, expected_status=412
    )

    voucher = read_voucher(voucher_id)
    assert voucher["version"] == observed + 1, (
        "only the fiscal pass bumped the row; the refused program pass did "
        f"not, got {voucher['version']}"
    )
    assert voucher["program_review_status"] == "PENDING", (
        "the refused call closed nothing, got "
        f"{voucher['program_review_status']}"
    )
    assert voucher["status"] == "SUBMITTED"
    assert read_residency(scenario["residency"]["id"])["disbursed_cents"] == 0


def test_the_refreshed_voucher_version_lets_the_second_track_fire_the_join(api):
    """PRD §2.6: "Because the two review tracks are independent, a reviewer
    closing the program track from the same observed version that another
    reviewer used to close the fiscal track would legitimately succeed under the
    state machine; the version check forces the second reviewer to re-read the
    voucher — and therefore the first track's outcome and the recomputed total —
    before closing their own track."
    PRD §3.8: "When a `PASS` closes the **second** track, so that both
    `fiscal_review_status` and `program_review_status` read `PASSED`, the join
    fires automatically and the voucher becomes `APPROVED`."
    PRD §3.8: "Approval moves money: the residency's `disbursed_cents` gains
    `total_cents`, its `encumbered_cents` loses the sum of the held amounts of
    the claimed sessions, each of those sessions has its held amount zeroed, and
    `available_cents` is recomputed — leaving the money identity of §2.12
    intact."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."

    Design: Corner/Cross-Cutting Complexity Layers/stale_voucher_version_blocks_the_second_review_track
    """
    scenario = _submitted_voucher_for_one_delivery()
    voucher_id = scenario["voucher"]["id"]
    observed = read_voucher(voucher_id)["version"]
    validate_success(
        _attempt_review_pass(
            voucher_id,
            "FISCAL",
            observed,
            make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID),
        )
    )
    validate_error(
        _attempt_review_pass(
            voucher_id,
            "PROGRAM",
            observed,
            make_program_director_headers(PROGRAM_DIRECTOR_USER_ID),
        ),
        ApiErrorId.ERR_STALE_VOUCHER_VERSION.value,
        expected_status=412,
    )

    approved = validate_success(
        _attempt_review_pass(
            voucher_id,
            "PROGRAM",
            read_voucher(voucher_id)["version"],
            make_program_director_headers(PROGRAM_DIRECTOR_USER_ID),
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the second pass fires the join, got {approved['status']}"
    )
    assert approved["fiscal_review_status"] == "PASSED"
    assert approved["program_review_status"] == "PASSED"
    assert approved["total_cents"] == 13974, (
        "the recomputed total is unchanged by the review round, got "
        f"{approved['total_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["disbursed_cents"] == 13974, (
        f"approval moves the whole total to disbursed, got "
        f"{residency['disbursed_cents']}"
    )
    assert residency["encumbered_cents"] == 0, (
        "the claimed session's hold is zeroed by the approval, got "
        f"{residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 186026, (
        f"200000 less 13974 disbursed and nothing encumbered, got "
        f"{residency['available_cents']}"
    )
    assert (
        residency["available_cents"]
        + residency["encumbered_cents"]
        + residency["disbursed_cents"]
        == 200000
    ), "the money identity must survive the join"


# ==========================================================================
# Derived counters after a school-side cancellation
# ==========================================================================
def _one_planned_session_at_a_healthy_school() -> dict:
    """An ACTIVE ten-session residency with a single PLANNED session on the
    books and nothing yet delivered."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_cancelling_the_only_planned_session_moves_the_unit_to_a_makeup_credit(api):
    """PRD §3.7: "School-side cancellation — reasons `SCHOOL_CLOSURE`,
    `TESTING_CONFLICT`, or `LOW_ENROLLMENT` — drives the session to
    `CANCELLED_SCHOOL` from `PLANNED`, from `CONFIRMED`, or from `VACATED`, and
    the three branches differ only in what they have to unwind."
    PRD §3.7: "`makeup_eligible` becomes true when the reason is
    `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or `ARTIST_NO_SHOW`,
    and false when it is `LOW_ENROLLMENT` or `RESIDENCY_DESCOPED`."
    PRD §3.7: "From `PLANNED` there is nothing held, so the effects are just the
    eligibility flag and the ledger move: `sessions_open_count` loses one, and
    `makeup_credits_outstanding` gains one when the session was make-up-eligible
    while `sessions_forfeited_count` gains one when it was not."
    PRD §2.12: "The sum of those five buckets always equals
    `contracted_session_count`."

    Design: Corner/Cross-Cutting Complexity Layers/derived_counters_reconcile_after_a_cancellation
    """
    scenario = _one_planned_session_at_a_healthy_school()
    residency_id = scenario["residency"]["id"]

    before = read_residency(residency_id)
    assert before["sessions_open_count"] == 1, (
        f"one PLANNED session is open, got {before['sessions_open_count']}"
    )
    assert before["sessions_unscheduled_count"] == 9, (
        "nine of the ten contracted sessions are still unscheduled, got "
        f"{before['sessions_unscheduled_count']}"
    )
    assert before["makeup_credits_outstanding"] == 0, (
        "nothing has been cancelled yet, got "
        f"{before['makeup_credits_outstanding']}"
    )
    assert before["encumbered_cents"] == 0, (
        f"a PLANNED session holds nothing, got {before['encumbered_cents']}"
    )

    cancelled = cancel_session_as_liaison(
        scenario["session"]["id"],
        scenario["school"]["id"],
        "SCHOOL_CLOSURE",
        note="snow day",
    )
    assert cancelled["status"] == "CANCELLED_SCHOOL"
    assert cancelled["makeup_eligible"] is True, (
        "SCHOOL_CLOSURE is a make-up-eligible reason, so the school gets the "
        "session back"
    )
    assert cancelled["makeup_consumed"] is False

    after = read_residency(residency_id)
    assert after["sessions_open_count"] == 0, (
        f"the only open session terminated, got {after['sessions_open_count']}"
    )
    assert after["makeup_credits_outstanding"] == 1, (
        "the unit moved out of the open bucket into the outstanding-credit "
        f"bucket, got {after['makeup_credits_outstanding']}"
    )
    assert after["sessions_forfeited_count"] == 0, (
        "a make-up-eligible cancellation forfeits nothing, got "
        f"{after['sessions_forfeited_count']}"
    )
    assert after["sessions_unscheduled_count"] == 9, (
        "the allotment already drawn by the cancelled session does not come "
        f"back as unscheduled, got {after['sessions_unscheduled_count']}"
    )
    assert after["encumbered_cents"] == 0
    buckets = (
        after["sessions_unscheduled_count"]
        + after["sessions_open_count"]
        + after["sessions_delivered_count"]
        + after["sessions_forfeited_count"]
        + after["makeup_credits_outstanding"]
    )
    assert buckets == 10, (
        f"9 unscheduled plus 1 outstanding credit must still equal the ten "
        f"contracted sessions, got {buckets}"
    )


def test_the_cancellation_leaves_the_cost_projection_and_school_rollup_intact(api):
    """PRD §3.4: "`projected_cost_cents` is the forward-looking figure the program
    director watches against `budget_cents`: it starts from
    `earned_to_date_cents`, adds a full-length fee projection for every session of
    the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED`, and then
    adds one lead projection for each remaining unscheduled allotment unit and
    each outstanding make-up credit — that is, `sessions_unscheduled_count` plus
    `makeup_credits_outstanding` lead projections."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status` of
    `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."
    PRD §3.3: "Otherwise health reads `HEALTHY`."
    PRD §3.3: "The size of that same set is published as `open_residency_count`."

    Design: Corner/Cross-Cutting Complexity Layers/derived_counters_reconcile_after_a_cancellation
    """
    scenario = _one_planned_session_at_a_healthy_school()
    residency_id = scenario["residency"]["id"]
    school_id = scenario["school"]["id"]

    projection_before = read_residency(residency_id)["projected_cost_cents"]
    assert projection_before == 139740, (
        "one PLANNED session projected at 13974 plus nine lead projections of "
        f"13974 each, got {projection_before}"
    )
    school_before = read_school(school_id)
    assert school_before["open_residency_count"] == 1, (
        "the school hosts exactly one non-terminal residency, got "
        f"{school_before['open_residency_count']}"
    )
    assert school_before["partnership_health"] == "HEALTHY"

    cancel_session_as_liaison(
        scenario["session"]["id"], school_id, "SCHOOL_CLOSURE", note="snow day"
    )

    residency = read_residency(residency_id)
    assert residency["staffing_status"] == "STAFFED", (
        "the lead artist is still in place and no session is VACATED, got "
        f"{residency['staffing_status']}"
    )
    assert residency["earned_to_date_cents"] == 0, (
        "nothing was delivered, so the backward-looking figure stays at zero"
    )
    assert residency["projected_cost_cents"] == projection_before, (
        "the cancelled session is replaced by an outstanding make-up "
        "obligation, so the ten lead-rate projections are unchanged at "
        f"139740, got {residency['projected_cost_cents']}"
    )

    school_after = read_school(school_id)
    assert school_after["open_residency_count"] == 1, (
        "the residency itself is still ACTIVE and therefore still counted, got "
        f"{school_after['open_residency_count']}"
    )
    assert school_after["partnership_health"] == "HEALTHY", (
        "a school-caused cancellation leaves no residency SUSPENDED, AT_RISK "
        f"or LEAD_VACANT, got {school_after['partnership_health']}"
    )
