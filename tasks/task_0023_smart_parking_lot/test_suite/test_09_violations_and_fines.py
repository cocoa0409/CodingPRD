"""Violations, Fines, and tow coordination (PRD §3.6, §2.10)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    advance_clock,
    api_client,
    assert_violation,
    create_violation_payload,
    create_vehicle,
    get_session,
    get_vehicle,
    get_violation,
    issue_violation,
    list_audit_logs,
    make_driver_headers,
    make_officer_headers,
    patch_violation_payload,
    pay_violation,
    pay_violation_payload,
    setup_lot_zone_spaces,
    setup_session_then_overstay_violation,
    setup_violation_pending,
    TEST_USERS,
    tow_violation_payload,
    unique_external_ref,
    unique_officer_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Photo evidence required
# ===========================================================================
class TestPhotoRequired:
    @pytest.mark.parametrize("violation_type", ["BLOCKING", "WRONG_ZONE"])
    def test_blocking_or_wrong_zone_without_photo_rejected(
        self, api, officer_headers, violation_type
    ):
        """PRD §3.6: 'When violation_type is BLOCKING or WRONG_ZONE, the
        photo_uri must be non-empty; an empty or missing photo_uri for
        these types is rejected with ERR_PHOTO_REQUIRED.'"""
        advance_clock("2026-05-01T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type=violation_type,
            space_id=spaces[0]["id"],
            detected_at="2026-05-01T10:00:00.000Z",
            photo_uri=None,
            officer_id=unique_officer_id(),
        )
        res = api.create_violation(payload, officer_headers)
        validate_error(res, "ERR_PHOTO_REQUIRED")

    @pytest.mark.parametrize("violation_type", ["OVERSTAY", "NON_PAYING"])
    def test_overstay_or_non_paying_without_photo_accepted(
        self, api, officer_headers, violation_type
    ):
        """PRD §3.6: photo only required for BLOCKING or WRONG_ZONE.
        OVERSTAY/NON_PAYING accept an absent photo."""
        advance_clock("2026-05-01T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type=violation_type,
            space_id=spaces[0]["id"],
            detected_at="2026-05-01T10:00:00.000Z",
            photo_uri=None,
            officer_id=unique_officer_id(),
        )
        res = api.create_violation(payload, officer_headers)
        data = validate_success(res, expected_status=201)
        assert data["violation_type"] == violation_type


# ===========================================================================
# §2.10 — Vehicle exemption blocks OVERSTAY/NON_PAYING
# ===========================================================================
class TestExemptVehicleViolation:
    @pytest.mark.parametrize("kind", ["EMERGENCY", "DISABLED"])
    @pytest.mark.parametrize("violation_type", ["OVERSTAY", "NON_PAYING"])
    def test_exempt_vehicle_overstay_or_non_paying_rejected(
        self, api, officer_headers, kind, violation_type
    ):
        """PRD §2.10: 'an attempt to ... issue an OVERSTAY or NON_PAYING
        violation against it, is rejected with ERR_EXEMPT_VEHICLE.'"""
        advance_clock("2026-05-02T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle(kind=kind)
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type=violation_type,
            space_id=spaces[0]["id"],
            detected_at="2026-05-02T10:00:00.000Z",
            officer_id=unique_officer_id(),
            photo_uri=None,
        )
        res = api.create_violation(payload, officer_headers)
        validate_error(res, "ERR_EXEMPT_VEHICLE")

    @pytest.mark.parametrize("kind", ["EMERGENCY", "DISABLED"])
    def test_exempt_vehicle_blocking_still_enforced(
        self, api, officer_headers, kind
    ):
        """PRD §2.10: 'BLOCKING and WRONG_ZONE violations remain enforceable
        against exempt vehicles on the same terms as any other vehicle.'"""
        advance_clock("2026-05-03T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle(kind=kind)
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type="BLOCKING",
            space_id=spaces[0]["id"],
            detected_at="2026-05-03T10:00:00.000Z",
            photo_uri="s3://photo/x.jpg",
            officer_id=unique_officer_id(),
        )
        res = api.create_violation(payload, officer_headers)
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.6 — Fine amount calculation (probed via /pay amount equality)
# ===========================================================================
class TestFineAmountCalculation:
    def test_overstay_no_prior_no_photo_pays_at_2000(self, api):
        """PRD §3.6: 'OVERSTAY is 2000 cents ($20.00) ... OVERSTAY is 1.0
        ... a count of zero implies a zero surcharge ... The final amount
        is computed by first multiplying base_cents by type_multiplier in
        arbitrary-precision decimal, rounding the product half-up to the
        nearest integer cent, and then adding the photo-required surcharge
        and the repeat-offender surcharge as integer cents.'

        Claim: Fine.amount_cents = 2000*1.0 + 0 (no photo) + 0 (no prior)
        = 2000. Probed via /violations/{id}/pay which requires
        amount_cents 'exactly equal to the fine's amount_cents'."""
        scen = setup_violation_pending(
            base_iso="2026-05-04T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        # Pay with exact computed amount: must succeed.
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=2000,
            external_ref=unique_external_ref(),
        )
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PAID"

    def test_blocking_no_prior_with_photo_pays_at_11500(self, api):
        """PRD §3.6: 'BLOCKING is 5000 cents ($50.00) ... BLOCKING is 2.0
        ... The photo-required surcharge is 1500 cents when violation_type
        is BLOCKING or WRONG_ZONE.'

        Claim: Fine.amount_cents = 5000*2.0 + 1500 (photo) + 0 (no prior)
        = 11500."""
        scen = setup_violation_pending(
            base_iso="2026-05-05T10:00:00.000Z",
            violation_type="BLOCKING",
            photo_uri="s3://e/p.jpg",
        )
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=11500,
            external_ref=unique_external_ref(),
        )
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PAID"

    def test_wrong_zone_no_prior_with_photo_pays_at_6500(self, api):
        """PRD §3.6: 'WRONG_ZONE is 4000 cents ($40.00) ... WRONG_ZONE is
        1.25 ... The photo-required surcharge is 1500 cents when
        violation_type is BLOCKING or WRONG_ZONE.'

        Claim: Fine.amount_cents = round(4000*1.25)+1500+0 = 5000+1500 = 6500."""
        scen = setup_violation_pending(
            base_iso="2026-05-06T10:00:00.000Z",
            violation_type="WRONG_ZONE",
            photo_uri="s3://e/wz.jpg",
        )
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=6500,
            external_ref=unique_external_ref(),
        )
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PAID"


# ===========================================================================
# §3.6 — Violation lifecycle: dispute / revert / pay
# ===========================================================================
class TestViolationLifecycle:
    def test_driver_dispute_pending_to_disputed(self, api):
        """PRD §3.6: 'A Driver may dispute a PENDING violation by patching
        its status to DISPUTED.'"""
        scen = setup_violation_pending(
            base_iso="2026-05-10T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="DISPUTED",
                                    reason="I left at 9:55"),
            headers,
        )
        validate_success(res, expected_status=200)
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "DISPUTED"

    def test_operator_revert_disputed_to_pending(self, api, operator_headers):
        """PRD §3.6: 'An Operator may flip a DISPUTED violation back to
        PENDING by patching its status to PENDING.'"""
        scen = setup_violation_pending(
            base_iso="2026-05-11T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        # First Driver disputes
        api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="DISPUTED", reason="dispute"),
            make_driver_headers(scen["vehicle"]["id"]),
        )
        # Now Operator reverts
        res = api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="PENDING",
                                    reason="evidence reviewed"),
            operator_headers,
        )
        validate_success(res, expected_status=200)
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PENDING"

    def test_dispute_outside_14_days_rejected(self, api):
        """PRD §3.6: 'the dispute is admitted only when the current instant
        is at or before detected_at plus 14 days.'
        PRD §2.7: state-machine eligibility yields ERR_INVALID_STATE."""
        scen = setup_violation_pending(
            base_iso="2026-05-12T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        # Advance 15 days
        advance_clock("2026-05-27T10:00:00.000Z")
        res = api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="DISPUTED", reason="late"),
            make_driver_headers(scen["vehicle"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pay_violation_exact_amount_succeeds(self, api):
        """PRD §3.6: 'On success, Violation.status transitions from PENDING
        to PAID ... the vehicle's open_violation_count decrements by one
        and binding_eligible is recomputed (true exactly when
        open_violation_count is now zero).'"""
        # OVERSTAY no prior no photo → 2000.
        scen = setup_violation_pending(
            base_iso="2026-05-14T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=2000,
            external_ref=unique_external_ref(),
        )
        v2 = get_violation(scen["violation"]["id"])
        assert v2["status"] == "PAID"
        veh = get_vehicle(scen["vehicle"]["id"])
        assert veh["open_violation_count"] == 0
        assert veh["binding_eligible"] is True


# ===========================================================================
# §3.6 — Tow coordination
# ===========================================================================
class TestTowCoordination:
    def test_tow_requires_24h_unpaid(self, api, operator_headers):
        """PRD §3.6: 'An Operator may coordinate a tow on a PENDING
        violation older than 24 hours by supplying a non-empty reason ...
        Fine.amount_cents has gone unpaid for at least 24 hours since
        detected_at.'"""
        scen = setup_violation_pending(
            base_iso="2026-05-15T10:00:00.000Z",
            violation_type="BLOCKING",
            photo_uri="s3://e/p.jpg",
        )
        # Try to tow at +1 hour — too early
        advance_clock("2026-05-15T11:00:00.000Z")
        res = api.tow_violation(
            scen["violation"]["id"],
            tow_violation_payload(reason="vehicle towed"),
            operator_headers,
        )
        # PRD §2.7 / §3.6: state-machine precondition not met
        validate_error(res, "ERR_INVALID_STATE")

    def test_tow_after_24h_succeeds(self, api, operator_headers):
        """PRD §3.6: 'Fine.amount_cents has gone unpaid for at least 24
        hours since detected_at. On success, Violation.status transitions
        to TOWED_AWAY.'"""
        scen = setup_violation_pending(
            base_iso="2026-05-16T10:00:00.000Z",
            violation_type="BLOCKING",
            photo_uri="s3://e/p.jpg",
        )
        # Advance >24h
        advance_clock("2026-05-17T11:00:00.000Z")
        res = api.tow_violation(
            scen["violation"]["id"],
            tow_violation_payload(reason="vehicle towed; 24h+"),
            operator_headers,
        )
        validate_success(res, expected_status=200)
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "TOWED_AWAY"

    def test_overstay_violation_cascades_session_to_disputed(self, api):
        """PRD §3.6: 'When the violation's violation_type is OVERSTAY and
        the linked session is EXITED and currently UNPAID, the session's
        payment_status cascades from UNPAID to DISPUTED.'"""
        scen = setup_session_then_overstay_violation(
            base_iso="2026-06-01T08:00:00.000Z"
        )
        viol = issue_violation(
            lot_id=scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
            violation_type="OVERSTAY",
            detected_at="2026-06-01T09:00:00.000Z",
            session_id=scen["session"]["id"],
        )
        sess = get_session(scen["session"]["id"])
        assert sess["payment_status"] == "DISPUTED"
        veh = get_vehicle(scen["vehicle"]["id"])
        assert veh["binding_eligible"] is False
        assert veh["open_violation_count"] == 1
