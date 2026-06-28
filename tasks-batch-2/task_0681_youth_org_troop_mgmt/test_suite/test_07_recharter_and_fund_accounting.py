"""Recharter: settled-vs-projected funds, the sweep, conservation invariants, OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_council,
    create_troop,
    create_member,
    create_live_fundraiser,
    place_order,
    place_and_fill_order,
    issue_and_pay_full,
    setup_ready_funded_troop,
    create_fundraiser_order_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_recharter_gate_uses_settled_not_projected_funds(api):
    """PRD §3.7: "The settled view, which is the one the recharter eligibility gate
    uses, counts only the commissions from FILLED orders together with posted
    payments. The recharter gate requires the troop's settled TROOP_DUES total to be
    at least the council's charter_fee_cents; if the settled funds fall short, the
    recharter is rejected with ERR_INSUFFICIENT_TROOP_FUNDS."

    Design: Difficulty/dual_variant_calc/recharter_sweep_projected_vs_settled_balance
    """
    council = create_council(name="Pine Council", charter_fee_cents=30000)
    troop = create_troop(council["id"], unit_number="U-201")
    seller = create_member(troop["id"], member_type="YOUTH", full_name="Seller")
    fr = create_live_fundraiser(council["id"], unit_price_cents=500, unit_cost_cents=200, total_inventory_units=2000)

    # One FILLED 150u order (commission 12500 settled) + one PLACED 150u order
    # (commission 12500 projected only). SETTLED=12500 < 30000 fee.
    place_and_fill_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])
    fr_after = get_success_data(api.get_fundraiser(fr["id"], REG))
    place_order(fr["id"], troop["id"], seller["id"], 150, fr_after["version"])

    troop_now = get_success_data(api.get_troop(troop["id"], REG))
    resp = api.recharter_troop(troop["id"], {"expected_troop_version": troop_now["version"]}, REG)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TROOP_FUNDS.value)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert troop_after["charter_status"] == "PROVISIONAL"


def test_recharter_insufficient_funds_leaves_provisional(api):
    """PRD §3.1: "It further requires that the troop's settled dues balance be
    sufficient to cover the charter fee, as detailed in §3.7; a shortfall is rejected
    with ERR_INSUFFICIENT_TROOP_FUNDS."

    Design: Difficulty/dual_variant_calc/recharter_sweep_projected_vs_settled_balance
    """
    council = create_council(name="Pine2", charter_fee_cents=30000)
    troop = create_troop(council["id"], unit_number="U-201b")
    seller = create_member(troop["id"], member_type="YOUTH", full_name="Seller")
    fr = create_live_fundraiser(council["id"], unit_price_cents=500, unit_cost_cents=200, total_inventory_units=2000)
    place_and_fill_order(fr["id"], troop["id"], seller["id"], 150, fr["version"])
    fr_after = get_success_data(api.get_fundraiser(fr["id"], REG))
    place_order(fr["id"], troop["id"], seller["id"], 150, fr_after["version"])

    troop_now = get_success_data(api.get_troop(troop["id"], REG))
    resp = api.recharter_troop(troop["id"], {"expected_troop_version": troop_now["version"]}, REG)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TROOP_FUNDS.value)
    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert troop_after["charter_status"] == "PROVISIONAL"


def test_recharter_sweep_evaluation_order_settles_and_sweeps(api):
    """PRD §3.7: "When the gate passes, the sweep posts two ledger rows under
    source_kind RECHARTER: it debits charter_fee_cents from TROOP_DUES (a negative
    amount_cents) and credits the same charter_fee_cents into COUNCIL_CASH (a positive
    amount_cents)."
    PRD §3.1: "the charter-fee sweep posts its two ledger rows, the troop's
    dues_account_cents and the council's fund_cash_cents are recomputed."

    Design: Difficulty/combinatorial_formula/recharter_sweep_evaluation_order_pinned
    """
    s = setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=30000, fill_units=600)
    troop = s["troop"]

    rechartered = validate_success(
        api.recharter_troop(troop["id"], {"expected_troop_version": s["troop_version"]}, REG), 200
    )
    assert rechartered["charter_status"] == "CHARTERED"

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    council_after = validate_success(api.get_council(s["council"]["id"], REG), 200)
    # settled TROOP_DUES before sweep = 60000 commission + 60000 (5x12000 dues) = 120000; after debit = 90000.
    assert troop_after["dues_account_cents"] == 90000, f"got {troop_after['dues_account_cents']}"
    # 600*500 fill gross 300000 + 30000 charter sweep = 330000.
    assert council_after["fund_cash_cents"] == 330000, f"got {council_after['fund_cash_cents']}"


def test_recharter_sweep_sets_chartered_status(api):
    """PRD §3.1: "On success the charter moves to CHARTERED, the charter_expires_at is
    set to the end of the council's program year ... the charter-fee sweep posts its
    two ledger rows, the troop's dues_account_cents and the council's fund_cash_cents
    are recomputed, and the troop's version increments by one."

    Design: Difficulty/combinatorial_formula/recharter_sweep_evaluation_order_pinned
    """
    s = setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=30000, fill_units=600)
    troop = s["troop"]
    rechartered = validate_success(
        api.recharter_troop(troop["id"], {"expected_troop_version": s["troop_version"]}, REG), 200
    )
    assert rechartered["charter_status"] == "CHARTERED"
    assert rechartered["version"] == s["troop_version"] + 1


def test_recharter_sweep_conserves_total_system_cash(api):
    """PRD §3.7: "The charter fee thus leaves the troop's dues account and enters
    council cash with the system's net cash unchanged — a conserved quantity — and
    the troop's dues_account_cents and the council's fund_cash_cents are both
    recomputed."

    Design: Difficulty/compensating_invariant/recharter_sweep_conserves_total_cash
    """
    s = setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=30000, fill_units=600)
    troop = s["troop"]

    troop_before = validate_success(api.get_troop(troop["id"], REG), 200)
    council_before = validate_success(api.get_council(s["council"]["id"], REG), 200)
    total_before = troop_before["dues_account_cents"] + council_before["fund_cash_cents"]

    validate_success(api.recharter_troop(troop["id"], {"expected_troop_version": troop_before["version"]}, REG), 200)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    council_after = validate_success(api.get_council(s["council"]["id"], REG), 200)
    total_after = troop_after["dues_account_cents"] + council_after["fund_cash_cents"]

    assert troop_after["dues_account_cents"] == 90000
    assert council_after["fund_cash_cents"] == 330000
    assert total_after == total_before, f"system cash not conserved: {total_before} -> {total_after}"


def test_recharter_conserved_balances_exact_values(api):
    """PRD §3.7: "it debits charter_fee_cents from TROOP_DUES (a negative amount_cents)
    and credits the same charter_fee_cents into COUNCIL_CASH (a positive amount_cents)."

    Design: Difficulty/compensating_invariant/recharter_sweep_conserves_total_cash
    """
    s = setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=30000, fill_units=600)
    troop = s["troop"]
    validate_success(api.recharter_troop(troop["id"], {"expected_troop_version": s["troop_version"]}, REG), 200)
    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    council_after = validate_success(api.get_council(s["council"]["id"], REG), 200)
    assert troop_after["dues_account_cents"] == 90000
    assert council_after["fund_cash_cents"] == 330000


def test_recharter_not_ready_rejected_on_fresh_troop(api):
    """PRD §3.1: "It requires the troop's recharter_posture to be READY — if the
    posture is anything else the request is rejected with ERR_RECHARTER_NOT_READY."

    Per PRD §3.9 the fiscal funds gate (ERR_INSUFFICIENT_TROOP_FUNDS) precedes the
    posture gate, so to isolate the posture failure the troop is funded past the
    charter fee (one FILLED 600u order settles 60000 into TROOP_DUES, well over the
    30000 fee) while leaving zero registered youth and zero cleared leaders — so the
    posture stays BLOCKED and ERR_RECHARTER_NOT_READY is the earliest applicable
    failure.

    Design: Corner/validations/recharter_not_ready_rejected
    """
    council = create_council(name="V3", charter_fee_cents=30000)
    troop = create_troop(council["id"], unit_number="V-3")
    seller = create_member(troop["id"], member_type="YOUTH", full_name="Seller")
    fr = create_live_fundraiser(council["id"], unit_price_cents=500, unit_cost_cents=200, total_inventory_units=2000)
    # FILLED order settles 60000 commission into TROOP_DUES (clears the funds gate);
    # the seller stays PENDING so registered_youth_count is 0 and posture is BLOCKED.
    place_and_fill_order(fr["id"], troop["id"], seller["id"], 600, fr["version"])

    troop_now = get_success_data(api.get_troop(troop["id"], REG))
    assert troop_now["recharter_posture"] == "BLOCKED"
    resp = api.recharter_troop(troop["id"], {"expected_troop_version": troop_now["version"]}, REG)
    validate_error(resp, ApiErrorId.ERR_RECHARTER_NOT_READY.value)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert troop_after["recharter_posture"] == "BLOCKED"


def test_recharter_stale_version_after_member_drop_rejected(api):
    """PRD §2.6: "a request whose expected_troop_version no longer matches is rejected
    with ERR_STALE_VERSION (HTTP 412). This forces the operator to re-read the troop's
    posture before committing the charter rather than acting on a stale view."

    Design: Corner/cross_cutting_complexity_layers/occ_recharter_stale_version
    """
    # 6 registered youth so dropping one spare keeps posture READY (>= 5).
    s = setup_ready_funded_troop(num_youth=5, num_leaders=2, charter_fee_cents=30000, fill_units=600, extra_youth=1)
    troop = s["troop"]
    spare = s["spares"][0]

    stale = get_success_data(api.get_troop(troop["id"], REG))
    stale_v = stale["version"]
    # Drop the spare youth -> bumps troop.version, making stale_v stale (still READY).
    get_success_data(api.drop_member(spare["id"], LEAD))

    resp = api.recharter_troop(troop["id"], {"expected_troop_version": stale_v}, REG)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert troop_after["charter_status"] == "PROVISIONAL"
