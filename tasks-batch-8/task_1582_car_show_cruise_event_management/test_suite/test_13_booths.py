"""Booth applications: fee computation, paid-gated assignment, space set
semantics, cancellation compensation, and vendor ownership."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_vendor_headers,
    create_published_event, create_booth_application_payload,
    create_booth_at_state, get_zone, get_summary,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


def _published_with_vendor_zone(api, **zone_overrides):
    ev, cls, zone = create_published_event(
        zone_overrides={"name": "Vendor Row", "zone_type": "VENDOR_ROW",
                        "capacity": 10, "has_power": True, **zone_overrides})
    return ev, zone


class TestBoothFeeComputation:
    def test_booth_fee_with_power_constant(self, api):
        """PRD §3.9: "computes the application's `fee_cents` as the tier fee plus
        a power surcharge: 7,500 cents for `SINGLE`, 14,000 for `DOUBLE`, 25,000
        for `SPONSOR`, and exactly 1,500 cents added when `power_requested` is
        set; the fee is integer cents with no rounding."

        Design: Corner/calculations/booth_fee_with_power_constant
        """
        ev, zone = _published_with_vendor_zone(api)
        powered = get_success_data(api.create_booth_application(
            create_booth_application_payload(ev["id"], business_name="Power Co",
                                             contact_email="pc@example.com",
                                             booth_tier="DOUBLE", power_requested=True), ORG))
        plain = get_success_data(api.create_booth_application(
            create_booth_application_payload(ev["id"], business_name="Plain Co",
                                             contact_email="pl@example.com",
                                             booth_tier="SINGLE"), ORG))
        f1 = validate_success(api.approve_booth_application(powered["id"], ORG))
        f2 = validate_success(api.approve_booth_application(plain["id"], ORG))
        assert f1["fee_cents"] == 15500, "DOUBLE 14000 + power 1500"
        assert f2["fee_cents"] == 7500


class TestAssignRequiresPaid:
    def _setup_approved_double(self, api):
        ev, zone = _published_with_vendor_zone(api)
        app = create_booth_at_state(ev["id"], target_state="APPROVED", tier="DOUBLE",
                                    business_name="Wax Works",
                                    contact_email="wax@example.com")
        return ev, zone, app

    def test_assign_while_approved_rejected(self, api):
        """PRD §3.9: "Assigning a booth takes a `zone_id` and a list of `spaces`
        and requires the application to be `PAID`, else `ERR_INVALID_BOOTH_STATE`."

        Design: Difficulty/cross_entity_state_dependency/booth_assign_requires_paid_state
        """
        ev, zone, app = self._setup_approved_double(api)
        assert app["fee_cents"] == 14000, "TIER_FEE_DOUBLE, no power"
        resp = api.assign_booth(app["id"], {"zone_id": zone["id"], "spaces": [1, 2]}, ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOTH_STATE)

    def test_payment_unblocks_assign(self, api):
        """PRD §3.9: "Acceptance writes a `BOOTH_FEE` payment, grows the
        application's `paid_cents`, credits the event treasury (incrementing the
        event's `version`), and moves the application to `PAID`." and "Success
        sets the application's `assigned_zone_id` and `assigned_spaces`, raises
        the zone's `assigned_count` by the number of spaces, and lands the
        application in `ASSIGNED`."

        Design: Difficulty/cross_entity_state_dependency/booth_assign_requires_paid_state
        """
        ev, zone, app = self._setup_approved_double(api)
        get_success_data(api.create_booth_payment(
            app["id"], {"amount_cents": 14000, "method": "CARD"}, ORG))
        assigned = validate_success(api.assign_booth(
            app["id"], {"zone_id": zone["id"], "spaces": [1, 2]}, ORG))
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_spaces"] == [1, 2]
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 2


class TestBoothSpaceSets:
    def _setup(self, api):
        ev, zone = _published_with_vendor_zone(api)
        b1 = create_booth_at_state(ev["id"], target_state="ASSIGNED", zone=zone,
                                   spaces=[3], tier="SINGLE", business_name="Single Co",
                                   contact_email="s@example.com")
        b2 = create_booth_at_state(ev["id"], target_state="PAID", tier="DOUBLE",
                                   business_name="Double Co",
                                   contact_email="d@example.com")
        return ev, zone, b1, b2

    def test_occupied_space_conflict_rejected(self, api):
        """PRD §3.9: "no requested space may intersect the `assigned_spaces` of
        any other `ASSIGNED` application in that zone, else
        `ERR_BOOTH_SPACE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/booth_space_set_conflict
        """
        ev, zone, b1, b2 = self._setup(api)
        resp = api.assign_booth(b2["id"], {"zone_id": zone["id"], "spaces": [3, 4]}, ORG)
        validate_error(resp, ApiErrorId.ERR_BOOTH_SPACE_CONFLICT)

    def test_non_contiguous_spaces_rejected_then_valid_pair_succeeds(self, api):
        """PRD §3.9: "The `spaces` list must contain exactly as many space
        integers as the tier demands — one, two, or three — arranged contiguous
        and ascending, else `ERR_BOOTH_SPACES_NOT_CONTIGUOUS`."

        Design: Difficulty/resource_temporal_overlap/booth_space_set_conflict
        """
        ev, zone, b1, b2 = self._setup(api)
        resp = api.assign_booth(b2["id"], {"zone_id": zone["id"], "spaces": [5, 7]}, ORG)
        validate_error(resp, ApiErrorId.ERR_BOOTH_SPACES_NOT_CONTIGUOUS)
        assigned = validate_success(api.assign_booth(
            b2["id"], {"zone_id": zone["id"], "spaces": [5, 6]}, ORG))
        assert assigned["status"] == "ASSIGNED"
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 3


class TestBoothCancellation:
    def test_booth_lifecycle_cancel_releases_space_and_refunds(self, api):
        """PRD §3.9: "Cancellation — by the organizer, or by the vendor on their
        own application, with an optional `reason` — is available from
        `APPROVED`, `PAID`, or `ASSIGNED` and moves the application to terminal
        `CANCELLED`. When `paid_cents` is above zero, a `REFUND` payment for the
        full `paid_cents` is written, the event treasury is debited, and
        `paid_cents` returns to zero. When the application was `ASSIGNED`, its
        spaces are released and the zone's `assigned_count` falls by the number
        of spaces."

        Design: Corner/state_machines/booth_lifecycle_cancel_releases_space_and_refunds
        """
        ev, zone = _published_with_vendor_zone(api)
        app = create_booth_at_state(ev["id"], target_state="ASSIGNED", zone=zone,
                                    spaces=[1], tier="SINGLE",
                                    business_name="Shine Supply",
                                    contact_email="shine@example.com")
        cancelled = validate_success(api.cancel_booth_application(
            app["id"], {"reason": "vendor bailed"}, ORG))
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(api.get_booth_application(app["id"], ORG))
        assert after["paid_cents"] == 0
        payments = get_success_data(api.list_booth_payments(app["id"], ORG))
        kinds = [(p["kind"], p["amount_cents"]) for p in payments]
        assert ("BOOTH_FEE", 7500) in kinds
        assert ("REFUND", 7500) in kinds
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 0
        assert get_summary(ev["id"])["treasury_cents"] == 0


class TestBoothPowerGate:
    def test_booth_power_unavailable_rejected(self, api):
        """PRD §3.9: "A power-requesting booth may land only in a zone whose
        `has_power` is set, else `ERR_POWER_NOT_AVAILABLE`."

        Design: Corner/validations/booth_power_unavailable_rejected
        """
        ev, zone = _published_with_vendor_zone(api, has_power=False, name="Dark Row",
                                               capacity=6)
        app = get_success_data(api.create_booth_application(
            create_booth_application_payload(ev["id"], business_name="Espresso Van",
                                             contact_email="es@example.com",
                                             booth_tier="SINGLE", power_requested=True), ORG))
        approved = get_success_data(api.approve_booth_application(app["id"], ORG))
        assert approved["fee_cents"] == 9000, "7500 + 1500 power fee"
        get_success_data(api.create_booth_payment(
            app["id"], {"amount_cents": 9000, "method": "CARD"}, ORG))
        resp = api.assign_booth(app["id"], {"zone_id": zone["id"], "spaces": [1]}, ORG)
        validate_error(resp, ApiErrorId.ERR_POWER_NOT_AVAILABLE)
        after = validate_success(api.get_booth_application(app["id"], ORG))
        assert after["status"] == "PAID"


class TestVendorOwnership:
    def test_vendor_cannot_read_others_application(self, api):
        """PRD §2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` equals the `id`
        of the vendor's own booth application, so a vendor can read, pay, or
        cancel exactly one application: their own. An entity-backed actor
        touching a resource owned by someone else is rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/vendor_cannot_read_others_application
        """
        ev, zone = _published_with_vendor_zone(api)
        b1 = get_success_data(api.create_booth_application(
            create_booth_application_payload(ev["id"], business_name="V1",
                                             contact_email="v1@example.com"), ORG))
        b2 = get_success_data(api.create_booth_application(
            create_booth_application_payload(ev["id"], business_name="V2",
                                             contact_email="v2@example.com"), ORG))
        resp = api.get_booth_application(b1["id"], make_vendor_headers(b2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
        own = validate_success(api.get_booth_application(b2["id"], make_vendor_headers(b2["id"])))
        assert own["business_name"] == "V2"
