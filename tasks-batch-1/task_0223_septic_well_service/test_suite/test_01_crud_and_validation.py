"""CRUD, creation defaults, field validation, and FK/existence checks.

Translates queue B (Corner) instances from the `entities` and `validations` sections,
plus the RBAC/auth instances, plus the OCC/derived-field instances under
cross_cutting_complexity_layers.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, TEST_USERS, make_field_tech_headers,
    create_account_payload, create_site_payload, create_asset_payload,
    create_technician_payload, create_work_order_payload, create_service_plan_payload,
    assert_account, assert_site,
    create_account, create_site, create_technician, create_route,
    create_service_plan, set_clock, setup_account_site_tech_route,
    create_completed_inspection_wo, create_inspection_report,
    create_completed_work_order, get_site,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FIELD_TECH = TEST_USERS["field_tech_headers"]


# ─── entities section ──────────────────────────────────

def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "A new account opens in GOOD standing and with an
    outstanding_balance_cents of 0."
    PRD §2.4: "The version field is an integer that begins at its initial value and
    increments by one on every mutation that changes the resource".

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    res = api.create_account(create_account_payload(), DISPATCHER)
    account = validate_success(res, 201)
    assert_account(account)
    assert account["standing"] == "GOOD"
    assert account["outstanding_balance_cents"] == 0
    assert account["version"] == 1


def test_get_account_not_found(api):
    """PRD §2.8: "When an endpoint path names a resource by id, that id must resolve to
    an existing resource or the request is rejected with ERR_NOT_FOUND".

    Design: Corner/entities/get_account_not_found
    """
    res = api.get_account("00000000-0000-4000-8000-000000000000", DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_site_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "Required body fields must be present and well-typed, and any enum value
    must fall within its allowed set, or the request fails with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_site_missing_required_field_returns_invalid_request
    """
    account = create_account()
    res = api.create_site({"account_id": account["id"], "address": "1 Pine"}, DISPATCHER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_site_default_service_minutes_applied(api):
    """PRD §3.1: "The service_minutes field is the default on-site duration used to size
    scheduling windows; it defaults to 60 minutes when omitted and must be at least 15
    minutes".

    Design: Corner/entities/create_site_default_service_minutes_applied
    """
    account = create_account()
    res = api.create_site(
        {"account_id": account["id"], "address": "1 Pine", "county_code": "KING"}, DISPATCHER
    )
    site = validate_success(res, 201)
    assert site["service_minutes"] == 60


def test_create_site_bad_fk_returns_fk_not_found(api):
    """PRD §2.8: "when a request body names another resource by foreign key — for example
    an account_id, site_id, work_order_id, inspection_report_id, technician_id, or
    route_id — and that reference does not point to an existing resource, the create is
    rejected with ERR_FK_NOT_FOUND."

    Design: Corner/entities/create_site_bad_fk_returns_fk_not_found
    """
    res = api.create_site(
        {"account_id": "00000000-0000-4000-8000-000000000001",
         "address": "1 Pine", "county_code": "KING"}, DISPATCHER
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=422)


def test_work_order_computed_cost_fields_ignored_on_create(api):
    """PRD §3.3: "A Dispatcher creates a work order in DRAFT with the site_id to be
    serviced". PRD §3.3: "At creation, billing_status is UNBILLED".
    PRD §3.5: "The estimate variant runs at scheduling: ... and it writes
    estimated_cost_cents."

    Design: Corner/entities/work_order_computed_cost_fields_ignored_on_create
    """
    account = create_account()
    site = create_site(account["id"])
    res = api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-01", 540, estimated_gallons=800),
        DISPATCHER,
    )
    wo = validate_success(res, 201)
    assert wo["status"] == "DRAFT"
    assert wo["billing_status"] == "UNBILLED"
    assert wo["estimated_cost_cents"] == 0


def test_create_asset_invalid_enum_returns_invalid_request(api):
    """PRD §2.8: "any enum value must fall within its allowed set, or the request fails
    with ERR_INVALID_REQUEST."
    PRD §3.1: "an asset_type of either SEPTIC_TANK or WELL".

    Design: Corner/entities/create_asset_invalid_enum_returns_invalid_request
    """
    account = create_account()
    site = create_site(account["id"])
    res = api.create_asset(
        {"site_id": site["id"], "asset_type": "LAGOON", "capacity_gallons": 1000, "install_year": 2010},
        DISPATCHER,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_technician_shift_end_before_start_validation(api):
    """PRD §3.11: "shift_end_minute must be strictly greater than shift_start_minute; a
    shift end at or before the shift start, or a minute value outside 0 through 1440, is
    rejected with ERR_VALIDATION."

    Design: Corner/entities/technician_shift_end_before_start_validation
    """
    res = api.create_technician(
        create_technician_payload(shift_start_minute=1020, shift_end_minute=480), DISPATCHER
    )
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_reminder_immutable_no_version_field(api):
    """PRD §2.4: "A Reminder is an append-only event record: it carries only id and
    created_at. It has neither updated_at nor version".
    PRD §3.7: "That recompute, in turn, emits a Reminder of reminder_type PUMP_DUE whose
    due_date is the freshly computed next_pump_due_date."

    Design: Corner/entities/reminder_immutable_no_version_field
    """
    account = create_account()
    site = create_site(account["id"])
    create_service_plan(site["id"], site["version"], frequency_months=36, estimated_gallons=800)
    base_tech = create_technician()
    route = create_route(base_tech["id"], "2026-07-02")
    create_completed_work_order(
        site["id"], route["id"], base_tech["id"], "2026-07-02", 540,
        work_type="PUMPING", complete_payload={"measured_gallons": 900},
    )
    data, meta = validate_paginated(api.list_site_reminders(site["id"], DISPATCHER))
    pump_due = [r for r in data if r["reminder_type"] == "PUMP_DUE"]
    assert len(pump_due) == 1, f"Expected exactly one PUMP_DUE reminder, got {len(data)}"
    assert "version" not in pump_due[0], "Reminder must not carry a version field"


# ─── validations section ───────────────────────────────

def test_dispatch_well_job_to_uncertified_tech_returns_not_certified(api):
    """PRD §3.11: "A well job — a WELL asset or well inspection — additionally requires
    the technician's certified_for_wells to be true at dispatch, and a well job dispatched
    to an uncertified technician is rejected with ERR_TECH_NOT_CERTIFIED."

    Design: Corner/validations/dispatch_well_job_to_uncertified_tech_returns_not_certified
    """
    account = create_account()
    site = create_site(account["id"])
    get_success_data(api.create_asset(
        create_asset_payload(site["id"], asset_type="WELL", capacity_gallons=1, install_year=2015),
        DISPATCHER,
    ))
    tech = create_technician(certified_for_wells=False)
    route = create_route(tech["id"], "2026-07-09")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "INSPECTION", "2026-07-09", 540), DISPATCHER
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    res = api.dispatch_work_order(wo["id"], DISPATCHER)
    validate_error(res, "ERR_TECH_NOT_CERTIFIED", expected_status=409)


def test_schedule_outside_shift_returns_outside_shift(api):
    """PRD §3.4: "the window must fall within the technician's shift: both
    window_start_minute and window_end_minute must lie within the technician's
    shift_start_minute through shift_end_minute bounds, and a window outside that shift is
    rejected with ERR_OUTSIDE_SHIFT."

    Design: Corner/validations/schedule_outside_shift_returns_outside_shift
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()  # shift 480-1020
    route = create_route(tech["id"], "2026-07-10")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-10", 1000, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_OUTSIDE_SHIFT", expected_status=409)


def test_permit_submit_before_cooling_off_returns_cooling_off(api):
    """PRD §3.9: "a cooling-off window must have elapsed: the server's current UTC clock
    must be at or past the report's finalized_at plus the cooling-off duration of 48
    hours, or the submit is rejected with ERR_COOLING_OFF."

    Design: Corner/validations/permit_submit_before_cooling_off_returns_cooling_off
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-01")
    wo = create_completed_inspection_wo(base, "2026-06-01", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    report = get_success_data(api.finalize_inspection_report(report["id"], {"result": "PASS"}, COMPLIANCE))
    filing = get_success_data(api.create_permit_filing(
        {"inspection_report_id": report["id"], "site_id": base["site"]["id"]}, COMPLIANCE
    ))
    set_clock("2026-06-01T01:00:00Z")
    res = api.submit_permit_filing(filing["id"], COMPLIANCE)
    validate_error(res, "ERR_COOLING_OFF", expected_status=409)


def test_schedule_onto_locked_route_returns_route_locked(api):
    """PRD §3.4: "A Dispatcher may lock a route, moving status to LOCKED; a locked route
    rejects assignment, revert, and optimize operations with ERR_ROUTE_LOCKED."

    Design: Corner/validations/schedule_onto_locked_route_returns_route_locked
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-11")
    get_success_data(api.lock_route(route["id"], DISPATCHER))
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-11", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_ROUTE_LOCKED", expected_status=409)


# ─── rbac section ──────────────────────────────────────

def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers. ... If either header is missing or invalid, the request is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_account(create_account_payload(), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_fieldtech_cannot_create_account_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform the
    requested operation, the request is rejected with ERR_FORBIDDEN."
    PRD §2.1: "The Dispatcher runs operations — creating accounts, sites, assets, service
    plans, routes, and work orders".

    Design: Corner/rbac/fieldtech_cannot_create_account_returns_forbidden
    """
    tech = create_technician()
    res = api.create_account(create_account_payload(name="Rogue", billing_email="r@x.com"),
                             make_field_tech_headers(tech["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_dispatcher_cannot_finalize_report_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform the
    requested operation, the request is rejected with ERR_FORBIDDEN."
    PRD §2.1: "The ComplianceOfficer owns inspection reports and county permit filings."

    Design: Corner/rbac/dispatcher_cannot_finalize_report_returns_forbidden
    """
    base = setup_account_site_tech_route("2026-07-15")
    wo = create_completed_inspection_wo(base, "2026-07-15", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    res = api.finalize_inspection_report(report["id"], {"result": "PASS"}, DISPATCHER)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── cross_cutting_complexity_layers section ───────────

def test_occ_stale_site_version_on_service_plan_create(api):
    """PRD §2.6: "If expected_site_version does not equal the site's current version, the
    request is rejected with ERR_STALE_VERSION (HTTP 412)".
    PRD §3.2: "Creating a new plan transitions the prior ACTIVE plan to SUPERSEDED, sets
    the new plan ACTIVE, recomputes the site's next_pump_due_date, and increments the
    site's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_site_version_on_service_plan_create
    """
    account = create_account()
    site = create_site(account["id"])
    site_v0 = site["version"]
    create_service_plan(site["id"], site_v0, frequency_months=36, estimated_gallons=800)
    # Second create still carrying the pre-supersede site version is stale.
    res = api.create_service_plan(
        create_service_plan_payload(site["id"], site_v0, frequency_months=24, estimated_gallons=700),
        DISPATCHER,
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_service_plan_supersede_marks_prior_superseded(api):
    """PRD §3.2: "a site may have only one ACTIVE plan at a time. Creating a new plan
    transitions the prior ACTIVE plan to SUPERSEDED, sets the new plan ACTIVE".

    Design: Corner/cross_cutting_complexity_layers/service_plan_supersede_marks_prior_superseded
    """
    account = create_account()
    site = create_site(account["id"])
    plan1 = create_service_plan(site["id"], site["version"], frequency_months=36, estimated_gallons=800)
    site_refreshed = get_site(site["id"])
    plan2 = create_service_plan(
        site["id"], site_refreshed["version"], frequency_months=24, estimated_gallons=700
    )
    plan1_now = validate_success(api.get_service_plan(plan1["id"], DISPATCHER), 200)
    assert plan1_now["status"] == "SUPERSEDED"
    assert plan2["status"] == "ACTIVE"


# ─── consistency_model section ─────────────────────────

def test_scheduled_estimate_visible_in_same_response(api):
    """PRD §3.4: "computes estimated_cost_cents (see §3.5)".
    PRD §3.5: "The first 1000 gallons (the base-included volume) are priced at 25 cents
    per gallon ... and add the 9000-cent trip fee to that pumping subtotal."

    Design: Corner/consistency_model/scheduled_estimate_visible_in_same_response
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-16")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-16", 540, estimated_gallons=800),
        DISPATCHER,
    ))
    res = api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER)
    scheduled = validate_success(res, 200)
    assert scheduled["estimated_cost_cents"] == 29000
    assert scheduled["status"] == "SCHEDULED"
