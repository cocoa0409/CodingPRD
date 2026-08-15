"""Waste partner lifecycle, OCC-guarded updates, and audit coverage windows."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, partner_status_payload, update_partner_payload,
    create_audit_payload,
    create_partner, get_partner, approve_partner, audit_partner,
    create_vetted_partner, set_clock,
    ca_headers, ehs_headers, assert_instant_equals,
)


class TestPartnerLifecycle:
    def test_partner_suspend_reinstate_and_reject_terminal(self, api):
        """PRD §3.5: "Approval moves a partner from `PENDING` — or from
        `SUSPENDED`, as a reinstatement — to `APPROVED`", "Suspension moves an
        `APPROVED` partner to `SUSPENDED`", and "Rejection moves a `PENDING`
        partner to `REJECTED`, which is terminal." PRD §2.9: "an entity already in
        a terminal state (`RETIRED`, `EMPTIED`, `VOIDED`, `RETURNED`, `ACCEPTED`,
        or `REJECTED`) rejects every further transition with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/partner_suspend_reinstate_and_reject_terminal
        """
        p1 = create_partner("TRANSPORTER", "HaulCo", "EPA-TR-1", ["D001"])
        p2 = create_partner("TSDF", "DispCo", "EPA-TS-1", ["D001"])
        # The APPROVED -> SUSPENDED -> APPROVED lap (reinstatement).
        approve_partner(p1)
        suspended = validate_success(api.set_partner_status(
            p1["id"], partner_status_payload("SUSPENDED"), ca_headers("aud-2")))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.set_partner_status(
            p1["id"], partner_status_payload("APPROVED"), ca_headers("aud-2")))
        assert reinstated["status"] == "APPROVED"
        # REJECTED is terminal.
        rejected = validate_success(api.set_partner_status(
            p2["id"], partner_status_payload("REJECTED"), ca_headers("aud-2")))
        assert rejected["status"] == "REJECTED"
        res = api.set_partner_status(
            p2["id"], partner_status_payload("APPROVED"), ca_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_occ_partner_update_stale_version(self, api):
        """PRD §2.8: "Updating a waste partner's registration (its `name`, its
        `permitted_waste_codes`, or both) requires `expected_waste_partner_version`
        holding the client's last observed `version` of that partner. A mismatch
        with the partner's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a stale writer cannot silently
        overwrite a permit change another writer just applied."

        Design: Corner/cross_cutting_layers/occ_partner_update_stale_version
        """
        partner = create_partner("TSDF", "DispCo", "EPA-TS-1", ["D001"])
        v1 = partner["version"]
        updated = validate_success(api.update_partner(
            partner["id"],
            update_partner_payload(v1, permitted_waste_codes=["D001", "F003"]),
            ca_headers("aud-1")))
        assert updated["version"] == v1 + 1
        assert updated["permitted_waste_codes"] == ["D001", "F003"]
        res = api.update_partner(
            partner["id"],
            update_partner_payload(v1, permitted_waste_codes=["D002"]),
            ca_headers("aud-1"))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert get_partner(partner["id"])["permitted_waste_codes"] == ["D001", "F003"]


class TestAuditWindows:
    def test_audit_currency_exclusive_end(self, api):
        """PRD §3.5: "The partner's coverage window is the half-open interval from
        `audit_coverage_start` up to but not including `audit_coverage_end`, and
        `is_audit_current` is true exactly when the logical clock sits before
        `audit_coverage_end` — at the end instant itself the audit is expired."

        Design: Corner/calculations/audit_currency_exclusive_end
        """
        partner = create_vetted_partner("TSDF", "EPA-TS-1", ["D001"], "DispCo")
        assert_instant_equals(partner["audit_coverage_end"],
                              "2027-01-01T00:00:00Z", "audit_coverage_end")
        set_clock("2026-12-31T23:59:59Z")
        assert get_partner(partner["id"])["is_audit_current"] is True
        set_clock("2027-01-01T00:00:00Z")
        assert get_partner(partner["id"])["is_audit_current"] is False

    def test_audit_window_abut_merges_and_fail_overlap_rejects(self, api):
        """PRD §3.5: "A new audit whose window overlaps or exactly abuts the
        current window merges into it when its outcome is `PASS`: the window
        becomes the earliest start to the latest end." and "a `FAIL`-outcome audit
        whose window strictly overlaps the current window's interior is
        `ERR_AUDIT_COVERAGE_OVERLAP` — a failing audit may not be blended into a
        passing record."

        Design: Difficulty/resource_temporal_overlap/audit_window_abut_merges_fail_overlap_rejects
        """
        partner = create_vetted_partner(
            "TSDF", "EPA-TS-1", ["D001"], "DispCo",
            coverage_from="2026-01-01T00:00:00Z", coverage_to="2027-01-01T00:00:00Z")
        # Exactly abutting PASS window (gap == 0): merge extends the end.
        audit_partner(partner["id"], "2027-01-01T00:00:00Z",
                      "2028-01-01T00:00:00Z", "PASS")
        merged = get_partner(partner["id"])
        assert_instant_equals(merged["audit_coverage_start"],
                              "2026-01-01T00:00:00Z", "audit_coverage_start")
        assert_instant_equals(merged["audit_coverage_end"],
                              "2028-01-01T00:00:00Z", "audit_coverage_end")
        assert merged["is_audit_current"] is True, "default clock 2026-08-01"
        # Strict-interior-overlapping FAIL window: rejected, never blended in.
        res = api.create_audit(
            partner["id"],
            create_audit_payload("2026-06-01T00:00:00Z", "2026-12-01T00:00:00Z",
                                 "FAIL"),
            ca_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_AUDIT_COVERAGE_OVERLAP)

    def test_audit_window_disjoint_later_pass_replaces(self, api):
        """PRD §3.5: "A new `PASS` window entirely disjoint and later than the
        current window replaces it outright."

        Design: Difficulty/resource_temporal_overlap/audit_window_abut_merges_fail_overlap_rejects
        """
        partner = create_vetted_partner(
            "TSDF", "EPA-TS-1", ["D001"], "DispCo",
            coverage_from="2026-01-01T00:00:00Z", coverage_to="2027-01-01T00:00:00Z")
        audit_partner(partner["id"], "2028-01-01T00:00:00Z",
                      "2029-01-01T00:00:00Z", "PASS")
        replaced = get_partner(partner["id"])
        assert_instant_equals(replaced["audit_coverage_start"],
                              "2028-01-01T00:00:00Z", "audit_coverage_start")
        assert_instant_equals(replaced["audit_coverage_end"],
                              "2029-01-01T00:00:00Z", "audit_coverage_end")

    def test_audit_window_regressive_rejected(self, api):
        """PRD §3.5: "Two regressions are rejected: a window entirely disjoint and
        earlier than the current window is `ERR_AUDIT_WINDOW_REGRESSIVE`".

        Design: Corner/validations/audit_window_regressive_rejected
        """
        partner = create_vetted_partner(
            "TSDF", "EPA-TS-1", ["D001"], "DispCo",
            coverage_from="2026-01-01T00:00:00Z", coverage_to="2027-01-01T00:00:00Z")
        res = api.create_audit(
            partner["id"],
            create_audit_payload("2025-01-01T00:00:00Z", "2025-06-01T00:00:00Z",
                                 "PASS"),
            ca_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_AUDIT_WINDOW_REGRESSIVE)
        unchanged = get_partner(partner["id"])
        assert_instant_equals(unchanged["audit_coverage_start"],
                              "2026-01-01T00:00:00Z", "audit_coverage_start")
        assert_instant_equals(unchanged["audit_coverage_end"],
                              "2027-01-01T00:00:00Z", "audit_coverage_end")
