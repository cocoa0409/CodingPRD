"""Transitive cascades: depth-3 chains originating at foreclose and at escalate.

Difficulty: transitive_cascade.
"""
from test_helpers import (
    get_success_data, validate_success,
    create_resort, create_owner, create_inventory_unit, create_active_contract,
    create_issued_invoice, setup_lien_case, get_points_account,
    create_reservation_payload, set_clock, make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


def test_foreclose_cascade_case_then_contract_then_invoice(api):
    """PRD §3.9: "A `DEEDED` contract is foreclosed: the case moves from `LIEN` to `FORECLOSURE` and
    the contract cascades from `SUSPENDED` to `FORECLOSED`."
    PRD §3.9: "In either branch the contract's terminal transition writes off its `DELINQUENT`
    invoices to `WRITTEN_OFF".

    Design: Difficulty/transitive_cascade/foreclose_cascade_depth3_case_contract_invoice
    """
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=2, resort_overrides={"foreclosure_threshold_periods": 2},
        contract_overrides={"ownership_type": "DEEDED", "annual_points_allotment": 10000})

    closed = validate_success(api.foreclose_delinquency_case(case["id"], _CO))
    # hop 1: case LIEN -> FORECLOSURE
    assert closed["status"] == "FORECLOSURE", f"hop1: case FORECLOSURE, got {closed['status']}"
    # hop 2: contract SUSPENDED -> FORECLOSED (caused by hop 1)
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "FORECLOSED", f"hop2: contract FORECLOSED, got {c['status']}"
    # hop 3: DELINQUENT invoice -> WRITTEN_OFF (caused by hop 2)
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["status"] == "WRITTEN_OFF", f"hop3: invoice WRITTEN_OFF, got {inv['status']}"


def test_foreclose_cascade_cancels_nonterminal_reservations(api):
    """PRD §3.9: "In either branch the contract's terminal transition writes off its `DELINQUENT`
    invoices to `WRITTEN_OFF`, cancels all non-terminal reservations on the contract
    (releasing their committed points)".

    Design: Difficulty/transitive_cascade/foreclose_cascade_depth3_case_contract_invoice
    """
    # A CONFIRMED reservation exists on the contract before foreclosure; the
    # terminal transition cascades it to CANCELLED.
    resort = create_resort(delinquency_grace_days=30, foreclosure_threshold_periods=2)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=23, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"],
                                      ownership_type="DEEDED", annual_points_allotment=10000)
    # Confirm a reservation on the unit.
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    get_success_data(api.confirm_reservation(resv["id"], headers))

    # Drive delinquency to LIEN at threshold (escalation suspends contract,
    # cancelling HELD only; the CONFIRMED reservation survives until foreclosure).
    invoice = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")
    get_success_data(api.mark_invoice_delinquent(invoice["id"], _RM))
    cases, _m = _list(api.list_delinquency_cases(_CO, params={"contract_id": contract["id"]}))
    case = cases[0]
    get_success_data(api.escalate_delinquency_case(case["id"], _CO))
    get_success_data(api.escalate_delinquency_case(case["id"], _CO))

    get_success_data(api.foreclose_delinquency_case(case["id"], _CO))
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "FORECLOSED", f"contract FORECLOSED, got {c['status']}"
    r = get_success_data(api.get_reservation(resv["id"], headers))
    assert r["status"] == "CANCELLED", \
        f"non-terminal reservation cancelled by foreclosure cascade, got {r['status']}"


def test_escalate_cascade_case_then_contract_then_held_reservation(api):
    """PRD §3.8: "The first escalation to `LIEN` also cascades the owning contract from `ACTIVE` to
    `SUSPENDED`, and that suspension itself cancels every `HELD` reservation on the
    contract (each moving from `HELD` to `CANCELLED`)."

    Design: Difficulty/transitive_cascade/escalate_cascade_depth3_case_contract_held_reservation
    """
    # Build: active contract + GOLD unit + a HELD reservation, then an ISSUED
    # invoice gone DELINQUENT (NOTICE case). Escalate -> LIEN cascade.
    resort = create_resort(delinquency_grace_days=30)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=22, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    assert resv["status"] == "HELD"

    invoice = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")
    get_success_data(api.mark_invoice_delinquent(invoice["id"], _RM))
    data, _meta = _list(api.list_delinquency_cases(_CO, params={"contract_id": contract["id"]}))
    case = data[0]

    escalated = validate_success(api.escalate_delinquency_case(case["id"], _CO))
    # hop 1: case NOTICE -> LIEN
    assert escalated["status"] == "LIEN", f"hop1: case LIEN, got {escalated['status']}"
    # hop 2: contract ACTIVE -> SUSPENDED (caused by hop 1)
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "SUSPENDED", f"hop2: contract SUSPENDED, got {c['status']}"
    # hop 3: HELD reservation -> CANCELLED (caused by hop 2 suspending the contract)
    r = get_success_data(api.get_reservation(resv["id"], headers))
    assert r["status"] == "CANCELLED", f"hop3: reservation CANCELLED, got {r['status']}"


def test_escalate_first_lien_suspends_contract(api):
    """PRD §3.8: "The first escalation to `LIEN` also cascades the owning contract from `ACTIVE` to
    `SUSPENDED".

    Design: Difficulty/transitive_cascade/escalate_cascade_depth3_case_contract_held_reservation
    """
    # Same trigger (escalate) but with NO HELD reservation present: the depth-2
    # link (case NOTICE->LIEN causing contract ACTIVE->SUSPENDED) is isolated.
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=1, resort_overrides={"foreclosure_threshold_periods": 2},
        contract_overrides={"annual_points_allotment": 10000})
    assert case["status"] == "LIEN", f"case LIEN, got {case['status']}"
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "SUSPENDED", \
        f"contract SUSPENDED by first escalation, got {c['status']}"


def _list(response):
    body = response.json()
    return body["data"], body.get("meta", {})
