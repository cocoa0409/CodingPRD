"""Inspections and the rework loop: PASS/FAIL cascades, resubmission, the
one-open-inspection rule, terminal-inspection lockout, and DRAFT-invoice holds."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_entry,
    create_draft_invoice,
    create_inspection_payload,
    report_production,
    schedule_inspection,
    setup_field_scenario,
    submit_inspection_result,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
INSPECTOR = TEST_USERS["utility_inspector_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def _rework_scenario(api, contract_number="C-400"):
    """Field setup with one SUBMITTED entry of 10 units and its SCHEDULED
    inspection. Returns (scenario, entry, inspection)."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": contract_number},
        bid_item_overrides={"item_code": "OH-XARM",
                            "description": "Crossarm install",
                            "unit_price": 20.00, "estimated_quantity": 100},
        wp_overrides={"name": "Pole top refit", "location": "Sub 7 feeder A"},
        crew_overrides={"crew_code": "CR-R"},
        equipment_overrides={"equipment_code": "EQ-R"})
    entry = report_production(scenario["assignment"]["id"],
                              scenario["bid_item"]["id"], "2026-08-04", 10)
    inspection = schedule_inspection(scenario["work_package"]["id"], entry["id"],
                                     "UTIL-OH-12.4")
    return scenario, entry, inspection


class TestReworkCycle:
    def test_fail_inspection_marks_rework_and_counts_open(self, api):
        """PRD §3.5: "A failing result moves the inspection to `FAILED` and the
        entry from `SUBMITTED` to `REWORK_REQUIRED`, which raises the work
        package's `rework_open_count` by one — and when that counter rises from
        zero to one, every `DRAFT` invoice of the work package takes on a
        `hold_reason` of `OPEN_REWORK`, flagging that billing is blocked until
        the rework clears."

        Design: Difficulty/non_linear_state_machine/production_entry_rework_cycle
        """
        scenario, entry, inspection = _rework_scenario(api)
        wp_id = scenario["work_package"]["id"]

        failed = submit_inspection_result(inspection["id"], "FAIL")
        assert failed["status"] == "FAILED"

        entry_after = validate_success(api.get_production_entry(entry["id"], FOREMAN))
        assert entry_after["status"] == "REWORK_REQUIRED", (
            "A failing result moves the entry from SUBMITTED to REWORK_REQUIRED")
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["rework_open_count"] == 1, (
            "The failure raises rework_open_count from 0 to 1")

    def test_resubmit_and_pass_closes_rework_loop(self, api):
        """PRD §3.3: "resubmission re-applies the quantity ceiling exactly as at
        creation — `ERR_QUANTITY_CAP_EXCEEDED` again on excess — returns the
        entry to `SUBMITTED`, increments its `rework_count` by one, decrements
        the work package's `rework_open_count` by one, and, when that counter
        falls back to zero, clears the `hold_reason` of every `DRAFT` invoice of
        the work package to null."
        PRD §3.5: "A passing result moves the inspection to `PASSED` and the
        production entry from `SUBMITTED` to `ACCEPTED`, which adds the entry's
        `quantity_reported` to the bid item's `accepted_quantity` and forces
        every `DRAFT` invoice of the work package to recompute its lines,
        `subtotal`, `retainage_amount`, and `amount_due`."

        Design: Difficulty/non_linear_state_machine/production_entry_rework_cycle
        """
        scenario, entry, inspection = _rework_scenario(api)
        wp_id = scenario["work_package"]["id"]
        bid_id = scenario["bid_item"]["id"]
        submit_inspection_result(inspection["id"], "FAIL")

        resubmitted = validate_success(
            api.resubmit_production_entry(entry["id"], FOREMAN))
        assert resubmitted["status"] == "SUBMITTED", (
            "Resubmission returns the entry to SUBMITTED")
        assert resubmitted["rework_count"] == 1, (
            "Resubmission increments rework_count by one")
        wp_mid = validate_success(api.get_work_package(wp_id, PM))
        assert wp_mid["rework_open_count"] == 0, (
            "Resubmission decrements rework_open_count back to zero")

        accept_entry(wp_id, entry["id"], )
        entry_final = validate_success(api.get_production_entry(entry["id"], FOREMAN))
        assert entry_final["status"] == "ACCEPTED"
        bid_item = validate_success(api.get_bid_item(bid_id, PM))
        assert bid_item["accepted_quantity"] == 10, (
            "The passed re-inspection adds the entry's quantity to the bid item")
        wp_final = validate_success(api.get_work_package(wp_id, PM))
        assert wp_final["rework_open_count"] == 0


class TestInspectionUniqueness:
    def test_second_open_inspection_on_entry_rejected(self, api):
        """PRD §3.5: "At most one inspection per production entry may be open at
        a time: scheduling a second while one still stands `SCHEDULED` is
        rejected with `ERR_INSPECTION_ALREADY_OPEN`."

        Design: Corner/validations/second_open_inspection_on_entry_rejected
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CV-10"},
            wp_overrides={"name": "WP io", "location": "L16"},
            crew_overrides={"crew_code": "CR-IO"},
            equipment_overrides={"equipment_code": "EQ-IO"})
        entry = report_production(scenario["assignment"]["id"],
                                  scenario["bid_item"]["id"], "2026-08-04", 5)
        schedule_inspection(scenario["work_package"]["id"], entry["id"],
                            "UTIL-OH-1.0")
        resp = api.create_inspection(
            scenario["work_package"]["id"],
            create_inspection_payload(entry["id"], "UTIL-OH-2.0"),
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_ALREADY_OPEN)

    def test_inspection_resubmit_after_terminal_rejected(self, api):
        """PRD §3.5: "The inspector records a `result` of `PASS` or `FAIL`; the
        entry under inspection must still stand in `SUBMITTED`, or the
        submission fails with `ERR_INVALID_STATE`."
        After the pass the entry stands ACCEPTED, so a second submission against
        the same inspection has no valid source state.

        Design: Corner/state_machines/inspection_resubmit_after_terminal_rejected
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CS-4"},
            wp_overrides={"name": "WP insp", "location": "L4"},
            crew_overrides={"crew_code": "CR-IS"},
            equipment_overrides={"equipment_code": "EQ-IS"})
        entry = report_production(scenario["assignment"]["id"],
                                  scenario["bid_item"]["id"], "2026-08-04", 5)
        inspection = schedule_inspection(scenario["work_package"]["id"],
                                         entry["id"], "UTIL-OH-1.0")
        passed = submit_inspection_result(inspection["id"], "PASS")
        assert passed["status"] == "PASSED"

        resp = api.submit_inspection(inspection["id"], {"result": "FAIL"}, INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        inspection_after = validate_success(api.get_inspection(inspection["id"], PM))
        assert inspection_after["status"] == "PASSED", (
            "The terminal inspection is unchanged by the rejected resubmission")
        entry_after = validate_success(api.get_production_entry(entry["id"], PM))
        assert entry_after["status"] == "ACCEPTED", (
            "The accepted entry is unchanged by the rejected resubmission")


class TestInvoiceHoldCascade:
    def _held_invoice_scenario(self, api):
        """Entry SUBMITTED with a SCHEDULED inspection and a DRAFT invoice
        already created for the covering period (hold_reason still null)."""
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "C-500"},
            bid_item_overrides={"item_code": "OH-FUSE",
                                "description": "Fused cutout",
                                "unit_price": 20.00, "estimated_quantity": 50},
            wp_overrides={"name": "Cutout retrofit", "location": "Feeder F-3"},
            crew_overrides={"crew_code": "CR-F"},
            equipment_overrides={"equipment_code": "EQ-F"})
        wp_id = scenario["work_package"]["id"]
        entry = report_production(scenario["assignment"]["id"],
                                  scenario["bid_item"]["id"], "2026-08-04", 10)
        inspection = schedule_inspection(wp_id, entry["id"], "UTIL-OH-12.4")
        invoice = create_draft_invoice(wp_id, "2026-08-01", "2026-08-31")
        assert invoice["status"] == "DRAFT"
        assert invoice["hold_reason"] is None
        return scenario, entry, inspection, invoice

    def test_fail_cascade_sets_invoice_hold_reason(self, api):
        """PRD §3.5: "A failing result moves the inspection to `FAILED` and the
        entry from `SUBMITTED` to `REWORK_REQUIRED`, which raises the work
        package's `rework_open_count` by one — and when that counter rises from
        zero to one, every `DRAFT` invoice of the work package takes on a
        `hold_reason` of `OPEN_REWORK`, flagging that billing is blocked until
        the rework clears."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_invoice_hold
        """
        scenario, entry, inspection, invoice = self._held_invoice_scenario(api)
        wp_id = scenario["work_package"]["id"]

        submit_inspection_result(inspection["id"], "FAIL")

        entry_after = validate_success(api.get_production_entry(entry["id"], PM))
        assert entry_after["status"] == "REWORK_REQUIRED"
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["rework_open_count"] == 1
        invoice_after = validate_success(api.get_invoice(invoice["id"], PM))
        assert invoice_after["hold_reason"] == "OPEN_REWORK", (
            "The DRAFT invoice takes on hold_reason OPEN_REWORK when the "
            "counter rises from zero to one")
        assert invoice_after["status"] == "DRAFT"

    def test_held_invoice_submit_blocked_open_rework(self, api):
        """PRD §3.9: "A transition with `to` set to `SUBMITTED` requires the work
        package's `rework_open_count` to be zero — open rework blocks billing
        with `ERR_OPEN_REWORK` — and at least one line whose in-schedule plus
        overrun units exceed zero, otherwise `ERR_NO_BILLABLE_UNITS` (HTTP 422)."
        PRD §3.9: "The `hold_reason` field, set to `OPEN_REWORK` on drafts while
        rework stands open per §3.5, must have cleared before submission can
        succeed."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_to_invoice_hold
        """
        scenario, entry, inspection, invoice = self._held_invoice_scenario(api)
        submit_inspection_result(inspection["id"], "FAIL")

        resp = api.transition_invoice(invoice["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_REWORK)
        invoice_after = validate_success(api.get_invoice(invoice["id"], PM))
        assert invoice_after["status"] == "DRAFT", (
            "The blocked submission leaves the invoice in DRAFT")
        assert invoice_after["hold_reason"] == "OPEN_REWORK"


class TestInspectionRbac:
    def test_safety_officer_cannot_create_inspection(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/work-packages/{work_package_id}/inspections` |
        Schedule a utility-standard inspection of a `SUBMITTED` production entry
        | UTILITY_INSPECTOR |"

        Design: Corner/rbac/safety_officer_cannot_create_inspection
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CR-2"},
            wp_overrides={"name": "WP rb2", "location": "L25"},
            crew_overrides={"crew_code": "CR-RB"},
            equipment_overrides={"equipment_code": "EQ-RB"})
        entry = report_production(scenario["assignment"]["id"],
                                  scenario["bid_item"]["id"], "2026-08-04", 5)
        resp = api.create_inspection(
            scenario["work_package"]["id"],
            create_inspection_payload(entry["id"], "UTIL-OH-1.0"),
            SAFETY)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        inspections, meta = validate_paginated(api.list_inspections(
            PM, params={"production_entry_id": entry["id"]}))
        assert meta["total_count"] == 0, (
            "The forbidden call creates no inspection for the entry")
