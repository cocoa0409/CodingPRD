"""Declared cross-cutting layers: version guards, selector filters, immediacy."""

from test_helpers import (
    entries_of_type,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestCasingInspectVersionGuard:
    def test_a_token_superseded_by_the_collect_hop_is_refused(self, api):
        """PRD §2.9: "Recording a casing inspection grade requires
        `expected_casing_version` in the request body as a non-optional field, carrying
        the `version` of the casing as the client last observed it."
        PRD §2.9: "If that value does not equal the casing's current `version`, the
        request is rejected with `ERR_STALE_CASING_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/casing_inspect_with_superseded_version_returns_412
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Occ Commercial",
                "location_code": "OCC",
                "scrap_permit_number": "OH-SCRAP-4045",
            }
        )
        fleet_id = program["fleet"]["id"]
        casing = fixtures.create_casing(
            fleet_id, casing_serial="CS-4045", scrap_weight_lbs=139
        )
        stale_version = casing["version"]
        collected = fixtures.collect_casing(casing["id"], program["location"]["id"])
        assert stale_version == 1
        assert collected["version"] == 2, "the collect hop bumped the row"

        validate_error(
            api.inspect_casing(
                casing["id"],
                factories.inspect_casing_payload("A", stale_version),
                fixtures.inspector_headers(),
            ),
            "ERR_STALE_CASING_VERSION",
            expected_status=412,
        )

        refused = fixtures.read_casing(casing["id"])
        assert refused["status"] == "COLLECTED", (
            "the state was legal for inspection; only the token was wrong"
        )
        assert refused.get("inspection_grade") is None
        assert refused["provisional_credit_cents"] == 0
        assert fixtures.list_casing_ledger(casing["id"]) == []
        assert fixtures.read_fleet(fleet_id)["casing_credit_balance_cents"] == 0

        graded = validate_success(
            api.inspect_casing(
                casing["id"],
                factories.inspect_casing_payload("A", collected["version"]),
                fixtures.inspector_headers(),
            )
        )
        assert graded["status"] == "INSPECTED"
        assert graded["inspection_grade"] == "A"
        assert graded["version"] == 3
        accruals = entries_of_type(
            fixtures.list_casing_ledger(casing["id"]), "ACCRUAL"
        )
        assert [entry["amount_cents"] for entry in accruals] == [12000]
        assert fixtures.read_fleet(fleet_id)["casing_credit_balance_cents"] == 12000


class TestInvoiceFleetVersionGuard:
    def test_a_concurrent_accrual_invalidates_the_clerks_snapshot(self, api):
        """PRD §2.9: "If that value does not equal the fleet account's current
        `version`, the request is rejected with `ERR_STALE_FLEET_VERSION` (HTTP 412)."
        PRD §3.8: "And, as §2.9 requires, a mismatched `expected_fleet_account_version`
        is rejected with `ERR_STALE_FLEET_VERSION` before any of this happens."

        Design: Corner/cross_cutting_complexity_layers/invoice_creation_with_superseded_fleet_version_returns_412
        """
        program = fixtures.setup_national_account_program(
            tier_discount_pct=0.125, casing_credit_rate_cents=15000
        )
        fleet_id = program["fleet"]["id"]
        call = fixtures.setup_billable_call(program)
        assert call["invoice_total_cents"] == fixtures.SMALL_LINE_CENTS

        stale_fleet_version = fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"]
        fixtures.accrue_casing_credit(
            fleet_id,
            program["location"]["id"],
            grade="B",
            casing_serial="CS-4046",
            scrap_weight_lbs=141,
        )
        assert fixtures.read_fleet(fleet_id)["casing_credit_balance_cents"] == 10500, (
            "15000 at the grade-B factor of 0.70 with no retread decay"
        )
        fresh_fleet_version = fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"]
        assert fresh_fleet_version > stale_fleet_version

        validate_error(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-01", "2026-08-31", stale_fleet_version
                ),
                fixtures.CLERK,
            ),
            "ERR_STALE_FLEET_VERSION",
            expected_status=412,
        )

        unclaimed = fixtures.read_call(call["id"])
        assert unclaimed["billing_status"] == "UNBILLED"
        assert unclaimed.get("cross_location_invoice_id") is None
        assert fixtures.count_invoices(fleet_id) == 0, (
            "the version guard sits above the whole fiscal ladder, and this request "
            "was otherwise perfectly billable"
        )

        invoice = validate_success(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id, "2026-08-01", "2026-08-31", fresh_fleet_version
                ),
                fixtures.CLERK,
            ),
            expected_status=201,
        )
        assert invoice["subtotal_cents"] == 12820
        assert invoice["discount_cents"] == 1603
        assert invoice["net_before_credit_cents"] == 11217
        assert invoice["credit_applied_cents"] == 2804
        assert invoice["total_cents"] == 8413


class TestSelectorSkipsBusyTechnician:
    def test_an_on_call_technician_is_filtered_out_before_any_ranking(self, api):
        """PRD §3.6: "The eligible pool is the technicians whose
        `service_location_id` equals the call's `service_location_id` and whose
        `status` is `AVAILABLE`; technicians at other locations are never considered,
        however idle they may be, and an `OFF_DUTY` or `ON_CALL` technician is never
        eligible."
        PRD §3.6: "Where they still tie, the technician whose `created_at` is earliest
        wins."

        Design: Corner/cross_cutting_complexity_layers/selector_skips_on_call_technician_even_when_top_ranked
        """
        program = fixtures.setup_fleet_program(
            location_overrides={
                "name": "Skip Commercial",
                "location_code": "SKC",
                "scrap_permit_number": "OH-SCRAP-4047",
            }
        )
        fleet_id = program["fleet"]["id"]
        location_id = program["location"]["id"]
        first_unit = fixtures.create_vehicle(
            fleet_id, unit_number="T-128", current_odometer_miles=20000
        )
        second_unit = fixtures.create_vehicle(
            fleet_id, unit_number="T-129", current_odometer_miles=21000
        )
        earlier = fixtures.create_technician(
            location_id, name="Skip One", certification_level="TIA_CERTIFIED"
        )
        later = fixtures.create_technician(
            location_id, name="Skip Two", certification_level="TIA_CERTIFIED"
        )

        call_a = fixtures.open_call(
            fleet_id, first_unit["id"], location_id, "2026-08-31T08:00:00Z"
        )
        fixtures.dispatch_call(
            call_a["id"], "2026-08-31T08:10:00Z", 6, earlier["id"]
        )
        busy = fixtures.read_technician(earlier["id"])
        assert busy["status"] == "ON_CALL"
        assert busy["completed_call_count"] == 0, (
            "the two candidates are still level on every ranking key"
        )
        assert fixtures.read_technician(later["id"])["status"] == "AVAILABLE"
        assert fixtures.read_technician(later["id"])["completed_call_count"] == 0

        call_b = fixtures.open_call(
            fleet_id,
            second_unit["id"],
            location_id,
            "2026-08-31T09:00:00Z",
            priority="EMERGENCY",
        )
        dispatched = validate_success(
            api.dispatch_road_service_call(
                call_b["id"],
                factories.dispatch_payload("2026-08-31T09:05:00Z", 6),
                fixtures.DISPATCHER,
            )
        )

        assert dispatched["technician_id"] == later["id"], (
            "the availability filter beat the created_at tie-break that would "
            "otherwise have chosen the earlier technician"
        )
        assert fixtures.read_technician(later["id"])["status"] == "ON_CALL"
        assert fixtures.read_vehicle(second_unit["id"])["status"] == "OUT_OF_SERVICE"

        untouched = fixtures.read_call(call_a["id"])
        assert untouched["dispatch_status"] == "DISPATCHED"
        assert untouched["technician_id"] == earlier["id"]


class TestInvoiceCreationIsImmediatelyConsistent:
    def test_the_creation_response_alone_carries_the_whole_rollup(self, api):
        """PRD §3.8: "Creation also claims its lines and touches the fleet."
        PRD §3.8: "When `credit_applied_cents` is greater than 0, an `APPLICATION`
        ledger entry is posted whose `amount_cents` is the negation of
        `credit_applied_cents`, carrying a null `casing_id`, a `source_entity_type` of
        `CROSS_LOCATION_INVOICE` and this invoice's identifier as `source_entity_id`;
        when `credit_applied_cents` is 0, no entry is posted at all."
        PRD §3.8: "The pricing agreement is resolved as the fleet's `ACTIVE` national
        agreement whose closed window covers `billing_period_start`, and its identifier
        is stored on the invoice as `national_agreement_id`; when no such agreement
        exists the creation is refused with `ERR_NO_ACTIVE_AGREEMENT`."

        Design: Corner/consistency_model/invoice_creation_response_already_carries_every_derived_field
        """
        program = fixtures.setup_national_account_program(
            tier_discount_pct=0.125, casing_credit_rate_cents=15000
        )
        fleet_id = program["fleet"]["id"]
        call = fixtures.setup_billable_call(program)
        fixtures.accrue_casing_credit(
            fleet_id,
            program["location"]["id"],
            grade="B",
            casing_serial="CS-4048",
            scrap_weight_lbs=142,
        )

        invoice = validate_success(
            api.create_cross_location_invoice(
                factories.invoice_payload(
                    fleet_id,
                    "2026-08-01",
                    "2026-08-31",
                    fixtures.read_fleet(fleet_id, fixtures.CLERK)["version"],
                ),
                fixtures.CLERK,
            ),
            expected_status=201,
        )

        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 12820
        assert invoice["discount_cents"] == 1603
        assert invoice["net_before_credit_cents"] == 11217
        assert invoice["credit_applied_cents"] == 2804
        assert invoice["total_cents"] == 8413
        assert invoice["status"] == "OPEN"
        assert invoice["national_agreement_id"] == program["agreement"]["id"]

        claimed = fixtures.read_call(call["id"])
        assert claimed["billing_status"] == "INVOICED", (
            "no settling pass is needed for the line to read as claimed"
        )
        assert claimed["cross_location_invoice_id"] == invoice["id"]

        fleet = fixtures.read_fleet(fleet_id, fixtures.CLERK)
        assert fleet["casing_credit_balance_cents"] == 10500, (
            "creation snapshots the balance; the APPLICATION entry posts at submit"
        )
        entries = fixtures.list_ledger(fleet_id)
        assert len(entries) == 1
        assert [entry["amount_cents"] for entry in entries_of_type(entries, "ACCRUAL")] == [
            10500
        ]
        assert entries_of_type(entries, "APPLICATION") == []
