"""Composite setup helpers for the Building Permit & Inspection API.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Entity-backed identity threading (PRD §2.1): after creating a PlanReviewer or
Inspector, ownership/segregation-gated calls use make_reviewer_headers(rev["id"])
/ make_inspector_headers(insp["id"]) with the real entity id — never a constant.

A counter feeds the globally-unique identifiers (license_number, badge_number,
cert_number). Because the server restarts before each test the DB is empty, but
keeping ids unique within a single test's setup avoids accidental collisions.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_clerk_headers,
    make_official_headers,
    make_reviewer_headers,
    make_inspector_headers,
)

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


# ─── Reference data ────────────────────────────────────
def create_jurisdiction(**overrides) -> dict:
    """Create a jurisdiction with the standard fee schedule."""
    payload = f.create_jurisdiction_payload(name=_uniq("City"), **overrides)
    resp = api_client.create_jurisdiction(payload, make_official_headers())
    return get_success_data(resp)


def create_contractor(**overrides) -> dict:
    """Register a contractor (defaults to a fully VERIFIED posture)."""
    if "license_number" not in overrides:
        overrides["license_number"] = _uniq("LIC")
    payload = f.create_contractor_payload(**overrides)
    resp = api_client.create_contractor(payload, make_clerk_headers())
    return get_success_data(resp)


def create_inspector(**overrides) -> dict:
    if "badge_number" not in overrides:
        overrides["badge_number"] = _uniq("BADGE")
    payload = f.create_inspector_payload(**overrides)
    resp = api_client.create_inspector(payload, make_official_headers())
    return get_success_data(resp)


def create_plan_reviewer(**overrides) -> dict:
    if "cert_number" not in overrides:
        overrides["cert_number"] = _uniq("CERT")
    payload = f.create_plan_reviewer_payload(**overrides)
    resp = api_client.create_plan_reviewer(payload, make_official_headers())
    return get_success_data(resp)


def create_slot(inspector_id, window_start="2026-07-01T08:00:00Z",
                window_end="2026-07-01T17:00:00Z", max_inspections=5, **overrides) -> dict:
    payload = f.create_slot_payload(
        inspector_id, window_start, window_end,
        max_inspections=max_inspections, **overrides,
    )
    resp = api_client.create_slot(payload, make_official_headers())
    return get_success_data(resp)


# ─── Permit base ───────────────────────────────────────
def create_permit(jurisdiction_id=None, contractor_id=None, **overrides) -> dict:
    """Create a SUBMITTED permit, auto-provisioning jurisdiction/contractor if absent."""
    if jurisdiction_id is None:
        jurisdiction_id = create_jurisdiction()["id"]
    if contractor_id is None:
        contractor_id = create_contractor()["id"]
    payload = f.create_permit_payload(jurisdiction_id, contractor_id, **overrides)
    resp = api_client.create_permit(payload, make_applicant_headers())
    return get_success_data(resp)


def create_submitted_permit(**permit_overrides) -> dict:
    """A SUBMITTED permit with default jurisdiction + verified contractor."""
    return create_permit(**permit_overrides)


# ─── Plan-review progression (Tier 1 / Tier 2) ─────────
def open_review(permit_id, reviewer_id) -> dict:
    resp = api_client.open_review(
        permit_id, f.open_review_payload(reviewer_id),
        make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def attach_correction(review_id, reviewer_id, **overrides) -> dict:
    resp = api_client.create_correction_notice(
        review_id, f.correction_notice_payload(**overrides),
        make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def decide_review(review_id, reviewer_id, decision) -> dict:
    resp = api_client.decide_review(
        review_id, {"decision": decision},
        make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def create_permit_under_review(reviewer=None, **permit_overrides):
    """SUBMITTED -> UNDER_REVIEW with an OPEN PlanReview.

    Returns (permit, review, reviewer).
    """
    permit = create_permit(**permit_overrides)
    if reviewer is None:
        reviewer = create_plan_reviewer()
    review = open_review(permit["id"], reviewer["id"])
    return permit, review, reviewer


def create_permit_corrections_required(num_open_corrections=1, **permit_overrides):
    """UNDER_REVIEW -> CORRECTIONS_REQUIRED with `num_open_corrections` OPEN notices.

    Returns (permit, review, reviewer, [corrections]).
    """
    permit, review, reviewer = create_permit_under_review(**permit_overrides)
    corrections = [
        attach_correction(review["id"], reviewer["id"],
                          code_section=f"R{300 + i}.1", description=f"Item {i}")
        for i in range(num_open_corrections)
    ]
    decide_review(review["id"], reviewer["id"], "CORRECTIONS")
    return permit, review, reviewer, corrections


def create_approved_permit(reviewer=None, contractor_id=None, jurisdiction_id=None,
                           **permit_overrides):
    """SUBMITTED -> UNDER_REVIEW -> APPROVED (no open corrections).

    Returns (permit, review, reviewer). The reviewer's id is the permit's
    approving_reviewer_id used by the segregation-of-duties check.
    """
    if jurisdiction_id is None:
        jurisdiction_id = create_jurisdiction()["id"]
    if contractor_id is None:
        contractor_id = create_contractor()["id"]
    permit = create_permit(jurisdiction_id, contractor_id, **permit_overrides)
    if reviewer is None:
        reviewer = create_plan_reviewer()
    review = open_review(permit["id"], reviewer["id"])
    decide_review(review["id"], reviewer["id"], "APPROVED")
    return permit, review, reviewer


# ─── Payment helpers ───────────────────────────────────
def pay_permit(permit_id, amount, payment_status=None) -> dict:
    payload = f.create_payment_payload(amount)
    if payment_status is not None:
        payload["payment_status"] = payment_status
    resp = api_client.create_payment(permit_id, payload, make_applicant_headers())
    return get_success_data(resp)


def pay_in_full(permit_id) -> dict:
    """Pay the permit's current balance_due exactly, driving balance_due to 0."""
    permit = get_success_data(api_client.get_permit(permit_id, make_clerk_headers()))
    balance = permit["balance_due"]
    if balance > 0:
        pay_permit(permit_id, balance)
    return get_success_data(api_client.get_permit(permit_id, make_clerk_headers()))


def current_version(permit_id) -> int:
    permit = get_success_data(api_client.get_permit(permit_id, make_clerk_headers()))
    return permit["version"]


# ─── Issuance (Tier 3) ─────────────────────────────────
def issue_permit(permit_id) -> dict:
    """Issue with the freshly-read current version. Returns the issued permit."""
    pv = current_version(permit_id)
    resp = api_client.issue_permit(
        permit_id, {"expected_permit_application_version": pv},
        make_clerk_headers(),
    )
    return get_success_data(resp)


def create_issued_permit(reviewer=None, contractor_id=None, jurisdiction_id=None,
                         **permit_overrides):
    """Full lifecycle to ISSUED: approve, pay in full, issue.

    Returns (permit_issued, reviewer). The contractor is fully VERIFIED.
    """
    permit, review, reviewer = create_approved_permit(
        reviewer=reviewer, contractor_id=contractor_id,
        jurisdiction_id=jurisdiction_id, **permit_overrides,
    )
    pay_in_full(permit["id"])
    issued = issue_permit(permit["id"])
    return issued, reviewer


# ─── Inspection helpers ────────────────────────────────
def schedule_inspection(permit_id, slot_id, inspection_type,
                        scheduled_start, scheduled_end) -> dict:
    resp = api_client.schedule_inspection(
        permit_id,
        f.schedule_inspection_payload(slot_id, inspection_type, scheduled_start, scheduled_end),
        make_applicant_headers(),
    )
    return get_success_data(resp)


def record_result(inspection_id, inspector_id, outcome) -> dict:
    resp = api_client.record_inspection_result(
        inspection_id, {"outcome": outcome},
        make_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def create_issued_permit_with_slot(max_inspections=5, **issued_overrides):
    """ISSUED permit + a neutral Inspector + a published slot.

    Returns (permit_issued, reviewer, inspector, slot).
    """
    issued, reviewer = create_issued_permit(**issued_overrides)
    inspector = create_inspector()
    slot = create_slot(inspector["id"], max_inspections=max_inspections)
    return issued, reviewer, inspector, slot


def create_issued_permit_with_scheduled_rough(max_inspections=5,
                                              start="2026-07-01T09:00:00Z",
                                              end="2026-07-01T10:00:00Z",
                                              **issued_overrides):
    """ISSUED permit with one SCHEDULED ROUGH inspection (booked_count 1).

    Returns (permit_issued, reviewer, inspector, slot, rough_inspection).
    """
    issued, reviewer, inspector, slot = create_issued_permit_with_slot(
        max_inspections=max_inspections, **issued_overrides)
    rough = schedule_inspection(issued["id"], slot["id"], "ROUGH", start, end)
    return issued, reviewer, inspector, slot, rough


def create_issued_permit_with_passed_rough(max_inspections=5, **issued_overrides):
    """ISSUED permit with a PASSED ROUGH inspection.

    Returns (permit_issued, reviewer, inspector, slot, rough_passed).
    """
    issued, reviewer, inspector, slot, rough = (
        create_issued_permit_with_scheduled_rough(
            max_inspections=max_inspections, **issued_overrides))
    rough_passed = record_result(rough["id"], inspector["id"], "PASS")
    return issued, reviewer, inspector, slot, rough_passed


def create_permit_with_certificate(max_inspections=5, **issued_overrides):
    """ISSUED permit with a PASSED ROUGH and a passed FINAL that cascaded an
    ISSUED CertificateOfOccupancy. The neutral inspector is distinct from the
    approving reviewer so the segregation-of-duties gate passes.

    Returns (permit_issued, reviewer, inspector, slot, final_passed, certificate).
    """
    issued, reviewer, inspector, slot = create_issued_permit_with_slot(
        max_inspections=max_inspections, **issued_overrides)
    rough = schedule_inspection(issued["id"], slot["id"], "ROUGH",
                                "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    record_result(rough["id"], inspector["id"], "PASS")
    final = schedule_inspection(issued["id"], slot["id"], "FINAL",
                                "2026-07-01T11:00:00Z", "2026-07-01T12:00:00Z")
    final_passed = record_result(final["id"], inspector["id"], "PASS")
    certs, _ = _list_certificates_for_permit(issued["id"])
    certificate = certs[0] if certs else None
    return issued, reviewer, inspector, slot, final_passed, certificate


def _list_certificates_for_permit(permit_id):
    resp = api_client.list_certificates(make_official_headers(), params={"permit_id": permit_id})
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


# ─── Expiration / renewal (Tier 5) ─────────────────────
def set_clock(iso8601: str):
    resp = api_client.clock_set({"to_iso8601": iso8601}, make_official_headers())
    return get_success_data(resp)


def advance_clock(days: int):
    resp = api_client.clock_advance({"days": days}, make_official_headers())
    return get_success_data(resp)


def create_expired_permit(base_clock="2026-01-01T00:00:00Z", advance_days=200,
                          permit_valid_days=180, **issued_overrides):
    """ISSUED -> EXPIRED via clock advance + expire sweep.

    Returns (permit_expired, reviewer). The jurisdiction uses permit_valid_days.
    """
    set_clock(base_clock)
    jurisdiction_id = create_jurisdiction(permit_valid_days=permit_valid_days)["id"]
    issued, reviewer = create_issued_permit(
        jurisdiction_id=jurisdiction_id, **issued_overrides)
    advance_clock(advance_days)
    resp = api_client.expire_permit(issued["id"], make_official_headers())
    expired = get_success_data(resp)
    return expired, reviewer


# ─── Stop-work ─────────────────────────────────────────
def issue_stop_work(permit_id, **overrides) -> dict:
    resp = api_client.create_stop_work_order(
        permit_id, f.stop_work_order_payload(**overrides), make_official_headers())
    return get_success_data(resp)
