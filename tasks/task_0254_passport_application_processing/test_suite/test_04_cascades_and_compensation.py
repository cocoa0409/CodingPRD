"""Transitive cascades (doc-accept -> risk -> review-hold; reject -> refund +
appointment cancel) and compensating-action invariants on the two conserved
quantities (the applicant fee ledger and the UNPAID fee total).

Difficulty queue: transitive_cascade, compensating_invariant. Corner queue:
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    adjudicate_payload,
    api_client,
    make_adjudicator_headers,
    make_agent_headers,
    make_applicant_headers,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/transitive_cascade/last_doc_accept_cascades_to_adjudicating_then_review_hold_depth3
# ════════════════════════════════════════════════════════════════════════
def test_last_doc_accept_recomputes_risk_to_50_10(api):
    """PRD §3.6: "The combined quality is 0.40 times the identity factor quality
    plus 0.35 times the citizenship factor quality plus 0.25 times the photo
    quality. The risk is then 100 minus that combined quality, rounded half up to 2
    decimal places." PRD §3.6: "The final variant is computed on every change to a
    supporting document's or photo's verification status".

    Design: Difficulty/transitive_cascade/last_doc_accept_cascades_to_adjudicating_then_review_hold_depth3
    """
    # IDENTITY quality 36, CITIZENSHIP quality 30, photo PASS:
    # quality = 0.40*36 + 0.35*30 + 0.25*100 = 14.4 + 10.5 + 25 = 49.9 -> risk 50.10
    # Accepting the first document while the second is still PENDING pushes the FINAL
    # risk above 50 (75 - 0.40*36 = 60.60), which per PRD §3.6 sends the application
    # to REVIEW_HOLD; the adjudicator must clear the hold before the second accept.
    ctx = fx.in_verification_application(
        application_type="NEW", product_type="BOOK",
        doc_specs=[("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": 36}),
                   ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": 30})])
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]
    app_id = ctx["application"]["id"]
    adjudicator = fx.create_adjudicator()
    fx.accept_documents_clearing_holds(
        app_id, appl_id, agent_id,
        [ctx["docs"]["IDENTITY"][0]["id"], ctx["docs"]["CITIZENSHIP"][0]["id"]],
        adjudicator["id"])

    applicant = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["verification_risk_score"] == 50.10


def test_last_doc_accept_above_threshold_lands_in_review_hold(api):
    """PRD §3.6: "If, however, that final recompute yields a score strictly above 50,
    the application instead lands in REVIEW_HOLD rather than ADJUDICATING." PRD §3.6:
    "When a final recompute of the applicant's verification_risk_score yields a score
    strictly greater than 50, the application, while IN_VERIFICATION, transitions to
    REVIEW_HOLD".

    Design: Difficulty/transitive_cascade/last_doc_accept_cascades_to_adjudicating_then_review_hold_depth3
    """
    # Final risk (both docs accepted) is 50.10 > 50, so after the LAST accept the
    # application lands in REVIEW_HOLD rather than ADJUDICATING. The intermediate
    # accept (first doc only) also trips the hold at 60.60, which the adjudicator
    # clears so the last accept can run.
    ctx = fx.in_verification_application(
        application_type="NEW", product_type="BOOK",
        doc_specs=[("IDENTITY", "DRIVERS_LICENSE", {"declared_quality": 36}),
                   ("CITIZENSHIP", "BIRTH_CERTIFICATE", {"declared_quality": 30})])
    appl_id = ctx["applicant"]["id"]
    agent_id = ctx["agent"]["id"]
    app_id = ctx["application"]["id"]
    adjudicator = fx.create_adjudicator()
    fx.accept_documents_clearing_holds(
        app_id, appl_id, agent_id,
        [ctx["docs"]["IDENTITY"][0]["id"], ctx["docs"]["CITIZENSHIP"][0]["id"]],
        adjudicator["id"])

    app = validate_success(api.get_application(app_id, make_applicant_headers(appl_id)), 200)
    assert app["status"] == "REVIEW_HOLD"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/transitive_cascade/reject_cascades_refund_and_appointment_cancel_depth2
# ════════════════════════════════════════════════════════════════════════
def _adjudicating_with_paid_urgent_appointment(api):
    """Adult NEW BOOK driven to ADJUDICATING with an urgent appointment booked
    BEFORE payment (so the urgent surcharge is in the 22500 total that gets paid),
    distinct agent and adjudicator."""
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    adjudicator = fx.create_adjudicator()

    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]

    appt = fx.book_counter_appointment(app_id, appl_id, counter["id"],
                                       "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                       ctx["application"]["version"])
    fee = fx.get_fee_for_application(app_id, appl_id)
    assert fee["total_due_cents"] == 22500
    validate_success(api.pay_fee_assessment(fee["id"], {"amount_tendered_cents": 22500},
                                            make_applicant_headers(appl_id)), 200)
    validate_success(api_client.begin_verification(app_id, make_agent_headers(agent["id"])), 200)
    fx.accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent["id"])
    fx.accept_document(ctx["docs"]["CITIZENSHIP"][0]["id"], agent["id"])
    return ctx, appt, fee, adjudicator


def test_reject_refunds_fee_and_zeroes_amount_paid(api):
    """PRD §3.9: "Rejecting moves the application from ADJUDICATING to REJECTED and
    triggers the full compensation cascade: the fee assessment, if PAID, is refunded
    (moved from PAID to REFUNDED, amount_paid_cents reset to 0, and the applicant's
    total_fees_paid_cents decremented by the refunded amount)".

    Design: Difficulty/transitive_cascade/reject_cascades_refund_and_appointment_cancel_depth2
    """
    ctx, appt, fee, adjudicator = _adjudicating_with_paid_urgent_appointment(api)
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]

    validate_success(api.adjudicate(app_id, adjudicate_payload("REJECT", reason_code="FRAUD"),
                                    make_adjudicator_headers(adjudicator["id"])), 200)
    fee_after = validate_success(api.get_fee_assessment(fee["id"], make_applicant_headers(appl_id)), 200)
    assert fee_after["payment_status"] == "REFUNDED"
    assert fee_after["amount_paid_cents"] == 0


def test_reject_cancels_booked_appointment_and_decrements_ledger(api):
    """PRD §3.9: "any BOOKED appointment for the application is cancelled (moved to
    CANCELLED)". PRD §3.5: a refund decrements "the applicant's total_fees_paid_cents
    by the assessment's current amount_paid_cents and then sets amount_paid_cents to
    0".

    Design: Difficulty/transitive_cascade/reject_cascades_refund_and_appointment_cancel_depth2
    """
    ctx, appt, fee, adjudicator = _adjudicating_with_paid_urgent_appointment(api)
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]

    validate_success(api.adjudicate(app_id, adjudicate_payload("REJECT", reason_code="FRAUD"),
                                    make_adjudicator_headers(adjudicator["id"])), 200)
    appt_after = validate_success(api.get_appointment(appt["id"], make_applicant_headers(appl_id)), 200)
    assert appt_after["status"] == "CANCELLED"
    applicant = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["total_fees_paid_cents"] == 0


# ════════════════════════════════════════════════════════════════════════
# Difficulty/compensating_invariant/withdraw_refund_conserves_applicant_total_fees_paid
# ════════════════════════════════════════════════════════════════════════
def test_total_fees_paid_is_16500_before_withdraw(api):
    """PRD §3.5: "On success the assessment moves from UNPAID to PAID,
    amount_paid_cents is set to total_due_cents, the owning applicant's
    total_fees_paid_cents is incremented by total_due_cents".

    Design: Difficulty/compensating_invariant/withdraw_refund_conserves_applicant_total_fees_paid
    """
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    applicant = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["total_fees_paid_cents"] == 16500


def test_withdraw_refund_returns_total_fees_paid_to_zero(api):
    """PRD §3.9: "Withdrawal runs the same compensation as rejection: if the fee
    assessment is PAID it is refunded (to REFUNDED, amount_paid_cents to 0,
    applicant's total_fees_paid_cents decremented)". PRD §3.5: "a pay-then-refund
    pair on the same assessment leaves total_fees_paid_cents exactly where it began,
    contributing a net of zero."

    Design: Difficulty/compensating_invariant/withdraw_refund_conserves_applicant_total_fees_paid
    """
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    fee = ctx["fee"]

    validate_success(api.withdraw_application(app_id, make_applicant_headers(appl_id)), 200)
    applicant = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["total_fees_paid_cents"] == 0
    fee_after = validate_success(api.get_fee_assessment(fee["id"], make_applicant_headers(appl_id)), 200)
    assert fee_after["payment_status"] == "REFUNDED"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/compensating_invariant/cancel_urgent_appointment_conserves_fee_total_due
# ════════════════════════════════════════════════════════════════════════
def test_urgent_fee_is_22500_while_appointment_booked(api):
    """PRD §3.7: "Booking a counter appointment ... sets the application's
    urgent_travel flag to true and, if the application's fee assessment is still
    UNPAID, re-derives that assessment so the urgent surcharge is reflected." PRD
    §3.5: "The urgent_surcharge_cents is 6000 cents ($60.00) when the application's
    urgent_travel is true".

    Design: Difficulty/compensating_invariant/cancel_urgent_appointment_conserves_fee_total_due
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    fx.book_counter_appointment(app_id, appl_id, counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx["application"]["version"])
    fee = fx.get_fee_for_application(app_id, appl_id)
    assert fee["total_due_cents"] == 22500


def test_cancel_urgent_appointment_reverts_fee_to_16500(api):
    """PRD §3.7: "When a cancelled appointment is an urgent-travel-counter
    appointment and no other BOOKED urgent appointment remains for that application,
    the system flips the application's urgent_travel back to false and re-derives the
    fee assessment if it is still UNPAID."

    Design: Difficulty/compensating_invariant/cancel_urgent_appointment_conserves_fee_total_due
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    appt = fx.book_counter_appointment(app_id, appl_id, counter["id"],
                                       "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                       ctx["application"]["version"])
    validate_success(api.cancel_appointment(appt["id"], make_applicant_headers(appl_id)), 200)

    fee_after = fx.get_fee_for_application(app_id, appl_id)
    assert fee_after["total_due_cents"] == 16500
    assert fee_after["urgent_surcharge_cents"] == 0
    app = validate_success(api.get_application(app_id, make_applicant_headers(appl_id)), 200)
    assert app["urgent_travel"] is False


# ════════════════════════════════════════════════════════════════════════
# Corner/cross_cutting_complexity_layers/derived_field_total_fees_paid_reconciles_after_pay
# ════════════════════════════════════════════════════════════════════════
def test_total_fees_paid_reconciles_from_zero_to_16500_on_pay(api):
    """PRD §3.5: "The applicant's total_fees_paid_cents is a strictly conserved
    quantity: at any time it equals the sum of amount_paid_cents over all of that
    applicant's fee assessments that are currently PAID."

    Design: Corner/cross_cutting_complexity_layers/derived_field_total_fees_paid_reconciles_after_pay
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    fee = ctx["fee"]
    before = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert before["total_fees_paid_cents"] == 0

    validate_success(api.pay_fee_assessment(fee["id"], {"amount_tendered_cents": fee["total_due_cents"]},
                                            make_applicant_headers(appl_id)), 200)
    after = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert after["total_fees_paid_cents"] == 16500


# ════════════════════════════════════════════════════════════════════════
# Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
# ════════════════════════════════════════════════════════════════════════
def test_application_version_starts_at_one_and_increments_on_submit(api):
    """PRD §2.4: a version "begins at its initial value and increments by one on
    every mutation of that resource." PRD §3.3: submission "increments the
    application's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_write
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    assert application["version"] == 1
    appl_id = applicant["id"]
    fx.add_photo(application["id"], appl_id)
    fx.add_document(application["id"], appl_id, doc_category="IDENTITY", doc_kind="DRIVERS_LICENSE")
    fx.add_document(application["id"], appl_id, doc_category="CITIZENSHIP", doc_kind="BIRTH_CERTIFICATE")
    before = validate_success(api.get_application(application["id"], make_applicant_headers(appl_id)), 200)
    submitted = validate_success(
        api.submit_application(application["id"], {"expected_application_version": before["version"]},
                               make_applicant_headers(appl_id)), 200)
    assert submitted["version"] == before["version"] + 1


# ════════════════════════════════════════════════════════════════════════
# Corner/consistency_model/immediate_urgent_fee_visible_in_same_booking_response_chain
# ════════════════════════════════════════════════════════════════════════
def test_urgent_fee_visible_immediately_after_booking(api):
    """PRD §3.7: booking a counter appointment "sets the application's urgent_travel
    flag to true and, if the application's fee assessment is still UNPAID, re-derives
    that assessment so the urgent surcharge is reflected." PRD §2: the system's
    consistency model is immediate — the re-derived fee is visible on the next read.

    Design: Corner/consistency_model/immediate_urgent_fee_visible_in_same_booking_response_chain
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    fx.book_counter_appointment(app_id, appl_id, counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx["application"]["version"])
    app = validate_success(api.get_application(app_id, make_applicant_headers(appl_id)), 200)
    assert app["urgent_travel"] is True
    fee = fx.get_fee_for_application(app_id, appl_id)
    assert fee["total_due_cents"] == 22500
