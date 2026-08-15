"""Variance requests: info cycle, uniqueness, windows, and priority pairs."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_interceptor,
    create_and_permit_hauler,
    create_establishment,
    create_hauler,
    create_manifest,
    create_variance,
    get_establishment,
    get_success_data,
    make_fse_contact_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestVarianceInfoCycle:
    def test_variance_info_request_cycle_repeats_then_denies(self, api):
        """PRD: "A `ComplianceOfficer` may push a request from `UNDER_REVIEW`
        to `INFO_REQUESTED` to demand more material; the applicant answers by
        supplying a replacement `justification`, which returns the request to
        `UNDER_REVIEW`. Naturally, only the owning establishment's contact may
        answer (`ERR_FORBIDDEN_OWNERSHIP` otherwise), and the cycle may repeat
        as needed."
        PRD: "Denial is simpler: a `ComplianceOfficer` may deny from either
        `UNDER_REVIEW` or `INFO_REQUESTED`, stamping `decided_at`."

        Design: Difficulty/non_linear_state_machine/variance_info_request_cycle
        """
        est = create_establishment(name="Rural Kitchen", street_address="3 Oak Rd")
        variance = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                                   requested_frequency_days=400,
                                   justification="rural low-grease operation")
        fse = make_fse_contact_headers(est["id"])

        info1 = validate_success(api.request_variance_info(variance["id"],
                                                           OFFICER))
        assert info1["status"] == "INFO_REQUESTED"
        back1 = validate_success(api.provide_variance_info(
            variance["id"], "updated docs: grease audit attached", fse))
        assert back1["status"] == "UNDER_REVIEW"
        assert back1["justification"] == "updated docs: grease audit attached"

        info2 = validate_success(api.request_variance_info(variance["id"],
                                                           OFFICER))
        assert info2["status"] == "INFO_REQUESTED", (
            "The UNDER_REVIEW -> INFO_REQUESTED cycle repeats"
        )
        back2 = validate_success(api.provide_variance_info(
            variance["id"], "second packet: historical manifests", fse))
        assert back2["status"] == "UNDER_REVIEW"
        assert back2["justification"] == "second packet: historical manifests", (
            "provide-info replaces the justification"
        )

        denied = validate_success(api.deny_variance_request(variance["id"],
                                                            OFFICER))
        assert denied["status"] == "DENIED"
        assert denied["decided_at"] is not None

    def test_provide_info_replaces_justification_and_reopens_review(self, api):
        """PRD: "the applicant answers by supplying a replacement
        `justification`, which returns the request to `UNDER_REVIEW`."
        PRD: "A `ComplianceOfficer` may push a request from `UNDER_REVIEW` to
        `INFO_REQUESTED` to demand more material"

        Design: Difficulty/non_linear_state_machine/variance_info_request_cycle
        """
        est = create_establishment(name="Cycle Kitchen",
                                   street_address="4 Oak Rd")
        variance = create_variance(est["id"], scope="INTERCEPTOR_SIZE",
                                   justification="initial packet")
        fse = make_fse_contact_headers(est["id"])
        get_success_data(api.request_variance_info(variance["id"], OFFICER))
        returned = validate_success(api.provide_variance_info(
            variance["id"], "replacement packet", fse))
        assert returned["status"] == "UNDER_REVIEW"
        assert returned["justification"] == "replacement packet"


class TestVarianceUniqueness:
    def test_open_variance_blocks_second_variance_same_scope(self, api):
        """PRD: "At most one open request — one in `UNDER_REVIEW` or
        `INFO_REQUESTED` — may exist per establishment and scope; a second
        filing collides with `ERR_VARIANCE_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/c_open_variance_blocks_second_variance_same_scope
        """
        est = create_establishment(name="Var Cafe", street_address="20 Q St")
        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=400, justification="v1")
        assert v1["status"] == "UNDER_REVIEW"

        resp = api.create_variance_request(
            {"establishment_id": est["id"], "scope": "PUMPING_FREQUENCY",
             "requested_frequency_days": 500,
             "justification": "v2 duplicate scope",
             "effective_from": "2028-01-01T00:00:00Z",
             "effective_to": "2028-07-01T00:00:00Z"},
            make_fse_contact_headers(est["id"]))
        validate_error(resp, ApiErrorId.ERR_VARIANCE_ALREADY_OPEN, 409)

        v3 = create_variance(est["id"], scope="INTERCEPTOR_SIZE",
                             justification="v3 other scope")
        assert v3["status"] == "UNDER_REVIEW", (
            "Uniqueness is per establishment+scope"
        )


class TestVarianceWindows:
    def test_variance_windows_half_open_adjacency(self, api):
        """PRD: "And no other `APPROVED` variance for the same establishment
        and scope may have a window overlapping the requested one — the
        windows are half-open, so one request's `effective_from` falling
        exactly on another's `effective_to` is adjacency rather than overlap,
        while a genuine collision is rejected with
        `ERR_VARIANCE_WINDOW_OVERLAP` (HTTP 409)."
        PRD: "for the `PUMPING_FREQUENCY` scope it also writes
        `requested_frequency_days` into the establishment's
        `variance_override_frequency_days`"

        Design: Difficulty/resource_temporal_overlap/variance_windows_half_open_adjacency
        """
        est = create_establishment(name="Adjacency Eats", street_address="90 G Ln")
        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=120, justification="v1",
                             effective_from="2027-01-01T00:00:00Z",
                             effective_to="2027-07-01T00:00:00Z")
        approved_v1 = validate_success(api.approve_variance_request(
            v1["id"], get_establishment(est["id"])["version"], OFFICER))
        assert approved_v1["status"] == "APPROVED"

        # V2 starts exactly at V1's end: half-open adjacency is allowed.
        v2 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=150,
                             justification="v2 adjacent",
                             effective_from="2027-07-01T00:00:00Z",
                             effective_to="2028-01-01T00:00:00Z")
        approved_v2 = validate_success(api.approve_variance_request(
            v2["id"], get_establishment(est["id"])["version"], OFFICER))
        assert approved_v2["status"] == "APPROVED", (
            "effective_from == other window's effective_to is adjacency"
        )

        # V3 overlaps V1's window by one day.
        v3 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=200,
                             justification="v3 overlapping",
                             effective_from="2027-06-30T00:00:00Z",
                             effective_to="2027-12-01T00:00:00Z")
        resp = api.approve_variance_request(
            v3["id"], get_establishment(est["id"])["version"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_WINDOW_OVERLAP, 409)

        current_v3 = validate_success(api.get_variance_request(v3["id"],
                                                               OFFICER))
        assert current_v3["status"] == "UNDER_REVIEW"
        after = get_establishment(est["id"])
        assert after["variance_override_frequency_days"] == 150, (
            "V2's frequency override is the latest; V3 wrote nothing"
        )

    def test_variance_window_overlap_is_per_scope(self, api):
        """PRD: "And no other `APPROVED` variance for the same establishment
        and scope may have a window overlapping the requested one — the
        windows are half-open, so one request's `effective_from` falling
        exactly on another's `effective_to` is adjacency rather than overlap,
        while a genuine collision is rejected with
        `ERR_VARIANCE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/variance_windows_half_open_adjacency
        """
        est = create_establishment(name="Scope Adjacency",
                                   street_address="91 G Ln")
        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=120, justification="v1")
        get_success_data(api.approve_variance_request(
            v1["id"], get_establishment(est["id"])["version"], OFFICER))

        # Same window but a different scope: no overlap check applies.
        v2 = create_variance(est["id"], scope="INTERCEPTOR_SIZE",
                             justification="v2 other scope, same window")
        approved = validate_success(api.approve_variance_request(
            v2["id"], get_establishment(est["id"])["version"], OFFICER))
        assert approved["status"] == "APPROVED"


class TestValidationOrder:
    def test_verify_manifest_safety_beats_referential(self, api):
        """PRD: "A manifest verification against an unpermitted hauler reports
        `ERR_HAULER_NOT_PERMITTED` before any cross-reference question is
        asked."
        PRD: "the named interceptor must belong to the manifest's
        establishment (`ERR_INTERCEPTOR_MISMATCH`, HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/verify_manifest_safety_beats_referential
        """
        ea = create_establishment(name="EA Grill", street_address="40 A Ave",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        ia = create_active_interceptor(ea["id"], 600)
        eb = create_establishment(name="EB Cafe", street_address="41 B Ave")
        ib = create_active_interceptor(eb["id"], 50)
        # Registered but never permitted (APPLIED): suspending a PERMITTED
        # hauler would cascade-reject its SUBMITTED manifests (PRD:
        # "suspension cascades immediately"), and verification is allowed
        # only from SUBMITTED — an APPLIED hauler keeps the manifest
        # SUBMITTED while still failing the PERMITTED gate.
        hauler = create_hauler(name="Prio Haul", permit_number="PN-PRI")
        # Manifest for EA naming EB's interceptor (mismatch not checked at
        # creation).
        manifest = create_manifest(ea["id"], ib["id"], hauler["id"])

        resp = api.verify_pump_manifest(manifest["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_HAULER_NOT_PERMITTED, 409)
        current = validate_success(api.get_pump_manifest(manifest["id"],
                                                         INSPECTOR))
        assert current["status"] == "SUBMITTED", (
            "The failed verify leaves the manifest SUBMITTED"
        )

    def test_verify_manifest_referential_fires_when_safety_passes(self, api):
        """PRD: "Manifest cross-reference coherence at verification, in this
        sequence: interceptor ownership (`ERR_INTERCEPTOR_MISMATCH`), disposal
        record existence (`ERR_DISPOSAL_RECORD_MISSING`), disposal volume
        tolerance (`ERR_DISPOSAL_DISCREPANCY`)."
        PRD: "A manifest verification against an unpermitted hauler reports
        `ERR_HAULER_NOT_PERMITTED` before any cross-reference question is
        asked."

        Design: Difficulty/priority_pair_validation_conflict/verify_manifest_safety_beats_referential
        """
        ea = create_establishment(name="EA Grill 2", street_address="42 A Ave",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        create_active_interceptor(ea["id"], 600)
        eb = create_establishment(name="EB Cafe 2", street_address="43 B Ave")
        ib = create_active_interceptor(eb["id"], 50)
        hauler = create_and_permit_hauler(name="Prio Haul 2",
                                          permit_number="PN-PRI2")
        manifest = create_manifest(ea["id"], ib["id"], hauler["id"])

        # Hauler PERMITTED but no disposal record: mismatch outranks missing.
        resp = api.verify_pump_manifest(manifest["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INTERCEPTOR_MISMATCH, 422)
        current = validate_success(api.get_pump_manifest(manifest["id"],
                                                         INSPECTOR))
        assert current["status"] == "SUBMITTED"

    def test_variance_approve_state_beats_temporal(self, api):
        """PRD: "Approval is the most heavily guarded decision in the program,
        and its checks run in a fixed order. The request must still be
        `UNDER_REVIEW`."
        PRD: "And no other `APPROVED` variance for the same establishment and
        scope may have a window overlapping the requested one"

        Design: Difficulty/priority_pair_validation_conflict/variance_approve_state_beats_temporal
        """
        est = create_establishment(name="Prio Cafe", street_address="50 C Ct")
        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=120, justification="v1")
        get_success_data(api.approve_variance_request(
            v1["id"], get_establishment(est["id"])["version"], OFFICER))

        # V2 overlaps V1's APPROVED window; deny V2 so it is terminal.
        v2 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=150, justification="v2",
                             effective_from="2027-03-01T00:00:00Z",
                             effective_to="2027-09-01T00:00:00Z")
        get_success_data(api.deny_variance_request(v2["id"], OFFICER))

        # Approving a terminal DENIED variance: the from-state check fires
        # even though its window would also overlap V1's.
        resp = api.approve_variance_request(
            v2["id"], get_establishment(est["id"])["version"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_variance_request(v2["id"], OFFICER))
        assert current["status"] == "DENIED"

    def test_variance_approve_terminal_under_review_pair(self, api):
        """PRD: "Approval is the most heavily guarded decision in the program,
        and its checks run in a fixed order. The request must still be
        `UNDER_REVIEW`."
        PRD: "`APPROVED` and `DENIED` are both terminal."

        Design: Difficulty/priority_pair_validation_conflict/variance_approve_state_beats_temporal
        """
        est = create_establishment(name="Prio Annex", street_address="51 C Ct")
        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=120, justification="v1")
        get_success_data(api.deny_variance_request(v1["id"], OFFICER))
        # A denied-then-approved attempt fails the state check regardless of
        # any window considerations (no other APPROVED variance exists here).
        resp = api.approve_variance_request(
            v1["id"], get_establishment(est["id"])["version"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_variance_request(v1["id"], OFFICER))
        assert current["status"] == "DENIED"
