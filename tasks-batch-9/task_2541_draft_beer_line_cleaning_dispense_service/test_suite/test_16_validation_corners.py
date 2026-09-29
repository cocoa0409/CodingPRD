"""Corner cases in the validation ladder: aggregate rules, scoped uniqueness keys, date and
hour boundaries, and checks that only surface once the check above them has passed."""

from test_helpers import (
    AUDITOR_HEADERS,
    ApiErrorId,
    BalanceRecordStatus,
    BalanceState,
    ComplianceResult,
    DISPATCH_HEADERS,
    GlycolStatus,
    SettlementState,
    VerificationStatus,
    VisitKind,
    WorkStatus,
    assert_instant,
    assert_liters,
    assert_pct,
    assert_psi,
    assert_score,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)


def test_the_third_line_breaches_a_cap_that_no_single_payload_violates(api):
    """PRD §3.2: "And the register must stay inside the commercial deal: if the number of
    lines already registered on the account plus this one would exceed the active contract's
    `contracted_line_count`, the registration is refused with
    `ERR_CONTRACT_LINE_LIMIT_EXCEEDED`."

    Design: Corner/validations/corner_third_line_breaches_the_contract_cap_although_each_line_is_valid
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(
        api, venue_name="Two Tap Bar", contracted_line_count=2, lines=()
    )
    account_id = venue["account"]["id"]

    first = fixtures.create_beer_line(api, account_id, line_number=1)
    second = fixtures.create_beer_line(
        api, account_id, line_number=2, beer_style_group="LAGER",
        average_daily_throughput_liters=10.0,
    )

    validate_error(
        api.create_beer_line(
            factories.beer_line_payload(
                account_id,
                line_number=3,
                run_length_feet=15,
                vertical_rise_feet=3,
                average_daily_throughput_liters=8.0,
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.CONTRACT_LINE_LIMIT_EXCEEDED,
        422,
    )

    rows, meta = validate_paginated(
        api.list_beer_lines(DISPATCH_HEADERS, account_id=account_id, limit=10, offset=0)
    )
    assert meta["total_count"] == 2
    assert sorted(row["line_number"] for row in rows) == [1, 2]
    assert first["line_number"] == 1
    assert second["line_number"] == 2


def test_the_same_line_number_is_a_collision_only_within_one_venue(api):
    """PRD §3.2: "Separately, `line_number` must be unique among that account's lines counting
    **every** status, including lines currently out of service; a collision is refused with
    `ERR_DUPLICATE_LINE_NUMBER`."

    Design: Corner/validations/corner_line_number_uniqueness_is_scoped_to_one_account
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    first_venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse")
    second_venue = fixtures.onboard_venue(api, venue_name="Harbor Taproom", lines=())
    incumbent = first_venue["lines"][0]
    duplicate_body = dict(
        line_number=1,
        run_length_feet=15,
        vertical_rise_feet=3,
        inner_diameter_inches=0.25,
        beer_style_group="LAGER",
        average_daily_throughput_liters=6.0,
    )

    validate_error(
        api.create_beer_line(
            factories.beer_line_payload(first_venue["account"]["id"], **duplicate_body),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.DUPLICATE_LINE_NUMBER,
        409,
    )
    accepted = get_success_data(
        api.create_beer_line(
            factories.beer_line_payload(second_venue["account"]["id"], **duplicate_body),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )

    assert accepted["line_number"] == 1
    assert accepted["account_id"] == second_venue["account"]["id"]
    # The rejected duplicate did not overwrite the incumbent's geometry.
    assert fixtures.read_line(api, incumbent["id"])["inner_diameter_inches"] == 0.375


def test_the_waiver_opens_on_the_seventy_second_hour_and_not_a_minute_before(api):
    """PRD §3.7: "It moves `UNVERIFIED → WAIVED`, requires `work_status` to be
    `WORK_COMPLETE` (`ERR_WORK_NOT_COMPLETE`), and may not be exercised until 72 hours have
    passed since `work_completed_at` — the venue gets three days to sign — else
    `ERR_WAIVER_TOO_EARLY`."
    PRD §3.7: "On the waiver path only, a withholding is subtracted: take
    `billable_line_count` multiplied by the per-line amount, take ten per cent of that
    pre-withholding line total (a withholding of 1000 basis points), and truncate downward to
    whole cents so the rounding cent favours the venue."

    Design: Corner/validations/corner_waiver_at_seventy_one_hours_fifty_nine_is_early_and_at_seventy_two_is_allowed
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    visit_id = ground["visit"]["id"]
    fixtures.log_cleaning_cycle(
        api, visit_id, ground["line"]["id"], ground["lot"]["id"],
        ground["technician"]["id"], **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    closed = fixtures.complete_work_on(api, visit_id, ground["technician"]["id"])
    assert_instant(
        closed["work_completed_at"], "2026-08-05T10:00:00Z", label="work_completed_at"
    )

    fixtures.set_clock(api, "2026-08-08T09:59:00Z")
    validate_error(
        api.record_verification_waiver(
            visit_id, "No signer on site at 71:59.", AUDITOR_HEADERS
        ),
        ApiErrorId.WAIVER_TOO_EARLY,
        422,
    )
    held = fixtures.read_visit(api, visit_id)
    assert held["verification_status"] == VerificationStatus.UNVERIFIED
    assert held["settlement_state"] == SettlementState.UNSETTLED

    fixtures.set_clock(api, "2026-08-08T10:00:00Z")
    waived = fixtures.waive_verification(api, visit_id, "No signer on site at 72:00.")

    assert waived["verification_status"] == VerificationStatus.WAIVED
    # 4593 less ten per cent truncated to 459.
    assert waived["cleaning_subtotal_cents"] == 4134
    assert waived["settled_charge_cents"] == 11634


def test_a_lot_expiring_today_still_pours_while_yesterdays_lot_is_dead(api):
    """PRD §3.4: "The logical clock's current date must not be past the lot's `expires_on`, else
    `ERR_CHEMICAL_LOT_EXPIRED`; expired chemistry may never touch a line."

    Design: Corner/validations/corner_lot_expiring_today_is_still_usable_and_yesterdays_lot_is_not
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=(
            {"lot_code": "C-2001", "expires_on": "2026-08-04"},
            {"lot_code": "C-2002", "expires_on": "2026-08-05"},
        ),
        visit_clock="2026-08-05T09:00:00Z",
    )
    stale, edge = ground["lots"]
    visit_id = ground["visit"]["id"]
    line_id = ground["line"]["id"]

    # The clock reads 2026-08-05, one day past the stale lot's expiry date.
    validate_error(
        api.create_cleaning_cycle(
            factories.cleaning_cycle_payload(
                visit_id, line_id, stale["id"], **fixtures.PASSING_CAUSTIC_CYCLE
            ),
            ground["tech_headers"],
        ),
        ApiErrorId.CHEMICAL_LOT_EXPIRED,
        422,
    )
    assert_liters(fixtures.read_lot(api, stale["id"])["liters_remaining"], 20.0)

    # The same payload against the lot expiring exactly today is accepted.
    cycle = fixtures.log_cleaning_cycle(
        api, visit_id, line_id, edge["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    assert cycle["compliance_result"] == ComplianceResult.PASS
    assert_liters(fixtures.read_lot(api, edge["id"])["liters_remaining"], 19.690)


def test_the_pressure_tolerance_answers_first_and_the_blend_tolerance_only_after_it(api):
    """PRD §3.5: "Then, and only once the pressure tolerance has passed, the absolute difference
    between `proposed_co2_pct` and `required_co2_pct` must be at most 2.0 percentage points, else
    the proposal is refused with `ERR_GAS_BLEND_MISMATCH`."

    Design: Corner/validations/corner_pressure_check_settles_before_the_gas_blend_check_is_reached
    """
    ground = fixtures.setup_started_visit(api, venue_name="Anchor Alehouse", lot_specs=())
    visit_id = ground["visit"]["id"]
    line_id = ground["line"]["id"]
    opening_version = ground["line"]["version"]
    assert opening_version == 1

    # Wrong on both axes: 12.0 psi is 1.6 off the 13.60 restriction and 30.0 per cent is
    # 29.2 points off the 59.2 the blend needs.
    validate_error(
        api.create_balance_record(
            factories.balance_record_payload(
                visit_id, line_id, opening_version,
                measured_temp_f=40.0, proposed_applied_psi=12.0, proposed_co2_pct=30.0,
            ),
            ground["tech_headers"],
        ),
        ApiErrorId.PRESSURE_OUT_OF_BALANCE,
        422,
    )

    # Pressure now exact, so the blend check is finally reached.
    validate_error(
        api.create_balance_record(
            factories.balance_record_payload(
                visit_id, line_id, opening_version,
                measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=30.0,
            ),
            ground["tech_headers"],
        ),
        ApiErrorId.GAS_BLEND_MISMATCH,
        422,
    )

    # Neither refusal moved the line, so the opening token is still current.
    record = fixtures.propose_balance(
        api, visit_id, line_id, opening_version, ground["technician"]["id"],
        measured_temp_f=40.0, proposed_applied_psi=13.4, proposed_co2_pct=61.0,
    )

    assert record["status"] == BalanceRecordStatus.PROPOSED
    assert_psi(record["required_applied_psi"], 13.60)
    assert_pct(record["required_co2_pct"], 59.2)
    assert record["balance_state"] == BalanceState.RESTRICTION_HIGH
    assert fixtures.read_line(api, line_id)["version"] == 2


def test_a_glycol_visit_is_refused_at_the_direct_draw_venue_and_booked_at_the_chiller_venue(api):
    """PRD §3.3: "A `GLYCOL_MAINTENANCE` booking is only meaningful at a venue that actually has a
    chiller loop, so it requires the account's `glycol_system_present` to be true and a glycol loop
    to exist for that account; otherwise the booking is refused with `ERR_NO_GLYCOL_SYSTEM`."

    Design: Corner/validations/corner_glycol_maintenance_visit_depends_on_the_accounts_glycol_flag
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    direct = fixtures.onboard_venue(api, venue_name="Anchor Alehouse", lines=())
    chiller = fixtures.onboard_venue(
        api, venue_name="Cellar Cooler Pub", glycol_system_present=True, lines=()
    )
    technician = fixtures.create_technician(api)

    booking = factories.service_visit_payload(
        direct["account"]["id"], technician["id"], visit_kind=VisitKind.GLYCOL_MAINTENANCE
    )
    validate_error(
        api.create_service_visit(booking, DISPATCH_HEADERS),
        ApiErrorId.NO_GLYCOL_SYSTEM,
        422,
    )

    visit = fixtures.book_visit(
        api, chiller["account"]["id"], technician["id"],
        visit_kind=VisitKind.GLYCOL_MAINTENANCE,
    )
    assert visit["visit_kind"] == VisitKind.GLYCOL_MAINTENANCE
    assert visit["work_status"] == WorkStatus.SCHEDULED

    _, direct_meta = validate_paginated(
        api.list_glycol_loops(DISPATCH_HEADERS, account_id=direct["account"]["id"])
    )
    chiller_loops, chiller_meta = validate_paginated(
        api.list_glycol_loops(DISPATCH_HEADERS, account_id=chiller["account"]["id"])
    )

    assert direct_meta["total_count"] == 0
    assert chiller_meta["total_count"] == 1
    assert chiller_loops[0]["status"] == GlycolStatus.NORMAL
    assert_score(chiller_loops[0]["health_score"], 100.00)


def test_close_out_needs_one_posted_cycle_before_it_will_settle_a_charge(api):
    """PRD §3.7: "What counts as evidence depends on the `visit_kind`: a `ROUTINE_CLEANING` or
    `EMERGENCY_TROUBLESHOOT` visit requires at least one cycle record on the visit still `POSTED`,
    whereas a `GLYCOL_MAINTENANCE` visit requires at least one loop maintenance recorded during the
    visit, meaning the account's loop carries a `last_serviced_at` at or after the start of the
    visit's day."

    Design: Corner/validations/corner_completing_a_visit_with_no_cycle_is_refused_then_allowed_after_one
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    visit_id = ground["visit"]["id"]

    validate_error(
        api.complete_visit_work(visit_id, ground["tech_headers"]),
        ApiErrorId.NO_WORK_RECORDED,
        422,
    )
    held = fixtures.read_visit(api, visit_id)
    assert held["work_status"] == WorkStatus.IN_PROGRESS
    assert held["work_completed_at"] is None

    cycle = fixtures.log_cleaning_cycle(
        api, visit_id, ground["line"]["id"], ground["lot"]["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert cycle["compliance_result"] == ComplianceResult.PASS

    closed = fixtures.complete_work_on(api, visit_id, ground["technician"]["id"])

    assert closed["work_status"] == WorkStatus.WORK_COMPLETE
    assert closed["serviced_line_count"] == 1
    # 7500 base plus one line at 4175 x 1.10.
    assert closed["provisional_charge_cents"] == 12093
