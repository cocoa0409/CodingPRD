"""Disproportionality reporting: dual comparison measures, rounding order,
expunged-row exclusion, and the reference-group requirement."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_expungement_request_payload, create_expungement_decision_payload,
    set_clock, create_offense_code_with_bands, create_student,
    create_sanctioned_case, issue_notice, confirm_case, close_case,
    setup_disproportionality_scenario, get_report, group_row,
    make_parent_guardian_headers, make_district_admin_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
CLS = TEST_USERS["school_classifier_headers"]


# ─── Difficulty: RISK_RATIO vs SHARE_GAP divergence ───

def test_report_risk_ratio_and_share_gap_diverge(api):
    """PRD §3.9: "The `risk_ratio` divides the group's risk by the reference
    group's risk — the division is performed at full precision and only the
    resulting ratio is rounded half-up to two decimal places". "The
    `share_gap` subtracts the group's share of total enrollment from its share
    of all disciplined students and rounds the difference half-up to four
    decimal places, a composition measure whose magnitude and sign structure
    differ from the ratio's for identical data."

    Design: Difficulty/dual_variant_calc/risk_ratio_vs_share_gap_diverge_on_same_report
    """
    setup_disproportionality_scenario()
    report = get_report()
    assert report["groups_evaluated"] == 2

    black = group_row(report, "BLACK")
    # risk = 1/6 -> 0.1667; share_gap = 1/2 - 6/9 -> -0.1667.
    assert black["risk"] == pytest.approx(0.1667, abs=1e-9)
    assert black["risk_ratio"] == pytest.approx(0.5, abs=1e-9)
    assert black["share_gap"] == pytest.approx(-0.1667, abs=1e-9)
    # The two measures diverge on identical inputs, down to the sign.
    assert black["risk_ratio"] != black["share_gap"]


def test_report_reference_group_row_is_identity(api):
    """PRD §3.9: "The `risk_ratio` divides the group's risk by the reference
    group's risk". "The `share_gap` subtracts the group's share of total
    enrollment from its share of all disciplined students and rounds the
    difference half-up to four decimal places".

    Design: Difficulty/dual_variant_calc/risk_ratio_vs_share_gap_diverge_on_same_report
    """
    setup_disproportionality_scenario()
    report = get_report()

    white = group_row(report, "WHITE")
    # risk = 1/3; ratio against itself is exactly 1; share_gap = 1/2 - 3/9.
    assert white["risk"] == pytest.approx(0.3333, abs=1e-9)
    assert white["risk_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert white["share_gap"] == pytest.approx(0.1667, abs=1e-9)

    black = group_row(report, "BLACK")
    assert black["risk"] == pytest.approx(0.1667, abs=1e-9)


# ─── Difficulty: divide-then-round pinning ────────────

def test_report_risk_ratio_divides_at_full_precision_then_rounds(api):
    """PRD §3.9: "the division is performed at full precision and only the
    resulting ratio is rounded half-up to two decimal places; rounding either
    group's risk before dividing is forbidden."
    PRD §2.10: "Report metrics are the sole exception to the no-rounding rule:
    they are rounded half-up, and every division entering them is performed at
    full precision before any rounding occurs."

    Design: Difficulty/combinatorial_formula/risk_ratio_rounding_order_divide_then_round
    """
    setup_disproportionality_scenario()
    report = get_report()
    black = group_row(report, "BLACK")
    # Full precision: (1/6)/(1/3) = 0.5 exactly. The forbidden round-first
    # order would give round(0.17/0.33, 2) == 0.52.
    assert black["risk_ratio"] == pytest.approx(0.5, abs=1e-9), (
        f"divide-then-round must yield 0.5, got {black['risk_ratio']}")
    assert not (black["risk_ratio"] == pytest.approx(0.52, abs=1e-9)), (
        "the implementation must not round group risks before dividing")


def test_report_displayed_risk_rounded_without_feeding_ratio(api):
    """PRD §3.9: "Each surviving group reports a displayed `risk`: the
    quotient of its disciplined students over its enrolled students, computed
    at full precision and rounded half-up to four decimal places."
    PRD §2.10: "The per-group displayed `risk` and each `share_gap` are
    rounded half-up to four decimal places; each `risk_ratio` is rounded
    half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/risk_ratio_rounding_order_divide_then_round
    """
    setup_disproportionality_scenario()
    report = get_report()
    black = group_row(report, "BLACK")
    # 1/6 displayed at 4 decimals; the ratio uses the unrounded quotient.
    assert black["risk"] == pytest.approx(0.1667, abs=1e-9)
    assert black["risk_ratio"] == pytest.approx(0.5, abs=1e-9)
    white = group_row(report, "WHITE")
    assert white["risk"] == pytest.approx(0.3333, abs=1e-9)


# ─── Corner: expunged exclusion and reference gate ────

def test_report_excludes_expunged_cases(api):
    """PRD §3.9: "those with at least one case in `CONFIRMED` or `CLOSED`
    status whose `incident_date` falls inside the window, `EXPUNGED` cases
    excluded."
    PRD §3.8: "every `CLOSED` case of the student becomes `EXPUNGED`, and the
    student's `cumulative_suspension_days` is recomputed with the expunged
    rows excluded".

    Design: Corner/calculations/report_excludes_expunged_cases
    """
    oc = create_offense_code_with_bands(
        bands=((1, 1, 2),), code="TARD-01", title="Tardiness",
        category="ATTENDANCE", severity_level=1)
    b1 = create_student(full_name="B One", date_of_birth="2010-01-01T00:00:00Z",
                        demographic_group="BLACK", guardian_id="gb1")
    w1 = create_student(full_name="W One", date_of_birth="2010-02-01T00:00:00Z",
                        demographic_group="WHITE", guardian_id="gw1")
    create_student(full_name="W Two", date_of_birth="2010-02-02T00:00:00Z",
                   demographic_group="WHITE", guardian_id="gw2")
    # Both referrals are worked at the same clock (2026-03-01), then both are
    # confirmed past the appeal deadline and closed the next day.
    set_clock("2026-03-01T00:00:00Z")
    worked = []
    for student, desc in ((b1, "b1 tardy"), (w1, "w1 tardy")):
        case = create_sanctioned_case(
            student["id"], oc["id"], "2026-02-20T08:00:00Z",
            sanction_days=1, sanction_type="IN_SCHOOL", description=desc)
        issue_notice(case["id"], "EMAIL")
        worked.append(case)
    set_clock("2026-03-08T00:00:00Z")
    confirmed = [confirm_case(c["id"]) for c in worked]
    set_clock("2026-03-09T00:00:00Z")  # confirmed 03-08 + 1 day
    for c in confirmed:
        close_case(c["id"])

    pre = get_report()
    assert pre["groups_evaluated"] == 2
    assert group_row(pre, "BLACK")["risk"] == pytest.approx(1.0, abs=1e-9), (
        "b1 is the only BLACK student and is disciplined: risk 1/1")

    # Past the 730-day wait (2026-03-09 + 731 days, spanning leap day).
    set_clock("2028-03-09T00:00:00Z")
    request = validate_success(api.create_expungement_request(
        create_expungement_request_payload(b1["id"]),
        make_parent_guardian_headers("gb1")), 201)
    validate_success(api.decide_expungement_request(
        request["id"], create_expungement_decision_payload("APPROVED"),
        make_district_admin_headers("da_1")), 200)

    post = get_report()
    black = group_row(post, "BLACK")
    assert black["risk"] == pytest.approx(0.0, abs=1e-9), (
        "the EXPUNGED case is excluded even though its incident_date lies in "
        "the academic-year window")
    assert black["risk_ratio"] == pytest.approx(0.0, abs=1e-9)
    white = group_row(post, "WHITE")
    assert white["risk"] == pytest.approx(0.5, abs=1e-9), (
        "WHITE is unchanged: one disciplined of two enrolled")
    assert white["risk_ratio"] == pytest.approx(1.0, abs=1e-9)


def test_report_reference_group_without_discipline_returns_422(api):
    """PRD §3.9: "The reference group must itself have both enrolled and
    disciplined students above zero in the requested year, or the report is
    rejected with `ERR_INVALID_REFERENCE_GROUP`."

    Design: Corner/calculations/report_reference_group_without_discipline_returns_422
    """
    for i, gid in enumerate(("gwa", "gwb", "gwc"), start=1):
        create_student(full_name=f"W {gid}", date_of_birth=f"2010-02-0{i}T00:00:00Z",
                       demographic_group="WHITE", guardian_id=gid)
    res = api.get_disproportionality_report(
        ADMIN, params={"academic_year": "2025-2026", "reference_group": "WHITE"})
    validate_error(res, ApiErrorId.ERR_INVALID_REFERENCE_GROUP,
                   expected_status=422)
