"""Record creation, single-resource reads and collection reads.

These tests cover what the programme stores when a row is minted, what it gives
back when that row is read, and how the collection reads carry their pagination
envelope and filters.  Every test builds its own world from an empty database
using only the endpoints the PRD declares.
"""
import pytest

from test_helpers import (
    CLOCK_PROGRAMME_START,
    CLOCK_RECEIPT_DAY,
    GUIDE_EFFECTIVE_FROM,
    INSPECTOR_USER_ID,
    NON_EXISTENT_UUID,
    REQ_LBL_01,
    REQ_SHP_04,
    ApiErrorId,
    add_allocation,
    add_evidence,
    add_requirement,
    assess_violation,
    create_deduction,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    file_violation,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_vendor_headers,
    purchase_order_payload,
    read_chargeback,
    read_deduction,
    read_purchase_order,
    read_shipment,
    read_violation,
    receive_shipment,
    publish_guide,
    scorecard_payload,
    set_clock,
    setup_detected_violation,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant_is(actual, expected_instant):
    """Instants are ISO-8601 UTC; the programme carries three fractional digits,
    so compare on the second rather than on the serialisation."""
    return isinstance(actual, str) and actual.startswith(expected_instant.rstrip("Z"))


def _two_chargeback_world(vendor_code, legal_name, payment_terms_days):
    """One supplier, one published edition holding a TIER_1 shipment requirement
    and a TIER_1 labelling requirement, one fully received 1000-unit shipment at
    500 cents a unit, and two assessed chargebacks against it."""
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code=vendor_code,
        legal_name=legal_name,
        payment_terms_days=payment_terms_days,
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from=GUIDE_EFFECTIVE_FROM,
    )
    req_shp = add_requirement(guide["id"], REQ_SHP_04)
    req_lbl = add_requirement(guide["id"], REQ_LBL_01)
    publish_guide(guide["id"])

    set_clock(CLOCK_RECEIPT_DAY)
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment["id"], 1000)

    violation_one = file_violation(
        shipment["id"],
        req_shp["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="Late ASN.",
    )
    add_evidence(
        violation_one["id"], kind="DOCUMENT", reference_uri="s3://evidence/1/a.pdf"
    )
    add_evidence(
        violation_one["id"], kind="MEASUREMENT", reference_uri="s3://evidence/1/b.csv"
    )
    chargeback_one = assess_violation(violation_one["id"], assessment_note="Late ASN.")

    violation_two = file_violation(
        shipment["id"],
        req_lbl["id"],
        affected_units=500,
        affected_cartons=20,
        narrative="Unreadable GS1-128 labels.",
    )
    add_evidence(
        violation_two["id"], kind="PHOTO", reference_uri="s3://evidence/2/a.jpg"
    )
    add_evidence(violation_two["id"], kind="SCAN", reference_uri="s3://evidence/2/b.txt")
    chargeback_two = assess_violation(
        violation_two["id"], assessment_note="Label scan failures."
    )

    return {
        "vendor": vendor,
        "guide": guide,
        "requirement_shipment": req_shp,
        "requirement_labeling": req_lbl,
        "po": po,
        "shipment": shipment,
        "chargeback_one": chargeback_one,
        "chargeback_two": chargeback_two,
    }


def test_vendor_registration_returns_the_declared_supplier_record(api, officer_headers):
    """PRD §3.1: "A supplier enters the programme when a `ComplianceOfficer`
    registers it with three pieces of information: a `vendor_code`, the
    retailer-assigned supplier code of between 1 and 16 characters drawn from
    uppercase letters and digits and unique across the whole programme; a
    `legal_name` of between 1 and 160 characters naming the legal entity; and
    `payment_terms_days`, an integer between 1 and 120 recording the net payment
    terms that apply when a deduction is later netted against that supplier's
    payables."
    PRD §3.1: "A newly registered supplier begins in `ACTIVE` sourcing posture
    with a clean sheet: `otif_score` 0.00, `open_chargeback_cents`,
    `recovered_lifetime_cents`, `refund_due_cents`, `open_violation_count` and
    `open_cap_count` all zero, and both governance flags —
    `repeat_offender_flag` and `exposure_alert_flag` — false."
    PRD §2.5: "Most resources additionally carry an `updated_at`, in the same
    timestamp format, refreshed on every mutation, and a `version`, an integer
    that starts at 1 on creation and increments by one on every mutation —
    including mutations the client did not request directly, such as a parent
    whose derived totals were recomputed by a cascade."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/corner_vendor_creation_returns_all_declared_fields
    """
    set_clock(CLOCK_PROGRAMME_START)

    response = api.create_vendor(
        {
            "vendor_code": "V2001",
            "legal_name": "Cornerstone Creations",
            "payment_terms_days": 45,
        },
        officer_headers,
    )
    vendor = validate_success(response, 201)

    assert response.json()["response_type"] == "object", (
        "a single supplier read is an object envelope"
    )
    assert is_valid_uuid(vendor["id"]), f"id must be a server-minted UUID: {vendor['id']!r}"
    assert is_iso8601_timestamp(vendor["created_at"])
    assert is_iso8601_timestamp(vendor["updated_at"])
    assert vendor["vendor_code"] == "V2001"
    assert vendor["legal_name"] == "Cornerstone Creations"
    assert vendor["payment_terms_days"] == 45
    assert vendor["status"] == "ACTIVE", "a new supplier begins ACTIVE"
    assert float(vendor["otif_score"]) == pytest.approx(0.00), (
        "otif_score reads 0.00 until a scorecard has been finalized"
    )
    assert vendor["open_chargeback_cents"] == 0
    assert vendor["recovered_lifetime_cents"] == 0
    assert vendor["refund_due_cents"] == 0
    assert vendor["open_violation_count"] == 0
    assert vendor["open_cap_count"] == 0
    assert vendor["repeat_offender_flag"] is False
    assert vendor["exposure_alert_flag"] is False
    assert vendor["version"] == 1, "version starts at 1 on creation"


def test_routing_guide_read_returns_the_drafted_row(api, officer_headers):
    """PRD §3.2: "A freshly drafted edition is `DRAFT`, with `requirement_count`
    0, `effective_until` null, and `published_at` and `published_by_user_id`
    both null."
    PRD §3.2: "An optional `supersedes_guide_id` names the currently published
    edition this one is intended to retire; it is left null for the first
    edition on a timeline, and because it points at another guide the chain it
    forms is self-referential."
    PRD §3.2: "A new requirement is created with `effective_until` null and
    raises its owning edition's `requirement_count` by one."

    Design: Corner/entities/corner_routing_guide_retrieval_returns_stored_row
    """
    set_clock(CLOCK_PROGRAMME_START)
    guide = create_guide(
        guide_code="RG-2026-R",
        title="Retrieval Guide",
        scope_code="LABELING",
        effective_from="2026-09-01T00:00:00Z",
    )
    add_requirement(guide["id"], REQ_LBL_01)

    stored = validate_success(api.get_routing_guide(guide["id"], officer_headers), 200)

    assert stored["guide_code"] == "RG-2026-R"
    assert stored["scope_code"] == "LABELING"
    assert _instant_is(stored["effective_from"], "2026-09-01T00:00:00"), (
        f"effective_from should be the drafted instant, got {stored['effective_from']!r}"
    )
    assert stored["effective_until"] is None, "a DRAFT edition is open-ended above"
    assert stored["supersedes_guide_id"] is None
    assert stored["status"] == "DRAFT"
    assert stored["requirement_count"] == 1, "one requirement raises the count to 1"
    assert stored["published_at"] is None
    assert stored["published_by_user_id"] is None


def test_chargeback_listing_carries_pagination_meta_and_honours_filters(
    api, accountant_headers
):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
    and `has_more` in the envelope's `meta` object, where `total_count` is the
    size of the filtered result set before the pagination window is applied and
    `has_more` states whether any item remains beyond that window."
    PRD §2.4: "Chargebacks are ordered by `assessed_at` and then `created_at`,
    and because a chargeback carries two independent state dimensions they may
    be filtered on either or both — `dispute_status` and `settlement_status` —
    as well as by `vendor_id`, `violation_id` and `requirement_id`."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."

    Design: Corner/entities/corner_chargeback_listing_is_paginated_and_filterable
    """
    world = _two_chargeback_world("V2003", "Pagination Partners", 60)
    vendor_id = world["vendor"]["id"]
    first_id = world["chargeback_one"]["id"]
    second_id = world["chargeback_two"]["id"]

    rows, meta = validate_paginated(
        api.list_chargebacks(accountant_headers, params={"vendor_id": vendor_id})
    )
    assert meta["total_count"] == 2, f"expected two chargebacks, meta was {meta}"
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {first_id, second_id}

    by_id = {row["id"]: row for row in rows}
    assert by_id[first_id]["gross_assessed_cents"] == 425000
    assert by_id[second_id]["gross_assessed_cents"] == 40000
    assert by_id[second_id]["cost_recovery_cents"] == 25000

    _, recovered_meta = validate_paginated(
        api.list_chargebacks(
            accountant_headers,
            params={"vendor_id": vendor_id, "settlement_status": "RECOVERED"},
        )
    )
    assert recovered_meta["total_count"] == 0, (
        "neither chargeback has been recovered, so the RECOVERED filter is empty"
    )

    _, requirement_meta = validate_paginated(
        api.list_chargebacks(
            accountant_headers,
            params={"requirement_id": world["requirement_labeling"]["id"]},
        )
    )
    assert requirement_meta["total_count"] == 1, (
        "one chargeback pinned the labelling requirement"
    )


def test_violation_read_with_unknown_id_is_not_found(api, inspector_headers):
    """PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/corner_violation_not_found_for_unknown_id
    """
    set_clock(CLOCK_PROGRAMME_START)

    response = api.get_violation(NON_EXISTENT_UUID, inspector_headers)

    assert response.status_code == 404, (
        f"an id that was never minted must be a 404, got {response.status_code}"
    )
    assert response.json()["response_type"] == "error"
    error = validate_error(response, ApiErrorId.ERR_VIOLATION_NOT_FOUND.value, 404)
    assert error["message"].strip(), "the error envelope carries a human-readable message"


def test_purchase_order_without_ordered_units_is_rejected(
    api, buyer_headers, officer_headers
):
    """PRD §2.7: "Request shape — every required body field is present, every
    value has the correct type, every enumerated value is a declared member, and
    every numeric range is honoured; otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.3: "A `CategoryBuyer` raises a purchase order naming the supplier
    through a payload containing that supplier's `vendor_id`, together with a
    `po_number` of 1 to 32 characters, `ordered_units` of at least 1, and
    `unit_cost_cents` of at least 1 representing landed cost per unit."
    PRD §2.4: "Purchase orders are ordered by `created_at` descending and
    filterable by `vendor_id` and `status`; the shipments raised against one
    purchase order are ordered by `created_at` ascending and filterable by
    `status`."

    Design: Corner/entities/corner_purchase_order_missing_required_fields_returns_invalid_request
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2005",
        legal_name="Missingfield Mercantile",
        payment_terms_days=30,
    )

    payload = purchase_order_payload(vendor["id"], po_number="PO-BAD")
    payload.pop("ordered_units")

    response = api.create_purchase_order(payload, buyer_headers)

    assert response.status_code == 400, (
        f"omitting ordered_units must be a 400, got {response.status_code}"
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_purchase_orders(officer_headers, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 0, "a rejected request stores no purchase order"


def test_scorecard_tolerance_inputs_default_when_omitted(api, officer_headers):
    """PRD §3.7: "Three tolerance inputs are optional and default when omitted:
    `tolerance_early_days`, the number of days before the contractual deadline
    that still counts as on time, defaulting to 2 and constrained to 0 through
    14; `tolerance_late_days`, the number of days after the deadline that still
    counts as on time, defaulting to 0 and likewise constrained to 0 through 14;
    and `fill_tolerance_pct`, the shortfall percentage tolerated before an order
    fails in full, defaulting to 2.00, constrained to 0.00 through 10.00 and
    carried to two decimals."
    PRD §3.7: "A new scorecard opens in `OPEN` with `measurement_variant` null,
    `measured_at` null, `finalized_at` null, `cap_required` false, and all
    measurement outputs — `measured_po_count`, `on_time_count`, `in_full_count`,
    `otif_count`, `on_time_pct`, `fill_rate_pct`, `otif_pct` and
    `composite_score` — at zero."

    Design: Corner/entities/corner_scorecard_tolerance_defaults_applied_when_omitted
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2006",
        legal_name="Defaultly Distributors",
        payment_terms_days=30,
    )

    defaulted = validate_success(
        api.create_scorecard(
            scorecard_payload(
                vendor["id"],
                period_code="2026-05",
                period_start="2026-05-01T00:00:00Z",
                period_end="2026-05-31T00:00:00Z",
            ),
            officer_headers,
        ),
        201,
    )

    assert defaulted["tolerance_early_days"] == 2
    assert defaulted["tolerance_late_days"] == 0
    assert float(defaulted["fill_tolerance_pct"]) == pytest.approx(2.00)
    assert defaulted["status"] == "OPEN"
    assert defaulted["cap_required"] is False
    assert defaulted["measurement_variant"] is None

    explicit = validate_success(
        api.create_scorecard(
            scorecard_payload(
                vendor["id"],
                period_code="2026-07",
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
                tolerance_early_days=5,
                tolerance_late_days=3,
                fill_tolerance_pct=0.50,
            ),
            officer_headers,
        ),
        201,
    )

    assert explicit["tolerance_early_days"] == 5
    assert explicit["tolerance_late_days"] == 3
    assert float(explicit["fill_tolerance_pct"]) == pytest.approx(0.50)


def test_receipt_values_the_shipment_from_counted_units(api, inspector_headers):
    """PRD §3.3: "A shipment is created `IN_TRANSIT`, taking its owning `po_id`
    from the path, with `received_units` null, `arrived_at` null,
    `invoice_value_cents` 0, `open_violation_count` 0 and
    `evidence_capture_count` 0."
    PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.3: "The order's `received_units` is recomputed as the sum of
    `received_units` over its shipments whose `status` is `RECEIVED`, and its
    `first_receipt_at` as the earliest `arrived_at` among those same shipments,
    remaining null while none has been received."
    PRD §3.3: "The order's `status` follows: it moves `OPEN →
    PARTIALLY_RECEIVED` when the recomputed `received_units` is at least 1 but
    still below `ordered_units`, and it advances to `RECEIVED` once the
    recomputed `received_units` reaches or exceeds `ordered_units`."

    Design: Corner/entities/corner_shipment_invoice_value_is_computed_at_receipt
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2007", legal_name="Computeco Imports", payment_terms_days=30
    )
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )

    in_transit = read_shipment(shipment["id"])
    assert in_transit["status"] == "IN_TRANSIT"
    assert in_transit["invoice_value_cents"] == 0, (
        "invoice value is derived at the door, not from the advice"
    )
    assert in_transit["received_units"] is None

    set_clock(CLOCK_RECEIPT_DAY)
    received = validate_success(
        api.receive_shipment(shipment["id"], {"received_units": 900}, inspector_headers),
        200,
    )

    assert received["status"] == "RECEIVED"
    assert received["received_units"] == 900
    assert _instant_is(received["arrived_at"], "2026-08-10T00:00:00"), (
        f"arrived_at should be the logical clock, got {received['arrived_at']!r}"
    )
    assert received["invoice_value_cents"] == 450000, (
        "900 counted units at 500 cents each is 450000 cents"
    )

    order = read_purchase_order(po["id"])
    assert order["received_units"] == 900
    assert _instant_is(order["first_receipt_at"], "2026-08-10T00:00:00")
    assert order["status"] == "PARTIALLY_RECEIVED", (
        "900 counted units is at least 1 but below the 1000 ordered"
    )


def test_violation_evidence_capture_stamps_server_fields(api, inspector_headers):
    """PRD §3.4: "Each item declares a `kind` — one of `PHOTO`, `SCAN`,
    `MEASUREMENT` or `DOCUMENT` — a `reference_uri` of 1 to 300 characters
    pointing immutably at the stored artefact, and an optional `note` annotation
    which defaults to null when omitted."
    PRD §3.4: "The stored item records `captured_by_user_id` from the acting
    `X-User-ID` and `captured_at` from the current logical clock, carries
    `subject_type` `VIOLATION` with the owning `violation_id` set and
    `dispute_id` null, and is never modified thereafter."
    PRD §3.4: "Each capture raises the violation's `evidence_count` by one and
    the shipment's `evidence_capture_count` by one."
    PRD §3.4: "As soon as `evidence_count` reaches or exceeds the pinned
    requirement's `min_evidence_count`, the violation is promoted `DETECTED →
    EVIDENCE_COMPLETE` in the same request and its `version` is incremented."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/entities/corner_evidence_item_system_fields_are_server_stamped
    """
    world = setup_detected_violation(
        REQ_LBL_01,
        affected_units=500,
        affected_cartons=20,
        narrative="Unreadable labels.",
        vendor_overrides={
            "vendor_code": "V2008",
            "legal_name": "Stampwell Supply",
            "payment_terms_days": 30,
        },
    )
    violation_id = world["violation"]["id"]

    item = validate_success(
        api.add_violation_evidence(
            violation_id,
            {
                "kind": "PHOTO",
                "reference_uri": "s3://evidence/lbl/face.jpg",
                "note": "Carton 12 face label.",
            },
            inspector_headers,
        ),
        201,
    )

    assert item["violation_id"] == violation_id, "the owning violation comes from the path"
    assert item["dispute_id"] is None
    assert item["subject_type"] == "VIOLATION"
    assert item["kind"] == "PHOTO"
    assert item["note"] == "Carton 12 face label."
    assert item["captured_by_user_id"] == INSPECTOR_USER_ID, (
        "captured_by_user_id is stamped from the acting X-User-ID"
    )
    assert _instant_is(item["captured_at"], "2026-08-10T00:00:00"), (
        f"captured_at should be the logical clock, got {item['captured_at']!r}"
    )

    violation = read_violation(violation_id)
    assert violation["evidence_count"] == 1
    assert violation["status"] == "DETECTED", (
        "one item of the two the requirement demands leaves the finding DETECTED"
    )
    assert read_shipment(world["shipment"]["id"])["evidence_capture_count"] == 1


def test_requirement_with_undeclared_domain_is_rejected(api, officer_headers):
    """PRD §3.2: "The `domain` places the requirement in one of `SHIPMENT`,
    `LABELING`, `PACKAGING` or `DOCUMENTATION`."
    PRD §3.2: "`min_evidence_count`, an integer from 0 to 5, is the number of
    evidence items that must exist before a breach of this requirement may be
    assessed; a value of 0 means evidence is optional for this requirement."
    PRD §2.7: "Request shape — every required body field is present, every value
    has the correct type, every enumerated value is a declared member, and every
    numeric range is honoured; otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "A freshly drafted edition is `DRAFT`, with `requirement_count` 0,
    `effective_until` null, and `published_at` and `published_by_user_id` both
    null."

    Design: Corner/entities/corner_requirement_invalid_enum_domain_is_rejected
    """
    set_clock(CLOCK_PROGRAMME_START)
    guide = create_guide(
        guide_code="RG-2026-E",
        title="Enum Guide",
        scope_code="ALL",
        effective_from="2026-09-01T00:00:00Z",
    )

    undeclared_domain = api.create_requirement(
        guide["id"],
        {
            "requirement_code": "FRT-01",
            "domain": "FREIGHT",
            "severity_tier": "TIER_1",
            "min_evidence_count": 1,
            "fixed_fee_cents": 10000,
            "per_unit_recovery_cents": 10,
            "handling_pct": 1.00,
            "min_fee_cents": 10000,
            "cap_cents": 50000,
        },
        officer_headers,
    )
    assert undeclared_domain.status_code == 400, (
        f"FREIGHT is not a declared domain, got {undeclared_domain.status_code}"
    )
    validate_error(undeclared_domain, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    out_of_range_evidence = api.create_requirement(
        guide["id"],
        {
            "requirement_code": "LBL-01",
            "domain": "LABELING",
            "severity_tier": "TIER_1",
            "min_evidence_count": 6,
            "fixed_fee_cents": 10000,
            "per_unit_recovery_cents": 10,
            "handling_pct": 1.00,
            "min_fee_cents": 10000,
            "cap_cents": 50000,
        },
        officer_headers,
    )
    assert out_of_range_evidence.status_code == 400, (
        f"min_evidence_count 6 is outside 0..5, got {out_of_range_evidence.status_code}"
    )
    validate_error(out_of_range_evidence, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    stored = validate_success(api.get_routing_guide(guide["id"], officer_headers), 200)
    assert stored["requirement_count"] == 0, "no requirement was stored"

    _, meta = validate_paginated(api.list_requirements(guide["id"], officer_headers))
    assert meta["total_count"] == 0


def test_violation_evidence_is_append_only_and_carries_no_version(
    api, inspector_headers, officer_headers
):
    """PRD §2.5: "The one exception is the evidence item: evidence is
    append-only audit history, so an evidence item carries only `id` and
    `created_at`. It has no `updated_at` and no `version`, there is no endpoint
    that modifies it, and nothing in the programme ever deletes one."
    PRD §3.4: "Each capture raises the violation's `evidence_count` by one and
    the shipment's `evidence_capture_count` by one."
    PRD §3.4: "As soon as `evidence_count` reaches or exceeds the pinned
    requirement's `min_evidence_count`, the violation is promoted `DETECTED →
    EVIDENCE_COMPLETE` in the same request and its `version` is incremented."

    Design: Corner/entities/corner_evidence_item_is_immutable_with_no_version_field
    """
    world = setup_detected_violation(
        REQ_LBL_01,
        affected_units=500,
        affected_cartons=20,
        narrative="Unreadable labels.",
        vendor_overrides={
            "vendor_code": "V2010",
            "legal_name": "Immutable Imports",
            "payment_terms_days": 30,
        },
    )
    violation_id = world["violation"]["id"]

    first = add_evidence(
        violation_id, kind="PHOTO", reference_uri="s3://evidence/lbl/first.jpg"
    )
    second = validate_success(
        api.add_violation_evidence(
            violation_id,
            {"kind": "SCAN", "reference_uri": "s3://evidence/lbl/second.txt"},
            inspector_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_violation_evidence(violation_id, officer_headers)
    )
    assert meta["total_count"] == 2, (
        f"the second capture appends rather than replaces, meta was {meta}"
    )
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    for row in rows:
        assert "version" not in row, "an evidence item carries no version"
        assert "updated_at" not in row, "an evidence item carries no updated_at"

    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["reference_uri"] == "s3://evidence/lbl/first.jpg"
    assert by_id[first["id"]]["kind"] == "PHOTO"
    assert by_id[second["id"]]["kind"] == "SCAN"

    violation = read_violation(violation_id)
    assert violation["evidence_count"] == 2
    assert violation["status"] == "EVIDENCE_COMPLETE", (
        "two items meet the requirement's minimum and promote the finding"
    )


def test_shipment_advice_requires_an_existing_purchase_order(api, officer_headers):
    """PRD §2.7: "Path existence — every identifier embedded in the URL
    resolves, checked left to right as described in §2.8; otherwise the
    not-found error for the first unresolved segment, at 404."
    PRD §2.8: "Each resource family has its own not-found error, all at 404:
    `ERR_VENDOR_NOT_FOUND`, `ERR_ROUTING_GUIDE_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_SCORECARD_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`
    and `ERR_ALLOCATION_NOT_FOUND`."
    PRD §3.3: "A shipment is created `IN_TRANSIT`, taking its owning `po_id`
    from the path, with `received_units` null, `arrived_at` null,
    `invoice_value_cents` 0, `open_violation_count` 0 and
    `evidence_capture_count` 0."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/entities/corner_shipment_creation_requires_an_existing_purchase_order
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2011", legal_name="Parentlink Producers", payment_terms_days=30
    )
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    vendor_headers = make_vendor_headers(vendor["id"])

    orphan = api.create_shipment(
        NON_EXISTENT_UUID,
        {"asn_number": "ASN-ORPHAN", "shipped_units": 100, "carton_count": 4},
        vendor_headers,
    )
    assert orphan.status_code == 404, (
        f"a shipment under an unknown order must be a 404, got {orphan.status_code}"
    )
    validate_error(orphan, ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND.value, 404)

    created = api.create_shipment(
        po["id"],
        {"asn_number": "ASN-1", "shipped_units": 1000, "carton_count": 40},
        vendor_headers,
    )
    shipment = validate_success(created, 201)
    assert shipment["po_id"] == po["id"], "the shipment takes its po_id from the path"
    assert shipment["status"] == "IN_TRANSIT"

    rows, meta = validate_paginated(api.list_po_shipments(po["id"], officer_headers))
    assert meta["total_count"] == 1, f"the order owns exactly one shipment, meta was {meta}"
    assert [row["id"] for row in rows] == [shipment["id"]]


def test_recovery_allocations_join_one_deduction_to_two_chargebacks(
    api, accountant_headers
):
    """PRD §3.9: "A new allocation is stored with `source_type` `DEDUCTION`,
    `effective_status` `PENDING`, `remittance_reference` null, `applied_at` null
    and `applied_by_user_id` from the acting accountant, and it raises the
    deduction's `amount_cents` by the allocated amount and its
    `allocation_count` by one."
    PRD §3.9: "A pending allocation contributes nothing to any chargeback's
    recovery; it is an intention, not a recovery."
    PRD §2.4: "Recovery allocations — the junction read that reconciles the
    many-to-many graph of chargebacks against deductions — are ordered by
    `applied_at` and then `created_at`, filterable by `chargeback_id`,
    `deduction_id`, `source_type` and `effective_status`."
    PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."
    PRD §3.5: "It opens with `reversal_cents` 0, `recovered_cents` 0,
    `outstanding_cents` equal to `gross_assessed_cents`, `deduction_posted`
    false, `dispute_status` `NONE` and `settlement_status` `ASSESSED`."

    Design: Corner/entities/corner_recovery_allocation_junction_joins_deduction_and_chargeback
    """
    world = _two_chargeback_world("V2012", "Junction Jobbers", 60)
    first_id = world["chargeback_one"]["id"]
    second_id = world["chargeback_two"]["id"]

    deduction = create_deduction(
        world["vendor"]["id"], invoice_reference="INV-JUNCTION"
    )
    first_allocation = add_allocation(deduction["id"], first_id, 100000)
    second_allocation = add_allocation(deduction["id"], second_id, 40000)

    assert first_allocation["deduction_id"] == deduction["id"]
    assert first_allocation["chargeback_id"] == first_id
    assert second_allocation["deduction_id"] == deduction["id"]
    assert second_allocation["chargeback_id"] == second_id
    assert first_allocation["source_type"] == "DEDUCTION"
    assert second_allocation["source_type"] == "DEDUCTION"
    assert first_allocation["effective_status"] == "PENDING"
    assert first_allocation["remittance_reference"] is None

    _, by_deduction = validate_paginated(
        api.list_allocations(
            accountant_headers, params={"deduction_id": deduction["id"]}
        )
    )
    assert by_deduction["total_count"] == 2, (
        f"the deduction holds two allocations, meta was {by_deduction}"
    )

    _, by_chargeback = validate_paginated(
        api.list_allocations(accountant_headers, params={"chargeback_id": first_id})
    )
    assert by_chargeback["total_count"] == 1, (
        "the first chargeback is recovered from one allocation"
    )

    _, by_cash = validate_paginated(
        api.list_allocations(accountant_headers, params={"source_type": "CASH"})
    )
    assert by_cash["total_count"] == 0, "no cash has been applied"

    stored_deduction = read_deduction(deduction["id"])
    assert stored_deduction["allocation_count"] == 2
    assert stored_deduction["amount_cents"] == 140000

    chargeback = read_chargeback(first_id)
    assert chargeback["recovered_cents"] == 0, "a pending allocation recovers nothing"
    assert chargeback["settlement_status"] == "ASSESSED"
