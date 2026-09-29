"""Registering the estate: server-minted fields, declared defaults and refused writes."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    add_service_event,
    assert_asset,
    assert_cents,
    assert_decimal,
    assert_department,
    assert_facility,
    assert_instant,
    assert_service_event,
    get_success_data,
    is_valid_uuid,
    make_asset,
    make_department,
    make_facility,
    pin_clock,
    refresh_asset,
    refresh_facility,
    service_event_rows,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _north_site():
    """Facility NRH alone, with the clock pinned at the startup instant."""
    pin_clock(CLOCK)
    return make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )


def _ct_department(facility_id):
    return make_department(facility_id, name="Diagnostic Imaging CT", modality_scope="CT")


def _ct_scanner(facility_id, department_id, **overrides):
    """The eight-year CT scanner installed 2020-08-02, exactly 2190 days old at the clock."""
    return make_asset(
        facility_id, department_id,
        modality="CT", model_name="Aquilon CT-8", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z", **overrides,
    )


def _asset_rows(api, **params):
    return get_success_data(api.list_assets(_PLANNER, params=params))


# ─── Facilities ───────────────────────────────────────────────────────


def test_a_new_facility_is_minted_with_its_ceiling_and_an_empty_asset_count(api):
    """PRD §3.1: "A facility is created with a display `name` of one to one hundred twenty
    characters that may not be blank, a short `code` of two to eight characters drawn only
    from uppercase letters A through Z and the digits 0 through 9 and unique across all
    facilities, and a `region` that is one of `NORTH`, `SOUTH`, `EAST` or `WEST`."
    PRD §3.1: "The server maintains `active_asset_count` on the facility, which starts at 0
    and always equals the number of equipment assets at that facility whose `status` is
    anything other than `DECOMMISSIONED`."
    PRD §2.6: "`version` is an integer that starts at 1 when the row is created and increases
    by exactly one on every mutation of that row, including mutations performed as a side
    effect of an operation on another resource."
    PRD §2.6: "Every resource carries an `id`, which is a server-minted UUID version 4 string
    with no type prefix."

    Design: Corner/entities/create_facility_with_all_required_fields_returns_system_and_computed_defaults
    """
    pin_clock(CLOCK)

    facility = validate_success(
        api.create_facility(
            {"name": "North Regional Hospital", "code": "NRH", "region": "NORTH",
             "max_concurrent_construction": 3},
            _PLANNER,
        ),
        201,
    )
    assert_facility(facility)
    assert facility["name"] == "North Regional Hospital"
    assert facility["code"] == "NRH"
    assert facility["region"] == "NORTH"
    assert facility["max_concurrent_construction"] == 3
    assert facility["active_asset_count"] == 0
    assert facility["version"] == 1
    assert is_valid_uuid(facility["id"])
    assert_instant(facility["updated_at"], facility["created_at"], "updated_at")


def test_a_facility_that_omits_the_ceiling_is_born_allowing_one_build(api):
    """PRD §3.1: "A facility also declares `max_concurrent_construction`, the largest number
    of live installation projects whose construction intervals may overlap at that site at any
    single instant; it defaults to 1 and must be at least 1 and at most 5."
    PRD §3.1: "Facilities can be listed filtered by `region` and by `code`."

    Design: Corner/entities/create_facility_omitting_max_concurrent_construction_applies_default_one
    """
    pin_clock(CLOCK)

    facility = validate_success(
        api.create_facility(
            {"name": "South Community Hospital", "code": "SCH", "region": "SOUTH"}, _PLANNER
        ),
        201,
    )
    assert_facility(facility)
    assert facility["max_concurrent_construction"] == 1
    assert facility["active_asset_count"] == 0
    assert facility["version"] == 1

    rows = get_success_data(api.list_facilities(_PLANNER, params={"code": "SCH"}))
    assert len(rows) == 1
    assert rows[0]["id"] == facility["id"]
    assert rows[0]["max_concurrent_construction"] == 1


# ─── Departments ──────────────────────────────────────────────────────


def test_a_new_department_carries_server_minted_audit_fields(api):
    """PRD §3.1: "A department declares the `facility_id` that owns it — immutable once set —
    a clinical `name` of one to one hundred twenty characters, and a `modality_scope` that is
    one of `CT`, `MRI`, `CATH_LAB`, `ULTRASOUND`, `LAB` or `SURGICAL`; the modality scope is
    the axis along which clinical downtime is deconflicted."
    PRD §3.1: "Two department fields are written only by the system and never by a caller:
    `utilization_penalty_points`, an integer that starts at 0 and can reach at most 20, and
    `underperformance_flag`, a boolean that starts false and becomes true the first time any
    post-implementation audit of that department's requests returns an underperforming
    verdict."

    Design: Corner/entities/department_system_fields_are_server_minted_on_create
    """
    facility = _north_site()

    department = validate_success(
        api.create_department(
            {"facility_id": facility["id"], "name": "Diagnostic Imaging CT",
             "modality_scope": "CT"},
            _PLANNER,
        ),
        201,
    )
    assert_department(department)
    assert is_valid_uuid(department["id"])
    assert department["version"] == 1
    assert_instant(department["updated_at"], department["created_at"], "updated_at")
    assert department["utilization_penalty_points"] == 0
    assert department["underperformance_flag"] is False
    assert department["facility_id"] == facility["id"]
    assert department["modality_scope"] == "CT"


def test_a_department_raised_under_no_facility_reports_the_missing_facility(api):
    """PRD §2.7: "A body-borne reference — `facility_id`, `department_id`, `cycle_id`,
    `asset_id`, `sponsor_member_id`, `gpo_contract_id`, `trade_in_asset_id`,
    `predecessor_project_id` or `installation_project_id` — that names no existing row yields
    the referenced entity's own not-found error at HTTP 404, and body references are checked
    after path references."
    PRD §2.11: "4. A body-borne reference that resolves to no row — the referenced entity's
    not-found error, 404."

    Design: Corner/entities/create_department_under_unknown_facility_returns_facility_not_found
    """
    pin_clock(CLOCK)

    response = api.create_department(
        {"facility_id": UNKNOWN_UUID, "name": "Diagnostic Imaging CT", "modality_scope": "CT"},
        _PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404)

    assert get_success_data(api.list_departments(_PLANNER)) == []


# ─── Equipment assets ─────────────────────────────────────────────────


def test_a_scanner_read_back_carries_both_its_inputs_and_its_derived_life_picture(api):
    """PRD §3.2: "First, `age_years` is the whole number of days elapsed between
    `install_date` and `ruls_as_of`, divided by 365, rounded half up to two decimals — a
    machine two thousand one hundred ninety days old is exactly 6.00 years old."
    PRD §3.2: "Every asset creation, asset edit and service-event append re-derives the
    asset's remaining-useful-life picture at the current logical clock, and stores that instant
    in `ruls_as_of`."
    PRD §3.1: "Creation runs the remaining-useful-life scoring described next, sets
    `disposition_status` to `NONE` and `trade_in_credit_applied_cents` to 0, and then
    increments the owning facility's `active_asset_count` and bumps that facility's `version`."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."

    Design: Corner/entities/get_asset_returns_stored_inputs_and_derived_ruls_fields
    """
    facility = _north_site()
    department = _ct_department(facility["id"])
    asset = _ct_scanner(facility["id"], department["id"])

    data = validate_success(api.get_asset(asset["id"], _AUDITOR))
    assert_asset(data)
    assert_decimal(data["age_years"], 6.00, "age_years")
    assert_decimal(data["nominal_ruls_score"], 25.00, "nominal_ruls_score")
    assert_decimal(data["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
    assert_decimal(data["service_penalty_points"], 0.00, "service_penalty_points")
    assert data["corrective_count_24m"] == 0
    assert_decimal(data["downtime_hours_24m"], 0.00, "downtime_hours_24m")
    assert data["unresolved_recall"] is False
    assert data["status"] == "IN_SERVICE"
    assert data["disposition_status"] == "NONE"
    assert_cents(data["trade_in_credit_applied_cents"], 0, "trade_in_credit_applied_cents")
    assert_instant(data["ruls_as_of"], CLOCK, "ruls_as_of")
    assert_instant(data["install_date"], "2020-08-02T00:00:00Z", "install_date")

    assert refresh_facility(facility["id"])["active_asset_count"] == 1


def test_extending_the_expected_life_recomputes_both_life_scores(api):
    """PRD §3.1: "A planner may later edit `model_name`, `install_date`,
    `expected_life_years`, `oem_support_end_date` and `acquisition_cost_cents`; every such edit
    re-runs the scoring, re-applies the derate gate, and re-scores any replacement request of
    that asset that is currently `SCORED`, appending a fresh score row whose `reason` is
    `ASSET_CONDITION_CHANGE`."
    PRD §3.2: "Second, the fraction of life remaining is the expected life in years less the
    age in years, divided by the expected life in years."
    PRD §3.2: "Third, the **nominal** score, stored as `nominal_ruls_score`, is that fraction
    multiplied by one hundred, rounded half up to two decimals and then clamped into the range
    0.00 through 100.00; the nominal variant reads nothing but `install_date` and
    `expected_life_years`, and it is never consulted for eligibility, for derating or for the
    safety driver."

    Design: Corner/entities/asset_ruls_fields_are_recomputed_from_inputs_not_accepted_from_client
    """
    facility = _north_site()
    department = _ct_department(facility["id"])
    asset = _ct_scanner(facility["id"], department["id"])

    patched = validate_success(
        api.patch_asset(asset["id"], {"expected_life_years": 10}, _PLANNER)
    )
    assert_asset(patched)
    assert patched["expected_life_years"] == 10
    assert_decimal(patched["age_years"], 6.00, "age_years")
    assert_decimal(patched["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(patched["adjusted_ruls_score"], 40.00, "adjusted_ruls_score")
    assert_decimal(patched["service_penalty_points"], 0.00, "service_penalty_points")
    assert_instant(patched["ruls_as_of"], CLOCK, "ruls_as_of")
    assert patched["version"] == 2
    assert patched["status"] == "IN_SERVICE"


def test_a_scanner_registered_at_the_wrong_site_is_refused_and_counts_nothing(api):
    """PRD §3.1: "The supplied `facility_id` must equal the owning department's own
    `facility_id`; a mismatch is rejected with `ERR_ASSET_FACILITY_MISMATCH`."
    PRD §2.11: "10. An asset whose `facility_id` is not the owning department's `facility_id`,
    on asset creation and asset patch — `ERR_ASSET_FACILITY_MISMATCH`, 422."

    Design: Corner/entities/asset_facility_must_equal_owning_department_facility
    """
    north = _north_site()
    south = make_facility(
        name="South Community Hospital", code="SCH", region="SOUTH",
        max_concurrent_construction=1,
    )
    department = _ct_department(north["id"])

    response = api.create_asset(
        {"facility_id": south["id"], "department_id": department["id"], "modality": "CT",
         "model_name": "Aquilon CT-8", "install_date": "2020-08-02T00:00:00Z",
         "expected_life_years": 8, "acquisition_cost_cents": 100000000,
         "oem_support_end_date": "2029-06-01T00:00:00Z"},
        _PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_ASSET_FACILITY_MISMATCH.value, 422)

    assert refresh_facility(south["id"])["active_asset_count"] == 0
    assert refresh_facility(north["id"])["active_asset_count"] == 0

    asset = _ct_scanner(north["id"], department["id"])
    assert_decimal(asset["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
    assert refresh_facility(north["id"])["active_asset_count"] == 1


def test_a_scanner_without_a_support_end_date_is_refused(api):
    """PRD §3.1: "Registering an equipment asset requires its `facility_id`, the
    `department_id` of the clinical department that operates it, a `modality` drawn from the
    same six values as a department's scope, a `model_name` of one to one hundred twenty
    characters, the `install_date` at which the machine entered service, an
    `expected_life_years` between 1 and 30 inclusive, an `acquisition_cost_cents` greater than
    zero, and the `oem_support_end_date` at which the manufacturer's support lapses."
    PRD §2.11: "7. A required input absent, a field of the wrong JSON type, an enum value
    outside its declared set, a string outside its length bounds or a number outside its
    declared range, on every write endpoint — `ERR_VALIDATION`, 422."

    Design: Corner/entities/create_asset_without_oem_support_end_date_returns_422
    """
    facility = _north_site()
    department = _ct_department(facility["id"])

    response = api.create_asset(
        {"facility_id": facility["id"], "department_id": department["id"], "modality": "CT",
         "model_name": "Aquilon CT-8", "install_date": "2020-08-02T00:00:00Z",
         "expected_life_years": 8, "acquisition_cost_cents": 100000000},
        _PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    assert _asset_rows(api, facility_id=facility["id"]) == []
    assert refresh_facility(facility["id"])["active_asset_count"] == 0


# ─── The append-only service log ──────────────────────────────────────


def test_a_service_event_of_an_unknown_category_is_refused(api):
    """PRD §3.2: "Each service event carries the `event_date` on which it occurred, which may
    not be later than the logical clock — a future-dated event is rejected with
    `ERR_EVENT_DATE_IN_FUTURE` — a `category` of `PM`, `CORRECTIVE`, `RECALL` or `UPGRADE`, a
    `downtime_hours` figure with two decimal places that defaults to 0.00 and must be at least
    0 and at most 8760, a `cost_cents` figure that defaults to 0 and may not be negative, a
    `recall_resolved` boolean that defaults to false and is meaningful only for a recall event
    (for every other category the value is ignored), and a free-text `notes` field of up to
    five hundred characters."
    PRD §2.11: "7. A required input absent, a field of the wrong JSON type, an enum value
    outside its declared set, a string outside its length bounds or a number outside its
    declared range, on every write endpoint — `ERR_VALIDATION`, 422."

    Design: Corner/entities/create_service_event_with_unknown_category_returns_422
    """
    facility = _north_site()
    department = _ct_department(facility["id"])
    asset = _ct_scanner(facility["id"], department["id"])

    response = api.create_service_event(
        asset["id"],
        {"event_date": "2026-05-01T00:00:00Z", "category": "PREVENTIVE", "downtime_hours": 2.00},
        _PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    assert service_event_rows(asset["id"]) == []
    after = refresh_asset(asset["id"])
    assert_decimal(after["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
    assert_decimal(after["downtime_hours_24m"], 0.00, "downtime_hours_24m")
    assert after["version"] == 1


def test_the_service_log_reads_back_append_only_and_oldest_first(api):
    """PRD §2.6: "Three resources are append-only records rather than mutable entities, and
    they carry only `id` and `created_at` — for a `ServiceEvent`, a `PriorityScore` and a
    `CommitteeVote` both `updated_at` and `version` are absent."
    PRD §3.2: "From those, `service_penalty_points` is three points for each corrective event
    plus half a point for each downtime hour, rounded half up to two decimals, and then capped
    at 40.00; the cap applies to this penalty term alone and never to the sum of all
    penalties."
    PRD §3.2: "Service events of an asset can be listed filtered by `category`."
    PRD §2.3: "Rows are always returned sorted by `created_at` ascending."

    Design: Corner/entities/service_events_are_append_only_with_no_update_or_version_field
    """
    facility = _north_site()
    department = _ct_department(facility["id"])
    asset = _ct_scanner(facility["id"], department["id"])
    pm_event = add_service_event(asset["id"], "2026-05-01T00:00:00Z", "PM", downtime_hours=1.00)
    corrective = add_service_event(
        asset["id"], "2026-06-01T00:00:00Z", "CORRECTIVE", downtime_hours=3.00
    )

    rows = get_success_data(api.list_service_events(asset["id"], _AUDITOR))
    assert len(rows) == 2
    assert [row["id"] for row in rows] == [pm_event["id"], corrective["id"]]
    for row in rows:
        assert_service_event(row)
        assert "version" not in row
        assert "updated_at" not in row

    after = refresh_asset(asset["id"])
    assert after["corrective_count_24m"] == 1
    assert_decimal(after["downtime_hours_24m"], 4.00, "downtime_hours_24m")
    assert_decimal(after["service_penalty_points"], 5.00, "service_penalty_points")
    assert_decimal(after["adjusted_ruls_score"], 20.00, "adjusted_ruls_score")
    assert after["version"] == 3

    filtered = get_success_data(
        api.list_service_events(asset["id"], _AUDITOR, params={"category": "CORRECTIVE"})
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == corrective["id"]
