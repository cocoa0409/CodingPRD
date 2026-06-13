"""Validation errors, RBAC denials, listing/pagination, OCC, and consistency
breadth.

Translates corner queue (B) instances under sections validations, errors, rbac,
endpoints, cross_cutting_complexity_layers, and consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_active_order,
    setup_order_with_principal,
    setup_allocation_for_order,
    setup_approved_modification,
    order_version,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]
SUP = TEST_USERS["supervisor_headers"]


def _parties(api, ssn="1015"):
    cp = validate_success(api.create_custodial_party({"full_name": "CP", "state_code": "CA"}, CW), 201)
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP", "ssn_last4": ssn}, CW), 201)
    return cp, ncp


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------
def test_activate_zero_current_support_returns_invalid_amount(api):
    """PRD §3.2: "Activation from `ESTABLISHED` additionally requires that
    `current_support_cents` be greater than zero, failing with `ERR_INVALID_AMOUNT` otherwise."

    Design: Corner/validations/activate_zero_current_support_returns_invalid_amount
    """
    cp, ncp = _parties(api, ssn="1015")
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 0}, CW), 201)
    validate_error(api.activate_support_order(order["id"], CW),
                   ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_allocate_zero_distributable_returns_nothing_to_allocate(api):
    """PRD §3.5: "and the remittance's `distributable_cents` must be greater than zero, failing
    with `ERR_NOTHING_TO_ALLOCATE`."

    Design: Corner/validations/allocate_zero_distributable_returns_nothing_to_allocate
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=30000)
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 100000, "gross_remitted_cents": 0}, FO), 201)
    validate_error(api.allocate_remittance(rem["id"], FO),
                   ApiErrorId.ERR_NOTHING_TO_ALLOCATE.value)


def test_allocate_no_eligible_order_returns_no_allocable_order(api):
    """PRD §3.5: "the obligor must have at least one eligible support order — one whose
    `obligation_status` is `ACTIVE` or `MODIFIED` — or the request fails with
    `ERR_NO_ALLOCABLE_ORDER`"

    Design: Corner/validations/allocate_no_eligible_order_returns_no_allocable_order
    """
    cp, ncp = _parties(api, ssn="1017")
    emp = validate_success(api.create_employer({"legal_name": "Emp", "fein": "25-2626262"}, CW), 201)
    # ESTABLISHED order only (never activated -> not eligible).
    validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 100000, "gross_remitted_cents": 30000}, FO), 201)
    validate_error(api.allocate_remittance(rem["id"], FO),
                   ApiErrorId.ERR_NO_ALLOCABLE_ORDER.value)


def test_enforcement_below_threshold_rejected(api):
    """PRD §3.8: "a delinquency below the threshold is rejected with
    `ERR_BELOW_ENFORCEMENT_THRESHOLD`."

    Design: Corner/validations/enforcement_below_threshold_rejected
    """
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=40000)
    # certifiable arrears 40000 < 50000 threshold.
    ver = order_version(order["id"])
    validate_error(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "TAX_INTERCEPT",
         "expected_support_order_version": ver}, CW),
        ApiErrorId.ERR_BELOW_ENFORCEMENT_THRESHOLD.value)


def test_fk_mismatch_allocation_not_on_named_order(api):
    """PRD §2.6: "a `Disbursement` whose `allocation_id` does not belong to the support order
    named in its `support_order_id`. A compatibility failure of this kind is reported as
    `ERR_FK_MISMATCH`."

    Design: Corner/validations/fk_mismatch_allocation_not_on_named_order
    """
    cp, ncp = _parties(api, ssn="1019")
    emp = validate_success(api.create_employer({"legal_name": "Emp", "fein": "26-2727272"}, CW), 201)
    o1 = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 20000}, CW), 201)
    o2 = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 20000}, CW), 201)
    validate_success(api.activate_support_order(o1["id"], CW))
    validate_success(api.activate_support_order(o2["id"], CW))
    rem = validate_success(api.create_remittance(
        {"employer_id": emp["id"], "noncustodial_party_id": ncp["id"],
         "disposable_earnings_cents": 100000, "gross_remitted_cents": 20000}, FO), 201)
    validate_success(api.allocate_remittance(rem["id"], FO))
    alloc_o1 = validate_success(api.list_allocations(
        FO, params={"remittance_id": rem["id"], "support_order_id": o1["id"]}))[0]
    # Disbursement names O2 but uses O1's allocation slice.
    validate_error(api.create_disbursement(
        {"support_order_id": o2["id"], "custodial_party_id": cp["id"],
         "allocation_id": alloc_o1["id"]}, FO),
        ApiErrorId.ERR_FK_MISMATCH.value)


def test_terminate_with_outstanding_arrears_only_returns_arrears_outstanding(api):
    """PRD §3.2: "the order may be terminated only when both `arrears_principal_cents` and
    `interest_balance_cents` are zero, failing with `ERR_ARREARS_OUTSTANDING` if either remains"

    Design: Corner/validations/terminate_with_outstanding_arrears_only_returns_arrears_outstanding
    """
    # arrears principal 50000, no enforcement -> isolated single-failure scenario.
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    validate_error(api.terminate_support_order(order["id"], CW),
                   ApiErrorId.ERR_ARREARS_OUTSTANDING.value)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
def test_over_disbursement_rejected(api):
    """PRD §3.7: "The disbursement amount may not exceed the allocation slice's distributable
    total — the combined family and state amount derivable from that slice — and an attempt to
    over-disburse a slice is rejected with `ERR_OVER_DISBURSEMENT`."

    Design: Corner/errors/over_disbursement_rejected
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=20000, gross_remitted_cents=20000)
    # First disbursement claims the full slice (family 20000).
    validate_success(api.create_disbursement(
        {"support_order_id": order["id"], "custodial_party_id": cp["id"],
         "allocation_id": allocation["id"]}, FO), 201)
    validate_error(api.create_disbursement(
        {"support_order_id": order["id"], "custodial_party_id": cp["id"],
         "allocation_id": allocation["id"]}, FO),
        ApiErrorId.ERR_OVER_DISBURSEMENT.value)


def test_invalid_amount_iwo_zero_ordered(api):
    """PRD §3.3: "The `ordered_amount_cents` must be greater than zero, failing with
    `ERR_INVALID_AMOUNT`."

    Design: Corner/errors/invalid_amount_iwo_zero_ordered
    """
    cp, ncp = _parties(api, ssn="1024")
    emp = validate_success(api.create_employer({"legal_name": "Emp", "fein": "28-2929292"}, CW), 201)
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    validate_error(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 0,
         "effective_start_at": "2026-01-01T00:00:00Z", "effective_end_at": "2027-01-01T00:00:00Z"}, CW),
        ApiErrorId.ERR_INVALID_AMOUNT.value)


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_financeofficer_cannot_create_support_order(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/financeofficer_cannot_create_support_order
    """
    cp, ncp = _parties(api, ssn="1025")
    # POST /sdu/support-orders is CaseWorker-only (PRD §4).
    validate_error(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, FO),
        ApiErrorId.ERR_FORBIDDEN.value)


def test_caseworker_cannot_decide_modification(api):
    """PRD §3.9: "A `Supervisor` — segregated from the caseworker who submitted — decides a
    submitted modification by supplying a `decision`."

    Design: Corner/rbac/caseworker_cannot_decide_modification
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=40000)
    mod = validate_success(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 45000,
         "coverage_start_at": "2026-07-01T00:00:00Z", "coverage_end_at": "2026-12-31T00:00:00Z"}, CW), 201)
    validate_success(api.submit_modification(mod["id"], CW))
    # decide is Supervisor-exclusive; CaseWorker is forbidden.
    validate_error(api.decide_modification(mod["id"], {"decision": "APPROVE"}, CW),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or does not name a recognized role,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    no_role_headers = {"X-User-ID": "anon", "Content-Type": "application/json"}
    validate_error(api.get_support_order(NON_EXISTENT_UUID, no_role_headers),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# endpoints (listing / filtering)
# ---------------------------------------------------------------------------
def test_list_support_orders_paginated_envelope(api):
    """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_support_orders_paginated_envelope
    """
    cp, ncp = _parties(api, ssn="1021")
    for cs in (10000, 20000):
        validate_success(api.create_support_order(
            {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
             "current_support_cents": cs}, CW), 201)
    resp = api.list_support_orders(CW, params={"noncustodial_party_id": ncp["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert len(data) == 1
    assert meta["has_more"] is True


def test_filtered_ledger_entries_by_order(api):
    """PRD §3.6: "Ledger entries can be listed for an order and filtered by `support_order_id`
    or by `entry_type`, returned in chronological order"

    Design: Corner/endpoints/filtered_ledger_entries_by_order
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=30000)
    entries = validate_success(api.list_ledger_entries(
        CW, params={"support_order_id": order["id"]}))
    first = entries[0]
    assert first["entry_type"] == "CHARGE"
    assert first["bucket"] == "CURRENT_SUPPORT"
    assert first["amount_cents"] == 30000


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------
def test_occ_stale_version_on_enforcement_propose(api):
    """PRD §2.8: "If another writer has advanced the order's version since the client last
    read it — for instance by already proposing an enforcement action, which legitimately moves
    the order's `enforcement_status` to `INTERCEPT_PENDING` and bumps its `version` — the
    proposal is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_enforcement_propose
    """
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    stale_ver = order_version(order["id"])
    enf1 = validate_success(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "TAX_INTERCEPT",
         "expected_support_order_version": stale_ver}, CW), 201)
    # First propose bumped the order version; withdraw makes a second propose state-legal.
    validate_success(api.withdraw_enforcement_action(enf1["id"], CW))
    validate_error(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "LICENSE_SUSPENSION",
         "expected_support_order_version": stale_ver}, CW),
        ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_stale_version_on_modification_apply(api):
    """PRD §2.8: "If another modification has already been applied — legitimately superseding
    `current_support_cents` and bumping the order's `version` — applying this stale view would
    clobber the newer amount, so the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_modification_apply
    """
    # M1 covers [01-01, 06-29], M2 covers [07-01, 12-31] (non-overlapping closed intervals).
    cp, ncp, emp, order, m1 = setup_approved_modification(
        current_support_cents=40000, proposed=50000,
        coverage_start_at="2026-01-01T00:00:00Z", coverage_end_at="2026-06-29T00:00:00Z")
    m2 = validate_success(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 55000,
         "coverage_start_at": "2026-07-01T00:00:00Z", "coverage_end_at": "2026-12-31T00:00:00Z"}, CW), 201)
    validate_success(api.submit_modification(m2["id"], CW))
    validate_success(api.decide_modification(m2["id"], {"decision": "APPROVE"}, SUP))
    stale_ver = order_version(order["id"])
    # Apply M1 first -> order bumps version, becomes MODIFIED; captured version now stale.
    validate_success(api.apply_modification(
        m1["id"], {"expected_support_order_version": stale_ver}, CW))
    validate_error(api.apply_modification(
        m2["id"], {"expected_support_order_version": stale_ver}, CW),
        ApiErrorId.ERR_STALE_VERSION.value)


def test_version_increments_on_each_order_mutation(api):
    """PRD §2.4: "an integer `version` that starts at its initial value and increments by one
    on each mutation."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_order_mutation
    """
    cp, ncp = _parties(api, ssn="1029")
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    assert order["version"] == 1
    activated = validate_success(api.activate_support_order(order["id"], CW))
    assert activated["version"] == 2
    suspended = validate_success(api.suspend_support_order(order["id"], CW))
    assert suspended["version"] == 3


# ---------------------------------------------------------------------------
# consistency_model
# ---------------------------------------------------------------------------
def test_allocation_balances_visible_in_same_request(api):
    """PRD §3.1: "reading a support order returns its three owed balances recomputed from the
    ledger at read time."

    Design: Corner/consistency_model/allocation_balances_visible_in_same_request
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=50000, gross_remitted_cents=50000)
    # After allocating distributable 50000 against current_support_due 50000, due -> 0.
    after = validate_success(api.get_support_order(order["id"], FO))
    assert after["current_support_due_cents"] == 0
