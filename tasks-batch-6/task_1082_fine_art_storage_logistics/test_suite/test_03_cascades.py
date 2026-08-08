"""Transitive cascades and conserved-ledger invariants."""
from test_helpers import (
    validate_success, get_success_data,
    make_client, make_vault, make_artwork, make_placement,
    setup_active_international_loan, setup_approved_loan, setup_ready_transport,
    setup_issued_invoice,
    condition_report_payload,
    REG, COORD, BILL,
    api_client as api,
)


# ==========================================================================
# Loan return: depth-3 cascade Loan -> Artwork -> Placement -> Vault (+carnet)
# ==========================================================================
def test_loan_return_restores_artwork_and_placement():
    """PRD §3.6: "It reverses the custody cascade: the artwork's `custody_status`
    moves from `ON_LOAN` back to `IN_STORAGE`, its suspended placement is
    reactivated — moving that placement from `SUSPENDED` to `ACTIVE` and
    incrementing the vault's `occupied_slots` by one (subject to the vault still
    having a free slot, else `ERR_VAULT_FULL`) — and the loan's carnet, if it is
    in `ISSUED` or `ACTIVATED`, is discharged to `DISCHARGED`."

    Design: Difficulty/transitive_cascade/loan_return_cascade_depth3
    """
    s = setup_active_international_loan()
    data = validate_success(api.transition_loan(s["loan"]["id"], {"to_status": "RETURNED"}, COORD))
    assert data["status"] == "RETURNED", data
    art = validate_success(api.get_artwork(s["artwork"]["id"], REG))
    assert art["custody_status"] == "IN_STORAGE", art
    placement = validate_success(api.get_placement(s["placement"]["id"], REG))
    assert placement["status"] == "ACTIVE", placement


def test_loan_return_discharges_carnet_and_restores_slot():
    """PRD §3.6: "It reverses the custody cascade: the artwork's `custody_status`
    moves from `ON_LOAN` back to `IN_STORAGE`, its suspended placement is
    reactivated — moving that placement from `SUSPENDED` to `ACTIVE` and
    incrementing the vault's `occupied_slots` by one (subject to the vault still
    having a free slot, else `ERR_VAULT_FULL`) — and the loan's carnet, if it is
    in `ISSUED` or `ACTIVATED`, is discharged to `DISCHARGED`."

    Design: Difficulty/transitive_cascade/loan_return_cascade_depth3
    """
    s = setup_active_international_loan()
    get_success_data(api.transition_loan(s["loan"]["id"], {"to_status": "RETURNED"}, COORD))
    vault = validate_success(api.get_vault(s["vault"]["id"], REG))
    assert vault["occupied_slots"] == 1, vault
    carnet = validate_success(api.get_carnet(s["carnet"]["id"], COORD))
    assert carnet["status"] == "DISCHARGED", carnet


# ==========================================================================
# Condition damage: depth-3 cascade ConditionReport -> Artwork -> Loan -> Carnet
# ==========================================================================
def test_major_damage_cancels_approved_loan():
    """PRD §3.3: "When a report notes damage and grades the work `F`, an artwork
    that was `SOUND` or `MINOR_DAMAGE` moves to `MAJOR_DAMAGE`."
    PRD §3.3: "the moment an artwork becomes `MAJOR_DAMAGE`, every loan agreement
    for that artwork currently in `APPROVED` or `ACTIVE` status is cancelled,
    transitioning to `CANCELLED`, and for each such cancelled loan any non-terminal
    carnet (one still in `ISSUED` or `ACTIVATED`) is discharged to `DISCHARGED`."

    Design: Difficulty/transitive_cascade/condition_damage_cascade_depth3
    """
    s = setup_approved_loan(is_international=True, with_carnet=True)
    get_success_data(api.create_condition_report(
        condition_report_payload(s["artwork"]["id"], report_type="POST_TRANSIT",
                                 condition_grade="F", damage_noted=True,
                                 notes="structural crack after handling"), REG))
    art = validate_success(api.get_artwork(s["artwork"]["id"], REG))
    assert art["condition_status"] == "MAJOR_DAMAGE", art
    loan = validate_success(api.get_loan(s["loan"]["id"], REG))
    assert loan["status"] == "CANCELLED", loan


def test_major_damage_discharges_loan_carnet():
    """PRD §3.3: "the moment an artwork becomes `MAJOR_DAMAGE`, every loan
    agreement for that artwork currently in `APPROVED` or `ACTIVE` status is
    cancelled, transitioning to `CANCELLED`, and for each such cancelled loan any
    non-terminal carnet (one still in `ISSUED` or `ACTIVATED`) is discharged to
    `DISCHARGED`."

    Design: Difficulty/transitive_cascade/condition_damage_cascade_depth3
    """
    s = setup_approved_loan(is_international=True, with_carnet=True)
    get_success_data(api.create_condition_report(
        condition_report_payload(s["artwork"]["id"], report_type="POST_TRANSIT",
                                 condition_grade="F", damage_noted=True), REG))
    carnet = validate_success(api.get_carnet(s["carnet"]["id"], COORD))
    assert carnet["status"] == "DISCHARGED", carnet


# ==========================================================================
# Compensating invariant: vault slot conservation
# ==========================================================================
def test_place_then_release_returns_slots_to_zero():
    """PRD §3.2: "When the placement was `ACTIVE` at release, the vault's
    `occupied_slots` is decremented by one; when it was already `SUSPENDED`, the
    slot was surrendered earlier and `occupied_slots` is left unchanged."

    Design: Difficulty/compensating_invariant/vault_slot_conservation
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=2)
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    p = make_placement(a["id"], v["id"])
    get_success_data(api.transition_placement(p["id"], {"to_status": "RELEASED"}, REG))
    vault = validate_success(api.get_vault(v["id"], REG))
    assert vault["occupied_slots"] == 0, vault


def test_released_placement_reaches_terminal_state():
    """PRD §3.2: "A registrar releases a placement by transitioning it to the
    terminal `RELEASED` status, permitted from either `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/compensating_invariant/vault_slot_conservation
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=2)
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    p = make_placement(a["id"], v["id"])
    data = validate_success(api.transition_placement(p["id"], {"to_status": "RELEASED"}, REG))
    assert data["status"] == "RELEASED", data


# ==========================================================================
# Compensating invariant: client outstanding-balance ledger
# ==========================================================================
def test_issue_then_void_restores_balance():
    """PRD §3.8: "Voiding an issued invoice moves it to `VOID` and likewise
    decrements the balance by `total_cents`, a compensating action that restores
    the ledger; a `DRAFT` invoice may also be voided directly, and because it was
    never issued that void makes no balance adjustment."

    Design: Difficulty/compensating_invariant/invoice_outstanding_conservation
    """
    s = setup_issued_invoice(line_amount=10000)
    get_success_data(api.transition_invoice(s["invoice"]["id"], {"to_status": "VOID"}, BILL))
    client = validate_success(api.get_client(s["client"]["id"], REG))
    assert client["outstanding_balance_cents"] == 0, client


def test_voided_invoice_total_preserved():
    """PRD §3.8: "The `total_cents` is `subtotal_cents` plus `tax_cents`."
    PRD §3.8: "Voiding an issued invoice moves it to `VOID` and likewise decrements
    the balance by `total_cents`, a compensating action that restores the ledger".

    Design: Difficulty/compensating_invariant/invoice_outstanding_conservation
    """
    s = setup_issued_invoice(line_amount=10000)
    data = validate_success(api.transition_invoice(s["invoice"]["id"], {"to_status": "VOID"}, BILL))
    # subtotal 10000 + round(10000*0.0875)=875 -> total 10875
    assert data["total_cents"] == 10875, data
    assert data["status"] == "VOID", data


# ==========================================================================
# Transport completion cascade (corner)
# ==========================================================================
def test_transport_completed_cascade_returns_artwork_to_storage():
    """PRD §3.4: "The cascade reverses the start: the artwork's `custody_status`
    returns from `IN_TRANSIT` to `IN_STORAGE`, and the crate returns from `IN_USE`
    to `READY`."
    PRD §3.4: "On completion the system records `actual_hours` and recomputes
    `transport_charge_cents` by the same rule as the estimate but substituting the
    logged `actual_hours` for the estimated hours (the rigging surcharge is applied
    identically)."

    Design: Corner/cross_cutting/transport_completed_cascade_returns_artwork_to_storage
    """
    s = setup_ready_transport(requires_rigging=False, estimated_hours=2, place_artwork=True)
    get_success_data(api.transition_transport_job(s["job"]["id"], {"to_status": "IN_PROGRESS"}, COORD))
    data = validate_success(api.transition_transport_job(
        s["job"]["id"], {"to_status": "COMPLETED", "actual_hours": 2}, COORD))
    # round(2*9000)+0 = 18000
    assert data["transport_charge_cents"] == 18000, data
    art = validate_success(api.get_artwork(s["artwork"]["id"], REG))
    assert art["custody_status"] == "IN_STORAGE", art
    crate = validate_success(api.get_crate(s["crate"]["id"], COORD))
    assert crate["status"] == "READY", crate
