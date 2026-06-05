"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server before
each test). These helpers build the multi-step preconditions FOIA tests need —
registering actors, perfecting + assigning a request into PROCESSING, walking records
through dispositions, issuing determinations, filing/assigning appeals, opening Reverse
FOIA objections, assessing fees, and booking inspection slots.

Identity threading: all four roles are entity-backed. After creating an officer /
requester / authority / submitter we always call the matching make_<role>_headers
builder with the real id for any ownership-gated or identity-recording call.

Setup uses get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing assertion deep in a test.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_requester_headers,
    make_officer_headers,
    make_appeal_authority_headers,
    make_submitter_headers,
)
from . import factories


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ─── Bootstrap header for the very first officer ──────
# POST /officers is FoiaOfficer-exclusive; the first officer is registered by an
# acting FoiaOfficer header whose X-User-ID need not resolve to a persisted entity
# (registration is not ownership-gated). Subsequent calls use the real officer id.
def _bootstrap_officer_headers() -> dict:
    return make_officer_headers("bootstrap-officer")


# ─── Tier 0: Actor registration ───────────────────────
def create_officer(can_invoke_glomar=False, **overrides):
    """Register a FOIA officer. Returns (officer_dict, officer_headers)."""
    payload = factories.create_officer_payload(
        full_name=overrides.pop("full_name", "Officer"),
        badge_id=overrides.pop("badge_id", _uniq("BADGE")),
        can_invoke_glomar=can_invoke_glomar,
        **overrides,
    )
    resp = api_client.create_officer(payload, _bootstrap_officer_headers())
    officer = get_success_data(resp)
    return officer, make_officer_headers(officer["id"])


def create_appeal_authority(officer_headers, **overrides):
    """Register an appeal authority. Returns (authority_dict, authority_headers)."""
    payload = factories.create_appeal_authority_payload(
        full_name=overrides.pop("full_name", "Authority"),
        badge_id=overrides.pop("badge_id", _uniq("AUTH")),
        **overrides,
    )
    resp = api_client.create_appeal_authority(payload, officer_headers)
    auth = get_success_data(resp)
    return auth, make_appeal_authority_headers(auth["id"])


def create_requester(officer_headers, declared_category="OTHER", **overrides):
    """Register a requester. Returns (requester_dict, requester_headers)."""
    payload = factories.create_requester_payload(
        full_name=overrides.pop("full_name", "Requester"),
        email=overrides.pop("email", _uniq("req") + "@example.com"),
        declared_category=declared_category,
        **overrides,
    )
    resp = api_client.create_requester(payload, officer_headers)
    requester = get_success_data(resp)
    return requester, make_requester_headers(requester["id"])


def create_submitter(officer_headers, **overrides):
    """Register a third-party submitter. Returns (submitter_dict, submitter_headers)."""
    payload = factories.create_submitter_payload(
        company_name=overrides.pop("company_name", "Submitter LLC"),
        contact_email=overrides.pop("contact_email", _uniq("sub") + "@example.com"),
        **overrides,
    )
    resp = api_client.create_submitter(payload, officer_headers)
    submitter = get_success_data(resp)
    return submitter, make_submitter_headers(submitter["id"])


# ─── Tier 1: Request lifecycle progression ────────────
def submit_request(officer_headers, requester, received_at="2026-01-05T00:00:00.000Z", **overrides):
    """Submit a FOIA request (status SUBMITTED). Returns the request dict."""
    payload = factories.create_request_payload(
        requester["id"], received_at=received_at, **overrides
    )
    resp = api_client.create_request(payload, officer_headers)
    return get_success_data(resp)


def create_submitted_request(declared_category="OTHER", received_at="2026-01-05T00:00:00.000Z",
                             request_overrides=None):
    """Officer + requester + a SUBMITTED request.
    Returns (officer, officer_headers, requester, requester_headers, request)."""
    officer, off_h = create_officer()
    requester, req_h = create_requester(off_h, declared_category=declared_category)
    request = submit_request(off_h, requester, received_at=received_at, **(request_overrides or {}))
    return officer, off_h, requester, req_h, request


def perfect_request(officer_headers, request_id, fee_category="OTHER"):
    """Perfect a SUBMITTED request -> PERFECTED. Returns the updated request dict."""
    resp = api_client.perfect_request(request_id, factories.perfect_request_payload(fee_category), officer_headers)
    return get_success_data(resp)


def assign_request(officer_headers, request_id):
    """Assign a PERFECTED request -> PROCESSING. Returns the updated request dict."""
    resp = api_client.assign_request(request_id, officer_headers)
    return get_success_data(resp)


def create_processing_request(fee_category="OTHER", declared_category=None,
                              received_at="2026-01-05T00:00:00.000Z", request_overrides=None,
                              officer_can_invoke_glomar=False):
    """Full preamble to a PROCESSING request.

    Returns dict with keys: officer, officer_headers, requester, requester_headers, request.
    """
    if declared_category is None:
        declared_category = fee_category
    officer, off_h = create_officer(can_invoke_glomar=officer_can_invoke_glomar)
    requester, req_h = create_requester(off_h, declared_category=declared_category)
    request = submit_request(off_h, requester, received_at=received_at, **(request_overrides or {}))
    perfect_request(off_h, request["id"], fee_category=fee_category)
    assign_request(off_h, request["id"])
    return {
        "officer": officer,
        "officer_headers": off_h,
        "requester": requester,
        "requester_headers": req_h,
        "request": request,
    }


def current_version(officer_headers, request_id) -> int:
    """Read the request's current version."""
    resp = api_client.get_request(request_id, officer_headers)
    return get_success_data(resp)["version"]


def withdraw_request(requester_headers, request_id):
    """Owning requester withdraws the request -> WITHDRAWN. Returns the updated request dict."""
    resp = api_client.withdraw_request(request_id, requester_headers)
    return get_success_data(resp)


def extend_request(officer_headers, request_id):
    """Apply the single 10-working-day extension. Returns the updated request dict."""
    resp = api_client.extend_request(request_id, officer_headers)
    return get_success_data(resp)


# ─── Tier 2: Records, exemptions, review ───────────────
def add_record(officer_headers, request_id, title="Record", page_count=1, **overrides):
    """Log a responsive record under a request. Returns the record dict."""
    payload = factories.create_record_payload(title=title, page_count=page_count, **overrides)
    resp = api_client.create_record(request_id, payload, officer_headers)
    return get_success_data(resp)


def add_record_exemption(officer_headers, request_id, record_id, exemption_code="B5",
                         justification="statutory basis"):
    """Assert a RECORD-scoped exemption citing record_id. Returns the exemption dict."""
    payload = factories.create_exemption_payload(
        "RECORD", exemption_code, justification=justification, record_id=record_id
    )
    resp = api_client.create_exemption(request_id, payload, officer_headers)
    return get_success_data(resp)


def add_request_exemption(officer_headers, request_id, exemption_code="B1",
                          justification="national security"):
    """Assert a REQUEST-scoped (Glomar) exemption. Returns the exemption dict."""
    payload = factories.create_exemption_payload("REQUEST", exemption_code, justification=justification)
    resp = api_client.create_exemption(request_id, payload, officer_headers)
    return get_success_data(resp)


def review_record(officer_headers, record_id, disposition):
    """Set a record's disposition. Returns the updated record dict."""
    resp = api_client.review_record(record_id, factories.review_record_payload(disposition), officer_headers)
    return get_success_data(resp)


# ─── Tier 3: Fees ─────────────────────────────────────
def assess_fee(officer_headers, request_id, search_hours=0, review_hours=0, billable_pages=0,
               expected_version=None):
    """Run a fee estimate. Returns the FeeEstimate dict."""
    if expected_version is None:
        expected_version = current_version(officer_headers, request_id)
    payload = factories.create_fee_estimate_payload(
        expected_version, search_hours=search_hours, review_hours=review_hours,
        billable_pages=billable_pages,
    )
    resp = api_client.create_fee_estimate(request_id, payload, officer_headers)
    return get_success_data(resp)


def grant_fee_waiver(officer_headers, request_id, findings=(True, True, True, True), expected_version=None):
    """Adjudicate a fee waiver with the four boolean findings. Returns the request dict."""
    if expected_version is None:
        expected_version = current_version(officer_headers, request_id)
    f_pu, f_nc, f_mc, f_ad = findings
    payload = factories.fee_waiver_payload(
        expected_version, f_public_understanding=f_pu, f_not_commercial_interest=f_nc,
        f_meaningful_contribution=f_mc, f_ability_to_disseminate=f_ad,
    )
    resp = api_client.adjudicate_fee_waiver(request_id, payload, officer_headers)
    return get_success_data(resp)


def setup_awaiting_payment(declared_category="COMMERCIAL", fee_category="COMMERCIAL",
                           search_hours=6, review_hours=4, billable_pages=500,
                           received_at="2026-01-05T00:00:00.000Z"):
    """Build a request that has tolled into AWAITING_PAYMENT via an above-threshold fee.

    Returns dict: officer, officer_headers, requester, requester_headers, request, fee_estimate.
    """
    ctx = create_processing_request(
        fee_category=fee_category, declared_category=declared_category, received_at=received_at
    )
    fee = assess_fee(ctx["officer_headers"], ctx["request"]["id"],
                     search_hours=search_hours, review_hours=review_hours, billable_pages=billable_pages)
    ctx["fee_estimate"] = fee
    return ctx


def pay_request(requester_headers, request_id, amount_cents):
    """Pay the assessed advance fee. Returns the updated request dict."""
    resp = api_client.pay_request(request_id, factories.payment_payload(amount_cents), requester_headers)
    return get_success_data(resp)


# ─── Tier 4: Determinations ───────────────────────────
def issue_determination(officer_headers, request_id, expected_version=None):
    """Issue a determination (OCC-guarded). Returns the updated request dict."""
    if expected_version is None:
        expected_version = current_version(officer_headers, request_id)
    payload = factories.determination_payload(expected_version)
    resp = api_client.issue_determination(request_id, payload, officer_headers)
    return get_success_data(resp)


def setup_denied_request(num_withheld=1, exemption_code="B5", received_at="2026-01-05T00:00:00.000Z"):
    """A request driven to DENIED with `num_withheld` WITHHELD records (each cited).

    Returns dict: officer, officer_headers, requester, requester_headers, request, records.
    """
    ctx = create_processing_request(fee_category="OTHER", received_at=received_at)
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    records = []
    for i in range(num_withheld):
        rec = add_record(off_h, rid, title=f"Withheld Doc {i + 1}", page_count=1)
        add_record_exemption(off_h, rid, rec["id"], exemption_code=exemption_code)
        review_record(off_h, rec["id"], "WITHHELD")
        records.append(rec)
    issue_determination(off_h, rid)
    ctx["records"] = records
    return ctx


def setup_partially_granted_request(received_at="2026-01-05T00:00:00.000Z"):
    """A request driven to PARTIALLY_GRANTED: one RELEASABLE + one REDACTED (B7) record.

    Returns dict: officer, officer_headers, requester, requester_headers, request,
    releasable_record, redacted_record.
    """
    ctx = create_processing_request(fee_category="OTHER", received_at=received_at)
    off_h = ctx["officer_headers"]
    rid = ctx["request"]["id"]
    rec_rel = add_record(off_h, rid, title="Open doc", page_count=1)
    rec_red = add_record(off_h, rid, title="Investigatory record", page_count=6)
    add_record_exemption(off_h, rid, rec_red["id"], exemption_code="B7", justification="law enforcement")
    review_record(off_h, rec_rel["id"], "RELEASABLE")
    review_record(off_h, rec_red["id"], "REDACTED")
    issue_determination(off_h, rid)
    ctx["releasable_record"] = rec_rel
    ctx["redacted_record"] = rec_red
    return ctx


# ─── Tier 5: Appeals ──────────────────────────────────
def file_appeal(requester_headers, request_id, appellant_id, grounds="grounds",
                filed_at="2026-02-10T00:00:00.000Z"):
    """File an appeal against a determination. Returns the appeal dict."""
    payload = factories.file_appeal_payload(appellant_id, grounds=grounds, filed_at=filed_at)
    resp = api_client.file_appeal(request_id, payload, requester_headers)
    return get_success_data(resp)


def assign_appeal(authority_headers, appeal_id):
    """Authority takes up a filed appeal -> UNDER_REVIEW. Returns the appeal dict."""
    resp = api_client.assign_appeal(appeal_id, authority_headers)
    return get_success_data(resp)


def decide_appeal(authority_headers, appeal_id, decision):
    """Authority decides the appeal (AFFIRM/REVERSE/REMAND). Returns the appeal dict."""
    payload = factories.decide_appeal_payload(decision)
    resp = api_client.decide_appeal(appeal_id, payload, authority_headers)
    return get_success_data(resp)


def setup_appeal_under_review(base_ctx, filed_at="2026-02-10T00:00:00.000Z"):
    """Given a determination-state request context (must already carry an
    AppealAuthority), file an appeal and advance it to UNDER_REVIEW.

    base_ctx must contain officer_headers, requester, requester_headers, request.
    An AppealAuthority is registered here. Returns base_ctx augmented with
    authority, authority_headers, appeal.
    """
    auth, auth_h = create_appeal_authority(base_ctx["officer_headers"])
    appeal = file_appeal(
        base_ctx["requester_headers"], base_ctx["request"]["id"],
        appellant_id=base_ctx["requester"]["id"], filed_at=filed_at,
    )
    assign_appeal(auth_h, appeal["id"])
    base_ctx["authority"] = auth
    base_ctx["authority_headers"] = auth_h
    base_ctx["appeal"] = appeal
    return base_ctx


def setup_denied_appeal_under_review(num_withheld=1, exemption_code="B5"):
    """A DENIED request with `num_withheld` WITHHELD records and an UNDER_REVIEW appeal."""
    ctx = setup_denied_request(num_withheld=num_withheld, exemption_code=exemption_code)
    return setup_appeal_under_review(ctx)


def setup_partial_appeal_under_review():
    """A PARTIALLY_GRANTED request (1 RELEASABLE + 1 REDACTED) with an UNDER_REVIEW appeal."""
    ctx = setup_partially_granted_request()
    return setup_appeal_under_review(ctx)


# ─── Tier 6: Reverse FOIA objections ──────────────────
def add_submitter_record(officer_headers, request_id, submitter_id, title="Pricing", page_count=2):
    """Log a record flagged contains_submitter_info=true tied to submitter_id."""
    payload = factories.create_record_payload(
        title=title, page_count=page_count, contains_submitter_info=True, submitter_id=submitter_id
    )
    resp = api_client.create_record(request_id, payload, officer_headers)
    return get_success_data(resp)


def open_objection(officer_headers, record_id, submitter_id, objection_text="confidential"):
    """Open a Reverse-FOIA notice on a submitter-info record. Returns the objection dict."""
    payload = factories.create_objection_payload(submitter_id, objection_text=objection_text)
    resp = api_client.create_objection(record_id, payload, officer_headers)
    return get_success_data(resp)


def submitter_object(submitter_headers, objection_id):
    """Submitter formally objects -> OBJECTED. Returns the objection dict."""
    resp = api_client.object_to_disclosure(objection_id, submitter_headers)
    return get_success_data(resp)


def resolve_objection(officer_headers, objection_id, resolution):
    """Officer resolves the objection (SUSTAIN/OVERRULE). Returns the objection dict."""
    payload = factories.resolve_objection_payload(resolution)
    resp = api_client.resolve_objection(objection_id, payload, officer_headers)
    return get_success_data(resp)


def setup_objected_record(received_at="2026-01-05T00:00:00.000Z"):
    """A PROCESSING request with a submitter-info record under an OBJECTED objection.

    Returns dict: officer, officer_headers, requester, requester_headers, request,
    submitter, submitter_headers, record, objection.
    """
    ctx = create_processing_request(fee_category="OTHER", received_at=received_at)
    off_h = ctx["officer_headers"]
    submitter, sub_h = create_submitter(off_h)
    record = add_submitter_record(off_h, ctx["request"]["id"], submitter["id"])
    objection = open_objection(off_h, record["id"], submitter["id"])
    submitter_object(sub_h, objection["id"])
    ctx["submitter"] = submitter
    ctx["submitter_headers"] = sub_h
    ctx["record"] = record
    ctx["objection"] = objection
    return ctx


# ─── Tier 7: Inspection facilities & bookings ─────────
def create_reading_room(officer_headers, capacity=1, name="Reading Room"):
    """Register a reading room. Returns the room dict."""
    payload = factories.create_reading_room_payload(name=name, capacity=capacity)
    resp = api_client.create_reading_room(payload, officer_headers)
    return get_success_data(resp)


def create_review_station(officer_headers, buffer_minutes=0, name="Review Station"):
    """Register a review station. Returns the station dict."""
    payload = factories.create_review_station_payload(name=name, buffer_minutes=buffer_minutes)
    resp = api_client.create_review_station(payload, officer_headers)
    return get_success_data(resp)


def book_reading_room(officer_headers, room_id, request_id, starts_at, ends_at):
    """Create a reading-room booking. Returns the booking dict."""
    payload = factories.booking_payload(request_id, starts_at, ends_at)
    resp = api_client.create_reading_room_booking(room_id, payload, officer_headers)
    return get_success_data(resp)


def book_review_station(officer_headers, station_id, request_id, starts_at, ends_at):
    """Create a review-station booking. Returns the booking dict."""
    payload = factories.booking_payload(request_id, starts_at, ends_at)
    resp = api_client.create_review_station_booking(station_id, payload, officer_headers)
    return get_success_data(resp)


def setup_reading_room_with_booking(capacity=1, starts_at="2026-03-02T10:00:00.000Z",
                                    ends_at="2026-03-02T11:00:00.000Z"):
    """A reading room (given capacity) holding one booking [starts_at, ends_at).

    Returns dict: officer, officer_headers, requester, request, room, booking.
    """
    ctx = create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    room = create_reading_room(off_h, capacity=capacity)
    booking = book_reading_room(off_h, room["id"], ctx["request"]["id"], starts_at, ends_at)
    ctx["room"] = room
    ctx["booking"] = booking
    return ctx


def setup_review_station_with_booking(buffer_minutes=15, starts_at="2026-03-02T13:00:00.000Z",
                                      ends_at="2026-03-02T14:00:00.000Z"):
    """A review station (given buffer) holding one booking [starts_at, ends_at].

    Returns dict: officer, officer_headers, requester, request, station, booking.
    """
    ctx = create_processing_request(fee_category="OTHER")
    off_h = ctx["officer_headers"]
    station = create_review_station(off_h, buffer_minutes=buffer_minutes)
    booking = book_review_station(off_h, station["id"], ctx["request"]["id"], starts_at, ends_at)
    ctx["station"] = station
    ctx["booking"] = booking
    return ctx


# ─── Tier 8: Clock helper ─────────────────────────────
def set_clock(officer_headers, to_iso8601):
    """Set the server's notion of 'now'."""
    resp = api_client.set_clock(factories.clock_payload(to_iso8601), officer_headers)
    # The clock endpoint returns 200 with no data; accept any 2xx.
    assert 200 <= resp.status_code < 300, f"set_clock failed: {resp.status_code} {resp.text}"
    return resp
