"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints and
uses the lenient get_success_data validator, so a broken setup surfaces as a clear
"Setup failed" rather than a confusing assertion error. The API server database is empty
at the start of every test, so nothing is carried over between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    production_company_payload, department_payload, officer_payload,
    street_segment_payload, application_payload, location_detail_payload,
    insurance_certificate_payload, rider_payload, road_closure_booking_payload,
    officer_assignment_payload, notification_payload, payment_payload,
)
from .test_users import (
    make_coordinator_headers, make_production_company_headers,
    make_department_reviewer_headers, make_field_officer_headers,
)

COORD = make_coordinator_headers()

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Atomic step helpers                                                          #
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, COORD))


def make_company(api, **overrides) -> dict:
    return get_success_data(api.create_production_company(production_company_payload(**overrides), COORD))


def make_department(api, **overrides) -> dict:
    return get_success_data(api.create_department(department_payload(**overrides), COORD))


def make_officer(api, **overrides) -> dict:
    return get_success_data(api.create_officer(officer_payload(**overrides), COORD))


def make_segment(api, **overrides) -> dict:
    return get_success_data(api.create_street_segment(street_segment_payload(**overrides), COORD))


def make_application(api, pc_id, **overrides) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.create_application(application_payload(pc_id, **overrides), hdr))


def add_location(api, app_id, pc_id, **overrides) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.add_location_detail(app_id, location_detail_payload(**overrides), hdr))


def current_version(api, app_id) -> int:
    return get_success_data(api.get_application(app_id, COORD))["version"]


def add_coi(api, app_id, pc_id, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = current_version(api, app_id)
    hdr = make_production_company_headers(pc_id)
    return get_success_data(
        api.submit_insurance_certificate(app_id, insurance_certificate_payload(expected_version, **overrides), hdr)
    )


def verify_coi(api, coi_id, decision="VERIFY") -> dict:
    return get_success_data(api.verify_insurance_certificate(coi_id, {"decision": decision}, COORD))


def submit_app(api, app_id, pc_id) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.submit_application(app_id, {}, hdr))


def get_review(api, app_id, dept_id) -> dict:
    data = get_success_data(api.list_department_reviews(COORD, params={"application_id": app_id, "department_id": dept_id}))
    assert data, f"no DepartmentReview found for app {app_id} / dept {dept_id}"
    return data[0]


def decide_review(api, review_id, dept_id, decision, notes=None) -> dict:
    hdr = make_department_reviewer_headers(dept_id)
    payload = {"decision": decision}
    if notes is not None:
        payload["decision_notes"] = notes
    return get_success_data(api.decide_department_review(review_id, payload, hdr))


def add_rider(api, app_id, pc_id, rider_type, **overrides) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.add_rider(app_id, rider_payload(rider_type, **overrides), hdr))


def decide_rider(api, rider_id, decision) -> dict:
    return get_success_data(api.decide_rider(rider_id, {"decision": decision}, COORD))


def add_booking(api, app_id, pc_id, segment_id, **overrides) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(
        api.create_road_closure_booking(road_closure_booking_payload(app_id, segment_id, **overrides), hdr)
    )


def add_assignment(api, app_id, officer_id, **overrides) -> dict:
    return get_success_data(
        api.create_officer_assignment(officer_assignment_payload(app_id, officer_id, **overrides), COORD)
    )


def pay(api, app_id, pc_id, entry_type, amount_cents) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.create_payment(app_id, payment_payload(entry_type, amount_cents), hdr))


def issue_app(api, app_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = current_version(api, app_id)
    return get_success_data(api.issue_application(app_id, {"expected_application_version": expected_version}, COORD))


def wrap_request(api, app_id, pc_id) -> dict:
    hdr = make_production_company_headers(pc_id)
    return get_success_data(api.wrap_request_application(app_id, {}, hdr))


def wrap_close(api, app_id, officer_id, **payload) -> dict:
    hdr = make_field_officer_headers(officer_id)
    return get_success_data(api.wrap_close_application(app_id, payload, hdr))


def read_booking(api, booking_id) -> dict:
    return get_success_data(api.get_road_closure_booking(booking_id, COORD))


def read_assignment(api, assignment_id) -> dict:
    return get_success_data(api.get_officer_assignment(assignment_id, COORD))


def read_review(api, review_id) -> dict:
    return get_success_data(api.get_department_review(review_id, COORD))


def read_company(api, pc_id) -> dict:
    return get_success_data(api.get_production_company(pc_id, COORD))


# --------------------------------------------------------------------------- #
# Composite scenarios                                                          #
# --------------------------------------------------------------------------- #
def setup_under_review_single_review(api, clock=DEFAULT_CLOCK, company_name="Rev Co",
                                     with_coi=False, aviation=False, verify=False,
                                     app_overrides=None):
    """Company + POLICE(ALL) department + DRAFT application (1 location) submitted to
    UNDER_REVIEW, with one PENDING DepartmentReview. Optionally attaches (and verifies)
    a COI before submit. Returns a context dict."""
    set_clock(api, clock)
    pc = make_company(api, legal_name=company_name, contact_email=f"{company_name.replace(' ', '')}@x.test",
                      primary_contact="PC")
    dept = make_department(api)
    app = make_application(api, pc["id"], **(app_overrides or {}))
    add_location(api, app["id"], pc["id"])
    coi = None
    if with_coi:
        coi = add_coi(api, app["id"], pc["id"], aviation_coverage=aviation)
        if verify:
            verify_coi(api, coi["id"])
    submit_app(api, app["id"], pc["id"])
    review = get_review(api, app["id"], dept["id"])
    return {"pc_id": pc["id"], "dept_id": dept["id"], "app_id": app["id"],
            "coi_id": coi["id"] if coi else None, "review_id": review["id"]}


def setup_issue_ready(api, clock=DEFAULT_CLOCK, company_name="Iss Co",
                      approve_review=True, with_verified_coi=True, pay_fee=True,
                      fee_cents=41200, app_overrides=None):
    """Minimal no-flag application (crew 5, one shoot day) walked to a state where issuance
    can be triggered: submitted, POLICE(ALL) review APPROVED, COI VERIFIED, permit fee paid.
    Toggle the flags to build the negative-precondition variants. Returns a context dict
    including a fresh `issue_version`."""
    ctx = setup_under_review_single_review(api, clock=clock, company_name=company_name,
                                           with_coi=with_verified_coi, aviation=False,
                                           verify=with_verified_coi, app_overrides=app_overrides)
    if approve_review:
        decide_review(api, ctx["review_id"], ctx["dept_id"], "APPROVE")
    if pay_fee:
        pay(api, ctx["app_id"], ctx["pc_id"], "PERMIT_FEE", fee_cents)
    ctx["issue_version"] = current_version(api, ctx["app_id"])
    return ctx


def setup_issued_application(api, clock=DEFAULT_CLOCK, company_name="Issued Co",
                            fee_cents=41200):
    """Full path to ISSUED for a minimal no-flag application (estimate 41200, deposit 8240)."""
    ctx = setup_issue_ready(api, clock=clock, company_name=company_name, fee_cents=fee_cents)
    issued = issue_app(api, ctx["app_id"], ctx["issue_version"])
    ctx["issued"] = issued
    ctx["deposit_cents"] = issued["deposit_cents"]
    return ctx


def setup_wrap_requested_application(api, clock=DEFAULT_CLOCK, company_name="Wrap Co",
                                     deposit_amount=8240):
    """ISSUED application + DEPOSIT paid + wrap requested. Creates an Officer whose id can act
    as the FieldOfficer for wrap-close. Returns a context dict with `officer_id`."""
    ctx = setup_issued_application(api, clock=clock, company_name=company_name)
    officer = make_officer(api)
    pay(api, ctx["app_id"], ctx["pc_id"], "DEPOSIT", deposit_amount)
    wrap_request(api, ctx["app_id"], ctx["pc_id"])
    ctx["officer_id"] = officer["id"]
    return ctx


# ---- Road-closure / cascade scenarios (two applications sharing one segment) ---- #
def _issue_ready_app_with_booking(api, pc_id, dept_id, seg_id,
                                  closure_start, closure_end, fee_cents, title="A1"):
    """Company-agnostic helper: an application (crew 5, road closure, 14h shoot day) walked
    to issue-ready with one PENDING booking. Returns app, booking, and a fresh issue_version."""
    app = make_application(api, pc_id, title=title,
                           shoot_start_at="2026-06-01T06:00:00Z",
                           shoot_end_at="2026-06-01T20:00:00Z",
                           crew_size=5, requires_road_closure=True)
    add_location(api, app["id"], pc_id,
                 requested_start_at="2026-06-01T06:00:00Z",
                 requested_end_at="2026-06-01T20:00:00Z", uses_road_closure=True)
    coi = add_coi(api, app["id"], pc_id)
    verify_coi(api, coi["id"])
    booking = add_booking(api, app["id"], pc_id, seg_id,
                          closure_start_at=closure_start, closure_end_at=closure_end)
    submit_app(api, app["id"], pc_id)
    review = get_review(api, app["id"], dept_id)
    decide_review(api, review["id"], dept_id, "APPROVE")
    pay(api, app["id"], pc_id, "PERMIT_FEE", fee_cents)
    return {"app": app, "booking": booking, "issue_version": current_version(api, app["id"])}


def _under_review_app_with_booking(api, pc_id, dept_id, seg_id,
                                   closure_start, closure_end, title="A2",
                                   officer_id=None, shift=None):
    """An application walked to UNDER_REVIEW with one PENDING booking, and optionally a
    PROPOSED officer assignment. Returns app, booking, and optional assignment."""
    app = make_application(api, pc_id, title=title,
                           shoot_start_at="2026-06-01T06:00:00Z",
                           shoot_end_at="2026-06-01T20:00:00Z",
                           crew_size=5, requires_road_closure=True)
    add_location(api, app["id"], pc_id,
                 requested_start_at="2026-06-01T06:00:00Z",
                 requested_end_at="2026-06-01T20:00:00Z", uses_road_closure=True)
    booking = add_booking(api, app["id"], pc_id, seg_id,
                          closure_start_at=closure_start, closure_end_at=closure_end)
    submit_app(api, app["id"], pc_id)
    assignment = None
    if officer_id is not None:
        s_start, s_end = shift or ("2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z")
        assignment = add_assignment(api, app["id"], officer_id,
                                    shift_start_at=s_start, shift_end_at=s_end)
    return {"app": app, "booking": booking, "assignment": assignment}


def setup_issue_cascade_scenario(api, clock=DEFAULT_CLOCK):
    """Two companies sharing one segment. app1 is issue-ready with booking B1 [08:00,12:00);
    app2 is UNDER_REVIEW with booking B2 [09:00,11:00) and a PROPOSED officer assignment.
    Issuing app1 (the caller's trigger) drives the depth-3 cascade."""
    set_clock(api, clock)
    pc1 = make_company(api, legal_name="PC One", contact_email="1@x.test", primary_contact="A")
    pc2 = make_company(api, legal_name="PC Two", contact_email="2@x.test", primary_contact="B")
    dept = make_department(api)
    officer = make_officer(api, full_name="Ofc Vega", badge_number="B-9")
    seg = make_segment(api, segment_code="MAIN-1", name="Main 1", length_m=100)
    a1 = _issue_ready_app_with_booking(api, pc1["id"], dept["id"], seg["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z", 82400, title="A1")
    a2 = _under_review_app_with_booking(api, pc2["id"], dept["id"], seg["id"],
                                        "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z", title="A2",
                                        officer_id=officer["id"],
                                        shift=("2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z"))
    return {
        "app1_id": a1["app"]["id"], "issue_version": a1["issue_version"], "b1_id": a1["booking"]["id"],
        "app2_id": a2["app"]["id"], "b2_id": a2["booking"]["id"], "oa2_id": a2["assignment"]["id"],
        "seg_id": seg["id"], "officer_id": officer["id"],
    }


def setup_confirmed_booking_on_segment(api, clock=DEFAULT_CLOCK):
    """app1 ISSUED with booking B1 [08:00,12:00) CONFIRMED on a segment; app2 UNDER_REVIEW with
    no booking yet. Used to test the buffer-expanded segment double-booking rule."""
    set_clock(api, clock)
    pc1 = make_company(api, legal_name="P8a1", contact_email="8a1@x.test", primary_contact="J")
    pc2 = make_company(api, legal_name="P8a2", contact_email="8a2@x.test", primary_contact="K")
    dept = make_department(api)
    seg = make_segment(api, segment_code="BUF-1", name="Buf 1", length_m=100)
    a1 = _issue_ready_app_with_booking(api, pc1["id"], dept["id"], seg["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z", 82400, title="P8a1")
    issue_app(api, a1["app"]["id"], a1["issue_version"])
    app2 = make_application(api, pc2["id"], title="P8a2",
                            shoot_start_at="2026-06-01T06:00:00Z",
                            shoot_end_at="2026-06-01T20:00:00Z",
                            crew_size=5, requires_road_closure=True)
    add_location(api, app2["id"], pc2["id"],
                 requested_start_at="2026-06-01T06:00:00Z",
                 requested_end_at="2026-06-01T20:00:00Z", uses_road_closure=True)
    submit_app(api, app2["id"], pc2["id"])
    return {"pc2_id": pc2["id"], "app2_id": app2["id"], "seg_id": seg["id"], "b1_id": a1["booking"]["id"]}


def setup_block_restore_scenario(api, clock=DEFAULT_CLOCK):
    """app1 ISSUED so B1 [08:00,12:00) CONFIRMED and app2's B2 [09:00,11:00) BLOCKED on the
    shared segment. Withdrawing app1 (caller's trigger) restores B2. Returns b1/b2 ids."""
    set_clock(api, clock)
    pc1 = make_company(api, legal_name="P9b1", contact_email="9b1@x.test", primary_contact="N")
    pc2 = make_company(api, legal_name="P9b2", contact_email="9b2@x.test", primary_contact="O")
    dept = make_department(api)
    seg = make_segment(api, segment_code="CONS-1", name="Cons 1", length_m=100)
    a1 = _issue_ready_app_with_booking(api, pc1["id"], dept["id"], seg["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z", 82400, title="P9b1")
    a2 = _under_review_app_with_booking(api, pc2["id"], dept["id"], seg["id"],
                                        "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z", title="P9b2")
    issue_app(api, a1["app"]["id"], a1["issue_version"])
    return {"pc1_id": pc1["id"], "app1_id": a1["app"]["id"],
            "b1_id": a1["booking"]["id"], "b2_id": a2["booking"]["id"], "seg_id": seg["id"]}


def setup_dual_variant_fee_scenario(api, clock=DEFAULT_CLOCK):
    """The cost-accounting dual-variant setup: crew 40, 3 shoot days, road closure + parking,
    one PENDING booking, a DRONE rider (later APPROVED) and a STILL_PHOTO rider (later DENIED),
    a VERIFIED aviation COI, permit fee 204750 paid. Walked to the point where issuance can be
    triggered. Returns the app id, pc id, and a fresh issue_version."""
    set_clock(api, clock)
    pc = make_company(api, legal_name="Acme Films", contact_email="ops@acme.test", primary_contact="Pat Lee")
    dept = make_department(api)
    seg = make_segment(api, segment_code="MAIN-100", name="Main St 100", length_m=120)
    app = make_application(api, pc["id"], title="Night Shoot", synopsis="City scene",
                           shoot_start_at="2026-06-01T08:00:00Z",
                           shoot_end_at="2026-06-03T20:00:00Z",
                           crew_size=40, requires_road_closure=True, requires_parking=True)
    add_location(api, app["id"], pc["id"], address="100 Main St",
                 requested_start_at="2026-06-01T08:00:00Z",
                 requested_end_at="2026-06-03T20:00:00Z", uses_road_closure=True)
    coi = add_coi(api, app["id"], pc["id"], policy_number="POL-1",
                  coverage_amount_cents=100000000, aviation_coverage=True)
    verify_coi(api, coi["id"])
    drone = add_rider(api, app["id"], pc["id"], "DRONE", faa_waiver_number="FAA-1",
                      max_altitude_ft=200, flight_start_at="2026-06-01T09:00:00Z",
                      flight_end_at="2026-06-01T12:00:00Z")
    still = add_rider(api, app["id"], pc["id"], "STILL_PHOTO")
    booking = add_booking(api, app["id"], pc["id"], seg["id"],
                          closure_start_at="2026-06-01T08:00:00Z", closure_end_at="2026-06-01T18:00:00Z")
    submit_app(api, app["id"], pc["id"])
    review = get_review(api, app["id"], dept["id"])
    decide_review(api, review["id"], dept["id"], "APPROVE")
    decide_rider(api, drone["id"], "APPROVE")
    decide_rider(api, still["id"], "DENY")
    pay(api, app["id"], pc["id"], "PERMIT_FEE", 204750)
    return {"pc_id": pc["id"], "app_id": app["id"], "seg_id": seg["id"],
            "booking_id": booking["id"], "issue_version": current_version(api, app["id"])}
