"""Business validations, RBAC denials, agency-scope isolation, authentication,
fair-share rejection, pagination, and reverse-reachability listing.

Covers Corner queue sections validations, endpoints, rbac, and the
fair-share entry of section errors.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated, build_user_headers,
)
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, fixtures, factories,
    make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------

def test_agency_suspended_blocks_order_submission(api):
    """PRD §3.5: "Submission is refused if the ordering agency's status is
    SUSPENDED (ERR_AGENCY_SUSPENDED)"
    PRD §3.2: "a suspended agency cannot submit or have orders approved."

    Design: Corner/validations/agency_suspended_blocks_order_submission
    """
    agency = fixtures.create_agency()
    validate_success(api.update_agency(agency["id"], {"status": "SUSPENDED"}, MGR))
    # PRD §3.4: opening a cycle requires at least one ACTIVE agency. The agency
    # under test is SUSPENDED, so a second ACTIVE agency must exist to satisfy
    # the open precondition before submission is attempted.
    fixtures.create_agency(name="Active Pantry", service_area="County-Active")
    cycle = fixtures.create_open_cycle()
    resp = api.create_agency_order(
        factories.create_agency_order_payload(
            agency["id"], cycle["id"],
            lines=[{"food_category": "PRODUCE", "requested_lbs": 100}]),
        make_agency_coordinator_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_AGENCY_SUSPENDED.value)


def test_over_distribution_finalize_rejected(api):
    """PRD §3.7: "Finalizing a PACKED event requires the operator-recorded
    actual_distributed_lbs, which must be zero or greater and must not exceed the
    event's planned_lbs — handing out more than was packed is rejected with
    ERR_OVER_DISTRIBUTION."

    Design: Corner/validations/over_distribution_finalize_rejected
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    resp = api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 250},
        make_agency_coordinator_headers(agency_id))
    validate_error(resp, ApiErrorId.ERR_OVER_DISTRIBUTION.value)


def test_cold_chain_mismatch_alone_on_intake(api):
    """PRD §2.5: "frozen meat requires FROZEN"
    PRD §2.5: "At intake, the derived required_temp_zone must equal the holding
    unit's temp_zone; a mismatch is rejected with ERR_COLD_CHAIN_MISMATCH."

    Design: Corner/validations/cold_chain_mismatch_alone_on_intake
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    resp = api.create_inventory_lot(
        {"cold_storage_unit_id": unit["id"], "food_category": "FROZEN_MEAT",
         "source_type": "PURCHASED", "intake_lbs": 50,
         "expiration_date": "2026-09-01T00:00:00.000Z", "unit_cost_cents": 300},
        OP)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_MISMATCH.value)


def test_fair_share_exceeded_on_over_cap_order(api):
    """PRD §3.4: "an order whose requested_lbs would push the agency's drawn
    poundage strictly above the cap is rejected with ERR_FAIR_SHARE_EXCEEDED,
    while an order landing exactly at the cap is allowed."

    Design: Corner/errors/fair_share_exceeded_on_over_cap_order
    """
    agency_a = fixtures.create_agency(name="Agency A", service_area="County-A", fair_share_weight=3)
    fixtures.create_agency(name="Agency B", service_area="County-B", fair_share_weight=1)
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=20000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=9000,
                                        expiration_date="2026-09-01T00:00:00.000Z")
    cycle = fixtures.create_open_cycle(total_pool_lbs=10000)
    # cap A = floor(10000*3/4) = 7500; request 7501 exceeds.
    order = fixtures.submit_order(
        agency_a["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 7501}])
    resp = api.approve_agency_order(order["id"], {"expected_lot_version": lot["version"]}, MGR)
    validate_error(resp, ApiErrorId.ERR_FAIR_SHARE_EXCEEDED.value)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_list_inventory_lots_pagination_envelope(api):
    """PRD §2.3: "limit caps the number of items returned: it defaults to 10, with
    a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response echoes limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Design: Corner/endpoints/list_inventory_lots_pagination_envelope
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    for i, exp in enumerate(["2026-07-01", "2026-07-02", "2026-07-03"]):
        fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                      intake_lbs=10 * (i + 1),
                                      expiration_date=f"{exp}T00:00:00.000Z")
    resp = api.list_inventory_lots(OP, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"limit=2 should return at most 2 items, got {len(data)}"
    assert meta["total_count"] == 3, f"total_count should be 3, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more should be True, got {meta['has_more']}"


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_VALIDATION_PAGINATION."

    Design: Corner/endpoints/pagination_limit_over_max_rejected
    """
    resp = api.list_agencies(MGR, params={"limit": 101, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_order_lines_reverse_reachability_lists_reserved_lines(api):
    """PRD §2.6: "the order lines under an order or against a lot" are reachable
    through a parent resource's path.
    PRD §3.5: "its reserved_lot_id is set to the single FEFO-earliest lot it
    reserved against (the one consumed first)"

    Design: Corner/endpoints/order_lines_reverse_reachability_lists_reserved_lines
    """
    ctx = fixtures.setup_approved_order(requested_lbs=120, intake_lbs=300)
    resp = api.list_lot_order_lines(ctx["lot"]["id"], MGR)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"one line reserved against the lot, got {len(data)}"
    assert data[0]["reserved_lot_id"] == ctx["lot"]["id"], \
        f"line should point to the lot, got {data[0]['reserved_lot_id']}"
    assert data[0]["reserved_lbs"] == 120.00, \
        f"reserved 120, got {data[0]['reserved_lbs']}"


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------

def test_agency_coordinator_cannot_approve_order(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: approve is authorized for AllocationManager only.

    Design: Corner/rbac/agency_coordinator_cannot_approve_order
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=300,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 100}])
    resp = api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]},
        make_agency_coordinator_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_coordinator_cannot_act_on_other_agency_order(api):
    """PRD §2.1: "An attempt to act on a resource owned by a different agency is
    rejected with ERR_AGENCY_SCOPE_VIOLATION."
    PRD §2.1: "an AgencyCoordinator may submit an order, cancel an order, register
    a household, or plan, pack, finalize, or void a distribution event only when
    the target resource belongs to the agency named by their X-User-ID."

    Design: Corner/rbac/coordinator_cannot_act_on_other_agency_order
    """
    agency_a = fixtures.create_agency(name="Agency A", service_area="County-A")
    agency_b = fixtures.create_agency(name="Agency B", service_area="County-B")
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency_a["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 100}])
    # coordinator acting as agency B tries to cancel agency A's order.
    resp = api.cancel_agency_order(
        order["id"], make_agency_coordinator_headers(agency_b["id"]))
    validate_error(resp, ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    X-User-Role value outside this set, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    stranger = build_user_headers("nobody-1", "Stranger")
    resp = api.list_agencies(stranger)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
