"""Endpoint contracts: the inline run summary, the clock echo and the evidence lookup."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    add_audience_sample,
    add_design_factor,
    api_client,
    assert_compliance_run_summary,
    assert_determination_evidence,
    assert_instant,
    create_service,
    read_service,
    run_compliance,
    set_clock,
    validate_paginated,
)


class TestComplianceRunSummaryAndSequence:
    """An idle run still advances the epoch and reports a full zeroed summary."""

    def test_01_two_idle_runs_report_sequence_one_then_two(self):
        """The run endpoint returns counters, not an entity, and never stalls.

        "A run first advances the service's `compliance_run_sequence` by one, and that new
        value is the run's sequence number for everything that follows." "The run advances the
        service's `version` by one and reports back a summary: the `service_id` it acted on,
        the `run_sequence` it used, an `expired_consent_count`, a `scheduled_count`, a
        `disposed_count`, the resulting `live_child_data_element_count_after`, and the
        resulting `compliance_posture_after`." Either a `ComplianceOfficer` or a
        `PrivacyEngineer` may trigger a run.

        Design: Corner/endpoints/compliance_run_reports_inline_counters_and_advances_its_own_sequence
        """
        service = create_service(name="Idle Run Kids")
        service_id = service["id"]
        assert service["compliance_run_sequence"] == 0, (
            f"no run has executed yet, got {service['compliance_run_sequence']}"
        )
        assert service["version"] == 1, (
            f"version begins at 1 when the resource is created, got {service['version']}"
        )

        first = run_compliance(service_id, OFFICER_HEADERS)

        assert_compliance_run_summary(first)
        assert first["service_id"] == service_id, (
            f"the summary echoes the service it acted on, got {first['service_id']}"
        )
        assert first["run_sequence"] == 1
        assert first["expired_consent_count"] == 0
        assert first["scheduled_count"] == 0
        assert first["disposed_count"] == 0
        assert first["live_child_data_element_count_after"] == 0
        assert first["compliance_posture_after"] == "OPEN"

        second = run_compliance(service_id, ENGINEER_HEADERS)

        assert second["run_sequence"] == 2, (
            f"the sequence advances even on an idle run, got {second['run_sequence']}"
        )
        assert second["expired_consent_count"] == 0
        assert second["scheduled_count"] == 0
        assert second["disposed_count"] == 0

        after = read_service(service_id)
        assert after["compliance_run_sequence"] == 2
        assert after["version"] == 3, (
            f"one increment per run on top of version 1 at creation, got {after['version']}"
        )
        assert after["lifetime_collected_element_count"] == 0, (
            "an idle run never fabricates records, got "
            f"{after['lifetime_collected_element_count']}"
        )


class TestClockEndpointEchoesTheNewInstant:
    """The declared startup default governs until an operator repositions the clock."""

    def test_02_the_startup_default_stamps_the_first_service_and_survives_the_move(self):
        """A service created before any clock call carries the declared startup instant.

        "The clock's startup value is exactly `2026-08-01T00:00:00Z`. Until an operator moves
        it, every comparison in this specification uses that instant. A `ComplianceOfficer`
        may reposition the clock by supplying `to_iso8601`; the response reports the new
        instant as `current_utc`." "If the service has no assessment at all, its
        `safe_harbor_status` is `NOT_ENROLLED`."

        Design: Corner/endpoints/clock_endpoint_reports_the_new_instant_and_the_declared_startup_default
        """
        at_default = create_service(name="Default Clock Kids")
        assert_instant(at_default["created_at"], STARTUP_CLOCK, "created_at")
        assert at_default["determination_evaluated_at"] is None, (
            "no determination run has happened, got "
            f"{at_default['determination_evaluated_at']}"
        )

        echoed = set_clock("2026-09-15T12:30:00Z")
        assert_instant(echoed["current_utc"], "2026-09-15T12:30:00Z", "current_utc")

        after_move = create_service(name="Moved Clock Kids")
        assert_instant(after_move["created_at"], "2026-09-15T12:30:00Z", "created_at")

        reread = read_service(at_default["id"])
        assert_instant(reread["created_at"], STARTUP_CLOCK, "created_at")
        assert reread["safe_harbor_status"] == "NOT_ENROLLED", (
            "the clock recompute leaves an unenrolled service alone, got "
            f"{reread['safe_harbor_status']}"
        )


class TestEvidenceReverseLookupScopeAndFilters:
    """The lookup is service-scoped, sequence-ordered, and its filters compose."""

    def test_03_kind_and_method_filters_compose_with_pagination_within_one_service(self):
        """Four rows on one service, one on another, and none of them leak.

        "the reverse-lookup listing of a service's determination evidence is ordered by
        `evidence_sequence` ascending, because that counter — not creation time and never the
        row's identifier — is the authoritative ordering of the evidence record." "Every
        accepted row advances the service's `evidence_sequence_counter` by one and is stamped
        with that new value as its `evidence_sequence`, starting at 1 for the first row." "A
        service's evidence reverse-lookup accepts `evidence_kind` and `measurement_method`".

        Design: Corner/endpoints/evidence_sub_resource_filters_by_kind_and_method_within_one_service
        """
        first_service = create_service(name="Evidence Lookup Kids A")
        second_service = create_service(name="Evidence Lookup Kids B")
        service_id = first_service["id"]

        design_one = add_design_factor(service_id, "SUBJECT_MATTER", "MODERATE")
        panel = add_audience_sample(service_id, 1000, 300, "PANEL", sample_verified=True)
        screen_log = add_audience_sample(
            service_id, 500, 100, "AGE_SCREEN_LOG", sample_verified=False
        )
        design_two = add_design_factor(service_id, "VISUAL_CONTENT", "STRONG")
        other = add_design_factor(second_service["id"], "LANGUAGE", "MODERATE")

        assert [row["evidence_sequence"] for row in (design_one, panel, screen_log, design_two)] == [
            1,
            2,
            3,
            4,
        ], "the counter starts at 1 and advances by one per accepted row"
        assert other["evidence_sequence"] == 1, (
            "the counter is per service, not global, got " f"{other['evidence_sequence']}"
        )
        assert_determination_evidence(panel)

        rows, meta = validate_paginated(
            api_client.list_service_determination_evidence(
                service_id, ENGINEER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 4
        assert [row["evidence_sequence"] for row in rows] == [1, 2, 3, 4], (
            "the listing is ordered by evidence_sequence ascending, got "
            f"{[row['evidence_sequence'] for row in rows]}"
        )
        assert rows[3]["evidence_kind"] == "DESIGN_FACTOR"

        design_rows, design_meta = validate_paginated(
            api_client.list_service_determination_evidence(
                service_id,
                ENGINEER_HEADERS,
                {"evidence_kind": "DESIGN_FACTOR", "limit": 100, "offset": 0},
            )
        )
        assert design_meta["total_count"] == 2
        assert [row["evidence_sequence"] for row in design_rows] == [1, 4], (
            "the filter preserves the sequence order and skips the two samples, got "
            f"{[row['evidence_sequence'] for row in design_rows]}"
        )

        panel_rows, panel_meta = validate_paginated(
            api_client.list_service_determination_evidence(
                service_id,
                ENGINEER_HEADERS,
                {
                    "evidence_kind": "AUDIENCE_SAMPLE",
                    "measurement_method": "PANEL",
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        assert panel_meta["total_count"] == 1, (
            "the age-screen-log row is excluded by measurement_method, got "
            f"{panel_meta['total_count']}"
        )
        assert panel_rows[0]["id"] == panel["id"]

        page_rows, page_meta = validate_paginated(
            api_client.list_service_determination_evidence(
                service_id, OFFICER_HEADERS, {"limit": 2, "offset": 2}
            )
        )
        assert page_meta["total_count"] == 4
        assert [row["evidence_sequence"] for row in page_rows] == [3, 4], (
            "limit 2 offset 2 returns the tail, got "
            f"{[row['evidence_sequence'] for row in page_rows]}"
        )
        assert page_meta["has_more"] is False

        other_rows, other_meta = validate_paginated(
            api_client.list_service_determination_evidence(
                second_service["id"], OFFICER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert other_meta["total_count"] == 1, (
            "the second service's evidence never leaks into the first lookup, got "
            f"{other_meta['total_count']}"
        )
        assert other_rows[0]["evidence_sequence"] == 1
