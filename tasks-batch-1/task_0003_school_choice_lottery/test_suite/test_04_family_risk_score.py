"""Tests for the family risk score (PRD §3.7): provisional vs final variant
divergence on DECLINED applications, and the empty-input boundary at zero
applications.
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    submit_application,
    advance_window_to_lottery_run,
    list_offers_for_application,
    decline_offer,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_success,
)


# =====================================================================
# Difficulty rule 1 / instance 2 — provisional vs final risk score
# diverge on DECLINED count
# =====================================================================

def test_family_risk_final_counts_declined_applications(api):
    """PRD §3.7: "The final variant, available post-finalization for audit,
    is 0.35 multiplied by the count of `DECLINED` applications plus 0.15
    multiplied by the count of `WAITLISTED` applications minus 0.20
    multiplied by the count of `ENROLLED` applications; this counts all
    terminal-state applications chronologically."

    A family with 2 DECLINED applications, 0 WAITLISTED, 0 ENROLLED must
    report risk-final = round(0.35 * 2, 3) = 0.700. The clamp at 1.000 is
    not exercised.

    Design: Difficulty/dual_variant_calc/family_risk_provisional_vs_final_diverge_on_declined_count
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DFR1", name="East", poverty_index_pct=0.00)
    schoolA = create_school(district["id"], code="SFR1A", name="EA",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=1)
    schoolB = create_school(district["id"], code="SFR1B", name="EB",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-FR1")
    family = register_family(district["id"], guardian_email="fr1@x.com",
                             residence_zone_code="ZFR1", poverty_flag=False)
    stuA = create_student(family["id"], full_name="StuA", grade_for_cycle=5)
    stuB = create_student(family["id"], full_name="StuB", grade_for_cycle=6)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    appA = create_application(family["id"], window["id"], stuA["id"],
                              schoolA["id"], choice_rank=1)
    submit_application(family["id"], appA["id"])
    appB = create_application(family["id"], window["id"], stuB["id"],
                              schoolB["id"], choice_rank=2)
    submit_application(family["id"], appB["id"])
    advance_window_to_lottery_run(window["id"])
    # Both are accepted (each school has 1 seat and 1 SUBMITTED app).
    offA = list_offers_for_application(appA["id"], family_id=family["id"])[0]
    offB = list_offers_for_application(appB["id"], family_id=family["id"])[0]
    decline_offer(family["id"], offA["id"])
    decline_offer(family["id"], offB["id"])
    res = api.get_family_risk_final(family["id"], make_guardian_headers(family["id"]))
    data = validate_success(res, 200)
    assert data["variant"] == "final", (
        f"risk-final must return variant='final'; got {data['variant']!r}"
    )
    assert data["risk_score"] == 0.700, (
        f"Final risk score = 0.35 * 2 DECLINED = 0.700; "
        f"got {data['risk_score']!r}"
    )


def test_family_risk_preview_excludes_declined_applications(api):
    """PRD §3.7: "The provisional variant, available while at least one of
    the family's applications is still `SUBMITTED`, is computed as 0.15
    multiplied by the count of the family's applications whose status is
    `WAITLISTED`, minus 0.20 multiplied by the count of the family's
    applications whose status is `ENROLLED`; declined applications are
    deliberately excluded, on the theory that a family with declined offers
    may still resubmit in the next cycle."

    Same scenario as the final test: a family with 2 DECLINED applications
    will, while at least one application is still SUBMITTED, report
    risk-preview = 0.000 — the provisional variant ignores DECLINED.

    Design: Difficulty/dual_variant_calc/family_risk_provisional_vs_final_diverge_on_declined_count
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DFR2", name="East2", poverty_index_pct=0.00)
    schoolA = create_school(district["id"], code="SFR2A", name="EA2",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=1)
    schoolB = create_school(district["id"], code="SFR2B", name="EB2",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=1)
    schoolC = create_school(district["id"], code="SFR2C", name="EC2",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-FR2")
    family = register_family(district["id"], guardian_email="fr2@x.com",
                             residence_zone_code="ZFR2", poverty_flag=False)
    stuA = create_student(family["id"], full_name="StuA", grade_for_cycle=5)
    stuB = create_student(family["id"], full_name="StuB", grade_for_cycle=6)
    stuC = create_student(family["id"], full_name="StuC", grade_for_cycle=7)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    appA = create_application(family["id"], window["id"], stuA["id"],
                              schoolA["id"], choice_rank=1)
    submit_application(family["id"], appA["id"])
    appB = create_application(family["id"], window["id"], stuB["id"],
                              schoolB["id"], choice_rank=2)
    submit_application(family["id"], appB["id"])
    advance_window_to_lottery_run(window["id"])
    offA = list_offers_for_application(appA["id"], family_id=family["id"])[0]
    offB = list_offers_for_application(appB["id"], family_id=family["id"])[0]
    decline_offer(family["id"], offA["id"])
    decline_offer(family["id"], offB["id"])
    # Reopen the gate for the provisional variant: at least one app must be
    # SUBMITTED. We add a fresh student in a NEW window and submit there.
    set_clock("2026-03-01T00:00:00Z")
    window2 = create_window(
        district["id"], cycle_label="2027-28-FR2",
        opens_at="2026-03-02T00:00:00Z",
        closes_at="2026-04-01T00:00:00Z",
        lottery_runs_at="2026-04-02T00:00:00Z",
    )
    set_clock("2026-03-03T00:00:00Z")
    open_window(window2["id"])
    appC = create_application(family["id"], window2["id"], stuC["id"],
                              schoolC["id"], choice_rank=1)
    submit_application(family["id"], appC["id"])
    # Provisional: 0 WAITLISTED, 0 ENROLLED, DECLINED excluded → 0.000.
    res = api.get_family_risk_preview(family["id"], make_guardian_headers(family["id"]))
    data = validate_success(res, 200)
    assert data["variant"] == "provisional", (
        f"risk-preview must return variant='provisional'; got {data['variant']!r}"
    )
    assert data["risk_score"] == 0.000, (
        f"Provisional risk score must exclude DECLINED apps "
        f"(2 declined, 0 waitlisted, 0 enrolled → 0.000); "
        f"got {data['risk_score']!r}"
    )


# =====================================================================
# Corner / calculations — zero-count boundary on family_risk_score
# =====================================================================

def test_family_risk_score_at_zero_count_returns_zero_for_both_variants(api):
    """PRD §3.7: "Both variants are rounded half-up to three decimal places
    and then clamped to the interval from 0.000 to 1.000 inclusive — values
    that would otherwise be negative are clipped to 0.000 and values
    exceeding 1.000 are clipped to 1.000."

    A newly registered family with zero applications: both endpoints must
    return risk_score=0.000.

    Design: Corner/calculations/family_risk_score_at_zero_count_returns_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DFRZ", name="Rz", poverty_index_pct=0.00)
    family = register_family(district["id"], guardian_email="rz@x.com",
                             residence_zone_code="ZFRZ", poverty_flag=False)
    res_prev = api.get_family_risk_preview(family["id"], make_guardian_headers(family["id"]))
    data_prev = validate_success(res_prev, 200)
    assert data_prev["risk_score"] == 0.000, (
        f"Zero-applications family must report risk-preview=0.000; "
        f"got {data_prev['risk_score']!r}"
    )
    res_fin = api.get_family_risk_final(family["id"], make_guardian_headers(family["id"]))
    data_fin = validate_success(res_fin, 200)
    assert data_fin["risk_score"] == 0.000, (
        f"Zero-applications family must report risk-final=0.000; "
        f"got {data_fin['risk_score']!r}"
    )
