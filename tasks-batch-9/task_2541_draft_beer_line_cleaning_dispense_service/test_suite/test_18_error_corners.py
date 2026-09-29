"""Corner cases in the error catalogue: uniqueness that ignores the payload's other fields,
refusals that must leave inventory untouched, boundaries that are refused one step out and
accepted on the edge, and a record frozen by settlement."""

from test_helpers import (
    AUDITOR_HEADERS,
    ApiErrorId,
    CertificationLevel,
    ChemicalType,
    ComplianceResult,
    DISPATCH_HEADERS,
    LotStatus,
    RecordStatus,
    SettlementState,
    TechnicianStatus,
    WorkStatus,
    assert_instant,
    assert_liters,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)

_ACID_CYCLE = {
    "chemical_type": ChemicalType.ACID,
    "contact_minutes": 12,
    "recirculation_temp_f": 75.0,
    "concentrate_liters_used": 0.35,
}


def test_a_lot_code_already_used_by_a_caustic_drum_is_closed_to_an_acid_drum(api):
    """PRD §3.4: "The payload declares the `chemical_type`, which is either `CAUSTIC` or `ACID`; the
    supplier's `lot_code`, which must be unique across every lot ever received regardless of that
    lot's current status, a collision being refused with `ERR_DUPLICATE_LOT_CODE`; the
    `concentration_pct_stock` active-ingredient percentage of the undiluted concentrate, between 1.0
    and 100.0 inclusive and held to one decimal place; the `liters_initial` volume received, which
    must be greater than zero and is held to three decimal places; and `expires_on`, the calendar
    expiry date."

    Design: Corner/errors/corner_lot_code_uniqueness_is_global_across_chemical_types
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    incumbent = fixtures.create_chemical_lot(api, lot_code="C-2001")

    # Nothing else about the two payloads matches; only the lot code collides.
    validate_error(
        api.create_chemical_lot(
            factories.chemical_lot_payload(
                chemical_type=ChemicalType.ACID, lot_code="C-2001",
                concentration_pct_stock=20.0, liters_initial=10.0, expires_on="2027-01-31",
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.DUPLICATE_LOT_CODE,
        409,
    )

    _, meta = validate_paginated(api.list_chemical_lots(DISPATCH_HEADERS))
    assert meta["total_count"] == 1

    reread = fixtures.read_lot(api, incumbent["id"])
    assert reread["chemical_type"] == ChemicalType.CAUSTIC
    assert reread["concentration_pct_stock"] == 45.0
    assert_liters(reread["liters_remaining"], 20.0)


def test_a_drained_quarantined_lot_is_released_only_after_a_void_refills_it(api):
    """PRD §3.4: "Releasing a quarantined lot additionally requires `liters_remaining` to be at
    least 0.05, otherwise the release is refused with `ERR_LOT_RELEASE_BLOCKED`."

    Design: Corner/errors/corner_drained_lot_can_be_quarantined_but_not_released_until_a_void_refills_it
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=({"lot_code": "L-9001", "liters_initial": 0.35},),
    )
    lot_id = ground["lot"]["id"]
    cycle = fixtures.log_cleaning_cycle(
        api, ground["visit"]["id"], ground["line"]["id"], lot_id, ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    # 0.350 less 0.310 leaves 0.040, under the 0.05 litre minimum usable volume.
    drained = fixtures.read_lot(api, lot_id)
    assert drained["status"] == LotStatus.DEPLETED
    assert_liters(drained["liters_remaining"], 0.040)

    pulled = get_success_data(
        api.set_chemical_lot_status(lot_id, LotStatus.QUARANTINED, AUDITOR_HEADERS)
    )
    assert pulled["status"] == LotStatus.QUARANTINED
    assert_liters(pulled["liters_remaining"], 0.040)

    validate_error(
        api.set_chemical_lot_status(lot_id, LotStatus.AVAILABLE, AUDITOR_HEADERS),
        ApiErrorId.LOT_RELEASE_BLOCKED,
        409,
    )

    fixtures.void_cycle(api, cycle["id"], "Logged against the wrong lot.")
    refilled = fixtures.read_lot(api, lot_id)
    assert_liters(refilled["liters_remaining"], 0.350)
    # The automatic revive edge runs only from DEPLETED, so the lot is still quarantined.
    assert refilled["status"] == LotStatus.QUARANTINED

    released = get_success_data(
        api.set_chemical_lot_status(lot_id, LotStatus.AVAILABLE, AUDITOR_HEADERS)
    )
    assert released["status"] == LotStatus.AVAILABLE
    assert_liters(released["liters_remaining"], 0.350)


def test_an_inactive_technician_cannot_be_booked_into_a_slot_an_active_one_takes(api):
    """PRD §3.3: "The named technician must be `ACTIVE`, else `ERR_TECHNICIAN_INACTIVE`."

    Design: Corner/errors/corner_booking_an_inactive_technician_is_refused_and_an_active_one_is_booked
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse", lines=())
    benched = fixtures.create_technician(
        api, full_name="Lee Park", certification_level=CertificationLevel.CERTIFIED,
        status=TechnicianStatus.INACTIVE,
    )
    working = fixtures.create_technician(api)
    assert benched["status"] == TechnicianStatus.INACTIVE

    validate_error(
        api.create_service_visit(
            factories.service_visit_payload(venue["account"]["id"], benched["id"]),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.TECHNICIAN_INACTIVE,
        409,
    )

    # The very same slot is free for the active technician, so the refusal was not a conflict.
    visit = fixtures.book_visit(api, venue["account"]["id"], working["id"])
    assert visit["technician_id"] == working["id"]
    assert visit["work_status"] == WorkStatus.SCHEDULED


def test_three_wrong_cycle_payloads_each_name_their_own_rule_and_spend_no_concentrate(api):
    """PRD §3.4: "The body's `chemical_type` must equal the lot's own `chemical_type`, else
    `ERR_CHEMICAL_TYPE_MISMATCH` — a caustic cycle cannot be logged against an acid lot."

    PRD §3.4: "The alternation rule must hold, else `ERR_CHEMICAL_PARITY_VIOLATION`: the body's
    `chemical_type` must differ from the line's `last_chemical_type`, and when `last_chemical_type`
    reads `NONE` the very first cycle in a line's life must be `CAUSTIC`."

    PRD §3.4: "The lot must hold enough concentrate: `liters_remaining` must be at least
    `concentrate_liters_used`, else `ERR_CHEMICAL_INSUFFICIENT_VOLUME`."

    Design: Corner/errors/corner_three_bad_cycle_payloads_each_report_their_own_code_and_draw_no_chemical
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=(
            {"lot_code": "C-2001"},
            {"chemical_type": ChemicalType.ACID, "lot_code": "A-3001",
             "concentration_pct_stock": 20.0, "liters_initial": 10.0},
            {"lot_code": "T-4001", "liters_initial": 0.2},
        ),
    )
    caustic, acid, thin = ground["lots"]
    visit_id = ground["visit"]["id"]
    line_id = ground["line"]["id"]
    headers = ground["tech_headers"]

    # An acid declaration against the caustic drum.
    validate_error(
        api.create_cleaning_cycle(
            factories.cleaning_cycle_payload(visit_id, line_id, caustic["id"], **_ACID_CYCLE),
            headers,
        ),
        ApiErrorId.CHEMICAL_TYPE_MISMATCH,
        422,
    )

    # A self-consistent acid pair, but the line has never been cleaned.
    validate_error(
        api.create_cleaning_cycle(
            factories.cleaning_cycle_payload(visit_id, line_id, acid["id"], **_ACID_CYCLE),
            headers,
        ),
        ApiErrorId.CHEMICAL_PARITY_VIOLATION,
        422,
    )

    # 0.31 litres drawn from a drum holding 0.200.
    validate_error(
        api.create_cleaning_cycle(
            factories.cleaning_cycle_payload(
                visit_id, line_id, thin["id"], **fixtures.PASSING_CAUSTIC_CYCLE
            ),
            headers,
        ),
        ApiErrorId.CHEMICAL_INSUFFICIENT_VOLUME,
        422,
    )

    cycle = fixtures.log_cleaning_cycle(
        api, visit_id, line_id, caustic["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert cycle["compliance_result"] == ComplianceResult.PASS

    assert_liters(fixtures.read_lot(api, caustic["id"])["liters_remaining"], 19.690)
    assert_liters(fixtures.read_lot(api, acid["id"])["liters_remaining"], 10.0)
    thin_reread = fixtures.read_lot(api, thin["id"])
    assert_liters(thin_reread["liters_remaining"], 0.200)
    assert thin_reread["status"] == LotStatus.AVAILABLE
    assert fixtures.read_line(api, line_id)["last_chemical_type"] == ChemicalType.CAUSTIC


def test_a_line_may_be_pulled_forward_two_days_but_not_sixteen(api):
    """PRD §3.4: "The early-cleaning guard must hold, else `ERR_CLEANING_TOO_EARLY`: when the line's
    `next_due_at` is not null, the date of `logged_at` must be on or after `next_due_at`'s date less
    two days, so a crew may pull a line forward by at most two days."

    Design: Corner/errors/corner_cleaning_five_days_after_the_last_one_is_too_early_and_two_days_before_due_is_fine
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=(
            {"lot_code": "C-2001"},
            {"chemical_type": ChemicalType.ACID, "lot_code": "A-3001",
             "concentration_pct_stock": 20.0, "liters_initial": 10.0},
        ),
    )
    caustic, acid = ground["lots"]
    visit_id = ground["visit"]["id"]
    line_id = ground["line"]["id"]
    fixtures.log_cleaning_cycle(
        api, visit_id, line_id, caustic["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert_instant(
        fixtures.read_line(api, line_id)["next_due_at"], "2026-08-26T09:00:00Z", label="next_due_at"
    )

    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    validate_error(
        api.create_cleaning_cycle(
            factories.cleaning_cycle_payload(visit_id, line_id, acid["id"], **_ACID_CYCLE),
            ground["tech_headers"],
        ),
        ApiErrorId.CLEANING_TOO_EARLY,
        422,
    )
    assert_liters(fixtures.read_lot(api, acid["id"])["liters_remaining"], 10.0)

    fixtures.set_clock(api, "2026-08-24T09:00:00Z")
    accepted = fixtures.log_cleaning_cycle(
        api, visit_id, line_id, acid["id"], ground["technician"]["id"], **_ACID_CYCLE
    )

    assert accepted["compliance_result"] == ComplianceResult.PASS
    assert_instant(accepted["logged_at"], "2026-08-24T09:00:00Z", label="logged_at")
    assert_liters(fixtures.read_lot(api, acid["id"])["liters_remaining"], 9.650)
    reread = fixtures.read_line(api, line_id)
    assert_instant(reread["last_cleaned_at"], "2026-08-24T09:00:00Z", label="last_cleaned_at")
    assert_instant(reread["next_due_at"], "2026-09-14T09:00:00Z", label="next_due_at")


def test_the_route_board_refuses_yesterday_and_the_forty_sixth_day_but_takes_the_forty_fifth(api):
    """PRD §3.3: "The `scheduled_date` may not fall before the logical clock's current date — no
    back-dated visits — else `ERR_VISIT_DATE_IN_PAST`. Nor may it fall more than six weeks and three
    days ahead: the route board extends exactly 45 days beyond the current date and no further, else
    `ERR_SCHEDULE_LEAD_EXCEEDED`."

    Design: Corner/errors/corner_back_dated_and_far_future_bookings_are_both_refused_at_their_own_edge
    """
    fixtures.set_clock(api, fixtures.CLOCK_EPOCH)
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse", lines=())
    account_id = venue["account"]["id"]
    technician = fixtures.create_technician(api)

    validate_error(
        api.create_service_visit(
            factories.service_visit_payload(
                account_id, technician["id"], scheduled_date="2026-07-31"
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.VISIT_DATE_IN_PAST,
        422,
    )

    # 2026-09-16 is the forty-sixth day beyond 2026-08-01.
    validate_error(
        api.create_service_visit(
            factories.service_visit_payload(
                account_id, technician["id"], scheduled_date="2026-09-16"
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.SCHEDULE_LEAD_EXCEEDED,
        422,
    )

    visit = fixtures.book_visit(
        api, account_id, technician["id"], scheduled_date="2026-09-15"
    )
    assert visit["scheduled_date"] == "2026-09-15"
    assert visit["work_status"] == WorkStatus.SCHEDULED

    # The two refusals persisted nothing.
    _, meta = validate_paginated(
        api.list_service_visits(DISPATCH_HEADERS, account_id=account_id)
    )
    assert meta["total_count"] == 1


def test_settlement_freezes_the_compliance_record_behind_the_money(api):
    """PRD §3.4: "Two conditions apply in order: the record must still be `POSTED`, else
    `ERR_CYCLE_ALREADY_VOIDED`, and the cycle's visit must not yet have `settlement_state` `SETTLED`,
    else `ERR_VISIT_ALREADY_SETTLED` — once money has moved, the compliance record behind it is
    frozen."

    Design: Corner/errors/corner_voiding_a_cycle_on_a_settled_visit_is_refused
    """
    ground = fixtures.setup_started_visit(
        api, venue_name="Anchor Alehouse", lot_specs=({"lot_code": "C-2001"},)
    )
    visit_id = ground["visit"]["id"]
    cycle = fixtures.log_cleaning_cycle(
        api, visit_id, ground["line"]["id"], ground["lot"]["id"], ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.complete_work_on(api, visit_id, ground["technician"]["id"])

    signed = fixtures.sign_visit(api, visit_id, ground["account"]["id"], signer_name="Mara Vance")
    assert signed["settlement_state"] == SettlementState.SETTLED
    # 7500 base plus one line at 4175 x 1.10, with no waiver withholding on the signature path.
    assert signed["settled_charge_cents"] == 12093

    validate_error(
        api.void_cleaning_cycle(
            cycle["id"], "Customer disputes the caustic pass.", AUDITOR_HEADERS
        ),
        ApiErrorId.VISIT_ALREADY_SETTLED,
        409,
    )

    frozen = fixtures.read_cycle(api, cycle["id"])
    assert frozen["record_status"] == RecordStatus.POSTED
    assert frozen["void_reason"] is None
    # No volume was handed back.
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 19.690)
    reread = fixtures.read_visit(api, visit_id)
    assert reread["settled_charge_cents"] == 12093
    assert reread["settlement_state"] == SettlementState.SETTLED
