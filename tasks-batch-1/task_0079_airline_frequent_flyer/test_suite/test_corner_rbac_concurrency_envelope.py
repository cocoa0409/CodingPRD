"""Queue B (Corner) — RBAC/ownership denials, OCC conflicts, and cross-entity /
consistency claims.

Covers sections: rbac, cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import validate_success, validate_error, validate_paginated, build_user_headers
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, create_pool, current_pool_version,
    inject_points, member_version, create_companion_certificate, create_flown_segment,
)
from test_helpers.factories import (
    create_member_payload, create_award_booking_payload, create_upgrade_request_payload,
    create_points_gift_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


# ---------- section: rbac ----------

class TestRbac:
    def test_member_cannot_register_members(self, api):
        """PRD §4: "POST /members | Register a loyalty member | ProgramAdmin"
        PRD §2.1: "If the headers are well-formed but the named role is not permitted to
        perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
        (HTTP 403)."

        Design: Corner/rbac/member_cannot_register_members
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        validate_error(
            api.create_member(create_member_payload(), member_headers_for(m)), "ERR_FORBIDDEN_ROLE"
        )

    def test_member_cannot_clear_waitlist(self, api):
        """PRD §4: "POST /flight-pools/{id}/clear-waitlist | Run priority clearing for a
        pool | OperationsAgent"
        PRD §2.1: "If the headers are well-formed but the named role is not permitted to
        perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
        (HTTP 403)."

        Design: Corner/rbac/member_cannot_clear_waitlist
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA13", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=2)
        set_clock(api, "2026-04-10T09:00:00.000Z")
        validate_error(api.clear_waitlist(pool["id"], member_headers_for(m)), "ERR_FORBIDDEN_ROLE")

    def test_member_cannot_issue_others_award(self, api):
        """PRD §2.1: "When a Member targets a resource they do not own, the request is
        rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Design: Corner/rbac/member_cannot_issue_others_award
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        inject_points(api, m1["id"], 30000)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m1["id"], cabin="ECONOMY", pricing_mode="FIXED"),
                member_headers_for(m1),
            ), 201,
        )
        validate_error(api.issue_award_booking(award["id"], member_headers_for(m2)), "ERR_NOT_RESOURCE_OWNER")

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "If either header is missing, or if X-User-Role is not one of these
        three known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        # Unknown role header -> unauthenticated.
        validate_error(api.get_member("00000000-0000-4000-8000-000000000000", build_user_headers("x", "Nobody")),
                       "ERR_UNAUTHENTICATED")


# ---------- section: cross_cutting_complexity_layers ----------

class TestCrossCutting:
    def test_occ_upgrade_request_stale_pool_negative(self, api):
        """PRD §2.9: "joining a flight pool's upgrade waitlist must carry
        expected_flightpool_version, the version of the target FlightPool that the
        client last observed. If that value does not match the pool's current version -
        for example because a clearing run or another joiner has already mutated the
        pool's seat accounting since the client read it - the create is rejected with
        ERR_STALE_POOL_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_upgrade_request_stale_pool_negative
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        pool = create_pool(api, flight_number="UA14", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=5)
        v0 = current_pool_version(api, pool["id"])
        validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m1["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m1),
            ), 201,
        )  # bumps pool.version
        # m2 reuses the now-stale v0.
        validate_error(
            api.create_upgrade_request(
                create_upgrade_request_payload(m2["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m2),
            ),
            "ERR_STALE_POOL_VERSION",
        )

    def test_occ_gift_settle_stale_member_negative(self, api):
        """PRD §2.9: "settling a points gift must carry expected_member_version, the
        version of the sender Member that the client last observed. If that value does
        not match the sender's current version - for example because an award redemption
        or a prior gift settlement has already lowered the sender's points_balance since
        the client read it - the settle is rejected with ERR_STALE_MEMBER_VERSION (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/occ_gift_settle_stale_member_negative
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 10000)
        hdrs = member_headers_for(sender)
        g_a = validate_success(
            api.create_points_gift(create_points_gift_payload(sender["id"], recipient["id"], 1000), hdrs), 201
        )
        g_b = validate_success(
            api.create_points_gift(create_points_gift_payload(sender["id"], recipient["id"], 1000), hdrs), 201
        )
        mv_stale = member_version(api, sender["id"])
        validate_success(api.settle_points_gift(g_a["id"], {"expected_member_version": mv_stale}, hdrs))  # bumps version
        validate_error(
            api.settle_points_gift(g_b["id"], {"expected_member_version": mv_stale}, hdrs),
            "ERR_STALE_MEMBER_VERSION",
        )

    def test_award_cancel_quoted_no_refund(self, api):
        """PRD §3.5: "Cancelling a still-QUOTED award (QUOTED -> CANCELLED) never debited
        points, so no refund row is written; if a certificate was attached it is released
        back to ISSUED and its attached_award_id is cleared."

        Design: Corner/cross_cutting_complexity_layers/award_cancel_quoted_no_refund
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 30000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        cancelled = validate_success(api.cancel_award_booking(award["id"], hdrs))
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED", cancelled
        assert member["points_balance"] == 30000, member  # no debit happened, so no refund

    def test_companion_cert_redeemed_on_issue(self, api):
        """PRD §3.5: "If a certificate is attached, the certificate cascades RESERVED ->
        REDEEMED as part of the same operation."

        Design: Corner/cross_cutting_complexity_layers/companion_cert_redeemed_on_issue
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 60000)
        hdrs = member_headers_for(m)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(
                    m["id"], cabin="ECONOMY", pricing_mode="FIXED", companion_certificate_id=cert["id"]
                ),
                hdrs,
            ), 201,
        )
        validate_success(api.issue_award_booking(award["id"], hdrs))
        cert_after = validate_success(api.get_companion_certificate(cert["id"], hdrs))
        assert cert_after["status"] == "REDEEMED", cert_after


# ---------- section: consistency_model ----------

class TestConsistencyModel:
    def test_ledger_balance_consistency_after_accrue(self, api):
        """PRD §2.6: "A member's points_balance is the conserved running total of
        non-expired ledger activity and is floored at 0."
        PRD §3.2: "An ACCRUAL ledger row is appended for the member with a positive delta
        equal to the awarded points, source_type FlightSegment, and an expires_at of the
        current instant plus the expiration window (see Section 3.6); the member's
        points_balance increases by that amount and last_activity_at is set to the
        current instant."

        Design: Corner/consistency_model/ledger_balance_consistency_after_accrue
        """
        set_clock(api, "2026-02-02T00:00:00.000Z")
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-02-02T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="ECONOMY",
            distance_miles=340, base_fare_usd=500, scheduled_departure="2026-02-01T08:00:00.000Z",
        )
        accrued = validate_success(api.accrue_flight_segment(seg["id"], AGENT))
        member = validate_success(api.get_member(m["id"], ADMIN))
        ledger, _ = validate_paginated(api.list_member_ledger(m["id"], ADMIN))
        # base=500*1.0=500; floor=170; max=500; BASE 0% -> 500
        assert accrued["points_awarded"] == 500, accrued
        assert member["points_balance"] == 500, member
        assert sum(row["delta"] for row in ledger) == member["points_balance"], (ledger, member)
