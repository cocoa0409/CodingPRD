"""Endpoints whose contract is about the call itself: the clock that reports
what it replaced, a manual escalation that can be taken back, a sweep that
rehearses before it writes, and derived reads that leave their subject alone."""

from test_helpers import (
    CLOCK_EPOCH_MS,
    CLOCK_HEADERS,
    add_contact,
    assert_severity,
    assert_two_decimal_value,
    assert_unchanged,
    complaint_payload,
    regulatory_report_payload,
    run_quality_ops,
    seed_base_world,
    seed_triaged_complaint,
    set_clock,
    triage,
    validate_paginated,
    validate_success,
)

SHARP_PACKAGING = dict(
    complaint_type="PACKAGING",
    foreign_object_class="HARD_SHARP",
    medical_attention_sought=True,
    symptom_codes=["CUT", "PAIN", "SWELLING", "BLEEDING"],
)


class TestLogicalClock:
    def test_setting_the_clock_reports_the_instant_it_replaced(self, api):
        """Each set echoes the new instant and the old one, forwards or backwards.

        PRD: "`SystemAdmin` sets it by supplying `current_utc`; the response
        echoes the newly effective `current_utc` alongside the `previous_utc` it
        replaced."

        Design: Corner/endpoints/corner_clock_endpoint_returns_previous_and_current_instants
        """
        assert "X-User-ID" not in CLOCK_HEADERS

        first_response = api.set_clock("2026-08-01T00:00:00.000Z", CLOCK_HEADERS)
        first = validate_success(first_response, 200)
        assert first_response.json()["response_type"] == "object"
        assert first["current_utc"] == "2026-08-01T00:00:00.000Z"

        forwards = validate_success(
            api.set_clock("2026-09-15T06:30:00.000Z", CLOCK_HEADERS), 200
        )
        assert forwards["current_utc"] == "2026-09-15T06:30:00.000Z"
        assert forwards["previous_utc"] == "2026-08-01T00:00:00.000Z"

        backwards = validate_success(
            api.set_clock("2026-07-01T00:00:00.000Z", CLOCK_HEADERS), 200
        )
        assert backwards["current_utc"] == "2026-07-01T00:00:00.000Z"
        assert backwards["previous_utc"] == "2026-09-15T06:30:00.000Z"


class TestManualEscalationRoundTrip:
    def test_withdrawing_a_manual_report_frees_the_complaint_to_escalate_again(
        self, api
    ):
        """A band that never auto-escalates is escalated by hand, then released.

        PRD: "Withdrawal moves the report to `WITHDRAWN`, which is terminal, and
        resets the complaint's `regulatory_status` all the way back to
        `NOT_APPLICABLE` — from `ESCALATED`, from `REPORTABLE`, or from
        `NOT_REPORTABLE` alike — which is precisely what makes a fresh escalation
        possible afterwards."

        Design: Corner/endpoints/corner_manual_regulatory_report_links_and_unlinks_the_complaint
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1"))
        seed_triaged_complaint(
            api,
            world,
            complaint_type="FOREIGN_MATERIAL",
            foreign_object_class="SOFT",
            contact_overrides={
                "channel": "EMAIL",
                "raw_message": "Soft matter, no injury.",
            },
        )
        complaint = world["complaints"]["cp1"]
        complaint_id = complaint["id"]
        assert_severity(complaint, adjudicated_score=48.38, adjudicated_band="S3")
        assert complaint["regulatory_status"] == "NOT_APPLICABLE"
        officer = world.headers("ro1")

        first_report = validate_success(
            api.create_regulatory_report(
                regulatory_report_payload(
                    complaint_id, report_kind="FOREIGN_MATERIAL_INJURY"
                ),
                officer,
            ),
            201,
        )
        assert first_report["status"] == "OPEN"
        assert first_report["escalated_at"] == CLOCK_EPOCH_MS
        assert first_report["due_at"] == "2026-08-04T00:00:00.000Z"

        escalated = validate_success(
            api.get_complaint(complaint_id, world.headers("ag1"))
        )
        assert escalated["regulatory_status"] == "ESCALATED"
        assert escalated["handling_status"] == "TRIAGED"

        withdrawn = validate_success(
            api.withdraw_regulatory_report(
                first_report["id"], {"reason": "Escalated in error."}, officer
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        released = validate_success(
            api.get_complaint(complaint_id, world.headers("ag1"))
        )
        assert released["regulatory_status"] == "NOT_APPLICABLE"

        second_report = validate_success(
            api.create_regulatory_report(
                regulatory_report_payload(complaint_id, report_kind="ADVERSE_EVENT"),
                officer,
            ),
            201,
        )
        assert second_report["status"] == "OPEN"
        assert second_report["id"] != first_report["id"]

        retired = validate_success(
            api.get_regulatory_report(first_report["id"], officer)
        )
        assert retired["status"] == "WITHDRAWN"
        live = validate_success(api.get_regulatory_report(second_report["id"], officer))
        assert live["status"] == "OPEN"


class TestQualityOpsDryRun:
    def test_a_rehearsed_sweep_reports_the_counts_it_does_not_write(self, api):
        """The dry run announces one signal and three memberships, then persists none.

        PRD: "With `dry_run` set to true the identical counts are returned and
        nothing at all is persisted."

        Design: Corner/endpoints/corner_quality_ops_dry_run_reports_without_writing
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1", "sup1", "ql1"),
            product="mug",
            lot={"batch_code": "LOT-DRY", "units_produced": 100000},
        )
        add_contact(
            api, world, "ct1", channel="WEB", raw_message="Sharp edges, three mugs."
        )
        for key in ("d1", "d2", "d3"):
            complaint = validate_success(
                api.create_complaint(
                    complaint_payload(
                        world["contacts"]["ct1"]["id"],
                        reported_batch_code="LOTDRY",
                        **SHARP_PACKAGING,
                    ),
                    world.headers("ag1"),
                ),
                201,
            )
            world["complaints"][key] = triage(api, world, complaint["id"])
            assert_severity(
                world["complaints"][key], adjudicated_score=89.00, adjudicated_band="S2"
            )
        set_clock(api, "2026-08-02T00:00:00Z")
        lead = world.headers("ql1")

        rehearsal = run_quality_ops(api, world, dry_run=True)
        assert rehearsal["run_at"] == "2026-08-02T00:00:00.000Z"
        assert rehearsal["signals_created_count"] == 1
        assert rehearsal["memberships_created_count"] == 3

        _rows, nothing_written = validate_paginated(api.list_trend_signals(lead))
        assert nothing_written["total_count"] == 0

        live_run = run_quality_ops(api, world, dry_run=False)
        assert live_run["signals_created_count"] == 1
        assert live_run["memberships_created_count"] == 3

        signals, written = validate_paginated(api.list_trend_signals(lead))
        assert written["total_count"] == 1
        signal = signals[0]
        assert signal["detection_source"] == "OPS_RUN"
        assert signal["scope_level"] == "LOT"
        assert signal["membership_count"] == 3
        assert signal["units_in_scope"] == 100000
        assert_two_decimal_value(signal["weighted_complaint_count"], 6.00)
        assert_two_decimal_value(signal["observed_rate_ppm"], 60.00)
        assert_two_decimal_value(signal["threshold_ppm"], 25.00)

        repeat = run_quality_ops(api, world)
        assert repeat["signals_created_count"] == 0
        assert repeat["signals_refreshed_count"] == 1
        _rows, after_repeat = validate_paginated(api.list_trend_signals(lead))
        assert after_repeat["total_count"] == 1


class TestComputedReadsArePure:
    def test_reading_a_rate_or_a_sentiment_never_moves_the_record(self, api):
        """Four derived reads agree with themselves and leave the lot's version alone.

        PRD: "Most resources — `StaffUser`, `Consumer`, `Plant`,
        `ProductionLine`, `Product`, `ProductionLot`, `Contact`, `Complaint`,
        `SampleKit`, `Remedy`, `RegulatoryReport`, `TrendSignal`, and
        `ResponseTemplate` — additionally carry `updated_at`, an ISO 8601 UTC
        instant refreshed on every mutation, and `version`, an integer that
        increments by one on every mutation."

        Design: Corner/endpoints/corner_computed_reads_do_not_mutate_their_subject
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_contact(
            api, world, "ct1", channel="EMAIL", raw_message="Two stale packs."
        )
        for key in ("x1", "x2"):
            complaint = validate_success(
                api.create_complaint(
                    complaint_payload(
                        world["contacts"]["ct1"]["id"], complaint_type="QUALITY"
                    ),
                    world.headers("ag1"),
                ),
                201,
            )
            world["complaints"][key] = triage(api, world, complaint["id"])
        lot_id = world["lot"]["id"]
        consumer_id = world["consumer"]["id"]
        supervisor = world.headers("sup1")
        before = validate_success(api.get_production_lot(lot_id, supervisor))

        rate = validate_success(api.get_lot_complaint_rate(lot_id, supervisor))
        assert rate["production_lot_id"] == lot_id
        assert rate["variant"] == "provisional"
        assert rate["numerator"] == 2
        assert rate["units_produced"] == 200000
        assert rate["rate_undefined"] is False
        assert_two_decimal_value(rate["rate_ppm"], 10.00)
        again = validate_success(api.get_lot_complaint_rate(lot_id, supervisor))
        assert again == rate

        sentiment = validate_success(
            api.get_consumer_sentiment(consumer_id, supervisor)
        )
        assert sentiment["complaint_count_in_window"] == 2
        assert_two_decimal_value(sentiment["sentiment_index"], 44.00)
        assert_two_decimal_value(sentiment["penalty_total"], 6.00)
        once_more = validate_success(
            api.get_consumer_sentiment(consumer_id, supervisor)
        )
        assert once_more == sentiment

        after = validate_success(api.get_production_lot(lot_id, supervisor))
        assert_unchanged(before, after, "version", "updated_at")
