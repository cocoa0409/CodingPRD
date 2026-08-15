"""Most-favored-licensee sweep: RETROACTIVE credit vs PROSPECTIVE re-rate,
and the two-hop activation cascade (PRD sections 3.3, 2.10)."""
from test_helpers import (
    create_accepted_report,
    create_active_agreement,
    create_agreement_payload,
    create_licensee,
    get_agreement,
    get_licensee,
    make_report_line,
    validate_success,
)


def _agreement_with_accepted_report(licensee, patent, *, rate_bp, mfl_clause,
                                    mfl_mode=None, lookback=4):
    """Create + activate an agreement and accept one report of net 1000000."""
    overrides = {
        "patent_reference": patent,
        "base_rate_bp": rate_bp,
        "minimum_period_royalty_cents": 0,
        "mfl_clause": mfl_clause,
        "underreport_tolerance_bp": 1000,
    }
    if mfl_mode is not None:
        overrides["mfl_mode"] = mfl_mode
        overrides["mfl_lookback_quarters"] = lookback
    licensee, agreement = create_active_agreement(licensee, **overrides)
    create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(product_label="A", units_sold=100,
                                gross_sales_cents=1_000_000)],
    )
    return licensee, agreement


def test_mfl_retroactive_vs_prospective_credit(api, analyst_headers):
    """PRD section 3.3: "Under `PROSPECTIVE`, the rate change is the whole
    remedy: `last_mfl_credit_cents` stays at 0 and no money moves. Under
    `RETROACTIVE`, the office also makes the favored licensee whole for the
    recent past." and "The credits sum to the agreement's new
    `last_mfl_credit_cents`, and that same total is added to the contracting
    licensee's `credit_balance_cents` — a second hop of the activation
    cascade, after the rate adjustment itself."

    Design: Difficulty/dual_variant_calc/mfl_retroactive_vs_prospective_credit
    """
    patent = "US-20200-A1"
    l1 = create_licensee(legal_name="Retro Co")
    l2 = create_licensee(legal_name="Pro Co")
    l3 = create_licensee(legal_name="New Co")

    # M1: 500 bp, RETROACTIVE, one accepted report with final 50000.
    _, m1 = _agreement_with_accepted_report(
        l1, patent, rate_bp=500, mfl_clause=True, mfl_mode="RETROACTIVE", lookback=4
    )
    # M2: 500 bp, PROSPECTIVE, one accepted report with final 50000.
    _, m2 = _agreement_with_accepted_report(
        l2, patent, rate_bp=500, mfl_clause=True, mfl_mode="PROSPECTIVE", lookback=4
    )

    # New agreement N at 400 bp on the same patent, then ACTIVATE.
    n = validate_success(
        api.create_agreement(
            create_agreement_payload(
                l3["id"], patent_reference=patent, title="N cheap", base_rate_bp=400,
                minimum_period_royalty_cents=0, mfl_clause=False,
                underreport_tolerance_bp=1000,
                effective_date="2026-06-01T00:00:00Z",
            ),
        analyst_headers,
    ),
        expected_status=201,
    )
    validate_success(api.agreement_lifecycle(n["id"], {"action": "ACTIVATE"}, analyst_headers))

    # RETROACTIVE: re-price 1000000 at 400 bp -> 40000; credit = 50000 - 40000 = 10000.
    m1_after = get_agreement(m1["id"])
    assert m1_after["mfl_adjusted_rate_bp"] == 400
    assert m1_after["last_mfl_credit_cents"] == 10_000
    assert get_licensee(l1["id"])["credit_balance_cents"] == 10_000

    # PROSPECTIVE: re-rate only, no credit.
    m2_after = get_agreement(m2["id"])
    assert m2_after["mfl_adjusted_rate_bp"] == 400
    assert m2_after["last_mfl_credit_cents"] == 0
    assert get_licensee(l2["id"])["credit_balance_cents"] == 0


def test_mfl_sweep_only_fires_when_new_rate_is_lower(api, analyst_headers):
    """PRD section 3.3: "The sweep only ever lowers rates; an existing
    agreement already enjoying an equal or lower effective rate is untouched."

    Design: Difficulty/dual_variant_calc/mfl_retroactive_vs_prospective_credit
    """
    patent = "US-20201-A2"
    l1 = create_licensee(legal_name="Keep Co")
    l2 = create_licensee(legal_name="High Co")

    # Existing agreement at 400 bp with MFL clause.
    _, m1 = _agreement_with_accepted_report(
        l1, patent, rate_bp=400, mfl_clause=True, mfl_mode="RETROACTIVE", lookback=4
    )
    # New agreement at a HIGHER rate (500 bp) must not move M1.
    n = validate_success(
        api.create_agreement(
            create_agreement_payload(
                l2["id"], patent_reference=patent, title="N pricey", base_rate_bp=500,
                mfl_clause=False, underreport_tolerance_bp=1000,
                effective_date="2026-06-01T00:00:00Z",
            ),
        analyst_headers,
    ),
        expected_status=201,
    )
    validate_success(api.agreement_lifecycle(n["id"], {"action": "ACTIVATE"}, analyst_headers))

    m1_after = get_agreement(m1["id"])
    assert m1_after["mfl_adjusted_rate_bp"] is None
    assert m1_after["last_mfl_credit_cents"] == 0
    assert get_licensee(l1["id"])["credit_balance_cents"] == 0


def test_mfl_activation_credit_chain(api, analyst_headers):
    """PRD section 3.3: "For each such agreement whose effective rate — its
    `mfl_adjusted_rate_bp` if one is set, otherwise its `base_rate_bp` —
    exceeds the newly activated agreement's `base_rate_bp`, the clause fires:
    the existing agreement's `mfl_adjusted_rate_bp` is set down to the new
    agreement's base rate" and "The credits sum to the agreement's new
    `last_mfl_credit_cents`, and that same total is added to the contracting
    licensee's `credit_balance_cents` — a second hop of the activation
    cascade, after the rate adjustment itself."

    Design: Difficulty/transitive_cascade/mfl_activation_credit_chain
    """
    patent = "US-80800-G1"
    l1 = create_licensee(legal_name="Old Co")
    l2 = create_licensee(legal_name="Cheap Co")

    _, m1 = _agreement_with_accepted_report(
        l1, patent, rate_bp=500, mfl_clause=True, mfl_mode="RETROACTIVE", lookback=4
    )

    n = validate_success(
        api.create_agreement(
            create_agreement_payload(
                l2["id"], patent_reference=patent, title="N", base_rate_bp=400,
                minimum_period_royalty_cents=0, mfl_clause=False,
                underreport_tolerance_bp=1000,
                effective_date="2026-06-01T00:00:00Z",
            ),
        analyst_headers,
    ),
        expected_status=201,
    )
    validate_success(api.agreement_lifecycle(n["id"], {"action": "ACTIVATE"}, analyst_headers))

    m1_after = get_agreement(m1["id"])
    # Hop 1: rate adjusted + credit computed (50000 - 40000).
    assert m1_after["mfl_adjusted_rate_bp"] == 400
    assert m1_after["last_mfl_credit_cents"] == 10_000
    # Hop 2: the licensee's credit balance mutated as a consequence of hop 1.
    assert get_licensee(l1["id"])["credit_balance_cents"] == 10_000


def test_mfl_sweep_ignores_agreements_without_clause(api, analyst_headers):
    """PRD section 3.3: "the system examines every other agreement covering
    the same `patent_reference` that is currently `ACTIVE` and carries
    `mfl_clause` set to true." Agreements without the clause are untouched.

    Design: Difficulty/transitive_cascade/mfl_activation_credit_chain
    """
    patent = "US-80801-G2"
    l1 = create_licensee(legal_name="Plain Co")
    l2 = create_licensee(legal_name="Drop Co")

    # M1 at 500 bp WITHOUT the MFL clause.
    _, m1 = _agreement_with_accepted_report(
        l1, patent, rate_bp=500, mfl_clause=False
    )
    n = validate_success(
        api.create_agreement(
            create_agreement_payload(
                l2["id"], patent_reference=patent, title="N2", base_rate_bp=400,
                mfl_clause=False, underreport_tolerance_bp=1000,
                effective_date="2026-06-01T00:00:00Z",
            ),
        analyst_headers,
    ),
        expected_status=201,
    )
    validate_success(api.agreement_lifecycle(n["id"], {"action": "ACTIVATE"}, analyst_headers))

    m1_after = get_agreement(m1["id"])
    assert m1_after["mfl_adjusted_rate_bp"] is None
    assert m1_after["last_mfl_credit_cents"] == 0
    assert get_licensee(l1["id"])["credit_balance_cents"] == 0
