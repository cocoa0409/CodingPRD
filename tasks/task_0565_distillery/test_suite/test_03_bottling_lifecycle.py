"""Bottling proof-gallon arithmetic, the production cascade, line contention,
and the label/state guards on starting a run."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_distillery,
    create_gauged_run,
    fill_barrel,
    create_approved_label,
    create_submitted_label,
    create_bottling_run_payload,
    setup_completed_run,
)

_PM = TEST_USERS["production_headers"]


class TestBottlingProofGallons:
    def test_bottled_pg_sum_then_round(self, api):
        """PRD 3.5: "first, the total volume in milliliters is the run's
        `cases_bottled` multiplied by `bottles_per_case` and by `bottle_size_ml`;
        that total is converted to wine gallons by dividing by 3785.411784
        milliliters per gallon; then `bottled_proof_gallons` is the wine-gallon figure
        multiplied by the referenced label application's `label_proof` and divided by
        100, with a single round to the nearest tenth applied once at the very end."

        Design: Difficulty/combinatorial_formula/bottling_pg_sum_then_round_pinned
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-BR-1", planned_cases=5,
                                  fill_proof_gallons=10)
        assert ctx["bottling_run"]["bottled_proof_gallons"] == 5.9

    def test_cases_bottled_equals_planned(self, api):
        """PRD 3.5: "The run's `cases_bottled` and `cases_available` are both set to
        `planned_cases`".

        Design: Difficulty/combinatorial_formula/bottling_pg_sum_then_round_pinned
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-BR-2", planned_cases=5,
                                  fill_proof_gallons=10)
        assert ctx["bottling_run"]["cases_bottled"] == 5


class TestProductionCascade:
    def test_complete_empties_barrel_and_closes_run(self, api):
        """PRD 3.5: "the barrel moves from `AGING` to `EMPTIED`". PRD 3.5: "the source
        distillation run's `open_barrel_count` is reduced by one; if that brings it to
        zero while the run is `GAUGED`, the run advances from `GAUGED` to `CLOSED`."

        Design: Difficulty/transitive_cascade/bottling_complete_empties_barrel_closes_run_archives_batch
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-BR-3", planned_cases=5,
                                  fill_proof_gallons=10)
        barrel = validate_success(api.get_barrel(ctx["barrel"]["id"], _PM))
        run = validate_success(api.get_distillation_run(ctx["run"]["id"], _PM))
        assert barrel["status"] == "EMPTIED"
        assert run["status"] == "CLOSED"

    def test_complete_archives_mash_batch(self, api):
        """PRD 3.5: "when the run closes, its mash batch advances from `DISTILLED` to
        `ARCHIVED`."

        Design: Difficulty/transitive_cascade/bottling_complete_empties_barrel_closes_run_archives_batch
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-BR-4", planned_cases=5,
                                  fill_proof_gallons=10)
        mash = validate_success(api.get_mash_batch(ctx["mash_id"], _PM))
        assert mash["status"] == "ARCHIVED"


class TestLineContention:
    def _setup(self, api, permit):
        dist = create_distillery(api, dsp_permit_number=permit)
        run, _ = create_gauged_run(api, dist["id"], collected_wine_gallons=60, collected_proof=100)
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=20)
        label = create_approved_label(api, dist["id"])
        get_success_data(
            api.create_bottling_run(
                create_bottling_run_payload(
                    barrel["id"], label["id"], line_id="LINE_A",
                    scheduled_start="2026-06-02T08:00:00Z",
                    scheduled_end="2026-06-02T12:00:00Z", planned_cases=1,
                ),
                _PM,
            )
        )
        return barrel, label

    def test_overlapping_interval_rejected(self, api):
        """PRD 3.5: "if any run that is `SCHEDULED` or `BOTTLING` on the same `line_id`
        already occupies an interval that overlaps the requested `scheduled_start`-to-
        `scheduled_end` window, the request is rejected with `ERR_LINE_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/bottling_line_halfopen_overlap_adjacency_allowed
        """
        barrel, label = self._setup(api, "DSP-BR-5")
        resp = api.create_bottling_run(
            create_bottling_run_payload(
                barrel["id"], label["id"], line_id="LINE_A",
                scheduled_start="2026-06-02T10:00:00Z",
                scheduled_end="2026-06-02T14:00:00Z", planned_cases=1,
            ),
            _PM,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_CONFLICT.value)

    def test_adjacent_interval_allowed(self, api):
        """PRD 3.5: "two runs that merely touch — one ending exactly when the next
        begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/bottling_line_halfopen_overlap_adjacency_allowed
        """
        barrel, label = self._setup(api, "DSP-BR-6")
        data = validate_success(
            api.create_bottling_run(
                create_bottling_run_payload(
                    barrel["id"], label["id"], line_id="LINE_A",
                    scheduled_start="2026-06-02T12:00:00Z",
                    scheduled_end="2026-06-02T16:00:00Z", planned_cases=1,
                ),
                _PM,
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED"


class TestStartLabelGuard:
    def _scheduled_with_submitted_label(self, api, permit):
        dist = create_distillery(api, dsp_permit_number=permit)
        run, _ = create_gauged_run(api, dist["id"])
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=10)
        label = create_submitted_label(api, dist["id"])
        br = get_success_data(
            api.create_bottling_run(
                create_bottling_run_payload(barrel["id"], label["id"], planned_cases=5), _PM
            )
        )
        return br, label

    def test_start_blocked_when_label_not_approved(self, api):
        """PRD 3.5: "the referenced label application must be `APPROVED`, otherwise the
        start is rejected with `ERR_LABEL_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/bottling_start_requires_label_approved
        """
        br, _ = self._scheduled_with_submitted_label(api, "DSP-BR-7")
        resp = api.start_bottling_run(br["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED.value)

    def test_start_permitted_after_label_approved(self, api):
        """PRD 3.5: "Starting a scheduled run advances it from `SCHEDULED` to
        `BOTTLING`." PRD 3.4: "an `APPROVE` outcome advances it from `SUBMITTED` to
        `APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/bottling_start_requires_label_approved
        """
        br, label = self._scheduled_with_submitted_label(api, "DSP-BR-8")
        get_success_data(api.decide_label(label["id"], {"outcome": "APPROVE"}, TEST_USERS["compliance_headers"]))
        data = validate_success(api.start_bottling_run(br["id"], _PM))
        assert data["status"] == "BOTTLING"


class TestStartStateBeatsLabel:
    def _cancelled_run_unapproved_label(self, api, permit):
        dist = create_distillery(api, dsp_permit_number=permit)
        run, _ = create_gauged_run(api, dist["id"])
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=10)
        label = create_submitted_label(api, dist["id"])
        br = get_success_data(
            api.create_bottling_run(
                create_bottling_run_payload(barrel["id"], label["id"], planned_cases=5), _PM
            )
        )
        api.cancel_bottling_run(br["id"], _PM)
        return br

    def test_cancelled_run_start_returns_invalid_state(self, api):
        """PRD 2.1: "then the legality of the requested state transition
        (`ERR_INVALID_STATE`, 409), and finally the operation-specific business rules
        described throughout Section 3." PRD 3.5: "Starting is legal only from
        `SCHEDULED`".

        Design: Difficulty/priority_pair_validation_conflict/bottling_start_state_beats_label_referential
        """
        br = self._cancelled_run_unapproved_label(api, "DSP-BR-9")
        resp = api.start_bottling_run(br["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancelled_run_start_not_label_error(self, api):
        """PRD 2.1: "The server evaluates guard conditions in a fixed order, so that
        the error a caller sees is always the earliest applicable one." State legality
        precedes the operation-specific `ERR_LABEL_NOT_APPROVED` guard.

        Design: Difficulty/priority_pair_validation_conflict/bottling_start_state_beats_label_referential
        """
        br = self._cancelled_run_unapproved_label(api, "DSP-BR-10")
        resp = api.start_bottling_run(br["id"], _PM)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_LABEL_NOT_APPROVED.value
