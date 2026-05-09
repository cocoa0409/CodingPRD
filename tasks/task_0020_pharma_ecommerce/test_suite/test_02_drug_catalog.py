"""Drug catalog: NDC validation, classification rules, shelving lifecycle,
and off-shelve cascade (PRD §2.9, §3.2).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    create_drug_payload,
    create_platform,
    setup_basic_platform,
    setup_otc_purchase_scenario,
    setup_approved_prescription_with_order,
    create_drug,
    shelve_drug,
    create_and_shelve_drug,
    create_otc_drug_on_shelf,
    create_vendor,
    create_pharmacist,
    create_customer,
    place_order,
    pay_order,
    get_order,
    get_drug,
    get_audit_logs,
    get_external_events,
    find_audit_logs,
    find_external_events,
    advance_clock,
    upload_and_approve_prescription,
    open_pharmacist_review,
    create_two_pharmacists,
    prescription_item,
    order_item,
    unique_ndc,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_vendor_admin_headers,
    FAR_FUTURE_ISO,
)


# ---------------------------------------------------------------------------
# NDC format and uniqueness (PRD §2.9)
# ---------------------------------------------------------------------------

class TestNDCValidation:
    """PRD §2.9: 'The ndc must match the regular expression
    ^\\d{4,5}-\\d{3,4}-\\d{1,2}$ — a digit group of 4 or 5 digits, then a
    digit group of 3 or 4 digits, then a digit group of 1 or 2 digits,
    separated by hyphens; if the format is wrong the create call is rejected
    with ERR_NDC_INVALID_FORMAT.'
    """

    @pytest.mark.parametrize("bad_ndc", [
        "123-456-78",        # first group only 3 digits
        "12345-12-12",       # second group only 2 digits
        "12345-1234-",       # missing third group
        "abcde-1234-12",     # non-numeric
        "12345 1234 12",     # spaces, no hyphens
        "",                   # empty
    ])
    def test_invalid_ndc_rejected(self, api, bad_ndc):
        """PRD §2.9: 'if the format is wrong the create call is rejected
        with ERR_NDC_INVALID_FORMAT.'"""
        pf, vendor = setup_basic_platform(api)
        payload = create_drug_payload(vendor["id"], ndc=bad_ndc)
        resp = api.create_drug(pf["id"], payload, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NDC_INVALID_FORMAT.value)

    def test_valid_ndc_5_4_2_accepted(self, api):
        """PRD §2.9: 5-4-2 digits is valid."""
        pf, vendor = setup_basic_platform(api)
        resp = api.create_drug(pf["id"],
                                  create_drug_payload(vendor["id"], ndc="12345-1234-12"),
                                  TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["ndc"] == "12345-1234-12"

    def test_valid_ndc_4_3_1_accepted(self, api):
        """PRD §2.9: 4-3-1 digits is also valid."""
        pf, vendor = setup_basic_platform(api)
        resp = api.create_drug(pf["id"],
                                  create_drug_payload(vendor["id"], ndc="1234-123-1"),
                                  TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["ndc"] == "1234-123-1"

    def test_ndc_duplicate_among_on_shelf_rejected(self, api):
        """PRD §2.9: 'Within a single platform, two drugs that are not in
        OFF_SHELF may not share the same ndc; a duplicate is rejected with
        ERR_NDC_DUPLICATE.'"""
        pf, vendor = setup_basic_platform(api)
        ndc = unique_ndc()
        # First drug created and shelved (ON_SHELF).
        d1 = create_and_shelve_drug(api, pf["id"], vendor["id"], ndc=ndc)
        # Second drug with same NDC: PRD §2.9 says 'two drugs that are not
        # in OFF_SHELF may not share the same ndc' — d1 is ON_SHELF, so the
        # second create is a non-OFF_SHELF collision.
        resp = api.create_drug(pf["id"],
                                  create_drug_payload(vendor["id"], ndc=ndc),
                                  TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NDC_DUPLICATE.value)


# ---------------------------------------------------------------------------
# Control category × classification rule (PRD §2.9)
# ---------------------------------------------------------------------------

class TestControlCategoryClassification:
    """PRD §2.9: 'Any drug whose control_category is not NONE must have
    classification equal to PRESCRIPTION; the mismatch is rejected with
    ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION.'
    """

    @pytest.mark.parametrize("category", ["NARCOTIC", "PSYCHOTROPIC_I",
                                              "PSYCHOTROPIC_II", "TOXIC"])
    def test_otc_with_control_category_rejected(self, api, category):
        """PRD §2.9: control_category != NONE + classification=OTC → reject."""
        pf, vendor = setup_basic_platform(api)
        resp = api.create_drug(pf["id"],
                                  create_drug_payload(vendor["id"],
                                                        classification="OTC",
                                                        control_category=category),
                                  TEST_USERS["admin_headers"])
        validate_error(resp,
                         ApiErrorId.ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION.value)

    def test_prescription_with_control_category_accepted(self, api):
        """PRD §2.9: control_category != NONE with classification=PRESCRIPTION succeeds."""
        pf, vendor = setup_basic_platform(api)
        resp = api.create_drug(pf["id"],
                                  create_drug_payload(vendor["id"],
                                                        classification="PRESCRIPTION",
                                                        control_category="PSYCHOTROPIC_II"),
                                  TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["control_category"] == "PSYCHOTROPIC_II"
        assert data["classification"] == "PRESCRIPTION"


# ---------------------------------------------------------------------------
# Drug shelving lifecycle (PRD §3.2)
# ---------------------------------------------------------------------------

class TestDrugShelvingLifecycle:
    """PRD §3.2: 'A new Drug is created in status PENDING_REVIEW.' shelve
    moves PENDING_REVIEW → ON_SHELF; off-shelve moves ON_SHELF → OFF_SHELF;
    re-shelve moves OFF_SHELF → ON_SHELF.
    """

    def test_drug_starts_pending_review(self, api):
        """PRD §3.2: 'A new Drug is created in status PENDING_REVIEW.'"""
        pf, vendor = setup_basic_platform(api)
        drug = create_drug(api, pf["id"], vendor["id"])
        assert drug["status"] == "PENDING_REVIEW"

    def test_shelve_pending_review_to_on_shelf(self, api):
        """PRD §3.2: 'A PlatformAdmin shelves a drug, transitioning it from
        PENDING_REVIEW to ON_SHELF.'"""
        pf, vendor = setup_basic_platform(api)
        drug = create_drug(api, pf["id"], vendor["id"])
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "ON_SHELF"

    def test_shelve_already_on_shelf_rejected(self, api):
        """PRD §3.2: 'shelves a drug ... only if the drug is currently
        PENDING_REVIEW (otherwise ERR_DRUG_NOT_PENDING_REVIEW).'"""
        pf, vendor = setup_basic_platform(api)
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])  # already ON_SHELF
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_DRUG_NOT_PENDING_REVIEW.value)

    def test_off_shelve_on_shelf_drug(self, api):
        """PRD §3.2: 'Off-shelving moves an ON_SHELF drug to OFF_SHELF.'"""
        pf, vendor = setup_basic_platform(api)
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        resp = api.off_shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "OFF_SHELF"

    def test_off_shelve_pending_review_rejected(self, api):
        """PRD §3.2: 'the precondition is that the drug be currently
        ON_SHELF (otherwise ERR_DRUG_NOT_ON_SHELF).'"""
        pf, vendor = setup_basic_platform(api)
        drug = create_drug(api, pf["id"], vendor["id"])  # PENDING_REVIEW
        resp = api.off_shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_DRUG_NOT_ON_SHELF.value)

    def test_shelve_requires_active_vendor(self, api):
        """PRD §3.2: 'shelves a drug ... only if ... the drug's vendor has
        qualification_status equal to ACTIVE (otherwise ERR_VENDOR_NOT_ACTIVE).'

        # difficulty: cross_entity_state_dependency/drug_shelve_requires_vendor_active
        We force the vendor into REVIEW_REQUIRED via vendor_qualification scoring:
        PRD §3.1 says 'when a vendor in qualification_status ACTIVE enters
        YELLOW or RED ... the vendor transitions ACTIVE → REVIEW_REQUIRED.'
        Setting expiry 15 days out yields score(15)=3 per component,
        raw_total=6, TIER=RED → REVIEW_REQUIRED on clock advance.
        """
        clock = "2025-01-15T00:00:00.000Z"
        pf = create_platform(api)
        advance_clock(api, pf["id"], clock)
        # 15-days-out expiry -> score 3 each, raw_total=6 → RED.
        vendor = create_vendor(api, pf["id"],
                                  business_license_expires_at="2025-01-30T00:00:00.000Z",
                                  drug_operation_permit_expires_at="2025-01-30T00:00:00.000Z")
        drug = create_drug(api, pf["id"], vendor["id"])
        # Trigger sweep: a one-millisecond clock advance.
        advance_clock(api, pf["id"], "2025-01-15T00:00:00.001Z")
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Off-shelve cascade (PRD §3.2)
# ---------------------------------------------------------------------------

class TestOffShelveCascade:
    """PRD §3.2: 'Off-shelving cascades: every outstanding Order that contains
    a line referencing the off-shelved drug and whose dispensing_status is
    PENDING_REVIEW or PHARMACIST_REVIEWING has its dispensing_status driven
    to REJECTED. Any of those orders that were already PAID cascade further:
    their payment_status flips from PAID to REFUNDED, an AuditLog row with
    action ORDER_REFUNDED is appended, and an ExternalEvent on channel
    PAYMENT with event_type order.refunded is emitted.'
    """

    def test_off_shelve_cancels_pending_review_order(self, api):
        """PRD §3.2: order in PENDING_REVIEW gets driven to REJECTED on off-shelve."""
        s = setup_otc_purchase_scenario(api)
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=1000)])
        # Off-shelve.
        api.off_shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        order_after = get_order(api, pf["id"], order["id"])
        assert order_after["dispensing_status"] == "REJECTED"

    def test_off_shelve_paid_order_triggers_refund_cascade(self, api):
        """PRD §3.2: 'Any of those orders that were already PAID cascade
        further: their payment_status flips from PAID to REFUNDED, an
        AuditLog row with action ORDER_REFUNDED is appended, and an
        ExternalEvent on channel PAYMENT with event_type order.refunded is
        emitted.'

        # difficulty: transitive_cascade/review_reject_order_reject_payment_refund (sibling)
        """
        s = setup_otc_purchase_scenario(api)
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=1000)])
        order = pay_order(api, pf["id"], order)
        assert order["payment_status"] == "PAID"

        api.off_shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])

        order_after = get_order(api, pf["id"], order["id"])
        assert order_after["dispensing_status"] == "REJECTED"
        assert order_after["payment_status"] == "REFUNDED"

        # AuditLog ORDER_REFUNDED row
        logs = get_audit_logs(api, pf["id"])
        refund_logs = find_audit_logs(logs, subject_id=order["id"],
                                          action="ORDER_REFUNDED")
        assert len(refund_logs) == 1, \
            f"Expected exactly one ORDER_REFUNDED audit log, got {len(refund_logs)}"

        # ExternalEvent order.refunded
        events = get_external_events(api, pf["id"])
        refund_events = find_external_events(events, channel="PAYMENT",
                                                 event_type="order.refunded",
                                                 subject_id=order["id"])
        assert len(refund_events) == 1, \
            f"Expected exactly one order.refunded ExternalEvent, got {len(refund_events)}"


# ---------------------------------------------------------------------------
# Re-shelve from OFF_SHELF (PRD §3.2)
# ---------------------------------------------------------------------------

class TestReShelve:
    """PRD §3.2: 'The same shelve capability also re-shelves a drug from
    OFF_SHELF back to ON_SHELF provided the drug is currently OFF_SHELF
    (otherwise ERR_DRUG_NOT_OFF_SHELF when the caller's intent is a
    re-shelve) and the vendor is again ACTIVE (otherwise
    ERR_VENDOR_NOT_ACTIVE).'
    """

    def test_re_shelve_off_shelf_drug_succeeds(self, api):
        """PRD §3.2: re-shelve from OFF_SHELF returns drug to ON_SHELF."""
        pf, vendor = setup_basic_platform(api)
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        api.off_shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "ON_SHELF"
