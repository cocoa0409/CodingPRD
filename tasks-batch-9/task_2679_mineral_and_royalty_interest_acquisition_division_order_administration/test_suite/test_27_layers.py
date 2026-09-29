"""Optimistic concurrency, version counters, decimal pinning and the escheat threshold."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_acreage,
    assert_decimal_interest,
    assert_money,
)
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    MANAGER_ALT_HEADERS,
    OPERATOR_HEADERS,
)

PUGH_UNIT = {"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}
LONG_ALLOCATION = {"effective_to": "2030-01-01"}


def test_papering_an_agreement_on_a_stale_interest_view_is_refused(api):
    """One version behind the interest of record is a 412, and nothing is papered.

    PRD: "Papering a purchase and sale agreement requires
    `expected_mineral_interest_version`, carrying the client's last observed `version`
    of the parent mineral interest. If it does not equal the interest's current
    `version`, the create is rejected with `ERR_STALE_INTEREST_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/psa_create_with_stale_interest_version_returns_412
    """
    world = fx.accepted_offer_ready(api)
    current = fx.interest_version(api, world["interest"]["id"])

    stale = api.create_psa(
        f.psa_payload(world["offer"]["id"], current - 1), MANAGER_ALT_HEADERS
    )

    validate_error(stale, "ERR_STALE_INTEREST_VERSION", 412)
    interest = fx.read_interest(api, world["interest"]["id"])
    assert interest["interest_status"] == "OFFERED"
    assert interest["version"] == current
    _psas, meta = validate_paginated(api.list_psas(MANAGER_ALT_HEADERS))
    assert meta["total_count"] == 0


def test_the_current_interest_view_papers_the_agreement(api):
    """At the version of record the agreement is EXECUTED at 48000.00.

    PRD: "The product legitimately allows a fresh agreement to be papered on an
    interest whose prior agreement terminated, so a second agreement is not inherently
    invalid; it is invalid only when the client's view of the interest — its
    valuation, its accepted offer, its acquisition posture — has been superseded."

    Design: Corner/cross-cutting complexity layers/psa_create_with_stale_interest_version_returns_412
    """
    world = fx.accepted_offer_ready(api)
    before = fx.interest_version(api, world["interest"]["id"])

    psa = fx.create_psa(api, world["interest"]["id"], world["offer"]["id"])

    assert psa["psa_status"] == "EXECUTED"
    assert psa["curative_status"] == "CURATIVE_OPEN"
    assert_money(psa["purchase_price"], "48000.00", "purchase_price")
    interest = fx.read_interest(api, world["interest"]["id"])
    assert interest["interest_status"] == "UNDER_PSA"
    assert interest["version"] > before


def test_issuing_an_order_on_a_stale_unit_view_is_refused(api):
    """The amendment that activated the pugh clause invalidated the client's version.

    PRD: "Issuing a division order requires `expected_unit_version`, carrying the
    client's last observed `version` of the parent unit. If it does not equal the
    unit's current `version`, the create is rejected with `ERR_STALE_UNIT_VERSION`
    (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/division_order_create_with_stale_unit_version_returns_412
    """
    world = fx.unit_with_allocation_ready(api)
    owner = fx.create_owner(api)
    interest = fx.create_interest(api, world["tract"]["id"], owner["id"])
    validate_success(api.update_unit(world["unit"]["id"], PUGH_UNIT, OPERATOR_HEADERS), 200)
    current = fx.unit_version(api, world["unit"]["id"])

    stale = api.create_division_order(
        f.division_order_payload(interest["id"], world["unit"]["id"], current - 1), ADMIN_HEADERS
    )

    validate_error(stale, "ERR_STALE_UNIT_VERSION", 412)
    _orders, meta = validate_paginated(
        api.list_division_orders(ADMIN_HEADERS, {"unit_id": world["unit"]["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.unit_version(api, world["unit"]["id"]) == current


def test_issuing_an_order_advances_the_parent_unit_version_by_one(api):
    """The order goes out at 0.00195313 and the unit's version steps by exactly one.

    PRD: "Issuing an order increments the unit's `version` by 1."

    Design: Corner/cross-cutting complexity layers/division_order_create_with_stale_unit_version_returns_412
    """
    world = fx.unit_with_allocation_ready(api)
    owner = fx.create_owner(api)
    interest = fx.create_interest(api, world["tract"]["id"], owner["id"])
    before = fx.unit_version(api, world["unit"]["id"])

    order = fx.create_division_order(api, interest["id"], world["unit"]["id"])

    assert order["do_status"] == "SENT"
    assert_decimal_interest(order["expected_decimal"], "0.00195313", "expected_decimal")
    assert fx.unit_version(api, world["unit"]["id"]) == before + 1


def test_reads_never_advance_a_version_counter(api):
    """A GET on the owner leaves the version exactly where the create left it.

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant
    with three fractional digits that is refreshed on every mutation, and `version`,
    an integer that starts at 1 on creation and increments by exactly 1 on each
    mutation of that row."

    Design: Corner/cross-cutting complexity layers/entity_version_increments_on_every_write
    """
    owner = fx.create_owner(api, tax_id_on_file=False)
    assert owner["version"] == 1

    read = validate_success(api.get_royalty_owner(owner["id"], ADMIN_HEADERS), 200)

    assert read["version"] == owner["version"]
    assert read["created_at"] == owner["created_at"]
    assert read["updated_at"] == owner["updated_at"]


def test_each_owner_amendment_advances_the_version_by_one(api):
    """Two PATCHes take version 1 to 3 while created_at holds still.

    PRD: "Every resource carries a server-minted `id` in UUID form, with no type
    prefix of any kind, and a `created_at` timestamp recorded as an ISO 8601 UTC
    instant with three fractional digits."

    Design: Corner/cross-cutting complexity layers/entity_version_increments_on_every_write
    """
    owner = fx.create_owner(api, tax_id_on_file=False)
    assert owner["created_at"] == owner["updated_at"]

    first = fx.patch_owner(api, owner["id"], {"tax_id_on_file": True})
    second = fx.patch_owner(api, owner["id"], {"mailing_address": "9 Pecos Rd, Pecos TX"})

    assert first["version"] == 2
    assert first["tax_id_on_file"] is True
    assert second["version"] == 3
    assert second["mailing_address"] == "9 Pecos Rd, Pecos TX"
    assert second["created_at"] == owner["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert first["updated_at"] >= owner["updated_at"]


def test_a_pugh_release_leaves_the_pinned_decimal_alone(api):
    """The live acreage shrinks by a third and the executed order does not move.

    PRD: "This variant deliberately ignores every allocation, pooling and pugh change
    that occurred after the order was executed, because that is exactly what pinning a
    decimal means."

    Design: Corner/cross-cutting complexity layers/pinned_decimal_stays_frozen_while_the_live_decimal_moves
    """
    world = fx.executed_division_order_ready(api, unit_overrides=PUGH_UNIT)
    fx.set_clock(api, "2027-01-01T00:00:00Z")

    released = fx.pugh_release(api, world["allocation"]["id"])

    assert_acreage(released["allocated_acres"], "213.3333", "allocated_acres")
    assert_acreage(released["released_acres"], "106.6667", "released_acres")
    assert_acreage(
        fx.read_unit(api, world["unit"]["id"])["unallocated_acres"],
        "1066.6667",
        "unallocated_acres",
    )
    order = fx.read_division_order(api, world["order"]["id"])
    assert_decimal_interest(order["pinned_decimal"], "0.00195313", "pinned_decimal")
    assert order["do_status"] == "EXECUTED"


def test_the_audit_variant_reports_the_drift_without_moving_a_cent(api):
    """Settlement pays 115.52 at the pinned decimal while the audit net is 77.02.

    PRD: "And `audit_variance_amount` is that audit net less `net_amount`, rounded
    half-up to cents; it too may be negative."

    Design: Corner/cross-cutting complexity layers/pinned_decimal_stays_frozen_while_the_live_decimal_moves
    """
    world = fx.executed_division_order_ready(api, unit_overrides=PUGH_UNIT)
    fx.set_clock(api, "2027-01-01T00:00:00Z")
    fx.pugh_release(api, world["allocation"]["id"])

    detail = fx.report_revenue(
        api,
        world["order"]["id"],
        production_month="2026-07",
        operator_decimal_used=0.00195313,
    )

    assert_money(detail["reported_gross_royalty"], "121.09", "reported_gross_royalty")
    assert_money(detail["net_amount"], "115.52", "net_amount")
    assert_money(detail["expected_net_amount"], "115.52", "expected_net_amount")
    assert_money(detail["variance_amount"], "0.00", "variance_amount")
    assert_decimal_interest(detail["audit_decimal"], "0.00130208", "audit_decimal")
    assert_money(detail["audit_gross_royalty"], "80.73", "audit_gross_royalty")
    assert_money(detail["audit_variance_amount"], "-38.50", "audit_variance_amount")
    assert detail["check_status"] == "PAID"
    assert_money(
        fx.read_division_order(api, world["order"]["id"])["paid_net_total"],
        "115.52",
        "paid_net_total",
    )


def test_thirty_five_months_of_dormancy_is_one_month_short(api):
    """At 2029-05-01 the account has run 35 months and will not escheat.

    PRD: "And it is lawful only once the statutory dormancy period has run:
    `months_held` must be at least thirty-six whole calendar months — three full
    years — and a shorter holding period is `ERR_ESCHEAT_PERIOD_NOT_ELAPSED`."

    Design: Corner/cross-cutting complexity layers/escheat_threshold_is_inclusive_at_thirty_six_months
    """
    world = fx.executed_division_order_ready(api, allocation_overrides=LONG_ALLOCATION)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})
    fx.report_revenue(api, world["order"]["id"], operator_decimal_used=0.00195313)
    account = fx.suspense_for_order(api, world["order"]["id"])
    assert account["suspense_reason"] == "UNLOCATABLE_OWNER"
    assert account["first_suspended_month"] == "2026-06"
    assert_money(account["accrued_amount"], "115.52", "accrued_amount")

    fx.set_clock(api, "2029-05-01T00:00:00Z")
    short = fx.read_suspense(api, account["id"])
    assert short["months_held"] == 35
    assert_money(short["interest_accrued"], "20.22", "interest_accrued")

    response = api.escheat_suspense(account["id"], f.escheat_payload(), ADMIN_ALT_HEADERS)

    validate_error(response, "ERR_ESCHEAT_PERIOD_NOT_ELAPSED", 409)
    assert fx.read_suspense(api, account["id"])["suspense_status"] == "ACCRUING"


def test_exactly_thirty_six_months_escheats_the_account(api):
    """The boundary is inclusive, so 2029-06-01 hands 136.31 to the state.

    PRD: "The boundary is inclusive, so exactly thirty-six months qualifies."

    Design: Corner/cross-cutting complexity layers/escheat_threshold_is_inclusive_at_thirty_six_months
    """
    world = fx.executed_division_order_ready(api, allocation_overrides=LONG_ALLOCATION)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})
    fx.report_revenue(api, world["order"]["id"], operator_decimal_used=0.00195313)
    account = fx.suspense_for_order(api, world["order"]["id"])

    fx.set_clock(api, "2029-06-01T00:00:00Z")
    ripe = fx.read_suspense(api, account["id"])
    assert ripe["months_held"] == 36

    escheated = validate_success(
        api.escheat_suspense(account["id"], f.escheat_payload(), ADMIN_ALT_HEADERS), 200
    )

    assert escheated["suspense_status"] == "ESCHEATED"
    assert escheated["escheat_state_code"] == "TX"
    assert_money(escheated["interest_accrued"], "20.79", "interest_accrued")
    assert_money(escheated["release_amount"], "136.31", "release_amount")
    assert_money(escheated["accrued_amount"], "0.00", "accrued_amount")
    assert escheated["held_detail_count"] == 0
    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "SUSPENDED"
    assert_money(order["paid_net_total"], "0.00", "paid_net_total")
