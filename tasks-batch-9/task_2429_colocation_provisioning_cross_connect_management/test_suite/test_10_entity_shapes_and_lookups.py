"""Entity shapes, seeded defaults, listing pages and reference resolution.

Every test builds its own scenery: the harness empties the store before each test.
"""

from datetime import datetime

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import BILLING_OPERATOR, ENGINEER_1, FACILITY_MANAGER, SECURITY_OFFICER


def _instant(value):
    """Parse an ISO 8601 UTC timestamp so two spellings of the same instant compare
    equal regardless of how many fractional digits the server writes."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Customers and contracts: what a creation and a read expose
# ---------------------------------------------------------------------------


def test_customer_creation_returns_declared_fields_and_active_status(api):
    """PRD §3.1: "Newly registered customers open with `account_status` set to `ACTIVE`; the field also admits `SUSPENDED` and `CLOSED`, which an operator action moves it to."
    PRD §2.4: "Customers, contracts, floor rows, cabinets, power circuits, patch-panel ports, cross-connect orders, authorized contacts, access visits, remote-hands tickets and decommission orders additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on each mutation of that row."

    Design: Corner/entities/customer_creation_returns_all_declared_fields
    """
    fx.set_clock(api)

    data = validate_success(
        api.create_customer(
            {"legal_name": "Alder Peak Systems", "account_code": "APS"}, FACILITY_MANAGER
        ),
        201,
    )

    assert data["legal_name"] == "Alder Peak Systems"
    assert data["account_code"] == "APS"
    assert data["account_status"] == "ACTIVE", (
        f"a newly registered customer opens ACTIVE, got {data['account_status']}"
    )
    ax.assert_customer(data)
    ax.assert_version_is(data, 1, "customer")


def test_contract_read_back_carries_commitments_with_every_rollup_at_zero(api):
    """PRD §3.1: "A newly created contract opens in `DRAFT` with `credit_hold` false, `remote_hands_remaining_minutes` initialised to `remote_hands_included_minutes`, every rollup field (`provisioned_power_kw`, `stranded_commit_kw`, `commit_utilization_pct`, `active_cross_connect_count`, `billed_total_usd`, `cross_connect_billed_usd`) at zero and `last_closed_period_end` unset."

    Design: Corner/entities/contract_retrieval_returns_stored_commitments_and_zeroed_rollups
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)
    contract = fx.create_contract(
        api,
        customer["id"],
        billing_mode="METERED_PLUS_COMMIT",
        committed_cabinet_count=2,
        power_commit_kw=20.0,
        committed_bandwidth_mbps=1000,
        cross_connect_cap=4,
        committed_cage_sqft=0,
        redundancy_requirement="N",
        cross_connect_allowance=0,
        remote_hands_included_minutes=60,
    )

    data = validate_success(api.get_contract(contract["id"], BILLING_OPERATOR))

    assert data["id"] == contract["id"]
    ax.assert_contract(data)
    assert data["status"] == "DRAFT"
    assert data["credit_hold"] is False
    ax.assert_kw_equals(data["power_commit_kw"], 20.0, "contract.power_commit_kw")
    assert data["committed_cabinet_count"] == 2
    assert data["cross_connect_cap"] == 4
    assert data["remote_hands_included_minutes"] == 60
    assert data["remote_hands_remaining_minutes"] == 60, (
        "remote_hands_remaining_minutes is initialised to remote_hands_included_minutes"
    )
    ax.assert_contract_power_rollup(
        data, provisioned_power_kw=0.000, stranded_commit_kw=0.000, commit_utilization_pct=0.0
    )
    ax.assert_contract_billing_rollup(
        data, billed_total_usd=0.00, cross_connect_billed_usd=0.00, active_cross_connect_count=0
    )
    assert data["last_closed_period_end"] is None


def test_contract_system_fields_are_server_seeded(api):
    """PRD §3.1: "A newly created contract opens in `DRAFT` with `credit_hold` false, `remote_hands_remaining_minutes` initialised to `remote_hands_included_minutes`, every rollup field (`provisioned_power_kw`, `stranded_commit_kw`, `commit_utilization_pct`, `active_cross_connect_count`, `billed_total_usd`, `cross_connect_billed_usd`) at zero and `last_closed_period_end` unset."
    PRD §2.7: "Derived fields are never accepted from clients."

    Design: Corner/entities/contract_system_fields_are_server_seeded_client_input_ignored
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)

    payload = f.create_contract_payload(
        customer["id"],
        billing_mode="COMMITTED_ONLY",
        committed_cabinet_count=1,
        power_commit_kw=10.0,
        committed_bandwidth_mbps=100,
        cross_connect_cap=1,
        status="ACTIVE",
        credit_hold=True,
        billed_total_usd=500.00,
    )
    data = validate_success(api.create_contract(payload, BILLING_OPERATOR), 201)

    assert data["status"] == "DRAFT", (
        f"a newly created contract opens in DRAFT, got {data['status']}"
    )
    assert data["credit_hold"] is False
    ax.assert_amount_equals(data["billed_total_usd"], 0.00, "contract.billed_total_usd")
    assert data["last_closed_period_end"] is None
    ax.assert_common_fields(data, "contract")


# ---------------------------------------------------------------------------
# Listings: default page and filtered page
# ---------------------------------------------------------------------------


def test_cabinet_listing_default_page_holds_ten_of_eleven_rows(api):
    """PRD §2.3: "`limit` is the maximum number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts every row matching the supplied filters and not merely the rows on the current page."

    Design: Corner/entities/cabinet_listing_default_page_reports_total_count_and_has_more
    """
    fx.set_clock(api)
    row = fx.create_row(api, hall_code="H2", row_code="R1", cabinet_slot_count=12)
    for number in range(1, 12):
        fx.create_cabinet(api, row["id"], cabinet_code=f"C{number:02d}", rated_power_kw=20.0)

    data, meta = validate_paginated(api.list_cabinets(FACILITY_MANAGER, params={"row_id": row["id"]}))

    assert len(data) == 10, f"the default page holds 10 cabinets, got {len(data)}"
    assert meta["limit"] == k.DEFAULT_LIMIT
    assert meta["offset"] == 0
    assert meta["total_count"] == 11, "total_count counts every matching row, not the page"
    assert meta["has_more"] is True


def test_cabinet_listing_filtered_by_status_returns_only_the_reserved_position(api):
    """PRD §4: "List cabinets, filterable by row, contract, status and footprint type."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts every row matching the supplied filters and not merely the rows on the current page."
    PRD §3.3: "On success the cabinet's `contract_id` is written, the row's `occupied_slot_count` rises by one, and the row's `density_ceiling_kw`, `effective_ceiling_kw`, both stranded views and `row_status` are recomputed; both the cabinet's and the row's `version` increment."

    Design: Corner/entities/cabinet_listing_filtered_by_status_excludes_available_positions
    """
    scenario = fx.setup_reserved_cabinet(
        api,
        row={"hall_code": "H2", "row_code": "R2"},
        contract={"committed_cabinet_count": 2},
        cabinet={"cabinet_code": "C01"},
    )
    fx.create_cabinet(api, scenario.row_id, cabinet_code="C02", rated_power_kw=20.0)
    fx.create_cabinet(api, scenario.row_id, cabinet_code="C03", rated_power_kw=20.0)

    data, meta = validate_paginated(
        api.list_cabinets(
            FACILITY_MANAGER, params={"row_id": scenario.row_id, "status": "RESERVED"}
        )
    )

    assert len(data) == 1, f"only the RESERVED position matches, got {len(data)} rows"
    assert data[0]["id"] == scenario.cabinet_id
    assert data[0]["status"] == "RESERVED"
    assert data[0]["contract_id"] == scenario.contract_id
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


def test_contract_get_with_unknown_id_reports_contract_not_found(api):
    """PRD §2.5: "Every identifier in the URL path resolves to a stored row, otherwise the per-entity 404 code for the first unresolved identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROW_NOT_FOUND`, `ERR_CABINET_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_CROSS_CONNECT_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_DECOMMISSION_ORDER_NOT_FOUND` or `ERR_INVOICE_LINE_NOT_FOUND`."

    Design: Corner/entities/contract_get_with_unknown_id_returns_not_found
    """
    fx.set_clock(api)

    validate_error(
        api.get_contract(NON_EXISTENT_UUID, BILLING_OPERATOR),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND,
    )


def test_cabinet_creation_against_unknown_row_reports_row_not_found(api):
    """PRD §2.5: "Every foreign key supplied in the request body resolves to a stored row, otherwise that referenced entity's own 404 code."
    PRD §2.5: "Applies to the creation endpoints for contracts, cabinets, power circuits, patch-panel ports, cross-connect orders, remote-hands tickets, access visits, decommission orders and contacts."

    Design: Corner/entities/cabinet_creation_against_unknown_row_returns_not_found
    """
    fx.set_clock(api)

    validate_error(
        api.create_cabinet(
            {"row_id": NON_EXISTENT_UUID, "cabinet_code": "C01", "rated_power_kw": 20.0},
            FACILITY_MANAGER,
        ),
        ApiErrorId.ERR_ROW_NOT_FOUND,
    )

    _, meta = validate_paginated(api.list_cabinets(FACILITY_MANAGER))
    assert meta["total_count"] == 0, "a refused create persists no cabinet"


def test_contact_creation_against_unknown_customer_reports_customer_not_found(api):
    """PRD §2.5: "Every foreign key supplied in the request body resolves to a stored row, otherwise that referenced entity's own 404 code."
    PRD §2.5: "Applies to the creation endpoints for contracts, cabinets, power circuits, patch-panel ports, cross-connect orders, remote-hands tickets, access visits, decommission orders and contacts."

    Design: Corner/entities/contact_creation_against_unknown_customer_returns_not_found
    """
    fx.set_clock(api)

    validate_error(
        api.create_contact(
            {
                "customer_id": NON_EXISTENT_UUID,
                "full_name": "Nobody",
                "authorization_scopes": ["SITE_ACCESS"],
                "access_level": "UNESCORTED",
            },
            SECURITY_OFFICER,
        ),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
    )

    _, meta = validate_paginated(api.list_contacts(SECURITY_OFFICER))
    assert meta["total_count"] == 0, "a refused create persists no contact"


# ---------------------------------------------------------------------------
# Input validation on creation
# ---------------------------------------------------------------------------


def test_power_circuit_creation_without_phase_is_rejected(api):
    """PRD §3.4: "A `ProvisioningEngineer` designs one against a `cabinet_id` with a `circuit_code` unique within that cabinet, the busway side it draws from in `feed_side` (`A` or `B`), its `redundancy_role` (`PRIMARY`, which carries load and allocates power, or `REDUNDANT`, which stands by and allocates none), the `breaker_amps` rating of the breaker, the nominal `volts` of the supply, and the `phase` of that supply (`SINGLE` or `THREE`)."
    PRD §2.5: "All required body fields are present, every enum value is inside its declared set, every number is inside its declared range and every datetime is ISO 8601 UTC, otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/power_circuit_creation_without_phase_is_rejected
    """
    fx.set_clock(api)
    row = fx.create_row(api, hall_code="H2", row_code="R3")
    cabinet = fx.create_cabinet(api, row["id"], cabinet_code="C01", rated_power_kw=20.0)

    payload = f.create_power_circuit_payload(
        cabinet["id"],
        circuit_code="A-1",
        feed_side="A",
        redundancy_role="PRIMARY",
        breaker_amps=50,
        volts=240,
    )
    payload.pop("phase")

    validate_error(api.create_power_circuit(payload, ENGINEER_1), ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_power_circuits(ENGINEER_1, params={"cabinet_id": cabinet["id"]})
    )
    assert meta["total_count"] == 0, "a refused design persists no circuit"


def test_row_creation_with_zero_cooling_capacity_is_rejected(api):
    """PRD §3.2: "A `FacilityManager` creates a row with its `hall_code`, a `row_code` that must be unique within that hall, the number of physical cabinet positions in `cabinet_slot_count` (at least one), the `design_density_kw_per_cabinet` figure the row was engineered to (strictly positive), the hard busway limit `max_row_power_kw` (strictly positive), and the sensible cooling capacity serving the row, `cooling_capacity_kw` (strictly positive)."
    PRD §2.5: "All required body fields are present, every enum value is inside its declared set, every number is inside its declared range and every datetime is ISO 8601 UTC, otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/row_creation_with_zero_cooling_capacity_is_rejected
    """
    fx.set_clock(api)

    payload = f.create_row_payload(
        hall_code="H2",
        row_code="R6",
        cabinet_slot_count=8,
        design_density_kw_per_cabinet=25.0,
        max_row_power_kw=200.0,
        cooling_capacity_kw=0,
    )
    validate_error(api.create_row(payload, FACILITY_MANAGER), ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_rows(FACILITY_MANAGER))
    assert meta["total_count"] == 0, "a refused create persists no row"


# ---------------------------------------------------------------------------
# Defaults and computed values at creation
# ---------------------------------------------------------------------------


def test_cabinet_creation_defaults_footprint_and_u_height_and_occupies_no_slot(api):
    """PRD §3.3: "Two attributes default: `footprint_type` is `CABINET` unless the caller supplies `CAGE_SLOT` or `MEET_ME`, and `u_height`, the number of rack units available, defaults to 42."
    PRD §3.3: "New cabinets open with `status` `AVAILABLE` and no `contract_id`; because an `AVAILABLE` cabinet occupies no slot, creating one does not move the row's density ceiling, though the row's capacity picture is recomputed anyway."
    PRD §3.2: "`occupied_slot_count` counts the cabinets in the row whose `status` is `RESERVED`, `CAPACITY_HELD`, `INSTALLED`, `ACTIVE` or `DECOMMISSIONING`; an `AVAILABLE` or `RELEASED` cabinet occupies nothing."

    Design: Corner/entities/cabinet_creation_defaults_apply_when_optional_fields_are_omitted
    """
    fx.set_clock(api)
    row = fx.create_row(api, hall_code="H2", row_code="R4")

    payload = f.create_cabinet_payload(row["id"], cabinet_code="C01", rated_power_kw=20.0)
    payload.pop("footprint_type")
    payload.pop("u_height")

    data = validate_success(api.create_cabinet(payload, FACILITY_MANAGER), 201)

    assert data["footprint_type"] == "CABINET"
    assert data["u_height"] == 42
    assert data["status"] == "AVAILABLE"
    assert data["contract_id"] is None
    ax.assert_cabinet(data)
    ax.assert_cabinet_power(
        data,
        allocated_power_kw=0.000,
        cooling_load_kw=0.000,
        energized_primary_circuit_count=0,
    )

    row_after = fx.read_row(api, row["id"])
    ax.assert_row_capacity_view(
        row_after, occupied_slot_count=0, density_ceiling_kw=0.000, row_status="OPEN"
    )


def test_power_circuit_derated_capacity_is_pinned_from_the_breaker_plate(api):
    """PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
    PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

    Design: Corner/entities/power_circuit_derated_kw_computed_client_supplied_input_ignored
    """
    fx.set_clock(api)
    row = fx.create_row(
        api,
        hall_code="H2",
        row_code="R5",
        design_density_kw_per_cabinet=40.0,
        cooling_capacity_kw=80.0,
    )
    cabinet = fx.create_cabinet(api, row["id"], cabinet_code="C01", rated_power_kw=40.0)

    data = validate_success(
        api.create_power_circuit(
            {
                "cabinet_id": cabinet["id"],
                "circuit_code": "A-1",
                "feed_side": "A",
                "redundancy_role": "PRIMARY",
                "breaker_amps": 60,
                "volts": 415,
                "phase": "THREE",
            },
            ENGINEER_1,
        ),
        201,
    )

    ax.assert_power_circuit(data)
    ax.assert_circuit_power(
        data,
        status="DESIGNED",
        derated_kw=34.501,
        allocated_kw=0.000,
        cooling_contribution_kw=0.000,
    )
    assert data["energized_at"] is None
    assert data["meter_intervals"] == []


def test_power_circuit_derated_capacity_ignores_a_client_supplied_value(api):
    """PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
    PRD §2.7: "Derived fields are never accepted from clients."

    Design: Corner/entities/power_circuit_derated_kw_computed_client_supplied_input_ignored
    """
    fx.set_clock(api)
    row = fx.create_row(
        api,
        hall_code="H2",
        row_code="R5",
        design_density_kw_per_cabinet=40.0,
        cooling_capacity_kw=80.0,
    )
    cabinet = fx.create_cabinet(api, row["id"], cabinet_code="C01", rated_power_kw=40.0)

    data = validate_success(
        api.create_power_circuit(
            {
                "cabinet_id": cabinet["id"],
                "circuit_code": "A-1",
                "feed_side": "A",
                "redundancy_role": "PRIMARY",
                "breaker_amps": 60,
                "volts": 415,
                "phase": "THREE",
                "derated_kw": 99.999,
                "allocated_kw": 99.999,
            },
            ENGINEER_1,
        ),
        201,
    )

    ax.assert_circuit_power(
        data, status="DESIGNED", derated_kw=34.501, allocated_kw=0.000
    )
    assert data["derated_kw"] != 99.999, "derated_kw is derived, never taken from the body"


# ---------------------------------------------------------------------------
# The immutable ledger row
# ---------------------------------------------------------------------------


def test_invoice_line_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "An `InvoiceLine` is an immutable ledger entry and carries only `id` and `created_at`; it has neither `updated_at` nor `version`."
    PRD §3.9: "Power billing begins with the committed charge, which is `power_commit_kw` multiplied by the standing rate of 175.00 USD per contracted kilowatt per month, rounded to two decimals."
    PRD §3.9: "Two lines may result, in this order: a `POWER_COMMIT` line whose `amount_usd` is the committed charge and whose `quantity` is `power_commit_kw`, always; and a `POWER_OVERAGE` line whose `amount_usd` is the overage charge and whose `quantity` is the overage energy, appended only when the overage energy is greater than zero."

    Design: Corner/entities/invoice_line_is_immutable_and_carries_no_version_field
    """
    scenario = fx.setup_active_contract(
        api,
        row={"hall_code": "H2", "row_code": "R7"},
        contract={
            "billing_mode": "METERED_PLUS_COMMIT",
            "committed_cabinet_count": 1,
            "power_commit_kw": 20.0,
            "cross_connect_allowance": 0,
            "remote_hands_included_minutes": 0,
        },
        cabinet={"cabinet_code": "C01"},
    )
    fx.close_period(api, scenario.contract_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    lines = fx.invoice_lines(api, scenario.contract_id)
    assert len(lines) == 1, (
        f"the close appends only the POWER_COMMIT line when there is no overage, got "
        f"{[line['line_type'] for line in lines]}"
    )

    data = validate_success(api.get_invoice_line(lines[0]["id"], BILLING_OPERATOR))

    ax.assert_invoice_line(data)
    assert "version" not in data, "an invoice line carries no version"
    assert "updated_at" not in data, "an invoice line carries no updated_at"
    ax.assert_invoice_line_values(
        data,
        line_type="POWER_COMMIT",
        amount_usd=3500.00,
        quantity=20.0,
        unit_rate_usd=175.0000,
        reversed_flag=False,
    )
    assert _instant(data["period_start"]) == _instant("2026-07-01T00:00:00Z")
    assert _instant(data["period_end"]) == _instant("2026-08-01T00:00:00Z")
