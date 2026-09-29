"""Serializers for every entity plus the two named cascades of PRD 2.7."""
import db
import services.calc as calc

COMMON = ("id", "created_at", "updated_at", "version")


def _pick(row, names):
    return dict((name, row.get(name)) for name in names)


# --- SchoolPartner ----------------------------------------------------------
def school_view(school):
    health, open_count = calc.school_health(school)
    out = _pick(school, ("id", "name", "district_name", "grade_span",
                         "concurrent_session_capacity", "total_enrollment",
                         "frl_pct", "ell_pct", "iep_pct",
                         "created_at", "updated_at", "version"))
    out["partnership_health"] = health
    out["open_residency_count"] = open_count
    return out


def blackout_view(row):
    return _pick(row, ("id", "school_partner_id", "blackout_type", "start_date",
                       "end_date", "note", "created_at"))


# --- TeachingArtist ---------------------------------------------------------
def artist_view(artist):
    status, expires_on = calc.artist_clearance_window(artist)
    count, mean = calc.portfolio_rollup(artist["id"])
    out = _pick(artist, ("id", "full_name", "email", "primary_discipline",
                         "secondary_disciplines", "grade_bands", "languages",
                         "roster_tier_assigned", "roster_tier_effective",
                         "vetting_status", "roster_status", "demo_attempt_count",
                         "demo_rubric_score", "demo_evaluator_user_id",
                         "reliability_bps_rolling", "reliability_bps_program_year",
                         "created_at", "updated_at", "version"))
    out["portfolio_review_count"] = count
    out["portfolio_mean_composite"] = float(mean) if mean is not None else None
    out["clearance_status"] = status
    out["clearance_expires_on"] = expires_on
    out["lifetime_delivered_count"] = calc.lifetime_delivered_count(artist["id"])
    out["no_show_count"] = calc.no_show_count(artist["id"])
    return out


def portfolio_review_view(review):
    composite = calc.portfolio_composite(review)
    out = _pick(review, ("id", "teaching_artist_id", "reviewer_user_id",
                         "artistic_quality_score", "pedagogical_clarity_score",
                         "cultural_responsiveness_score", "created_at"))
    out["composite_score"] = float(composite)
    out["recommendation"] = calc.portfolio_recommendation(composite)
    return out


def screening_view(screening):
    out = _pick(screening, ("id", "teaching_artist_id", "screening_type", "outcome",
                            "effective_on", "expires_on", "adjudication_note",
                            "created_at"))
    out["superseded"] = calc.screening_superseded(screening)
    return out


# --- ArtsStandard -----------------------------------------------------------
def standard_view(standard):
    return _pick(standard, ("id", "code", "discipline", "grade_band", "strand",
                            "description", "created_at", "updated_at", "version"))


# --- Residency --------------------------------------------------------------
def residency_view(residency):
    out = _pick(residency, ("id", "school_partner_id", "lead_artist_id", "title",
                            "discipline", "grade_band", "instruction_language",
                            "contracted_session_count", "session_length_minutes",
                            "budget_cents", "materials_stipend_cents",
                            "collaboration_expectation", "co_planning_hours_required",
                            "required_strands", "term_start_date", "term_end_date",
                            "enrolled_student_count", "status",
                            "created_at", "updated_at", "version"))
    out["staffing_status"] = calc.staffing_status(residency)
    out.update(calc.session_ledger(residency))
    out.update(calc.budget_ledger(residency))
    out["earned_to_date_cents"] = calc.earned_to_date_cents(residency)
    out["projected_cost_cents"] = calc.projected_cost_cents(residency)
    index = calc.evaluation_index(residency)
    out["evaluation_index"] = float(index) if index is not None else None
    return out


# --- LessonPlan -------------------------------------------------------------
def lesson_plan_view(plan):
    return _pick(plan, ("id", "residency_id", "author_artist_id", "title",
                        "session_sequence_no", "standard_codes", "materials_list",
                        "adaptation_summary", "status", "revision_round",
                        "covered_strands", "reviewer_note", "reviewer_user_id",
                        "aligned_on", "created_at", "updated_at", "version"))


# --- Session ----------------------------------------------------------------
def session_view(session):
    return _pick(session, ("id", "residency_id", "assigned_artist_id",
                           "vacated_artist_id", "lesson_plan_id",
                           "makeup_for_session_id", "payment_voucher_id",
                           "session_type", "is_substitute", "session_date",
                           "start_time", "end_time", "classroom_teacher_name",
                           "co_planning_completed", "status", "cancel_reason",
                           "makeup_eligible", "makeup_consumed",
                           "students_present_count", "minutes_delivered",
                           "travel_miles", "materials_spend_cents",
                           "encumbered_cents", "fee_cents",
                           "travel_reimbursement_cents",
                           "materials_reimbursement_cents", "payable_cents",
                           "created_at", "updated_at", "version"))


def evaluation_view(record):
    out = _pick(record, ("id", "session_id", "evaluation_type", "evaluator_user_id",
                         "rubric_engagement_score", "rubric_craft_score",
                         "rubric_standards_evidence_score", "teacher_survey_score",
                         "student_work_artifact_count", "created_at"))
    composite = calc.rubric_composite(record)
    out["rubric_composite"] = float(composite) if composite is not None else None
    return out


# --- PaymentVoucher ---------------------------------------------------------
def voucher_view(voucher):
    out = _pick(voucher, ("id", "teaching_artist_id", "residency_id", "session_ids",
                          "period_start", "period_end", "status",
                          "fiscal_review_status", "program_review_status",
                          "fiscal_reviewed_by", "program_reviewed_by", "void_reason",
                          "created_at", "updated_at", "version"))
    out.update(calc.voucher_total(voucher))
    return out


# --- FunderReport -----------------------------------------------------------
def report_view(report):
    return _pick(report, ("id", "funder_name", "grant_code", "period_start",
                          "period_end", "scope_residency_ids", "headcount_basis",
                          "status", "compiled_by_user_id", "certified_by_user_id",
                          "attestation_text", "invalidated_reason",
                          "sessions_delivered_total", "students_served",
                          "frl_students_reached", "ell_students_reached",
                          "iep_students_reached", "direct_cost_cents",
                          "indirect_cost_cents", "total_spend_cents",
                          "cost_per_student_cents",
                          "created_at", "updated_at", "version"))


# =============================================================================
# Cascade A — artist suspension
# =============================================================================
def cascade_a(artist):
    """Links 2-4: vacate sessions, re-staff residencies, recompute school health.

    Residency staffing/ledger figures and school health are computed on read, so
    the cascade only has to move the rows and stamp the versions of the rows
    whose own stored fields changed: every vacated session, and a residency
    either releasing an encumbrance or losing its lead artist reference.
    """
    touched = []
    money_moved = []
    for session in db.ordered(list(db.sessions.values())):
        if session["assigned_artist_id"] != artist["id"]:
            continue
        if session["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        released = session["status"] == "CONFIRMED"
        session["vacated_artist_id"] = artist["id"]
        session["assigned_artist_id"] = None
        session["status"] = "VACATED"
        session["encumbered_cents"] = 0
        db.touch(session)
        if session["residency_id"] not in touched:
            touched.append(session["residency_id"])
        if released and session["residency_id"] not in money_moved:
            money_moved.append(session["residency_id"])
    for residency_id in touched:
        residency = db.residencies.get(residency_id)
        if residency is None:
            continue
        lost_lead = residency.get("lead_artist_id") == artist["id"]
        if lost_lead:
            residency["lead_artist_id"] = None
        if lost_lead or residency_id in money_moved:
            db.touch(residency)
    return touched


def suspend_artist(artist):
    """Cascade A in full, starting from link 1."""
    artist["roster_status"] = "SUSPENDED"
    calc.recompute_tier(artist)
    db.touch(artist)
    cascade_a(artist)


# =============================================================================
# Cascade B — artist-side cancellation
# =============================================================================
def _artist_snapshot(artist):
    return (artist["roster_status"], artist["roster_tier_effective"],
            artist["reliability_bps_rolling"], artist["reliability_bps_program_year"])


def enter_probation(artist):
    """Link 4: cap the tier and re-project every residency holding open work."""
    artist["roster_status"] = "PROBATION"
    calc.recompute_tier(artist)
    db.touch(artist)
    reproject_open_residencies(artist)


def reproject_open_residencies(artist):
    """Link 4's re-projection.

    ``projected_cost_cents`` is computed on every read of a residency from the
    artist's current effective tier, so capping that tier has already re-projected
    every residency holding open work; no residency row is written, and therefore
    none is version-stamped.
    """
    return


def cascade_b(session, artist):
    """Links 2-4 after a session has terminated as CANCELLED_ARTIST."""
    if artist is None:
        return
    # no_show_count and both reliability figures are recomputed from the session
    # rows themselves; only rows whose stored values actually move are stamped.
    before = _artist_snapshot(artist)
    calc.recompute_reliability(artist)
    calc.recompute_tier(artist)
    if _artist_snapshot(artist) != before:
        db.touch(artist)
    if (artist["roster_status"] == "ACTIVE"
            and artist["reliability_bps_rolling"] < calc.RELIABILITY_PROBATION_FLOOR_BPS
            and len(calc.terminal_sessions(artist["id"])) >= calc.RELIABILITY_MIN_TERMINAL):
        enter_probation(artist)


# =============================================================================
# Funder-report staleness (PRD 3.9)
# =============================================================================
def invalidate_reports(residency_id, session_date):
    for report in db.funder_reports.values():
        if report["status"] != "COMPILED":
            continue
        if residency_id not in report["scope_residency_ids"]:
            continue
        if not (report["period_start"] <= session_date <= report["period_end"]):
            continue
        report["status"] = "DRAFT"
        report["invalidated_reason"] = "SCOPE_DELIVERY_CHANGED"
        db.touch(report)
