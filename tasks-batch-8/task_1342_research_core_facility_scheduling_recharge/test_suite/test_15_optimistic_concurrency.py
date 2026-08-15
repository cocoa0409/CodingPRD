"""Optimistic concurrency control on the three OCC write endpoints
(PRD §2.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_rate_line_payload,
    make_researcher_headers,
    setup_canonical_stack, create_instrument, open_fiscal_year,
    create_draft_rate_set, create_user, create_grant,
    create_approved_booking, get_booking, get_grant,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestBookingRescheduleOCC:
    def test_occ_booking_reschedule_stale(self, api):
        """PRD §2.8: "Rescheduling an `APPROVED` booking requires
        `expected_booking_version` matching the booking's current `version`. If
        another writer has advanced the booking's version since the client last
        read it (for example, an earlier legitimate reschedule already moved
        the window), the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from overwriting a booking state it
        never observed." PRD §3.7: "On success the estimate is recomputed
        against the *pinned* rate snapshot (rates never re-pin on reschedule),
        the grant encumbrance adjusts by the delta, and the grant's status is
        recomputed."

        Design: Corner/cross_cutting_layers/occ_booking_reschedule_stale
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)  # version advanced once by approval
        owner = make_researcher_headers(stack["u1"]["id"])
        observed_version = b1["version"]

        first = validate_success(
            api.reschedule_booking(
                b1["id"],
                {"expected_booking_version": observed_version,
                 "start_at": "2026-09-01T09:00:00Z",
                 "end_at": "2026-09-01T11:00:00Z"},
                owner,
            ),
            200,
        )
        assert first["version"] == observed_version + 1
        assert first["estimated_charge_cents"] == 24000, (
            "re-estimated against the pinned rate: 120 min x 200"
        )
        grant_mid = get_grant(stack["g1"]["id"])
        assert grant_mid["budget_encumbered_cents"] == 24000, (
            "encumbrance adjusted by the delta (18000 -> 24000)"
        )

        stale = api.reschedule_booking(
            b1["id"],
            {"expected_booking_version": observed_version,
             "start_at": "2026-09-02T09:00:00Z",
             "end_at": "2026-09-02T11:00:00Z"},
            owner,
        )
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
        after = get_booking(b1["id"])
        assert after["end_at"] == first["end_at"], (
            "the stale write must not move the window"
        )
        assert get_grant(stack["g1"]["id"])["budget_encumbered_cents"] == 24000


class TestGrantAmendOCC:
    def test_occ_grant_amend_stale(self, api):
        """PRD §2.8: "Amending a grant via its `PUT` requires
        `expected_grant_version` matching the grant's current `version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Sequential
        amendments are individually legitimate, so only the stale-version check
        rejects the second writer."

        Design: Corner/cross_cutting_layers/occ_grant_amend_stale
        """
        u1 = create_user(is_pi=True)
        g1 = create_grant(u1["id"])
        observed_version = g1["version"]

        first = validate_success(
            api.amend_grant(
                g1["id"],
                {"expected_grant_version": observed_version,
                 "budget_total_cents": 120000},
                FINANCE,
            ),
            200,
        )
        assert first["version"] == observed_version + 1
        assert first["budget_total_cents"] == 120000

        stale = api.amend_grant(
            g1["id"],
            {"expected_grant_version": observed_version,
             "budget_total_cents": 150000},
            FINANCE,
        )
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
        assert get_grant(g1["id"])["budget_total_cents"] == 120000


class TestRateSetEditOCC:
    def test_occ_rate_set_edit_stale(self, api):
        """PRD §2.8: "Editing a `DRAFT` rate set via its `PUT` requires
        `expected_rate_set_version` matching the set's current `version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_rate_set_edit_stale
        """
        i1 = create_instrument()
        open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 19000},
        )
        observed_version = rs27["version"]

        first = validate_success(
            api.edit_rate_set(
                rs27["id"],
                {"expected_rate_set_version": observed_version,
                 "effective_from": "2027-01-15T00:00:00Z"},
                ADMIN,
            ),
            200,
        )
        assert first["version"] == observed_version + 1
        assert first["effective_from"].startswith("2027-01-15T00:00:00")

        stale = api.edit_rate_set(
            rs27["id"],
            {"expected_rate_set_version": observed_version,
             "effective_from": "2027-02-01T00:00:00Z"},
            ADMIN,
        )
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
        after = validate_success(api.get_rate_set(rs27["id"], ADMIN), 200)
        assert after["effective_from"].startswith("2027-01-15T00:00:00"), (
            "the stale edit must not change effective_from"
        )
