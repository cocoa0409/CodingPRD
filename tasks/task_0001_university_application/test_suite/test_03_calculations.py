"""Calculation tests: demonstrated_need, admission_probability_score,
school_yield_quota, school_yield_rate.

Covers Corner-design Section 3 + difficulty rules 1 (dual variant) and
2 (combinatorial formula).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_clock_and_school, register_applicant, create_application,
    create_essay, invite_and_accept_recommender, create_and_submit_letter,
    setup_applicant_ready, setup_admitted_application,
    setup_admitted_with_fa_profile,
    submit_application, start_review, decide,
    create_fa_profile_payload, create_aid_offer_payload,
    make_applicant_headers, fa_officer_headers, admissions_headers,
    api_client,
)


# ============================================================================
# Difficulty Rule 1 — Dual-variant calculations
# ============================================================================

def test_aid_offer_federal_vs_institutional_demonstrated_need_diverges(api):
    """PRD §3.6: "the applicable EFC is fafsa_efc_cents from the linked
    FinancialAidProfile when variant is FEDERAL, and css_efc_cents from
    the linked profile when variant is INSTITUTIONAL."
    PRD §3.6: "The demonstrated_need_cents is the maximum of zero and the
    difference between cost_of_attendance_cents and the applicable EFC"

    Design: Difficulty/dual_variant_calc/aid_offer_federal_vs_institutional_divergence
    """
    # Build an Applicant ADMITTED on a CSS-requiring school, with a FA
    # profile carrying both fafsa and css EFC values.
    applicant, school, admitted, fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=2_000_000,
        css_efc_cents=3_500_000,
        family_income_cents=8_000_000,
        school_overrides={"requires_css_profile": True,
                          "name": "Stanford-DV"},
    )

    # Issue a FEDERAL offer with COA=8_000_000 → need = max(0, 8M - 2M) = 6M
    federal_res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=8_000_000,
            variant="FEDERAL",
            grant_cents=0, loan_cents=0, work_study_cents=0),
        fa_officer_headers())
    federal = validate_success(federal_res, 201)
    assert federal["demonstrated_need_cents"] == 6_000_000
    assert federal["variant"] == "FEDERAL"
    assert federal["net_price_cents"] == 8_000_000

    # An INSTITUTIONAL offer on the same input set would use css_efc_cents
    # = 3,500,000 → demonstrated_need = max(0, 8M - 3.5M) = 4.5M < 6M.
    # We can't issue a second AidOffer (application_id unique), but we
    # can build a parallel application and verify INSTITUTIONAL math is
    # different.
    applicant2, school2, admitted2, _fa2 = setup_admitted_with_fa_profile(
        fafsa_efc_cents=2_000_000,
        css_efc_cents=3_500_000,
        family_income_cents=8_000_000,
        school_overrides={"requires_css_profile": True,
                          "name": "Stanford-DV-INST"},
    )
    inst_res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted2["id"], expected_application_version=admitted2["version"],
            cost_of_attendance_cents=8_000_000,
            variant="INSTITUTIONAL",
            grant_cents=0, loan_cents=0, work_study_cents=0),
        fa_officer_headers())
    institutional = validate_success(inst_res, 201)
    assert institutional["demonstrated_need_cents"] == 4_500_000
    assert institutional["demonstrated_need_cents"] < federal["demonstrated_need_cents"]


def test_admission_probability_provisional_vs_final_diverges(api):
    """PRD §3.5: "The PROVISIONAL variant counts letters whose status is
    REQUESTED, IN_PROGRESS, or SUBMITTED — the optimistic projection used
    while admissions has not yet begun reviewing"
    PRD §3.5: "The FINAL variant counts only letters whose status is
    SUBMITTED — the conservative projection used once admissions has
    begun review."

    Design: Difficulty/dual_variant_calc/admission_probability_provisional_vs_final_divergence
    """
    school = setup_clock_and_school(name="Yale-AP")
    # gpa=3.8 → gpa_component = min(40, round_half_up(38.0)) = 38
    # sat=1500 → sat_component = min(30, floor((1500-400)/40)) = min(30, 27) = 27
    applicant = register_applicant(full_name="AP One", gpa=3.8, sat_total=1500)
    rec_a = invite_and_accept_recommender(applicant["id"])
    rec_b = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])

    # Letter A → SUBMITTED; letter B stays REQUESTED.
    create_and_submit_letter(app["id"], applicant["id"], rec_a["id"])
    # Create letter B but do not start/submit.
    from test_helpers import create_requested_letter
    create_requested_letter(app["id"], applicant["id"], rec_b["id"])
    # PRD §3.4 requires "All RecommendationLetter rows for this application
    # must be in SUBMITTED status" for the DRAFT→SUBMITTED transition, so we
    # cannot submit the application while letter B is REQUESTED. The
    # PROVISIONAL vs FINAL divergence is observable on a DRAFT application
    # via the explicit `score_variant` query parameter (PRD §3.4: "the
    # application read endpoint accepts the optional score_variant query
    # parameter").

    headers = make_applicant_headers(applicant["id"])
    prov_res = api.get_application(app["id"], headers,
                                   params={"score_variant": "PROVISIONAL"})
    final_res = api.get_application(app["id"], headers,
                                    params={"score_variant": "FINAL"})
    prov = validate_success(prov_res, 200)
    fnl = validate_success(final_res, 200)

    # PROVISIONAL: counts 2 letters (1 SUBMITTED + 1 REQUESTED) → letters = min(15, 10) = 10
    # FINAL: counts 1 SUBMITTED → letters = min(15, 5) = 5
    # gpa=38, sat=27, plan_bonus=0
    assert prov["admission_probability_score"] == 38 + 27 + 0 + 10  # 75
    assert fnl["admission_probability_score"] == 38 + 27 + 0 + 5   # 70
    assert prov["admission_probability_score"] > fnl["admission_probability_score"]


# ============================================================================
# Difficulty Rule 2 — Combinatorial formulas
# ============================================================================

def test_admission_score_per_component_rounding_order_pinned(api):
    """PRD §3.5: "rounding is applied at the per-component step before
    summation, never at the end."
    PRD §3.5: "Because the per-component rounding rule pins the order, a
    GPA of 3.85 (whose pre-cap real value is 38.5) rounds to 39 at the
    GPA-component step and contributes 39 to the sum"

    Design: Difficulty/combinatorial_formula/admission_score_per_component_rounding_order_pinned
    """
    school = setup_clock_and_school(name="MIT-RD")
    # gpa=3.85 → 38.5 real; round_half_up to 39, then capped at 40 → 39.
    # sat=null → 0; plan=REGULAR → 0; zero letters → 0. Total = 39.
    applicant = register_applicant(full_name="Round Test", gpa=3.85,
                                   sat_total=None)
    invite_and_accept_recommender(applicant["id"])  # so a recommender row exists
    app = create_application(applicant["id"], school["id"], "REGULAR")

    res = api.get_application(app["id"],
                              make_applicant_headers(applicant["id"]),
                              params={"score_variant": "PROVISIONAL"})
    data = validate_success(res, 200)
    assert data["admission_probability_score"] == 39


def test_aid_offer_three_input_floor_clamps_net_price_at_zero(api):
    """PRD §3.6: "The net_price_cents is the maximum of zero and the value
    of cost_of_attendance_cents minus grant_cents minus loan_cents minus
    work_study_cents."

    Design: Difficulty/combinatorial_formula/aid_offer_three_input_conditional_branch_with_floor
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=1_500_000,
        family_income_cents=6_000_000,
        school_overrides={"name": "Harvard-Floor",
                          "requires_css_profile": False},
    )
    # COA = 7_000_000; grant 5_500_000 == demonstrated_need (boundary,
    # not over); loan 1M; work_study 1M; sum (7.5M) > COA → net floors at 0.
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=7_000_000,
            variant="FEDERAL",
            grant_cents=5_500_000,
            loan_cents=1_000_000,
            work_study_cents=1_000_000),
        fa_officer_headers())
    offer = validate_success(res, 201)
    assert offer["demonstrated_need_cents"] == 5_500_000
    assert offer["net_price_cents"] == 0
    assert offer["grant_cents"] == 5_500_000


# ============================================================================
# Corner Section 3 — Calculations
# ============================================================================

# ─── calc_demonstrated_need_institutional_when_school_does_not_require_css

def test_aid_offer_institutional_when_school_does_not_require_css_rejected(api):
    """PRD §3.6: "INSTITUTIONAL is permitted only when the target school's
    requires_css_profile is true AND the applicant's
    FinancialAidProfile.css_efc_cents is not null, and a violation of
    either condition is rejected with ERR_INSTITUTIONAL_VARIANT_INELIGIBLE."

    Design: Corner/calculations/calc_demonstrated_need_institutional_when_school_does_not_require_css_rejected
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=1_000_000,
        css_efc_cents=2_000_000,
        family_income_cents=5_000_000,
        school_overrides={"requires_css_profile": False, "name": "INE-1"},
    )
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=6_000_000,
            variant="INSTITUTIONAL",
            grant_cents=0, loan_cents=0, work_study_cents=0),
        fa_officer_headers())
    validate_error(res, "ERR_INSTITUTIONAL_VARIANT_INELIGIBLE")


# ─── calc_admission_score_letters_factor_capped_at_15 ───────────────────

def test_admission_score_letters_factor_saturates_at_15(api):
    """PRD §3.5: "The letters factor counts qualifying RecommendationLetter
    rows for this application, multiplies that count by five, and caps
    the result at a maximum of fifteen — that is, the letters factor
    saturates after the third qualifying letter, so additional letters
    beyond three contribute nothing."

    Design: Corner/calculations/calc_admission_score_letters_factor_capped_at_15
    """
    school = setup_clock_and_school(name="CAP-15")
    # gpa=3.0 → gpa_component = min(40, round(30.0)) = 30
    # sat=null → 0; plan_bonus REGULAR = 0; letters = min(15, 5*4) = 15
    # Total = 30 + 0 + 0 + 15 = 45.
    applicant = register_applicant(full_name="Cap15", gpa=3.0, sat_total=None)
    recs = [invite_and_accept_recommender(applicant["id"]) for _ in range(4)]
    app = create_application(applicant["id"], school["id"], "REGULAR")
    for rec in recs:
        create_and_submit_letter(app["id"], applicant["id"], rec["id"])

    res = api.get_application(app["id"],
                              make_applicant_headers(applicant["id"]),
                              params={"score_variant": "FINAL"})
    data = validate_success(res, 200)
    assert data["admission_probability_score"] == 45


# ─── calc_yield_rate_precision_4dp ──────────────────────────────────────

def test_school_yield_rate_4dp_precision(api):
    """PRD §3.7: "the rate is the enrolled count divided by the admitted
    count, rounded half up to four decimal places."
    PRD §3.7: "where admitted applications are those whose status is in
    the set ADMITTED, ENROLLED, or DECLINED_OFFER, and enrolled
    applications are those whose status is ENROLLED."

    Design: Corner/calculations/calc_yield_rate_precision_4dp
    """
    school = setup_clock_and_school(name="YR-1",
                                    target_class_size=10)

    def _drive_to_admitted_and_optionally_accept(accept: bool, email_seed: str):
        applicant = register_applicant(email=f"{email_seed}@example.com")
        rec = invite_and_accept_recommender(applicant["id"])
        app = create_application(applicant["id"], school["id"], "REGULAR")
        create_essay(app["id"], applicant["id"])
        create_and_submit_letter(app["id"], applicant["id"], rec["id"])
        submit_application(app["id"], applicant["id"])
        reviewed = start_review(app["id"])
        admitted = decide(app["id"], "ADMIT", reviewed["version"])
        if accept:
            get_success_data(api_client.accept_offer(
                admitted["id"], make_applicant_headers(applicant["id"])))

    # Three admitted, two enroll → 2/3 = 0.6666... → round_half_up to 0.6667.
    _drive_to_admitted_and_optionally_accept(True, "yr1")
    _drive_to_admitted_and_optionally_accept(True, "yr2")
    _drive_to_admitted_and_optionally_accept(False, "yr3")

    res = api.get_school_yield_report(school["id"], admissions_headers())
    report = validate_success(res, 200)
    assert report["yield_rate"] == pytest.approx(0.6667, abs=1e-9)


# ─── calc_school_yield_quota_waterfall_promotes_min_open_seats ──────────

def test_yield_quota_promotes_min_of_open_seats_and_waitlist(api):
    """PRD §3.7: "The number of promotions is the smaller of the two
    values: the open-seats count and the length of the eligible waitlist."

    Design: Corner/calculations/calc_school_yield_quota_waterfall_promotes_min_open_seats
    """
    school = setup_clock_and_school(name="WTQ-1", target_class_size=2)
    apps = []
    for i, clock_stamp in enumerate(("2030-10-01T00:01:00Z",
                                     "2030-10-01T00:02:00Z",
                                     "2030-10-01T00:03:00Z")):
        applicant = register_applicant(email=f"wq{i}@example.com")
        rec = invite_and_accept_recommender(applicant["id"])
        app = create_application(applicant["id"], school["id"], "REGULAR")
        create_essay(app["id"], applicant["id"])
        create_and_submit_letter(app["id"], applicant["id"], rec["id"])
        submit_application(app["id"], applicant["id"])
        reviewed = start_review(app["id"])
        # Advance the clock between each WAITLIST so waitlist_added_at
        # differs (deterministic ordering per PRD §3.7).
        from test_helpers import advance_clock_to
        advance_clock_to(clock_stamp)
        waitlisted = decide(app["id"], "WAITLIST", reviewed["version"])
        apps.append((applicant, waitlisted))

    res = api.run_yield(school["id"], admissions_headers())
    # Run-yield body shape is not pinned by PRD; we only need to inspect
    # the post-state of each application.
    assert res.status_code == 200

    def _status(app_id, owner_id):
        data = validate_success(api.get_application(
            app_id, make_applicant_headers(owner_id)), 200)
        return data["status"]

    # First two (by waitlist_added_at) → ADMITTED, third stays WAITLISTED.
    statuses = [_status(a["id"], applicant["id"])
                for applicant, a in apps]
    assert statuses[0] == "ADMITTED"
    assert statuses[1] == "ADMITTED"
    assert statuses[2] == "WAITLISTED"


# ─── calc_admission_score_threshold_sat_floor_at_zero_when_null ─────────

def test_admission_score_sat_is_zero_when_null(api):
    """PRD §3.5: "The SAT component is zero when the applicant's sat_total
    is null."

    Design: Corner/calculations/calc_admission_score_threshold_sat_floor_at_zero_when_null
    """
    school = setup_clock_and_school(name="TH-NULL")
    # gpa=2.0 → gpa_component = min(40, round_half_up(20.0)) = 20
    # sat=null → 0; plan_bonus REGULAR=0; letters=0 → score 20.
    applicant = register_applicant(full_name="ThN", gpa=2.0, sat_total=None)
    app = create_application(applicant["id"], school["id"], "REGULAR")
    res = api.get_application(app["id"],
                              make_applicant_headers(applicant["id"]),
                              params={"score_variant": "PROVISIONAL"})
    data = validate_success(res, 200)
    assert data["admission_probability_score"] == 20
