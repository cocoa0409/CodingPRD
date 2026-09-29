"""Refresher accrual, renewal term arithmetic, the credential cycle and the sweep."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credential,
    assert_hours,
    assert_instant,
    credit_refresher_hours,
    read_activation,
    read_assignment,
    read_cohort,
    read_credential,
    read_program,
    read_trainee,
    set_clock,
    setup_credentialed_trainees,
    setup_rostered_activation,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _credentialed_with_two_drills():
    """11.3 refresher hours banked inside the term: 8.3 from one drill and 3.0 from another."""
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=5.5, role_played="TEAM_LEADER", key="drill1",
        title="Drill 1", starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
        accept_at="2026-09-01T14:00:00Z",
    )
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=2.4, role_played="SEARCH_RESCUE", key="drill2",
        title="Drill 2", starts_at="2026-09-02T08:00:00Z", ends_at="2026-09-02T10:00:00Z",
        accept_at="2026-09-02T12:00:00Z",
    )
    return ctx


def test_only_hours_earned_inside_the_current_term_count_toward_renewal(api):
    """PRD §3.6: "That refresh is an aggregation over a **half-open term window** running
    from `term_start_on` inclusive to the current logical clock exclusive."
    PRD §3.6: "Rows in any other state contribute nothing — registered or voided
    participations, and recorded, pending, or failed completions, are all worth zero — and
    rows dated before `term_start_on` are excluded even if they were never counted in an
    earlier term."
    PRD §3.5: "At issuance the count is necessarily 0, so a new credential is always
    `STANDARD` with 8.0 required hours, no surplus and no extension; `term_start_on` is the
    logical clock, `expires_on` is 365 days after `term_start_on`, and `grace_ends_on` is a
    further 60 days after `expires_on`."

    Design: Difficulty/combinatorial_formula/renewal_tier_resolved_before_reinstatement_count_increment
    """
    ctx = _credentialed_with_two_drills()
    credential = read_credential(ctx, "tara")

    assert_instant(credential["term_start_on"], "2026-08-05T16:00:00Z", "term_start_on")
    assert_hours(credential["refresher_hours_in_term"], 11.3, "refresher_hours_in_term")
    assert credential["reinstatement_count"] == 0
    assert credential["renewal_tier"] == "STANDARD"
    assert_hours(credential["required_refresher_hours"], 8.0, "required_refresher_hours")
    assert credential["status"] == "ACTIVE"


def test_renewal_is_governed_by_the_pre_increment_tier_and_buys_a_capped_extension(api):
    """PRD §3.6: "Once the gate is passed, the term is recomputed in the pinned order: the
    base term is again 365 days; `renewal_tier` is resolved from `reinstatement_count` as it
    stood **before** this renewal; `required_refresher_hours` follows from that tier; the
    surplus is the amount by which `refresher_hours_in_term` exceeds
    `required_refresher_hours`, floored at zero so that an exact match yields no surplus; the
    extension is the whole-number part of that surplus multiplied by 5 days per surplus hour,
    capped at 90 days however large the surplus grows; the new term length is 365 days plus
    that extension; `term_start_on` is set to the logical clock, `expires_on` to the new term
    length after `term_start_on`, and `grace_ends_on` to 60 days after `expires_on`; only then
    is `reinstatement_count` increased by 1; and finally `refresher_hours_in_term` is reset to
    0.0 because the new term starts empty."
    PRD §3.6: "Renewal from `GRACE` also moves the trainee's `currency_status` `LAPSING →
    CURRENT`; renewal from `EXPIRED` moves it `LAPSED → CURRENT`; renewal from `ACTIVE` leaves
    it `CURRENT`."

    Design: Difficulty/combinatorial_formula/renewal_tier_resolved_before_reinstatement_count_increment
    """
    ctx = _credentialed_with_two_drills()
    set_clock("2027-06-01T00:00:00Z")

    renewed = validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "RENEW"}, COORD
        )
    )
    assert_credential(renewed)
    assert renewed["reinstatement_count"] == 1
    assert_instant(renewed["term_start_on"], "2027-06-01T00:00:00Z", "term_start_on")
    # 11.3 hours against an 8.0 STANDARD requirement leaves a 3.3-hour surplus,
    # of which the whole 3 hours buy 15 days on top of the 365-day base.
    assert_instant(renewed["expires_on"], "2028-06-15T00:00:00Z", "expires_on")
    assert_instant(renewed["grace_ends_on"], "2028-08-14T00:00:00Z", "grace_ends_on")
    assert_hours(renewed["refresher_hours_in_term"], 0.0, "refresher_hours_in_term")
    assert renewed["status"] == "ACTIVE"
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"


def test_the_sweep_walks_a_credential_from_active_through_grace_to_expired(api):
    """PRD §3.6: "A credential standing at `ACTIVE` whose `expires_on` the clock has reached
    or passed, while the clock is still strictly before `grace_ends_on`, moves `ACTIVE →
    GRACE` and mirrors the trainee's `currency_status` `CURRENT → LAPSING`. A credential
    standing at `GRACE` whose `grace_ends_on` the clock has reached or passed moves `GRACE →
    EXPIRED`, mirrors the trainee's `currency_status` `LAPSING → LAPSED`, withdraws every
    roster assignment of that trainee standing at `NOTIFIED` or `ACCEPTED` whose activation
    stands at `REQUESTED`, `ROSTERED`, or `ACTIVATED`, and has each affected activation
    recompute `rostered_count`, `accepted_count`, and `fill_status`."

    Design: Difficulty/non_linear_state_machine/credential_cycles_active_grace_expired_and_back_to_active
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credential = read_credential(ctx, "tara")
    assert_instant(credential["expires_on"], "2027-08-05T16:00:00Z", "expires_on")
    assert_instant(credential["grace_ends_on"], "2027-10-04T16:00:00Z", "grace_ends_on")

    set_clock("2027-08-06T00:00:00Z")
    validate_success(
        api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD)
    )
    assert read_credential(ctx, "tara")["status"] == "GRACE"
    assert read_trainee(ctx, "tara")["currency_status"] == "LAPSING"

    set_clock("2027-10-05T00:00:00Z")
    validate_success(
        api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD)
    )
    assert read_credential(ctx, "tara")["status"] == "EXPIRED"
    assert read_trainee(ctx, "tara")["currency_status"] == "LAPSED"


def test_renewal_from_expired_reopens_a_fresh_term_without_touching_issued_on(api):
    """PRD §3.6: "**Renewal** is available from `GRACE`, from `EXPIRED`, and from `ACTIVE`
    (an early renewal), and all three edges behave identically apart from their effect on the
    currency dimension."
    PRD §3.5: "Its `issued_on` is stamped from the logical clock and never changes again, not
    even across renewals, while `term_start_on` is also set to that instant but is reset on
    every later renewal or reinstatement."
    PRD §3.6: "Renewal from `GRACE` also moves the trainee's `currency_status` `LAPSING →
    CURRENT`; renewal from `EXPIRED` moves it `LAPSED → CURRENT`; renewal from `ACTIVE` leaves
    it `CURRENT`."

    Design: Difficulty/non_linear_state_machine/credential_cycles_active_grace_expired_and_back_to_active
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=8.0, role_played="LOGISTICS", key="drill1",
        title="Drill 1", starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
        accept_at="2026-09-01T14:00:00Z",
    )
    set_clock("2027-08-06T00:00:00Z")
    validate_success(api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD))
    set_clock("2027-10-05T00:00:00Z")
    validate_success(api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD))
    assert read_credential(ctx, "tara")["status"] == "EXPIRED"

    renewed = validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "RENEW"}, COORD
        )
    )
    assert renewed["status"] == "ACTIVE", "EXPIRED is not terminal - the cycle closes"
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"
    assert renewed["reinstatement_count"] == 1
    assert_instant(renewed["term_start_on"], "2027-10-05T00:00:00Z", "term_start_on")
    # Exactly 8.0 hours leaves no surplus, so the new term is the bare 365-day base.
    assert_instant(renewed["expires_on"], "2028-10-04T00:00:00Z", "expires_on")
    assert_instant(renewed["issued_on"], "2026-08-05T16:00:00Z", "issued_on")


def test_renewal_below_the_refresher_requirement_is_refused(api):
    """PRD §3.6: "Every renewal requires the trainee to stand at `GRADUATED` and requires
    `refresher_hours_in_term` to be greater than or equal to `required_refresher_hours` —
    hours landing exactly on the requirement qualify, and only a strictly smaller figure is
    refused, with `ERR_REFRESHER_HOURS_INSUFFICIENT` and HTTP 422, in which case nothing
    further is executed."

    Design: Difficulty/boundary_precision_check/refresher_hours_exactly_at_requirement_permits_renewal
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=7.9, role_played="LOGISTICS", key="drill1",
        title="Drill 1", starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
        accept_at="2026-09-01T14:00:00Z",
    )
    set_clock("2026-11-01T00:00:00Z")

    validate_error(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "RENEW"}, COORD
        ),
        ApiErrorId.ERR_REFRESHER_HOURS_INSUFFICIENT.value,
    )

    credential = read_credential(ctx, "tara")
    assert_hours(credential["refresher_hours_in_term"], 7.9, "refresher_hours_in_term")
    assert credential["status"] == "ACTIVE"
    assert credential["reinstatement_count"] == 0


def test_refresher_hours_landing_exactly_on_the_requirement_permit_renewal(api):
    """PRD §3.6: "Every renewal requires the trainee to stand at `GRADUATED` and requires
    `refresher_hours_in_term` to be greater than or equal to `required_refresher_hours` —
    hours landing exactly on the requirement qualify, and only a strictly smaller figure is
    refused, with `ERR_REFRESHER_HOURS_INSUFFICIENT` and HTTP 422, in which case nothing
    further is executed."
    PRD §3.8: "Each crediting adds the credited hours to that trainee's credential
    `refresher_hours_in_term` when the credential's term window contains the crediting
    instant, and recomputes that trainee's `last_qualifying_activity_at` and
    `readiness_score`."

    Design: Difficulty/boundary_precision_check/refresher_hours_exactly_at_requirement_permits_renewal
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=7.9, role_played="LOGISTICS", key="drill1",
        title="Drill 1", starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
        accept_at="2026-09-01T14:00:00Z",
    )
    set_clock("2026-11-01T00:00:00Z")
    validate_error(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "RENEW"}, COORD
        ),
        ApiErrorId.ERR_REFRESHER_HOURS_INSUFFICIENT.value,
    )

    credit_refresher_hours(
        ctx, "tara", base_credit_hours=0.1, role_played="LOGISTICS", key="drill2",
        title="Drill 2", starts_at="2026-12-01T08:00:00Z", ends_at="2026-12-01T09:00:00Z",
        accept_at="2026-12-01T10:00:00Z",
    )
    assert_hours(
        read_credential(ctx, "tara")["refresher_hours_in_term"], 8.0,
        "refresher_hours_in_term",
    )

    set_clock("2027-01-01T00:00:00Z")
    renewed = validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "RENEW"}, COORD
        )
    )
    assert renewed["reinstatement_count"] == 1
    assert_instant(renewed["term_start_on"], "2027-01-01T00:00:00Z", "term_start_on")
    assert_instant(renewed["expires_on"], "2028-01-01T00:00:00Z", "expires_on")
    assert_hours(renewed["refresher_hours_in_term"], 0.0, "refresher_hours_in_term")


def test_suspension_lapses_currency_while_enrollment_stands_still(api):
    """PRD §3.6: "**Suspension** moves the credential `ACTIVE → SUSPENDED`, either because a
    coordinator asked for it or because the trainee was demoted out of graduation by a voided
    completion. It carries three consequences: the trainee's `currency_status` moves `CURRENT
    → LAPSED`; every roster assignment of that trainee standing at `NOTIFIED` or `ACCEPTED`
    whose activation stands at `REQUESTED`, `ROSTERED`, or `ACTIVATED` moves to `WITHDRAWN`;
    and each affected activation recomputes `rostered_count`, `accepted_count`, and
    `fill_status`."
    PRD §3.6: "Reinstatement pointedly does **not** increase `reinstatement_count` — only
    renewal does — so a volunteer who is suspended and reinstated repeatedly never drifts into
    a stricter tier, while one who lets the card lapse and renews repeatedly does."

    Design: Difficulty/non_linear_state_machine/trainee_enrollment_and_currency_dimensions_advance_independently
    """
    ctx = setup_credentialed_trainees()
    credential_id = ctx["credentials"]["tara"]["id"]

    suspended = validate_success(
        api.credential_status_action(credential_id, {"action": "SUSPEND"}, COORD)
    )
    assert suspended["status"] == "SUSPENDED"
    trainee = read_trainee(ctx, "tara")
    assert trainee["currency_status"] == "LAPSED"
    assert trainee["enrollment_status"] == "GRADUATED", (
        "the enrollment axis is untouched by a currency move"
    )

    reinstated = validate_success(
        api.credential_status_action(credential_id, {"action": "REINSTATE"}, COORD)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["reinstatement_count"] == 0
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"


def test_withdrawing_a_graduate_leaves_their_currency_dimension_alone(api):
    """PRD §2.10: "A trainee carries **two parallel state dimensions on the same row**, and
    they advance independently."
    PRD §2.10: "The currency dimension is driven entirely by the credential machine and is
    never advanced by an enrollment action; conversely, no currency transition changes the
    enrollment dimension. A graduated volunteer may therefore be lapsed, and a withdrawn
    volunteer may remain current until their credential is actually revoked."
    PRD §3.2: "A trainee may be withdrawn from `APPLIED` with no ledger effect at all, from
    `WAITLISTED` with `seats_waitlisted` reduced by 1, or from `ENROLLED` or `GRADUATED`, in
    which case `seats_confirmed` falls by 1 and the program's `active_member_count` falls by 1."

    Design: Difficulty/non_linear_state_machine/trainee_enrollment_and_currency_dimensions_advance_independently
    """
    ctx = setup_credentialed_trainees()

    withdrawn = validate_success(
        api.trainee_enrollment(
            ctx["trainees"]["tara"]["id"], {"action": "WITHDRAW"}, COORD
        )
    )
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert withdrawn["currency_status"] == "CURRENT", (
        "a withdrawn volunteer stays current until the credential itself moves"
    )
    assert read_credential(ctx, "tara")["status"] == "ACTIVE"
    assert read_cohort(ctx)["seats_confirmed"] == 0
    assert read_program(ctx)["active_member_count"] == 0


def test_module_passes_before_the_term_opened_never_count_as_refresher_hours(api):
    """PRD §3.6: "The second is the sum of `credited_contact_hours` over that trainee's
    module completions standing at `PASSED` on modules whose `refresher_eligible` flag is
    true, again with `updated_at` inside the window."
    PRD §3.6: "Rows in any other state contribute nothing — registered or voided
    participations, and recorded, pending, or failed completions, are all worth zero — and
    rows dated before `term_start_on` are excluded even if they were never counted in an
    earlier term."

    Design: Corner/calculations/refresher_hours_exclude_passes_outside_the_current_term
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    credit_refresher_hours(
        ctx, "tara", base_credit_hours=2.0, role_played="LOGISTICS", key="drill1",
        title="Drill 1", starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
        accept_at="2026-09-01T14:00:00Z",
    )

    credential = read_credential(ctx, "tara")
    assert_instant(credential["term_start_on"], "2026-08-05T16:00:00Z", "term_start_on")
    assert_hours(credential["refresher_hours_in_term"], 2.0, "refresher_hours_in_term")
    assert_hours(credential["required_refresher_hours"], 8.0, "required_refresher_hours")
    assert credential["renewal_tier"] == "STANDARD"
    assert_hours(
        read_trainee(ctx, "tara")["earned_contact_hours"], 10.0, "earned_contact_hours"
    )


def test_replaying_the_currency_sweep_at_the_same_clock_changes_nothing(api):
    """PRD §3.6: "A coordinator-only operational sweep, scoped to a `program_id`, advances
    the passage of time for one program at the current logical clock and reports four figures:
    `swept_credential_count` for the credentials it examined, `graced_count` and
    `expired_count` for the credentials it moved, and `no_response_count` for the call-out
    notifications it timed out."
    PRD §3.6: "A credential standing at `ACTIVE` whose `expires_on` the clock has reached or
    passed, while the clock is still strictly before `grace_ends_on`, moves `ACTIVE → GRACE`
    and mirrors the trainee's `currency_status` `CURRENT → LAPSING`."

    Design: Corner/cross_cutting_layers/currency_sweep_is_stable_when_replayed_at_the_same_clock
    """
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    set_clock("2027-08-06T00:00:00Z")

    first = validate_success(
        api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD)
    )
    assert first["swept_credential_count"] == 1
    assert first["graced_count"] == 1
    assert first["expired_count"] == 0
    assert first["no_response_count"] == 0
    assert read_credential(ctx, "tara")["status"] == "GRACE"
    assert read_trainee(ctx, "tara")["currency_status"] == "LAPSING"

    second = validate_success(
        api.run_currency_sweep({"program_id": ctx["program"]["id"]}, COORD)
    )
    assert second["graced_count"] == 0
    assert second["expired_count"] == 0

    credential = read_credential(ctx, "tara")
    assert credential["status"] == "GRACE"
    assert read_trainee(ctx, "tara")["currency_status"] == "LAPSING"
    assert_instant(credential["expires_on"], "2027-08-05T16:00:00Z", "expires_on")
    assert_instant(credential["grace_ends_on"], "2027-10-04T16:00:00Z", "grace_ends_on")


def test_revoking_a_credential_unwinds_the_open_call_out_commitment(api):
    """PRD §3.6: "**Revocation** moves the credential to `REVOKED` from any live state,
    drives the trainee's `currency_status` to `REVOKED`, withdraws every roster assignment of
    that trainee standing at `NOTIFIED` or `ACCEPTED`, and has each affected activation
    recompute its counts and `fill_status`."
    PRD §3.9: "The activation's `response_deadline_at` is stamped as the logical clock plus
    the window its `severity` earns: four hours for `ROUTINE`, two hours for `URGENT`, and one
    hour for `CRITICAL`."

    Design: Corner/state_machines/revoking_a_credential_compensates_open_roster_commitments
    """
    ctx = setup_rostered_activation(severity="URGENT", requested_responders=1)
    assignment = ctx["assignments"]["tara"]
    activation = read_activation(ctx)
    assert_instant(activation["response_deadline_at"], "2026-08-05T17:00:00Z",
                   "response_deadline_at")

    revoked = validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "REVOKE"}, COORD
        )
    )
    assert revoked["status"] == "REVOKED"

    trainee = read_trainee(ctx, "tara")
    assert trainee["currency_status"] == "REVOKED"
    assert trainee["enrollment_status"] == "GRADUATED"

    assert read_assignment(ctx, assignment)["status"] == "WITHDRAWN"
    activation = read_activation(ctx)
    assert activation["rostered_count"] == 0
    assert activation["fill_status"] == "UNFILLED"
