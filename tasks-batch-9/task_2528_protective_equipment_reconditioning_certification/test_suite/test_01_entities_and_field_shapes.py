"""Entity field shapes, server-minted system fields, declared defaults and the
referential-existence rules of the reconditioning API.

Every test builds all of its own state through the documented endpoints, since
the server is restarted and the database emptied before each test runs.
"""
from test_helpers import (
    COMPLIANCE_1,
    DEFAULT_COOLDOWN_MINUTES,
    INTAKE_CLERK,
    PLANT_MANAGER,
    REQUIRED_WAIVER_VERSION,
    TECHNICIAN_1,
    TECHNICIAN_1_USER_ID,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_approved_part,
    assert_component_inspection,
    assert_customer_account,
    assert_intake_shipment,
    assert_model_spec,
    assert_test_bench,
    count_shipment_payload,
    create_account,
    create_bench,
    create_customer_account_payload,
    create_equipment_unit_payload,
    create_intake_shipment_payload,
    create_loaner_unit_payload,
    create_model,
    create_model_spec_payload,
    create_part,
    create_test_bench_payload,
    disassemble_unit,
    get_success_data,
    identify_unit,
    inspect_component,
    is_iso8601_timestamp,
    is_valid_uuid,
    liability_acknowledgment_payload,
    set_clock,
    setup_accepted_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

# A well-formed identifier that no row in an empty plant database can carry.
_UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_model_spec_creation_returns_every_declared_field(api):
    """Registering a model echoes every declared field, including the nested
    component criteria, the version the server mints and the default for
    `reconditionable` when the registration omits it.

    PRD: "A `PlantManager` registers one by supplying the `manufacturer` name, a
    `model_code` between 1 and 40 characters that must be unique across all
    model specifications, and the `standard_code` of the applicable performance
    standard, which is printed verbatim on every recertification label the plant
    issues for that model."

    PRD: "`reconditionable` is a boolean that defaults to true when omitted from
    the registration and is set false for models the manufacturer has withdrawn
    from reconditioning entirely."

    PRD: "Most resources additionally carry an `updated_at` timestamp in the same
    format and an integer `version` that starts at 1 when the resource is created
    and increases by exactly one on every mutation that changes the row."

    Design: Corner/entities/model_spec_creation_returns_every_declared_field
    """
    set_clock()

    payload = create_model_spec_payload()
    payload.pop("reconditionable")

    response = api.create_model_spec(payload, PLANT_MANAGER)
    data = validate_success(response, 201)

    assert_model_spec(data)
    assert data["manufacturer"] == TEST_DEFAULTS["MANUFACTURER"]
    assert data["model_code"] == TEST_DEFAULTS["MODEL_CODE"]
    assert data["standard_code"] == TEST_DEFAULTS["STANDARD_CODE"]
    assert data["shell_material"] == "POLYCARBONATE"
    assert data["max_service_life_years"] == TEST_DEFAULTS["MAX_SERVICE_LIFE_YEARS"]
    assert data["warranty_years"] == TEST_DEFAULTS["WARRANTY_YEARS"]
    assert data["record_retention_years"] == TEST_DEFAULTS["RECORD_RETENTION_YEARS"]
    assert data["pass_si_max"] == TEST_DEFAULTS["PASS_SI_MAX"]
    assert data["repair_si_max"] == TEST_DEFAULTS["REPAIR_SI_MAX"]
    assert data["max_retest_count"] == TEST_DEFAULTS["MAX_RETEST_COUNT"]
    assert data["required_component_codes"] == ["SHELL"]

    assert len(data["component_criteria"]) == 1
    criteria = data["component_criteria"][0]
    assert criteria["code"] == "SHELL"
    assert criteria["metric"] == "crack_length_mm"
    assert criteria["metric_direction"] == "HIGHER_IS_WORSE"
    assert criteria["replace_threshold"] == TEST_DEFAULTS["SHELL_REPLACE_THRESHOLD"]
    assert criteria["fail_threshold"] == TEST_DEFAULTS["SHELL_FAIL_THRESHOLD"]
    assert criteria["unit"] == "mm"

    assert data["reconditionable"] is True
    assert data["version"] == 1


def test_get_test_bench_returns_the_stored_row(api):
    """Reading one impact rig returns the values its registration wrote, and a
    rig that has never been calibrated still reads a null calibration expiry.

    PRD: "A rig carries a `bench_code` unique across all benches, a `test_type`
    of either `DROP_IMPACT` or `PNEUMATIC_RAM`, a `daily_session_quota` of at
    least 1 capping how many shell-test sessions it may hold per UTC calendar
    day, and a `cooldown_minutes` between 0 and 240 that defaults to 45 minutes
    when the registration omits it."

    PRD: "A newly registered rig has a null `calibration_valid_until` and
    therefore cannot host a single session until a `PlantManager` calibrates it;
    calibration supplies the `calibration_valid_until` expiry directly and
    advances the bench's `version` by one."

    PRD: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/get_test_bench_returns_the_stored_row
    """
    set_clock()
    bench = create_bench(calibrate=False)

    response = api.get_test_bench(bench["id"], TECHNICIAN_1)
    data = validate_success(response, 200)

    assert response.json()["response_type"] == "object"
    assert_test_bench(data)
    assert data["id"] == bench["id"]
    assert data["bench_code"] == "RIG-1"
    assert data["test_type"] == "DROP_IMPACT"
    assert data["daily_session_quota"] == TEST_DEFAULTS["BENCH_DAILY_SESSION_QUOTA"]
    assert data["cooldown_minutes"] == DEFAULT_COOLDOWN_MINUTES
    assert data["calibration_valid_until"] is None
    assert data["version"] == 1


def test_list_approved_parts_filters_by_component_and_paginates(api):
    """The parts-cage list applies its filters before the page window: two SHELL
    parts and one LINER part exist, so a one-row page filtered to SHELL reports a
    total of two with more rows remaining, while the unfiltered model read
    reports all three.

    PRD: "Approved parts may be filtered by `model_spec_id` and
    `component_code`."

    PRD: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the size of the full
    filtered result set before the page window is applied and `has_more`
    indicates whether any rows remain beyond the current page."

    The PRD also orders list results by `created_at` ascending, so the one-row
    page must carry the earliest-created SHELL part.

    Design: Corner/entities/list_approved_parts_filters_by_component_and_paginates
    """
    set_clock()
    model = create_model()

    shell_1 = create_part(
        model["id"],
        part_number="PN-SHELL-1",
        component_code="SHELL",
        unit_price_cents=4500,
        received_qty=4,
    )
    shell_2 = create_part(
        model["id"],
        part_number="PN-SHELL-2",
        component_code="SHELL",
        unit_price_cents=5200,
        received_qty=2,
    )
    liner_1 = create_part(
        model["id"],
        part_number="PN-LINER-1",
        component_code="LINER",
        unit_price_cents=3100,
        received_qty=6,
    )

    response = api.list_approved_parts(
        PLANT_MANAGER,
        params={
            "model_spec_id": model["id"],
            "component_code": "SHELL",
            "limit": 1,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    assert rows[0]["id"] == shell_1["id"]
    assert rows[0]["component_code"] == "SHELL"
    assert rows[0]["part_number"] == "PN-SHELL-1"
    assert rows[0]["unit_price_cents"] == 4500
    assert_approved_part(rows[0])

    unfiltered_rows, unfiltered_meta = validate_paginated(
        api.list_approved_parts(PLANT_MANAGER, params={"model_spec_id": model["id"]})
    )
    assert unfiltered_meta["total_count"] == 3
    assert unfiltered_meta["has_more"] is False
    assert [row["id"] for row in unfiltered_rows] == [
        shell_1["id"],
        shell_2["id"],
        liner_1["id"],
    ]


def test_get_unknown_equipment_unit_returns_not_found(api):
    """A well-formed identifier that addresses no unit is a referential failure,
    answered with the unit's own not-found code, ERR_UNIT_NOT_FOUND, and HTTP
    404 rather than an empty success envelope.

    PRD: "Within this rung the path identifier is resolved first, and then
    foreign-key fields in this declaration order: `customer_account_id`,
    `model_spec_id`, `intake_shipment_id`, `equipment_unit_id`, `test_bench_id`,
    `approved_part_id`, `loaner_unit_id`."

    PRD: "A read of the inspections recorded on a unit, the labels issued for a
    unit, or the destruction records raised for a unit resolves the unit
    identifier first; if no such unit exists, the request fails with
    `ERR_UNIT_NOT_FOUND` before any child collection is considered."

    Design: Corner/entities/get_unknown_equipment_unit_returns_not_found
    """
    set_clock()

    response = api.get_equipment_unit(_UNKNOWN_UUID, INTAKE_CLERK)
    error = validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND.value, 404)

    assert response.json()["response_type"] == "error"
    assert error["error_id"] == "ERR_UNIT_NOT_FOUND"
    assert len(error["message"].strip()) > 0


def test_create_customer_account_missing_required_sport_rejected(api):
    """A program's primary sport is a required input with no default, so opening
    an account without it is a request-schema failure carrying
    ERR_INVALID_REQUEST and HTTP 400.

    PRD: "A `PlantManager` opens an account for each program the plant serves,
    supplying the `org_name` — between 1 and 120 characters, and required —
    together with an `org_type` drawn from `SCHOOL`, `CLUB`, `COLLEGE` or
    `MUNICIPAL`, a primary `sport` drawn from `FOOTBALL`, `LACROSSE`, `HOCKEY` or
    `BASEBALL`, and a `contact_email` used for billing and notification."

    PRD: "**Request schema** — a required field absent, a field of the wrong JSON
    type, an enum value outside its declared set, a numeric field out of range
    (any of the peak-g readings below zero, a part-line `quantity` below 1, a
    `counted_unit_count` below 1, a `limit` outside 1 through 100, a negative
    `offset`, a `record_retention_years` below 1), or a window whose `window_end`
    is not strictly after its `window_start`: `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_customer_account_missing_required_sport_rejected
    """
    set_clock()

    payload = create_customer_account_payload()
    payload.pop("sport")

    response = api.create_customer_account(payload, PLANT_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert error["error_id"] == "ERR_INVALID_REQUEST"
    assert response.status_code == 400


def test_test_bench_cooldown_minutes_default_is_45(api):
    """A rig registered without a cooldown persists the declared default of 45
    minutes — not null and not zero — because the bench-window rule pads every
    requested session interval by that field.

    PRD: "A rig carries a `bench_code` unique across all benches, a `test_type`
    of either `DROP_IMPACT` or `PNEUMATIC_RAM`, a `daily_session_quota` of at
    least 1 capping how many shell-test sessions it may hold per UTC calendar
    day, and a `cooldown_minutes` between 0 and 240 that defaults to 45 minutes
    when the registration omits it."

    Design: Corner/entities/test_bench_cooldown_minutes_default_is_45
    """
    set_clock()

    payload = create_test_bench_payload(
        bench_code="RIG-2", test_type="PNEUMATIC_RAM", daily_session_quota=4
    )
    payload.pop("cooldown_minutes")

    response = api.create_test_bench(payload, PLANT_MANAGER)
    data = validate_success(response, 201)

    assert_test_bench(data)
    assert data["cooldown_minutes"] == DEFAULT_COOLDOWN_MINUTES
    assert data["cooldown_minutes"] == 45
    assert data["bench_code"] == "RIG-2"
    assert data["test_type"] == "PNEUMATIC_RAM"
    assert data["daily_session_quota"] == 4
    assert data["calibration_valid_until"] is None
    assert data["version"] == 1


def test_shipment_count_computes_discrepancy_and_quarantines(api):
    """Counting three shells against a packing list of two writes a discrepancy
    of one and forks the shipment to QUARANTINED instead of COUNTED, leaving the
    resolution unset until acceptance.

    PRD: "The count writes `counted_unit_count`, derives `discrepancy_count` as
    the counted tally minus the declared tally — so a shortfall is negative and
    an overage positive — and advances the shipment's `version` by one."

    PRD: "The resulting status depends entirely on that difference: when
    `discrepancy_count` is exactly zero the shipment moves `DRAFT → COUNTED`, and
    when it is anything other than zero the shipment moves `DRAFT → QUARANTINED`
    instead."

    Design: Corner/entities/shipment_count_computes_discrepancy_and_quarantines
    """
    set_clock()
    account = create_account()
    shipment = get_success_data(
        api.create_intake_shipment(
            create_intake_shipment_payload(account["id"], declared_unit_count=2),
            INTAKE_CLERK,
        )
    )
    assert shipment["status"] == "DRAFT"
    assert shipment["version"] == 1

    response = api.count_intake_shipment(
        shipment["id"], count_shipment_payload(3), INTAKE_CLERK
    )
    data = validate_success(response, 200)

    assert_intake_shipment(data)
    assert data["id"] == shipment["id"]
    assert data["declared_unit_count"] == 2
    assert data["counted_unit_count"] == 3
    assert data["discrepancy_count"] == 1
    assert data["status"] == "QUARANTINED"
    assert data["discrepancy_resolution"] is None
    assert data["version"] == 2


def test_system_fields_minted_on_customer_account_create(api):
    """The account's identity and system fields are server-minted: a bare UUID
    identifier, an ISO 8601 creation timestamp, version 1 on create and version 2
    after the first mutation, which here is the liability acknowledgment.

    PRD: "Every persisted resource is addressed by an `id` that the server mints
    as a UUID."

    PRD: "Identifiers carry no type prefix — a shipment `id` and a unit `id` are
    indistinguishable by shape, and clients must not attempt to infer a
    resource's kind from its identifier."

    PRD: "Most resources additionally carry an `updated_at` timestamp in the same
    format and an integer `version` that starts at 1 when the resource is created
    and increases by exactly one on every mutation that changes the row."

    PRD: "That computed posture takes exactly three values: `MISSING` while
    `liability_waiver_version` is still null; `ON_FILE` when the recorded revision
    is exactly the revision the plant currently requires, which is the string
    `2026.1`; and `STALE` when some other, non-null revision is on file."

    Design: Corner/entities/system_fields_minted_on_customer_account_create
    """
    set_clock()

    created = validate_success(
        api.create_customer_account(create_customer_account_payload(), PLANT_MANAGER),
        201,
    )
    assert_customer_account(created)
    assert is_valid_uuid(created["id"])
    assert "_" not in created["id"]
    assert is_iso8601_timestamp(created["created_at"])
    assert created["version"] == 1
    assert created["liability_waiver_status"] == "MISSING"
    assert created["liability_waiver_version"] is None
    assert created["open_shipment_count"] == 0

    acknowledged = validate_success(
        api.acknowledge_liability(
            created["id"], liability_acknowledgment_payload(), INTAKE_CLERK
        ),
        200,
    )
    assert_customer_account(acknowledged)
    assert acknowledged["id"] == created["id"]
    assert acknowledged["created_at"] == created["created_at"]
    assert acknowledged["updated_at"] >= acknowledged["created_at"]
    assert acknowledged["version"] == 2
    assert acknowledged["liability_waiver_status"] == "ON_FILE"
    assert acknowledged["liability_waiver_version"] == REQUIRED_WAIVER_VERSION
    assert acknowledged["liability_waiver_signer"] == "R. Vega"
    assert acknowledged["open_shipment_count"] == 0


def test_create_shipment_with_invalid_service_tier_enum_rejected(api):
    """A service tier outside its declared set is a request-schema failure, so it
    is answered with ERR_INVALID_REQUEST and HTTP 400 and no shipment row is
    written for the program.

    PRD: "An `IntakeClerk` opens one against a program by supplying the
    `customer_account_id`, the `sport` the shipment belongs to drawn from
    `FOOTBALL`, `LACROSSE`, `HOCKEY` or `BASEBALL`, a commercial `service_tier` of
    `STANDARD`, `SEASONAL_CONTRACT` or `PRIORITY_RUSH`, the `declared_unit_count`
    of at least one unit that the program wrote on its packing list, and the
    program's competitive season as a `season_start_date` and a
    `season_end_date` at UTC midnight, where `season_end_date` must fall strictly
    after `season_start_date`."

    PRD: "**Request schema** — a required field absent, a field of the wrong JSON
    type, an enum value outside its declared set, a numeric field out of range
    (any of the peak-g readings below zero, a part-line `quantity` below 1, a
    `counted_unit_count` below 1, a `limit` outside 1 through 100, a negative
    `offset`, a `record_retention_years` below 1), or a window whose `window_end`
    is not strictly after its `window_start`: `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_shipment_with_invalid_service_tier_enum_rejected
    """
    set_clock()
    account = create_account()

    response = api.create_intake_shipment(
        create_intake_shipment_payload(
            account["id"], service_tier="GOLD", declared_unit_count=2
        ),
        INTAKE_CLERK,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    rows, meta = validate_paginated(
        api.list_intake_shipments(
            INTAKE_CLERK, params={"customer_account_id": account["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_component_inspection_is_immutable_and_carries_no_version(api):
    """A recorded component measurement is append-only evidence: the row carries
    an identifier and a creation timestamp but no updated timestamp and no
    version at all, and it snapshots the manufacturer criteria that produced its
    verdict together with the measuring technician.

    PRD: "There is one deliberate exception: a `ComponentInspection` is an
    immutable measurement record and therefore carries only `id` and `created_at`
    — it has no `updated_at` and no `version` at all, because a recorded
    measurement is never edited."

    PRD: "The recorded row snapshots the manufacturer criteria in force at that
    moment — `metric_direction_applied`, `replace_threshold_applied` and
    `fail_threshold_applied` are all copied from the criteria object of the unit's
    model whose `code` matches the supplied `component_code` — so that a later
    edit to the model specification cannot retroactively change a verdict already
    reached."

    PRD: "When it is `HIGHER_IS_WORSE`, the verdict is `FAIL` if
    `measurement_value` is greater than or equal to `fail_threshold_applied`,
    otherwise `REPLACE` if `measurement_value` is greater than or equal to
    `replace_threshold_applied`, and otherwise `PASS`."

    PRD: "`inspector_user_id` is taken from the acting `X-User-ID`."

    Design: Corner/entities/component_inspection_is_immutable_and_carries_no_version
    """
    ctx = setup_accepted_shipment(unit_count=1)
    unit = ctx["unit"]
    identify_unit(unit["id"], ctx["model"]["id"])
    disassemble_unit(unit["id"])

    created = inspect_component(unit["id"], headers=TECHNICIAN_1)
    assert_component_inspection(created)
    assert "version" not in created
    assert "updated_at" not in created

    rows, meta = validate_paginated(
        api.list_component_inspections(unit["id"], COMPLIANCE_1)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    row = rows[0]
    assert row["id"] == created["id"]
    assert "version" not in row
    assert "updated_at" not in row
    assert is_iso8601_timestamp(row["created_at"])
    assert row["equipment_unit_id"] == unit["id"]
    assert row["component_code"] == "SHELL"
    assert row["measurement_value"] == TEST_DEFAULTS["SHELL_MEASUREMENT_PASS"]
    assert row["verdict"] == "PASS"
    assert row["replace_threshold_applied"] == TEST_DEFAULTS["SHELL_REPLACE_THRESHOLD"]
    assert row["fail_threshold_applied"] == TEST_DEFAULTS["SHELL_FAIL_THRESHOLD"]
    assert row["metric_direction_applied"] == "HIGHER_IS_WORSE"
    assert row["inspector_user_id"] == TECHNICIAN_1_USER_ID


def test_register_unit_under_unknown_shipment_returns_not_found(api):
    """A unit hangs off its shipment by foreign key, so registering one against an
    unknown shipment identifier resolves at the existence rung to
    ERR_SHIPMENT_NOT_FOUND with HTTP 404 rather than to the unit's own not-found
    code.

    PRD: "**Existence** — a referenced row does not exist. Within this rung the
    path identifier is resolved first, and then foreign-key fields in this
    declaration order: `customer_account_id`, `model_spec_id`,
    `intake_shipment_id`, `equipment_unit_id`, `test_bench_id`,
    `approved_part_id`, `loaner_unit_id`. The error returned is the specific
    not-found code for the first unresolved reference."

    PRD: "An `IntakeClerk` supplies the `intake_shipment_id`, the `serial_number`
    stamped in the shell, and optionally a `declared_model_code` — the model the
    program *claimed* on its packing list, which may be null and which the plant
    treats as a hint rather than as fact."

    Design: Corner/entities/register_unit_under_unknown_shipment_returns_not_found
    """
    set_clock()

    payload = create_equipment_unit_payload(_UNKNOWN_UUID, serial_number="SN-0001")
    payload.pop("declared_model_code")

    response = api.create_equipment_unit(payload, INTAKE_CLERK)
    error = validate_error(response, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value, 404)

    assert error["error_id"] == "ERR_SHIPMENT_NOT_FOUND"
    assert response.status_code == 404


def test_create_loaner_unit_with_unknown_model_spec_returns_not_found(api):
    """A loaner references its model by a foreign key carried in the request body
    rather than in the URL, so an unknown model identifier is answered with
    ERR_MODEL_SPEC_NOT_FOUND and HTTP 404 and no loaner joins the pool.

    PRD: "A loaner unit belongs to exactly one model — loaners are only
    interchangeable within a model — and is registered with its `model_spec_id`,
    a plant `asset_tag` unique across all loaner units, a `condition_grade` of
    `A`, `B` or `C` capturing cosmetic and fit quality, and a
    `certification_valid_until` marking the expiry of the loaner's own
    recertification."

    PRD: "**Existence** — a referenced row does not exist. Within this rung the
    path identifier is resolved first, and then foreign-key fields in this
    declaration order: `customer_account_id`, `model_spec_id`,
    `intake_shipment_id`, `equipment_unit_id`, `test_bench_id`,
    `approved_part_id`, `loaner_unit_id`. The error returned is the specific
    not-found code for the first unresolved reference."

    Design: Corner/entities/create_loaner_unit_with_unknown_model_spec_returns_not_found
    """
    set_clock()

    response = api.create_loaner_unit(
        create_loaner_unit_payload(
            _UNKNOWN_UUID,
            asset_tag="LN-009",
            condition_grade="A",
            certification_valid_until="2026-12-31T00:00:00Z",
        ),
        PLANT_MANAGER,
    )
    error = validate_error(response, ApiErrorId.ERR_MODEL_SPEC_NOT_FOUND.value, 404)
    assert error["error_id"] == "ERR_MODEL_SPEC_NOT_FOUND"

    rows, meta = validate_paginated(api.list_loaner_units(PLANT_MANAGER))
    assert meta["total_count"] == 0
    assert rows == []
