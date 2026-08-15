"""Minor work-permit gating at offer acceptance and booking confirmation, and
guardian access rights (PRD sections 2.1, 3.8, 3.9)."""
from test_helpers import (
    ApiErrorId,
    accept_offer,
    create_booking,
    create_guardian,
    create_permit,
    create_production,
    create_talent,
    make_guardian_headers,
    set_clock,
    setup_minor_pipeline,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

ENGAGEMENT = {
    "engagement_start": "2026-08-20T00:00:00Z",
    "engagement_end": "2026-08-22T00:00:00Z",
    "proration_mode": "CALENDAR_SPAN",
}


class TestPermitGate:
    def test_booking_confirm_rejected_without_verified_permit(self, api):
        """PRD section 3.8: "The **permit gate** protects three operations with
        one rule, evaluated at each: when the role `is_minor_role` and the talent
        `is_minor`, there must exist a `VERIFIED` permit covering that talent and
        production whose `valid_until` reaches at least the engagement's final day
        — the `engagement_end` the deal memo will carry."
        PRD section 3.9: "Confirmation — `PENDING → CONFIRMED`, again a
        `ProductionCoordinator` action — runs its checks in order: state-machine
        legality; the memo still `EXECUTED`; the permit gate for minor roles (a
        `VERIFIED` permit with `valid_until` reaching at least the memo's
        `engagement_end`); the daily-hours cap of §3.8; and finally the
        engagement-overlap check."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_permit_state
        """
        # A VERIFIED permit P1 lets acceptance and creation pass; the booking is
        # pinned to a second, merely PENDING_VERIFICATION permit P2. Revoking P1
        # (which cancels only bookings referencing P1) leaves no VERIFIED permit
        # at confirm time.
        ctx = setup_minor_pipeline(with_verified_permit=True)
        permit_p1 = ctx["permit"]
        assert permit_p1["status"] == "VERIFIED"
        memo = accept_offer(ctx["offer"], ctx["submission"], **ENGAGEMENT)
        permit_p2 = create_permit(
            ctx["talent"]["id"], ctx["production"]["id"], ctx["guardian"]["id"], permit_number="PER-unverified"
        )
        assert permit_p2["status"] == "PENDING_VERIFICATION"
        booking = create_booking(ctx["submission"]["id"], memo["id"], work_permit_id=permit_p2["id"])
        validate_success(api.revoke_permit(permit_p1["id"], COORDINATOR))
        resp = api.confirm_booking(booking["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED)
        after = validate_success(api.get_booking(booking["id"], COORDINATOR))
        assert after["status"] == "PENDING", "rejected confirm leaves the booking PENDING"

    def test_offer_accept_rejected_without_verified_permit(self, api):
        """PRD section 3.8: "Offer acceptance, booking creation, and booking
        confirmation all enforce this gate, and all three reject a failure with
        `ERR_PERMIT_REQUIRED` (HTTP 422)."
        PRD section 3.7: "Acceptance evaluates its gates in order: state-machine
        legality, then the minor-permit gate of §3.8 (`ERR_PERMIT_REQUIRED`)".

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_permit_state
        """
        ctx = setup_minor_pipeline(with_verified_permit=False)
        assert ctx["permit"]["status"] == "PENDING_VERIFICATION"
        resp = api.accept_offer(ctx["offer"]["id"], ENGAGEMENT, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED)


class TestGuardianAccess:
    def test_guardian_reads_linked_permit_but_cannot_verify(self, api):
        """PRD section 2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is the
        `id` of the acting `Guardian`; visibility checks compare
        guardian-referencing fields such as a permit's `guardian_user_id` to
        `X-User-ID`."
        PRD section 4: "| GET | `/casting/permits/{id}` | Fetch a permit |
        CastingDirector, CastingAssociate, ProductionCoordinator, Guardian |" and
        "| POST | `/casting/permits/{id}/verify` | Verify a PENDING_VERIFICATION
        permit | ProductionCoordinator |".
        PRD section 2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/guardian_read_only_allowed_and_write_denied
        """
        set_clock("2026-08-01T00:00:00Z")
        production = create_production(title="RB3")
        guardian = create_guardian()
        talent = create_talent(full_name="Kid", date_of_birth="2012-01-01T00:00:00Z")
        permit = create_permit(talent["id"], production["id"], guardian["id"])
        guardian_headers = make_guardian_headers(guardian["id"])
        read = validate_success(api.get_permit(permit["id"], guardian_headers))
        assert read["id"] == permit["id"], "Guardian shared read of the linked permit succeeds"
        resp = api.verify_permit(permit["id"], guardian_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
