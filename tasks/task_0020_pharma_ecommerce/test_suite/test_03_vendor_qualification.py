"""Vendor qualification scoring, auto-sweeps, and the depth-4 cascade
(PRD §3.1, §2.11, §3.2).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    create_platform,
    create_vendor,
    create_drug,
    shelve_drug,
    create_and_shelve_drug,
    create_otc_drug_on_shelf,
    create_pharmacist,
    create_customer,
    create_two_pharmacists,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    open_pharmacist_review,
    advance_clock,
    setup_platform_at_clock,
    setup_basic_platform,
    setup_vendor_with_expiries,
    get_vendor,
    get_drug,
    get_order,
    get_prescription,
    get_audit_logs,
    get_external_events,
    find_audit_logs,
    find_external_events,
    prescription_item,
    order_item,
    TEST_USERS,
    make_admin_headers,
    make_vendor_admin_headers,
    FAR_FUTURE_ISO,
)


# ---------------------------------------------------------------------------
# Vendor qualification scoring (PRD §3.1)
# ---------------------------------------------------------------------------

class TestVendorQualificationScoring:
    """PRD §3.1: 'the vendor transitions ACTIVE → REVIEW_REQUIRED' when the
    raw_total → TIER computation yields YELLOW or RED.

    Tier thresholds (PRD §3.1):
      - 0 days remaining (>= 0 but < 30): score 3
      - 30..89 days remaining: score 1
      - >= 90 days remaining: score 0
      - days < 0 (already expired): score 5
      - TIER GREEN if raw_total <= 1
      - TIER YELLOW if 2 <= raw_total <= 4
      - TIER RED if raw_total >= 5
    """

    def test_yellow_tier_triggers_review_required(self, api):
        """PRD §3.1: 'When a vendor in qualification_status ACTIVE enters
        YELLOW or RED ... the vendor transitions ACTIVE → REVIEW_REQUIRED.'

        # difficulty: dual_variant_calc/vendor_qualification_score_ordering_variant
        clock=2025-01-15, expiry=2025-04-01 → L_days=P_days=76 → score(76)=1
        each (since 30 <= 76 < 90), raw_total = 1+1+0=2 → TIER YELLOW.
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-04-01T00:00:00.000Z",
            permit_expires_at="2025-04-01T00:00:00.000Z",
        )
        # Trigger sweep with a negligible advance.
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        vendor_after = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert vendor_after["qualification_status"] == "REVIEW_REQUIRED"

    def test_red_tier_triggers_review_required(self, api):
        """PRD §3.1: 'when a vendor in qualification_status ACTIVE enters
        YELLOW or RED ... the vendor transitions ACTIVE → REVIEW_REQUIRED.'

        # difficulty: combinatorial_formula/vendor_score_circular_tier_then_multiplier
        clock=2025-01-15, expiry=2025-02-10 → L_days=P_days=26 → score(26)=3
        each (since 0 <= 26 < 30), raw_total = 3+3+0=6 → TIER RED (>=5).
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-02-10T00:00:00.000Z",
            permit_expires_at="2025-02-10T00:00:00.000Z",
        )
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        vendor_after = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert vendor_after["qualification_status"] == "REVIEW_REQUIRED"

    def test_green_tier_stays_active(self, api):
        """PRD §3.1: TIER GREEN (raw_total <= 1) leaves vendor ACTIVE.

        Far-future expiries → days >= 90 → score 0 each → raw_total=0 → GREEN.
        No transition is implied; vendor stays ACTIVE.
        """
        s = setup_vendor_with_expiries(api, clock_iso="2025-01-15T00:00:00.000Z")
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        vendor_after = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert vendor_after["qualification_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Vendor SUSPENDED transition (PRD §3.1, §2.11)
# ---------------------------------------------------------------------------

class TestVendorSuspendedTransition:
    """PRD §3.1: 'When the clock subsequently reaches the later of the two
    expiry timestamps, the vendor transitions REVIEW_REQUIRED → SUSPENDED;
    this transition appends an AuditLog row with action VENDOR_SUSPENDED and
    subject_type VENDOR, and it cascades: every drug of this vendor whose
    status is ON_SHELF is moved to OFF_SHELF.'
    """

    def test_clock_past_max_expiry_suspends_vendor(self, api):
        """PRD §3.1: clock >= max(license_expires, permit_expires) → SUSPENDED."""
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-01-20T00:00:00.000Z",
            permit_expires_at="2025-01-25T00:00:00.000Z",
        )
        # Advance past the later expiry.
        advance_clock(api, s["platform"]["id"], "2025-01-26T00:00:00.000Z")
        vendor_after = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert vendor_after["qualification_status"] == "SUSPENDED"

    def test_suspended_appends_audit_log_vendor_suspended(self, api):
        """PRD §3.1: 'this transition appends an AuditLog row with action
        VENDOR_SUSPENDED and subject_type VENDOR.'"""
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-01-20T00:00:00.000Z",
            permit_expires_at="2025-01-25T00:00:00.000Z",
        )
        advance_clock(api, s["platform"]["id"], "2025-01-26T00:00:00.000Z")
        logs = get_audit_logs(api, s["platform"]["id"])
        suspended_logs = find_audit_logs(logs,
                                            subject_id=s["vendor"]["id"],
                                            subject_type="VENDOR",
                                            action="VENDOR_SUSPENDED")
        assert len(suspended_logs) == 1, \
            f"Expected exactly one VENDOR_SUSPENDED audit log, got {len(suspended_logs)}"

    def test_suspended_cascades_drug_to_off_shelf(self, api):
        """PRD §3.1: 'every drug of this vendor whose status is ON_SHELF
        is moved to OFF_SHELF.'

        # difficulty: transitive_cascade/vendor_suspended_drug_offshelf_order_rejected_prescription_archived
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-01-20T00:00:00.000Z",
            permit_expires_at="2025-01-25T00:00:00.000Z",
        )
        pf, vendor = s["platform"], s["vendor"]
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        advance_clock(api, pf["id"], "2025-01-26T00:00:00.000Z")
        drug_after = get_drug(api, pf["id"], drug["id"])
        assert drug_after["status"] == "OFF_SHELF"

    def test_full_depth4_cascade_vendor_drug_order_prescription(self, api):
        """PRD §3.1+§3.2+§3.4: depth-4 cascade.
        PRD §3.1: 'every drug of this vendor whose status is ON_SHELF is
        moved to OFF_SHELF, and that drug-level off-shelving in turn cascades
        into outstanding orders containing those drugs (see §3.2).'
        PRD §3.2: 'every outstanding Order that contains a line referencing
        the off-shelved drug and whose dispensing_status is PENDING_REVIEW or
        PHARMACIST_REVIEWING has its dispensing_status driven to REJECTED.'
        PRD §2.7: 'The system also auto-archives a referenced approved
        prescription as soon as none of its referencing orders are in a
        non-terminal state.'

        # difficulty: transitive_cascade/vendor_suspended_drug_offshelf_order_rejected_prescription_archived
        """
        # Stage at clock=2025-01-01, vendor expiries 2025-01-02.
        clock = "2025-01-01T00:00:00.000Z"
        pf = setup_platform_at_clock(api, clock)
        vendor = create_vendor(
            api, pf["id"],
            business_license_expires_at="2025-01-02T00:00:00.000Z",
            drug_operation_permit_expires_at="2025-01-02T00:00:00.000Z",
        )
        drug = create_and_shelve_drug(
            api, pf["id"], vendor["id"],
            classification="PRESCRIPTION", control_category="NONE",
        )
        customer = create_customer(api, pf["id"], real_name_verified=True)
        pr, rr = create_two_pharmacists(api, pf["id"])
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"], qty=1)],
            issued_at=clock, validity_days=999,
        )
        order = place_order(
            api, pf["id"], customer,
            items=[order_item(drug["id"], qty=1, unit_price_cents=5000)],
            prescription_id=rx["id"],
        )
        # Order in PENDING_REVIEW; pay would also be valid but we test the
        # unpaid path (no refund cascade) so we can verify Order REJECTED
        # without REFUNDED noise.

        # Clock past max expiry → vendor suspended cascade.
        advance_clock(api, pf["id"], "2025-01-02T00:00:00.001Z")

        vendor_after = get_vendor(api, pf["id"], vendor["id"])
        assert vendor_after["qualification_status"] == "SUSPENDED"

        drug_after = get_drug(api, pf["id"], drug["id"])
        assert drug_after["status"] == "OFF_SHELF"

        order_after = get_order(api, pf["id"], order["id"])
        assert order_after["dispensing_status"] == "REJECTED"
        # We never paid; payment_status remains UNPAID (no refund cascade).
        assert order_after["payment_status"] == "UNPAID"

        rx_after = get_prescription(api, pf["id"], rx["id"])
        assert rx_after["status"] == "ARCHIVED", \
            f"Prescription auto-archive expected, got {rx_after['status']}"


# ---------------------------------------------------------------------------
# Vendor re-submission and renewal (PRD §3.1)
# ---------------------------------------------------------------------------

class TestVendorResubmitQualification:
    """PRD §3.1: 'A VendorAdmin whose X-User-ID equals the vendor's id may
    exit REVIEW_REQUIRED or SUSPENDED by re-submitting qualification with a
    new business_license_expires_at and a new drug_operation_permit_expires_at.
    Both renewal timestamps must be strictly greater than current_clock_iso;
    otherwise the request is rejected with ERR_RENEWAL_DATE_NOT_FUTURE.'
    """

    def test_resubmit_to_active_with_future_dates(self, api):
        """PRD §3.1: 'The vendor's qualification_status returns to ACTIVE
        and latest_review_submitted_at is set to current_clock_iso.'

        Identity threading: X-User-ID == vendor.id (entity-backed VendorAdmin).
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-01-20T00:00:00.000Z",
            permit_expires_at="2025-01-20T00:00:00.000Z",
        )
        # Push to REVIEW_REQUIRED (within ALERT_DAYS=30 of expiry).
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        v = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert v["qualification_status"] == "REVIEW_REQUIRED"

        # Resubmit with strictly-future renewal dates as VendorAdmin (vendor.id == X-User-ID).
        resp = api.resubmit_vendor_qualification(
            s["platform"]["id"], s["vendor"]["id"],
            payload={
                "business_license_expires_at": "2099-01-01T00:00:00.000Z",
                "drug_operation_permit_expires_at": "2099-01-01T00:00:00.000Z",
            },
            headers=make_vendor_admin_headers(s["vendor"]["id"]),
        )
        data = validate_success(resp)
        assert data["qualification_status"] == "ACTIVE"

    def test_resubmit_with_past_dates_rejected(self, api):
        """PRD §3.1: 'Both renewal timestamps must be strictly greater than
        current_clock_iso; otherwise the request is rejected with
        ERR_RENEWAL_DATE_NOT_FUTURE.'"""
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-01-20T00:00:00.000Z",
            permit_expires_at="2025-01-20T00:00:00.000Z",
        )
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        # New license dates equal to (NOT strictly greater than) the clock.
        resp = api.resubmit_vendor_qualification(
            s["platform"]["id"], s["vendor"]["id"],
            payload={
                "business_license_expires_at": "2025-01-15T00:00:00.001Z",
                "drug_operation_permit_expires_at": "2099-01-01T00:00:00.000Z",
            },
            headers=make_vendor_admin_headers(s["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_DATE_NOT_FUTURE.value)

    def test_resubmit_active_vendor_rejected(self, api):
        """PRD §3.1: 'Re-submitting qualification on a vendor that is
        currently ACTIVE is rejected with ERR_VENDOR_NOT_IN_REVIEW.'"""
        s = setup_vendor_with_expiries(api)  # ACTIVE
        resp = api.resubmit_vendor_qualification(
            s["platform"]["id"], s["vendor"]["id"],
            payload={
                "business_license_expires_at": "2099-06-01T00:00:00.000Z",
                "drug_operation_permit_expires_at": "2099-06-01T00:00:00.000Z",
            },
            headers=make_vendor_admin_headers(s["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_IN_REVIEW.value)

    def test_resubmit_does_not_auto_re_shelve_drugs(self, api):
        """PRD §3.1: 'Note that re-activating a previously SUSPENDED vendor
        does not auto re-shelve that vendor's drugs — they remain OFF_SHELF
        and a PlatformAdmin must explicitly re-shelve each one.'"""
        clock = "2025-01-01T00:00:00.000Z"
        pf = setup_platform_at_clock(api, clock)
        vendor = create_vendor(
            api, pf["id"],
            business_license_expires_at="2025-01-05T00:00:00.000Z",
            drug_operation_permit_expires_at="2025-01-05T00:00:00.000Z",
        )
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        # Advance past expiry → vendor SUSPENDED, drug OFF_SHELF (cascade).
        advance_clock(api, pf["id"], "2025-01-06T00:00:00.000Z")
        # Re-activate vendor.
        api.resubmit_vendor_qualification(
            pf["id"], vendor["id"],
            payload={
                "business_license_expires_at": "2099-01-01T00:00:00.000Z",
                "drug_operation_permit_expires_at": "2099-01-01T00:00:00.000Z",
            },
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        drug_after = get_drug(api, pf["id"], drug["id"])
        assert drug_after["status"] == "OFF_SHELF", \
            "Drug must remain OFF_SHELF after vendor re-activation; PRD §3.1 forbids auto re-shelve"
