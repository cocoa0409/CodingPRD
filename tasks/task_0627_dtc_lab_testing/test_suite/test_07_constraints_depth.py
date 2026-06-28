"""Depth tests for validation precedence, boundary precision, cross-entity state
dependencies, resource temporal overlap, and compensating invariants.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]
PHYSICIAN = TEST_USERS["ordering_physician_headers"]


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_vs_business_safety_release_critical_unack_state_wins
# ---------------------------------------------------------------------------
def test_double_release_fails_state_check_not_critical_callback(api):
    """PRD 2.5: "then the target resource's state admits the requested transition
    (a 409 state error); and finally the domain-specific business rules described
    throughout Section 3."
    PRD 3.8: "A result release moves the result to RELEASED and is permitted only
    when the result is in PROCESSING or PENDING_CRITICAL_CALLBACK (else
    ERR_RESULT_NOT_RELEASABLE)".

    A second release on an already-RELEASED result fails the state check first
    (ERR_RESULT_NOT_RELEASABLE), not the critical-callback safety check.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_release_critical_unack_state_wins
    """
    # CR with ref 70-100, critical_high 400; first result analyzer 50 -> NORMAL, released.
    ctx = fx.setup_processed_result(
        analyzer_value=50,
        fulfillment_mode="HOME_KIT",
        offering_overrides={
            "test_code": "CR", "display_name": "Critical Test", "list_price_cents": 4000,
            "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100, "critical_high": 400,
        },
        patient_overrides={"state_code": "CA", "consent_share_results": True},
        api=api,
    )
    res = ctx["lab_result"]
    get_success_data(api.release_lab_result(res["id"], LAB2))

    resp = api.release_lab_result(res["id"], LAB2)
    error = validate_error(resp, ApiErrorId.ERR_RESULT_NOT_RELEASABLE.value)
    assert error["error_id"] != ApiErrorId.ERR_CRITICAL_CALLBACK_REQUIRED.value


def test_double_release_state_check_returns_409(api):
    """PRD 3.8: "A result release moves the result to RELEASED and is permitted only
    when the result is in PROCESSING or PENDING_CRITICAL_CALLBACK (else
    ERR_RESULT_NOT_RELEASABLE)".

    The first release of a non-critical result succeeds (RELEASED); a second
    release of the same now-RELEASED result hits the state guard, confirming the
    state precondition (Section 2.5) is evaluated, returning HTTP 409
    ERR_RESULT_NOT_RELEASABLE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_release_critical_unack_state_wins
    """
    ctx = fx.setup_processed_result(
        analyzer_value=50,
        fulfillment_mode="HOME_KIT",
        offering_overrides={
            "test_code": "CR", "display_name": "Critical Test", "list_price_cents": 4000,
            "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100, "critical_high": 400,
        },
        patient_overrides={"state_code": "CA", "consent_share_results": True},
        api=api,
    )
    res = ctx["lab_result"]
    first = validate_success(api.release_lab_result(res["id"], LAB2))
    assert first["status"] == "RELEASED"
    resp = api.release_lab_result(res["id"], LAB2)
    validate_error(resp, ApiErrorId.ERR_RESULT_NOT_RELEASABLE.value, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/existence_vs_invalid_request_order_missing_cart_existence_wins
# ---------------------------------------------------------------------------
def test_checkout_missing_cart_fails_existence_before_body(api):
    """PRD 2.5: "The server resolves every path and body identifier left to right,
    and the first identifier that fails to resolve causes immediate rejection with
    ERR_NOT_FOUND before any business rule runs."
    PRD 2.5: "then existence of every referenced identifier (ERR_NOT_FOUND); then
    request-body well-formedness — required fields present, enum values within
    their domain, and integers non-negative where required (ERR_INVALID_REQUEST)".

    Checkout naming a non-existent cart_id AND omitting expected_cart_version fails
    existence first -> ERR_NOT_FOUND, not the malformed-body error.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_invalid_request_order_missing_cart_existence_wins
    """
    patient = fx.create_patient(api=api, state_code="CA")
    resp = api.create_order(
        {"cart_id": "00000000-0000-4000-8000-000000000000", "fulfillment_mode": "HOME_KIT"},
        make_patient_headers(patient["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


def test_checkout_existing_cart_bad_enum_returns_invalid_request(api):
    """PRD 2.5: "then request-body well-formedness — required fields present, enum
    values within their domain, and integers non-negative where required
    (ERR_INVALID_REQUEST)".
    PRD 3.4: "the fulfillment_mode (either PSC or HOME_KIT)".

    With an existing cart (existence passes) but a fulfillment_mode outside its
    domain, the request reaches the body-well-formedness check and is rejected with
    ERR_INVALID_REQUEST — the very check that ERR_NOT_FOUND pre-empts when the cart
    is missing.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_invalid_request_order_missing_cart_existence_wins
    """
    off = fx.create_offering(api=api, test_code="EXR", display_name="Exists", list_price_cents=1000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_now = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    resp = api.create_order(
        {"cart_id": cart["id"], "fulfillment_mode": "TELEPORT", "expected_cart_version": cart_now["version"]},
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/platform_discount_tier1_at_exactly_20000_subtotal
# ---------------------------------------------------------------------------
def test_platform_tier1_at_exactly_20000_subtotal(api):
    """PRD 3.3: "When the subtotal is at least 50000 cents (five hundred dollars),
    the platform rate is 0.15; otherwise, when the subtotal is at least 20000 cents
    (two hundred dollars), the platform rate is 0.10; otherwise the rate is zero.
    The platform discount is the subtotal multiplied by that rate, rounded half-up
    to a whole cent, and estimated_total_cents is the subtotal minus that rounded
    discount."

    A single 20000-cent line hits the tier1 boundary: 20000 - round(20000*0.10)
    = 20000 - 2000 = 18000.

    Design: Difficulty/boundary_precision_check/platform_discount_tier1_at_exactly_20000_subtotal
    """
    off = fx.create_offering(api=api, test_code="Z20", display_name="Twenty K", list_price_cents=20000, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["subtotal_cents"] == 20000
    assert cart_read["estimated_total_cents"] == 18000, (
        f"Expected 18000 at the 20000-cent tier1 boundary, got {cart_read['estimated_total_cents']}"
    )


def test_platform_tier_just_below_boundary_no_discount(api):
    """PRD 3.3: "otherwise, when the subtotal is at least 20000 cents (two hundred
    dollars), the platform rate is 0.10; otherwise the rate is zero."

    A subtotal of 19999 (one cent below the tier1 boundary) gets a 0% platform
    rate, so estimated_total_cents == 19999.

    Design: Difficulty/boundary_precision_check/platform_discount_tier1_at_exactly_20000_subtotal
    """
    off = fx.create_offering(api=api, test_code="Z199", display_name="Below Tier", list_price_cents=19999, specimen_type="BLOOD")
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off["id"], api=api)
    cart_read = validate_success(api.get_cart(cart["id"], make_patient_headers(patient["id"])))
    assert cart_read["subtotal_cents"] == 19999
    assert cart_read["estimated_total_cents"] == 19999


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/empty_cart_checkout_zero_line_count_boundary
# ---------------------------------------------------------------------------
def test_checkout_empty_cart_rejected(api):
    """PRD 3.4: "Checkout is refused on an empty cart — a line_count of zero yields
    ERR_EMPTY_CART".

    Design: Difficulty/boundary_precision_check/empty_cart_checkout_zero_line_count_boundary
    """
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    assert cart["line_count"] == 0
    resp = api.create_order(
        F.create_order_payload(cart["id"], "HOME_KIT", cart["version"]),
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_CART.value)


def test_new_cart_line_count_is_zero(api):
    """PRD 3.2: "A new cart begins in status OPEN with line_count, subtotal_cents,
    estimated_total_cents, estimated_hsa_applied_cents, and estimated_patient_due_cents
    all initialized to zero."

    Design: Difficulty/boundary_precision_check/empty_cart_checkout_zero_line_count_boundary
    """
    patient = fx.create_patient(api=api, state_code="CA")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    assert cart["line_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/orderline_collect_requires_physician_order_approved
# ---------------------------------------------------------------------------
def test_collect_restricted_line_blocked_until_physician_approved(api):
    """PRD 3.5: "if the line's requires_physician_order is true, an APPROVED
    physician order must exist for the line, or it is rejected with
    ERR_PHYSICIAN_ORDER_REQUIRED".
    PRD 3.5: "Approving moves the order from SUBMITTED to APPROVED and thereby
    satisfies the collection gate for its line".

    Design: Difficulty/cross_entity_state_dependency/orderline_collect_requires_physician_order_approved
    """
    ctx = fx.setup_restricted_order(test_code="TST3", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    line = ctx["order_line"]
    po = ctx["physician_order"]

    # First collect while PhysicianOrder is SUBMITTED -> rejected.
    resp = api.collect_order_line(line["id"], PHLEB)
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_ORDER_REQUIRED.value)

    # Approve, then collect succeeds.
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN))
    spec = validate_success(api.collect_order_line(line["id"], PHLEB), expected_status=201)
    line_after = validate_success(api.get_order_line(line["id"], ADMIN))
    assert line_after["status"] == "COLLECTED"


def test_collect_succeeds_after_physician_approval(api):
    """PRD 3.5: "Collection advances an order line from ORDERED to COLLECTED and is
    permitted only when several conditions hold".
    PRD 3.5: "On success the server mints a Specimen in status COLLECTED".

    Design: Difficulty/cross_entity_state_dependency/orderline_collect_requires_physician_order_approved
    """
    ctx = fx.setup_restricted_order(test_code="TST3", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    line = ctx["order_line"]
    po = ctx["physician_order"]
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN))
    spec = validate_success(api.collect_order_line(line["id"], PHLEB), expected_status=201)
    assert spec["status"] == "COLLECTED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/psc_orderline_collect_requires_appointment_checked_in
# ---------------------------------------------------------------------------
def test_collect_psc_line_blocked_until_appointment_checked_in(api):
    """PRD 3.5: "and for a PSC order, a CHECKED_IN appointment must exist for the
    order, or it is rejected with ERR_APPOINTMENT_NOT_CHECKED_IN."
    PRD 3.7: "A PhlebotomyTech checks an appointment in, moving it from BOOKED to
    CHECKED_IN, which is what enables collection for that PSC order."

    Design: Difficulty/cross_entity_state_dependency/psc_orderline_collect_requires_appointment_checked_in
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="PSC",
        offering_overrides={"test_code": "H", "display_name": "Test H", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    appt = fx.book_appointment(order["id"], patient["id"], "PSC-1", "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z", api=api)

    # Collect while appointment only BOOKED -> rejected.
    resp = api.collect_order_line(line["id"], PHLEB)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_CHECKED_IN.value)

    # Check in, then collect succeeds.
    fx.check_in_appointment(appt["id"], api=api)
    spec = validate_success(api.collect_order_line(line["id"], PHLEB), expected_status=201)
    line_after = validate_success(api.get_order_line(line["id"], ADMIN))
    assert line_after["status"] == "COLLECTED"


def test_collect_psc_succeeds_after_check_in(api):
    """PRD 3.7: "A PhlebotomyTech checks an appointment in, moving it from BOOKED
    to CHECKED_IN, which is what enables collection for that PSC order."

    Design: Difficulty/cross_entity_state_dependency/psc_orderline_collect_requires_appointment_checked_in
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="PSC",
        offering_overrides={"test_code": "H", "display_name": "Test H", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order, line = ctx["patient"], ctx["order"], ctx["order_line"]
    appt = fx.book_appointment(order["id"], patient["id"], "PSC-1", "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z", api=api)
    fx.check_in_appointment(appt["id"], api=api)
    spec = validate_success(api.collect_order_line(line["id"], PHLEB), expected_status=201)
    assert spec["status"] == "COLLECTED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/appointment_half_open_overlap_at_psc_location
# ---------------------------------------------------------------------------
def test_appointment_overlap_rejected_touch_allowed(api):
    """PRD 3.7: "The new slot must not overlap an existing BOOKED or CHECKED_IN
    appointment at the same psc_location_code under half-open [start, end)
    semantics, so two appointments that merely touch at a boundary do not conflict;
    an overlap is rejected with ERR_SLOT_OVERLAP."

    Prior [09:00,09:30) at PSC-2: a [09:15,09:45) overlaps -> ERR_SLOT_OVERLAP; a
    [09:30,10:00) merely touches -> allowed.

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_overlap_at_psc_location
    """
    off = fx.create_offering(api=api, test_code="H2", display_name="Test H2", list_price_cents=4000, specimen_type="BLOOD")
    p_a = fx.create_patient(api=api, state_code="CA")
    p_b = fx.create_patient(api=api, state_code="CA")

    cart_a = fx.open_cart(p_a["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart_a["id"], p_a["id"], off["id"], api=api)
    order_a = fx.checkout(cart_a["id"], p_a["id"], "PSC", api=api)
    fx.book_appointment(order_a["id"], p_a["id"], "PSC-2", "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z", api=api)

    cart_b = fx.open_cart(p_b["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart_b["id"], p_b["id"], off["id"], api=api)
    order_b = fx.checkout(cart_b["id"], p_b["id"], "PSC", api=api)

    # Overlapping slot rejected.
    overlap = api.create_appointment(
        F.create_appointment_payload(order_b["id"], "PSC-2", "2026-02-01T09:15:00Z", "2026-02-01T09:45:00Z"),
        make_patient_headers(p_b["id"]),
    )
    validate_error(overlap, ApiErrorId.ERR_SLOT_OVERLAP.value)

    # Touching slot allowed.
    touch = validate_success(
        api.create_appointment(
            F.create_appointment_payload(order_b["id"], "PSC-2", "2026-02-01T09:30:00Z", "2026-02-01T10:00:00Z"),
            make_patient_headers(p_b["id"]),
        ),
        expected_status=201,
    )
    assert touch["status"] == "BOOKED"


def test_appointment_touching_boundary_allowed(api):
    """PRD 3.7: "so two appointments that merely touch at a boundary do not
    conflict".

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_overlap_at_psc_location
    """
    off = fx.create_offering(api=api, test_code="H2", display_name="Test H2", list_price_cents=4000, specimen_type="BLOOD")
    p_a = fx.create_patient(api=api, state_code="CA")
    p_b = fx.create_patient(api=api, state_code="CA")
    cart_a = fx.open_cart(p_a["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart_a["id"], p_a["id"], off["id"], api=api)
    order_a = fx.checkout(cart_a["id"], p_a["id"], "PSC", api=api)
    fx.book_appointment(order_a["id"], p_a["id"], "PSC-2", "2026-02-01T09:00:00Z", "2026-02-01T09:30:00Z", api=api)
    cart_b = fx.open_cart(p_b["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart_b["id"], p_b["id"], off["id"], api=api)
    order_b = fx.checkout(cart_b["id"], p_b["id"], "PSC", api=api)
    touch = validate_success(
        api.create_appointment(
            F.create_appointment_payload(order_b["id"], "PSC-2", "2026-02-01T09:30:00Z", "2026-02-01T10:00:00Z"),
            make_patient_headers(p_b["id"]),
        ),
        expected_status=201,
    )
    assert touch["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/analyzer_run_buffer_extended_overlap_on_instrument
# ---------------------------------------------------------------------------
def test_analyzer_run_buffer_extended_overlap(api):
    """PRD 3.9: "a new run does not overlap a prior RESERVED run on the same
    analyzer_code only when the new run's run_start is at or after the prior run's
    run_end plus the prior run's buffer_minutes, or the prior run's run_start is at
    or after the new run's run_end plus the new run's buffer_minutes. In any other
    arrangement the two runs overlap and the reservation is rejected with
    ERR_ANALYZER_RUN_OVERLAP — so two runs that merely touch at a boundary still
    conflict, because the buffer gap is mandatory."

    Prior [09:00,10:00) buffer 30 blocks until 10:30: a run at 10:29 overlaps; a
    run at exactly 10:30 is allowed.

    Design: Difficulty/resource_temporal_overlap/analyzer_run_buffer_extended_overlap_on_instrument
    """
    get_success_data(api.create_analyzer_run(
        F.create_analyzer_run_payload("CHEM-1", "2026-02-01T09:00:00Z", "2026-02-01T10:00:00Z", buffer_minutes=30), LAB,
    ))
    too_soon = api.create_analyzer_run(
        F.create_analyzer_run_payload("CHEM-1", "2026-02-01T10:29:00Z", "2026-02-01T11:00:00Z", buffer_minutes=30), LAB,
    )
    validate_error(too_soon, ApiErrorId.ERR_ANALYZER_RUN_OVERLAP.value)

    ok = validate_success(
        api.create_analyzer_run(
            F.create_analyzer_run_payload("CHEM-1", "2026-02-01T10:30:00Z", "2026-02-01T11:00:00Z", buffer_minutes=30), LAB,
        ),
        expected_status=201,
    )
    assert ok["status"] == "RESERVED"


def test_analyzer_run_at_buffer_boundary_allowed(api):
    """PRD 3.9: "a new run does not overlap a prior RESERVED run on the same
    analyzer_code only when the new run's run_start is at or after the prior run's
    run_end plus the prior run's buffer_minutes".

    Design: Difficulty/resource_temporal_overlap/analyzer_run_buffer_extended_overlap_on_instrument
    """
    get_success_data(api.create_analyzer_run(
        F.create_analyzer_run_payload("CHEM-1", "2026-02-01T09:00:00Z", "2026-02-01T10:00:00Z", buffer_minutes=30), LAB,
    ))
    ok = validate_success(
        api.create_analyzer_run(
            F.create_analyzer_run_payload("CHEM-1", "2026-02-01T10:30:00Z", "2026-02-01T11:00:00Z", buffer_minutes=30), LAB,
        ),
        expected_status=201,
    )
    assert ok["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/card_net_charge_conserved_on_authorize_then_cancel_refund
# ---------------------------------------------------------------------------
def test_card_order_refunded_with_zero_capture_on_cancel(api):
    """PRD 3.4: "Concurrently a Payment is minted in status AUTHORIZED, with
    fund_source snapshotting the order's fund source and authorized_amount_cents
    set to the cart's estimated_patient_due_cents captured at this moment."
    PRD 3.7: "On the payment axis, an AUTHORIZED payment moves directly to REFUNDED
    with no HSA restore needed because no HSA debit ever occurred".

    A CARD order authorized for 4000, cancelled before any result, is REFUNDED with
    captured_amount_cents 0.

    Design: Difficulty/compensating_invariant/card_net_charge_conserved_on_authorize_then_cancel_refund
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "J", "display_name": "Test J", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    p_headers = make_patient_headers(patient["id"])
    validate_success(api.cancel_order(order["id"], {"expected_order_version": order["version"]}, p_headers))

    payments, _meta = fx._list(api.list_payments(p_headers, params={"order_id": order["id"]}))
    pay = payments[0]
    assert pay["authorized_amount_cents"] == 4000
    assert pay["captured_amount_cents"] == 0
    assert pay["status"] == "REFUNDED"


def test_card_order_payment_status_refunded_on_cancel(api):
    """PRD 3.7: "the payment is refunded along the payment axis (hop 3)."

    Design: Difficulty/compensating_invariant/card_net_charge_conserved_on_authorize_then_cancel_refund
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "J", "display_name": "Test J", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    p_headers = make_patient_headers(patient["id"])
    cancelled = validate_success(api.cancel_order(order["id"], {"expected_order_version": order["version"]}, p_headers))
    assert cancelled["payment_status"] == "REFUNDED"
