"""Calculation results: GA composite/deviation, registration fees, complaint
brand rollup (PRD §3.6, §3.7, §3.8)."""
import pytest

from test_helpers import (
    assert_ga_report,
    create_brand_owner,
    create_complaint,
    create_formula,
    get_brand,
    lab_sample_payload,
    make_regulatory_affairs_headers,
    setup_batch_in_state,
    setup_registration,
    state_registration_payload,
    triage_complaint,
    validate_success,
)


def test_ga_spot_mean_and_deviation_index_misbranded(api, quality_analyst_headers):
    """PRD §3.6: "When no `COMPOSITE` sample exists, every weight is 1 and the
    composite is the plain mean of the spot readings."
    PRD §3.6: "The index is three times the protein deficit, plus two times the
    fat deficit, plus one and a half times the fiber excess, plus one times the
    moisture excess, rounded half up to 2 decimal places"
    PRD §3.6: "The report's `label_compliance` — default `PENDING` — resolves to
    `MISBRANDED` when the deviation index is greater than zero, and to `COMPLIANT`
    when it is exactly zero."

    Design: Corner/calculations/ga_spot_mean_and_deviation_index
    """
    # Label guarantees: protein >= 26.0, fat >= 9.0, fiber <= 3.0, moisture <= 10.0.
    ctx = setup_batch_in_state("COMPLETED", planned_kg=500.0, line_id="LINE-G1")
    batch_id = ctx["batch"]["id"]
    for position in ("FIRST", "MIDDLE"):
        validate_success(
            api.create_lab_sample(
                batch_id,
                lab_sample_payload(
                    sample_type=position,
                    measured_protein_pct=25.0,
                    measured_fat_pct=12.0,
                    measured_fiber_pct=2.0,
                    measured_moisture_pct=9.0,
                ),
                quality_analyst_headers,
            ),
            expected_status=201,
        )
    report = validate_success(api.create_ga_report(batch_id, quality_analyst_headers), 201)
    assert_ga_report(report)
    assert report["composite_protein_pct"] == pytest.approx(25.0, abs=0.005)
    # protein deficit 1.0 -> 3 * 1.0 = 3.0; all other nutrients within guarantee.
    assert report["deviation_index"] == pytest.approx(3.0, abs=0.005)
    assert report["label_compliance"] == "MISBRANDED"


def test_ga_spot_mean_compliant_when_within_label(api, quality_analyst_headers):
    """PRD §3.6: "The report's `label_compliance` — default `PENDING` — resolves
    to `MISBRANDED` when the deviation index is greater than zero, and to
    `COMPLIANT` when it is exactly zero."

    Design: Corner/calculations/ga_spot_mean_and_deviation_index
    """
    ctx = setup_batch_in_state("COMPLETED", planned_kg=500.0, line_id="LINE-G2")
    batch_id = ctx["batch"]["id"]
    for position in ("FIRST", "LAST"):
        validate_success(
            api.create_lab_sample(
                batch_id,
                lab_sample_payload(
                    sample_type=position,
                    measured_protein_pct=27.0,
                    measured_fat_pct=12.0,
                    measured_fiber_pct=2.0,
                    measured_moisture_pct=9.0,
                ),
                quality_analyst_headers,
            ),
            expected_status=201,
        )
    report = validate_success(api.create_ga_report(batch_id, quality_analyst_headers), 201)
    assert report["composite_protein_pct"] == pytest.approx(27.0, abs=0.005)
    assert report["deviation_index"] == pytest.approx(0.0, abs=0.005)
    assert report["label_compliance"] == "COMPLIANT"


def test_registration_fee_schedule_tiers(api):
    """PRD §3.7: "The annual registration fee is assessed in integer cents from a
    per-state base — 7500 cents for CA, 6000 cents for TX, 8000 cents for NY, and
    a default of 5000 cents for any other state — scaled by the declared tonnage
    tier. Tier boundaries are inclusive at their lower bound: below 5 tons pays
    the base fee; 5 tons up to but not including 50 tons pays one and a half
    times the base; 50 tons or more pays double. Multiplication results are
    rounded half up to whole cents."

    Design: Corner/calculations/registration_fee_schedule_tiers
    """
    # tonnage_tier declares prior-year tonnage (PRD §3.7): below 5 tons pays
    # the base fee; 5 to <50 tons pays 1.5x; 50+ tons pays double.
    ctx = setup_registration(target_state="SUBMITTED", state_code="CA", tonnage_tier=3.0)
    assert ctx["registration"]["fee_cents"] == 7500

    ra = make_regulatory_affairs_headers(ctx["brand"]["id"])
    oh = validate_success(
        api.create_state_registration(
            ctx["formula"]["id"],
            state_registration_payload(state_code="OH", tonnage_tier=3.0),
            ra,
        ),
        expected_status=201,
    )
    assert oh["fee_cents"] == 5000

    ny = validate_success(
        api.create_state_registration(
            ctx["formula"]["id"],
            state_registration_payload(state_code="NY", tonnage_tier=20.0),
            ra,
        ),
        expected_status=201,
    )
    assert ny["fee_cents"] == 12000


def test_complaint_brand_rollup_weighted_window(
    api, quality_analyst_headers, platform_admin_headers
):
    """PRD §3.8: "The brand-level `complaint_score` is a weighted mean over recent
    casework: final triage scores of the brand's cases sitting in `TRIAGED` or
    `INVESTIGATING` within the trailing 90-day window ending at the logical clock,
    with cases still in `TRIAGED` contributing at half weight. Recently closed
    cases do not vanish immediately: for 30 days after a case reaches `RESOLVED`
    or `CLOSED_NO_ACTION`, it continues to contribute one quarter of its final
    score."
    PRD §3.8: "Severity contributes 5 points for `MINOR`, 20 for `SERIOUS`, 45 for
    `LIFE_THREATENING`, and 60 for `DEATH`. Category contributes 2 for
    `PALATABILITY`, 3 for `PACKAGING`, 8 for `LABEL_DEFECT`, 12 for
    `FOREIGN_MATERIAL`, and 15 for `ILLNESS`."

    Design: Corner/calculations/complaint_brand_rollup_weighted_window
    """
    brand = create_brand_owner()
    formula = create_formula(brand["id"])

    case1 = create_complaint(brand["id"], formula["id"], "SERIOUS", "ILLNESS", False)
    t1 = triage_complaint(case1["id"], confirm_flag=False)
    assert t1["triage_score"] == pytest.approx(35.0, abs=0.005)

    case2 = create_complaint(
        brand["id"], formula["id"], "LIFE_THREATENING", "FOREIGN_MATERIAL", False
    )
    t2 = triage_complaint(case2["id"], confirm_flag=False)
    assert t2["triage_score"] == pytest.approx(57.0, abs=0.005)

    # Both TRIAGED (half weight each): (35*0.5 + 57*0.5) / (0.5 + 0.5) == 46.0.
    brand_now = get_brand(brand["id"])
    assert brand_now["complaint_score"] == pytest.approx(46.0, abs=0.005)

    # Resolve case2: it keeps one quarter of its score; (17.5 + 14.25) / 0.75 == 42.33.
    validate_success(api.open_investigation(case2["id"], quality_analyst_headers))
    validate_success(api.resolve_complaint(case2["id"], quality_analyst_headers))
    brand_now = get_brand(brand["id"])
    assert brand_now["complaint_score"] == pytest.approx(42.33, abs=0.005)

    # Advance the logical clock 31 days: case2's 30-day decay share expires,
    # case1 (TRIAGED, 31 days old) is still inside the 90-day window.
    validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, platform_admin_headers)
    )
    brand_now = get_brand(brand["id"])
    assert brand_now["complaint_score"] == pytest.approx(35.0, abs=0.005)
