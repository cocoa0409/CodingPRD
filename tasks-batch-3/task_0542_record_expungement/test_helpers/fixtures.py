"""Composite setup helpers.

Each helper drives the API through the multi-step sequences required to reach an
interesting state, so tests can focus on assertions. Every helper builds its
preconditions from scratch (the server is restarted with an empty database before
each test) using only PRD-declared endpoints, and uses ``get_success_data`` (the
lenient validator) so setup failures surface as clear "Setup failed" errors.

Objection-window handling: because the PRD does not fix the numeric objection
window length, helpers that must *clear* served notifications advance the logical
clock to ``CLOCK_FAR_FUTURE`` first, guaranteeing the window has elapsed for any
day-scale window. Helpers whose purpose is to keep the window *open* leave the
clock at the serve instant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_petitioner_payload,
    create_criminal_record_payload,
    create_courtroom_payload,
    create_judge_payload,
    create_background_vendor_payload,
    create_petition_payload,
)
from .constants import CLOCK_START, CLOCK_FAR_FUTURE, STANDARD_MISDEMEANOR_FEE_CENTS

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
AGENCY = TEST_USERS["agency_headers"]


def _data(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return _data(api.set_clock({"to_iso8601": iso}, CLERK))


# --------------------------------------------------------------------------- #
# Primitive creators (Clerk-driven; Clerk bypasses Petitioner ownership checks)
# --------------------------------------------------------------------------- #
def create_petitioner(api, **overrides):
    return _data(api.create_petitioner(create_petitioner_payload(**overrides), CLERK))


def create_record(api, petitioner_id, **overrides):
    return _data(api.create_criminal_record(
        create_criminal_record_payload(petitioner_id, **overrides), CLERK))


def screen_record(api, record_id):
    return _data(api.screen_criminal_record(record_id, CLERK))


def create_courtroom(api, **overrides):
    return _data(api.create_courtroom(create_courtroom_payload(**overrides), CLERK))


def create_judge(api, **overrides):
    return _data(api.create_judge(create_judge_payload(**overrides), CLERK))


def create_vendor(api, **overrides):
    return _data(api.create_background_vendor(create_background_vendor_payload(**overrides), CLERK))


def create_petition(api, petitioner_id, record_ids, **overrides):
    return _data(api.create_petition(
        create_petition_payload(petitioner_id, record_ids, **overrides), CLERK))


def transition_petition(api, petition_id, to_status):
    return _data(api.transition_petition(petition_id, {"to_status": to_status}, CLERK))


def pay_fee(api, petition_id, amount_cents):
    return _data(api.pay_fee(petition_id, {"amount_cents": amount_cents}, CLERK))


def petition_version(api, petition_id):
    return _data(api.get_petition(petition_id, CLERK))["version"]


def list_notifications(api, petition_id):
    return _data(api.list_agency_notifications(CLERK, params={"petition_id": petition_id}))


def list_distributions(api, court_order_id, recipient_type=None):
    params = {"court_order_id": court_order_id}
    if recipient_type is not None:
        params["recipient_type"] = recipient_type
    return _data(api.list_sealing_distributions(CLERK, params=params))


# --------------------------------------------------------------------------- #
# The standard, single MISDEMEANOR/CONVICTED, eligible record scenario.
# eligible_on = sentence_completion_date (2020-01-01) + 2 years = 2022-01-01,
# which is at/after CLOCK_START (2026-05-01) -> ELIGIBLE. Per-record fee 12900.
# --------------------------------------------------------------------------- #
def setup_screened_petition(api, *, income=9_000_000, household_size=1,
                            monthly_liquid_assets_cents=None, jurisdiction="CA-01",
                            clock=CLOCK_START):
    """Petitioner + one screened-ELIGIBLE MISDEMEANOR record + petition -> SCREENED."""
    set_clock(api, clock)
    p_over = {"annual_income_cents": income, "household_size": household_size}
    if monthly_liquid_assets_cents is not None:
        p_over["monthly_liquid_assets_cents"] = monthly_liquid_assets_cents
    petitioner = create_petitioner(api, **p_over)
    record = create_record(api, petitioner["id"])
    record = screen_record(api, record["id"])
    petition = create_petition(api, petitioner["id"], [record["id"]], jurisdiction_code=jurisdiction)
    petition = transition_petition(api, petition["id"], "SCREENED")
    return {"petitioner": petitioner, "record": record, "petition": petition}


def setup_filed_petition(api, *, jurisdiction="CA-01", clock=CLOCK_START):
    """Standard scenario carried to FILED (fee 12900 paid). Includes the 3
    PENDING AgencyNotifications created on filing."""
    ctx = setup_screened_petition(api, jurisdiction=jurisdiction, clock=clock)
    pet_id = ctx["petition"]["id"]
    pay_fee(api, pet_id, STANDARD_MISDEMEANOR_FEE_CENTS)
    ctx["petition"] = transition_petition(api, pet_id, "FILED")
    ctx["notifications"] = list_notifications(api, pet_id)
    return ctx


def setup_notifications_cleared_petition(api, *, jurisdiction="CA-01", clock=CLOCK_START):
    """FILED petition whose 3 notifications are all SERVED then CLEARED (clock
    advanced far into the future to guarantee the window has elapsed)."""
    ctx = setup_filed_petition(api, jurisdiction=jurisdiction, clock=clock)
    pet_id = ctx["petition"]["id"]
    for n in ctx["notifications"]:
        api.transition_agency_notification(n["id"], {"to_status": "SERVED"}, CLERK)
    set_clock(api, CLOCK_FAR_FUTURE)
    for n in ctx["notifications"]:
        _data(api.transition_agency_notification(n["id"], {"to_status": "CLEARED"}, CLERK))
    ctx["notifications"] = list_notifications(api, pet_id)
    return ctx


def setup_courtroom_and_judge(api, *, jurisdiction="CA-01", room_name="Room 1", judge_name="Judge 1"):
    courtroom = create_courtroom(api, name=room_name, jurisdiction_code=jurisdiction)
    judge = create_judge(api, name=judge_name, jurisdiction_code=jurisdiction)
    return courtroom, judge


def setup_hearing_set_petition(api, *, jurisdiction="CA-01", clock=CLOCK_START,
                               scheduled_start="2026-06-02T09:00:00Z",
                               scheduled_end="2026-06-02T10:00:00Z"):
    """Notifications-cleared petition + a matching courtroom & judge + a scheduled
    hearing (petition -> HEARING_SET). Returns the ctx plus courtroom/judge/hearing."""
    ctx = setup_notifications_cleared_petition(api, jurisdiction=jurisdiction, clock=clock)
    courtroom, judge = setup_courtroom_and_judge(api, jurisdiction=jurisdiction)
    pet_id = ctx["petition"]["id"]
    v = petition_version(api, pet_id)
    hearing = _data(api.create_hearing(pet_id, {
        "courtroom_id": courtroom["id"], "judge_id": judge["id"],
        "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
        "expected_petition_version": v,
    }, CLERK))
    ctx.update({"courtroom": courtroom, "judge": judge, "hearing": hearing})
    ctx["petition"] = _data(api.get_petition(pet_id, CLERK))
    return ctx


def setup_held_hearing_petition(api, *, jurisdiction="CA-01", clock=CLOCK_START):
    """HEARING_SET petition whose hearing has been marked HELD."""
    ctx = setup_hearing_set_petition(api, jurisdiction=jurisdiction, clock=clock)
    ctx["hearing"] = _data(api.transition_hearing(ctx["hearing"]["id"], {"to_status": "HELD"}, CLERK))
    return ctx


def setup_granted_order(api, *, jurisdiction="CA-01", clock=CLOCK_START, with_vendor=False):
    """Full grant chain: held hearing + GRANTED order. Seals the record and queues
    the SealingDistribution rows. Returns ctx plus court_order and distributions.

    When ``with_vendor`` is True a BackgroundVendor is registered *before* the grant
    so the distribution fan-out includes one BACKGROUND_VENDOR row."""
    vendor = None
    if with_vendor:
        vendor = create_vendor(api)
    ctx = setup_held_hearing_petition(api, jurisdiction=jurisdiction, clock=clock)
    order = _data(api.create_court_order(ctx["hearing"]["id"], {"disposition": "GRANTED"}, JUDGE))
    ctx["court_order"] = order
    ctx["vendor"] = vendor
    ctx["distributions"] = list_distributions(api, order["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Multi-record petition builder (for the provisional/final fee scenarios).
# --------------------------------------------------------------------------- #
def build_petition_with_records(api, record_specs, *, income=9_000_000, household_size=1,
                                jurisdiction="CA-01", clock=CLOCK_START, to_status=None,
                                screen=True):
    """Create a petitioner + one record per spec (optionally screened) + petition.
    ``record_specs`` is a list of dicts of create_criminal_record overrides.
    Optionally advance the petition to ``to_status`` (e.g. "SCREENED")."""
    set_clock(api, clock)
    petitioner = create_petitioner(api, annual_income_cents=income, household_size=household_size)
    records = []
    for spec in record_specs:
        r = create_record(api, petitioner["id"], **spec)
        if screen:
            r = screen_record(api, r["id"])
        records.append(r)
    petition = create_petition(api, petitioner["id"], [r["id"] for r in records],
                               jurisdiction_code=jurisdiction)
    if to_status:
        petition = transition_petition(api, petition["id"], to_status)
    return {"petitioner": petitioner, "records": records, "petition": petition}


# --------------------------------------------------------------------------- #
# Fee waiver
# --------------------------------------------------------------------------- #
def setup_occupied_courtroom_scenario(api, *, jurisdiction="CA-01",
                                      occ_start="2026-06-02T09:00:00Z",
                                      occ_end="2026-06-02T10:00:00Z"):
    """Two fully-cleared petitions (A already occupying courtroom X with judge J1 over
    [occ_start, occ_end); B ready to schedule) plus two courtrooms and two judges, all
    in the same jurisdiction. Used for courtroom/judge temporal-conflict tests.
    Returns ids for courtroom_x, courtroom_y, judge_1, judge_2, petition_a, hearing_a,
    petition_b."""
    courtroom_x = create_courtroom(api, name="Room X", jurisdiction_code=jurisdiction)
    courtroom_y = create_courtroom(api, name="Room Y", jurisdiction_code=jurisdiction)
    judge_1 = create_judge(api, name="Judge 1", jurisdiction_code=jurisdiction)
    judge_2 = create_judge(api, name="Judge 2", jurisdiction_code=jurisdiction)

    ctx_a = setup_notifications_cleared_petition(api, jurisdiction=jurisdiction)
    pet_a = ctx_a["petition"]["id"]
    hearing_a = _data(api.create_hearing(pet_a, {
        "courtroom_id": courtroom_x["id"], "judge_id": judge_1["id"],
        "scheduled_start": occ_start, "scheduled_end": occ_end,
        "expected_petition_version": petition_version(api, pet_a),
    }, CLERK))

    ctx_b = setup_notifications_cleared_petition(api, jurisdiction=jurisdiction)
    return {
        "courtroom_x": courtroom_x, "courtroom_y": courtroom_y,
        "judge_1": judge_1, "judge_2": judge_2,
        "petition_a": ctx_a["petition"], "hearing_a": hearing_a,
        "petition_b": ctx_b["petition"],
    }


def setup_requested_fee_waiver(api, *, income, household_size, monthly_liquid_assets_cents=0,
                               jurisdiction="CA-01"):
    """Petitioner (with the given finances) + one record + DRAFT petition +
    a REQUESTED FeeWaiver whose determination has just been computed."""
    petitioner = create_petitioner(api, annual_income_cents=income, household_size=household_size,
                                   monthly_liquid_assets_cents=monthly_liquid_assets_cents)
    record = create_record(api, petitioner["id"])
    petition = create_petition(api, petitioner["id"], [record["id"]], jurisdiction_code=jurisdiction)
    waiver = _data(api.create_fee_waiver(
        {"petitioner_id": petitioner["id"], "petition_id": petition["id"]}, CLERK))
    return {"petitioner": petitioner, "record": record, "petition": petition, "waiver": waiver}


# --------------------------------------------------------------------------- #
# Objection helpers
# --------------------------------------------------------------------------- #
def setup_filed_petition_one_served(api, *, jurisdiction="CA-01", clock=CLOCK_START):
    """FILED petition with its first notification SERVED and the clock left at the
    serve instant (objection window open)."""
    ctx = setup_filed_petition(api, jurisdiction=jurisdiction, clock=clock)
    n0 = ctx["notifications"][0]
    ctx["served_notification"] = _data(
        api.transition_agency_notification(n0["id"], {"to_status": "SERVED"}, CLERK))
    return ctx
