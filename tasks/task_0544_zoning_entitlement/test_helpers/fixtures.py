"""Composite setup helpers for the Zoning Entitlement pipeline.

Every test starts against an empty database with the logical clock at its startup
default (2026-05-01T00:00:00Z); these helpers rebuild all preconditions from
scratch using only PRD-declared endpoints. Setup calls use get_success_data()
(lenient) so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DECISION_BASE, HEARING_DATE, CLOCK_AFTER_WINDOW,
)
from .factories import (
    parcel_payload, fee_schedule_payload, applicant_payload, application_payload,
    completeness_payload, notice_payload, hearing_payload, agenda_item_payload,
    decide_payload, plat_payload, record_payload, pay_payload,
)
from .test_users import (
    TEST_USERS, make_applicant_headers, make_planner_headers,
    make_commissioner_headers, DEFAULT_PLANNER_ID, DEFAULT_COMMISSIONER_ID,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------
# Primitive step wrappers
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def seed_parcel(**overrides) -> dict:
    return get_success_data(api_client.create_parcel(parcel_payload(**overrides), ADMIN))


def seed_fee_schedule(**overrides) -> dict:
    return get_success_data(api_client.create_fee_schedule(fee_schedule_payload(**overrides), ADMIN))


def seed_applicant(**overrides) -> dict:
    return get_success_data(api_client.create_applicant(applicant_payload(**overrides), ADMIN))


def make_application(parcel_id, applicant_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    payload = application_payload(parcel_id, applicant_id, **overrides)
    return get_success_data(api_client.create_application(payload, headers))


def submit(app_id, applicant_id) -> dict:
    return get_success_data(
        api_client.submit_application(app_id, make_applicant_headers(applicant_id)))


def record_completeness(app_id, determination="COMPLETE", planner_id=DEFAULT_PLANNER_ID,
                        deficiency_notes=None) -> dict:
    payload = completeness_payload(determination=determination)
    if deficiency_notes is not None:
        payload["deficiency_notes"] = deficiency_notes
    return get_success_data(
        api_client.record_completeness(app_id, payload, make_planner_headers(planner_id)))


def create_notice(app_id, notice_kind="MAILED") -> dict:
    return get_success_data(
        api_client.create_notice(app_id, notice_payload(notice_kind), CLERK))


def create_hearing(**overrides) -> dict:
    return get_success_data(api_client.create_hearing(hearing_payload(**overrides), CLERK))


def place_agenda(hearing_id, app_id, expected_hearing_version) -> dict:
    payload = agenda_item_payload(app_id, expected_hearing_version)
    return get_success_data(api_client.place_agenda_item(hearing_id, payload, CLERK))


def decide(item_id, decision="APPROVE", findings=None, conditions=None,
           commissioner_id=DEFAULT_COMMISSIONER_ID) -> dict:
    payload = decide_payload(decision=decision, findings=findings, conditions=conditions)
    return get_success_data(
        api_client.decide_agenda_item(item_id, payload, make_commissioner_headers(commissioner_id)))


def effectuate(app_id) -> dict:
    return get_success_data(api_client.effectuate_application(app_id, CLERK))


def make_plat(app_id, applicant_id, fee_schedule_id, **overrides) -> dict:
    payload = plat_payload(app_id, fee_schedule_id, **overrides)
    return get_success_data(
        api_client.create_plat(payload, make_applicant_headers(applicant_id)))


def impact_fee_of(plat_id) -> dict:
    data = get_success_data(api_client.list_plat_impact_fee(plat_id, CLERK))
    assert data, f"expected an impact-fee assessment for plat {plat_id}"
    return data[0]


def record_plat(plat_id, recorded_lot_count=4, recorded_gross_acres=10) -> dict:
    payload = record_payload(recorded_lot_count=recorded_lot_count,
                             recorded_gross_acres=recorded_gross_acres)
    return get_success_data(api_client.record_plat(plat_id, payload, CLERK))


def pay_fee(fee_id, amount_cents, applicant_id) -> dict:
    return get_success_data(
        api_client.pay_impact_fee(fee_id, pay_payload(amount_cents),
                                  make_applicant_headers(applicant_id)))


# --------------------------------------------------------------------------
# Composite scenario builders
# --------------------------------------------------------------------------

def build_submitted(app_type="VARIANCE", clock=CLOCK_DECISION_BASE,
                    parcel_over=None, app_over=None):
    """clock -> parcel -> applicant -> DRAFT application -> first submit (SUBMITTED)."""
    if clock is not None:
        set_clock(clock)
    parcel = seed_parcel(**(parcel_over or {}))
    applicant = seed_applicant()
    app = make_application(parcel["id"], applicant["id"],
                          application_type=app_type, **(app_over or {}))
    submit(app["id"], applicant["id"])
    return {"parcel": parcel, "applicant": applicant, "app": app}


def build_accepted(app_type="VARIANCE", clock=CLOCK_DECISION_BASE, parcel_over=None,
                   app_over=None, planner_id=DEFAULT_PLANNER_ID, with_notice=False):
    """... through a COMPLETE completeness review (ACCEPTED). Optionally mails a notice."""
    ctx = build_submitted(app_type=app_type, clock=clock,
                         parcel_over=parcel_over, app_over=app_over)
    record_completeness(ctx["app"]["id"], "COMPLETE", planner_id=planner_id)
    if with_notice:
        ctx["notice"] = create_notice(ctx["app"]["id"])
    return ctx


def build_scheduled(app_type="VARIANCE", clock=CLOCK_DECISION_BASE, parcel_over=None,
                   app_over=None, planner_id=DEFAULT_PLANNER_ID,
                   hearing_over=None):
    """... ACCEPTED + notice + hearing + agenda placement (application SCHEDULED)."""
    ctx = build_accepted(app_type=app_type, clock=clock, parcel_over=parcel_over,
                        app_over=app_over, planner_id=planner_id, with_notice=True)
    hearing = create_hearing(**(hearing_over or {}))
    item = place_agenda(hearing["id"], ctx["app"]["id"], hearing["version"])
    ctx["hearing"] = hearing
    ctx["item"] = item
    return ctx


def build_decided_approved(app_type="VARIANCE", clock=CLOCK_DECISION_BASE,
                          parcel_over=None, app_over=None,
                          planner_id=DEFAULT_PLANNER_ID,
                          commissioner_id=DEFAULT_COMMISSIONER_ID,
                          findings=None, conditions=None, hearing_over=None):
    """... SCHEDULED + APPROVE decision (application DECIDED_APPROVED)."""
    ctx = build_scheduled(app_type=app_type, clock=clock, parcel_over=parcel_over,
                        app_over=app_over, planner_id=planner_id, hearing_over=hearing_over)
    decide(ctx["item"]["id"], "APPROVE", findings=findings, conditions=conditions,
           commissioner_id=commissioner_id)
    return ctx


def build_effective(app_type="VARIANCE", clock=CLOCK_DECISION_BASE,
                   after_window_clock=CLOCK_AFTER_WINDOW, parcel_over=None, app_over=None,
                   planner_id=DEFAULT_PLANNER_ID, commissioner_id=DEFAULT_COMMISSIONER_ID,
                   findings=None, conditions=None):
    """... DECIDED_APPROVED, advance clock past the appeal window, effectuate (EFFECTIVE)."""
    ctx = build_decided_approved(app_type=app_type, clock=clock, parcel_over=parcel_over,
                               app_over=app_over, planner_id=planner_id,
                               commissioner_id=commissioner_id,
                               findings=findings, conditions=conditions)
    if after_window_clock is not None:
        set_clock(after_window_clock)
    effectuate(ctx["app"]["id"])
    return ctx


def build_effective_subdivision_with_plat(declared_lot_count=4, declared_gross_acres=10,
                                          affordable_housing=False, prior_paid_fee_cents=None,
                                          parcel_over=None):
    """A SUBDIVISION application driven to EFFECTIVE, with a fee schedule, a PENDING
    plat, and its PROVISIONAL assessment. Returns ctx incl fee_schedule/plat/assessment."""
    fee_schedule = seed_fee_schedule()
    app_over = {"affordable_housing": affordable_housing} if affordable_housing else None
    ctx = build_effective(app_type="SUBDIVISION", parcel_over=parcel_over, app_over=app_over)
    ctx["fee_schedule"] = fee_schedule
    plat_over = {"declared_lot_count": declared_lot_count,
                 "declared_gross_acres": declared_gross_acres}
    if prior_paid_fee_cents is not None:
        plat_over["prior_paid_fee_cents"] = prior_paid_fee_cents
    plat = make_plat(ctx["app"]["id"], ctx["applicant"]["id"], fee_schedule["id"], **plat_over)
    ctx["plat"] = plat
    ctx["assessment"] = impact_fee_of(plat["id"])
    return ctx


def build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                        recorded_lot_count=4, recorded_gross_acres=10,
                        affordable_housing=False, prior_paid_fee_cents=None,
                        parcel_over=None):
    """... EFFECTIVE SUBDIVISION with a plat driven to RECORDED (assessment ASSESSED)."""
    ctx = build_effective_subdivision_with_plat(
        declared_lot_count=declared_lot_count, declared_gross_acres=declared_gross_acres,
        affordable_housing=affordable_housing, prior_paid_fee_cents=prior_paid_fee_cents,
        parcel_over=parcel_over)
    record_plat(ctx["plat"]["id"], recorded_lot_count=recorded_lot_count,
                recorded_gross_acres=recorded_gross_acres)
    ctx["assessment"] = impact_fee_of(ctx["plat"]["id"])
    return ctx
