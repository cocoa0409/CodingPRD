"""Access control: authentication, role remits, supplier self-scope and the
separation between detecting and adjudicating.
"""
from test_helpers import (
    CLOCK_PROGRAMME_START,
    CLOCK_RECEIPT_DAY,
    NON_EXISTENT_UUID,
    OFFICER_USER_ID,
    REQ_LBL_01,
    SECOND_OFFICER_USER_ID,
    ApiErrorId,
    assess_payload,
    assess_violation,
    create_vendor,
    deduction_payload,
    dispute_decision_payload,
    dispute_payload,
    file_violation,
    make_inspector_headers,
    make_officer_headers,
    make_vendor_headers,
    open_dispute,
    purchase_order_payload,
    read_chargeback,
    read_dispute,
    read_purchase_order,
    receipt_payload,
    set_clock,
    setup_published_guide,
    setup_received_shipment,
    shipment_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_payload,
)


def _assessed_chargeback_for(vendor_id: str, requirement_id: str, **violation) -> dict:
    """File one breach against a fresh receipt for this supplier and price it."""
    world = setup_received_shipment(vendor_id, ordered_units=1000, unit_cost_cents=500)
    violation_row = file_violation(
        world["shipment"]["id"], requirement_id, **violation
    )
    return assess_violation(violation_row["id"], assessment_note="Assessed.")


def test_requests_without_identity_headers_are_unauthenticated(api, officer_headers):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, declaring the capacity in which that
    principal acts. If either header is absent, or if `X-User-Role` is not one of
    the five roles the programme recognises, the request is rejected with
    `ERR_UNAUTHENTICATED` (401)."
    PRD §2.7: "The server evaluates rules in the following fixed order and returns
    the first failure it finds. Later rungs are never evaluated once an earlier
    rung has failed."
    PRD §2.7: "Authentication — `X-User-Role` and `X-User-ID` are present and
    `X-User-Role` is one of the five declared roles; otherwise
    `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
    PRD §2.7: "Path existence — every identifier embedded in the URL resolves,
    checked left to right as described in §2.8; otherwise the not-found error for
    the first unresolved segment, at 404."

    Design: Corner/rbac/corner_missing_identity_headers_are_unauthenticated
    """
    set_clock(CLOCK_PROGRAMME_START)

    anonymous_read = api.get_vendor(NON_EXISTENT_UUID, None)
    validate_error(anonymous_read, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    anonymous_write = api.create_vendor(
        vendor_payload(legal_name="Anonymous Attempt"), None
    )
    validate_error(anonymous_write, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, meta = validate_paginated(api.list_vendors(officer_headers))
    assert meta["total_count"] == 0, (
        f"an unauthenticated write must create nothing, got total_count "
        f"{meta['total_count']}"
    )


def test_cross_role_exclusive_operations_are_forbidden(
    api, officer_headers, inspector_headers, accountant_headers, buyer_headers
):
    """PRD §2.1: "Once a caller is authenticated, the acting role must appear in
    the authorised-role list of the endpoint being called, as tabulated in §4; a
    role acting outside its remit is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §2.1: "The `ComplianceOfficer` is the retailer's supplier-compliance
    operator: it registers vendors, drafts and publishes routing guides and their
    requirements, assesses and voids violations, requests information on and
    adjudicates vendor disputes, opens, measures and finalizes scorecards, decides
    and closes corrective action plans, and is the only role permitted to drive the
    programme's logical clock. The `DCInspector` works the receiving door:
    receiving shipments, filing compliance violations and capturing evidence. The
    `APAccountant` owns the money movement: drafting deductions, earmarking
    allocations against them, posting and reversing deductions, and applying vendor
    remittance cash to chargebacks. The `CategoryBuyer` raises purchase orders and
    owns the buying-decision escalation on repeat-offender corrective action plans;
    it never adjudicates disputes, which is the structural half of the
    segregation-of-duties rule described in §2.11. The `Vendor` role acts on its own
    records only: advising shipments against its own purchase orders, opening and
    resubmitting disputes against its own chargebacks with supporting evidence, and
    submitting corrective action plans issued against it."
    PRD §2.7: "Authorisation — the acting role appears in the target endpoint's
    authorised-role list; otherwise `ERR_UNAUTHORIZED` (403). Applies to every
    endpoint."
    PRD §2.7: "Path existence — every identifier embedded in the URL resolves,
    checked left to right as described in §2.8; otherwise the not-found error for
    the first unresolved segment, at 404."

    Design: Corner/rbac/corner_cross_role_exclusive_operations_are_forbidden
    """
    set_clock(CLOCK_PROGRAMME_START)

    inspector_assessing = api.assess_violation(
        NON_EXISTENT_UUID,
        assess_payload(assessment_note="Inspector trying to assess."),
        inspector_headers,
    )
    validate_error(inspector_assessing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    vendor_ordering = api.create_purchase_order(
        purchase_order_payload(
            NON_EXISTENT_UUID, po_number="PO-X", ordered_units=10, unit_cost_cents=500
        ),
        make_vendor_headers(NON_EXISTENT_UUID),
    )
    validate_error(vendor_ordering, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    accountant_publishing = api.publish_routing_guide(
        NON_EXISTENT_UUID, accountant_headers
    )
    validate_error(accountant_publishing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    buyer_posting = api.post_deduction(NON_EXISTENT_UUID, buyer_headers)
    validate_error(buyer_posting, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    officer_advising = api.create_shipment(
        NON_EXISTENT_UUID,
        shipment_payload(asn_number="ASN-X", shipped_units=10, carton_count=1),
        officer_headers,
    )
    validate_error(officer_advising, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    for listing in (
        api.list_vendors(officer_headers),
        api.list_purchase_orders(officer_headers),
        api.list_routing_guides(officer_headers),
        api.list_deductions(officer_headers),
        api.list_violations(officer_headers),
    ):
        _, meta = validate_paginated(listing)
        assert meta["total_count"] == 0, (
            f"a refused write must leave the store empty, got total_count "
            f"{meta['total_count']}"
        )


def test_each_role_can_perform_its_own_exclusive_writes(
    api,
    officer_headers,
    inspector_headers,
    accountant_headers,
    buyer_headers,
):
    """PRD §2.1: "The `ComplianceOfficer` is the retailer's supplier-compliance
    operator: it registers vendors, drafts and publishes routing guides and their
    requirements, assesses and voids violations, requests information on and
    adjudicates vendor disputes, opens, measures and finalizes scorecards, decides
    and closes corrective action plans, and is the only role permitted to drive the
    programme's logical clock. The `DCInspector` works the receiving door:
    receiving shipments, filing compliance violations and capturing evidence. The
    `APAccountant` owns the money movement: drafting deductions, earmarking
    allocations against them, posting and reversing deductions, and applying vendor
    remittance cash to chargebacks. The `CategoryBuyer` raises purchase orders and
    owns the buying-decision escalation on repeat-offender corrective action plans;
    it never adjudicates disputes, which is the structural half of the
    segregation-of-duties rule described in §2.11. The `Vendor` role acts on its own
    records only: advising shipments against its own purchase orders, opening and
    resubmitting disputes against its own chargebacks with supporting evidence, and
    submitting corrective action plans issued against it."
    PRD §2.1: "All five roles may read every collection and every single-resource
    view in the programme — read access is deliberately universal so that a
    supplier, an inspector, an accountant and a buyer all look at the same numbers
    — while every state-changing operation is restricted."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."
    PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.3: "The order's `status` follows: it moves `OPEN →
    PARTIALLY_RECEIVED` when the recomputed `received_units` is at least 1 but
    still below `ordered_units`, and it advances to `RECEIVED` once the recomputed
    `received_units` reaches or exceeds `ordered_units`."
    PRD §3.9: "The deduction opens in `DRAFT` with `amount_cents` 0,
    `allocation_count` 0, `over_allocated_cents` 0, and `posted_at`,
    `posted_by_user_id`, `reversed_at` and `reversal_reason` all null; creating it
    increments the supplier's `version` by one, which is exactly why a client
    drafting a second deduction must re-read the supplier first."
    PRD §3.1: "A newly registered supplier begins in `ACTIVE` sourcing posture
    with a clean sheet: `otif_score` 0.00, `open_chargeback_cents`,
    `recovered_lifetime_cents`, `refund_due_cents`, `open_violation_count` and
    `open_cap_count` all zero, and both governance flags — `repeat_offender_flag`
    and `exposure_alert_flag` — false."

    Design: Corner/rbac/corner_each_role_can_perform_its_own_exclusive_writes
    """
    set_clock("2026-08-10T00:00:00Z")

    vendor = validate_success(
        api.create_vendor(
            vendor_payload(legal_name="Everyrole Enterprises"), officer_headers
        ),
        201,
    )
    order = validate_success(
        api.create_purchase_order(
            purchase_order_payload(
                vendor["id"],
                po_number="PO-1",
                ordered_units=1000,
                unit_cost_cents=500,
                ship_window_start="2026-08-06T00:00:00Z",
                ship_window_end="2026-08-09T00:00:00Z",
                must_arrive_by="2026-08-12T00:00:00Z",
            ),
            buyer_headers,
        ),
        201,
    )
    shipment = validate_success(
        api.create_shipment(
            order["id"],
            shipment_payload(asn_number="ASN-1", shipped_units=1000, carton_count=40),
            make_vendor_headers(vendor["id"]),
        ),
        201,
    )
    received = validate_success(
        api.receive_shipment(shipment["id"], receipt_payload(1000), inspector_headers),
        200,
    )
    assert received["status"] == "RECEIVED", (
        f"the inspector's receipt should land the shipment in RECEIVED, "
        f"got {received['status']}"
    )

    seen_by_accountant = validate_success(
        api.get_vendor(vendor["id"], accountant_headers), 200
    )
    deduction = validate_success(
        api.create_deduction(
            deduction_payload(
                vendor["id"],
                seen_by_accountant["version"],
                invoice_reference="INV-2066",
            ),
            accountant_headers,
        ),
        201,
    )
    assert deduction["status"] == "DRAFT", (
        f"a new deduction opens in DRAFT, got {deduction['status']}"
    )

    assert read_purchase_order(order["id"])["status"] == "RECEIVED", (
        "a receipt covering the whole order should take it straight to RECEIVED"
    )

    for headers in (
        inspector_headers,
        make_vendor_headers(vendor["id"]),
        buyer_headers,
        officer_headers,
    ):
        seen = validate_success(api.get_vendor(vendor["id"], headers), 200)
        assert seen["id"] == vendor["id"], (
            f"the read surface is shared by every role, got {seen['id']!r}"
        )
        assert seen["status"] == "ACTIVE", (
            f"the supplier should still be ACTIVE, got {seen['status']}"
        )


def test_vendor_cannot_dispute_another_vendors_chargeback(api, officer_headers):
    """PRD §2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the
    acting `Vendor` entity, and ownership checks compare that value against the
    vendor-referencing foreign key of the targeted resource. Five operations carry
    this check: advising a shipment compares the owning purchase order's
    `vendor_id`; opening a dispute compares the chargeback's `vendor_id`;
    attaching evidence to a dispute and resubmitting a dispute both compare the
    dispute's `vendor_id`; and submitting a corrective action plan compares the
    plan's `vendor_id`. Any mismatch is rejected with `ERR_VENDOR_SCOPE_VIOLATION`
    (403)."
    PRD §2.7: "Vendor self-scope — when the acting role is `Vendor`, `X-User-ID`
    matches the owning vendor of the targeted resource, per the five comparisons
    listed in §2.1; otherwise `ERR_VENDOR_SCOPE_VIOLATION` (403)."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock, `chargeback_id`
    taken from the path and `vendor_id` denormalised from the chargeback."
    PRD §3.6: "The same request moves the chargeback's `dispute_status` `NONE →
    OPEN` and increments the chargeback's `version` by one; its
    `settlement_status` is untouched, so a chargeback that was
    `PARTIALLY_RECOVERED` or `RECOVERED` stays exactly where it was on that
    dimension."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/rbac/corner_vendor_cannot_dispute_another_vendors_chargeback
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor_a = create_vendor(legal_name="Alpha Apparel")
    vendor_b = create_vendor(legal_name="Beta Bottling")
    published = setup_published_guide(
        REQ_LBL_01, None, {"min_evidence_count": 0}
    )

    set_clock(CLOCK_RECEIPT_DAY)
    chargeback = _assessed_chargeback_for(
        vendor_a["id"],
        published["requirement"]["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )

    foreign_attempt = api.create_dispute(
        chargeback["id"],
        dispute_payload(
            reason_code="NOT_OUR_LABEL",
            claimed_reversal_cents=5000,
            narrative="Vendor B reaching into vendor A's case.",
        ),
        make_vendor_headers(vendor_b["id"]),
    )
    validate_error(foreign_attempt, ApiErrorId.ERR_VENDOR_SCOPE_VIOLATION.value, 403)

    own_attempt = api.create_dispute(
        chargeback["id"],
        dispute_payload(
            reason_code="NOT_OUR_LABEL",
            claimed_reversal_cents=5000,
            narrative="Vendor A disputing its own chargeback.",
        ),
        make_vendor_headers(vendor_a["id"]),
    )
    dispute = validate_success(own_attempt, 201)
    assert dispute["vendor_id"] == vendor_a["id"], (
        f"the dispute belongs to the chargeback's own supplier, got "
        f"{dispute['vendor_id']!r}"
    )

    _, meta = validate_paginated(
        api.list_disputes(officer_headers, params={"chargeback_id": chargeback["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the owner's dispute should exist, got total_count {meta['total_count']}"
    )
    assert read_chargeback(chargeback["id"])["dispute_status"] == "OPEN"


def test_detecting_operator_may_not_adjudicate_the_dispute(api):
    """PRD §2.11: "When a dispute is adjudicated, the acting `ComplianceOfficer`'s
    `X-User-ID` is compared against the `detected_by_user_id` recorded on the
    compliance violation that produced the disputed chargeback, and if the two are
    equal the adjudication is refused with `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §2.11: "Note that the check reaches back two hops — from the dispute to
    its chargeback, and from the chargeback to its violation — so an officer who
    has never touched the dispute may still be barred from deciding it."
    PRD §2.1: "The server records it where a workflow demands an audit stamp — as
    `published_by_user_id` on a routing guide, `detected_by_user_id` on a
    violation, `captured_by_user_id` on an evidence item, `decided_by_user_id` on a
    dispute, `posted_by_user_id` on a deduction and `applied_by_user_id` on a
    recovery allocation — but it never compares those values against any entity's
    `id`."
    PRD §3.6: "A `DENY` decision short-circuits the arithmetic:
    `reason_ceiling_pct` is set to 0.00, `goodwill_cents` to 0 and
    `approved_reversal_cents` to 0, the dispute lands in `DENIED`, and the
    chargeback moves `OPEN → UPHELD` on its dispute dimension with
    `reversal_cents` left exactly as it was."
    PRD §3.5: "The flat component, `fixed_fee_cents`, is copied straight from the
    pinned requirement's `fixed_fee_cents`. A unit-recovery amount is formed by
    multiplying the requirement's `per_unit_recovery_cents` by the violation's
    `affected_units`. A handling-recovery amount is formed by multiplying the
    shipment's `invoice_value_cents` by the requirement's `handling_pct`, dividing
    by 100, and rounding the result half up to a whole number of cents before it
    is used anywhere."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case for
    a `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3`
    requirement once a matching prior chargeback exists inside that 180-day
    lookback. Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."
    PRD §4: "An endpoint that brings a new resource row into existence answers
    `201` on success; every other successful call answers `200`, including the
    action endpoints that only advance an existing row's state."

    Design: Corner/rbac/corner_detecting_operator_may_not_adjudicate_the_dispute
    """
    set_clock(CLOCK_PROGRAMME_START)
    vendor = create_vendor(legal_name="Detection Dilemma Foods")
    published = setup_published_guide(REQ_LBL_01, None, {"min_evidence_count": 0})

    set_clock(CLOCK_RECEIPT_DAY)
    world = setup_received_shipment(vendor["id"], ordered_units=1000, unit_cost_cents=500)
    violation = file_violation(
        world["shipment"]["id"],
        published["requirement"]["id"],
        make_inspector_headers(OFFICER_USER_ID),
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )
    assert violation["detected_by_user_id"] == OFFICER_USER_ID, (
        f"the filing identity is stamped on the finding, got "
        f"{violation['detected_by_user_id']!r}"
    )
    chargeback = assess_violation(
        violation["id"],
        make_officer_headers(SECOND_OFFICER_USER_ID),
        assessment_note="Assessed.",
    )
    assert chargeback["gross_assessed_cents"] == 38_000, (
        f"gross_assessed_cents should be 38000, got {chargeback['gross_assessed_cents']}"
    )
    dispute = open_dispute(
        chargeback["id"],
        vendor["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=10_000,
        narrative="Carrier mishandled the pallet.",
    )

    self_judgement = api.decide_dispute(
        dispute["id"],
        dispute_decision_payload(
            "DENY", review_note="The detecting operator judging their own finding."
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(self_judgement, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_dispute(dispute["id"])["status"] == "SUBMITTED", (
        "a refused adjudication must leave the dispute awaiting decision"
    )

    independent = api.decide_dispute(
        dispute["id"],
        dispute_decision_payload("DENY", review_note="Independent officer denies the dispute."),
        make_officer_headers(SECOND_OFFICER_USER_ID),
    )
    decided = validate_success(independent, 200)
    assert decided["status"] == "DENIED", (
        f"a DENY lands the dispute in DENIED, got {decided['status']}"
    )
    assert decided["approved_reversal_cents"] == 0, (
        f"a denial approves nothing, got {decided['approved_reversal_cents']}"
    )

    final = read_chargeback(chargeback["id"])
    assert final["dispute_status"] == "UPHELD", (
        f"a denial upholds the chargeback, got {final['dispute_status']}"
    )
    assert final["reversal_cents"] == 0, (
        f"reversal_cents is left exactly as it was, got {final['reversal_cents']}"
    )
    assert final["outstanding_cents"] == 38_000, (
        f"the whole assessment remains outstanding, got {final['outstanding_cents']}"
    )
