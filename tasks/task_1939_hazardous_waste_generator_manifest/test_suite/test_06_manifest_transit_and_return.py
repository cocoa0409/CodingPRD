"""Manifest transit, receipt, discrepancy loop, the 45-day return window,
exception sweeps, and the sign-generator state/SoD precedence."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, manifest_line_item, create_manifest, get_manifest, get_site,
    get_container, attach_ldr, sign_manifest_generator, confirm_manifest_return,
    sign_manifest_transporter, receive_manifest, create_staged_container,
    set_clock, create_manifest_chain, setup_shippable_site,
    ehs_headers, wc_headers, ca_headers,
    make_transporter_agent_headers, make_tsdf_agent_headers,
    assert_instant_equals, exception_report_payload,
)


class TestReturnWindowRead:
    def test_manifest_get_shows_computed_return_window(self, api):
        """PRD §3.7: "This stamps `shipped_at` with the logical instant and opens
        the return window: `return_due_at` is exactly 45 days after `shipped_at`.
        The signature cascades to the cargo — every line-item container moves from
        `STAGED_FOR_SHIPMENT` to `SHIPPED` and has its `shipped_manifest_id` set to
        this manifest's id." PRD §3.6: "A drafted manifest starts in `DRAFT` with
        `total_quantity_kg` equal to the sum of the lines' `quantity_kg` and
        `tonnage_fee_cents` computed per the pinned rounding of §2.10".

        Design: Corner/endpoints/manifest_get_shows_computed_return_window
        """
        env = create_manifest_chain(quantity_kg=100.0, tracking_number="MT-240",
                                    through="IN_TRANSIT")
        manifest = get_manifest(env["manifest"]["id"])
        assert manifest["status"] == "IN_TRANSIT"
        assert_instant_equals(manifest["shipped_at"], "2026-08-01T00:00:00Z",
                              "shipped_at")
        assert_instant_equals(manifest["return_due_at"], "2026-09-15T00:00:00Z",
                              "return_due_at")
        assert manifest["total_quantity_kg"] == 100.0
        assert manifest["tonnage_fee_cents"] == 1050
        container = get_container(env["container"]["id"])
        assert container["status"] == "SHIPPED"
        assert container["shipped_manifest_id"] == manifest["id"]


class TestDiscrepancyLoop:
    def test_manifest_discrepancy_cycle(self, api):
        """PRD §3.7: "the same `TSDFAgent` raises a discrepancy on a `DELIVERED`
        manifest, moving it to `DISCREPANCY_RAISED` and incrementing the site's
        `open_discrepancy_count` by one. A `ComplianceAuditor` later resolves the
        discrepancy, returning the manifest to `DELIVERED` and decrementing the
        same counter by one — the pair nets to zero, and `DISCREPANCY_RAISED`
        never blocks the return confirmation that follows."

        Design: Difficulty/non_linear_state_machine/manifest_discrepancy_cycle
        """
        env = create_manifest_chain(tracking_number="MT-400", through="DELIVERED")
        manifest, tsdf = env["manifest"], env["tsdf"]
        raised = validate_success(api.raise_discrepancy(
            manifest["id"], make_tsdf_agent_headers(tsdf["id"])))
        assert raised["status"] == "DISCREPANCY_RAISED"
        assert get_site(env["site"]["id"])["open_discrepancy_count"] == 1
        resolved = validate_success(api.resolve_discrepancy(
            manifest["id"], ca_headers("aud-2")))
        assert resolved["status"] == "DELIVERED"
        assert get_site(env["site"]["id"])["open_discrepancy_count"] == 0
        returned = confirm_manifest_return(manifest["id"])
        assert returned["status"] == "RETURNED"
        assert returned["is_return_late"] is False
        # The cargo reached its terminal state at receipt and stays there.
        assert get_container(env["container"]["id"])["status"] == "EMPTIED"

    def test_discrepancy_cycle_repeats_before_return(self, api):
        """PRD §3.7: "A `ComplianceAuditor` later resolves the discrepancy,
        returning the manifest to `DELIVERED` and decrementing the same counter
        by one — the pair nets to zero, and `DISCREPANCY_RAISED` never blocks the
        return confirmation that follows."

        Design: Difficulty/non_linear_state_machine/manifest_discrepancy_cycle
        """
        env = create_manifest_chain(tracking_number="MT-401", through="DELIVERED")
        manifest, tsdf = env["manifest"], env["tsdf"]
        for _ in range(2):  # two full DELIVERED -> DISCREPANCY_RAISED -> DELIVERED laps
            raised = validate_success(api.raise_discrepancy(
                manifest["id"], make_tsdf_agent_headers(tsdf["id"])))
            assert raised["status"] == "DISCREPANCY_RAISED"
            resolved = validate_success(api.resolve_discrepancy(
                manifest["id"], ca_headers("aud-2")))
            assert resolved["status"] == "DELIVERED"
        returned = confirm_manifest_return(manifest["id"])
        assert returned["status"] == "RETURNED"
        assert get_site(env["site"]["id"])["open_discrepancy_count"] == 0

    def test_discrepancy_raise_resolve_restores_counter(self, api):
        """PRD §3.7: "raises a discrepancy on a `DELIVERED` manifest, moving it to
        `DISCREPANCY_RAISED` and incrementing the site's `open_discrepancy_count`
        by one. A `ComplianceAuditor` later resolves the discrepancy, returning
        the manifest to `DELIVERED` and decrementing the same counter by one —
        the pair nets to zero".

        Design: Difficulty/compensating_invariant/discrepancy_raise_resolve_restores_counter
        """
        env = create_manifest_chain(tracking_number="MT-950", through="DELIVERED")
        site_id = env["site"]["id"]
        assert get_site(site_id)["open_discrepancy_count"] == 0
        validate_success(api.raise_discrepancy(
            env["manifest"]["id"], make_tsdf_agent_headers(env["tsdf"]["id"])))
        after_raise = get_site(site_id)
        assert after_raise["open_discrepancy_count"] == 1
        assert get_manifest(env["manifest"]["id"])["status"] == "DISCREPANCY_RAISED"
        validate_success(api.resolve_discrepancy(
            env["manifest"]["id"], ca_headers("aud-2")))
        after_resolve = get_site(site_id)
        assert after_resolve["open_discrepancy_count"] == 0, (
            "the raise/resolve pair conserves the counter")
        assert get_manifest(env["manifest"]["id"])["status"] == "DELIVERED"

    def test_discrepancy_counter_is_scoped_per_site(self, api):
        """PRD §3.7: "moving it to `DISCREPANCY_RAISED` and incrementing the
        site's `open_discrepancy_count` by one" — the counter belongs to the
        manifest's own site; a sister site's counter is untouched.

        Design: Difficulty/compensating_invariant/discrepancy_raise_resolve_restores_counter
        """
        env_a = create_manifest_chain(tracking_number="MT-951", through="DELIVERED")
        env_b = create_manifest_chain(tracking_number="MT-952",
                                      epa_id_number="EPA-SITE-B",
                                      transporter_epa="EPA-TR-B",
                                      tsdf_epa="EPA-TS-B", through="DELIVERED")
        validate_success(api.raise_discrepancy(
            env_a["manifest"]["id"], make_tsdf_agent_headers(env_a["tsdf"]["id"])))
        assert get_site(env_a["site"]["id"])["open_discrepancy_count"] == 1
        assert get_site(env_b["site"]["id"])["open_discrepancy_count"] == 0
        validate_success(api.resolve_discrepancy(
            env_a["manifest"]["id"], ca_headers("aud-2")))
        assert get_site(env_a["site"]["id"])["open_discrepancy_count"] == 0


class TestReturnWindowBoundary:
    def test_manifest_return_exactly_45_days_not_overdue_at_due(self, api):
        """PRD §3.8: "At exactly `return_due_at` the manifest is not yet overdue —
        the comparison is strictly greater-than." PRD §3.7: "`return_due_at` is
        exactly 45 days after `shipped_at`."

        Design: Difficulty/boundary_precision_check/manifest_return_exactly_45_days
        """
        env = create_manifest_chain(tracking_number="MT-800", through="IN_TRANSIT")
        manifest = get_manifest(env["manifest"]["id"])
        assert_instant_equals(manifest["return_due_at"], "2026-09-15T00:00:00Z",
                              "return_due_at")
        # The clock sitting exactly on the deadline has not tripped it.
        set_clock("2026-09-15T00:00:00Z")
        manifest = get_manifest(env["manifest"]["id"])
        assert manifest["status"] == "IN_TRANSIT"
        assert get_site(env["site"]["id"])["open_exception_count"] == 0

    def test_manifest_return_one_second_late_trips_exception(self, api):
        """PRD §3.8: "When the logical clock advances past a manifest's
        `return_due_at` while the manifest sits in `IN_TRANSIT`, `DELIVERED`, or
        `DISCREPANCY_RAISED`, the sweep moves it to `EXCEPTION_REQUIRED` and
        increments the site's `open_exception_count` by one per manifest."

        Design: Difficulty/boundary_precision_check/manifest_return_exactly_45_days
        """
        env = create_manifest_chain(tracking_number="MT-801", through="IN_TRANSIT")
        set_clock("2026-09-15T00:00:01Z")  # one second past the 45-day window
        manifest = get_manifest(env["manifest"]["id"])
        assert manifest["status"] == "EXCEPTION_REQUIRED"
        assert get_site(env["site"]["id"])["open_exception_count"] == 1


class TestSignGeneratorPrecedence:
    def test_sign_generator_state_beats_sod(self, api):
        """PRD §2.9: "seventh, state-machine legality (`ERR_INVALID_STATE` or the
        more specific state errors); eighth and onward, the business,
        segregation-of-duties, referential, and temporal rules described
        throughout §3". PRD §3.6: "the manifest must be `DRAFT` (otherwise
        `ERR_MANIFEST_NOT_DRAFT`)". The second signature attempt by the manifest's
        own creator fails both gates; the state gate reports first.

        Design: Difficulty/priority_pair_validation_conflict/sign_generator_state_beats_sod
        """
        env = create_manifest_chain(tracking_number="MT-600", creator="wc-1",
                                    through="GENERATOR_SIGNED")
        res = api.sign_manifest_generator(env["manifest"]["id"], ehs_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_MANIFEST_NOT_DRAFT)
        assert res.status_code == 409
        assert get_manifest(env["manifest"]["id"])["status"] == "GENERATOR_SIGNED"

    def test_sign_generator_terminal_beats_sod(self, api):
        """PRD §2.9: "an entity already in a terminal state (`RETIRED`, `EMPTIED`,
        `VOIDED`, `RETURNED`, `ACCEPTED`, or `REJECTED`) rejects every further
        transition with `ERR_ALREADY_TERMINAL`" — and the state band runs before
        "the business, segregation-of-duties, referential, and temporal rules".

        Design: Difficulty/priority_pair_validation_conflict/sign_generator_state_beats_sod
        """
        env = create_manifest_chain(tracking_number="MT-601", creator="wc-1",
                                    through="RETURNED")
        res = api.sign_manifest_generator(env["manifest"]["id"], ehs_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert get_manifest(env["manifest"]["id"])["status"] == "RETURNED"


class TestExceptionSweep:
    def test_clock_sweep_exception_blocks_new_manifest(self, api):
        """PRD §3.8: "the sweep moves it to `EXCEPTION_REQUIRED` and increments
        the site's `open_exception_count` by one per manifest." and "The
        consequence is immediate: while `open_exception_count` is positive, the
        site may not create new manifests, per the
        `ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST` rule of §3.6."

        Design: Difficulty/transitive_cascade/clock_sweep_exception_blocks_new_manifest
        """
        env = create_manifest_chain(tracking_number="MT-500", through="IN_TRANSIT")
        # A second container sits STAGED_FOR_SHIPMENT, ready for a follow-up.
        c2 = create_staged_container(env["stream"]["id"], env["central"]["id"],
                                     5, 50.0)
        set_clock("2026-09-16T00:00:00Z")  # one day past return_due_at
        assert get_manifest(env["manifest"]["id"])["status"] == "EXCEPTION_REQUIRED"
        assert get_site(env["site"]["id"])["open_exception_count"] == 1
        line = manifest_line_item(env["stream"]["id"], c2["id"], 50.0)
        res = api.create_manifest(
            {"site_id": env["site"]["id"],
             "transporter_id": env["transporter"]["id"],
             "tsdf_id": env["tsdf"]["id"], "manifest_tracking_number": "MT-501",
             "line_items": [line]},
            wc_headers("wc-1"))
        validate_error(res, ApiErrorId.ERR_OPEN_EXCEPTION_BLOCKS_MANIFEST)
        assert get_container(c2["id"])["status"] == "STAGED_FOR_SHIPMENT"

    def test_exception_discharge_reopens_manifest_creation(self, api):
        """PRD §3.8: "A `ComplianceAuditor` discharges the exception paperwork by
        filing an exception report on an `EXCEPTION_REQUIRED` manifest, supplying
        an `exception_note`. Filing moves the manifest to
        `EXCEPTION_REPORT_FILED` and stores the note; the manifest continues to
        count toward `open_exception_count` until a return is confirmed." PRD
        §3.7: "When the transition leaves `EXCEPTION_REQUIRED` or
        `EXCEPTION_REPORT_FILED`, the site's `open_exception_count` is decremented
        by one."

        Design: Difficulty/transitive_cascade/clock_sweep_exception_blocks_new_manifest
        """
        env = create_manifest_chain(tracking_number="MT-500", through="IN_TRANSIT")
        c2 = create_staged_container(env["stream"]["id"], env["central"]["id"],
                                     5, 50.0)
        set_clock("2026-09-16T00:00:00Z")
        manifest_id = env["manifest"]["id"]
        # Filing the report does NOT clear the counter.
        filed = validate_success(api.file_exception_report(
            manifest_id, exception_report_payload("transporter unreachable"),
            ca_headers("aud-2")))
        assert filed["status"] == "EXCEPTION_REPORT_FILED"
        assert get_site(env["site"]["id"])["open_exception_count"] == 1
        # The return confirmation discharges it and reopens manifest creation.
        returned = confirm_manifest_return(manifest_id)
        assert returned["status"] == "RETURNED"
        assert returned["is_return_late"] is True
        assert get_site(env["site"]["id"])["open_exception_count"] == 0
        line = manifest_line_item(env["stream"]["id"], c2["id"], 50.0)
        follow_up = create_manifest(
            env["site"]["id"], env["transporter"]["id"], env["tsdf"]["id"],
            [line], "MT-501")
        assert follow_up["status"] == "DRAFT"


class TestManifestTerminalLockdown:
    def test_manifest_returned_terminal_lockdown(self, api):
        """PRD §3.7: confirm-return moves the manifest "to the terminal state
        `RETURNED`". PRD §2.9: "an entity already in a terminal state (`RETIRED`,
        `EMPTIED`, `VOIDED`, `RETURNED`, `ACCEPTED`, or `REJECTED`) rejects every
        further transition with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/manifest_returned_terminal_lockdown
        """
        env = create_manifest_chain(tracking_number="MT-100", through="RETURNED")
        first = env["manifest"]
        res = api.confirm_manifest_return(first["id"], ehs_headers())
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        fresh = get_manifest(first["id"])
        assert fresh["status"] == "RETURNED"
        assert fresh["returned_at"] == first["returned_at"]

    def test_file_exception_report_from_in_transit_rejected(self, api):
        """PRD §3.8: "A `ComplianceAuditor` discharges the exception paperwork by
        filing an exception report on an `EXCEPTION_REQUIRED` manifest" — filing
        while merely `IN_TRANSIT` is a state mismatch, and per PRD §2.9 the state
        band reports `ERR_INVALID_STATE`.

        Design: Corner/endpoints/file_exception_report_from_in_transit_rejected
        """
        env = create_manifest_chain(tracking_number="MT-250", through="IN_TRANSIT")
        res = api.file_exception_report(
            env["manifest"]["id"], exception_report_payload("premature filing"),
            ca_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_manifest(env["manifest"]["id"])["status"] == "IN_TRANSIT"
