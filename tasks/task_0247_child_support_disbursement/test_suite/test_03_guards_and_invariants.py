"""Boundaries, temporal overlaps, cross-entity guards, priority pairs, and
compensating invariants.

Translates difficulty queue (A) instances under rules boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap,
priority_pair_validation_conflict, and compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    TEST_USERS,
    setup_active_order,
    setup_order_with_principal,
    setup_approved_modification,
    setup_pending_disbursement,
    setup_sent_disbursement,
    setup_order_with_proposed_enforcement,
    create_modification,
    order_version,
    create_remittance,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# boundary_precision_check / enforcement_threshold_inclusive_at_exactly_50000
# ---------------------------------------------------------------------------
def test_enforcement_threshold_inclusive_at_exactly_50000(api):
    """PRD §3.8: "Proposal is allowed only when the certifiable arrears — the order's
    `arrears_principal_cents` plus its `interest_balance_cents` — reach the statutory threshold
    of fifty thousand cents, with the boundary inclusive (an amount exactly equal to the
    threshold qualifies)"

    Design: Difficulty/boundary_precision_check/enforcement_threshold_inclusive_at_exactly_50000
    """
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    # principal exactly 50000, interest 0 -> certifiable 50000 == threshold.
    assert order["arrears_principal_cents"] == 50000
    ver = order_version(order["id"])
    enf = validate_success(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "TAX_INTERCEPT",
         "expected_support_order_version": ver}, CW), 201)
    assert enf["status"] == "PROPOSED"
    after = validate_success(api.get_support_order(order["id"], CW))
    assert after["enforcement_status"] == "INTERCEPT_PENDING"


def test_enforcement_below_threshold_at_49999_rejected(api):
    """PRD §3.8: "a delinquency below the threshold is rejected with
    `ERR_BELOW_ENFORCEMENT_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/enforcement_threshold_inclusive_at_exactly_50000
    """
    # principal 40000 < 50000 threshold (one below the boundary band).
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=40000)
    assert order["arrears_principal_cents"] == 40000
    ver = order_version(order["id"])
    validate_error(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "TAX_INTERCEPT",
         "expected_support_order_version": ver}, CW),
        ApiErrorId.ERR_BELOW_ENFORCEMENT_THRESHOLD.value)


# ---------------------------------------------------------------------------
# boundary_precision_check / interest_accrual_zero_days_no_posting
# ---------------------------------------------------------------------------
def test_interest_accrual_zero_days_posts_nothing(api):
    """PRD §3.6: "When fewer than a full day has elapsed (a day count of zero), the accrued
    amount is zero, no ledger row is posted, and `last_interest_accrual_at` is left unchanged."

    Design: Difficulty/boundary_precision_check/interest_accrual_zero_days_no_posting
    """
    api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, FO)
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    # Clock unchanged since activation stamped last_interest_accrual_at -> days == 0.
    updated = validate_success(api.accrue_interest(order["id"], FO))
    assert updated["interest_balance_cents"] == 0


def test_interest_accrual_zero_days_leaves_no_interest_ledger_row(api):
    """PRD §3.6: "Interest accrues as simple interest on arrears principal only — never on
    already-accrued interest."

    Design: Difficulty/boundary_precision_check/interest_accrual_zero_days_no_posting
    """
    api_client.set_clock({"to_iso8601": "2026-02-01T00:00:00Z"}, FO)
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    validate_success(api.accrue_interest(order["id"], FO))
    entries = validate_success(api.list_ledger_entries(
        CW, params={"support_order_id": order["id"], "entry_type": "INTEREST"}))
    assert entries == [], "zero-day accrual posts no INTEREST ledger row"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / modification_apply_requires_order_active
# ---------------------------------------------------------------------------
def test_apply_modification_blocked_when_order_suspended(api):
    """PRD §3.9: "application is permitted only while the modification's `status` is `APPROVED`
    (otherwise `ERR_INVALID_STATE`) and only when the linked order's `obligation_status` is
    `ACTIVE` (otherwise `ERR_ORDER_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/modification_apply_requires_order_active
    """
    cp, ncp, emp, order, mod = setup_approved_modification(
        current_support_cents=40000, proposed=50000)
    validate_success(api.suspend_support_order(order["id"], CW))
    ver = order_version(order["id"])
    validate_error(api.apply_modification(
        mod["id"], {"expected_support_order_version": ver}, CW),
        ApiErrorId.ERR_ORDER_NOT_ACTIVE.value)


def test_apply_modification_blocked_when_order_suspended_leaves_mod_approved(api):
    """PRD §3.9: "Applying an approved modification is the act that changes the order"

    Design: Difficulty/cross_entity_state_dependency/modification_apply_requires_order_active
    """
    cp, ncp, emp, order, mod = setup_approved_modification(
        current_support_cents=40000, proposed=50000)
    validate_success(api.suspend_support_order(order["id"], CW))
    ver = order_version(order["id"])
    validate_error(api.apply_modification(
        mod["id"], {"expected_support_order_version": ver}, CW),
        ApiErrorId.ERR_ORDER_NOT_ACTIVE.value)
    mod_after = validate_success(api.get_modification(mod["id"], CW))
    assert mod_after["status"] == "APPROVED", "a blocked apply must not advance the modification"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / disbursement_send_requires_payee_active
# ---------------------------------------------------------------------------
def test_send_disbursement_blocked_when_payee_on_hold(api):
    """PRD §3.7: "only when the disbursement's `CustodialParty` has a `payee_status` of
    `ACTIVE`; a payee on hold causes `ERR_PAYEE_ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_send_requires_payee_active
    """
    cp, ncp, emp, order, allocation, disb = setup_pending_disbursement(current_support_cents=20000)
    validate_success(api.hold_custodial_party(cp["id"], {"hold": True}, FO))
    validate_error(api.send_disbursement(disb["id"], FO),
                   ApiErrorId.ERR_PAYEE_ON_HOLD.value)


def test_send_disbursement_blocked_when_payee_on_hold_stays_pending(api):
    """PRD §3.7: "A `FinanceOfficer` sends a pending disbursement, which is permitted only
    while its `status` is `PENDING` (otherwise `ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/disbursement_send_requires_payee_active
    """
    cp, ncp, emp, order, allocation, disb = setup_pending_disbursement(current_support_cents=20000)
    validate_success(api.hold_custodial_party(cp["id"], {"hold": True}, FO))
    validate_error(api.send_disbursement(disb["id"], FO),
                   ApiErrorId.ERR_PAYEE_ON_HOLD.value)
    disb_after = validate_success(api.get_disbursement(disb["id"], FO))
    assert disb_after["status"] == "PENDING", "a blocked send must leave the disbursement PENDING"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / iwo_half_open_interval_overlap_rejected_adjacency_allowed
# ---------------------------------------------------------------------------
def test_iwo_overlapping_half_open_interval_rejected(api):
    """PRD §3.3: "A new IWO is rejected with `ERR_IWO_PERIOD_OVERLAP` if its half-open
    interval overlaps any non-`TERMINATED` IWO already recorded on the same `support_order_id`."

    Design: Difficulty/resource_temporal_overlap/iwo_half_open_interval_overlap_rejected_adjacency_allowed
    """
    cp, ncp, emp = _iwo_parties(api)
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    validate_success(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 30000,
         "effective_start_at": "2026-01-01T00:00:00Z", "effective_end_at": "2026-04-01T00:00:00Z"}, CW), 201)
    validate_error(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 30000,
         "effective_start_at": "2026-03-01T00:00:00Z", "effective_end_at": "2026-06-01T00:00:00Z"}, CW),
        ApiErrorId.ERR_IWO_PERIOD_OVERLAP.value)


def test_iwo_adjacent_half_open_interval_accepted(api):
    """PRD §3.3: "Because the interval is half-open, adjacency is allowed: an IWO whose
    `effective_start_at` equals an existing IWO's `effective_end_at` does not overlap and is
    accepted."

    Design: Difficulty/resource_temporal_overlap/iwo_half_open_interval_overlap_rejected_adjacency_allowed
    """
    cp, ncp, emp = _iwo_parties(api)
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    validate_success(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 30000,
         "effective_start_at": "2026-01-01T00:00:00Z", "effective_end_at": "2026-04-01T00:00:00Z"}, CW), 201)
    accepted = validate_success(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 30000,
         "effective_start_at": "2026-04-01T00:00:00Z", "effective_end_at": "2026-07-01T00:00:00Z"}, CW), 201)
    assert accepted["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / modification_closed_interval_boundary_touch_overlaps
# ---------------------------------------------------------------------------
def test_modification_boundary_touch_overlaps_rejected(api):
    """PRD §3.9: "A new modification is rejected with `ERR_MODIFICATION_PERIOD_OVERLAP` if its
    closed interval overlaps any non-`REJECTED` modification on the same `support_order_id`;
    because both ends are inclusive, two modifications that merely touch at a boundary instant
    do overlap and the new one is rejected."

    Design: Difficulty/resource_temporal_overlap/modification_closed_interval_boundary_touch_overlaps
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=40000)
    validate_success(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 45000,
         "coverage_start_at": "2026-01-01T00:00:00Z", "coverage_end_at": "2026-06-30T00:00:00Z"}, CW), 201)
    validate_error(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 50000,
         "coverage_start_at": "2026-06-30T00:00:00Z", "coverage_end_at": "2026-12-31T00:00:00Z"}, CW),
        ApiErrorId.ERR_MODIFICATION_PERIOD_OVERLAP.value)


def test_modification_closed_interval_overlap_rejected(api):
    """PRD §3.9: "The coverage interval is closed: it runs from `coverage_start_at` through
    `coverage_end_at` inclusive on both ends."

    Design: Difficulty/resource_temporal_overlap/modification_closed_interval_boundary_touch_overlaps
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=40000)
    validate_success(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 45000,
         "coverage_start_at": "2026-01-01T00:00:00Z", "coverage_end_at": "2026-06-30T00:00:00Z"}, CW), 201)
    validate_error(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 50000,
         "coverage_start_at": "2026-05-01T00:00:00Z", "coverage_end_at": "2026-09-30T00:00:00Z"}, CW),
        ApiErrorId.ERR_MODIFICATION_PERIOD_OVERLAP.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / allocate_invalid_state_beats_no_allocable_order
# ---------------------------------------------------------------------------
def test_allocate_returned_remittance_with_no_eligible_order_returns_invalid_state(api):
    """PRD §2.9: "Only after these gate checks pass does the system evaluate transition-state
    validity (`ERR_INVALID_STATE`), then the optimistic-concurrency version match
    (`ERR_STALE_VERSION`), and then the operation-specific business rules described throughout
    Section 3."

    Design: Difficulty/priority_pair_validation_conflict/allocate_invalid_state_beats_no_allocable_order
    """
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP T2", "ssn_last4": "1313"}, CW), 201)
    emp = validate_success(api.create_employer(
        {"legal_name": "EmpT2", "fein": "66-6666666"}, CW), 201)
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 100000, "gross_remitted_cents": 50000}, FO), 201)
    validate_success(api.return_remittance(rem["id"], FO))  # -> RETURNED (terminal)
    # Obligor has zero ACTIVE/MODIFIED orders AND the remittance is RETURNED.
    validate_error(api.allocate_remittance(rem["id"], FO),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_allocate_returned_remittance_state_check_precedes_business_rule(api):
    """PRD §3.5: "Allocation is permitted only while the remittance `status` is `RECEIVED`
    (otherwise `ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/allocate_invalid_state_beats_no_allocable_order
    """
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP T2b", "ssn_last4": "1314"}, CW), 201)
    emp = validate_success(api.create_employer(
        {"legal_name": "EmpT2b", "fein": "66-6666660"}, CW), 201)
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 100000, "gross_remitted_cents": 50000}, FO), 201)
    validate_success(api.return_remittance(rem["id"], FO))
    validate_error(api.allocate_remittance(rem["id"], FO),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# compensating_invariant / disbursement_send_return_conserves_net_disbursed_to_family
# ---------------------------------------------------------------------------
def test_disbursement_send_then_return_conserves_net_disbursed(api):
    """PRD §3.7: "the order's `net_disbursed_to_family_cents` decreases by `family_amount_cents`
    back to its pre-send value, leaving the conserved cash-out total with zero drift"

    Design: Difficulty/compensating_invariant/disbursement_send_return_conserves_net_disbursed_to_family
    """
    cp, ncp, emp, order, allocation, disb = setup_sent_disbursement(
        current_support_cents=20000, gross_remitted_cents=30000,
        assistance_status="NEVER_ASSISTED", with_principal=True)
    # family_amount 30000; after send net == 30000.
    sent_order = validate_success(api.get_support_order(order["id"], FO))
    assert sent_order["net_disbursed_to_family_cents"] == 30000
    validate_success(api.return_disbursement(disb["id"], FO))
    after = validate_success(api.get_support_order(order["id"], FO))
    assert after["net_disbursed_to_family_cents"] == 0, (
        "send-then-return leaves net_disbursed_to_family_cents at its pre-send value")


def test_disbursement_send_return_leaves_owed_buckets_untouched(api):
    """PRD §3.7: "Crucially, the order's owed buckets — `current_support_due_cents`,
    `interest_balance_cents`, and `arrears_principal_cents` — are unaffected by both the send
    and the return, because disbursement sits downstream of collection."

    Design: Difficulty/compensating_invariant/disbursement_send_return_conserves_net_disbursed_to_family
    """
    cp, ncp, emp, order, allocation, disb = setup_sent_disbursement(
        current_support_cents=20000, gross_remitted_cents=30000,
        assistance_status="NEVER_ASSISTED", with_principal=True)
    validate_success(api.return_disbursement(disb["id"], FO))
    after = validate_success(api.get_support_order(order["id"], FO))
    # Order had principal 20000, allocation paid 10000 -> principal 10000; unaffected by disb.
    assert after["arrears_principal_cents"] == 10000


# ---------------------------------------------------------------------------
# compensating_invariant / enforcement_propose_withdraw_conserves_orders_under_enforcement_count
# ---------------------------------------------------------------------------
def test_enforcement_withdraw_returns_status_to_none(api):
    """PRD §3.8: "withdrawal moves the action to the terminal `WITHDRAWN` and, as a cross-entity
    effect, returns the order's `enforcement_status` from `INTERCEPT_PENDING` to `NONE`."

    Design: Difficulty/compensating_invariant/enforcement_propose_withdraw_conserves_orders_under_enforcement_count
    """
    cp, ncp, emp, order, enf = setup_order_with_proposed_enforcement(
        current_support_cents=50000, action_type="LICENSE_SUSPENSION")
    enf_after = validate_success(api.withdraw_enforcement_action(enf["id"], CW))
    assert enf_after["status"] == "WITHDRAWN"
    order_after = validate_success(api.get_support_order(order["id"], CW))
    assert order_after["enforcement_status"] == "NONE"


def test_enforcement_propose_then_withdraw_conserves_enforcement_dimension(api):
    """PRD §3.8: "A successful proposal creates the action with `status` of `PROPOSED` and,
    as a cross-entity effect, moves the order's `enforcement_status` from `NONE` to
    `INTERCEPT_PENDING` and increments the order's `version`."

    Design: Difficulty/compensating_invariant/enforcement_propose_withdraw_conserves_orders_under_enforcement_count
    """
    cp, ncp, emp, order, enf = setup_order_with_proposed_enforcement(
        current_support_cents=50000, action_type="LICENSE_SUSPENSION")
    assert order["enforcement_status"] == "INTERCEPT_PENDING"
    validate_success(api.withdraw_enforcement_action(enf["id"], CW))
    order_after = validate_success(api.get_support_order(order["id"], CW))
    # propose (+1 into enforcement) then withdraw (-1) leaves the order back at NONE.
    assert order_after["enforcement_status"] == "NONE"


# ---------------------------------------------------------------------------
# helpers local to this file
# ---------------------------------------------------------------------------
def _iwo_parties(api):
    cp = validate_success(api.create_custodial_party(
        {"full_name": "CP O1", "state_code": "CA"}, CW), 201)
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP O1", "ssn_last4": "1818"}, CW), 201)
    emp = validate_success(api.create_employer(
        {"legal_name": "EmpO1", "fein": "88-8888888"}, CW), 201)
    return cp, ncp, emp
