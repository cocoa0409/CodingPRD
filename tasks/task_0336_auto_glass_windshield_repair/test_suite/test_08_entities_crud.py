"""Entity creation, retrieval, required-field / type / FK validation, defaults,
duplicates, listing, and the restock + backorder side effects (PRD 3.1, 3.4)."""
from test_helpers import validate_success, validate_error, validate_paginated, is_valid_uuid
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER
NON_EXISTENT_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Corner entities — create_customer_returns_201_with_system_fields
# ---------------------------------------------------------------------------
def test_create_customer_returns_201_with_system_fields(api):
    """PRD 2.4: "a unique, server-minted identifier formatted as a UUID, with no
    type prefix."
    PRD 2.4: "an integer that starts at the resource's creation value and increments
    by one on every mutation."

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    resp = api.create_customer(f.create_customer_payload(), ADVISOR)
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert data["version"] == 1, f"created version must be 1, got {data['version']}"
    assert data.get("created_at"), "created_at must be present"


# ---------------------------------------------------------------------------
# Corner entities — get_customer_not_found
# ---------------------------------------------------------------------------
def test_get_customer_not_found(api):
    """PRD 2.5: "The request is rejected with ERR_NOT_FOUND for the first identifier
    — path segment or required reference — that does not correspond to an existing
    resource."

    Design: Corner/entities/get_customer_not_found
    """
    resp = api.get_customer(NON_EXISTENT_UUID, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner entities — create_vehicle_missing_required_vin_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_vehicle_missing_vin_rejected(api):
    """PRD 3.1: "The create body names the customer_id of the owner and supplies the
    vin, the make, the model, the model_year, the OEM windshield part number
    glass_part_number".
    PRD 2.8: "the presence and well-typedness of required input fields ...
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_vehicle_missing_required_vin_returns_invalid_request
    """
    cust = fx.create_customer()
    payload = {
        "customer_id": cust["id"],
        "make": "Honda", "model": "Civic", "model_year": 2021,
        "glass_part_number": "FWVINMISS",
    }
    resp = api.create_vehicle(payload, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner entities — create_vehicle_default_adas_equipped_false
# ---------------------------------------------------------------------------
def test_create_vehicle_default_adas_equipped_false(api):
    """PRD 3.1: "when the field is omitted at creation it defaults to false."

    Design: Corner/entities/create_vehicle_default_adas_equipped_false
    """
    cust = fx.create_customer()
    payload = {
        "customer_id": cust["id"],
        "vin": f.unique_vin(),
        "make": "Honda", "model": "Civic", "model_year": 2021,
        "glass_part_number": "FWDEFAULT",
    }
    data = validate_success(api.create_vehicle(payload, ADVISOR), 201)
    assert data["adas_equipped"] is False, f"omitted adas_equipped must default to false, got {data['adas_equipped']}"


# ---------------------------------------------------------------------------
# Corner entities — create_glass_part_invalid_bay_type_enum_rejected
# (the instance creates a ServiceBay with an undeclared bay_type member)
# ---------------------------------------------------------------------------
def test_create_service_bay_invalid_bay_type_rejected(api):
    """PRD 3.1: "The bay_type is either INSTALL, for bays that do glass replacement
    only, or CALIBRATION".
    PRD 2.8: "including that enum fields carry a declared member ...
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_glass_part_invalid_bay_type_enum_rejected
    """
    resp = api.create_service_bay({"name": "Bad Bay", "bay_type": "DETAIL", "cleanroom": False}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner entities — duplicate_customer_email_rejected
# ---------------------------------------------------------------------------
def test_duplicate_customer_email_rejected(api):
    """PRD 3.1: "the email must be unique across all customers ... An attempt to
    register a customer whose email duplicates an existing one is rejected with
    ERR_DUPLICATE."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    email = f.unique_email()
    validate_success(api.create_customer(f.create_customer_payload(email=email), ADVISOR), 201)
    resp = api.create_customer(f.create_customer_payload(email=email), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


# ---------------------------------------------------------------------------
# Corner entities — duplicate_vehicle_vin_rejected
# ---------------------------------------------------------------------------
def test_duplicate_vehicle_vin_rejected(api):
    """PRD 3.1: "The vin must be exactly seventeen characters and unique across all
    vehicles; a duplicate vin is rejected with ERR_DUPLICATE."

    Design: Corner/entities/duplicate_vehicle_vin_rejected
    """
    cust = fx.create_customer()
    vin = f.unique_vin()
    validate_success(api.create_vehicle(f.create_vehicle_payload(cust["id"], vin=vin), ADVISOR), 201)
    resp = api.create_vehicle(f.create_vehicle_payload(cust["id"], vin=vin), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


# ---------------------------------------------------------------------------
# Corner entities — create_vehicle_nonexistent_customer_not_found
# ---------------------------------------------------------------------------
def test_create_vehicle_nonexistent_customer_rejected(api):
    """PRD 2.5: "the system validates the existence of each referenced resource in a
    strict left-to-right order ... The request is rejected with ERR_NOT_FOUND for the
    first identifier — path segment or required reference — that does not correspond
    to an existing resource."

    Design: Corner/entities/create_vehicle_nonexistent_customer_not_found
    """
    payload = f.create_vehicle_payload(NON_EXISTENT_UUID)
    resp = api.create_vehicle(payload, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner entities — list_customer_vehicles_reverse_reachability
# ---------------------------------------------------------------------------
def test_list_customer_vehicles(api):
    """PRD 3.1: "the system exposes reverse lookups that list all vehicles for a
    customer, all work orders for a customer, and all work orders for a vehicle."

    Design: Corner/entities/list_customer_vehicles_reverse_reachability
    """
    cust = fx.create_customer()
    veh = fx.create_vehicle(cust["id"], glass_part_number="FWLIST")
    resp = api.list_customer_vehicles(cust["id"], ADVISOR)
    data, meta = validate_paginated(resp)
    ids = [v["id"] for v in data]
    assert veh["id"] in ids, f"created vehicle {veh['id']} must appear in the customer's vehicle list"
    assert all(v["customer_id"] == cust["id"] for v in data), "every listed vehicle must belong to the customer"


# ---------------------------------------------------------------------------
# Corner entities — glass_part_lookup_by_oem_number
# ---------------------------------------------------------------------------
def test_glass_part_lookup_by_oem_number(api):
    """PRD 3.1: "the list endpoint accepts an oem_part_number filter to find the SKU
    matching a vehicle's required part".

    Design: Corner/entities/glass_part_lookup_by_oem_number
    """
    target_oem = f.unique_oem()
    fx.create_glass_part(oem_part_number=target_oem, adas_compatible=True, on_hand_qty=2)
    fx.create_glass_part(oem_part_number=f.unique_oem(), adas_compatible=False, on_hand_qty=2)
    resp = api.list_glass_parts(MANAGER, params={"oem_part_number": target_oem})
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "lookup must return the matching SKU"
    assert all(p["oem_part_number"] == target_oem for p in data), (
        "every returned part must match the oem_part_number filter")


# ---------------------------------------------------------------------------
# Corner endpoints — restock_increments_on_hand
# ---------------------------------------------------------------------------
def test_restock_increments_on_hand(api):
    """PRD 3.1: "To add stock to an existing SKU the manager submits an add_qty,
    which increments on_hand_qty by that amount."

    Design: Corner/endpoints/restock_increments_on_hand
    """
    part = fx.create_glass_part(on_hand_qty=2)
    data = validate_success(api.restock_glass_part(part["id"], {"add_qty": 3}, MANAGER), 200)
    assert data["on_hand_qty"] == 5, f"on_hand_qty must rise from 2 to 5, got {data['on_hand_qty']}"


# ---------------------------------------------------------------------------
# Corner endpoints — backordered_part_then_received_side_effect
# ---------------------------------------------------------------------------
def test_backordered_part_then_received(api):
    """PRD 3.4: "if on_hand_qty is below the ordered quantity, the order is placed
    into BACKORDERED with no stock movement".
    PRD 3.4: "receiving it increments the part's reserved_qty by the quantity (the
    arriving stock lands directly in reservation for this order)".

    Design: Corner/endpoints/backordered_part_then_received_side_effect
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWBACK")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWBACK", adas_compatible=False, on_hand_qty=0)
    po = validate_success(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR), 201)
    assert po["status"] == "BACKORDERED", f"zero-stock order must be BACKORDERED, got {po['status']}"
    po_recv = validate_success(api.receive_part_order(po["id"], MANAGER), 200)
    assert po_recv["status"] == "RESERVED", f"receive must yield RESERVED, got {po_recv['status']}"
    part_after = validate_success(api.get_glass_part(part["id"], MANAGER), 200)
    assert part_after["reserved_qty"] == 1, f"reserved_qty must be 1 after receive, got {part_after['reserved_qty']}"
