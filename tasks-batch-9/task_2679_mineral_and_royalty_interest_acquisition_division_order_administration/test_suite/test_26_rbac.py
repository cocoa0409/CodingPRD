"""Role denial, owner-bound identity, authentication and segregation of duties."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import ROLE_TITLE_ANALYST
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    MANAGER_HEADERS,
    OPERATOR_ALT_HEADERS,
    headers_without_user_id,
    make_headers,
    make_royalty_owner_headers,
)


def test_a_title_analyst_may_not_carve_a_mineral_interest(api):
    """Carving is the acquisition manager's exclusive act; only the role differs.

    PRD: "3. The acting role is authorised for the target operation — otherwise
    `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/title_analyst_cannot_create_a_mineral_interest_returns_403
    """
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    payload = f.mineral_interest_payload(tract["id"], owner["id"])

    denied = api.create_mineral_interest(payload, ANALYST_HEADERS)

    validate_error(denied, "ERR_UNAUTHORIZED", 403)
    _items, meta = validate_paginated(
        api.list_mineral_interests(MANAGER_HEADERS, {"tract_id": tract["id"]})
    )
    assert meta["total_count"] == 0

    allowed = validate_success(api.create_mineral_interest(payload, MANAGER_HEADERS), 201)
    assert allowed["tract_id"] == tract["id"]


def test_the_role_gate_fires_before_the_chain_completeness_gate(api):
    """A division-order admin certifying an empty chain sees 403, not 409.

    PRD: "When more than one rule could reject a request, the rule that fires is
    always the lowest-numbered rule in the ladder below, and the client sees that
    rule's error and status."

    Design: Corner/rbac/division_order_admin_cannot_certify_title_returns_403
    """
    tract = fx.create_tract(api)
    assert tract["version"] == 1

    denied = api.certify_title(tract["id"], ADMIN_HEADERS)

    validate_error(denied, "ERR_UNAUTHORIZED", 403)
    unchanged = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert unchanged["title_status"] == "RESEARCH"
    assert unchanged["chain_entry_count"] == 0
    assert unchanged["version"] == 1


def test_one_owner_cannot_accept_another_owners_offer(api):
    """The identity rung binds the acceptance to the interest's seller_owner_id.

    PRD: "4. Owner-bound and operator-bound identity match — otherwise
    `ERR_NOT_RESOURCE_OWNER` (403). This rung guards exactly eight operations: an
    owner countering an offer, an owner accepting an offer, an owner rejecting an
    offer, an owner submitting a cure, an operator exercising a pugh release, an
    operator terminating an allocation, an operator responding to a division order,
    and an operator correcting a disputed division order."

    Design: Corner/rbac/royalty_owner_cannot_accept_another_owners_offer_returns_403
    """
    world = fx.offer_ready(api)
    stranger = fx.create_owner(api, legal_name="D Heir", mailing_address="2 Pecos Rd, Pecos TX")

    denied = api.accept_offer_letter(
        world["offer"]["id"], make_royalty_owner_headers(stranger["id"])
    )

    validate_error(denied, "ERR_NOT_RESOURCE_OWNER", 403)
    letter = fx.read_offer(api, world["offer"]["id"])
    assert letter["offer_status"] == "SENT"
    assert letter["accepted_at"] is None
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "OFFERED"


def test_the_seller_of_record_accepts_their_own_offer(api):
    """The same call from the interest's own owner lands the acceptance.

    PRD: "It sets `offer_status` to `ACCEPTED` and stamps `accepted_at` with the
    logical-clock instant."

    Design: Corner/rbac/royalty_owner_cannot_accept_another_owners_offer_returns_403
    """
    world = fx.offer_ready(api)

    accepted = fx.accept_offer(api, world["offer"]["id"], world["owner"]["id"])

    assert accepted["offer_status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None


def test_a_foreign_operator_cannot_terminate_the_allocation(api):
    """op-user-002 is not the unit's operator of record, so the acreage stays out.

    PRD: "On creation the unit's `unallocated_acres` is set equal to
    `unit_gross_acres`, its `active_allocation_count` is 0, and its
    `operator_user_id` is stamped from the creating `X-User-ID` — the identifier
    every later operator action on this unit, on its allocations and on its division
    orders must present."

    Design: Corner/rbac/operator_cannot_terminate_another_operators_allocation_returns_403
    """
    world = fx.unit_with_allocation_ready(api)

    denied = api.terminate_allocation(
        world["allocation"]["id"],
        f.terminate_allocation_payload(termination_reason="Attempted by a foreign operator"),
        OPERATOR_ALT_HEADERS,
    )

    validate_error(denied, "ERR_NOT_RESOURCE_OWNER", 403)
    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["allocation_status"] == "ACTIVE"
    assert allocation["termination_reason"] is None
    unit = fx.read_unit(api, world["unit"]["id"])
    assert float(unit["unallocated_acres"]) == 960.0
    assert unit["active_allocation_count"] == 1

    allowed = fx.terminate_allocation(api, world["allocation"]["id"])
    assert allowed["allocation_status"] == "TERMINATED"


def test_a_request_without_an_identity_is_unauthenticated(api):
    """A missing header, an empty header and an undeclared role are all 401.

    PRD: "1. `X-User-ID` present and non-empty — otherwise `ERR_UNAUTHENTICATED`
    (401)."

    PRD: "2. `X-User-Role` present and one of the six declared roles — otherwise
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/request_without_a_user_id_header_returns_401
    """
    payload = f.tract_payload(operator_activity_tier=f.OMIT)

    missing = api.create_tract(payload, headers_without_user_id(ROLE_TITLE_ANALYST))
    empty = api.create_tract(payload, make_headers("", ROLE_TITLE_ANALYST))
    undeclared = api.create_tract(payload, make_headers("ta-user-001", "Auditor"))

    validate_error(missing, "ERR_UNAUTHENTICATED", 401)
    validate_error(empty, "ERR_UNAUTHENTICATED", 401)
    validate_error(undeclared, "ERR_UNAUTHENTICATED", 401)

    _items, meta = validate_paginated(api.list_tracts(ANALYST_HEADERS))
    assert meta["total_count"] == 0


def test_the_admin_who_issued_the_order_may_not_release_its_money(api):
    """Disbursement is segregated from issuance, so do-user-001 is refused.

    PRD: "26. (Priority 51) Segregation of duties on disbursement — otherwise
    `ERR_SEGREGATION_OF_DUTIES` (403). Guards suspense release."

    Design: Corner/rbac/suspense_release_by_the_order_creator_returns_403
    """
    world = fx.variance_held_ready(api)

    denied = api.release_suspense(world["suspense"]["id"], ADMIN_HEADERS)

    validate_error(denied, "ERR_SEGREGATION_OF_DUTIES", 403)
    account = fx.read_suspense(api, world["suspense"]["id"])
    assert account["suspense_status"] == "ACCRUING"
    assert_money(account["accrued_amount"], "106.47", "accrued_amount")
    assert account["released_by_user_id"] is None


def test_a_second_admin_releases_the_held_revenue(api):
    """do-user-002 pays the 106.47 out and the order re-opens at that total.

    PRD: "On success `months_held`, `interest_accrued` and `release_amount` are
    recomputed against the logical clock, `suspense_status` moves
    `ACCRUING → RELEASED`, `released_by_user_id` is stamped from the acting
    `X-User-ID`, and `accrued_amount` and `held_detail_count` are zeroed to 0.00 and
    0."

    Design: Corner/rbac/suspense_release_by_the_order_creator_returns_403
    """
    world = fx.variance_held_ready(api)

    released = validate_success(
        api.release_suspense(world["suspense"]["id"], ADMIN_ALT_HEADERS), 200
    )

    assert released["suspense_status"] == "RELEASED"
    assert released["released_by_user_id"] == "do-user-002"
    assert_money(released["accrued_amount"], "0.00", "accrued_amount")
    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "EXECUTED"
    assert_money(order["paid_net_total"], "106.47", "paid_net_total")
