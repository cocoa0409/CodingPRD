"""Exhibition lifecycle and posture — PRD §3.1, §2.9, §2.6.

Covers the linear state path DRAFT → INTAKE_OPEN →
ALLOCATION_PUBLISHED → SETUP → OPEN → TEARDOWN → CLOSED and the
posture transitions tied to it, plus the safety-inspection gate on
open-doors.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_exhibition,
    confirm_allocation_as_owner,
    create_exhibition,
    create_safety_inspection_payload,
    iso_offset,
    setup_exhibition_in_setup_with_confirmed_allocation,
    setup_exhibition_with_active_plan,
    setup_exhibition_with_published_allocation,
    setup_open_exhibition,
    validate_error,
    validate_success,
)


# ===========================================================================
# Initial state and posture (PRD §3.1, §2.9)
# ===========================================================================
class TestInitialState:

    def test_freshly_created_exhibition_is_draft_with_frozen_posture(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "A freshly created exhibition is in the DRAFT
        lifecycle status with posture FROZEN."

        Claim: POST /exhibitions returns status=DRAFT, posture=FROZEN.
        """
        exh = create_exhibition()
        assert exh["status"] == "DRAFT"
        assert exh["posture"] == "FROZEN"
        assert_exhibition(exh)

    def test_objection_window_defaults_to_72_hours(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "objection_window_hours value (defaulting to
        seventy-two hours) that controls how long published
        allocations may be objected to."

        Claim: when objection_window_hours is omitted, server stores 72.
        """
        exh = create_exhibition()  # factory omits the field
        assert exh["objection_window_hours"] == 72


# ===========================================================================
# DRAFT → INTAKE_OPEN (PRD §3.1)
# ===========================================================================
class TestOpenIntake:

    def test_open_intake_requires_active_floor_plan(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Once at least one Hall under the exhibition has
        an ACTIVE floor plan and the theme_code is non-empty, the
        admin may open intake, transitioning the exhibition from DRAFT
        to INTAKE_OPEN."

        Claim: open-intake with no Hall yet → ERR_INVALID_STATE.
        """
        exh = create_exhibition()
        res = api.open_intake(exh["id"], venue_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_open_intake_succeeds_with_active_plan(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Once at least one Hall under the exhibition has
        an ACTIVE floor plan and the theme_code is non-empty, the
        admin may open intake, transitioning the exhibition from DRAFT
        to INTAKE_OPEN."

        Claim: open-intake on a DRAFT exhibition with one Hall + ACTIVE
        plan → status==INTAKE_OPEN.
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        res = api.open_intake(exh["id"], venue_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "INTAKE_OPEN"

    def test_open_intake_sets_posture_frozen(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "The posture is set to FROZEN on this transition
        — entry remains blocked because the show is not running yet."

        Claim: posture remains FROZEN after open-intake.
        """
        exh, _, _ = setup_exhibition_with_active_plan()
        res = api.open_intake(exh["id"], venue_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["posture"] == "FROZEN"


# ===========================================================================
# INTAKE_OPEN → ALLOCATION_PUBLISHED (PRD §3.1, §3.4)
# ===========================================================================
class TestPublishAllocation:

    def test_publish_allocation_cascades_proposed_to_published(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "Publication is not per-row but per-exhibition:
        when the admin moves the exhibition from INTAKE_OPEN to
        ALLOCATION_PUBLISHED, every allocation still in PROPOSED is
        cascaded to PUBLISHED in a single step."

        Claim: after publish-allocation, allocation.status==PUBLISHED.
        """
        ctx = setup_exhibition_with_published_allocation()
        assert ctx["exhibition"]["status"] == "ALLOCATION_PUBLISHED"
        assert ctx["allocation"]["status"] == "PUBLISHED"

    def test_publish_pins_quoted_price_from_booth_base_price(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "For each cascading allocation, the
        at-publish-or-relocate variant of the booth pricing rule is
        evaluated and the result is pinned to quoted_price_cents."

        Claim: published allocation carries quoted_price_cents equal
        to the booth's at-publish-time computed price; for a non-corner
        STANDARD booth on a non-PRO theme, that is 200000 cents.
        """
        ctx = setup_exhibition_with_published_allocation(
            theme_code="GEN", booth_cell={"row": 2, "col": 2},
        )
        # booth at (2,2) on a 5x5 grid is interior — is_corner=false;
        # STANDARD tier base = 200000; no theme add-on (no PRO_ prefix).
        assert ctx["allocation"]["quoted_price_cents"] == 200000
        assert ctx["booth"]["base_price_cents"] == 200000


# ===========================================================================
# ALLOCATION_PUBLISHED → SETUP (PRD §3.1)
# ===========================================================================
class TestStartSetup:

    def test_start_setup_blocked_before_objection_window_elapses(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Moving from ALLOCATION_PUBLISHED to SETUP
        requires that every BoothAllocation on the exhibition has
        reached CONFIRMED or REVOKED, and that the current server
        clock is at or beyond the moment the allocation was published
        plus the exhibition's objection_window_hours value (so the
        objection window has elapsed)."

        Claim: start-setup before window elapses → ERR_INVALID_STATE.
        """
        ctx = setup_exhibition_with_published_allocation(
            objection_window_hours=72,
        )
        confirm_allocation_as_owner(
            ctx["allocation"]["id"], ctx["exhibitor_id"],
        )
        # No clock advance — window still open.
        res = api.start_setup(ctx["exhibition"]["id"], venue_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_setup_blocked_when_allocation_not_confirmed(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Moving from ALLOCATION_PUBLISHED to SETUP
        requires that every BoothAllocation on the exhibition has
        reached CONFIRMED or REVOKED."

        Claim: with a still-PUBLISHED allocation (not confirmed), and
        objection window elapsed, start-setup → ERR_INVALID_STATE.
        """
        ctx = setup_exhibition_with_published_allocation(
            objection_window_hours=1,
        )
        advance_clock(to=iso_offset(hours=2))
        # Allocation still in PUBLISHED — neither CONFIRMED nor REVOKED.
        res = api.start_setup(ctx["exhibition"]["id"], venue_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_setup_succeeds_and_lowers_posture_to_restricted(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "On the transition to SETUP, the posture moves to
        RESTRICTED (gate scanning blocked, staff only)."

        Claim: after start-setup, status==SETUP and posture==RESTRICTED.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        assert ctx["exhibition"]["status"] == "SETUP"
        assert ctx["exhibition"]["posture"] == "RESTRICTED"


# ===========================================================================
# SETUP → OPEN (PRD §3.1, §3.5)
# ===========================================================================
class TestOpenDoors:

    def test_open_doors_requires_pre_open_safety_inspection_pass(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Opening the doors then requires a PRE_OPEN
        SafetyInspection with a PASS result on the exhibition, and
        the current clock to be at or beyond open_date."
        PRD §3.1: "an attempt to open the doors without a PRE_OPEN
        PASS surfaces as ERR_SAFETY_INSPECTION_MISSING."

        Claim: open-doors without a PRE_OPEN PASS inspection →
        ERR_SAFETY_INSPECTION_MISSING.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation(
            open_date=iso_offset(hours=-1),  # already past open_date
            close_date=iso_offset(days=2),
        )
        res = api.open_doors(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_SAFETY_INSPECTION_MISSING.value)

    def test_open_doors_succeeds_with_pass_inspection(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.1: "on success, the exhibition moves to OPEN and
        posture flips to OPEN."

        Claim: after PRE_OPEN PASS and open-doors, status==OPEN and
        posture==OPEN.
        """
        ctx = setup_open_exhibition()
        assert ctx["exhibition"]["status"] == "OPEN"
        assert ctx["exhibition"]["posture"] == "OPEN"


# ===========================================================================
# OPEN → TEARDOWN (PRD §3.1, §2.6)
# ===========================================================================
class TestCloseDoors:

    def test_close_doors_requires_zero_occupancy(
        self, api, venue_admin_headers,
    ):
        """PRD §3.1: "Closing the doors requires the current clock to
        be at or beyond close_date and the exhibition's live_occupancy
        to be exactly zero."

        Claim: close-doors while live_occupancy>0 → ERR_INVALID_STATE.
        """
        from test_helpers import setup_open_exhibition_at_occupancy
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10, target_live_occupancy=1,
        )
        # Advance clock past close_date (= ~200h from setup_open_exhibition).
        advance_clock(to=iso_offset(hours=210))
        res = api.close_doors(ctx["exhibition"]["id"], venue_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Posture default (PRD §2.9)
# ===========================================================================
class TestPostureDefault:

    def test_draft_exhibition_posture_default_is_frozen(
        self, api, venue_admin_headers,
    ):
        """PRD §2.9: "The default initial posture of a DRAFT exhibition
        is FROZEN."

        Claim: exhibition.posture == 'FROZEN' immediately after creation.
        """
        exh = create_exhibition()
        assert exh["posture"] == "FROZEN"
