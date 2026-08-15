"""Loyalty members, points expiry, and discount-network enrollment caps."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_fuel_sale_payload,
    create_member,
    post_fuel_price,
    set_clock,
    setup_enrolled_member,
    setup_fuel_site,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.fixtures import (
    CASH_1,
    GM,
    authorize_retail_sale,
    create_active_network,
    create_pump,
    create_register,
    enroll_member,
    open_shift,
    reload_member,
)
from test_helpers.factories import member_adjustment_payload
from test_helpers.test_users import make_loyalty_member_headers


def _setup_three_pending_enrollments():
    network = create_active_network("FleetPass", 0.10, ("DIESEL",), 2)
    members, enrollments = [], []
    for i, (name, email) in enumerate(
        (("Driver One", "one@x.com"), ("Driver Two", "two@x.com"),
         ("Driver Three", "three@x.com"))
    ):
        member = create_member(full_name=name, email=email)
        enrollment = enroll_member(member["id"], network["id"], activate=False)
        members.append(member)
        enrollments.append(enrollment)
    return network, members, enrollments


class TestNetworkCapBoundary:
    def test_activations_up_to_cap_succeed(self, api):
        """PRD section 3.4: "the network's count of `ACTIVE` enrollments must
        be below `program_cap` (`ERR_NETWORK_CAP_REACHED`, HTTP 422)" — with
        cap 2, the first two activations see counts 0 and 1, both below 2.

        Design: Difficulty/boundary_precision_check/network_cap_at_exact_limit
        """
        _, _, enrollments = _setup_three_pending_enrollments()
        e1 = validate_success(api.enrollment_activate(enrollments[0]["id"], CASH_1))
        e2 = validate_success(api.enrollment_activate(enrollments[1]["id"], CASH_1))
        assert e1["status"] == "ACTIVE"
        assert e2["status"] == "ACTIVE"

    def test_activation_beyond_cap_rejected(self, api):
        """PRD section 3.4: "the network's count of `ACTIVE` enrollments must
        be below `program_cap` (`ERR_NETWORK_CAP_REACHED`, HTTP 422)" — the
        third activation sees count 2, which is not below 2.

        Design: Difficulty/boundary_precision_check/network_cap_at_exact_limit
        """
        _, _, enrollments = _setup_three_pending_enrollments()
        validate_success(api.enrollment_activate(enrollments[0]["id"], CASH_1))
        validate_success(api.enrollment_activate(enrollments[1]["id"], CASH_1))

        resp = api.enrollment_activate(enrollments[2]["id"], CASH_1)
        validate_error(resp, ApiErrorId.ERR_NETWORK_CAP_REACHED)

        # Enrollment remains PENDING: read it back through the member listing.
        from test_helpers import validate_paginated
        data, _ = validate_paginated(
            api.list_member_enrollments(enrollments[2]["loyalty_member_id"], CASH_1)
        )
        assert len(data) == 1
        assert data[0]["status"] == "PENDING"


class TestMemberStatusGatesRedemption:
    def test_suspended_member_redeem_rejected_then_reactivated(self, api):
        """PRD section 3.4: "Any operation that redeems points, accrues
        points, activates an enrollment, or creates a reservation or service
        ticket for a member requires that member to be `ACTIVE`; against a
        suspended or closed member the rejection is `ERR_MEMBER_NOT_ACTIVE`."
        PRD section 3.4: "reactivation returns `SUSPENDED → ACTIVE`".

        Design: Corner/validations/validation_suspended_member_redeem_rejected
        """
        ctx = setup_fuel_site("Site V15", diesel_cents=385, clock=TEST_CLOCK_ISO)
        member = create_member(points=9000)
        validate_success(api.member_suspend(member["id"], GM))

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DIESEL", tender_type="CASH", max_gallons=10.0,
            loyalty_member_id=member["id"], requested_redeem_points=100,
        )
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

        validate_success(api.member_reactivate(member["id"], GM))
        sale = authorize_retail_sale(
            ctx, member_id=member["id"], redeem_points=100, max_gallons=10.0
        )
        assert sale["authorized_quote_cents_per_gallon"] == 335  # 385 - 50


class TestPointsExpiry:
    def test_expired_points_redeem_rejected(self, api):
        """PRD section 2.9: "an `expires_at` exactly 360 days after the
        grant" and "A member's `points_balance` is always the sum of
        `remaining_points` across lots whose `expires_at` is strictly later
        than the current logical clock".
        PRD section 2.9: "A redemption may never exceed the member's
        redeemable (non-expired) balance; a request that does is rejected
        with `ERR_NO_POINTS` (HTTP 422)".

        Design: Corner/errors/error_no_points_after_expiry
        """
        from test_helpers.fixtures import create_site

        site = create_site("Site R8")
        post_fuel_price(site["id"], "DIESEL", 385)
        pump = create_pump(site["id"], 1, ("DIESEL",))
        register = create_register(site["id"])
        shift = open_shift(site["id"], register["id"])
        member = create_member(full_name="Driver A", email="a@x.com")
        # Grant at the initial clock (2026-08-01T00:00:00Z): the lot expires
        # exactly 360 days later, at 2027-07-27T00:00:00Z.
        validate_success(api.member_adjustment(
            member["id"], member_adjustment_payload(500, "old promo"), GM), 201)

        # Advance past the lot's expiry (the clock only moves forward).
        set_clock("2027-08-12T10:00:00Z")
        member_now = reload_member(member["id"])
        assert member_now["points_balance"] == 0, (
            "500-point lot earned 2026-08-01 expired 360 days later"
        )

        def _redeem(points):
            payload = create_fuel_sale_payload(
                pump["id"], shift["id"], pricing_mode="RETAIL",
                fuel_type="DIESEL", tender_type="CASH", max_gallons=10.0,
                loyalty_member_id=member["id"], requested_redeem_points=points,
            )
            return api.create_fuel_sale(site["id"], payload, CASH_1)

        validate_error(_redeem(100), ApiErrorId.ERR_NO_POINTS)

        validate_success(api.member_adjustment(
            member["id"], member_adjustment_payload(300, "fresh promo"), GM), 201)
        validate_error(_redeem(350), ApiErrorId.ERR_NO_POINTS)

        ok = validate_success(_redeem(300), 201)
        assert ok["authorized_quote_cents_per_gallon"] == 235  # 385 - 150


class TestEnrollmentGates:
    def test_activate_enrollment_draft_network_rejected(self, api):
        """PRD section 3.4: "Activation — by a cashier or manager — enforces
        four gates: the network must be `ACTIVE` (`ERR_NETWORK_NOT_ACTIVE`,
        HTTP 422)".

        Design: Corner/errors/error_network_not_active_on_activate
        """
        from test_helpers.factories import create_discount_network_payload

        network = validate_success(
            api.create_discount_network(
                create_discount_network_payload("FleetPass", 0.10, ("DIESEL",), 5),
                GM,
            ),
            201,
        )
        member = create_member()
        enrollment = enroll_member(member["id"], network["id"], activate=False)

        validate_error(api.enrollment_activate(enrollment["id"], CASH_1),
                       ApiErrorId.ERR_NETWORK_NOT_ACTIVE)

        from test_helpers import validate_paginated
        data, _ = validate_paginated(
            api.list_member_enrollments(member["id"], CASH_1)
        )
        assert data[0]["status"] == "PENDING"

    def test_duplicate_enrollment_rejected(self, api):
        """PRD section 3.4: "the member must not already hold an enrollment
        in the same network in `PENDING`, `ACTIVE`, or `SUSPENDED`
        (`ERR_DUPLICATE_NETWORK_ENROLLMENT`, HTTP 422 — also enforced at
        enrollment creation)".

        Design: Corner/errors/error_duplicate_network_enrollment
        """
        from test_helpers.factories import create_enrollment_payload

        network = create_active_network("FleetPass", 0.10, ("DIESEL",), 5)
        member = create_member()
        enroll_member(member["id"], network["id"], activate=False)

        resp = api.create_member_enrollment(
            member["id"], create_enrollment_payload(network["id"]), CASH_1
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NETWORK_ENROLLMENT)
