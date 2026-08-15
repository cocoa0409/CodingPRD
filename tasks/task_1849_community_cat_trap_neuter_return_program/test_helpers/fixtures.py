"""Composite setup helpers: multi-step state builders used across test files.

All helpers use get_success_data() so setup failures surface as clear
"Setup failed" errors instead of confusing assertion failures.

The default logical clock before any set_clock call is exactly
2026-08-01T00:00:00Z (PRD §2.4), so default service dates are in mid/late
August 2026 and default trap dates fall strictly before them.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_caretaker_payload, create_colony_payload, create_cat_payload,
    create_partner_clinic_payload, create_clinic_day_payload,
    create_appointment_payload, create_surgery_record_payload,
    create_voucher_payload, create_complaint_payload, create_foster_home_payload,
    create_foster_placement_payload, create_population_survey_payload,
)
from .test_users import (
    make_caretaker_headers, make_volunteer_headers, make_coordinator_headers,
    make_clinic_staff_headers, make_officer_headers,
)

DEFAULT_SERVICE_DATE = "2026-08-20T00:00:00Z"
DEFAULT_TRAP_DATE = "2026-08-19T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_caretaker(coordinator_headers=None, **overrides):
    """Register a caretaker; return (caretaker_dict, caretaker_headers)."""
    ch = coordinator_headers or make_coordinator_headers()
    resp = api_client.create_caretaker(create_caretaker_payload(**overrides), ch)
    ct = get_success_data(resp)
    return ct, make_caretaker_headers(ct["id"])


def create_colony(caretaker, coordinator_headers=None, **overrides):
    """Register a colony under the given caretaker (dict or id)."""
    ch = coordinator_headers or make_coordinator_headers()
    ct_id = caretaker["id"] if isinstance(caretaker, dict) else caretaker
    resp = api_client.create_colony(create_colony_payload(ct_id, **overrides), ch)
    return get_success_data(resp)


def setup_caretaker_with_colony(**colony_overrides):
    """Caretaker + colony. Returns (caretaker, caretaker_headers, colony)."""
    ct, cth = create_caretaker()
    col = create_colony(ct, **colony_overrides)
    return ct, cth, col


def create_cat(colony, headers=None, **overrides):
    """Add a cat to a colony. Returns cat dict."""
    col_id = colony["id"] if isinstance(colony, dict) else colony
    h = headers or make_coordinator_headers()
    resp = api_client.create_cat(col_id, create_cat_payload(**overrides), h)
    return get_success_data(resp)


def create_partner_clinic(coordinator_headers=None, **overrides):
    ch = coordinator_headers or make_coordinator_headers()
    resp = api_client.create_partner_clinic(
        create_partner_clinic_payload(**overrides), ch)
    return get_success_data(resp)


def create_clinic_day(clinic, staff_headers=None, **overrides):
    """Schedule a clinic day. Returns clinic day dict."""
    sh = staff_headers or make_clinic_staff_headers()
    clin_id = clinic["id"] if isinstance(clinic, dict) else clinic
    resp = api_client.create_clinic_day(create_clinic_day_payload(clin_id, **overrides), sh)
    return get_success_data(resp)


def list_slots(day, headers=None):
    """List the slots of a clinic day (paginated data list)."""
    day_id = day["id"] if isinstance(day, dict) else day
    h = headers or make_clinic_staff_headers()
    resp = api_client.list_clinic_day_slots(day_id, h)
    return get_success_data(resp)


def get_day(day_id, headers=None):
    h = headers or make_clinic_staff_headers()
    resp = api_client.get_clinic_day(day_id, h)
    return get_success_data(resp)


def get_cat(cat_id, headers=None):
    h = headers or make_coordinator_headers()
    resp = api_client.get_cat(cat_id, h)
    return get_success_data(resp)


def get_voucher(voucher_id, headers=None):
    h = headers or make_coordinator_headers()
    resp = api_client.get_voucher(voucher_id, h)
    return get_success_data(resp)


def get_slot(slot_id, headers=None):
    h = headers or make_clinic_staff_headers()
    resp = api_client.get_clinic_slot(slot_id, h)
    return get_success_data(resp)


def get_appointment(appointment_id, headers=None):
    h = headers or make_coordinator_headers()
    resp = api_client.get_appointment(appointment_id, h)
    return get_success_data(resp)


def get_foster_home(home_id, headers=None):
    h = headers or make_coordinator_headers()
    resp = api_client.get_foster_home(home_id, h)
    return get_success_data(resp)


def get_colony(colony_id, headers=None):
    h = headers or make_coordinator_headers()
    resp = api_client.get_colony(colony_id, h)
    return get_success_data(resp)


def create_voucher(caretaker, coordinator_headers=None, **overrides):
    """Issue a voucher to a caretaker. Returns voucher dict."""
    ch = coordinator_headers or make_coordinator_headers()
    ct_id = caretaker["id"] if isinstance(caretaker, dict) else caretaker
    resp = api_client.create_voucher(create_voucher_payload(ct_id, **overrides), ch)
    return get_success_data(resp)


def create_foster_home(coordinator_headers=None, **overrides):
    """Register a foster home. Returns (home_dict, volunteer_headers)."""
    ch = coordinator_headers or make_coordinator_headers()
    resp = api_client.create_foster_home(create_foster_home_payload(**overrides), ch)
    home = get_success_data(resp)
    return home, make_volunteer_headers(home["id"])


def create_complaint(colony, officer_headers=None, **overrides):
    """File a complaint against a colony. Returns complaint dict."""
    oh = officer_headers or make_officer_headers()
    col_id = colony["id"] if isinstance(colony, dict) else colony
    resp = api_client.create_complaint(col_id, create_complaint_payload(**overrides), oh)
    return get_success_data(resp)


def create_survey(colony, headers=None, **overrides):
    h = headers or make_coordinator_headers()
    col_id = colony["id"] if isinstance(colony, dict) else colony
    resp = api_client.create_population_survey(
        col_id, create_population_survey_payload(**overrides), h)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: booking pipeline
# ---------------------------------------------------------------------------

def setup_clinic_day_with_slots(base_capacity=2, surge_capacity=0,
                                service_date=DEFAULT_SERVICE_DATE,
                                staff_headers=None, **clinic_overrides):
    """Clinic + one clinic day. Returns (clinic, day, slots)."""
    sh = staff_headers or make_clinic_staff_headers()
    clinic = create_partner_clinic(**clinic_overrides)
    day = create_clinic_day(clinic, staff_headers=sh,
                            base_capacity=base_capacity,
                            surge_capacity=surge_capacity,
                            service_date=service_date)
    slots = list_slots(day, headers=sh)
    return clinic, day, slots


def book_appointment(cat, slot, day_id, caretaker_headers, voucher_id=None,
                     trap_date=DEFAULT_TRAP_DATE):
    """Book an appointment, fetching the clinic day's live version for OCC.

    Returns (appointment_dict, new_day_version).
    """
    day = get_day(day_id)
    payload = create_appointment_payload(
        cat["id"] if isinstance(cat, dict) else cat,
        slot["id"] if isinstance(slot, dict) else slot,
        day["version"],
        trap_date=trap_date,
    )
    if voucher_id is not None:
        payload["voucher_id"] = voucher_id
    resp = api_client.create_appointment(payload, caretaker_headers)
    appt = get_success_data(resp)
    day_after = get_day(day_id)
    return appt, day_after["version"]


def drive_cat_to_post_surgery(cat, colony_caretaker_headers, day_id, slot,
                              voucher_id=None, surgery_overrides=None,
                              trap_date=DEFAULT_TRAP_DATE):
    """Book -> mark-trapped -> check-in -> surviving surgery.

    Returns (appointment, surgery_record, cat_after).
    """
    appt, _ = book_appointment(cat, slot, day_id, colony_caretaker_headers,
                               voucher_id=voucher_id, trap_date=trap_date)
    resp = api_client.mark_trapped(appt["id"], colony_caretaker_headers)
    get_success_data(resp)
    sh = make_clinic_staff_headers()
    resp = api_client.check_in(appt["id"], sh)
    get_success_data(resp)
    payload = create_surgery_record_payload(appt["id"], **(surgery_overrides or {}))
    resp = api_client.create_surgery_record(payload, sh)
    record = get_success_data(resp)
    cat_after = get_cat(cat["id"] if isinstance(cat, dict) else cat)
    return appt, record, cat_after


def setup_cat_at_post_surgery(approximate_age_months=24, base_capacity=2,
                              surge_capacity=0, service_date=DEFAULT_SERVICE_DATE,
                              surgery_overrides=None, **colony_overrides):
    """Full setup: caretaker, colony, one cat driven to POST_SURGERY.

    Returns a dict with the scenario state:
      caretaker, caretaker_headers, colony, cat, clinic, day, slots,
      appointment, surgery_record
    """
    ct, cth, col = setup_caretaker_with_colony(**colony_overrides)
    cat = create_cat(col, approximate_age_months=approximate_age_months)
    clinic, day, slots = setup_clinic_day_with_slots(
        base_capacity=base_capacity, surge_capacity=surge_capacity,
        service_date=service_date)
    appt, record, cat_after = drive_cat_to_post_surgery(cat, cth, day["id"], slots[0],
                                                        surgery_overrides=surgery_overrides)
    return {
        "caretaker": ct,
        "caretaker_headers": cth,
        "colony": col,
        "cat": cat_after,
        "clinic": clinic,
        "day": day,
        "slots": slots,
        "appointment": appt,
        "surgery_record": record,
    }


def setup_cat_returned(**kwargs):
    """Cat driven to POST_SURGERY then RETURNED via RETURN_TO_FIELD decision.

    Returns the scenario dict from setup_cat_at_post_surgery, with "cat"
    refreshed to the RETURNED state.
    """
    sc = setup_cat_at_post_surgery(**kwargs)
    cat = sc["cat"]
    resp = api_client.decide_pathway(
        cat["id"], {"pathway": "RETURN_TO_FIELD", "expected_cat_version": cat["version"]},
        make_coordinator_headers())
    get_success_data(resp)
    sc["cat"] = get_cat(cat["id"])
    return sc


def setup_cat_in_adoption_pipeline(**kwargs):
    """Adult cat driven to POST_SURGERY then ADOPTION_PIPELINE."""
    sc = setup_cat_at_post_surgery(**kwargs)
    cat = sc["cat"]
    resp = api_client.decide_pathway(
        cat["id"], {"pathway": "ADOPTION", "expected_cat_version": cat["version"]},
        make_coordinator_headers())
    get_success_data(resp)
    sc["cat"] = get_cat(cat["id"])
    return sc


def setup_kitten_in_foster(home_capacity=3, kitten_age_months=2, **kwargs):
    """Kitten driven to POST_SURGERY then placed into a foster home.

    Returns scenario dict augmented with "foster_home", "volunteer_headers",
    and "placement".
    """
    sc = setup_cat_at_post_surgery(approximate_age_months=kitten_age_months, **kwargs)
    home, vh = create_foster_home(capacity_kittens=home_capacity)
    resp = api_client.create_foster_placement(
        create_foster_placement_payload(sc["cat"]["id"], home["id"]),
        make_coordinator_headers())
    placement = get_success_data(resp)
    sc["foster_home"] = home
    sc["volunteer_headers"] = vh
    sc["placement"] = placement
    sc["cat"] = get_cat(sc["cat"]["id"])
    return sc
