"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: every ownership-gated call uses make_caregiver_headers /
make_provider_headers with the real entity id, never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    create_application_payload,
    create_booking_payload,
    create_caregiver_payload,
    create_emergency_request_payload,
    create_program_payload,
    create_provider_payload,
    create_survey_payload,
    create_voucher_payload,
    create_window_payload,
)
from .test_users import TEST_USERS, make_caregiver_headers, make_provider_headers

ANON = TEST_USERS["anonymous_headers"]
COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["funder_admin_headers"]


# ─── Primitive steps ───────────────────────────────────

def set_clock(to_iso8601=CLOCK_DEFAULT_ISO):
    """Advance the logical clock (FunderAdmin-only test-driving endpoint)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_program(**overrides):
    """Create a program. Default rate card: 3000 cents/h, caps 80/320, reserve 200."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))


def run_ops_run(program_id, run_type="STANDARD"):
    """Run an ops-run; returns the generated ReportSnapshot."""
    return get_success_data(api_client.create_ops_run(program_id, {"run_type": run_type}, COORD))


def create_active_caregiver(program=None, email="ann@x.com", need_score=8,
                            **caregiver_overrides):
    """Enroll caregiver, submit application, coordinator APPROVE.
    A single program must exist (approval posture gate + allocation auto-create);
    one is created when not supplied.
    Returns {"program", "caregiver", "application", "allocation"} (OPEN grant)."""
    program = program or create_program()
    caregiver = get_success_data(api_client.create_caregiver(
        create_caregiver_payload(email=email, **caregiver_overrides), ANON))
    cg_headers = make_caregiver_headers(caregiver["id"])
    application = get_success_data(api_client.create_eligibility_application(
        caregiver["id"], create_application_payload(need_score=need_score), cg_headers))
    get_success_data(api_client.create_review_decision(
        application["id"], {"action": "APPROVE"}, COORD))
    allocations = get_success_data(api_client.list_caregiver_allocations(caregiver["id"], COORD))
    open_allocs = [a for a in allocations if a["status"] == "OPEN"]
    assert open_allocs, f"Setup: no OPEN allocation auto-created for caregiver {caregiver['id']}"
    return {"program": program, "caregiver": caregiver,
            "application": application, "allocation": open_allocs[0]}


def setup_caregiver_with_allocation(email="ann@x.com", need_score=8):
    """Program + ACTIVE caregiver with auto-created OPEN allocation."""
    return create_active_caregiver(email=email, need_score=need_score)


def create_active_provider(name="Prov A", credential_level="STANDARD", accepts_emergency=None):
    """Register provider and activate credentials. Returns provider dict."""
    payload = create_provider_payload(name=name, credential_level=credential_level)
    if accepts_emergency is not None:
        payload["accepts_emergency"] = accepts_emergency
    provider = get_success_data(api_client.create_provider(payload, ANON))
    get_success_data(api_client.transition_provider(
        provider["id"], {"target_status": "ACTIVE"}, COORD))
    return provider


def add_window(provider_id, start_at, end_at, capacity=1):
    """Publish an availability window for an ACTIVE provider."""
    return get_success_data(api_client.create_availability_window(
        provider_id, create_window_payload(start_at, end_at, capacity),
        make_provider_headers(provider_id)))


def issue_voucher(allocation_id, caregiver_id, authorized_hours, as_coordinator=False):
    """Issue a voucher against an OPEN allocation."""
    headers = COORD if as_coordinator else make_caregiver_headers(caregiver_id)
    return get_success_data(api_client.create_voucher(
        create_voucher_payload(allocation_id, caregiver_id, authorized_hours), headers))


def create_explicit_booking(voucher_id, caregiver_id, provider_id, window_id,
                            start_at, end_at):
    """EXPLICIT-mode booking pinned to provider + window. Lands PENDING_CONFIRMATION."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(voucher_id, caregiver_id, start_at, end_at,
                               match_mode="EXPLICIT",
                               provider_id=provider_id, window_id=window_id),
        make_caregiver_headers(caregiver_id)))


def confirm_booking(booking_id, provider_id):
    return get_success_data(api_client.confirm_booking(
        booking_id, make_provider_headers(provider_id)))


def check_in_booking(booking_id, provider_id, clock_iso, location="37.77,-122.41"):
    """Set clock then EVV check-in. Returns the OPEN VisitRecord."""
    set_clock(clock_iso)
    return get_success_data(api_client.check_in_booking(
        booking_id, {"check_in_location": location}, make_provider_headers(provider_id)))


def check_out_visit(visit_id, provider_id, clock_iso, payload=None):
    """Set clock then EVV check-out. Returns the SUBMITTED VisitRecord."""
    set_clock(clock_iso)
    return get_success_data(api_client.check_out_visit(
        visit_id, payload or {}, make_provider_headers(provider_id)))


def decide_visit(visit_id, decision, reason=None):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.create_verification_decision(visit_id, payload, COORD))


def get_claim_for_voucher(voucher_id):
    claims = get_success_data(api_client.list_claims(COORD, params={"voucher_id": voucher_id}))
    assert len(claims) == 1, f"Setup: expected exactly one claim for voucher {voucher_id}"
    return claims[0]


def submit_claim(claim_id, provider_id):
    return get_success_data(api_client.submit_claim(claim_id, make_provider_headers(provider_id)))


def adjudicate_claim(claim_id, decision, reason=None):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, ADMIN))


def pay_claim(claim_id):
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


def appeal_claim(claim_id, provider_id, reason="appeal"):
    return get_success_data(api_client.appeal_claim(
        claim_id, {"reason": reason}, make_provider_headers(provider_id)))


# ─── Composite: full verified-service chain ────────────

def setup_service_world(window_start="2026-05-04T00:00:00Z",
                        window_end="2026-05-15T00:00:00Z",
                        window_capacity=2,
                        voucher_hours=20,
                        provider_kwargs=None,
                        program_overrides=None):
    """Program + ACTIVE caregiver (80h Q2 allocation) + ACTIVE provider + window + voucher.
    Returns ctx dict with program/caregiver/application/allocation/provider/window/voucher."""
    program = create_program(**(program_overrides or {}))
    ctx = create_active_caregiver(program=program)
    provider = create_active_provider(**(provider_kwargs or {}))
    window = add_window(provider["id"], window_start, window_end, window_capacity)
    voucher = issue_voucher(ctx["allocation"]["id"], ctx["caregiver"]["id"], voucher_hours)
    ctx.update({"provider": provider, "window": window, "voucher": voucher})
    return ctx


def book_and_confirm(ctx, start_at, end_at):
    """Create EXPLICIT booking on ctx's voucher/window/provider, then provider-confirm."""
    booking = create_explicit_booking(
        ctx["voucher"]["id"], ctx["caregiver"]["id"],
        ctx["provider"]["id"], ctx["window"]["id"], start_at, end_at)
    booking = confirm_booking(booking["id"], ctx["provider"]["id"])
    ctx["booking"] = booking
    return booking


def run_visit_through_checkout(ctx, booking, check_in_clock, check_out_clock, checkout_payload=None):
    """Check in at check_in_clock, check out at check_out_clock. Returns SUBMITTED visit."""
    visit = check_in_booking(booking["id"], ctx["provider"]["id"], check_in_clock)
    visit = check_out_visit(visit["id"], ctx["provider"]["id"], check_out_clock, checkout_payload)
    ctx["visit"] = visit
    return visit


def setup_verified_service(booking_start="2026-05-04T19:00:00Z",
                           booking_end="2026-05-04T21:00:00Z",
                           check_in_clock=None,
                           check_out_clock=None,
                           window_start="2026-05-04T00:00:00Z",
                           window_end="2026-05-15T00:00:00Z",
                           window_capacity=2,
                           voucher_hours=20,
                           provider_kwargs=None,
                           program_overrides=None):
    """Full EVV chain through coordinator VERIFY.
    Returns ctx with program/caregiver/allocation/provider/window/voucher/booking/visit/claim.
    Post-state: booking COMPLETED, voucher REDEEMED, claim DRAFT."""
    ctx = setup_service_world(window_start=window_start, window_end=window_end,
                              window_capacity=window_capacity, voucher_hours=voucher_hours,
                              provider_kwargs=provider_kwargs,
                              program_overrides=program_overrides)
    booking = book_and_confirm(ctx, booking_start, booking_end)
    run_visit_through_checkout(ctx, booking,
                               check_in_clock or booking_start,
                               check_out_clock or booking_end)
    decide_visit(ctx["visit"]["id"], "VERIFY")
    ctx["claim"] = get_claim_for_voucher(ctx["voucher"]["id"])
    return ctx


def setup_submitted_claim(**kwargs):
    """Verified service + provider submits the claim. Post-state: claim SUBMITTED."""
    ctx = setup_verified_service(**kwargs)
    ctx["claim"] = submit_claim(ctx["claim"]["id"], ctx["provider"]["id"])
    return ctx


def setup_approved_claim(**kwargs):
    """Submitted claim + FunderAdmin APPROVE. Post-state: claim APPROVED."""
    ctx = setup_submitted_claim(**kwargs)
    ctx["claim"] = adjudicate_claim(ctx["claim"]["id"], "APPROVE")
    return ctx


def setup_paid_claim(**kwargs):
    """Approved claim + FunderAdmin pay. Post-state: claim PAID, voucher SETTLED."""
    ctx = setup_approved_claim(**kwargs)
    ctx["claim"] = pay_claim(ctx["claim"]["id"])
    return ctx


# ─── Composite: caregiver suspension scenario ──────────

def setup_suspension_scenario():
    """Caregiver ACTIVE; allocation 80.00 OPEN; voucher1 10.00h ISSUED;
    voucher2 10.00h COMMITTED to a CONFIRMED booking 2026-05-06 10:00-12:00
    in a capacity-1 window (window FULLY_BOOKED over that interval)."""
    program = create_program()
    ctx = create_active_caregiver(program=program)
    provider = create_active_provider()
    window = add_window(provider["id"], "2026-05-06T08:00:00Z", "2026-05-06T20:00:00Z", 1)
    cg_id = ctx["caregiver"]["id"]
    voucher1 = issue_voucher(ctx["allocation"]["id"], cg_id, 10)
    voucher2 = issue_voucher(ctx["allocation"]["id"], cg_id, 10)
    booking = create_explicit_booking(voucher2["id"], cg_id, provider["id"], window["id"],
                                      "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    booking = confirm_booking(booking["id"], provider["id"])
    ctx.update({"provider": provider, "window": window,
                "voucher1": voucher1, "voucher2": voucher2, "booking": booking})
    return ctx


# ─── Composite: emergency respite ──────────────────────

def create_triaged_emergency(caregiver_id, needed_start_at, needed_end_at,
                             approved_hours, reason="caregiver hospitalized"):
    """Create + triage an emergency request. Returns the TRIAGED request."""
    request = get_success_data(api_client.create_emergency_request(
        create_emergency_request_payload(caregiver_id, needed_start_at, needed_end_at, reason),
        make_caregiver_headers(caregiver_id)))
    request = get_success_data(api_client.triage_emergency_request(
        request["id"], {"approved_hours": approved_hours}, COORD))
    return request
