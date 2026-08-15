"""Timeline commitments: revision cycles, OCC, the MISSED sweep, and delay credits."""
from test_helpers import (
    ApiErrorId,
    complete_turn_on_payload,
    confirm_booking,
    create_booking,
    create_crew,
    create_gis_as_built_payload,
    create_inspector_payload,
    create_meter_set_payload,
    create_turn_on_event_payload,
    get_success_data,
    make_inspector_headers,
    record_as_built_payload,
    record_purge_leak_test,
    refresh_application,
    refresh_commitment,
    refresh_invoice,
    refresh_main_extension,
    set_clock,
    setup_ciac_pending_app,
    setup_quoted_app,
    validate_error,
    validate_success,
)


class TestRevisionRoundTrip:
    def _setup_accepted(self, api):
        ctx = setup_quoted_app(design_footage_ft=200, crossings=[
            {"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0},
        ])
        commitment = ctx["commitment"]
        assert commitment["committed_completion_date"] == "2026-09-02"
        accepted = get_success_data(
            api.accept_commitment(commitment["id"], ctx["builder_headers"])
        )
        return ctx, accepted

    def test_accept_decision_adopts_requested_date(self, api, rep_headers):
        """PRD §3.7: "The proposal parks the commitment in `REVISION_PENDING` until a `NewBusinessRep` responds: a `decision` of `ACCEPT` replaces the `committed_completion_date` with the requested date and clears `requested_completion_date`, while `REJECT` leaves the committed date untouched and clears the request — both paths land back in `ACCEPTED`."

        Design: Difficulty/non_linear_state_machine/commitment_revision_roundtrip_cycle
        """
        ctx, accepted = self._setup_accepted(api)
        tc_id = ctx["commitment"]["id"]
        proposed = get_success_data(
            api.propose_commitment_revision(
                tc_id,
                {"requested_completion_date": "2026-09-10",
                 "expected_commitment_version": accepted["version"]},
                ctx["builder_headers"],
            )
        )
        assert proposed["status"] == "REVISION_PENDING"

        resp = api.respond_commitment_revision(tc_id, {"decision": "ACCEPT"}, rep_headers)
        resolved = validate_success(resp)
        assert resolved["status"] == "ACCEPTED"
        assert resolved["committed_completion_date"] == "2026-09-10", (
            "the builder's requested date replaces the committed date"
        )
        assert not resolved.get("requested_completion_date"), (
            "the accepted request is cleared"
        )

    def test_reject_decision_keeps_committed_date(self, api, rep_headers):
        """PRD §3.7: "a `decision` of `ACCEPT` replaces the `committed_completion_date` with the requested date and clears `requested_completion_date`, while `REJECT` leaves the committed date untouched and clears the request — both paths land back in `ACCEPTED`."

        Design: Difficulty/non_linear_state_machine/commitment_revision_roundtrip_cycle
        """
        ctx, accepted = self._setup_accepted(api)
        tc_id = ctx["commitment"]["id"]
        get_success_data(
            api.propose_commitment_revision(
                tc_id,
                {"requested_completion_date": "2026-09-10",
                 "expected_commitment_version": accepted["version"]},
                ctx["builder_headers"],
            )
        )
        get_success_data(
            api.respond_commitment_revision(tc_id, {"decision": "ACCEPT"}, rep_headers)
        )
        # Cycle a second time: ACCEPTED -> REVISION_PENDING -> (REJECT) ACCEPTED.
        current = refresh_commitment(tc_id)
        second = get_success_data(
            api.propose_commitment_revision(
                tc_id,
                {"requested_completion_date": "2026-09-20",
                 "expected_commitment_version": current["version"]},
                ctx["builder_headers"],
            )
        )
        assert second["status"] == "REVISION_PENDING"

        resp = api.respond_commitment_revision(tc_id, {"decision": "REJECT"}, rep_headers)
        resolved = validate_success(resp)
        assert resolved["status"] == "ACCEPTED"
        assert resolved["committed_completion_date"] == "2026-09-10", (
            "REJECT leaves the committed date untouched (not 2026-09-20)"
        )
        assert not resolved.get("requested_completion_date")


class TestRevisionGates:
    def test_propose_revision_from_proposed_rejected(self, api):
        """PRD §3.7: "Later, the builder may propose a different committed date — but only from `ACCEPTED` (any other status is rejected with `ERR_COMMITMENT_NOT_REVISABLE`, HTTP 409)"

        Design: Corner/errors/commitment_revision_from_proposed_rejected
        """
        ctx = setup_quoted_app(design_footage_ft=100, crossings=[])
        commitment = ctx["commitment"]
        assert commitment["status"] == "PROPOSED"

        # The version is current, so optimistic concurrency passes and the state
        # gate is the rule that fires.
        resp = api.propose_commitment_revision(
            commitment["id"],
            {"requested_completion_date": "2026-09-10",
             "expected_commitment_version": commitment["version"]},
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_REVISABLE,
                       expected_status=409)

        after = refresh_commitment(commitment["id"])
        assert after["version"] == commitment["version"], (
            "a rejected proposal must not advance the version"
        )

    def test_stale_version_rejected_after_reject_round_trip(self, api, rep_headers):
        """PRD §2.7: "Proposing a commitment revision requires `expected_commitment_version` equal to the commitment's current `version` — and this check applies even when the commitment has since returned to `ACCEPTED` after an earlier propose-then-reject round trip, because that round trip restored the state but advanced the version."

        Design: Corner/complexity_layers/commitment_revision_occ_stale_rejected
        """
        ctx = setup_quoted_app(design_footage_ft=100, crossings=[])
        tc_id = ctx["commitment"]["id"]
        accepted = get_success_data(
            api.accept_commitment(tc_id, ctx["builder_headers"])
        )
        stale_version = accepted["version"]
        assert ctx["commitment"]["committed_completion_date"] == "2026-08-12"

        get_success_data(
            api.propose_commitment_revision(
                tc_id,
                {"requested_completion_date": "2026-09-10",
                 "expected_commitment_version": stale_version},
                ctx["builder_headers"],
            )
        )
        rejected = get_success_data(
            api.respond_commitment_revision(tc_id, {"decision": "REJECT"}, rep_headers)
        )
        assert rejected["status"] == "ACCEPTED", "the round trip restores ACCEPTED"

        resp = api.propose_commitment_revision(
            tc_id,
            {"requested_completion_date": "2026-09-11",
             "expected_commitment_version": stale_version},
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = refresh_commitment(tc_id)
        assert after["committed_completion_date"] == "2026-08-12"


class TestMissedCommitmentPenalty:
    def test_late_completion_computes_penalty_credit(self, api, admin_headers,
                                                     clerk_headers, coordinator_headers,
                                                     engineer_headers, gis_analyst_headers,
                                                     rep_headers, supervisor_headers,
                                                     technician_headers):
        """PRD §3.7: "The `penalty_credit_cents` — zero by default — is computed at application completion from the calendar days between the committed and actual completion dates: zero or negative days late means the commitment was met and no credit accrues; otherwise each of the first five late days earns 2,500 cents ($25.00) and each late day beyond the fifth earns 5,000 cents, with the total capped at 50,000 cents ($500.00)."
        PRD §2.9: "a timeline commitment in `ACCEPTED` or `AT_RISK` whose `committed_completion_date` has passed, while its application is not yet `COMPLETED`, moves to `MISSED`; a commitment swept from `ACCEPTED` that has no recorded delay attribution is attributed to `UTILITY` by default."
        PRD §3.8: "Submission starts the record in `SUBMITTED`, stamps `submitted_by_user_id`, and slides the application from `ENERGIZED` into `GIS_REVIEW`."
        PRD §3.8: "which is accepted only while the application is `ENERGIZED` or already in `GIS_REVIEW`, and only once per application (`ERR_DUPLICATE_GIS`, HTTP 409)"

        Design: Corner/calculations/commitment_missed_penalty_on_late_completion
        """
        # Zero-CIAC happy path (100 ft, no crossings): invoice auto-PAID.
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        tc_id = ctx["commitment"]["id"]
        get_success_data(api.accept_commitment(tc_id, ctx["builder_headers"]))
        assert refresh_commitment(tc_id)["committed_completion_date"] == "2026-08-12"

        crew = create_crew(specialty="SERVICE_LINE")
        booking = create_booking(ctx["app"]["id"], crew["id"], work_date="2026-08-04",
                                 start=540, end=1020, scope="SERVICE_INSTALL")
        confirm_booking(booking["id"])
        get_success_data(api.schedule_construction(ctx["app"]["id"], supervisor_headers))
        get_success_data(api.complete_booking(booking["id"], supervisor_headers))

        me_id = ctx["me"]["id"]
        get_success_data(api.record_as_built(me_id, record_as_built_payload(),
                                             supervisor_headers))
        get_success_data(api.finalize_main_extension(me_id, clerk_headers))
        assert refresh_invoice(ctx["invoice"]["id"])["status"] == "SETTLED", (
            "identical as-built on a zero invoice settles with delta zero"
        )
        assert refresh_main_extension(me_id)["status"] == "FINALIZED"

        ms = get_success_data(
            api.create_meter_set(create_meter_set_payload(ctx["app"]["id"]),
                                 technician_headers)
        )
        get_success_data(api.size_meter_set(ms["id"], engineer_headers))
        get_success_data(
            api.mark_meter_ordered(ms["id"], {"serial_number": "M-9001"},
                                   technician_headers)
        )
        get_success_data(api.install_meter_set(ms["id"], technician_headers))
        plt = record_purge_leak_test(ms["id"], observed_pressure_drop_psi=0.200)
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        get_success_data(
            api.certify_purge_leak_test(plt["id"],
                                        make_inspector_headers(inspector["id"]))
        )
        event = get_success_data(
            api.create_turn_on_event(
                create_turn_on_event_payload(ctx["app"]["id"], ctx["loads"][0]["id"]),
                technician_headers,
            )
        )
        get_success_data(
            api.complete_turn_on_event(event["id"], complete_turn_on_payload(),
                                       technician_headers)
        )
        get_success_data(api.energize_application(ctx["app"]["id"], technician_headers))

        gis = get_success_data(
            api.create_gis_as_built(
                create_gis_as_built_payload(ctx["app"]["id"], depth_inches=24.0),
                supervisor_headers,
            )
        )
        assert refresh_application(ctx["app"]["id"])["status"] == "GIS_REVIEW"

        resp = api.create_gis_as_built(
            create_gis_as_built_payload(ctx["app"]["id"], pipe_material="STEEL",
                                        depth_inches=30.0),
            supervisor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GIS, expected_status=409)

        get_success_data(api.validate_gis(gis["id"], gis_analyst_headers))

        # Move past the committed date: the sweep marks the commitment MISSED.
        set_clock("2026-08-18T09:00:00Z")
        swept = refresh_commitment(tc_id)
        assert swept["status"] == "MISSED"
        assert swept["delay_attribution"] == "UTILITY", (
            "no attribution was ever recorded, so the sweep defaults to UTILITY"
        )

        completed = get_success_data(
            api.complete_application(ctx["app"]["id"], rep_headers)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-08-18")

        final_commitment = refresh_commitment(tc_id)
        # 2026-08-18 is 6 days late: 5 x 2500 + 1 x 5000 = 17500.
        assert final_commitment["penalty_credit_cents"] == 17500, (
            f"expected 17500, got {final_commitment['penalty_credit_cents']}"
        )
