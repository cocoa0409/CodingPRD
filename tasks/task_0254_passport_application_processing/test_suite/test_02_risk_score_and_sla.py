"""Dual-variant computed reads: the verification risk score (provisional vs final)
and the SLA processing target (forward-looking vs chronological), plus the summary
progress counts.

Difficulty queue: dual_variant_calc. Corner queue: calculations (summary required-docs
progress).
"""
from test_helpers import (
    api_client,
    make_agent_headers,
    make_applicant_headers,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/dual_variant_calc/risk_score_provisional_vs_final_diverge_on_same_applicant
# ════════════════════════════════════════════════════════════════════════
def test_provisional_risk_score_is_75_at_submission(api):
    """PRD §3.6: "documents still PENDING contribute a factor quality of 0 (the
    worst case), so an applicant whose documents are all still pending but who has
    a passing photo scores exactly 75.00 (the photo factor alone contributes 25 of
    quality, leaving a risk of 75)."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_diverge_on_same_applicant
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    applicant = validate_success(
        api.get_applicant(ctx["applicant"]["id"], make_applicant_headers(ctx["applicant"]["id"])), 200)
    assert applicant["verification_risk_score"] == 75.00


def test_final_risk_score_drops_to_zero_after_both_docs_accepted(api):
    """PRD §3.6: "only ACCEPTED documents contribute their declared_quality, so once
    identity and citizenship documents are accepted at high quality the risk drops
    toward 0.00." PRD §3.6: "The combined quality is 0.40 times the identity factor
    quality plus 0.35 times the citizenship factor quality plus 0.25 times the photo
    quality. The risk is then 100 minus that combined quality".

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_diverge_on_same_applicant
    """
    ctx = fx.in_verification_application(application_type="NEW", product_type="BOOK",
                                         doc_specs=[("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": 100}),
                                                    ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": 100})])
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]
    fx.accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent_id)
    fx.accept_document(ctx["docs"]["CITIZENSHIP"][0]["id"], agent_id)

    applicant = validate_success(
        api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["verification_risk_score"] == 0.00


# ════════════════════════════════════════════════════════════════════════
# Difficulty/dual_variant_calc/sla_forward_looking_vs_chronological_diverge_by_verification_delay
# ════════════════════════════════════════════════════════════════════════
def _drive_to_verified_with_delay():
    """Adult NEW BOOK ROUTINE: submitted at 2026-06-01, both docs accepted at
    2026-06-08, so verification_completed_at is 7 days after submission."""
    fx.set_clock("2026-06-01T10:00:00Z")
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    # begin verification while clock is still 2026-06-01
    validate_success(api_client.begin_verification(app_id, make_agent_headers(agent["id"])), 200)
    # advance clock to 2026-06-08 before accepting documents
    fx.set_clock("2026-06-08T10:00:00Z")
    fx.accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent["id"])
    fx.accept_document(ctx["docs"]["CITIZENSHIP"][0]["id"], agent["id"])
    return ctx


def test_forward_looking_sla_target_is_42_days_from_submission(api):
    """PRD §3.8: "a routine application is given 42 calendar days and an expedite
    application 21 calendar days, the chosen number depending on service_level. The
    forward-looking variant adds that span to the date portion of submitted_at".

    Design: Difficulty/dual_variant_calc/sla_forward_looking_vs_chronological_diverge_by_verification_delay
    """
    ctx = _drive_to_verified_with_delay()
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    summary = validate_success(
        api.get_application_summary(app_id, make_applicant_headers(appl_id)), 200)
    assert summary["forward_looking_target_date"] == "2026-07-13"
    app = validate_success(api.get_application(app_id, make_applicant_headers(appl_id)), 200)
    assert app["target_completion_date"] == "2026-07-13"


def test_chronological_sla_target_is_42_days_from_verification_completed(api):
    """PRD §3.8: "A separate chronological variant of the same target uses the date
    portion of verification_completed_at as its effective start instead, adding the
    same 42-or-21 day span". PRD §3.8: "a seven-day delay between submission and
    verification completion makes the chronological target fall exactly seven
    calendar days after the forward-looking one."

    Design: Difficulty/dual_variant_calc/sla_forward_looking_vs_chronological_diverge_by_verification_delay
    """
    ctx = _drive_to_verified_with_delay()
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    summary = validate_success(
        api.get_application_summary(app_id, make_applicant_headers(appl_id)), 200)
    assert summary["forward_looking_target_date"] == "2026-07-13"
    assert summary["chronological_target_date"] == "2026-07-20"


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/summary_required_docs_progress_counts
# ════════════════════════════════════════════════════════════════════════
def test_summary_reports_required_docs_progress(api):
    """PRD §3.8: the summary "returns forward_looking_target_date,
    chronological_target_date, the current total_due_cents, the count of required
    documents required_docs_total, and the count of those accepted
    required_docs_accepted."

    Design: Corner/calculations/summary_required_docs_progress_counts
    """
    ctx = fx.in_verification_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]
    # Accept only IDENTITY; leave CITIZENSHIP PENDING.
    fx.accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent_id)

    summary = validate_success(
        api.get_application_summary(ctx["application"]["id"], make_applicant_headers(appl_id)), 200)
    assert summary["required_docs_total"] == 2
    assert summary["required_docs_accepted"] == 1
