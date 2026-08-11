"""Discharge: cascade side effects, incident gating, notice rules, terminal
lockdown, refund computation, and discharge-record retrieval."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_discharge_payload, setup_admitted_resident, setup_incident_with_case,
    file_incident, discharge_resident_now, set_clock, fresh_bed, fresh_resident,
    assert_same_instant,
    fresh_incident, fresh_medication_order, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestDischargeCascade:
    def test_discharge_releases_bed_and_discontinues_orders(self, api):
        """PRD §3.8: "A successful discharge moves the resident `ADMITTED` →
        `DISCHARGED` — terminal — stamps `discharged_at` from the clock and copies it
        onto the new discharge record, returns the occupied bed to `AVAILABLE`,
        discontinues every remaining `ACTIVE` medication order, recomputes the home's
        `current_census`, and switches invoice generation for the occupancy window to
        the final, chronological variant of §3.7."

        Design: Corner/cross_cutting_layers/discharge_cascades_bed_release_and_order_discontinue
        """
        ctx = setup_admitted_resident()
        order = validate_success(api.create_medication_order(
            ctx["resident"]["id"],
            {"drug_name": "Metformin", "dose": "500mg oral",
             "schedule_times": ["08:00", "20:00"]},
            NURSE), 201)
        record = discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                                        notice_days=30, clock="2026-06-05T09:00:00Z")
        assert fresh_bed(ctx["bed"]["id"])["status"] == "AVAILABLE", \
            "discharge must release the occupied bed"
        order_after = fresh_medication_order(ctx["resident"]["id"], order["id"])
        assert order_after["status"] == "DISCONTINUED", \
            "every remaining ACTIVE order must be discontinued"
        assert record["refund_amount_cents"] == 0, \
            "no prepaid post-discharge days exist, so the refund floor holds"

    def test_discharge_stamps_discharged_at_from_clock(self, api):
        """PRD §3.8: "A successful discharge moves the resident `ADMITTED` →
        `DISCHARGED` — terminal — stamps `discharged_at` from the clock and copies it
        onto the new discharge record, returns the occupied bed to `AVAILABLE`,
        discontinues every remaining `ACTIVE` medication order, recomputes the home's
        `current_census`, and switches invoice generation for the occupancy window to
        the final, chronological variant of §3.7."

        Design: Corner/cross_cutting_layers/discharge_cascades_bed_release_and_order_discontinue
        """
        ctx = setup_admitted_resident()
        record = discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                                        notice_days=30, clock="2026-06-05T09:00:00Z")
        resident_after = fresh_resident(ctx["resident"]["id"])
        assert resident_after["status"] == "DISCHARGED"
        assert_same_instant(resident_after["discharged_at"], "2026-06-05T09:00:00Z")
        assert_same_instant(record["discharged_at"], "2026-06-05T09:00:00Z")


class TestDischargeNoticeRule:
    def test_insufficient_notice_rejected(self, api):
        """PRD §3.8: "Then the notice rule: `notice_days` must be at least thirty
        unless the reason is `HOSPITALIZATION` or `DECEASED`, else
        `ERR_INSUFFICIENT_NOTICE`."

        Design: Corner/errors/err_insufficient_notice_triggered
        """
        ctx = setup_admitted_resident()
        res = api.discharge_resident(ctx["resident"]["id"],
                                     create_discharge_payload(reason="VOLUNTARY",
                                                              notice_days=10),
                                     PROVIDER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_NOTICE, expected_status=422)
        assert fresh_resident(ctx["resident"]["id"])["status"] == "ADMITTED", \
            "a rejected discharge must fire no side effects"


class TestDischargeIncidentGate:
    def test_open_critical_incident_blocks_discharge(self, api):
        """PRD §3.8: "The incident block is evaluated first, per §2.9: while any
        `CRITICAL` incident for the resident is `REPORTED` or `UNDER_REVIEW`, the
        discharge is rejected with `ERR_BLOCKED_BY_INCIDENT`."

        Design: Difficulty/cross_entity_state_dependency/discharge_blocked_by_open_critical_incident
        """
        ctx = setup_incident_with_case(
            severity="CRITICAL", incident_type="ELOPEMENT",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Left facility")
        res = api.discharge_resident(ctx["resident"]["id"],
                                     create_discharge_payload(reason="VOLUNTARY",
                                                              notice_days=30),
                                     PROVIDER)
        validate_error(res, ApiErrorId.ERR_BLOCKED_BY_INCIDENT, expected_status=409)

    def test_resolving_case_lifts_discharge_gate(self, api):
        """PRD §3.6: "Marking a case unfounded moves `OPEN` → `UNFOUNDED`, resolves
        the linked incident in the same way, and recomputes the counter."
        PRD §3.8: "The incident block is evaluated first, per §2.9: while any
        `CRITICAL` incident for the resident is `REPORTED` or `UNDER_REVIEW`, the
        discharge is rejected with `ERR_BLOCKED_BY_INCIDENT`."

        Design: Difficulty/cross_entity_state_dependency/discharge_blocked_by_open_critical_incident
        """
        ctx = setup_incident_with_case(
            severity="CRITICAL", incident_type="ELOPEMENT",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Left facility")
        res = api.discharge_resident(ctx["resident"]["id"],
                                     create_discharge_payload(reason="VOLUNTARY",
                                                              notice_days=30),
                                     PROVIDER)
        validate_error(res, ApiErrorId.ERR_BLOCKED_BY_INCIDENT, expected_status=409)
        validate_success(api.mark_case_unfounded(ctx["case"]["id"], PROVIDER), 200)
        assert fresh_incident(ctx["incident"]["id"])["status"] == "RESOLVED"
        record = validate_success(api.discharge_resident(
            ctx["resident"]["id"],
            create_discharge_payload(reason="VOLUNTARY", notice_days=30),
            PROVIDER), 200)
        assert record["resident_id"] == ctx["resident"]["id"]
        assert fresh_resident(ctx["resident"]["id"])["status"] == "DISCHARGED", \
            "once the critical incident resolves, the discharge gate lifts"


class TestDischargeValidationPriority:
    def test_critical_incident_beats_notice_rule(self, api):
        """PRD §3.8: "The incident block is evaluated first, per §2.9: while any
        `CRITICAL` incident for the resident is `REPORTED` or `UNDER_REVIEW`, the
        discharge is rejected with `ERR_BLOCKED_BY_INCIDENT`. Then the notice rule:
        `notice_days` must be at least thirty unless the reason is `HOSPITALIZATION`
        or `DECEASED`, else `ERR_INSUFFICIENT_NOTICE`."

        Design: Difficulty/priority_pair_validation_conflict/discharge_critical_incident_safety_beats_notice_constraint
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-01T12:00:00Z")
        file_incident(ctx["resident"]["id"], "2026-06-01T08:00:00Z",
                      severity="CRITICAL", incident_type="ELOPEMENT",
                      description="Resident left unsupervised")
        res = api.discharge_resident(ctx["resident"]["id"],
                                     create_discharge_payload(reason="VOLUNTARY",
                                                              notice_days=5),
                                     PROVIDER)
        validate_error(res, ApiErrorId.ERR_BLOCKED_BY_INCIDENT, expected_status=409)

    def test_blocked_discharge_fires_no_side_effects(self, api):
        """PRD §3.8: "The incident block is evaluated first, per §2.9: while any
        `CRITICAL` incident for the resident is `REPORTED` or `UNDER_REVIEW`, the
        discharge is rejected with `ERR_BLOCKED_BY_INCIDENT`."

        Design: Difficulty/priority_pair_validation_conflict/discharge_critical_incident_safety_beats_notice_constraint
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-01T12:00:00Z")
        file_incident(ctx["resident"]["id"], "2026-06-01T08:00:00Z",
                      severity="CRITICAL", incident_type="ELOPEMENT",
                      description="Resident left unsupervised")
        res = api.discharge_resident(ctx["resident"]["id"],
                                     create_discharge_payload(reason="VOLUNTARY",
                                                              notice_days=5),
                                     PROVIDER)
        validate_error(res, ApiErrorId.ERR_BLOCKED_BY_INCIDENT, expected_status=409)
        assert fresh_resident(ctx["resident"]["id"])["status"] == "ADMITTED"
        assert fresh_bed(ctx["bed"]["id"])["status"] == "OCCUPIED"


class TestDischargedResidentLockdown:
    def test_withdraw_on_discharged_resident_rejected(self, api):
        """PRD §3.8: "A successful discharge moves the resident `ADMITTED` →
        `DISCHARGED` — terminal — stamps `discharged_at` from the clock and copies it
        onto the new discharge record, returns the occupied bed to `AVAILABLE`,
        discontinues every remaining `ACTIVE` medication order, recomputes the home's
        `current_census`, and switches invoice generation for the occupancy window to
        the final, chronological variant of §3.7."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/resident_terminal_discharged_lockdown
        """
        ctx = setup_admitted_resident()
        discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                               notice_days=30, clock="2026-06-05T09:00:00Z")
        assert fresh_resident(ctx["resident"]["id"])["status"] == "DISCHARGED"
        res = api.withdraw_resident(ctx["resident"]["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestDischargeRecordRetrieval:
    def test_discharge_records_listable_after_discharge(self, api):
        """PRD §3.8: "The discharge record itself, carrying `reason`, `notice_days`,
        `discharged_at`, and `refund_amount_cents`, is append-only per §2.5."
        PRD §4: "Collection endpoints accept `limit` and `offset` for pagination
        plus resource-appropriate filters: `status` on most collections, `payer_type`
        on resident and rate-schedule listings, `severity` on incident listings, and
        the foreign-key filters `resident_id`, `bed_id`, `assessment_id`, `order_id`,
        `caregiver_id`, `home_id`, `incident_id`, and `invoice_id` where a collection
        is reachable through multiple parents."

        Design: Corner/endpoints/discharge_records_listable_after_discharge
        """
        ctx = setup_admitted_resident()
        record = discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                                        notice_days=30, clock="2026-06-05T09:00:00Z")
        data, meta = validate_paginated(api.list_discharge_records(
            PROVIDER, params={"resident_id": ctx["resident"]["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == record["id"]
        assert data[0]["reason"] == "VOLUNTARY"
        assert data[0]["notice_days"] == 30

    def test_discharge_refund_zero_without_prepaid_days(self, api):
        """PRD §3.8: "The remainder — never below zero, since negative refunds are
        not issued — is the refund, and it is applied against the final invoice."

        Design: Corner/endpoints/discharge_records_listable_after_discharge
        """
        ctx = setup_admitted_resident()
        record = discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                                        notice_days=30, clock="2026-06-05T09:00:00Z")
        assert record["refund_amount_cents"] == 0, \
            "with no payments at all, the waterfall leaves a zero-floor refund"
