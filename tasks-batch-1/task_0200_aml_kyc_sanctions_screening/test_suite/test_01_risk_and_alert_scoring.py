"""Risk scoring and alert severity calculations.

Covers the dual-variant and combinatorial calculation difficulty instances plus
the corner calculation-boundary instances. Each test cites the PRD prose that
uniquely fixes the computed value.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_customer_payload, create_legal_entity_payload, create_risk_assessment_payload,
    create_account_payload, create_transaction_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]
AN = TEST_USERS["analyst_headers"]
SF = TEST_USERS["system_feed_headers"]


# ==========================================================================
# Queue A — dual_variant_calc
# ==========================================================================
def test_provisional_vs_final_band_flip_on_confirmed_hit(api):
    """PRD §3.2: "A `FINAL` assessment, before applying the weighted formula,
    adds 1 to the `pep_factor` (capped so it never exceeds 5) whenever the
    customer has at least one screening hit that is both `CONFIRMED` and
    derogatory at the moment of computation; this pre-formula bump is what makes
    a `FINAL` assessment diverge from a `PROVISIONAL` one computed from identical
    input factors once a sanctions hit has been confirmed."
    PRD §3.2: "a `total_score` of at least 60 but below 84 yields `HIGH`; a
    `total_score` of at least 35 but below 60 yields `MEDIUM`".

    Design: Difficulty/dual_variant_calc/risk_scoring_provisional_vs_final_band_flip
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Pep Person", country_code="US",
                                date_of_birth="1980-01-01", is_pep_self_declared=True), CO), 201)
    hit = validate_success(api.create_screening_hit(
        cust["id"], {"list_type": "OFAC_SDN", "matched_name": "Pep Person", "match_score": 0.97}, CO), 201)
    validate_success(api.disposition_hit(hit["id"], {"decision": "ESCALATE"}, CO))
    confirmed = validate_success(api.disposition_hit(hit["id"], {"decision": "CONFIRM"}, CO))
    assert confirmed["disposition"] == "CONFIRMED"

    factors = dict(geography_factor=5, product_factor=3, pep_factor=4, adverse_media_factor=3)
    prov = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(variant="PROVISIONAL", **factors), CO), 201)
    final = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(variant="FINAL", **factors), CO), 201)

    assert prov["total_score"] == pytest.approx(58.00, abs=0.01), prov["total_score"]
    assert prov["risk_band"] == "MEDIUM"
    assert final["total_score"] == pytest.approx(75.00, abs=0.01), final["total_score"]
    assert final["risk_band"] == "HIGH"


def test_provisional_final_identical_without_confirmed_hit(api):
    """PRD §3.2: "A `PROVISIONAL` assessment never applies this bump."
    PRD §3.2: "A `FINAL` assessment, before applying the weighted formula,
    adds 1 to the `pep_factor` (capped so it never exceeds 5) whenever the
    customer has at least one screening hit that is both `CONFIRMED` and
    derogatory at the moment of computation".

    With no confirmed derogatory hit, FINAL applies no bump, so PROVISIONAL and
    FINAL coincide on identical factors.

    Design: Difficulty/dual_variant_calc/risk_scoring_provisional_vs_final_band_flip
    """
    cust = validate_success(api.create_customer(create_customer_payload(), CO), 201)
    factors = dict(geography_factor=5, product_factor=3, pep_factor=4, adverse_media_factor=3)
    prov = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(variant="PROVISIONAL", **factors), CO), 201)
    final = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(variant="FINAL", **factors), CO), 201)
    # base = 5*4 + 3*3 + 4*5 + 3*3 = 20+9+20+9 = 58, max(pep,media)=4 -> no surcharge.
    assert prov["total_score"] == pytest.approx(58.00, abs=0.01)
    assert final["total_score"] == pytest.approx(58.00, abs=0.01)
    assert prov["risk_band"] == "MEDIUM"
    assert final["risk_band"] == "MEDIUM"


def test_alert_severity_high_customer_structuring(api):
    """PRD §3.7: "First take the rule base weight for the alert's `rule_code`:
    40 for `STRUCTURING`, 35 for `RAPID_MOVEMENT`, 25 for `HIGH_RISK_GEO`, and
    20 for `CTR_THRESHOLD`. Second take the customer-risk multiplier for the
    owning customer's `risk_rating` at mint time: 1.0 for `LOW`, 1.5 for
    `MEDIUM`, 2.0 for `HIGH`, and 2.0 for `PROHIBITED` (a prohibited rating uses
    the same multiplier as high); a customer with no rating yet uses a multiplier
    of 1.0. Third, the `severity_score` is the rule base weight multiplied by
    that multiplier, rounded half-up to two decimal places."

    STRUCTURING(40) * HIGH(2.0) = 80.00.

    Design: Difficulty/dual_variant_calc/alert_severity_varies_by_owning_customer_risk_rating
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=5, product_factor=4, pep_factor=4, adverse_media_factor=4),
        legal_entity=True)
    assert rated["risk_rating"] == "HIGH"
    acct = fx.create_account(rated["id"], account_ref="AC-SEV-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-01T10:00:00Z", counterparty_country="US"), SF), 201)
    alerts, _ = fx._list(api.list_account_alerts(acct["id"], CO))
    assert alerts[0]["rule_code"] == "STRUCTURING"
    assert alerts[0]["severity_score"] == pytest.approx(80.00, abs=0.01), alerts[0]["severity_score"]


def test_alert_severity_high_risk_geo_medium_customer(api):
    """PRD §3.7: "First take the rule base weight for the alert's `rule_code`:
    40 for `STRUCTURING`, 35 for `RAPID_MOVEMENT`, 25 for `HIGH_RISK_GEO`, and
    20 for `CTR_THRESHOLD`. Second take the customer-risk multiplier for the
    owning customer's `risk_rating` at mint time: 1.0 for `LOW`, 1.5 for
    `MEDIUM`, 2.0 for `HIGH`, and 2.0 for `PROHIBITED` (a prohibited rating uses
    the same multiplier as high); a customer with no rating yet uses a multiplier
    of 1.0. Third, the `severity_score` is the rule base weight multiplied by
    that multiplier, rounded half-up to two decimal places."

    HIGH_RISK_GEO(25) * MEDIUM(1.5) = 37.50.

    Design: Difficulty/dual_variant_calc/alert_severity_varies_by_owning_customer_risk_rating
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=3, product_factor=2, pep_factor=3, adverse_media_factor=2),
        legal_entity=True)
    assert rated["risk_rating"] == "MEDIUM"
    acct = fx.create_account(rated["id"], account_ref="AC-SEV-2")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-01T10:00:00Z", counterparty_country="IR"), SF), 201)
    alerts, _ = fx._list(api.list_account_alerts(acct["id"], CO))
    assert alerts[0]["rule_code"] == "HIGH_RISK_GEO"
    assert alerts[0]["severity_score"] == pytest.approx(37.50, abs=0.01), alerts[0]["severity_score"]


# ==========================================================================
# Queue A — combinatorial_formula
# ==========================================================================
def test_nonlinear_pep_surcharge_applied_once(api):
    """PRD §3.2: "A single non-linear surcharge then applies: when the larger of
    `pep_factor` and `adverse_media_factor` equals 5, a flat surcharge of 12 is
    added to the base — and because the surcharge keys off the maximum of the two
    factors rather than each independently, it is added at most once even when
    both factors are maxed."
    PRD §3.2: "a `total_score` of at least 84 yields `PROHIBITED`".

    base = 5*4+5*3+5*5+5*3 = 75, +12 surcharge (once) = 87 -> PROHIBITED.

    Design: Difficulty/combinatorial_formula/risk_scoring_nonlinear_pep_surcharge_mode_a
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Combo A", date_of_birth="1975-05-05"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(
            variant="PROVISIONAL", geography_factor=5, product_factor=5,
            pep_factor=5, adverse_media_factor=5), CO), 201)
    assert ra["total_score"] == pytest.approx(87.00, abs=0.01), ra["total_score"]
    assert ra["risk_band"] == "PROHIBITED"


def test_nonlinear_surcharge_not_applied_below_max(api):
    """PRD §3.2: "A single non-linear surcharge then applies: when the larger of
    `pep_factor` and `adverse_media_factor` equals 5, a flat surcharge of 12 is
    added to the base — and because the surcharge keys off the maximum of the two
    factors rather than each independently, it is added at most once even when
    both factors are maxed."

    With max(pep,media)=4 (neither maxed), NO surcharge fires: base
    5*4+5*3+4*5+4*3 = 67 exactly, with no +12.

    Design: Difficulty/combinatorial_formula/risk_scoring_nonlinear_pep_surcharge_mode_a
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(legal_name="Combo No Surcharge", date_of_birth="1975-05-05"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(
            variant="PROVISIONAL", geography_factor=5, product_factor=5,
            pep_factor=4, adverse_media_factor=4), CO), 201)
    assert ra["total_score"] == pytest.approx(67.00, abs=0.01), ra["total_score"]
    assert ra["risk_band"] == "HIGH"


def test_alert_severity_pinned_order_ctr_medium(api):
    """PRD §3.7: "First take the rule base weight for the alert's `rule_code`:
    40 for `STRUCTURING`, 35 for `RAPID_MOVEMENT`, 25 for `HIGH_RISK_GEO`, and
    20 for `CTR_THRESHOLD`. Second take the customer-risk multiplier for the
    owning customer's `risk_rating` at mint time: 1.0 for `LOW`, 1.5 for
    `MEDIUM`, 2.0 for `HIGH`, and 2.0 for `PROHIBITED` (a prohibited rating uses
    the same multiplier as high); a customer with no rating yet uses a multiplier
    of 1.0. Third, the `severity_score` is the rule base weight multiplied by
    that multiplier, rounded half-up to two decimal places."
    PRD §3.6: "if that post-addition total is strictly greater than 1,000,000
    cents (that is, strictly above 10,000 dollars), the rule `CTR_THRESHOLD`
    fires".

    Two 600,000 same-day cash-ins accumulate to 1,200,000 (> 1,000,000): CTR
    fires. CTR(20) * MEDIUM(1.5) = 30.00.

    Design: Difficulty/combinatorial_formula/alert_severity_pinned_evaluation_order_mode_c
    """
    rated = fx.create_and_rate_customer(
        factors=dict(geography_factor=3, product_factor=2, pep_factor=3, adverse_media_factor=2),
        legal_entity=True)
    assert rated["risk_rating"] == "MEDIUM"
    acct = fx.create_account(rated["id"], account_ref="AC-CTR-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-01T09:00:00Z", counterparty_country="US"), SF), 201)
    t2 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-01T15:00:00Z", counterparty_country="US"), SF), 201)
    assert t2["triggered_rule"] == "CTR_THRESHOLD"
    alerts, _ = fx._list(api.list_account_alerts(acct["id"], CO))
    assert alerts[0]["rule_code"] == "CTR_THRESHOLD"
    assert alerts[0]["severity_score"] == pytest.approx(30.00, abs=0.01), alerts[0]["severity_score"]


def test_alert_severity_pinned_order_unrated_customer_multiplier_one(api):
    """PRD §3.7: "Second take the customer-risk multiplier for the owning
    customer's `risk_rating` at mint time: 1.0 for `LOW`, 1.5 for `MEDIUM`, 2.0
    for `HIGH`, and 2.0 for `PROHIBITED` (a prohibited rating uses the same
    multiplier as high); a customer with no rating yet uses a multiplier of 1.0.
    Third, the `severity_score` is the rule base weight multiplied by that
    multiplier, rounded half-up to two decimal places."

    Same fixed 3-step order, but on an unrated customer the multiplier is 1.0:
    STRUCTURING(40) * 1.0 = 40.00, isolating step 2's null-rating branch.

    Design: Difficulty/combinatorial_formula/alert_severity_pinned_evaluation_order_mode_c
    """
    cust = fx.create_legal_entity(legal_name="Unrated Co")  # no rating applied
    acct = fx.create_account(cust["id"], account_ref="AC-UNR-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-01T10:00:00Z", counterparty_country="US"), SF), 201)
    alerts, _ = fx._list(api.list_account_alerts(acct["id"], CO))
    assert alerts[0]["rule_code"] == "STRUCTURING"
    assert alerts[0]["severity_score"] == pytest.approx(40.00, abs=0.01), alerts[0]["severity_score"]


# ==========================================================================
# Queue B — calculations: band boundaries, rules
# ==========================================================================
def test_risk_band_high_boundary_at_60(api):
    """PRD §3.2: "a `total_score` of at least 60 but below 84 yields `HIGH`".

    g=5,p=4,pep=4,media=3 -> 20+12+20+9 = 61 (>= 60) -> HIGH.

    Design: Corner/calculations/risk_scoring_band_boundary_high_at_60
    """
    cust = validate_success(api.create_customer(create_customer_payload(), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(
            variant="PROVISIONAL", geography_factor=5, product_factor=4,
            pep_factor=4, adverse_media_factor=3), CO), 201)
    assert ra["total_score"] == pytest.approx(61.00, abs=0.01)
    assert ra["risk_band"] == "HIGH"


def test_risk_band_medium_boundary_at_35(api):
    """PRD §3.2: "a `total_score` of at least 35 but below 60 yields `MEDIUM`".
    PRD §3.2: "when the larger of `pep_factor` and `adverse_media_factor` equals
    5, a flat surcharge of 12 is added to the base".

    g=2,p=3,pep=2,media=3 -> 8+9+10+9 = 36 (>= 35), max(pep,media)=3 so no
    surcharge -> MEDIUM.

    Design: Corner/calculations/risk_scoring_band_boundary_medium_at_35
    """
    cust = validate_success(api.create_customer(create_customer_payload(), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(
            variant="PROVISIONAL", geography_factor=2, product_factor=3,
            pep_factor=2, adverse_media_factor=3), CO), 201)
    assert ra["total_score"] == pytest.approx(36.00, abs=0.01)
    assert ra["risk_band"] == "MEDIUM"


def test_rapid_movement_at_90pct_credited(api):
    """PRD §3.6: "the rapid-movement rule: a `CASH_OUT` or `WIRE_OUT` fires
    `RAPID_MOVEMENT` when its `amount_cents` is at least 90 percent of the
    account's `cumulative_credited_cents` as observed before this transaction was
    folded in, where that 90-percent threshold is the product of 0.90 and the
    prior cumulative credited amount, rounded half-up to a whole cent before the
    comparison."
    PRD §3.6: "The `cumulative_credited_cents` is the lifetime running sum of all
    credited amounts — every `CASH_IN` and every `WIRE_IN`".

    WIRE_IN 1,000,000 sets credited; CASH_OUT of exactly 900,000 == 0.90 *
    1,000,000 fires RAPID_MOVEMENT (>= boundary). The WIRE_IN itself credits but
    is not a CASH_IN so does not enter the CTR cash window.

    Design: Corner/calculations/rapid_movement_threshold_at_90pct_credited
    """
    cust = fx.create_legal_entity()
    acct = fx.create_account(cust["id"], account_ref="AC-RAP-1")
    t_in = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="WIRE_IN", amount_cents=1000000,
                                               posted_at="2026-06-16T08:00:00Z", counterparty_country="US"), SF), 201)
    assert t_in["triggered_rule"] is None
    t_out = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_OUT", amount_cents=900000,
                                               posted_at="2026-06-16T10:00:00Z", counterparty_country="US"), SF), 201)
    assert t_out["triggered_rule"] == "RAPID_MOVEMENT"


def test_high_risk_geo_fires_on_sanctioned_country(api):
    """PRD §3.6: "the high-risk-geography rule: a transaction whose
    `counterparty_country` is one of IR, KP, SY, or CU fires `HIGH_RISK_GEO`."

    A small CASH_IN (below both CTR and the structuring band) from IR falls
    through to HIGH_RISK_GEO.

    Design: Corner/calculations/high_risk_geo_rule_fires_on_sanctioned_country
    """
    cust = fx.create_legal_entity()
    acct = fx.create_account(cust["id"], account_ref="AC-GEO-1")
    txn = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-17T08:00:00Z", counterparty_country="IR"), SF), 201)
    assert txn["triggered_rule"] == "HIGH_RISK_GEO"


def test_structuring_lower_boundary_inclusive(api):
    """PRD §3.6: "the structuring rule: a `CASH_IN` whose own `amount_cents` is at
    least 900,000 and at most 1,000,000 cents — the just-under-threshold band,
    inclusive at both ends — fires `STRUCTURING`."

    900,000 (== STRUCT_LOW) fires STRUCTURING; 899,999 fires nothing.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_structuring_band_lower_boundary
    """
    cust = fx.create_legal_entity()
    acct_low = fx.create_account(cust["id"], account_ref="AC-STR-LOW")
    acct_und = fx.create_account(cust["id"], account_ref="AC-STR-UND")
    low = validate_success(api.post_transaction(
        acct_low["id"], create_transaction_payload(direction="CASH_IN", amount_cents=900000,
                                                   posted_at="2026-06-27T08:00:00Z", counterparty_country="US"), SF), 201)
    und = validate_success(api.post_transaction(
        acct_und["id"], create_transaction_payload(direction="CASH_IN", amount_cents=899999,
                                                   posted_at="2026-06-27T08:00:00Z", counterparty_country="US"), SF), 201)
    assert low["triggered_rule"] == "STRUCTURING"
    assert und["triggered_rule"] is None
