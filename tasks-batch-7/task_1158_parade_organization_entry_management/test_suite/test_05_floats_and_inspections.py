"""Float registration, safety inspection, segregation of duties, and the
inspection-fail suspension cascade."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, assert_float, assert_entry,
)

COMMITTEE = th.make_committee_admin_headers()
ENTRANT1 = th.make_entrant_headers("entrant_1")
INSP1 = th.make_safety_inspector_headers("insp_1")
INSP2 = th.make_safety_inspector_headers("insp_2")


class TestFloatRegistration:

    def test_float_for_band_entry_rejected(self, api):
        """PRD §3.4: "Float registration is open to the owning entrant only
        once the entry stands `APPROVED`, and only when its `assigned_category`
        is `FLOAT` or `VEHICLE`; an attempt for any other category is rejected
        with `ERR_CATEGORY_WITHOUT_FLOAT` (HTTP 422)."

        Design: Corner/validations/float_for_band_entry_rejected_category
        """
        parade = th.create_parade(name="Category Parade")
        entry = th.create_approved_entry(parade["id"], "entrant_1", category="BAND")
        resp = api.create_float(
            entry["id"],
            th.create_float_payload(length_m=5, width_m=2, height_m=2, weight_kg=500,
                                    vehicle_class="PUSHED", fuel_type="NONE"),
            ENTRANT1,
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_WITHOUT_FLOAT)


class TestReinspectionSegregation:

    def _failed_float(self, api, parade_name="SoD Parade"):
        """APPROVED FLOAT entry whose float FAILED under insp_1."""
        parade = th.create_parade(name=parade_name)
        entry = th.create_approved_entry(parade["id"], "entrant_1", category="FLOAT",
                                         estimated_participants=50)
        float_obj = get_success_data(
            api.create_float(entry["id"], th.create_float_payload(), ENTRANT1)
        )
        inspection = get_success_data(
            api.schedule_inspection(float_obj["id"], th.schedule_inspection_payload(), INSP1)
        )
        get_success_data(api.fail_inspection(inspection["id"], {"checklist_score": 50}, INSP1))
        return parade, entry, float_obj

    def test_reinspection_by_same_inspector_rejected_sod(self, api):
        """PRD §3.4: "Segregation of duties governs re-inspection: the
        inspector of a new inspection must differ from the inspector who
        recorded the float's latest `FAILED` inspection, and a violation is
        rejected with `ERR_REINSPECTION_SOD` (HTTP 422)."

        Design: Corner/validations/reinspection_by_same_inspector_rejected_sod
        """
        _, _, float_obj = self._failed_float(api)
        resp = api.schedule_inspection(
            float_obj["id"], th.schedule_inspection_payload(scheduled_at="2026-06-28T09:00:00Z"),
            INSP1,
        )
        validate_error(resp, ApiErrorId.ERR_REINSPECTION_SOD)

        _, meta = validate_paginated(api.list_inspections(float_obj["id"], COMMITTEE))
        assert meta["total_count"] == 1, "no new inspection may be persisted"

    def test_reinspection_pass_by_different_inspector_reinstates_entry(self, api):
        """PRD §3.4: "Passing requires a score of at least 70 — a pass
        attempted with a lower score is `ERR_VALIDATION` — and stamps
        `decided_at` from the logical clock; the float then transitions from
        `PENDING_INSPECTION` to `CERTIFIED`, and if the parent entry had been
        sitting in `SUSPENDED`, it is compensated back to `APPROVED` with the
        parade's `approved_entry_count` recomputed."
        PRD §3.4: "scheduling one against a float currently in `FAILED`
        compliance returns the float to `PENDING_INSPECTION` so the cycle can
        restart."

        Design: Corner/validations/reinspection_pass_by_different_inspector_reinstates_entry
        """
        parade, entry, float_obj = self._failed_float(api, parade_name="Reinstate Parade")
        suspended = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert suspended["status"] == "SUSPENDED", "setup: the failure must suspend the entry"

        inspection2 = get_success_data(
            api.schedule_inspection(
                float_obj["id"],
                th.schedule_inspection_payload(scheduled_at="2026-06-28T09:00:00Z"),
                INSP2,
            )
        )
        passed = validate_success(
            api.pass_inspection(inspection2["id"], {"checklist_score": 80}, INSP2)
        )
        assert passed["status"] == "PASSED"

        float_after = validate_success(api.get_float(float_obj["id"], COMMITTEE))
        assert_float(float_after)
        assert float_after["compliance_status"] == "CERTIFIED"

        entry_after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert entry_after["status"] == "APPROVED", (
            "the suspension must be compensated back to APPROVED"
        )
        parade_after = validate_success(api.get_parade(parade["id"], COMMITTEE))
        assert parade_after["approved_entry_count"] == 1


class TestInspectionFailCascade:
    """Difficulty: inspection_fail_suspends_entry_pulls_assignment."""

    def _setup(self, api):
        """OPERATIONAL parade; certified+paid FLOAT entry; CONFIRMED
        assignment; APPROVED ENTRY_INTRO; spot re-inspection by insp_2."""
        ctx = th.setup_operational_parade(name="Inspect Parade",
                                          staging_overrides={"name": "Lot B"})
        entry, float_obj = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            vehicle_class="TOWED", fuel_type="NONE",
        )
        assignment = th.create_confirmed_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        item = th.create_approved_intro_item(ctx["parade"]["id"], entry["id"])
        inspection2 = get_success_data(
            api.schedule_inspection(
                float_obj["id"],
                th.schedule_inspection_payload(scheduled_at="2026-06-28T09:00:00Z"),
                INSP2,
            )
        )
        return ctx, entry, float_obj, assignment, item, inspection2

    def test_fail_flips_float_and_suspends_entry(self, api):
        """PRD §3.4: "Failing requires a score strictly below 70 — a fail
        attempted at 70 or above is `ERR_VALIDATION` — and fires a four-hop
        cascade of its own: the float's `compliance_status` becomes `FAILED`;
        the parent entry, if `APPROVED`, drops to `SUSPENDED`; that suspension
        pulls the entry's `CONFIRMED` and `CHECKED_IN` lineup assignments to
        `PULLED`; and each pull releases its staging slot and cancels the
        entry's approved `ENTRY_INTRO` script items."
        PRD §3.4: "A certified float is not immune: a spot re-inspection that
        fails moves the float from `CERTIFIED` to `FAILED` and fires the
        identical suspension cascade."

        Design: Difficulty/transitive_cascade/inspection_fail_suspends_entry_pulls_assignment
        """
        ctx, entry, float_obj, assignment, item, inspection2 = self._setup(api)
        failed = validate_success(
            api.fail_inspection(inspection2["id"], {"checklist_score": 40}, INSP2)
        )
        assert failed["status"] == "FAILED"

        float_after = validate_success(api.get_float(float_obj["id"], COMMITTEE))
        assert float_after["compliance_status"] == "FAILED", "hop 1: float must fail"

        entry_after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert entry_after["status"] == "SUSPENDED", "hop 2: the float failure suspends the entry"

    def test_fail_pulls_assignment_releases_slot_cancels_intro(self, api):
        """PRD §3.4: "Failing requires a score strictly below 70 — a fail
        attempted at 70 or above is `ERR_VALIDATION` — and fires a four-hop
        cascade of its own: the float's `compliance_status` becomes `FAILED`;
        the parent entry, if `APPROVED`, drops to `SUSPENDED`; that suspension
        pulls the entry's `CONFIRMED` and `CHECKED_IN` lineup assignments to
        `PULLED`; and each pull releases its staging slot and cancels the
        entry's approved `ENTRY_INTRO` script items."

        Design: Difficulty/transitive_cascade/inspection_fail_suspends_entry_pulls_assignment
        """
        ctx, entry, float_obj, assignment, item, inspection2 = self._setup(api)
        validate_success(api.fail_inspection(inspection2["id"], {"checklist_score": 40}, INSP2))

        assignment_after = validate_success(api.get_lineup_assignment(assignment["id"], COMMITTEE))
        assert assignment_after["status"] == "PULLED", "hop 3: the suspension pulls the assignment"

        staging_after = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging_after["reserved_slots"] == 0, "hop 4: the pull releases the staging slot"

        item_after = validate_success(api.get_script_item(item["id"], COMMITTEE))
        assert item_after["status"] == "CANCELLED", "hop 4: the pull cancels the ENTRY_INTRO item"
