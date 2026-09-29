"""
Entity-surface corners: defaults, derived classifications, not-found handling,
required fields, enum validation, append-only rows, server-minted fields,
listing pagination and the zeroed store baseline.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_STORE_NOT_FOUND
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_array_envelope,
    assert_common_fields,
    assert_error_envelope,
    assert_instant,
    assert_instant_is_none,
    assert_mass,
    assert_money,
    assert_object_envelope,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import (
    COMPLIANCE_MANAGER_HEADERS,
    REGULATOR_HEADERS,
    make_technician_headers,
)
from test_helpers.types import (
    APPLICABILITY_EXEMPT,
    APPLICABILITY_REGULATED,
    ATTEMPT_AWAITING_VERIFICATION,
    CATEGORY_COMFORT_COOLING,
    CATEGORY_INDUSTRIAL_PROCESS_REFRIGERATION,
    CERT_TYPE_I,
    CERT_TYPE_II,
    CERT_TYPE_III,
    DETECTION_AUTOMATED_MONITORING,
    DETECTION_MANUAL_INSPECTION,
    EVENT_OPEN,
    EVENT_VERIFIED_CLOSED,
    METHOD_ROLLING_AVERAGE,
    ODS_HCFC,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    PRESSURE_LOW,
    REGION_WEST,
    STATE_COMPLIANT,
    SYSTEM_ACTIVE,
)


def _store_and_r404a(api):
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    rt404 = X.create_r404a(api)
    return store, rt404


def test_system_create_defaults_the_leak_rate_method_and_derives_its_class(api):
    """
    The optional method falls back to the rolling average, and the four
    classification fields are computed from the nameplate charge, the category and
    the chemistry's pressure class rather than taken from the request.

    Design: Corner/entities/system_create_applies_leak_rate_method_default_and_derived_fields
    """
    store, rt404 = _store_and_r404a(api)

    system = validate_success(
        api.create_system(
            F.system_payload(store["id"], rt404["id"], leak_rate_method=F.OMIT),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    assert system["leak_rate_method"] == METHOD_ROLLING_AVERAGE
    assert system["applicability"] == APPLICABILITY_REGULATED
    assert_money(system["threshold_pct"], 20.0, "threshold_pct")
    assert system["required_certification_type"] == CERT_TYPE_II
    assert_system_charge(
        system, current_charge_lbs=80.0, leak_rate_pct=0.0, exceedance_count_12mo=0
    )
    assert_instant(
        system["leak_rate_baseline_at"], "2025-01-15T00:00:00Z", "leak_rate_baseline_at"
    )
    assert_system_axes(
        system, operational_status=SYSTEM_ACTIVE, compliance_state=STATE_COMPLIANT
    )
    assert_instant_is_none(system["retrofit_due_on"], "retrofit_due_on")
    assert_common_fields(system, expected_version=1)


def test_applicability_threshold_and_certification_class_are_each_derived(api):
    """
    Three systems separate the three derivations: a 30.0 lb comfort-cooling rack is
    exempt at a 10.0 percent threshold, a 4.0 lb appliance needs only the smallest
    certification class, and a low-pressure industrial system needs the largest.

    Design: Corner/entities/system_applicability_and_certification_class_derived_from_charge_and_pressure
    """
    store, rt404 = _store_and_r404a(api)
    rt123 = validate_success(
        api.create_refrigerant_type(
            F.refrigerant_type_payload(
                name="R-123", gwp=79, pressure_class=PRESSURE_LOW, ods_class=ODS_HCFC
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        expected_status=201,
    )

    exempt = X.create_system(
        api,
        store["id"],
        rt404["id"],
        system_category=CATEGORY_COMFORT_COOLING,
        full_charge_lbs=30.0,
        initial_charge_lbs=10.0,
        installed_on="2025-04-01T00:00:00Z",
        leak_rate_method=F.OMIT,
    )
    small = X.create_system(
        api,
        store["id"],
        rt404["id"],
        full_charge_lbs=4.0,
        initial_charge_lbs=2.0,
        installed_on="2025-04-02T00:00:00Z",
        leak_rate_method=F.OMIT,
    )
    industrial = X.create_system(
        api,
        store["id"],
        rt123["id"],
        system_category=CATEGORY_INDUSTRIAL_PROCESS_REFRIGERATION,
        full_charge_lbs=120.0,
        initial_charge_lbs=100.0,
        installed_on="2025-04-03T00:00:00Z",
        leak_rate_method=F.OMIT,
    )

    assert exempt["applicability"] == APPLICABILITY_EXEMPT
    assert_money(exempt["threshold_pct"], 10.0, "threshold_pct")
    assert exempt["required_certification_type"] == CERT_TYPE_II

    assert small["applicability"] == APPLICABILITY_EXEMPT
    assert small["required_certification_type"] == CERT_TYPE_I
    assert_money(small["threshold_pct"], 20.0, "threshold_pct")

    assert industrial["applicability"] == APPLICABILITY_REGULATED
    assert_money(industrial["threshold_pct"], 30.0, "threshold_pct")
    assert industrial["required_certification_type"] == CERT_TYPE_III

    assert_store_posture(
        X.get_store(api, store["id"]),
        regulated_system_count=1,
        total_regulated_charge_lbs=120.0,
    )


def test_store_get_with_an_unused_uuid_is_a_not_found_error(api):
    """
    A syntactically valid but unused identifier is a 404 carrying the store's own
    error identifier and a human-readable message, not an empty success body.

    Design: Corner/entities/store_get_with_unknown_id_returns_store_not_found
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    X.create_store(api)

    response = api.get_store(NON_EXISTENT_UUID, COMPLIANCE_MANAGER_HEADERS)
    validate_error(response, ERR_STORE_NOT_FOUND, 404)
    body = assert_error_envelope(response)
    assert body["data"]["message"] != ""


def test_service_record_without_the_expected_version_is_an_invalid_request(api):
    """
    The concurrency token is a required input, so omitting it is refused rather
    than defaulted to the current version, and no record is written.

    Design: Corner/entities/service_record_missing_expected_system_version_is_invalid_request
    """
    env = X.base_env(api, with_second_technician=False)

    validate_error(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                F.OMIT,
                cylinder_id=env["cyl1_id"],
                refrigerant_added_lbs=10.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == 1
    listing = assert_array_envelope(
        api.list_service_records(
            COMPLIANCE_MANAGER_HEADERS, {"system_id": env["system_id"]}
        )
    )
    assert listing["meta"]["total_count"] == 0


def test_system_create_with_an_undeclared_category_is_rejected(api):
    """
    A plausible but undeclared category is refused rather than stored or coerced to
    a default, which would silently pick a leak threshold.

    Design: Corner/entities/system_create_with_invalid_enum_category_is_rejected
    """
    store, rt404 = _store_and_r404a(api)

    validate_error(
        api.create_system(
            F.system_payload(
                store["id"],
                rt404["id"],
                system_category="WALK_IN_COOLER",
                leak_rate_method=F.OMIT,
            ),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    listing = assert_array_envelope(
        api.list_systems(COMPLIANCE_MANAGER_HEADERS, {"store_id": store["id"]})
    )
    assert listing["meta"]["total_count"] == 0


def test_repair_attempt_is_an_append_only_evidence_row(api):
    """
    An evidence row carries an identifier and a creation stamp and neither a
    version nor an update stamp, and it keeps the work instant it was filed with
    rather than the clock.

    Design: Corner/entities/repair_attempt_is_immutable_with_no_version_or_update_surface
    """
    env = X.repaired_event_env(api)

    body = assert_object_envelope(
        api.get_repair_attempt(env["attempt1_id"], COMPLIANCE_MANAGER_HEADERS)
    )
    attempt = body["data"]
    assert_append_only_fields(attempt)
    assert attempt["outcome"] == ATTEMPT_AWAITING_VERIFICATION
    assert attempt["attempt_number"] == 1
    assert attempt["was_late"] is False
    assert_instant(
        attempt["repair_completed_at"], "2026-08-05T09:00:00Z", "repair_completed_at"
    )


def test_system_create_naming_an_unknown_store_is_a_not_found_error(api):
    """
    The owning-store reference is resolved before any business rule, so an unused
    identifier yields a 404 and leaves no orphan system behind.

    Design: Corner/entities/system_create_with_unknown_store_returns_store_not_found
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    rt404 = X.create_r404a(api)

    validate_error(
        api.create_system(
            F.system_payload(NON_EXISTENT_UUID, rt404["id"], leak_rate_method=F.OMIT),
            COMPLIANCE_MANAGER_HEADERS,
        ),
        ERR_STORE_NOT_FOUND,
        404,
    )

    listing = assert_array_envelope(api.list_systems(COMPLIANCE_MANAGER_HEADERS))
    assert listing["meta"]["total_count"] == 0


def test_supplied_identifier_and_computed_fields_are_ignored_on_a_record(api):
    """
    Every computed field is server-minted: a request that supplies an identifier,
    a retention date, a resulting charge, an occupancy end and a void flag gets
    the formulas' answers back instead.

    Design: Corner/entities/service_record_system_and_computed_fields_input_ignored
    """
    env = X.base_env(api, with_second_technician=False)

    record = validate_success(
        api.create_service_record(
            F.service_record_payload(
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                X.system_version(api, env["system_id"]),
                cylinder_id=env["cyl1_id"],
                refrigerant_added_lbs=10.0,
                performed_at="2026-08-01T00:00:00Z",
                duration_minutes=60,
                id="11111111-1111-4111-8111-111111111111",
                retention_until="2026-09-01T00:00:00Z",
                system_charge_after_lbs=999.9,
                occupies_until="2026-08-01T23:59:00Z",
                voided=True,
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        expected_status=201,
    )

    assert record["id"] != "11111111-1111-4111-8111-111111111111"
    assert_instant(record["retention_until"], "2029-08-01T00:00:00Z", "retention_until")
    assert_mass(record["system_charge_after_lbs"], 90.0, "system_charge_after_lbs")
    assert_money(record["leak_rate_pct_after"], 10.0, "leak_rate_pct_after")
    assert_instant(record["occupies_until"], "2026-08-01T01:00:00Z", "occupies_until")
    assert_instant(
        record["equipment_released_at"],
        "2026-08-01T02:00:00Z",
        "equipment_released_at",
    )
    assert record["voided"] is False


def _three_events_on_one_store(api):
    """
    Three empty systems on one store, each carrying one manually declared event,
    declared in system order so the creation ordering is unambiguous.
    """
    store, rt404 = _store_and_r404a(api)
    events = []
    for index, installed_on in enumerate(
        ("2025-03-01T00:00:00Z", "2025-03-02T00:00:00Z", "2025-03-03T00:00:00Z")
    ):
        system = X.create_system(
            api,
            store["id"],
            rt404["id"],
            full_charge_lbs=60.0,
            initial_charge_lbs=0.0,
            installed_on=installed_on,
            leak_rate_method=F.OMIT,
        )
        detection_method = (
            DETECTION_AUTOMATED_MONITORING if index == 1 else DETECTION_MANUAL_INSPECTION
        )
        payload = F.leak_event_payload(
            system["id"],
            detected_at="2026-08-01T00:00:00Z",
            detection_method=detection_method,
        )
        headers = REGULATOR_HEADERS if index == 2 else COMPLIANCE_MANAGER_HEADERS
        event = validate_success(
            api.create_leak_event(payload, headers), expected_status=201
        )
        events.append({"system_id": system["id"], "event_id": event["id"]})
    return store, events


def test_leak_event_listing_pages_in_creation_order_and_filters_by_status(api):
    """
    The first page carries the two oldest rows and reports more to come, the second
    carries the remaining one and reports none, and the status and system filters
    narrow the count without disturbing the ordering.

    Design: Corner/entities/leak_event_listing_paginates_and_filters_by_status
    """
    store, events = _three_events_on_one_store(api)

    page1 = assert_array_envelope(
        api.list_leak_events(COMPLIANCE_MANAGER_HEADERS, {"limit": 2, "offset": 0})
    )
    assert page1["meta"]["total_count"] == 3
    assert page1["meta"]["has_more"] is True
    assert len(page1["data"]) == 2
    assert page1["data"][0]["id"] == events[0]["event_id"]
    assert page1["data"][1]["id"] == events[1]["event_id"]

    page2 = assert_array_envelope(
        api.list_leak_events(COMPLIANCE_MANAGER_HEADERS, {"limit": 2, "offset": 2})
    )
    assert page2["meta"]["total_count"] == 3
    assert page2["meta"]["has_more"] is False
    assert len(page2["data"]) == 1
    assert page2["data"][0]["id"] == events[2]["event_id"]

    assert X.list_leak_events(api, status=EVENT_OPEN)["meta"]["total_count"] == 3
    assert (
        X.list_leak_events(api, status=EVENT_VERIFIED_CLOSED)["meta"]["total_count"] == 0
    )

    by_system = X.list_leak_events(api, system_id=events[1]["system_id"])
    assert by_system["meta"]["total_count"] == 1
    assert by_system["data"][0]["detection_method"] == DETECTION_AUTOMATED_MONITORING

    assert_store_posture(
        X.get_store(api, store["id"]),
        open_leak_event_count=3,
        compliance_status=POSTURE_AT_RISK,
    )


def test_new_store_round_trips_its_inputs_with_every_posture_field_zeroed(api):
    """
    A freshly created store returns its four inputs unchanged and every derived
    posture field at its zero value, which is the baseline later exposure and
    posture assertions are measured against.

    Design: Corner/entities/store_retrieval_returns_stored_and_zeroed_posture_fields
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    created = X.create_store(api)

    body = assert_object_envelope(
        api.get_store(created["id"], COMPLIANCE_MANAGER_HEADERS)
    )
    store = body["data"]
    assert store["name"] == "Northgate Market"
    assert store["store_code"] == "NG-001"
    assert store["state_code"] == "CA"
    assert store["region"] == REGION_WEST

    assert_store_posture(
        store,
        compliance_status=POSTURE_COMPLIANT,
        chronic_leaker_flag=False,
        regulated_system_count=0,
        open_leak_event_count=0,
        overdue_leak_event_count=0,
        mandated_retrofit_count=0,
        total_regulated_charge_lbs=0.0,
        vented_loss_lbs=0.0,
        penalty_exposure_total_usd=0.00,
    )
    assert_common_fields(store, expected_version=1)
