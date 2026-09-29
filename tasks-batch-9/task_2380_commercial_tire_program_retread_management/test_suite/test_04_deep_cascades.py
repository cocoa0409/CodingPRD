"""Cascades that propagate three, four and five hops from a single request."""

from test_helpers import (
    assert_balance_equals_ledger,
    assert_ledger_sum,
    entries_of_type,
    fixtures,
    validate_success,
)


def _completion_cascade_program():
    """A started retread job on a graded-C carcass, plus one OPEN invoice that
    is already offsetting that carcass's provisional credit.

    The agreement rate is 4000 cents, so the credit stays well under the
    invoice's cap and every recomputation is visible in the invoice total.
    """
    program = fixtures.setup_plant_program(
        with_agreement=True,
        agreement_overrides={
            "casing_credit_rate_cents": 4000,
            "tier_discount_pct": 0.125,
        },
    )
    program["call"] = fixtures.setup_billable_call(program)
    program["casing"] = fixtures.create_inspected_casing(
        program["fleet"]["id"], program["location"]["id"], grade="C", retread_count=0
    )
    program["job"] = fixtures.schedule_retread_job(
        program["casing"]["id"], program["line"]["id"]
    )
    fixtures.start_job(program["job"]["id"])
    program["invoice"] = fixtures.create_invoice(program["fleet"]["id"])
    return program


class TestRetreadCompletionCascade:
    """One completion request moves five entities in order."""

    def test_completion_propagates_from_job_to_open_invoice_total(self, api):
        """PRD §3.5: "In hop 3, because the casing's retread count changed, an
        `ADJUSTMENT` ledger entry is posted for the production-verified figure
        minus the grade-provisional figure as defined in §3.4, and the casing's
        `provisional_credit_cents` is recomputed."
        PRD §3.5: "In hop 5, because the fleet's balance moved, **every**
        cross-location invoice of that fleet whose `status` is `OPEN` recomputes
        its `credit_applied_cents` and its `total_cents` and increments its own
        `version`; those invoices' `subtotal_cents`, `discount_cents` and
        `net_before_credit_cents` are deliberately left untouched, because the lines
        and the tier discount have not changed — only the credit available to offset
        them has."

        Design: Difficulty/transitive_cascade/retread_completion_ledger_cascade_depth_five
        """
        program = _completion_cascade_program()
        invoice_before = program["invoice"]
        assert invoice_before["subtotal_cents"] == 12820
        assert invoice_before["discount_cents"] == 1603
        assert invoice_before["net_before_credit_cents"] == 11217
        assert invoice_before["credit_applied_cents"] == 1600, (
            "4000 at grade C with no prior retread"
        )
        assert invoice_before["total_cents"] == 9617

        completed = fixtures.complete_job(
            program["job"]["id"],
            completed_at="2026-08-20T11:00:00Z",
            cost_basis_cents=28000,
        )
        assert completed["status"] == "COMPLETED"

        casing = fixtures.read_casing(program["casing"]["id"])
        assert casing["status"] == "RETREADED"
        assert casing["retread_count"] == 1
        assert casing.get("inspection_grade") is None
        assert casing["provisional_credit_cents"] == 1760, (
            "the production-verified figure carries the ten-percent uplift"
        )

        entries = fixtures.list_ledger(program["fleet"]["id"])
        adjustments = entries_of_type(entries, "ADJUSTMENT")
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == 160, "1760 less the 1600 already posted"

        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["casing_credit_balance_cents"] == 1760
        assert_balance_equals_ledger(fleet, entries)

        invoice = fixtures.read_invoice(invoice_before["id"])
        assert invoice["credit_applied_cents"] == 1760
        assert invoice["total_cents"] == 9457, "11217 net less the enlarged credit"

    def test_the_invoice_line_figures_are_deliberately_left_untouched(self, api):
        """PRD §3.5: "In hop 5, because the fleet's balance moved, **every**
        cross-location invoice of that fleet whose `status` is `OPEN` recomputes its
        `credit_applied_cents` and its `total_cents` and increments its own `version`;
        those invoices' `subtotal_cents`, `discount_cents` and
        `net_before_credit_cents` are deliberately left untouched, because the lines
        and the tier discount have not changed — only the credit available to offset
        them has."
        PRD §3.5: "In hop 4, because a ledger entry was posted, the fleet's
        `casing_credit_balance_cents` is recomputed and the fleet's `version`
        increases by 1."

        Design: Difficulty/transitive_cascade/retread_completion_ledger_cascade_depth_five
        """
        program = _completion_cascade_program()
        invoice_before = program["invoice"]
        fleet_version_before = fixtures.read_fleet(program["fleet"]["id"])["version"]

        fixtures.complete_job(
            program["job"]["id"],
            completed_at="2026-08-20T11:00:00Z",
            cost_basis_cents=28000,
        )

        invoice = fixtures.read_invoice(invoice_before["id"])
        assert invoice["status"] == "OPEN"
        assert invoice["subtotal_cents"] == invoice_before["subtotal_cents"]
        assert invoice["discount_cents"] == invoice_before["discount_cents"]
        assert (
            invoice["net_before_credit_cents"]
            == invoice_before["net_before_credit_cents"]
        )
        assert invoice["line_count"] == invoice_before["line_count"]
        assert invoice["version"] == invoice_before["version"] + 1, (
            "the invoice moved exactly once"
        )

        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["version"] == fleet_version_before + 1

        # The claimed line itself is not part of the cascade.
        call = fixtures.read_call(program["call"]["id"])
        assert call["billing_status"] == "INVOICED"
        assert call["invoice_total_cents"] == 12820

        # And the released slot is the completion's separate consequence.
        assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0


class TestCertifiedDestructionCascade:
    """Certification is where credit finally leaves the fleet balance."""

    def test_certifying_one_load_expires_exactly_the_credit_it_carried(self, api):
        """PRD §3.7: "In hop 3, for each casing that reached `SCRAPPED` while
        carrying a non-zero `provisional_credit_cents`, an `EXPIRY` ledger entry is
        posted whose `amount_cents` is the negation of that casing's
        `provisional_credit_cents`, with `source_entity_type` of `SCRAP_MANIFEST`
        and `source_entity_id` naming this manifest — one entry per such casing."
        PRD §3.7: "In hop 2, because the manifest was certified, every listed
        casing advances `REJECTED → SCRAPPED`, and every tire asset built on one of
        those casings whose `status` is `PULLED` advances `PULLED → SCRAPPED`
        alongside it."

        Design: Difficulty/transitive_cascade/certify_destruction_credit_expiry_cascade_depth_four
        """
        program = fixtures.setup_failed_cure_job(
            failure_reason="CASING_FAILURE",
            grade="B",
            with_agreement=True,
            agreement_overrides={"casing_credit_rate_cents": 15000},
        )
        casing = fixtures.read_casing(program["casing"]["id"])
        assert casing["status"] == "REJECTED"
        assert casing["provisional_credit_cents"] == 10500
        assert (
            fixtures.read_fleet(program["fleet"]["id"])["casing_credit_balance_cents"]
            == 10500
        )

        manifest = fixtures.create_manifest(
            program["location"]["id"], hauler_capacity_lbs=500
        )
        fixtures.add_manifest_line(manifest["id"], casing["id"])
        fixtures.sign_manifest(manifest["id"])
        fixtures.transport_manifest(manifest["id"])

        certified = fixtures.certify_destruction(manifest["id"])

        assert certified["status"] == "CERTIFIED_DESTROYED"
        assert certified["certified_by_user_id"] == "officer-certifier"
        assert fixtures.read_casing(casing["id"])["status"] == "SCRAPPED"

        entries = fixtures.list_ledger(program["fleet"]["id"])
        expiries = entries_of_type(entries, "EXPIRY")
        assert len(expiries) == 1
        assert expiries[0]["amount_cents"] == -10500
        assert expiries[0]["source_entity_type"] == "SCRAP_MANIFEST"
        assert expiries[0]["source_entity_id"] == manifest["id"]
        assert expiries[0]["casing_id"] == casing["id"]

        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["casing_credit_balance_cents"] == 0
        assert_ledger_sum(entries, 0)
        assert fixtures.read_casing(casing["id"])["provisional_credit_cents"] == 0
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 0
        )

    def test_a_two_casing_load_posts_one_expiry_per_casing(self, api):
        """PRD §3.7: "In hop 4, because ledger entries were posted, the fleet's
        `casing_credit_balance_cents` is recomputed and the fleet's `version`
        increments, and the `casings_in_holding_count` of every affected location
        is recomputed, since a `SCRAPPED` carcass is no longer in holding."
        PRD §2.8: "The fleet account's `casing_credit_balance_cents` is the sum of
        `amount_cents` over every entry carrying that fleet's `fleet_account_id`,
        with no filter on entry type, age or status."

        Design: Difficulty/transitive_cascade/certify_destruction_credit_expiry_cascade_depth_four
        """
        program = fixtures.setup_transported_manifest(
            casing_specs=[125, 130],
            grade="B",
            with_agreement=True,
            agreement_overrides={"casing_credit_rate_cents": 15000},
        )
        assert (
            fixtures.read_fleet(program["fleet"]["id"])["casing_credit_balance_cents"]
            == 21000
        )
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 2
        )
        fleet_version_before = fixtures.read_fleet(program["fleet"]["id"])["version"]

        fixtures.certify_destruction(program["manifest"]["id"])

        entries = fixtures.list_ledger(program["fleet"]["id"])
        expiries = entries_of_type(entries, "EXPIRY")
        assert len(expiries) == 2, "one entry per scrapped carcass, not one per load"
        assert sorted(e["amount_cents"] for e in expiries) == [-10500, -10500]
        assert {e["casing_id"] for e in expiries} == {
            c["id"] for c in program["casings"]
        }

        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["casing_credit_balance_cents"] == 0
        assert fleet["version"] == fleet_version_before + 1
        assert_balance_equals_ledger(fleet, entries)
        for casing in program["casings"]:
            assert fixtures.read_casing(casing["id"])["status"] == "SCRAPPED"
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 0
        )


def _replacement_program():
    """A truck running one mounted assembly, and a technician on the way."""
    program = fixtures.setup_fleet_program()
    program["vehicle"] = fixtures.create_vehicle(program["fleet"]["id"])
    program["technician"] = fixtures.create_technician(program["location"]["id"])
    program["casing"] = fixtures.create_casing(program["fleet"]["id"])
    program["asset"] = fixtures.create_mounted_asset(
        program["fleet"]["id"],
        program["casing"]["id"],
        program["vehicle"]["id"],
    )
    return program


def _run_replacement_call(program, **complete_overrides):
    return fixtures.run_completed_call(
        program["fleet"]["id"],
        program["vehicle"]["id"],
        program["location"]["id"],
        program["technician"]["id"],
        reported_at="2026-08-05T13:00:00Z",
        dispatched_at="2026-08-05T13:05:00Z",
        arrived_at="2026-08-05T14:00:00Z",
        closed_at="2026-08-05T15:00:00Z",
        labor_hours=1.0,
        dispatch_miles=30,
        **complete_overrides,
    )


class TestRoadServiceReplacementCascade:
    """A failed assembly comes off the truck and the carcass rides home."""

    def test_recording_a_replacement_pulls_the_asset_and_collects_its_casing(
        self, api
    ):
        """PRD §3.6: "In hop 2, because the replaced asset became `PULLED`, its
        casing is automatically collected — the casing advances `ON_WHEEL →
        COLLECTED` with `collected_at_location_id` set to the call's
        `service_location_id`, on the plain operational logic that the road service
        technician carries the failed carcass back to the yard they came from."
        PRD §3.6: "In hop 3, because that casing entered the holding set, the
        `casings_in_holding_count` of that location is recomputed."
        PRD §3.6: "In hop 1 the replaced asset moves from `MOUNTED` or
        `PULL_FLAGGED` to `PULLED` with its `pull_reason` set to the fixed string
        `ROAD_SERVICE_REPLACEMENT`; and if `replacement_casing_id` is also supplied, a
        fresh tire asset is minted on that casing and mounted immediately on the same
        `vehicle_id` at the same `position` the failed assembly occupied, taking
        `replacement_brand` as its `brand` and `replacement_cost_basis_cents` as its
        `cost_basis_cents`, with `odometer_at_mount` set from the unit's
        `current_odometer_miles` and `tread_depth_at_mount_32nds` set from the
        governing policy's `new_tire_tread_depth_32nds`, and carrying
        `replaced_tire_asset_id` pointing back at the assembly it succeeded."

        Design: Difficulty/transitive_cascade/road_service_replacement_collection_cascade_depth_three
        """
        program = _replacement_program()
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 0
        )

        call = _run_replacement_call(
            program, replaced_tire_asset_id=program["asset"]["id"]
        )

        assert call["gross_cents"] == 29050, "9500 base plus 11000 labour plus 8550 miles"
        assert call["sla_met"] is True
        assert call["sla_credit_cents"] == 0

        asset = fixtures.read_tire_asset(program["asset"]["id"])
        assert asset["status"] == "PULLED"
        assert asset["pull_reason"] == "ROAD_SERVICE_REPLACEMENT"
        assert asset["vehicle_id"] == program["vehicle"]["id"], (
            "a pulled assembly keeps the record of where it was running"
        )
        assert asset["position"] == "DRIVE"

        casing = fixtures.read_casing(program["casing"]["id"])
        assert casing["status"] == "COLLECTED"
        assert casing["collected_at_location_id"] == program["location"]["id"]
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 1
        )

        assert fixtures.list_ledger(program["fleet"]["id"]) == [], (
            "collection alone accrues nothing; grading is where credit is born"
        )

    def test_a_supplied_replacement_casing_is_minted_and_mounted_in_the_same_request(
        self, api
    ):
        """PRD §3.6: "In hop 1 the replaced asset moves from `MOUNTED` or
        `PULL_FLAGGED` to `PULLED` with its `pull_reason` set to the fixed string
        `ROAD_SERVICE_REPLACEMENT`; and if `replacement_casing_id` is also supplied, a
        fresh tire asset is minted on that casing and mounted immediately on the same
        `vehicle_id` at the same `position` the failed assembly occupied, taking
        `replacement_brand` as its `brand` and `replacement_cost_basis_cents` as its
        `cost_basis_cents`, with `odometer_at_mount` set from the unit's
        `current_odometer_miles` and `tread_depth_at_mount_32nds` set from the
        governing policy's `new_tire_tread_depth_32nds`, and carrying
        `replaced_tire_asset_id` pointing back at the assembly it succeeded."

        Design: Difficulty/transitive_cascade/road_service_replacement_collection_cascade_depth_three
        """
        program = _replacement_program()
        replacement_casing = fixtures.create_casing(program["fleet"]["id"])

        _run_replacement_call(
            program,
            replaced_tire_asset_id=program["asset"]["id"],
            replacement_casing_id=replacement_casing["id"],
            replacement_brand="Bridgestone",
            replacement_cost_basis_cents=61000,
        )

        assert fixtures.read_tire_asset(program["asset"]["id"])["status"] == "PULLED"

        minted = fixtures.list_assets_for_casing(replacement_casing["id"])
        assert len(minted) == 1, "the replacement casing carries exactly one new asset"
        fresh = minted[0]
        assert fresh["status"] == "MOUNTED"
        assert fresh["vehicle_id"] == program["vehicle"]["id"]
        assert fresh["position"] == "DRIVE", "the wheel the failed assembly vacated"
        assert fresh["brand"] == "Bridgestone"
        assert fresh["cost_basis_cents"] == 61000
        assert fresh["odometer_at_mount"] == 100000, "the unit's current odometer"
        assert fresh["tread_depth_at_mount_32nds"] == 24, (
            "the governing policy's new_tire_tread_depth_32nds"
        )
        assert fresh["replaced_tire_asset_id"] == program["asset"]["id"]

        assert fixtures.read_casing(replacement_casing["id"])["status"] == "ON_WHEEL", (
            "the new carcass is in service, not in holding"
        )
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 1
        ), "only the failed carcass entered the holding set"

        listed = validate_success(
            api.get_tire_asset(fresh["id"], fixtures.ADMIN)
        )
        assert listed["id"] == fresh["id"]
