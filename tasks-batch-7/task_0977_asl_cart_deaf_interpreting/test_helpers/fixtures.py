"""
Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so each fixture builds
its preconditions from scratch against an empty database, using only
PRD-declared endpoints. Setup calls go through get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_org_payload,
    create_rate_card_payload,
    create_vri_rate_card_payload,
    create_interpreter_payload,
    create_certification_payload,
    create_availability_window_payload,
    create_request_payload,
    create_offer_payload,
    create_complaint_payload,
)
from .test_users import (
    TEST_USERS,
    make_org_requester_headers,
    make_interpreter_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]

CLOCK_START = TEST_DEFAULTS["CLOCK_START"]


# ─── Primitive steps ─────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_org(name="Metro Hospital", org_type="MEDICAL",
               credit_limit_cents=TEST_DEFAULTS["ORG_CREDIT_LIMIT_CENTS"]) -> dict:
    resp = api_client.create_org(
        create_org_payload(name=name, org_type=org_type,
                           credit_limit_cents=credit_limit_cents),
        ADMIN,
    )
    return get_success_data(resp)


def create_standard_rate_card(**overrides) -> dict:
    resp = api_client.create_rate_card(create_rate_card_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_vri_rate_card(**overrides) -> dict:
    resp = api_client.create_rate_card(create_vri_rate_card_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_active_interpreter(
    full_name="Ana ASL",
    modalities=("ASL_ONSITE",),
    vri_platform_certified=False,
    credential="RID_NIC",
    level="CERTIFIED",
    expires_on="2028-01-01T00:00:00Z",
) -> dict:
    """Create interpreter + certification, verify the cert, activate. Returns interpreter."""
    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(
            full_name=full_name,
            modalities_offered=list(modalities),
            vri_platform_certified=vri_platform_certified,
        ),
        ADMIN,
    ))
    cert = get_success_data(api_client.create_certification(
        interp["id"],
        create_certification_payload(
            credential=credential, level=level, expires_on=expires_on),
        ADMIN,
    ))
    get_success_data(api_client.verify_certification(interp["id"], cert["id"], ADMIN))
    return get_success_data(api_client.activate_interpreter(interp["id"], ADMIN))


def add_availability(interpreter_id: str, start_at: str, end_at: str,
                     modalities=("ASL_ONSITE",)) -> dict:
    resp = api_client.create_availability_window(
        interpreter_id,
        create_availability_window_payload(
            start_at=start_at, end_at=end_at, modalities=list(modalities)),
        make_interpreter_headers(interpreter_id),
    )
    return get_success_data(resp)


def create_draft_request(org_id: str, **overrides) -> dict:
    resp = api_client.create_request(
        create_request_payload(org_id, **overrides),
        make_org_requester_headers(org_id),
    )
    return get_success_data(resp)


def submit_request(req: dict) -> dict:
    resp = api_client.submit_request(req["id"], make_org_requester_headers(req["org_id"]))
    return get_success_data(resp)


def create_submitted_request(org_id: str, **overrides) -> dict:
    req = create_draft_request(org_id, **overrides)
    return submit_request(req)


def get_request(req_id: str) -> dict:
    return get_success_data(api_client.get_request(req_id, ADMIN))


def get_request_version(req_id: str) -> int:
    return get_request(req_id)["version"]


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_interpreter(interpreter_id: str) -> dict:
    return get_success_data(api_client.get_interpreter(interpreter_id, ADMIN))


def get_org(org_id: str) -> dict:
    return get_success_data(api_client.get_org(org_id, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def get_encounter_of(assignment_id: str) -> dict:
    rows = get_success_data(api_client.list_assignment_encounters(assignment_id, ADMIN))
    assert len(rows) == 1, f"Expected exactly one encounter for {assignment_id}"
    return rows[0]


# ─── Tier 2/3: dispatch chain ────────────────────────

def offer_to(req_id: str, interpreter_id: str) -> dict:
    """Create an offer against a request, re-reading the current version first."""
    version = get_request_version(req_id)
    resp = api_client.create_offer(
        req_id,
        create_offer_payload(interpreter_id, version),
        ADMIN,
    )
    return get_success_data(resp)


def accept_assignment(asg: dict) -> dict:
    resp = api_client.accept_assignment(
        asg["id"], make_interpreter_headers(asg["interpreter_id"]))
    return get_success_data(resp)


def confirm_assignment(asg: dict) -> dict:
    resp = api_client.confirm_assignment(asg["id"], ADMIN)
    return get_success_data(resp)


def setup_offered_assignment(
    request_overrides=None,
    interpreter_kwargs=None,
    rate_card_overrides=None,
    org_kwargs=None,
) -> dict:
    """Standard on-site scenario driven to an OFFERED assignment.

    Returns ctx: {org, rate_card, interpreter, request, assignment}.
    """
    set_clock(CLOCK_START)
    org = create_org(**(org_kwargs or {}))
    rate_card = create_standard_rate_card(**(rate_card_overrides or {}))
    interpreter = create_active_interpreter(**(interpreter_kwargs or {}))
    add_availability(
        interpreter["id"],
        TEST_DEFAULTS["AVAILABILITY_START"],
        TEST_DEFAULTS["AVAILABILITY_END"],
        modalities=tuple((interpreter_kwargs or {}).get("modalities", ("ASL_ONSITE",))),
    )
    request = create_submitted_request(org["id"], **(request_overrides or {}))
    assignment = offer_to(request["id"], interpreter["id"])
    return {
        "org": org,
        "rate_card": rate_card,
        "interpreter": interpreter,
        "request": get_request(request["id"]),
        "assignment": assignment,
    }


def setup_accepted_assignment(**kwargs) -> dict:
    ctx = setup_offered_assignment(**kwargs)
    ctx["assignment"] = accept_assignment(ctx["assignment"])
    return ctx


def setup_confirmed_assignment(**kwargs) -> dict:
    """OFFERED -> ACCEPTED -> CONFIRMED; request bubbles to CONFIRMED."""
    ctx = setup_accepted_assignment(**kwargs)
    ctx["assignment"] = confirm_assignment(ctx["assignment"])
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx


def drive_to_checkout(
    ctx: dict,
    check_in_time: str = "2026-06-10T14:00:00Z",
    check_out_time: str = "2026-06-10T16:10:00Z",
    checkout_payload=None,
    depart: bool = True,
) -> dict:
    """CONFIRMED -> (depart) -> check-in -> check-out. Adds ctx['encounter']."""
    asg_id = ctx["assignment"]["id"]
    interp_id = ctx["interpreter"]["id"]
    set_clock(check_in_time)
    if depart:
        get_success_data(api_client.depart_assignment(asg_id, make_interpreter_headers(interp_id)))
    get_success_data(api_client.check_in_assignment(asg_id, make_interpreter_headers(interp_id)))
    set_clock(check_out_time)
    ctx["assignment"] = get_success_data(api_client.check_out_assignment(
        asg_id, checkout_payload or {}, make_interpreter_headers(interp_id)))
    ctx["encounter"] = get_encounter_of(asg_id)
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx


def setup_completed_encounter(verify: bool = False, verify_payload=None, **kwargs) -> dict:
    """Full on-site flow through check-out; optionally requester-verifies.

    Canonical service record: 130 actual minutes (14:00 -> 16:10) with
    90 travel minutes and 12 miles claimed at check-out, so the generated
    invoice totals 24840 (LABOR 19500 + TRAVEL_TIME 4500 + MILEAGE 840)
    against the standard rate card.
    """
    ctx = setup_confirmed_assignment(**kwargs)
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    if verify:
        verify_encounter(ctx, payload=verify_payload)
    return ctx


def verify_encounter(ctx: dict, payload=None) -> dict:
    resp = api_client.verify_encounter(
        ctx["encounter"]["id"],
        payload or {},
        make_org_requester_headers(ctx["org"]["id"]),
    )
    ctx["encounter"] = get_success_data(resp)
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx["encounter"]


def setup_generated_invoice(**kwargs) -> dict:
    """Through verified encounter + DRAFT invoice generation. Adds ctx['invoice']."""
    ctx = setup_completed_encounter(verify=True, **kwargs)
    resp = api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK)
    ctx["invoice"] = get_success_data(resp)
    return ctx


def setup_issued_invoice(issue_at: str = None, **kwargs) -> dict:
    """Through generate + ISSUED. Adds ctx['invoice']."""
    ctx = setup_generated_invoice(**kwargs)
    if issue_at is not None:
        set_clock(issue_at)
    ctx["invoice"] = get_success_data(api_client.issue_invoice(ctx["invoice"]["id"], CLERK))
    return ctx


# ─── Complaints ──────────────────────────────────────

def file_complaint(ctx: dict, category="QUALITY", severity="MINOR",
                   narrative="Service quality issue") -> dict:
    resp = api_client.create_complaint(
        create_complaint_payload(
            ctx["org"]["id"], ctx["assignment"]["id"],
            category=category, severity=severity, narrative=narrative),
        make_org_requester_headers(ctx["org"]["id"]),
    )
    return get_success_data(resp)


def adjudicate(complaint_id: str, outcome: str, **payload_extra) -> dict:
    payload = {"outcome": outcome}
    payload.update(payload_extra)
    resp = api_client.adjudicate_complaint(complaint_id, payload, REVIEWER)
    return get_success_data(resp)


def begin_review(complaint_id: str) -> dict:
    return get_success_data(api_client.begin_review(complaint_id, REVIEWER))


def file_and_adjudicate(ctx: dict, outcome: str, category="QUALITY",
                        severity="MINOR", narrative="n", **payload_extra) -> dict:
    complaint = file_complaint(ctx, category=category, severity=severity,
                               narrative=narrative)
    begin_review(complaint["id"])
    return adjudicate(complaint["id"], outcome, **payload_extra)


# ─── Strikes ─────────────────────────────────────────

def create_manual_strike(interpreter_id: str, occurred_at: str) -> dict:
    from .factories import create_strike_payload
    resp = api_client.create_strike(
        create_strike_payload(interpreter_id, occurred_at=occurred_at), ADMIN)
    return get_success_data(resp)


# ─── VRI scenario ────────────────────────────────────

def create_vri_interpreter(full_name="Vee One", window_start="2026-06-15T00:00:00Z",
                           window_end="2026-06-16T00:00:00Z",
                           vri_platform_certified=True) -> dict:
    interp = create_active_interpreter(
        full_name=full_name,
        modalities=("VRI",),
        vri_platform_certified=vri_platform_certified,
        credential="STATE_QA",
        level="SCREENED",
    )
    add_availability(interp["id"], window_start, window_end, modalities=("VRI",))
    return interp


def setup_vri_base(org_kwargs=None) -> dict:
    """Org (EDUCATION) + VRI rate card + one certified VRI interpreter."""
    set_clock(CLOCK_START)
    org = create_org(name="State Univ", org_type="EDUCATION", **(org_kwargs or {}))
    rate_card = create_vri_rate_card()
    interpreter = create_vri_interpreter()
    return {"org": org, "rate_card": rate_card, "interpreter": interpreter}


def create_submitted_vri_request(org_id: str, start="2026-06-15T10:00:00Z",
                                 end="2026-06-15T11:00:00Z",
                                 consumer_name="Stu Dent") -> dict:
    """VRI booking: onsite_address must not be demanded (None omits the field)."""
    return create_submitted_request(
        org_id,
        consumer_name=consumer_name,
        modality="VRI",
        ada_context="GENERAL",
        scheduled_start=start,
        scheduled_end=end,
        onsite_address=None,
        estimated_mileage=0,
    )
