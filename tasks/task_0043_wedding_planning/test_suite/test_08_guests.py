"""Guest list, RSVP, per-scale capacity cap, and table-seat-limit rule.
Covers PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GUEST_CAP_INTIMATE,
    TABLE_SEAT_LIMIT,
    create_guest,
    create_guest_payload,
    make_planner_headers,
    patch_guest,
    patch_guest_payload,
    rsvp_confirm,
    rsvp_payload,
    setup_intimate_project_with_confirmed_party_size,
    setup_project_in_planning,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 -- Guest creation defaults.
# ===========================================================================
class TestGuestCreation:

    def test_default_party_size_one(self, api):
        """PRD §3.7: "optional fields at creation are party_size (defaulting
        to 1, MUST be at least 1)."

        Claim: POST /guests without party_size -> party_size == 1.
        """
        project = setup_project_in_planning(scale="INTIMATE")
        planner_headers = make_planner_headers()
        res = api.create_guest(
            project["id"],
            create_guest_payload(full_name="Alice"),
            planner_headers,
        )
        g = validate_success(res, expected_status=201)
        assert g["party_size"] == 1

    def test_initial_rsvp_status_invited(self, api):
        """PRD §3.7: "The new guest's rsvp_status is initialized to
        INVITED, table_number to null, gift_amount_cents to 0, and
        thank_you_sent_at to null."

        Claim: created guest -> rsvp_status==INVITED, table_number==null,
        gift_amount_cents==0, thank_you_sent_at==null.
        """
        project = setup_project_in_planning(scale="INTIMATE")
        planner_headers = make_planner_headers()
        res = api.create_guest(
            project["id"],
            create_guest_payload(full_name="Bob"),
            planner_headers,
        )
        g = validate_success(res, expected_status=201)
        assert g["rsvp_status"] == "INVITED"
        assert g["table_number"] is None
        assert g["gift_amount_cents"] == 0
        assert g["thank_you_sent_at"] is None


# ===========================================================================
# §3.7 -- Per-scale guest capacity cap (INTIMATE=50).
# ===========================================================================
class TestGuestCapacityCap:

    def test_rsvp_at_cap_succeeds(self, api):
        """PRD §3.7: "The per-scale cap limits the total of party_size
        across all guests with rsvp_status of CONFIRMED on the project: at
        most 50 for INTIMATE, at most 200 for MEDIUM, and at most 500 for
        GRAND."

        Claim: confirmed sum AT cap of 50 succeeds.
        """
        project, _g = setup_intimate_project_with_confirmed_party_size(
            confirmed_total=50, party_size_per_guest=10,
        )
        # If we got here, the 50th seat confirmation succeeded.
        # Sanity: list guests, verify at least 5 CONFIRMED.
        from test_helpers import validate_paginated
        planner_headers = make_planner_headers()
        list_resp = api.list_guests(
            project["id"], planner_headers, params={"limit": 100}
        )
        data, _meta = validate_paginated(list_resp)
        confirmed_seats = sum(
            g["party_size"] for g in data
            if g["rsvp_status"] == "CONFIRMED"
        )
        assert confirmed_seats == 50

    def test_rsvp_above_cap_rejected(self, api):
        """PRD §3.7: "Adding a guest, patching a guest's party_size, or
        setting an RSVP to CONFIRMED -- any of which would push the
        confirmed total past its scale cap -- is rejected with
        ERR_GUEST_CAPACITY_EXCEEDED (HTTP 409)."

        Claim: with 50 already confirmed on an INTIMATE project, RSVPing a
        new 1-seat guest to CONFIRMED -> ERR_GUEST_CAPACITY_EXCEEDED / 409.
        """
        project, _g = setup_intimate_project_with_confirmed_party_size(
            confirmed_total=50, party_size_per_guest=10,
        )
        planner_headers = make_planner_headers()
        # Add a new guest with party_size=1.
        new_guest = create_guest(
            project["id"], full_name="Extra", party_size=1,
        )
        # Try to confirm -> should breach cap (50+1==51 > 50).
        res = api.rsvp_guest(
            project["id"], new_guest["id"],
            rsvp_payload(rsvp_status="CONFIRMED"),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_GUEST_CAPACITY_EXCEEDED.value)


# ===========================================================================
# §3.7 -- Table-seat-limit rule.
# ===========================================================================
class TestTableSeatLimit:

    def test_table_at_limit_allowed(self, api):
        """PRD §3.7: "the sum of party_size across all guests assigned to
        the same table MUST not exceed 10 seats."

        Claim: assigning two guests party_size=5 each to table 1 ->
        sum==10 -> allowed.
        """
        project = setup_project_in_planning(scale="INTIMATE")
        g_a = create_guest(project["id"], full_name="A", party_size=5)
        g_b = create_guest(project["id"], full_name="B", party_size=5)
        patch_guest(
            project["id"], g_a["id"],
            patch_guest_payload(table_number=1),
        )
        res = patch_guest(
            project["id"], g_b["id"],
            patch_guest_payload(table_number=1),
        )
        assert res["table_number"] == 1

    def test_table_above_limit_rejected(self, api):
        """PRD §3.7: "the sum of party_size across all guests assigned to
        the same table MUST not exceed 10 seats; otherwise the request is
        rejected with ERR_TABLE_SEAT_LIMIT_EXCEEDED (HTTP 409)."

        Claim: assigning a third guest party_size=2 to a table already
        carrying 10 seats -> 12 > 10 -> ERR_TABLE_SEAT_LIMIT_EXCEEDED / 409.
        """
        project = setup_project_in_planning(scale="INTIMATE")
        g_a = create_guest(project["id"], full_name="A", party_size=5)
        g_b = create_guest(project["id"], full_name="B", party_size=5)
        g_c = create_guest(project["id"], full_name="C", party_size=2)
        patch_guest(
            project["id"], g_a["id"], patch_guest_payload(table_number=1),
        )
        patch_guest(
            project["id"], g_b["id"], patch_guest_payload(table_number=1),
        )
        planner_headers = make_planner_headers()
        res = api.patch_guest(
            project["id"], g_c["id"],
            patch_guest_payload(table_number=1),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_TABLE_SEAT_LIMIT_EXCEEDED.value)


# ===========================================================================
# §2.5 -- OCC on Guest.
# ===========================================================================
class TestGuestVersionConflict:

    def test_stale_version_rejected(self, api):
        """PRD §2.5: "When version is supplied and does not equal the
        current version of the target resource, the request is rejected
        with ERR_VERSION_CONFLICT (HTTP 409)."

        Claim: PATCH /guests/{id} with stale version ->
        ERR_VERSION_CONFLICT / 409.
        """
        project = setup_project_in_planning(scale="INTIMATE")
        g = create_guest(project["id"], full_name="X", party_size=1)
        # Mutate once so version increments.
        planner_headers = make_planner_headers()
        api.patch_guest(
            project["id"], g["id"],
            patch_guest_payload(party_size=2),
            planner_headers,
        )
        # Submit a PATCH with the stale (original) version.
        res = api.patch_guest(
            project["id"], g["id"],
            patch_guest_payload(party_size=3, version=g["version"]),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)
