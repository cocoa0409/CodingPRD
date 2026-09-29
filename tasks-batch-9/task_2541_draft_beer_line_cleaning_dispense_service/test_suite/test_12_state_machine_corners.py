"""Corner cases on the declared state machines: revert edges, initial states and
triggers that are only declared on states the row has already left."""

from test_helpers import (
    AUDITOR_HEADERS,
    AbandonReason,
    ApiErrorId,
    ChemicalType,
    DISPATCH_HEADERS,
    LotStatus,
    SettlementState,
    VerificationStatus,
    WorkStatus,
    assert_instant,
    assert_liters,
    assert_score,
    factories,
    fixtures,
    get_success_data,
    make_service_technician_headers,
    make_venue_manager_headers,
    validate_error,
    validate_paginated,
)


def _booked_visit(api, scheduled_date: str = "2026-08-05"):
    """A venue with an ACTIVE contract, one crew and one freshly booked visit."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(
        api,
        venue_name="Anchor Alehouse",
        cleaning_frequency_days=21,
        contracted_line_count=4,
        per_line_rate_cents=4175,
        visit_base_fee_cents=7500,
        lines=(),
    )
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")
    return venue, technician


def test_quarantining_a_lot_and_releasing_it_leaves_the_volume_untouched(api):
    """PRD §3.4: "Manually, a `QualityAuditor` supplies a `to_status` to pull a lot for
    inspection (`AVAILABLE → QUARANTINED` or `DEPLETED → QUARANTINED`), to release an
    inspected lot (`QUARANTINED → AVAILABLE`), or to write a lot off (`AVAILABLE → EXPIRED`
    or `QUARANTINED → EXPIRED`); each of those requires the lot to be in the stated
    originating status."
    PRD §3.4: "Thereafter `liters_remaining` is a projection: it is `liters_initial` less the
    sum of `concentrate_liters_used` across every cycle record still `POSTED` that drew on
    the lot, rounded to three decimal places, and it never goes negative."

    Design: Corner/state_machines/corner_chemical_lot_quarantine_then_release_returns_it_to_available
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    lot = fixtures.create_chemical_lot(
        api,
        chemical_type=ChemicalType.CAUSTIC,
        lot_code="C-2001",
        concentration_pct_stock=45.0,
        liters_initial=20.0,
        expires_on="2026-12-31",
    )
    assert lot["status"] == LotStatus.AVAILABLE
    assert_liters(lot["liters_remaining"], 20.0)

    pulled = get_success_data(
        api.set_chemical_lot_status(lot["id"], LotStatus.QUARANTINED, AUDITOR_HEADERS),
        expected_status=200,
    )
    released = get_success_data(
        api.set_chemical_lot_status(lot["id"], LotStatus.AVAILABLE, AUDITOR_HEADERS),
        expected_status=200,
    )

    assert pulled["status"] == LotStatus.QUARANTINED
    assert released["status"] == LotStatus.AVAILABLE
    # No cycle ever drew on this lot, so the projection stands at 20.000 both ways.
    assert_liters(pulled["liters_remaining"], 20.0)
    assert_liters(released["liters_remaining"], 20.0)
    # The status edge moves status only.
    assert released["chemical_type"] == ChemicalType.CAUSTIC
    assert released["concentration_pct_stock"] == 45.0
    assert released["lot_code"] == "C-2001"


def test_a_freshly_booked_visit_sits_at_the_start_of_all_three_dimensions(api):
    """PRD §3.3: "A freshly booked visit is `SCHEDULED`, `UNVERIFIED` and `UNSETTLED`, with
    `abandon_reason` `NONE`, `rescheduled_from_visit_id`, `signer_name`, `signed_at` and
    `work_completed_at` all null, and every count and money figure at zero."

    Design: Corner/state_machines/corner_new_visit_starts_scheduled_unverified_and_unsettled
    """
    venue, technician = _booked_visit(api)

    response = api.create_service_visit(
        factories.service_visit_payload(
            venue["account"]["id"],
            technician["id"],
            scheduled_date="2026-08-05",
            scheduled_start_minute=540,
            scheduled_end_minute=660,
        ),
        DISPATCH_HEADERS,
    )

    visit = get_success_data(response, expected_status=201)
    assert visit["work_status"] == WorkStatus.SCHEDULED
    assert visit["verification_status"] == VerificationStatus.UNVERIFIED
    assert visit["settlement_state"] == SettlementState.UNSETTLED
    assert visit["abandon_reason"] == AbandonReason.NONE
    assert visit["rescheduled_from_visit_id"] is None
    assert visit["work_completed_at"] is None
    assert visit["signed_at"] is None
    assert visit["signer_name"] is None
    assert visit["serviced_line_count"] == 0
    assert visit["billable_line_count"] == 0
    assert visit["provisional_charge_cents"] == 0
    assert visit["settled_charge_cents"] == 0
    assert visit["brewer_funded_cents"] == 0
    assert visit["account_due_cents"] == 0


def test_the_start_gate_turns_on_the_calendar_date_not_the_slot_minute(api):
    """PRD §3.3: "Four conditions apply: the visit must be `SCHEDULED` (else
    `ERR_VISIT_NOT_SCHEDULED`), the caller's `X-User-ID` must equal the visit's
    `technician_id` (else `ERR_TECHNICIAN_NOT_ASSIGNED`), the logical clock's current date
    must have reached the visit's `scheduled_date` (else `ERR_VISIT_START_TOO_EARLY` — a crew
    cannot open tomorrow's job today), and the account must still be `ACTIVE` (else
    `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Corner/state_machines/corner_starting_a_visit_the_day_before_its_scheduled_date_is_too_early
    """
    venue, technician = _booked_visit(api)
    visit = fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    tech_headers = make_service_technician_headers(technician["id"])

    fixtures.set_clock(api, "2026-08-04T23:59:00Z")
    validate_error(
        api.start_visit(visit["id"], tech_headers),
        ApiErrorId.VISIT_START_TOO_EARLY,
        422,
    )

    # The refusal left the field-work dimension exactly where it was.
    held = fixtures.read_visit(api, visit["id"])
    assert held["work_status"] == WorkStatus.SCHEDULED

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    opened = get_success_data(api.start_visit(visit["id"], tech_headers), expected_status=200)

    # Midnight on the scheduled date is enough, hours before the 540-minute slot opens.
    assert opened["work_status"] == WorkStatus.IN_PROGRESS
    assert opened["verification_status"] == VerificationStatus.UNVERIFIED


def test_neither_start_nor_reschedule_is_available_from_in_progress(api):
    """PRD §3.3: "The original visit must still be `SCHEDULED`, otherwise the request is
    refused with `ERR_VISIT_NOT_SCHEDULED`, and the named technician — the replacement's if
    supplied, otherwise the original's — must be `ACTIVE`, otherwise
    `ERR_TECHNICIAN_INACTIVE`."
    PRD §3.3: "Four conditions apply: the visit must be `SCHEDULED` (else
    `ERR_VISIT_NOT_SCHEDULED`), the caller's `X-User-ID` must equal the visit's
    `technician_id` (else `ERR_TECHNICIAN_NOT_ASSIGNED`), the logical clock's current date
    must have reached the visit's `scheduled_date` (else `ERR_VISIT_START_TOO_EARLY` — a crew
    cannot open tomorrow's job today), and the account must still be `ACTIVE` (else
    `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Corner/state_machines/corner_start_and_reschedule_are_both_rejected_once_the_visit_is_in_progress
    """
    venue, technician = _booked_visit(api)
    visit = fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    tech_headers = make_service_technician_headers(technician["id"])
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.start_visit(api, visit["id"], technician["id"])

    validate_error(
        api.start_visit(visit["id"], tech_headers),
        ApiErrorId.VISIT_NOT_SCHEDULED,
        409,
    )
    validate_error(
        api.reschedule_visit(
            visit["id"],
            factories.reschedule_payload(
                scheduled_date="2026-08-07",
                scheduled_start_minute=540,
                scheduled_end_minute=660,
            ),
            DISPATCH_HEADERS,
        ),
        ApiErrorId.VISIT_NOT_SCHEDULED,
        409,
    )

    held = fixtures.read_visit(api, visit["id"])
    assert held["work_status"] == WorkStatus.IN_PROGRESS
    assert held["abandon_reason"] == AbandonReason.NONE
    rows, meta = validate_paginated(
        api.list_service_visits(DISPATCH_HEADERS, account_id=venue["account"]["id"], limit=10, offset=0)
    )
    # The refused reschedule minted no replacement.
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == visit["id"]


def test_a_second_void_on_the_same_cycle_gives_no_second_refund(api):
    """PRD §3.4: "Two conditions apply in order: the record must still be `POSTED`, else
    `ERR_CYCLE_ALREADY_VOIDED`, and the cycle's visit must not yet have `settlement_state`
    `SETTLED`, else `ERR_VISIT_ALREADY_SETTLED` — once money has moved, the compliance record
    behind it is frozen."
    PRD §3.4: "A void advances the record `POSTED → VOIDED`, stores the `void_reason`, and
    gives back the chemistry: the lot's `liters_remaining` is increased by
    `concentrate_liters_used`, held to three decimal places, and a `DEPLETED` lot climbs back
    to `AVAILABLE` when the restored volume reaches 0.05 liters."
    PRD §3.4: "The line's `last_chemical_type`, `last_cleaned_at`, `next_due_at`,
    `days_overdue` and `compliance_flag` are then replayed from the cycles that remain
    `POSTED`, which can roll `last_cleaned_at` back to an earlier passing cycle or to null,
    pull `next_due_at` earlier, and push `days_overdue` past the three-day grace inside the
    very same request."

    Design: Corner/state_machines/corner_voiding_a_voided_cycle_is_refused_and_does_not_restore_liters_twice
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=({"lot_code": "C-2001"},),
    )
    cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["line"]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert cycle["compliance_result"] == "PASS"
    first_reason = "Keyed against the wrong line by the crew."
    voided = fixtures.void_cycle(api, cycle["id"], first_reason)
    assert voided["record_status"] == "VOIDED"
    assert voided["void_reason"] == first_reason
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 20.0)

    validate_error(
        api.void_cleaning_cycle(
            cycle["id"], "Second attempt at the same correction.", AUDITOR_HEADERS
        ),
        ApiErrorId.CYCLE_ALREADY_VOIDED,
        409,
    )

    replayed_cycle = fixtures.read_cycle(api, cycle["id"])
    assert replayed_cycle["record_status"] == "VOIDED"
    # The refused replay stored none of its own text.
    assert replayed_cycle["void_reason"] == first_reason
    # The refund happened once: 20.000, not 20.310.
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 20.0)
    line = fixtures.read_line(api, ground["line"]["id"])
    assert line["last_cleaned_at"] is None
    assert line["next_due_at"] is None
    assert line["days_overdue"] == 0
    assert line["status"] == "IN_SERVICE"
    assert line["compliance_flag"] == "COMPLIANT"


def test_replaying_the_signature_does_not_settle_the_visit_twice(api):
    """PRD §3.7: "Whichever branch is taken, the platform first checks that the verification
    dimension permits the decision at all: a `SIGN` requires the visit to be `UNVERIFIED` or
    `DISPUTED`, a `DISPUTE` requires it to be `SIGNED`, and a waiver requires `UNVERIFIED`."
    PRD §3.7: "The provisional run stores the result in `provisional_charge_cents`; the
    settled run stores it in `settled_charge_cents` and then hands it to the brewer
    waterfall."
    PRD §3.7: "If the contract names no `brewer_program_id`, or its `funding_status` is
    anything other than `BREWER_FUNDED`, or the programme's status is anything other than
    `ACTIVE`, then `brewer_funded_cents` is 0, `account_due_cents` is the whole
    `settled_charge_cents`, and the waterfall stops there."

    Design: Corner/state_machines/corner_a_second_sign_on_a_signed_visit_is_already_recorded
    """
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lot_specs=({"lot_code": "C-2001"},),
    )
    fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["line"]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    completed = fixtures.complete_work_on(
        api, ground["visit"]["id"], ground["technician"]["id"]
    )
    # 7500 base fee plus one billable line at 4175 x 1.10 = 4593.
    assert completed["provisional_charge_cents"] == 12093

    fixtures.set_clock(api, "2026-08-05T11:00:00Z")
    signed = fixtures.sign_visit(
        api, ground["visit"]["id"], ground["account"]["id"], signer_name="Ana Ortiz"
    )
    assert signed["verification_status"] == VerificationStatus.SIGNED
    assert signed["settled_charge_cents"] == 12093
    assert_instant(signed["signed_at"], "2026-08-05T11:00:00Z", label="signed_at")

    validate_error(
        api.record_verification(
            ground["visit"]["id"],
            factories.verification_payload(decision="SIGN", signer_name="Someone Else"),
            make_venue_manager_headers(ground["account"]["id"]),
        ),
        ApiErrorId.VERIFICATION_ALREADY_RECORDED,
        409,
    )

    held = fixtures.read_visit(api, ground["visit"]["id"])
    assert held["verification_status"] == VerificationStatus.SIGNED
    assert held["settlement_state"] == SettlementState.SETTLED
    # No second settlement was posted on top of the first.
    assert held["settled_charge_cents"] == 12093
    assert held["account_due_cents"] == 12093
    assert held["brewer_funded_cents"] == 0
    assert held["signer_name"] == "Ana Ortiz"
    assert_instant(held["signed_at"], "2026-08-05T11:00:00Z", label="signed_at")


def test_only_the_venue_that_declared_a_chiller_gets_a_loop(api):
    """PRD §3.1: "When `glycol_system_present` is true, the same request also creates exactly
    one glycol loop for the venue, seeded with `glycol_pct` 35.0, `pump_psi` 12.0,
    `bath_temp_f` 28.0, `last_serviced_at` equal to the loop's own `created_at`,
    `health_score` 100.0 and `status` `NORMAL`."
    PRD §3.1: "That loop is **not** included in the account payload returned by registration;
    the only way to discover it is to list glycol loops filtered by the owning `account_id`."
    PRD §3.9: "When the window is empty, `window_avg_cooler_temp_f` is null and the
    temperature penalty is zero; otherwise `window_avg_cooler_temp_f` is the mean of the
    window's `cooler_temp_f` values rounded half up to two decimal places."

    Design: Corner/state_machines/corner_account_created_with_the_glycol_flag_cascade_creates_exactly_one_loop
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    chilled = fixtures.create_account(
        api, venue_name="Chiller House", glycol_system_present=True
    )
    dry = fixtures.create_account(api, venue_name="Dry Room", glycol_system_present=False)

    chilled_loops, chilled_meta = validate_paginated(
        api.list_glycol_loops(DISPATCH_HEADERS, account_id=chilled["id"], limit=10, offset=0)
    )
    dry_loops, dry_meta = validate_paginated(
        api.list_glycol_loops(DISPATCH_HEADERS, account_id=dry["id"], limit=10, offset=0)
    )

    # Exactly one loop, not zero and not one per line.
    assert chilled_meta["total_count"] == 1
    assert len(chilled_loops) == 1
    assert dry_meta["total_count"] == 0
    assert dry_loops == []
    loop = chilled_loops[0]
    assert loop["account_id"] == chilled["id"]
    assert loop["glycol_pct"] == 35.0
    assert loop["pump_psi"] == 12.0
    assert loop["bath_temp_f"] == 28.0
    assert_score(loop["health_score"], 100.0)
    assert loop["status"] == "NORMAL"
    # A loop with no reading yet has no window average.
    assert loop["window_avg_cooler_temp_f"] is None
    assert_instant(loop["last_serviced_at"], loop["created_at"], label="last_serviced_at")
