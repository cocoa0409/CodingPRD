"""Cemetery-spec boundary compliance, material allow-list, and state-before-fiscal
validation precedence."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / height_at_cemetery_max_boundary
# ---------------------------------------------------------------------------
def _cemetery_max_height_90():
    return th.make_cemetery(allowed_materials=["GRANITE"], max_height_cm=90, max_width_cm=75,
                            max_base_width_cm=80, requires_permit=False, permit_fee_cents=0)


def test_height_equal_to_cemetery_max_accepted(api):
    """PRD §2.6: "The marker's `height_cm` must not exceed `max_height_cm`, its `width_cm` must
    not exceed `max_width_cm`, and its foundation `base_width_cm` must not exceed
    `max_base_width_cm`; any dimension that overshoots its ceiling is rejected with
    `ERR_EXCEEDS_CEMETERY_SPEC`."

    Design: Difficulty/boundary_precision_check/height_at_cemetery_max_boundary
    """
    cem = _cemetery_max_height_90()
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=90, width_cm=40, base_width_cm=50)
    order = th.validate_success(api.create_order(payload, th.make_customer_headers(cust["id"])), 201)
    assert order["production_status"] == "DRAFTING", order


def test_height_above_cemetery_max_rejected(api):
    """PRD §2.6: "any dimension that overshoots its ceiling is rejected with
    `ERR_EXCEEDS_CEMETERY_SPEC`."

    Design: Difficulty/boundary_precision_check/height_at_cemetery_max_boundary
    """
    cem = _cemetery_max_height_90()
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"], height_cm=91, width_cm=40, base_width_cm=50)
    resp = api.create_order(payload, th.make_customer_headers(cust["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_EXCEEDS_CEMETERY_SPEC.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / approve_state_precedes_fiscal
# ---------------------------------------------------------------------------
def test_approve_draft_proof_returns_state_error_not_fiscal(api):
    """PRD §3.3: "An approve attempted on a proof not in `SUBMITTED` is rejected with
    `ERR_PROOF_NOT_SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_precedes_fiscal
    """
    ctx = th.setup_draft_proof(proof_lines=[21, 31])
    resp = api.approve_design_proof(ctx["proof"]["id"], ctx["customer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PROOF_NOT_SUBMITTED.value)


def test_approve_state_check_wins_while_order_still_unpaid(api):
    """PRD §2.10: "then the target resource being in the correct state for the transition (the 409
    state family)".
    PRD §2.10: "then fiscal sufficiency (`ERR_DEPOSIT_NOT_PAID` / `ERR_BALANCE_NOT_PAID` /
    `ERR_ZERO_PAYMENT_AMOUNT`, HTTP 402)".

    Design: Difficulty/priority_pair_validation_conflict/approve_state_precedes_fiscal
    """
    ctx = th.setup_draft_proof(proof_lines=[21, 31])
    # The order is UNPAID (deposit unpaid — the fiscal violation) AND the proof is DRAFT, not
    # SUBMITTED (the state violation); the higher-precedence state error must win.
    order_before = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order_before["payment_status"] == "UNPAID", order_before
    resp = api.approve_design_proof(ctx["proof"]["id"], ctx["customer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_PROOF_NOT_SUBMITTED.value)


# ---------------------------------------------------------------------------
# Corner: validations / material_not_allowed_returns_error
# ---------------------------------------------------------------------------
def test_material_not_in_allowed_list_returns_error(api):
    """PRD §2.6: "An order's chosen `material` must be a member of the destination cemetery's
    `allowed_materials`; a material outside that set is rejected with `ERR_MATERIAL_NOT_ALLOWED`."

    Design: Corner/validations/material_not_allowed_returns_error
    """
    cem = th.make_cemetery(allowed_materials=["GRANITE"], requires_permit=False, permit_fee_cents=0)
    cust = th.make_customer()
    payload = th.create_order_payload(cust["id"], cem["id"], material="BRONZE")
    resp = api.create_order(payload, th.make_customer_headers(cust["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_MATERIAL_NOT_ALLOWED.value)
