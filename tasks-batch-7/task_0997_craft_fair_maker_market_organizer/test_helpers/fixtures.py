"""Composite setup helpers for multi-step test prerequisites.

Most testable claims require the system to be deep inside the event lifecycle
(an APPROVED application, an ACTIVE assignment, a LIVE gate, a PENDING
settlement). These helpers encapsulate the 5-15 call preambles so tests focus
on assertions. All setup calls use get_success_data() so a setup failure
surfaces as a clear "Setup failed" error rather than a confusing assertion.

Identity threading: Vendor is entity-backed by VendorProfile, so every
ownership-gated call (create/submit/pay/forfeit applications & assignments,
post ledger entries, dispute settlements) uses make_vendor_headers(vendor["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, AFTER_CLOSE
from .factories import (
    create_maker_event_payload,
    create_booth_zone_payload,
    create_booth_payload,
    create_vendor_profile_payload,
    create_application_payload,
    create_jury_score_payload,
    create_decide_payload,
    create_ticket_payload,
    create_load_slot_payload,
    create_ledger_entry_payload,
)
from .test_users import TEST_USERS, make_vendor_headers, make_event_coordinator_headers

COORD = TEST_USERS["event_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
GATE = TEST_USERS["gate_agent_headers"]

DEFAULT_SCORE_CARDS = ((8, 8, 8), (8, 8, 8))
DEFAULT_JUROR_IDS = ("juror-1", "juror-2")


# ─── Small building blocks ──────────────────────────────────────────────────

def reset_clock(to_iso8601=CLOCK_START):
    """Drive the logical clock to an explicit instant (default: startup instant)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_event(coordinator_headers=None, **overrides):
    headers = coordinator_headers or COORD
    res = api_client.create_maker_event(create_maker_event_payload(**overrides), headers)
    return get_success_data(res)


def create_zone(event_id, coordinator_headers=None, **overrides):
    headers = coordinator_headers or COORD
    res = api_client.create_booth_zone(
        event_id, create_booth_zone_payload(**overrides), headers
    )
    return get_success_data(res)


def create_booth(event_id, zone_id, coordinator_headers=None, **overrides):
    headers = coordinator_headers or COORD
    res = api_client.create_booth(
        event_id, zone_id, create_booth_payload(**overrides), headers
    )
    return get_success_data(res)


def create_vendor(**overrides):
    res = api_client.create_vendor_profile(create_vendor_profile_payload(**overrides), ADMIN)
    return get_success_data(res)


def open_applications(event_id, coordinator_headers=None):
    headers = coordinator_headers or COORD
    return get_success_data(api_client.open_applications(event_id, headers))


def create_application(event_id, vendor, category="CERAMICS", tier="STANDARD"):
    """Vendor-owned draft application (X-User-ID == VendorProfile.id)."""
    vh = make_vendor_headers(vendor["id"])
    res = api_client.create_application(
        event_id, create_application_payload(vendor["id"], requested_category=category,
                                             requested_tier=tier), vh
    )
    return get_success_data(res)


def submit_application(event_id, app_id, vendor_id):
    vh = make_vendor_headers(vendor_id)
    return get_success_data(api_client.submit_application(event_id, app_id, vh))


def close_applications(event_id, coordinator_headers=None):
    """Manual close ('by hand') — advances posture APPLICATION_OPEN -> JURY_REVIEW."""
    headers = coordinator_headers or COORD
    return get_success_data(api_client.close_applications(event_id, headers))


def post_jury_scores(event_id, app_id, cards=DEFAULT_SCORE_CARDS,
                     juror_ids=DEFAULT_JUROR_IDS):
    """Post one scorecard per distinct juror. Returns list of JuryScore payloads."""
    from .test_users import make_juror_headers
    scores = []
    for juror_id, (c, o, b) in zip(juror_ids, cards):
        res = api_client.create_jury_score(
            event_id, app_id,
            create_jury_score_payload(craftsmanship=c, originality=o, booth_presentation=b),
            make_juror_headers(juror_id),
        )
        scores.append(get_success_data(res))
    return scores


def get_event(event_id, headers=None):
    return get_success_data(api_client.get_maker_event(event_id, headers or COORD))


def decide_application(event_id, app_id, outcome, coordinator_headers=None):
    """Decide with a fresh OCC token: re-reads the event version first.
    Returns the raw response so callers can assert success or error."""
    headers = coordinator_headers or COORD
    version = get_event(event_id, headers)["version"]
    return api_client.decide_application(
        event_id, app_id, create_decide_payload(outcome, version), headers
    )


def begin_scheduling(event_id, coordinator_headers=None):
    headers = coordinator_headers or COORD
    return get_success_data(api_client.begin_scheduling(event_id, headers))


def get_assignment_for_app(event_id, app_id, headers=None):
    data = get_success_data(api_client.list_assignments(
        event_id, headers or COORD, params={"vendor_application_id": app_id}))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one assignment for application {app_id}, got {data}"
    )
    return data[0]


def list_assignments_for_app(event_id, app_id, headers=None):
    return get_success_data(api_client.list_assignments(
        event_id, headers or COORD, params={"vendor_application_id": app_id}))


def pay_assignment(event_id, assignment_id, vendor_id):
    vh = make_vendor_headers(vendor_id)
    return get_success_data(api_client.pay_assignment(event_id, assignment_id, vh))


def forfeit_assignment(event_id, assignment_id, vendor_id):
    vh = make_vendor_headers(vendor_id)
    return get_success_data(api_client.forfeit_assignment(event_id, assignment_id, vh))


def go_live(event_id, coordinator_headers=None):
    headers = coordinator_headers or COORD
    return get_success_data(api_client.go_live(event_id, headers))


def sell_ticket(event_id, coordinator_headers=None, **overrides):
    headers = coordinator_headers or COORD
    res = api_client.create_ticket(event_id, create_ticket_payload(**overrides), headers)
    return get_success_data(res)


def redeem_ticket(event_id, ticket_id):
    return api_client.redeem_ticket(event_id, ticket_id, GATE)


def reserve_slot(event_id, assignment_id, vendor_id, **overrides):
    vh = make_vendor_headers(vendor_id)
    return api_client.create_load_slot(
        event_id, create_load_slot_payload(assignment_id, **overrides), vh
    )


def post_sale(event_id, assignment_id, vendor_id, gross_cents, reversal_of_entry_id=None):
    vh = make_vendor_headers(vendor_id)
    payload = create_ledger_entry_payload(assignment_id, gross_cents)
    if reversal_of_entry_id is not None:
        payload["reversal_of_entry_id"] = reversal_of_entry_id
    return get_success_data(api_client.create_ledger_entry(event_id, payload, vh))


def end_event(event_id, coordinator_headers=None):
    headers = coordinator_headers or COORD
    return get_success_data(api_client.end_event(event_id, headers))


def get_settlement_for_assignment(event_id, assignment_id, headers=None):
    data = get_success_data(api_client.list_settlements(
        event_id, headers or TREASURER, params={"booth_assignment_id": assignment_id}))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one settlement for assignment {assignment_id}, got {data}"
    )
    return data[0]


def compute_settlement(event_id, settlement_id, treasurer_headers=None):
    headers = treasurer_headers or TREASURER
    return get_success_data(api_client.compute_settlement(event_id, settlement_id, headers))


def list_charges(event_id, assignment_id, headers=None):
    return get_success_data(api_client.list_charges(
        event_id, assignment_id, headers or COORD))


def charge_by_kind(charges, kind):
    matches = [c for c in charges if c["charge_kind"] == kind]
    return matches


# ─── Tier 1+2+3: lifecycle composites ───────────────────────────────────────

def setup_in_review_ctx(
    zone_overrides=None,
    booth_specs=({"code": "H-01"},),
    event_overrides=None,
    app_category="CERAMICS",
    app_tier="STANDARD",
    score_cards=DEFAULT_SCORE_CARDS,
    coordinator_user_id="coordinator-1",
):
    """Event + one zone + booth(s) + one vendor; application submitted, window
    closed by hand, jury scores posted. Posture: JURY_REVIEW; app: IN_REVIEW.

    Returns ctx dict: event, zone, booths, vendor, app, coordinator_headers,
    vendor_headers.
    """
    coordinator_headers = make_event_coordinator_headers(coordinator_user_id)
    reset_clock()
    event = create_event(coordinator_headers, **(event_overrides or {}))
    zone = create_zone(event["id"], coordinator_headers, **(zone_overrides or {}))
    booths = [
        create_booth(event["id"], zone["id"], coordinator_headers, **spec)
        for spec in booth_specs
    ]
    vendor = create_vendor()
    open_applications(event["id"], coordinator_headers)
    app = create_application(event["id"], vendor, app_category, app_tier)
    submit_application(event["id"], app["id"], vendor["id"])
    close_applications(event["id"], coordinator_headers)
    if score_cards:
        post_jury_scores(event["id"], app["id"], cards=score_cards)
    return {
        "event": event,
        "zone": zone,
        "booths": booths,
        "vendor": vendor,
        "app": get_success_data(
            api_client.get_application(event["id"], app["id"], coordinator_headers)
        ),
        "coordinator_headers": coordinator_headers,
        "vendor_headers": make_vendor_headers(vendor["id"]),
    }


def setup_approved_ctx(begin_schedule=True, **kwargs):
    """IN_REVIEW ctx + decide APPROVE. Adds 'assignment' (PENDING_PAYMENT).
    With begin_schedule=True (default) also advances posture to SCHEDULING."""
    ctx = setup_in_review_ctx(**kwargs)
    event_id = ctx["event"]["id"]
    res = decide_application(event_id, ctx["app"]["id"], "APPROVE",
                             ctx["coordinator_headers"])
    ctx["decided_app"] = get_success_data(res)
    if begin_schedule:
        begin_scheduling(event_id, ctx["coordinator_headers"])
    ctx["assignment"] = get_assignment_for_app(event_id, ctx["app"]["id"])
    return ctx


def setup_paid_ctx(**kwargs):
    """Approved ctx in SCHEDULING + vendor pays. Assignment becomes ACTIVE and a
    FINAL fee charge is minted. Adds 'paid_assignment'."""
    ctx = setup_approved_ctx(begin_schedule=True, **kwargs)
    event_id = ctx["event"]["id"]
    ctx["paid_assignment"] = pay_assignment(
        event_id, ctx["assignment"]["id"], ctx["vendor"]["id"]
    )
    return ctx


def setup_live_ctx(**kwargs):
    """Paid ctx + go-live. Posture: LIVE. Tickets redeemable at the gate."""
    ctx = setup_paid_ctx(**kwargs)
    go_live(ctx["event"]["id"], ctx["coordinator_headers"])
    return ctx


def setup_settlement_ctx(sales_cents=(), **kwargs):
    """Live ctx + sales posted during LIVE + clock past closes_at + end-event.
    Posture: SETTLEMENT; one PENDING settlement synthesized for the ACTIVE
    assignment. Adds 'sales' (list of ledger entries) and 'settlement'."""
    ctx = setup_live_ctx(**kwargs)
    event_id = ctx["event"]["id"]
    entries = [
        post_sale(event_id, ctx["assignment"]["id"], ctx["vendor"]["id"], gross)
        for gross in sales_cents
    ]
    ctx["sales"] = entries
    reset_clock(AFTER_CLOSE)
    end_event(event_id, ctx["coordinator_headers"])
    ctx["settlement"] = get_settlement_for_assignment(event_id, ctx["assignment"]["id"])
    return ctx


def setup_computed_ctx(sales_cents=(), **kwargs):
    """Settlement ctx + treasurer compute. Settlement is COMPUTED with
    gross/commission/net populated. Adds 'computed_settlement'."""
    ctx = setup_settlement_ctx(sales_cents=sales_cents, **kwargs)
    ctx["computed_settlement"] = compute_settlement(
        ctx["event"]["id"], ctx["settlement"]["id"]
    )
    return ctx


# ─── Tier 2 variant: two-zone live fair (weather cascade probes) ────────────

def setup_two_zone_live_ctx(coordinator_user_id="coordinator-1"):
    """LIVE event with two ACTIVE assignments: one on an OPEN_AIR CERAMICS zone,
    one on an INDOOR TEXTILES zone. Returns ctx with both branches keyed
    'open' and 'in' (each: zone, booth, vendor, app, assignment)."""
    coordinator_headers = make_event_coordinator_headers(coordinator_user_id)
    reset_clock()
    event = create_event(coordinator_headers)
    zone_open = create_zone(event["id"], coordinator_headers,
                            label="Open Lawn", weather_exposure="OPEN_AIR",
                            category="CERAMICS", category_cap=3)
    zone_in = create_zone(event["id"], coordinator_headers,
                          label="Pavilion", weather_exposure="INDOOR",
                          category="TEXTILES", category_cap=3)
    booth_open = create_booth(event["id"], zone_open["id"], coordinator_headers,
                              code="OL-01")
    booth_in = create_booth(event["id"], zone_in["id"], coordinator_headers,
                            code="PV-01")
    v_open = create_vendor()
    v_in = create_vendor()
    open_applications(event["id"], coordinator_headers)
    app_open = create_application(event["id"], v_open, "CERAMICS", "STANDARD")
    submit_application(event["id"], app_open["id"], v_open["id"])
    app_in = create_application(event["id"], v_in, "TEXTILES", "STANDARD")
    submit_application(event["id"], app_in["id"], v_in["id"])
    close_applications(event["id"], coordinator_headers)
    post_jury_scores(event["id"], app_open["id"])
    post_jury_scores(event["id"], app_in["id"])
    get_success_data(decide_application(event["id"], app_open["id"], "APPROVE",
                                        coordinator_headers))
    get_success_data(decide_application(event["id"], app_in["id"], "APPROVE",
                                        coordinator_headers))
    begin_scheduling(event["id"], coordinator_headers)
    assign_open = get_assignment_for_app(event["id"], app_open["id"], coordinator_headers)
    assign_in = get_assignment_for_app(event["id"], app_in["id"], coordinator_headers)
    pay_assignment(event["id"], assign_open["id"], v_open["id"])
    pay_assignment(event["id"], assign_in["id"], v_in["id"])
    go_live(event["id"], coordinator_headers)
    return {
        "event": event,
        "coordinator_headers": coordinator_headers,
        "open": {"zone": zone_open, "booth": booth_open, "vendor": v_open,
                 "app": app_open, "assignment": assign_open},
        "in": {"zone": zone_in, "booth": booth_in, "vendor": v_in,
               "app": app_in, "assignment": assign_in},
    }
