"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before every
test. Fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors.

Identity threading: Host and Member are entity_backed roles, so every
ownership-gated call threads the real entity id through make_host_headers() /
make_member_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_host_payload, create_house_payload, create_room_payload,
    create_member_payload, create_application_payload,
    create_screening_report_payload, create_membership_payload,
    create_invoice_payload, create_payment_payload, create_incident_payload,
    create_ticket_payload, create_payout_payload,
)
from .test_users import (
    admin_headers, manager_headers, compliance_headers, finance_headers,
    make_host_headers, make_member_headers,
)


# ==========================================================================
# Atomic builders
# ==========================================================================
def set_clock(api, iso):
    return get_success_data(api.set_clock({"to_iso8601": iso}, admin_headers()))


def new_host(api, **o):
    return get_success_data(api.create_host(create_host_payload(**o), admin_headers()))


def new_house(api, host_id, **o):
    return get_success_data(
        api.create_house(create_house_payload(host_id, **o), make_host_headers(host_id)))


def new_room(api, house_id, host_id, room_number="101", **o):
    return get_success_data(
        api.create_room(create_room_payload(house_id, room_number, **o),
                        make_host_headers(host_id)))


def new_member(api, **o):
    return get_success_data(api.create_member(create_member_payload(**o), admin_headers()))


def new_application(api, member_id, room_id, **o):
    return get_success_data(
        api.create_application(create_application_payload(member_id, room_id, **o),
                               make_member_headers(member_id)))


def screen(api, app_id, co="co-1", **o):
    return get_success_data(
        api.create_screening_report(app_id, create_screening_report_payload(**o),
                                    compliance_headers(co)))


def decide(api, app_id, decision="APPROVE", co="co-1", **o):
    payload = {"decision": decision}
    payload.update(o)
    return get_success_data(api.decide_application(app_id, payload, compliance_headers(co)))


def resubmit(api, app_id, member_id, **o):
    return get_success_data(
        api.resubmit_application(app_id, dict(o), make_member_headers(member_id)))


def new_membership(api, app_id, move_in_date="2026-06-01", cm="cm-1"):
    return get_success_data(
        api.create_membership(create_membership_payload(app_id, move_in_date),
                              manager_headers(cm)))


def do_move_in(api, mem_id, cm="cm-1"):
    return get_success_data(api.move_in(mem_id, manager_headers(cm)))


def file_notice(api, mem_id, reason, scheduled_move_out_date=None, headers=None,
                member_id=None, cm="cm-1"):
    payload = {"reason": reason}
    if scheduled_move_out_date is not None:
        payload["scheduled_move_out_date"] = scheduled_move_out_date
    if headers is None:
        headers = make_member_headers(member_id) if member_id else manager_headers(cm)
    return get_success_data(api.file_notice(mem_id, payload, headers))


def do_move_out(api, mem_id, actual_move_out_date, cm="cm-1"):
    return get_success_data(
        api.move_out(mem_id, {"actual_move_out_date": actual_move_out_date},
                     manager_headers(cm)))


def new_invoice(api, mem_id, period_start, period_end, fa="fa-1"):
    return get_success_data(
        api.create_invoice(create_invoice_payload(mem_id, period_start, period_end),
                           finance_headers(fa)))


def pay_invoice(api, invoice_id, amount, method="ACH", member_id=None, fa="fa-1"):
    headers = make_member_headers(member_id) if member_id else finance_headers(fa)
    return get_success_data(
        api.create_payment(invoice_id, create_payment_payload(amount, method), headers))


def assess_fee(api, invoice_id, fa="fa-1"):
    return get_success_data(api.fee_adjustment(invoice_id, {"action": "ASSESS"}, finance_headers(fa)))


def waive_fee(api, invoice_id, fa="fa-1"):
    return get_success_data(api.fee_adjustment(invoice_id, {"action": "WAIVE"}, finance_headers(fa)))


def file_incident(api, mem_id, co="co-2", **o):
    return get_success_data(
        api.create_incident(create_incident_payload(mem_id, **o), compliance_headers(co)))


def adjudicate(api, inc_id, outcome="UPHOLD", co="co-1", **o):
    payload = {"outcome": outcome}
    payload.update(o)
    return get_success_data(api.adjudicate_incident(inc_id, payload, compliance_headers(co)))


def dispute(api, inc_id, member_id, reason="disputing"):
    return get_success_data(
        api.dispute_incident(inc_id, {"dispute_reason": reason}, make_member_headers(member_id)))


def open_ticket(api, house_id, headers=None, cm="cm-1", **o):
    return get_success_data(
        api.create_ticket(create_ticket_payload(house_id, **o), headers or manager_headers(cm)))


def schedule_ticket(api, ticket_id, visit_start, visit_end, expected_house_version, cm="cm-1"):
    return get_success_data(
        api.schedule_ticket(ticket_id,
                            {"visit_start": visit_start, "visit_end": visit_end,
                             "expected_house_version": expected_house_version},
                            manager_headers(cm)))


def resolve_ticket(api, ticket_id, cm="cm-1", **o):
    return get_success_data(api.resolve_ticket(ticket_id, dict(o), manager_headers(cm)))


def new_payout(api, house_id, cycle_start, cycle_end, fa="fa-1"):
    return get_success_data(
        api.create_payout(create_payout_payload(house_id, cycle_start, cycle_end),
                          finance_headers(fa)))


def project(api, payout_id, fa="fa-1"):
    return get_success_data(api.project_payout(payout_id, finance_headers(fa)))


def release(api, payout_id, fa="fa-2"):
    return get_success_data(api.release_payout(payout_id, finance_headers(fa)))


# ==========================================================================
# Read helpers (reads are platform-wide; any authenticated role may read)
# ==========================================================================
def read_house(api, house_id):
    return get_success_data(api.get_house(house_id, manager_headers()))


def read_room(api, room_id):
    return get_success_data(api.get_room(room_id, manager_headers()))


def read_member(api, member_id):
    return get_success_data(api.get_member(member_id, manager_headers()))


def read_application(api, app_id):
    return get_success_data(api.get_application(app_id, compliance_headers()))


def read_membership(api, mem_id):
    return get_success_data(api.get_membership(mem_id, manager_headers()))


def read_invoice(api, invoice_id):
    return get_success_data(api.get_invoice(invoice_id, finance_headers()))


def read_incident(api, inc_id):
    return get_success_data(api.get_incident(inc_id, compliance_headers()))


def read_ticket(api, ticket_id):
    return get_success_data(api.get_ticket(ticket_id, manager_headers()))


def read_payout(api, payout_id):
    return get_success_data(api.get_payout(payout_id, finance_headers()))


def house_version(api, house_id):
    return read_house(api, house_id)["version"]


def room_version(api, room_id):
    return read_room(api, room_id)["version"]


# ==========================================================================
# Composite scenarios
# ==========================================================================
def base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000, set_initial_clock=True):
    """Clock + host + house (no rooms). Returns dict(host, house)."""
    if set_initial_clock:
        set_clock(api, clock)
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=budget)
    return {"host": host, "house": house}


def screened_application(api, *, clock="2026-06-01T00:00:00Z", set_initial_clock=True,
                         budget=60000, weekly=25000, monthly=100000, room_number="101",
                         billing_cycle="WEEKLY", requested_move_in="2026-06-01",
                         verified_income=400000, background="CLEAR",
                         member_name="Ada Reyes", member_email="ada@resident.example",
                         declared_income=400000, report_reference="SCR-A1"):
    """Full chain up through a SCREENED application.

    Returns dict(host, house, room, member, application).
    """
    if set_initial_clock:
        set_clock(api, clock)
    host = new_host(api)
    house = new_house(api, host["id"], monthly_utility_budget_cents=budget)
    room = new_room(api, house["id"], host["id"], room_number,
                    weekly_rate_cents=weekly, monthly_rate_cents=monthly)
    member = new_member(api, full_name=member_name, email=member_email,
                        declared_monthly_income_cents=declared_income)
    app = new_application(api, member["id"], room["id"],
                          requested_move_in_date=requested_move_in, billing_cycle=billing_cycle)
    screen(api, app["id"], verified_monthly_income_cents=verified_income,
           background_result=background, report_reference=report_reference)
    app = get_success_data(api.get_application(app["id"], compliance_headers()))
    return {"host": host, "house": house, "room": room, "member": member, "application": app}


def approved_application(api, *, decision="APPROVE", **kw):
    """screened_application + a rendered decision (default APPROVE)."""
    ctx = screened_application(api, **kw)
    ctx["application"] = decide(api, ctx["application"]["id"], decision=decision)
    return ctx


def pending_membership(api, *, move_in_date=None, **kw):
    """approved_application + membership create (PENDING_MOVE_IN / CURRENT)."""
    ctx = approved_application(api, **kw)
    mid = move_in_date if move_in_date is not None else kw.get("requested_move_in", "2026-06-01")
    ctx["membership"] = new_membership(api, ctx["application"]["id"], mid)
    return ctx


def active_tenancy(api, *, move_in_date=None, **kw):
    """pending_membership + move-in (tenancy ACTIVE / room OCCUPIED)."""
    ctx = pending_membership(api, move_in_date=move_in_date, **kw)
    ctx["membership"] = do_move_in(api, ctx["membership"]["id"])
    return ctx


def active_tenancy_with_open_invoice(api, *, period_start="2026-06-01",
                                     period_end="2026-06-07", **kw):
    """active_tenancy + one OPEN invoice for the given period. Adds 'invoice'."""
    ctx = active_tenancy(api, **kw)
    ctx["invoice"] = new_invoice(api, ctx["membership"]["id"], period_start, period_end)
    return ctx
