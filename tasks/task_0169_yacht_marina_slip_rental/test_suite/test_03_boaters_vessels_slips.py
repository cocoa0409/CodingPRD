"""Boaters, Vessels, and Slips — PRD §3.2, §3.3.

Covers basic CRUD shape, slip status transitions with If-Match
optimistic concurrency (PRD §2.6 / §3.3), and ownership-gated slip
status update.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to_iso,
    assert_boater,
    assert_slip,
    assert_vessel,
    create_boater,
    create_marina,
    create_slip,
    create_slip_payload,
    create_vessel,
    create_vessel_payload,
    get_slip,
    make_boater_headers,
    patch_slip_status,
    patch_slip_status_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Boater creation — PRD §3.2
# ===========================================================================
class TestBoaterCreate:

    def test_new_boater_has_deposit_zero_status_active(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "The new record carries a `deposit_balance_cents`
        initialized to 0 and a `status` of `ACTIVE`..."

        Claim: a freshly created Boater has deposit_balance_cents == 0
        and status == ACTIVE."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        assert boater["deposit_balance_cents"] == 0, (
            f"deposit_balance_cents must start at 0, got "
            f"{boater['deposit_balance_cents']!r}"
        )
        assert boater["status"] == "ACTIVE", (
            f"Boater.status must be ACTIVE on create, got "
            f"{boater['status']!r}"
        )
        assert_boater(boater)


# ===========================================================================
# Vessel creation — PRD §3.2
# ===========================================================================
class TestVesselCreate:

    def test_vessel_loa_must_be_positive(self, api, dock_master_headers):
        """PRD §3.2: "`loa_feet` (length overall, which must be strictly
        greater than zero)..."

        Claim: creating a vessel with loa_feet=0 → ERR_BAD_REQUEST."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        payload = create_vessel_payload(loa_feet=0.0)
        resp = api.create_vessel(
            marina["id"], boater["id"], payload,
            make_boater_headers(boater["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_vessel_shape(self, api, dock_master_headers):
        """PRD §3.2 vessel field set."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        vessel = create_vessel(
            marina["id"], boater,
            loa_feet=30.0, beam_feet=10.0, draft_feet=4.0,
            holding_tank_gallons=40,
        )
        assert_vessel(vessel)


# ===========================================================================
# Slip — PRD §3.3
# ===========================================================================
class TestSlipCreate:

    def test_slip_born_available(self, api, dock_master_headers):
        """PRD §3.3: "A slip is born with a `status` of `AVAILABLE`.\""""
        marina = create_marina()
        slip = create_slip(marina["id"])
        assert slip["status"] == "AVAILABLE", (
            f"New Slip.status must be AVAILABLE, got {slip['status']!r}"
        )
        assert_slip(slip)

    def test_slip_liveaboard_allowed_defaults_false(
        self, api, dock_master_headers,
    ):
        """PRD §3.3: "a boolean `liveaboard_allowed` (defaulting to
        false)..."

        Claim: omitting liveaboard_allowed yields false."""
        marina = create_marina()
        payload = create_slip_payload()
        payload.pop("liveaboard_allowed", None)
        resp = api.create_slip(marina["id"], payload, dock_master_headers)
        slip = validate_success(resp, expected_status=201)
        assert slip["liveaboard_allowed"] is False, (
            f"liveaboard_allowed must default to False, got "
            f"{slip['liveaboard_allowed']!r}"
        )


# ===========================================================================
# Slip status PATCH — PRD §3.3 / §2.6
# ===========================================================================
class TestSlipStatusPatch:

    def test_patch_slip_status_to_maintenance(
        self, api, dock_master_headers,
    ):
        """PRD §3.3: "Operators may transition a slip's status — to
        `MAINTENANCE` while the berth is being worked on or to `RETIRED`
        once it is permanently out of service — by patching the
        slip..."

        Claim: a PATCH with current version transitions AVAILABLE →
        MAINTENANCE."""
        marina = create_marina()
        slip = create_slip(marina["id"])
        updated = patch_slip_status(marina["id"], slip, "MAINTENANCE")
        assert updated["status"] == "MAINTENANCE", (
            f"After PATCH, slip.status must be MAINTENANCE, got "
            f"{updated['status']!r}"
        )

    def test_patch_slip_status_missing_if_match_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §2.6: "Every `PATCH` or `PUT` request must include an
        `If-Match` header whose value equals the current integer
        `version` of the target resource. If the header is missing on
        such a request ... the server rejects the request with
        `ERR_VERSION_CONFLICT` (HTTP 409)."

        Claim: PATCH without If-Match → ERR_VERSION_CONFLICT."""
        marina = create_marina()
        slip = create_slip(marina["id"])
        # Do not include If-Match.
        resp = api.patch_slip_status(
            marina["id"], slip["id"],
            patch_slip_status_payload(status="MAINTENANCE"),
            dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_slip_status_stale_if_match_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §2.6: "If the header is missing on such a request, or if
        its value does not match the stored `version`, the server
        rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409)."

        Claim: PATCH with stale If-Match → ERR_VERSION_CONFLICT."""
        marina = create_marina()
        slip = create_slip(marina["id"])
        h = dict(dock_master_headers)
        # Use a version that cannot match (slip.version starts at 1).
        h["If-Match"] = "999"
        resp = api.patch_slip_status(
            marina["id"], slip["id"],
            patch_slip_status_payload(status="MAINTENANCE"), h,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)
