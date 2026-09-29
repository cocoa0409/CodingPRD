"""Requests that break two rules at once, and which rule the platform reports."""

from test_helpers import (
    AccountStatus,
    ApiErrorId,
    ContractStatus,
    DISPATCH_HEADERS,
    SuspendedReason,
    WorkStatus,
    assert_instant,
    assert_liters,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)

OUT_OF_WINDOW_SLOT = {
    "scheduled_date": "2026-08-05",
    "scheduled_start_minute": 300,
    "scheduled_end_minute": 400,
}


def _suspended_venue(api):
    """A venue with no visits at all, manually suspended by the compliance office."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Beacon Alehouse", lines=())
    technician = fixtures.create_technician(
        api, full_name="Nils Okonkwo", certification_level="CERTIFIED"
    )
    fixtures.suspend_account(api, venue["account"]["id"])
    return venue, technician


def test_a_suspended_venue_masks_the_out_of_window_slot_on_a_booking(api):
    """PRD §3.3: "The slot must sit wholly inside the venue's crew access window, meaning
    `scheduled_start_minute` is at or after the account's `access_window_start_minute` and
    `scheduled_end_minute` is at or before the account's `access_window_end_minute`; both
    bounds are inclusive, so a slot ending exactly at `access_window_end_minute` is allowed,
    and a breach is `ERR_OUTSIDE_ACCESS_WINDOW`."
    PRD §3.3: "Because the account-state check sits above this one, a booking that is
    both outside the window and aimed at a suspended venue reports
    `ERR_ACCOUNT_NOT_ACTIVE`, never the window error."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_out_of_window_slot_on_visit_booking
    """
    venue, technician = _suspended_venue(api)
    account = fixtures.read_account(api, venue["account"]["id"])
    assert account["status"] == AccountStatus.SUSPENDED
    assert account["suspended_reason"] == SuspendedReason.MANUAL

    refused = api.create_service_visit(
        factories.service_visit_payload(
            venue["account"]["id"], technician["id"], **OUT_OF_WINDOW_SLOT
        ),
        DISPATCH_HEADERS,
    )

    validate_error(refused, ApiErrorId.ACCOUNT_NOT_ACTIVE, 409)


def test_reactivating_the_venue_exposes_the_window_error_the_suspension_hid(api):
    """PRD §3.3: "both bounds are inclusive, so a slot ending exactly at
    `access_window_end_minute` is allowed, and a breach is `ERR_OUTSIDE_ACCESS_WINDOW`."
    PRD §3.1: "Moving a `SUSPENDED` contract back to `ACTIVE` requires it to be `SUSPENDED`
    and requires the owning account to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), and
    it restores `billing_mode` to `PROGRAM_BILL` when the contract's `funding_status` is
    `BREWER_FUNDED` and to `DIRECT_BILL` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_out_of_window_slot_on_visit_booking
    """
    venue, technician = _suspended_venue(api)
    fixtures.reactivate_account(api, venue["account"]["id"])

    account = fixtures.read_account(api, venue["account"]["id"])
    assert account["status"] == AccountStatus.ACTIVE
    assert account["suspended_reason"] == SuspendedReason.NONE
    assert fixtures.read_contract(api, venue["contract"]["id"])["status"] == (
        ContractStatus.ACTIVE
    )

    same_payload = factories.service_visit_payload(
        venue["account"]["id"], technician["id"], **OUT_OF_WINDOW_SLOT
    )
    refused = api.create_service_visit(same_payload, DISPATCH_HEADERS)
    validate_error(refused, ApiErrorId.OUTSIDE_ACCESS_WINDOW, 422)

    booked = get_success_data(
        api.create_service_visit(
            factories.service_visit_payload(
                venue["account"]["id"],
                technician["id"],
                scheduled_date="2026-08-05",
                scheduled_start_minute=480,
                scheduled_end_minute=1080,
            ),
            DISPATCH_HEADERS,
        ),
        expected_status=201,
    )
    assert booked["work_status"] == WorkStatus.SCHEDULED
    assert booked["scheduled_end_minute"] == 1080, (
        "a slot ending exactly on the window's closing minute is allowed"
    )


def _inspection_ground(api):
    """An open job plus three catalogue rows: wrong type, right type but empty, stocked."""
    return fixtures.setup_started_visit(
        api,
        venue_name="Cellar Door Pub",
        part_specs=(
            {
                "sku": "COUPLER-7",
                "component_type": "COUPLER",
                "unit_price_cents": 1200,
                "stock_on_hand": 0,
                "brewer_funded_eligible": True,
            },
            {
                "sku": "FAUCET-88",
                "component_type": "FAUCET",
                "unit_price_cents": 3195,
                "stock_on_hand": 0,
                "brewer_funded_eligible": True,
            },
            {
                "sku": "FAUCET-99",
                "component_type": "FAUCET",
                "unit_price_cents": 2450,
                "stock_on_hand": 2,
                "brewer_funded_eligible": False,
            },
        ),
    )


def _replace_faucet_with(api, ground, part):
    return api.create_component_inspection(
        factories.component_inspection_payload(
            ground["visit"]["id"],
            ground["line"]["id"],
            component_type="FAUCET",
            condition_grade="WORN",
            action_taken="REPLACED",
            part_sku_id=part["id"],
        ),
        ground["tech_headers"],
    )


def test_the_wrong_component_type_is_reported_even_when_that_sku_is_also_empty(api):
    """PRD §3.6: "The referenced catalogue part's `component_type` must equal the
    `component_type` in the payload, else `ERR_PART_TYPE_MISMATCH` — a faucet inspection
    cannot consume a coupler sku."
    PRD §3.6: "Because the type check sits above the stock check, a request naming a sku
    of the wrong component type that is *also* out of stock reports the mismatch and never
    the shortfall."

    Design: Difficulty/priority_pair_validation_conflict/part_type_mismatch_outranks_part_out_of_stock_on_inspection
    """
    ground = _inspection_ground(api)
    coupler, empty_faucet, _stocked = ground["parts"]

    refused = _replace_faucet_with(api, ground, coupler)
    validate_error(refused, ApiErrorId.PART_TYPE_MISMATCH, 422)

    assert fixtures.read_part(api, coupler["id"])["stock_on_hand"] == 0
    assert fixtures.read_part(api, empty_faucet["id"])["stock_on_hand"] == 0


def test_a_correctly_typed_but_empty_sku_reports_the_shortfall_and_a_stocked_one_bills(api):
    """PRD §3.6: "Only after that does the platform look at stock: the part's
    `stock_on_hand` must be at least 1, else `ERR_PART_OUT_OF_STOCK`."
    PRD §3.6: "A `part_sku_id` accompanies the record when and only when the action was
    `REPLACED`; it is null otherwise."

    Design: Difficulty/priority_pair_validation_conflict/part_type_mismatch_outranks_part_out_of_stock_on_inspection
    """
    ground = _inspection_ground(api)
    _coupler, empty_faucet, stocked_faucet = ground["parts"]

    refused = _replace_faucet_with(api, ground, empty_faucet)
    validate_error(refused, ApiErrorId.PART_OUT_OF_STOCK, 409)

    accepted = get_success_data(
        _replace_faucet_with(api, ground, stocked_faucet), expected_status=201
    )
    assert accepted["part_charge_cents"] == 2450, (
        f"the catalogue price is stamped on the record, got {accepted['part_charge_cents']}"
    )
    assert fixtures.read_part(api, stocked_faucet["id"])["stock_on_hand"] == 1
    assert fixtures.read_part(api, empty_faucet["id"])["stock_on_hand"] == 0


def _alternation_ground(api):
    """A line cleaned with caustic on the 5th, with two later jobs on the board."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Sailmaker Bar")
    line = venue["lines"][0]
    certified = fixtures.create_technician(
        api, full_name="Dana Ruiz", certification_level="MASTER", caustic_certified=True
    )
    uncertified = fixtures.create_technician(
        api, full_name="Kem Adeyemi", certification_level="CERTIFIED", caustic_certified=False
    )
    caustic_lot = fixtures.create_chemical_lot(
        api, chemical_type="CAUSTIC", lot_code="C-1001", concentration_pct_stock=45.0,
        liters_initial=20.0,
    )
    acid_lot = fixtures.create_chemical_lot(
        api, chemical_type="ACID", lot_code="A-2001", concentration_pct_stock=30.0,
        liters_initial=10.0,
    )
    first = fixtures.book_visit(
        api, venue["account"]["id"], certified["id"], scheduled_date="2026-08-05"
    )
    second = fixtures.book_visit(
        api, venue["account"]["id"], uncertified["id"], scheduled_date="2026-08-24"
    )
    third = fixtures.book_visit(
        api, venue["account"]["id"], certified["id"], scheduled_date="2026-08-25"
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.start_visit(api, first["id"], certified["id"])
    passing = fixtures.log_cleaning_cycle(
        api, first["id"], line["id"], caustic_lot["id"], certified["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    return {
        "account": venue["account"],
        "line": line,
        "certified": certified,
        "uncertified": uncertified,
        "caustic_lot": caustic_lot,
        "acid_lot": acid_lot,
        "second_visit": second,
        "third_visit": third,
        "passing_cycle": passing,
    }


def _log_caustic(api, visit_id, ground, technician_id):
    return api.create_cleaning_cycle(
        factories.cleaning_cycle_payload(
            visit_id,
            ground["line"]["id"],
            ground["caustic_lot"]["id"],
            chemical_type="CAUSTIC",
            contact_minutes=20,
            recirculation_temp_f=96.0,
            concentrate_liters_used=0.31,
        ),
        fixtures.make_service_technician_headers(technician_id),
    )


def test_an_uncertified_crew_is_told_about_the_credential_not_the_alternation(api):
    """PRD §3.4: "A `CAUSTIC` cycle requires the technician's `caustic_certified` to be
    true, else `ERR_TECHNICIAN_NOT_CAUSTIC_CERTIFIED`."
    PRD §3.4: "Check 8 sits above check 10, so an uncertified technician logging a caustic
    cycle that *also* breaks the alternation is told about the certification, never the
    parity."

    Design: Difficulty/priority_pair_validation_conflict/caustic_certification_outranks_chemical_alternation_on_cycle_log
    """
    ground = _alternation_ground(api)
    assert ground["passing_cycle"]["compliance_result"] == "PASS"
    assert ground["passing_cycle"]["effective_active_pct"] == 1.993
    before = fixtures.read_line(api, ground["line"]["id"])
    assert before["last_chemical_type"] == "CAUSTIC"
    assert_instant(before["next_due_at"], "2026-08-26T09:00:00Z", label="next_due_at")

    fixtures.set_clock(api, "2026-08-24T09:00:00Z")
    fixtures.start_visit(api, ground["second_visit"]["id"], ground["uncertified"]["id"])
    refused = _log_caustic(
        api, ground["second_visit"]["id"], ground, ground["uncertified"]["id"]
    )

    validate_error(refused, ApiErrorId.TECHNICIAN_NOT_CAUSTIC_CERTIFIED, 422)
    # A refused circulation draws no chemistry.
    assert_liters(fixtures.read_lot(api, ground["caustic_lot"]["id"])["liters_remaining"], 19.690)


def test_a_certified_crew_repeating_the_chemistry_is_told_about_the_alternation(api):
    """PRD §3.4: "The alternation rule must hold, else `ERR_CHEMICAL_PARITY_VIOLATION`:
    the body's `chemical_type` must differ from the line's `last_chemical_type`, and when
    `last_chemical_type` reads `NONE` the very first cycle in a line's life must be
    `CAUSTIC`."
    PRD §3.4: "when the line's `next_due_at` is not null, the date of `logged_at` must be
    on or after `next_due_at`'s date less two days, so a crew may pull a line forward by
    at most two days."

    Design: Difficulty/priority_pair_validation_conflict/caustic_certification_outranks_chemical_alternation_on_cycle_log
    """
    ground = _alternation_ground(api)
    fixtures.set_clock(api, "2026-08-25T09:00:00Z")
    fixtures.start_visit(api, ground["third_visit"]["id"], ground["certified"]["id"])

    refused = _log_caustic(
        api, ground["third_visit"]["id"], ground, ground["certified"]["id"]
    )
    validate_error(refused, ApiErrorId.CHEMICAL_PARITY_VIOLATION, 422)

    acid = fixtures.log_cleaning_cycle(
        api,
        ground["third_visit"]["id"],
        ground["line"]["id"],
        ground["acid_lot"]["id"],
        ground["certified"]["id"],
        chemical_type="ACID",
        contact_minutes=15,
        recirculation_temp_f=80.0,
        concentrate_liters_used=0.23,
    )
    assert acid["chemical_type"] == "ACID"
    assert acid["effective_active_pct"] == 0.986
    assert acid["required_contact_minutes"] == 15
    assert acid["compliance_result"] == "PASS"
    assert_liters(fixtures.read_lot(api, ground["acid_lot"]["id"])["liters_remaining"], 9.770)
    assert_liters(fixtures.read_lot(api, ground["caustic_lot"]["id"])["liters_remaining"], 19.690)
    line = fixtures.read_line(api, ground["line"]["id"])
    assert line["last_chemical_type"] == "ACID"
    assert_instant(line["last_cleaned_at"], "2026-08-25T09:00:00Z", label="last_cleaned_at")
    assert_instant(line["next_due_at"], "2026-09-15T09:00:00Z", label="next_due_at")
    assert line["status"] == "IN_SERVICE"
