"""Endpoint-shape tests + cross-cutting layer tests.

Covers Corner-design Section 5 (endpoints), Section 6 (errors triggerable
where not absorbed by other instances), and Section 8 (cross-cutting
layers — ops checkpoint, pagination with filter).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_clock_and_school, register_applicant, create_application,
    create_essay, invite_and_accept_recommender, create_and_submit_letter,
    setup_under_review_application, setup_admitted_with_fa_profile,
    setup_waitlisted_application,
    submit_application, start_review, decide, advance_clock_to,
    create_aid_offer_payload, decide_payload,
    make_applicant_headers, admissions_headers, fa_officer_headers,
    admin_headers, assert_version_incremented,
    api_client,
)


# ============================================================================
# Corner Section 5 — Endpoints
# ============================================================================

# ─── endpoint_patch_applicants_updates_then_flips_to_ready ──────────────

def test_patch_applicant_full_name_flips_profile_to_ready(api):
    """PRD §3.1: "The profile flips from DRAFT to READY once two conditions
    hold together: the applicant's full_name and gpa are both present, and
    at least one Recommender row exists for this applicant. The flip
    happens automatically — either when the applicant updates their own
    profile (mutating one of full_name, gpa, or sat_total through the
    owner-only profile-update capability) and the new state satisfies
    both conditions"

    Design: Corner/endpoints/endpoint_patch_applicants_updates_then_flips_to_ready
    """
    # Applicant registered with full_name and gpa present; recommender
    # already invited so profile_status is already READY at this point.
    # The PATCH still must succeed and the response must still report
    # profile_status=READY (the field-completeness half plus the
    # recommender-row half both hold).
    applicant = register_applicant(full_name="X", gpa=3.0,
                                   email="pa@example.com")
    invite_and_accept_recommender(applicant["id"])

    old_version = applicant["version"]
    res = api.patch_applicant(applicant["id"],
                              {"full_name": "X Updated"},
                              make_applicant_headers(applicant["id"]))
    updated = validate_success(res, 200)
    assert updated["full_name"] == "X Updated"
    assert_version_incremented(updated["version"], old_version)
    assert updated["profile_status"] == "READY"


# ─── endpoint_post_clock_advance_drives_time ────────────────────────────

def test_clock_advance_returns_200(api):
    """PRD §2.10: "the administrator-only clock-advance capability takes
    a to_iso8601 value in the request body and mutates the global clock
    that every subsequent timestamp comparison reads from."

    Design: Corner/endpoints/endpoint_post_clock_advance_drives_time
    """
    res = api.advance_clock("2031-06-15T12:34:56Z", admin_headers())
    assert res.status_code == 200


# ─── endpoint_get_yield_report_computed_read ────────────────────────────

def test_get_yield_report_returns_rate_and_enrollment_count(api):
    """PRD §3.7: "The rate is the ratio of enrolled applications to admitted
    applications at this school, where admitted applications are those
    whose status is in the set ADMITTED, ENROLLED, or DECLINED_OFFER, and
    enrolled applications are those whose status is ENROLLED."

    Design: Corner/endpoints/endpoint_get_yield_report_computed_read
    """
    school = setup_clock_and_school(name="YR-2", target_class_size=10)
    # Two admitted, one accepts (ENROLLED), one stays ADMITTED.
    a1 = register_applicant(email="yr2a@example.com")
    rec1 = invite_and_accept_recommender(a1["id"])
    app1 = create_application(a1["id"], school["id"], "REGULAR")
    create_essay(app1["id"], a1["id"])
    create_and_submit_letter(app1["id"], a1["id"], rec1["id"])
    submit_application(app1["id"], a1["id"])
    reviewed1 = start_review(app1["id"])
    admitted1 = decide(app1["id"], "ADMIT", reviewed1["version"])
    get_success_data(api.accept_offer(
        admitted1["id"], make_applicant_headers(a1["id"])))

    a2 = register_applicant(email="yr2b@example.com")
    rec2 = invite_and_accept_recommender(a2["id"])
    app2 = create_application(a2["id"], school["id"], "REGULAR")
    create_essay(app2["id"], a2["id"])
    create_and_submit_letter(app2["id"], a2["id"], rec2["id"])
    submit_application(app2["id"], a2["id"])
    reviewed2 = start_review(app2["id"])
    decide(app2["id"], "ADMIT", reviewed2["version"])

    res = api.get_school_yield_report(school["id"], admissions_headers())
    report = validate_success(res, 200)
    # 1 enrolled / 2 admitted = 0.5 → rounded half up to 4dp = 0.5
    assert report["yield_rate"] == pytest.approx(0.5, abs=1e-9)
    assert report["confirmed_enrollment_count"] == 1


# ─── endpoint_patch_aid_offer_recomputes_net_price ──────────────────────

def test_patch_aid_offer_recomputes_net_price(api):
    """PRD §3.6: "On every create and on every update of the offer through
    the officer-only offer-update capability (which adjusts grant_cents,
    loan_cents, and work_study_cents), the server computes two derived
    fields. ... The net_price_cents is the maximum of zero and the value
    of cost_of_attendance_cents minus grant_cents minus loan_cents minus
    work_study_cents."

    Design: Corner/endpoints/endpoint_patch_aid_offer_recomputes_net_price
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=1_000_000,
        family_income_cents=5_000_000,
        school_overrides={"name": "PA-AO"},
    )
    # Create AidOffer: COA=8M, grant=2M, loan=1M, work_study=0 → net=5M.
    create_res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=8_000_000,
            variant="FEDERAL",
            grant_cents=2_000_000, loan_cents=1_000_000, work_study_cents=0),
        fa_officer_headers())
    offer = validate_success(create_res, 201)
    assert offer["net_price_cents"] == 5_000_000

    # Adjust grant up to 4M → net = 8M - 4M - 1M - 0 = 3M.
    patch_res = api.patch_aid_offer(
        offer["id"], {"grant_cents": 4_000_000}, fa_officer_headers())
    patched = validate_success(patch_res, 200)
    assert patched["net_price_cents"] == 3_000_000


# ============================================================================
# Corner Section 6 — Errors (only non-stub entries)
# ============================================================================

# ─── error_ERR_FORBIDDEN_ROLE_triggerable ───────────────────────────────

def test_applicant_calling_decide_returns_forbidden_role(api):
    """PRD §2.1: "When the role is recognized but is not permitted to
    invoke the requested endpoint per the per-endpoint authorization
    table in §4, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP
    403)."
    PRD §4: the per-endpoint table lists "POST /applications/{id}/decide
    | Admissions renders a decision (ADMIT, WAITLIST, DENY, or DEFER) |
    AdmissionsOfficer".

    Design: Corner/errors/error_ERR_FORBIDDEN_ROLE_triggerable
    """
    school = setup_clock_and_school(name="FR-1")
    applicant = register_applicant(email="fr@example.com")
    app = create_application(applicant["id"], school["id"], "REGULAR")
    res = api.decide_application(
        app["id"],
        {"decision": "ADMIT", "expected_application_version": 1},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── error_ERR_DEADLINE_PASSED_triggerable ──────────────────────────────

def test_regular_submit_past_rd_deadline_returns_deadline_passed(api):
    """PRD §3.4: "for a Regular-Decision submission the server clock must
    be at or before rd_deadline_iso ... A submission that violates any
    deadline window is rejected with ERR_DEADLINE_PASSED."

    Design: Corner/errors/error_ERR_DEADLINE_PASSED_triggerable
    """
    school = setup_clock_and_school(
        clock_iso="2030-09-15T00:00:00Z",
        name="DLN-R",
        ed_deadline_iso="2030-10-01T00:00:00Z",
        ea_deadline_iso="2030-10-15T00:00:00Z",
        rd_deadline_iso="2030-11-01T00:00:00Z",
    )
    applicant = register_applicant(email="dln@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    advance_clock_to("2030-12-01T00:00:00Z")

    res = api.submit_application(
        app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED")


# ============================================================================
# Corner Section 8 — Cross-cutting layers
# ============================================================================

# ─── layer_ops_run_checkpoint_yield_run_advances_count_and_timestamp ────

def test_yield_run_increments_count_and_sets_last_yield_run_at(api):
    """PRD §3.7: "The run also recomputes waitlist_rank for any
    applications that remain on the waitlist after the promotions,
    increments the AdmissionCycle's yield_run_count by one, and sets
    last_yield_run_at to the server clock."

    Design: Corner/cross_cutting_layers/layer_ops_run_checkpoint_yield_run_advances_count_and_timestamp
    """
    applicant, school, _waitlisted = setup_waitlisted_application(
        school_overrides={"name": "OPS-1", "target_class_size": 5})

    get_success_data(api.run_yield(school["id"], admissions_headers()))
    cycle = validate_success(api.get_admission_cycle(
        school["id"], admissions_headers()), 200)
    assert cycle["yield_run_count"] == 1
    assert cycle["last_yield_run_at"] is not None


# ─── layer_pagination_with_filtering_applications_status ────────────────

def test_list_applications_filter_by_status_and_paginate(api):
    """PRD §3.8: "admissions officers may additionally filter the
    application list by school_id, by status, or by plan (any combination
    is permitted) and may page the result through limit and offset."
    PRD §2.3: "The meta object on a list response carries limit, offset,
    total_count, and has_more"

    Design: Corner/cross_cutting_layers/layer_pagination_with_filtering_applications_status
    """
    setup_clock_and_school()  # advance clock first
    from test_helpers import create_school
    s1 = create_school(name="PG-1")
    s2 = create_school(name="PG-2")
    s3 = create_school(name="PG-3")
    applicant = register_applicant(email="pg@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    ap1 = create_application(applicant["id"], s1["id"], "REGULAR")
    ap2 = create_application(applicant["id"], s2["id"], "REGULAR")
    ap3 = create_application(applicant["id"], s3["id"], "REGULAR")

    # Drive ap3 to SUBMITTED; ap1, ap2 stay DRAFT.
    create_essay(ap3["id"], applicant["id"])
    create_and_submit_letter(ap3["id"], applicant["id"], rec["id"])
    submit_application(ap3["id"], applicant["id"])

    res = api.list_applications(
        make_applicant_headers(applicant["id"]),
        params={"status": "DRAFT", "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
    assert data[0]["status"] == "DRAFT"


# ============================================================================
# Corner Section 9 — Consistency Model
# ============================================================================

# ─── consistency_immediate_school_posture_reflects_accept_in_same_response

def test_accept_offer_school_posture_visible_immediately(api):
    """PRD §2.7: "Every cascade described below is part of the same
    logical transaction as the operation that triggered it: every
    affected row has its updated_at refreshed and its version incremented
    in the same call."
    PRD §2.7: "When an applicant accepts an offer on an admitted
    application, the owning school's confirmed_enrollment_count is
    incremented by one and the school's posture is recomputed in the
    same transaction (a first-order cascade)."

    Design: Corner/consistency_model/consistency_immediate_school_posture_reflects_accept_in_same_response
    """
    from test_helpers import setup_admitted_application
    applicant, school, admitted = setup_admitted_application(
        plan="REGULAR",
        school_overrides={"name": "IM-1", "target_class_size": 1})
    get_success_data(api.accept_offer(
        admitted["id"], make_applicant_headers(applicant["id"])))

    refetched = validate_success(api.get_school(
        school["id"], admin_headers()), 200)
    assert refetched["confirmed_enrollment_count"] == 1
    assert refetched["posture"] == "AT_TARGET"
