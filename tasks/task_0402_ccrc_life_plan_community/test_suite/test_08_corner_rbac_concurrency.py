"""Corner (breadth) tests for RBAC, optimistic concurrency, and immediate
consistency.

Queue (B) corner-design instances from the `rbac`, `cross_cutting_complexity_layers`,
and `consistency_model` sections (PRD §2.1, §2.8, §3.2). The three
excluded_because stubs in cross_cutting are NOT translated; their assertions are
owned by the cited queue-(A) difficulty instances.
"""
from test_helpers import (
    create_community,
    create_resident,
    get_community,
    get_residency,
    setup_active_residency,
    AD,
    FO,
)
from test_helpers.api_client import api_client
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_care_transition_payload,
    create_community_payload,
    create_second_person_payload,
)
from test_helpers.test_users import (
    make_admissions_director_headers,
    make_care_coordinator_headers,
    make_resident_headers,
)


# ─── rbac / missing_auth_headers_returns_401 ────────────────────────────────

def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_AUTH`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api_client.create_community(
        create_community_payload(name="NoAuth", actuarial_discount_rate_bps=0),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ─── rbac / care_coordinator_cannot_create_community_returns_403 ────────────

def test_care_coordinator_cannot_create_community(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "The `FinanceOfficer` owns the financial and governance surface of the
    platform: creating communities".

    Design: Corner/rbac/care_coordinator_cannot_create_community_returns_403
    """
    resp = api_client.create_community(
        create_community_payload(name="Wrong", actuarial_discount_rate_bps=0),
        make_care_coordinator_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / admissions_director_cannot_propose_care_transition_returns_403 ──

def test_admissions_director_cannot_propose_care_transition(api):
    """PRD §2.1: "The `CareCoordinator` owns the care continuum and the health center:
    proposing, applying, and reverting care transitions".
    PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/admissions_director_cannot_propose_care_transition_returns_403
    """
    community = create_community(name="RbacT")
    plan = _plan(community["id"])
    resident = create_resident(community["id"], full_name="Rb R")
    residency = validate_success(api_client.create_residency(
        {"community_id": community["id"], "primary_resident_id": resident["id"],
         "contract_plan_id": plan["id"]}, make_admissions_director_headers(),
    ), expected_status=201)
    resp = api_client.create_care_transition(
        create_care_transition_payload(residency["id"], "ASSISTED"),
        make_admissions_director_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / resident_can_read_lists_shared_operation ────────────────────────

def test_resident_can_read_shared_list(api):
    """PRD §2.1: "A `Resident` may read community data and cast a council vote on
    behalf of their own active residency. All four roles may call the read-only list
    and get endpoints."

    Design: Corner/rbac/resident_can_read_lists_shared_operation
    """
    community = create_community(name="ReadT")
    resident = create_resident(community["id"], full_name="Rea R")
    resp = api_client.list_communities(make_resident_headers(resident["id"]))
    data = validate_success(resp)
    assert isinstance(data, list), "shared list read by Resident must return an array"


# ─── cross_cutting / occ_stale_version_on_terminate_returns_412 ─────────────

def test_terminate_with_stale_version_rejected(api):
    """PRD §2.8: "Both the activation operation and the termination operation require
    an `expected_residency_version` field in the request body that carries the
    client's last observed `version` of the target residency. This guard is evaluated
    before any state-machine precondition: if `expected_residency_version` does not
    equal the residency's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the state checks never run."
    PRD §3.4: "Adding the second person sets the residency's `has_second_person` to
    true and bumps the residency's `version` by one".

    Capture the post-activation version, add a second person (which bumps the live
    version), then terminate carrying the now-stale captured version → 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_terminate_returns_412
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="OccT",
        plan_overrides={"name": "Op", "second_person_fee_cents": 150_000},
    )
    stale_version = active["version"]
    validate_success(api_client.add_second_person(
        active["id"],
        create_second_person_payload(full_name="Spouse", date_of_birth="1931-01-01"),
        make_admissions_director_headers(),
    ), expected_status=201)
    resp = api_client.terminate_residency(
        active["id"],
        {"reason": "VOLUNTARY", "expected_residency_version": stale_version},
        make_admissions_director_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── consistency_model / reserve_credit_visible_in_same_request_immediate ───

def test_reserve_credit_visible_immediately_after_activation(api):
    """PRD §3.2: "The frozen entrance fee is simultaneously booked into the
    community's reserve: the community's `reserve_assets_cents` is increased by the
    residency's `entrance_fee_paid_cents`."

    With reserve_assets 0 and a plan entrance_fee 5_000_000, a GET on the community
    right after activation reflects reserve_assets_cents == 5_000_000 (immediate
    consistency).

    Design: Corner/consistency_model/reserve_credit_visible_in_same_request_immediate
    """
    community, _plan, _unit, _active = setup_active_residency(
        community_name="Immed",
        reserve_assets_cents=0,
        plan_overrides={
            "name": "Imp", "contract_type": "TYPE_C",
            "entrance_fee_cents": 5_000_000, "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 300_000, "second_person_fee_cents": 0,
        },
    )
    fresh = get_community(community["id"])
    assert fresh["reserve_assets_cents"] == 5_000_000, (
        f"reserve must reflect the booked entrance fee immediately, "
        f"got {fresh['reserve_assets_cents']}"
    )


def _plan(community_id):
    from test_helpers import create_plan
    return create_plan(community_id, name="Rp", second_person_fee_cents=0)
