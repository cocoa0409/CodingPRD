"""Expansion options and land banking: exercise windows, zoning gate, and
terminal-state lockdown (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_expansion_option,
    set_logical_clock,
    setup_granted_option,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]


class TestExerciseWindow:
    def test_exercise_at_window_close_inclusive_succeeds(self, api):
        """PRD §3.6: "Both window bounds are inclusive at exercise time." and
        "the clock must not have passed `window_close_date`, which is
        inclusive — an attempt after the close flips the option itself to
        `EXPIRED` and the call fails with `ERR_OPTION_WINDOW_EXPIRED` (409)."
        and "A successful exercise moves the option `GRANTED` → `EXERCISED`".

        Design: Difficulty/boundary_precision_check/exercise_at_window_close_inclusive
        """
        bundle = setup_granted_option(zoning_outcome="CLEARED")
        set_logical_clock("2026-12-01T00:00:00Z")  # exactly window_close_date
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        data = validate_success(resp, 200)
        assert data["status"] == "EXERCISED", (
            f"Exercise at exactly window_close_date must succeed (inclusive "
            f"bound), got {data['status']}"
        )
        assert_expansion_option(data)

    def test_exercise_at_window_close_reserves_land(self, api):
        """PRD §3.6: "A successful exercise moves the option `GRANTED` →
        `EXERCISED` and reserves the land: the parcel moves `LISTED` →
        `RESERVED` with `option_sf` added to its `reserved_sf` and
        `available_sf` recomputed."

        Design: Difficulty/boundary_precision_check/exercise_at_window_close_inclusive
        """
        bundle = setup_granted_option(zoning_outcome="CLEARED")
        set_logical_clock("2026-12-01T00:00:00Z")
        validate_success(api.exercise_expansion_option(bundle["option"]["id"], REP_1))
        land = validate_success(api.get_site(bundle["land_site"]["id"], LM))
        assert land["status"] == "RESERVED"
        assert land["reserved_sf"] == 100000
        assert land["available_sf"] == 400000, (
            f"500000 total - 100000 reserved must leave 400000 available, "
            f"got {land['available_sf']}"
        )

    def test_option_window_not_open_returns_409(self, api):
        """PRD §3.6: "the logical clock must have reached `window_open_date`
        (`ERR_OPTION_WINDOW_NOT_OPEN`, 409)".

        Design: Corner/validations/option_window_not_open_returns_409
        """
        bundle = setup_granted_option(zoning_outcome="CLEARED")
        # Clock is still at the tour-completion instant 2026-08-10T11:00:00Z,
        # before the 2026-09-01 window open.
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_OPTION_WINDOW_NOT_OPEN)
        option = validate_success(
            api.get_expansion_option(bundle["option"]["id"], LM)
        )
        assert option["status"] == "GRANTED"
        land = validate_success(api.get_site(bundle["land_site"]["id"], LM))
        assert land["status"] == "LISTED"

    def test_option_window_expired_marks_expired(self, api):
        """PRD §3.6: "an attempt after the close flips the option itself to
        `EXPIRED` and the call fails with `ERR_OPTION_WINDOW_EXPIRED` (409)."

        Design: Corner/validations/option_window_expired_marks_expired
        """
        bundle = setup_granted_option(zoning_outcome="CLEARED")
        set_logical_clock("2026-12-02T00:00:00Z")  # one day past the close
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_OPTION_WINDOW_EXPIRED)
        option = validate_success(
            api.get_expansion_option(bundle["option"]["id"], LM)
        )
        assert option["status"] == "EXPIRED", (
            f"The failed exercise must flip the option to EXPIRED, got "
            f"{option['status']}"
        )
        land = validate_success(api.get_site(bundle["land_site"]["id"], LM))
        assert land["status"] == "LISTED"
        assert land["available_sf"] == 500000


class TestExercisePrecedenceComplianceOverExpiry:
    """Zoning gate (checked before the window checks) masks expiry (PRD §3.6)."""

    def test_flagged_compliance_and_expired_window_reports_compliance(self, api):
        """PRD §3.6: "The exercise checks fire in precedence order: the option
        must be `GRANTED` (`ERR_INVALID_STATE`); the land parcel must still be
        `LISTED` (`ERR_SITE_NOT_LISTED`); the zoning gate of §3.4 must hold
        for the parcel and the LOI's requirement (`ERR_COMPLIANCE_NOT_CLEARED`);
        the parcel's `available_sf` must be at least `option_sf`
        (`ERR_INSUFFICIENT_SF`); the logical clock must have reached
        `window_open_date` (`ERR_OPTION_WINDOW_NOT_OPEN`, 409); and the clock
        must not have passed `window_close_date`, which is inclusive".
        PRD §2.8: "later failures are masked by earlier ones."

        Design: Difficulty/priority_pair_validation_conflict/exercise_flagged_compliance_and_expired_window
        """
        bundle = setup_granted_option(zoning_outcome="FLAGGED")
        set_logical_clock("2026-12-02T00:00:00Z")  # past the close
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED)
        option = validate_success(
            api.get_expansion_option(bundle["option"]["id"], LM)
        )
        assert option["status"] == "GRANTED", (
            f"When the compliance error masks the expiry check, the option "
            f"must NOT transition to EXPIRED; got {option['status']}"
        )

    def test_flagged_compliance_inside_window_also_reports_compliance(self, api):
        """PRD §3.6: "The exercise checks fire in precedence order: ... the
        zoning gate of §3.4 must hold for the parcel and the LOI's requirement
        (`ERR_COMPLIANCE_NOT_CLEARED`); ..." — the zoning gate precedes the
        window checks, so a FLAGGED review rejects the exercise even with the
        clock inside the window.

        Design: Difficulty/priority_pair_validation_conflict/exercise_flagged_compliance_and_expired_window
        """
        bundle = setup_granted_option(zoning_outcome="FLAGGED")
        set_logical_clock("2026-10-01T00:00:00Z")  # inside the window
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED)
        option = validate_success(
            api.get_expansion_option(bundle["option"]["id"], LM)
        )
        assert option["status"] == "GRANTED"
        land = validate_success(api.get_site(bundle["land_site"]["id"], LM))
        assert land["status"] == "LISTED"


class TestOptionTerminalStates:
    def test_exercise_released_option_returns_invalid_state(self, api):
        """PRD §3.6: "Release is the clean exit: the owning representative
        moves a `GRANTED` option to `RELEASED`" and "`EXERCISED`, `EXPIRED`,
        and `RELEASED` are all terminal." PRD §2.8: "terminal states accept no
        further transitions — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/exercise_released_option_returns_invalid_state
        """
        bundle = setup_granted_option()
        released = validate_success(
            api.release_expansion_option(bundle["option"]["id"], REP_1)
        )
        assert released["status"] == "RELEASED"
        resp = api.exercise_expansion_option(bundle["option"]["id"], REP_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        land = validate_success(api.get_site(bundle["land_site"]["id"], LM))
        assert land["status"] == "LISTED", (
            "No reservation may leak from an exercise attempt on a RELEASED "
            "option"
        )
