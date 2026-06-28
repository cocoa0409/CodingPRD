"""Composite setup helpers.

These encapsulate the multi-step preambles that most lab-testing test claims
require: create catalog -> register patient -> open cart -> add lines ->
checkout -> book/check-in or ship a kit -> collect -> process -> release.

All setup calls use the lenient get_success_data() validator so a setup failure
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: the Patient role is entity-backed, so every ownership-gated
call uses make_patient_headers(patient["id"]) with the real patient id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_patient_headers,
)
from . import factories as F

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]
PHYSICIAN = TEST_USERS["ordering_physician_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------
def create_offering(api=api_client, **overrides) -> dict:
    payload = F.create_test_offering_payload(**overrides)
    return get_success_data(api.create_test_offering(payload, ADMIN))


def archive_offering(offering_id, api=api_client) -> dict:
    return get_success_data(api.archive_test_offering(offering_id, ADMIN))


def create_bundle(member_test_codes, api=api_client, **overrides) -> dict:
    payload = F.create_panel_bundle_payload(member_test_codes=member_test_codes, **overrides)
    return get_success_data(api.create_panel_bundle(payload, ADMIN))


def create_patient(api=api_client, **overrides) -> dict:
    payload = F.create_patient_payload(**overrides)
    return get_success_data(api.create_patient(payload, ADMIN))


def open_cart(patient_id, api=api_client, **overrides) -> dict:
    payload = F.create_cart_payload(patient_id, **overrides)
    return get_success_data(api.create_cart(payload, make_patient_headers(patient_id)))


def add_cart_line(cart_id, patient_id, offering_id, api=api_client) -> dict:
    payload = F.create_cart_line_payload(cart_id, offering_id)
    return get_success_data(api.create_cart_line(payload, make_patient_headers(patient_id)))


def get_cart(cart_id, patient_id, api=api_client) -> dict:
    return get_success_data(api.get_cart(cart_id, make_patient_headers(patient_id)))


def checkout(cart_id, patient_id, fulfillment_mode, api=api_client) -> dict:
    """Read the cart for its current version, then place the order."""
    cart = get_cart(cart_id, patient_id, api=api)
    payload = F.create_order_payload(cart_id, fulfillment_mode, cart["version"])
    return get_success_data(api.create_order(payload, make_patient_headers(patient_id)))


def ship_home_kit(order_id, patient_id, shipping_state_code, api=api_client) -> dict:
    payload = F.create_home_kit_payload(order_id, shipping_state_code)
    return get_success_data(api.create_home_kit(payload, make_patient_headers(patient_id)))


def order_lines_for(order_id, api=api_client) -> list:
    data, _meta = _list(api.list_order_lines(ADMIN, params={"order_id": order_id, "limit": 100}))
    return data


def physician_order_for_line(order_line_id, api=api_client) -> dict:
    data, _meta = _list(api.list_physician_orders(PHYSICIAN, params={"order_line_id": order_line_id, "limit": 100}))
    return data[0] if data else None


def _list(response):
    """Return (data_list, meta) from a list response, lenient."""
    body = get_success_data(response)
    # get_success_data returns the data payload directly; for list endpoints the
    # framework yields the list. Fall back gracefully if a dict envelope leaks.
    if isinstance(body, list):
        return body, {}
    return body, {}


# ---------------------------------------------------------------------------
# Tier 1: a checked-out single-line order, ready for fulfillment
# ---------------------------------------------------------------------------
def _offering_overrides_for_mode(fulfillment_mode, offering_overrides):
    """A HOME_KIT order ships a kit, and PRD §3.5 requires every order-line
    offering to be home_kit_eligible (the flag defaults to false). When the
    fixture drives a HOME_KIT order it must therefore create an eligible
    offering unless the caller pinned the flag explicitly."""
    ov = dict(offering_overrides or {})
    if fulfillment_mode == "HOME_KIT" and "home_kit_eligible" not in ov:
        ov["home_kit_eligible"] = True
    return ov


def setup_single_line_order(
    fulfillment_mode="HOME_KIT",
    offering_overrides=None,
    patient_overrides=None,
    shipping_state_code=None,
    api=api_client,
):
    """Catalog one offering, register a patient, build a one-line cart, check out,
    and (for HOME_KIT) ship a kit. Returns a dict with offering, patient, cart,
    order, order_line.

    shipping_state_code defaults to None, meaning the kit ships to the patient's
    own state_code — PRD §3.5 requires the shipping state to equal the patient's
    state, so a fixture that hardcoded a different state would wrongly trip
    ERR_HOME_KIT_STATE_BANNED for patients registered outside that state.
    """
    offering = create_offering(api=api, **_offering_overrides_for_mode(fulfillment_mode, offering_overrides))
    patient = create_patient(api=api, **(patient_overrides or {}))
    cart = open_cart(patient["id"], api=api, fund_source="CARD")
    add_cart_line(cart["id"], patient["id"], offering["id"], api=api)
    order = checkout(cart["id"], patient["id"], fulfillment_mode, api=api)
    if fulfillment_mode == "HOME_KIT":
        ship_home_kit(order["id"], patient["id"], shipping_state_code or patient["state_code"], api=api)
    lines = order_lines_for(order["id"], api=api)
    return {
        "offering": offering,
        "patient": patient,
        "cart": cart,
        "order": order,
        "order_line": lines[0],
        "order_lines": lines,
    }


def setup_order_with_fund_source(
    fund_source="CARD",
    fulfillment_mode="HOME_KIT",
    offering_overrides=None,
    patient_overrides=None,
    shipping_state_code=None,
    api=api_client,
):
    """Like setup_single_line_order but lets the caller pin the cart fund_source.
    shipping_state_code defaults to the patient's own state (see
    setup_single_line_order)."""
    offering = create_offering(api=api, **_offering_overrides_for_mode(fulfillment_mode, offering_overrides))
    patient = create_patient(api=api, **(patient_overrides or {}))
    cart = open_cart(patient["id"], api=api, fund_source=fund_source)
    add_cart_line(cart["id"], patient["id"], offering["id"], api=api)
    order = checkout(cart["id"], patient["id"], fulfillment_mode, api=api)
    if fulfillment_mode == "HOME_KIT":
        ship_home_kit(order["id"], patient["id"], shipping_state_code or patient["state_code"], api=api)
    lines = order_lines_for(order["id"], api=api)
    return {
        "offering": offering,
        "patient": patient,
        "cart": cart,
        "order": order,
        "order_line": lines[0],
        "order_lines": lines,
    }


# ---------------------------------------------------------------------------
# Tier 2: collect / process / release a single line
# ---------------------------------------------------------------------------
def collect_line(order_line_id, collector_headers=PHLEB, api=api_client) -> dict:
    """Collect a specimen for an order line. Returns the Specimen."""
    return get_success_data(api.collect_order_line(order_line_id, collector_headers))


def process_specimen(specimen_id, analyzer_value, api=api_client) -> dict:
    """Enter an analyzer value, minting a LabResult. Returns the LabResult."""
    payload = F.process_specimen_payload(analyzer_value)
    return get_success_data(api.process_specimen(specimen_id, payload, LAB))


def release_result(lab_result_id, releaser_headers=LAB2, api=api_client) -> dict:
    """Release a result. Defaults to a DIFFERENT LabTech identity than the
    default PhlebotomyTech collector to satisfy segregation of duties."""
    return get_success_data(api.release_lab_result(lab_result_id, releaser_headers))


def setup_collected_line(
    fulfillment_mode="HOME_KIT",
    offering_overrides=None,
    patient_overrides=None,
    shipping_state_code=None,
    collector_headers=PHLEB,
    api=api_client,
):
    """Single-line order driven to a COLLECTED specimen. Adds 'specimen' to the
    dict returned by setup_single_line_order."""
    ctx = setup_single_line_order(
        fulfillment_mode=fulfillment_mode,
        offering_overrides=offering_overrides,
        patient_overrides=patient_overrides,
        shipping_state_code=shipping_state_code,
        api=api,
    )
    ctx["specimen"] = collect_line(ctx["order_line"]["id"], collector_headers=collector_headers, api=api)
    return ctx


def setup_processed_result(
    analyzer_value=5,
    fulfillment_mode="HOME_KIT",
    offering_overrides=None,
    patient_overrides=None,
    shipping_state_code=None,
    collector_headers=PHLEB,
    api=api_client,
):
    """Single-line order driven to a PROCESSING (or PENDING_CRITICAL_CALLBACK)
    LabResult. Adds 'lab_result' to the context."""
    ctx = setup_collected_line(
        fulfillment_mode=fulfillment_mode,
        offering_overrides=offering_overrides,
        patient_overrides=patient_overrides,
        shipping_state_code=shipping_state_code,
        collector_headers=collector_headers,
        api=api,
    )
    ctx["lab_result"] = process_specimen(ctx["specimen"]["id"], analyzer_value, api=api)
    return ctx


def setup_released_result(
    analyzer_value=5,
    fulfillment_mode="HOME_KIT",
    offering_overrides=None,
    patient_overrides=None,
    shipping_state_code=None,
    collector_headers=PHLEB,
    releaser_headers=LAB2,
    api=api_client,
):
    """Single-line order driven through to a RELEASED result (and thus a
    COMPLETED order). Adds 'lab_result_released' to the context."""
    ctx = setup_processed_result(
        analyzer_value=analyzer_value,
        fulfillment_mode=fulfillment_mode,
        offering_overrides=offering_overrides,
        patient_overrides=patient_overrides,
        shipping_state_code=shipping_state_code,
        collector_headers=collector_headers,
        api=api,
    )
    ctx["lab_result_released"] = release_result(
        ctx["lab_result"]["id"], releaser_headers=releaser_headers, api=api
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: prior-released history (for repeat-discount + delta-check setups)
# ---------------------------------------------------------------------------
_HISTORY_SLOT_SEQ = [0]


def give_patient_released_result(
    patient_id, offering_id, analyzer_value=1, shipping_state_code="CA", api=api_client,
):
    """Drive one PSC order for an existing patient/offering through to a RELEASED
    result, so the patient gains released history for that test_code. Returns the
    released LabResult.

    Uses the PSC fulfillment path (book + check-in an appointment) rather than a
    home kit: the caller's offering need not be home_kit_eligible (PRD §3.5 only
    requires that flag for the HOME_KIT path), so this helper works for any
    offering. A unique appointment slot per call avoids ERR_SLOT_OVERLAP."""
    cart = open_cart(patient_id, api=api, fund_source="CARD")
    add_cart_line(cart["id"], patient_id, offering_id, api=api)
    order = checkout(cart["id"], patient_id, "PSC", api=api)
    # Distinct, non-overlapping slot per history result.
    n = _HISTORY_SLOT_SEQ[0]
    _HISTORY_SLOT_SEQ[0] += 1
    hh = 6 + (n % 12)
    slot_start = f"2026-02-01T{hh:02d}:00:00Z"
    slot_end = f"2026-02-01T{hh:02d}:30:00Z"
    appt = book_appointment(order["id"], patient_id, f"PSC-HIST-{n}", slot_start, slot_end, api=api)
    check_in_appointment(appt["id"], api=api)
    line = order_lines_for(order["id"], api=api)[0]
    specimen = collect_line(line["id"], api=api)
    result = process_specimen(specimen["id"], analyzer_value, api=api)
    return release_result(result["id"], api=api)


# ---------------------------------------------------------------------------
# Tier 4: physician-order (PWN) flows for restricted offerings (test_code TST*)
# ---------------------------------------------------------------------------
def setup_restricted_order(
    test_code="TST",
    patient_overrides=None,
    api=api_client,
):
    """A HOME_KIT order for a PWN-restricted offering (test_code starts with
    'TST'). Returns the single-line-order context plus the SUBMITTED
    physician_order for the restricted line."""
    ctx = setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": test_code},
        patient_overrides=patient_overrides,
        api=api,
    )
    ctx["physician_order"] = physician_order_for_line(ctx["order_line"]["id"], api=api)
    return ctx


def approve_physician_order(physician_order_id, api=api_client) -> dict:
    payload = F.physician_decision_payload("APPROVE")
    return get_success_data(api.decide_physician_order(physician_order_id, payload, PHYSICIAN))


# ---------------------------------------------------------------------------
# Tier 5: PSC appointment flow
# ---------------------------------------------------------------------------
def book_appointment(order_id, patient_id, psc_location_code, slot_start, slot_end,
                     fasting_confirmed=None, api=api_client) -> dict:
    overrides = {}
    if fasting_confirmed is not None:
        overrides["fasting_confirmed"] = fasting_confirmed
    payload = F.create_appointment_payload(order_id, psc_location_code, slot_start, slot_end, **overrides)
    return get_success_data(api.create_appointment(payload, make_patient_headers(patient_id)))


def check_in_appointment(appointment_id, api=api_client) -> dict:
    return get_success_data(api.check_in_appointment(appointment_id, PHLEB))
