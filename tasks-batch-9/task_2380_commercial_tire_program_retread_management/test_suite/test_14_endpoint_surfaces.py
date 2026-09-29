"""Declared endpoint surfaces: partial updates, action posts and link posts."""

from test_helpers import (
    factories,
    fixtures,
    make_fleet_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTirePolicySurface:
    def test_a_revision_touches_only_the_named_field_and_bumps_the_version(self, api):
        """PRD §3.1: "Revising a policy may change any of those values except
        `position`, and increments the policy's `version`."
        PRD §3.1: "The policy carries `target_pressure_psi`, the cold inflation target,
        which must be greater than 0 and at most 150; `pressure_tolerance_pct`, the
        allowed absolute deviation fraction from that target before a survey raises a
        pressure finding, which must be greater than 0 and at most 0.50;
        `min_tread_depth_32nds`, the legal minimum tread depth in thirty-seconds of an
        inch, which must be at least 2 and strictly less than the pull point;
        `pull_point_32nds`, the fleet's own pull threshold in thirty-seconds, which must
        be strictly greater than the legal minimum and at most 20; `max_retread_count`,
        the maximum number of prior retreads a casing may already carry and still be
        booked for another retread at this position, which must be at least 0 and at
        most 5; `approved_brands`, a non-empty array of brand strings explicitly
        approved for the position; `new_tire_tread_depth_32nds`, the nominal as-new
        depth in thirty-seconds used as the mount-time baseline for a replacement, which
        must be strictly greater than the pull point and at most 32; and
        `casing_spec_code`, the required casing specification code, which defaults to
        the wildcard string `ANY`."

        Design: Corner/endpoints/tire_policy_create_read_patch_and_list_surface
        """
        program = fixtures.setup_fleet_program(with_policy=False)
        fleet_id = program["fleet"]["id"]
        reader = make_fleet_manager_headers(fleet_id)

        drive = validate_success(
            api.create_tire_policy(
                fleet_id,
                factories.tire_policy_payload(
                    position="DRIVE",
                    approved_brands=["Bridgestone", "Michelin"],
                    casing_spec_code="R22.5",
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )
        assert drive["version"] == 1
        assert drive["approved_brands"] == ["Bridgestone", "Michelin"], (
            "the array is stored in the order it was given"
        )

        trailer_payload = factories.tire_policy_payload(
            position="TRAILER",
            target_pressure_psi=95,
            pressure_tolerance_pct=0.12,
            min_tread_depth_32nds=2,
            pull_point_32nds=4,
            max_retread_count=2,
            new_tire_tread_depth_32nds=20,
        )
        trailer_payload.pop("casing_spec_code")
        trailer = validate_success(
            api.create_tire_policy(fleet_id, trailer_payload, fixtures.ADMIN),
            expected_status=201,
        )

        read_back = validate_success(api.get_tire_policy(drive["id"], reader))
        assert read_back["version"] == 1, "a read is not a revision"
        assert read_back["pull_point_32nds"] == 6

        revised = validate_success(
            api.update_tire_policy(drive["id"], {"pull_point_32nds": 8}, fixtures.ADMIN)
        )
        assert revised["pull_point_32nds"] == 8
        assert revised["version"] == 2
        assert revised["position"] == "DRIVE"
        assert revised["target_pressure_psi"] == 100, "an unnamed field is untouched"
        assert revised["approved_brands"] == ["Bridgestone", "Michelin"]
        assert revised["casing_spec_code"] == "R22.5"
        assert revised["min_tread_depth_32nds"] == 4
        assert revised["max_retread_count"] == 3

        rows, meta = validate_paginated(
            api.list_tire_policies(
                reader, params={"fleet_account_id": fleet_id, "position": "TRAILER"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == trailer["id"]
        assert rows[0]["casing_spec_code"] == "ANY", "the wildcard default survived"


class TestRetreadLineStatusAction:
    def test_the_status_action_round_trip_carries_no_schedule_side_effects(self, api):
        """PRD §3.1: "A `DealerAdmin` may set a line's `status` to `DOWN` for
        maintenance and back to `AVAILABLE`; a `DOWN` line rejects new scheduling,
        rescheduling and job starts with `ERR_LINE_DOWN`, but already-booked jobs keep
        their slots and the line's `booked_minutes` does not change when the line goes
        down or comes back up."
        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp with three fractional digits refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increases by exactly 1
        on every mutation of that row."

        Design: Corner/endpoints/retread_line_status_action_endpoint_round_trip
        """
        program = fixtures.setup_plant_program(line_count=1, cure_cooldown_minutes=30)
        line = program["line"]
        assert line["version"] == 1

        downed = validate_success(
            api.set_retread_line_status(
                line["id"],
                factories.retread_line_status_payload("DOWN"),
                fixtures.ADMIN,
            )
        )
        assert downed["status"] == "DOWN"
        assert downed["version"] == 2
        assert downed["booked_minutes"] == 0
        assert downed["cure_cooldown_minutes"] == 30

        rows, meta = validate_paginated(
            api.list_retread_lines(
                fixtures.SCHEDULER,
                params={
                    "service_location_id": program["location"]["id"],
                    "status": "DOWN",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == line["id"]

        restored = validate_success(
            api.set_retread_line_status(
                line["id"],
                factories.retread_line_status_payload("AVAILABLE"),
                fixtures.ADMIN,
            )
        )
        assert restored["status"] == "AVAILABLE"
        assert restored["version"] == 3, "versions climb, they never revert"
        assert restored["booked_minutes"] == 0
        assert restored["cure_cooldown_minutes"] == 30


class TestInvoiceSettlementAmount:
    def test_only_the_post_discount_total_settles_the_invoice(self, api):
        """PRD §3.8: "The clerk supplies `paid_amount_cents`, which must equal the
        invoice's `total_cents` exactly; a partial or excess amount is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."
        PRD §3.8: "The invoice advances `SUBMITTED → PAID` and records the amount, and
        every claimed call cascades `BILLED_TO_NATIONAL → SETTLED`."

        Design: Corner/endpoints/settle_invoice_with_wrong_amount_rejected
        """
        program = fixtures.setup_submitted_invoice()
        invoice = program["invoice"]
        call_id = program["calls"][0]["id"]
        assert invoice["subtotal_cents"] == 12820
        assert invoice["total_cents"] == 11217

        validate_error(
            api.settle_cross_location_invoice(
                invoice["id"], factories.settle_invoice_payload(12820), fixtures.CLERK
            ),
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            expected_status=422,
        )
        validate_error(
            api.settle_cross_location_invoice(
                invoice["id"], factories.settle_invoice_payload(11216), fixtures.CLERK
            ),
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            expected_status=422,
        )

        assert fixtures.read_invoice(invoice["id"])["status"] == "SUBMITTED"
        assert (
            fixtures.read_call(call_id)["billing_status"] == "BILLED_TO_NATIONAL"
        ), "a refused payment releases nothing"

        paid = validate_success(
            api.settle_cross_location_invoice(
                invoice["id"], factories.settle_invoice_payload(11217), fixtures.CLERK
            )
        )
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 11217
        assert fixtures.read_call(call_id)["billing_status"] == "SETTLED"


class TestManifestLineSingleOwner:
    def test_a_carcass_already_spoken_for_cannot_be_linked_to_a_second_load(self, api):
        """PRD §3.7: "The casing's `scrap_manifest_id` must be empty, since a carcass
        cannot be on two loads at once; a repeat is rejected with
        `ERR_CASING_ALREADY_ON_MANIFEST`."
        PRD §3.4: "A `COLLECTED` casing graded `REJECT` advances `COLLECTED → REJECTED`
        and posts **no ledger entry whatsoever**, on the principle that a carcass that
        never graded retreadable never accrued anything to reverse."

        Design: Corner/endpoints/casing_on_second_manifest_returns_already_on_manifest
        """
        program = fixtures.setup_fleet_program()
        location_id = program["location"]["id"]
        casing = fixtures.create_condemned_casing(
            program["fleet"]["id"], location_id, scrap_weight_lbs=140
        )
        first = fixtures.create_manifest(location_id, hauler_capacity_lbs=1000)
        second = fixtures.create_manifest(location_id, hauler_capacity_lbs=1000)
        fixtures.add_manifest_line(first["id"], casing["id"])

        validate_error(
            api.add_scrap_manifest_line(
                second["id"],
                factories.manifest_line_payload(casing["id"]),
                fixtures.OFFICER,
            ),
            "ERR_CASING_ALREADY_ON_MANIFEST",
            expected_status=409,
        )

        incumbent = fixtures.read_manifest(first["id"])
        assert incumbent["tire_count"] == 1
        assert incumbent["total_weight_lbs"] == 140
        rival = fixtures.read_manifest(second["id"])
        assert rival["tire_count"] == 0
        assert rival["total_weight_lbs"] == 0

        held = fixtures.read_casing(casing["id"])
        assert held["scrap_manifest_id"] == first["id"]
        assert held["status"] == "REJECTED"
        assert fixtures.list_casing_ledger(casing["id"]) == [], (
            "a REJECT grade accrued nothing"
        )


class TestManifestLineAccumulation:
    def test_the_totals_are_recomputed_per_post_and_a_refusal_leaves_them_alone(
        self, api
    ):
        """PRD §3.7: "On success the casing's `scrap_manifest_id` is set, the
        manifest's `tire_count` and `total_weight_lbs` are recomputed from the casings
        now linked to it, and the manifest's `version` increments."
        PRD §3.7: "The comparison is strict — a load landing on **exactly** the
        capacity is accepted, and only a load that would push the total strictly above
        it is rejected with `ERR_MANIFEST_CAPACITY_EXCEEDED`."

        Design: Corner/endpoints/repeated_manifest_line_posts_accumulate_totals
        """
        program = fixtures.setup_fleet_program()
        fleet_id = program["fleet"]["id"]
        location_id = program["location"]["id"]
        light = fixtures.create_condemned_casing(
            fleet_id, location_id, scrap_weight_lbs=140
        )
        medium = fixtures.create_condemned_casing(
            fleet_id, location_id, scrap_weight_lbs=150
        )
        heavy = fixtures.create_condemned_casing(
            fleet_id, location_id, scrap_weight_lbs=160
        )
        manifest = fixtures.create_manifest(location_id, hauler_capacity_lbs=300)

        after_first = fixtures.add_manifest_line(manifest["id"], light["id"])
        assert after_first["tire_count"] == 1
        assert after_first["total_weight_lbs"] == 140

        after_second = fixtures.add_manifest_line(manifest["id"], medium["id"])
        assert after_second["tire_count"] == 2
        assert after_second["total_weight_lbs"] == 290

        validate_error(
            api.add_scrap_manifest_line(
                manifest["id"],
                factories.manifest_line_payload(heavy["id"]),
                fixtures.OFFICER,
            ),
            "ERR_MANIFEST_CAPACITY_EXCEEDED",
            expected_status=409,
        )

        unchanged = fixtures.read_manifest(manifest["id"])
        assert unchanged["tire_count"] == 2
        assert unchanged["total_weight_lbs"] == 290, "290 plus 160 would gross 450"
        assert unchanged["status"] == "DRAFT"
        assert fixtures.read_casing(heavy["id"]).get("scrap_manifest_id") is None

        _rows, meta = validate_paginated(
            api.list_casings(
                fixtures.OFFICER, params={"scrap_manifest_id": manifest["id"]}
            )
        )
        assert meta["total_count"] == 2, "the totals are a view of the linked set"
