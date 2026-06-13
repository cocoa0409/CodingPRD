"""Claim lifecycle: filing, RMA issuance, adjudication branches, fulfillment,
withdrawal, and the refund-fulfillment cascade (PRD §3.5–§3.10, §3.13)."""
from test_helpers import set_clock, validate_error, validate_success
from test_helpers import fixtures as F


# ─── Difficulty: non_linear_state_machine (approve vs deny fork) ─────────────
def test_adjudicate_approve_writes_resolution_and_debit(api):
    """PRD §3.7: "On a successful approval the system sets the claim's
    `resolution_type` to the admin-chosen branch ... the system writes a `DEBIT`
    ledger entry whose `reason` matches the resolution ... then decrements the
    registration's `remaining_coverage_cents` by that assessed value".
    PRD §3.7: "An approval moves the claim from `RMA_ISSUED` to `ADJUDICATED`".

    Design: Difficulty/non_linear_state_machine/claim_branching_adjudicate_approve_vs_deny_divergent_side_effects
    """
    s = F.setup_claim_in_rma(
        with_extension=True,
        ext_kwargs={"ext_cap_cents": 40000, "ext_refund_eligible": True},
        reported_date="2025-01-15T00:00:00Z",
    )
    set_clock("2025-01-15T00:00:00Z")
    claim = F.adjudicate_approve(s["claim"]["id"], "REPAIR", repair_cost_cents=8000)
    assert claim["status"] == "ADJUDICATED"
    assert claim["resolution_type"] == "REPAIR"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 32000


def test_adjudicate_deny_leaves_resolution_null_and_no_debit(api):
    """PRD §3.7: "A denial moves the claim from `RMA_ISSUED` to `DENIED`, leaving
    `resolution_type` null, and is the required outcome when the defect category
    is `WEAR_AND_TEAR`, `ACCIDENTAL`, or `COSMETIC`".
    PRD §2.7: remaining coverage is "the cap minus total debits plus total
    credits" — with no debit it stays at the cap.

    Design: Difficulty/non_linear_state_machine/claim_branching_adjudicate_approve_vs_deny_divergent_side_effects
    """
    s = F.setup_claim_in_rma(
        with_extension=True,
        ext_kwargs={"ext_cap_cents": 40000, "ext_refund_eligible": True},
        defect_category="MANUFACTURING",
        reported_date="2025-01-15T00:00:00Z",
    )
    claim = F.adjudicate_deny(s["claim"]["id"])
    assert claim["status"] == "DENIED"
    assert claim["resolution_type"] is None
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 40000
    ledger = F.list_ledger(s["registration"]["id"], s["owner"]["id"])
    assert len(ledger) == 0


# ─── Difficulty: transitive_cascade (depth-3 fulfill-refund) ─────────────────
def test_fulfill_refund_cascades_to_void_and_cancel_extension(api):
    """PRD §3.10: "When the resolution is `REFUND`, fulfillment additionally drives
    the parent registration to `VOIDED` and cancels every `ACTIVE` extended
    warranty on that registration, because a refund terminates coverage."
    PRD §3.10: "Fulfillment moves the claim from `ADJUDICATED` to `FULFILLED`".

    Design: Difficulty/transitive_cascade/fulfill_refund_cascades_claim_then_registration_then_extension
    """
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={"ext_cap_cents": 40000, "ext_refund_eligible": True},
        reported_date="2025-01-15T00:00:00Z",
        adjudicate_clock="2025-01-15T00:00:00Z",
    )
    fulfilled = F.fulfill_claim(s["claim"]["id"])
    assert fulfilled["status"] == "FULFILLED"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["status"] == "VOIDED"
    ext = validate_success(api.get_extended_warranty(s["extension"]["id"], F.ADMIN))
    assert ext["status"] == "CANCELLED"


def test_fulfill_repair_does_not_void_registration(api):
    """PRD §3.10: "Fulfillment moves the claim from `ADJUDICATED` to `FULFILLED`
    and is permitted only when the claim is `ADJUDICATED` and its
    `resolution_type` is not null. When the resolution is `REFUND`, fulfillment
    additionally drives the parent registration to `VOIDED`".

    Design: Difficulty/transitive_cascade/fulfill_refund_cascades_claim_then_registration_then_extension
    """
    s = F.setup_claim_in_rma(
        with_extension=True,
        ext_kwargs={"ext_cap_cents": 40000, "ext_refund_eligible": True},
        reported_date="2025-01-15T00:00:00Z",
    )
    set_clock("2025-01-15T00:00:00Z")
    F.adjudicate_approve(s["claim"]["id"], "REPAIR", repair_cost_cents=8000)
    fulfilled = F.fulfill_claim(s["claim"]["id"])
    assert fulfilled["status"] == "FULFILLED"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["status"] == "ACTIVE"


# ─── Difficulty: cross_entity_state_dependency (issue-rma needs ACTIVE+VALIDATED)
def test_issue_rma_blocked_when_registration_still_registered(api):
    """PRD §3.6: "This transition from `INTAKE` to `RMA_ISSUED` is allowed only
    when the claim is in `INTAKE`, the parent registration is `ACTIVE`, the
    registration's `proof_status` is `VALIDATED`, and the claim's reported date is
    on or before the registration's `warranty_end_date`".
    PRD §2.10: "the target resource's state is checked fourth, yielding
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/claim_issue_rma_requires_registration_active_and_proof_validated
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    # Registration left REGISTERED (no proof validated). A claim can still be filed.
    claim = F.file_claim(reg["id"], owner["id"], defect_category="MANUFACTURING", reported_date="2024-02-15T00:00:00Z")
    resp = api.issue_rma(claim["id"], F.CP)
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_claim(claim["id"], F.CP))["status"] == "INTAKE"


def test_issue_rma_succeeds_when_registration_active_and_validated(api):
    """PRD §3.6: "This transition from `INTAKE` to `RMA_ISSUED` is allowed only
    when the claim is in `INTAKE`, the parent registration is `ACTIVE`, the
    registration's `proof_status` is `VALIDATED`, and the claim's reported date is
    on or before the registration's `warranty_end_date`".

    Design: Difficulty/cross_entity_state_dependency/claim_issue_rma_requires_registration_active_and_proof_validated
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-15T00:00:00Z")
    issued = F.issue_rma(claim["id"])
    assert issued["status"] == "RMA_ISSUED"
    assert issued["rma_number"] is not None


# ─── Corner: state machine claims ────────────────────────────────────────────
def test_issue_rma_twice_second_call_invalid_state(api):
    """PRD §3.6: "This transition from `INTAKE` to `RMA_ISSUED` is allowed only
    when the claim is in `INTAKE`".

    Design: Corner/state_machines/issue_rma_twice_idempotency_second_call_invalid_state
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    resp = api.issue_rma(s["claim"]["id"], F.CP)
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_claim(s["claim"]["id"], F.CP))["status"] == "RMA_ISSUED"


def test_fulfill_denied_claim_returns_invalid_state(api):
    """PRD §3.10: "Fulfillment moves the claim from `ADJUDICATED` to `FULFILLED`
    and is permitted only when the claim is `ADJUDICATED` and its
    `resolution_type` is not null."

    Design: Corner/state_machines/fulfill_terminal_denied_claim_returns_invalid_state
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
        defect_category="WEAR_AND_TEAR",
    )
    F.adjudicate_deny(s["claim"]["id"])
    resp = api.fulfill_claim(s["claim"]["id"], F.CP)
    validate_error(resp, "ERR_INVALID_STATE")
    assert validate_success(api.get_claim(s["claim"]["id"], F.CP))["status"] == "DENIED"


def test_void_blocked_when_claim_in_rma_issued(api):
    """PRD §3.13: "A `WarrantyAdmin` may void a registration that is in
    `REGISTERED` or `ACTIVE`, provided no claim of that registration is in
    `RMA_ISSUED`, `ADJUDICATED`, or `FULFILLED`."

    Design: Corner/state_machines/void_registration_blocked_when_claim_in_rma_issued
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    resp = api.void_registration(s["registration"]["id"], F.ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")
    assert F.get_registration(s["registration"]["id"], s["owner"]["id"])["status"] == "ACTIVE"


def test_void_active_registration_cancels_active_extension(api):
    """PRD §3.13: "Voiding drives the registration to `VOIDED` and cancels every
    `ACTIVE` extended warranty on the registration."

    Design: Corner/state_machines/void_active_registration_cancels_active_extension_cascade
    """
    s = F.setup_active_registration_with_extension(ext_cap_cents=40000)
    resp = api.void_registration(s["registration"]["id"], F.ADMIN)
    data = validate_success(resp)
    assert data["status"] == "VOIDED"
    ext = validate_success(api.get_extended_warranty(s["extension"]["id"], F.ADMIN))
    assert ext["status"] == "CANCELLED"


def test_claim_starts_in_intake_initial_state(api):
    """PRD §3.5: "A claim is created in `status` `INTAKE`; its `resolution_type`
    is null, its `rma_number` is null, its `claims_processor_user_id` is null, and
    its `assessed_value_cents` is 0 at this point."

    Design: Corner/state_machines/claim_starts_in_intake_initial_state
    """
    s = F.setup_active_registration(base_cap_cents=20000, product_overrides={"base_warranty_months": 24})
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-15T00:00:00Z")
    assert claim["status"] == "INTAKE"
    assert claim["resolution_type"] is None
    assert claim["rma_number"] is None


def test_registration_expires_when_clock_advances_past_warranty_end(api):
    """PRD §3.13: "Advancing the clock runs an expiry sweep: any `ACTIVE`
    registration whose `warranty_end_date` has passed — that is, the current time
    is strictly later than the warranty end date — transitions from `ACTIVE` to
    `EXPIRED`".

    Design: Corner/state_machines/registration_expires_when_clock_advances_past_warranty_end
    """
    s = F.setup_active_registration(base_cap_cents=20000, product_overrides={"base_warranty_months": 12})
    F.advance_clock("2025-02-01T00:00:00Z")
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["status"] == "EXPIRED"


def test_withdraw_claim_under_rma_moves_to_closed_no_ledger(api):
    """PRD §3.5: "An owner may withdraw their own claim, but only while it sits at
    `RMA_ISSUED`. Withdrawal moves the claim from `RMA_ISSUED` to `CLOSED` and
    records no ledger movement."

    Design: Corner/state_machines/withdraw_claim_under_rma_moves_to_closed_no_ledger_movement
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    resp = api.withdraw_claim(s["claim"]["id"], F.make_owner_headers(s["owner"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "CLOSED"
    ledger = F.list_ledger(s["registration"]["id"], s["owner"]["id"])
    assert len(ledger) == 0


# ─── Corner: endpoint actions ────────────────────────────────────────────────
def test_issue_rma_mints_rma_number_and_records_processor(api):
    """PRD §3.6: "Issuing the authorization mints the claim's `rma_number` and
    records the acting processor's identifier in `claims_processor_user_id`".

    Design: Corner/endpoints/issue_rma_mints_rma_number_and_records_processor
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-15T00:00:00Z")
    resp = api.issue_rma(claim["id"], F.make_claims_processor_headers("cp-007"))
    data = validate_success(resp)
    assert data["status"] == "RMA_ISSUED"
    assert data["rma_number"] is not None
    assert data["claims_processor_user_id"] == "cp-007"


def test_adjudicate_repair_writes_debit_ledger_entry(api):
    """PRD §3.7: "the system writes a `DEBIT` ledger entry whose `reason` matches
    the resolution (`REPAIR_COST`, `REPLACE_COST`, or `REFUND_PAYOUT`), whose
    `claim_id` is this claim, and whose `amount_cents` is the assessed value".
    PRD §3.7: "for a `REPAIR` or `REPLACE` it is the supplied cost basis."

    Design: Corner/endpoints/adjudicate_repair_writes_debit_ledger_entry_with_reason
    """
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    claim = F.adjudicate_approve(s["claim"]["id"], "REPAIR", repair_cost_cents=8000)
    assert claim["assessed_value_cents"] == 8000
    ledger = F.list_ledger(s["registration"]["id"], s["owner"]["id"])
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["entry_type"] == "DEBIT"
    assert entry["reason"] == "REPAIR_COST"
    assert entry["amount_cents"] == 8000
    assert entry["claim_id"] == s["claim"]["id"]
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 32000


def test_list_claims_filter_by_registration_id(api):
    """PRD §4: "List claims (filter by registration_id, status)".
    PRD §2.5: "Several list endpoints support reverse-reachability filters".

    Design: Corner/endpoints/list_claims_filter_by_registration_id_reverse_reachability
    """
    s = F.setup_active_registration(base_cap_cents=40000, product_overrides={"base_warranty_months": 24})
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-02-15T00:00:00Z")
    resp = api.list_claims(F.ADMIN, params={"registration_id": s["registration"]["id"]})
    from test_helpers import validate_paginated
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == claim["id"]
