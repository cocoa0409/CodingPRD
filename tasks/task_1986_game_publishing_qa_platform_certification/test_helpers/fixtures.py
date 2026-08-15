"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CHECKLIST_PASS_SEQUENCE,
    PLATFORM_TERRITORY,
    TEST_DEFAULTS,
)
from .factories import (
    create_age_rating_payload,
    create_assignment_payload,
    create_blackout_window_payload,
    create_bug_payload,
    create_build_payload,
    create_finding_payload,
    create_hotfix_payload,
    create_localization_pack_payload,
    create_plan_entry_payload,
    create_release_window_payload,
    create_submission_package_payload,
    create_test_plan_payload,
    create_title_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_certification_lead_headers,
    make_platform_reviewer_headers,
)

RM = TEST_USERS["release_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]
VM = TEST_USERS["vendor_manager_headers"]
CL = TEST_USERS["certification_lead_headers"]
PR = TEST_USERS["platform_reviewer_headers"]
CM = TEST_USERS["compliance_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
READER = TEST_USERS["reader_headers"]


# ─── Clock / ops ──────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, PA))


def ops_run():
    """Run the ops-run checkpoint sweep (PRD §2.4)."""
    return get_success_data(api_client.ops_run(PA))


# ─── Tier 1: single-entity creation and state progression ─────────────

def create_title(**overrides):
    """Register a title; it starts CONCEPT with version 1 (PRD §3.1)."""
    return get_success_data(
        api_client.create_title(create_title_payload(**overrides), RM)
    )


def advance_title(title_id, to_status):
    return get_success_data(
        api_client.transition_title(title_id, {"to_status": to_status}, RM)
    )


def set_embargo(title_id, embargoed, reason):
    return get_success_data(
        api_client.set_embargo(
            title_id, {"embargoed": embargoed, "reason": reason}, CM
        )
    )


def get_title(title_id):
    return get_success_data(api_client.get_title(title_id, READER))


def create_vendor(**overrides):
    """Onboard a vendor; it starts ACTIVE (PRD §3.3)."""
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(**overrides), VM)
    )


def get_vendor(vendor_id):
    return get_success_data(api_client.get_vendor(vendor_id, READER))


def transition_vendor(vendor_id, to_status):
    return get_success_data(
        api_client.transition_vendor(vendor_id, {"to_status": to_status}, VM)
    )


def create_plan(title_id, platform_code="PS5"):
    """Create a test plan; it starts DRAFT (PRD §3.2)."""
    return get_success_data(
        api_client.create_test_plan(
            create_test_plan_payload(title_id, platform_code), QA
        )
    )


def add_plan_entry(plan_id, feature_area="COMBAT", required_coverage_hours=10,
                   is_cert_blocker=True, platform_layer="GAME"):
    return get_success_data(
        api_client.add_plan_entry(
            plan_id,
            create_plan_entry_payload(
                feature_area=feature_area,
                platform_layer=platform_layer,
                is_cert_blocker=is_cert_blocker,
                required_coverage_hours=required_coverage_hours,
            ),
            QA,
        )
    )


def transition_plan(plan_id, to_status):
    return get_success_data(
        api_client.transition_test_plan(plan_id, {"to_status": to_status}, QA)
    )


def get_plan(plan_id):
    return get_success_data(api_client.get_test_plan(plan_id, READER))


def create_assignment(vendor_id, plan_id, feature_area="COMBAT",
                      week_start_date=TEST_DEFAULTS["WEEK_START"],
                      reserved_hours=10):
    """Reserve vendor hours against a plan entry; starts SCHEDULED (PRD §3.3)."""
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(
                vendor_id, plan_id,
                feature_area=feature_area,
                week_start_date=week_start_date,
                reserved_hours=reserved_hours,
            ),
            VM,
        )
    )


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, READER))


def transition_assignment(assignment_id, to_status, actual_hours=None):
    payload = {"to_status": to_status}
    if actual_hours is not None:
        payload["actual_hours"] = actual_hours
    return get_success_data(
        api_client.transition_assignment(assignment_id, payload, VM)
    )


def complete_assignment(assignment_id, actual_hours):
    """Drive SCHEDULED -> IN_PROGRESS -> DONE recording actual_hours."""
    transition_assignment(assignment_id, "IN_PROGRESS")
    return transition_assignment(assignment_id, "DONE", actual_hours=actual_hours)


def create_build(title_id, platform_code="PS5", version_string=None, **overrides):
    """Register a build; it starts RECEIVED (PRD §3.4)."""
    return get_success_data(
        api_client.create_build(
            create_build_payload(title_id, platform_code, version_string, **overrides),
            QA,
        )
    )


def transition_build(build_id, to_status):
    return get_success_data(
        api_client.transition_build(build_id, {"to_status": to_status}, QA)
    )


def get_build(build_id):
    return get_success_data(api_client.get_build(build_id, READER))


def create_candidate_build(title_id, platform_code="PS5", version_string=None,
                           **overrides):
    """Create a build and drive it RECEIVED -> IN_TEST -> TEST_PASSED ->
    CANDIDATE (PRD §3.4). Returns the CANDIDATE build."""
    build = create_build(title_id, platform_code, version_string, **overrides)
    transition_build(build["id"], "IN_TEST")
    transition_build(build["id"], "TEST_PASSED")
    return transition_build(build["id"], "CANDIDATE")


def create_bug(title_id, build_id, severity="MAJOR", category="GAMEPLAY",
               **overrides):
    """File a bug; it starts OPEN (PRD §3.4)."""
    return get_success_data(
        api_client.create_bug(
            create_bug_payload(title_id, build_id, severity, category, **overrides),
            QA,
        )
    )


def get_bug(bug_id):
    return get_success_data(api_client.get_bug(bug_id, READER))


def triage_bug(bug_id, severity, category=None):
    payload = {"severity": severity}
    if category is not None:
        payload["category"] = category
    return get_success_data(api_client.triage_bug(bug_id, payload, QA))


def transition_bug(bug_id, to_status, **extra):
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(api_client.transition_bug(bug_id, payload, QA))


def close_bug_fully(bug_id, severity="MAJOR"):
    """Drive a fresh OPEN bug through triage to terminal CLOSED."""
    triage_bug(bug_id, severity)
    transition_bug(bug_id, "IN_PROGRESS")
    transition_bug(bug_id, "RESOLVED")
    transition_bug(bug_id, "VERIFIED")
    return transition_bug(bug_id, "CLOSED")


# ─── Age-rating filings (PRD §3.8) ────────────────────────────────────

def create_age_rating_filing(title_id, territory="ESRB", content_descriptors=None):
    return get_success_data(
        api_client.create_age_rating_filing(
            create_age_rating_payload(title_id, territory, content_descriptors), RM
        )
    )


def transition_filing(filing_id, to_status, headers=None, **extra):
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_age_rating_filing(filing_id, payload, headers or RM)
    )


def file_and_grant_age_rating(title_id, territory="ESRB"):
    """Create a filing and drive it DRAFT -> FILED -> GRANTED (PRD §3.8)."""
    filing = create_age_rating_filing(title_id, territory)
    transition_filing(filing["id"], "FILED")
    return transition_filing(filing["id"], "GRANTED", headers=PR)


# ─── Localization packs (PRD §3.8) ────────────────────────────────────

def create_localization_pack(title_id, locale, is_required=True,
                             text_asset_total=100, audio_asset_total=50):
    return get_success_data(
        api_client.create_localization_pack(
            create_localization_pack_payload(
                title_id, locale,
                is_required=is_required,
                text_asset_total=text_asset_total,
                audio_asset_total=audio_asset_total,
            ),
            RM,
        )
    )


def get_localization_pack(pack_id):
    return get_success_data(api_client.get_localization_pack(pack_id, READER))


def transition_pack_translation(pack_id, to_status, translated_text_assets=None,
                                translated_audio_assets=None):
    payload = {"axis": "TRANSLATION", "to_status": to_status}
    if translated_text_assets is not None:
        payload["translated_text_assets"] = translated_text_assets
    if translated_audio_assets is not None:
        payload["translated_audio_assets"] = translated_audio_assets
    return get_success_data(
        api_client.transition_localization_pack(pack_id, payload, RM)
    )


def sign_off_pack(pack_id):
    return get_success_data(
        api_client.transition_localization_pack(
            pack_id, {"axis": "SIGNOFF", "to_status": "SIGNED"}, QA
        )
    )


# ─── Tier 2: plan coverage ────────────────────────────────────────────

def create_approved_plan(title_id, vendor_id, platform_code="PS5",
                         entries=(("COMBAT", 10, True),)):
    """Create a plan with the given (feature_area, required_hours,
    is_cert_blocker) entries, cover every cert-blocker entry with an
    exactly-fitting assignment, and drive DRAFT -> IN_REVIEW -> APPROVED
    (PRD §3.2). Returns the APPROVED plan."""
    plan = create_plan(title_id, platform_code)
    for feature_area, hours, is_blocker in entries:
        add_plan_entry(plan["id"], feature_area=feature_area,
                       required_coverage_hours=hours, is_cert_blocker=is_blocker)
    for feature_area, hours, is_blocker in entries:
        if is_blocker:
            create_assignment(vendor_id, plan["id"], feature_area=feature_area,
                              reserved_hours=hours)
    transition_plan(plan["id"], "IN_REVIEW")
    return transition_plan(plan["id"], "APPROVED")


# ─── Tier 3: submission package lifecycle ─────────────────────────────

def create_submission_package(title_id, platform_code, build_id, plan_id,
                              expedited=False, headers=None):
    """Assemble a package, OCC-guarded on the title's current version
    (PRD §2.6, §3.5). Returns the created package data."""
    title = get_title(title_id)
    payload = create_submission_package_payload(
        platform_code, build_id, plan_id, title["version"], expedited=expedited
    )
    return get_success_data(
        api_client.create_submission_package(
            title_id, payload, headers or CL
        )
    )


def get_package(package_id):
    return get_success_data(api_client.get_submission_package(package_id, READER))


def get_checklist_id_for_package(package_id):
    """Find the package's auto-seeded checklist via the checklist list
    endpoint filtered by submission_package_id (PRD §3.5)."""
    data, _meta = validate_paginated(
        api_client.list_checklists(READER, params={"submission_package_id": package_id})
    )
    assert len(data) == 1, f"expected exactly one checklist for package {package_id}"
    return data[0]["id"]


def get_checklist(checklist_id):
    return get_success_data(api_client.get_checklist(checklist_id, READER))


def verify_item(checklist_id, requirement_code, result):
    return get_success_data(
        api_client.verify_checklist_item(
            checklist_id,
            {"requirement_code": requirement_code, "result": result},
            CM,
        )
    )


def verify_checklist_pass_sequence(checklist_id, platform_code="PS5"):
    """Drive every seeded catalog item to a terminal pass-equivalent state:
    REQUIRED items PASSED, RECOMMENDED items NA (PRD §3.6)."""
    for requirement_code, result in CHECKLIST_PASS_SEQUENCE[platform_code]:
        verify_item(checklist_id, requirement_code, result)
    return get_checklist(checklist_id)


def waive_item(checklist_id, requirement_code, justification, headers=None):
    """Request a waiver, OCC-guarded on the checklist's current version
    (PRD §2.6, §3.6)."""
    checklist = get_checklist(checklist_id)
    payload = {
        "requirement_code": requirement_code,
        "justification": justification,
        "expected_checklist_version": checklist["version"],
    }
    return get_success_data(
        api_client.waive_checklist_item(checklist_id, payload, headers or CL)
    )


def decide_waiver(checklist_id, requirement_code, decision, headers=None):
    return get_success_data(
        api_client.decide_waiver(
            checklist_id,
            {"requirement_code": requirement_code, "decision": decision},
            headers or CM,
        )
    )


def setup_submittable_package(title_code=None, cert_budget_total_cents=None,
                              platform_code="PS5", vendor_rate=5000,
                              vendor_capacity=40, entry_hours=10,
                              expedited=False, verify_checklist=True,
                              age_rating="granted"):
    """Full assembly chain (PRD §3.2–§3.6): title -> IN_DEVELOPMENT, ACTIVE
    vendor, APPROVED plan with one fully covered cert-blocker entry,
    CANDIDATE build, age-rating filing for the platform's mapped territory,
    package ASSEMBLING, checklist verification.

    age_rating: "granted" drives the filing DRAFT -> FILED -> GRANTED;
    "filed" stops at FILED; None skips the filing entirely.
    verify_checklist=False leaves every checklist item UNVERIFIED.

    Returns a dict with title, vendor, plan, build, package, checklist_id
    (and filing when one was created).
    """
    title = create_title(
        title_code=title_code or "T-SUB",
        platform_codes=[platform_code],
        cert_budget_total_cents=(
            cert_budget_total_cents
            if cert_budget_total_cents is not None
            else TEST_DEFAULTS["TITLE_BUDGET_CENTS"]
        ),
    )
    advance_title(title["id"], "IN_DEVELOPMENT")
    vendor = create_vendor(weekly_capacity_hours=vendor_capacity,
                           cost_rate_cents_per_hour=vendor_rate)
    plan = create_approved_plan(
        title["id"], vendor["id"], platform_code,
        entries=(("COMBAT", entry_hours, True),),
    )
    build = create_candidate_build(title["id"], platform_code)
    filing = None
    if age_rating is not None:
        filing = create_age_rating_filing(
            title["id"], PLATFORM_TERRITORY[platform_code]
        )
        transition_filing(filing["id"], "FILED")
        if age_rating == "granted":
            filing = transition_filing(filing["id"], "GRANTED", headers=PR)
    package = create_submission_package(
        title["id"], platform_code, build["id"], plan["id"], expedited=expedited
    )
    checklist_id = get_checklist_id_for_package(package["id"])
    if verify_checklist:
        verify_checklist_pass_sequence(checklist_id, platform_code)
    return {
        "title": get_title(title["id"]),
        "vendor": vendor,
        "plan": get_plan(plan["id"]),
        "build": get_build(build["id"]),
        "package": get_package(package["id"]),
        "checklist_id": checklist_id,
        "filing": filing,
    }


def submit_package(package_id, submitter_user_id="cl-1"):
    """Move ASSEMBLING -> SUBMITTED as a CertificationLead with the given
    X-User-ID (PRD §3.5). Returns the SUBMITTED package."""
    return get_success_data(
        api_client.transition_submission_package(
            package_id, {"to_status": "SUBMITTED"},
            make_certification_lead_headers(submitter_user_id),
        )
    )


def review_package(package_id, reviewer_user_id="pr-0"):
    """Move SUBMITTED -> IN_REVIEW as a PlatformReviewer (PRD §3.5)."""
    return get_success_data(
        api_client.transition_submission_package(
            package_id, {"to_status": "IN_REVIEW"},
            make_platform_reviewer_headers(reviewer_user_id),
        )
    )


def decide_package(package_id, to_status, reviewer_user_id="pr-1"):
    """Decide IN_REVIEW -> APPROVED / REJECTED as a PlatformReviewer whose
    user id differs from the submitter's (PRD §3.5)."""
    return get_success_data(
        api_client.transition_submission_package(
            package_id, {"to_status": to_status},
            make_platform_reviewer_headers(reviewer_user_id),
        )
    )


def setup_submitted_package(submitter_user_id="cl-1", **kwargs):
    """Submittable chain plus a successful submit. Returns the setup dict
    with the package refreshed in SUBMITTED."""
    ctx = setup_submittable_package(**kwargs)
    package = submit_package(ctx["package"]["id"], submitter_user_id)
    ctx["package"] = package
    ctx["title"] = get_title(ctx["title"]["id"])
    return ctx


def run_certification_chain(title_id, platform_code="PS5", entry_hours=10):
    """On an existing title (IN_DEVELOPMENT or CERTIFICATION): onboard a
    vendor, build an APPROVED plan, promote a build to CANDIDATE, file and
    grant the platform's mapped age rating, assemble a package with a fully
    verified checklist, then submit, review, and decide APPROVED with
    segregation of duties (PRD §3.2–§3.6). Returns the setup dict."""
    vendor = create_vendor()
    plan = create_approved_plan(
        title_id, vendor["id"], platform_code,
        entries=(("COMBAT", entry_hours, True),),
    )
    build = create_candidate_build(title_id, platform_code)
    filing = file_and_grant_age_rating(title_id, PLATFORM_TERRITORY[platform_code])
    package = create_submission_package(
        title_id, platform_code, build["id"], plan["id"]
    )
    checklist_id = get_checklist_id_for_package(package["id"])
    verify_checklist_pass_sequence(checklist_id, platform_code)
    package = submit_package(package["id"])
    review_package(package["id"])
    package = decide_package(package["id"], "APPROVED")
    return {
        "title": get_title(title_id),
        "vendor": vendor,
        "plan": get_plan(plan["id"]),
        "build": get_build(build["id"]),
        "package": package,
        "checklist_id": checklist_id,
        "filing": filing,
    }


def setup_approved_title(title_code="T-APR", cert_budget_total_cents=None,
                         platform_code="PS5", title_platform_codes=None):
    """Drive a title to CERT_APPROVED via a fully decided APPROVED package
    (PRD §3.1, §3.5). Returns the setup dict."""
    title = create_title(
        title_code=title_code,
        platform_codes=title_platform_codes or [platform_code],
        cert_budget_total_cents=(
            cert_budget_total_cents
            if cert_budget_total_cents is not None
            else TEST_DEFAULTS["TITLE_BUDGET_CENTS"]
        ),
    )
    advance_title(title["id"], "IN_DEVELOPMENT")
    advance_title(title["id"], "CERTIFICATION")
    ctx = run_certification_chain(title["id"], platform_code)
    advance_title(title["id"], "CERT_APPROVED")
    ctx["title"] = get_title(title["id"])
    return ctx


def setup_launched_title(title_code="T-LAU", cert_budget_total_cents=None,
                         platform_code="PS5"):
    """Drive a title all the way to LAUNCHED (PRD §3.1). Returns the setup
    dict from the CERT_APPROVED chain."""
    ctx = setup_approved_title(title_code, cert_budget_total_cents, platform_code)
    advance_title(ctx["title"]["id"], "LAUNCHED")
    ctx["title"] = get_title(ctx["title"]["id"])
    return ctx


# ─── Findings / remediation (PRD §3.7) ────────────────────────────────

def create_finding(package_id, severity="CATEGORY_A",
                   requirement_code="TRC-PS-02", description="cert finding"):
    return get_success_data(
        api_client.create_finding(
            package_id,
            create_finding_payload(
                severity=severity,
                requirement_code=requirement_code,
                description=description,
            ),
            PR,
        )
    )


def get_finding(finding_id):
    return get_success_data(api_client.get_finding(finding_id, READER))


def transition_finding(finding_id, to_status, headers=None, **extra):
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(
        api_client.transition_finding(finding_id, payload, headers or PR)
    )


def setup_rejected_package_with_finding(title_code="T-REJ",
                                        cert_budget_total_cents=2_000_000,
                                        finding_requirement="TRC-PS-02"):
    """Full chain to a REJECTED package carrying one OPEN CATEGORY_A finding
    (PRD §3.5, §3.7). Returns the setup dict with finding included."""
    ctx = setup_submittable_package(
        title_code=title_code, cert_budget_total_cents=cert_budget_total_cents
    )
    submit_package(ctx["package"]["id"])
    review_package(ctx["package"]["id"])
    finding = create_finding(ctx["package"]["id"],
                             requirement_code=finding_requirement)
    decide_package(ctx["package"]["id"], "REJECTED")
    ctx["package"] = get_package(ctx["package"]["id"])
    ctx["finding"] = finding
    ctx["title"] = get_title(ctx["title"]["id"])
    return ctx


# ─── Release windows / blackouts (PRD §3.9) ───────────────────────────

def create_release_window(title_id, platform_code="PS5", kind="LAUNCH",
                          start_utc="2026-08-10T09:00:00Z",
                          end_utc="2026-08-10T17:00:00Z"):
    """Reserve a release window; it starts RESERVED with fee null (PRD §3.9)."""
    return get_success_data(
        api_client.create_release_window(
            create_release_window_payload(
                title_id, platform_code, kind, start_utc, end_utc
            ),
            RM,
        )
    )


def transition_window(window_id, to_status):
    return get_success_data(
        api_client.transition_release_window(
            window_id, {"to_status": to_status}, RM
        )
    )


def confirm_release_window(title_id, platform_code="PS5", kind="LAUNCH",
                           start_utc="2026-08-10T09:00:00Z",
                           end_utc="2026-08-10T17:00:00Z"):
    """Reserve + CONFIRM a window; returns the CONFIRMED window (fee set)."""
    window = create_release_window(title_id, platform_code, kind,
                                   start_utc, end_utc)
    return transition_window(window["id"], "CONFIRMED")


def get_release_window(window_id):
    return get_success_data(api_client.get_release_window(window_id, READER))


def create_blackout_window(platform_code="PS5",
                           start_utc="2026-08-10T00:00:00Z",
                           end_utc="2026-08-12T00:00:00Z",
                           buffer_hours=24, reason="platform cert freeze"):
    return get_success_data(
        api_client.create_blackout_window(
            create_blackout_window_payload(
                platform_code, start_utc, end_utc, buffer_hours, reason
            ),
            PA,
        )
    )


# ─── Hotfixes (PRD §3.9) ──────────────────────────────────────────────

def create_hotfix(title_id, platform_code, build_id, severity="S1",
                  incident_summary="post-launch incident"):
    """Declare a hotfix on a LAUNCHED, non-embargoed title; starts DECLARED."""
    return get_success_data(
        api_client.create_hotfix(
            create_hotfix_payload(
                title_id, platform_code, build_id, severity, incident_summary
            ),
            RM,
        )
    )


def get_hotfix(hotfix_id):
    return get_success_data(api_client.get_hotfix(hotfix_id, READER))


def transition_hotfix(hotfix_id, to_status, headers=None):
    return get_success_data(
        api_client.transition_hotfix(
            hotfix_id, {"to_status": to_status}, headers or RM
        )
    )


def create_ready_hotfix(title_id, platform_code, build_id, severity="S1",
                        incident_summary="post-launch incident"):
    """Drive a hotfix DECLARED -> IN_DEV -> READY_FOR_CERT (PRD §3.9)."""
    hotfix = create_hotfix(title_id, platform_code, build_id, severity,
                           incident_summary)
    transition_hotfix(hotfix["id"], "IN_DEV")
    return transition_hotfix(hotfix["id"], "READY_FOR_CERT")


def expedite_hotfix(hotfix_id):
    """READY_FOR_CERT -> EXPEDITED_CERT as a PlatformReviewer (PRD §3.9)."""
    return transition_hotfix(hotfix_id, "EXPEDITED_CERT", headers=PR)
