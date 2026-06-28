"""Calculation correctness: preparation-fee tiers and discount, refund-advance
maximum-eligible nested minimum, and the disbursement surcharge rounding order.

Every literal expected value below is copied from the design index and was
verified against the PRD §3.4 / §3.7 / §3.8 formulas.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_return_in_docs_pending, setup_return_in_prep,
    create_client, create_return, create_refund_advance,
    setup_accepted_return_with_disbursed_advance_and_pending_transfer,
    create_audit_protection, create_refund_transfer, create_approved_advance,
    TEST_USERS,
)

BO = TEST_USERS["bank_officer_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─── Queue A: dual_variant_calc / prep_fee_new_vs_returning_client ─────────

def test_prep_fee_new_client_no_discount(api):
    """PRD §3.4: "When the client is not returning, no discount line is
    produced and prep_fee_cents equals the subtotal exactly."
    PRD §3.4: "the base line is the base-1040 fee of 15000 cents multiplied by
    that band multiplier and rounded half-up to whole cents"

    Design: Difficulty/dual_variant_calc/prep_fee_new_vs_returning_client
    """
    ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "New Ned", "ssn_last4": "1111", "is_returning": False},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1})
    res = api.transition_return(ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"])
    ret = validate_success(res, 200)
    # STANDARD x1.20: base 18000 + A 4800 + C 10800 + state 7200 = 40800, no discount.
    assert ret["prep_fee_cents"] == 40800, f"new-client fee should be 40800, got {ret['prep_fee_cents']}"


def test_prep_fee_returning_client_discount_applied(api):
    """PRD §3.4: "the discount is the smaller of a cap of 2500 cents and ten
    percent of the subtotal rounded half-up to whole cents, and it is added as a
    single negative DISCOUNT line carrying the negated discount amount."
    PRD §3.4: "When the client is returning, prep_fee_cents is the subtotal
    minus the discount, and the figure is floored at zero so it can never go
    negative."

    Design: Difficulty/dual_variant_calc/prep_fee_new_vs_returning_client
    """
    ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "Ret Rita", "ssn_last4": "2222", "is_returning": True},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1})
    res = api.transition_return(ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"])
    ret = validate_success(res, 200)
    # subtotal 40800; 10% = 4080 > cap 2500 -> discount 2500 -> 38300.
    assert ret["prep_fee_cents"] == 38300, f"returning-client fee should be 38300, got {ret['prep_fee_cents']}"


def test_prep_fee_new_vs_returning_diverge_by_capped_discount(api):
    """PRD §3.4: "the discount is the smaller of a cap of 2500 cents and ten
    percent of the subtotal rounded half-up to whole cents"

    Design: Difficulty/dual_variant_calc/prep_fee_new_vs_returning_client
    """
    new_ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "New Ned", "ssn_last4": "1111", "is_returning": False},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1})
    new_fee = validate_success(api.transition_return(
        new_ctx["return"]["id"], {"to": "IN_PREP"}, new_ctx["prep_headers"]), 200)["prep_fee_cents"]

    ret_ctx = setup_return_in_docs_pending(
        client_overrides={"full_name": "Ret Rita", "ssn_last4": "2222", "is_returning": True},
        return_overrides={"complexity_band": "STANDARD", "schedules": ["A", "C"],
                          "state_return_count": 1})
    ret_fee = validate_success(api.transition_return(
        ret_ctx["return"]["id"], {"to": "IN_PREP"}, ret_ctx["prep_headers"]), 200)["prep_fee_cents"]

    assert new_fee - ret_fee == 2500, f"variant divergence should be the 2500 cap, got {new_fee - ret_fee}"


# ─── Queue A: dual_variant_calc / advance_max_eligible_low_vs_high_risk ────

def _setup_bank_office_return(risk_band, expected_refund_cents, ssn, year=2025, kind=None):
    """Bank-product office + client at given risk + return with expected refund."""
    office = api_client.create_office(
        {"name": "Bank Office", "efin": "654321", "state_code": "TX",
         "bank_product_enabled": True}, TEST_USERS["office_manager_headers"])
    office = validate_success(office, 201)
    client = create_client(office["id"], full_name="C", ssn_last4=ssn, risk_band=risk_band)
    overrides = {"expected_refund_cents": expected_refund_cents}
    if kind:
        overrides["return_kind"] = kind
    ret = create_return(office["id"], client["id"], tax_year=year, **overrides)
    return office, client, ret


def test_advance_low_risk_approved_via_fraction(api):
    """PRD §3.8: "The risk fraction is read from the linked client's risk_band:
    LOW uses 0.75, MEDIUM uses 0.50, and HIGH uses 0.00."
    PRD §3.8: "On an approval, approved_cents is set to the smaller of
    requested_cents and that maximum eligible."

    Design: Difficulty/dual_variant_calc/advance_max_eligible_low_vs_high_risk
    """
    _, _, ret = _setup_bank_office_return("LOW", 250000, "3333")
    adv = create_refund_advance(ret["id"], 200000)
    res = api.underwrite_refund_advance(adv["id"], {"decision": "APPROVE"}, BO)
    approved = validate_success(res, 200)
    # tier(250000)=50000; round(250000*0.75)=187500; min=50000; min(200000,50000)=50000.
    assert approved["approved_cents"] == 50000, f"expected 50000, got {approved['approved_cents']}"
    assert approved["status"] == "APPROVED"


def test_advance_high_risk_ineligible(api):
    """PRD §3.8: "A HIGH risk band therefore drives the fraction product to
    zero, forcing the maximum eligible to zero and producing
    ERR_ADVANCE_INELIGIBLE regardless of refund size"

    Design: Difficulty/dual_variant_calc/advance_max_eligible_low_vs_high_risk
    """
    _, _, ret = _setup_bank_office_return("HIGH", 250000, "4444")
    adv = create_refund_advance(ret["id"], 200000)
    res = api.underwrite_refund_advance(adv["id"], {"decision": "APPROVE"}, BO)
    validate_error(res, "ERR_ADVANCE_INELIGIBLE", expected_status=409)
    after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert after["status"] == "REQUESTED", "denied-eligibility advance must stay REQUESTED"


# ─── Queue A: combinatorial_formula / advance_max_eligible_nested_min ──────

def test_advance_nested_min_tier_binds_for_medium_risk(api):
    """PRD §3.8: "The maximum eligible is the smaller of the tier cap and the
    expected refund multiplied by the risk fraction, rounded half-up to whole
    cents."
    PRD §3.8: "a refund from 300000 cents up to but not including 600000 cents
    yields a cap of 150000 cents"

    Design: Difficulty/combinatorial_formula/advance_max_eligible_nested_min_tier_mode_a
    """
    _, _, ret = _setup_bank_office_return("MEDIUM", 500000, "5555")
    adv = create_refund_advance(ret["id"], 400000)
    approved = validate_success(api.underwrite_refund_advance(
        adv["id"], {"decision": "APPROVE"}, BO), 200)
    # tier(500000)=150000; round(500000*0.50)=250000; min=150000.
    assert approved["approved_cents"] == 150000, f"expected 150000, got {approved['approved_cents']}"


def test_advance_nested_min_fraction_binds_for_low_risk(api):
    """PRD §3.8: "a refund from 100000 cents up to but not including 300000
    cents yields a cap of 50000 cents"
    PRD §3.8: "The maximum eligible is the smaller of the tier cap and the
    expected refund multiplied by the risk fraction, rounded half-up to whole
    cents."

    Design: Difficulty/combinatorial_formula/advance_max_eligible_nested_min_tier_mode_a
    """
    _, _, ret = _setup_bank_office_return("LOW", 100000, "6666")
    adv = create_refund_advance(ret["id"], 400000)
    approved = validate_success(api.underwrite_refund_advance(
        adv["id"], {"decision": "APPROVE"}, BO), 200)
    # tier(100000)=50000; round(100000*0.75)=75000; min=50000.
    assert approved["approved_cents"] == 50000, f"expected 50000, got {approved['approved_cents']}"


# ─── Queue A: combinatorial_formula / disbursement_surcharge round_per_bucket

def test_disbursement_surcharge_round_per_bucket_then_sum(api):
    """PRD §3.7: "The surcharge is 2.9 percent applied to each bucket that the
    waterfall actually funded — that is, each bucket whose take was greater than
    zero — with each per-bucket charge rounded half-up to whole cents and then
    those rounded charges summed in that same pinned bucket order."

    Design: Difficulty/combinatorial_formula/disbursement_surcharge_round_per_bucket_mode_b
    """
    # Build: SIMPLE return (prep 15000) accepted; audit fee 1000 ACTIVE; advance
    # approved 1020 + disbursed; RefundTransfer pending; disburse 50000.
    ctx = setup_return_in_prep(
        bank_product_enabled=True,
        client_overrides={"full_name": "Sim Sam", "ssn_last4": "7777", "risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    validate_success(api.transition_return(rid, {"to": "PREPARED"}, ph), 200)
    create_audit_protection(rid, fee_cents=1000)
    adv = create_approved_advance(rid, 1020)
    rt = create_refund_transfer(rid)
    rt_v = rt["version"]
    validate_success(api.efile_return(rid, ph), 200)
    validate_success(api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph), 200)
    validate_success(api.disburse_refund_advance(adv["id"], BO), 200)

    res = api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 50000, "expected_refundtransfer_version": rt_v}, BO)
    disbursed = validate_success(res, 200)
    # buckets funded [3995,15000,1000,1020]; round-per-bucket 2.9% sums to 610.
    # PRD §3.7 pins that the disburse response "reports an electronic-disbursement
    # surcharge" with this round-per-bucket value, but does not pin the exact
    # response field name; accept either PRD-faithful spelling.
    surcharge = disbursed.get("surcharge_cents", disbursed.get("disbursement_surcharge_cents"))
    assert surcharge == 610, f"surcharge should be 610, got {surcharge}"


def test_disbursement_surcharge_net_and_repaid(api):
    """PRD §3.7: "After all four buckets, whatever remains is
    net_to_taxpayer_cents."
    PRD §3.7: "the advance-repayment bucket's take becomes that advance's
    repaid_cents and the advance moves to REPAID"

    Design: Difficulty/combinatorial_formula/disbursement_surcharge_round_per_bucket_mode_b
    """
    ctx = setup_return_in_prep(
        bank_product_enabled=True,
        client_overrides={"full_name": "Sim Sam", "ssn_last4": "7777", "risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    validate_success(api.transition_return(rid, {"to": "PREPARED"}, ph), 200)
    create_audit_protection(rid, fee_cents=1000)
    adv = create_approved_advance(rid, 1020)
    rt = create_refund_transfer(rid)
    rt_v = rt["version"]
    validate_success(api.efile_return(rid, ph), 200)
    validate_success(api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph), 200)
    validate_success(api.disburse_refund_advance(adv["id"], BO), 200)

    disbursed = validate_success(api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 50000, "expected_refundtransfer_version": rt_v}, BO), 200)
    # 50000 - (3995+15000+1000+1020) = 28985 net; advance repaid 1020.
    assert disbursed["net_to_taxpayer_cents"] == 28985, f"net should be 28985, got {disbursed['net_to_taxpayer_cents']}"
    adv_after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert adv_after["repaid_cents"] == 1020, f"repaid should be 1020, got {adv_after['repaid_cents']}"
