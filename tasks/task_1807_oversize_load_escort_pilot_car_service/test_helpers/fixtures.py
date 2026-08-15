"""Composite setup helpers — multi-step scenario builders used by the tests.

Every helper builds its preconditions from scratch against a freshly restarted
server and returns plain dicts parsed from success envelopes. Setup calls use
the lenient get_success_data validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.
"""
from datetime import datetime

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_BASE
from .factories import (
    create_carrier_payload,
    create_escort_payload,
    create_job_payload,
    create_permit_payload,
    submit_survey_payload,
    decide_survey_payload,
    create_assignment_payload,
    create_delay_event_payload,
    create_incident_payload,
    assess_incident_payload,
    clock_payload,
    leg_spec,
)
from .test_users import (
    TEST_USERS,
    make_carrier_rep_headers,
    make_escort_operator_headers,
    make_billing_clerk_headers,
    make_safety_manager_headers,
    make_finance_manager_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SURVEYOR = TEST_USERS["route_surveyor_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def parse_ts(ts: str) -> datetime:
    """Parse a three-fractional-digit UTC timestamp from the API."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(clock_payload(to_iso8601), DISPATCHER)
    return get_success_data(resp)


def register_carrier(credit_limit_cents=10_000_000, carrier_name="Test Carrier") -> dict:
    resp = api_client.create_carrier(
        create_carrier_payload(carrier_name=carrier_name, credit_limit_cents=credit_limit_cents),
        DISPATCHER,
    )
    return get_success_data(resp)


def register_escort(
    certified_state_codes=("TX",),
    operator_name="Test Rider",
    has_height_pole=None,
    height_pole_max_inches=None,
) -> dict:
    overrides = {}
    if has_height_pole is not None:
        overrides["has_height_pole"] = has_height_pole
    if height_pole_max_inches is not None:
        overrides["height_pole_max_inches"] = height_pole_max_inches
    resp = api_client.create_escort(
        create_escort_payload(
            operator_name=operator_name,
            certified_state_codes=list(certified_state_codes),
            **overrides,
        ),
        DISPATCHER,
    )
    return get_success_data(resp)


def read_escort(escort_id: str) -> dict:
    """Read one escort via the roster listing (no single-get endpoint exists)."""
    offset = 0
    while True:
        resp = api_client.list_escorts(DISPATCHER, params={"limit": 100, "offset": offset})
        rows, meta = validate_paginated(resp)
        for row in rows:
            if row["id"] == escort_id:
                return row
        if not meta.get("has_more"):
            break
        offset += meta.get("limit", 100)
    raise AssertionError(f"Setup failed: escort {escort_id} not present in roster")


def get_carrier(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, DISPATCHER))


def get_job(job_id: str) -> dict:
    return get_success_data(api_client.get_job(job_id, DISPATCHER))


def get_leg(leg_id: str) -> dict:
    return get_success_data(api_client.get_leg(leg_id, DISPATCHER))


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, DISPATCHER))


def get_survey(survey_id: str) -> dict:
    return get_success_data(api_client.get_survey(survey_id, DISPATCHER))


def get_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident(incident_id, DISPATCHER))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, DISPATCHER))


def list_job_legs(job_id: str) -> list:
    rows, _ = validate_paginated(api_client.list_job_legs(job_id, DISPATCHER))
    return rows


def list_leg_assignments(leg_id: str) -> list:
    rows, _ = validate_paginated(api_client.list_leg_assignments(leg_id, DISPATCHER))
    return rows


def create_tx_job(
    carrier: dict,
    *,
    load_description="Test load",
    width_inches=170,
    height_inches=150,
    length_inches=600,
    gross_weight_lbs=150000,
    window_start_at="2026-08-10T09:00:00Z",
    window_end_at="2026-08-10T13:00:00Z",
    legs=None,
    state_code="TX",
    distance_miles=120,
    planned_entry_at=None,
    planned_exit_at=None,
    map_min_clearance_inches=180,
) -> dict:
    """Create a DRAFT job as the owning CarrierRep. Returns the job row."""
    if legs is None:
        legs = [
            leg_spec(
                state_code=state_code,
                distance_miles=distance_miles,
                planned_entry_at=planned_entry_at or window_start_at,
                planned_exit_at=planned_exit_at or window_end_at,
                map_min_clearance_inches=map_min_clearance_inches,
            )
        ]
    payload = create_job_payload(
        carrier["id"],
        load_description=load_description,
        width_inches=width_inches,
        height_inches=height_inches,
        length_inches=length_inches,
        gross_weight_lbs=gross_weight_lbs,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        legs=legs,
    )
    resp = api_client.create_job(payload, make_carrier_rep_headers(carrier["id"]))
    return get_success_data(resp)


def quote_job(job_id: str) -> dict:
    return get_success_data(api_client.quote_job(job_id, DISPATCHER))


def accept_quote(job_id: str, carrier: dict) -> dict:
    return get_success_data(api_client.accept_quote(job_id, make_carrier_rep_headers(carrier["id"])))


def add_permit(
    leg_id: str,
    *,
    permit_number="TX-P-1",
    valid_from="2026-08-09T00:00:00Z",
    valid_until="2026-08-12T00:00:00Z",
    holiday_closure_dates=None,
) -> dict:
    payload = create_permit_payload(
        permit_number=permit_number, valid_from=valid_from, valid_until=valid_until
    )
    if holiday_closure_dates is not None:
        payload["holiday_closure_dates"] = holiday_closure_dates
    return get_success_data(api_client.create_permit(leg_id, payload, DISPATCHER))


def issue_permit(permit_id: str) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, DISPATCHER))


def request_survey(leg_id: str) -> dict:
    return get_success_data(api_client.request_route_survey(leg_id, SURVEYOR))


def submit_survey(survey_id: str, surveyed_min_clearance_inches: int, obstructions=None) -> dict:
    return get_success_data(
        api_client.submit_survey(
            survey_id, submit_survey_payload(surveyed_min_clearance_inches, obstructions), SURVEYOR
        )
    )


def decide_survey(survey_id: str, leg_id: str, outcome="ACCEPTED", rejection_reason=None) -> dict:
    """Decide a survey, fetching the leg's current version for the OCC guard."""
    leg = get_leg(leg_id)
    payload = decide_survey_payload(leg["version"], outcome)
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.decide_survey(survey_id, payload, SAFETY))


def accept_survey_with_clearance(leg_id: str, surveyed_min_clearance_inches: int) -> dict:
    """Request + submit + accept a survey in one shot. Returns the survey."""
    survey = request_survey(leg_id)
    submit_survey(survey["id"], surveyed_min_clearance_inches)
    return decide_survey(survey["id"], leg_id, "ACCEPTED")


def confirm_police(leg_id: str) -> dict:
    return get_success_data(api_client.confirm_police(leg_id, DISPATCHER))


def offer_assignment(leg_id: str, position="REAR", escort_id=None) -> dict:
    return get_success_data(
        api_client.create_assignment(leg_id, create_assignment_payload(position, escort_id), DISPATCHER)
    )


def accept_assignment(assignment: dict, escort_id: str) -> dict:
    return get_success_data(
        api_client.accept_assignment(assignment["id"], make_escort_operator_headers(escort_id))
    )


def release_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.release_assignment(assignment_id, DISPATCHER))


def check_in(assignment_id: str, escort_id: str) -> dict:
    return get_success_data(
        api_client.create_checkin(assignment_id, make_escort_operator_headers(escort_id))
    )


def schedule_job(job_id: str) -> dict:
    return get_success_data(api_client.schedule_job(job_id, DISPATCHER))


def depart_job(job_id: str) -> dict:
    return get_success_data(api_client.depart_job(job_id, DISPATCHER))


def deliver_job(job_id: str) -> dict:
    return get_success_data(api_client.deliver_job(job_id, DISPATCHER))


def hold_job(job_id: str) -> dict:
    return get_success_data(api_client.hold_job(job_id, DISPATCHER))


def resume_job(job_id: str) -> dict:
    return get_success_data(api_client.resume_job(job_id, DISPATCHER))


def cancel_job(job_id: str, carrier: dict = None) -> dict:
    headers = make_carrier_rep_headers(carrier["id"]) if carrier is not None else DISPATCHER
    return get_success_data(api_client.cancel_job(job_id, headers))


def open_delay(job_id: str, cause: str, started_at: str, escort_id: str = None) -> dict:
    headers = make_escort_operator_headers(escort_id) if escort_id is not None else DISPATCHER
    return get_success_data(
        api_client.create_delay_event(job_id, create_delay_event_payload(cause, started_at), headers)
    )


def close_delay(delay_event_id: str, escort_id: str = None) -> dict:
    headers = make_escort_operator_headers(escort_id) if escort_id is not None else DISPATCHER
    return get_success_data(api_client.close_delay_event(delay_event_id, headers))


def report_incident(
    job_id: str,
    *,
    incident_type="PROPERTY_DAMAGE",
    description="Incident under test",
    claimed_amount_cents=100000,
    assignment_id=None,
    reporter_user_id="disp-1",
    reporter_role="Dispatcher",
) -> dict:
    payload = create_incident_payload(
        incident_type=incident_type,
        description=description,
        claimed_amount_cents=claimed_amount_cents,
        assignment_id=assignment_id,
    )
    headers = {"X-User-ID": reporter_user_id, "X-User-Role": reporter_role, "Content-Type": "application/json"}
    return get_success_data(api_client.create_incident(job_id, payload, headers))


def assess_incident(incident_id: str, escort_fault_share_pct: int, assessor_user_id="sm-1", assessor_role="SafetyManager") -> dict:
    headers = {"X-User-ID": assessor_user_id, "X-User-Role": assessor_role, "Content-Type": "application/json"}
    return get_success_data(
        api_client.assess_incident(incident_id, assess_incident_payload(escort_fault_share_pct), headers)
    )


def dispute_incident(incident_id: str, carrier: dict) -> dict:
    return get_success_data(
        api_client.dispute_incident(incident_id, make_carrier_rep_headers(carrier["id"]))
    )


def settle_incident(incident_id: str) -> dict:
    return get_success_data(api_client.settle_incident(incident_id, FINANCE))


def generate_invoice(job_id: str, clerk_user_id="bc-1") -> dict:
    return get_success_data(api_client.create_invoice(job_id, make_billing_clerk_headers(clerk_user_id)))


def finalize_invoice(invoice_id: str, clerk_user_id="bc-2") -> dict:
    return get_success_data(api_client.finalize_invoice(invoice_id, make_billing_clerk_headers(clerk_user_id)))


def dispute_invoice(invoice_id: str, carrier: dict, reason="Disputed amount") -> dict:
    return get_success_data(
        api_client.dispute_invoice(invoice_id, {"dispute_reason": reason}, make_carrier_rep_headers(carrier["id"]))
    )


def adjust_invoice(invoice_id: str, delta_cents: int, note="Adjustment", clerk_user_id="bc-2") -> dict:
    return get_success_data(
        api_client.adjust_invoice(
            invoice_id,
            {"adjustment_delta_cents": delta_cents, "adjustment_note": note},
            make_billing_clerk_headers(clerk_user_id),
        )
    )


def record_payment(invoice_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.record_payment(invoice_id, {"amount_cents": amount_cents}, FINANCE))


# ---------------------------------------------------------------------------
# Composite scenario builders
# ---------------------------------------------------------------------------

def setup_booked_job(
    carrier=None,
    *,
    credit_limit_cents=10_000_000,
    width_inches=170,
    height_inches=150,
    gross_weight_lbs=150000,
    distance_miles=120,
    window_start_at="2026-08-10T09:00:00Z",
    window_end_at="2026-08-10T13:00:00Z",
    planned_entry_at=None,
    planned_exit_at=None,
    map_min_clearance_inches=180,
    state_code="TX",
    load_description="Test load",
    clock_base=CLOCK_BASE,
) -> dict:
    """Carrier + job quoted and accepted (BOOKED). Returns a bundle dict.

    `clock_base` pins the logical clock before booking; in scenarios that build
    a second job after time has already advanced, pass a base at or after the
    current clock so the clock never moves backward.
    """
    carrier = carrier or register_carrier(credit_limit_cents)
    set_clock(clock_base)
    job = create_tx_job(
        carrier,
        load_description=load_description,
        width_inches=width_inches,
        height_inches=height_inches,
        gross_weight_lbs=gross_weight_lbs,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        state_code=state_code,
        distance_miles=distance_miles,
        planned_entry_at=planned_entry_at,
        planned_exit_at=planned_exit_at,
        map_min_clearance_inches=map_min_clearance_inches,
    )
    legs = list_job_legs(job["id"])
    quote_job(job["id"])
    job = accept_quote(job["id"], carrier)
    return {"carrier": carrier, "job": job, "legs": legs, "leg": legs[0]}


def advance_to_cleared(bundle: dict, *, survey_clearance=None, permit_kwargs=None, confirm_police_flag=None) -> dict:
    """Booked bundle -> leg CLEARED + job CLEARED.

    Issues a permit; when survey_clearance is provided (i.e. the leg requires a
    survey), runs a passing survey; confirms police when the leg requires it
    (or when confirm_police_flag is explicitly True).
    """
    leg = bundle["leg"]
    permit_kwargs = permit_kwargs or {}
    permit = add_permit(leg["id"], **permit_kwargs)
    permit = issue_permit(permit["id"])
    bundle["permit"] = permit
    survey = None
    if survey_clearance is not None:
        survey = accept_survey_with_clearance(leg["id"], survey_clearance)
        bundle["survey"] = survey
    leg_now = get_leg(leg["id"])
    if confirm_police_flag is None:
        confirm_police_flag = bool(leg_now.get("requires_police_escort"))
    if confirm_police_flag:
        confirm_police(leg["id"])
    bundle["leg"] = get_leg(leg["id"])
    bundle["job"] = get_job(bundle["job"]["id"])
    return bundle


def offer_and_accept(bundle: dict, escort: dict, position="REAR", leg=None) -> dict:
    leg = leg or bundle["leg"]
    assignment = offer_assignment(leg["id"], position, escort["id"])
    assignment = accept_assignment(assignment, escort["id"])
    bundle.setdefault("assignments", []).append(assignment)
    return assignment


def advance_to_scheduled(bundle: dict) -> dict:
    bundle["job"] = schedule_job(bundle["job"]["id"])
    return bundle


def advance_to_en_route(bundle: dict, at="2026-08-10T09:00:00Z") -> dict:
    set_clock(at)
    bundle["job"] = depart_job(bundle["job"]["id"])
    bundle["assignments"] = [get_assignment(a["id"]) for a in bundle.get("assignments", [])]
    return bundle


def advance_to_delivered(bundle: dict, at="2026-08-10T10:00:00Z", checkin_at=None) -> dict:
    if checkin_at is not None:
        set_clock(checkin_at)
        for a in bundle.get("assignments", []):
            check_in(a["id"], a["escort_id"])
    set_clock(at)
    bundle["job"] = deliver_job(bundle["job"]["id"])
    bundle["assignments"] = [get_assignment(a["id"]) for a in bundle.get("assignments", [])]
    bundle["leg"] = get_leg(bundle["leg"]["id"])
    return bundle


def setup_delivered_rear_job(
    *,
    width_inches=170,
    height_inches=150,
    gross_weight_lbs=150000,
    distance_miles=120,
    carrier_credit=10_000_000,
    survey_clearance=None,
    depart_at="2026-08-10T09:00:00Z",
    checkin_at=None,
    deliver_at="2026-08-10T10:00:00Z",
    escort_name="Test Rider",
    map_min_clearance_inches=180,
) -> dict:
    """Full spine: carrier + TX escort + one-position TX job carried to
    DELIVERED. Default movement is 60 minutes (09:00 -> 10:00)."""
    carrier = register_carrier(carrier_credit)
    escort = register_escort(("TX",), escort_name)
    bundle = setup_booked_job(
        carrier,
        width_inches=width_inches,
        height_inches=height_inches,
        gross_weight_lbs=gross_weight_lbs,
        distance_miles=distance_miles,
        map_min_clearance_inches=map_min_clearance_inches,
    )
    bundle["escort"] = escort
    advance_to_cleared(bundle, survey_clearance=survey_clearance)
    offer_and_accept(bundle, escort, "REAR")
    advance_to_scheduled(bundle)
    advance_to_en_route(bundle, depart_at)
    advance_to_delivered(bundle, deliver_at, checkin_at)
    return bundle


def setup_delivered_superload_tx(*, with_delay=False) -> dict:
    """Delivered one-leg TX superload (width 195 / height 180 / 250,000 lbs):
    two pole-equipped FRONT escorts + one REAR escort, police coordination,
    passing survey at 190 inches. Movement 09:00 -> 13:30 (270 min -> 4.5h).
    """
    carrier = register_carrier(10_000_000, "Superload Carrier")
    esc_f1 = register_escort(("TX",), "Pole One", True, 192)
    esc_f2 = register_escort(("TX",), "Pole Two", True, 192)
    esc_r = register_escort(("TX",), "Rear Plain")
    bundle = setup_booked_job(
        carrier,
        width_inches=195,
        height_inches=180,
        gross_weight_lbs=250000,
        map_min_clearance_inches=200,
    )
    bundle["escorts"] = {"front1": esc_f1, "front2": esc_f2, "rear": esc_r}
    advance_to_cleared(bundle, survey_clearance=190, confirm_police_flag=True)
    offer_and_accept(bundle, esc_f1, "FRONT")
    offer_and_accept(bundle, esc_f2, "FRONT")
    offer_and_accept(bundle, esc_r, "REAR")
    advance_to_scheduled(bundle)
    advance_to_en_route(bundle, "2026-08-10T09:00:00Z")
    if with_delay:
        set_clock("2026-08-10T10:00:00Z")
        delay = open_delay(bundle["job"]["id"], "CARRIER_DELAY", "2026-08-10T10:00:00Z")
        set_clock("2026-08-10T10:31:00Z")
        delay = close_delay(delay["id"])
        bundle["delay"] = delay
    advance_to_delivered(bundle, "2026-08-10T13:30:00Z", checkin_at="2026-08-10T12:00:00Z")
    return bundle


def setup_en_route_one_position_job(*, escort_name="Test Rider") -> dict:
    """Booked/permitted/scheduled one-position TX job, EN_ROUTE since 09:00."""
    carrier = register_carrier(10_000_000)
    escort = register_escort(("TX",), escort_name)
    bundle = setup_booked_job(carrier)
    bundle["escort"] = escort
    advance_to_cleared(bundle)
    offer_and_accept(bundle, escort, "REAR")
    advance_to_scheduled(bundle)
    advance_to_en_route(bundle, "2026-08-10T09:00:00Z")
    return bundle
