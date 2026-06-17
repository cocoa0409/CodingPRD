"""RFQ and PartLine intake: creation, defaults, validation, derived fields, listing.

Translates queue B (Corner) section `entities` instances and the RFQ-intake
`state_machines` instances. All tests build their own entities from scratch.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_rfq_payload, create_part_line_payload,
    assert_rfq, assert_part_line, assert_inspection_station,
    create_draft_rfq, create_inspection_station_payload,
    TEST_USERS, ZERO_UUID,
)

ADMIN = TEST_USERS["shop_admin_headers"]
INSP = TEST_USERS["inspector_headers"]


def test_create_rfq_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created RFQ enters status DRAFT and its derived
    part_line_count begins at 0."
    PRD §3.1: "The shipping term incoterm is optional and defaults to EXW".

    Design: Corner/entities/create_rfq_returns_201_with_defaults
    """
    res = api.create_rfq(create_rfq_payload(customer_name="Acme", customer_id="C-1"), ADMIN)
    rfq = validate_success(res, 201)
    assert_rfq(rfq)
    assert rfq["status"] == "DRAFT", f"expected DRAFT, got {rfq['status']}"
    assert rfq["part_line_count"] == 0
    assert rfq["incoterm"] == "EXW"
    assert rfq["version"] == 1


def test_get_rfq_nonexistent_returns_not_found(api):
    """PRD §2.4: "The first identifier in the path that does not resolve to an
    existing resource causes the request to fail immediately with ERR_NOT_FOUND".

    Design: Corner/entities/get_rfq_nonexistent_returns_not_found
    """
    res = api.get_rfq(ZERO_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_part_line_missing_required_field_rejected(api):
    """PRD §2.9: "Request well-formedness — required fields present, enum values
    valid, and numeric ranges satisfied ... otherwise ERR_INVALID_REQUEST (422)."
    PRD §3.1: "Each part line names the part_number, the drawing revision
    drawing_rev, the material specification material_spec ... and the quantity".

    Design: Corner/entities/create_part_line_missing_required_field_rejected
    """
    rfq = create_draft_rfq(customer_id="C-2")
    payload = create_part_line_payload()
    del payload["material_spec"]
    res = api.create_part_line(rfq["id"], payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_part_line_invalid_enum_rejected(api):
    """PRD §3.1: "the material specification material_spec (one of AL_6061,
    SS_304, TI_6AL4V, or BRASS_360)".
    PRD §2.9: "enum values valid ... otherwise ERR_INVALID_REQUEST (422)".

    Design: Corner/entities/create_part_line_invalid_enum_rejected
    """
    rfq = create_draft_rfq(customer_id="C-3")
    res = api.create_part_line(
        rfq["id"], create_part_line_payload(material_spec="COPPER"), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_part_line_quantity_zero_rejected(api):
    """PRD §3.1: "the quantity of parts requested, which must be at least 1."
    PRD §2.9: "numeric ranges satisfied (for example part quantity at least 1
    ...); otherwise ERR_INVALID_REQUEST (422)."

    Design: Corner/entities/create_part_line_quantity_zero_rejected
    """
    rfq = create_draft_rfq(customer_id="C-4")
    res = api.create_part_line(
        rfq["id"], create_part_line_payload(quantity=0), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_part_line_default_tolerance_class_standard(api):
    """PRD §3.1: "The tolerance class tolerance_class is optional and defaults
    to STANDARD".

    Design: Corner/entities/part_line_default_tolerance_class_standard
    """
    rfq = create_draft_rfq(customer_id="C-5")
    payload = create_part_line_payload()
    del payload["tolerance_class"]
    res = api.create_part_line(rfq["id"], payload, ADMIN)
    pl = validate_success(res, 201)
    assert_part_line(pl)
    assert pl["tolerance_class"] == "STANDARD"


def test_rfq_part_line_count_derived_field_recomputes(api):
    """PRD §3.1: "Every time a part line is added, the RFQ's part_line_count is
    recomputed as the count of its part-line children — a derived field, so
    creating a part line raises the count by one."

    Design: Corner/entities/rfq_part_line_count_derived_field_recomputes
    """
    rfq = create_draft_rfq(customer_id="C-6")
    api.create_part_line(rfq["id"], create_part_line_payload(part_number="P-1"), ADMIN)
    api.create_part_line(
        rfq["id"], create_part_line_payload(part_number="P-2", material_spec="SS_304"), ADMIN)
    updated = validate_success(api.get_rfq(rfq["id"], ADMIN), 200)
    assert updated["part_line_count"] == 2


def test_inspection_station_immutable_no_version_field(api):
    """PRD §2.5: "An InspectionStation has no updated_at field and no version
    field, and it is never the target of an optimistic-concurrency check."
    PRD §3.5: "A station, being a configuration record, is immutable after
    creation and carries only id and created_at."

    Design: Corner/entities/inspection_station_immutable_no_version_field
    """
    res = api.create_inspection_station(
        create_inspection_station_payload(name="CMM-1", supports_mode="FAI", buffer_min=20), INSP)
    station = validate_success(res, 201)
    assert_inspection_station(station)
    assert station["name"] == "CMM-1"
    assert station["buffer_min"] == 20
    assert "version" not in station, "InspectionStation must not carry a version field"
    assert "updated_at" not in station, "InspectionStation must not carry an updated_at field"


def test_list_rfqs_pagination_envelope(api):
    """PRD §2.3: "List responses surface the pagination state in the meta object
    of the envelope through the fields limit, offset, total_count, and has_more."

    Design: Corner/entities/list_rfqs_pagination_envelope
    """
    create_draft_rfq(customer_name="A", customer_id="C-7a")
    create_draft_rfq(customer_name="B", customer_id="C-7b")
    data, meta = validate_paginated(api.list_rfqs(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
