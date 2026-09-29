"""Endpoint shapes: registry round trips, bulk sweeps, calibration links and cure gates."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    CRITICAL_ACTION_DUE_AT,
    FIRST_VISIT_END,
    FIRST_VISIT_START,
    SCORE_SHEET_ONE_CRITICAL,
    SCORE_SHEET_SHADOW_CLOSE,
    TEST_DEFAULTS,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_instant,
    assert_versioned_record,
    calibration_record_payload,
    create_brand,
    finalize_visit,
    franchisee_payload,
    schedule_visit,
    score_visit,
    setup_brand_program,
    setup_finalized_visit,
    start_visit,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFranchiseeRegistry:
    def test_franchisee_create_read_and_list_round_trip(self):
        """Create, read and list are the whole surface, and the counters start empty.

        PRD: "A franchisee's two derived fields — `open_default_location_count`, the number of
        its locations whose `franchise_agreement_status` is anything other than
        `GOOD_STANDING`, and `termination_recommended`, which becomes true as soon as any one of
        its locations reaches `TERMINATION_RECOMMENDED` — both begin at their empty values (zero
        and false) and move only through the cascades described in §2.7."

        Design: Corner/endpoints/franchisee_create_read_list_round_trip_with_computed_counters
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()

        first = validate_success(
            api_client.create_franchisee(franchisee_payload(brand["id"]), ADMIN_HEADERS),
            expected_status=201,
        )
        assert_versioned_record(first)
        assert first["open_default_location_count"] == 0
        assert first["termination_recommended"] is False
        assert first["version"] == 1
        assert_instant(first["created_at"], CLOCK_EPOCH, "created_at")

        second = validate_success(
            api_client.create_franchisee(
                franchisee_payload(
                    brand["id"],
                    legal_name="Lakeshore QSR Group Inc",
                    contact_email="ops@lakeshore.test",
                    agreement_signed_at="2025-06-15T00:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        reread = validate_success(api_client.get_franchisee(first["id"], ADMIN_HEADERS))
        assert reread["legal_name"] == TEST_DEFAULTS["FRANCHISEE_LEGAL_NAME"]
        assert reread["brand_id"] == brand["id"]
        assert_instant(
            reread["agreement_signed_at"], TEST_DEFAULTS["AGREEMENT_SIGNED_AT"],
            "agreement_signed_at",
        )
        assert reread["open_default_location_count"] == 0

        page_one, meta_one = validate_paginated(
            api_client.list_franchisees(
                ADMIN_HEADERS, params={"brand_id": brand["id"], "limit": 1, "offset": 0}
            )
        )
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert [row["id"] for row in page_one] == [first["id"]]

        page_two, meta_two = validate_paginated(
            api_client.list_franchisees(
                ADMIN_HEADERS, params={"brand_id": brand["id"], "limit": 1, "offset": 1}
            )
        )
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert [row["id"] for row in page_two] == [second["id"]], \
            "the second page continues the created_at ascending order"


class TestOverdueSweepNoOp:
    def test_a_sweep_with_nothing_past_due_is_a_repeatable_no_op(self):
        """An empty selection is a success, and running it twice changes nothing.

        PRD: "It reports four figures: `swept_count` for the actions it examined and moved,
        `overdue_count` for those that landed in `OVERDUE`, `escalated_count` for those that
        continued on to `ESCALATED`, and `escalated_location_count` for the number of distinct
        locations affected by an escalation."

        Design: Corner/endpoints/overdue_sweep_with_nothing_past_due_is_a_no_op_and_is_repeatable
        """
        program = setup_finalized_visit()
        advance_clock("2026-08-06T00:00:00Z")

        for attempt in ("first", "second"):
            sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
            assert sweep["swept_count"] == 0, f"{attempt} sweep found nothing past due"
            assert sweep["overdue_count"] == 0
            assert sweep["escalated_count"] == 0
            assert sweep["escalated_location_count"] == 0

        critical = validate_success(
            api_client.get_corrective_action(program["actions"]["FS-1"]["id"], ADMIN_HEADERS)
        )
        assert critical["status"] == "ASSIGNED"
        assert_instant(critical["due_at"], CRITICAL_ACTION_DUE_AT, "critical due_at")
        standard = validate_success(
            api_client.get_corrective_action(program["actions"]["BS-1"]["id"], ADMIN_HEADERS)
        )
        assert standard["status"] == "ASSIGNED"

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["escalation_level"] == 0
        assert location["franchise_agreement_status"] == "GOOD_STANDING"
        assert location["open_corrective_action_count"] == 3
        assert location["standing_score"] == pytest.approx(90.70, abs=0.01)

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["brand_risk_index"] == pytest.approx(11.58, abs=0.01)
        assert risk["brand_risk_tier"] == "BASELINE"
        assert risk["default_location_count"] == 0
        assert risk["open_critical_action_count"] == 1


class TestCalibrationRecordLinks:
    def test_a_calibration_record_links_both_visits_and_both_auditors(self):
        """The body names only the shadow visit; the server derives the other three links.

        PRD: "The server derives the rest: `primary_visit_id` is the shadow visit's
        `shadow_of_visit_id` target, `auditor_id` is the primary visit's auditor — the party
        whose reliability this record adjusts — `reviewer_auditor_id` is the shadow visit's
        auditor acting in the review seat, and `recorded_at` is the logical clock."

        Design: Corner/endpoints/calibration_record_links_shadow_visit_primary_visit_and_two_auditors
        """
        program = setup_brand_program(with_reviewer=True)
        auditor_id = program["auditor"]["id"]
        reviewer_id = program["reviewer"]["id"]

        primary = schedule_visit(program, FIRST_VISIT_START, FIRST_VISIT_END)
        shadow = schedule_visit(
            program, FIRST_VISIT_START, FIRST_VISIT_END, visit_type="SHADOW",
            auditor_id=reviewer_id, shadow_of_visit_id=primary["id"],
        )

        start_visit(program, primary["id"], at=FIRST_VISIT_START)
        score_visit(program, primary["id"], SCORE_SHEET_ONE_CRITICAL)
        submit_visit(program, primary["id"])

        start_visit(program, shadow["id"], auditor_id=reviewer_id)
        score_visit(program, shadow["id"], SCORE_SHEET_SHADOW_CLOSE, auditor_id=reviewer_id)
        shadow_submitted = submit_visit(program, shadow["id"], auditor_id=reviewer_id)
        assert shadow_submitted["composite_score"] == pytest.approx(90.20, abs=0.01)

        primary_final = finalize_visit(program, primary["id"], at=FIRST_VISIT_END)
        assert primary_final["composite_score"] == pytest.approx(90.70, abs=0.01)

        record = validate_success(
            api_client.create_calibration_record(
                calibration_record_payload(shadow["id"]),
                program["reviewer_calibration_headers"],
            ),
            expected_status=201,
        )
        assert record["primary_visit_id"] == primary["id"]
        assert record["auditor_id"] == auditor_id, "the audited party is the primary's auditor"
        assert record["reviewer_auditor_id"] == reviewer_id
        assert record["auditor_id"] != record["reviewer_auditor_id"]
        assert record["variance_points"] == pytest.approx(0.50, abs=0.01)
        assert record["band"] == "EXCELLENT"
        assert record["reliability_delta"] == pytest.approx(4.00, abs=0.01)
        assert_instant(record["recorded_at"], FIRST_VISIT_END, "recorded_at")

        audited = validate_success(api_client.get_auditor(auditor_id, ADMIN_HEADERS))
        assert audited["reliability_score"] == pytest.approx(74.00, abs=0.01), \
            "70.00 plus the newest delta at full strength"
        assert audited["status"] == "CERTIFIED"
        reviewer = validate_success(api_client.get_auditor(reviewer_id, ADMIN_HEADERS))
        assert reviewer["reliability_score"] == pytest.approx(70.00, abs=0.01), \
            "only the audited auditor's reliability moves"

        lookups = (
            api_client.list_visit_calibration_records(
                shadow["id"], ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            ),
            api_client.list_visit_calibration_records(
                primary["id"], ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            ),
            api_client.list_auditor_calibration_records(
                auditor_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            ),
            api_client.list_auditor_calibration_records(
                reviewer_id, ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            ),
        )
        for response in lookups:
            rows, meta = validate_paginated(response)
            assert meta["total_count"] == 1
            assert rows[0]["id"] == record["id"]


class TestCureAcceptanceGates:
    def test_cure_acceptance_needs_both_an_escalation_and_no_open_actions(self):
        """The state guard answers first; the open-action gate answers second.

        PRD: "Acceptance requires that the location's `open_corrective_action_count` be exactly
        0 — every outstanding remediation must be verified, voided, or escalated out of the open
        pool first — and an attempt with open actions is rejected with
        `ERR_OPEN_CORRECTIVE_ACTIONS`. An attempt against a location already in
        `GOOD_STANDING` is rejected with `ERR_NO_ESCALATION_TO_CURE`."

        Design: Corner/endpoints/cure_acceptance_is_refused_unless_both_escalation_and_open_action_gates_hold
        """
        program = setup_finalized_visit()
        location_id = program["location"]["id"]

        validate_error(
            api_client.accept_cure(location_id, ADMIN_HEADERS, {}),
            ApiErrorId.ERR_NO_ESCALATION_TO_CURE,
            expected_status=409,
        )
        untouched = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert untouched["escalation_level"] == 0
        assert untouched["franchise_agreement_status"] == "GOOD_STANDING"
        assert untouched["cure_period_started_at"] is None

        advance_clock("2026-08-09T00:00:00Z")
        sweep = validate_success(api_client.run_overdue_sweep(ADMIN_HEADERS, {}))
        assert sweep["swept_count"] == 1, "only the critical action is past its due_at"
        assert sweep["escalated_count"] == 1

        validate_error(
            api_client.accept_cure(location_id, ADMIN_HEADERS, {"note": "Hood cleaned"}),
            ApiErrorId.ERR_OPEN_CORRECTIVE_ACTIONS,
            expected_status=409,
        )

        escalated = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert escalated["escalation_level"] == 1
        assert escalated["franchise_agreement_status"] == "NOTICE_OF_DEFAULT"
        assert escalated["open_corrective_action_count"] == 2, \
            "escalation took the critical action out of the open pool"
        assert escalated["cure_period_started_at"] is None, \
            "the second refusal was also side-effect free"

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["brand_risk_index"] == pytest.approx(21.58, abs=0.01), \
            "0.60 * 9.30 plus 6.00 for the escalated critical action plus 10.00 for the default"
        assert risk["default_location_count"] == 1
