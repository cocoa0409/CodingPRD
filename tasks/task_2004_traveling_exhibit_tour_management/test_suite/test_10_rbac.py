"""Role-based access control denials (PRD §2.1, §4)."""
import pytest
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_tour_payload,
    create_and_open_booking,
    create_venue,
    book_stop,
    create_and_send_contract,
    issue_certificate,
    plan_first_leg,
    setup_booking_tour_with_stop,
)

TM = TEST_USERS["tour_manager_headers"]
VR = TEST_USERS["venue_registrar_headers"]
SHIP = TEST_USERS["shipper_headers"]
INS = TEST_USERS["insurer_headers"]


class TestRbacDenials:
    def test_venue_registrar_cannot_create_tour(self, api):
        """PRD §4: the `POST /tours` row authorizes only "TourManager".
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/venue_registrar_cannot_create_tour
        """
        res = api.create_tour(
            create_tour_payload(
                title="X",
                exhibit_code="X-2026",
                crate_count=1,
                declared_value_cents=100,
                refurbishment_gap_days=0,
            ),
            VR,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_insurer_cannot_create_tour(self, api):
        """PRD §4: the `POST /tours` row authorizes only "TourManager".
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/venue_registrar_cannot_create_tour
        """
        res = api.create_tour(create_tour_payload(), INS)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_shipper_cannot_sign_contract(self, api):
        """PRD §3.3: "Signature (`SIGN`) belongs to the `VenueRegistrar` alone:
        at that moment the committed `sponsorship_credit_cents` is checked
        against the venue's `local_sponsorship_cap_cents`, and an over-cap
        commitment is refused with `ERR_SPONSORSHIP_OVER_CAP`."
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/shipper_cannot_sign_contract
        """
        tour, _ = create_and_open_booking(
            title="RBAC", exhibit_code="RBAC-2026", declared_value_cents=100000
        )
        venue = create_venue(name="RBAC Hall")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=100000, sponsorship_credit_cents=0
        )
        res = api.transition_contract(tour["id"], stop["id"], {"action": "SIGN"}, SHIP)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_tour_manager_cannot_sign_contract(self, api):
        """PRD §3.3: "Signature (`SIGN`) belongs to the `VenueRegistrar` alone:
        at that moment the committed `sponsorship_credit_cents` is checked
        against the venue's `local_sponsorship_cap_cents`, and an over-cap
        commitment is refused with `ERR_SPONSORSHIP_OVER_CAP`."
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/shipper_cannot_sign_contract
        """
        tour, _ = create_and_open_booking(
            title="RBAC", exhibit_code="RBAC-2026", declared_value_cents=100000
        )
        venue = create_venue(name="RBAC Hall")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        create_and_send_contract(
            tour["id"], stop["id"], base_fee_cents=100000, sponsorship_credit_cents=0
        )
        # The TourManager owns SEND/REVOKE; SIGN is VenueRegistrar alone.
        res = api.transition_contract(tour["id"], stop["id"], {"action": "SIGN"}, TM)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_insurer_cannot_dispatch_shipment(self, api):
        """PRD §3.6: "Dispatch (`action` `DISPATCH`, by the `Shipper`) is
        permitted only when the origin stop is `TEARDOWN` or `CLOSED` — or the
        origin is null for that first leg — and the four-clause coverage rule of
        §3.5 is satisfied for the leg."
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/insurer_cannot_dispatch_shipment
        """
        tour, crates, venue, stop = setup_booking_tour_with_stop(
            title="RBAC2", exhibit_code="RBC2-2026", declared_value_cents=100000
        )
        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        shipment = plan_first_leg(tour["id"], stop["id"], [c["id"] for c in crates])
        res = api.transition_shipment(
            tour["id"], shipment["id"], {"action": "DISPATCH"}, INS
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_registrar_cannot_dispatch_shipment(self, api):
        """PRD §3.6: "Dispatch (`action` `DISPATCH`, by the `Shipper`) is
        permitted only when the origin stop is `TEARDOWN` or `CLOSED` — or the
        origin is null for that first leg — and the four-clause coverage rule of
        §3.5 is satisfied for the leg."
        PRD §2.1: "A well-identified caller attempting an operation reserved for
        another role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/insurer_cannot_dispatch_shipment
        """
        tour, crates, venue, stop = setup_booking_tour_with_stop(
            title="RBAC2", exhibit_code="RBC2-2026", declared_value_cents=100000
        )
        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        shipment = plan_first_leg(tour["id"], stop["id"], [c["id"] for c in crates])
        res = api.transition_shipment(
            tour["id"], shipment["id"], {"action": "DISPATCH"}, TEST_USERS["registrar_headers"]
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
