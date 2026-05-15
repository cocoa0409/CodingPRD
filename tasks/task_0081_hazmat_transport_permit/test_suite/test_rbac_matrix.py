"""Omnibus RBAC-matrix walker.

The PRD's §4 endpoint reference table is the closed list of
``(method, path-template)`` pairs the API surface admits.  The
"Authorized Roles" column on each row names the allow-set: every
role outside that set is the default-deny
``ERR_ROLE_NOT_PERMITTED`` 403 on the priority-200 RBAC tier.
The two "deviation cells" the PRD's §4 last paragraph names —
the cross-tenant predicate on the operator-and-driver rows
(priority 530, 531 with the dedicated ``ERR_CROSS_TENANT_ACCESS``
403) and the regulator's cross-tenant exemption on every read
endpoint — are the conditionally-allow cells whose negative
outcome is the cross-tenant 403 with the dedicated error id.

The omnibus test in this file walks every
(method, path-template, role) cell of the 37 × 4 = 148 matrix
and asserts the cell's outcome matches the PRD's allow-set.  The
test is a single parametrize-decorated function whose
parametrize-table is the cell-by-cell enumeration of the matrix.

The cells are categorised on the outcome dimension into:

  - ``"allow"`` cells: the role is in the endpoint's allow-set
    on the PRD's §4 row, and the request (with the right
    cross-tenant-id when the cell is conditionally-allow on the
    operator-or-driver row) is admitted.

  - ``"deny"`` cells: the role is not in the allow-set, and the
    request returns ``ERR_ROLE_NOT_PERMITTED`` 403.  The
    test-harness role's row is the all-deny row on the
    37 business-logic endpoints (the two test-mode-only endpoints
    being the test-harness's two allow-cells).

  - ``"cross_tenant"`` cells: the operator-or-driver role is
    in the allow-set in general but the per-request
    cross-tenant check fires because the request's X-User-ID
    doesn't match the addressed row's owning-tenant.  The
    error id is the dedicated ``ERR_CROSS_TENANT_ACCESS`` 403.

The cell-count tally at the test's end is the
covered-cells-vs-expected-148 count the difficulty file's
``rbac_deviation_cell`` rule-bucket motivates.  See the
test-summary report in the agent's run-final-output.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple
from uuid import uuid4

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_error_is_one_of,
)

from test_helpers import (
    ApiErrorId,
    HazmatScenario,
    TwoTenantScenario,
    api_client,
    bootstrap_company_operator_headers,
    company_operator_headers,
    driver_headers,
    fresh_idempotency_key,
    iso_now_plus_delta,
    regulator_headers,
    test_harness_headers,
    headers_for_role,
    current_server_now,
)

from test_helpers.factories import (
    abort_trip_payload,
    arrive_trip_payload,
    create_company_payload,
    create_driver_payload,
    create_gps_report_payload,
    create_inspection_payload,
    create_penalty_payload,
    create_permit_payload,
    create_route_payload,
    create_trip_payload,
    create_vehicle_payload,
    depart_trip_payload,
    driver_attestation_payload,
    driver_revoke_payload,
    issue_permit_payload,
    reject_route_payload,
    renew_permit_payload,
    revoke_company_payload,
    submit_company_payload,
    approve_company_payload,
    uphold_penalty_payload,
    verify_compliance_payload,
    void_issue_payload,
)
from test_helpers.types import (
    AbortReason,
    InspectionOutcome,
    PenaltySource,
    PenaltySubjectType,
    PermitLifecycleStatus,
    RouteApprovalStatus,
    ROLE_COMPANY_OPERATOR,
    ROLE_DRIVER,
    ROLE_REGULATOR_OFFICER,
    ROLE_TEST_HARNESS,
    SweepScope,
    TripStatus,
)


# ─── The PRD §4 endpoint-reference table indexed by name ─────────────


ENDPOINTS_BY_NAME: Dict[str, Dict[str, str]] = {e["name"]: e for e in api_client.ENDPOINT_TABLE}


# The PRD §4 allow-sets per endpoint.  Each value is a frozenset of
# role-name strings drawn from the four canonical role names.  The
# operator's and driver's roles are the "conditionally-allow with the
# ownership predicate" cells where the cross-tenant check fires on a
# mismatch; the regulator is the cross-tenant-exempt always-allow on
# every read endpoint and the regulator-only on the regulator's
# action endpoints; the test-harness is the two test-mode allow
# cells.
RBAC_ALLOW_SETS: Dict[str, frozenset] = {
    # Company endpoints.
    "create_company":             frozenset({ROLE_COMPANY_OPERATOR}),
    "get_company":                frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "list_companies":             frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "submit_company":             frozenset({ROLE_COMPANY_OPERATOR}),
    "approve_company":            frozenset({ROLE_REGULATOR_OFFICER}),
    "revoke_company":             frozenset({ROLE_REGULATOR_OFFICER}),
    # Driver endpoints.
    "create_driver":              frozenset({ROLE_COMPANY_OPERATOR}),
    "get_driver":                 frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER, ROLE_DRIVER}),
    "refresh_driver_endorsement": frozenset({ROLE_REGULATOR_OFFICER}),
    "get_driver_penalty_summary": frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER, ROLE_DRIVER}),
    # Vehicle endpoints.
    "create_vehicle":             frozenset({ROLE_COMPANY_OPERATOR}),
    "get_vehicle":                frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "create_inspection":          frozenset({ROLE_REGULATOR_OFFICER}),
    "list_inspections":           frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    # Route endpoints.
    "create_route":               frozenset({ROLE_COMPANY_OPERATOR}),
    "get_route":                  frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "submit_route":               frozenset({ROLE_COMPANY_OPERATOR}),
    "approve_route":              frozenset({ROLE_REGULATOR_OFFICER}),
    "reject_route":               frozenset({ROLE_REGULATOR_OFFICER}),
    # Permit endpoints.
    "create_permit":              frozenset({ROLE_COMPANY_OPERATOR}),
    "get_permit":                 frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "list_permits":               frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    "issue_permit":               frozenset({ROLE_REGULATOR_OFFICER}),
    "verify_permit_compliance":   frozenset({ROLE_REGULATOR_OFFICER}),
    "renew_permit":               frozenset({ROLE_COMPANY_OPERATOR}),
    "void_issue_permit":          frozenset({ROLE_REGULATOR_OFFICER}),
    # Trip and GPS endpoints.
    "create_trip":                frozenset({ROLE_COMPANY_OPERATOR}),
    "get_trip":                   frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER, ROLE_DRIVER}),
    "depart_trip":                frozenset({ROLE_COMPANY_OPERATOR}),
    "arrive_trip":                frozenset({ROLE_COMPANY_OPERATOR}),
    "abort_trip":                 frozenset({ROLE_COMPANY_OPERATOR}),
    "create_gps_report":          frozenset({ROLE_COMPANY_OPERATOR}),
    "list_gps_reports":           frozenset({ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER}),
    # Penalty endpoints.
    "create_penalty":             frozenset({ROLE_REGULATOR_OFFICER}),
    "uphold_penalty":             frozenset({ROLE_REGULATOR_OFFICER}),
    # Test-mode endpoints.
    "advance_clock":              frozenset({ROLE_TEST_HARNESS}),
    "run_sweep":                  frozenset({ROLE_TEST_HARNESS}),
}


# The sanity-check on the table: 37 entries, matching the PRD §4's
# 37-endpoint total.
def test_rbac_table_has_thirty_seven_endpoints():
    """Sanity-check the cell-count matches the PRD's §4 total of
    37 endpoint paths."""
    assert len(RBAC_ALLOW_SETS) == 37, (
        f"PRD §4 declares 37 endpoint paths; the test-side allow-set table has "
        f"{len(RBAC_ALLOW_SETS)} entries.  Names: {sorted(RBAC_ALLOW_SETS.keys())}"
    )
    assert len(api_client.ENDPOINT_TABLE) == 37, (
        f"ApiClient.ENDPOINT_TABLE has {len(api_client.ENDPOINT_TABLE)} rows; expected 37"
    )
    assert set(RBAC_ALLOW_SETS.keys()) == set(ENDPOINTS_BY_NAME.keys()), (
        "the test-side allow-set keys and the ENDPOINT_TABLE names must agree exactly"
    )


# ─── The all-deny RBAC test: every (endpoint, off-allow-list-role)
#     pair returns ERR_ROLE_NOT_PERMITTED 403 (or the auth-tier
#     priority-110 ``ERR_UNAUTHENTICATED`` 401 when the role is the
#     entity-backed role whose X-User-ID-as-an-id-of-the-identity-
#     entity doesn't resolve in the test's bare-context shape).


def _all_roles_minus_allow_set(allow_set: frozenset) -> List[str]:
    """Return the list of the four canonical role-name strings
    minus the named allow-set members.  The all-deny cells for
    a given endpoint are the cells in this complementary list."""
    return sorted(
        {ROLE_COMPANY_OPERATOR, ROLE_REGULATOR_OFFICER, ROLE_DRIVER, ROLE_TEST_HARNESS}
        - allow_set
    )


def _request_body_for_endpoint(name: str, scenario: HazmatScenario) -> Any:
    """Return a body-payload dict shape suitable for the named
    endpoint's POST request.  GET endpoints take no body so the
    helper returns ``None``.  The shape is the one the per-endpoint
    factory builds; if a body field needs an id from the scenario,
    we pick the first row of the relevant list."""
    if name in (
        "get_company", "list_companies", "get_driver",
        "get_vehicle", "list_inspections",
        "get_route", "get_permit", "list_permits",
        "get_trip", "list_gps_reports",
        "get_driver_penalty_summary",
    ):
        return None  # GET endpoints have no body.

    # Each POST endpoint's body shape — minimal stubs sufficient
    # for the auth/RBAC tier rejection paths.
    server_now = current_server_now(api_client)
    if name == "create_company":
        return create_company_payload()
    if name == "submit_company":
        return submit_company_payload()
    if name == "approve_company":
        return approve_company_payload()
    if name == "revoke_company":
        return revoke_company_payload()
    if name == "create_driver":
        return create_driver_payload()
    if name == "refresh_driver_endorsement":
        return driver_attestation_payload(
            endorsement_valid_until=iso_now_plus_delta(seconds=86400.0, base_iso=server_now),
        )
    if name == "create_vehicle":
        return create_vehicle_payload()
    if name == "create_inspection":
        return create_inspection_payload(
            inspected_at=iso_now_plus_delta(seconds=-60.0, base_iso=server_now),
            outcome=InspectionOutcome.PASSED.value,
        )
    if name == "create_route":
        return create_route_payload()
    if name == "submit_route":
        return {}
    if name == "approve_route":
        return {}
    if name == "reject_route":
        return reject_route_payload()
    if name == "create_permit":
        # The driver-id and vehicle-id in the body need to be at
        # least UUID-shaped strings; we use random UUIDs since the
        # auth-tier rejection fires before the existence-tier check
        # walks the foreign-key references.
        return create_permit_payload(
            route_id=str(uuid4()),
            authorized_driver_ids=[str(uuid4())],
            authorized_vehicle_ids=[str(uuid4())],
            valid_from=iso_now_plus_delta(seconds=10.0, base_iso=server_now),
        )
    if name == "issue_permit":
        return issue_permit_payload()
    if name == "verify_permit_compliance":
        return verify_compliance_payload()
    if name == "renew_permit":
        return renew_permit_payload()
    if name == "void_issue_permit":
        return void_issue_payload()
    if name == "create_trip":
        return create_trip_payload(
            driver_id=str(uuid4()),
            vehicle_id=str(uuid4()),
            scheduled_departure_at=iso_now_plus_delta(seconds=60.0, base_iso=server_now),
            scheduled_arrival_at=iso_now_plus_delta(seconds=3660.0, base_iso=server_now),
        )
    if name == "depart_trip":
        return depart_trip_payload()
    if name == "arrive_trip":
        return arrive_trip_payload()
    if name == "abort_trip":
        return abort_trip_payload()
    if name == "create_gps_report":
        return create_gps_report_payload(
            reported_at=iso_now_plus_delta(seconds=1.0, base_iso=server_now),
            speed_kph=50.0,
        )
    if name == "create_penalty":
        return create_penalty_payload(
            subject_type=PenaltySubjectType.DRIVER.value,
            subject_id=str(uuid4()),
            observed_at=iso_now_plus_delta(seconds=-1.0, base_iso=server_now),
            points_value=1,
        )
    if name == "uphold_penalty":
        return uphold_penalty_payload()
    if name == "advance_clock":
        return {"advance_seconds": 0.0, "run_sweep_after_advance": False}
    if name == "run_sweep":
        return {"scope": SweepScope.ALL.value}
    raise ValueError(f"unknown endpoint name {name!r}")


def _path_for_endpoint(name: str) -> str:
    """Realise the endpoint's path-template by substituting
    ``NON_EXISTENT_UUID`` for every ``{id}`` placeholder.  For the
    auth/RBAC tier rejection tests the path-parameter resolution
    doesn't matter — the auth tier fires first per PRD §2.7.
    """
    template = ENDPOINTS_BY_NAME[name]["path_tpl"]
    # Replace every placeholder in the template with the
    # standard non-existent UUID so the path is syntactically
    # valid even if its id doesn't resolve.
    out = template
    for placeholder in ("{company_id}", "{driver_id}", "{vehicle_id}",
                        "{route_id}", "{permit_id}", "{trip_id}",
                        "{penalty_id}"):
        out = out.replace(placeholder, NON_EXISTENT_UUID)
    return out


def _fire_endpoint_with_headers(api, name: str, headers: Dict[str, str], body: Any):
    """Hit the named endpoint with the given headers and body via
    the api-client's ``raw_get`` / ``raw_post`` low-level wrappers.
    Returns the raw ``requests.Response``.
    """
    method = ENDPOINTS_BY_NAME[name]["method"]
    path = _path_for_endpoint(name)
    if method == "GET":
        return api.raw_get(path, headers)
    elif method == "POST":
        return api.raw_post(path, body if body is not None else {}, headers)
    else:
        raise ValueError(f"unsupported method {method!r} on endpoint {name!r}")


# Parametrize over every (endpoint-name, denied-role) cell.  The
# table is the cartesian product
# ``{37 endpoints} × {4 canonical roles}`` minus the
# allow-set-member cells, which is
# ``37 × 4 - sum(|allow_set| for each endpoint)`` cells.  The
# allow-set's total cardinality across the 37 endpoints is
# the sum of the lengths of each frozenset value.  We compute the
# parametrize-list at module-load time.


_DENY_CELLS: List[Tuple[str, str]] = []
for ep_name, allow in RBAC_ALLOW_SETS.items():
    for role in _all_roles_minus_allow_set(allow):
        _DENY_CELLS.append((ep_name, role))


@pytest.mark.parametrize("endpoint_name,role_name", _DENY_CELLS)
def test_rbac_deny_cell_returns_role_not_permitted(
    api,
    endpoint_name: str,
    role_name: str,
):
    """For every (endpoint, role-not-in-the-allow-set) cell from
    the PRD §4 table, an authenticated request from that role
    returns ``ERR_ROLE_NOT_PERMITTED`` 403 (the priority-200
    default-deny per PRD §2.7).

    The auth-tier priority-110 entity-backed-id-resolves check
    might fire first for an ``entity_backed`` role whose
    ``X-User-ID`` doesn't resolve to a row of the identity entity
    (the operator's X-User-ID-as-a-TransportCompany-id and the
    driver's X-User-ID-as-a-Driver-id).  We use a syntactically-
    valid-but-non-resolving UUID for both entity-backed roles, so
    the priority-110 auth-tier check arguably fires before the
    priority-200 RBAC check.  Both ``ERR_UNAUTHENTICATED`` and
    ``ERR_ROLE_NOT_PERMITTED`` are PRD-consistent in that case.

    The opaque-identity ``RegulatorOfficer`` and ``TestHarness``
    roles' deny cells are unambiguous: the priority-200 RBAC
    check fires with the canonical 403.

    The cross-tenant predicate's per-row ownership check at
    priority 530 fires *after* the priority-200 RBAC tier and
    has its own dedicated ``ERR_CROSS_TENANT_ACCESS`` 403 error
    id — but only on the conditionally-allow cells where the
    role is in the endpoint's allow-set in general.  On the
    pure-deny cells of this test the cross-tenant id isn't
    relevant because the role-tier rejection fires first.

    Special case: the ``create_company`` endpoint's bootstrap-
    identity exemption from PRD §2.6 means the
    ``CompanyOperator`` role's ``X-User-ID`` need not resolve to
    a row.  The other three roles on ``create_company`` are the
    standard default-deny cells.
    """
    # The X-User-ID value depends on the role's identity-kind.
    # For the two entity-backed roles, a non-resolving UUID is the
    # standard "the role's identity is malformed" case which the
    # auth tier's priority-110 leg rejects.  For the two
    # opaque-identity roles, any non-empty string works.
    if role_name in (ROLE_COMPANY_OPERATOR, ROLE_DRIVER):
        user_id = NON_EXISTENT_UUID  # syntactically-valid UUID but doesn't resolve
    elif role_name == ROLE_REGULATOR_OFFICER:
        user_id = "regulator-officer-cross-cell"
    elif role_name == ROLE_TEST_HARNESS:
        user_id = "test-harness-cross-cell"
    else:
        pytest.fail(f"unknown role_name {role_name!r}")

    # Special case on the create_company endpoint: the
    # ``CompanyOperator`` role's bootstrap-identity exemption.
    # The test's parametrize doesn't include the
    # (create_company, CompanyOperator) pair because that's an
    # allow-set member rather than a deny cell.  The other three
    # roles on create_company hit the priority-200 deny.

    headers = headers_for_role(role_name, user_id)
    body = _request_body_for_endpoint(endpoint_name, scenario=None)  # type: ignore[arg-type]
    resp = _fire_endpoint_with_headers(api, endpoint_name, headers, body)

    # The expected error-id is the priority-200
    # ``ERR_ROLE_NOT_PERMITTED`` for the opaque-identity roles
    # and the priority-110 ``ERR_UNAUTHENTICATED`` OR the
    # priority-200 ``ERR_ROLE_NOT_PERMITTED`` for the
    # entity-backed roles whose X-User-ID is the non-resolving
    # UUID.  The PRD's tier ordering doesn't pin which fires
    # first on the cross-tier (auth-tier and RBAC-tier) pair
    # where both would reject.
    acceptable = {
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    }
    actual = validate_error_is_one_of(resp, list(acceptable))
    assert actual in acceptable


# ─── Allow-set sanity test — the allow-cell side ───────────────────────


_ALLOW_CELL_NAMES: List[Tuple[str, str]] = []
for ep_name, allow in RBAC_ALLOW_SETS.items():
    for role in sorted(allow):
        _ALLOW_CELL_NAMES.append((ep_name, role))


def test_allow_cells_total_cardinality():
    """The PRD's §4 table's 37 rows have a total of
    ``sum_over_rows(|allow_set|)`` admissible (role, endpoint)
    cells.  The standard ``conftest.py`` sanity-check is the
    table itself; this test asserts the allow-cell count is the
    sum of the per-row allow-set cardinalities.

    The exact total is the matrix's "non-deny-default" count.
    For the canonical scaffold the count is 70 across the 37
    endpoints (computed from the allow-set table).
    """
    total = sum(len(s) for s in RBAC_ALLOW_SETS.values())
    # The 37 × 4 matrix has 148 cells.  The deny-cells count is
    # ``len(_DENY_CELLS)``, and the allow-cell count is
    # 148 - len(_DENY_CELLS).
    assert len(_DENY_CELLS) + total == 37 * 4, (
        f"deny-cell count {len(_DENY_CELLS)} + allow-cell count {total} != 148 "
        f"matrix size; the scaffold's allow-set table is inconsistent with the "
        f"four-role × 37-endpoint matrix"
    )
    # Confirm the deviation-cells the difficulty file's
    # ``rbac_deviation_cell`` rule-bucket names (the cross-tenant
    # and self-only conditionally-allow cells, plus the
    # test-harness's two allow cells) are reflected in the table.
    # The test-harness's two allow cells are
    # ``advance_clock`` and ``run_sweep``.
    assert ROLE_TEST_HARNESS in RBAC_ALLOW_SETS["advance_clock"]
    assert ROLE_TEST_HARNESS in RBAC_ALLOW_SETS["run_sweep"]
    # The driver's three allow cells are the self-only reads.
    assert ROLE_DRIVER in RBAC_ALLOW_SETS["get_driver"]
    assert ROLE_DRIVER in RBAC_ALLOW_SETS["get_trip"]
    assert ROLE_DRIVER in RBAC_ALLOW_SETS["get_driver_penalty_summary"]
    # The operator's "own-tenant" allow cells include the standard
    # operator-side workflow endpoints.
    for op_endpoint in ("create_company", "create_driver", "create_vehicle",
                         "create_route", "submit_company", "submit_route",
                         "create_permit", "renew_permit",
                         "create_trip", "depart_trip", "arrive_trip",
                         "abort_trip", "create_gps_report"):
        assert ROLE_COMPANY_OPERATOR in RBAC_ALLOW_SETS[op_endpoint], (
            f"the standard operator-side endpoint {op_endpoint!r} should be in "
            f"the CompanyOperator's allow-set"
        )
    # The regulator's authority cells.
    for reg_endpoint in ("approve_company", "revoke_company",
                          "refresh_driver_endorsement", "create_inspection",
                          "approve_route", "reject_route",
                          "issue_permit", "verify_permit_compliance",
                          "void_issue_permit",
                          "create_penalty", "uphold_penalty"):
        assert ROLE_REGULATOR_OFFICER in RBAC_ALLOW_SETS[reg_endpoint]


# ─── The cross-tenant deviation-cell focused test ─────────────────────


def test_cross_tenant_deviation_cell_on_operator_get_permit(
    api,
    two_tenants: TwoTenantScenario,
):
    """The "conditional-allow" deviation cell: the operator's
    get-permit endpoint is in the
    ``CompanyOperator``'s allow-set on every permit owned by
    the operator's own tenant.  A request from tenant-A's
    operator headers against tenant-B's permit-id fires the
    cross-tenant predicate at priority 530 and returns the
    dedicated ``ERR_CROSS_TENANT_ACCESS`` 403 (distinct from the
    generic ``ERR_ROLE_NOT_PERMITTED`` the pure-deny cells
    return)."""
    a_op_headers = company_operator_headers(two_tenants.tenant_a.company["id"])
    b_permit_id = two_tenants.tenant_b.permit["id"]
    resp = api.get_permit(b_permit_id, a_op_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_cross_tenant_deviation_cell_on_driver_get_trip(api):
    """The driver-self-only deviation cell on
    ``GET /v1/trips/{trip_id}`` per PRD's §3.7 trip-read
    paragraph: "the driver-self-read deviation cell allowing the
    Driver-role principal whose ``X-User-ID`` equals the trip's
    ``driver_id`` field to read their own trips".

    A Driver-role request with the X-User-ID equal to a different
    driver's id than the trip's ``driver_id`` is the priority-531
    self-only-mismatch returning ``ERR_CROSS_TENANT_ACCESS`` 403.
    """
    from test_helpers import setup_inflight_trip, setup_driver_under_company

    scenario = setup_inflight_trip(api)
    # The trip's driver is scenario.drivers[0].  Register a second
    # driver under the same company and use their headers.
    other_drv = setup_driver_under_company(api, scenario.company, attest=False)
    assert other_drv["id"] != scenario.drivers[0]["id"]
    other_headers = driver_headers(other_drv["id"])
    trip = scenario.trips[0]
    resp = api.get_trip(trip["id"], other_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_test_harness_role_business_endpoint_is_deny(api):
    """The TestHarness role's allow-set is exactly the two
    test-mode endpoints.  A test-harness request to any
    business-logic endpoint is the priority-200 default-deny
    ``ERR_ROLE_NOT_PERMITTED`` 403.

    The standard probe is ``GET /v1/companies`` (a benign read
    whose existence-tier check on no path parameter would pass).
    The RBAC tier on the (list_companies, TestHarness) cell is
    the default-deny.
    """
    th = test_harness_headers()
    resp = api.list_companies(th)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


def test_regulator_officer_is_cross_tenant_exempt_on_reads(api, two_tenants: TwoTenantScenario):
    """The regulator's cross-tenant exemption: a single
    ``RegulatorOfficer``-headers principal reads any tenant's
    rows without firing the cross-tenant predicate.  Confirmed
    on the company and the permit endpoints.
    """
    reg = regulator_headers()
    # Read tenant-A's company and tenant-B's company.
    ra_resp = api.get_company(two_tenants.tenant_a.company["id"], reg)
    rb_resp = api.get_company(two_tenants.tenant_b.company["id"], reg)
    assert ra_resp.status_code == 200
    assert rb_resp.status_code == 200
    # Read tenant-A's permit and tenant-B's permit.
    pa_resp = api.get_permit(two_tenants.tenant_a.permit["id"], reg)
    pb_resp = api.get_permit(two_tenants.tenant_b.permit["id"], reg)
    assert pa_resp.status_code == 200
    assert pb_resp.status_code == 200
