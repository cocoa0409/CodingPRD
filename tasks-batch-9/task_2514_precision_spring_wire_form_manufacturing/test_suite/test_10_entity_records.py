"""What each entity looks like the instant it is written, and how it reads back.

Every resource in this API is born with a fixed shape: the commercial envelope a
program echoes, the eleven counters it seeds, the defaults an omitted optional
input falls back to, the computed engineering stack a design derives from its
geometry, the three-bucket mass ledger a heat opens with, and the two axes a run
starts at rest on. Three resources are write-once and expose neither
`updated_at` nor `version`. This module drives each of those creation and
retrieval shapes on its own, together with the body-shape rejections that keep a
malformed row out of the store and the pagination envelope every collection
answers in.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PLANT_ADMIN_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROCESS_TECHNICIAN_PRIMARY,
    PROGRAM_MANAGER_HEADERS,
    PROGRAM_MANAGER_PRIMARY,
    QUALITY_INSPECTOR_HEADERS,
    QUALITY_INSPECTOR_PRIMARY,
    make_headers,
)


def test_program_creation_echoes_terms_and_seeds_every_counter(api: ApiClient):
    """PRD §3.1: "A freshly opened program starts its commitment ledger at rest:
    `open_commitment_pieces` is initialised to the same number as
    `committed_pieces`, while `allocated_pieces`, `shipped_pieces` and
    `quarantined_lot_count` all start at 0."
    PRD §3.1: "`quote_frozen` starts false and every quoted figure — `quoted_qty`,
    `quoted_pre_discount_subtotal_cents`, `quoted_volume_discount_pct`,
    `quoted_tooling_amort_per_piece_cents`, `quoted_unit_price_cents` and
    `quoted_total_cents` — starts null."
    PRD §3.1: "`delivery_posture` starts at `BLOCKED`, which is simply what the
    posture rule below returns for a program with no granted approval on file."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of that row — and `version`, an
    integer that begins at 1 when the row is created and increases by 1 each time
    the row is mutated."

    Design: Corner/entities/program_creation_persists_the_commercial_envelope_and_initialises_counters
    """
    payload = F.program_payload()

    program = validate_success(api.create_program(payload, PROGRAM_MANAGER_HEADERS), 201)

    assert program["program_code"] == C.CANONICAL_PROGRAM_CODE, "program_code is echoed"
    assert program["application_class"] == C.CLASS_INDUSTRIAL, (
        "application_class is echoed as supplied"
    )
    assert program["ppap_level"] == 1, "ppap_level is echoed as supplied"
    assert program["committed_pieces"] == 500_000, "committed_pieces is echoed"
    assert program["minimum_order_quantity"] == 1_000, "minimum_order_quantity is echoed"
    assert program["amortization_method"] == C.FORECAST_BASIS, (
        "amortization_method is echoed as supplied"
    )

    assert program["open_commitment_pieces"] == 500_000, (
        "open_commitment_pieces is initialised to committed_pieces"
    )
    assert program["allocated_pieces"] == 0, "allocated_pieces starts at 0"
    assert program["shipped_pieces"] == 0, "shipped_pieces starts at 0"
    assert program["quarantined_lot_count"] == 0, "quarantined_lot_count starts at 0"
    A.assert_commitment_conserved(program)

    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "a program with no granted approval on file starts BLOCKED"
    )
    assert program["quote_frozen"] is False, "quote_frozen starts false"
    for quoted_field in (
        "quoted_qty",
        "quoted_pre_discount_subtotal_cents",
        "quoted_volume_discount_pct",
        "quoted_tooling_amort_per_piece_cents",
        "quoted_unit_price_cents",
        "quoted_total_cents",
    ):
        assert program[quoted_field] is None, f"{quoted_field} starts null"

    A.assert_audited_resource(program)
    assert program["version"] == 1, "version begins at 1 when the row is created"


def test_program_optional_floors_fall_back_to_their_declared_defaults(api: ApiClient):
    """PRD §3.1: "Four acceptance floors are optional and each has a default when
    omitted: `required_salt_spray_hours` is the minimum coating salt-spray
    endurance the chosen material must provide and defaults to 0 with a floor of
    0; `biocompatibility_required` defaults to false; `min_fatigue_margin`, the
    fatigue margin a design must reach before it can be released for this
    program, defaults to 1.000; and `required_ppk`, the long-run capability floor
    every safety-critical characteristic must reach before pieces may be
    allocated, also defaults to 1.000."

    Design: Corner/entities/program_optional_inputs_fall_back_to_their_declared_defaults
    """
    payload = F.without(
        F.program_payload(program_code="PGM-DEF"),
        "required_salt_spray_hours",
        "biocompatibility_required",
        "min_fatigue_margin",
        "required_ppk",
    )

    program = validate_success(api.create_program(payload, PROGRAM_MANAGER_HEADERS), 201)

    assert program["required_salt_spray_hours"] == C.DEFAULT_REQUIRED_SALT_SPRAY_HOURS, (
        "an omitted required_salt_spray_hours defaults to 0, not null"
    )
    assert program["biocompatibility_required"] is C.DEFAULT_BIOCOMPATIBILITY_REQUIRED, (
        "an omitted biocompatibility_required defaults to false"
    )
    assert program["min_fatigue_margin"] == C.DEFAULT_MIN_FATIGUE_MARGIN, (
        "an omitted min_fatigue_margin defaults to 1.000"
    )
    assert program["required_ppk"] == C.DEFAULT_REQUIRED_PPK, (
        "an omitted required_ppk defaults to 1.000"
    )
    assert program["amortization_method"] == C.FORECAST_BASIS, (
        "the supplied amortization_method is untouched by the defaulting"
    )


def test_program_creation_without_amortization_method_is_rejected(api: ApiClient):
    """PRD §3.1: "Finally `amortization_method` must be either `FORECAST_BASIS` or
    `ACTUAL_BASIS`, and it decides which of two very different tooling-recovery
    formulas runs every time a lot ships."
    PRD §2.8: "`ERR_INVALID_REQUEST` — body shape, required fields, enum
    membership, numeric constraints and measurement typing, on every endpoint."

    Design: Corner/entities/program_creation_missing_required_amortization_method_is_rejected
    """
    payload = F.without(
        F.program_payload(program_code="PGM-NOAMORT"), "amortization_method"
    )

    validate_error(
        api.create_program(payload, PROGRAM_MANAGER_HEADERS), ERR_INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0, (
        "a body missing a required field must not leave a CustomerProgram row behind"
    )


def test_program_creation_with_unknown_application_class_is_rejected(api: ApiClient):
    """PRD §3.1: "The single most consequential field is `application_class`, which
    must be one of `AUTOMOTIVE_SAFETY`, `AUTOMOTIVE_NON_SAFETY`,
    `MEDICAL_IMPLANT`, `MEDICAL_DEVICE` or `INDUSTRIAL`; it selects which fatigue
    criterion the engineering stack applies, which packaging methods the shipping
    dock may use, and how deep the approval documentation runs."
    PRD §2.8: "`ERR_INVALID_REQUEST` — body shape, required fields, enum
    membership, numeric constraints and measurement typing, on every endpoint."

    Design: Corner/entities/program_creation_with_invalid_enum_application_class_rejected
    """
    payload = F.program_payload(
        program_code="PGM-BADENUM", application_class="AEROSPACE"
    )

    validate_error(
        api.create_program(payload, PROGRAM_MANAGER_HEADERS), ERR_INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0, (
        "an application_class outside the five members must not be persisted"
    )


def test_program_retrieval_returns_the_stored_row_unchanged(api: ApiClient):
    """PRD §2.4: "`CustomerProgram.version` is incremented **only** by the program
    quoting operation, `POST /customer-programs/{id}/quote`, and by nothing else."
    PRD §3.1: "A freshly opened program starts its commitment ledger at rest:
    `open_commitment_pieces` is initialised to the same number as
    `committed_pieces`, while `allocated_pieces`, `shipped_pieces` and
    `quarantined_lot_count` all start at 0."

    Design: Corner/entities/program_retrieval_returns_the_stored_row_unchanged
    """
    created = validate_success(
        api.create_program(F.program_payload(), PROGRAM_MANAGER_HEADERS), 201
    )

    fetched = validate_success(api.get_program(created["id"], PROGRAM_MANAGER_HEADERS))

    assert fetched == created, (
        "a read with no intervening mutation must return the stored row byte for byte"
    )
    assert fetched["version"] == 1, (
        "reading a program is not a quoting operation, so version stays at 1"
    )
    assert fetched["open_commitment_pieces"] == created["committed_pieces"], (
        "the commitment ledger reads back at rest"
    )


def test_program_listing_paginates_with_total_count_and_has_more(api: ApiClient):
    """PRD §2.3: "Unless a subsection states otherwise, list endpoints return rows
    sorted by `created_at` in ascending order, so the oldest row appears first and
    paging forward walks the collection chronologically."
    PRD §2.3: "The `meta` object of every list response carries `limit` and `offset`
    echoing the effective values in force, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` set true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/program_listing_paginates_with_total_count_and_has_more
    """
    codes = ["PGM-P1", "PGM-P2", "PGM-P3"]
    for code in codes:
        validate_success(
            api.create_program(
                F.program_payload(program_code=code), PROGRAM_MANAGER_HEADERS
            ),
            201,
        )

    first_page, first_meta = validate_paginated(
        api.list_programs(PROGRAM_MANAGER_HEADERS, {"limit": 2, "offset": 0})
    )
    assert first_meta["limit"] == 2, "meta echoes the effective limit in force"
    assert first_meta["offset"] == 0, "meta echoes the effective offset in force"
    assert first_meta["total_count"] == 3, (
        "total_count counts every matching row before pagination is applied"
    )
    assert first_meta["has_more"] is True, "one row remains beyond the first page of two"
    assert [row["program_code"] for row in first_page] == codes[:2], (
        "rows are returned oldest first"
    )

    second_page, second_meta = validate_paginated(
        api.list_programs(PROGRAM_MANAGER_HEADERS, {"limit": 2, "offset": 2})
    )
    assert second_meta["total_count"] == 3, (
        "total_count is independent of the page being served"
    )
    assert second_meta["has_more"] is False, "no rows remain beyond the last page"
    assert [row["program_code"] for row in second_page] == codes[2:], (
        "paging forward continues chronologically"
    )


def test_program_listing_default_page_size_is_ten(api: ApiClient):
    """PRD §2.3: "`limit` controls page size; it defaults to 10 when omitted, has a
    minimum of 1 and a maximum of 100."
    PRD §2.3: "`offset` controls how many rows are skipped before the page begins;
    it defaults to 0 and has a minimum of 0 with no upper bound."

    Design: Corner/entities/program_listing_default_page_size_is_ten
    """
    for index in range(11):
        validate_success(
            api.create_program(
                F.program_payload(program_code=f"PGM-D{index:02d}"),
                PROGRAM_MANAGER_HEADERS,
            ),
            201,
        )

    rows, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))

    assert meta["limit"] == 10, "an omitted limit defaults to 10"
    assert meta["offset"] == 0, "an omitted offset defaults to 0"
    assert len(rows) == 10, "the default page carries at most ten rows"
    assert meta["total_count"] == 11, "total_count reports all eleven stored programs"
    assert meta["has_more"] is True, "the eleventh row remains beyond the default page"
    assert rows[0]["program_code"] == "PGM-D00", (
        "a defaulted offset of 0 starts at the oldest row"
    )


def test_material_spec_is_immutable_and_exposes_no_version_field(api: ApiClient):
    """PRD §2.4: "Three resources are deliberately write-once and carry only `id`
    and `created_at`, with **both** `updated_at` and `version` absent from their
    representations entirely: a `MaterialSpec`, a `CriticalCharacteristic` and an
    `InspectionRecord` are never edited after creation, so there is nothing for
    those two fields to describe."

    Design: Corner/entities/material_spec_is_immutable_and_exposes_no_version_field
    """
    created = validate_success(
        api.create_material_spec(F.material_spec_payload(), DESIGN_ENGINEER_HEADERS), 201
    )

    A.assert_write_once_resource(created)

    fetched = validate_success(
        api.get_material_spec(created["id"], DESIGN_ENGINEER_HEADERS)
    )
    A.assert_write_once_resource(fetched)
    assert fetched == created, "a write-once row reads back exactly as it was written"


def test_material_spec_biocompatible_defaults_false_when_omitted(api: ApiClient):
    """PRD §3.1: "`biocompatible` records whether the grade plus coating is
    qualified for implant or device contact and defaults to false."

    Design: Corner/entities/material_spec_biocompatible_defaults_false_when_omitted
    """
    payload = F.without(F.material_spec_payload(), "biocompatible")

    spec = validate_success(
        api.create_material_spec(payload, DESIGN_ENGINEER_HEADERS), 201
    )

    assert spec["biocompatible"] is False, (
        "an omitted biocompatible defaults to false, not null"
    )
    assert spec["salt_spray_hours"] == 96, (
        "the supplied coating endurance is untouched by the defaulting"
    )


def test_design_creation_computes_every_engineering_field_from_geometry(api: ApiClient):
    """PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the
    incoming `X-User-ID`, leaves `reviewed_by_user_id` null, sets
    `current_revision_no` to 1 with `superseded_revision_no` null, sets
    `release_status` to `DRAFT`, and then runs the complete engineering stack."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear
    modulus multiplied by the wire diameter raised to the fourth power, divided by
    the product of eight, the mean coil diameter cubed, and the active coil count,
    with the result rounded half up to three decimal places."
    PRD §3.2: "Evaluating that expression at `max_working_load_n` and rounding half
    up to two decimal places gives `shear_stress_max_mpa`; evaluating it at
    `min_working_load_n` and rounding the same way gives `shear_stress_min_mpa`."
    PRD §3.2: "The amplitude and mean split is taken from the **unrounded** stress
    values, not from the two rounded fields: `stress_amplitude_mpa` is the
    unrounded maximum-load stress minus the unrounded minimum-load stress, divided
    by two, rounded half up to two decimal places once at the end;
    `mean_stress_mpa` is the sum of those same two unrounded stresses divided by
    two, rounded half up to two decimal places once at the end."
    PRD §3.2: "Which one binds is decided by the owning program's
    `application_class`: the design's `fatigue_criterion` is set to `SODERBERG`
    when the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN`
    for `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator
    belonging to the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "A ratio of at least 1.300 yields ten million cycles."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from
    millimetres to metres by dividing by one thousand, multiplied by that area,
    multiplied by the material's `density_kg_per_m3`, rounded half up to exactly
    six decimal places."
    PRD §3.2: "`tangle_risk_index` is the free length divided by the outer
    diameter, rounded half up to three decimal places."
    PRD §3.2: "`tangle_risk_class` is `HIGH` when that index is at least 4.000
    **or** the `end_type` is `HOOK_EXTENSION`, and `LOW` in every other case."

    Design: Corner/entities/design_creation_computes_every_engineering_field_from_geometry
    """
    program = X.open_program(api)
    material = X.register_material(api)

    design = validate_success(
        api.create_design(
            F.design_payload(program["id"], material["id"]), DESIGN_ENGINEER_HEADERS
        ),
        201,
    )

    assert design["release_status"] == C.RELEASE_DRAFT, "a new design opens in DRAFT"
    assert design["current_revision_no"] == 1, "current_revision_no is set to 1"
    assert design["superseded_revision_no"] is None, "superseded_revision_no starts null"
    assert design["reviewed_by_user_id"] is None, "reviewed_by_user_id is left null"

    assert design["spring_rate_n_per_mm"] == C.D1_SPRING_RATE, (
        "spring rate is computed from geometry and shear modulus to 3 decimals"
    )
    assert design["shear_stress_max_mpa"] == C.D1_SHEAR_STRESS_MAX, (
        "shear_stress_max_mpa is the Wahl-corrected stress at the maximum load"
    )
    assert design["shear_stress_min_mpa"] == C.D1_SHEAR_STRESS_MIN, (
        "shear_stress_min_mpa is the Wahl-corrected stress at the minimum load"
    )
    assert design["stress_amplitude_mpa"] == C.D1_STRESS_AMPLITUDE, (
        "the amplitude is split from the unrounded stresses and rounded once"
    )
    assert design["mean_stress_mpa"] == C.D1_MEAN_STRESS, (
        "the mean is split from the unrounded stresses and rounded once"
    )
    assert design["fatigue_criterion"] == C.CRITERION_GOODMAN, (
        "an INDUSTRIAL program binds the GOODMAN line"
    )
    assert design["fatigue_margin_ratio"] == C.D1_FATIGUE_MARGIN_GOODMAN, (
        "the margin is the reciprocal of the criterion denominator to 3 decimals"
    )
    assert design["predicted_fatigue_life_cycles"] == 10_000_000, (
        "a margin of at least 1.300 selects the ten-million-cycle tier"
    )
    assert design["wire_mass_per_piece_kg"] == C.D1_WIRE_MASS_PER_PIECE_KG, (
        "per-piece wire mass is carried to exactly six decimals"
    )
    assert design["tangle_risk_index"] == C.D1_TANGLE_RISK_INDEX, (
        "the tangle index is free length over outer diameter to 3 decimals"
    )
    assert design["tangle_risk_class"] == C.TANGLE_LOW, (
        "an index below 4.000 on a ground end is LOW risk"
    )
    A.assert_audited_resource(design)


def test_design_creation_ignores_a_client_supplied_spring_rate(api: ApiClient):
    """PRD §3.2: "Nothing outside the design's own geometry and the linked
    material's shear modulus contributes."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear
    modulus multiplied by the wire diameter raised to the fourth power, divided by
    the product of eight, the mean coil diameter cubed, and the active coil count,
    with the result rounded half up to three decimal places."

    Design: Corner/entities/design_creation_extra_field_spring_rate_input_ignored
    """
    program = X.open_program(api)
    material = X.register_material(api)
    payload = F.design_payload(
        program["id"], material["id"], spring_rate_n_per_mm=999.999
    )

    design = validate_success(api.create_design(payload, DESIGN_ENGINEER_HEADERS), 201)

    assert design["spring_rate_n_per_mm"] == C.D1_SPRING_RATE, (
        "a client-supplied spring rate contributes nothing to the computed field"
    )


def test_design_system_fields_are_stamped_from_the_header_not_the_body(api: ApiClient):
    """PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the
    incoming `X-User-ID`, leaves `reviewed_by_user_id` null, sets
    `current_revision_no` to 1 with `superseded_revision_no` null, sets
    `release_status` to `DRAFT`, and then runs the complete engineering stack."
    PRD §2.1: "The server records it on the resources those roles touch — as
    `created_by_user_id` and `reviewed_by_user_id` on a spring design,
    `set_by_user_id` on a machine setup, `certified_by_user_id` on a wire lot,
    `inspected_by_user_id` on an inspection record, and `submitted_by_user_id` on a
    qualification submission — and it compares such recorded values against the
    incoming `X-User-ID` for the two segregation-of-duties gates, but it never
    compares an opaque identifier to any entity's `id`."

    Design: Corner/entities/design_system_fields_are_stamped_from_the_header_not_the_body
    """
    program = X.open_program(api)
    material = X.register_material(api)
    authoring_headers = make_headers("de-07", C.ROLE_DESIGN_ENGINEER)
    payload = F.design_payload(
        program["id"],
        material["id"],
        created_by_user_id="de-99",
        release_status=C.RELEASE_PROTOTYPE,
        current_revision_no=7,
    )

    design = validate_success(api.create_design(payload, authoring_headers), 201)

    assert design["created_by_user_id"] == "de-07", (
        "created_by_user_id is stamped from the incoming X-User-ID, not the body"
    )
    assert design["release_status"] == C.RELEASE_DRAFT, (
        "release_status is set to DRAFT by the server regardless of the body"
    )
    assert design["current_revision_no"] == 1, (
        "current_revision_no is set to 1 by the server regardless of the body"
    )
    assert design["reviewed_by_user_id"] is None, (
        "reviewed_by_user_id is left null on creation"
    )


def test_design_creation_with_unknown_program_id_returns_program_not_found(
    api: ApiClient,
):
    """PRD §2.8: "Foreign keys carried in a request body are resolved after the path
    but before any business rule reads them."
    PRD §2.8: "`ERR_PROGRAM_NOT_FOUND` — on `GET`/`POST /customer-programs/{id}/*`,
    `POST /spring-designs`, `POST /qualification-submissions`,
    `POST /shipment-lots`."

    Design: Corner/entities/design_creation_with_unknown_program_id_returns_program_not_found
    """
    material = X.register_material(api)
    payload = F.design_payload(NON_EXISTENT_UUID, material["id"])

    validate_error(
        api.create_design(payload, DESIGN_ENGINEER_HEADERS), ERR_PROGRAM_NOT_FOUND, 404
    )

    _, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0, (
        "an unresolvable program_id must not leave a SpringDesign row behind"
    )


def test_characteristic_listing_is_scoped_to_its_parent_design(api: ApiClient):
    """PRD §3.3: "While a design is still `DRAFT`, the authoring `DesignEngineer`
    builds its statistical-process-control plan by adding **critical
    characteristics**, each of which is an immutable sub-resource of the design."
    PRD §3.3: "The plan of one design can be read back as a sub-resource list."
    PRD §2.3: "The `meta` object of every list response carries `limit` and `offset`
    echoing the effective values in force, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` set true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/characteristic_listing_is_scoped_to_its_parent_design
    """
    program = X.open_program(api)
    material = X.register_material(api)
    first_design = X.draft_design(api, program["id"], material["id"])
    second_design = X.draft_design(
        api, program["id"], material["id"], part_number="D2"
    )
    X.add_characteristic(api, first_design["id"])
    validate_success(
        api.add_characteristic(
            second_design["id"],
            F.non_safety_characteristic_payload(),
            DESIGN_ENGINEER_HEADERS,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_characteristics(first_design["id"], DESIGN_ENGINEER_HEADERS)
    )

    assert meta["total_count"] == 1, (
        "the sub-resource list counts only the parent design's own plan"
    )
    assert len(rows) == 1, "a sibling design's characteristic must not leak into the page"
    assert rows[0]["char_code"] == C.CHAR_FREE_LENGTH, (
        "the row returned is the one added to this design"
    )
    assert rows[0]["design_id"] == first_design["id"], (
        "every row of the list belongs to the design in the path"
    )


def test_characteristic_is_immutable_and_defaults_its_spc_gates(api: ApiClient):
    """PRD §3.3: "Two optional fields carry the quality weight: `is_safety_critical`
    defaults to false, and when it is true an out-of-control subgroup on this
    characteristic escalates the entire production run onto a quality hold;
    `cpk_floor`, the short-run capability floor for this characteristic, defaults to
    1.333 and is compared with the measured index using an at-least test."
    PRD §2.4: "Three resources are deliberately write-once and carry only `id` and
    `created_at`, with **both** `updated_at` and `version` absent from their
    representations entirely: a `MaterialSpec`, a `CriticalCharacteristic` and an
    `InspectionRecord` are never edited after creation, so there is nothing for
    those two fields to describe."

    Design: Corner/entities/characteristic_is_immutable_and_defaults_its_spc_gates
    """
    program = X.open_program(api)
    material = X.register_material(api)
    design = X.draft_design(api, program["id"], material["id"])
    payload = F.without(
        F.characteristic_payload(), "is_safety_critical", "cpk_floor"
    )

    characteristic = validate_success(
        api.add_characteristic(design["id"], payload, DESIGN_ENGINEER_HEADERS), 201
    )

    assert characteristic["is_safety_critical"] is False, (
        "an omitted is_safety_critical defaults to false"
    )
    assert characteristic["cpk_floor"] == C.DEFAULT_CPK_FLOOR, (
        "an omitted cpk_floor defaults to 1.333"
    )
    A.assert_write_once_resource(characteristic)


def test_characteristic_with_lsl_above_nominal_rejects_inverted_limits(api: ApiClient):
    """PRD §3.3: "It also declares the print `nominal_value`, a `lsl` lower
    specification limit that must be strictly less than the nominal, and a `usl`
    upper specification limit that must be strictly greater than the nominal."
    PRD §2.8: "`ERR_INVALID_REQUEST` — body shape, required fields, enum
    membership, numeric constraints and measurement typing, on every endpoint."

    Design: Corner/entities/characteristic_with_lsl_above_nominal_rejects_inverted_limits
    """
    program = X.open_program(api)
    material = X.register_material(api)
    design = X.draft_design(api, program["id"], material["id"])
    payload = F.characteristic_payload(nominal_value=60.0, lsl=60.2, usl=60.5)

    validate_error(
        api.add_characteristic(design["id"], payload, DESIGN_ENGINEER_HEADERS),
        ERR_INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(
        api.list_characteristics(design["id"], DESIGN_ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        "a lsl at or above the nominal must not be persisted into the plan"
    )


def test_tooling_asset_creation_seeds_the_amortization_ledger_as_pending(api: ApiClient):
    """PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING`
    with `recovered_cents` at 0 and `unamortized_cents` equal to
    `original_cost_cents`."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay
    null: until the customer has granted full approval, nobody knows over how many
    pieces the tool will be recovered."

    Design: Corner/entities/tooling_asset_creation_seeds_the_amortization_ledger_as_pending
    """
    program = X.open_program(api)
    material = X.register_material(api)
    design = X.draft_design(api, program["id"], material["id"])

    tool = validate_success(
        api.create_tooling_asset(
            F.tooling_payload(design["id"]), ENGINEERING_MANAGER_HEADERS
        ),
        201,
    )

    assert tool["amortization_status"] == C.AMORT_PENDING, (
        "a newly capitalised tool opens in PENDING"
    )
    assert tool["recovered_cents"] == 0, "recovered_cents opens at 0"
    assert tool["unamortized_cents"] == tool["original_cost_cents"], (
        "unamortized_cents opens equal to original_cost_cents"
    )
    assert tool["amortization_basis_pieces"] is None, (
        "amortization_basis_pieces stays null until full approval is granted"
    )
    assert tool["amort_per_piece_cents"] is None, (
        "amort_per_piece_cents stays null until full approval is granted"
    )
    A.assert_tooling_ledger_conserved(tool)
    A.assert_audited_resource(tool)


def test_wire_lot_creation_initialises_the_three_ledger_quantities(api: ApiClient):
    """PRD §3.5: "At receipt the three buckets are opened with all mass free:
    `on_hand_kg` equals `received_kg`, while `reserved_kg` and `consumed_kg` both
    start at 0.000."
    PRD §3.5: "`certification_status` starts at `UNCERTIFIED`, and both
    `tensile_test_mpa` and `certified_by_user_id` are null."

    Design: Corner/entities/wire_lot_creation_initialises_the_three_ledger_quantities
    """
    material = X.register_material(api)

    lot = validate_success(
        api.create_wire_lot(
            F.wire_lot_payload(material["id"]), QUALITY_INSPECTOR_HEADERS
        ),
        201,
    )

    assert lot["received_kg"] == 800.0, "received_kg is the conserved quantity as booked"
    assert lot["on_hand_kg"] == 800.0, "on_hand_kg opens equal to received_kg"
    assert lot["reserved_kg"] == 0.0, "reserved_kg opens at 0.000"
    assert lot["consumed_kg"] == 0.0, "consumed_kg opens at 0.000"
    assert lot["certification_status"] == C.CERT_UNCERTIFIED, (
        "certification_status starts at UNCERTIFIED"
    )
    assert lot["tensile_test_mpa"] is None, "tensile_test_mpa starts null"
    assert lot["certified_by_user_id"] is None, "certified_by_user_id starts null"
    A.assert_wire_ledger_conserved(lot)
    A.assert_audited_resource(lot)


def test_coiling_machine_creation_rejects_a_negative_changeover_buffer(api: ApiClient):
    """PRD §3.6: "A `PlantAdmin` commissions each computer-controlled coiler with a
    `machine_code` unique across all machines, a `max_wire_diameter_mm` greater
    than zero giving the largest wire the coiler can form, and
    `changeover_buffer_minutes`, the whole number of minutes of tooling changeover
    that must separate two setup windows on this machine, which must be at least 0."
    PRD §2.8: "`ERR_INVALID_REQUEST` — body shape, required fields, enum
    membership, numeric constraints and measurement typing, on every endpoint."

    Design: Corner/entities/coiling_machine_creation_rejects_a_negative_changeover_buffer
    """
    payload = F.machine_payload(changeover_buffer_minutes=-1)

    validate_error(
        api.create_machine(payload, PLANT_ADMIN_HEADERS), ERR_INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api.list_machines(PLANT_ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        "a changeover buffer below zero must not commission a coiler"
    )


def test_coiling_machine_creation_starts_idle_with_no_active_setup(api: ApiClient):
    """PRD §3.6: "A new coiler opens in `machine_state` `IDLE` with `active_setup_id`
    null."
    PRD §2.10: "`CoilingMachine.active_setup_id` is a denormalised pointer resolved
    as the single machine setup row on that machine whose `setup_status` is
    `ACTIVE`, and is null when no such row exists; it is never accepted as an input."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of that row — and `version`, an
    integer that begins at 1 when the row is created and increases by 1 each time
    the row is mutated."

    Design: Corner/entities/coiling_machine_creation_starts_idle_with_no_active_setup
    """
    machine = validate_success(
        api.create_machine(F.machine_payload(), PLANT_ADMIN_HEADERS), 201
    )

    assert machine["machine_state"] == C.MACHINE_IDLE, "a new coiler opens IDLE"
    assert machine["active_setup_id"] is None, (
        "active_setup_id is null while no setup on the coiler is ACTIVE"
    )
    assert machine["max_wire_diameter_mm"] == 4.0, "the commissioned ceiling is echoed"
    assert machine["changeover_buffer_minutes"] == 45, (
        "the commissioned changeover buffer is echoed"
    )
    A.assert_audited_resource(machine)
    assert machine["version"] == 1, "an unoccupied coiler is still at version 1"


def test_machine_setup_retrieval_returns_the_stored_window_and_pointers(api: ApiClient):
    """PRD §3.6: "The payload names the `machine_id` of the coiler, the `design_id`
    being set up, the `tooling_asset_id` of the tool set being mounted, and the
    occupation window as `window_start` (inclusive) and `window_end` (exclusive),
    both ISO 8601 UTC instants."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's
    `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the
    coiler's `version` by 1."
    PRD §2.10: "`MachineSetup.superseded_by_setup_id` is likewise a denormalised
    pointer to the setup whose creation superseded this one, and is null unless the
    row's `setup_status` is `SUPERSEDED`."

    Design: Corner/entities/machine_setup_retrieval_returns_the_stored_window_and_pointers
    """
    world = X.scheduled_setup_world(api)

    setup = validate_success(api.get_setup(world.setup_id, PROCESS_TECHNICIAN_HEADERS))

    assert setup == world.setup, "the booking response and the read agree row for row"
    assert setup["machine_id"] == world.machine_id, "the setup points at its coiler"
    assert setup["design_id"] == world.design_id, "the setup points at its design"
    assert setup["tooling_asset_id"] == world.tooling_id, (
        "the setup points at the mounted tool set"
    )
    assert setup["window_start"].replace(".000Z", "Z") == C.CLOCK_SETUP_DAY_START, (
        "the booked window start reads back as stored"
    )
    assert setup["window_end"].replace(".000Z", "Z") == C.CLOCK_SETUP_WINDOW_END, (
        "the booked window end reads back as stored"
    )
    assert setup["setup_status"] == C.SETUP_SCHEDULED, "the booking opens SCHEDULED"
    assert setup["set_by_user_id"] == PROCESS_TECHNICIAN_PRIMARY, (
        "set_by_user_id is stamped from the booking technician's X-User-ID"
    )
    assert setup["superseded_by_setup_id"] is None, (
        "superseded_by_setup_id is null unless the row is SUPERSEDED"
    )
    A.assert_audited_resource(setup)


def test_run_creation_defaults_both_status_axes_and_every_counter(api: ApiClient):
    """PRD §3.7: "A newly opened run starts on both axes at rest — `process_status`
    `FAI_PENDING`, `quality_status` `OPEN`, `fai_disposition` `PENDING`,
    `heat_treat_state` `NOT_STARTED`, `peening_verified` false, `produced_pieces`
    and `scrapped_pieces` at 0, `wire_consumed_kg` at 0.000, and both
    `min_cpk_observed` and `min_ppk_observed` null."
    PRD §3.7: "Start from the design's **stored** `wire_mass_per_piece_kg`, already
    rounded to six decimal places."
    PRD §3.7: "Multiply it by `planned_pieces`."
    PRD §3.7: "Inflate that product by a scrap allowance of three percent — that is,
    multiply by one plus 0.03."
    PRD §3.7: "Round the result half up to three decimal places, once, at the very
    end."
    PRD §3.7: "That figure is written to the run's `wire_reserved_kg` and is the
    value compared against the heat's `on_hand_kg` for the sufficiency gate; the
    heat's ledger is never fed into the computation, only compared against its
    result."

    Design: Corner/entities/run_creation_defaults_both_status_axes_and_every_counter
    """
    world = X.certified_wire_world(api)

    run = validate_success(
        api.create_run(
            F.run_payload(world.setup_id, world.wire_lot_id, world.design_id),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        201,
    )

    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        "the process axis starts at FAI_PENDING"
    )
    assert run["quality_status"] == C.QUALITY_OPEN, "the quality axis starts at OPEN"
    assert run["fai_disposition"] == C.FAI_PENDING, "fai_disposition starts at PENDING"
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        "heat_treat_state starts at NOT_STARTED"
    )
    assert run["peening_verified"] is False, "peening_verified starts false"
    assert run["produced_pieces"] == 0, "produced_pieces starts at 0"
    assert run["scrapped_pieces"] == 0, "scrapped_pieces starts at 0"
    assert run["wire_consumed_kg"] == 0.0, "wire_consumed_kg starts at 0.000"
    assert run["min_cpk_observed"] is None, "min_cpk_observed starts null"
    assert run["min_ppk_observed"] is None, "min_ppk_observed starts null"

    expected_reserved = A.expected_wire_reserved_kg(
        world.design["wire_mass_per_piece_kg"], 26_000
    )
    assert run["wire_reserved_kg"] == expected_reserved, (
        "the reservation scales the stored six-decimal mass by the plan plus 3 percent"
    )
    A.assert_audited_resource(run)


def test_run_creation_links_three_independent_parents_in_one_write(api: ApiClient):
    """PRD §3.7: "Opening a production run is the `ProcessTechnician`'s act and joins
    three things: the mounted setup named by `setup_id`, the certified heat named by
    `wire_lot_id`, and the design named by `design_id`, together with
    `planned_pieces`, the number of pieces the run is scheduled to coil, which must
    be greater than zero."
    PRD §3.7: "The `design_id` in the body must equal the design the setup was tooled
    for, or the answer is `ERR_SETUP_DESIGN_MISMATCH` (HTTP 422)."
    PRD §3.7: "The heat's `material_spec_id` must equal the design's
    `material_spec_id`, or the answer is `ERR_MATERIAL_MISMATCH` (HTTP 422)."
    PRD §3.7: "Runs may be listed filtered by `setup_id`, `wire_lot_id`, `design_id`,
    `process_status` and `quality_status`."

    Design: Corner/entities/run_creation_links_three_independent_parents_in_one_write
    """
    world = X.certified_wire_world(api)

    run = validate_success(
        api.create_run(
            F.run_payload(world.setup_id, world.wire_lot_id, world.design_id),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        201,
    )

    assert run["setup_id"] == world.setup_id, "the run carries the mounted setup"
    assert run["wire_lot_id"] == world.wire_lot_id, "the run carries the certified heat"
    assert run["design_id"] == world.design_id, "the run carries the design it coils"
    assert run["planned_pieces"] == 26_000, "planned_pieces is echoed as supplied"

    for filter_field, filter_value in (
        ("setup_id", world.setup_id),
        ("wire_lot_id", world.wire_lot_id),
        ("design_id", world.design_id),
    ):
        rows, meta = validate_paginated(
            api.list_runs(PROCESS_TECHNICIAN_HEADERS, {filter_field: filter_value})
        )
        assert meta["total_count"] == 1, (
            f"the single write is reachable by its {filter_field} parent"
        )
        assert rows[0]["id"] == run["id"], (
            f"filtering by {filter_field} returns the run just opened"
        )


def test_inspection_record_is_immutable_and_stamps_its_record_kind_from_the_route(
    api: ApiClient,
):
    """PRD §3.7: "The server stamps `record_kind` as `FAI` from the endpoint itself;
    `record_kind` is never accepted from a request body."
    PRD §3.8: "The server stamps `record_kind` as `SPC` — again from the endpoint,
    never from the body — stamps `inspected_by_user_id`, and computes the full
    statistic set of section 3.7 including the pooled `ppk_value`."
    PRD §3.7: "`subgroup_size` is the number of values in `measurements`."
    PRD §2.4: "Three resources are deliberately write-once and carry only `id` and
    `created_at`, with **both** `updated_at` and `version` absent from their
    representations entirely: a `MaterialSpec`, a `CriticalCharacteristic` and an
    `InspectionRecord` are never edited after creation, so there is nothing for
    those two fields to describe."

    Design: Corner/entities/inspection_record_is_immutable_and_stamps_its_record_kind_from_the_route
    """
    world = X.running_run_world(api)
    characteristic = world.characteristics[0]

    assert world.fai_records[0]["record_kind"] == C.RECORD_KIND_FAI, (
        "the first-article endpoint stamps record_kind as FAI"
    )
    A.assert_write_once_resource(world.fai_records[0])

    payload = F.measurement_payload(
        characteristic["id"], X.in_control_subgroup(characteristic)
    )
    payload["record_kind"] = C.RECORD_KIND_FAI

    record = validate_success(
        api.record_inspection(world.run_id, payload, QUALITY_INSPECTOR_HEADERS), 201
    )

    assert record["record_kind"] == C.RECORD_KIND_SPC, (
        "the in-process endpoint stamps record_kind as SPC, never taking it from the body"
    )
    assert record["inspected_by_user_id"] == QUALITY_INSPECTOR_PRIMARY, (
        "inspected_by_user_id is stamped from the inspector's X-User-ID"
    )
    assert record["subgroup_size"] == 3, (
        "subgroup_size is the number of values in measurements"
    )
    A.assert_write_once_resource(record)

    fetched = validate_success(
        api.get_inspection_record(record["id"], QUALITY_INSPECTOR_HEADERS)
    )
    assert fetched == record, "an immutable record reads back exactly as it was stamped"


def test_oven_creation_initialises_scheduled_load_to_zero(api: ApiClient):
    """PRD §3.9: "A `PlantAdmin` commissions each stress-relief oven with a unique
    `oven_code`, a `capacity_kg` greater than zero giving the maximum aggregate mass
    that may be co-resident in the oven at any instant, and a `max_temp_c` greater
    than zero giving the temperature ceiling it holds."
    PRD §3.9: "A new oven opens with `scheduled_load_kg` at 0.000, and that field is
    always the sum of `load_kg` over the oven's batches whose `batch_status` is
    `SCHEDULED` or `RUNNING`."

    Design: Corner/entities/oven_creation_initialises_scheduled_load_to_zero
    """
    oven = validate_success(api.create_oven(F.oven_payload(), PLANT_ADMIN_HEADERS), 201)

    assert oven["oven_code"] == C.CANONICAL_OVEN_CODE, "the oven code is echoed"
    assert oven["capacity_kg"] == 600.0, "the commissioned capacity is echoed"
    assert oven["max_temp_c"] == 450.0, "the commissioned temperature ceiling is echoed"
    assert oven["scheduled_load_kg"] == 0.0, (
        "an oven with no batches opens with scheduled_load_kg at 0.000"
    )
    A.assert_audited_resource(oven)


def test_batch_peening_requested_defaults_false_when_omitted(api: ApiClient):
    """PRD §3.9: "The payload names the `oven_id`, the `run_id` whose pieces are being
    relieved, the occupation window as `window_start` and `window_end` — both
    **inclusive** for this entity — the weighed basket `load_kg` in kilograms carried
    to three decimal places and greater than zero, the requested soak `target_temp_c`
    greater than zero, and the optional `peening_requested` flag recording whether
    shot peening is part of this batch's recipe, defaulting to false."
    PRD §3.9: "Note the asymmetry between the two peening fields: `peening_requested`
    is the recipe's intent stated at scheduling time, while `peening_performed` is
    the outcome recorded at discharge and stays null until the batch is `COMPLETE`."
    PRD §3.9: "A successful booking opens the batch in `batch_status` `SCHEDULED` and
    adds its `load_kg` to the oven's `scheduled_load_kg`."

    Design: Corner/entities/batch_peening_requested_defaults_false_when_omitted
    """
    world = X.complete_run_world(api)
    oven = X.commission_oven(api)
    payload = F.without(F.batch_payload(oven["id"], world.run_id), "peening_requested")

    batch = validate_success(
        api.create_batch(payload, PROCESS_TECHNICIAN_HEADERS), 201
    )

    assert batch["peening_requested"] is False, (
        "an omitted peening_requested defaults to false, not null"
    )
    assert batch["peening_performed"] is None, (
        "peening_performed stays null until the batch is COMPLETE"
    )
    assert batch["batch_status"] == C.BATCH_SCHEDULED, "the booking opens SCHEDULED"
    assert batch["load_kg"] == 250.0, "the weighed basket load is echoed as booked"

    reloaded_oven = X.refresh_oven(api, oven["id"])
    assert reloaded_oven["scheduled_load_kg"] == 250.0, (
        "the booked load is added to the oven's scheduled_load_kg"
    )
    A.assert_audited_resource(batch)


def test_submission_starts_at_round_one_in_submitted_status(api: ApiClient):
    """PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status`
    `SUBMITTED` with `submitted_by_user_id` stamped from the header,
    `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."

    Design: Corner/entities/submission_starts_at_round_one_in_submitted_status
    """
    world = X.running_run_world(api)

    submission = validate_success(
        api.create_submission(
            F.submission_payload(world.program_id, world.design_id),
            PROGRAM_MANAGER_HEADERS,
        ),
        201,
    )

    assert submission["round_no"] == 1, "a filing opens at round_no 1"
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "a filing opens in SUBMITTED status"
    )
    assert submission["submitted_by_user_id"] == PROGRAM_MANAGER_PRIMARY, (
        "submitted_by_user_id is stamped from the filing manager's header"
    )
    assert submission["interim_piece_cap"] is None, "interim_piece_cap starts null"
    assert submission["reviewed_by_program_id"] is None, (
        "reviewed_by_program_id starts null"
    )
    assert submission["decided_at"] is None, "decided_at starts null"
    assert submission["program_id"] == world.program_id, "the package names its program"
    assert submission["design_id"] == world.design_id, "the package names its design"
    A.assert_audited_resource(submission)


def test_shipment_lot_snapshots_the_frozen_price_fields_at_creation(api: ApiClient):
    """PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED`
    with `packaging_method` null, and it snapshots the commercial terms at creation:
    `unit_price_cents` from the program's `quoted_unit_price_cents`,
    `tooling_amort_per_piece_cents` from the program's
    `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as
    `piece_count` multiplied by `unit_price_cents`."
    PRD §3.11: "`tooling_recovery_cents` starts at 0 and `shipped_at` and
    `quarantine_reason` start null."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count`
    and `allocated_pieces` increases by it, conserving `committed_pieces`, and
    `delivery_posture` is re-derived."

    Design: Corner/entities/shipment_lot_snapshots_the_frozen_price_fields_at_creation
    """
    world = X.approved_world(api)
    program = X.refresh_program(api, world.program_id)

    lot = validate_success(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        201,
    )

    assert lot["lot_status"] == C.LOT_ALLOCATED, "a surviving lot opens ALLOCATED"
    assert lot["packaging_method"] is None, "packaging_method starts null"
    assert lot["unit_price_cents"] == program["quoted_unit_price_cents"], (
        "unit_price_cents is snapshotted from the program's quoted unit price"
    )
    assert lot["tooling_amort_per_piece_cents"] == (
        program["quoted_tooling_amort_per_piece_cents"]
    ), "the per-piece amortization is snapshotted from the program's quote"
    assert lot["extended_price_cents"] == 1_000 * lot["unit_price_cents"], (
        "extended_price_cents is piece_count multiplied by the snapshotted unit price"
    )
    assert lot["tooling_recovery_cents"] == 0, "tooling_recovery_cents starts at 0"
    assert lot["shipped_at"] is None, "shipped_at starts null"
    assert lot["quarantine_reason"] is None, "quarantine_reason starts null"

    reloaded_program = X.refresh_program(api, world.program_id)
    assert reloaded_program["allocated_pieces"] == 1_000, (
        "allocated_pieces increases by the lot's piece_count"
    )
    assert reloaded_program["open_commitment_pieces"] == (
        program["open_commitment_pieces"] - 1_000
    ), "open_commitment_pieces decreases by the same piece_count"
    A.assert_commitment_conserved(reloaded_program)
    A.assert_audited_resource(lot)


def test_wire_lot_retrieval_returns_the_created_heat_verbatim(api: ApiClient):
    """PRD §3.5: "The receiving payload names the `material_spec_id`, the mill's
    `heat_number` — unique across all wire lots — and `received_kg`, the kilograms
    received, which must be greater than zero and is carried to three decimal places."
    PRD §3.5: "Wire lots may be listed filtered by `material_spec_id` and
    `certification_status`, and each read exposes the full three-bucket ledger."

    Design: Corner/entities/wire_lot_retrieval_returns_the_created_heat_verbatim
    """
    material = X.register_material(api)
    created = validate_success(
        api.create_wire_lot(
            F.wire_lot_payload(material["id"], received_kg=612.5),
            QUALITY_INSPECTOR_HEADERS,
        ),
        201,
    )

    fetched = validate_success(
        api.get_wire_lot(created["id"], QUALITY_INSPECTOR_HEADERS)
    )

    assert fetched == created, (
        "a read with no intervening posting returns the booked heat unchanged"
    )
    assert fetched["heat_number"] == C.CANONICAL_HEAT_NUMBER, (
        "the mill heat number reads back verbatim"
    )
    assert fetched["material_spec_id"] == material["id"], (
        "the heat reads back against the grade it was purchased on"
    )
    assert fetched["received_kg"] == 612.5, "received_kg reads back as booked"
    assert fetched["on_hand_kg"] == 612.5, "the read exposes the on-hand bucket"
    assert fetched["reserved_kg"] == 0.0, "the read exposes the reserved bucket"
    assert fetched["consumed_kg"] == 0.0, "the read exposes the consumed bucket"
    A.assert_wire_ledger_conserved(fetched)
