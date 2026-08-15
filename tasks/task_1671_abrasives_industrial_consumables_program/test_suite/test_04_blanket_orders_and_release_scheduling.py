"""Blanket order lifecycle and release scheduling: remaining-pool accounting,
OCC on release create, term-window temporal gate, substitution pendency gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    get_order,
    get_release,
    make_blanket_order,
    make_contract,
    make_lot,
    make_machine,
    make_product,
    make_release,
    make_standard,
    make_trial,
    make_trial_in_evaluation,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _setup_open_order(committed_qty=50, sku="BO-1", contract_number="C-BO1"):
    product = make_product(sku=sku, name="Order Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-BO",
        contract_number=contract_number,
    )
    order = make_blanket_order(contract["id"], product["id"], committed_qty=committed_qty)
    return product, contract, order


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check / release_qty_exactly_remaining_boundary
# ---------------------------------------------------------------------------


def test_release_qty_exactly_remaining_allowed(api):
    """PRD §3.6: "the `qty` must be at least 1 and no greater than the order's
    `remaining_qty` (`ERR_RELEASE_EXCEEDS_REMAINING` — a release exactly equal
    to the remaining pool is allowed)."
    PRD §3.6: "the order auto-closes: after any individual release ships or is
    cancelled, if the order's `remaining_qty` has reached zero and no release
    remains in `SCHEDULED`, `ON_HOLD`, or `PICKED`, the order transitions from
    `OPEN` to `CLOSED` on its own."

    Design: Difficulty/boundary_precision_check/release_qty_exactly_remaining_boundary
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="CB-BND",
                                                 contract_number="C-1007")
    r1 = make_release(order["id"], order["version"], qty=30,
                      scheduled_ship_date="2026-09-01")
    assert r1["id"]

    mid = get_order(order["id"])
    assert mid["remaining_qty"] == 20

    # qty == remaining (20) is the inclusive upper bound: allowed.
    r2 = make_release(order["id"], mid["version"], qty=20,
                      scheduled_ship_date="2026-09-01")
    assert r2["id"]

    end = get_order(order["id"])
    assert end["remaining_qty"] == 0
    assert end["status"] == "OPEN", (
        "auto-close requires no open releases; R1/R2 still SCHEDULED -> OPEN"
    )


def test_release_qty_remaining_plus_one_rejected(api):
    """PRD §3.6: "the `qty` must be at least 1 and no greater than the order's
    `remaining_qty` (`ERR_RELEASE_EXCEEDS_REMAINING` — a release exactly equal
    to the remaining pool is allowed)."

    Design: Difficulty/boundary_precision_check/release_qty_exactly_remaining_boundary
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="CB-BND2",
                                                 contract_number="C-1007B")
    r1 = make_release(order["id"], order["version"], qty=30,
                      scheduled_ship_date="2026-09-01")
    mid = get_order(order["id"])
    r2 = make_release(order["id"], mid["version"], qty=20,
                      scheduled_ship_date="2026-09-01")
    end = get_order(order["id"])
    assert end["remaining_qty"] == 0

    # remaining + 1 == 1: rejected.
    resp = api.create_release(
        order["id"],
        {"qty": 1, "scheduled_ship_date": "2026-09-01",
         "expected_blanket_order_version": end["version"]},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_EXCEEDS_REMAINING.value)
    assert get_order(order["id"])["remaining_qty"] == 0


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict / release_create_temporal_beats_fiscal
# ---------------------------------------------------------------------------


def test_release_create_temporal_beats_fiscal_window_error_wins(api):
    """PRD §2.8: "When several checks could fail on the same request, the API
    evaluates them in a single fixed priority order and reports the **first**
    failure." — item 9 "Temporal rules — release ship dates inside the contract
    term" precedes item 10 "Capacity and quota rules — release quantity against
    the order's remaining pool".
    PRD §3.6: "the `scheduled_ship_date` must fall within the contract's term,
    on or after `term_start` and on or before `term_end`
    (`ERR_RELEASE_WINDOW_OUTSIDE_TERM`); and finally the `qty` must be at least
    1 and no greater than the order's `remaining_qty`
    (`ERR_RELEASE_EXCEEDS_REMAINING`)"

    Design: Difficulty/priority_pair_validation_conflict/release_create_temporal_beats_fiscal
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="CB-TF",
                                                 contract_number="C-1006")
    # Both conditions hold: ship 2028-01-10 > term_end 2027-12-31 AND
    # qty 60 > remaining 50. The temporal error (earlier priority) must win.
    resp = api.create_release(
        order["id"],
        {"qty": 60, "scheduled_ship_date": "2028-01-10",
         "expected_blanket_order_version": order["version"]},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_WINDOW_OUTSIDE_TERM.value)


def test_release_create_temporal_beats_fiscal_no_reservation(api):
    """PRD §2.7: "the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is persisted" — and likewise for any rejected create: the order's
    `remaining_qty` is unchanged.
    PRD §3.6: "On acceptance the release starts `SCHEDULED`, the order's
    `remaining_qty` decreases by the release's `qty`"

    Design: Difficulty/priority_pair_validation_conflict/release_create_temporal_beats_fiscal
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="CB-TF2",
                                                 contract_number="C-1006B")
    resp = api.create_release(
        order["id"],
        {"qty": 60, "scheduled_ship_date": "2028-01-10",
         "expected_blanket_order_version": order["version"]},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_WINDOW_OUTSIDE_TERM.value)
    assert get_order(order["id"])["remaining_qty"] == 50, (
        "rejected release must not reserve quantity"
    )


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant / blanket_order_units_conserved_on_cancel
# ---------------------------------------------------------------------------


def test_blanket_order_units_conserved_on_cancel_progression(api):
    """PRD §3.6: "The committed pool is tracked continuously: `remaining_qty` is
    `committed_qty` minus the summed `qty` of the order's releases in
    `SCHEDULED`, `ON_HOLD`, `PICKED`, or `SHIPPED` status. Releases in
    `CANCELLED` are excluded from the sum — their quantity is given back to the
    pool."
    PRD §3.7: "From `SCHEDULED`, the release moves to `CANCELLED`, its `qty` is
    added back to the order's `remaining_qty`, and the auto-close check runs."

    Design: Difficulty/compensating_invariant/blanket_order_units_conserved_on_cancel
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="CB-INV1",
                                                 contract_number="C-1009")
    assert order["remaining_qty"] == 100  # 100 = 100 + 0

    r1 = make_release(order["id"], order["version"], qty=40,
                      scheduled_ship_date="2026-09-01")
    mid = get_order(order["id"])
    assert mid["remaining_qty"] == 60  # 60 + 40 = 100

    r2 = make_release(order["id"], mid["version"], qty=25,
                      scheduled_ship_date="2026-09-01")
    after2 = get_order(order["id"])
    assert after2["remaining_qty"] == 35  # 35 + 40 + 25 = 100

    validate_success(api.cancel_release(r1["id"], AM), 200)
    after3 = get_order(order["id"])
    assert after3["remaining_qty"] == 75, (
        f"cancel gives back 40: 75 + 25 = 100; got {after3['remaining_qty']}"
    )
    assert after3["status"] == "OPEN", "cancel restored remaining above 0"


def test_blanket_order_units_conserved_cancel_excluded_from_sum(api):
    """PRD §3.6: "`remaining_qty` is `committed_qty` minus the summed `qty` of
    the order's releases in `SCHEDULED`, `ON_HOLD`, `PICKED`, or `SHIPPED`
    status. Releases in `CANCELLED` are excluded from the sum — their quantity
    is given back to the pool."

    Design: Difficulty/compensating_invariant/blanket_order_units_conserved_on_cancel
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="CB-INV1B",
                                                 contract_number="C-1009B")
    r1 = make_release(order["id"], order["version"], qty=40,
                      scheduled_ship_date="2026-09-01")
    mid = get_order(order["id"])
    r2 = make_release(order["id"], mid["version"], qty=25,
                      scheduled_ship_date="2026-09-01")

    validate_success(api.cancel_release(r1["id"], AM), 200)
    cancelled = get_release(r1["id"])
    assert cancelled["status"] == "CANCELLED"

    # Invariant: committed == remaining + sum(qty over non-CANCELLED releases).
    after = get_order(order["id"])
    live_sum = 25  # only r2 remains in the reserved set
    assert after["committed_qty"] == after["remaining_qty"] + live_sum


# ---------------------------------------------------------------------------
# Corner / cross_cutting_layers / occ_release_create_stale_version_rejected
# ---------------------------------------------------------------------------


def test_occ_release_create_first_create_advances_version(api):
    """PRD §3.6: "On acceptance the release starts `SCHEDULED`, the order's
    `remaining_qty` decreases by the release's `qty`, the release's
    `provisional_unit_price_cents` is stamped by evaluating the price at its
    `scheduled_ship_date`, and the parent order's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_release_create_stale_version_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="OC-1",
                                                 contract_number="C-OC1")
    r1 = make_release(order["id"], order["version"], qty=10,
                      scheduled_ship_date="2026-09-01")
    assert r1["status"] == "SCHEDULED"
    after = get_order(order["id"])
    assert after["version"] == order["version"] + 1
    assert after["remaining_qty"] == 40


def test_occ_release_create_stale_version_rejected(api):
    """PRD §2.7: "**Release creation under a blanket order.** The request must
    carry `expected_blanket_order_version`, holding the order's `version` as the
    client last observed it. If the value does not match the blanket order's
    current `version` — because the order has been mutated since the client read
    it, legitimately changing its committed pool — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted."

    Design: Corner/cross_cutting_layers/occ_release_create_stale_version_rejected
    """
    product, contract, order = _setup_open_order(committed_qty=50, sku="OC-1B",
                                                 contract_number="C-OC1B")
    stale_version = order["version"]
    make_release(order["id"], stale_version, qty=10, scheduled_ship_date="2026-09-01")

    resp = api.create_release(
        order["id"],
        {"qty": 5, "scheduled_ship_date": "2026-09-01",
         "expected_blanket_order_version": stale_version},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    after = get_order(order["id"])
    assert after["remaining_qty"] == 40, "only the first release reserved"
    assert after["version"] == stale_version + 1


# ---------------------------------------------------------------------------
# Corner / validations / release_scheduled_on_term_end_allowed
# ---------------------------------------------------------------------------


def test_release_scheduled_on_term_end_allowed(api):
    """PRD §3.6: "the `scheduled_ship_date` must fall within the contract's
    term, on or after `term_start` and on or before `term_end`
    (`ERR_RELEASE_WINDOW_OUTSIDE_TERM`)"

    Design: Corner/validations/release_scheduled_on_term_end_allowed
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="TE-1",
                                                 contract_number="C-TE")
    r = make_release(order["id"], order["version"], qty=10,
                     scheduled_ship_date="2027-12-31")
    assert r["id"], "ship date == term_end is inside the inclusive window"


def test_release_scheduled_day_after_term_end_rejected(api):
    """PRD §3.6: "the `scheduled_ship_date` must fall within the contract's
    term, on or after `term_start` and on or before `term_end`
    (`ERR_RELEASE_WINDOW_OUTSIDE_TERM`)"

    Design: Corner/validations/release_scheduled_on_term_end_allowed
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="TE-2",
                                                 contract_number="C-TE2")
    resp = api.create_release(
        order["id"],
        {"qty": 10, "scheduled_ship_date": "2028-01-01",
         "expected_blanket_order_version": order["version"]},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_WINDOW_OUTSIDE_TERM.value)


# ---------------------------------------------------------------------------
# Corner / validations / confirm_order_preconditions_rejected
# ---------------------------------------------------------------------------


def test_confirm_order_draft_contract_rejected(api):
    """PRD §3.6: "Confirmation, a `ProgramAdmin` act, moves the order from
    `DRAFT` to `OPEN` and is gated on three conditions: the governing contract
    must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); a contract line must exist
    for the order's contract-and-product pair (`ERR_CONTRACT_LINE_MISSING`);
    and the product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`)."

    Design: Corner/validations/confirm_order_preconditions_rejected
    """
    pa = make_product(sku="CF-A", name="Confirm A")
    contract = make_contract(
        [{"product_id": pa["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-CFA", contract_number="C-CFA", activate=False,
    )
    order = make_blanket_order(contract["id"], pa["id"], committed_qty=10, confirm=False)
    resp = api.confirm_blanket_order(order["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


def test_confirm_order_missing_contract_line_rejected(api):
    """PRD §3.6: "a contract line must exist for the order's
    contract-and-product pair (`ERR_CONTRACT_LINE_MISSING`)"

    Design: Corner/validations/confirm_order_preconditions_rejected
    """
    pbm = make_product(sku="CF-BM", name="Confirm B Main")
    pbo = make_product(sku="CF-BO", name="Confirm B Other")
    contract = make_contract(
        [{"product_id": pbo["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-CFB", contract_number="C-CFB",
    )
    order = make_blanket_order(contract["id"], pbm["id"], committed_qty=10,
                               confirm=False)
    resp = api.confirm_blanket_order(order["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_LINE_MISSING.value)


def test_confirm_order_discontinued_product_rejected(api):
    """PRD §3.6: "and the product must be `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`)"

    Design: Corner/validations/confirm_order_preconditions_rejected
    """
    pc1 = make_product(sku="CF-C1", name="Confirm C Old")
    pc2 = make_product(sku="CF-C2", name="Confirm C New", max_operating_speed_rpm=6500)
    contract = make_contract(
        [
            {"product_id": pc1["id"], "base_unit_price_cents": 9000},
            {"product_id": pc2["id"], "base_unit_price_cents": 9500},
        ],
        customer_ref="PLANT-CFC", contract_number="C-CFC",
    )
    order = make_blanket_order(contract["id"], pc1["id"], committed_qty=10,
                               confirm=False)
    validate_success(
        api.discontinue_product(pc1["id"], {"replacement_product_id": pc2["id"]}, ADMIN),
        200,
    )
    resp = api.confirm_blanket_order(order["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / release_on_hold_pick_and_create_rejected
# ---------------------------------------------------------------------------


def _setup_pending_order(sku_old="OH-1", sku_new="OH-2", contract_number="C-OH"):
    p1 = make_product(sku=sku_old, name="OnHold Disc Old")
    p2 = make_product(sku=sku_new, name="OnHold Disc New", max_operating_speed_rpm=6500)
    contract = make_contract(
        [
            {"product_id": p1["id"], "base_unit_price_cents": 9000},
            {"product_id": p2["id"], "base_unit_price_cents": 9500},
        ],
        customer_ref="PLANT-OH", contract_number=contract_number,
    )
    order = make_blanket_order(contract["id"], p1["id"], committed_qty=50)
    release = make_release(order["id"], order["version"], qty=5,
                           scheduled_ship_date="2026-09-01")
    validate_success(
        api_client.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN),
        200,
    )
    return p1, p2, contract, order, release


def test_release_create_rejected_while_substitution_pending(api):
    """PRD §3.6: "The remaining gates apply in order: the order's
    `substitution_status` must be `NONE` (`ERR_SUBSTITUTION_PENDING` — a
    substitution awaiting acceptance freezes new scheduling)"
    PRD §3.1: "While an order's `substitution_status` is `PENDING`, no new
    releases may be scheduled against it (§3.6)."

    Design: Corner/state_machines/release_on_hold_pick_and_create_rejected
    """
    _p1, _p2, _c, order, release = _setup_pending_order()
    pending = get_order(order["id"])
    assert pending["substitution_status"] == "PENDING"

    resp = api.create_release(
        order["id"],
        {"qty": 3, "scheduled_ship_date": "2026-09-01",
         "expected_blanket_order_version": pending["version"]},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_PENDING.value)


def test_pick_rejected_on_on_hold_release(api):
    """PRD §2.8 item 6: "release picks only from `SCHEDULED`, ships only from
    `PICKED`, cancels only from a non-terminal state ... violations yield
    `ERR_INVALID_STATE_TRANSITION`, 409"
    PRD §3.1: "**Hop 2 — releases.** Every release in `SCHEDULED` belonging to a
    blanket order that just became `PENDING` moves to `ON_HOLD`."

    Design: Corner/state_machines/release_on_hold_pick_and_create_rejected
    """
    _p1, _p2, _c, order, release = _setup_pending_order("OH-3", "OH-4", "C-OH2")
    assert get_release(release["id"])["status"] == "ON_HOLD"

    resp = api.pick_release(release["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_release(release["id"])["status"] == "ON_HOLD"
    assert get_order(order["id"])["remaining_qty"] == 45


# ---------------------------------------------------------------------------
# Corner / consistency_model / read_your_writes_remaining_immediate
# ---------------------------------------------------------------------------


def test_read_your_writes_remaining_immediate(api):
    """PRD §2.9: "any operation whose rules cascade to other resources applies
    the primary mutation **and** every cascade atomically within the request;
    there is no observable intermediate state."
    PRD §3.6: "On acceptance the release starts `SCHEDULED`, the order's
    `remaining_qty` decreases by the release's `qty`"

    Design: Corner/consistency_model/read_your_writes_remaining_immediate
    """
    product, contract, order = _setup_open_order(committed_qty=100, sku="RY-1",
                                                 contract_number="C-RY")
    assert order["remaining_qty"] == 100

    make_release(order["id"], order["version"], qty=40,
                 scheduled_ship_date="2026-09-01")
    after = get_order(order["id"])
    assert after["remaining_qty"] == 60, (
        "reservation must be visible on the very next read — no eventual lag"
    )
