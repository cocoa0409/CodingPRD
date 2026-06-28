"""Disbursement lifecycle, the trust ledger, OCC on create, settle/void conservation,
and the trust-lock cross-entity dependency.

Translates difficulty rules dual_variant_calc (cleared trust balance),
non_linear_state_machine (settle->void revert), transitive_cascade (complete locks trust),
cross_entity_state_dependency (approve requires unlocked trust), compensating_invariant
(trust funds conserved); and corner sections state_machines / validations / errors /
cross_cutting (OCC success).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_qi_coordinator_headers, make_settlement_officer_headers,
    assert_trust_conserved,
    setup_closed_exchange, setup_requested_disbursement, setup_settled_disbursement,
    setup_completed_exchange,
    create_requested_disbursement, get_trust, trust_version, set_clock,
)
from test_helpers.factories import create_disbursement_payload


# ── Cleared trust-balance variant ────────────────────────────────────

def test_available_balance_counts_only_settled_disbursements(api):
    """PRD §3.6: "Its `available_balance` is always the `deposited_amount` less the sum
    of the `amount` of every disbursement on the exchange whose `settlement_status` is
    `SETTLED`."

    Design: Difficulty/dual_variant_calc/trust_balance_cleared_vs_reserved_variant
    """
    exchange, trust, dis = setup_requested_disbursement("QI_FEE", 1500, "coord-fwd")
    officer = make_settlement_officer_headers("officer-1")
    # The disbursement is REQUESTED (not yet approved/settled).
    trust_read = validate_success(api.list_trust(exchange["id"], officer))[0]
    assert trust_read["available_balance"] == pytest.approx(350000.00, abs=0.01), (
        "REQUESTED disbursement is not deducted from available_balance (cleared variant)"
    )
    assert trust_read["deposited_amount"] == pytest.approx(350000.00, abs=0.01)


def test_available_balance_deducts_only_on_settle(api):
    """PRD §3.6: "Its `available_balance` is always the `deposited_amount` less the sum
    of the `amount` of every disbursement on the exchange whose `settlement_status` is
    `SETTLED`."

    Design: Difficulty/dual_variant_calc/trust_balance_cleared_vs_reserved_variant
    """
    # Before approval the REQUESTED 1500 is NOT deducted; after settle it IS.
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-fwd2", "officer-1")
    trust_after = get_trust(exchange["id"], "coord-fwd2")
    assert trust_after["available_balance"] == pytest.approx(348500.00, abs=0.01), (
        "the deduction of 1500 lands only once the disbursement becomes SETTLED"
    )


# ── Settle / void revert cycle and conservation ──────────────────────

def test_settle_then_void_restores_trust_credit(api):
    """PRD §3.6: "Voiding a disbursement that is currently `SETTLED` requires the trust
    to be unlocked; it moves the disbursement to `VOIDED`, credits the trust's
    `available_balance` back by the disbursement's `amount` as compensation that
    restores the conserved trust quantity."

    Design: Difficulty/non_linear_state_machine/disbursement_settle_then_void_revert_cycle
    """
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-void", "officer-1")
    officer = make_settlement_officer_headers("officer-1")
    # After settle the trust is 348500.
    trust_settled = get_trust(exchange["id"], "coord-void")
    assert trust_settled["available_balance"] == pytest.approx(348500.00, abs=0.01)
    voided = validate_success(api.void_disbursement(dis["id"], officer))
    assert voided["settlement_status"] == "VOIDED"
    trust_after = get_trust(exchange["id"], "coord-void")
    assert trust_after["available_balance"] == pytest.approx(350000.00, abs=0.01), (
        "void credits the 1500 back, restoring available_balance to 350000"
    )


def test_settled_disbursement_can_be_voided_revert_edge(api):
    """PRD §3.6: "Voiding a disbursement that is currently `SETTLED` requires the trust
    to be unlocked; it moves the disbursement to `VOIDED` ... and increments both the
    disbursement's `version` and the trust's `version`."

    Design: Difficulty/non_linear_state_machine/disbursement_settle_then_void_revert_cycle
    """
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-void2", "officer-1")
    assert dis["settlement_status"] == "SETTLED"
    officer = make_settlement_officer_headers("officer-1")
    voided = validate_success(api.void_disbursement(dis["id"], officer))
    assert voided["settlement_status"] == "VOIDED", "SETTLED -> VOIDED is the compensating revert edge"
    assert voided["version"] > dis["version"], "voiding bumps the disbursement version"


def test_trust_funds_conserved_under_settle_void(api):
    """PRD §3.6: "Its `available_balance` is always the `deposited_amount` less the sum
    of the `amount` of every disbursement on the exchange whose `settlement_status` is
    `SETTLED`."

    Design: Difficulty/compensating_invariant/trust_funds_conserved_under_settle_void
    """
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-cn1", "officer-1")
    officer = make_settlement_officer_headers("officer-1")
    validate_success(api.void_disbursement(dis["id"], officer))
    trust_after = get_trust(exchange["id"], "coord-cn1")
    assert trust_after["deposited_amount"] == pytest.approx(350000.00, abs=0.01)
    # After void no disbursement is SETTLED, so settled_total == 0.
    assert_trust_conserved(trust_after, settled_total=0.0)
    assert trust_after["available_balance"] == pytest.approx(350000.00, abs=0.01)


def test_trust_invariant_holds_at_settled_midpoint(api):
    """PRD §3.6: "Its `available_balance` is always the `deposited_amount` less the sum
    of the `amount` of every disbursement on the exchange whose `settlement_status` is
    `SETTLED`."

    Design: Difficulty/compensating_invariant/trust_funds_conserved_under_settle_void
    """
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-cn1b", "officer-1")
    trust_settled = get_trust(exchange["id"], "coord-cn1b")
    # One SETTLED disbursement of 1500: deposited == available + 1500.
    assert_trust_conserved(trust_settled, settled_total=1500.0)
    assert trust_settled["available_balance"] == pytest.approx(348500.00, abs=0.01)


def test_void_requested_disbursement_no_trust_effect(api):
    """PRD §3.6: "Voiding a disbursement that is still `REQUESTED` — one that was never
    debited — simply moves it to `VOIDED` with no trust effect and increments only the
    disbursement's `version`."

    Design: Corner/state_machines/void_requested_disbursement_no_trust_effect
    """
    exchange, trust, dis = setup_requested_disbursement("QI_FEE", 1500, "coord-vr")
    officer = make_settlement_officer_headers("officer-1")
    voided = validate_success(api.void_disbursement(dis["id"], officer))
    assert voided["settlement_status"] == "VOIDED"
    trust_after = get_trust(exchange["id"], "coord-vr")
    assert trust_after["available_balance"] == pytest.approx(350000.00, abs=0.01), (
        "voiding a never-settled disbursement leaves available_balance unchanged"
    )


def test_approve_already_settled_disbursement_rejected(api):
    """PRD §3.6: "Approval — moving the disbursement from `REQUESTED` to `SETTLED`."
    PRD §2.10: "state-machine legality (`ERR_INVALID_STATE` when the target entity is
    not in a state from which the requested transition is defined)."

    Design: Corner/state_machines/approve_already_settled_disbursement_returns_invalid_state
    """
    exchange, trust, dis = setup_settled_disbursement("QI_FEE", 1500, "coord-idm", "officer-1")
    officer = make_settlement_officer_headers("officer-1")
    resp = api.approve_disbursement(dis["id"], officer)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    trust_after = get_trust(exchange["id"], "coord-idm")
    assert trust_after["available_balance"] == pytest.approx(348500.00, abs=0.01), (
        "rejected re-approval must not produce a second debit"
    )


# ── Insufficient funds ───────────────────────────────────────────────

def test_approve_overdraw_rejected_insufficient_funds(api):
    """PRD §3.6: "an approval whose amount exceeds the available balance is rejected
    with `ERR_INSUFFICIENT_TRUST_FUNDS`."

    Design: Corner/validations/insufficient_trust_funds_on_overdraw_approval
    """
    exchange, trust, dis = setup_requested_disbursement("ACQUISITION", 400000, "coord-ovr")
    officer = make_settlement_officer_headers("officer-1")
    resp = api.approve_disbursement(dis["id"], officer)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TRUST_FUNDS.value)


# ── Trust lock cross-entity dependency ───────────────────────────────

def test_complete_exchange_locks_trust(api):
    """PRD §3.7: "Completion recomputes the posture to `COMPLETED`, locks the qualified
    trust by setting `is_locked` to true (the cascade from exchange complete to trust
    lock), sets the exchange `status` to `COMPLETED`, and increments the exchange's
    `version`."

    Design: Difficulty/transitive_cascade/complete_exchange_cascade_depth2_trust_lock
    """
    exchange, trust, idn, cand, rp = setup_completed_exchange("coord-cmp")
    headers = make_qi_coordinator_headers("coord-cmp")
    assert exchange["compliance_posture"] == "COMPLETED"
    assert exchange["status"] == "COMPLETED"
    trust_after = validate_success(api.list_trust(exchange["id"], headers))[0]
    assert trust_after["is_locked"] is True, "completing the exchange must lock the trust"


def test_complete_sets_posture_and_status_completed(api):
    """PRD §3.7: "Completion recomputes the posture to `COMPLETED` ... sets the exchange
    `status` to `COMPLETED`, and increments the exchange's `version`."

    Design: Difficulty/transitive_cascade/complete_exchange_cascade_depth2_trust_lock
    """
    exchange, trust, idn, cand, rp = setup_completed_exchange("coord-cmp3")
    assert exchange["compliance_posture"] == "COMPLETED"
    assert exchange["status"] == "COMPLETED"


def test_approve_on_locked_trust_after_complete_rejected(api):
    """PRD §3.7: "A locked trust rejects all new disbursement creates and approvals."

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_unlocked_trust
    """
    # Build a completed exchange that has a leftover REQUESTED disbursement created
    # before completion.
    set_clock("2026-03-01T00:00:00Z", "coord-lkt")
    from test_helpers.fixtures import setup_finalized_identification
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-lkt")
    headers = make_qi_coordinator_headers("coord-lkt")
    dis = create_requested_disbursement(exchange["id"], "QI_FEE", 1500, "coord-lkt")
    from test_helpers.factories import create_replacement_property_payload
    validate_success(
        api.create_replacement_property(
            exchange["id"],
            create_replacement_property_payload(cands[0]["id"], purchase_price=420000, replacement_debt=120000),
            headers,
        ),
        expected_status=201,
    )
    validate_success(api.complete_exchange(exchange["id"], headers))
    officer = make_settlement_officer_headers("officer-1")
    resp = api.approve_disbursement(dis["id"], officer)
    validate_error(resp, ApiErrorId.ERR_TRUST_LOCKED.value)
    after = validate_success(api.get_disbursement(dis["id"], officer))
    assert after["settlement_status"] == "REQUESTED", "rejected approval leaves disbursement REQUESTED"


def test_approve_on_locked_trust_after_fail_rejected(api):
    """PRD §3.6: "An approval against a locked trust is rejected with
    `ERR_TRUST_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_approve_requires_unlocked_trust
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-lkt2")
    headers = make_qi_coordinator_headers("coord-lkt2")
    dis = create_requested_disbursement(closed["id"], "QI_FEE", 1500, "coord-lkt2")
    # Drive the exchange to FAILED, which locks the trust.
    set_clock("2026-09-01T00:00:00Z", "coord-lkt2")
    validate_success(api.fail_exchange(closed["id"], headers))
    officer = make_settlement_officer_headers("officer-1")
    resp = api.approve_disbursement(dis["id"], officer)
    validate_error(resp, ApiErrorId.ERR_TRUST_LOCKED.value)


# ── OCC on disbursement create ───────────────────────────────────────

def test_disbursement_create_with_current_trust_version_succeeds(api):
    """PRD §2.11: "A create request must carry `expected_qualified_trust_version`
    holding the client's last observed `version` of the exchange's `QualifiedTrust`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_trust_version_disbursement_create_succeeds
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-occ")
    headers = make_qi_coordinator_headers("coord-occ")
    ver = trust_version(closed["id"], "coord-occ")
    resp = api.create_disbursement(
        create_disbursement_payload(closed["id"], "QI_FEE", 1500, ver), headers
    )
    data = validate_success(resp, expected_status=201)
    assert data["settlement_status"] == "REQUESTED", "create yields a REQUESTED disbursement"


def test_disbursement_create_with_stale_trust_version_rejected(api):
    """PRD §2.11: "If that value does not equal the trust's current `version` — meaning
    another writer has advanced the trust since the client last read it — the create is
    rejected with `ERR_STALE_TRUST_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_trust_version_on_disbursement_create
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-stl")
    headers = make_qi_coordinator_headers("coord-stl")
    stale_ver = trust_version(closed["id"], "coord-stl")
    # Approve a first disbursement to advance the trust version above stale_ver.
    first = create_requested_disbursement(closed["id"], "QI_FEE", 1500, "coord-stl")
    officer = make_settlement_officer_headers("officer-1")
    validate_success(api.approve_disbursement(first["id"], officer))
    # Now the trust version has advanced; the stale value must be rejected.
    resp = api.create_disbursement(
        create_disbursement_payload(closed["id"], "ACQUISITION", 1000, stale_ver), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TRUST_VERSION.value)


# ── Listing ──────────────────────────────────────────────────────────

def test_qicoordinator_cannot_approve_disbursement(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/qicoordinator_cannot_approve_disbursement
    """
    exchange, trust, dis = setup_requested_disbursement("QI_FEE", 1500, "coord-au")
    # Approve is a SettlementOfficer-exclusive op; a coordinator caller is unauthorized.
    coord = make_qi_coordinator_headers("coord-au")
    resp = api.approve_disbursement(dis["id"], coord)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_disbursements_filtered_by_exchange_id(api):
    """PRD §3.6: "Disbursements are fetchable individually and listable with optional
    `exchange_id` and `replacement_property_id` filters."

    Design: Corner/endpoints/list_disbursements_filtered_by_exchange_id
    """
    exchange, trust, dis = setup_requested_disbursement("QI_FEE", 1500, "coord-ld")
    officer = make_settlement_officer_headers("officer-1")
    resp = api.list_disbursements(officer, params={"exchange_id": exchange["id"]})
    data, meta = validate_paginated(resp)
    assert all(d["exchange_id"] == exchange["id"] for d in data), (
        "every returned disbursement must belong to the filtered exchange"
    )
