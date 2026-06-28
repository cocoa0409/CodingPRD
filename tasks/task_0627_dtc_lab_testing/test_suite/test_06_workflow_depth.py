"""Depth tests for non-linear state machines, transitive cascades, and the
clinical provisional-vs-final flag divergence.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]
PHYSICIAN = TEST_USERS["ordering_physician_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/clinical_result_provisional_vs_final_flag_diverge
# ---------------------------------------------------------------------------
def test_final_flag_escalates_via_delta_check_when_provisional_normal(api):
    """PRD 3.8: "If a prior result exists and the absolute difference between this
    result's analyzer_value and the prior's analyzer_value is at least 50 analyzer
    units, the swing escalates the base flag one severity step — NORMAL becomes
    ABNORMAL, ABNORMAL becomes CRITICAL, and CRITICAL stays CRITICAL; otherwise
    final_flag equals the base flag."
    PRD 3.8: "Because of this, the same analyzer_value that is NORMAL provisionally
    can become ABNORMAL finally once a large enough prior swing exists."

    GLU (ref 70-100): value 95 is provisionally NORMAL, but with a prior RELEASED
    GLU of 44 the swing |95-44|=51 >= 50 escalates final_flag to ABNORMAL.

    Design: Difficulty/dual_variant_calc/clinical_result_provisional_vs_final_flag_diverge
    """
    off_glu = fx.create_offering(
        api=api, test_code="GLU", display_name="Glucose", list_price_cents=4000,
        specimen_type="BLOOD", critical_low=40, critical_high=400, ref_low=70, ref_high=100,
        home_kit_eligible=True,
    )
    patient = fx.create_patient(api=api, state_code="CA")
    # Prior released GLU=44 (NORMAL, no prior history).
    fx.give_patient_released_result(patient["id"], off_glu["id"], analyzer_value=44, api=api)

    # Second order: GLU processed at 95.
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off_glu["id"], api=api)
    order = fx.checkout(cart["id"], patient["id"], "HOME_KIT", api=api)
    fx.ship_home_kit(order["id"], patient["id"], "CA", api=api)
    line = fx.order_lines_for(order["id"], api=api)[0]
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 95, api=api)
    assert res["provisional_flag"] == "NORMAL", f"95 in ref [70,100] is NORMAL provisionally, got {res['provisional_flag']}"

    released = validate_success(api.release_lab_result(res["id"], LAB2))
    assert released["final_flag"] == "ABNORMAL", (
        f"Delta |95-44|=51 >= 50 should escalate NORMAL -> ABNORMAL, got {released['final_flag']}"
    )


def test_provisional_flag_ignores_prior_history(api):
    """PRD 3.8: "At this moment the result's provisional_flag is computed from the
    offering's bounds alone, with no history."

    GLU value 95 in ref [70,100] is provisional NORMAL regardless of a prior 44.

    Design: Difficulty/dual_variant_calc/clinical_result_provisional_vs_final_flag_diverge
    """
    off_glu = fx.create_offering(
        api=api, test_code="GLU", display_name="Glucose", list_price_cents=4000,
        specimen_type="BLOOD", critical_low=40, critical_high=400, ref_low=70, ref_high=100,
        home_kit_eligible=True,
    )
    patient = fx.create_patient(api=api, state_code="CA")
    fx.give_patient_released_result(patient["id"], off_glu["id"], analyzer_value=44, api=api)

    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off_glu["id"], api=api)
    order = fx.checkout(cart["id"], patient["id"], "HOME_KIT", api=api)
    fx.ship_home_kit(order["id"], patient["id"], "CA", api=api)
    line = fx.order_lines_for(order["id"], api=api)[0]
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 95, api=api)
    assert res["provisional_flag"] == "NORMAL"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/physician_order_cyclic_needs_more_info_back_to_submitted
# ---------------------------------------------------------------------------
def test_physician_order_cycles_needs_more_info_then_approves(api):
    """PRD 3.5: "Requesting more information moves the order from SUBMITTED to
    NEEDS_MORE_INFO and records the reviewing physician."
    PRD 3.5: "A Patient may resubmit an order that sits in NEEDS_MORE_INFO, moving
    it back to SUBMITTED for re-review and, when a new clinical_note is supplied,
    overwriting the stored note; this is the cyclic loop where a request-info round
    returns the order to SUBMITTED."
    PRD 3.5: "Approving moves the order from SUBMITTED to APPROVED and thereby
    satisfies the collection gate for its line, but only after two further checks".

    Design: Difficulty/non_linear_state_machine/physician_order_cyclic_needs_more_info_back_to_submitted
    """
    ctx = fx.setup_restricted_order(test_code="TST", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    po = ctx["physician_order"]
    patient = ctx["patient"]

    after_req = validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("REQUEST_INFO"), PHYSICIAN))
    assert after_req["status"] == "NEEDS_MORE_INFO"

    after_resubmit = validate_success(api.resubmit_physician_order(po["id"], {"clinical_note": "added labs"}, make_patient_headers(patient["id"])))
    assert after_resubmit["status"] == "SUBMITTED"

    after_approve = validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN))
    assert after_approve["status"] == "APPROVED"


def test_physician_order_reaches_approved_after_revision_loop(api):
    """PRD 3.5: "A decision is allowed only while the order is SUBMITTED; an attempt
    against any other state is rejected with ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE."

    After a REQUEST_INFO -> resubmit cycle the order is SUBMITTED again and a
    fresh APPROVE decision is therefore permitted, ending at APPROVED.

    Design: Difficulty/non_linear_state_machine/physician_order_cyclic_needs_more_info_back_to_submitted
    """
    ctx = fx.setup_restricted_order(test_code="TST", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    po = ctx["physician_order"]
    patient = ctx["patient"]
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("REQUEST_INFO"), PHYSICIAN))
    validate_success(api.resubmit_physician_order(po["id"], {"clinical_note": "more"}, make_patient_headers(patient["id"])))
    approved = validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN))
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes_evolve_independently
# ---------------------------------------------------------------------------
def test_order_payment_axis_stays_authorized_while_fulfillment_advances(api):
    """PRD 3.4: "so a freshly placed order is observed with payment_status at
    AUTHORIZED and its fulfillment_status at AWAITING_COLLECTION."
    PRD 3.5: "If the order was in AWAITING_COLLECTION, this first collect advances
    its fulfillment_status to IN_PROCESSING."
    PRD 3.7: "When every order line has reached a terminal state (RESULTED,
    REJECTED, or CANCELLED) and at least one is RESULTED, the order advances to
    COMPLETED, whether it arrives there from PARTIALLY_RESULTED or directly from
    IN_PROCESSING without an intermediate partial".

    payment_status remains AUTHORIZED at placement, mid-collect, and post-release
    while fulfillment_status walks AWAITING_COLLECTION -> IN_PROCESSING -> COMPLETED.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes_evolve_independently
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "E", "display_name": "Test E", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line = ctx["order"], ctx["order_line"]
    assert order["payment_status"] == "AUTHORIZED"
    assert order["fulfillment_status"] == "AWAITING_COLLECTION"

    spec = fx.collect_line(line["id"], api=api)
    mid = validate_success(api.get_order(order["id"], ADMIN))
    assert mid["payment_status"] == "AUTHORIZED"
    assert mid["fulfillment_status"] == "IN_PROCESSING"

    res = fx.process_specimen(spec["id"], 5, api=api)
    get_success_data(api.release_lab_result(res["id"], LAB2))
    end = validate_success(api.get_order(order["id"], ADMIN))
    assert end["payment_status"] == "AUTHORIZED"
    assert end["fulfillment_status"] == "COMPLETED"


def test_order_fulfillment_advances_to_in_processing_on_first_collect(api):
    """PRD 3.7: "An order's fulfillment axis advances automatically as its lines
    resolve. The first collected line moves the order from AWAITING_COLLECTION to
    IN_PROCESSING."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes_evolve_independently
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "E", "display_name": "Test E", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line = ctx["order"], ctx["order_line"]
    fx.collect_line(line["id"], api=api)
    mid = validate_success(api.get_order(order["id"], ADMIN))
    assert mid["fulfillment_status"] == "IN_PROCESSING"
    assert mid["payment_status"] == "AUTHORIZED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/physician_decline_cascades_orderline_reject_to_order_completion_depth3
# ---------------------------------------------------------------------------
def test_physician_decline_cascades_to_order_completion(api):
    """PRD 3.5: "When a physician declines, three cascade hops follow in order: the
    owning order line transitions from ORDERED to REJECTED (hop 1); that rejection
    bubbles up to recompute the parent order's fulfillment_status (hop 2); and if
    every other order line is already terminal, the order's fulfillment_status
    resolves to COMPLETED or CANCELLED per the order cascade rule of Section 3.7
    (hop 3)."
    PRD 3.7: "When every order line has reached a terminal state (RESULTED,
    REJECTED, or CANCELLED) and at least one is RESULTED, the order advances to
    COMPLETED".

    Order with F (resulted) + TST2 (declined): decline rejects the TST2 line and,
    since F is RESULTED, the order auto-completes.

    Design: Difficulty/transitive_cascade/physician_decline_cascades_orderline_reject_to_order_completion_depth3
    """
    off_f = fx.create_offering(api=api, test_code="F", display_name="Test F", list_price_cents=4000, specimen_type="BLOOD", home_kit_eligible=True)
    off_tst2 = fx.create_offering(api=api, test_code="TST2", display_name="Restricted 2", list_price_cents=5000, specimen_type="BLOOD", home_kit_eligible=True)
    patient = fx.create_patient(api=api, state_code="CA", date_of_birth="1990-01-01")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off_f["id"], api=api)
    fx.add_cart_line(cart["id"], patient["id"], off_tst2["id"], api=api)
    order = fx.checkout(cart["id"], patient["id"], "HOME_KIT", api=api)
    fx.ship_home_kit(order["id"], patient["id"], "CA", api=api)
    lines = fx.order_lines_for(order["id"], api=api)
    line_f = next(l for l in lines if l["test_code"] == "F")
    line_tst2 = next(l for l in lines if l["test_code"] == "TST2")

    # Result F.
    spec_f = fx.collect_line(line_f["id"], api=api)
    res_f = fx.process_specimen(spec_f["id"], 5, api=api)
    get_success_data(api.release_lab_result(res_f["id"], LAB2))

    # Decline TST2's physician order.
    po = fx.physician_order_for_line(line_tst2["id"], api=api)
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("DECLINE"), PHYSICIAN))

    line_tst2_after = validate_success(api.get_order_line(line_tst2["id"], ADMIN))
    assert line_tst2_after["status"] == "REJECTED"
    order_after = validate_success(api.get_order(order["id"], ADMIN))
    assert order_after["fulfillment_status"] == "COMPLETED"


def test_physician_decline_excludes_line_from_invoice(api):
    """PRD 3.5: "A declined line is excluded from the order invoice."
    PRD 3.6: "The invoice uses the same four-step arithmetic as the cart estimate
    of Section 3.3, but its input set is only the order lines whose status is
    RESULTED at the moment of recompute; lines in REJECTED, CANCELLED, COLLECTED,
    or ORDERED are excluded."

    Only F (4000) is RESULTED; TST2 declined. Invoice = 4000 (below tier1).

    Design: Difficulty/transitive_cascade/physician_decline_cascades_orderline_reject_to_order_completion_depth3
    """
    off_f = fx.create_offering(api=api, test_code="F", display_name="Test F", list_price_cents=4000, specimen_type="BLOOD", home_kit_eligible=True)
    off_tst2 = fx.create_offering(api=api, test_code="TST2", display_name="Restricted 2", list_price_cents=5000, specimen_type="BLOOD", home_kit_eligible=True)
    patient = fx.create_patient(api=api, state_code="CA", date_of_birth="1990-01-01")
    cart = fx.open_cart(patient["id"], api=api, fund_source="CARD")
    fx.add_cart_line(cart["id"], patient["id"], off_f["id"], api=api)
    fx.add_cart_line(cart["id"], patient["id"], off_tst2["id"], api=api)
    order = fx.checkout(cart["id"], patient["id"], "HOME_KIT", api=api)
    fx.ship_home_kit(order["id"], patient["id"], "CA", api=api)
    lines = fx.order_lines_for(order["id"], api=api)
    line_f = next(l for l in lines if l["test_code"] == "F")
    line_tst2 = next(l for l in lines if l["test_code"] == "TST2")
    spec_f = fx.collect_line(line_f["id"], api=api)
    res_f = fx.process_specimen(spec_f["id"], 5, api=api)
    get_success_data(api.release_lab_result(res_f["id"], LAB2))
    po = fx.physician_order_for_line(line_tst2["id"], api=api)
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("DECLINE"), PHYSICIAN))

    order_after = validate_success(api.get_order(order["id"], ADMIN))
    assert order_after["invoiced_total_cents"] == 4000


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/result_release_cascades_line_resulted_to_invoice_recompute_depth2
# ---------------------------------------------------------------------------
def test_result_release_cascades_line_resulted_then_invoice(api):
    """PRD 3.8: "A successful release fires the full result cascade: the order line
    moves from COLLECTED to RESULTED and its Specimen moves to RESULTED (hop 1);
    the order's invoiced total is recomputed and its fulfillment axis bubbles to
    PARTIALLY_RESULTED or COMPLETED per the rules of Section 3.7 (hop 2)".

    Pre-release invoice is 0; after release the line is RESULTED and invoice = 4000.

    Design: Difficulty/transitive_cascade/result_release_cascades_line_resulted_to_invoice_recompute_depth2
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "G", "display_name": "Test G", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line = ctx["order"], ctx["order_line"]
    spec = fx.collect_line(line["id"], api=api)
    res = fx.process_specimen(spec["id"], 5, api=api)

    order_pre = validate_success(api.get_order(order["id"], ADMIN))
    assert order_pre["invoiced_total_cents"] == 0

    get_success_data(api.release_lab_result(res["id"], LAB2))
    line_after = validate_success(api.get_order_line(line["id"], ADMIN))
    assert line_after["status"] == "RESULTED"
    order_post = validate_success(api.get_order(order["id"], ADMIN))
    assert order_post["invoiced_total_cents"] == 4000


def test_invoice_zero_before_any_release(api):
    """PRD 3.4: "The order's own invoiced_total_cents, hsa_applied_cents, and
    patient_due_cents start at zero and are filled in only as results are released."

    Design: Difficulty/transitive_cascade/result_release_cascades_line_resulted_to_invoice_recompute_depth2
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "G", "display_name": "Test G", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line = ctx["order"], ctx["order_line"]
    fx.collect_line(line["id"], api=api)
    order_pre = validate_success(api.get_order(order["id"], ADMIN))
    assert order_pre["invoiced_total_cents"] == 0
