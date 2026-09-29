"""Resource surfaces: creation, reads, listing, defaults, derived and system fields."""
from test_helpers import (
    assert_facility,
    assert_immutable_ledger_row,
    assert_intake,
    assert_metal_index_price,
    assert_module,
    assert_supplier,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_INTAKE, CLOCK_PROCESS

_UNKNOWN_INTAKE = "11111111-1111-4111-8111-111111111111"
_UNKNOWN_INTAKE_FOR_MODULE = "22222222-2222-4222-8222-222222222222"
_UNKNOWN_SUPPLIER = "33333333-3333-4333-8333-333333333333"
_UNKNOWN_FACILITY = "44444444-4444-4444-8444-444444444444"


def _network(api):
    """The clock at the intake instant, one campus and one counterparty."""
    return fx.bootstrap_network(api, quotes=None)


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------

def test_registering_a_campus_returns_created_with_the_default_status(api):
    """The campus write echoes the four declared fields, applies the ACTIVE default
    and starts the version counter at one.

    PRD §3.1: "The campus also carries a `status` which the caller may supply and
    which otherwise defaults to `ACTIVE`; the only other permitted value is
    `SUSPENDED`."

    Design: Corner/entities/create_facility_with_all_required_fields_returns_created
    """
    clock = fx.move_clock(api, CLOCK_INTAKE)
    assert clock["current_utc"] == CLOCK_INTAKE

    facility = validate_success(
        api.create_facility(f.create_facility_payload(), fx.ADMIN), expected_status=201
    )

    assert_facility(facility)
    assert is_valid_uuid(facility["id"])
    assert facility["name"] == "Reno Campus"
    assert facility["state_code"] == "NV"
    assert float(facility["mech_capacity_kg_per_day"]) == 3000.0
    assert float(facility["hydro_capacity_kg_per_day"]) == 2000.0
    assert facility["status"] == "ACTIVE"
    assert facility["version"] == 1
    assert facility["created_at"] == CLOCK_INTAKE
    assert facility["updated_at"] is not None


# --------------------------------------------------------------------------
# Reads and listing
# --------------------------------------------------------------------------

def test_reading_a_shipment_returns_the_stored_snapshot(api):
    """A freshly booked shipment reads back with its computed net mass, both state
    dimensions at their initial values and every optional field empty.

    PRD §3.2: "Everything else on a fresh shipment is empty: `identified_chemistry`,
    `soc_pct`, `packaging_type`, `hold_reason` and `released_at` are all null, and
    `module_mass_total_kg`, `assigned_mass_kg` and `unassigned_mass_kg` are all 0.0."

    Design: Corner/entities/get_intake_returns_stored_snapshot
    """
    ctx = _network(api)
    booked = fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"])

    intake = fx.read_intake(api, booked["id"])

    assert_intake(intake)
    assert float(intake["net_mass_kg"]) == 100.0
    assert intake["custody_state"] == "RECEIVED"
    assert intake["compliance_state"] == "MANIFEST_DRAFT"
    assert intake["received_at"] == CLOCK_INTAKE
    assert float(intake["declared_ni_pct"]) == 12.0
    assert float(intake["declared_co_pct"]) == 0.0
    assert float(intake["declared_li_pct"]) == 0.0
    assert float(intake["declared_cu_pct"]) == 0.0
    assert intake["identified_chemistry"] is None
    assert intake["soc_pct"] is None
    assert intake["packaging_type"] is None
    assert intake["released_at"] is None
    assert intake["hold_reason"] is None
    assert float(intake["module_mass_total_kg"]) == 0.0
    assert float(intake["assigned_mass_kg"]) == 0.0
    assert float(intake["unassigned_mass_kg"]) == 0.0
    assert intake["version"] == 1


def test_listing_shipments_paginates_and_filters_by_custody_state(api):
    """Three shipments page two at a time with total_count and has_more reported, and
    the custody filter narrows the same collection to the identified row.

    PRD §2.3: "The four pagination fields reported in `meta` are `limit` (the
    effective page size), `offset` (the effective starting position), `total_count`
    (the number of rows matching the filters before the page window is applied) and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/list_intakes_with_pagination_and_custody_filter
    """
    ctx = _network(api)
    booked = [
        fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"]) for _ in range(3)
    ]
    fx.identify_chemistry(api, booked[0]["id"])

    page_one, meta_one = validate_paginated(
        api.list_intakes(fx.CLERK, params={"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_intakes(fx.CLERK, params={"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False
    assert page_one[0]["id"] != page_two[0]["id"]

    filtered, meta_filtered = validate_paginated(
        api.list_intakes(fx.CLERK, params={"custody_state": "IDENTIFIED"})
    )
    assert meta_filtered["total_count"] == 1
    assert filtered[0]["id"] == booked[0]["id"]
    assert filtered[0]["custody_state"] == "IDENTIFIED"
    for other in booked[1:]:
        assert fx.read_intake(api, other["id"])["custody_state"] == "RECEIVED"


def test_reading_an_unknown_shipment_returns_its_own_not_found_code(api):
    """A syntactically valid identifier that names no row is a 404, not an empty
    success body.

    PRD §2.6: "Path parameters are resolved strictly **left to right**, and the first
    segment that names a row which does not exist determines the error."

    Design: Corner/entities/get_intake_with_unknown_uuid_returns_intake_not_found
    """
    _network(api)

    validate_error(api.get_intake(_UNKNOWN_INTAKE, fx.CLERK), "ERR_INTAKE_NOT_FOUND", 404)

    _, meta = validate_paginated(api.list_intakes(fx.CLERK))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Request shape, defaults and constraints
# --------------------------------------------------------------------------

def test_booking_a_shipment_without_the_gross_weighbridge_reading_is_invalid(api):
    """The gross reading has no default, so omitting it is a malformed request rather
    than a zero-mass shipment.

    PRD §3.2: "the weighbridge readings: `gross_mass_kg` greater than zero including
    packaging, and `packaging_tare_kg` which must be at least zero and strictly less
    than `gross_mass_kg`."

    Design: Corner/entities/create_intake_without_gross_mass_kg_returns_invalid_request
    """
    ctx = _network(api)

    response = api.create_intake(
        f.create_intake_payload(
            ctx["supplier"]["id"],
            ctx["facility"]["id"],
            gross_mass_kg=f.OMIT,
            declared_ni_pct=f.OMIT,
            packaging_tare_kg=10.0,
        ),
        fx.CLERK,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(api.list_intakes(fx.CLERK))
    assert meta["total_count"] == 0


def test_omitting_every_optional_input_applies_the_declared_defaults(api):
    """The counterparty's four ledger fields, the shipment's six measurements and the
    line's changeover buffer all take their declared defaults.

    PRD §3.2: "Six further measurements are optional and each defaults to 0.0 when
    omitted: `declared_ni_pct`, `declared_co_pct`, `declared_li_pct` and
    `declared_cu_pct` state the supplier's declared nickel, cobalt, lithium and copper
    assays as mass percentages of net mass, while `moisture_pct` reports measured free
    moisture and `foreign_material_pct` reports measured non-battery foreign material,
    again as mass percentages."

    Design: Corner/entities/create_intake_omitting_optional_fields_applies_declared_defaults
    """
    fx.move_clock(api, CLOCK_INTAKE)
    facility = fx.create_facility(api)

    supplier = validate_success(
        api.create_supplier(f.create_supplier_payload(), fx.ADMIN), expected_status=201
    )
    assert_supplier(supplier)
    assert supplier["credit_hold"] is False
    assert supplier["payable_balance_cents"] == 0
    assert supplier["paid_to_date_cents"] == 0
    assert supplier["quality_strike_count"] == 0
    assert supplier["contact_email"] is None

    intake = validate_success(
        api.create_intake(
            f.create_intake_payload(supplier["id"], facility["id"], declared_ni_pct=f.OMIT),
            fx.CLERK,
        ),
        expected_status=201,
    )
    for field in (
        "declared_ni_pct",
        "declared_co_pct",
        "declared_li_pct",
        "declared_cu_pct",
        "moisture_pct",
        "foreign_material_pct",
    ):
        assert float(intake[field]) == 0.0, f"{field} defaults to 0.0"
    assert intake["custody_state"] == "RECEIVED"
    assert intake["compliance_state"] == "MANIFEST_DRAFT"

    line = validate_success(
        api.create_processing_line(
            f.create_processing_line_payload(facility["id"]), fx.ADMIN
        ),
        expected_status=201,
    )
    assert line["changeover_buffer_hours"] == 6
    assert line["status"] == "AVAILABLE"


def test_out_of_range_shipment_values_are_refused_while_the_boundary_is_accepted(api):
    """An unlisted chemistry, a tare equal to the gross and an assay above one hundred
    are all malformed, while an assay of exactly one hundred is inside the range.

    PRD §3.2: "All six must fall between 0.0 and 100.0 inclusive."

    Design: Corner/entities/create_intake_with_out_of_range_values_returns_invalid_request
    """
    ctx = _network(api)
    supplier_id, facility_id = ctx["supplier"]["id"], ctx["facility"]["id"]

    for overrides in (
        {"declared_chemistry": "LTO", "declared_ni_pct": f.OMIT},
        {"packaging_tare_kg": 110.0, "declared_ni_pct": f.OMIT},
        {"declared_ni_pct": 120.0},
    ):
        response = api.create_intake(
            f.create_intake_payload(supplier_id, facility_id, **overrides), fx.CLERK
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

    accepted = validate_success(
        api.create_intake(
            f.create_intake_payload(supplier_id, facility_id, declared_ni_pct=100.0),
            fx.CLERK,
        ),
        expected_status=201,
    )
    assert float(accepted["net_mass_kg"]) == 100.0

    listed, meta = validate_paginated(api.list_intakes(fx.CLERK))
    assert meta["total_count"] == 1
    assert listed[0]["id"] == accepted["id"]


# --------------------------------------------------------------------------
# Derived, system and immutable fields
# --------------------------------------------------------------------------

def test_shipment_mass_fields_are_derived_from_the_weighbridge_and_the_modules(api):
    """The net mass comes from gross less tare at booking, and each module insertion
    re-derives the module total and the unassigned balance.

    PRD §3.4: "Each accepted insertion recomputes the shipment's
    `module_mass_total_kg` as the sum of module masses, rounded half up to three
    decimals, and recomputes `unassigned_mass_kg` accordingly, and it increments the
    shipment's `version` by 1."

    Design: Corner/entities/intake_mass_fields_are_computed_from_gross_tare_and_modules
    """
    ctx = _network(api)
    booked = fx.book_intake(
        api,
        ctx["supplier"]["id"],
        ctx["facility"]["id"],
        gross_mass_kg=850.0,
        packaging_tare_kg=50.0,
    )
    assert float(booked["net_mass_kg"]) == 800.0
    fx.identify_chemistry(api, booked["id"])

    first = fx.add_module(api, booked["id"], "M-1", mass_kg=400.0)
    intake = fx.read_intake(api, booked["id"])
    assert float(intake["module_mass_total_kg"]) == 400.0
    assert float(intake["unassigned_mass_kg"]) == 400.0

    fx.add_module(api, booked["id"], "M-2", mass_kg=400.0)
    intake = fx.read_intake(api, booked["id"])
    assert float(intake["module_mass_total_kg"]) == 800.0
    assert float(intake["unassigned_mass_kg"]) == 800.0
    assert float(intake["assigned_mass_kg"]) == 0.0

    assert_module(first)
    assert first["chemistry"] == "NMC622", (
        "chemistry is copied from the shipment's identified_chemistry, never supplied"
    )
    assert first["status"] == "PENDING_TRIAGE"
    assert first["second_life_score"] is None
    assert first["grade"] is None
    assert first["lot_id"] is None


def test_system_fields_are_stamped_from_the_logical_clock_and_never_re_stamped(api):
    """The received instant is taken from the logical clock at booking and survives a
    later clock move, while the version counter advances by exactly one per write.

    PRD §2.4: "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC
    instant with exactly three fractional digits, stamped from the logical clock at
    the moment the row is created."; "`version`, an integer that starts at 1 on
    creation and increments by exactly 1 on every accepted mutation of that row"

    Design: Corner/entities/intake_system_fields_are_stamped_from_the_logical_clock
    """
    ctx = _network(api)
    booked = fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"])
    assert booked["received_at"] == CLOCK_INTAKE
    assert booked["created_at"] == CLOCK_INTAKE
    assert booked["version"] == 1
    assert is_valid_uuid(booked["id"])

    fx.move_clock(api, CLOCK_PROCESS)
    identified = fx.identify_chemistry(api, booked["id"])

    assert identified["received_at"] == CLOCK_INTAKE, (
        "a system field is not re-stamped by a later write"
    )
    assert identified["created_at"] == CLOCK_INTAKE
    assert identified["version"] == 2


def test_index_quotes_are_immutable_rows_that_carry_no_version(api):
    """A published quote exposes only its identity and creation stamp, applies the
    default publishing index and is corrected only by appending another quote.

    PRD §2.4: "Two resources are immutable ledger rows and carry **only** `id` and
    `created_at`: `MetalIndexPrice`, a published market quote that is never edited,
    and `RecoveryOutput`, an append-only assay line."

    Design: Corner/entities/metal_index_price_rows_are_immutable_and_carry_no_version
    """
    fx.move_clock(api, CLOCK_INTAKE)

    first = validate_success(
        api.create_metal_index_price(
            f.create_metal_index_price_payload(
                metal="NI", effective_date="2026-07-01T00:00:00.000Z", price_cents_per_kg=1600
            ),
            fx.ANALYST,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_metal_index_price(
            f.create_metal_index_price_payload(
                metal="NI",
                effective_date="2026-08-15T00:00:00.000Z",
                price_cents_per_kg=1750,
                source_index="SHFE",
            ),
            fx.ANALYST,
        ),
        expected_status=201,
    )

    assert first["id"] != second["id"]
    assert first["source_index"] == "LME"
    assert second["source_index"] == "SHFE"
    for quote in (first, second):
        assert_metal_index_price(quote)
        assert_immutable_ledger_row(quote, "index quote")

    listed, meta = validate_paginated(
        api.list_metal_index_prices(fx.ANALYST, params={"metal": "NI"})
    )
    assert meta["total_count"] == 2
    for quote in listed:
        assert "version" not in quote
        assert "updated_at" not in quote


# --------------------------------------------------------------------------
# Parent and foreign-key resolution
# --------------------------------------------------------------------------

def test_booking_a_module_under_an_unknown_shipment_reports_the_shipment(api):
    """The nested parent is resolved before the concurrency token is compared, so the
    answer names the shipment rather than the version.

    PRD §2.7: "**Path existence**, left to right, as described in §2.6. The applicable
    404 code."

    Design: Corner/entities/create_module_under_unknown_intake_returns_intake_not_found
    """
    ctx = _network(api)
    booked = fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"])
    identified = fx.identify_chemistry(api, booked["id"])

    response = api.create_module(
        _UNKNOWN_INTAKE_FOR_MODULE,
        f.create_module_payload("M-1", identified["version"]),
        fx.CLERK,
    )
    validate_error(response, "ERR_INTAKE_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api.list_modules(fx.CLERK, params={"intake_id": booked["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_intake(api, booked["id"])["version"] == identified["version"]


def test_unknown_body_foreign_keys_each_report_their_own_not_found_code(api):
    """The shipment body joins a counterparty and a campus, and each unresolvable
    identifier reports its own entity.

    PRD §2.6: "Foreign keys arriving in a **request body** are checked the same way
    and produce the same 404 codes. The bodies that carry them are shipment creation
    (`supplier_id` and `facility_id`), processing-line commissioning (`facility_id`),
    campaign scheduling (`line_id`), permit-allotment registration (`facility_id`),
    lot charging (every identifier in `module_ids`) and discharge-event booking
    (`allotment_id`)."

    Design: Corner/entities/create_intake_with_unknown_supplier_id_returns_supplier_not_found
    """
    ctx = _network(api)
    supplier_id, facility_id = ctx["supplier"]["id"], ctx["facility"]["id"]

    validate_error(
        api.create_intake(
            f.create_intake_payload(_UNKNOWN_SUPPLIER, facility_id), fx.CLERK
        ),
        "ERR_SUPPLIER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_intake(
            f.create_intake_payload(supplier_id, _UNKNOWN_FACILITY), fx.CLERK
        ),
        "ERR_FACILITY_NOT_FOUND",
        404,
    )

    accepted = validate_success(
        api.create_intake(f.create_intake_payload(supplier_id, facility_id), fx.CLERK),
        expected_status=201,
    )
    assert accepted["supplier_id"] == supplier_id
    assert accepted["facility_id"] == facility_id

    _, meta = validate_paginated(
        api.list_intakes(fx.CLERK, params={"supplier_id": supplier_id})
    )
    assert meta["total_count"] == 1
