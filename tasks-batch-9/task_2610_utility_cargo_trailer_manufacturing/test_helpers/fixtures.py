"""Precondition builders.

The harness restarts the API server before every test, so each test starts
against an empty database. Every precondition here is therefore built from
scratch through the endpoints of PRD section 4, in the order PRD section 3
allows, and never by reaching behind the API.

Each function returns the created resource body (or a dict of bodies for the
composites) so a test can thread the ids it needs.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants as K
from . import factories as F
from .test_users import (
    ASSEMBLY_TECH,
    CERT_OFFICER,
    CERT_OFFICER_2,
    PLANT_ENGINEER,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    make_dealer_headers,
)


# --- PRD 2.4 the logical clock ------------------------------------------
def set_clock(client, to_iso8601=K.CLOCK_DEFAULT_UTC, headers=None):
    return get_success_data(client.set_clock(to_iso8601, headers=headers or PLANT_ENGINEER))


# --- PRD 3.1 model configuration ----------------------------------------
def create_model(client, headers=None, **overrides):
    return get_success_data(
        client.create_model(F.model_payload(**overrides), headers=headers or PLANT_ENGINEER)
    )


def submit_model(client, model_id, headers=None, **overrides):
    return get_success_data(
        client.submit_model(
            model_id, F.submission_payload(**overrides), headers=headers or PLANT_ENGINEER
        )
    )


def decide_model(client, model_id, decision="CERTIFIED", headers=None, **overrides):
    return get_success_data(
        client.decide_model(
            model_id,
            F.decision_payload(decision, **overrides),
            headers=headers or CERT_OFFICER,
        )
    )


def create_certified_model(client, payload=None, **overrides):
    """PRD 3.1: DRAFT, then IN_ENGINEERING_REVIEW, then signed by an officer."""
    body = payload if payload is not None else F.model_payload(**overrides)
    model = get_success_data(client.create_model(body, headers=PLANT_ENGINEER))
    submit_model(client, model["id"])
    return decide_model(client, model["id"])


# --- PRD 3.2 and 3.6 plant assets ---------------------------------------
def commission_jig(client, payload=None, headers=None, **overrides):
    body = payload if payload is not None else F.jig_payload(**overrides)
    return get_success_data(client.create_jig(body, headers=headers or PLANT_ENGINEER))


def commission_lane(client, payload=None, headers=None, **overrides):
    body = payload if payload is not None else F.lane_payload(**overrides)
    return get_success_data(client.create_lane(body, headers=headers or PLANT_ENGINEER))


# --- PRD 3.8 dealer enrollment ------------------------------------------
def enroll_dealer(client, payload=None, headers=None, **overrides):
    body = payload if payload is not None else F.dealer_payload(**overrides)
    return get_success_data(client.create_dealer(body, headers=headers or SALES_ADMIN))


def read_dealer(client, dealer_id, headers=None):
    return get_success_data(client.get_dealer(dealer_id, headers=headers or SALES_ADMIN))


def adjust_floor_plan(client, dealer_id, adjustment_type, amount_cents=0, headers=None, **overrides):
    return get_success_data(
        client.adjust_floor_plan(
            dealer_id,
            F.adjustment_payload(adjustment_type, amount_cents, **overrides),
            headers=headers or SALES_ADMIN,
        )
    )


# --- PRD 3.2 build records ----------------------------------------------
def open_unit(client, model_id, serial_number="SN-000101", headers=None, **overrides):
    return get_success_data(
        client.create_unit(
            F.unit_payload(model_id, serial_number, **overrides),
            headers=headers or WELD_SUPERVISOR,
        )
    )


def read_unit(client, unit_id, headers=None):
    return get_success_data(client.get_unit(unit_id, headers=headers or WELD_SUPERVISOR))


def read_jig(client, jig_id, headers=None):
    return get_success_data(client.get_jig(jig_id, headers=headers or WELD_SUPERVISOR))


def reserve_jig_window(client, jig_id, unit_id, window=None, headers=None, **overrides):
    """PRD 2.8: the request carries the `version` of the WeldJig row last read."""
    jig = read_jig(client, jig_id)
    payload = F.reservation_payload(unit_id, jig["version"], window=window, **overrides)
    return get_success_data(
        client.reserve_jig(jig_id, payload, headers=headers or WELD_SUPERVISOR)
    )


# --- PRD 3.3 dimensional control ----------------------------------------
def inspect_frame(client, unit_id, headers=None, **overrides):
    return get_success_data(
        client.create_frame_inspection(
            unit_id, F.inspection_payload(**overrides), headers=headers or WELD_SUPERVISOR
        )
    )


# --- PRD 3.4 systems stages ---------------------------------------------
def install_lighting(client, unit_id, headers=None, **overrides):
    return get_success_data(
        client.install_systems(
            unit_id, F.lighting_payload(**overrides), headers=headers or ASSEMBLY_TECH
        )
    )


def install_brakes(
    client,
    unit_id,
    installed_braked_axle_count=1,
    breakaway_kit_installed=True,
    headers=None,
    **overrides
):
    return get_success_data(
        client.install_systems(
            unit_id,
            F.brake_payload(installed_braked_axle_count, breakaway_kit_installed, **overrides),
            headers=headers or ASSEMBLY_TECH,
        )
    )


# --- PRD 3.5 option installs --------------------------------------------
def charge_option(client, unit_id, headers=None, **overrides):
    return get_success_data(
        client.create_option_install(
            unit_id, F.option_payload(**overrides), headers=headers or ASSEMBLY_TECH
        )
    )


def complete_option(client, option_install_id, headers=None, **overrides):
    return get_success_data(
        client.complete_option_install(
            option_install_id, F.signoff_payload(**overrides), headers=headers or ASSEMBLY_TECH
        )
    )


def remove_option(client, option_install_id, headers=None, **overrides):
    return get_success_data(
        client.delete_option_install(
            option_install_id, F.removal_payload(**overrides), headers=headers or ASSEMBLY_TECH
        )
    )


# --- PRD 3.6 road tests --------------------------------------------------
def book_road_test(client, unit_id, lane_id, window=None, headers=None, **overrides):
    return get_success_data(
        client.book_road_test(
            unit_id,
            F.road_test_payload(lane_id, window=window, **overrides),
            headers=headers or QUALITY_INSPECTOR,
        )
    )


def record_road_test_result(
    client, road_test_id, brake_stop_distance_ft=32.5, lighting_check_passed=True, headers=None, **overrides
):
    return get_success_data(
        client.record_road_test_result(
            road_test_id,
            F.road_test_result_payload(
                brake_stop_distance_ft, lighting_check_passed, **overrides
            ),
            headers=headers or QUALITY_INSPECTOR,
        )
    )


# --- PRD 3.7 certification labels ---------------------------------------
def issue_label(client, unit_id, headers=None, **overrides):
    """PRD 2.11: the issuing officer must not be the officer who certified the model."""
    return get_success_data(
        client.issue_label(
            unit_id, F.label_payload(**overrides), headers=headers or CERT_OFFICER_2
        )
    )


# --- PRD 3.8 orders, allocation and delivery ----------------------------
def place_order(client, dealer_id, model_id, headers=None, **overrides):
    return get_success_data(
        client.create_order(
            F.order_payload(dealer_id, model_id, **overrides), headers=headers or SALES_ADMIN
        )
    )


def allocate_order(client, order_id, dealer_id, headers=None, **overrides):
    """PRD 2.8: the request carries the `version` of the Dealer row last read."""
    dealer = read_dealer(client, dealer_id)
    return get_success_data(
        client.allocate_order(
            order_id,
            F.allocation_payload(dealer["version"], **overrides),
            headers=headers or SALES_ADMIN,
        )
    )


def cancel_order(client, order_id, headers=None, **overrides):
    return get_success_data(
        client.cancel_order(
            order_id, F.cancellation_payload(**overrides), headers=headers or SALES_ADMIN
        )
    )


def deliver_order(client, order_id, headers=None, **overrides):
    return get_success_data(
        client.deliver_order(
            order_id, F.delivery_payload(**overrides), headers=headers or SALES_ADMIN
        )
    )


# --- PRD 3.9 warranty ----------------------------------------------------
def file_claim(client, unit_id, dealer_id, headers=None, **overrides):
    return get_success_data(
        client.create_claim(
            F.claim_payload(unit_id, dealer_id, **overrides), headers=headers or SALES_ADMIN
        )
    )


def review_claim(client, claim_id, decision="APPROVE", headers=None, **overrides):
    return get_success_data(
        client.review_claim(
            claim_id, F.review_payload(decision, **overrides), headers=headers or SALES_ADMIN
        )
    )


def resubmit_claim(client, claim_id, dealer_id, headers=None, **overrides):
    return get_success_data(
        client.resubmit_claim(
            claim_id,
            F.resubmission_payload(**overrides),
            headers=headers or make_dealer_headers(dealer_id),
        )
    )


def ship_claim_parts(client, claim_id, tracking_number="TRK-0001", headers=None, **overrides):
    return get_success_data(
        client.ship_claim_parts(
            claim_id,
            F.shipment_payload(tracking_number, **overrides),
            headers=headers or SALES_ADMIN,
        )
    )


# =========================================================================
# Composite state-progression builders
# =========================================================================
def setup_plant(client, clock=K.CLOCK_DEFAULT_UTC, dealer_overrides=None, model_overrides=None):
    """A certified TA-7X14, a TA weld jig, an asphalt lane and an enrolled dealer."""
    set_clock(client, clock)
    model = create_certified_model(client, **(model_overrides or {}))
    jig = commission_jig(client)
    lane = commission_lane(client)
    dealer = enroll_dealer(client, **(dealer_overrides or {}))
    return {"model": model, "jig": jig, "lane": lane, "dealer": dealer}


def unit_at_jig_reserved(plant, client, serial_number="SN-000101", window=None):
    """PRD 3.2: the reservation pins the model revision and seeds the weight budget."""
    unit = open_unit(client, plant["model"]["id"], serial_number)
    reservation = reserve_jig_window(client, plant["jig"]["id"], unit["id"], window=window)
    return {"unit": read_unit(client, unit["id"]), "reservation": reservation}


def unit_at_frame_welded(plant, client, serial_number="SN-000101", window=None):
    """PRD 3.3: a PASS moves the trailer to FRAME_WELDED and consumes the reservation."""
    staged = unit_at_jig_reserved(plant, client, serial_number, window)
    inspect_frame(client, staged["unit"]["id"])
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def unit_at_systems_installed(plant, client, serial_number="SN-000101", window=None):
    """PRD 3.4: BRAKE_AND_AXLE is where the two status dimensions re-couple."""
    staged = unit_at_frame_welded(plant, client, serial_number, window)
    install_lighting(client, staged["unit"]["id"])
    install_brakes(client, staged["unit"]["id"])
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def unit_at_road_test_passed(
    plant, client, serial_number="SN-000101", window=None, lane_window=None
):
    """PRD 3.6: a PASSED result moves the trailer ROAD_TEST_PENDING to ROAD_TEST_PASSED."""
    staged = unit_at_systems_installed(plant, client, serial_number, window)
    road_test = book_road_test(
        client, staged["unit"]["id"], plant["lane"]["id"], window=lane_window
    )
    record_road_test_result(client, road_test["id"])
    staged["road_test"] = road_test
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def unit_in_stock(plant, client, serial_number="SN-000101", window=None, lane_window=None):
    """PRD 3.7: with no pending option lines the trailer is labelled and released at once."""
    staged = unit_at_road_test_passed(plant, client, serial_number, window, lane_window)
    staged["label"] = issue_label(client, staged["unit"]["id"])
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def order_allocated(plant, client, staged=None, po_ref="PO-10001", stocking_program="STOCK"):
    """PRD 3.8: allocation prices the order and draws the dealer's floor plan."""
    if staged is None:
        staged = unit_in_stock(plant, client)
    order = place_order(
        client,
        plant["dealer"]["id"],
        plant["model"]["id"],
        po_ref=po_ref,
        stocking_program=stocking_program,
    )
    order = allocate_order(client, order["id"], plant["dealer"]["id"])
    staged["order"] = order
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def unit_shipped(plant, client, staged=None, delivery_clock=K.CLOCK_AUG_05, po_ref="PO-10001"):
    """PRD 3.8: delivery stamps warranty_start_date from the logical clock."""
    staged = order_allocated(plant, client, staged=staged, po_ref=po_ref)
    if delivery_clock is not None:
        set_clock(client, delivery_clock)
    staged["order"] = deliver_order(client, staged["order"]["id"])
    staged["unit"] = read_unit(client, staged["unit"]["id"])
    return staged


def claim_submitted(plant, client, staged=None, claim_clock=K.CLOCK_SEP_01, **claim_overrides):
    """PRD 3.9: a claim may only be filed against a SHIPPED trailer."""
    staged = unit_shipped(plant, client, staged=staged)
    if claim_clock is not None:
        set_clock(client, claim_clock)
    staged["claim"] = file_claim(
        client, staged["unit"]["id"], plant["dealer"]["id"], **claim_overrides
    )
    return staged


# --- Read-back helpers ---------------------------------------------------
def read_model(client, model_id, headers=None):
    return get_success_data(client.get_model(model_id, headers=headers or PLANT_ENGINEER))


def read_lane(client, lane_id, headers=None):
    return get_success_data(client.get_lane(lane_id, headers=headers or PLANT_ENGINEER))


def read_order(client, order_id, headers=None):
    return get_success_data(client.get_order(order_id, headers=headers or SALES_ADMIN))


def read_claim(client, claim_id, headers=None):
    return get_success_data(client.get_claim(claim_id, headers=headers or SALES_ADMIN))


def read_option_install(client, option_install_id, headers=None):
    return get_success_data(
        client.get_option_install(option_install_id, headers=headers or ASSEMBLY_TECH)
    )


def read_road_test(client, road_test_id, headers=None):
    return get_success_data(
        client.get_road_test(road_test_id, headers=headers or QUALITY_INSPECTOR)
    )
