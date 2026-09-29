"""Multi-factor arithmetic whose factors interact, and whose order is pinned.

Three formulas are exercised here: the penalty multiplier chain with its
rounded-then-clamped ceiling, the round-then-sum booking of transaction lines,
and the tier that is read before the assessment books its own points.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import (
    assert_discrepancy_rates,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_submission_totals,
)
from test_helpers.types import (
    AuditFinding,
    DelinquencyTier,
    PenaltyStatus,
    PurchaseType,
    RegistrationStatus,
    SubmissionStatus,
    SuspendedReason,
    ViolationType,
)


def _delta_firm(api):
    """Delta Packing: one cattle plant averaging 126,000 head, ACTIVE for 2026."""
    return fx.obligated_firm(api, legal_name="Delta Packing", plant_code="EST-404")


def test_01_repeat_escalation_then_the_per_assessment_cap_clamps_the_third_row(api):
    """Five factors compose, and the third row is clamped after rounding.

    Three failures to register escalate 1.00 -> 1.50 -> 2.00 on recidivism over
    a 1,000,000-cent base lifted 1.126 times on volume, so the third row's raw
    2,252,000 cents is clamped to the 2,000,000-cent per-assessment ceiling.

    PRD §3.8: "That raw figure is then rounded half up to a whole number of
    cents, and" only after rounding "is it clamped: `assessed_amount_cents` is
    the smaller of 2,000,000 cents".

    Design: Difficulty/combinatorial_formula/penalty_multiplier_chain_with_capped_nonlinear_uplift
    """
    firm = _delta_firm(api)

    penalties = fx.assess_non_registration_penalties(api, firm["entity"]["id"], 3)

    assert_penalty_breakdown(
        penalties[0],
        base_amount_cents=1000000,
        repeat_index=0,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        assessed_amount_cents=1126000,
    )
    assert_penalty_breakdown(
        penalties[1],
        repeat_index=1,
        repeat_multiplier=1.50,
        assessed_amount_cents=1689000,
    )
    assert_penalty_breakdown(
        penalties[2],
        base_amount_cents=1000000,
        days_late=0,
        day_tier_multiplier=1.00,
        repeat_index=2,
        repeat_multiplier=2.00,
        volume_factor=1.126,
        suspension_surcharge=1.00,
        assessed_amount_cents=2000000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_1.value,
    )
    assert penalties[2]["assessed_amount_cents"] != 2252000, (
        "the raw 2252000 must be clamped to the per-assessment ceiling"
    )


def test_02_the_capped_third_assessment_still_books_its_full_points(api):
    """Clamping the money does not clamp the points or the enforcement chain.

    The ceiling caps the third row's cents but not its eight points, so the
    firm crosses into the top tier on 24 points and its registration is
    suspended for the delinquency breach.

    PRD §2.11: "`assessed_penalty_cents` is the sum of `assessed_amount_cents`
    across every assessment regardless of settlement state".

    Design: Difficulty/combinatorial_formula/penalty_multiplier_chain_with_capped_nonlinear_uplift
    """
    firm = _delta_firm(api)

    fx.assess_non_registration_penalties(api, firm["entity"]["id"], 3)

    entity = fx.read_entity(api, firm["entity"]["id"])
    assert_penalty_ledger(
        entity,
        assessed_penalty_cents=4815000,
        paid_penalty_cents=0,
        waived_penalty_cents=0,
        outstanding_penalty_cents=4815000,
        delinquency_points=24,
    )

    registration = fx.read_registration(api, firm["registration"]["id"])
    assert registration["status"] == RegistrationStatus.SUSPENDED.value, registration
    assert (
        registration["suspended_reason"] == SuspendedReason.DELINQUENCY_TIER_BREACH.value
    ), registration


def test_03_each_transaction_line_rounds_before_the_filing_sums_them(api):
    """Two lines worth 2427.1750 each book 4854.36, not 4854.35.

    The value is rounded at the line and only the already-rounded figures are
    added, so the booked total is a cent above what a single final rounding of
    the full-precision sum would produce.

    PRD §2.7: "Two transaction lines each worth 2427.1750 dollars therefore book
    as 2427.18 plus 2427.18, that is 4854.36 — not the 4854.35 that summing at
    full precision and rounding once would give."

    Design: Difficulty/combinatorial_formula/per_record_round_then_sum_line_value
    """
    firm = fx.alpha_firm(api)
    window = fx.create_window(api)
    filing = fx.draft_filing(
        api, firm["entity"]["id"], firm["plant"]["id"], window["id"]
    )

    line = f.transaction_payload(
        purchase_type=PurchaseType.NEGOTIATED.value,
        head_count=1,
        avg_net_price_per_cwt=285.55,
        avg_carcass_weight_cwt=8.50,
    )
    for _ in range(2):
        recorded = fx.add_transaction(
            api, firm["entity"]["id"], filing["id"], dict(line)
        )
        assert recorded["line_value_dollars"] == 2427.18, recorded

    booked = fx.read_submission(api, filing["id"])
    assert booked["reported_value_dollars"] == 4854.36, booked
    assert booked["reported_value_dollars"] != 4854.35, (
        "summing at full precision and rounding once is not the booking rule"
    )


def test_04_the_remaining_booked_totals_follow_the_same_line_discipline(api):
    """Hundredweight rounds per line too, and the wholesale totals stay at zero.

    Each line's head times carcass weight is rounded before it is added, so two
    lines of one head at 8.50 hundredweight book 17.00, while a live-animal
    filing books no pounds and no loads at all.

    PRD §3.4: "its `reported_cwt` is the sum, over the same lines, of each line's
    `head_count` multiplied by its `avg_carcass_weight_cwt` with that per-line
    product rounded half up to 2 decimals before it is added in".

    Design: Difficulty/combinatorial_formula/per_record_round_then_sum_line_value
    """
    firm = fx.alpha_firm(api)
    window = fx.create_window(api)
    filing = fx.draft_filing(
        api, firm["entity"]["id"], firm["plant"]["id"], window["id"]
    )

    for _ in range(2):
        fx.add_transaction(
            api,
            firm["entity"]["id"],
            filing["id"],
            f.transaction_payload(
                head_count=1,
                avg_net_price_per_cwt=285.55,
                avg_carcass_weight_cwt=8.50,
            ),
        )

    booked = fx.read_submission(api, filing["id"])
    assert_submission_totals(
        booked,
        reported_head=2,
        reported_cwt=17.00,
        reported_value_dollars=4854.36,
        reported_pounds=0,
        reported_load_count=0,
    )


def test_05_the_tier_is_read_before_the_assessment_books_its_own_points(api):
    """An assessment never sees the consequences of itself.

    With 24 points already standing the pre-read tier is the top one, which
    both doubles this row's five points to ten and -- through the registration
    status read at the same instant -- applies the 1.25 suspension surcharge to
    a 500,000-cent base lifted 1.126 times on volume.

    PRD §3.8: "`suspension_surcharge` is 1.25 when the governing registration's
    `status` read before this assessment was `SUSPENDED`, and 1.00 otherwise."

    Design: Difficulty/combinatorial_formula/tier_read_before_own_points_then_doubling
    """
    firm = _delta_firm(api)
    window = fx.create_window(api)
    filing = fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=400,
                avg_net_price_per_cwt=284.00,
                avg_carcass_weight_cwt=8.50,
            )
        ],
    )
    assert_submission_totals(
        fx.read_submission(api, filing["id"]),
        reported_head=400,
        reported_value_dollars=965600.00,
    )

    case = fx.discrepant_case(api, filing["id"], 380, 965600.00)
    assert_discrepancy_rates(case, 5.26, 0.00, AuditFinding.MATERIAL_HEAD.value)

    fx.assess_non_registration_penalties(api, firm["entity"]["id"], 3)

    assessment = fx.assess_penalty(
        api,
        firm["entity"]["id"],
        ViolationType.INACCURATE_DATA.value,
        officer=u.PENALTY_OFFICER_2,
        audit_case_id=case["id"],
    )

    assert_penalty_breakdown(
        assessment,
        base_amount_cents=500000,
        day_tier_multiplier=1.00,
        repeat_index=0,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        suspension_surcharge=1.25,
        assessed_amount_cents=703750,
        points=10,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_2.value,
    )
    assert assessment["status"] == PenaltyStatus.ASSESSED.value


def test_06_doubled_points_land_on_the_ledger_and_revoke_the_registration(api):
    """The doubled points are added only after the money is computed.

    Twenty-four points plus this row's doubled ten make 34, and because the
    governing registration was already suspended the second top-tier landing
    revokes it -- while the filing reopened by the audit is not voided with the
    firm's in-flight work.

    PRD §3.8: "A governing registration already in `SUSPENDED` status moves
    `SUSPENDED → REVOKED` instead, and `suspended_reason` is cleared to null".

    Design: Difficulty/combinatorial_formula/tier_read_before_own_points_then_doubling
    """
    firm = _delta_firm(api)
    window = fx.create_window(api)
    filing = fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=400,
                avg_net_price_per_cwt=284.00,
                avg_carcass_weight_cwt=8.50,
            )
        ],
    )
    case = fx.discrepant_case(api, filing["id"], 380, 965600.00)
    fx.assess_non_registration_penalties(api, firm["entity"]["id"], 3)

    fx.assess_penalty(
        api,
        firm["entity"]["id"],
        ViolationType.INACCURATE_DATA.value,
        officer=u.PENALTY_OFFICER_2,
        audit_case_id=case["id"],
    )

    entity = fx.read_entity(api, firm["entity"]["id"])
    assert_penalty_ledger(
        entity,
        assessed_penalty_cents=5518750,
        outstanding_penalty_cents=5518750,
        delinquency_points=34,
    )

    registration = fx.read_registration(api, firm["registration"]["id"])
    assert registration["status"] == RegistrationStatus.REVOKED.value, registration
    assert registration["suspended_reason"] is None, registration

    audited = fx.read_submission(api, filing["id"])
    assert audited["status"] == SubmissionStatus.UNDER_CORRECTION.value, audited
