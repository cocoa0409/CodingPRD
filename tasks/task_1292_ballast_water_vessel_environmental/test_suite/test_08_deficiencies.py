"""Port State Control deficiency rectification: deadlines, lifecycle legality,
OCC on the rectification claim, and posture lift on verification."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_deficiency,
    assert_timestamp_equals,
    begin_rectification_ok,
    claim_rectified_ok,
    get_deficiency,
    get_vessel,
    list_deficiencies,
    make_psc_officer_headers,
    rectify_deficiency_to_rectified,
    setup_psc_exceeded_deficiency,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.assertions import _parse_iso8601
from datetime import timedelta


class TestRectificationDeadline:
    def test_rectification_deadline_a15_identified_plus_14d(self, api, psc_officer_headers):
        """PRD section 3.5: "When `exceeded` is true, evaluation cascades: if the
        inspection kind is `PORT_STATE_CONTROL`, a port state control deficiency is
        created with `action_code` defaulting to `A15`"
        PRD section 3.6: "The action code drives the `rectification_deadline`: `A10`
        means rectify before departure (the deadline is the voyage's `departed_at` if
        the vessel has not yet departed, otherwise `identified_at` itself); `A15`
        allows 14 days from `identified_at`; `A16` allows 30 days; `A17` allows 7
        days; `A99` allows 21 days."
        PRD section 3.6: "The `is_priority_one` flag is true exactly when the action
        code is `A10` or `A15` — these block departure and feed the vessel's
        compliance posture."

        Design: Corner/calculations/rectification_deadline_a15_identified_plus_14d
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100038", vessel_name="MV Godwit", voyage_number="V9406"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-08"]
        )
        assert_deficiency(deficiency)
        assert deficiency["action_code"] == "A15", (
            f"exceedance-created deficiency must default to A15, got {deficiency['action_code']}"
        )
        assert deficiency["is_priority_one"] is True
        assert deficiency["rectification_status"] == "OPEN"
        # A15: deadline is identified_at + 14 days (relative to the row's own
        # identified_at anchor).
        expected_deadline = _parse_iso8601(deficiency["identified_at"]) + timedelta(days=14)
        assert _parse_iso8601(deficiency["rectification_deadline"]) == expected_deadline, (
            f"rectification_deadline {deficiency['rectification_deadline']} != "
            f"identified_at {deficiency['identified_at']} + 14 days"
        )


class TestRectificationLifecycle:
    def test_deficiency_begin_rectification_twice_returns_409(self, api, vessel_master_headers):
        """PRD section 3.6: "Beginning rectification by the `VesselMaster` moves the
        deficiency from `OPEN` to `RECTIFYING` and increments the vessel's `version`."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/deficiency_begin_rectification_twice_returns_409
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100025", vessel_name="MV Pelican", voyage_number="V9305"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-06"]
        )
        begin_rectification_ok(vessel["id"], deficiency["id"])

        resp = api.begin_rectification(vessel["id"], deficiency["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_claim_rectified_stale_version_returns_412(self, api, vessel_master_headers):
        """PRD section 3.6: "Claiming rectification by the `VesselMaster` moves it
        from `RECTIFYING` to `RECTIFIED` and stamps `rectified_at`; this claim is
        OCC-guarded and must carry `expected_deficiency_version` matching the
        deficiency's current `version`, with a mismatch rejected as
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_claim_rectified_stale_version_returns_412
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100067", vessel_name="MV Ruff", voyage_number="V9806"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-13"]
        )
        stale_version = deficiency["version"]  # observed before begin-rectification
        begin_rectification_ok(vessel["id"], deficiency["id"])  # advances the version

        resp = api.claim_rectified(
            vessel["id"], deficiency["id"],
            {"expected_deficiency_version": stale_version}, vessel_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = get_deficiency(vessel["id"], deficiency["id"])
        assert current["rectification_status"] == "RECTIFYING", (
            "rejected claim must leave the deficiency RECTIFYING"
        )


class TestVerifyLiftsPosture:
    def _setup_rectified_deficiency(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000010", vessel_name="MV Jaeger", voyage_number="V5002"
        )
        inspection, deficiency, record = setup_psc_exceeded_deficiency(
            vessel["id"], voyage["id"], organism=12.0, findings=["BWMS-03"],
            recorder_user_id="psc-1", evaluator_user_id="fs-1",
        )
        rectify_deficiency_to_rectified(vessel["id"], deficiency["id"],
                                        claimer_user_id="master-1")
        return vessel, voyage, deficiency

    def test_verify_transitions_deficiency_to_verified_and_stamps_timestamp(
            self, api, psc_officer_headers):
        """PRD section 3.6: "Verification by a `PSCOfficer` moves the deficiency from
        `RECTIFIED` to `VERIFIED` and stamps `verified_at`"
        PRD section 3.12: "The server runs on a logical clock that starts at
        2026-08-01T00:00:00Z and never falls back to wall-clock time."

        Design: Difficulty/transitive_cascade/deficiency_verify_lifts_posture_depth2
        """
        vessel, voyage, deficiency = self._setup_rectified_deficiency()
        # A different X-User-ID than the claimer performs verification.
        resp = api.verify_deficiency(vessel["id"], deficiency["id"],
                                     make_psc_officer_headers("psc-9"))
        verified = validate_success(resp, 200)
        assert verified["rectification_status"] == "VERIFIED"
        assert_timestamp_equals(verified["verified_at"], "2026-08-01T00:00:00Z",
                                label="verified_at")

    def test_verify_last_p1_deficiency_lifts_posture_to_open(self, api, shore_officer_headers):
        """PRD section 3.6: "Verification recomputes the vessel's posture — if the
        deficiency was priority-one and every other priority-one deficiency is now
        `VERIFIED`, the posture may lift from `RESTRICTED` back to `OPEN`."
        PRD section 2.8: "Otherwise it is `RESTRICTED` when at least one priority-one
        port state control deficiency is in `OPEN`, `RECTIFYING`, `RECTIFIED`, or
        `REOPENED` status, or when a `CRITICAL` noncompliance record detected within
        the last 180 days is not yet `CLOSED`. Otherwise the vessel is `OPEN`."

        Design: Difficulty/transitive_cascade/deficiency_verify_lifts_posture_depth2
        """
        vessel, voyage, deficiency = self._setup_rectified_deficiency()
        posture_before = get_vessel(vessel["id"])["compliance_posture"]
        assert posture_before == "RESTRICTED", (
            "an OPEN priority-one deficiency must hold the vessel RESTRICTED"
        )

        resp = api.verify_deficiency(vessel["id"], deficiency["id"],
                                     make_psc_officer_headers("psc-9"))
        validate_success(resp, 200)

        posture_after = get_vessel(vessel["id"])["compliance_posture"]
        assert posture_after == "OPEN", (
            "verifying the last OPEN priority-one deficiency must lift the posture to OPEN"
        )
