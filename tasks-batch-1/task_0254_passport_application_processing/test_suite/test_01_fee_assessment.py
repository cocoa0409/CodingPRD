"""Fee assessment: dual-variant base fee, surcharges, and the urgent re-derivation.

Difficulty queue: combinatorial_formula (bundle x minor age band; urgent-surcharge
evaluation order). Corner queue: calculations section (adult bundle, plain renewal,
card-only execution-only with default-zero delivery).
"""
from test_helpers import make_applicant_headers, validate_success
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/combinatorial_formula/fee_bundle_minor_age_band_nonlinear_interaction
# ════════════════════════════════════════════════════════════════════════
def test_minor_bundle_expedite_base_fee_is_10500(api):
    """PRD §3.5: "for a minor it is 10000 plus 1500 minus 1000, that is 10500 cents
    — the bundle discount and the minor age band both apply." This computed base is
    stored as base_fee_cents.

    Design: Difficulty/combinatorial_formula/fee_bundle_minor_age_band_nonlinear_interaction
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    guardian = fx.create_applicant(full_legal_name="Guardian G", date_of_birth="1985-01-01")
    minor = fx.create_applicant(full_legal_name="Minor M", date_of_birth="2015-01-01",
                                guardian_applicant_id=guardian["id"])
    application = fx.create_application(minor["id"], application_type="MINOR",
                                        product_type="BOOK_AND_CARD", service_level="EXPEDITE")
    fx.add_photo(application["id"], minor["id"])
    fx.add_document(application["id"], minor["id"], doc_category="GUARDIAN_CONSENT",
                    doc_kind="CONSENT_FORM", declared_quality=100)
    submitted = validate_success(
        api.submit_application(application["id"], {"expected_application_version": application["version"]},
                               make_applicant_headers(minor["id"])), 200)
    assert submitted["status"] == "SUBMITTED"
    fee = fx.get_fee_for_application(application["id"], minor["id"])
    assert fee["base_fee_cents"] == 10500


def test_minor_bundle_expedite_total_due_is_20000(api):
    """PRD §3.5: "The execution_fee_cents is 3500 cents ($35.00) when the
    application's requires_execution is true". PRD §3.5: "The expedite_fee_cents
    is 6000 cents ($60.00) when service_level is EXPEDITE". PRD §3.5: "The
    total_due_cents is the exact sum of base_fee_cents, execution_fee_cents,
    expedite_fee_cents, urgent_surcharge_cents, and one_day_delivery_cents".

    Design: Difficulty/combinatorial_formula/fee_bundle_minor_age_band_nonlinear_interaction
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    guardian = fx.create_applicant(full_legal_name="Guardian G", date_of_birth="1985-01-01")
    minor = fx.create_applicant(full_legal_name="Minor M", date_of_birth="2015-01-01",
                                guardian_applicant_id=guardian["id"])
    application = fx.create_application(minor["id"], application_type="MINOR",
                                        product_type="BOOK_AND_CARD", service_level="EXPEDITE")
    fx.add_photo(application["id"], minor["id"])
    fx.add_document(application["id"], minor["id"], doc_category="GUARDIAN_CONSENT",
                    doc_kind="CONSENT_FORM", declared_quality=100)
    validate_success(
        api.submit_application(application["id"], {"expected_application_version": application["version"]},
                               make_applicant_headers(minor["id"])), 200)
    fee = fx.get_fee_for_application(application["id"], minor["id"])
    assert fee["execution_fee_cents"] == 3500
    assert fee["expedite_fee_cents"] == 6000
    assert fee["total_due_cents"] == 20000


# ════════════════════════════════════════════════════════════════════════
# Difficulty/combinatorial_formula/fee_evaluation_order_urgent_surcharge_pinned_after_book
# ════════════════════════════════════════════════════════════════════════
def test_urgent_surcharge_added_after_counter_booking(api):
    """PRD §3.7: "Booking a counter appointment has fiscal consequences: it sets
    the application's urgent_travel flag to true and, if the application's fee
    assessment is still UNPAID, re-derives that assessment so the urgent surcharge
    is reflected." PRD §3.5: "The urgent_surcharge_cents is 6000 cents ($60.00)
    when the application's urgent_travel is true, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/fee_evaluation_order_urgent_surcharge_pinned_after_book
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter = fx.create_counter(cleanup_buffer_minutes=15)
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]

    fee_before = fx.get_fee_for_application(app_id, appl_id)
    assert fee_before["total_due_cents"] == 16500
    assert fee_before["urgent_surcharge_cents"] == 0

    fx.book_counter_appointment(app_id, appl_id, counter["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx["application"]["version"])

    fee_after = fx.get_fee_for_application(app_id, appl_id)
    assert fee_after["urgent_surcharge_cents"] == 6000
    assert fee_after["total_due_cents"] == 22500


def test_urgent_travel_flag_set_on_counter_booking(api):
    """PRD §3.7: "it sets the application's urgent_travel flag to true and, if the
    application's fee assessment is still UNPAID, re-derives that assessment so the
    urgent surcharge is reflected."

    Design: Difficulty/combinatorial_formula/fee_evaluation_order_urgent_surcharge_pinned_after_book
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


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/fee_adult_book_and_card_bundle_discount_correct
# ════════════════════════════════════════════════════════════════════════
def test_adult_bundle_total_is_18500(api):
    """PRD §3.5: "for an adult this is 13000 plus 3000 minus 1000, that is 15000
    cents". PRD §3.5: "The execution_fee_cents is 3500 cents ($35.00) when the
    application's requires_execution is true, and 0 otherwise."

    Design: Corner/calculations/fee_adult_book_and_card_bundle_discount_correct
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK_AND_CARD")
    fee = fx.get_fee_for_application(ctx["application"]["id"], ctx["applicant"]["id"])
    assert fee["base_fee_cents"] == 15000
    assert fee["execution_fee_cents"] == 3500
    assert fee["total_due_cents"] == 18500


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/fee_renewal_no_name_change_no_execution_fee
# ════════════════════════════════════════════════════════════════════════
def test_plain_renewal_has_no_execution_fee(api):
    """PRD §3.2: "for a RENEWAL it is true only when name_change_requested is true
    and the requested name change is not eligible for handling by mail, and it is
    false for a plain renewal." PRD §3.5: "The execution_fee_cents is 3500 cents
    ($35.00) when the application's requires_execution is true, and 0 otherwise."

    Design: Corner/calculations/fee_renewal_no_name_change_no_execution_fee
    """
    ctx = fx.submitted_application(application_type="RENEWAL", product_type="BOOK",
                                   applicant_overrides={"date_of_birth": "1985-01-01"})
    assert ctx["application"]["requires_execution"] is False
    fee = fx.get_fee_for_application(ctx["application"]["id"], ctx["applicant"]["id"])
    assert fee["execution_fee_cents"] == 0
    assert fee["total_due_cents"] == 13000


# ════════════════════════════════════════════════════════════════════════
# Corner/calculations/fee_card_new_execution_only_no_delivery_default
# ════════════════════════════════════════════════════════════════════════
def test_card_new_total_is_6500_with_default_zero_delivery(api):
    """PRD §3.5: "For a card product, the base is 3000 cents ($30.00) for an adult".
    PRD §3.5: "The one_day_delivery_cents is 2136 cents ($21.36) when one-day return
    delivery is purchased — captured by the one_day_delivery boolean input, which
    defaults to false — and 0 otherwise."

    Design: Corner/calculations/fee_card_new_execution_only_no_delivery_default
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="CARD")
    fee = fx.get_fee_for_application(ctx["application"]["id"], ctx["applicant"]["id"])
    assert fee["one_day_delivery_cents"] == 0
    assert fee["execution_fee_cents"] == 3500
    assert fee["total_due_cents"] == 6500
