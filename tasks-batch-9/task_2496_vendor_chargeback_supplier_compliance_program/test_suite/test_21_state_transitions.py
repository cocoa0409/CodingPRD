"""State transitions across the programme's lifecycles.

Publication and supersession of a routing guide edition, the compound receipt
posture a purchase order derives from its shipments, the initial state of a
deduction, and the refusals that guard settled and terminal states.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    REQ_DOC_03,
    REQ_LBL_01,
    REQ_PKG_02,
    add_requirement,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    make_vendor_headers,
    publish_guide,
    read_chargeback,
    read_dispute,
    read_guide,
    read_purchase_order,
    read_requirements,
    read_shipment,
    read_violation,
    receive_shipment,
    set_clock,
    setup_assessed_chargeback,
    open_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMME_START = "2026-08-01T00:00:00Z"


def _instant(value: str) -> datetime:
    """Compare two ISO 8601 UTC instants without depending on their spelling."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_publishing_a_draft_edition_moves_it_to_published(api, officer_headers):
    """PRD §3.2: "The first link moves the edition `DRAFT → PUBLISHED`, stamps
    `published_at` with the current logical clock and records the acting operator
    in `published_by_user_id`."
    PRD §3.2: "A `SUPERSEDED` edition is terminal; while an edition is `DRAFT` or
    `PUBLISHED` its `effective_until` and its requirements' `effective_until`
    remain null, meaning the window is open-ended above."
    PRD §2.10: "Each entity a cascade touches has its `updated_at` refreshed and
    its `version` incremented by one, whether or not the caller named that entity
    in the request."

    Design: Corner/state_machines/corner_routing_guide_draft_to_published_transition
    """
    set_clock(PROGRAMME_START)
    guide = create_guide(
        guide_code="RG-2026-V",
        title="Valid Transition Guide",
        scope_code="PACKAGING",
        effective_from="2026-08-20T00:00:00Z",
    )
    add_requirement(guide["id"], REQ_PKG_02)
    version_before = read_guide(guide["id"])["version"]

    data = validate_success(api.publish_routing_guide(guide["id"], officer_headers), 200)

    assert data["status"] == "PUBLISHED", f"expected PUBLISHED, got {data['status']}"
    assert _instant(data["published_at"]) == _instant(PROGRAMME_START), (
        f"published_at should read the logical clock {PROGRAMME_START}, "
        f"got {data['published_at']}"
    )
    assert data["published_by_user_id"] == OFFICER_USER_ID, (
        f"published_by_user_id should record the acting operator "
        f"{OFFICER_USER_ID}, got {data['published_by_user_id']}"
    )
    assert data["effective_until"] is None, (
        f"a PUBLISHED edition keeps effective_until null, got {data['effective_until']}"
    )
    assert data["version"] > version_before, (
        f"publication must increment version above {version_before}, "
        f"got {data['version']}"
    )

    rows, meta = validate_paginated(
        api.list_routing_guides(officer_headers, params={"status": "PUBLISHED"})
    )
    assert meta["total_count"] == 1, (
        f"exactly one edition should be PUBLISHED, got {meta['total_count']}"
    )
    assert rows[0]["id"] == guide["id"]


def test_publish_refused_once_effective_from_is_no_longer_in_the_future(
    api, officer_headers
):
    """PRD §3.2: "The edition's `effective_from` must be strictly later than the
    current logical clock — a guide may not begin governing arrivals that have
    already happened — and an `effective_from` at or before the clock is refused
    with `ERR_GUIDE_EFFECTIVE_FROM_IN_PAST`."
    PRD §3.2: "A freshly drafted edition is `DRAFT`, with `requirement_count` 0,
    `effective_until` null, and `published_at` and `published_by_user_id` both
    null."

    Design: Corner/state_machines/corner_publish_precondition_rejects_effective_from_in_the_past
    """
    set_clock(PROGRAMME_START)
    stale = create_guide(
        guide_code="RG-PAST",
        title="Stale Guide",
        scope_code="LABELING",
        effective_from="2026-08-05T00:00:00Z",
    )
    add_requirement(stale["id"], REQ_DOC_03)
    forward = create_guide(
        guide_code="RG-FUTURE",
        title="Forward Guide",
        scope_code="PACKAGING",
        effective_from="2026-09-01T00:00:00Z",
    )
    add_requirement(forward["id"], REQ_DOC_03)
    set_clock("2026-08-06T00:00:00Z")

    validate_error(
        api.publish_routing_guide(stale["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_EFFECTIVE_FROM_IN_PAST,
    )
    refused = read_guide(stale["id"])
    assert refused["status"] == "DRAFT", (
        f"the refused edition must stay DRAFT, got {refused['status']}"
    )
    assert refused["published_at"] is None, (
        f"a refused publication stamps nothing, got {refused['published_at']}"
    )

    published = validate_success(
        api.publish_routing_guide(forward["id"], officer_headers), 200
    )
    assert published["status"] == "PUBLISHED", (
        f"an edition dated ahead of the clock publishes, got {published['status']}"
    )
    assert _instant(published["published_at"]) == _instant("2026-08-06T00:00:00Z"), (
        f"published_at should read the clock 2026-08-06T00:00:00Z, "
        f"got {published['published_at']}"
    )


def test_publishing_a_successor_retires_the_predecessor_and_its_requirements(
    api, officer_headers
):
    """PRD §3.2: "The second link, caused by the first, applies only when
    `supersedes_guide_id` was supplied: the named predecessor moves `PUBLISHED →
    SUPERSEDED` and its `effective_until` is stamped with the successor's
    `effective_from`, closing its half-open window at exactly the instant the new
    edition opens."
    PRD §3.2: "The third link, caused by the second, copies that same
    `effective_until` down onto every requirement owned by the superseded
    predecessor, retiring the old fee schedule without deleting a single row — an
    assessment computed under the old schedule must remain explicable years
    later."
    PRD §3.2: "A `SUPERSEDED` edition is terminal; while an edition is `DRAFT` or
    `PUBLISHED` its `effective_until` and its requirements' `effective_until`
    remain null, meaning the window is open-ended above."

    Design: Corner/state_machines/corner_publish_supersession_side_effects_propagate_to_requirements
    """
    set_clock(PROGRAMME_START)
    predecessor = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    req_a1 = add_requirement(predecessor["id"], REQ_LBL_01)
    req_a2 = add_requirement(predecessor["id"], REQ_PKG_02)
    publish_guide(predecessor["id"])

    successor = create_guide(
        guide_code="RG-2026-B",
        title="Domestic Routing Guide 2026-B",
        scope_code="ALL",
        effective_from="2026-09-01T00:00:00Z",
        supersedes_guide_id=predecessor["id"],
    )
    req_b1 = add_requirement(
        successor["id"], {**REQ_LBL_01, "fixed_fee_cents": 30_000}
    )

    data = validate_success(
        api.publish_routing_guide(successor["id"], officer_headers), 200
    )
    assert data["status"] == "PUBLISHED", f"expected PUBLISHED, got {data['status']}"
    assert data["supersedes_guide_id"] == predecessor["id"]

    retired = read_guide(predecessor["id"])
    assert retired["status"] == "SUPERSEDED", (
        f"the predecessor must move to SUPERSEDED, got {retired['status']}"
    )
    assert _instant(retired["effective_until"]) == _instant("2026-09-01T00:00:00Z"), (
        f"the predecessor's window must close at the successor's effective_from, "
        f"got {retired['effective_until']}"
    )

    retired_requirements = {row["id"]: row for row in read_requirements(predecessor["id"])}
    for requirement_id in (req_a1["id"], req_a2["id"]):
        row = retired_requirements[requirement_id]
        assert _instant(row["effective_until"]) == _instant("2026-09-01T00:00:00Z"), (
            f"requirement {requirement_id} should inherit the closing instant, "
            f"got {row['effective_until']}"
        )

    live_requirements = {row["id"]: row for row in read_requirements(successor["id"])}
    assert live_requirements[req_b1["id"]]["effective_until"] is None, (
        "the successor's own requirements keep effective_until null"
    )

    rows, meta = validate_paginated(
        api.list_routing_guides(officer_headers, params={"status": "SUPERSEDED"})
    )
    assert meta["total_count"] == 1, (
        f"exactly one edition should be SUPERSEDED, got {meta['total_count']}"
    )
    assert rows[0]["id"] == predecessor["id"]

    rows, meta = validate_paginated(
        api.list_routing_guides(
            officer_headers, params={"supersedes_guide_id": predecessor["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one edition should name the predecessor, got {meta['total_count']}"
    )
    assert rows[0]["id"] == successor["id"]


def test_purchase_order_reaches_received_when_the_last_units_arrive(
    api, officer_headers, inspector_headers
):
    """PRD §3.3: "The order's `received_units` is recomputed as the sum of
    `received_units` over its shipments whose `status` is `RECEIVED`, and its
    `first_receipt_at` as the earliest `arrived_at` among those same shipments,
    remaining null while none has been received."
    PRD §3.3: "The order's `status` follows: it moves `OPEN → PARTIALLY_RECEIVED`
    when the recomputed `received_units` is at least 1 but still below
    `ordered_units`, and it advances to `RECEIVED` once the recomputed
    `received_units` reaches or exceeds `ordered_units`."
    PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."

    Design: Corner/state_machines/corner_purchase_order_bubbles_up_to_received_when_all_units_arrive
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2020", legal_name="Bubbleup Brands", payment_terms_days=30
    )
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-12T00:00:00Z",
    )
    first = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=600, carton_count=24
    )
    second = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-2", shipped_units=400, carton_count=16
    )

    set_clock("2026-08-10T00:00:00Z")
    receive_shipment(first["id"], 600)
    set_clock("2026-08-11T00:00:00Z")

    partial = read_purchase_order(po["id"])
    assert partial["status"] == "PARTIALLY_RECEIVED", (
        f"600 of 1000 units leaves the order PARTIALLY_RECEIVED, got {partial['status']}"
    )
    assert partial["received_units"] == 600, (
        f"expected a 600-unit roll-up, got {partial['received_units']}"
    )

    receipt = validate_success(
        api.receive_shipment(second["id"], {"received_units": 400}, inspector_headers),
        200,
    )

    closed = read_purchase_order(po["id"])
    assert closed["status"] == "RECEIVED", (
        f"the closing receipt takes the order to RECEIVED, got {closed['status']}"
    )
    assert closed["received_units"] == 1000, (
        f"expected a 1000-unit roll-up, got {closed['received_units']}"
    )
    assert _instant(closed["first_receipt_at"]) == _instant("2026-08-10T00:00:00Z"), (
        f"first_receipt_at is the earliest arrival 2026-08-10T00:00:00Z, "
        f"got {closed['first_receipt_at']}"
    )

    assert read_shipment(first["id"])["invoice_value_cents"] == 300000, (
        "600 units at 500 cents is 300000 cents"
    )
    assert receipt["invoice_value_cents"] == 200000, (
        f"400 units at 500 cents is 200000 cents, got {receipt['invoice_value_cents']}"
    )
    assert _instant(receipt["arrived_at"]) == _instant("2026-08-11T00:00:00Z"), (
        f"arrived_at reads the clock 2026-08-11T00:00:00Z, got {receipt['arrived_at']}"
    )

    _, meta = validate_paginated(
        api.list_po_shipments(po["id"], officer_headers, params={"status": "RECEIVED"})
    )
    assert meta["total_count"] == 2, (
        f"both shipments should read RECEIVED, got {meta['total_count']}"
    )


def test_new_deduction_opens_in_draft_with_no_money_on_it(api, accountant_headers):
    """PRD §3.9: "The deduction opens in `DRAFT` with `amount_cents` 0,
    `allocation_count` 0, `over_allocated_cents` 0, and `posted_at`,
    `posted_by_user_id`, `reversed_at` and `reversal_reason` all null; creating it
    increments the supplier's `version` by one, which is exactly why a client
    drafting a second deduction must re-read the supplier first."
    PRD §2.5: "Most resources additionally carry an `updated_at`, in the same
    timestamp format, refreshed on every mutation, and a `version`, an integer
    that starts at 1 on creation and increments by one on every mutation —
    including mutations the client did not request directly, such as a parent
    whose derived totals were recomputed by a cascade."

    Design: Corner/state_machines/corner_deduction_starts_in_draft_initial_state
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2021",
        legal_name="Initialstate Industries",
        payment_terms_days=30,
    )

    data = validate_success(
        api.create_deduction(
            {
                "vendor_id": vendor["id"],
                "invoice_reference": "INV-INIT",
                "expected_vendor_version": vendor["version"],
            },
            accountant_headers,
        ),
        201,
    )

    assert data["status"] == "DRAFT", f"a new deduction is DRAFT, got {data['status']}"
    assert data["invoice_reference"] == "INV-INIT"
    assert data["amount_cents"] == 0, (
        f"a new deduction nets nothing yet, got {data['amount_cents']}"
    )
    assert data["allocation_count"] == 0, (
        f"a new deduction holds no allocation, got {data['allocation_count']}"
    )
    assert data["over_allocated_cents"] == 0, (
        f"a new deduction cannot be over-allocated, got {data['over_allocated_cents']}"
    )
    assert data["posted_at"] is None, f"posted_at must be null, got {data['posted_at']}"
    assert data["posted_by_user_id"] is None, (
        f"posted_by_user_id must be null, got {data['posted_by_user_id']}"
    )
    assert data["reversed_at"] is None, (
        f"reversed_at must be null, got {data['reversed_at']}"
    )
    assert data["reversal_reason"] is None, (
        f"reversal_reason must be null, got {data['reversal_reason']}"
    )
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"


def test_neither_a_superseded_nor_a_published_edition_can_be_republished(
    api, officer_headers
):
    """PRD §3.2: "A `ComplianceOfficer` publishes an edition that is still
    `DRAFT`; publishing anything else is refused with `ERR_GUIDE_NOT_DRAFT`."
    PRD §3.2: "The second link, caused by the first, applies only when
    `supersedes_guide_id` was supplied: the named predecessor moves `PUBLISHED →
    SUPERSEDED` and its `effective_until` is stamped with the successor's
    `effective_from`, closing its half-open window at exactly the instant the new
    edition opens."
    PRD §3.2: "A `SUPERSEDED` edition is terminal; while an edition is `DRAFT` or
    `PUBLISHED` its `effective_until` and its requirements' `effective_until`
    remain null, meaning the window is open-ended above."

    Design: Corner/state_machines/corner_superseded_guide_is_locked_and_rejects_republication
    """
    set_clock(PROGRAMME_START)
    predecessor = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    add_requirement(predecessor["id"], REQ_LBL_01)
    publish_guide(predecessor["id"])

    successor = create_guide(
        guide_code="RG-2026-B",
        title="Domestic Routing Guide 2026-B",
        scope_code="ALL",
        effective_from="2026-09-01T00:00:00Z",
        supersedes_guide_id=predecessor["id"],
    )
    add_requirement(successor["id"], {**REQ_LBL_01, "fixed_fee_cents": 30_000})
    publish_guide(successor["id"])

    validate_error(
        api.publish_routing_guide(predecessor["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_NOT_DRAFT,
    )
    validate_error(
        api.publish_routing_guide(successor["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_NOT_DRAFT,
    )

    retired = read_guide(predecessor["id"])
    assert retired["status"] == "SUPERSEDED", (
        f"SUPERSEDED is terminal, got {retired['status']}"
    )
    assert _instant(retired["effective_until"]) == _instant("2026-09-01T00:00:00Z"), (
        f"a refused republication leaves effective_until untouched, "
        f"got {retired['effective_until']}"
    )
    assert read_guide(successor["id"])["status"] == "PUBLISHED", (
        "the successor stays PUBLISHED after a refused republication"
    )


def test_second_receipt_on_the_same_shipment_is_refused(
    api, inspector_headers
):
    """PRD §3.3: "The shipment must still be `IN_TRANSIT`; receiving one that has
    already been received is refused with `ERR_SHIPMENT_ALREADY_RECEIVED`."
    PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.3: "The order's `status` follows: it moves `OPEN → PARTIALLY_RECEIVED`
    when the recomputed `received_units` is at least 1 but still below
    `ordered_units`, and it advances to `RECEIVED` once the recomputed
    `received_units` reaches or exceeds `ordered_units`."

    Design: Corner/state_machines/corner_second_receive_on_the_same_shipment_is_rejected
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V2022", legal_name="Replay Wholesale", payment_terms_days=30
    )
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
    set_clock("2026-08-10T00:00:00Z")
    receive_shipment(shipment["id"], 800)

    validate_error(
        api.receive_shipment(shipment["id"], {"received_units": 800}, inspector_headers),
        ApiErrorId.ERR_SHIPMENT_ALREADY_RECEIVED,
    )

    after = read_shipment(shipment["id"])
    assert after["received_units"] == 800, (
        f"the replayed receipt must not double the count, got {after['received_units']}"
    )
    assert after["invoice_value_cents"] == 400000, (
        f"800 units at 500 cents is 400000 cents, got {after['invoice_value_cents']}"
    )

    order = read_purchase_order(po["id"])
    assert order["received_units"] == 800, (
        f"the parent roll-up must not double either, got {order['received_units']}"
    )
    assert order["status"] == "PARTIALLY_RECEIVED", (
        f"800 of 1000 units leaves the order PARTIALLY_RECEIVED, got {order['status']}"
    )


def test_triggers_absent_from_a_settled_state_are_refused_with_their_own_codes(
    api, officer_headers
):
    """PRD §3.4: "A `ComplianceOfficer` voids a violation with a mandatory
    `void_reason`, permitted while the violation's `status` is `DETECTED` or
    `EVIDENCE_COMPLETE`; from `VOIDED` or `CHARGED` the request is refused with
    `ERR_VIOLATION_NOT_OPEN`."
    PRD §3.4: "A newly filed violation records `detected_at` from the current
    logical clock and `detected_by_user_id` from the acting inspector's
    `X-User-ID`, takes its `shipment_id` from the path, pins the supplied
    `requirement_id`, starts with `evidence_count` 0 and `void_reason` null, and
    raises both the shipment's `open_violation_count` and the supplier's
    `open_violation_count` by one."
    PRD §3.6: "Resubmission requires the dispute to be exactly `INFO_REQUESTED`,
    refused otherwise with `ERR_DISPUTE_NOT_INFO_REQUESTED`; requires
    `round_count` to be strictly less than 2, refused otherwise with
    `ERR_DISPUTE_ROUND_LIMIT_EXCEEDED`; and re-checks the claim against
    `gross_assessed_cents` less `reversal_cents`, refused otherwise with
    `ERR_CLAIM_EXCEEDS_ASSESSMENT`."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock,
    `chargeback_id` taken from the path and `vendor_id` denormalised from the
    chargeback."

    Design: Corner/state_machines/corner_invalid_triggers_from_settled_states_are_rejected
    """
    world = setup_assessed_chargeback(
        REQ_LBL_01,
        evidence_kinds=("PHOTO", "SCAN"),
        assessment_note="Label scan failures.",
        affected_units=500,
        affected_cartons=20,
        narrative="Unreadable labels.",
        vendor_overrides={
            "vendor_code": "V2023",
            "legal_name": "Settled States Sourcing",
            "payment_terms_days": 30,
        },
    )
    violation_id = world["violation"]["id"]
    chargeback_id = world["chargeback"]["id"]
    dispute = open_dispute(
        chargeback_id,
        world["vendor"]["id"],
        reason_code="NOT_OUR_LABEL",
        claimed_reversal_cents=10_000,
        narrative="Labels were compliant on our side.",
    )

    validate_error(
        api.void_violation(
            violation_id,
            {"void_reason": "Attempt to void after charging."},
            officer_headers,
        ),
        ApiErrorId.ERR_VIOLATION_NOT_OPEN,
    )
    charged = read_violation(violation_id)
    assert charged["status"] == "CHARGED", (
        f"a charged finding stays CHARGED, got {charged['status']}"
    )
    assert charged["void_reason"] is None, (
        f"a refused void stores no reason, got {charged['void_reason']}"
    )

    validate_error(
        api.resubmit_dispute(
            dispute["id"],
            {"claimed_reversal_cents": 12_000, "narrative": "Second thoughts."},
            make_vendor_headers(world["vendor"]["id"]),
        ),
        ApiErrorId.ERR_DISPUTE_NOT_INFO_REQUESTED,
    )
    submitted = read_dispute(dispute["id"])
    assert submitted["status"] == "SUBMITTED", (
        f"the dispute stays SUBMITTED, got {submitted['status']}"
    )
    assert submitted["round_count"] == 1, (
        f"a refused resubmission consumes no round, got {submitted['round_count']}"
    )
    assert submitted["claimed_reversal_cents"] == 10000, (
        f"the claim keeps its opening value, got {submitted['claimed_reversal_cents']}"
    )
    assert read_chargeback(chargeback_id)["dispute_status"] == "OPEN", (
        "the chargeback's dispute dimension stays OPEN"
    )
