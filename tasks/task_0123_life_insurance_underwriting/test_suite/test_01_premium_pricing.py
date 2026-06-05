"""Premium engine: provisional vs final variants, combinatorial table multipliers,
and the pinned round-per-step sequence.

Covers difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner provisional-premium correctness instance.
"""
from test_helpers import (
    validate_success,
    setup_application_under_review,
    setup_application_approved,
    create_product, create_underwriter, create_draft_application, submit_application,
    make_underwriter_headers,
    EXAM_PREFERRED, EXAM_STANDARD,
)


def test_provisional_and_final_premium_diverge_preferred(api):
    """PRD §3.5: "Consequently the final premium differs from the provisional whenever
    the assessed class is anything other than `STANDARD`."
    PRD §3.5: "the final premium follows the same pinned multiply-and-round sequence as
    the provisional one ... but its class multiplier is derived from the finalized
    assessment rather than assumed: `PREFERRED` uses 850 milli-units"
    PRD §3.2: "the class multiplier for the provisional variant is fixed at 1000 milli-units"

    Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_diverge_on_application
    """
    # Non-tobacco, PREFERRED build (h70/w160/bp120 -> build_debits 0 -> total 0 -> PREFERRED).
    ctx = setup_application_approved(
        exam_overrides=dict(EXAM_PREFERRED),
        applicant_overrides={"tobacco_use": False},
        app_overrides={"requested_face_amount_cents": 50_000_000},
    )
    app = ctx["application"]
    assert app["provisional_annual_premium_cents"] == 125000, app
    assert app["final_annual_premium_cents"] == 106250, app
    assert app["final_annual_premium_cents"] != app["provisional_annual_premium_cents"]
    assert app["status"] == "APPROVED_OFFER"


def test_risk_assessment_build_only_vs_impaired_diverge(api):
    """PRD §3.4: "A tobacco-using applicant adds 50 debits"
    PRD §3.4: "a total of 100 or more yields a `TABLE_N` class, where N is computed as the
    integer floor of the quantity (total debits minus 100) divided by 50, plus 1, and N is
    capped at 8."

    Design: Difficulty/dual_variant_calc/risk_build_only_vs_impaired_diverge_on_risk_assessment
    """
    # Tobacco applicant, build 50 (h70/w210/bp120) + tobacco 50 = total 100 -> TABLE_1.
    ctx = setup_application_under_review(
        exam_overrides=dict(EXAM_STANDARD),
        applicant_overrides={"tobacco_use": True},
    )
    ra_list, _ = _risk_assessment(api, ctx)
    ra = ra_list[0]
    assert ra["build_debits"] == 50, ra
    assert ra["total_debits"] == 100, ra
    assert ra["risk_class"] == "TABLE_1", ra
    assert ra["table_rating"] == 1, ra


def test_final_premium_three_input_nonlinear_table_multiplier(api):
    """PRD §3.5: "a `TABLE_N` class uses 1000 plus N times 250 milli-units, where N is the
    table rating"
    PRD §3.5: "The premium is the after-tobacco figure multiplied by this class multiplier
    divided by 1000, rounded half up to a whole cent."
    PRD §3.2: "a tobacco multiplier of 1500 milli-units applies when the applicant uses tobacco"

    Design: Difficulty/combinatorial_formula/final_premium_three_input_nonlinear_table_multiplier_mode_a
    """
    # Tobacco, TABLE_1 (build 50 + tobacco 50 = 100). face 50000000:
    # base 125000 -> after_tobacco round(125000*1500/1000)=187500 -> *1250/1000 = 234375.
    ctx = setup_application_approved(
        exam_overrides=dict(EXAM_STANDARD),
        applicant_overrides={"tobacco_use": True},
        app_overrides={"requested_face_amount_cents": 50_000_000},
    )
    app = ctx["application"]
    assert app["final_annual_premium_cents"] == 234375, app
    assert app["status"] == "APPROVED_OFFER"


def test_final_premium_round_per_step_not_round_at_end(api):
    """PRD §2.6: "The premium engine performs this rounding once per multiplication step
    in a pinned order rather than once at the end, so that intermediate results are
    themselves whole cents"
    PRD §3.2: "an after-tobacco figure is the base multiplied by the tobacco multiplier
    divided by 1000 and rounded half up to a whole cent, and the provisional premium is that
    after-tobacco figure multiplied by the class multiplier divided by 1000 and rounded half
    up to a whole cent."
    PRD §3.5: "The final premium follows the same pinned multiply-and-round sequence as the
    provisional one"

    Design: Difficulty/combinatorial_formula/premium_round_per_step_not_round_at_end_mode_b
    """
    # Product base_rate 101, face 50000000 -> thousands 500, base 50500.
    # Tobacco, STANDARD (build 0 + tobacco 50 = 50 -> STANDARD, class 1000).
    # after_tobacco round(50500*1500/1000)=75750, premium round(75750*1000/1000)=75750.
    ctx = setup_application_approved(
        product_overrides={"base_annual_rate_per_thousand_cents": 101},
        exam_overrides=dict(EXAM_PREFERRED),  # build 0 so total = tobacco 50 -> STANDARD
        applicant_overrides={"tobacco_use": True},
        app_overrides={"requested_face_amount_cents": 50_000_000},
    )
    app = ctx["application"]
    assert app["final_annual_premium_cents"] == 75750, app
    assert app["status"] == "APPROVED_OFFER"


def test_provisional_premium_correct_at_submit(api):
    """PRD §3.2: "Submission computes a provisional annual premium from the facts declared
    so far and writes it to `provisional_annual_premium_cents`, which is null until this point."
    PRD §3.2: "a base figure is that thousands count multiplied by the product's
    `base_annual_rate_per_thousand_cents`."

    Design: Corner/calculations/provisional_premium_correct_at_submit
    """
    product = create_product(base_annual_rate_per_thousand_cents=250, max_face_amount_cents=100_000_000)
    u = create_underwriter()
    _, app = create_draft_application(
        product["id"], u["id"],
        applicant_overrides={"tobacco_use": False},
        requested_face_amount_cents=50_000_000,
    )
    data = validate_success(api.submit_application(app["id"], make_underwriter_headers(u["id"])))
    assert data["provisional_annual_premium_cents"] == 125000, data


# ─── helper ────────────────────────────────────────────
def _risk_assessment(api, ctx):
    from test_helpers import validate_paginated
    resp = api.get_risk_assessment(ctx["application"]["id"], make_underwriter_headers(ctx["u2"]["id"]))
    return validate_paginated(resp)
