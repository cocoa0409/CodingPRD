"""
Payload builders and single-call setup helpers.

Every helper here performs one documented call and validates only that the call
succeeded, returning the row the API replied with. A failure inside one of them
means a precondition could not be established through the documented interface,
not that the rule under test is wrong — which is why none of them asserts a
business figure.
"""

from prd_bench_local_runner.testing import validate_success

from . import constants as C
from . import test_users as U
from .api_client import ApiClient
from .types import Headers, JsonDict


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------
def room_payload(**overrides) -> JsonDict:
    payload = dict(C.DRY_STORE_1)
    payload.update(overrides)
    return payload


def booth_payload(**overrides) -> JsonDict:
    payload = dict(C.FINISH_BOOTH_1)
    payload.update(overrides)
    return payload


def lot_payload(**overrides) -> JsonDict:
    payload = {
        "lot_code": "LOT-001",
        "species_code": "SITKA_SPRUCE",
        "cites_appendix": "NONE",
        "board_feet_received": 100.00,
        "moisture_content_pct": 12.0,
    }
    payload.update(overrides)
    return payload


def spec_payload(**overrides) -> JsonDict:
    payload = dict(C.SPEC_TOP_OM)
    payload.update(overrides)
    return payload


def station_payload(**overrides) -> JsonDict:
    payload = dict(C.CNC_STATION)
    payload.update(overrides)
    return payload


def order_payload(**overrides) -> JsonDict:
    payload = {
        "order_code": "ORD-001",
        "model_code": "OM45",
        "base_price_cents": 480000,
        "promised_date": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def option_payload(**overrides) -> JsonDict:
    payload = dict(C.OPTION_VINE_INLAY)
    payload.update(overrides)
    return payload


def measurement_payload(**overrides) -> JsonDict:
    payload = {
        "action_mm_treble": 1.60,
        "action_mm_bass": 2.20,
        "relief_mm": 0.25,
        "intonation_cents_max": 4.0,
    }
    payload.update(overrides)
    return payload


def shop_payload(**overrides) -> JsonDict:
    payload = {"shop_code": "SHP-A", "shop_name": "Alpha Fretworks", "country_code": "US"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> JsonDict:
    return validate_success(api.set_current_utc({"current_utc": current_utc}), 200)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
def create_room(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_storage_room(payload, headers or U.PLANT_ADMIN_HEADERS), 201)


def log_climate_reading(api: ApiClient, room_id: str, rh_pct: float, temp_c: float,
                        headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_climate_reading(room_id, {"rh_pct": rh_pct, "temp_c": temp_c},
                                   headers or U.PLANT_ADMIN_HEADERS), 200)


def certify_room(api: ApiClient, room_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.certify_storage_room(room_id, headers or U.PLANT_ADMIN_HEADERS), 200)


# ---------------------------------------------------------------------------
# Tonewood lots
# ---------------------------------------------------------------------------
def create_lot(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_tonewood_lot(payload, headers or U.WOOD_BUYER_HEADERS), 201)


def attest_permit(api: ApiClient, lot_id: str, permit_number: str,
                  headers: Headers = None) -> JsonDict:
    return validate_success(
        api.attest_permit(lot_id, {"permit_number": permit_number},
                          headers or U.COMPLIANCE_HEADERS), 200)


def reject_lot(api: ApiClient, lot_id: str, reason: str = "documentation defect",
               headers: Headers = None) -> JsonDict:
    return validate_success(
        api.reject_tonewood_lot(lot_id, headers or U.COMPLIANCE_HEADERS,
                                {"reason": reason}), 200)


def log_moisture_reading(api: ApiClient, lot_id: str, moisture_content_pct: float,
                         headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_moisture_reading(lot_id,
                                    {"moisture_content_pct": moisture_content_pct},
                                    headers or U.WOOD_BUYER_HEADERS), 200)


def condition_lot(api: ApiClient, lot_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.condition_tonewood_lot(lot_id, headers or U.WOOD_BUYER_HEADERS), 200)


def release_lot(api: ApiClient, lot_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.release_tonewood_lot(lot_id, headers or U.WOOD_BUYER_HEADERS), 200)


# ---------------------------------------------------------------------------
# Billets, specs and components
# ---------------------------------------------------------------------------
def create_billet(api: ApiClient, lot_id: str, expected_version: int,
                  billet_code: str = "BLT-001", board_feet: float = 30.00,
                  grade: str = "AAA", headers: Headers = None,
                  **overrides) -> JsonDict:
    payload = {
        "billet_code": billet_code,
        "lot_id": lot_id,
        "board_feet": board_feet,
        "grade": grade,
        "expected_tonewood_lot_version": expected_version,
    }
    payload.update(overrides)
    return validate_success(
        api.create_billet(payload, headers or U.MACHINIST_HEADERS), 201)


def create_spec(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_component_spec(payload, headers or U.PLANT_ADMIN_HEADERS), 201)


def create_component(api: ApiClient, spec_id: str, billet_id: str,
                     build_order_id: str = None, headers: Headers = None) -> JsonDict:
    payload = {"spec_id": spec_id, "billet_id": billet_id}
    if build_order_id is not None:
        payload["build_order_id"] = build_order_id
    return validate_success(
        api.create_component(payload, headers or U.MACHINIST_HEADERS), 201)


def route_component(api: ApiClient, component_id: str, reservation_id: str,
                    measured_thickness_mm: float = 2.90,
                    headers: Headers = None) -> JsonDict:
    payload = {
        "station_reservation_id": reservation_id,
        "measured_thickness_mm": measured_thickness_mm,
    }
    return validate_success(
        api.route_component(component_id, payload, headers or U.MACHINIST_HEADERS), 200)


def hand_shape_component(api: ApiClient, component_id: str, reservation_id: str,
                         measured_thickness_mm: float = 2.90,
                         headers: Headers = None) -> JsonDict:
    payload = {
        "station_reservation_id": reservation_id,
        "measured_thickness_mm": measured_thickness_mm,
    }
    return validate_success(
        api.hand_shape_component(component_id, payload,
                                 headers or U.LUTHIER_HEADERS), 200)


def qc_component(api: ApiClient, component_id: str, verdict: str = "ACCEPT",
                 hold_reason: str = None, headers: Headers = None) -> JsonDict:
    payload = {"verdict": verdict}
    if hold_reason is not None:
        payload["hold_reason"] = hold_reason
    return validate_success(
        api.qc_component(component_id, payload, headers or U.INSPECTOR_HEADERS), 200)


def disposition_component(api: ApiClient, component_id: str, disposition: str,
                          headers: Headers = None) -> JsonDict:
    default = U.LUTHIER_HEADERS if disposition == "REWORK" else U.INSPECTOR_HEADERS
    return validate_success(
        api.disposition_component(component_id, {"disposition": disposition},
                                  headers or default), 200)


# ---------------------------------------------------------------------------
# Stations and reservations
# ---------------------------------------------------------------------------
def create_station(api: ApiClient, room_id: str, payload: JsonDict,
                   headers: Headers = None) -> JsonDict:
    body = dict(payload)
    body["room_id"] = room_id
    return validate_success(
        api.create_station(body, headers or U.PLANT_ADMIN_HEADERS), 201)


def create_reservation(api: ApiClient, station_id: str, starts_at: str, ends_at: str,
                       build_order_id: str = None, component_id: str = None,
                       headers: Headers = None) -> JsonDict:
    payload = {"station_id": station_id, "starts_at": starts_at, "ends_at": ends_at}
    if build_order_id is not None:
        payload["build_order_id"] = build_order_id
    if component_id is not None:
        payload["component_id"] = component_id
    return validate_success(
        api.create_station_reservation(payload, headers or U.MACHINIST_HEADERS), 201)


def release_reservation(api: ApiClient, reservation_id: str,
                        headers: Headers = None) -> JsonDict:
    return validate_success(
        api.release_station_reservation(reservation_id,
                                        headers or U.MACHINIST_HEADERS), 200)


# ---------------------------------------------------------------------------
# Catalog, orders and selections
# ---------------------------------------------------------------------------
def create_option(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_option(payload, headers or U.PLANT_ADMIN_HEADERS), 201)


def create_order(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_build_order(payload, headers or U.COORDINATOR_HEADERS), 201)


def create_selection(api: ApiClient, build_order_id: str, option_id: str,
                     expected_version: int, quantity: int = None,
                     headers: Headers = None) -> JsonDict:
    payload = {
        "option_id": option_id,
        "expected_build_order_version": expected_version,
    }
    if quantity is not None:
        payload["quantity"] = quantity
    return validate_success(
        api.create_option_selection(build_order_id, payload,
                                    headers or U.COORDINATOR_HEADERS), 201)


def approve_selection(api: ApiClient, selection_id: str,
                      headers: Headers = None) -> JsonDict:
    return validate_success(
        api.approve_option_selection(selection_id,
                                     headers or U.COORDINATOR_2_HEADERS), 200)


def reject_selection(api: ApiClient, selection_id: str, reason: str = "declined",
                     headers: Headers = None) -> JsonDict:
    return validate_success(
        api.reject_option_selection(selection_id, headers or U.COORDINATOR_HEADERS,
                                    {"reason": reason}), 200)


def confirm_order(api: ApiClient, build_order_id: str, deposit_cents: int,
                  headers: Headers = None) -> JsonDict:
    return validate_success(
        api.confirm_build_order(build_order_id, {"deposit_cents": deposit_cents},
                                headers or U.COORDINATOR_HEADERS), 200)


def lock_options(api: ApiClient, build_order_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.lock_options(build_order_id, headers or U.COORDINATOR_HEADERS), 200)


def release_components(api: ApiClient, build_order_id: str,
                       headers: Headers = None) -> JsonDict:
    return validate_success(
        api.release_components(build_order_id, headers or U.MACHINIST_HEADERS), 200)


def start_assembly(api: ApiClient, build_order_id: str,
                   headers: Headers = None) -> JsonDict:
    return validate_success(
        api.start_assembly(build_order_id, headers or U.LUTHIER_HEADERS), 200)


def record_fretwork(api: ApiClient, build_order_id: str,
                    headers: Headers = None) -> JsonDict:
    return validate_success(
        api.record_fretwork(build_order_id, headers or U.LUTHIER_HEADERS), 200)


def record_setup(api: ApiClient, build_order_id: str,
                 headers: Headers = None) -> JsonDict:
    return validate_success(
        api.record_setup(build_order_id, headers or U.LUTHIER_HEADERS), 200)


def open_inspection(api: ApiClient, build_order_id: str,
                    headers: Headers = None) -> JsonDict:
    return validate_success(
        api.open_setup_inspection(build_order_id, headers or U.LUTHIER_HEADERS), 201)


def measure_inspection(api: ApiClient, inspection_id: str, payload: JsonDict = None,
                       headers: Headers = None) -> JsonDict:
    return validate_success(
        api.measure_setup_inspection(inspection_id, payload or measurement_payload(),
                                     headers or U.LUTHIER_HEADERS), 200)


def sign_inspection(api: ApiClient, inspection_id: str,
                    headers: Headers = None) -> JsonDict:
    return validate_success(
        api.sign_setup_inspection(inspection_id, headers or U.INSPECTOR_HEADERS), 200)


def assign_serial(api: ApiClient, build_order_id: str,
                  headers: Headers = None) -> JsonDict:
    return validate_success(
        api.assign_serial(build_order_id, headers or U.COORDINATOR_HEADERS), 200)


def cancel_order(api: ApiClient, build_order_id: str, reason: str = "customer withdrew",
                 headers: Headers = None) -> JsonDict:
    return validate_success(
        api.cancel_build_order(build_order_id, headers or U.COORDINATOR_HEADERS,
                               {"reason": reason}), 200)


def clear_compliance_hold(api: ApiClient, build_order_id: str,
                          headers: Headers = None) -> JsonDict:
    return validate_success(
        api.clear_compliance_hold(build_order_id, headers or U.COMPLIANCE_HEADERS), 200)


# ---------------------------------------------------------------------------
# Finish runs
# ---------------------------------------------------------------------------
def create_finish_run(api: ApiClient, build_order_id: str, booth_id: str,
                      expected_version: int, finish_system: str = "NITRO",
                      coat_count: int = 8, headers: Headers = None) -> JsonDict:
    payload = {
        "build_order_id": build_order_id,
        "booth_id": booth_id,
        "finish_system": finish_system,
        "coat_count": coat_count,
        "expected_build_order_version": expected_version,
    }
    return validate_success(
        api.create_finish_run(payload, headers or U.FINISH_TECH_HEADERS), 201)


def complete_spray(api: ApiClient, finish_run_id: str,
                   headers: Headers = None) -> JsonDict:
    return validate_success(
        api.complete_spray(finish_run_id, headers or U.FINISH_TECH_HEADERS), 200)


def resume_cure(api: ApiClient, finish_run_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.resume_cure(finish_run_id, headers or U.FINISH_TECH_HEADERS), 200)


def buff_run(api: ApiClient, finish_run_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.buff_finish_run(finish_run_id, headers or U.FINISH_TECH_HEADERS), 200)


def complete_run(api: ApiClient, finish_run_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.complete_finish_run(finish_run_id, headers or U.FINISH_TECH_HEADERS), 200)


def reject_run(api: ApiClient, finish_run_id: str, reason: str = "orange peel",
               headers: Headers = None) -> JsonDict:
    return validate_success(
        api.reject_finish_run(finish_run_id, headers or U.INSPECTOR_HEADERS,
                              {"reason": reason}), 200)


# ---------------------------------------------------------------------------
# Service network and export
# ---------------------------------------------------------------------------
def create_shop(api: ApiClient, payload: JsonDict, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.create_repair_shop(payload, headers or U.SERVICE_MANAGER_HEADERS), 201)


def authorize_shop(api: ApiClient, shop_id: str,
                   authorization_level: str = "FULL_SERVICE",
                   headers: Headers = None) -> JsonDict:
    return validate_success(
        api.authorize_repair_shop(shop_id, {"authorization_level": authorization_level},
                                  headers or U.SERVICE_MANAGER_HEADERS), 200)


def suspend_shop(api: ApiClient, shop_id: str, headers: Headers = None) -> JsonDict:
    return validate_success(
        api.suspend_repair_shop(shop_id, headers or U.SERVICE_MANAGER_HEADERS), 200)


def create_registration(api: ApiClient, build_order_id: str, shop_id: str,
                        serial_number: str, purchase_date: str = "2026-08-16T00:00:00Z",
                        owner_email: str = "owner@example.com",
                        headers: Headers = None) -> JsonDict:
    payload = {
        "build_order_id": build_order_id,
        "registering_shop_id": shop_id,
        "serial_number": serial_number,
        "owner_email": owner_email,
        "purchase_date": purchase_date,
    }
    return validate_success(
        api.create_warranty_registration(payload,
                                         headers or U.SERVICE_MANAGER_HEADERS), 201)


def void_registration(api: ApiClient, registration_id: str, reason: str = "returned",
                      headers: Headers = None) -> JsonDict:
    return validate_success(
        api.void_warranty_registration(registration_id,
                                       headers or U.SERVICE_MANAGER_HEADERS,
                                       {"reason": reason}), 200)


def create_shipment(api: ApiClient, build_order_id: str,
                    destination_country_code: str = "JP",
                    headers: Headers = None) -> JsonDict:
    payload = {
        "build_order_id": build_order_id,
        "destination_country_code": destination_country_code,
    }
    return validate_success(
        api.create_export_shipment(payload, headers or U.COMPLIANCE_HEADERS), 201)


def attach_docs(api: ApiClient, shipment_id: str, cites_permit_number: str = None,
                headers: Headers = None) -> JsonDict:
    payload = {}
    if cites_permit_number is not None:
        payload["cites_permit_number"] = cites_permit_number
    return validate_success(
        api.attach_docs(shipment_id, headers or U.COMPLIANCE_HEADERS, payload), 200)


def reject_docs(api: ApiClient, shipment_id: str, reason: str = "permit illegible",
                headers: Headers = None) -> JsonDict:
    return validate_success(
        api.reject_docs(shipment_id, {"reason": reason},
                        headers or U.COMPLIANCE_HEADERS), 200)


def release_shipment(api: ApiClient, shipment_id: str,
                     headers: Headers = None) -> JsonDict:
    return validate_success(
        api.release_export_shipment(shipment_id, headers or U.COMPLIANCE_2_HEADERS), 200)


def depart_shipment(api: ApiClient, shipment_id: str,
                    headers: Headers = None) -> JsonDict:
    return validate_success(
        api.depart_export_shipment(shipment_id, headers or U.COMPLIANCE_HEADERS), 200)
