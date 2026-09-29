"""Package and contract ledgers: the cancellation window, conservation, freezes and sweeps."""
from test_helpers import (
    advance_clock,
    create_clearance_document,
    create_compliant_coach,
    create_draft_contract,
    deliver_session,
    enroll_athlete,
    fetch_athlete,
    fetch_certification,
    fetch_clearance_document,
    fetch_enrollment,
    fetch_group_session,
    fetch_membership_package,
    fetch_staff_member,
    fetch_team_contract,
    register_athlete,
    run_movement_screen,
    sell_package,
    setup_athlete_on_medical_hold,
    setup_cleared_athlete,
    setup_session_with_coach,
    validate_error,
    validate_success,
)


def test_01_a_cancellation_exactly_twenty_four_hours_out_refunds_the_credit(
        api, front_desk_headers):
    """The window is inclusive at its own edge, so equality refunds rather than forfeits.

    "The late-cancellation window is 24 hours."

    "When the gap between the session's `start_at` and the current logical clock is 24
    hours **or more**, the row becomes `CANCELED` with `cancel_reason` of
    `ATHLETE_REQUEST` and the credit is fully refunded: a package's
    `sessions_reserved` falls by one and `sessions_remaining` rises by one, returning a
    `DEPLETED` package to `ACTIVE`; a contract's `sessions_reserved` falls by one and
    `sessions_available` rises by one, with `offsite_sessions_used` also decremented
    for an offsite session."

    Design: Difficulty/boundary_precision_check/cancellation_exactly_at_late_cancel_window_boundary_refunds_package_credit
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Boundary Canceller",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Boundary")
    package = sell_package(athlete["id"], sessions_purchased=1, price_cents=12000,
                           expires_on="2026-12-31")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"],
                                funding_preference="PACKAGE_ONLY")
    assert enrollment["funding_source"] == "MEMBERSHIP_PACKAGE"
    reserved = fetch_membership_package(package["id"])
    assert reserved["status"] == "DEPLETED"
    assert reserved["sessions_remaining"] == 0
    assert reserved["sessions_reserved"] == 1

    advance_clock("2026-08-10T10:00:00Z")

    canceled = validate_success(api.cancel_enrollment(enrollment["id"],
                                                     front_desk_headers))

    assert canceled["status"] == "CANCELED"
    assert canceled["status"] != "LATE_CANCEL", \
        "twenty-four hours exactly is inside the refunding branch"
    assert canceled["cancel_reason"] == "ATHLETE_REQUEST"
    assert canceled["station_number"] is None
    refunded = fetch_membership_package(package["id"])
    assert refunded["status"] == "ACTIVE"
    assert refunded["sessions_remaining"] == 1
    assert refunded["sessions_reserved"] == 0
    assert refunded["sessions_forfeited"] == 0
    assert refunded["sessions_consumed"] == 0
    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_02_a_cancellation_a_few_hours_later_forfeits_the_same_credit(
        api, front_desk_headers):
    """Sixteen hours out is inside the window, so the credit is lost.

    "When that gap is **less than** 24 hours, the row becomes `LATE_CANCEL` instead,
    still with `cancel_reason` of `ATHLETE_REQUEST`, and the credit is forfeited rather
    than refunded: a package's `sessions_reserved` falls by one and
    `sessions_forfeited` rises by one, while a contract's `sessions_reserved` falls by
    one and `sessions_delivered` rises by one — the facility counts the slot as
    delivered because the coach's time was reserved."

    "No strike is recorded and `no_show_fee_cents` stays 0."

    Design: Difficulty/boundary_precision_check/cancellation_exactly_at_late_cancel_window_boundary_refunds_package_credit
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Late Canceller",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Boundary")
    package = sell_package(athlete["id"], sessions_purchased=1, price_cents=12000,
                           expires_on="2026-12-31")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"],
                                funding_preference="PACKAGE_ONLY")

    advance_clock("2026-08-10T18:00:00Z")

    canceled = validate_success(api.cancel_enrollment(enrollment["id"],
                                                      front_desk_headers))

    assert canceled["status"] == "LATE_CANCEL"
    assert canceled["cancel_reason"] == "ATHLETE_REQUEST"
    assert canceled["no_show_fee_cents"] == 0
    forfeited = fetch_membership_package(package["id"])
    assert forfeited["sessions_reserved"] == 0
    assert forfeited["sessions_forfeited"] == 1
    assert forfeited["sessions_remaining"] == 0
    assert forfeited["status"] == "DEPLETED", \
        "a forfeit restores no credit, so the depleted ledger stays depleted"
    assert fetch_athlete(athlete["id"])["no_show_count"] == 0


def test_03_a_timely_cancellation_returns_a_credit_to_the_remaining_bucket(
        api, front_desk_headers):
    """Two reservations deplete the package, and one refund reopens it.

    "The four spend counters plus `sessions_remaining` form a **conservation
    identity**: every credit ever purchased is at all times either remaining, reserved
    by a held enrollment, consumed by an attended session, or forfeited."

    "A package moves `ACTIVE → DEPLETED` at the moment a reservation takes its last
    remaining credit, leaving `sessions_remaining` at 0, and moves `DEPLETED → ACTIVE`
    again as soon as a refund — from a timely enrollment cancellation, a suspension
    cascade, or a session cancellation — restores at least one credit."

    Design: Difficulty/compensating_invariant/package_credit_ledger_conserved_across_reserve_deplete_refund_and_consume
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Ledger Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Ledger")
    package = sell_package(athlete["id"], sessions_purchased=2, price_cents=24000,
                           expires_on="2026-12-31")
    first = setup_session_with_coach(
        staff["id"], start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        station_count=3, max_athletes=8)
    second = setup_session_with_coach(
        staff["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        station_count=3, max_athletes=8)

    enroll_athlete(athlete["id"], first["id"], funding_preference="PACKAGE_ONLY")
    held = enroll_athlete(athlete["id"], second["id"],
                          funding_preference="PACKAGE_ONLY")

    depleted = fetch_membership_package(package["id"])
    assert depleted["status"] == "DEPLETED"
    assert depleted["sessions_remaining"] == 0
    assert depleted["sessions_reserved"] == 2
    assert (depleted["sessions_remaining"] + depleted["sessions_reserved"]
            + depleted["sessions_consumed"] + depleted["sessions_forfeited"]) == 2

    validate_success(api.cancel_enrollment(held["id"], front_desk_headers))

    reopened = fetch_membership_package(package["id"])
    assert reopened["status"] == "ACTIVE"
    assert reopened["sessions_remaining"] == 1
    assert reopened["sessions_reserved"] == 1
    assert reopened["sessions_forfeited"] == 0
    assert (reopened["sessions_remaining"] + reopened["sessions_reserved"]
            + reopened["sessions_consumed"] + reopened["sessions_forfeited"]) == 2


def test_04_attendance_moves_the_last_held_credit_into_the_consumed_bucket(
        api, front_desk_headers):
    """Reserve, deplete, refund and consume all conserve the two purchased credits.

    "Credits move between these buckets and are never created or destroyed.
    Reservation moves a credit from `sessions_remaining` to `sessions_reserved`;
    attendance moves it from `sessions_reserved` to `sessions_consumed`; a no-show or a
    late cancellation moves it from `sessions_reserved` to `sessions_forfeited`; a
    refund moves it from `sessions_reserved` back to `sessions_remaining`; and an
    expiry sweep moves the whole remainder from `sessions_remaining` to
    `sessions_forfeited`."

    Design: Difficulty/compensating_invariant/package_credit_ledger_conserved_across_reserve_deplete_refund_and_consume
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides={"full_name": "Ledger Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Ledger")
    package = sell_package(athlete["id"], sessions_purchased=2, price_cents=24000,
                           expires_on="2026-12-31")
    attended_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        station_count=3, max_athletes=8)
    dropped_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        station_count=3, max_athletes=8)
    kept = enroll_athlete(athlete["id"], attended_session["id"],
                          funding_preference="PACKAGE_ONLY")
    dropped = enroll_athlete(athlete["id"], dropped_session["id"],
                             funding_preference="PACKAGE_ONLY")
    validate_success(api.cancel_enrollment(dropped["id"], front_desk_headers))

    deliver_session(attended_session, coach_headers,
                    attend_enrollment_ids=[kept["id"]])

    settled = fetch_membership_package(package["id"])
    assert settled["sessions_remaining"] == 1
    assert settled["sessions_reserved"] == 0
    assert settled["sessions_consumed"] == 1
    assert settled["sessions_forfeited"] == 0
    assert (settled["sessions_remaining"] + settled["sessions_reserved"]
            + settled["sessions_consumed"]
            + settled["sessions_forfeited"]) == settled["sessions_purchased"]
    assert settled["status"] == "ACTIVE"
    assert settled["effective_expires_on"] == "2026-12-31"

    consumed_row = fetch_enrollment(kept["id"])
    assert consumed_row["status"] == "ATTENDED"
    assert consumed_row["funding_source"] == "MEMBERSHIP_PACKAGE"
    assert consumed_row["charge_cents"] == 0
    assert fetch_enrollment(dropped["id"])["status"] == "CANCELED"
    reread_athlete = fetch_athlete(athlete["id"])
    assert reread_athlete["attended_count"] == 1
    assert reread_athlete["no_show_count"] == 0


def test_05_an_active_package_cannot_be_unfrozen(api, front_desk_headers):
    """Unfreezing is declared from FROZEN alone, so an active package is refused.

    "Only a `FROZEN` package can be unfrozen; an `ACTIVE` package cannot be unfrozen
    and a `FROZEN` package cannot be frozen again, both of which return
    `ERR_INVALID_STATE`, while any operation against an `EXPIRED` package returns
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/membership_package_unfreeze_from_active_rejected
    """
    athlete = register_athlete(full_name="Never Frozen Athlete",
                               date_of_birth="2009-02-02")
    package = sell_package(athlete["id"], sessions_purchased=5, price_cents=20000,
                           expires_on="2026-12-31")
    assert package["status"] == "ACTIVE"

    validate_error(
        api.unfreeze_membership_package(package["id"], front_desk_headers),
        "ERR_INVALID_STATE", expected_status=409)

    reread = fetch_membership_package(package["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["frozen_at"] is None
    assert reread["frozen_days_total"] == 0
    assert reread["effective_expires_on"] == "2026-12-31"


def test_06_a_late_canceled_enrollment_refuses_every_further_transition(
        api, front_desk_headers):
    """The second cancellation addresses a terminal row and is refused as such.

    "`NO_SHOW`, `LATE_CANCEL` and `CANCELED` are all terminal enrollment states."

    "A request against a terminal state returns `ERR_ALREADY_TERMINAL`; any other
    undeclared source state returns `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_terminal_late_cancel_locks_further_transitions
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Terminal Row Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Terminal")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    advance_clock("2026-08-10T18:00:00Z")

    first = validate_success(api.cancel_enrollment(enrollment["id"],
                                                   front_desk_headers))
    assert first["status"] == "LATE_CANCEL"

    validate_error(api.cancel_enrollment(enrollment["id"], front_desk_headers),
                   "ERR_ALREADY_TERMINAL", expected_status=409)

    assert fetch_enrollment(enrollment["id"])["status"] == "LATE_CANCEL"


def test_07_a_contract_can_only_be_activated_once(api, performance_director_headers):
    """Activation is declared from DRAFT, so the second attempt finds the wrong state.

    "Activation by the `PerformanceDirector` requires the contract to be `DRAFT` and
    its `term_end` to be later than the current logical date; on success `status` moves
    `DRAFT → ACTIVE` and `sessions_available` is set to `contracted_sessions`."

    "A request against a terminal state returns `ERR_ALREADY_TERMINAL`; any other
    undeclared source state returns `ERR_INVALID_STATE`."

    Design: Corner/state_machines/team_contract_activate_twice_second_attempt_rejected
    """
    contract = create_draft_contract(
        organization_name="Twice Activated Club", organization_type="CLUB",
        contracted_sessions=10, base_rate_cents=18000, offsite_allowance=0,
        term_start="2026-01-01", term_end="2026-12-31")
    assert contract["status"] == "DRAFT"
    draft_version = contract["version"]

    activated = validate_success(api.activate_team_contract(
        contract["id"], performance_director_headers))
    assert activated["status"] == "ACTIVE"
    assert activated["sessions_available"] == 10
    assert activated["version"] == draft_version + 1

    validate_error(api.activate_team_contract(contract["id"],
                                              performance_director_headers),
                   "ERR_INVALID_STATE", expected_status=409)

    reread = fetch_team_contract(contract["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["sessions_available"] == 10
    assert reread["version"] == draft_version + 1, \
        "the refused second activation mutated nothing"


def test_08_cancelling_a_session_refunds_only_the_rows_that_are_still_held(
        api, front_desk_headers, performance_director_headers):
    """One athlete already forfeited their credit, and the session cancellation leaves it lost.

    "Both source states drive `session_status` to `CANCELED`, which is terminal, and
    both run the same refund chain: every enrollment on the session whose `status` is
    `RESERVED` or `WAITLISTED` becomes `CANCELED` with an enrollment-level
    `cancel_reason` of `SESSION_CANCELED`, and its funding is returned to its source —
    a package credit restored with `DEPLETED` reverting to `ACTIVE` where applicable,
    or a contract slot restored including the `offsite_sessions_used` decrement for an
    offsite session."

    "No strike is recorded and no fee is charged against any athlete."

    Design: Corner/state_machines/session_cancel_only_refunds_non_terminal_enrollments
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Washout")
    stayer = register_athlete(full_name="Session Cancel Stayer",
                              date_of_birth="2009-02-02")
    leaver = register_athlete(full_name="Session Cancel Leaver",
                              date_of_birth="2009-03-03")
    for athlete in (stayer, leaver):
        run_movement_screen(athlete["id"], coach_headers)
    package_a = sell_package(stayer["id"], sessions_purchased=3, price_cents=12000,
                             expires_on="2026-12-31")
    package_b = sell_package(leaver["id"], sessions_purchased=3, price_cents=12000,
                             expires_on="2026-12-31")
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=8)
    held = enroll_athlete(stayer["id"], session["id"],
                          funding_preference="PACKAGE_ONLY")
    forfeiting = enroll_athlete(leaver["id"], session["id"],
                                funding_preference="PACKAGE_ONLY")

    advance_clock("2026-08-24T18:00:00Z")
    late = validate_success(api.cancel_enrollment(forfeiting["id"],
                                                  front_desk_headers))
    assert late["status"] == "LATE_CANCEL"
    assert fetch_membership_package(package_b["id"])["sessions_forfeited"] == 1

    canceled = validate_success(api.cancel_group_session(
        session["id"], {"cancel_reason": "Facility flooding"},
        performance_director_headers))

    assert canceled["session_status"] == "CANCELED"
    refunded_row = fetch_enrollment(held["id"])
    assert refunded_row["status"] == "CANCELED"
    assert refunded_row["cancel_reason"] == "SESSION_CANCELED"
    assert refunded_row["no_show_fee_cents"] == 0
    restored = fetch_membership_package(package_a["id"])
    assert restored["sessions_remaining"] == 3
    assert restored["sessions_reserved"] == 0
    assert restored["sessions_forfeited"] == 0

    untouched_row = fetch_enrollment(forfeiting["id"])
    assert untouched_row["status"] == "LATE_CANCEL", \
        "a terminal row is outside the refund chain"
    assert untouched_row["cancel_reason"] == "ATHLETE_REQUEST"
    untouched_package = fetch_membership_package(package_b["id"])
    assert untouched_package["sessions_remaining"] == 2
    assert untouched_package["sessions_forfeited"] == 1
    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_09_a_partial_frozen_day_is_rounded_up_into_the_effective_expiry(
        api, front_desk_headers):
    """Three and a quarter frozen days credit four whole days of expiry.

    "Unfreezing returns `status` to `ACTIVE`, clears `frozen_at` to null, and credits
    the frozen time back to the athlete: the elapsed seconds between `frozen_at` and
    the unfreeze instant are divided by 86,400 and **rounded up**, so any partial day
    counts as a full day, and the result is added to `frozen_days_total`."

    "`effective_expires_on` is then recomputed as `expires_on` advanced by
    `frozen_days_total` whole days."

    Design: Corner/calculations/package_unfreeze_ceils_partial_frozen_day_into_effective_expiry
    """
    athlete = register_athlete(full_name="Freeze Credit Athlete",
                               date_of_birth="2009-02-02")
    package = sell_package(athlete["id"], sessions_purchased=5, price_cents=20000,
                           expires_on="2026-09-30")

    frozen = validate_success(api.freeze_membership_package(package["id"],
                                                            front_desk_headers))
    assert frozen["status"] == "FROZEN"
    assert frozen["frozen_at"] is not None
    assert frozen["effective_expires_on"] == "2026-09-30"

    advance_clock("2026-08-04T06:00:00Z")
    thawed = validate_success(api.unfreeze_membership_package(package["id"],
                                                              front_desk_headers))

    assert thawed["status"] == "ACTIVE"
    assert thawed["frozen_at"] is None
    assert thawed["frozen_days_total"] == 4, \
        "three and a quarter days of freeze counts as four whole days"
    assert thawed["expires_on"] == "2026-09-30"
    assert thawed["effective_expires_on"] == "2026-10-04"
    assert fetch_membership_package(package["id"])["effective_expires_on"] == "2026-10-04"


def test_10_a_contract_athlete_link_waits_for_activation(
        api, performance_director_headers):
    """The same link is refused while the contract is a draft and accepted once active.

    "Linking a roster athlete to a contract — done by the `PerformanceDirector` or
    `FrontDesk` with the athlete's `athlete_id` — likewise requires the contract to be
    `ACTIVE`, failing which the link is refused with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Corner/endpoints/team_contract_athlete_link_requires_active_contract
    """
    athlete = register_athlete(full_name="Draft Link Athlete",
                               date_of_birth="2009-02-02")
    contract = create_draft_contract(
        organization_name="Draft Link School", organization_type="SCHOOL",
        contracted_sessions=8, base_rate_cents=18000, offsite_allowance=0,
        term_start="2026-01-01", term_end="2026-12-31")

    validate_error(
        api.link_contract_athlete(contract["id"], {"athlete_id": athlete["id"]},
                                  performance_director_headers),
        "ERR_CONTRACT_NOT_ACTIVE", expected_status=422)
    assert fetch_athlete(athlete["id"])["team_contract_id"] is None

    activated = validate_success(api.activate_team_contract(
        contract["id"], performance_director_headers))
    assert activated["status"] == "ACTIVE"
    assert activated["sessions_available"] == 8

    linked = validate_success(api.link_contract_athlete(
        contract["id"], {"athlete_id": athlete["id"]},
        performance_director_headers))

    assert linked["team_contract_id"] == contract["id"]
    assert fetch_athlete(athlete["id"])["team_contract_id"] == contract["id"]


def test_11_the_clock_sweep_expires_documents_and_packages_but_never_certifications(
        api, medical_provider_headers):
    """One advance walks the pinned order and reports one document and one package.

    "First, every `ClearanceDocument` whose `status` is `SIGNED` and whose
    `expires_on` falls earlier than the new logical date moves to `EXPIRED`."

    "Second, every `MembershipPackage` whose `status` is `ACTIVE`, `FROZEN`, or
    `DEPLETED` and whose `effective_expires_on` falls earlier than the new logical date
    moves to `EXPIRED`."

    "On expiry the unspent remainder is forfeited: the value of `sessions_remaining` is
    added to `sessions_forfeited` and `sessions_remaining` is then set to zero, which
    preserves the credit-conservation identity described in §3.6."

    "Third — and this is deliberate — `Certification` rows are **not** touched."

    Design: Corner/cross_cutting_layers/clock_advance_sweeps_signed_clearances_then_packages_in_pinned_order
    """
    staff, certification, _coach_headers = create_compliant_coach(
        full_name="Coach Unswept", cert_code="CSCS", issued_on="2023-08-02",
        cert_expires_on="2026-08-02")
    athlete, _staff, _coach = setup_athlete_on_medical_hold(
        athlete_overrides={"full_name": "Swept Documents Athlete",
                           "date_of_birth": "2009-02-02"})
    document = create_clearance_document(
        athlete["id"], "MEDICAL_HOLD_RELEASE", expires_on="2026-08-05",
        rts_plan_id=None, stage_number=None)
    signed = validate_success(api.sign_clearance_document(
        document["id"], {"provider_license_id": "MD-31-8842"},
        medical_provider_headers))
    assert signed["status"] == "SIGNED"
    package = sell_package(athlete["id"], sessions_purchased=2, price_cents=9000,
                           expires_on="2026-08-06")

    swept = advance_clock("2026-08-15T09:00:00Z")

    assert swept["current_utc"] == "2026-08-15T09:00:00Z"
    assert swept["clearance_documents_expired_count"] == 1
    assert swept["packages_expired_count"] == 1
    assert fetch_clearance_document(document["id"])["status"] == "EXPIRED"
    expired_package = fetch_membership_package(package["id"])
    assert expired_package["status"] == "EXPIRED"
    assert expired_package["sessions_remaining"] == 0
    assert expired_package["sessions_forfeited"] == 2

    assert fetch_certification(certification["id"])["status"] == "VALID", \
        "advancing the clock never lapses a certification"
    reread_staff = fetch_staff_member(staff["id"])
    assert reread_staff["credential_status"] == "COMPLIANT"
    assert reread_staff["valid_certification_count"] == 1


def test_12_the_logical_clock_refuses_to_run_backwards(api,
                                                       performance_director_headers):
    """An earlier instant is refused while the identical instant is a no-op sweep.

    "The clock is monotonic: an instant earlier than the current logical clock is
    refused with `ERR_CLOCK_REWIND_FORBIDDEN`, while an instant exactly equal to the
    current value is accepted and processed as a no-op sweep."

    Design: Corner/errors/clock_rewind_request_returns_clock_rewind_forbidden
    """
    advanced = advance_clock("2026-08-10T09:00:00Z")
    assert advanced["current_utc"] == "2026-08-10T09:00:00Z"

    validate_error(api.set_clock("2026-08-09T09:00:00Z",
                                 performance_director_headers),
                   "ERR_CLOCK_REWIND_FORBIDDEN", expected_status=422)

    repeated = validate_success(api.set_clock("2026-08-10T09:00:00Z",
                                              performance_director_headers))
    assert repeated["current_utc"] == "2026-08-10T09:00:00Z"
    assert repeated["clearance_documents_expired_count"] == 0
    assert repeated["packages_expired_count"] == 0
