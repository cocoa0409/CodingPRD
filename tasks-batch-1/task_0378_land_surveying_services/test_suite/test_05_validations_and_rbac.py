"""Single-rule validation rejections, role-based access control, and optimistic
concurrency: payment overpayment, instrument calibration, duplicate research
packet, researcher role mismatch, role-forbidden writes, missing auth, and the
stale-order-version OCC guard on seal and issue.

Corner queue: validations, rbac, cross_cutting_complexity_layers sections.
"""
from test_helpers import (
    fixtures as fx,
    make_billing_clerk_headers,
    make_coordinator_headers,
    make_drafter_headers,
    make_surveyor_headers,
    create_crew_member_payload,
    create_field_assignment_payload,
    create_instrument_payload,
    create_instrument_reservation_payload,
    create_research_packet_payload,
    create_survey_order_payload,
    issue_invoice_payload,
    payment_payload,
    seal_payload,
    validate_error,
    validate_success,
    ABSENT_UUID,
    ApiErrorId,
    TEST_USERS,
)


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/payment_exceeds_balance_rejected
# ════════════════════════════════════════════════════════════════════════
def test_payment_exceeding_balance_rejected(api):
    """PRD §3.6: "A payment's amount must be greater than zero and must not exceed
    the invoice's current `balance_due_cents`; a non-positive amount or one that
    would overpay is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    A 200000 payment against an invoice whose balance is 155880 overpays and is
    rejected with ERR_PAYMENT_EXCEEDS_BALANCE; no payment is applied (amount_paid 0,
    balance still 155880).

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    ctx = fx.issued_invoice(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]

    pre = validate_success(api.get_invoice(ctx["invoice_id"], make_billing_clerk_headers(bid)), 200)
    assert pre["balance_due_cents"] == 155880

    resp = api.pay_invoice(ctx["invoice_id"], payment_payload(200000), make_billing_clerk_headers(bid))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    after = validate_success(api.get_invoice(ctx["invoice_id"], make_billing_clerk_headers(bid)), 200)
    assert after["amount_paid_cents"] == 0
    assert after["balance_due_cents"] == 155880


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/instrument_out_of_calibration_rejected
# ════════════════════════════════════════════════════════════════════════
def test_instrument_out_of_calibration_rejected(api):
    """PRD §3.3: "the instrument's `calibration_due_on` must fall after the
    assignment's `scheduled_end` — an instrument whose calibration deadline is at or
    before the field window's end is out of calibration for that window and the
    reservation is rejected with `ERR_INSTRUMENT_OUT_OF_CALIBRATION`."

    Reserving an instrument whose calibration_due_on (10:00) is before the
    assignment's scheduled_end (13:00) is rejected with
    ERR_INSTRUMENT_OUT_OF_CALIBRATION; the instrument stays AVAILABLE.

    Design: Corner/validations/instrument_out_of_calibration_rejected
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    oid = ctx["order_id"]

    instrument = validate_success(
        api.create_instrument(
            create_instrument_payload(instrument_type="DRONE",
                                      calibration_due_on="2026-07-01T10:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    assignment = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(oid, tid, "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)

    resp = api.create_instrument_reservation(
        create_instrument_reservation_payload(assignment["id"], instrument["id"]),
        make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_OUT_OF_CALIBRATION)
    after = validate_success(api.get_instrument(instrument["id"], make_coordinator_headers(cid)), 200)
    assert after["status"] == "AVAILABLE"


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/second_research_packet_per_order_rejected
# ════════════════════════════════════════════════════════════════════════
def test_second_research_packet_rejected(api):
    """PRD §3.2: "At most one research packet may exist per order — a second attempt
    is rejected with `ERR_DUPLICATE_CHILD`."

    Opening a second ResearchPacket for an order that already has one is rejected
    with ERR_DUPLICATE_CHILD.

    Design: Corner/validations/second_research_packet_per_order_rejected
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    order = validate_success(
        api.create_survey_order(create_survey_order_payload(), make_coordinator_headers(cid)), 201)
    oid = order["id"]
    validate_success(
        api.create_research_packet(create_research_packet_payload(oid, rid, encumbrance_count=0),
                                   make_coordinator_headers(cid)), 201)

    resp = api.create_research_packet(
        create_research_packet_payload(oid, rid, encumbrance_count=0), make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHILD)


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/research_begin_with_non_researcher_role_mismatch
# ════════════════════════════════════════════════════════════════════════
def test_research_packet_with_non_researcher_rejected(api):
    """PRD §3.2: "The `assigned_researcher_id` must resolve to a crew member whose
    `role_type` is `RESEARCHER`; if it does not, the packet creation is rejected
    with `ERR_ROLE_MISMATCH`."

    Opening a ResearchPacket whose assigned_researcher_id points to a TECH (not
    RESEARCHER) is rejected with ERR_ROLE_MISMATCH.

    Design: Corner/validations/research_begin_with_non_researcher_role_mismatch
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    order = validate_success(
        api.create_survey_order(create_survey_order_payload(), make_coordinator_headers(cid)), 201)

    resp = api.create_research_packet(
        create_research_packet_payload(order["id"], tid, encumbrance_count=0),
        make_coordinator_headers(cid))
    validate_error(resp, ApiErrorId.ERR_ROLE_MISMATCH)


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/drafter_cannot_seal_plat_forbidden
# ════════════════════════════════════════════════════════════════════════
def test_drafter_cannot_seal_plat(api):
    """PRD §3.5: "Sealing is the most heavily guarded operation in the system,
    reserved to a `Surveyor`, and it moves a plat from `UNDER_REVIEW` to `SEALED`."
    PRD §2.1: "When an authenticated user attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A Drafter attempting to seal an UNDER_REVIEW plat is rejected with
    ERR_FORBIDDEN_ROLE; the plat stays UNDER_REVIEW.

    Design: Corner/rbac/drafter_cannot_seal_plat_forbidden
    """
    ctx = fx.plat_under_review(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    did = crew["drafter"]["id"]
    ov = fx.order_version(ctx)

    resp = api.seal_plat(ctx["plat_id"], seal_payload(did, ov), make_drafter_headers(did))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    plat = validate_success(api.get_plat_drawing(ctx["plat_id"], make_coordinator_headers(cid)), 200)
    assert plat["status"] == "UNDER_REVIEW"


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/missing_auth_headers_unauthenticated
# ════════════════════════════════════════════════════════════════════════
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and
    `X-User-Role`, which declares the operational capacity under which the request
    is made. If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    A POST /survey-orders with no auth headers is rejected with ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.create_survey_order(create_survey_order_payload(), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/billing_clerk_cannot_create_field_assignment_forbidden
# ════════════════════════════════════════════════════════════════════════
def test_billing_clerk_cannot_create_field_assignment(api):
    """PRD §3.3: "A `Coordinator` schedules fieldwork by creating a field assignment
    against an order."
    PRD §2.1: "When an authenticated user attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A BillingClerk attempting POST /field-assignments (a Coordinator operation) is
    rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/billing_clerk_cannot_create_field_assignment_forbidden
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    tid = crew["tech"]["id"]
    bid = crew["billing"]["id"]

    resp = api.create_field_assignment(
        create_field_assignment_payload(ctx["order_id"], tid,
                                        "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
        make_billing_clerk_headers(bid))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ════════════════════════════════════════════════════════════════════════
# Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_seal_returns_412
# ════════════════════════════════════════════════════════════════════════
def test_seal_with_stale_order_version_returns_412(api):
    """PRD §2.8: "A request to seal a plat drawing must carry `expected_order_version`
    matching the current `version` of the plat's parent `SurveyOrder`. Sealing
    advances that order from `DRAFTING` to `SEALED` and increments the order's
    `version`; if another writer has already advanced the order since the client last
    read it ... the supplied `expected_order_version` no longer matches, and the seal
    is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Sealing with expected_order_version one less than the order's current version is
    rejected with ERR_STALE_ORDER_VERSION; the plat stays UNDER_REVIEW.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_seal_returns_412
    """
    ctx = fx.plat_under_review(survey_type="BOUNDARY", acreage=3, rush=False, closure_error_ppm=20)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    pls_id = crew["pls"]["id"]
    ov = fx.order_version(ctx)

    resp = api.seal_plat(ctx["plat_id"], seal_payload(pls_id, ov - 1), make_surveyor_headers(pls_id))
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
    plat = validate_success(api.get_plat_drawing(ctx["plat_id"], make_coordinator_headers(cid)), 200)
    assert plat["status"] == "UNDER_REVIEW"


# ════════════════════════════════════════════════════════════════════════
# Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
# ════════════════════════════════════════════════════════════════════════
def test_order_version_increments_on_mutation(api):
    """PRD §2.4: "`version` (integer): a server-managed integer that begins at 1 on
    creation and increments by one on every mutation of the resource."

    A SurveyOrder is version 1 at creation; after start-research mutates it, its
    version is 2.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    rid = crew["researcher"]["id"]
    order = validate_success(
        api.create_survey_order(create_survey_order_payload(), make_coordinator_headers(cid)), 201)
    oid = order["id"]
    assert order["version"] == 1
    validate_success(
        api.create_research_packet(create_research_packet_payload(oid, rid, encumbrance_count=0),
                                   make_coordinator_headers(cid)), 201)

    advanced = validate_success(api.start_research(oid, make_coordinator_headers(cid)), 200)
    assert advanced["version"] == 2


# ════════════════════════════════════════════════════════════════════════
# Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_invoice_issue_returns_412
# ════════════════════════════════════════════════════════════════════════
def test_issue_invoice_with_stale_order_version_returns_412(api):
    """PRD §2.8: "A request to issue an invoice must carry `expected_order_version`
    matching the current `version` of the order being billed. Issuing freezes the
    order's `final_fee_cents` from the order's then-current fee components; if a
    revision applied after the client last read the order has since bumped the
    order's `version` (and its fee components), issuing against the stale version is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Issuing a DRAFT invoice with expected_order_version one less than the order's
    current version is rejected with ERR_STALE_ORDER_VERSION; the invoice stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_invoice_issue_returns_412
    """
    ctx = fx.draft_invoice_on_sealed_order(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    bid = crew["billing"]["id"]
    ov = fx.order_version(ctx)

    resp = api.issue_invoice(ctx["invoice_id"], issue_invoice_payload(ov - 1), make_billing_clerk_headers(bid))
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
    invoice = validate_success(api.get_invoice(ctx["invoice_id"], make_billing_clerk_headers(bid)), 200)
    assert invoice["lifecycle_status"] == "DRAFT"
