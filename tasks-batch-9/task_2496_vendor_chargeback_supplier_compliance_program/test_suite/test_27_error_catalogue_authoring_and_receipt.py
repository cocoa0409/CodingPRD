"""Error catalogue: unknown identifiers, authoring guards, door quantities and the filing window.

Every test builds its own world from an empty database using only endpoints the
PRD declares.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CLOCK_PROGRAMME_START,
    GUIDE_EFFECTIVE_FROM,
    REQ_LBL_01,
    REQ_PKG_02,
    add_requirement,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    file_violation,
    publish_guide,
    read_guide,
    read_purchase_order,
    read_shipment,
    receipt_payload,
    receive_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_payload,
    violation_payload,
)

# ---------------------------------------------------------------------------
# Unknown identifiers on the eleven single-resource reads
# ---------------------------------------------------------------------------
def test_unknown_vendor_id_answers_vendor_not_found(api, officer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_vendor(NON_EXISTENT_UUID, officer_headers),
        ApiErrorId.ERR_VENDOR_NOT_FOUND,
    )


def test_unknown_routing_guide_id_answers_routing_guide_not_found(api, officer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_routing_guide(NON_EXISTENT_UUID, officer_headers),
        ApiErrorId.ERR_ROUTING_GUIDE_NOT_FOUND,
    )


def test_unknown_purchase_order_id_answers_purchase_order_not_found(api, buyer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_purchase_order(NON_EXISTENT_UUID, buyer_headers),
        ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND,
    )


def test_unknown_shipment_id_answers_shipment_not_found(api, inspector_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_shipment(NON_EXISTENT_UUID, inspector_headers),
        ApiErrorId.ERR_SHIPMENT_NOT_FOUND,
    )


def test_unknown_violation_id_answers_violation_not_found(api, inspector_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_violation(NON_EXISTENT_UUID, inspector_headers),
        ApiErrorId.ERR_VIOLATION_NOT_FOUND,
    )


def test_unknown_chargeback_id_answers_chargeback_not_found(api, accountant_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_chargeback(NON_EXISTENT_UUID, accountant_headers),
        ApiErrorId.ERR_CHARGEBACK_NOT_FOUND,
    )


def test_unknown_dispute_id_answers_dispute_not_found(api, officer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_dispute(NON_EXISTENT_UUID, officer_headers),
        ApiErrorId.ERR_DISPUTE_NOT_FOUND,
    )


def test_unknown_scorecard_id_answers_scorecard_not_found(api, officer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_scorecard(NON_EXISTENT_UUID, officer_headers),
        ApiErrorId.ERR_SCORECARD_NOT_FOUND,
    )


def test_unknown_corrective_action_plan_id_answers_cap_not_found(api, officer_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_cap(NON_EXISTENT_UUID, officer_headers),
        ApiErrorId.ERR_CAP_NOT_FOUND,
    )


def test_unknown_deduction_id_answers_deduction_not_found(api, accountant_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_deduction(NON_EXISTENT_UUID, accountant_headers),
        ApiErrorId.ERR_DEDUCTION_NOT_FOUND,
    )


def test_unknown_recovery_allocation_id_answers_allocation_not_found(
    api, accountant_headers
):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."

    Design: Corner/errors/corner_every_entity_not_found_code_is_triggerable
    """
    validate_error(
        api.get_allocation(NON_EXISTENT_UUID, accountant_headers),
        ApiErrorId.ERR_ALLOCATION_NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# Authoring-time uniqueness and publish readiness
# ---------------------------------------------------------------------------
def _draft_guide_world():
    """One supplier holding vendor code V-2055 and one DRAFT edition with no
    requirements yet."""
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2055",
        legal_name="Duplicode Dry Goods",
        payment_terms_days=30,
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from=GUIDE_EFFECTIVE_FROM,
    )
    return vendor, guide


def test_second_supplier_reusing_a_vendor_code_is_refused(api, officer_headers):
    """PRD §3.1: "A code already held by another supplier is refused with
    `ERR_VENDOR_CODE_TAKEN`."

    Design: Corner/errors/corner_authoring_uniqueness_and_publish_readiness_codes_are_triggerable
    """
    vendor, _guide = _draft_guide_world()

    validate_error(
        api.create_vendor(
            vendor_payload(
                vendor_code="V2055",
                legal_name="Duplicode Dry Goods (second entry)",
                payment_terms_days=45,
            ),
            officer_headers,
        ),
        ApiErrorId.ERR_VENDOR_CODE_TAKEN,
    )

    rows, _meta = validate_paginated(api.list_vendors(officer_headers))
    holders = [row for row in rows if row["vendor_code"] == "V2055"]
    assert len(holders) == 1, f"vendor code V-2055 must be held once, got {len(holders)}"
    assert holders[0]["id"] == vendor["id"], "the original supplier must keep the code"


def test_publishing_a_requirementless_draft_is_refused_and_leaves_it_draft(
    api, officer_headers
):
    """PRD §3.2: "The edition must own at least one requirement, so a
    `requirement_count` of 0 is refused with `ERR_GUIDE_HAS_NO_REQUIREMENTS`."
    PRD §3.2: "The first link moves the edition `DRAFT → PUBLISHED`, stamps
    `published_at` with the current logical clock and records the acting operator
    in `published_by_user_id`."

    Design: Corner/errors/corner_authoring_uniqueness_and_publish_readiness_codes_are_triggerable
    """
    _vendor, guide = _draft_guide_world()

    validate_error(
        api.publish_routing_guide(guide["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_HAS_NO_REQUIREMENTS,
    )
    refused = read_guide(guide["id"])
    assert refused["status"] == "DRAFT", (
        f"a refused publication must leave the edition DRAFT, got {refused['status']}"
    )

    add_requirement(guide["id"], dict(REQ_LBL_01))
    published = validate_success(api.publish_routing_guide(guide["id"], officer_headers))
    assert published["status"] == "PUBLISHED", (
        f"an edition owning one requirement must publish, got {published['status']}"
    )


def test_requirement_code_reused_within_the_same_edition_is_refused(
    api, officer_headers
):
    """PRD §3.2: "The `requirement_code` — values such as `ASN_LATE` or
    `GS1_LABEL_MISSING` — is 1 to 32 characters and must be unique within the
    owning edition, with a collision refused as `ERR_REQUIREMENT_CODE_TAKEN`."
    PRD §3.2: "A new requirement is created with `effective_until` null and
    raises its owning edition's `requirement_count` by one."

    Design: Corner/errors/corner_authoring_uniqueness_and_publish_readiness_codes_are_triggerable
    """
    _vendor, guide = _draft_guide_world()
    first = add_requirement(guide["id"], dict(REQ_LBL_01))

    validate_error(
        api.create_requirement(
            guide["id"],
            {
                "requirement_code": "LBL-01",
                "domain": "PACKAGING",
                "severity_tier": "TIER_3",
                "min_evidence_count": 0,
                "fixed_fee_cents": 100,
                "per_unit_recovery_cents": 1,
                "handling_pct": 0.50,
                "min_fee_cents": 0,
                "cap_cents": 1000,
            },
            officer_headers,
        ),
        ApiErrorId.ERR_REQUIREMENT_CODE_TAKEN,
    )

    rows, meta = validate_paginated(api.list_requirements(guide["id"], officer_headers))
    assert meta["total_count"] == 1, (
        f"the refused collision must not create a second row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]
    assert rows[0]["domain"] == "LABELING", (
        f"the surviving requirement keeps its own domain, got {rows[0]['domain']}"
    )


# ---------------------------------------------------------------------------
# Door quantities: receipt against shipped, findings against received
# ---------------------------------------------------------------------------
def _shipment_awaiting_receipt():
    """A supplier with a PUBLISHED edition carrying LBL-01, and one IN_TRANSIT
    shipment of 1000 units against a 1000-unit order."""
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2056", legal_name="Quantity Quilts", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from=GUIDE_EFFECTIVE_FROM,
    )
    requirement = add_requirement(
        guide["id"], dict(REQ_LBL_01, min_evidence_count=0)
    )
    publish_guide(guide["id"])
    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    return {
        "vendor": vendor,
        "requirement": requirement,
        "po": po,
        "shipment": shipment,
    }


def test_receipt_larger_than_the_shipped_quantity_is_refused(api, inspector_headers):
    """PRD §3.3: "The inspector posts the counted quantity as `received_units`,
    which may be zero or more but may never exceed the shipment's
    `shipped_units`; an excess is refused with `ERR_RECEIPT_EXCEEDS_SHIPPED`."

    Design: Corner/errors/corner_receipt_and_violation_quantity_codes_are_triggerable
    """
    world = _shipment_awaiting_receipt()

    validate_error(
        api.receive_shipment(
            world["shipment"]["id"], receipt_payload(1200), inspector_headers
        ),
        ApiErrorId.ERR_RECEIPT_EXCEEDS_SHIPPED,
    )


def test_short_receipt_is_stored_and_leaves_the_order_partially_received(
    api, inspector_headers
):
    """PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.3: "The order's `status` follows: it moves `OPEN → PARTIALLY_RECEIVED`
    when the recomputed `received_units` is at least 1 but still below
    `ordered_units`, and it advances to `RECEIVED` once the recomputed
    `received_units` reaches or exceeds `ordered_units`."

    Design: Corner/errors/corner_receipt_and_violation_quantity_codes_are_triggerable
    """
    world = _shipment_awaiting_receipt()

    received = validate_success(
        api.receive_shipment(
            world["shipment"]["id"], receipt_payload(600), inspector_headers
        )
    )
    assert received["status"] == "RECEIVED", (
        f"the counted shipment advances to RECEIVED, got {received['status']}"
    )
    assert received["received_units"] == 600, (
        f"received_units must store the counted quantity, got {received['received_units']}"
    )

    order = read_purchase_order(world["po"]["id"])
    assert order["status"] == "PARTIALLY_RECEIVED", (
        f"600 of 1000 ordered units leaves the order PARTIALLY_RECEIVED, "
        f"got {order['status']}"
    )


def test_violation_citing_an_unknown_requirement_is_refused(api, inspector_headers):
    """PRD §3.4: "The `requirement_id` must resolve, or the answer is
    `ERR_REQUIREMENT_NOT_FOUND`."

    Design: Corner/errors/corner_receipt_and_violation_quantity_codes_are_triggerable
    """
    world = _shipment_awaiting_receipt()
    receive_shipment(world["shipment"]["id"], 600)

    validate_error(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                NON_EXISTENT_UUID,
                affected_units=100,
                affected_cartons=4,
                narrative="Cites a requirement that does not exist.",
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_REQUIREMENT_NOT_FOUND,
    )


def test_affected_units_beyond_the_counted_receipt_are_refused(api, inspector_headers):
    """PRD §3.4: "`affected_units` must be zero or more and no greater than the
    shipment's `received_units`; `affected_cartons` must be zero or more and no
    greater than the shipment's `carton_count`; a breach of either bound is
    refused with `ERR_AFFECTED_UNITS_EXCEED_RECEIPT`."

    Design: Corner/errors/corner_receipt_and_violation_quantity_codes_are_triggerable
    """
    world = _shipment_awaiting_receipt()
    receive_shipment(world["shipment"]["id"], 600)

    validate_error(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                world["requirement"]["id"],
                affected_units=700,
                affected_cartons=28,
                narrative="Claims more affected units than were received.",
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_AFFECTED_UNITS_EXCEED_RECEIPT,
    )


def test_second_finding_citing_the_same_requirement_code_is_a_duplicate(
    api, inspector_headers, officer_headers
):
    """PRD §3.4: "A filing is refused with `ERR_DUPLICATE_VIOLATION` when another
    violation on the same shipment already cites the same `requirement_code` and
    is in `DETECTED`, `EVIDENCE_COMPLETE` or `CHARGED`."

    Design: Corner/errors/corner_receipt_and_violation_quantity_codes_are_triggerable
    """
    world = _shipment_awaiting_receipt()
    receive_shipment(world["shipment"]["id"], 600)

    first = validate_success(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                world["requirement"]["id"],
                affected_units=100,
                affected_cartons=4,
                narrative="Unreadable labels on four cartons.",
            ),
            inspector_headers,
        ),
        expected_status=201,
    )
    assert first["affected_units"] == 100

    validate_error(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                world["requirement"]["id"],
                affected_units=50,
                affected_cartons=2,
                narrative="Second filing for the same requirement.",
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_VIOLATION,
    )

    _rows, meta = validate_paginated(
        api.list_violations(officer_headers, params={"shipment_id": world["shipment"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the duplicate must not create a second finding, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The 72-hour filing window
# ---------------------------------------------------------------------------
def _received_shipment_for_window():
    """A 1000-unit shipment received at exactly 2026-08-10T00:00:00Z, under an
    edition carrying two requirements so two distinct findings are possible."""
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2057", legal_name="Windowclose Wares", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from=GUIDE_EFFECTIVE_FROM,
    )
    packaging = add_requirement(guide["id"], dict(REQ_PKG_02, min_evidence_count=0))
    labeling = add_requirement(guide["id"], dict(REQ_LBL_01, min_evidence_count=0))
    publish_guide(guide["id"])
    set_clock("2026-08-09T00:00:00Z")
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-08T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    set_clock("2026-08-10T00:00:00Z")
    shipment = receive_shipment(shipment["id"], 1000)
    return {
        "vendor": vendor,
        "packaging": packaging,
        "labeling": labeling,
        "po": po,
        "shipment": shipment,
    }


def test_finding_filed_one_second_inside_the_window_is_accepted(
    api, inspector_headers
):
    """PRD §3.4: "And the filing window must still be open: the current logical
    clock must be strictly earlier than 72 hours — three days — after the
    shipment's `arrived_at`. At exactly 72 hours the window is already closed,
    and a late filing is refused with `ERR_VIOLATION_FILING_WINDOW_CLOSED`."
    PRD §3.4: "A newly filed violation records `detected_at` from the current
    logical clock and `detected_by_user_id` from the acting inspector's
    `X-User-ID`, takes its `shipment_id` from the path, pins the supplied
    `requirement_id`, starts with `evidence_count` 0 and `void_reason` null, and
    raises both the shipment's `open_violation_count` and the supplier's
    `open_violation_count` by one."

    Design: Corner/errors/corner_violation_filing_window_closes_exactly_at_seventy_two_hours
    """
    world = _received_shipment_for_window()
    arrival = read_shipment(world["shipment"]["id"])["arrived_at"]
    assert arrival.startswith("2026-08-10T00:00:00"), (
        f"the receipt must be stamped at the receiving clock, got {arrival}"
    )

    set_clock("2026-08-12T23:59:59Z")
    filed = validate_success(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                world["packaging"]["id"],
                affected_units=100,
                affected_cartons=4,
                narrative="Filed one second inside the window.",
            ),
            inspector_headers,
        ),
        expected_status=201,
    )
    assert filed["detected_at"].startswith("2026-08-12T23:59:59"), (
        f"detected_at reads the logical clock, got {filed['detected_at']}"
    )


def test_finding_filed_at_exactly_seventy_two_hours_is_refused(
    api, inspector_headers, officer_headers
):
    """PRD §3.4: "And the filing window must still be open: the current logical
    clock must be strictly earlier than 72 hours — three days — after the
    shipment's `arrived_at`. At exactly 72 hours the window is already closed,
    and a late filing is refused with `ERR_VIOLATION_FILING_WINDOW_CLOSED`."

    Design: Corner/errors/corner_violation_filing_window_closes_exactly_at_seventy_two_hours
    """
    world = _received_shipment_for_window()

    set_clock("2026-08-12T23:59:59Z")
    file_violation(
        world["shipment"]["id"],
        world["packaging"]["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Filed one second inside the window.",
    )

    set_clock("2026-08-13T00:00:00Z")
    validate_error(
        api.create_violation(
            world["shipment"]["id"],
            violation_payload(
                world["labeling"]["id"],
                affected_units=100,
                affected_cartons=4,
                narrative="Filed exactly at the 72-hour mark.",
            ),
            inspector_headers,
        ),
        ApiErrorId.ERR_VIOLATION_FILING_WINDOW_CLOSED,
    )

    _rows, meta = validate_paginated(
        api.list_violations(
            officer_headers, params={"shipment_id": world["shipment"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the in-window finding may exist, got {meta['total_count']}"
    )
