"""Role-based authorization denials and optimistic-concurrency on the
incident aggregate (IAP and cost-record creates).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_jurisdiction,
    create_iap,
    create_cost_record,
    incident_version,
    create_iap_payload,
    create_cost_record_payload,
    create_incident_payload,
    make_jurisdiction_liaison_headers,
)

EOC = TEST_USERS["eoc_manager_headers"]
OPS = TEST_USERS["operations_chief_headers"]
PLAN = TEST_USERS["planning_chief_headers"]
FIN = TEST_USERS["finance_chief_headers"]


# ─── Corner: rbac / operations_chief_cannot_create_resource_pool ───
def test_operations_chief_cannot_create_pool(api):
    """PRD §2.1: "If the header is present and valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/operations_chief_cannot_create_resource_pool
    """
    jur = create_jurisdiction(name="RBAC Owner")
    validate_error(
        api.create_resource_pool(
            {"jurisdiction_id": jur["id"], "resource_type": "VEHICLE", "total_units": 4}, OPS
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


# ─── Corner: rbac / liaison_cannot_create_incident ───
def test_liaison_cannot_create_incident(api):
    """PRD §2.1: "If the header is present and valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/liaison_cannot_create_incident
    """
    jur = create_jurisdiction(name="Liaison Home")
    headers = make_jurisdiction_liaison_headers(jur["id"])
    validate_error(
        api.create_incident(create_incident_payload(name="Illegal", hazard_type="FLOOD"), headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


# ─── Corner: cross_cutting_complexity_layers / occ_stale_iap_create_conflict ───
def test_stale_incident_version_blocks_iap_create(api):
    """PRD §2.6: "If that value does not equal the incident's current `version` — because
    another writer has advanced it since the client last read it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_iap_create_conflict
    """
    inc = create_activated_incident(name="OCC IAP Ctx", hazard_type="FLOOD")
    observed = incident_version(inc["id"])
    # IAP #1 create advances the incident version past `observed`.
    create_iap(
        inc["id"], expected_incident_version=observed,
        operational_period_start="2026-03-01T06:00:00Z", operational_period_end="2026-03-02T06:00:00Z",
    )
    stale_payload = create_iap_payload(
        inc["id"], observed,
        operational_period_start="2026-03-03T06:00:00Z", operational_period_end="2026-03-04T06:00:00Z",
    )
    validate_error(api.create_iap(stale_payload, PLAN), ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner: cross_cutting_complexity_layers / occ_stale_cost_record_create_conflict ───
def test_stale_incident_version_blocks_cost_record_create(api):
    """PRD §2.6: "creating a Cost Record requires `expected_incident_version` to match the
    incident's current `version`; because a new cost record grows the incident's committed-cost
    ledger and advances the incident `version`, a creator whose `expected_incident_version` no
    longer matches (another cost record already landed) is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_cost_record_create_conflict
    """
    inc = create_activated_incident(name="OCC Cost Ctx", hazard_type="WILDFIRE")
    observed = incident_version(inc["id"])
    create_cost_record(inc["id"], expected_incident_version=observed, category="LABOR", estimated_cost=100.00)
    stale_payload = create_cost_record_payload(
        inc["id"], observed, category="MATERIALS", estimated_cost=100.00
    )
    validate_error(api.create_cost_record(stale_payload, FIN), ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner: cross_cutting_complexity_layers / occ_fresh_version_iap_create_succeeds ───
def test_fresh_incident_version_allows_iap_create(api):
    """PRD §2.6: "Creating an Incident Action Plan requires the body to carry
    `expected_incident_version` holding the client's last observed `version` of the target
    incident."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_iap_create_succeeds
    """
    inc = create_activated_incident(name="OCC Fresh Ctx", hazard_type="FLOOD")
    v1 = incident_version(inc["id"])
    create_iap(
        inc["id"], expected_incident_version=v1,
        operational_period_start="2026-03-01T06:00:00Z", operational_period_end="2026-03-02T06:00:00Z",
    )
    v2 = incident_version(inc["id"])  # re-read after IAP #1 advanced the version
    fresh_payload = create_iap_payload(
        inc["id"], v2,
        operational_period_start="2026-03-03T06:00:00Z", operational_period_end="2026-03-04T06:00:00Z",
    )
    iap2 = validate_success(api.create_iap(fresh_payload, PLAN), expected_status=201)
    assert iap2["status"] == "DRAFT", f"fresh-version IAP create must succeed as DRAFT, got {iap2['status']}"
