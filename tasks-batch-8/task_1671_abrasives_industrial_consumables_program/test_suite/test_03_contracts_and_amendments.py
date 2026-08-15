"""Contract lifecycle: activation, amendment cascade, OCC, expiry sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_contract,
    get_order,
    get_release,
    make_blanket_order,
    make_contract,
    make_product,
    make_release,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade / contract_amend_price_cascade_depth3
# ---------------------------------------------------------------------------


def _setup_amend_cascade(sku="CB-AM", contract_number="C-1004"):
    product = make_product(sku=sku, name="Coated Belt Am")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-6",
        contract_number=contract_number,
        term_start="2026-01-01",
        term_end="2027-12-31",
        price_hold_end="2026-12-31",
        escalation_pct=0.04,
        escalation_effective_date="2027-01-01",
    )
    order = make_blanket_order(contract["id"], product["id"], committed_qty=100)
    release = make_release(
        order["id"], order["version"], qty=10, scheduled_ship_date="2026-09-01"
    )
    return product, contract, order, release


def test_contract_amend_cascade_line_order_release_restamps(api):
    """PRD §3.5: "A successful amendment increments the contract's `version` by
    one and fires the program's deepest cascade, atomically:
    - **Hop 1 — lines.** Every contract line of the amended contract re-stamps
      `current_unit_price_cents` by evaluating the price at the current clock
      date under the amended terms.
    - **Hop 2 — blanket orders.** Every blanket order in `OPEN` whose
      `product_id` matches a re-stamped line re-stamps its
      `provisional_unit_price_cents` from that line's
      `current_unit_price_cents`, and recomputes
      `provisional_remaining_value_cents` as its `remaining_qty` multiplied by
      the new provisional unit price.
    - **Hop 3 — releases.** Every release in `SCHEDULED` belonging to a
      re-stamped order re-stamps its `provisional_unit_price_cents` by
      evaluating the price at that release's `scheduled_ship_date`."

    Design: Difficulty/transitive_cascade/contract_amend_price_cascade_depth3
    """
    product, contract, order, release = _setup_amend_cascade()
    assert release["provisional_unit_price_cents"] == 10000, (
        "release scheduled 2026-09-01 is inside the hold -> base price"
    )

    # Advance clock into the escalation window (term_end not passed).
    sweep = set_clock("2027-02-01T00:00:00Z")
    assert sweep["contracts_expired"] == 0

    amended = validate_success(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": contract["version"], "escalation_pct": 0.05},
            ADMIN,
        ),
        200,
    )
    assert amended["version"] == contract["version"] + 1

    # Hop 1: line re-stamped: round_half_up(10000 * 1.05) = 10500.
    lines, _meta = validate_paginated(
        api.list_contract_lines(ADMIN, params={"contract_id": contract["id"]})
    )
    assert len(lines) == 1
    assert lines[0]["current_unit_price_cents"] == 10500, (
        f"hop 1 line price: {lines[0]['current_unit_price_cents']}"
    )

    # Hop 2: OPEN order provisional re-stamp: remaining 90 x 10500 = 945000.
    order_after = get_order(order["id"])
    assert order_after["provisional_unit_price_cents"] == 10500
    assert order_after["provisional_remaining_value_cents"] == 945000

    # Hop 3: SCHEDULED release re-stamped at its scheduled_ship_date under the
    # amended terms: eval 2026-09-01 <= price_hold_end 2026-12-31 (unchanged)
    # -> hold branch -> base 10000. The release price therefore stays 10000,
    # which the PRD's hop-3 rule uniquely derives.
    release_after = get_release(release["id"])
    assert release_after["provisional_unit_price_cents"] == 10000, (
        f"hop 3 re-stamp evaluates price_at(scheduled_ship_date 2026-09-01) "
        f"under amended terms: still <= price_hold_end 2026-12-31 -> base "
        f"10000; got {release_after['provisional_unit_price_cents']}"
    )


def test_contract_amend_cascade_increments_version_and_sweep_count(api):
    """PRD §3.5: "A successful amendment increments the contract's `version` by
    one"
    PRD §2.4: "every contract still `ACTIVE` whose `term_end` is strictly
    earlier than the new clock date transitions to `EXPIRED`; a contract whose
    `term_end` equals the new date stays `ACTIVE`."

    Design: Difficulty/transitive_cascade/contract_amend_price_cascade_depth3
    """
    product, contract, order, release = _setup_amend_cascade(
        sku="CB-AM2", contract_number="C-1004B"
    )
    sweep = set_clock("2027-02-01T00:00:00Z")
    assert sweep["contracts_expired"] == 0, (
        f"term_end 2027-12-31 not passed at 2027-02-01: {sweep}"
    )
    assert get_contract(contract["id"])["status"] == "ACTIVE"

    amended = validate_success(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": contract["version"], "escalation_pct": 0.05},
            ADMIN,
        ),
        200,
    )
    assert amended["version"] == contract["version"] + 1, (
        f"amend must increment contract version by 1: "
        f"{contract['version']} -> {amended['version']}"
    )


# ---------------------------------------------------------------------------
# Corner / state_machines / contract_amend_draft_rejected
# ---------------------------------------------------------------------------


def test_contract_amend_draft_rejected(api):
    """PRD §3.5: "amending a contract that is not `ACTIVE` is
    `ERR_INVALID_STATE_TRANSITION`."
    PRD §2.7: "A mismatch with the contract's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)" — here the version matches, so the state
    precondition is what rejects.

    Design: Corner/state_machines/contract_amend_draft_rejected
    """
    product = make_product(sku="AD-1", name="Amend Draft Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-AD",
        contract_number="C-AD",
        escalation_pct=0.04,
        activate=False,
    )
    assert contract["status"] == "DRAFT"

    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": contract["version"], "escalation_pct": 0.07},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / contract_terminate_then_activate_rejected
# ---------------------------------------------------------------------------


def test_contract_terminate_then_activate_rejected(api):
    """PRD §3.5: "Termination, also a `ProgramAdmin` act, moves the contract
    from `DRAFT` or `ACTIVE` to `TERMINATED`; the same transition from any other
    state is `ERR_INVALID_STATE_TRANSITION`." — and activation is only declared
    from DRAFT, so activate on TERMINATED is `ERR_INVALID_STATE_TRANSITION`.

    Design: Corner/state_machines/contract_terminate_then_activate_rejected
    """
    product = make_product(sku="TA-1", name="Term Act Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-TA",
        contract_number="C-TA",
        activate=False,
    )
    validate_success(api.terminate_contract(contract["id"], ADMIN), 200)

    resp = api.activate_contract(contract["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / contract_double_activate_rejected
# ---------------------------------------------------------------------------


def test_contract_double_activate_rejected(api):
    """PRD §3.5: "Activation, performed by a `ProgramAdmin`, moves the contract
    from `DRAFT` to `ACTIVE`" — the transition is declared only from DRAFT, so
    a second activate on an already-ACTIVE contract is
    `ERR_INVALID_STATE_TRANSITION` (PRD §2.8 item 6: "contract amendment only
    on `ACTIVE`; ... violations yield `ERR_INVALID_STATE_TRANSITION`, 409").

    Design: Corner/state_machines/contract_double_activate_rejected
    """
    product = make_product(sku="DA-1", name="Double Act Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-DA",
        contract_number="C-DA",
    )
    assert contract["status"] == "ACTIVE"

    resp = api.activate_contract(contract["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner / state_machines / contract_expiry_sweep_boundary
# ---------------------------------------------------------------------------


def test_contract_expiry_sweep_active_on_term_end(api):
    """PRD §2.4: "every contract still `ACTIVE` whose `term_end` is strictly
    earlier than the new clock date transitions to `EXPIRED`; a contract whose
    `term_end` equals the new date stays `ACTIVE`."

    Design: Corner/state_machines/contract_expiry_sweep_boundary
    """
    product = make_product(sku="CX-1", name="Contract Expiry Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-CX",
        contract_number="C-CX",
        term_start="2026-01-01",
        term_end="2026-08-01",
    )
    # Default clock is 2026-08-01 == term_end: still ACTIVE.
    assert contract["status"] == "ACTIVE"
    assert get_contract(contract["id"])["status"] == "ACTIVE"


def test_contract_expiry_sweep_expires_day_after_term_end(api):
    """PRD §2.4: "every contract still `ACTIVE` whose `term_end` is strictly
    earlier than the new clock date transitions to `EXPIRED`" and "The response
    of that capability reports the resulting `current_utc` together with two
    sweep counters, `lots_expired` and `contracts_expired`."

    Design: Corner/state_machines/contract_expiry_sweep_boundary
    """
    product = make_product(sku="CX-2", name="Contract Expiry Disc 2")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-CX2",
        contract_number="C-CX2",
        term_start="2026-01-01",
        term_end="2026-08-01",
    )
    sweep = set_clock("2026-08-02T00:00:00Z")
    assert sweep["contracts_expired"] == 1, f"sweep result: {sweep}"
    assert get_contract(contract["id"])["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner / cross_cutting_layers / occ_contract_amend_stale_version_rejected
# ---------------------------------------------------------------------------


def test_occ_contract_amend_first_amend_succeeds(api):
    """PRD §2.7: "**Contract amendment.** The request must carry
    `expected_contract_version`, holding the contract's `version` as the client
    last observed it. A mismatch with the contract's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412)"
    PRD §3.5: "A successful amendment increments the contract's `version` by
    one"

    Design: Corner/cross_cutting_layers/occ_contract_amend_stale_version_rejected
    """
    product = make_product(sku="OC-2", name="OCC Contract Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-OC2",
        contract_number="C-OC2",
        escalation_pct=0.04,
    )
    amended = validate_success(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": contract["version"], "escalation_pct": 0.05},
            ADMIN,
        ),
        200,
    )
    assert amended["version"] == contract["version"] + 1
    assert amended["escalation_pct"] == pytest.approx(0.05)


def test_occ_contract_amend_stale_version_rejected(api):
    """PRD §2.7: "**Contract amendment.** The request must carry
    `expected_contract_version`, holding the contract's `version` as the client
    last observed it. A mismatch with the contract's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from
    re-pricing a contract it has not re-read."

    Design: Corner/cross_cutting_layers/occ_contract_amend_stale_version_rejected
    """
    product = make_product(sku="OC-2B", name="OCC Contract Disc B")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-OC2B",
        contract_number="C-OC2B",
        escalation_pct=0.04,
    )
    original_version = contract["version"]
    validate_success(
        api.amend_contract(
            contract["id"],
            {"expected_contract_version": original_version, "escalation_pct": 0.05},
            ADMIN,
        ),
        200,
    )

    # Replay the activation-era version: now stale.
    resp = api.amend_contract(
        contract["id"],
        {"expected_contract_version": original_version, "escalation_pct": 0.06},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    after = get_contract(contract["id"])
    assert after["escalation_pct"] == pytest.approx(0.05), (
        "stale amend must not apply; first amend's escalation_pct stays"
    )
    assert after["version"] == original_version + 1
