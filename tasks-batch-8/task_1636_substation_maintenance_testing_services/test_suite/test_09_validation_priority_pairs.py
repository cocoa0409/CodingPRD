"""Validation priority pairs (PRD §2.8): when one request trips two rules, the
higher-priority error is surfaced."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_accepted_test_event,
    create_certified_technician,
    create_defect,
    create_outage_window,
    create_technician,
    grant_certification,
    make_technician_headers,
    setup_asset,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestStateBeatsSafetyOnSubmit:
    def _setup_accepted_event_with_revoked_cert(self) -> dict:
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        tech = create_technician()
        cert = grant_certification(tech["id"], "NETA_LEVEL_2")
        tech_headers = make_technician_headers(tech["id"])
        event = create_accepted_test_event(
            base["asset"]["id"], tech_headers, "OIL_MOISTURE",
            value_primary=10, measured_at="2026-07-01T10:00:00Z",
        )
        # Revoke the certification AFTER acceptance: a re-submit now violates
        # both the state precondition (event is ACCEPTED) and the cert gate.
        validate_success(api_client.revoke_certification(cert["id"], OPS))
        return {**base, "event": event, "tech_headers": tech_headers}

    def test_state_error_wins_over_cert_gate(self):
        """PRD §2.8: "When a request would trip more than one rule, the platform
        surfaces exactly one error, chosen by priority."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409); then the OCC stale-version check
        (`ERR_STALE_VERSION`, HTTP 412); then the certification gate
        (`ERR_CERTIFICATION_REQUIRED`, HTTP 403)"
        PRD §3.4: "Submission from `DRAFT` transitions to `SUBMITTED`;
        submission from `RETURNED` (a resubmission) also transitions to
        `SUBMITTED` and recomputes the result from the current `value_primary`,
        `value_secondary`, and `ambient_temp_c`."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_safety_on_submit_rejected
        """
        ctx = self._setup_accepted_event_with_revoked_cert()
        resp = api_client.submit_test_event(ctx["event"]["id"], ctx["tech_headers"])
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION)

    def test_state_error_not_cert_error_and_event_unchanged(self):
        """PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409); then the OCC stale-version check
        (`ERR_STALE_VERSION`, HTTP 412); then the certification gate
        (`ERR_CERTIFICATION_REQUIRED`, HTTP 403)"
        PRD §3.4: "A decision of `ACCEPT` transitions `SUBMITTED → ACCEPTED`
        and stamps `reviewed_by`."

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_safety_on_submit_rejected
        """
        ctx = self._setup_accepted_event_with_revoked_cert()
        resp = api_client.submit_test_event(ctx["event"]["id"], ctx["tech_headers"])
        err = validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)
        assert err["error_id"] != ApiErrorId.ERR_CERTIFICATION_REQUIRED
        event = validate_success(api_client.get_test_event(ctx["event"]["id"], OPS))
        assert event["status"] == "ACCEPTED"


class TestSafetyBeatsConstraintOnOutageCreate:
    def _setup_asset_with_c1_defect_and_window(self) -> dict:
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        # Existing non-terminal window occupying 2026-09-01 08:00-16:00.
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z",
            purpose="Existing window",
        )
        tech = create_technician()
        defect = create_defect(
            base["asset"]["id"], make_technician_headers(tech["id"]), "C1",
            title="Active oil leak", description="Main tank seam leak",
        )
        return {**base, "window": window, "defect": defect}

    def test_critical_defect_error_wins_over_overlap_conflict(self):
        """PRD §2.8: "then the open-critical-defect guard on outage
        create/approve (`ERR_OPEN_CRITICAL_DEFECT`, HTTP 422); then
        interval-in-the-past (`ERR_INTERVAL_IN_PAST`, HTTP 422); then
        clock-gated action windows (`ERR_OUTSIDE_WINDOW`, HTTP 422); then
        outage-window overlap and the 24-hour buffer
        (`ERR_OUTAGE_WINDOW_CONFLICT`, HTTP 409)"
        PRD §3.2: "If the asset carries an open critical defect — a `Defect` at
        severity `C1` in `OPEN`, `WORK_ORDERED`, or `DEFERRED` — creation is
        rejected with `ERR_OPEN_CRITICAL_DEFECT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_constraint_on_outage_create_rejected
        """
        ctx = self._setup_asset_with_c1_defect_and_window()
        # This window overlaps the existing one, so it trips BOTH the C1
        # guard and the overlap constraint; the safety error must win.
        payload = {
            "substation_id": ctx["substation"]["id"],
            "asset_id": ctx["asset"]["id"],
            "start_ts": "2026-09-01T12:00:00Z",
            "end_ts": "2026-09-01T20:00:00Z",
            "purpose": "Overlapping window",
        }
        resp = api_client.create_outage_window(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_DEFECT)

    def test_critical_defect_error_wins_over_buffer_conflict(self):
        """PRD §2.8: "then the open-critical-defect guard on outage
        create/approve (`ERR_OPEN_CRITICAL_DEFECT`, HTTP 422); then
        interval-in-the-past (`ERR_INTERVAL_IN_PAST`, HTTP 422); then
        clock-gated action windows (`ERR_OUTSIDE_WINDOW`, HTTP 422); then
        outage-window overlap and the 24-hour buffer
        (`ERR_OUTAGE_WINDOW_CONFLICT`, HTTP 409)"
        PRD §3.2: "Any overlap under half-open semantics, or a gap to the
        nearest such window of strictly less than 24 hours, is rejected with
        `ERR_OUTAGE_WINDOW_CONFLICT` (HTTP 409); a gap of exactly 24 hours is
        permitted."

        Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_constraint_on_outage_create_rejected
        """
        ctx = self._setup_asset_with_c1_defect_and_window()
        # Adjacent window (gap 0 < 24h) trips the buffer rule; the C1 guard
        # still wins because safety runs before the constraint.
        payload = {
            "substation_id": ctx["substation"]["id"],
            "asset_id": ctx["asset"]["id"],
            "start_ts": "2026-09-01T16:00:00Z",
            "end_ts": "2026-09-02T00:00:00Z",
            "purpose": "Adjacent window",
        }
        resp = api_client.create_outage_window(payload, COORD)
        err = validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_DEFECT, 422)
        assert err["error_id"] != ApiErrorId.ERR_OUTAGE_WINDOW_CONFLICT
