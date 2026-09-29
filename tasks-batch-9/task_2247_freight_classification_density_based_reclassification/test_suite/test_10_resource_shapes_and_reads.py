"""The shape of each resource as the contract declares it.

Creation defaults, the derived cube-and-density fields, the two append-only
records that carry no version, the paginated list envelope, and the family of
not-found codes that every read shares.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_capture_event,
    assert_commodity_profile,
    assert_customer,
    assert_shipment,
    assert_shipment_line,
    assert_terminal,
    factories,
    is_valid_uuid,
    make_classification_auditor_headers,
    make_pricing_analyst_headers,
    make_shipper_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
AUDITOR = make_classification_auditor_headers()

CLOCK = "2026-01-10T08:00:00Z"

HAZMAT_PROFILE = {
    "nmfc_item": "049500",
    "description": "Corrosive liquids, drummed",
    "classification_basis": "DENSITY_BASED",
    "handling_code": "HAZMAT",
}

DENSE_DRUM_LINE = {
    "line_no": 1,
    "declared_class_code": 60,
    "declared_weight_lb": 3055,
    "pieces": 22,
    "declared_length_in": 20.0,
    "declared_width_in": 20.0,
    "declared_height_in": 20.0,
}


def _small_line(line_no):
    """A 100-pound single handling unit measuring 40.0 inches on every side."""
    return {
        "line_no": line_no,
        "declared_class_code": 100,
        "declared_weight_lb": 100,
        "pieces": 1,
        "declared_length_in": 40.0,
        "declared_width_in": 40.0,
        "declared_height_in": 40.0,
    }


# ==========================================================================
# Creation defaults
# ==========================================================================


def test_terminal_registration_returns_the_declared_calibration_defaults():
    """A terminal registered without an interval starts calibrated at 250 captures.

    PRD: "On registration `captures_since_calibration` is 0, `dimensioner_status`
    is `CALIBRATED` and `last_capture_at` is null."

    Design: Corner/entities/terminal_creation_returns_common_fields_and_declared_defaults
    """
    response = api_client.create_terminal(
        factories.create_terminal_payload(code="TRM1", name="Chicago Dock"), ANALYST
    )

    terminal = validate_success(response, expected_status=201)

    assert_terminal(terminal)
    assert is_valid_uuid(terminal["id"]), (
        f"the id is a bare UUID with no type prefix, got {terminal['id']}"
    )
    assert terminal["code"] == "TRM1"
    assert terminal["name"] == "Chicago Dock"
    assert terminal["calibration_interval_captures"] == 250, (
        f"the interval defaults to 250, got {terminal['calibration_interval_captures']}"
    )
    assert terminal["captures_since_calibration"] == 0
    assert terminal["dimensioner_status"] == "CALIBRATED"
    assert terminal["last_capture_at"] is None
    assert terminal["version"] == 1
    assert terminal["created_at"].startswith("2026-08-01T00:00:00"), (
        f"the logical clock starts at 2026-08-01T00:00:00Z, got {terminal['created_at']}"
    )


def test_shipper_registration_applies_every_declared_field_default():
    """The whole offender and education record is initialised, not left absent.

    PRD: "On creation `billing_posture` is `OPEN`, `education_status` is `NONE`,
    `education_threshold_strikes` is initialised equal to
    `education_strike_interval`, `offender_strike_count` is 0, both
    `liability_index_rolling` and `liability_index_lifetime` are 0.00,
    `offender_tier` is `TIER_0`, `dispute_window_days` is 30,
    `education_required_at` is null and `active_program_type` is null."

    Design: Corner/entities/customer_creation_applies_declared_field_defaults
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_customer(
        factories.create_customer_payload(account_code="ACME", name="Acme Mfg"), ANALYST
    )

    customer = validate_success(response, expected_status=201)

    assert_customer(customer)
    assert customer["account_code"] == "ACME"
    assert customer["education_strike_interval"] == 3, (
        f"the interval defaults to 3, got {customer['education_strike_interval']}"
    )
    assert customer["education_threshold_strikes"] == 3
    assert customer["education_status"] == "NONE"
    assert customer["education_required_at"] is None
    assert customer["billing_posture"] == "OPEN"
    assert customer["offender_strike_count"] == 0
    assert customer["liability_index_rolling"] == 0.00
    assert customer["liability_index_lifetime"] == 0.00
    assert customer["offender_tier"] == "TIER_0"
    assert customer["dispute_window_days"] == 30
    assert customer["active_program_type"] is None
    assert customer["version"] == 1


# ==========================================================================
# Reads of a tendered bill of lading
# ==========================================================================


def test_shipment_read_returns_the_pinned_snapshot_and_the_zeroed_money():
    """Tender pins the program and the standard, and every counter starts at zero.

    PRD: "The shipment is created with `class_status` `DECLARED` and
    `billing_status` `UNBILLED`, with `line_count` and `declared_total_weight_lb`
    at 0, with `measured_total_weight_lb` and `weight_variance_pct` null,
    `reweigh_required` false, `declared_vs_found_class_delta_count` at 0,
    `original_charge_cents`, `assessed_total_cents` and `open_notice_count` at 0,
    and `billed_at` null."

    Design: Corner/entities/shipment_retrieval_returns_stored_and_snapshotted_fields
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(env, "PROE001")

    shipment = fx.get_shipment(tendered["shipment_id"])
    line = fx.get_shipment_line(tendered["line_ids"][0])

    assert_shipment(shipment)
    assert_shipment_line(line)
    assert shipment["pro_number"] == "PROE001"
    assert shipment["customer_id"] == env["customer_id"]
    assert shipment["origin_terminal_id"] == env["terminal_id"]
    assert shipment["rate_program_id"] == env["rate_program_id"], (
        "tender pins the shipper's ACTIVE pricing program"
    )
    assert shipment["tariff_version_id"] == env["tariff_version_id"], (
        "tender pins the newest release effective at or before pickup"
    )
    assert shipment["class_status"] == "DECLARED"
    assert shipment["billing_status"] == "UNBILLED"
    assert shipment["line_count"] == 1
    assert shipment["declared_total_weight_lb"] == 400, (
        "the summed declared weight of the lines, not the header figure"
    )
    assert shipment["measured_total_weight_lb"] is None
    assert shipment["original_charge_cents"] == 0
    assert shipment["assessed_total_cents"] == 0
    assert shipment["billed_at"] is None
    assert line["declared_cubic_ft"] == 213.33, (
        f"four 48.0 x 40.0 x 48.0 units cube to 213.33, got {line['declared_cubic_ft']}"
    )
    assert line["declared_density_pcf"] == 1.88, (
        f"400 pounds over 213.33 cubic feet rounds to 1.88, "
        f"got {line['declared_density_pcf']}"
    )
    assert line["effective_class_code"] == 70, (
        "an unmeasured line rates at the class the shipper declared"
    )


def test_bill_of_lading_line_listing_paginates_at_ten_rows_by_default():
    """Twelve lines come back as ten then two, with the counts in the envelope.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/shipment_line_listing_paginates_with_declared_envelope
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(
        env,
        "PROE002",
        line_specs=[_small_line(line_no) for line_no in range(1, 13)],
        bol_declared_total_weight_lb=1200,
    )
    shipment_id = tendered["shipment_id"]

    first_page, first_meta = validate_paginated(
        api_client.list_shipment_lines(ANALYST, params={"shipment_id": shipment_id})
    )
    second_page, second_meta = validate_paginated(
        api_client.list_shipment_lines(
            ANALYST, params={"shipment_id": shipment_id, "limit": 10, "offset": 10}
        )
    )

    assert len(first_page) == 10, (
        f"limit defaults to 10, so the first page holds 10 rows, got {len(first_page)}"
    )
    assert first_meta["total_count"] == 12
    assert first_meta["has_more"] is True
    assert len(second_page) == 2
    assert second_meta["total_count"] == 12
    assert second_meta["has_more"] is False
    assert [row["line_no"] for row in first_page] == list(range(1, 11)), (
        "lines are iterated by their line_no ordinal"
    )

    shipment = fx.get_shipment(shipment_id)
    assert shipment["line_count"] == 12
    assert shipment["declared_total_weight_lb"] == 1200
    assert first_page[0]["declared_cubic_ft"] == 37.04, (
        f"one 40.0 x 40.0 x 40.0 unit cubes to 37.04, "
        f"got {first_page[0]['declared_cubic_ft']}"
    )
    assert first_page[0]["declared_density_pcf"] == 2.70
    assert first_page[0]["effective_class_code"] == 100


def test_a_capture_event_carries_no_version_and_no_updated_at():
    """The append-only record omits both mutation fields entirely.

    PRD: "Two resources are append-only records of something that already happened
    and therefore carry only `id` and `created_at`: a capture event and a credit
    memo. For those two, both `updated_at` and `version` are absent from the
    response entirely."

    Design: Corner/entities/capture_event_is_immutable_with_no_version_field
    """
    scenario = fx.setup_single_line_billed_shipment(pro_number="PROE003")
    recorded = fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        520,
        fx.single_line_measurement(520),
    )

    capture = validate_success(
        api_client.get_capture_event(recorded["id"], ANALYST)
    )

    assert_capture_event(capture)
    assert "version" not in capture, (
        f"a capture event has no version field, got {sorted(capture.keys())}"
    )
    assert "updated_at" not in capture, (
        f"a capture event has no updated_at field, got {sorted(capture.keys())}"
    )
    assert capture["created_at"].startswith("2026-01-10T08:00:00")
    assert capture["captured_at"].startswith("2026-01-10T08:00:00")
    assert capture["terminal_id"] == scenario["terminal_id"]
    assert capture["captured_by_user_id"] == scenario["terminal_id"], (
        "terminal_id and captured_by_user_id are both taken from the operator's header"
    )
    assert capture["capture_sequence"] == 1


# ==========================================================================
# The characteristic class floor
# ==========================================================================


def test_the_class_floor_is_the_largest_of_the_three_characteristic_codes():
    """A hazmat, non-stackable, high-liability commodity floors at 125; a benign one
    at nothing.

    PRD: "Each code contributes a class floor, and the profile's computed
    `min_class_floor` is the largest of the three contributions."

    Design: Corner/entities/commodity_profile_min_class_floor_is_max_of_three_characteristics
    """
    fx.set_clock(CLOCK)
    draft = fx.create_draft_tariff_version()

    hazardous = fx.create_commodity_profile(
        draft["id"],
        nmfc_item="049500",
        description="Corrosive liquids, drummed",
        classification_basis="DENSITY_BASED",
        handling_code="HAZMAT",
        stowability_code="NON_STACKABLE",
        liability_code="HIGH",
    )
    benign = fx.create_commodity_profile(
        draft["id"],
        nmfc_item="156600",
        description="Machine parts, boxed",
        classification_basis="DENSITY_BASED",
        handling_code="STANDARD",
        stowability_code="STACKABLE",
        liability_code="LOW",
    )

    assert_commodity_profile(hazardous)
    assert_commodity_profile(benign)
    assert hazardous["min_class_floor"] == 125, (
        f"handling contributes 125, stowability 125 and liability 100, so the floor "
        f"is 125, got {hazardous['min_class_floor']}"
    )
    assert hazardous["fixed_class_code"] is None, (
        "fixed_class_code must be null for a density-based profile"
    )
    assert benign["min_class_floor"] == 0, (
        f"three benign codes mean no floor at all, got {benign['min_class_floor']}"
    )
    assert benign["classification_basis"] == "DENSITY_BASED"
    assert fx.get_tariff_version(draft["id"])["status"] == "DRAFT", (
        "the catalogue is populated while the release is still DRAFT"
    )


def test_the_class_floor_lifts_a_dense_line_above_its_declared_class():
    """Nearly 30 pounds per cubic foot would rate low; the hazmat floor overrides it.

    PRD: "`effective_class_code` is the greater of the step-two candidate and the
    governing profile's `min_class_floor`, and `class_floor_applied` is true
    exactly when that floor was strictly greater than the candidate."

    Design: Corner/entities/line_class_floor_overrides_dense_declared_class
    """
    env = fx.setup_pricing_environment(clock=CLOCK, profile_overrides=HAZMAT_PROFILE)
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PROE004",
        line_specs=[DENSE_DRUM_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 3055},
    )

    line = fx.get_shipment_line(scenario["line_ids"][0])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert line["declared_cubic_ft"] == 101.86, (
        f"twenty-two 20.0-inch cubes come to 101.86 cubic feet, "
        f"got {line['declared_cubic_ft']}"
    )
    assert line["declared_density_pcf"] == 29.99
    assert line["declared_class_code"] == 60
    assert line["effective_class_code"] == 125, (
        f"the 125 floor is greater than the declared 60, "
        f"got {line['effective_class_code']}"
    )
    assert line["class_floor_applied"] is True
    assert line["classification_source"] == "BOL_DECLARED", (
        "the floor does not change where the class came from"
    )
    assert shipment["original_charge_cents"] == 91742, (
        f"30.55 hundredweight at 4200 cents, class 125, the 0.88 weight break and a "
        f"35 percent discount is 91742, got {shipment['original_charge_cents']}"
    )
    assert shipment["assessed_total_cents"] == 91742
    assert shipment["billed_at"] is not None
    assert shipment["billed_at"].startswith("2026-01-10T08:00:00")


# ==========================================================================
# Rejected reads and rejected writes
# ==========================================================================


def test_every_read_of_an_unknown_identifier_returns_its_own_not_found_code():
    """Each resource family answers with the code named for it, at HTTP 404.

    PRD: "Resolution of every identifier templated into the URL, validated left to
    right, each against its own not-found code"

    Design: Corner/entities/shipment_and_notice_reads_with_unknown_id_not_found
    """
    reads = [
        (api_client.get_terminal(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_TERMINAL_NOT_FOUND),
        (api_client.get_customer(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        (api_client.get_tariff_version(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_TARIFF_VERSION_NOT_FOUND),
        (api_client.get_commodity_profile(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_COMMODITY_PROFILE_NOT_FOUND),
        (api_client.get_rate_program(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_RATE_PROGRAM_NOT_FOUND),
        (api_client.get_exception_agreement(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_EXCEPTION_AGREEMENT_NOT_FOUND),
        (api_client.get_shipment(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
        (api_client.get_shipment_line(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_SHIPMENT_LINE_NOT_FOUND),
        (api_client.get_capture_event(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_CAPTURE_EVENT_NOT_FOUND),
        (api_client.get_inspection_finding(NON_EXISTENT_UUID, AUDITOR),
         ApiErrorId.ERR_INSPECTION_FINDING_NOT_FOUND),
        (api_client.get_correction_notice(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_CORRECTION_NOTICE_NOT_FOUND),
        (api_client.get_dispute(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_DISPUTE_NOT_FOUND),
        (api_client.get_credit_memo(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_CREDIT_MEMO_NOT_FOUND),
        (api_client.get_repricing_run(NON_EXISTENT_UUID, ANALYST),
         ApiErrorId.ERR_REPRICING_RUN_NOT_FOUND),
    ]

    for response, expected in reads:
        body = validate_error(response, expected.value, expected_status=404)
        assert body["message"], f"{expected.value} must carry a message"


def test_a_line_without_a_declared_weight_is_refused_and_leaves_no_line_behind():
    """The shape failure is reported first, and the shipment stays unbillable.

    PRD: "Request shape: required fields present, types correct, enum members
    recognized, numeric ranges honored (a contract discount is at least 0 and at
    most 0.75, piece counts are at least 1, weights are at least 1, `limit` is
    between 1 and 100 inclusive) — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/line_creation_missing_required_declared_weight_rejected
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    shipment = fx.tender_shipment(env["customer_id"], env["terminal_id"], "PROE005")
    payload = factories.create_shipment_line_payload(env["commodity_profile_id"])
    payload.pop("declared_weight_lb")

    line_response = api_client.create_shipment_line(
        shipment["id"], payload, make_shipper_headers(env["customer_id"])
    )
    validate_error(line_response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    bill_response = api_client.bill_shipment(shipment["id"], {}, ANALYST)
    validate_error(
        bill_response, ApiErrorId.ERR_NO_SHIPMENT_LINES.value, expected_status=422
    )

    stored = fx.get_shipment(shipment["id"])
    assert stored["line_count"] == 0, (
        f"the refused line was not persisted, got line_count {stored['line_count']}"
    )
    assert stored["billing_status"] == "UNBILLED"
    assert stored["original_charge_cents"] == 0, (
        "a shipment with no lines has original_charge_cents of exactly 0"
    )


def test_a_line_citing_a_commodity_from_another_release_is_refused():
    """The profile must belong to the release the shipment pinned at tender.

    PRD: "The line's commodity profile must belong to the shipment's pinned
    `tariff_version_id`; a profile from any other release is rejected with
    `ERR_TARIFF_MISMATCH`."

    Design: Corner/entities/line_commodity_profile_from_other_tariff_version_rejected
    """
    fx.set_clock(CLOCK)
    older = fx.create_published_standard(
        code="NMFC-2026A", effective_at="2026-01-01T00:00:00Z"
    )
    newer = fx.create_published_standard(
        code="NMFC-2026B", effective_at="2026-02-01T00:00:00Z"
    )
    customer = fx.create_customer()
    fx.create_active_rate_program(customer["id"])
    terminal = fx.create_terminal()
    shipment = fx.tender_shipment(customer["id"], terminal["id"], "PROE006")
    assert shipment["tariff_version_id"] == older["tariff_version_id"], (
        "a 2026-01-10 pickup pins the release effective 2026-01-01"
    )

    mismatched = api_client.create_shipment_line(
        shipment["id"],
        factories.create_shipment_line_payload(newer["commodity_profile_id"]),
        make_shipper_headers(customer["id"]),
    )
    validate_error(
        mismatched, ApiErrorId.ERR_TARIFF_MISMATCH.value, expected_status=422
    )

    accepted = api_client.create_shipment_line(
        shipment["id"],
        factories.create_shipment_line_payload(older["commodity_profile_id"]),
        make_shipper_headers(customer["id"]),
    )
    line = validate_success(accepted, expected_status=201)

    assert line["commodity_profile_id"] == older["commodity_profile_id"]
    assert fx.get_shipment(shipment["id"])["line_count"] == 1
    older_release = fx.get_tariff_version(older["tariff_version_id"])
    assert older_release["status"] == "SUPERSEDED"
    assert (
        older_release["superseded_by_tariff_version_id"]
        == newer["tariff_version_id"]
    ), "publishing the newer release supersedes the older one"
