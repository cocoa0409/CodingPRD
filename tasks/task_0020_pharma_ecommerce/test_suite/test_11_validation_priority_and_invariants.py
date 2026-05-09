"""Validation priority pairings explicitly named by PRD prose, plus
domain invariants that PRD prose pins (PRD §3.4, §3.5, §3.6, §2.4).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_prescription_scenario,
    setup_basic_platform,
    setup_otc_purchase_scenario,
    setup_approved_prescription_with_order,
    upload_prescription,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    cancel_order,
    create_pharmacist,
    create_customer,
    create_otc_drug_on_shelf,
    create_two_pharmacists,
    open_pharmacist_review,
    advance_clock,
    setup_platform_at_clock,
    create_purchase_limit_rule_payload,
    open_pharmacist_review_payload,
    create_order_payload,
    prescription_item,
    order_item,
    add_to_denylist,
    TEST_USERS,
    make_customer_headers,
    make_prescription_reviewer_headers,
    make_pharmacist_re_reviewer_headers,
)


# ---------------------------------------------------------------------------
# State-vs-segregation precedence (PRD §3.6 + §3.6 SOD note)
# ---------------------------------------------------------------------------

class TestStateVsSegregationPrecedence:
    """PRD §3.6 (open-review): the order's dispensing_status must be
    PENDING_REVIEW (otherwise ERR_ORDER_NOT_REVIEWABLE); also, X-User-ID
    must differ from prescription.reviewer_pharmacist_id (otherwise
    ERR_SEGREGATION_OF_DUTIES_VIOLATION).

    PRD §3.6 lists state as the first precondition ('The order's
    dispensing_status must be PENDING_REVIEW (otherwise
    ERR_ORDER_NOT_REVIEWABLE).') — but PRD does not commit to a strict
    ordering for which error fires when both fail. Two PRD-faithful
    implementers could legitimately diverge here. We accept either id.

    # difficulty: priority_pair_validation_conflict/state_vs_segregation_of_duties
    """

    def test_state_vs_sod_when_both_fail(self, api):
        """When dispensing_status is not PENDING_REVIEW AND the acting
        pharmacist is the prescription's reviewer, either ERR_ORDER_NOT_REVIEWABLE
        or ERR_SEGREGATION_OF_DUTIES_VIOLATION is acceptable per PRD."""
        s = setup_approved_prescription_with_order(api)
        # Cancel order so dispensing_status is CANCELLED (not PENDING_REVIEW).
        cancel_order(api, s["platform"]["id"], s["order"])
        # Open-pharmacist-review with PR pharmacist (the reviewer) → SOD violation.
        from test_helpers import validate_error_is_one_of
        payload = open_pharmacist_review_payload(s["pr_pharmacist"]["id"])
        resp = api.open_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], payload,
            make_pharmacist_re_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ORDER_NOT_REVIEWABLE.value,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        ])


# ---------------------------------------------------------------------------
# Prescription expired vs contraindication (PRD §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionExpiredVsContraindication:
    """PRD §3.4 lists approval preconditions but does NOT explicitly commit
    to which error fires first when multiple preconditions fail
    simultaneously. Both ERR_PRESCRIPTION_EXPIRED and
    ERR_CONTRAINDICATION_VIOLATION are PRD-faithful outcomes for an
    'expired AND contraindicated' approval. We accept either id.

    # difficulty: priority_pair_validation_conflict/prescription_expired_vs_contraindication
    """

    def test_expired_and_contraindicated_returns_one_of(self, api):
        clock = "2025-02-01T00:00:00.000Z"
        s = setup_prescription_scenario(
            api, clock_iso=clock,
            drug_overrides={"contraindications": ["PREGNANCY"]},
            customer_overrides={"special_population_flags": ["PREGNANCY"]},
        )
        # issued_at long ago, validity 7 days → prescription expired by 2025-02-01.
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=7,
        )
        from test_helpers import validate_error_is_one_of
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PRESCRIPTION_EXPIRED.value,
            ApiErrorId.ERR_CONTRAINDICATION_VIOLATION.value,
        ])

    def test_with_only_contraindication_returns_contraindication(self, api):
        """When ONLY contraindication fails (prescription not expired),
        ERR_CONTRAINDICATION_VIOLATION is uniquely required."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_prescription_scenario(
            api, clock_iso=clock,
            drug_overrides={"contraindications": ["PREGNANCY"]},
            customer_overrides={"special_population_flags": ["PREGNANCY"]},
        )
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at=clock, validity_days=999,  # not expired
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRAINDICATION_VIOLATION.value)


# ---------------------------------------------------------------------------
# Compensating invariant: refunded total matches paid total (PRD §3.5)
# ---------------------------------------------------------------------------

class TestPaidRefundCompensatingInvariant:
    """PRD §3.5: 'Payment becoming REFUNDED is always a system-driven
    cascade — there is no direct refund endpoint; it occurs whenever a
    PAID order's dispensing_status flips to REJECTED or CANCELLED.'
    PRD §2.7: 'Each cascaded mutation refreshes the affected row's
    updated_at and increments its version.'

    Per pay-then-cancel sequence, a customer's net unrefunded paid amount
    must be unchanged: PAID first adds total to the PAID-sum; CANCEL moves
    payment_status to REFUNDED and the same row now contributes to the
    REFUNDED-sum, so the net = paid - refunded == 0.

    # difficulty: compensating_invariant/paid_minus_refunded_invariant_on_cancel_cascade
    """

    def test_pay_then_cancel_idempotent_refund_event(self, api):
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=2, unit_price_cents=12_999)])
        # 2 * 12999 = 25998
        assert order["total_amount_cents"] == 25_998
        order = pay_order(api, s["platform"]["id"], order)
        cancelled = cancel_order(api, s["platform"]["id"], order)
        assert cancelled["payment_status"] == "REFUNDED"

        # Exactly one order.refunded ExternalEvent (PRD §2.8 idempotency).
        from test_helpers import get_external_events, find_external_events
        events = get_external_events(api, s["platform"]["id"])
        match = find_external_events(events, channel="PAYMENT",
                                         event_type="order.refunded",
                                         subject_id=order["id"])
        assert len(match) == 1


# ---------------------------------------------------------------------------
# Append-only entities: AuditLog/ExternalEvent shape (PRD §2.4)
# ---------------------------------------------------------------------------

class TestAppendOnlyEntityShape:
    """PRD §2.4: 'Two entities are append-only logs and do not participate
    in the common-fields convention: AuditLog and ExternalEvent carry only
    id and created_at; they have no updated_at and no version.
    PrescriberDenylistEntry is similarly append-only with no updated_at and
    no version.'
    """

    def test_audit_log_no_updated_at_or_version(self, api):
        """AuditLog rows lack updated_at and version."""
        # Trigger an audit-emitting transition: prescription approve.
        s = setup_prescription_scenario(api)
        from test_helpers import upload_prescription
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        from test_helpers import get_audit_logs
        logs = get_audit_logs(api, s["platform"]["id"])
        assert len(logs) >= 1
        for entry in logs:
            assert "updated_at" not in entry, \
                f"AuditLog must NOT carry updated_at; got {entry.get('updated_at')}"
            assert "version" not in entry, \
                f"AuditLog must NOT carry version; got {entry.get('version')}"

    def test_external_event_no_updated_at_or_version(self, api):
        """ExternalEvent rows lack updated_at and version."""
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        pay_order(api, s["platform"]["id"], order)
        from test_helpers import get_external_events
        events = get_external_events(api, s["platform"]["id"])
        assert len(events) >= 1
        for evt in events:
            assert "updated_at" not in evt, \
                f"ExternalEvent must NOT carry updated_at; got {evt.get('updated_at')}"
            assert "version" not in evt, \
                f"ExternalEvent must NOT carry version; got {evt.get('version')}"
