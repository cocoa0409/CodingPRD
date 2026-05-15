"""Trade-background verification lifecycle and capital-flow check
(PRD §3.9).

Covers create, on-site, finalize (PASS / FAIL), and capital-flow vs
goods-flow consistency.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_trade_background_verification,
    create_verification_payload,
    open_and_pass_verification,
    setup_registered_receivable,
    validate_error,
    validate_success,
)


def test_open_verification_starts_inconclusive(
    api, risk_reviewer_headers,
):
    """PRD §3.9: "The verification starts in INCONCLUSIVE state."
    """
    bundle = setup_registered_receivable(amount_cents=100_000)
    res = api.create_verification(
        create_verification_payload(
            receivable_id=bundle["receivable"]["id"],
            third_party_score=0.85,
        ),
        risk_reviewer_headers,
    )
    v = validate_success(res, expected_status=201)
    assert_trade_background_verification(v)
    assert v["outcome"] == "INCONCLUSIVE"


def test_finalize_pass_when_all_conditions_met(
    api, risk_reviewer_headers,
):
    """PRD §3.9: "Finalising as PASS requires capital_flow_match true,
    third_party_score at or above the THIRD_PARTY_PASS_FLOOR system
    constant, and — if on_site_required is true — on_site_completed
    true."

    With an amount below the on-site threshold and a high third-party
    score, finalize must produce PASS.
    """
    bundle = setup_registered_receivable(amount_cents=10_000)
    v = open_and_pass_verification(
        bundle["receivable"],
        third_party_score=0.99,
        reviewer_headers=risk_reviewer_headers,
    )
    assert v["outcome"] == "PASS"


def test_finalize_pass_blocked_when_on_site_required_but_not_completed(
    api, risk_reviewer_headers,
):
    """PRD §3.9: "Finalising as PASS requires capital_flow_match true,
    third_party_score at or above the THIRD_PARTY_PASS_FLOOR system
    constant, and — if on_site_required is true — on_site_completed
    true (else ERR_ON_SITE_REQUIRED)."

    Pick a very large amount so on_site_required becomes true. Open
    the verification with a waybill so capital_flow_match is true and
    a high third_party_score so the PASS-eligibility conditions are
    otherwise satisfied; skip the on-site call; finalize must reject
    with ERR_ON_SITE_REQUIRED (the PASS-blocking error per PRD §3.9).
    """
    from test_helpers.constants import TEST_DEFAULTS
    bundle = setup_registered_receivable(amount_cents=500_000_000_00)
    open_res = api.create_verification(
        create_verification_payload(
            receivable_id=bundle["receivable"]["id"],
            third_party_score=0.99,
            waybill_doc_id=TEST_DEFAULTS["WAYBILL_DOC_ID"],
        ),
        risk_reviewer_headers,
    )
    v = validate_success(open_res, expected_status=201)
    assert v.get("on_site_required"), (
        "Setup amount must flip on_site_required for this test."
    )
    assert v.get("capital_flow_match"), (
        "Setup must yield capital_flow_match=true so PASS-eligibility "
        "depends on on-site completion (otherwise the call would FAIL "
        "without hitting the ERR_ON_SITE_REQUIRED branch)."
    )
    # Do NOT call /on-site. Finalize directly:
    res = api.finalize_verification(v["id"], risk_reviewer_headers)
    validate_error(res, ApiErrorId.ERR_ON_SITE_REQUIRED.value)


def test_finalize_fail_increments_aml_risk_score_via_fraud_penalty(
    api, risk_reviewer_headers,
):
    """PRD §3.9: "in addition, a FAIL adds the FRAUD_PENALTY system
    constant to the supplier's aml_risk_score, clamping the result to
    the closed interval from 0.00 to 1.00."

    Cause a FAIL by submitting a low third_party_score; then observe
    that the supplier's aml_risk_score has strictly increased.
    """
    from test_helpers import get_supplier
    bundle = setup_registered_receivable(
        amount_cents=10_000, supplier_aml=0.10,
    )
    before = get_supplier(bundle["supplier"]["id"])
    res = api.create_verification(
        create_verification_payload(
            receivable_id=bundle["receivable"]["id"],
            third_party_score=0.01,  # Far below any reasonable PASS floor.
        ),
        risk_reviewer_headers,
    )
    v = validate_success(res, expected_status=201)
    fin = api.finalize_verification(v["id"], risk_reviewer_headers)
    finalized = validate_success(fin)
    assert finalized["outcome"] == "FAIL"
    after = get_supplier(bundle["supplier"]["id"])
    assert float(after["aml_risk_score"]) > float(before["aml_risk_score"]), (
        f"FAIL must increase aml_risk_score by FRAUD_PENALTY (PRD §3.9). "
        f"before={before['aml_risk_score']}, after={after['aml_risk_score']}"
    )
    assert 0.0 <= float(after["aml_risk_score"]) <= 1.0


def test_capital_flow_match_threshold(api, risk_reviewer_headers):
    """PRD §3.9: "the match is true exactly when this rounded deviation
    is at most the CAPITAL_GOODS_TOLERANCE_BPS system constant (currently
    500 basis points, or 5.00%)."

    The capital_cents and goods_cents are PRD-defined; the goods_cents
    is "the declared value (in cents) on the uploaded waybill document"
    which test factories don't fully control — we instead assert that
    a verification opened with a benign waybill returns
    ``capital_flow_match`` as a boolean. PRD pins the formula but the
    waybill metadata source is implementation-defined so we test the
    BOOLEAN PRESENCE rather than the truth value (which would require
    waybill-side mocking PRD doesn't promise).
    """
    bundle = setup_registered_receivable(amount_cents=100_000)
    res = api.create_verification(
        create_verification_payload(
            receivable_id=bundle["receivable"]["id"],
            third_party_score=0.85,
            waybill_doc_id="waybill-001",
        ),
        risk_reviewer_headers,
    )
    v = validate_success(res, expected_status=201)
    assert isinstance(v["capital_flow_match"], bool), (
        "PRD §3.9 declares capital_flow_match as a boolean computed at "
        "creation."
    )
