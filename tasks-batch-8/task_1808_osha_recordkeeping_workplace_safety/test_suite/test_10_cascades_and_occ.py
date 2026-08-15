"""Cross-entity cascades, clock sweeps, and optimistic concurrency."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_day_entry,
    assert_version_incremented,
    create_case,
    create_classified_case,
    create_corrective_action,
    create_citation,
    create_inspection,
    create_summary,
    fresh_summary_version,
    get_case,
    get_establishment,
    get_success_data,
    get_summary,
    prepare_summary,
    reclassify_case,
    set_clock,
    setup_org,
    setup_year_hour_logs,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORDINATOR, OFFICER


class TestOptimisticConcurrency:
    def test_occ_stale_case_version_on_classify(self, api):
        """PRD §2.8: "Classifying a case (the initial determination or a
        re-determination) requires the request to carry
        `expected_case_version` holding the case `version` the client last
        observed; if another writer has advanced the case's version since the
        client last read it, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because the client's view of the case predates that
        writer's update."
        PRD §2.5: "Every explicit case operation — classification,
        reclassification, day-count closure, and finalization — increments the
        case's `version` by exactly one"

        Design: Corner/cross_cutting_layers/occ_stale_case_version_on_classify
        """
        _, establishment, employee = setup_org(fein="16-0000035",
                                               site_name="OCC Site")
        set_clock("2026-08-01T12:00:00Z")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-01T10:00:00Z", description="OCC")
        original_version = case["version"]

        classified = validate_success(api.classify_case(
            case["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": original_version},
            OFFICER), 200)
        assert_version_incremented(classified["version"], original_version)

        # Reach RECLASSIFIED, where classification is a legal transition, so
        # that only the stale version can fail the second classify.
        add_day_entry(case["id"], "RESTRICTED", "2026-08-02", "2026-08-04")
        reclassified = reclassify_case(case["id"])
        assert reclassified["status"] == "RECLASSIFIED"

        resp = api.classify_case(
            case["id"],
            {"classification": "DAYS_AWAY",
             "expected_case_version": original_version},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_summary_version_on_certify(self, api):
        """PRD §2.8: "Certifying an annual summary likewise requires
        `expected_summary_version`: a case mutation after preparation bounces
        the summary back to `DRAFT` and advances its version, so a client
        certifying against a pre-mutation version observes exactly this
        stale-version rejection, also `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.5: "summary certification increments the summary's `version`
        by exactly one."

        Design: Corner/cross_cutting_layers/occ_stale_summary_version_on_certify
        """
        _, establishment, _ = setup_org(fein="17-0000036",
                                        site_name="OCC2 Site")
        setup_year_hour_logs(establishment["id"], 2026)
        summary = create_summary(establishment["id"], 2026)
        create_time_version = summary["version"]
        prepare_summary(summary["id"])

        resp = api.certify_summary(
            summary["id"],
            {"expected_summary_version": create_time_version},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestClassifyCascade:
    def _prepared_summary_and_pending_case(self, fein):
        """Two recordable cases (Jan/Feb), twelve approved logs, a PREPARED
        summary, and a third case awaiting classification."""
        _, establishment, employee = setup_org(fein=fein, site_name="Fab 4",
                                               naics_code="333111",
                                               state_code="IA")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-01-20T10:00:00Z",
                               clock_iso="2026-01-20T12:00:00Z",
                               description="Burn", body_part="arm")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-02-14T10:00:00Z",
                               clock_iso="2026-02-14T12:00:00Z",
                               description="Sprain", body_part="knee")
        setup_year_hour_logs(establishment["id"], 2026)
        set_clock("2026-07-01T00:00:00Z")
        summary = create_summary(establishment["id"], 2026)
        prepared = prepare_summary(summary["id"])

        set_clock("2026-08-01T12:00:00Z")
        pending = create_case(establishment["id"], employee["id"],
                              "2026-08-01T10:00:00Z",
                              description="Foreign body eye",
                              body_part="eye")
        return establishment, prepared, pending

    def test_classify_bounces_prepared_summary_to_draft(self, api):
        """PRD §3.7: "While the summary sits in `PREPARED` these rates are
        live reflections of the underlying cases: any case mutation for the
        year — a classification, a reclassification, or a day-entry change —
        bounces the summary back to `DRAFT`, clearing `prepared_by` and
        discarding the provisional figures."
        PRD §3.7: "stores provisional rates: `trir` as the recordable-case
        count multiplied by 200,000 and divided by the total hours worked"

        Design: Difficulty/transitive_cascade/case_classify_cascades_summary_bounce_and_rate_shift
        """
        _, prepared, pending = self._prepared_summary_and_pending_case(
            "55-9090909")
        assert prepared["status"] == "PREPARED"
        assert prepared["trir"] == pytest.approx(6.7, abs=0.01), (
            "Provisional: 2 x 200000 / 60000 = 6.67 -> 6.7")

        classified = validate_success(api.classify_case(
            pending["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": pending["version"]},
            OFFICER), 200)
        assert classified["status"] == "RECORDABLE"

        bounced = get_summary(prepared["id"])
        assert bounced["status"] == "DRAFT", (
            "The case mutation bounces the PREPARED summary")

    def test_bounce_discards_preparer_and_provisional_rates(self, api):
        """PRD §3.7: "any case mutation for the year — a classification, a
        reclassification, or a day-entry change — bounces the summary back to
        `DRAFT`, clearing `prepared_by` and discarding the provisional
        figures."

        Design: Difficulty/transitive_cascade/case_classify_cascades_summary_bounce_and_rate_shift
        """
        _, prepared, pending = self._prepared_summary_and_pending_case(
            "55-9090910")
        validate_success(api.classify_case(
            pending["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": pending["version"]},
            OFFICER), 200)

        bounced = get_summary(prepared["id"])
        assert bounced["status"] == "DRAFT"
        assert bounced["prepared_by"] is None
        assert bounced["trir"] is None, (
            "The bounce discards the stored provisional rates")
        assert bounced["dart_rate"] is None


class TestCitationOverdueCascade:
    def _final_order_citation_with_actions(self, api, fein):
        """Two corrective actions due 2026-08-06 plus a citation accepted as
        final order with abatement due 2026-08-10."""
        _, establishment, employee = setup_org(fein=fein, site_name="Depot 5",
                                               naics_code="484110",
                                               state_code="GA")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-04T10:00:00Z",
            clock_iso="2026-08-05T09:00:00Z", description="Strain",
            body_part="back")
        for label in ("Dock plate fix A", "Dock plate fix B"):
            create_corrective_action(
                establishment["id"], case_id=case["id"], description=label,
                assigned_to="op-fix-9", due_date="2026-08-06")
        inspection = create_inspection(
            establishment["id"], opened_on="2026-08-05",
            inspection_type="PROGRAMMED", scope="COMPREHENSIVE")
        citation = create_citation(
            inspection["id"], standard_cited="29 CFR 1910.178",
            proposed_penalty_usd=12000, abatement_due_date="2026-08-10")
        get_success_data(api.accept_final_order(citation["id"], OFFICER))
        return establishment, citation

    def test_first_sweep_scores_overdue_actions_only(self, api):
        """PRD §2.4: "Every clock repositioning triggers a compliance sweep.
        Each corrective action whose `due_date` falls before the new clock
        date and that still sits in `OPEN` or `REOPENED` moves to `OVERDUE`"
        PRD §2.7: "plus 5.0 for each corrective action currently in
        `OVERDUE`"
        PRD §2.7: "anything below 25.0 yields `CLEAR`."

        Design: Difficulty/transitive_cascade/citation_overdue_cascades_posture_and_risk
        """
        establishment, citation = self._final_order_citation_with_actions(
            api, "55-1112223")
        set_clock("2026-08-07T00:00:00Z")

        est = get_establishment(establishment["id"])
        assert est["risk_score"] == pytest.approx(10.0, abs=0.01), (
            "2 overdue actions x 5.0; citation not yet due")
        assert est["posture"] == "CLEAR"
        assert get_success_data(
            api.get_citation(citation["id"], OFFICER))["status"] == (
                "ABATEMENT_PENDING")

    def test_second_sweep_cascades_citation_overdue_into_risk(self, api):
        """PRD §2.4: "each citation whose `abatement_due_date` has passed
        without abatement moves from `ABATEMENT_PENDING` to `OVERDUE`. Every
        such transition recomputes the owning establishment's posture and risk
        score (§2.7)"
        PRD §2.7: "plus 8.0 for each citation currently in `OVERDUE`"

        Design: Difficulty/transitive_cascade/citation_overdue_cascades_posture_and_risk
        """
        establishment, citation = self._final_order_citation_with_actions(
            api, "55-1112224")
        set_clock("2026-08-07T00:00:00Z")
        set_clock("2026-08-11T00:00:00Z")

        refreshed = get_success_data(api.get_citation(citation["id"], OFFICER))
        assert refreshed["status"] == "OVERDUE", (
            "Abatement due 2026-08-10 passes without abatement")

        est = get_establishment(establishment["id"])
        assert est["risk_score"] == pytest.approx(18.0, abs=0.01), (
            "10.0 from the two overdue actions + 8.0 from the overdue "
            "citation")
        assert est["posture"] == "CLEAR", (
            "18.0 remains below the inclusive 25.0 WATCH threshold")
