"""Authentication-tier and authorization-tier contract tests.

Covers the PRD's §2.1 two-header auth contract (the ``X-User-ID`` and
``X-User-Role`` pair), the four canonical role-name strings, the
priority-100 missing-or-bad-header rejection
``ERR_UNAUTHENTICATED``, the priority-110
entity-backed-id-resolves rejection (the same error id on a
syntactically-valid ``X-User-ID`` that doesn't resolve to a row in the
identity-entity table), the priority-200 RBAC role-deny default
``ERR_ROLE_NOT_PERMITTED``, the priority-530 cross-tenant ownership
``ERR_CROSS_TENANT_ACCESS`` on the operator-side, the priority-531
driver-self-only variant of the same error-id on the Driver-role's
three allow-list endpoints, the regulator-officer's cross-tenant
exemption per the regulatory-mandate convention, the test-harness
role's limited allow-list, and the bootstrap-identity exception on
``POST /v1/companies`` from PRD §2.6.

The existence-vs-cross-tenant precedence pair (the 300-vs-530
priority pair where the not-found error wins on a wrong-tenant
request for a non-existent resource id) is tested in
``test_validation_precedence.py``; this file covers each rejection
in isolation per the "test each validation in an isolated scenario
where only one can fail" rule from the unit-test-generator's
philosophy.
"""

from __future__ import annotations

from typing import Dict, List
from uuid import uuid4

import pytest

from test_helpers import (
    ApiErrorId,
    HazmatScenario,
    TwoTenantScenario,
    api_client,
    bootstrap_company_operator_headers,
    build_user_headers,
    company_operator_headers,
    create_company_payload,
    driver_headers,
    fetch_penalty_summary,
    get_success_data,
    headers_for_role,
    is_valid_uuid,
    regulator_headers,
    setup_active_permit,
    setup_approved_company,
    setup_driver_under_company,
    setup_two_tenants,
    test_harness_headers,
    validate_error,
    validate_success,
)
from test_helpers.types import (
    ROLE_COMPANY_OPERATOR,
    ROLE_DRIVER,
    ROLE_REGULATOR_OFFICER,
    ROLE_TEST_HARNESS,
)


NON_EXISTENT_UUID_LOCAL = "00000000-0000-0000-0000-000000000000"


# ─── Auth tier — priority 100 ──────────────────────────────────────────


@pytest.mark.parametrize("headers", [
    {},                                                # both headers missing
    {"X-User-Role": ROLE_REGULATOR_OFFICER},           # X-User-ID missing
    {"X-User-ID": "some-id"},                          # X-User-Role missing
    {"X-User-Role": "", "X-User-ID": "some-id"},       # empty role string
    {"X-User-Role": ROLE_REGULATOR_OFFICER, "X-User-ID": ""},  # empty id string
    {"X-User-Role": "UnknownRoleName", "X-User-ID": "id"},      # role outside the canonical four
])
def test_missing_or_invalid_auth_headers_rejected_401(api, headers: Dict[str, str]):
    """PRD §2.1: "A request that omits either header, that supplies an
    empty string in either field, or that supplies a role name
    outside the four canonical strings is rejected at the top of the
    validation pipeline with ``ERR_UNAUTHENTICATED`` returned at
    HTTP status 401".

    Drives the six canonical bad-header shapes through a benign
    read endpoint (``GET /v1/companies``) so the failure is the
    auth-tier rejection rather than any downstream existence or
    business check.
    """
    resp = api.get(path="/v1/companies", headers=headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_entity_backed_id_non_resolving_is_401(api, approved_company: Dict):
    """PRD §2.1: "for the two entity-backed roles, the entity-id-
    resolves check, which fires the same ``ERR_UNAUTHENTICATED`` 401
    because a credential naming a non-existent backing entity is
    itself an invalid credential rather than a "not found"
    reference" — the priority-110 check.

    The fixture creates one APPROVED TransportCompany row whose id
    is a known UUID.  A CompanyOperator request with an
    ``X-User-ID`` set to a *different* syntactically-valid UUID
    that does NOT resolve to any TransportCompany row is the
    canonical priority-110 case.  The endpoint we hit is the
    ``GET /v1/companies/{company_id}`` for the real company's id
    — the auth-tier check fires before the existence-tier 404 so
    the error id is the auth's ``ERR_UNAUTHENTICATED``.
    """
    real_company_id = approved_company["id"]
    bogus_operator_id = str(uuid4())
    bad_headers = build_user_headers(bogus_operator_id, ROLE_COMPANY_OPERATOR)
    resp = api.get_company(real_company_id, bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_driver_role_with_non_resolving_id_is_401(api, approved_company: Dict):
    """The Driver-role version of the priority-110 check.  A
    syntactically-valid ``X-User-ID`` UUID that doesn't resolve to
    any Driver row is the auth-tier rejection regardless of the
    target endpoint."""
    # The Driver role's three allow-list endpoints include
    # ``GET /v1/drivers/{driver_id}``.  Address the company-id as
    # the path (a wrong-type id), but the auth-tier check on the
    # X-User-ID's resolves-to-a-Driver-row leg fires first.
    headers = build_user_headers(str(uuid4()), ROLE_DRIVER)
    resp = api.get_driver(NON_EXISTENT_UUID_LOCAL, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ─── Auth tier — the bootstrap exception on POST /v1/companies ────────


def test_company_create_bootstrap_accepts_arbitrary_x_user_id(api):
    """PRD §2.6 last paragraph: "the operator's very first request —
    ``POST /v1/companies`` to file the initial qualification
    application — necessarily carries an ``X-User-ID`` that does
    not yet correspond to a TransportCompany row because the row is
    what the request is asking the server to create.  The handler
    treats this single case specially: the request's ``X-User-ID``
    is accepted as the would-be operator identifier, the server
    mints a fresh UUID for the new row's ``id`` regardless of the
    header's value".

    Issue the company-create with a deliberately-non-resolving
    ``X-User-ID`` and confirm the response is the 201 success
    envelope with the server-minted row id.
    """
    bogus_id = "bootstrap-token-" + uuid4().hex
    headers = build_user_headers(bogus_id, ROLE_COMPANY_OPERATOR)
    resp = api.create_company(create_company_payload(), headers)
    data = validate_success(resp, 201)
    # The server-minted id is a fresh UUID, distinct from the bogus
    # bootstrap-identifier the request sent.
    assert is_valid_uuid(data["id"])
    assert data["id"] != bogus_id, (
        "company-create response's id should be a server-minted UUID, "
        "not the bootstrap-identifier the request sent"
    )
    assert data["qualification_status"] == "DRAFT"


def test_subsequent_operator_call_after_bootstrap_uses_minted_id(api):
    """The post-bootstrap convention: the client's subsequent
    operator-side calls use the response body's
    ``data.id`` field as their ``X-User-ID``.  A read on the
    just-minted company with the minted id is a 200 success; the
    cross-tenant predicate trivially holds because the
    ``X-User-ID`` equals the addressed row's id.
    """
    boot_headers = bootstrap_company_operator_headers()
    co_resp = api.create_company(create_company_payload(), boot_headers)
    company = get_success_data(co_resp)
    op_headers = company_operator_headers(company["id"])
    read_resp = api.get_company(company["id"], op_headers)
    re_read = validate_success(read_resp, 200)
    assert re_read["id"] == company["id"]


# ─── RBAC tier — priority 200 default-deny ─────────────────────────────


@pytest.mark.parametrize("role_name,id_value", [
    (ROLE_REGULATOR_OFFICER, "regulator-officer-x"),
    (ROLE_DRIVER, str(uuid4())),
    (ROLE_TEST_HARNESS, "test-harness-y"),
])
def test_non_operator_cannot_create_company(api, role_name: str, id_value: str):
    """PRD §4 endpoint table for ``POST /v1/companies``: the
    "Authorized Role(s)" column has just ``CompanyOperator``; every
    other role is the default-deny ``ERR_ROLE_NOT_PERMITTED`` 403
    on this endpoint.
    """
    headers = build_user_headers(id_value, role_name)
    resp = api.create_company(create_company_payload(), headers)
    # For the Driver role with a non-resolving X-User-ID, the
    # priority-110 auth-tier rejection (the entity-backed-id-resolves
    # leg) fires before the RBAC priority-200 check, so the error id
    # is ``ERR_UNAUTHENTICATED``.  The opaque-id-bearing
    # RegulatorOfficer and TestHarness roles hit the RBAC tier
    # cleanly.
    if role_name == ROLE_DRIVER:
        # The Driver role's auth-tier id-resolves leg fires first.
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
    else:
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


@pytest.mark.parametrize("role_name,id_value", [
    (ROLE_COMPANY_OPERATOR, "operator-id-not-resolving-here"),
    (ROLE_DRIVER, str(uuid4())),
    (ROLE_TEST_HARNESS, "test-harness-z"),
])
def test_non_regulator_cannot_approve_company(
    api,
    submitted_company: Dict,
    role_name: str,
    id_value: str,
):
    """The ``POST /v1/companies/{company_id}/approve`` endpoint's
    RBAC cell is regulator-only; an operator's, a driver's, or a
    test-harness role's request is the priority-200 default-deny
    case.

    For the operator-and-driver entity-backed roles, the
    auth-tier priority-110 id-resolves leg fires first if the
    ``X-User-ID`` does not resolve to a row of the identity-entity
    type, so we send a non-resolving id deliberately and assert the
    auth-tier error.  The test-harness opaque-identity role hits
    the priority-200 RBAC default-deny cleanly.

    The submitted-company fixture provides the path-id of an
    existing SUBMITTED company so the existence-tier check
    succeeds before the RBAC tier fires.
    """
    company_id = submitted_company["id"]
    headers = build_user_headers(id_value, role_name)
    resp = api.approve_company(company_id, {}, headers)
    if role_name in (ROLE_COMPANY_OPERATOR, ROLE_DRIVER):
        # The entity-backed-id-resolves auth leg fires first on a
        # non-resolving id.  For the CompanyOperator role with a
        # non-UUID id, the resolution fails and ``ERR_UNAUTHENTICATED``
        # is returned.  An operator whose id IS a real
        # TransportCompany row's id but doesn't equal the path's
        # ``{company_id}`` would be the cross-tenant 403 case
        # tested below; here we test the bare auth-leg with a
        # non-resolving id.
        # The CompanyOperator's RBAC cell on this endpoint is
        # default-deny, so once the priority-110 auth leg passes
        # the priority-200 RBAC tier fires.  Two valid PRD readings
        # for the non-resolving-operator-id-on-a-regulator-only
        # endpoint case (priority 110 vs 200) coexist, so we accept
        # either rejection.
        from prd_bench_local_runner.testing import validate_error_is_one_of

        actual = validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_UNAUTHENTICATED.value, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value],
        )
        assert actual in {ApiErrorId.ERR_UNAUTHENTICATED.value, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value}
    else:
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


def test_test_harness_role_denied_business_endpoint(api, approved_company: Dict):
    """The ``TestHarness`` role's allow-set is the two test-mode
    endpoints (and the two admin affordances).  Any business-logic
    endpoint hit by a TestHarness-role request is the priority-200
    default-deny ``ERR_ROLE_NOT_PERMITTED`` 403."""
    th_headers = test_harness_headers()
    resp = api.get_company(approved_company["id"], th_headers)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


def test_company_operator_cannot_run_clock_advance(api):
    """The mirror-image case: the operator role's RBAC cell on the
    two test-mode endpoints is the default-deny.  A
    ``CompanyOperator``-headers request to ``POST /v1/_clock/advance``
    is the priority-200 ``ERR_ROLE_NOT_PERMITTED`` 403.

    The operator's ``X-User-ID`` here is a bootstrap-identifier
    that doesn't resolve to a TransportCompany row, but the
    test-mode endpoints' allow-set is the singleton
    ``{"TestHarness"}`` so the role-deny fires regardless of the
    id-resolves question.  Two PRD-faithful implementations
    disagree on whether the auth-tier's priority-110 id-resolves
    leg or the priority-200 RBAC default-deny fires first on this
    case (the entity-backed-id-resolves leg arguably applies
    universally, but the test-mode endpoint's "any X-User-ID-string
    is fine as long as the role is TestHarness" opaque-identity
    contract complicates the question), so the test admits either
    answer.
    """
    bogus_operator_id = "co-bootstrap-no-row-" + uuid4().hex
    headers = build_user_headers(bogus_operator_id, ROLE_COMPANY_OPERATOR)
    resp = api.advance_clock(0.0, run_sweep_after_advance=False, headers=headers)
    # The CompanyOperator role's RBAC cell on /_clock/advance is the
    # default-deny so the canonical error is ``ERR_ROLE_NOT_PERMITTED``.
    # An entity-backed-id-resolves auth-tier failure on the
    # bootstrap-id ``X-User-ID`` would also be PRD-consistent
    # (the priority-110 leg fires for every entity-backed role
    # regardless of the endpoint), so we accept either error.
    from prd_bench_local_runner.testing import validate_error_is_one_of

    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, ApiErrorId.ERR_UNAUTHENTICATED.value],
    )


# ─── Cross-tenant 403 — priority 530 on the operator side ──────────────


def test_operator_cannot_read_other_companys_row(api, two_tenants: TwoTenantScenario):
    """PRD §2.6: "The cross-tenant predicate fires when the resolved
    owning tenant id is non-null and does not equal the requesting
    operator's ``X-User-ID``, and the failure code is
    ``ERR_CROSS_TENANT_ACCESS`` at HTTP status 403".

    Tenant-A's operator hits tenant-B's company row.  The existence
    tier passes (the row exists), the RBAC tier passes (the
    operator role is allowed on the get-company endpoint in
    general), and the priority-530 cross-tenant predicate fires
    because the operator's ``X-User-ID`` is tenant-A's company id,
    not tenant-B's.
    """
    sa = two_tenants.tenant_a
    sb = two_tenants.tenant_b
    a_op_headers = company_operator_headers(sa.company["id"])
    resp = api.get_company(sb.company["id"], a_op_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_operator_cannot_read_other_companys_permit(api, two_tenants: TwoTenantScenario):
    """The cross-tenant predicate's transitive-ownership variant:
    ``GET /v1/permits/{permit_id}`` for a permit whose
    ``company_id`` is the other tenant's company.  The same
    priority-530 ``ERR_CROSS_TENANT_ACCESS`` 403 fires."""
    sa = two_tenants.tenant_a
    sb = two_tenants.tenant_b
    a_op_headers = company_operator_headers(sa.company["id"])
    assert sb.permit is not None, "the two-tenants fixture must produce both an ACTIVE permit per tenant"
    resp = api.get_permit(sb.permit["id"], a_op_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_operator_cannot_read_other_companys_driver(api, two_tenants: TwoTenantScenario):
    """The cross-tenant predicate's per-Driver variant.  Tenant-A's
    operator hits tenant-B's driver.  The transitive ownership is
    on the driver's ``company_id`` foreign key per the PRD's §2.6's
    "a Driver's owning tenant is the driver's ``company_id``"."""
    sa = two_tenants.tenant_a
    sb = two_tenants.tenant_b
    a_op_headers = company_operator_headers(sa.company["id"])
    resp = api.get_driver(sb.drivers[0]["id"], a_op_headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_operator_list_companies_with_other_tenant_filter_is_403(api, two_tenants: TwoTenantScenario):
    """PRD §3.1 last paragraph + §2.6: "the operator's list call
    enforces a stricter convention: an absent ``company_id`` is the
    implicit-self default and the response is the operator's own
    … while a present ``company_id`` that does not equal the
    operator's ``X-User-ID`` is rejected with
    ``ERR_CROSS_TENANT_ACCESS`` 403 rather than being silently
    rewritten to the operator's-own filter".

    Tenant-A's operator passes the ``company_id`` query parameter
    set to tenant-B's id and gets the cross-tenant 403 rather than
    a silently-narrowed-to-self response.
    """
    sa = two_tenants.tenant_a
    sb = two_tenants.tenant_b
    a_op_headers = company_operator_headers(sa.company["id"])
    resp = api.list_companies(a_op_headers, params={"company_id": sb.company["id"]})
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


# ─── Cross-tenant 403 — priority 531 driver-self-only variant ─────────


def test_driver_cannot_read_other_drivers_row(api, qualified_carrier: HazmatScenario):
    """PRD §2.6 driver-self-only paragraph: "The Driver role has its
    own self-only variant of the predicate (priority 531 in the
    validation ordering): a Driver-role request whose ``X-User-ID``
    does not match the addressed Driver row's ``id`` … is the same
    ``ERR_CROSS_TENANT_ACCESS`` 403, with the meaning generalized
    from 'wrong company' to 'wrong individual identity'".

    Create a second driver under the same company so the existence
    tier on the second driver-row resolves.  The first driver's
    role-headers (``X-User-ID = drivers[0].id``) hitting
    ``GET /v1/drivers/{drivers[1].id}`` is the self-only-mismatch
    rejection.
    """
    scenario = qualified_carrier
    # Add a second driver so the existence-tier check on the
    # second-driver path passes.
    drv2 = setup_driver_under_company(api, scenario.company, attest=True)
    self_headers_for_first = driver_headers(scenario.drivers[0]["id"])
    resp = api.get_driver(drv2["id"], self_headers_for_first)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_driver_can_read_own_row(api, qualified_carrier: HazmatScenario):
    """The companion happy-path for the self-only predicate: a
    Driver-role request whose ``X-User-ID`` equals the path's
    ``{driver_id}`` is allowed (the priority-531 check's
    pass-the-predicate branch).
    """
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    self_headers = driver_headers(drv["id"])
    resp = api.get_driver(drv["id"], self_headers)
    data = validate_success(resp, 200)
    assert data["id"] == drv["id"]


def test_driver_cannot_read_other_drivers_penalty_summary(api, qualified_carrier: HazmatScenario):
    """PRD §3.8's penalty-summary endpoint's RBAC cell pins the
    self-only-on-Driver-role constraint with the same
    priority-531 error id.

    The ``regulator`` access on the same endpoint is the
    cross-tenant-exempt all-driver view; the operator's access is
    the parent-company-id-equals-operator-id check.
    """
    scenario = qualified_carrier
    drv2 = setup_driver_under_company(api, scenario.company, attest=True)
    self_headers_for_first = driver_headers(scenario.drivers[0]["id"])
    resp = api.get_driver_penalty_summary(drv2["id"], self_headers_for_first)
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value, expected_status=403)


def test_driver_can_read_own_penalty_summary(api, qualified_carrier: HazmatScenario):
    """The happy path of the penalty-summary self-only check."""
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    self_headers = driver_headers(drv["id"])
    resp = api.get_driver_penalty_summary(drv["id"], self_headers)
    summary = validate_success(resp, 200)
    assert summary["driver_id"] == drv["id"]


# ─── Regulator's cross-tenant exemption ────────────────────────────────


def test_regulator_can_read_any_companys_row(api, two_tenants: TwoTenantScenario):
    """PRD §2.1 regulator paragraph: "the regulator is exempt from
    the cross-tenant ownership predicate and reads every row in the
    system regardless of the row's owning tenant, in line with the
    regulatory-mandate cross-tenant exemption".

    A single regulator-headers principal reads tenant-A's company
    and tenant-B's company in two consecutive calls and both succeed
    with the 200 envelope.
    """
    reg = regulator_headers()
    a = two_tenants.tenant_a.company
    b = two_tenants.tenant_b.company
    ra = validate_success(api.get_company(a["id"], reg), 200)
    rb = validate_success(api.get_company(b["id"], reg), 200)
    assert ra["id"] == a["id"]
    assert rb["id"] == b["id"]
    assert ra["id"] != rb["id"]


def test_regulator_global_company_list_unfiltered_returns_all_tenants(
    api,
    two_tenants: TwoTenantScenario,
):
    """The regulator's list-companies call without the ``company_id``
    filter returns the global cross-tenant list, per PRD §2.6's
    list-endpoint paragraph: "the regulator's list call accepts the
    ``company_id`` filter as a narrowing parameter — present and
    matching one tenant's id, the list is that tenant's rows;
    absent, the list is the global cross-tenant set".

    The autoreset between tests means the two tenant-rows from the
    fixture are the only rows in the system, so the list has
    exactly two entries.
    """
    reg = regulator_headers()
    resp = api.list_companies(reg, params={"limit": 100})
    from test_helpers import validate_paginated as vp

    data, meta = vp(resp)
    ids_in_list = {c["id"] for c in data}
    assert two_tenants.tenant_a.company["id"] in ids_in_list
    assert two_tenants.tenant_b.company["id"] in ids_in_list


def test_test_harness_role_allow_set_is_clock_and_sweep_only(api):
    """PRD §2.1: "the role's allow-set is exactly the two test-mode
    endpoints ``POST /v1/_clock/advance`` and ``POST /v1/_sweep/run``
    covered in §2.5".

    The test-harness role can drive both of those.  A clock-advance
    by zero seconds returns the pre-and-post-clock ISO timestamps
    and the structure-summary fields the PRD's §2.5 declares.
    """
    th = test_harness_headers()
    # The clock-advance endpoint returns the structured payload.
    resp_advance = api.advance_clock(0.0, run_sweep_after_advance=False, headers=th)
    data = validate_success(resp_advance, 200)
    # The two timestamp fields are present.
    assert "prior_now" in data and "new_now" in data
    # Sweep call also succeeds.
    resp_sweep = api.run_sweep(scope="ALL", headers=th)
    sw = validate_success(resp_sweep, 200)
    assert "as_of_now" in sw
    assert sw.get("scope") == "ALL"


def test_unknown_role_name_rejected_at_auth_tier(api):
    """The four canonical role-name strings from PRD §2.1 are
    ``CompanyOperator``, ``RegulatorOfficer``, ``Driver``,
    ``TestHarness``.  Any other string in the ``X-User-Role`` header
    is the priority-100 auth-tier rejection ``ERR_UNAUTHENTICATED``
    (the "role name outside the four canonical strings is rejected
    at the top of the validation pipeline" clause).
    """
    bad = {"X-User-ID": "x", "X-User-Role": "GhostAdmin"}
    resp = api.get_company(NON_EXISTENT_UUID_LOCAL, bad)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_operator_self_company_id_filter_is_allowed_match(api, qualified_carrier: HazmatScenario):
    """The companion of the cross-tenant-403-on-mismatch case: when
    the operator's ``company_id`` filter equals their own
    ``X-User-ID``, the list call succeeds with a one-row response
    containing their own company.  The PRD's §2.6 first-list-paragraph
    pins the implicit-self default as the absent-filter case and
    the matching-explicit-filter as the same single-row outcome.
    """
    op = company_operator_headers(qualified_carrier.company["id"])
    resp = api.list_companies(op, params={"company_id": qualified_carrier.company["id"]})
    from test_helpers import validate_paginated as vp

    data, meta = vp(resp)
    assert len(data) == 1
    assert data[0]["id"] == qualified_carrier.company["id"]
