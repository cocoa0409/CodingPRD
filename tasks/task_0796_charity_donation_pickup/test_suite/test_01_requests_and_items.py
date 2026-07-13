"""Provisioning, pickup-request creation, and item accumulation.

Translated from SCAFFOLD_CORNER_DESIGN.yaml §1.9 — section `entities`.
"""
from test_helpers import (
    api_client as api,
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_partner_payload, create_pickup_request_payload,
    assert_charity_partner,
    create_partner, create_donor, create_request, add_item,
    make_donor_headers, TEST_USERS,
)

PLATFORM = TEST_USERS["platform_admin_headers"]


def test_create_partner_returns_201_with_zeroed_totals():
    """PRD §3.1: "A partner's two rolling totals, ytd_donation_value_cents and
    diverted_weight_lbs, both begin at zero and are only ever moved by the
    reconciliations of Section 3.8."
    PRD §3.1: "A partner's status may be supplied and is otherwise ACTIVE; the
    only other value is SUSPENDED"

    Design: Corner/entities/create_partner_returns_201_with_fields
    """
    res = api.create_partner(
        create_partner_payload(name="AcmeCharity", tax_id="EIN-C1",
                               accepted_categories=["FURNITURE", "HOUSEHOLD"]),
        PLATFORM,
    )
    partner = validate_success(res, 201)
    assert_charity_partner(partner)
    assert partner["status"] == "ACTIVE"
    assert partner["ytd_donation_value_cents"] == 0
    assert partner["diverted_weight_lbs"] == 0
    assert partner["version"] == 1


def test_create_request_missing_disposition_rejected():
    """PRD §2.10: "Field-level input validity — required fields present, enum
    values in range, numeric fields within their declared bounds, and
    window/slot end strictly after start (ERR_INVALID_REQUEST, 400)."

    Design: Corner/entities/create_request_missing_required_disposition_returns_invalid_request
    """
    partner = create_partner(accepted_categories=["FURNITURE"])
    donor = create_donor()
    payload = create_pickup_request_payload(donor["id"], partner["id"])
    del payload["disposition"]
    res = api.create_pickup_request(payload, make_donor_headers(donor["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_request_invalid_disposition_enum_rejected():
    """PRD §2.10: "Field-level input validity — required fields present, enum
    values in range, numeric fields within their declared bounds, and
    window/slot end strictly after start (ERR_INVALID_REQUEST, 400)."

    Design: Corner/entities/create_request_invalid_disposition_enum_returns_invalid_request
    """
    partner = create_partner(accepted_categories=["FURNITURE"])
    donor = create_donor()
    payload = create_pickup_request_payload(donor["id"], partner["id"], disposition="SELL")
    res = api.create_pickup_request(payload, make_donor_headers(donor["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_nonexistent_partner_returns_not_found():
    """PRD §2.5: "The first identifier that does not resolve produces that
    resource's not-found error — ERR_PARTNER_NOT_FOUND, ERR_VEHICLE_NOT_FOUND,
    ERR_ROUTE_NOT_FOUND, ERR_DONOR_NOT_FOUND, ERR_REQUEST_NOT_FOUND,
    ERR_ITEM_NOT_FOUND, ERR_RECEIPT_NOT_FOUND, ERR_INVOICE_NOT_FOUND, or
    ERR_PLAN_NOT_FOUND as appropriate"

    Design: Corner/entities/get_partner_nonexistent_returns_not_found
    """
    res = api.get_partner(NON_EXISTENT_UUID, PLATFORM)
    validate_error(res, "ERR_PARTNER_NOT_FOUND", expected_status=404)


def test_declared_volume_and_free_flag_computed_from_items():
    """PRD §3.2: "The request's declared_volume_cf becomes the sum of volume_cf
    over all of its items — every item is included, since items are not
    individually removable."
    PRD §3.2: "The request's is_free_donation becomes true exactly when the
    disposition is DONATION and the declared volume is at most 50 cubic feet,
    and false otherwise."

    Design: Corner/entities/request_declared_volume_computed_from_items
    """
    partner = create_partner(accepted_categories=["FURNITURE"])
    donor = create_donor()
    request = create_request(donor["id"], partner["id"], disposition="DONATION")
    add_item(request["id"], donor["id"], category="FURNITURE", volume_cf=30)
    add_item(request["id"], donor["id"], category="FURNITURE", volume_cf=20)

    fetched = validate_success(api.get_pickup_request(request["id"], make_donor_headers(donor["id"])), 200)
    assert fetched["declared_volume_cf"] == 50
    assert fetched["is_free_donation"] is True
