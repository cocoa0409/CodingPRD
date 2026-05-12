"""ReturnShipment service."""
from clock import now
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create, bump, write_audit, emit_event
from services.pricing import storage_fee_at


def create_return_shipment(parcel_id: str, body: dict, actor_role: str, actor_id: str):
    from services.parcel import get_parcel
    parcel = get_parcel(parcel_id, allow_not_found=False)
    courier_tracking_return = (body or {}).get("courier_tracking_return")
    with GLOBAL_LOCK:
        if parcel["status"] != "AWAITING_RETURN":
            raise_error(E.INVALID_PARCEL_STATE,
                        "Parcel must be in AWAITING_RETURN to request a return")
        row = stamp_create({
            "parcel_id": parcel_id,
            "courier_company_id": parcel["courier_company_id"],
            "courier_tracking_return": courier_tracking_return,
            "status": "REQUESTED",
            "requested_at": now(),
            "courier_response_at": None,
            "shipped_at": None,
        })
        store.return_shipments[row["id"]] = row
        emit_event("COURIER", "RETURN_REQUESTED", "ReturnShipment", row["id"],
                   payload={"parcel_id": parcel_id})
        write_audit("ReturnShipment", row["id"], "RETURN_REQUESTED",
                    actor_role, actor_id, from_state=None, to_state="REQUESTED",
                    payload={"parcel_id": parcel_id})
        return row


def courier_response(return_shipment_id, body, actor_role, actor_id):
    rs = store.return_shipments.get(return_shipment_id)
    if rs is None:
        raise_error(E.RESOURCE_NOT_FOUND, "ReturnShipment not found")
    decision = (body or {}).get("decision")
    if decision not in ("accept", "decline"):
        raise_error(E.VALIDATION, "decision must be accept or decline")
    parcel = store.parcels.get(rs["parcel_id"])
    with GLOBAL_LOCK:
        if rs["status"] != "REQUESTED":
            raise_error(E.INVALID_RETURN_STATE, "ReturnShipment not in REQUESTED")
        if parcel is None or parcel["status"] != "AWAITING_RETURN":
            raise_error(E.INVALID_PARCEL_STATE, "Parent parcel not AWAITING_RETURN")
        t = now()
        from_state = rs["status"]
        rs["status"] = "COURIER_ACCEPTED" if decision == "accept" else "COURIER_DECLINED"
        rs["courier_response_at"] = t
        bump(rs)
        action = "RETURN_ACCEPTED" if decision == "accept" else "RETURN_DECLINED"
        write_audit("ReturnShipment", rs["id"], action, actor_role, actor_id,
                    from_state=from_state, to_state=rs["status"], payload={})
        return rs


def ship_return(return_shipment_id, body, actor_role, actor_id):
    rs = store.return_shipments.get(return_shipment_id)
    if rs is None:
        raise_error(E.RESOURCE_NOT_FOUND, "ReturnShipment not found")
    courier_tracking_return = (body or {}).get("courier_tracking_return")
    parcel = store.parcels.get(rs["parcel_id"])
    with GLOBAL_LOCK:
        if rs["status"] != "COURIER_ACCEPTED":
            raise_error(E.INVALID_RETURN_STATE, "ReturnShipment must be COURIER_ACCEPTED")
        if parcel is None or parcel["status"] != "AWAITING_RETURN":
            raise_error(E.INVALID_PARCEL_STATE, "Parent parcel not AWAITING_RETURN")
        t = now()
        if courier_tracking_return:
            rs["courier_tracking_return"] = courier_tracking_return
        from_state = rs["status"]
        rs["status"] = "SHIPPED"
        rs["shipped_at"] = t
        bump(rs)

        # Cascade parcel -> RETURNED
        parcel["returned_at"] = t
        parcel["storage_fee_total"] = storage_fee_at(
            parcel["free_storage_deadline"], t, parcel["size_class"])
        parcel["storage_fee_locked"] = True
        parcel_from = parcel["status"]
        parcel["status"] = "RETURNED"
        bump(parcel)

        station = store.stations.get(parcel["station_id"])
        if station is not None:
            station["current_occupancy"] = max(0, station["current_occupancy"] - 1)
            bump(station)
        zone = store.shelf_zones.get(parcel["shelf_zone_id"])
        if zone is not None:
            zone["occupied_slots"] = max(0, zone["occupied_slots"] - 1)
            bump(zone)

        from services.parcel import _void_codes_on_terminal
        _void_codes_on_terminal(parcel["id"])

        write_audit("ReturnShipment", rs["id"], "RETURN_SHIPPED", actor_role, actor_id,
                    from_state=from_state, to_state="SHIPPED",
                    payload={"parcel_id": parcel["id"]})
        write_audit("Parcel", parcel["id"], "RETURNED", actor_role, actor_id,
                    from_state=parcel_from, to_state="RETURNED",
                    payload={"return_shipment_id": rs["id"]})
        emit_event("COURIER", "RETURN_SHIPPED", "ReturnShipment", rs["id"],
                   payload={"parcel_id": parcel["id"]})
        return rs
