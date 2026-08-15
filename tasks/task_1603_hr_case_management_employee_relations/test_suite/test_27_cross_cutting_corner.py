"""Corner tests — cross_cutting_layers + consistency_model sections."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    assign_case_to,
    run_case_to_closed,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestOccAssignStaleVersion:
    def test_occ_assign_stale_version_rejected(self):
        """PRD §2.9: "When the case's current `version` no longer equals the
        supplied `expected_case_version` — because an intervening write of any
        kind has advanced it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and no change is applied."

        Design: Corner/cross_cutting_layers/occ_assign_stale_version_rejected
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot OCC",
            default_category="HARASSMENT", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        case = setup_case(channel["id"], subject["id"],
                          reporter_employee_id=reporter["id"],
                          category="HARASSMENT", severity="LOW")
        v0 = case["version"]
        # assign to inv1 → v0+1
        assign_case_to(case["id"], inv1["id"], v0)
        # unassign → v0+2
        case_now = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        api_client.unassign_case(
            case["id"], {"expected_case_version": case_now["version"]},
            TEST_USERS["er_manager_headers"],
        )
        # Now client holds v0 — stale
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": v0},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        # No change applied — case still TRIAGE, no assignment
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "TRIAGE"
        assert after["assigned_investigator_id"] is None


class TestOccCorrectVersionSucceeds:
    def test_occ_correct_version_succeeds_and_increments(self):
        """PRD §2.4: "`version` — a system-managed integer that increments by
        one on every mutation."
        PRD §2.9: "The guarded operations are: assigning an investigator
        (`POST /er/cases/{id}/assign`) ..."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_increments
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot OCC2",
            default_category="HARASSMENT", default_severity="LOW",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_case(channel["id"], subject["id"],
                          category="HARASSMENT", severity="LOW")
        v0 = case["version"]
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv1["id"], "expected_case_version": v0},
            TEST_USERS["er_manager_headers"],
        )
        after = validate_success(resp, 200)
        assert after["status"] == "ASSIGNED"
        assert after["version"] == v0 + 1, (
            f"version must increment by exactly 1: {v0} -> {after['version']}"
        )


class TestImmediateConsistencyOnClose:
    def test_immediate_consistency_close_response_reflects_all_side_effects(self):
        """PRD §3.6: "A successful closure stamps `closed_at` from the logical
        clock and derives `days_to_close` as the calendar days between
        `intake_received_at` and `closed_at` for this most recent closure; it
        recomputes the assigned investigator's `active_case_count` downward by
        one; it marks every trend snapshot whose scope matches the case's
        manager chain or `location_code` as stale (§3.7); and it advances the
        case's `version`."

        Design: Corner/consistency_model/immediate_consistency_close_response_reflects_all_side_effects
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon IMM",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            category="SAFETY", severity="MEDIUM",
            action_type="POLICY_CHANGE", severity_points=30,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        # Close response itself shows the side effects
        assert case["status"] == "CLOSED"
        assert case["closed_at"] is not None
        assert case["days_to_close"] is not None
        # Investigator's count is already decremented on immediate read
        inv_after = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_after["active_case_count"] == 0, (
            f"active_case_count expected 0 immediately after close, got {inv_after['active_case_count']}"
        )
