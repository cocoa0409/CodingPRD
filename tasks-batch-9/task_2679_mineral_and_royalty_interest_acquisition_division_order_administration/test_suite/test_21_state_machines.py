"""Initial states, preconditions, idempotency and terminal lockdown."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_acreage,
    assert_decimal_interest,
    assert_money,
)
from test_helpers.test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_USER_ID,
    ANALYST_HEADERS,
    MANAGER_ALT_HEADERS,
    OPERATOR_HEADERS,
)

LONG_ALLOCATION = {"effective_to": "2030-01-01"}


def test_a_new_division_order_is_sent_with_nothing_pinned(api):
    """SENT, dispute_reason NONE, and every pinned figure still null.

    PRD: "The order opens with `do_status` of `SENT`, a `dispute_reason` of `NONE`,
    a null `pinned_decimal`, a null `operator_decimal`, a null
    `effective_production_month`, a `cumulative_variance_amount` of 0.00, a
    `paid_net_total` of 0.00, a `correction_round_count` of 0, and
    `created_by_user_id` stamped from the acting `X-User-ID` — the counterparty for
    the disbursement segregation of duties."

    Design: Corner/state_machines/new_division_order_starts_in_sent_with_null_pinned_decimal
    """
    world = fx.division_order_ready(api)
    order = world["order"]

    assert order["do_status"] == "SENT"
    assert order["pinned_decimal"] is None
    assert order["operator_decimal"] is None
    assert order["effective_production_month"] is None
    assert order["dispute_reason"] == "NONE"
    assert_decimal_interest(order["expected_decimal"], "0.00195313", "expected_decimal")
    assert order["correction_round_count"] == 0
    assert_money(order["paid_net_total"], "0.00", "paid_net_total")
    assert_money(order["cumulative_variance_amount"], "0.00", "cumulative_variance_amount")
    assert order["created_by_user_id"] == ADMIN_USER_ID
    assert order["royalty_owner_id"] == world["owner"]["id"]


def test_a_chain_with_two_patents_cannot_be_certified(api):
    """Two severances leave the replay without a single root.

    PRD: "it requires the chain to hold at least one entry and to hold exactly one
    `PATENT` instrument. An empty chain, a chain with no patent, or a chain with two
    or more patents is `ERR_TITLE_CHAIN_INCOMPLETE`."

    Design: Corner/state_machines/certify_title_with_two_patents_returns_title_chain_incomplete
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(
        api,
        tract["id"],
        f.patent_entry_payload(
            instrument_date="1906-03-02",
            conveyed_fraction=0.5,
            county_book_page="101/2",
            grantee_name="B Patentee",
        ),
    )

    response = api.certify_title(tract["id"], ANALYST_HEADERS)

    validate_error(response, "ERR_TITLE_CHAIN_INCOMPLETE", 409)
    reread = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert reread["title_status"] == "RESEARCH"
    assert reread["net_mineral_acres_certified"] is None
    assert reread["existing_burden_fraction"] is None
    assert reread["chain_entry_count"] == 2
    assert reread["certified_at"] is None


def test_certifying_a_certified_tract_a_second_time_is_refused(api):
    """The transition only leaves RESEARCH, and the refusal moves no version.

    PRD: "It requires the tract to be in `RESEARCH` — a second certification of an
    already `CERTIFIED` tract is `ERR_TRACT_STATE_INVALID` — and it requires the
    chain to hold at least one entry and to hold exactly one `PATENT` instrument."

    Design: Corner/state_machines/certify_title_twice_returns_tract_state_invalid
    """
    tract = fx.create_tract(api)
    fx.add_canonical_chain(api, tract["id"])
    certified = fx.certify_tract(api, tract["id"])
    assert certified["title_status"] == "CERTIFIED"
    assert_acreage(
        certified["net_mineral_acres_certified"], "80.0000", "net_mineral_acres_certified"
    )

    response = api.certify_title(tract["id"], ANALYST_HEADERS)

    validate_error(response, "ERR_TRACT_STATE_INVALID", 409)
    reread = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert reread["version"] == certified["version"]
    assert reread["certified_at"] == certified["certified_at"]


def test_an_agreeing_operator_response_pins_the_decimal(api):
    """Branch A records the decimal, pins it and opens the revenue channel.

    PRD: "On **branch A**, where the supplied `operator_decimal` equals the order's
    `expected_decimal`, the order moves `SENT → EXECUTED`: the supplied
    `operator_decimal` is recorded, `pinned_decimal` is set to `expected_decimal` —
    this is the version-pinning act that fixes the decimal every future revenue
    check will be reconciled against — the supplied `effective_production_month` is
    recorded as the first production month the executed order governs — production
    months earlier than it are not reported against this order — `do_status` becomes
    `EXECUTED` and `dispute_reason` becomes `NONE`."

    Design: Corner/state_machines/operator_response_with_agreed_decimal_pins_it_and_executes_order
    """
    world = fx.executed_division_order_ready(api)
    order = world["order"]

    assert order["do_status"] == "EXECUTED"
    assert_decimal_interest(order["operator_decimal"], "0.00195313", "operator_decimal")
    assert_decimal_interest(order["pinned_decimal"], "0.00195313", "pinned_decimal")
    assert_decimal_interest(order["expected_decimal"], "0.00195313", "expected_decimal")
    assert order["effective_production_month"] == "2026-06"
    assert order["dispute_reason"] == "NONE"


def test_a_disagreeing_operator_response_disputes_and_pins_nothing(api):
    """Branch B records the operator's figure but leaves the pin null.

    PRD: "On **branch B**, where the supplied `operator_decimal` differs from
    `expected_decimal`, the order moves `SENT → DISPUTED` instead: the supplied
    `operator_decimal` is still recorded, `do_status` becomes `DISPUTED`,
    `dispute_reason` becomes `DECIMAL_MISMATCH`, and — the crucial asymmetry —
    `pinned_decimal` stays null and `effective_production_month` stays null."

    Design: Corner/state_machines/operator_response_with_disagreed_decimal_disputes_without_pinning
    """
    world = fx.division_order_ready(api)

    disputed = fx.send_operator_response(
        api, world["order"]["id"], operator_decimal=0.00180000
    )

    assert disputed["do_status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "DECIMAL_MISMATCH"
    assert disputed["pinned_decimal"] is None
    assert disputed["effective_production_month"] is None
    assert_decimal_interest(disputed["operator_decimal"], "0.00180000", "operator_decimal")


def test_a_correction_must_state_the_recomputed_decimal(api):
    """A wrong corrected_decimal is refused; the right one re-issues the order.

    PRD: "The `Operator` supplies a single `corrected_decimal`, and the correction
    is permitted only from `DISPUTED`. The system re-runs the allocation selector
    and the decimal computation against present-day state — the same three failure
    modes listed above apply — and the supplied `corrected_decimal` must equal that
    freshly recomputed figure to all 8 decimal places; anything else is
    `ERR_CORRECTED_DECIMAL_MISMATCH`."

    Design: Corner/state_machines/operator_response_with_disagreed_decimal_disputes_without_pinning
    """
    world = fx.division_order_ready(api)
    fx.send_operator_response(api, world["order"]["id"], operator_decimal=0.00180000)

    wrong = api.correct_division_order(
        world["order"]["id"], f.correct_payload(corrected_decimal=0.00180000), OPERATOR_HEADERS
    )
    validate_error(wrong, "ERR_CORRECTED_DECIMAL_MISMATCH", 422)
    assert fx.read_division_order(api, world["order"]["id"])["do_status"] == "DISPUTED"

    corrected = validate_success(
        api.correct_division_order(
            world["order"]["id"], f.correct_payload(), OPERATOR_HEADERS
        ),
        200,
    )

    assert corrected["do_status"] == "SENT"
    assert corrected["dispute_reason"] == "NONE"
    assert corrected["operator_decimal"] is None
    assert corrected["correction_round_count"] == 1
    assert_decimal_interest(corrected["expected_decimal"], "0.00195313", "expected_decimal")


def test_a_second_wire_against_a_funded_agreement_is_refused(api):
    """The funding dimension only leaves UNFUNDED once.

    PRD: "The funding dimension must read `UNFUNDED`; a second wire is
    `ERR_PSA_ALREADY_FUNDED`."

    Design: Corner/state_machines/fund_psa_twice_returns_psa_already_funded
    """
    world = fx.psa_ready(api)
    fx.close_curative(api, world["psa"]["id"])

    funded = fx.fund_psa(api, world["psa"]["id"], wire_reference="WIRE-S6-FIRST")
    assert funded["funding_status"] == "FUNDED"
    assert funded["wire_reference"] == "WIRE-S6-FIRST"

    response = api.fund_psa(
        world["psa"]["id"],
        f.fund_payload(wire_reference="WIRE-S6-SECOND"),
        MANAGER_ALT_HEADERS,
    )

    validate_error(response, "ERR_PSA_ALREADY_FUNDED", 409)
    reread = fx.read_psa(api, world["psa"]["id"])
    assert reread["wire_reference"] == "WIRE-S6-FIRST"
    assert reread["psa_status"] == "EXECUTED"


def test_a_pugh_release_before_the_deadline_is_refused(api):
    """The deadline day is the first releasable day, so 2026-08-01 is too early.

    PRD: "The logical clock's date must be on or after the unit's `pugh_deadline`,
    or the request is `ERR_PUGH_DEADLINE_NOT_REACHED` — the boundary is inclusive,
    so the deadline day itself is releasable."

    Design: Corner/state_machines/pugh_release_before_deadline_returns_deadline_not_reached
    """
    world = fx.unit_with_allocation_ready(
        api, unit_overrides={"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}
    )

    response = api.pugh_release(world["allocation"]["id"], OPERATOR_HEADERS)

    validate_error(response, "ERR_PUGH_DEADLINE_NOT_REACHED", 409)
    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["allocation_status"] == "ACTIVE"
    assert_acreage(allocation["allocated_acres"], "320.0000", "allocated_acres")
    assert_acreage(allocation["released_acres"], "0.0000", "released_acres")
    assert_acreage(
        fx.read_unit(api, world["unit"]["id"])["unallocated_acres"],
        "960.0000",
        "unallocated_acres",
    )


def test_a_unit_producing_from_every_depth_has_nothing_to_release(api):
    """Once the third depth comes on production the release has no dead depth left.

    PRD: "And there must be something to release: `producing_depth_count` must be
    strictly less than `total_depth_count`, because a unit producing from every
    depth it holds has no dead depth to hand back, and an attempt in that situation
    is `ERR_PUGH_ALL_DEPTHS_PRODUCING`."

    Design: Corner/state_machines/pugh_release_before_deadline_returns_deadline_not_reached
    """
    world = fx.unit_with_allocation_ready(
        api, unit_overrides={"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}
    )
    fx.set_clock(api, "2027-01-01T00:00:00Z")
    validate_success(
        api.update_unit(world["unit"]["id"], {"producing_depth_count": 3}, OPERATOR_HEADERS),
        200,
    )

    response = api.pugh_release(world["allocation"]["id"], OPERATOR_HEADERS)

    validate_error(response, "ERR_PUGH_ALL_DEPTHS_PRODUCING", 409)
    allocation = fx.read_allocation(api, world["allocation"]["id"])
    assert allocation["allocation_status"] == "ACTIVE"
    assert_acreage(allocation["allocated_acres"], "320.0000", "allocated_acres")
    assert_acreage(allocation["released_acres"], "0.0000", "released_acres")


def test_an_escheated_account_can_never_be_released(api):
    """ESCHEATED is terminal and the parent order stays suspended forever.

    PRD: "`RELEASED` and `ESCHEATED` are both terminal for a suspense account."

    PRD: "The account's `suspense_status` must be `ACCRUING`; an already `RELEASED`
    or `ESCHEATED` account is `ERR_SUSPENSE_STATE_INVALID`."

    Design: Corner/state_machines/suspense_release_from_escheated_account_returns_suspense_state_invalid
    """
    world = fx.executed_division_order_ready(api, allocation_overrides=LONG_ALLOCATION)
    fx.patch_owner(api, world["owner"]["id"], {"contact_status": "UNLOCATABLE"})
    fx.report_revenue(api, world["order"]["id"], operator_decimal_used=0.00195313)
    account = fx.suspense_for_order(api, world["order"]["id"])
    assert account["suspense_reason"] == "UNLOCATABLE_OWNER"

    fx.set_clock(api, "2029-06-01T00:00:00Z")
    escheated = validate_success(
        api.escheat_suspense(account["id"], f.escheat_payload(), ADMIN_ALT_HEADERS), 200
    )
    assert escheated["suspense_status"] == "ESCHEATED"
    assert escheated["escheat_state_code"] == "TX"
    assert escheated["months_held"] == 36
    assert_money(escheated["interest_accrued"], "20.79", "interest_accrued")
    assert_money(escheated["release_amount"], "136.31", "release_amount")

    response = api.release_suspense(account["id"], ADMIN_ALT_HEADERS)

    validate_error(response, "ERR_SUSPENSE_STATE_INVALID", 409)
    reread = fx.read_suspense(api, account["id"])
    assert reread["suspense_status"] == "ESCHEATED"
    assert reread["released_by_user_id"] is None
    order = fx.read_division_order(api, world["order"]["id"])
    assert order["do_status"] == "SUSPENDED"
    assert_money(order["paid_net_total"], "0.00", "paid_net_total")
