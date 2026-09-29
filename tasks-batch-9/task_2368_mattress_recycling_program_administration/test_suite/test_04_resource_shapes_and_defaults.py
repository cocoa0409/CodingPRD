"""Resource shapes on creation and retrieval: declared defaults, server-generated
fields, required-field and type constraints, and cross-collection references."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_collection_site,
    assert_custody_buckets,
    assert_hauler,
    assert_load_inspection,
    assert_pickup_order,
    assert_state_program,
    assert_volume_report,
    ca_program_payload,
    create_ca_program,
    create_collection_site_payload,
    create_hauler_payload,
    create_pickup_order_payload,
    create_registrant,
    create_remittance,
    create_site,
    create_state_program_payload,
    create_volume_report_payload,
    create_wa_program,
    enroll_site,
    is_iso8601_timestamp,
    make_registrant_headers,
    make_site_operator_headers,
    propose_rate,
    setup_inspected_order,
    setup_logistics_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

UNUSED_PROGRAM_ID = "00000000-0000-4000-8000-000000000999"
UNUSED_FK_PROGRAM_ID = "00000000-0000-4000-8000-0000000000c1"
UNUSED_REMITTANCE_ID = "00000000-0000-4000-8000-0000000004a1"


def test_program_creation_returns_a_fully_populated_ledger_and_recommendation(api):
    """PRD §3.1: "A newly created program is fully quiet. Its `enforcement_posture`
    begins at `NORMAL`, `enrolled_site_count` at 0, `reported_units_total` at 0,
    `delinquent_registrant_count` at 0, and the three cash aggregates
    `fee_collected_cents`, `site_credit_paid_cents` and `hauler_payment_paid_cents`
    at 0, along with `receivable_cents`. The creation itself computes
    `reserve_balance_cents` from the opening reserve, then
    `reserve_coverage_months`, then `recommended_rate_cents`."

    Design: Corner/entities/state_program_creation_returns_ledger_and_recommendation_envelope
    """
    response = api.create_state_program(ca_program_payload(), ADMIN)

    program = validate_success(response, 201)
    assert_state_program(program)
    assert program["state_code"] == "CA"
    assert program["program_name"] == "California Mattress Recycling Program"
    assert program["fee_collected_cents"] == 0
    assert program["site_credit_paid_cents"] == 0
    assert program["hauler_payment_paid_cents"] == 0
    assert program["receivable_cents"] == 0
    assert program["enrolled_site_count"] == 0
    assert program["reported_units_total"] == 0
    assert program["delinquent_registrant_count"] == 0
    assert program["enforcement_posture"] == "NORMAL"
    assert program["reserve_balance_cents"] == 5_000_000
    assert program["reserve_coverage_months"] == pytest.approx(1.00)
    assert program["recommended_rate_cents"] == 1075
    assert program["version"] == 1


def test_a_freshly_applied_site_reads_back_its_inputs_with_empty_custody(api):
    """PRD §3.5: "A newly applied site has `enrollment_status` `APPLIED`, all five
    custody buckets at zero along with `units_reported_total`,
    `contamination_strike_count` at 0, and both `infestation_quarantine_until` and
    `suspended_at` null."

    Design: Corner/entities/collection_site_retrieval_returns_stored_and_zeroed_custody_fields
    """
    program = create_wa_program(api)
    site = create_site(api, program["id"])

    stored = validate_success(api.get_collection_site(site["id"], ADMIN))

    assert_collection_site(stored)
    assert stored["state_program_id"] == program["id"]
    assert stored["operator_name"] == "Puget Transfer Station"
    assert stored["site_type"] == "TRANSFER_STATION"
    assert stored["region_code"] == "NORTH"
    assert stored["enrollment_status"] == "APPLIED"
    assert_custody_buckets(stored, 0, 0, 0, 0, 0, reported_total=0)
    assert stored["contamination_strike_count"] == 0
    assert stored["infestation_quarantine_until"] is None
    assert stored["suspended_at"] is None


def test_rate_schedule_listing_reports_the_unpaginated_total_and_the_window(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the size of the filtered
    result set before pagination is applied and `has_more` indicates whether records
    remain beyond the current window."

    Design: Corner/entities/fee_rate_schedule_list_paginates_with_total_count_and_has_more
    """
    program = create_ca_program(api)
    for effective_from, effective_to in (
        ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        ("2026-10-01T00:00:00Z", None),
    ):
        propose_rate(
            api,
            program["id"],
            unit_class="FOUNDATION",
            fee_cents_per_unit=900,
            effective_from=effective_from,
            effective_to=effective_to,
        )

    first_page, first_meta = validate_paginated(
        api.list_fee_rate_schedules(
            ADMIN,
            params={
                "state_program_id": program["id"],
                "unit_class": "FOUNDATION",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_fee_rate_schedules(
            ADMIN,
            params={
                "state_program_id": program["id"],
                "unit_class": "FOUNDATION",
                "limit": 2,
                "offset": 2,
            },
        )
    )

    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_reading_an_unused_program_id_reports_the_program_not_found_code(api):
    """PRD §2.5: "The first identifier that fails to resolve determines the
    response: the request is rejected with the 404 error specific to that entity
    type, and no later reference is examined."

    Design: Corner/entities/unknown_state_program_id_not_found_returns_404
    """
    create_ca_program(api)

    response = api.get_state_program(UNUSED_PROGRAM_ID, ADMIN)

    validate_error(response, "ERR_STATE_PROGRAM_NOT_FOUND", 404)


def test_applying_a_site_without_a_region_code_is_refused_and_stores_nothing(api):
    """PRD §3.5: "A `ProgramAdministrator` brings a drop-off point into the program
    by applying it, supplying the `state_program_id` it belongs to, the
    `operator_name` of the operating organisation, a `site_type` of
    `COLLECTION_SITE`, `TRANSFER_STATION` or `PERMANENT_DROPOFF`, and a
    `region_code`."

    Design: Corner/entities/collection_site_create_missing_required_region_code_invalid_request
    """
    program = create_wa_program(api)
    payload = create_collection_site_payload(program["id"])
    payload.pop("region_code")

    response = api.create_collection_site(payload, ADMIN)

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    _, meta = validate_paginated(
        api.list_collection_sites(ADMIN, params={"state_program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_omitted_program_options_take_their_declared_defaults_into_the_rate(api):
    """PRD §3.1: "It also carries the forecast the whole fee-setting apparatus is
    built on: `forecast_annual_cost_cents`, the projected annual cost of running the
    program, which must be at least 1; `forecast_annual_units`, the projected annual
    count of chargeable units, also at least 1; and optionally
    `forecast_other_revenue_cents`, projected non-fee revenue such as commodity
    proceeds and grants, which must be zero or greater and defaults to 0 when
    omitted."

    Design: Corner/entities/state_program_optional_inputs_fall_back_to_declared_defaults
    """
    payload = create_state_program_payload(
        state_code="OR", program_name="Oregon Mattress Stewardship Program"
    )
    payload.pop("forecast_other_revenue_cents")
    payload.pop("delinquency_alert_threshold")

    program = validate_success(api.create_state_program(payload, ADMIN), 201)

    assert program["forecast_other_revenue_cents"] == 0
    assert program["delinquency_alert_threshold"] == 1
    assert program["recommended_rate_cents"] == 1127, (
        "with no other revenue the recoverable amount is 65,000,000 cents, a base "
        "rate of 1084 cents and a four percent surcharge"
    )
    assert program["reserve_coverage_months"] == pytest.approx(1.00)


def test_an_omitted_route_ceiling_lets_the_hauler_hold_exactly_two_windows(api):
    """PRD §3.6: "Optionally `max_concurrent_routes` sets how many
    buffer-overlapping pickup windows the hauler may hold at once; it must be at
    least 1 and defaults to 2."

    Design: Corner/entities/hauler_omitted_max_concurrent_routes_defaults_to_two
    """
    chain = setup_logistics_chain(api)
    payload = create_hauler_payload(chain["program_id"], company_name="Default Fleet Hauling")
    payload.pop("max_concurrent_routes")
    hauler = validate_success(api.create_hauler(payload, ADMIN), 201)
    site_headers = make_site_operator_headers(chain["site_id"])

    assert_hauler(hauler)
    assert hauler["max_concurrent_routes"] == 2

    def dispatch(window_start, window_end):
        return api.create_pickup_order(
            create_pickup_order_payload(
                chain["site_id"],
                chain["recycler_id"],
                hauler_id=hauler["id"],
                units_manifested=100,
                route_distance_km=40.0,
                pickup_window_start=window_start,
                pickup_window_end=window_end,
            ),
            site_headers,
        )

    first = dispatch("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    second = dispatch("2026-08-05T10:30:00Z", "2026-08-05T11:00:00Z")
    third = dispatch("2026-08-05T11:00:00Z", "2026-08-05T11:30:00Z")

    validate_success(first, 201)
    validate_success(second, 201)
    validate_error(third, "ERR_HAULER_WINDOW_CAPACITY_EXCEEDED", 409)
    stored_hauler = validate_success(api.get_hauler(hauler["id"], ADMIN))
    assert stored_hauler["active_route_count"] == 2
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 310
    assert site["units_in_transit"] == 200


def test_a_submitted_volume_report_credits_nothing_until_it_is_accepted(api):
    """PRD §3.5: "A new report starts in `SUBMITTED` with `credited_units` and
    `credit_cents` at 0 and `accepted_at` null — nothing is credited and no custody
    moves until an administrator accepts it."

    Design: Corner/entities/volume_report_computed_credit_input_ignored_until_acceptance
    """
    program = create_wa_program(api)
    site = create_site(
        api,
        program["id"],
        operator_name="Chinook Collection Site",
        site_type="COLLECTION_SITE",
    )
    enroll_site(api, site["id"])
    payload = create_volume_report_payload(
        period_month="2026-08",
        units_mattress=320,
        units_foundation=190,
        credit_cents=999_999,
        credited_units=12,
    )

    submitted = validate_success(
        api.create_volume_report(site["id"], payload, make_site_operator_headers(site["id"])),
        201,
    )

    assert_volume_report(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["credit_cents"] == 0
    assert submitted["credited_units"] == 0
    assert submitted["accepted_at"] is None

    accepted = validate_success(api.accept_volume_report(submitted["id"], ADMIN))

    assert accepted["credited_units"] == 510
    assert accepted["credit_cents"] == 163_328
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 510


def test_a_dispatched_order_starts_on_the_server_declared_status_axes(api):
    """PRD §3.6: "A dispatched order starts on two independent status axes. Its
    `fulfillment_status` begins at `SCHEDULED` and its `settlement_status` at
    `UNSETTLED`, with `units_delivered`, `units_accepted`,
    `estimated_payment_cents` and `final_payment_cents` all null."

    Design: Corner/entities/pickup_order_system_fields_generated_and_client_values_input_ignored
    """
    chain = setup_logistics_chain(api)
    payload = create_pickup_order_payload(
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-05T09:00:00Z",
        pickup_window_end="2026-08-05T10:00:00Z",
        fulfillment_status="CLOSED",
        settlement_status="FINALIZED",
        version=99,
    )

    order = validate_success(
        api.create_pickup_order(payload, make_site_operator_headers(chain["site_id"])), 201
    )

    assert_pickup_order(order)
    assert order["fulfillment_status"] == "SCHEDULED"
    assert order["settlement_status"] == "UNSETTLED"
    assert order["version"] == 1
    assert order["units_delivered"] is None
    assert order["units_accepted"] is None
    assert order["estimated_payment_cents"] is None
    assert order["final_payment_cents"] is None
    assert order["hauler_auto_selected"] is False
    assert is_iso8601_timestamp(order["created_at"])
    assert order["created_at"].startswith("2026-08-01T00:00:00")
    assert order["updated_at"] == order["created_at"]


def test_a_recorded_inspection_carries_no_version_and_cannot_be_recorded_twice(api):
    """PRD §2.4: "The one exception is the load inspection. An inspection is an
    append-only event record: it carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from a load inspection, because an
    inspection is never modified after it is written."

    Design: Corner/entities/load_inspection_is_immutable_with_no_version_and_no_update_endpoint
    """
    chain = setup_inspected_order(api, contaminated_unit_count=12, units_delivered=240)
    recycler_headers = chain["recycler_headers"]

    inspections, meta = validate_paginated(
        api.list_load_inspections(chain["order_id"], recycler_headers)
    )

    assert meta["total_count"] == 1
    recorded = inspections[0]
    assert recorded["id"] == chain["inspection"]["id"]
    assert_load_inspection(recorded)
    assert "version" not in recorded
    assert "updated_at" not in recorded
    assert recorded["contamination_pct"] == pytest.approx(5.00)
    assert recorded["units_accepted"] == 228
    second = api.create_load_inspection(
        chain["order_id"],
        {"contaminated_unit_count": 0, "infestation_finding": "NONE"},
        recycler_headers,
    )
    validate_error(second, "ERR_LOAD_ALREADY_INSPECTED", 409)


def test_a_malformed_period_code_or_enum_value_is_refused_before_storage(api):
    """PRD §3.3: "The `period_code` is a reporting quarter written as four digits,
    the letter Q, and a digit from 1 to 4 — `2026Q1` and the like — and from it the
    server derives `period_start`, the first instant of that quarter in UTC, and
    `period_end`, the last day of that quarter at `23:59:59.999Z`."

    Design: Corner/entities/sales_remittance_invalid_period_code_and_enum_values_rejected
    """
    program = create_ca_program(api)
    registrant = create_registrant(api)
    registrant_headers = make_registrant_headers(registrant["id"])

    bad_quarter = api.create_sales_remittance(
        {
            "registrant_id": registrant["id"],
            "state_program_id": program["id"],
            "period_code": "2026Q5",
            "units_sold_mattress": 100,
            "units_sold_foundation": 0,
        },
        registrant_headers,
    )
    negative_units = api.create_sales_remittance(
        {
            "registrant_id": registrant["id"],
            "state_program_id": program["id"],
            "period_code": "2026Q2",
            "units_sold_mattress": -1,
            "units_sold_foundation": 0,
        },
        registrant_headers,
    )
    bad_registrant_type = api.create_registrant(
        {
            "legal_name": "Wholesale Sleep Depot",
            "registrant_type": "WHOLESALER",
            "home_state_code": "CA",
        },
        ADMIN,
    )

    validate_error(bad_quarter, "ERR_INVALID_REQUEST", 400)
    validate_error(negative_units, "ERR_INVALID_REQUEST", 400)
    validate_error(bad_registrant_type, "ERR_INVALID_REQUEST", 400)
    _, meta = validate_paginated(
        api.list_sales_remittances(ADMIN, params={"registrant_id": registrant["id"]})
    )
    assert meta["total_count"] == 0


def test_a_claim_against_an_unused_remittance_id_creates_no_orphan(api):
    """PRD §3.4: "Each claim carries a `remittance_id` identifying the filing it
    belongs to."

    PRD §2.5: "The first identifier that fails to resolve determines the response:
    the request is rejected with the 404 error specific to that entity type, and no
    later reference is examined."

    Design: Corner/entities/exemption_claim_requires_existing_parent_remittance_not_found
    """
    program = create_ca_program(api)
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    registrant_headers = make_registrant_headers(registrant["id"])

    response = api.create_exemption_claim(
        UNUSED_REMITTANCE_ID,
        {"claim_type": "EXEMPT_SALE", "unit_class": "MATTRESS", "units": 10},
        registrant_headers,
    )

    validate_error(response, "ERR_REMITTANCE_NOT_FOUND", 404)
    _, meta = validate_paginated(
        api.list_exemption_claims(remittance["id"], registrant_headers)
    )
    assert meta["total_count"] == 0


def test_body_carried_program_references_are_resolved_on_peer_collections(api):
    """PRD §2: "The collections in this API are peers at the root of the URL space —
    there is no single enclosing container resource. Programs, fee-rate schedules,
    registrants, remittances, exemption claims, collection sites, volume reports,
    haulers, recyclers, pickup orders, load inspections, commodity output records
    and take-back deliveries are joined to one another by explicit reference fields
    carried in request bodies."

    Design: Corner/entities/flat_topology_foreign_keys_validated_across_peer_collections
    """
    program = create_wa_program(api)

    orphan_site = api.create_collection_site(
        create_collection_site_payload(
            UNUSED_FK_PROGRAM_ID,
            operator_name="Orphan Site",
            site_type="COLLECTION_SITE",
        ),
        ADMIN,
    )
    orphan_hauler = api.create_hauler(
        create_hauler_payload(UNUSED_FK_PROGRAM_ID, company_name="Orphan Hauling"),
        ADMIN,
    )

    validate_error(orphan_site, "ERR_STATE_PROGRAM_NOT_FOUND", 404)
    validate_error(orphan_hauler, "ERR_STATE_PROGRAM_NOT_FOUND", 404)
    _, site_meta = validate_paginated(
        api.list_collection_sites(ADMIN, params={"state_program_id": program["id"]})
    )
    _, hauler_meta = validate_paginated(
        api.list_haulers(ADMIN, params={"state_program_id": program["id"]})
    )
    assert site_meta["total_count"] == 0
    assert hauler_meta["total_count"] == 0
