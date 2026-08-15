"""Finalization gates, the ops checkpoint, event cancellation cascades, and
swim-safety assessments."""
from test_helpers import (
    ApiErrorId,
    assert_event,
    assess_penalty,
    create_event,
    create_safety_assessment_payload,
    file_appeal_under_review,
    get_result_of,
    get_success_data,
    setup_finished_race,
    setup_live_race,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
REFEREE = TEST_USERS["referee_headers"]


class TestSwimSafety:
    def test_swim_temp_inclusive_boundary_12_0(self, api):
        """PRD §3.5: "The derived `outcome` is `SWIM_CANCEL` when the water is
        colder than 12.0 degrees, warmer than 31.0 degrees, or lightning is
        present within ten kilometers, and `SWIM_OK` otherwise — the
        boundaries are inclusive on the proceed side, so exactly 12.0 degrees
        and exactly 31.0 degrees both proceed."
        PRD §3.5: "Recording a new assessment supersedes the event's previous
        `RECORDED` assessment, moving it to `SUPERSEDED` (terminal), and flips
        the event's `swim_status` to match the new outcome."

        Design: Difficulty/boundary_precision_check/swim_temp_inclusive_boundary_12_0
        """
        event = create_event(has_swim=True, water_pool_units=100)
        ok = validate_success(api.create_safety_assessment(
            event["id"],
            create_safety_assessment_payload(water_temp_celsius=12.0),
            RD), expected_status=201)
        assert ok["outcome"] == "SWIM_OK", \
            "exactly 12.0 degrees proceeds (inclusive boundary)"

        cancel = validate_success(api.create_safety_assessment(
            event["id"],
            create_safety_assessment_payload(water_temp_celsius=11.9),
            RD), expected_status=201)
        assert cancel["outcome"] == "SWIM_CANCEL", "11.9 degrees cancels"

        after = validate_success(api.get_event(event["id"], RD))
        assert after["swim_status"] == "SWIM_CANCELLED", \
            "the superseding assessment governs swim_status"

    def test_swim_temp_upper_boundary_31_0(self, api):
        """PRD §3.5: "the boundaries are inclusive on the proceed side, so
        exactly 12.0 degrees and exactly 31.0 degrees both proceed."

        Design: Difficulty/boundary_precision_check/swim_temp_inclusive_boundary_12_0
        """
        event = create_event(has_swim=True, water_pool_units=100)
        at_max = validate_success(api.create_safety_assessment(
            event["id"],
            create_safety_assessment_payload(water_temp_celsius=31.0),
            RD), expected_status=201)
        assert at_max["outcome"] == "SWIM_OK"

        above_max = validate_success(api.create_safety_assessment(
            event["id"],
            create_safety_assessment_payload(water_temp_celsius=31.1),
            RD), expected_status=201)
        assert above_max["outcome"] == "SWIM_CANCEL"

    def test_lightning_forces_cancellation(self, api):
        """PRD §3.5: "The derived `outcome` is `SWIM_CANCEL` when the water is
        colder than 12.0 degrees, warmer than 31.0 degrees, or lightning is
        present within ten kilometers, and `SWIM_OK` otherwise".

        Design: Difficulty/boundary_precision_check/swim_temp_inclusive_boundary_12_0
        """
        event = create_event(has_swim=True, water_pool_units=100)
        lightning = validate_success(api.create_safety_assessment(
            event["id"],
            create_safety_assessment_payload(water_temp_celsius=20.0,
                                             lightning_within_10km=True),
            RD), expected_status=201)
        assert lightning["outcome"] == "SWIM_CANCEL", \
            "lightning within 10km cancels regardless of temperature"

    def test_superseded_assessment_chain(self, api):
        """PRD §3.5: "Recording a new assessment supersedes the event's
        previous `RECORDED` assessment, moving it to `SUPERSEDED` (terminal),
        and flips the event's `swim_status` to match the new outcome."
        PRD §3.5: "The reverse, reinstating a cancelled swim from
        `SWIM_CANCELLED` back to `SWIM_ON`, recomputes results under the
        standard triathlon variant but is forbidden once the event is `LIVE`
        (`ERR_INVALID_STATE`)" — pre-LIVE the reinstatement is allowed.

        Design: Corner/complexity_layers/superseded_assessment_chain
        """
        event = create_event(has_swim=True, water_pool_units=100)
        s1 = get_success_data(api.create_safety_assessment(
            event["id"], create_safety_assessment_payload(
                water_temp_celsius=20.0), RD))
        s2 = get_success_data(api.create_safety_assessment(
            event["id"], create_safety_assessment_payload(
                water_temp_celsius=10.0), RD))
        s3 = get_success_data(api.create_safety_assessment(
            event["id"], create_safety_assessment_payload(
                water_temp_celsius=25.0), RD))

        statuses = {
            s["id"]: validate_success(api.get_safety_assessment(s["id"], RD))["status"]
            for s in (s1, s2, s3)
        }
        assert statuses[s1["id"]] == "SUPERSEDED"
        assert statuses[s2["id"]] == "SUPERSEDED"
        assert statuses[s3["id"]] == "RECORDED", \
            "exactly one assessment remains RECORDED — the latest"

        after = validate_success(api.get_event(event["id"], RD))
        assert after["swim_status"] == "SWIM_ON", \
            "the latest assessment governs; reinstatement is allowed pre-LIVE"


class TestFinalizationGates:
    def test_finalize_blocked_with_outstanding_appeal(self, api):
        """PRD §3.7: "moving `LIVE` to `FINALIZED` requires that no penalty
        remain `ASSESSED` (`ERR_PENALTIES_UNRESOLVED`) and that no appeal
        remain `FILED` or `UNDER_REVIEW` (`ERR_APPEALS_OUTSTANDING`)."

        Design: Corner/validations/finalize_blocked_with_outstanding_appeal
        """
        ctx = setup_live_race(num_athletes=1)
        athlete = ctx["athletes"][0]
        registration = ctx["registrations"][0]
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")
        file_appeal_under_review(penalty["id"], athlete, reviewer_id="ref-2",
                                 grounds="g")

        resp = api.finalize_event(ctx["event"]["id"], RD)
        # An open appeal implies its penalty is still ASSESSED (penalties leave
        # ASSESSED only via a decision or an auto-confirm that open appeals
        # block), so both §3.7 gate conditions hold at once and PRD names no
        # precedence between them.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_APPEALS_OUTSTANDING.value,
            ApiErrorId.ERR_PENALTIES_UNRESOLVED.value,
        ])
        after = validate_success(api.get_event(ctx["event"]["id"], RD))
        assert after["posture"] == "LIVE"

    def test_finalize_blocked_with_unresolved_penalty(self, api):
        """PRD §3.7: "moving `LIVE` to `FINALIZED` requires that no penalty
        remain `ASSESSED` (`ERR_PENALTIES_UNRESOLVED`)".

        Design: Corner/errors/error_penalties_unresolved_on_finalize
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        # Assessed at 08:00 with the default 60-minute window (expires 09:00).
        assess_penalty(registration["id"], kind="EQUIPMENT", referee_id="ref-1")
        # Still inside the window: no auto-confirm possible, no appeal filed.
        get_success_data(api.set_clock("2026-10-15T08:30:00Z", RD))

        resp = api.finalize_event(ctx["event"]["id"], RD)
        validate_error(resp, ApiErrorId.ERR_PENALTIES_UNRESOLVED.value)
        after = validate_success(api.get_event(ctx["event"]["id"], RD))
        assert after["posture"] == "LIVE"

    def test_finalize_never_confirms_implicitly(self, api):
        """PRD §3.7: "A penalty leaves `ASSESSED` in only three ways: the ops
        checkpoint auto-confirms it once `appeal_window_expires_at` is at or
        before the clock and no appeal of it is `FILED` or `UNDER_REVIEW`; an
        appeal decision of `UPHELD` or `REDUCED` confirms it; or an appeal
        decision of `OVERTURNED` overturns it." Finalize is not among them.
        PRD §3.7: "moving `LIVE` to `FINALIZED` requires that no penalty
        remain `ASSESSED` (`ERR_PENALTIES_UNRESOLVED`)".

        Design: Corner/errors/penalties_unresolved_and_dsq_finalize_blocked
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        assess_penalty(registration["id"], kind="EQUIPMENT", referee_id="ref-1")
        # Window (60 min from 08:00) has expired, but no run-ops has run.
        get_success_data(api.set_clock("2026-10-15T09:30:00Z", RD))

        resp = api.finalize_event(ctx["event"]["id"], RD)
        validate_error(resp, ApiErrorId.ERR_PENALTIES_UNRESOLVED.value)
        # window expiry alone does not confirm; finalize stays blocked

        get_success_data(api.run_ops(ctx["event"]["id"], RD))
        finalized = validate_success(api.finalize_event(ctx["event"]["id"], RD))
        assert_event(finalized)
        assert finalized["posture"] == "FINALIZED", \
            "after the ops checkpoint confirmed the penalty, finalize succeeds"

    def test_finalize_makes_results_official(self, api):
        """PRD §3.7: "It moves every result to `OFFICIAL`, sets each
        `official_total_seconds` to the provisional total plus
        `penalty_seconds_total`, recomputes division ranks over
        `effective_total_seconds`, and increments the event's `version` by
        one."

        Design: Corner/errors/penalties_unresolved_and_dsq_finalize_blocked
        """
        ctx = setup_finished_race()
        registration = ctx["registrations"][0]
        finalized = validate_success(api.finalize_event(ctx["event"]["id"], RD))
        assert finalized["posture"] == "FINALIZED"
        result = get_result_of(registration["id"])
        assert result["status"] == "OFFICIAL"
        assert result["official_total_seconds"] == 6390, \
            "no penalties: official == provisional"
        assert result["effective_total_seconds"] == 6390


class TestOpsCheckpoint:
    def test_penalty_auto_confirm_only_after_window(self, api):
        """PRD §3.7: "the ops checkpoint auto-confirms it once
        `appeal_window_expires_at` is at or before the clock and no appeal of
        it is `FILED` or `UNDER_REVIEW`".
        PRD §3.6: "`penalty_seconds_total` sums the `seconds` of the
        registration's penalties in `CONFIRMED` status only — assessed and
        overturned penalties contribute nothing."

        Design: Corner/complexity_layers/penalty_auto_confirm_only_after_window
        """
        ctx = setup_live_race(num_athletes=1)
        registration = ctx["registrations"][0]
        # Assessed at 08:00; default 60-minute window expires 09:00.
        penalty = assess_penalty(registration["id"], kind="EQUIPMENT",
                                 referee_id="ref-1")

        get_success_data(api.set_clock("2026-10-15T08:30:00Z", RD))
        get_success_data(api.run_ops(ctx["event"]["id"], RD))
        still = validate_success(api.get_penalty(penalty["id"], RD))
        assert still["status"] == "ASSESSED", \
            "run-ops inside the window leaves the penalty ASSESSED"

        get_success_data(api.set_clock("2026-10-15T09:00:00Z", RD))
        get_success_data(api.run_ops(ctx["event"]["id"], RD))
        confirmed = validate_success(api.get_penalty(penalty["id"], RD))
        assert confirmed["status"] == "CONFIRMED", \
            "at the expiry instant (expires_at <= clock) run-ops confirms"

        result = get_result_of(registration["id"])
        assert result["penalty_seconds_total"] == 60, \
            "the confirmed EQUIPMENT penalty joins the CONFIRMED-only sum"

    def test_run_ops_increments_ops_run_index(self, api):
        """PRD §3.7: "Each run increments the event's `ops_run_index` by
        one".

        Design: Corner/complexity_layers/penalty_auto_confirm_only_after_window
        """
        ctx = setup_live_race(num_athletes=1)
        first = validate_success(api.run_ops(ctx["event"]["id"], RD))
        second = validate_success(api.run_ops(ctx["event"]["id"], RD))
        assert second["ops_run_index"] == first["ops_run_index"] + 1


class TestDsqCascade:
    def test_third_drafting_confirm_triggers_dsq(self, api):
        """PRD §3.7: "when the confirmed penalty's `triggers_dsq` is set, the
        registration — whether `RACING` or `FINISHED` — moves to `DSQ`, its
        `division_rank` is nulled, and it is excluded from ranking".
        PRD §3.7: "with two or more priors the penalty carries zero seconds
        and instead sets `triggers_dsq`, the disqualification flag."
        PRD §3.6: "Disqualified and unfinished results carry a null
        `division_rank`."

        Design: Corner/state_machines/dsq_cascade_on_third_drafting_confirm
        """
        ctx = setup_finished_race()
        registration = ctx["registrations"][0]
        assert registration["status"] == "FINISHED"
        assert get_result_of(registration["id"])["division_rank"] == 1

        # All three assessed at the 08:00 clock; default 60-minute window.
        assess_penalty(registration["id"], kind="DRAFTING", referee_id="ref-1")
        assess_penalty(registration["id"], kind="DRAFTING", referee_id="ref-1")
        third = assess_penalty(registration["id"], kind="DRAFTING",
                               referee_id="ref-1")
        assert third["triggers_dsq"] is True, "third DRAFTING carries the flag"

        get_success_data(api.set_clock("2026-10-15T10:00:00Z", RD))
        get_success_data(api.run_ops(ctx["event"]["id"], RD))

        after = validate_success(api.get_registration(registration["id"], RD))
        assert after["status"] == "DSQ", \
            "confirming the DSQ-flagged penalty flips even a FINISHED registration"
        result = get_result_of(registration["id"])
        assert result["division_rank"] is None, "excluded from ranking"
        assert result["penalty_seconds_total"] == 420, \
            "120 + 300 + 0: the DSQ-tier penalty contributes zero seconds"
