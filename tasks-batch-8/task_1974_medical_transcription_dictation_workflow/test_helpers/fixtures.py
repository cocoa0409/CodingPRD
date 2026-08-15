"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the runner restarts the server before each test, so nothing is
carried over. Setup calls use the lenient get_success_data() validator so a
setup failure surfaces as a clear "Setup step failed" error.

Identity threading: Provider/Editor are entity-backed roles (PRD §2.1), so any
ownership-gated call is made with make_provider_headers(provider["id"]) /
make_editor_headers(editor["id"]) — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    T0,
    WIDE_WINDOW_START,
    WIDE_WINDOW_END,
    TEST_DEFAULTS,
    TEXT_65_CHARS,
    TEXT_131_CHARS,
)
from .factories import (
    create_clinic_account_payload,
    create_sla_policy_payload,
    create_provider_payload,
    create_editor_payload,
    create_shift_window_payload,
    create_dictation_job_payload,
    create_submit_payload,
    create_qa_review_payload,
    create_billing_period_payload,
)
from .test_users import TEST_USERS, make_provider_headers, make_editor_headers

VENDOR = TEST_USERS["vendor_admin_headers"]
CLIENT = TEST_USERS["client_admin_headers"]
QA = TEST_USERS["qa_supervisor_headers"]
QA_REVIEWER = TEST_DEFAULTS["QA_REVIEWER_USER_ID"]


# ---------------------------------------------------------------------------
# Primitive single-call helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, VENDOR))


def setup_clinic(**overrides) -> dict:
    """Create a clinic account; PRD §3.1 defaults apply unless overridden."""
    return get_success_data(api_client.create_clinic_account(
        create_clinic_account_payload(**overrides), VENDOR))


def add_sla_policy(clinic_id, priority="ROUTINE", tat_minutes=1440,
                   rate_per_line_cents=10, breach_credit_pct=5,
                   measurement_basis="END_TO_END") -> dict:
    return get_success_data(api_client.create_sla_policy(
        create_sla_policy_payload(
            clinic_id, priority=priority, tat_minutes=tat_minutes,
            rate_per_line_cents=rate_per_line_cents,
            breach_credit_pct=breach_credit_pct,
            measurement_basis=measurement_basis),
        VENDOR))


def setup_provider(clinic_id, **overrides) -> dict:
    return get_success_data(api_client.create_provider(
        create_provider_payload(clinic_id, **overrides), CLIENT))


def setup_editor(display_name="Editor E", wide_window=True) -> dict:
    editor = get_success_data(api_client.create_editor(
        create_editor_payload(display_name=display_name), VENDOR))
    if wide_window:
        get_success_data(api_client.create_editor_shift_window(
            create_shift_window_payload(editor["id"]),
            make_editor_headers(editor["id"])))
    return editor


def setup_workgroup(priorities=("ROUTINE",), sla_overrides=None) -> dict:
    """Clinic + one SLA policy per priority + one provider + one editor with a
    wide shift window. Returns {"clinic", "provider", "editor"}."""
    clinic = setup_clinic()
    sla_overrides = sla_overrides or {}
    for prio in priorities:
        add_sla_policy(clinic["id"], priority=prio, **sla_overrides.get(prio, {}))
    provider = setup_provider(clinic["id"])
    editor = setup_editor()
    return {"clinic": clinic, "provider": provider, "editor": editor}


# ---------------------------------------------------------------------------
# Job lifecycle helpers
# ---------------------------------------------------------------------------

def create_job(provider, work_type="CONSULT", priority="ROUTINE",
               audio_duration_seconds=60, template_id=None) -> dict:
    payload = create_dictation_job_payload(
        provider["id"], work_type=work_type, priority=priority,
        audio_duration_seconds=audio_duration_seconds)
    if template_id is not None:
        payload["template_id"] = template_id
    return get_success_data(api_client.create_dictation_job(
        payload, make_provider_headers(provider["id"])))


def claim_job(job_id, editor) -> dict:
    return get_success_data(api_client.claim_job(
        job_id, {"editor_id": editor["id"]}, make_editor_headers(editor["id"])))


def submit_job(job_id, editor, final_text=TEXT_65_CHARS) -> dict:
    return get_success_data(api_client.submit_job(
        job_id, create_submit_payload(final_text=final_text),
        make_editor_headers(editor["id"])))


def review_job(job_id, critical=0, major=0, minor=0, reviewer=QA_REVIEWER) -> dict:
    from .test_users import make_qa_supervisor_headers
    return get_success_data(api_client.create_qa_review(
        create_qa_review_payload(
            job_id, critical_error_count=critical,
            major_error_count=major, minor_error_count=minor),
        make_qa_supervisor_headers(reviewer)))


def get_job(job_id) -> dict:
    return get_success_data(api_client.get_dictation_job(job_id, VENDOR))


def get_editor(editor_id) -> dict:
    return get_success_data(api_client.get_editor(editor_id, VENDOR))


def get_provider(provider_id) -> dict:
    return get_success_data(api_client.get_provider(provider_id, VENDOR))


def get_clinic(clinic_id) -> dict:
    return get_success_data(api_client.get_clinic_account(clinic_id, VENDOR))


def get_job_transcripts(job_id) -> list:
    return get_success_data(api_client.list_transcripts(
        VENDOR, params={"dictation_job_id": job_id}))


def get_period_line_items(period_id) -> list:
    return get_success_data(api_client.list_billing_period_line_items(period_id, VENDOR))


def deliver_job(provider, editor, priority="ROUTINE", work_type="CONSULT",
                audio_duration_seconds=60, final_text=TEXT_65_CHARS,
                review=(0, 0, 0)) -> dict:
    """Create -> claim -> submit -> QA-PASS. Returns
    {"job": <final job>, "transcript": <delivered transcript>, "review": ...}."""
    job = create_job(provider, work_type=work_type, priority=priority,
                     audio_duration_seconds=audio_duration_seconds)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor, final_text=final_text)
    review = review_job(job["id"], *review)
    transcripts = get_job_transcripts(job["id"])
    return {
        "job": get_job(job["id"]),
        "transcript": transcripts[-1] if transcripts else None,
        "review": review,
    }


def drive_editor_reviews(provider, editor, review_specs, priority="ROUTINE",
                         work_type="CONSULT") -> list:
    """Run one full claim->submit->review cycle per (critical, major, minor)
    spec; each cycle uses a fresh job. Returns the job ids in order."""
    job_ids = []
    for critical, major, minor in review_specs:
        job = create_job(provider, work_type=work_type, priority=priority)
        claim_job(job["id"], editor)
        submit_job(job["id"], editor)
        review_job(job["id"], critical, major, minor)
        job_ids.append(job["id"])
    return job_ids


# ---------------------------------------------------------------------------
# Editor standing fixtures (PRD §3.6)
# ---------------------------------------------------------------------------

def setup_probation_editor() -> dict:
    """Editor with five PASS reviews scored 84.0 (m=3, i=1): rolling 84.00,
    qa_review_count 5 -> PROBATION. Returns {"clinic", "provider", "editor"}."""
    wg = setup_workgroup()
    drive_editor_reviews(wg["provider"], wg["editor"], [(0, 3, 1)] * 5)
    return wg


def setup_capacity_cascade() -> dict:
    """Four delivered jobs scored 80.0 (m=4) put the editor at count 4 (standing
    not yet evaluated); then the editor holds three EDITING jobs claimed at
    00:01 (ROUTINE), 00:02 (URGENT), 00:03 (URGENT), and the ROUTINE job is
    submitted at 00:04 — staged for the standing/capacity cascade trigger."""
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="ROUTINE", tat_minutes=1440,
                   rate_per_line_cents=10, breach_credit_pct=5)
    add_sla_policy(clinic["id"], priority="URGENT", tat_minutes=480,
                   rate_per_line_cents=15, breach_credit_pct=10)
    provider = setup_provider(clinic["id"])
    editor = setup_editor()
    drive_editor_reviews(provider, editor, [(0, 4, 0)] * 4)
    j_r = create_job(provider, priority="ROUTINE")
    j_u1 = create_job(provider, work_type="OP_NOTE", priority="URGENT")
    j_u2 = create_job(provider, work_type="OP_NOTE", priority="URGENT")
    set_clock("2026-08-01T00:01:00Z")
    claim_job(j_r["id"], editor)
    set_clock("2026-08-01T00:02:00Z")
    claim_job(j_u1["id"], editor)
    set_clock("2026-08-01T00:03:00Z")
    claim_job(j_u2["id"], editor)
    set_clock("2026-08-01T00:04:00Z")
    submit_job(j_r["id"], editor)
    return {"clinic": clinic, "provider": provider, "editor": editor,
            "j_r": j_r, "j_u1": j_u1, "j_u2": j_u2}


# ---------------------------------------------------------------------------
# Provider aging / suspension fixtures (PRD §3.7)
# ---------------------------------------------------------------------------

def setup_unsigned_delivered_transcripts(n=3, with_billing_period=False) -> dict:
    """Clinic (default thresholds 3 / 24h / 72h / 14d) + provider + editor with
    n ROUTINE jobs delivered at T0 and left unsigned. Optionally also creates,
    closes, and finalizes a covering billing period (finalized_at = T0)."""
    wg = setup_workgroup()
    transcripts = []
    jobs = []
    for _ in range(n):
        delivered = deliver_job(wg["provider"], wg["editor"], review=(0, 1, 0))
        jobs.append(delivered["job"])
        transcripts.append(delivered["transcript"])
    period = None
    if with_billing_period:
        period = get_success_data(api_client.create_billing_period(
            create_billing_period_payload(wg["clinic"]["id"]), VENDOR))
        get_success_data(api_client.close_billing_period(period["id"], VENDOR))
        period = get_success_data(api_client.finalize_billing_period(period["id"], VENDOR))
    return {"clinic": wg["clinic"], "provider": wg["provider"],
            "editor": wg["editor"], "jobs": jobs, "transcripts": transcripts,
            "period": period}


# ---------------------------------------------------------------------------
# Billing fixtures (PRD §3.9)
# ---------------------------------------------------------------------------

def setup_dual_basis_scenario() -> dict:
    """Two clinics with identical STAT SLAs except measurement_basis
    (END_TO_END vs PRODUCTION_WINDOW); both jobs claimed at T0+30m, submitted
    (65 visible chars) and QA-passed at T0+150m; both periods closed and
    finalized. Returns ids for both lineages."""
    c1 = setup_clinic(name="C E2E")
    add_sla_policy(c1["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25,
                   measurement_basis="END_TO_END")
    c2 = setup_clinic(name="C PW")
    add_sla_policy(c2["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25,
                   measurement_basis="PRODUCTION_WINDOW")
    p1 = setup_provider(c1["id"], full_name="P One")
    p2 = setup_provider(c2["id"], full_name="P Two")
    editor = setup_editor()
    j1 = create_job(p1, priority="STAT", audio_duration_seconds=300)
    j2 = create_job(p2, priority="STAT", audio_duration_seconds=300)
    set_clock("2026-08-01T00:30:00Z")
    claim_job(j1["id"], editor)
    claim_job(j2["id"], editor)
    set_clock("2026-08-01T02:30:00Z")
    submit_job(j1["id"], editor)
    submit_job(j2["id"], editor)
    review_job(j1["id"], 0, 1, 0)
    review_job(j2["id"], 0, 1, 0)
    bp1 = get_success_data(api_client.create_billing_period(
        create_billing_period_payload(c1["id"]), VENDOR))
    get_success_data(api_client.close_billing_period(bp1["id"], VENDOR))
    get_success_data(api_client.finalize_billing_period(bp1["id"], VENDOR))
    bp2 = get_success_data(api_client.create_billing_period(
        create_billing_period_payload(c2["id"]), VENDOR))
    get_success_data(api_client.close_billing_period(bp2["id"], VENDOR))
    get_success_data(api_client.finalize_billing_period(bp2["id"], VENDOR))
    return {"c1": c1, "c2": c2, "p1": p1, "p2": p2, "editor": editor,
            "j1": j1, "j2": j2, "bp1": bp1, "bp2": bp2}


def setup_breaching_stat_period(num_jobs=2, rate=35, pct=10) -> dict:
    """Clinic with STAT SLA (tat 120) and `num_jobs` STAT jobs created at T0,
    claimed at 00:10/00:11..., submitted with 131 visible chars at 02:10/02:11...
    (past the 02:00 deadline) and QA-passed; period [07-01, 09-01] closed and
    finalized. Each item: 3 lines -> 105c final, credit round_half_up(10.5)=11."""
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=rate, breach_credit_pct=pct,
                   measurement_basis="END_TO_END")
    provider = setup_provider(clinic["id"], specialty="RADIOLOGY")
    editor = setup_editor()
    jobs = [create_job(provider, work_type="RADIOLOGY_REPORT", priority="STAT")
            for _ in range(num_jobs)]
    for i, job in enumerate(jobs):
        set_clock(f"2026-08-01T00:{10 + i:02d}:00Z")
        claim_job(job["id"], editor)
    for i, job in enumerate(jobs):
        set_clock(f"2026-08-01T02:{10 + i:02d}:00Z")
        submit_job(job["id"], editor, final_text=TEXT_131_CHARS)
    for job in jobs:
        review_job(job["id"], 0, 0, 0)
    period = get_success_data(api_client.create_billing_period(
        create_billing_period_payload(clinic["id"]), VENDOR))
    get_success_data(api_client.close_billing_period(period["id"], VENDOR))
    period = get_success_data(api_client.finalize_billing_period(period["id"], VENDOR))
    return {"clinic": clinic, "provider": provider, "editor": editor,
            "jobs": jobs, "period": period}


def setup_period_with_delivered_job(audio_duration_seconds=100,
                                    final_text=TEXT_65_CHARS) -> dict:
    """Clinic (ROUTINE tat 1440, rate 10c) + provider + editor + one ROUTINE
    job delivered at T0; period [07-01, 09-01] created but NOT closed."""
    wg = setup_workgroup()
    delivered = deliver_job(wg["provider"], wg["editor"],
                            audio_duration_seconds=audio_duration_seconds,
                            final_text=final_text)
    period = get_success_data(api_client.create_billing_period(
        create_billing_period_payload(wg["clinic"]["id"]), VENDOR))
    return {"clinic": wg["clinic"], "provider": wg["provider"],
            "editor": wg["editor"], "job": delivered["job"],
            "transcript": delivered["transcript"], "period": period}
