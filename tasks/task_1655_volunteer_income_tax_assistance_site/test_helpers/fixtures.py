"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.

Identity threading: SiteCoordinator, Preparer, QualityReviewer, and Screener
are entity-backed roles (PRD §2.1) — every call made on their behalf uses
make_<role>_headers(volunteer["id"]) with the real Volunteer id, never the
shared TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appointment_payload,
    create_certification_payload,
    create_refund_allocation_payload,
    create_site_payload,
    create_site_report_payload,
    create_tax_return_payload,
    create_taxpayer_payload,
    create_volunteer_payload,
    patch_tax_return_payload,
)
from .test_users import (
    TEST_USERS,
    make_preparer_headers,
    make_quality_reviewer_headers,
    make_screener_headers,
    make_site_coordinator_headers,
)

ADMIN = TEST_USERS["sponsor_admin_headers"]

# Standard appointment slot inside every default site's season and daily
# window, and after the startup logical clock (PRD §2.5).
DAY1_START = "2026-08-03T10:00:00Z"
DAY1_END = "2026-08-03T11:00:00Z"
DAY2_START = "2026-08-04T10:00:00Z"
DAY2_END = "2026-08-04T11:00:00Z"
DAY3_START = "2026-08-05T10:00:00Z"
DAY3_END = "2026-08-05T11:00:00Z"


class VitaSiteCtx:
    """A site plus the volunteers who staff it, with per-role headers."""

    def __init__(self, site, coordinator):
        self.site = site
        self.coordinator = coordinator
        self.screener = None
        self.preparer = None
        self.reviewer = None

    @property
    def site_id(self):
        return self.site["id"]

    @property
    def coord_headers(self):
        return make_site_coordinator_headers(self.coordinator["id"])

    @property
    def scr_headers(self):
        return make_screener_headers(self.screener["id"])

    @property
    def prep_headers(self):
        return make_preparer_headers(self.preparer["id"])

    @property
    def rev_headers(self):
        return make_quality_reviewer_headers(self.reviewer["id"])


# ─── Clock (PRD §2.5) ─────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock; SponsorAdmin-only."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: site onboarding (PRD §3.1) ───────────────

def create_site(**overrides):
    """Create a SETUP site. Returns the site."""
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def register_volunteer(site_id, actor_headers, **overrides):
    """Register a volunteer (REGISTERED) at a site."""
    return get_success_data(
        api_client.create_volunteer(create_volunteer_payload(site_id, **overrides), actor_headers)
    )


def get_volunteer(volunteer_id, actor_headers=ADMIN):
    return get_success_data(api_client.get_volunteer(volunteer_id, actor_headers))


def record_certification(volunteer_id, actor_headers, test_type="ETHICS", score=90,
                         tax_season=2026):
    """Record one certification attempt against a volunteer.

    The call is optimistic-concurrency guarded on the volunteer's version
    (PRD §2.7), and each recording increments that version by one, so the
    helper re-reads the volunteer immediately before posting.
    """
    current = get_volunteer(volunteer_id, actor_headers)
    payload = create_certification_payload(
        current["version"], test_type=test_type, score=score, tax_season=tax_season
    )
    return get_success_data(api_client.record_certification(volunteer_id, payload, actor_headers))


def transition_volunteer(volunteer_id, to_status, actor_headers):
    return get_success_data(api_client.transition_volunteer(volunteer_id, to_status, actor_headers))


def activate_volunteer(volunteer_id, actor_headers):
    """REGISTERED/INACTIVE -> ACTIVE; requires a CURRENT passed ETHICS cert
    for season 2026 (PRD §3.2)."""
    return transition_volunteer(volunteer_id, "ACTIVE", actor_headers)


def bootstrap_coordinator(site, full_name="Coord Ann", email="coord@x.org"):
    """Register, ETHICS-certify (95), and activate the site's first
    coordinator — allowed while the site is still SETUP (PRD §3.2)."""
    coord = register_volunteer(
        site["id"], ADMIN, full_name=full_name, email=email, is_coordinator=True
    )
    record_certification(coord["id"], ADMIN, test_type="ETHICS", score=95)
    return activate_volunteer(coord["id"], ADMIN)


def transition_site(site_id, to_status, coord_headers):
    return get_success_data(api_client.transition_site(site_id, to_status, coord_headers))


def setup_certified_site(**site_overrides):
    """Site + ACTIVE coordinator, site driven SETUP -> CERTIFIED.

    Certification requires at least one ACTIVE volunteer with
    is_coordinator true (PRD §3.1)."""
    site = create_site(**site_overrides)
    coord = bootstrap_coordinator(site)
    site = transition_site(site["id"], "CERTIFIED", make_site_coordinator_headers(coord["id"]))
    return VitaSiteCtx(site, coord)


def setup_open_site(**site_overrides):
    """Site + ACTIVE coordinator, site driven SETUP -> CERTIFIED -> OPEN.
    Opening is allowed because the startup logical clock lies inside the
    default season window (PRD §3.1)."""
    ctx = setup_certified_site(**site_overrides)
    ctx.site = transition_site(ctx.site_id, "OPEN", ctx.coord_headers)
    return ctx


# ─── Tier 2: staffing (PRD §3.2) ──────────────────────

def add_screener(ctx, full_name="Screen Sam", email="scr@x.org"):
    """A REGISTERED screener. Screener duties (taxpayer registration,
    identity verification, appointment scheduling/check-in) carry no
    activation or certification gate in the PRD."""
    ctx.screener = register_volunteer(ctx.site_id, ctx.coord_headers,
                                      full_name=full_name, email=email)
    return ctx.screener


def add_preparer(ctx, full_name="Prep Pat", email="prep@x.org", advanced=False,
                 ethics_score=90, basic_score=88):
    """An ACTIVE preparer holding CURRENT passed ETHICS + BASIC
    (+ ADVANCED when requested) for season 2026 (PRD §3.4)."""
    prep = register_volunteer(ctx.site_id, ctx.coord_headers, full_name=full_name, email=email)
    record_certification(prep["id"], ctx.coord_headers, test_type="ETHICS", score=ethics_score)
    record_certification(prep["id"], ctx.coord_headers, test_type="BASIC", score=basic_score)
    if advanced:
        record_certification(prep["id"], ctx.coord_headers, test_type="ADVANCED", score=86)
    ctx.preparer = activate_volunteer(prep["id"], ctx.coord_headers)
    return ctx.preparer


def add_reviewer(ctx, full_name="Rev Rita", email="rev@x.org", with_advanced=True,
                 activate=True):
    """A quality reviewer holding CURRENT passed ETHICS + INTAKE_QR
    (+ ADVANCED when with_advanced) for season 2026, ACTIVE when asked
    (PRD §3.5 reviewer gates)."""
    rev = register_volunteer(ctx.site_id, ctx.coord_headers, full_name=full_name, email=email)
    record_certification(rev["id"], ctx.coord_headers, test_type="ETHICS", score=90)
    record_certification(rev["id"], ctx.coord_headers, test_type="INTAKE_QR", score=92)
    if with_advanced:
        record_certification(rev["id"], ctx.coord_headers, test_type="ADVANCED", score=85)
    if activate:
        rev = activate_volunteer(rev["id"], ctx.coord_headers)
    ctx.reviewer = rev
    return rev


def setup_staffed_site(**site_overrides):
    """OPEN site with coordinator, screener, preparer (ETHICS+BASIC), and
    reviewer (ETHICS+INTAKE_QR+ADVANCED) — the standard full crew."""
    ctx = setup_open_site(**site_overrides)
    add_screener(ctx)
    add_preparer(ctx)
    add_reviewer(ctx)
    return ctx


# ─── Tier 2: taxpayers and appointments (PRD §3.3) ────

def register_taxpayer(actor_headers, **overrides):
    return get_success_data(
        api_client.create_taxpayer(create_taxpayer_payload(**overrides), actor_headers)
    )


def verify_taxpayer(taxpayer_id, actor_headers, id_document_type="DRIVERS_LICENSE"):
    return get_success_data(
        api_client.verify_identity(taxpayer_id, id_document_type, actor_headers)
    )


def create_verified_taxpayer(actor_headers, id_document_type="DRIVERS_LICENSE", **overrides):
    tp = register_taxpayer(actor_headers, **overrides)
    return verify_taxpayer(tp["id"], actor_headers, id_document_type)


def schedule_appointment(ctx, taxpayer_id, volunteer_id, start_at=DAY1_START,
                         end_at=DAY1_END, purpose="PREPARATION", actor_headers=None):
    """Create a SCHEDULED appointment; creation gates on the site being
    CERTIFIED/OPEN and the assigned volunteer being ACTIVE (PRD §3.3)."""
    payload = create_appointment_payload(
        ctx.site_id, taxpayer_id, volunteer_id,
        purpose=purpose, start_at=start_at, end_at=end_at,
    )
    return get_success_data(
        api_client.create_appointment(payload, actor_headers or ctx.scr_headers)
    )


def transition_appointment(appointment_id, to_status, actor_headers):
    return get_success_data(
        api_client.transition_appointment(appointment_id, to_status, actor_headers)
    )


def check_in_appointment(appointment_id, actor_headers):
    """SCHEDULED -> CHECKED_IN; requires the site to be OPEN (PRD §3.3)."""
    return transition_appointment(appointment_id, "CHECKED_IN", actor_headers)


def create_checked_in_appointment(ctx, taxpayer_id, volunteer_id, **kwargs):
    appt = schedule_appointment(ctx, taxpayer_id, volunteer_id, **kwargs)
    return check_in_appointment(appt["id"], ctx.scr_headers)


# ─── Tier 3: return lifecycle shortcuts (PRD §3.4-§3.7) ──

def open_return(appointment_id, preparer_id, **overrides):
    """Open a return from a CHECKED_IN appointment as its owning Preparer;
    the return begins INTAKE_STARTED (PRD §3.4)."""
    payload = create_tax_return_payload(appointment_id, **overrides)
    return get_success_data(
        api_client.create_tax_return(payload, make_preparer_headers(preparer_id))
    )


def patch_return(ret, actor_headers, **fields):
    """OCC-guarded edit of a return's intake/preparation fields (PRD §2.7,
    §3.4). `ret` must be the latest observed return dict."""
    payload = patch_tax_return_payload(ret["version"], **fields)
    return get_success_data(api_client.patch_tax_return(ret["id"], payload, actor_headers))


def preparation_ready_patch(ret, actor_headers, **overrides):
    """The standard patch making a return eligible for IN_PREPARATION:
    core documents present, interview confirmed, verified withholding
    recorded (PRD §3.4)."""
    fields = {
        "documents_received": ["PHOTO_ID", "SSN_CARD", "W2"],
        "interview_confirmed": True,
        "wages_cents": 1000000,
        "other_income_cents": 0,
        "earned_income_cents": 1000000,
        "withholding_reported_cents": 100000,
        "withholding_verified_cents": 100000,
    }
    fields.update(overrides)
    return patch_return(ret, actor_headers, **fields)


def create_intake_return(ctx, taxpayer_id, preparer_id=None, appt_kwargs=None,
                         return_overrides=None):
    """CHECKED_IN appointment + INTAKE_STARTED return owned by the preparer."""
    prep_id = preparer_id or ctx.preparer["id"]
    appt_kwargs = appt_kwargs or {}
    appt = create_checked_in_appointment(ctx, taxpayer_id, prep_id, **appt_kwargs)
    ret = open_return(appt["id"], prep_id, **(return_overrides or {}))
    return appt, ret


def create_preparation_ready_return(ctx, taxpayer_id, preparer_id=None,
                                    appt_kwargs=None, return_overrides=None,
                                    patch_overrides=None):
    """INTAKE_STARTED return already patched preparation-ready (PRD §3.4)."""
    appt, ret = create_intake_return(ctx, taxpayer_id, preparer_id, appt_kwargs,
                                     return_overrides)
    ret = preparation_ready_patch(ret, make_preparer_headers(ret["preparer_id"]),
                                  **(patch_overrides or {}))
    return appt, ret


def transition_return(return_id, to_status, actor_headers, **extra):
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(api_client.transition_tax_return(return_id, payload, actor_headers))


def begin_preparation(ret, preparer_id=None):
    """INTAKE_STARTED -> IN_PREPARATION, owner-only (PRD §3.4)."""
    pid = preparer_id or ret["preparer_id"]
    return transition_return(ret["id"], "IN_PREPARATION", make_preparer_headers(pid))


def submit_for_review(ret, preparer_id=None):
    """IN_PREPARATION -> PENDING_QR, owner-only; recomputes
    final_refund_cents (PRD §3.5)."""
    pid = preparer_id or ret["preparer_id"]
    return transition_return(ret["id"], "PENDING_QR", make_preparer_headers(pid))


def review_pass(ret, reviewer_id):
    """PENDING_QR -> QR_PASSED by a certified reviewer (PRD §3.5)."""
    return transition_return(
        ret["id"], "QR_PASSED", make_quality_reviewer_headers(reviewer_id)
    )


def review_fail(ret, reviewer_id, review_notes="Figure mismatch"):
    """PENDING_QR -> QR_FAILED; review_notes required (PRD §3.5)."""
    return transition_return(
        ret["id"], "QR_FAILED", make_quality_reviewer_headers(reviewer_id),
        review_notes=review_notes,
    )


def transmit_return(ret, coord_headers):
    """QR_PASSED -> TRANSMITTED by the SiteCoordinator (PRD §3.6)."""
    return transition_return(ret["id"], "TRANSMITTED", coord_headers)


def accept_return(ret, coord_headers):
    return transition_return(ret["id"], "ACCEPTED", coord_headers)


def reject_return(ret, coord_headers, rejection_code="R0000-503",
                  rejection_text="Spouse SSN mismatch"):
    return transition_return(
        ret["id"], "REJECTED", coord_headers,
        rejection_code=rejection_code, rejection_text=rejection_text,
    )


def complete_return(ret, coord_headers):
    return transition_return(
        ret["id"], "COMPLETED", coord_headers,
        disbursement_confirmed=True, taxpayer_notified=True,
    )


def get_return(return_id, actor_headers=ADMIN):
    return get_success_data(api_client.get_tax_return(return_id, actor_headers))


def drive_return_to_qr_passed(ctx, taxpayer_id, preparer_id=None, appt_kwargs=None,
                              return_overrides=None, patch_overrides=None):
    """Full walk to QR_PASSED: intake -> patch -> IN_PREPARATION ->
    PENDING_QR -> QR_PASSED. Returns (appointment, return)."""
    appt, ret = create_preparation_ready_return(
        ctx, taxpayer_id, preparer_id, appt_kwargs, return_overrides, patch_overrides
    )
    ret = begin_preparation(ret)
    ret = submit_for_review(ret)
    ret = review_pass(ret, ctx.reviewer["id"])
    return appt, ret


def drive_return_to_accepted(ctx, taxpayer_id=None, **kwargs):
    """QR_PASSED -> TRANSMITTED -> ACCEPTED (PAPER_CHECK default: no
    allocation gate, PRD §3.6). Returns (appointment, return)."""
    if taxpayer_id is not None:
        kwargs["taxpayer_id"] = taxpayer_id
    appt, ret = drive_return_to_qr_passed(ctx, **kwargs)
    ret = transmit_return(ret, ctx.coord_headers)
    ret = accept_return(ret, ctx.coord_headers)
    return appt, ret


def drive_return_to_completed(ctx, taxpayer_id=None, **kwargs):
    if taxpayer_id is not None:
        kwargs["taxpayer_id"] = taxpayer_id
    appt, ret = drive_return_to_accepted(ctx, **kwargs)
    ret = complete_return(ret, ctx.coord_headers)
    return appt, ret


def create_rejected_return(ctx, rejection_code="R0000-503",
                           rejection_text="Spouse SSN mismatch", **kwargs):
    """Drive a return to TRANSMITTED then REJECTED. Returns
    (appointment, return, rejection)."""
    appt, ret = drive_return_to_qr_passed(ctx, **kwargs)
    ret = transmit_return(ret, ctx.coord_headers)
    ret = reject_return(ret, ctx.coord_headers, rejection_code, rejection_text)
    rejections = get_success_data(api_client.list_efile_rejections(ret["id"], ADMIN))
    return appt, ret, rejections[0]


def resolve_rejection(rejection_id, actor_headers, resolution_note="Corrected with taxpayer"):
    return get_success_data(
        api_client.record_follow_up(
            rejection_id, {"outcome": "RESOLVED", "resolution_note": resolution_note},
            actor_headers,
        )
    )


def rework_rejected_return(ret, preparer_id=None):
    """REJECTED -> IN_PREPARATION by the owning preparer (PRD §3.7)."""
    pid = preparer_id or ret["preparer_id"]
    return transition_return(ret["id"], "IN_PREPARATION", make_preparer_headers(pid))


# ─── Tier 4: allocations and savings match (PRD §3.6) ──

def add_allocation(tax_return_id, preparer_id, **overrides):
    """Add a refund allocation as the owning Preparer."""
    payload = create_refund_allocation_payload(tax_return_id, **overrides)
    return get_success_data(
        api_client.create_refund_allocation(payload, make_preparer_headers(preparer_id))
    )


def delete_allocation(allocation_id, preparer_id):
    resp = api_client.delete_refund_allocation(
        allocation_id, make_preparer_headers(preparer_id)
    )
    if not (200 <= resp.status_code < 300):
        raise AssertionError(f"Setup step failed with HTTP {resp.status_code}")
    return resp


def list_allocations(tax_return_id, actor_headers=ADMIN):
    return get_success_data(api_client.list_refund_allocations(tax_return_id, actor_headers))


# ─── Tier 4: financial-service referrals (PRD §3.8) ────

def offer_referral(tax_return_id, actor_headers, service_type="CREDIT_COUNSELING"):
    return get_success_data(
        api_client.create_financial_referral(tax_return_id, service_type, actor_headers)
    )


def list_referrals(tax_return_id, actor_headers=ADMIN):
    return get_success_data(api_client.list_financial_referrals(tax_return_id, actor_headers))


# ─── Tier 5: reporting (PRD §3.9) ─────────────────────

def generate_report(site_id, coord_headers, **overrides):
    return get_success_data(
        api_client.create_site_report(site_id, create_site_report_payload(**overrides),
                                      coord_headers)
    )
