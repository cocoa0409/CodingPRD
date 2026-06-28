"""RBAC denials, paginated list endpoints, optimistic-concurrency success,
scheduled feeding-plan activation, overdue flagging, and immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_field_tech_headers,
    make_customer_owner_headers,
    setup_active_system_with_tech,
    create_active_contract_with_system,
    create_started_visit,
    create_completed_visit,
    TEST_USERS,
)
from test_helpers.fixtures import create_contract, create_system
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. X-User-ID identifies the acting user, and X-User-Role
    declares the operational capacity under which they are acting. If either
    header is missing or malformed, the request is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.get_contract(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_fieldtech_cannot_book_visit_forbidden_role(api):
    """PRD §2.1: "When a request carries valid headers but the acting role is not
    permitted to invoke the targeted endpoint, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §4: booking a visit (POST /aquatics/visits) is authorized for Dispatcher.

    Design: Corner/rbac/fieldtech_cannot_book_visit_forbidden_role
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    resp = api.create_visit(
        f.create_visit_payload(base["system"]["id"], base["technician"]["id"],
                               base["system"]["version"],
                               scheduled_start="2026-03-06T09:00:00Z",
                               scheduled_end="2026-03-06T10:00:00Z"),
        make_field_tech_headers("tech-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_non_owner_customer_cannot_dispute_visit(api):
    """PRD §2.1: "When a CustomerOwner disputes a visit, approves an install, or
    cancels a feeding plan, the acting X-User-ID must equal the customer_user_id
    of the ServiceContract that owns the underlying system or project; if it does
    not, the request is rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/non_owner_customer_cannot_dispute_visit
    """
    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-03-07T09:00:00Z",
                                  scheduled_end="2026-03-07T10:00:00Z")
    # owner-2 does not own this contract.
    resp = api.dispute_visit(base["visit"]["id"], make_customer_owner_headers("owner-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Endpoints / pagination
# ---------------------------------------------------------------------------
def test_list_systems_under_contract_paginated(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."
    PRD §4: GET /aquatics/contracts/{id}/systems lists systems under a contract.

    Design: Corner/endpoints/list_systems_under_contract_paginated
    """
    contract = create_contract(customer_user_id="owner-1")
    create_system(contract["id"], system_kind="FRESHWATER", nominal_volume_l=200, label="S1")
    create_system(contract["id"], system_kind="POND", nominal_volume_l=5000, label="S2")

    resp = api.list_systems_under_contract(contract["id"], AM)
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"Expected 2 systems, got {len(data)}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_water_tests_list_default_pagination(api):
    """PRD §2.3: "The limit parameter sets the maximum number of items returned;
    it defaults to 10 when omitted ... Every list response includes limit, offset,
    total_count, and has_more in the meta object of the envelope."

    Design: Corner/endpoints/water_tests_pagination_default_limit
    """
    base = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                nominal_volume_l=200,
                                scheduled_start="2026-03-04T09:00:00Z",
                                scheduled_end="2026-03-04T10:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    validate_success(api.create_water_test(
        base["visit"]["id"],
        f.create_water_test_payload(parameter="NITRATE", measured_value=20,
                                    target_value=5, product_strength_ppm_per_ml=10),
        tech_headers), expected_status=201)

    resp = api.list_water_tests(base["visit"]["id"], tech_headers)
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"Expected 1 water test, got {len(data)}"
    assert meta["total_count"] == 1
    assert meta["limit"] == 10, f"Expected default limit 10, got {meta['limit']}"


# ---------------------------------------------------------------------------
# Cross-cutting complexity layers
# ---------------------------------------------------------------------------
def test_booking_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "On a successful booking, the target SystemProfile.version
    increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    before_version = base["system"]["version"]

    visit = api.create_visit(
        f.create_visit_payload(system_id, base["technician"]["id"], before_version,
                               scheduled_start="2026-03-08T09:00:00Z",
                               scheduled_end="2026-03-08T10:00:00Z"),
        DISP)
    validate_success(visit, expected_status=201)

    system = validate_success(api.get_system(system_id, AM))
    assert system["version"] == before_version + 1, (
        f"Expected version {before_version + 1}, got {system['version']}")


def test_feeding_plan_activates_when_clock_reaches_window(api):
    """PRD §3.11: "When the clock reaches a plan's window_start and the plan's home
    SystemProfile is ACTIVE, the plan moves SCHEDULED → ACTIVE".
    PRD §3.11: "advancing it auto-evaluates every scheduled feeding plan,
    activating those whose window_start has been reached".

    Design: Corner/cross_cutting_complexity_layers/feeding_plan_scheduled_activates_when_clock_reaches_window
    """
    base = create_active_contract_with_system(service_tier="BASIC",
                                              customer_user_id="owner-1",
                                              nominal_volume_l=200)
    owner_headers = make_customer_owner_headers("owner-1")
    plan = validate_success(api.create_feeding_plan(
        f.create_feeding_plan_payload(base["system"]["id"],
                                      window_start="2026-07-01T00:00:00Z",
                                      window_end="2026-07-10T00:00:00Z",
                                      feedings_per_day=2),
        owner_headers), expected_status=201)
    assert plan["status"] == "SCHEDULED"

    validate_success(api.set_clock("2026-07-02T00:00:00Z", AM))
    refreshed = validate_success(api.get_feeding_plan(plan["id"], owner_headers))
    assert refreshed["status"] == "ACTIVE", (
        f"Expected ACTIVE after clock reaches window_start, got {refreshed['status']}")


def test_visit_complete_balance_visible_immediately(api):
    """PRD §2.10: "This balance is recomputed on every invoice mutation —
    creation, voiding, or payment — so that suspending, reactivating, and
    terminating decisions always read a current figure."

    A BASIC visit completed at 30 minutes issues a 6000-cent invoice; the
    contract balance reads 6000 immediately on the next GET.

    Design: Corner/consistency_model/visit_complete_balance_visible_same_response_chain
    """
    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-03-09T09:00:00Z",
                                  scheduled_end="2026-03-09T10:00:00Z")
    contract = validate_success(api.get_contract(base["contract"]["id"], AM))
    assert contract["account_balance_cents"] == 6000, (
        f"Expected balance 6000 immediately after completion, got "
        f"{contract['account_balance_cents']}")
