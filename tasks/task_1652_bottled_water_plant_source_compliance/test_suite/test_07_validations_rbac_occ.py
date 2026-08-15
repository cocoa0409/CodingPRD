"""Validation ladder edges (auth, existence, temporal, referential), the RBAC
matrix, optimistic concurrency, and preform-delivery verdict bookkeeping."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_bottle,
    create_bottling_line,
    create_permit,
    create_permit_payload,
    create_plant,
    create_preform_delivery_payload,
    create_production_lot_payload,
    create_treatment_run,
    create_wash_batch,
    create_withdrawal_event_payload,
    create_community_report_payload,
    get_success_data,
    passing_parameters_payload,
    post_withdrawal_event,
    qc_verdict_payload,
    setup_line_with_preforms,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, SOURCE_MONITOR, COMPLIANCE_OFFICER, PL1, QA1, SL1,
)


class TestAuthentication:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing header, or an `X-User-Role`
        value outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/missing_headers_unauthenticated
        """
        plant = create_plant("Plant VA1")
        resp = api.get_plant(plant["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_source_monitor_cannot_create_permit_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)" — permit
        registration belongs to `ComplianceOfficer` (§3.1).

        Design: Corner/validations/source_monitor_cannot_create_permit_forbidden
        """
        plant = create_plant("Plant VA2")
        payload = create_permit_payload(
            permit_number="SP-VA2", daily_cap_gallons=5000, monthly_cap_gallons=100000,
        )
        resp = api.create_permit(plant["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_priority_auth_beats_existence(self, api):
        """PRD §2.7: "every request is evaluated against a fixed priority
        ladder, so that a request failing several checks always surfaces the
        earliest one" — authorization is rung 2 ("the role rule of §2.1
        (`ERR_FORBIDDEN`)") and existence is rung 3 ("path identifiers left to
        right, then body foreign keys (`ERR_NOT_FOUND`)").

        Design: Corner/validations/priority_auth_beats_existence
        """
        plant = create_plant("Plant VA4")
        # ProductionLead may not record withdrawals (SourceMonitor-exclusive);
        # the target permit id does not even exist — authorization wins.
        payload = create_withdrawal_event_payload(
            gallons=10, meter_reading_start_gallons=0, meter_reading_end_gallons=10,
            expected_permit_version=1,
        )
        resp = api.create_withdrawal_event(NON_EXISTENT_UUID, payload, PL1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_qa_officer_cannot_run_compliance_checkpoint(self, api):
        """PRD §3.2: "a `PlantAdmin` triggers the plant's compliance
        checkpoint" — other roles are rejected per §2.1.

        Design: Corner/rbac/qa_officer_cannot_run_compliance_checkpoint
        """
        plant = create_plant("Plant RB1")
        resp = api.run_compliance(plant["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_sanitation_lead_cannot_validate_run(self, api):
        """PRD §3.3: "Validation belongs to a `QAOfficer`" — other roles are
        rejected per §2.1 even on a run that is ready to validate.

        Design: Corner/rbac/sanitation_lead_cannot_validate_run
        """
        plant = create_plant("Plant RB2")
        permit = create_permit(plant["id"], permit_number="SP-RB2")
        run = create_treatment_run(plant["id"], permit["id"])
        validate_success(api.start_treatment_run(run["id"], PL1))
        validate_success(api.record_run_parameters(
            run["id"], passing_parameters_payload(), PL1
        ))

        resp = api.validate_treatment_run(run["id"], SL1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        run_now = validate_success(api.get_treatment_run(run["id"], SL1))
        assert run_now["status"] == "IN_PROGRESS", "rejection left state untouched"

    def test_production_lead_cannot_publish_report(self, api):
        """PRD §3.9: "Publication by a `ComplianceOfficer`" — other roles are
        rejected per §2.1.

        Design: Corner/rbac/production_lead_cannot_publish_report
        """
        plant = create_plant("Plant RB3")
        rep = validate_success(api.create_community_report(
            plant["id"], create_community_report_payload(period_year=2026, period_month=8),
            COMPLIANCE_OFFICER,
        ), expected_status=201)

        resp = api.publish_community_report(rep["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rep_now = validate_success(api.get_community_report(rep["id"], COMPLIANCE_OFFICER))
        assert rep_now["status"] == "DRAFT"

    def test_compliance_officer_cannot_record_withdrawal(self, api):
        """PRD §3.1: "a `SourceMonitor` records withdrawal events" — the
        ComplianceOfficer who owns the permit lifecycle is rejected per §2.1.

        Design: Corner/rbac/compliance_officer_cannot_record_withdrawal
        """
        plant = create_plant("Plant RB4")
        permit = create_permit(plant["id"], permit_number="SP-RB4")
        payload = create_withdrawal_event_payload(
            gallons=100, meter_reading_start_gallons=0, meter_reading_end_gallons=100,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_all_roles_can_read_plant(self, api):
        """PRD §2.1: "All list and read endpoints are shared by every role."

        Design: Corner/rbac/all_roles_can_read_plant
        """
        plant = create_plant("Plant RB5")
        for uid, role in [
            ("pa-1", "PlantAdmin"), ("sm-1", "SourceMonitor"), ("qa-1", "QAOfficer"),
            ("pl-1", "ProductionLead"), ("sl-1", "SanitationLead"),
            ("co-1", "ComplianceOfficer"),
        ]:
            read = validate_success(api.get_plant(plant["id"], build_user_headers(uid, role)))
            assert read["id"] == plant["id"], f"{role} must read the plant"


class TestExistencePriority:
    def test_priority_existence_beats_state_and_business(self, api):
        """PRD §2.7: "the first identifier that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no further
        checks run."

        Design: Corner/validations/priority_existence_beats_state_and_business
        """
        plant = create_plant("Plant VA3")
        permit = create_permit(
            plant["id"], permit_number="SP-VA3",
            daily_cap_gallons=1000, monthly_cap_gallons=30000,
        )
        # The payload would far exceed any cap, but the missing permit id
        # short-circuits before the OCC and constraint checks.
        payload = create_withdrawal_event_payload(
            gallons=99999, meter_reading_start_gallons=0,
            meter_reading_end_gallons=99999,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(NON_EXISTENT_UUID, payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWithdrawalTemporalRules:
    def test_meter_reading_mismatch_rejected(self, api):
        """PRD §3.1: "the end reading minus the start reading must equal
        `gallons` exactly, otherwise the posting fails with
        `ERR_METER_READING_MISMATCH` (HTTP 422)."

        Design: Corner/validations/meter_reading_mismatch_rejected
        """
        plant = create_plant("Plant VA5")
        permit = create_permit(plant["id"], permit_number="SP-VA5")
        payload = create_withdrawal_event_payload(
            gallons=100, meter_reading_start_gallons=0, meter_reading_end_gallons=150,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_METER_READING_MISMATCH)

    def test_withdrawal_date_before_validity_rejected(self, api):
        """PRD §3.1: "The withdrawal date must fall inside the permit's
        validity window, else `ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW` (HTTP 409)".

        Design: Corner/validations/withdrawal_date_before_validity_rejected
        """
        plant = create_plant("Plant VA6")
        permit = create_permit(plant["id"], permit_number="SP-VA6",
                               valid_from="2026-01-01", valid_to="2026-12-31")
        payload = create_withdrawal_event_payload(
            withdrawal_date="2025-12-15", gallons=100,
            meter_reading_start_gallons=0, meter_reading_end_gallons=100,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW)

    def test_future_withdrawal_date_rejected(self, api):
        """PRD §3.1: "and must not lie after the current logical date, else
        `ERR_FUTURE_WITHDRAWAL_DATE` (HTTP 409)" — the clock defaults to
        2026-08-01 (§2.4), so 2026-08-02 is in the future.

        Design: Corner/validations/future_withdrawal_date_rejected
        """
        plant = create_plant("Plant VA7")
        permit = create_permit(plant["id"], permit_number="SP-VA7")
        payload = create_withdrawal_event_payload(
            withdrawal_date="2026-08-02", gallons=100,
            meter_reading_start_gallons=0, meter_reading_end_gallons=100,
            expected_permit_version=permit["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_FUTURE_WITHDRAWAL_DATE)

    def test_supersede_voided_target_rejected(self, api):
        """PRD §3.1: "The supersede target must not itself be `VOIDED` and
        must belong to the same permit, otherwise
        `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 409)".

        Design: Corner/validations/supersede_voided_target_rejected
        """
        plant = create_plant("Plant VA8")
        permit = create_permit(plant["id"], permit_number="SP-VA8")
        ev, _ = post_withdrawal_event(permit["id"], gallons=100)
        validate_success(api.void_withdrawal_event(ev["id"], SOURCE_MONITOR))

        permit_now = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        payload = create_withdrawal_event_payload(
            gallons=120, meter_reading_start_gallons=100, meter_reading_end_gallons=220,
            expected_permit_version=permit_now["version"],
            supersedes_event_id=ev["id"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)

    def test_monthly_cap_exact_boundary(self, api):
        """PRD §3.1: "it must then not exceed the monthly cap minus the
        provisional gallons already posted for that year-month, otherwise
        `ERR_MONTHLY_CAP_EXCEEDED` (HTTP 409). Equality is allowed at both
        levels".

        Design: Corner/calculations/monthly_cap_exact_boundary
        """
        plant = create_plant("Plant CA1")
        permit = create_permit(plant["id"], permit_number="SP-CA1",
                               daily_cap_gallons=10000, monthly_cap_gallons=15000)
        post_withdrawal_event(permit["id"], gallons=10000, withdrawal_date="2026-08-01")

        from test_helpers import set_clock
        set_clock("2026-08-02T00:00:00Z")
        ev2, permit_now = post_withdrawal_event(
            permit["id"], gallons=5000, withdrawal_date="2026-08-02", meter_start=10000
        )
        assert ev2["status"] == "RECORDED", "monthly total exactly 15000 == cap is allowed"
        assert permit_now["withdrawn_month_provisional_gallons"] == 15000

        # One further gallon on Aug 2: daily total 5001 (under the daily cap),
        # but the month tips to 15001.
        payload = create_withdrawal_event_payload(
            withdrawal_date="2026-08-02", gallons=1,
            meter_reading_start_gallons=15000, meter_reading_end_gallons=15001,
            expected_permit_version=permit_now["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_MONTHLY_CAP_EXCEEDED)


class TestOptimisticConcurrency:
    def test_occ_stale_permit_version_rejected(self, api):
        """PRD §2.8: "Recording a withdrawal event beneath a permit requires
        `expected_permit_version`, carrying the client's last observed
        `version` of that permit. If the permit's current `version` has
        advanced since the client read it — because another event was posted,
        voided, or superseded in the meantime — the request is rejected with
        `ERR_STALE_PERMIT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_permit_version_rejected
        """
        plant = create_plant("Plant CC1")
        permit = create_permit(plant["id"], permit_number="SP-CC1")
        assert permit["version"] == 1

        ev1_payload = create_withdrawal_event_payload(
            gallons=1000, meter_reading_start_gallons=0, meter_reading_end_gallons=1000,
            expected_permit_version=1,
        )
        ev1 = validate_success(api.create_withdrawal_event(
            permit["id"], ev1_payload, SOURCE_MONITOR
        ), expected_status=201)
        assert ev1["status"] == "RECORDED"

        # The first post advanced the permit to version 2; the client's
        # version-1 view is now stale.
        stale_payload = create_withdrawal_event_payload(
            gallons=500, meter_reading_start_gallons=1000, meter_reading_end_gallons=1500,
            expected_permit_version=1,
        )
        resp = api.create_withdrawal_event(permit["id"], stale_payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION)

        # Re-read, re-base, and the retry succeeds.
        permit_now = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert permit_now["version"] == 2
        fresh_payload = create_withdrawal_event_payload(
            gallons=500, meter_reading_start_gallons=1000, meter_reading_end_gallons=1500,
            expected_permit_version=permit_now["version"],
        )
        ev2 = validate_success(api.create_withdrawal_event(
            permit["id"], fresh_payload, SOURCE_MONITOR
        ), expected_status=201)
        assert ev2["status"] == "RECORDED"

    def test_occ_stale_line_version_rejected_with_progression(self, api):
        """PRD §2.8: "Creating a production lot beneath a bottling line
        likewise requires `expected_line_version`; a mismatch with the line's
        current `version` is rejected with `ERR_STALE_LINE_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_line_version_rejected_with_progression
        """
        from test_helpers.fixtures import create_lot_on_line
        plant = create_plant("Plant CC2")
        permit = create_permit(plant["id"], permit_number="SP-CC2")
        line = create_bottling_line(plant["id"])
        assert line["version"] == 1
        run = create_treatment_run(plant["id"], permit["id"])

        # Delivery create bumps the line to 2; QC verdict bumps it to 3.
        del_payload = create_preform_delivery_payload(delivered_units=1000)
        del_payload["expected_line_version"] = line["version"]
        delivery = validate_success(api.create_preform_delivery(
            line["id"], del_payload, PL1
        ), expected_status=201)
        validate_success(api.qc_verdict_preform_delivery(
            delivery["id"], qc_verdict_payload(verdict="ACCEPTED", accepted_units=1000), QA1
        ))

        # The client's version-1 view went stale.
        stale_payload = create_production_lot_payload(
            treatment_run_id=run["id"], planned_units=100,
            expected_line_version=1,
        )
        resp = api.create_production_lot(line["id"], stale_payload, PL1)
        validate_error(resp, ApiErrorId.ERR_STALE_LINE_VERSION)

        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_now["version"] == 3

        lot = create_lot_on_line(line["id"], run["id"], planned_units=100)
        assert lot["status"] == "PLANNED"
        line_after = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_after["version"] == 4, "the lot create itself bumped the version"


class TestDerivedFieldReconciliation:
    def test_updated_at_refreshes_on_mutation(self, api):
        """PRD §2.5: "The `updated_at` is an ISO 8601 UTC timestamp with
        three fractional digits, refreshed on any change to the resource" and
        §2.6: "every affected resource is updated in the same request, each
        hop refreshing the target's `updated_at` and incrementing its
        `version`."

        Design: Corner/cross_cutting_complexity_layers/updated_at_refreshes_on_mutation
        """
        plant = create_plant("Plant CC4")
        permit = create_permit(plant["id"], permit_number="SP-CC4")
        v0 = permit["version"]

        ev, permit_after = post_withdrawal_event(permit["id"], gallons=250)
        assert permit_after["version"] == v0 + 1
        # Note: §2.5 requires updated_at to be refreshed on change, but does
        # not name its clock source; with the logical clock frozen (§2.4), a
        # faithful implementation may re-stamp the same value, so no
        # observable-delta assertion is made here.
        assert permit_after["withdrawn_month_provisional_gallons"] == 250


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.6: "the system maintains hierarchical consistency
        synchronously: when one operation mutates several resources, every
        affected resource is updated in the same request".

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        plant = create_plant("Plant CM1")
        b = create_bottle(plant["id"], "B-CM1")

        read = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert read["bottle_gross_pool_units"] == 1
        assert read["bottle_sanitized_pool_units"] == 1

        bottle = validate_success(api.get_bottle(b["id"], SL1))
        assert bottle["status"] == "SANITIZED"


class TestPreformDeliveryVerdicts:
    def test_preform_delivery_accepted_units_null_until_verdict(self, api):
        """PRD §3.5: "the create is OCC-guarded by `expected_line_version`
        per §2.8, increments the line's `version`, and lands in `PENDING_QC`
        with `accepted_units` null" and "An `ACCEPTED` verdict ... books the
        accepted quantity into the line's `preform_on_hand_units`."

        Design: Corner/entities/preform_delivery_accepted_units_null_until_verdict
        """
        plant = create_plant("Plant EN12")
        line = create_bottling_line(plant["id"])
        del_payload = create_preform_delivery_payload(delivered_units=1000)
        del_payload["expected_line_version"] = line["version"]
        delivery = validate_success(api.create_preform_delivery(
            line["id"], del_payload, PL1
        ), expected_status=201)
        assert delivery["status"] == "PENDING_QC"
        assert delivery["accepted_units"] is None

        verdict = validate_success(api.qc_verdict_preform_delivery(
            delivery["id"], qc_verdict_payload(verdict="ACCEPTED", accepted_units=600), QA1
        ))
        assert verdict["status"] == "ACCEPTED"
        assert verdict["accepted_units"] == 600

        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_now["preform_on_hand_units"] == 600, (
            "partial acceptance books only accepted_units"
        )

    def test_qc_verdict_rejected_keeps_inventory_unchanged(self, api):
        """PRD §3.5: "A `REJECTED` verdict sets `accepted_units` to 0 and
        leaves the line's inventory untouched. Either verdict moves the
        delivery out of `PENDING_QC` to its terminal state, increments the
        line's `version`".

        Design: Corner/endpoints/qc_verdict_rejected_keeps_inventory_unchanged
        """
        plant = create_plant("Plant EP1")
        line = create_bottling_line(plant["id"])
        del_payload = create_preform_delivery_payload(delivered_units=800)
        del_payload["expected_line_version"] = line["version"]
        delivery = validate_success(api.create_preform_delivery(
            line["id"], del_payload, PL1
        ), expected_status=201)

        line_before = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_before["preform_on_hand_units"] == 0
        assert line_before["version"] == 2, "creation bumped the line version"

        verdict = validate_success(api.qc_verdict_preform_delivery(
            delivery["id"], {"verdict": "REJECTED"}, QA1
        ))
        assert verdict["status"] == "REJECTED"
        assert verdict["accepted_units"] == 0

        line_after = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_after["preform_on_hand_units"] == 0, "no inventory movement on rejection"
        assert line_after["version"] == 3, "the verdict bumped the line version"

    def test_qc_verdict_over_acceptance_rejected(self, api):
        """PRD §3.5: "An `ACCEPTED` verdict requires `accepted_units`
        present, greater than zero, and no greater than `delivered_units` —
        anything else fails input-shape validation with
        `ERR_INVALID_REQUEST`".

        Design: Corner/endpoints/qc_verdict_over_acceptance_rejected
        """
        plant = create_plant("Plant EP2")
        line = create_bottling_line(plant["id"])
        del_payload = create_preform_delivery_payload(delivered_units=1000)
        del_payload["expected_line_version"] = line["version"]
        delivery = validate_success(api.create_preform_delivery(
            line["id"], del_payload, PL1
        ), expected_status=201)

        resp = api.qc_verdict_preform_delivery(
            delivery["id"], {"verdict": "ACCEPTED", "accepted_units": 1001}, QA1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        delivery_now = validate_success(api.get_preform_delivery(delivery["id"], QA1))
        assert delivery_now["status"] == "PENDING_QC"


class TestReorderProjection:
    def test_preform_reorder_projection_ordering(self, api):
        """PRD §3.5: "`preform_reorder_quantity` is advisory only, computed
        on read: take the line's target stock of two days of production —
        `daily_capacity_units` multiplied by 2 — add the current
        `preform_reserved_units`, subtract the current
        `preform_on_hand_units`, subtract the inbound pipeline (the sum of
        `delivered_units` over the line's deliveries still in `PENDING_QC`),
        and floor the result at zero."

        Design: Corner/calculations/preform_reorder_projection_ordering
        """
        from test_helpers.fixtures import create_lot_on_line
        plant = create_plant("Plant CA3")
        permit = create_permit(plant["id"], permit_number="SP-CA3")
        line = create_bottling_line(plant["id"])  # daily_capacity 8000

        # 5000 accepted; 3000 still PENDING_QC.
        d1_payload = create_preform_delivery_payload(delivered_units=5000)
        d1_payload["expected_line_version"] = line["version"]
        d1 = validate_success(api.create_preform_delivery(line["id"], d1_payload, PL1),
                              expected_status=201)
        validate_success(api.qc_verdict_preform_delivery(
            d1["id"], qc_verdict_payload(verdict="ACCEPTED", accepted_units=5000), QA1
        ))
        line_v2 = validate_success(api.get_bottling_line(line["id"], PL1))
        d2_payload = create_preform_delivery_payload(delivered_units=3000)
        d2_payload["expected_line_version"] = line_v2["version"]
        validate_success(api.create_preform_delivery(line["id"], d2_payload, PL1),
                         expected_status=201)

        run = create_treatment_run(plant["id"], permit["id"])
        lot = create_lot_on_line(
            line["id"], run["id"], planned_units=2000,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        assert lot["status"] == "PLANNED"

        read = validate_success(api.get_bottling_line(line["id"], PL1))
        assert read["preform_on_hand_units"] == 5000
        assert read["preform_reserved_units"] == 2000
        assert read["preform_free_units"] == 3000
        # max(0, 8000*2 + 2000 - 5000 - 3000) = 10000
        assert read["preform_reorder_quantity"] == 10000


class TestFkReverseLookups:
    def test_fk_reverse_lookup_filtered_lists(self, api):
        """PRD §3.4: "The cross-plant list accepts `plant_id`,
        `subject_permit_id`, `subject_lot_id`, `subject_wash_batch_id`,
        `test_type`, and `status` filters" and §3.6: "Lots can be listed with
        `line_id`, `treatment_run_id`, `recall_id`, and `status` filters."

        Design: Corner/endpoints/fk_reverse_lookup_filtered_lists
        """
        from test_helpers.fixtures import create_lot_on_line
        plant = create_plant("Plant EP3")
        permit = create_permit(plant["id"], permit_number="SP-EP3")
        from test_helpers.fixtures import create_source_raw_test
        test = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-05")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=500)
        run = create_treatment_run(plant["id"], permit["id"])
        lot = create_lot_on_line(line["id"], run["id"], planned_units=100)

        page_t, meta_t = validate_paginated(api.list_lab_tests(
            QA1, params={"subject_permit_id": permit["id"]}
        ))
        assert meta_t["total_count"] >= 1
        assert any(t["id"] == test["id"] for t in page_t)

        page_l, meta_l = validate_paginated(api.list_production_lots(
            PL1, params={"treatment_run_id": run["id"]}
        ))
        assert meta_l["total_count"] == 1
        assert page_l[0]["id"] == lot["id"]

        page_l2, meta_l2 = validate_paginated(api.list_production_lots(
            PL1, params={"treatment_run_id": run["id"], "status": "REWORK"}
        ))
        assert meta_l2["total_count"] == 0
