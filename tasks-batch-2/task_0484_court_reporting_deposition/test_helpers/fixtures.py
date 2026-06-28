"""Composite setup helpers (PRD §3).

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() so a setup failure surfaces clearly.

Identity threading (PRD §2.1): Reporter is entity_backed:Resource and Attorney
is entity_backed:Attorney. Every ownership/case-party-gated call therefore uses
make_reporter_headers(<resource_id>) / make_attorney_headers(<attorney_id>) with
the *acting* entity's id — never the shared constant. ScheduleCoordinator,
BillingClerk, and PlatformAdmin are opaque operators.

Many interesting claims need a job several state-machine hops deep (NOTICED ->
CONFIRMED -> IN_SESSION -> ADJOURNED) and a transcript through its production /
read-and-sign lifecycle. The builders below expose the values tests control
(jurisdiction, tier, pages, rates, session window, exhibits) and default the rest.
The OCC field expected_job_version (PRD §2.6) is re-read from the live job before
each mutating job call so chains stay version-correct.
"""
from dataclasses import dataclass, field
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_schedule_coordinator_headers,
    make_billing_clerk_headers,
    make_platform_admin_headers,
    make_reporter_headers,
    make_attorney_headers,
)
from . import factories as F

COORD = make_schedule_coordinator_headers()
BILLING = make_billing_clerk_headers()
ADMIN = make_platform_admin_headers()

_DOCKET_SEQ = [0]
_EMAIL_SEQ = [0]


def _data(resp):
    return get_success_data(resp)


def _next_docket(prefix="FX"):
    _DOCKET_SEQ[0] += 1
    return f"{prefix}-{_DOCKET_SEQ[0]:05d}"


def _next_email(prefix="fx"):
    _EMAIL_SEQ[0] += 1
    return f"{prefix}{_EMAIL_SEQ[0]:05d}@x.com"


# ---------------------------------------------------------------------------
# Clock control (PRD §2.8)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the logical server clock to an absolute ISO 8601 UTC instant."""
    return _data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Primitive reference-data builders (PRD §3.1)
# ---------------------------------------------------------------------------
def make_attorney(full_name="Test Attorney", firm_name="Test LLP", bar_state="CA",
                  email=None):
    return _data(api_client.create_attorney(
        F.create_attorney_payload(
            full_name=full_name, firm_name=firm_name, bar_state=bar_state,
            email=email or _next_email()),
        COORD))


def make_case(noticing_attorney_id, caption="Doe v Acme", jurisdiction="STATE_CA",
              docket_number=None):
    return _data(api_client.create_case(
        F.create_case_payload(
            caption=caption, docket_number=docket_number or _next_docket(),
            jurisdiction=jurisdiction, noticing_attorney_id=noticing_attorney_id),
        COORD))


def make_reporter(full_name="Test Reporter", hourly_appearance_cents=10000,
                  realtime_capable=None, certifications=None):
    extra = {}
    if realtime_capable is not None:
        extra["realtime_capable"] = realtime_capable
    if certifications is not None:
        extra["certifications"] = certifications
    return _data(api_client.create_resource(
        F.create_resource_payload(
            full_name=full_name, kind="REPORTER",
            hourly_appearance_cents=hourly_appearance_cents, **extra),
        COORD))


def make_videographer(full_name="Test Videographer", hourly_appearance_cents=8000):
    return _data(api_client.create_resource(
        F.create_resource_payload(
            full_name=full_name, kind="VIDEOGRAPHER",
            hourly_appearance_cents=hourly_appearance_cents),
        COORD))


def make_interpreter(full_name="Test Interpreter", certifications=None,
                     hourly_appearance_cents=9000):
    return _data(api_client.create_resource(
        F.create_resource_payload(
            full_name=full_name, kind="INTERPRETER",
            certifications=certifications or [],
            hourly_appearance_cents=hourly_appearance_cents),
        COORD))


def deactivate_resource(resource_id):
    return _data(api_client.deactivate_resource(resource_id, ADMIN))


def make_job(case_id, scheduled_start="2026-06-01T09:00:00Z",
             scheduled_end="2026-06-01T11:00:00Z", deponent_name="Witness W",
             **flags):
    """Notice a job. flags may include requires_videographer, requires_interpreter,
    interpreter_language, requires_realtime."""
    return _data(api_client.create_job(
        F.create_job_payload(
            case_id=case_id, scheduled_start=scheduled_start,
            scheduled_end=scheduled_end, deponent_name=deponent_name, **flags),
        COORD))


def current_job_version(job_id):
    return _data(api_client.get_job(job_id, COORD))["version"]


def add_assignment(job_id, resource_id, role, expected_job_version=None):
    if expected_job_version is None:
        expected_job_version = current_job_version(job_id)
    return _data(api_client.create_assignment(
        job_id,
        F.create_assignment_payload(
            resource_id=resource_id, role=role,
            expected_job_version=expected_job_version),
        COORD))


def confirm_job(job_id):
    return _data(api_client.confirm_job(
        job_id, {"expected_job_version": current_job_version(job_id)}, COORD))


def start_job(job_id):
    return _data(api_client.start_job(
        job_id, {"expected_job_version": current_job_version(job_id)}, COORD))


def adjourn_job(job_id):
    return _data(api_client.adjourn_job(
        job_id, {"expected_job_version": current_job_version(job_id)}, COORD))


def cancel_job(job_id):
    return _data(api_client.cancel_job(
        job_id, {"expected_job_version": current_job_version(job_id)}, COORD))


# ---------------------------------------------------------------------------
# Composite scenario result
# ---------------------------------------------------------------------------
@dataclass
class JobScenario:
    attorney_id: str
    case_id: str
    reporter_id: str
    job_id: str
    assignment_id: Optional[str] = None
    videographer_id: Optional[str] = None
    videographer_assignment_id: Optional[str] = None
    transcript_order_id: Optional[str] = None
    invoice_id: Optional[str] = None
    jurisdiction: str = "STATE_CA"
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier 1/2/3 — job lifecycle builders
# ---------------------------------------------------------------------------
def setup_reporter_job(jurisdiction="STATE_CA",
                       scheduled_start="2026-06-01T09:00:00Z",
                       scheduled_end="2026-06-01T11:00:00Z",
                       hourly_appearance_cents=10000, realtime_capable=None,
                       requires_realtime=False, certifications=("CSR_CA",)):
    """A NOTICED job with one ACTIVE reporter assignment (posture READY for a
    reporter-only job). Returns a JobScenario."""
    att = make_attorney()
    case = make_case(att["id"], jurisdiction=jurisdiction)
    flags = {}
    if requires_realtime:
        flags["requires_realtime"] = True
    rep = make_reporter(
        hourly_appearance_cents=hourly_appearance_cents,
        realtime_capable=realtime_capable,
        certifications=list(certifications) if certifications is not None else None)
    job = make_job(case["id"], scheduled_start=scheduled_start,
                   scheduled_end=scheduled_end, **flags)
    asg = add_assignment(job["id"], rep["id"], "REPORTER")
    return JobScenario(
        attorney_id=att["id"], case_id=case["id"], reporter_id=rep["id"],
        job_id=job["id"], assignment_id=asg["id"], jurisdiction=jurisdiction)


def setup_confirmed_reporter_job(**kwargs):
    """A CONFIRMED reporter-only job (posture READY)."""
    sc = setup_reporter_job(**kwargs)
    confirm_job(sc.job_id)
    return sc


def run_session(job_id, start_iso, end_iso):
    """Advance a CONFIRMED job through start (at start_iso) and adjourn (at
    end_iso), driving the logical clock to each instant. Leaves the job ADJOURNED
    with appearance fees frozen onto its completed assignments (PRD §3.5/§3.6)."""
    set_clock(start_iso)
    start_job(job_id)
    set_clock(end_iso)
    return adjourn_job(job_id)


def setup_adjourned_reporter_job(jurisdiction="STATE_CA",
                                 scheduled_start="2026-06-01T09:00:00Z",
                                 scheduled_end="2026-06-01T11:00:00Z",
                                 session_start=None, session_end=None,
                                 hourly_appearance_cents=10000):
    """A job run end-to-end to ADJOURNED. By default the actual session matches a
    2-hour scheduled window. Returns a JobScenario."""
    sc = setup_confirmed_reporter_job(
        jurisdiction=jurisdiction, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, hourly_appearance_cents=hourly_appearance_cents)
    run_session(sc.job_id, session_start or scheduled_start,
                session_end or scheduled_end)
    return sc


# ---------------------------------------------------------------------------
# Tier 3 — transcript production lifecycle
# ---------------------------------------------------------------------------
def order_transcript(sc: JobScenario, turnaround_tier="STANDARD",
                     certified_copy=None, estimated_pages=30):
    """Order a transcript on an ADJOURNED job, acting as the ordering attorney."""
    extra = {}
    if certified_copy is not None:
        extra["certified_copy"] = certified_copy
    to = _data(api_client.create_transcript_order(
        F.create_transcript_order_payload(
            job_id=sc.job_id, ordering_attorney_id=sc.attorney_id,
            turnaround_tier=turnaround_tier, estimated_pages=estimated_pages, **extra),
        make_attorney_headers(sc.attorney_id)))
    sc.transcript_order_id = to["id"]
    return to


def deliver_rough(sc: JobScenario):
    return _data(api_client.deliver_rough(
        sc.transcript_order_id, make_reporter_headers(sc.reporter_id)))


def certify(sc: JobScenario, final_pages=30):
    return _data(api_client.certify_transcript(
        sc.transcript_order_id, F.create_certify_payload(final_pages=final_pages),
        make_reporter_headers(sc.reporter_id)))


def open_read_sign(sc: JobScenario):
    return _data(api_client.open_read_sign(sc.transcript_order_id, COORD))


def file_errata(sc: JobScenario, corrections=None, reason="transcription error"):
    payload = F.create_errata_payload(reason=reason)
    if corrections is not None:
        payload["corrections"] = corrections
    return _data(api_client.file_errata(
        sc.transcript_order_id, payload, make_attorney_headers(sc.attorney_id)))


def sign(sc: JobScenario):
    return _data(api_client.sign_transcript(
        sc.transcript_order_id, make_attorney_headers(sc.attorney_id)))


def deliver_transcript(sc: JobScenario):
    return _data(api_client.deliver_transcript(sc.transcript_order_id, COORD))


def add_exhibit(sc: JobScenario, marked_label, page_count, confidential=None):
    extra = {}
    if confidential is not None:
        extra["confidential"] = confidential
    return _data(api_client.create_exhibit(
        sc.transcript_order_id,
        F.create_exhibit_payload(marked_label=marked_label, page_count=page_count, **extra),
        make_attorney_headers(sc.attorney_id)))


def setup_certified_transcript(jurisdiction="STATE_CA", turnaround_tier="STANDARD",
                               certified_copy=True, estimated_pages=30,
                               final_pages=30, hourly_appearance_cents=10000):
    """Run a reporter-only job to ADJOURNED, order + rough-deliver + certify a
    transcript. Returns (JobScenario, transcript_order dict at CERTIFIED)."""
    sc = setup_adjourned_reporter_job(
        jurisdiction=jurisdiction, hourly_appearance_cents=hourly_appearance_cents)
    order_transcript(sc, turnaround_tier=turnaround_tier,
                     certified_copy=certified_copy, estimated_pages=estimated_pages)
    deliver_rough(sc)
    to = certify(sc, final_pages=final_pages)
    return sc, to


def setup_read_sign_open_transcript(**kwargs):
    """A CERTIFIED transcript advanced to READ_SIGN_OPEN. Returns (sc, to)."""
    sc, _ = setup_certified_transcript(**kwargs)
    to = open_read_sign(sc)
    return sc, to


def setup_delivered_transcript(jurisdiction="STATE_CA", turnaround_tier="STANDARD",
                               certified_copy=True, estimated_pages=30,
                               final_pages=30, hourly_appearance_cents=10000,
                               exhibits=None):
    """Run a transcript all the way through to DELIVERED (sign then deliver),
    optionally attaching exhibits before certification. exhibits is a list of
    (marked_label, page_count, confidential) tuples. Returns (sc, to)."""
    sc = setup_adjourned_reporter_job(
        jurisdiction=jurisdiction, hourly_appearance_cents=hourly_appearance_cents)
    order_transcript(sc, turnaround_tier=turnaround_tier,
                     certified_copy=certified_copy, estimated_pages=estimated_pages)
    if exhibits:
        for label, pages, conf in exhibits:
            add_exhibit(sc, label, pages, confidential=conf)
    deliver_rough(sc)
    to = certify(sc, final_pages=final_pages)
    open_read_sign(sc)
    sign(sc)
    to = deliver_transcript(sc)
    return sc, to


def create_invoice(sc: JobScenario):
    inv = _data(api_client.create_invoice(
        F.create_invoice_payload(
            job_id=sc.job_id, transcript_order_id=sc.transcript_order_id),
        BILLING))
    sc.invoice_id = inv["id"]
    return inv


def issue_invoice(sc: JobScenario):
    return _data(api_client.issue_invoice(sc.invoice_id, BILLING))


def setup_issued_invoice(jurisdiction="STATE_CA", turnaround_tier="STANDARD",
                         certified_copy=True, final_pages=30,
                         hourly_appearance_cents=10000, estimated_pages=None,
                         exhibits=None):
    """Full path to an ISSUED invoice over a delivered transcript. Returns (sc, invoice)."""
    sc, _ = setup_delivered_transcript(
        jurisdiction=jurisdiction, turnaround_tier=turnaround_tier,
        certified_copy=certified_copy,
        estimated_pages=estimated_pages if estimated_pages is not None else final_pages,
        final_pages=final_pages, hourly_appearance_cents=hourly_appearance_cents,
        exhibits=exhibits)
    create_invoice(sc)
    inv = issue_invoice(sc)
    return sc, inv


# ---------------------------------------------------------------------------
# Realtime-stream lifecycle (PRD §3.7)
# ---------------------------------------------------------------------------
def setup_insession_realtime_job(hourly_appearance_cents=15000,
                                 scheduled_start="2026-08-10T09:00:00Z",
                                 scheduled_end="2026-08-10T13:00:00Z",
                                 session_start="2026-08-10T09:00:00Z"):
    """A requires_realtime job IN_SESSION with a realtime_capable reporter
    assignment. Returns a JobScenario (clock left at session_start)."""
    att = make_attorney()
    case = make_case(att["id"], jurisdiction="STATE_CA")
    rep = make_reporter(hourly_appearance_cents=hourly_appearance_cents,
                        realtime_capable=True, certifications=["CSR_CA", "RMR"])
    job = make_job(case["id"], scheduled_start=scheduled_start,
                   scheduled_end=scheduled_end, requires_realtime=True)
    asg = add_assignment(job["id"], rep["id"], "REPORTER")
    confirm_job(job["id"])
    set_clock(session_start)
    start_job(job["id"])
    return JobScenario(
        attorney_id=att["id"], case_id=case["id"], reporter_id=rep["id"],
        job_id=job["id"], assignment_id=asg["id"], jurisdiction="STATE_CA")


def provision_stream(sc: JobScenario):
    stream = _data(api_client.create_realtime_stream(
        sc.job_id, F.create_realtime_stream_payload(reporter_assignment_id=sc.assignment_id),
        COORD))
    sc.extra["stream_id"] = stream["id"]
    return stream


def go_live(sc: JobScenario):
    return _data(api_client.go_live_stream(
        sc.extra["stream_id"], make_reporter_headers(sc.reporter_id)))
