"""Resource creation defaults, initial states, and basic reads."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_facility_admin_headers, make_gate_operator_headers, make_environmental_officer_headers,
    facility_payload, cell_payload, hauler_account_payload, ticket_payload, gas_reading_payload,
    assert_facility, assert_cell, assert_ticket, assert_gas_reading,
    create_facility, create_hauler,
)


def test_facility_create_returns_computed_defaults(api):
    """PRD §3.1: "the new facility opens with `consumed_airspace_cubic_yards` at 0,
    `latest_methane_ppm` at 0, `gas_status` at `NORMAL`, `acceptance_posture` at `OPEN`,
    both `diversion_rate_provisional` and `diversion_rate_final` at 0, and `version` at 1."

    Design: Corner/entities/facility_create_returns_computed_defaults
    """
    resp = api.create_facility(
        facility_payload(name="F1", total_airspace_cubic_yards=500),
        make_facility_admin_headers("adm1"),
    )
    data = validate_success(resp, 201)
    assert_facility(data)
    assert data["gas_status"] == "NORMAL"
    assert data["acceptance_posture"] == "OPEN"
    assert data["consumed_airspace_cubic_yards"] == 0
    assert data["version"] == 1


def test_cell_create_defaults_open_zero(api):
    """PRD §3.1: "A new cell starts with `consumed_cubic_yards` at 0 and `status` `OPEN`,
    and is stamped with a `fill_sequence` drawn from a monotone counter maintained per
    facility, so that every cell in a facility has a distinct fill order."

    Design: Corner/entities/cell_create_defaults_open_zero
    """
    facility = create_facility(500)
    resp = api.create_cell(
        facility["id"], cell_payload(name="C1", capacity_cubic_yards=100),
        make_facility_admin_headers("adm1"),
    )
    data = validate_success(resp, 201)
    assert_cell(data)
    assert data["status"] == "OPEN"
    assert data["consumed_cubic_yards"] == 0


def test_facility_get_unknown_returns_not_found(api):
    """PRD §2.5: "rejects the request with `ERR_NOT_FOUND` at the first identifier that does
    not resolve to an existing resource."

    Design: Corner/entities/facility_not_found_returns_404
    """
    resp = api.get_facility(NON_EXISTENT_UUID, make_facility_admin_headers("adm1"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_ticket_initial_state_is_created_with_provisional_estimate(api):
    """PRD §3.3: "The new ticket enters `CREATED`, with `cell_id`, `invoice_id`,
    `tare_weight_tons`, `net_weight_tons`, `tipping_fee_cents`, and `posted_airspace_cy` all
    still unset."
    PRD §3.4: "`MSW` is charged at 4500 cents per ton for the portion of the weight up to 5
    tons and 3800 cents per ton for the portion above 5 tons."

    Design: Corner/state_machines/ticket_initial_state_is_created
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    resp = api.create_ticket(
        ticket_payload(facility["id"], hauler["id"], material="MSW", gross_weight_tons=6.0),
        make_gate_operator_headers("op1"),
    )
    data = validate_success(resp, 201)
    assert_ticket(data)
    assert data["status"] == "CREATED"
    assert data["estimated_fee_cents"] == 26300


def test_gas_reading_is_append_only_no_version(api):
    """PRD §2.4: "A `GasReading` is an append-only event record: it carries only `id` and
    `created_at`. It has neither an `updated_at` nor a `version` field, because a reading is
    never modified after it is recorded."

    Design: Corner/entities/gas_reading_is_append_only_no_version
    """
    facility = create_facility(500)
    resp = api.create_gas_reading(
        facility["id"], gas_reading_payload(120, "2026-03-01T06:00:00Z"),
        make_environmental_officer_headers("eo1"),
    )
    data = validate_success(resp, 201)
    assert_gas_reading(data)
    assert data["resulting_gas_status"] == "NORMAL"
    assert "version" not in data
    assert "updated_at" not in data


def test_tickets_filtered_by_hauler_returns_array(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return
    resources sorted by their creation timestamp (`created_at`) in ascending order. Every
    list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the envelope."

    Design: Corner/endpoints/tickets_filtered_by_hauler_returns_array
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    tk_resp = api.create_ticket(
        ticket_payload(facility["id"], hauler["id"], material="MSW", gross_weight_tons=6.0),
        make_gate_operator_headers("op1"),
    )
    ticket = validate_success(tk_resp, 201)
    resp = api.list_tickets(make_gate_operator_headers("op1"),
                            params={"hauler_account_id": hauler["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "listing should return the hauler's ticket"
    ids = [row["id"] for row in data]
    assert ticket["id"] in ids
    for row in data:
        assert row["hauler_account_id"] == hauler["id"]
