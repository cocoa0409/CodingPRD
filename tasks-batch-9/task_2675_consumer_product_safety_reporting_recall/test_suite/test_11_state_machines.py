"""Opening states, legal transitions and locked states across the docket."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
    assert_unchanged,
    assert_version_advanced,
)
from test_helpers.test_users import (
    INTAKE_HEADERS,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
)

CHAIN_CLOCK = "2026-03-01T00:00:00Z"
CLASSIFY_CLOCK = "2026-03-05T12:00:00Z"
FILING_CLOCK = "2026-03-13T00:00:00Z"
LATE_ACK_CLOCK = "2026-03-17T00:00:00Z"
REPLAY_CLOCK = "2026-03-23T00:00:00Z"

ANALYSIS_WINDOW = {
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-02-28T00:00:00Z",
}

# Two verified burn reports clear the concentration and risk-index thresholds
# while leaving the incident count one short of the minimum of three.
TWO_VERIFIED_BURN_REPORTS = (
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": (
            "Base plate weld failed; second-degree burn, consumer hospitalised "
            "overnight."
        ),
        "injury_class": "HOSPITALIZATION",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "RETAILER",
        "incident_date": "2026-01-20T00:00:00Z",
        "narrative": (
            "Store return: unit overheated and scorched the counter; consumer "
            "treated at urgent care."
        ),
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
)

UNTRIAGED_REPORT = {
    "report_channel": "WEB_FORM",
    "incident_date": "2026-02-10T00:00:00Z",
    "narrative": "Web form: consumer reports a smell of hot plastic, no injury yet.",
}


def _assert_instant(actual, expected_iso):
    """A stored timestamp names the expected instant, fractional digits aside."""
    assert isinstance(actual, str), f"expected a timestamp string, got {actual!r}"
    assert actual.startswith(expected_iso[:19]), (
        f"expected the instant {expected_iso}, got {actual}"
    )


def _dispose_incident(api, incident_id, **overrides):
    """Dispose of one incident as a duplicate or as requiring no action."""
    return validate_success(
        api.dispose_incident(
            incident_id, f.dispose_payload(**overrides), headers=INTAKE_HEADERS
        )
    )


def _incident_rows(api, **params):
    """The incident rows matching one set of collection filters."""
    rows, meta = validate_paginated(
        api.list_incidents(params, headers=OFFICER_HEADERS)
    )
    return rows, meta


def _pattern_rows(api, **params):
    """The hazard-pattern rows matching one set of collection filters."""
    rows, meta = validate_paginated(
        api.list_hazard_patterns(params, headers=OFFICER_HEADERS)
    )
    return rows, meta


class TestDeclaredInitialStates:
    """Every machine in the docket opens on its own declared first value."""

    def test_intake_analysis_evaluation_and_report_open_at_their_first_state(
        self, api
    ):
        """A fresh incident, pattern, evaluation and report each open unadvanced.

        The contract states: "A new report lands in `INTAKE` status with no injury
        classification at all: `injury_class` and `hazard_code` are both null,
        `injury_verified` is false, `severity_weight` is 0.00, `classified_at` and
        `escalation_deadline_at` are null, and both `hazard_pattern_id` and
        `duplicate_of_incident_id` are null." "The new pattern is created in
        `pattern_status` `ANALYZED`; the enumeration is `ANALYZED`, `CONFIRMED`,
        `DISMISSED` and `SUPERSEDED`, of which the last two are terminal." "Its
        `status` starts at `OPEN` and moves through `OPEN`, `IN_REVIEW` and then
        one of the two terminal outcomes `REPORTABLE` or `NOT_REPORTABLE`." "The
        new report is created in `DRAFT` with `days_late` at 0,
        `late_surcharge_cents` at 0, and `submitted_at` and `reviewed_at` both
        null."

        Design: Corner/state_machines/all_twelve_machines_open_in_their_declared_initial_state
        """
        fx.set_clock(api, CHAIN_CLOCK)
        model = fx.create_product_model(api)
        fx.canonical_incident_set(api, model["id"])

        model = fx.get_product_model(api, model["id"])
        pattern = fx.create_pattern(
            api, model["id"], model["version"], **ANALYSIS_WINDOW
        )
        assert_field_values(pattern, pattern_status="ANALYZED")

        fx.adjudicate_pattern(api, pattern["id"], "CONFIRMED")
        evaluation = fx.create_evaluation(api, pattern["id"])
        assert_field_values(evaluation, status="OPEN", escalation_breached=False)
        assert_fields_null(
            evaluation,
            "review_started_at",
            "determined_at",
            "report_due_at",
            "defect_score",
            "risk_score",
            "determination_note",
        )

        fx.begin_review(api, evaluation["id"])
        fx.determine_evaluation(api, evaluation["id"])
        report = fx.create_section_report(api, evaluation["id"])
        assert_field_values(
            report, status="DRAFT", days_late=0, late_surcharge_cents=0
        )
        assert_fields_null(report, "submitted_at", "reviewed_at")

        fresh = fx.create_incident(api, model["id"], **UNTRIAGED_REPORT)
        assert_field_values(fresh, status="INTAKE", injury_verified=False)
        assert_decimal_equals(fresh["severity_weight"], "0.00")
        assert_fields_null(
            fresh,
            "injury_class",
            "hazard_code",
            "classified_at",
            "escalation_deadline_at",
            "hazard_pattern_id",
            "duplicate_of_incident_id",
        )

    def test_the_recall_row_opens_both_of_its_dimensions_independently(self, api):
        """The plan axis opens at DRAFT and the outreach axis at NOT_STARTED.

        The contract states: "A new recall is created with `plan_status` at
        `DRAFT`, `notification_status` at `NOT_STARTED`, `units_corrected` at 0,
        `units_outstanding` initialised to `units_in_commerce`,
        `effectiveness_flag` at `PENDING`, and `stop_sale_effective_at`,
        `submitted_by_user_id` and `last_accepted_period_end` all null."

        Design: Corner/state_machines/all_twelve_machines_open_in_their_declared_initial_state
        """
        env = fx.accepted_report_env(api)
        recall = fx.create_recall(api, env["report_id"], units_in_commerce=100)

        assert_field_values(
            recall,
            plan_status="DRAFT",
            notification_status="NOT_STARTED",
            units_in_commerce=100,
            units_corrected=0,
            units_outstanding=100,
            effectiveness_flag="PENDING",
        )
        assert_fields_null(
            recall,
            "stop_sale_effective_at",
            "submitted_by_user_id",
            "last_accepted_period_end",
        )

    def test_notification_notice_and_penalty_rows_open_at_their_first_state(
        self, api
    ):
        """Enrolment, notice scheduling and docketing all open unadvanced.

        The contract states: "a new notification is always created in `PENDING`
        with `stop_sale_required` false and with `issued_at`, `ack_due_at`,
        `acknowledged_at`, `verified_at` and `units_on_shelf_reported` all null."
        "Each notice is created in `status` `SCHEDULED` with `released_at` null,
        and its `status` runs `SCHEDULED → RELEASED` and then, when overtaken,
        `RELEASED → SUPERSEDED`, which is terminal." "A new case is created in
        `status` `ASSESSMENT_OPEN`, with `reserved_cents` at 0 and
        `available_cents` equal to `assessed_penalty_cents`, so the conserved
        reserve identity holds from the first instant."

        Design: Corner/state_machines/all_twelve_machines_open_in_their_declared_initial_state
        """
        env = fx.draft_recall_env(api)

        assert_field_values(
            env["notification"], status="PENDING", stop_sale_required=False
        )
        assert_fields_null(
            env["notification"],
            "issued_at",
            "ack_due_at",
            "acknowledged_at",
            "verified_at",
            "units_on_shelf_reported",
        )

        assert_field_values(env["notice"], status="SCHEDULED", channel="DIRECT_NOTICE")
        assert_fields_null(env["notice"], "released_at")

        case = fx.create_penalty_case(api, env["report_id"], violation_count=4)
        assert_field_values(case, status="ASSESSMENT_OPEN", reserved_cents=0)
        assert case["available_cents"] == case["assessed_penalty_cents"], case

    def test_audit_visit_claim_and_progress_report_open_at_their_first_state(
        self, api
    ):
        """The three rows gated behind approval each open unadvanced too.

        The contract states: "A new visit is created with `status` `SCHEDULED`,
        `verdict` `PENDING`, and `shelf_units_found` and `completed_at` both null;
        `status` runs `SCHEDULED → COMPLETED` and `verdict` is one of `PENDING`,
        `PASS` and `FAIL`." "A new claim is created in `status` `SUBMITTED` with
        `fulfilled_at` and `voided_at` null; its `status` runs through
        `SUBMITTED`, `APPROVED`, `FULFILLED` and the terminal `VOID`." "The report
        is created in `status` `DRAFT` with `assessment` at `PENDING`,
        `effectiveness_rate` at 0, `units_corrected_in_period` at 0,
        `cumulative_units_corrected` at 0, and `submitted_at` and `accepted_at`
        null."

        Design: Corner/state_machines/all_twelve_machines_open_in_their_declared_initial_state
        """
        env = fx.approved_recall_env(api)

        visit = fx.create_audit_visit(api, env["notification_id"])
        assert_field_values(visit, status="SCHEDULED", verdict="PENDING")
        assert_fields_null(visit, "shelf_units_found", "completed_at")

        claim = fx.create_claim(api, env["recall_id"], remedy_type="REFUND", quantity=10)
        assert_field_values(claim, status="SUBMITTED")
        assert_fields_null(claim, "fulfilled_at", "voided_at")

        report = fx.create_progress_report(api, env["recall_id"])
        assert_field_values(
            report,
            status="DRAFT",
            assessment="PENDING",
            units_corrected_in_period=0,
            cumulative_units_corrected=0,
        )
        assert_decimal_equals(report["effectiveness_rate"], "0.00")
        assert_fields_null(report, "submitted_at", "accepted_at")


class TestClassificationAdvancesTheIntakeReport:
    """The forward classify transition, its clock stamp and its frozen weight."""

    def test_classifying_an_intake_report_stamps_the_logical_clock(self, api):
        """Classification advances INTAKE to CLASSIFIED at the logical clock.

        The contract states: "The operation stamps `classified_at` with the
        logical clock and recomputes the incident's `severity_weight`. From
        `INTAKE` it advances the report to `CLASSIFIED`". The clock itself is a
        controllable input: "The service holds a **logical UTC clock**, and every
        deadline, escalation window, embargo, audit window, reporting period and
        lateness computation reads that clock — never the host wall clock."

        Design: Corner/state_machines/classification_moves_intake_to_classified_and_stamps_the_clock
        """
        fx.set_clock(api, CHAIN_CLOCK)
        model = fx.create_product_model(api)
        incident = fx.create_incident(
            api,
            model["id"],
            report_channel="MEDICAL_EXAMINER",
            incident_date="2026-01-12T00:00:00Z",
            narrative="Base plate weld failure, overnight hospitalisation.",
        )
        assert_field_values(incident, status="INTAKE", version=1)

        fx.set_clock(api, CLASSIFY_CLOCK)
        classified = fx.classify_incident(
            api,
            incident["id"],
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
            injury_verified=True,
        )

        assert_field_values(
            classified,
            status="CLASSIFIED",
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
            injury_verified=True,
            version=2,
        )
        _assert_instant(classified["classified_at"], CLASSIFY_CLOCK)
        assert not classified["classified_at"].startswith(CHAIN_CLOCK[:19]), (
            "classified_at was stamped from the intake clock rather than the "
            "clock reading at classification time"
        )
        assert_decimal_equals(classified["severity_weight"], "30.00")
        assert_fields_null(classified, "hazard_pattern_id")


class TestConfirmabilityGateOnAdjudication:
    """Confirming a pattern reads the flag the analysis froze."""

    def test_a_pattern_one_incident_short_of_the_minimum_cannot_be_confirmed(
        self, api
    ):
        """Two qualifying incidents fail the count leg and refuse confirmation.

        The contract states: "Finally `pattern_confirmed` is true only when all
        three of the following hold at once: `incident_count` is at least 3,
        `concentration_ratio` is at least 0.6000, and `risk_index` is at least
        10.00." Confirmation reads exactly that stored flag: "it requires the
        pattern's stored `pattern_confirmed` to be true, and a pattern that failed
        any of the three confirmability thresholds is refused with
        `ERR_PATTERN_NOT_CONFIRMABLE` (HTTP 422)."

        Design: Corner/state_machines/adjudicating_confirmed_requires_the_stored_confirmability_flag
        """
        env = fx.analyzed_pattern_env(
            api, incidents=TWO_VERIFIED_BURN_REPORTS, **ANALYSIS_WINDOW
        )
        pattern = env["pattern"]

        assert_field_values(pattern, incident_count=2, pattern_confirmed=False)
        assert_decimal_equals(pattern["severity_sum"], "39.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(pattern["risk_index"], "59.40")

        validate_error(
            api.adjudicate_hazard_pattern(
                env["pattern_id"],
                f.adjudicate_payload(decision="CONFIRMED"),
                headers=OFFICER_HEADERS,
            ),
            "ERR_PATTERN_NOT_CONFIRMABLE",
            422,
        )

        after = fx.get_pattern(api, env["pattern_id"])
        assert_field_values(after, pattern_status="ANALYZED")
        assert_unchanged(pattern, after, "version", "incident_count", "risk_index")

    def test_a_pattern_clearing_all_three_thresholds_confirms(self, api):
        """The third qualifying incident is what makes the same call legal.

        The contract states: "A `decision` of `CONFIRMED` moves the pattern
        `ANALYZED → CONFIRMED` and makes it eligible for a reportability
        evaluation; it requires the pattern's stored `pattern_confirmed` to be
        true". "This branch touches no incident and leaves the model's
        `hazard_posture` exactly where it was."

        Design: Corner/state_machines/adjudicating_confirmed_requires_the_stored_confirmability_flag
        """
        env = fx.analyzed_pattern_env(api, **ANALYSIS_WINDOW)
        pattern = env["pattern"]

        assert_field_values(pattern, incident_count=3, pattern_confirmed=True)
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(pattern["risk_index"], "63.90")

        confirmed = fx.adjudicate_pattern(api, env["pattern_id"], "CONFIRMED")

        assert_field_values(confirmed, pattern_status="CONFIRMED")
        assert_version_advanced(pattern, confirmed)
        model = fx.get_product_model(api, env["model_id"])
        assert_field_values(model, hazard_posture="MONITORED")


class TestPatternCreationSweepsItsNeighbours:
    """A second analysis re-points the cluster and retires the first pattern."""

    def _model_with_a_second_analysis(self, api):
        """One model analysed twice, the second run over the same window."""
        env = fx.analyzed_pattern_env(api, **ANALYSIS_WINDOW)
        first = env["pattern"]
        model_after_first = fx.get_product_model(api, env["model_id"])
        second = fx.create_pattern(
            api,
            env["model_id"],
            model_after_first["version"],
            analysis_basis="FINAL",
            **ANALYSIS_WINDOW,
        )
        return env, first, model_after_first, second

    def test_the_new_analysis_repoints_every_clustered_incident_onto_itself(
        self, api
    ):
        """All three incidents leave the first pattern for the second.

        The contract states: "Every qualifying incident that was `CLASSIFIED` is
        flipped to `CLUSTERED` with its `hazard_pattern_id` set to the new
        pattern, processed in `created_at` ascending order; a qualifying incident
        that was already `CLUSTERED` to an older pattern is re-pointed to the new
        one, staying in `CLUSTERED`." Those sibling effects are observable only
        through the collections: "no creation response ever contains the sibling
        rows a cascade touched."

        Design: Corner/state_machines/pattern_creation_clusters_qualifying_incidents_and_supersedes_the_prior_pattern
        """
        env, first, _model_after_first, second = self._model_with_a_second_analysis(api)

        for incident in env["incidents"]:
            row = fx.get_incident(api, incident["id"])
            assert_field_values(
                row, status="CLUSTERED", hazard_pattern_id=second["id"]
            )

        orphaned, orphan_meta = _incident_rows(api, hazard_pattern_id=first["id"])
        assert orphaned == [], (
            f"incidents still reference the superseded pattern: {orphaned}"
        )
        assert orphan_meta["total_count"] == 0, orphan_meta

        clustered, clustered_meta = _incident_rows(
            api, hazard_pattern_id=second["id"], status="CLUSTERED"
        )
        assert clustered_meta["total_count"] == 3, clustered_meta
        assert {row["id"] for row in clustered} == {
            incident["id"] for incident in env["incidents"]
        }

    def test_the_new_analysis_supersedes_the_prior_pattern_and_bumps_the_model(
        self, api
    ):
        """The first pattern goes terminal and the model's version advances.

        The contract states: "Every other hazard pattern on the same product
        model whose `pattern_status` is `ANALYZED` or `CONFIRMED` is flipped to
        `SUPERSEDED`. The product model's `version` is incremented by 1 — which is
        why the next analysis of the same model needs a fresh
        `expected_product_model_version`."

        Design: Corner/state_machines/pattern_creation_clusters_qualifying_incidents_and_supersedes_the_prior_pattern
        """
        env, first, model_after_first, second = self._model_with_a_second_analysis(api)

        assert_field_values(second, pattern_status="ANALYZED", incident_count=3)

        retired = fx.get_pattern(api, first["id"])
        assert_field_values(retired, pattern_status="SUPERSEDED")
        assert_version_advanced(first, retired)

        superseded, superseded_meta = _pattern_rows(
            api, product_model_id=env["model_id"], pattern_status="SUPERSEDED"
        )
        assert superseded_meta["total_count"] == 1, superseded_meta
        assert superseded[0]["id"] == first["id"], superseded

        model_after_second = fx.get_product_model(api, env["model_id"])
        assert_version_advanced(model_after_first, model_after_second)


class TestTerminalRowsRejectFurtherTriggers:
    """Four machines whose terminal states were reached by four routes."""

    def test_a_merged_duplicate_incident_refuses_classification(self, api):
        """A report folded into a primary can no longer be classified.

        The contract states: "The same error answers any classification attempt on
        a `CLUSTERED` or `ESCALATED` report, or on one already in a terminal
        state." The terminal states are named too: "An incident's `status` moves
        through the enumeration `INTAKE`, `CLASSIFIED`, `CLUSTERED`, `ESCALATED`,
        `MERGED_DUPLICATE` and `CLOSED_NO_ACTION`, of which the last two are
        terminal."

        Design: Corner/state_machines/terminal_rows_reject_every_further_trigger_across_five_machines
        """
        fx.set_clock(api, CHAIN_CLOCK)
        model = fx.create_product_model(api)
        primary = fx.classified_incident(api, model["id"])
        duplicate = fx.create_incident(
            api,
            model["id"],
            report_channel="WEB_FORM",
            incident_date="2026-02-11T00:00:00Z",
            narrative="Second-hand retelling of the January hospitalisation.",
        )
        merged = _dispose_incident(
            api,
            duplicate["id"],
            disposition="MERGED_DUPLICATE",
            duplicate_of_incident_id=primary["id"],
        )
        assert_field_values(
            merged,
            status="MERGED_DUPLICATE",
            duplicate_of_incident_id=primary["id"],
        )

        validate_error(
            api.classify_incident(
                duplicate["id"],
                f.classify_payload(
                    injury_class="FIRST_AID",
                    hazard_code="BURN",
                    injury_verified=False,
                ),
                headers=INTAKE_HEADERS,
            ),
            "ERR_INCIDENT_STATE_INVALID",
            409,
        )

        after = fx.get_incident(api, duplicate["id"])
        assert_field_values(after, status="MERGED_DUPLICATE")
        assert_unchanged(merged, after, "version", "injury_class", "severity_weight")

    def test_a_dismissed_hazard_pattern_refuses_recomputation(self, api):
        """A dismissed analysis is closed to any further recompute.

        The contract states: "Recomputation requires the pattern to be in
        `ANALYZED` — any other status draws `ERR_PATTERN_STATE_INVALID`". The
        dismissal itself is terminal: "A `decision` of `DISMISSED` moves the
        pattern `ANALYZED → DISMISSED` and releases the whole cluster".

        Design: Corner/state_machines/terminal_rows_reject_every_further_trigger_across_five_machines
        """
        fx.set_clock(api, CHAIN_CLOCK)
        model = fx.create_product_model(api)
        pattern = fx.create_pattern(
            api, model["id"], model["version"], **ANALYSIS_WINDOW
        )
        dismissed = fx.adjudicate_pattern(api, pattern["id"], "DISMISSED")
        assert_field_values(dismissed, pattern_status="DISMISSED")

        validate_error(
            api.recompute_hazard_pattern(
                pattern["id"], {"analysis_basis": "FINAL"}, headers=OFFICER_HEADERS
            ),
            "ERR_PATTERN_STATE_INVALID",
            409,
        )

        after = fx.get_pattern(api, pattern["id"])
        assert_field_values(after, pattern_status="DISMISSED")
        assert_unchanged(dismissed, after, "version", "analysis_basis", "risk_index")

    def test_an_accepted_statutory_report_refuses_revision(self, api):
        """An accepted filing cannot be pulled back into draft.

        The contract states: "A report in any other status cannot be revised and
        draws `ERR_SECTION_REPORT_STATE_INVALID`." Acceptance is the terminal
        value: "Its `status` moves among `DRAFT`, `SUBMITTED`, `ACCEPTED` and
        `RETURNED_FOR_INFO`, with `ACCEPTED` the only terminal value."

        Design: Corner/state_machines/terminal_rows_reject_every_further_trigger_across_five_machines
        """
        env = fx.accepted_report_env(api)
        accepted = env["report"]
        assert_field_values(accepted, status="ACCEPTED")

        validate_error(
            api.revise_section_report(
                env["report_id"],
                {"corrective_action_summary": "Second thoughts about the remedy."},
                headers=OFFICER_HEADERS,
            ),
            "ERR_SECTION_REPORT_STATE_INVALID",
            409,
        )

        after = fx.get_section_report(api, env["report_id"])
        assert_field_values(after, status="ACCEPTED")
        assert_unchanged(
            accepted, after, "version", "submitted_at", "corrective_action_summary"
        )
        model = fx.get_product_model(api, env["model_id"])
        assert_field_values(model, hazard_posture="RESTRICTED")

    def test_a_reportable_evaluation_refuses_a_second_determination(self, api):
        """A recorded determination cannot be walked back to no-action.

        The contract states: "The evaluation must be `IN_REVIEW`, otherwise
        `ERR_EVALUATION_STATE_INVALID`." Nothing about the docket relaxes on a
        rejected call: "Evaluation stops at the first failure and no later rule is
        consulted."

        Design: Corner/state_machines/terminal_rows_reject_every_further_trigger_across_five_machines
        """
        env = fx.determined_evaluation_env(api)
        determined = env["evaluation"]
        assert_field_values(determined, status="REPORTABLE", defect_score=8)
        _assert_instant(determined["report_due_at"], "2026-03-11T00:00:00Z")

        validate_error(
            api.determine_evaluation(
                env["evaluation_id"],
                f.determination_payload(
                    determination="NOT_REPORTABLE",
                    defect_score=1,
                    risk_score=1,
                    determination_note="Trying to walk the determination back.",
                ),
                headers=OFFICER_HEADERS,
            ),
            "ERR_EVALUATION_STATE_INVALID",
            409,
        )

        after = fx.get_evaluation(api, env["evaluation_id"])
        assert_field_values(after, status="REPORTABLE", defect_score=8, risk_score=7)
        assert_unchanged(determined, after, "version", "determined_at", "report_due_at")
        model = fx.get_product_model(api, env["model_id"])
        assert_field_values(model, hazard_posture="FROZEN")


class TestReplayedStatutoryFiling:
    """A second submit of the same report is refused, not re-run."""

    def test_the_second_submit_is_refused_and_the_first_surcharge_survives(
        self, api
    ):
        """Replaying submit ten days later neither re-stamps nor re-scores.

        The contract states: "A report not in `DRAFT` cannot be filed and draws
        `ERR_SECTION_REPORT_STATE_INVALID`." That matters because "Every action
        operation in this system is a state transition and none of them are
        idempotent: re-firing the same trigger on a row that has already advanced
        returns that entity's state error at step 9 rather than succeeding
        silently", and because "Lateness is measured against the immutable
        `report_due_at` of the report's evaluation, reached through
        `reportability_evaluation_id`."

        Design: Corner/state_machines/submitting_the_same_section_report_twice_fails_on_the_second_attempt
        """
        env = fx.submitted_report_env(api)
        submitted = env["report"]

        assert_field_values(
            submitted, status="SUBMITTED", days_late=2, late_surcharge_cents=500000
        )
        _assert_instant(submitted["submitted_at"], FILING_CLOCK)

        fx.set_clock(api, REPLAY_CLOCK)
        validate_error(
            api.submit_section_report(env["report_id"], headers=OFFICER_HEADERS),
            "ERR_SECTION_REPORT_STATE_INVALID",
            409,
        )

        after = fx.get_section_report(api, env["report_id"])
        assert_field_values(
            after, status="SUBMITTED", days_late=2, late_surcharge_cents=500000
        )
        _assert_instant(after["submitted_at"], FILING_CLOCK)
        assert_unchanged(submitted, after, "version", "submitted_at")


class TestClassifyIsUnavailableFromLockedStates:
    """Two non-terminal states from which reclassification is still refused."""

    def test_a_clustered_incident_cannot_be_reclassified(self, api):
        """An incident owned by an analysis refuses the classify self-loop.

        The contract states: "The self-loop is only legal while the incident's
        `hazard_pattern_id` is null: once a hazard pattern has claimed the report,
        it is owned by that analysis and may not be reclassified, and the attempt
        is refused with `ERR_INCIDENT_STATE_INVALID`." The frozen snapshot is the
        reason: "The severity weight itself combines three factors and is frozen
        at classification time — it is never recomputed because the parent product
        model or some hazard pattern changed."

        Design: Corner/state_machines/classify_is_unavailable_from_clustered_and_escalated
        """
        env = fx.confirmed_pattern_env(api, **ANALYSIS_WINDOW)
        clustered = fx.get_incident(api, env["incidents"][0]["id"])
        assert_field_values(
            clustered, status="CLUSTERED", hazard_pattern_id=env["pattern_id"]
        )

        validate_error(
            api.classify_incident(
                clustered["id"],
                f.classify_payload(
                    injury_class="FIRST_AID",
                    hazard_code="LACERATION",
                    injury_verified=False,
                ),
                headers=INTAKE_HEADERS,
            ),
            "ERR_INCIDENT_STATE_INVALID",
            409,
        )

        after = fx.get_incident(api, clustered["id"])
        assert_field_values(
            after,
            status="CLUSTERED",
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
        )
        assert_decimal_equals(after["severity_weight"], "30.00")
        assert_unchanged(clustered, after, "version", "classified_at")

        pattern = fx.get_pattern(api, env["pattern_id"])
        assert_decimal_equals(pattern["risk_index"], "63.90")

    def test_an_escalated_incident_cannot_be_reclassified(self, api):
        """An escalated incident refuses the same trigger from its own state.

        The contract states: "The same error answers any classification attempt on
        a `CLUSTERED` or `ESCALATED` report, or on one already in a terminal
        state." The escalation itself is the determination's work: "every incident
        whose `hazard_pattern_id` equals this evaluation's pattern and whose
        `status` is `CLUSTERED` is flipped `CLUSTERED → ESCALATED` with its
        `escalation_deadline_at` set to `determined_at` plus 120 hours (five
        days)".

        Design: Corner/state_machines/classify_is_unavailable_from_clustered_and_escalated
        """
        env = fx.determined_evaluation_env(api, **ANALYSIS_WINDOW)
        escalated = fx.get_incident(api, env["incidents"][0]["id"])
        assert_field_values(escalated, status="ESCALATED")
        _assert_instant(escalated["escalation_deadline_at"], "2026-03-06T00:00:00Z")

        validate_error(
            api.classify_incident(
                escalated["id"],
                f.classify_payload(
                    injury_class="FIRST_AID",
                    hazard_code="LACERATION",
                    injury_verified=False,
                ),
                headers=INTAKE_HEADERS,
            ),
            "ERR_INCIDENT_STATE_INVALID",
            409,
        )

        after = fx.get_incident(api, escalated["id"])
        assert_field_values(
            after,
            status="ESCALATED",
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
        )
        assert_decimal_equals(after["severity_weight"], "30.00")
        assert_unchanged(
            escalated, after, "version", "escalation_deadline_at", "classified_at"
        )


class TestRecallDimensionsMoveIndependently:
    """The plan axis and the outreach axis on one recall row."""

    def test_submitting_the_plan_leaves_the_outreach_axis_at_not_started(self, api):
        """The paperwork axis advances alone, then approval moves both.

        The contract states: "A recall carries **two independent state dimensions
        on the same row**, and they do not move in lockstep." "Submitting the plan
        advances `plan_status` `DRAFT → SUBMITTED` and stores the acting
        `X-User-ID` as `submitted_by_user_id`." Only approval drives the second
        axis: "A follow-on effect of that link moves the recall's
        `notification_status` `NOT_STARTED → IN_PROGRESS`, but only when at least
        one notification actually flipped".

        Design: Corner/state_machines/recall_plan_status_and_notification_status_advance_on_independent_axes
        """
        env = fx.draft_recall_env(api)

        submitted = fx.submit_plan(api, env["recall_id"])
        assert_field_values(
            submitted,
            plan_status="SUBMITTED",
            notification_status="NOT_STARTED",
            submitted_by_user_id=OFFICER_USER_ID,
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="PENDING"
        )
        assert_field_values(fx.get_notice(api, env["notice_id"]), status="SCHEDULED")

        approved = fx.approve_plan(api, env["recall_id"])
        assert_field_values(
            approved, plan_status="APPROVED", notification_status="IN_PROGRESS"
        )
        assert_version_advanced(submitted, approved)
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="ISSUED"
        )
        assert_field_values(fx.get_notice(api, env["notice_id"]), status="SCHEDULED")

    def test_approval_without_a_pending_notification_moves_only_the_plan_axis(
        self, api
    ):
        """With nothing to issue, the outreach axis stays at NOT_STARTED.

        The contract states: "when the recall had no `PENDING` notification at
        approval time the notification dimension stays at `NOT_STARTED` while
        `plan_status` still advances to `APPROVED`, which is the clearest
        demonstration that the two dimensions are independent."

        Design: Corner/state_machines/recall_plan_status_and_notification_status_advance_on_independent_axes
        """
        env = fx.draft_recall_env(api, enroll_retailer=False)

        submitted = fx.submit_plan(api, env["recall_id"])
        assert_field_values(
            submitted, plan_status="SUBMITTED", notification_status="NOT_STARTED"
        )

        approved = fx.approve_plan(api, env["recall_id"])
        assert_field_values(
            approved, plan_status="APPROVED", notification_status="NOT_STARTED"
        )
        _assert_instant(approved["stop_sale_effective_at"], FILING_CLOCK)


class TestLateAcknowledgementCompensatesTheSweep:
    """The sweep records a delinquency; the late acknowledgement repairs it."""

    def _swept_into_delinquency(self, api):
        """An approved recall swept one day after its acknowledgement deadline."""
        env = fx.approved_recall_env(api)
        _assert_instant(env["notification"]["ack_due_at"], "2026-03-16T00:00:00Z")
        assert_field_values(
            env["retailer"], compliance_posture="STOP_SALE_ACTIVE", open_stop_sale_count=1
        )

        fx.set_clock(api, LATE_ACK_CLOCK)
        env["swept_recall"] = fx.compliance_sweep(api, env["recall_id"])
        return env

    def test_the_sweep_marks_the_notification_the_retailer_and_the_recall(self, api):
        """One overdue notification moves three rows in one scan.

        The contract states: "Every notification on the recall that is still
        `ISSUED` and whose `ack_due_at` the logical clock has **strictly** passed
        is flipped `ISSUED → DELINQUENT`, processed in `created_at` ascending
        order". "For each notification flipped, the owning retailer's
        `delinquent_count` is incremented by 1 and its `compliance_posture` is set
        to `DELINQUENT`. When at least one notification was flipped, the recall's
        `notification_status` moves `IN_PROGRESS → DEFICIENT`."

        Design: Corner/state_machines/late_acknowledgement_compensates_the_delinquency_sweep_on_both_entities
        """
        env = self._swept_into_delinquency(api)

        assert_field_values(
            env["swept_recall"],
            notification_status="DEFICIENT",
            plan_status="APPROVED",
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="DELINQUENT"
        )
        assert_field_values(
            fx.get_retailer(api, env["retailer_id"]),
            compliance_posture="DELINQUENT",
            delinquent_count=1,
            open_stop_sale_count=1,
        )

    def test_the_late_acknowledgement_repairs_both_rows_but_keeps_the_counter(
        self, api
    ):
        """Repair restores the stop-sale posture and the outreach axis only.

        The contract states: "When the notification was `DELINQUENT`,
        acknowledgement also repairs the retailer's posture: `compliance_posture`
        returns to `STOP_SALE_ACTIVE` when that retailer's `open_stop_sale_count`
        is at least 1, and to `CLEAR` otherwise." "Acknowledgement does *not*
        reduce `delinquent_count` — that counter is monotonic, recording how many
        times this retailer has ever been swept into delinquency, and it is never
        decremented." "Finally, when the acknowledgement cleared the last
        `DELINQUENT` notification on the recall, the recall's
        `notification_status` moves `DEFICIENT → IN_PROGRESS`".

        Design: Corner/state_machines/late_acknowledgement_compensates_the_delinquency_sweep_on_both_entities
        """
        env = self._swept_into_delinquency(api)

        acknowledged = fx.acknowledge_as_retailer(
            api,
            env["notification_id"],
            env["retailer_id"],
            units_on_shelf_reported=4,
        )
        assert_field_values(
            acknowledged, status="ACKNOWLEDGED", units_on_shelf_reported=4
        )
        _assert_instant(acknowledged["acknowledged_at"], LATE_ACK_CLOCK)

        retailer = fx.get_retailer(api, env["retailer_id"])
        assert_field_values(
            retailer,
            compliance_posture="STOP_SALE_ACTIVE",
            open_stop_sale_count=1,
            delinquent_count=1,
            verified_removal_count=0,
        )

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, notification_status="IN_PROGRESS", plan_status="APPROVED"
        )
