"""Composite setup helpers for the cooperative member-services workflows.

Every helper builds its preconditions from scratch through the public API and
uses the lenient get_success_data() validator so setup failures surface as
clear 'Setup failed' errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import COOP_DEFAULTS
from .factories import (
    create_allocation_payload,
    create_ballot_payload,
    create_cooperative_payload,
    create_device_payload,
    create_election_payload,
    create_invoice_payload,
    create_member_payload,
    create_meter_reading_payload,
    create_outage_report_payload,
    create_rate_schedule_payload,
    create_retirement_payload,
    create_row_agreement_payload,
    create_service_location_payload,
    create_service_order_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_rep_headers

ADMIN = TEST_USERS["platform_admin"]
REP = TEST_USERS["rep"]
DIRECTOR = TEST_USERS["board_director"]
SECRETARY = TEST_USERS["board_secretary"]
ANALYST = TEST_USERS["rate_analyst"]
CLERK = TEST_USERS["billing_clerk"]
FIELD = TEST_USERS["field_ops"]
DISPATCHER = TEST_USERS["dispatcher"]
LEGAL = TEST_USERS["legal_counsel"]


def setup_cooperative(**overrides):
    """Create the cooperative config. Returns cooperative dict."""
    resp = api_client.create_cooperative(create_cooperative_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def setup_member(status="ACTIVE", rate_class="RESIDENTIAL", address="1 Ln",
                 member_overrides=None, location_overrides=None):
    """Create a member with one service location and (optionally) activate.

    Returns (member, location). Status APPLICANT leaves the member inactive.
    """
    member = get_success_data(
        api_client.create_member(create_member_payload(**(member_overrides or {})), REP), 201)
    loc_payload = create_service_location_payload(
        member_id=member["id"], rate_class=rate_class, address=address,
        **(location_overrides or {}))
    location = get_success_data(api_client.create_service_location(loc_payload, REP), 201)
    if status == "ACTIVE":
        member = get_success_data(api_client.activate_member(member["id"], REP), 200)
    return member, location


def setup_published_schedule(rate_class="RESIDENTIAL", **overrides):
    """Create and publish a rate schedule. Returns schedule dict."""
    payload = create_rate_schedule_payload(rate_class=rate_class, **overrides)
    schedule = get_success_data(api_client.create_rate_schedule(payload, ANALYST), 201)
    return get_success_data(api_client.publish_rate_schedule(schedule["id"], ANALYST), 200)


def record_meter_readings(location_id, pairs):
    """Submit a sequence of (reading_at, kwh_register, demand_kw) readings."""
    readings = []
    for reading_at, kwh, demand in pairs:
        readings.append(get_success_data(api_client.create_meter_reading(
            create_meter_reading_payload(
                service_location_id=location_id, reading_at=reading_at,
                kwh_register=kwh, demand_kw=demand),
            CLERK), 201))
    return readings


def setup_finalized_invoice(location_id, period_start, period_end,
                            start_kwh, end_kwh, demand_kw=0.0):
    """Record boundary readings then create + finalize an invoice.

    Returns the FINALIZED invoice dict.
    """
    record_meter_readings(location_id, [
        (period_start, start_kwh, demand_kw),
        (period_end, end_kwh, demand_kw),
    ])
    inv = get_success_data(api_client.create_invoice(
        create_invoice_payload(
            service_location_id=location_id,
            billing_period_start=period_start, billing_period_end=period_end),
        CLERK), 201)
    return get_success_data(api_client.finalize_invoice(inv["id"], CLERK), 200)


def setup_energized_location(member=None, member_overrides=None,
                             rate_class="RESIDENTIAL", address="1 Ln",
                             location_overrides=None,
                             distance_ft=100, requires_road_bore=False,
                             row_path="consent"):
    """Full build-out: ACTIVE member + location + service order walked to
    CONSTRUCTED + ROW recorded (or condemned when row_path == 'condemn') +
    location ENERGIZED.

    Returns (member, location, service_order, row_agreement).
    """
    if member is None:
        member, location = setup_member(
            status="ACTIVE", rate_class=rate_class, address=address,
            member_overrides=member_overrides, location_overrides=location_overrides)
    else:
        loc_payload = create_service_location_payload(
            member_id=member["id"], rate_class=rate_class, address=address,
            **(location_overrides or {}))
        location = get_success_data(api_client.create_service_location(loc_payload, REP), 201)

    order = get_success_data(api_client.create_service_order(
        create_service_order_payload(
            service_location_id=location["id"],
            distance_ft=distance_ft, requires_road_bore=requires_road_bore),
        REP), 201)
    order = get_success_data(api_client.estimate_service_order(order["id"], FIELD), 200)

    row = get_success_data(api_client.create_row_agreement(
        create_row_agreement_payload(service_location_id=location["id"]), FIELD), 201)
    member_headers = make_member_headers(member["id"])
    if row_path == "condemn":
        row = get_success_data(api_client.contest_row(row["id"], member_headers), 200)
        row = get_success_data(api_client.condemn_row(row["id"], LEGAL), 200)
    else:
        row = get_success_data(api_client.consent_row(row["id"], member_headers), 200)
        row = get_success_data(api_client.record_row(row["id"], FIELD), 200)

    # Zero-ATC orders skip invoicing and move ESTIMATED -> PAID directly.
    if order.get("aid_to_construction_cents", 0) > 0:
        order = get_success_data(api_client.invoice_atc(order["id"], REP), 200)
    order = get_success_data(api_client.mark_order_paid(order["id"], REP), 200)
    order = get_success_data(api_client.schedule_service_order(order["id"], FIELD), 200)
    order = get_success_data(api_client.construct_service_order(order["id"], FIELD), 200)

    location = get_success_data(api_client.energize_location(location["id"], FIELD), 200)
    return member, location, order, row


def setup_member_with_billed_kwh(kwh, fiscal_year=2025, method_pool=None,
                                 member_name="M", district_id=1,
                                 rate_class="RESIDENTIAL", address="1",
                                 period=None):
    """ACTIVE member whose location has a FINALIZED invoice of `kwh` in the
    given fiscal year's billing window.

    With fiscal_year_end_month == 12, fiscal year N covers the calendar year N;
    billing_period_end must land inside it. Returns (coop, member, location, invoice).
    """
    coop = setup_cooperative()
    member, location = setup_member(
        status="ACTIVE", rate_class=rate_class, address=address,
        member_overrides={"legal_name": member_name, "district_id": district_id})
    setup_published_schedule(rate_class=rate_class)
    if period is None:
        # End the billing window unambiguously inside fiscal_year: under PRD
        # §3.7 the invoice's kwh is attributed to the fiscal year containing
        # its billing_period_end, and FY N ends on the last day of month
        # fiscal_year_end_month of calendar year N.
        period = (f"{fiscal_year}-12-01T00:00:00Z", f"{fiscal_year}-12-31T00:00:00Z")
    invoice = setup_finalized_invoice(location["id"], period[0], period[1], 0, kwh)
    return coop, member, location, invoice


def setup_approved_allocation(coop, fiscal_year=2025, method="FLAT_PER_MEMBER",
                              margin_cents=10000, rep_headers=None):
    """Post margin, create allocation, board-approve it.

    Returns (allocation, coop_version_after_approve).
    """
    rep = rep_headers or REP
    get_success_data(api_client.post_margin(
        coop["id"], {"fiscal_year": fiscal_year, "margin_cents": margin_cents}, rep), 200)
    alloc = get_success_data(api_client.create_allocation(
        create_allocation_payload(
            cooperative_id=coop["id"], fiscal_year=fiscal_year, method=method),
        rep), 201)
    alloc = get_success_data(api_client.approve_allocation(alloc["id"], DIRECTOR), 200)
    coop_now = get_success_data(api_client.get_cooperative(coop["id"], rep), 200)
    return alloc, coop_now["version"]


def setup_posted_allocation(coop, fiscal_year=2025, method="FLAT_PER_MEMBER",
                            margin_cents=10000):
    """Full allocation lifecycle through POSTED. Returns allocation dict."""
    alloc, version = setup_approved_allocation(
        coop, fiscal_year=fiscal_year, method=method, margin_cents=margin_cents)
    return get_success_data(api_client.post_allocation(
        alloc["id"], {"expected_cooperative_version": version}, REP), 200)


def setup_executed_retirement(coop, method="PRO_RATA_PERCENTAGE",
                              total_retire_cents=5000, pro_rata_pct=0.5):
    """Propose, board-approve and execute a retirement run.

    Returns (retirement, payouts_list).
    """
    payload = create_retirement_payload(
        cooperative_id=coop["id"], method=method, total_retire_cents=total_retire_cents)
    if method == "PRO_RATA_PERCENTAGE":
        payload["pro_rata_pct"] = pro_rata_pct
    ret = get_success_data(api_client.create_retirement(payload, REP), 201)
    ret = get_success_data(api_client.board_approve_retirement(ret["id"], DIRECTOR), 200)
    coop_now = get_success_data(api_client.get_cooperative(coop["id"], REP), 200)
    ret = get_success_data(api_client.execute_retirement(
        ret["id"], {"expected_cooperative_version": coop_now["version"]}, REP), 200)
    payouts = get_success_data(api_client.list_retirement_payouts(ret["id"], REP), 200)
    return ret, payouts


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), 200)


def setup_voting_open_election(coop, seats=(1,), candidates=("Cand A",),
                               voting_opens_at="2026-08-01T00:00:00Z",
                               voting_closes_at="2026-08-15T00:00:00Z",
                               clock_before_open=True):
    """Election walked DRAFT -> NOMINATION_OPEN -> NOMINATION_CLOSED -> VOTING_OPEN.

    Returns the election dict (VOTING_OPEN).
    """
    if clock_before_open:
        set_clock("2026-08-01T00:00:00Z")
    election = get_success_data(api_client.create_election(
        create_election_payload(
            cooperative_id=coop["id"], seats=list(seats),
            voting_opens_at=voting_opens_at, voting_closes_at=voting_closes_at),
        SECRETARY), 201)
    election = get_success_data(api_client.open_nominations(election["id"], SECRETARY), 200)
    election = get_success_data(api_client.close_nominations(
        election["id"], {"candidate_names": list(candidates)}, SECRETARY), 200)
    coop_now = get_success_data(api_client.get_cooperative(coop["id"], SECRETARY), 200)
    election = get_success_data(api_client.open_voting(
        election["id"], {"expected_cooperative_version": coop_now["version"]}, SECRETARY), 200)
    return election
