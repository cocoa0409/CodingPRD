"""Inbound ASN flow: receiving, line-status derivation, the putaway/cross-dock
close fork, ASN state guards, and LPN minting.

Covers queue-B corner instances under state_machines (ASN/LPN), calculations
(asn_line_status), validations (lines-open close), and endpoints (LPN filter).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_license_plate, assert_asn_line,
    create_inbound_asn_payload, create_asn_line_payload, create_receipt_payload,
)
import test_helpers as th

CLERK = TEST_USERS["receiving_clerk_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]


def test_asn_line_satisfied_at_exact_equality(api):
    """PRD 3.2: "when received_qty exactly equals expected_qty the line is SATISFIED".
    PRD 3.2: "The SATISFIED band is exact equality only — neither under nor over
    receipt counts as satisfied."

    Design: Corner/calculations/asn_line_status_satisfied_at_exact_equality
    """
    sku = th.create_sku(sku_code="SKU-AL1", abc_class="C")
    asn = th.create_asn(asn_number="ASN-AL1")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    th.post_receipt(asn["id"], line["id"], 5)
    data = validate_success(api.get_asn_line(line["id"], CLERK))
    assert_asn_line(data)
    assert data["received_qty"] == 5
    assert data["line_status"] == "SATISFIED"


def test_asn_line_over_when_received_exceeds_expected(api):
    """PRD 3.2: "when received_qty is strictly greater than expected_qty the line is
    OVER". PRD 3.2: "it recomputes the line's received_qty as the sum of all that
    line's receipt events".

    Design: Corner/calculations/asn_line_status_over_when_exceeds_expected
    """
    sku = th.create_sku(sku_code="SKU-AL2", abc_class="C")
    asn = th.create_asn(asn_number="ASN-AL2")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    th.post_receipt(asn["id"], line["id"], 4)
    th.post_receipt(asn["id"], line["id"], 3)
    data = validate_success(api.get_asn_line(line["id"], CLERK))
    assert data["received_qty"] == 7
    assert data["line_status"] == "OVER"


def test_receipt_mints_lpn_putaway_pending_with_null_location(api):
    """PRD 3.2: "it mints a new LicensePlate for the line's SKU with qty equal to the
    received eaches, source_asn_id set to this ASN, disposition of PUTAWAY_PENDING,
    and location_id null".

    Design: Corner/state_machines/lpn_initial_disposition_putaway_pending
    """
    sku = th.create_sku(sku_code="SKU-INI", abc_class="C")
    asn = th.create_asn(asn_number="ASN-INI")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    receipt = validate_success(api.post_receipt(asn["id"], create_receipt_payload(line["id"], received_qty=5), CLERK), 201)
    lpn = validate_success(api.get_license_plate(receipt["lpn_id"], CLERK))
    assert_license_plate(lpn)
    assert lpn["disposition"] == "PUTAWAY_PENDING"
    assert lpn["location_id"] is None


def test_cancel_asn_after_receiving_returns_invalid_state(api):
    """PRD 3.3: "an ASN that is still ANNOUNCED with no receipts posted may be
    cancelled, moving it from ANNOUNCED to CANCELLED". PRD 2.11: "fifth, the
    state-machine precondition that the target entity is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)".

    Design: Corner/state_machines/asn_cancel_after_receiving_returns_invalid_state
    """
    sku = th.create_sku(sku_code="SKU-SM2", abc_class="C")
    asn = th.create_asn(asn_number="ASN-SM2")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    th.post_receipt(asn["id"], line["id"], 5)  # ASN now RECEIVING
    resp = api.cancel_asn(asn["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    asn_now = validate_success(api.get_inbound_asn(asn["id"], CLERK))
    assert asn_now["status"] == "RECEIVING"


def test_close_asn_with_open_line_returns_lines_open(api):
    """PRD 3.3: "every AsnLine must have line_status of SATISFIED or OVER, with no
    line still OPEN. If any line remains OPEN (its received_qty below its
    expected_qty), the close is rejected with ERR_ASN_LINES_OPEN."

    Design: Corner/validations/asn_close_with_open_line_returns_lines_open
    """
    sku = th.create_sku(sku_code="SKU-LO1", abc_class="C")
    asn = th.create_asn(asn_number="ASN-LO1")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    th.post_receipt(asn["id"], line["id"], 3)  # OPEN: 3 < 5
    resp = api.close_asn(asn["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_ASN_LINES_OPEN.value, 409)
    asn_now = validate_success(api.get_inbound_asn(asn["id"], CLERK))
    assert asn_now["status"] == "RECEIVING"


def test_crossdock_close_lands_lpn_stored_in_crossdock_lane(api):
    """PRD 3.3: "for every PUTAWAY_PENDING plate of this ASN, moves it directly into a
    CROSS_DOCK-zone location chosen by the cross-dock selector: each plate's
    disposition becomes STORED, its location_id is set to the chosen lane".
    PRD 3.3: "the cross-dock branch creates no putaway tasks; the plate lands STORED
    in a cross-dock lane immediately."

    Design: Corner/state_machines/crossdock_close_lands_lpn_stored_in_crossdock_zone
    """
    sku = th.create_sku(sku_code="SKU-XD1", abc_class="A")
    xd = th.create_location(location_code="XD-1", zone="CROSS_DOCK", max_volume_cm3=1000)
    asn = th.create_asn(asn_number="ASN-XD1", handling_mode="CROSS_DOCK")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    receipt = th.post_receipt(asn["id"], line["id"], 5)
    asn_after = validate_success(api.close_asn(asn["id"], CLERK))
    assert asn_after["status"] == "CROSS_DOCKED"
    lpn = validate_success(api.get_license_plate(receipt["lpn_id"], CLERK))
    assert lpn["disposition"] == "STORED"
    assert lpn["location_id"] == xd["id"]


def test_list_license_plates_filtered_by_source_asn(api):
    """PRD 2.3: "total_count (the full number of records matching the query before
    pagination)". PRD 3.5: a license plate originates "from source_asn_id". The
    license-plates list endpoint filters by source_asn_id.

    Design: Corner/endpoints/list_lpns_filtered_by_source_asn
    """
    sku = th.create_sku(sku_code="SKU-EP1", abc_class="C")
    asn = th.create_asn(asn_number="ASN-EP1")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    th.post_receipt(asn["id"], line["id"], 2)
    th.post_receipt(asn["id"], line["id"], 3)
    resp = api.list_license_plates(PUTAWAY, params={"source_asn_id": asn["id"]})
    data, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array"
    assert meta["total_count"] == 2
