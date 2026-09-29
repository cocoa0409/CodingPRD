"""The cross-cutting screens every request passes: header authentication, role
authorisation, per-aggregate not-found codes, payload shape and the asymmetric reads."""
from test_helpers import (
    ADMIN,
    FINANCE_A,
    OPERATOR,
    PROGRAM,
    VERIFIER,
    create_facility,
    create_pathway,
    headers_with_unrecognised_role,
    headers_without_role,
    headers_without_user,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_FACILITY_ID = "9f000000-0000-4000-8000-000000000002"


def test_01_every_aggregate_answers_an_unknown_path_id_with_its_own_code(api):
    """Twelve detail reads of twelve missing rows produce twelve distinct 404 codes.

    PRD: "**Path resolution** — every identifier embedded in the URL is resolved strictly left to right, and the first one that does not exist produces its own not-found error: `ERR_DAIRY_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_OPS_DAY_NOT_FOUND`, `ERR_INTERCONNECT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`, `ERR_PATHWAY_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND` or `ERR_STATEMENT_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/error_every_unknown_path_id_returns_its_own_not_found_code
    """
    sweep = [
        (api.get_dairy, "9f000000-0000-4000-8000-000000000001", "ERR_DAIRY_NOT_FOUND"),
        (api.get_facility, "9f000000-0000-4000-8000-000000000002", "ERR_FACILITY_NOT_FOUND"),
        (api.get_agreement, "9f000000-0000-4000-8000-000000000003", "ERR_AGREEMENT_NOT_FOUND"),
        (api.get_delivery, "9f000000-0000-4000-8000-000000000004", "ERR_DELIVERY_NOT_FOUND"),
        (api.get_ops_day, "9f000000-0000-4000-8000-000000000005", "ERR_OPS_DAY_NOT_FOUND"),
        (
            api.get_interconnect,
            "9f000000-0000-4000-8000-000000000006",
            "ERR_INTERCONNECT_NOT_FOUND",
        ),
        (api.get_nomination, "9f000000-0000-4000-8000-000000000007", "ERR_NOMINATION_NOT_FOUND"),
        (api.get_pathway, "9f000000-0000-4000-8000-000000000008", "ERR_PATHWAY_NOT_FOUND"),
        (api.get_batch, "9f000000-0000-4000-8000-000000000009", "ERR_BATCH_NOT_FOUND"),
        (api.get_audit, "9f000000-0000-4000-8000-00000000000a", "ERR_AUDIT_NOT_FOUND"),
        (
            api.get_nutrient_application,
            "9f000000-0000-4000-8000-00000000000b",
            "ERR_APPLICATION_NOT_FOUND",
        ),
        (api.get_statement, "9f000000-0000-4000-8000-00000000000c", "ERR_STATEMENT_NOT_FOUND"),
    ]

    seen = set()
    for read, missing_id, expected in sweep:
        body = validate_error(read(missing_id, ADMIN), expected, 404)
        seen.add(body["error_id"])
    assert len(seen) == 12


def test_02_a_malformed_header_pair_is_rejected_before_the_row_is_looked_up(api):
    """A missing role, a missing user and an invented role all answer 401, never 404.

    PRD: "If either header is absent, or if the value of `X-User-Role` is not one of those seven exact strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_missing_auth_headers_are_unauthenticated_before_any_lookup
    """
    attempts = [
        headers_without_role(),
        headers_without_user(),
        headers_with_unrecognised_role(),
    ]

    for headers in attempts:
        body = validate_error(
            api.get_facility(UNKNOWN_FACILITY_ID, headers), "ERR_UNAUTHENTICATED", 401
        )
        assert isinstance(body["message"], str)
        assert body["message"] != ""


def test_03_a_bad_enum_a_bad_range_and_a_bad_type_share_one_screening_code(api):
    """Three different shape breaches, one code, and nothing persisted afterwards.

    PRD: "**Schema conformance** — required fields present, types correct, numeric ranges honoured, enum members valid, decimal scale not exceeded: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/errors/error_enum_and_numeric_constraint_breaches_are_invalid_request
    """
    validate_error(
        api.create_facility(
            {
                "name": "Ambient Lagoon",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "AMBIENT",
                "target_temperature_c": 22.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
                "dscr_minimum": 1.250,
            },
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_dairy(
            {
                "name": "Empty Barn Dairy",
                "county": "Tulare",
                "herd_size": 0,
                "manure_management_baseline": "LAGOON",
                "haul_distance_km": 12.0,
                "annual_nitrogen_budget_kg": 24000.000,
            },
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.create_dairy(
            {
                "name": "Typo Dairy",
                "county": "Tulare",
                "herd_size": "three thousand",
                "manure_management_baseline": "LAGOON",
                "haul_distance_km": 12.0,
                "annual_nitrogen_budget_kg": 24000.000,
            },
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _, dairy_page = validate_paginated(api.list_dairies(ADMIN, {"limit": 10, "offset": 0}))
    assert dairy_page["total_count"] == 0
    _, facility_page = validate_paginated(
        api.list_facilities(ADMIN, {"limit": 10, "offset": 0})
    )
    assert facility_page["total_count"] == 0


def test_04_the_platform_administrator_owns_the_clock_and_the_master_data(api):
    """The clock move, the dairy registration and the facility registration all succeed.

    PRD: "A `PlatformAdmin` registers master data — dairies and facilities — moves the logical clock and grants posture overrides."

    Design: Corner/rbac/rbac_platform_admin_performs_its_exclusive_master_data_writes
    """
    set_clock("2026-08-01T00:00:00Z")

    dairy = validate_success(
        api.create_dairy(
            {
                "name": "Vista Verde Dairy",
                "county": "Tulare",
                "herd_size": 3200,
                "manure_management_baseline": "LAGOON",
                "haul_distance_km": 12.0,
                "annual_nitrogen_budget_kg": 24000.000,
            },
            ADMIN,
        ),
        201,
    )
    facility = validate_success(
        api.create_facility(
            {
                "name": "Tulare Digester 1",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "MESOPHILIC",
                "target_temperature_c": 38.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
                "dscr_minimum": 1.250,
            },
            ADMIN,
        ),
        201,
    )

    assert dairy["status"] == "PROSPECT"
    assert facility["design_max_olr"] == 3.500


def test_05_a_perfectly_formed_body_does_not_buy_a_role_its_way_in(api):
    """Four valid payloads from four wrong roles are all stopped at the role check.

    PRD: "If both headers are well-formed but the declared role is not among the roles authorised for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_other_roles_are_forbidden_from_exclusive_writes
    """
    facility = create_facility()
    pathway = create_pathway(facility["id"])

    validate_error(
        api.create_dairy(
            {
                "name": "Vista Verde Dairy",
                "county": "Tulare",
                "herd_size": 3200,
                "manure_management_baseline": "LAGOON",
                "haul_distance_km": 12.0,
                "annual_nitrogen_budget_kg": 24000.000,
            },
            OPERATOR,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_facility(
            {
                "name": "Shadow Plant",
                "digester_volume_m3": 6000.000,
                "hydraulic_capacity_tonnes_per_day": 500.000,
                "thermal_regime": "MESOPHILIC",
                "target_temperature_c": 38.0,
                "reserve_target_cents": 4_000_000,
                "annual_debt_service_cents": 18_000_000,
                "dscr_minimum": 1.250,
            },
            FINANCE_A,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_pathway(
            {
                "facility_id": facility["id"],
                "program": "RFS_D3",
                "pathway_code": "EPA-RFS-D3-2026-01",
            },
            VERIFIER,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_audit(
            {
                "pathway_id": pathway["id"],
                "audit_year": 2026,
                "verifier_body_name": "Sierra Verification Services",
            },
            PROGRAM,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    _, dairy_page = validate_paginated(api.list_dairies(ADMIN, {"limit": 10, "offset": 0}))
    assert dairy_page["total_count"] == 0
    untouched = validate_success(api.get_pathway(pathway["id"], PROGRAM))
    assert untouched["status"] == "PROVISIONAL"


def test_06_the_two_computed_reads_do_not_share_the_same_audience(api):
    """The verifier reads the credit ledger and is turned away from the money view.

    PRD: "Read access is broad but not universal: the facility financial summary is readable only by `PlatformAdmin`, `ProjectOperator` and `FinanceController`, while the pathway credit ledger is readable only by `ProgramAdministrator`, `CreditVerifier` and `FinanceController`."

    Design: Corner/rbac/rbac_shared_reads_split_the_ledger_from_the_settlement_summary
    """
    facility = create_facility()
    pathway = create_pathway(facility["id"])

    verifier_ledger = validate_success(api.get_credit_ledger(pathway["id"], VERIFIER))
    assert verifier_ledger["credits_outstanding"] == 0.000

    validate_error(
        api.get_financial_summary(facility["id"], VERIFIER), "ERR_FORBIDDEN_ROLE", 403
    )

    finance_ledger = validate_success(api.get_credit_ledger(pathway["id"], FINANCE_A))
    assert finance_ledger["credit_control_residual"] == 0.000
    finance_summary = validate_success(api.get_financial_summary(facility["id"], FINANCE_A))
    assert finance_summary["gross_revenue_to_date_cents"] == 0
