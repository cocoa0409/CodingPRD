"""Warranty claim adjudication: the approve/deny fork, settlement, voiding on deny, and
the cross-entity review guard.

Covers Difficulty queue: non_linear_state_machine (fork/join deny), cross_entity_state_dependency
(review requires equipment IN_WARRANTY), compensating_invariant (deny-then-settle blocked);
plus corner validations on approval and claim origin.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    TEST_USERS,
    approve_claim_payload,
    deny_claim_payload,
    create_warranty_claim_payload,
    ApiErrorId,
    setup_claim_in_state,
    setup_completed_warranty_visit,
    setup_visit_on_site,
    file_warranty_claim,
    get_equipment,
    get_customer,
    get_claim,
    advance_clock,
)

ADMIN = TEST_USERS["contract_admin_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine — fork to DENIED voids equipment warranty
# ===========================================================================
def test_deny_claim_sets_zero_approved_and_voids_equipment_warranty(api):
    """PRD §3.10: "Denial moves it `UNDER_REVIEW → DENIED`, sets `approved_amount_cents`
    to 0, records the supplied `denial_reason`, and cascades across to the equipment by
    setting that equipment's `warranty_status` to `VOIDED` — a denied claim voids the
    warranty."

    Design: Difficulty/non_linear_state_machine/warranty_claim_fork_join_approve_vs_deny_divergent_effects
    """
    ctx = setup_claim_in_state("UNDER_REVIEW", claimed_amount_cents=50000)
    denied = validate_success(
        api.deny_warranty_claim(ctx["claim"]["id"], deny_claim_payload("pre-existing damage"), ADMIN), 200
    )
    assert denied["status"] == "DENIED", f"fork to DENIED, got {denied['status']}"
    assert denied["approved_amount_cents"] == 0, f"deny sets approved 0, got {denied['approved_amount_cents']}"
    eq = get_equipment(ctx["equipment"]["id"])
    assert eq["warranty_status"] == "VOIDED", f"deny voids equipment warranty, got {eq['warranty_status']}"


def test_approve_claim_records_authorized_amount_and_leaves_warranty(api):
    """PRD §3.10: "Approval moves it `UNDER_REVIEW → APPROVED` and records the authorized
    amount into `approved_amount_cents`; the authorized amount may not exceed the
    `claimed_amount_cents`, or the approval is rejected with `ERR_APPROVAL_EXCEEDS_CLAIM`."

    Design: Difficulty/non_linear_state_machine/warranty_claim_fork_join_approve_vs_deny_divergent_effects
    """
    ctx = setup_claim_in_state("UNDER_REVIEW", claimed_amount_cents=50000)
    approved = validate_success(
        api.approve_warranty_claim(ctx["claim"]["id"], approve_claim_payload(30000), ADMIN), 200
    )
    assert approved["status"] == "APPROVED", f"fork to APPROVED, got {approved['status']}"
    assert approved["approved_amount_cents"] == 30000, (
        f"approve records authorized 30000, got {approved['approved_amount_cents']}"
    )
    # The approve branch leaves the warranty axis untouched (it is not the deny branch).
    eq = get_equipment(ctx["equipment"]["id"])
    assert eq["warranty_status"] == "IN_WARRANTY", (
        f"approval does not void the warranty, got {eq['warranty_status']}"
    )


# ===========================================================================
# Difficulty / cross_entity_state_dependency — review requires IN_WARRANTY equipment
# ===========================================================================
def test_start_review_rejected_when_equipment_warranty_expired(api):
    """PRD §3.10: "Starting review moves the claim `SUBMITTED → UNDER_REVIEW`, but only
    while the referenced equipment is still `IN_WARRANTY` on its warranty axis."
    PRD §3.7: "When equipment is fetched, the system refreshes the warranty axis against
    the clock: if the current clock has reached or passed `warranty_expires_at` while the
    unit is still `IN_WARRANTY`, the warranty axis flips to `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_equipment_in_warranty_claim_equipment_pair
    """
    ctx = setup_completed_warranty_visit(equipment_overrides={"warranty_expires_at": "2026-08-01T00:00:00Z"})
    claim = file_warranty_claim(ctx["equipment"]["id"], ctx["warranty_visit"]["id"], 50000)
    # Age the clock past warranty_expires_at so the equipment warranty has lapsed.
    advance_clock("2026-09-01T00:00:00Z")
    validate_error(api.start_review_warranty_claim(claim["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_start_review_succeeds_while_equipment_in_warranty(api):
    """PRD §3.10: "Starting review moves the claim `SUBMITTED → UNDER_REVIEW`, but only
    while the referenced equipment is still `IN_WARRANTY` on its warranty axis."

    Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_equipment_in_warranty_claim_equipment_pair
    """
    # warranty_expires_at is far in the future, so the equipment is still IN_WARRANTY.
    ctx = setup_completed_warranty_visit(equipment_overrides={"warranty_expires_at": "2030-01-01T00:00:00Z"})
    claim = file_warranty_claim(ctx["equipment"]["id"], ctx["warranty_visit"]["id"], 50000)
    reviewed = validate_success(api.start_review_warranty_claim(claim["id"], ADMIN), 200)
    assert reviewed["status"] == "UNDER_REVIEW", (
        f"review starts while equipment IN_WARRANTY, got {reviewed['status']}"
    )


# ===========================================================================
# Difficulty / compensating_invariant — denied claim never credits the ledger
# ===========================================================================
def test_denied_claim_cannot_settle_and_leaves_ledger_unchanged(api):
    """PRD §3.10: "The `APPROVED → SETTLED` transition credits the customer's ledger by
    exactly the `approved_amount_cents` — that amount is subtracted from the customer's
    `billing_balance_cents` — and increments the claim's `version` by one."
    PRD §3.10: "A denied claim, having no settlement, moves the ledger by nothing."

    Design: Difficulty/compensating_invariant/warranty_deny_then_settle_blocked_keeps_customer_ledger_invariant
    """
    ctx = setup_claim_in_state("UNDER_REVIEW", claimed_amount_cents=50000,
                              plan_overrides={"annual_fee_cents": 24000})
    denied = validate_success(api.deny_warranty_claim(ctx["claim"]["id"], deny_claim_payload(), ADMIN), 200)
    assert denied["status"] == "DENIED"
    # settle is only defined from APPROVED; on a DENIED claim it is an invalid transition.
    validate_error(api.settle_warranty_claim(ctx["claim"]["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 24000, (
        f"a denied (never settled) claim leaves the ledger at the 24000 annual fee, got "
        f"{customer['billing_balance_cents']}"
    )


def test_settled_approved_claim_credits_ledger_exactly_once(api):
    """PRD §3.10: "The `APPROVED → SETTLED` transition credits the customer's ledger by
    exactly the `approved_amount_cents` — that amount is subtracted from the customer's
    `billing_balance_cents` — and increments the claim's `version` by one."
    PRD §2.7: "a claim that travels from submission through to settlement with an
    authorized amount moves the ledger by exactly the negative of that authorized amount
    and nothing more, while a denied claim moves the ledger by zero."

    Design: Difficulty/compensating_invariant/warranty_deny_then_settle_blocked_keeps_customer_ledger_invariant
    """
    # The forward (approved->settled) credit fires exactly once for an APPROVED claim,
    # the conserved-quantity complement of the denied branch.
    ctx = setup_claim_in_state("SETTLED", claimed_amount_cents=50000, approved_amount_cents=20000,
                              plan_overrides={"annual_fee_cents": 24000})
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 4000, (
        f"balance = 24000 annual fee - 20000 approved credit = 4000, got {customer['billing_balance_cents']}"
    )


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_approve_exceeding_claim_rejected(api):
    """PRD §3.10: "the authorized amount may not exceed the `claimed_amount_cents`, or the
    approval is rejected with `ERR_APPROVAL_EXCEEDS_CLAIM`."

    Design: Corner/validations/warranty_approve_exceeds_claim_rejected
    """
    ctx = setup_claim_in_state("UNDER_REVIEW", claimed_amount_cents=50000)
    validate_error(
        api.approve_warranty_claim(ctx["claim"]["id"], approve_claim_payload(60000), ADMIN),
        ApiErrorId.ERR_APPROVAL_EXCEEDS_CLAIM.value,
    )


def test_warranty_claim_from_non_warranty_origin_visit_rejected(api):
    """PRD §3.10: "The origin must be legitimate: the origin visit's `visit_kind` must be
    `WARRANTY` and that visit's `site_id` must equal the equipment's `site_id`, or the
    filing is rejected with `ERR_CLAIM_ORIGIN_INVALID`."

    Design: Corner/validations/warranty_claim_origin_not_warranty_visit_rejected
    """
    # Complete a SEASONAL visit (wrong kind) at the equipment's site.
    ctx = setup_visit_on_site(equipment_overrides={"refrigerant_type": "R410A"})
    tech_headers = TEST_USERS["technician_headers"]  # not used for ownership; the complete uses the assigned tech
    from test_helpers import make_technician_headers
    completed = validate_success(
        api.complete_service_visit(ctx["visit"]["id"], make_technician_headers(ctx["technician"]["id"])), 200
    )
    assert completed["visit_kind"] == "SEASONAL"
    validate_error(
        api.create_warranty_claim(
            create_warranty_claim_payload(ctx["equipment"]["id"], ctx["visit"]["id"], 10000), ADMIN),
        ApiErrorId.ERR_CLAIM_ORIGIN_INVALID.value,
    )
