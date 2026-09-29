"""Style catalogue and the test-and-certify chain.

Covers style drafting and activation, lab product tests and their verdict
thresholds, certificate issuance / supersession / revocation, segregation of
duties between the testing technician and the certifying officer, the style
recycled-content computed read under both accounting bases, and the report the
logical-clock advance returns.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_append_only_fields,
    factories,
    fixtures,
    make_certification_officer_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]
EXTRUDER = TEST_USERS["extrusion_operator_headers"]
QA = TEST_USERS["qa_lab_technician_headers"]
CERTIFIER = TEST_USERS["certification_officer_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]

QA_TECH_ID = "qa-tech-1"
CERT_OFFICER_ID = "cert-officer-1"

RUN_WINDOW_OPEN = "2026-08-05T08:00:00Z"
SECOND_RUN_START = "2026-08-07T08:00:00Z"
SECOND_RUN_END = "2026-08-07T16:00:00Z"

# The PRD confines sbr_pct to the inclusive range 30 to 70. At 70.0 percent SBR
# with a 20.0 percent filler load, a full 120 second cure at 150 C on ACTION_BAC
# the predicted peel strength is 3.10 lbf, above the 2.50 lbf floor, so every run
# built below lands in BACKED rather than BACKING_FAILED.
_BACKING = {"sbr_pct": 70.0}


def _backed_solution_dyed_run_with_roll():
    """A solution-dyed ACTIVE style whose run is BACKED, with one doffed roll.

    The roll is left at qa_status PENDING: nothing in this module needs it
    released except where a test releases it explicitly.
    """
    ctx = fixtures.setup_backed_solution_dyed_run(backing_overrides=dict(_BACKING))
    ctx["roll_good"] = fixtures.doff_roll_good(ctx["run"]["id"])
    return ctx


def _blended_recycled_style():
    """A style whose single BACKED run creels a batch blending virgin nylon with
    a non-segregated lot declared at 60.00 percent recycled."""
    virgin = fixtures.create_polymer_lot(
        lot_code="PL-VIRGIN-01",
        polymer_type="NYLON_66",
        received_kg=2500.0,
        melt_flow_index=18.0,
        recycled_content_pct=0.0,
        segregated=False,
        reclaim_source="VIRGIN",
    )
    blend = fixtures.create_polymer_lot(
        lot_code="PL-BLEND-60",
        polymer_type="NYLON_66",
        received_kg=2500.0,
        melt_flow_index=16.0,
        recycled_content_pct=60.0,
        segregated=False,
        reclaim_source="POST_CONSUMER",
    )
    fiber_batch = fixtures.create_released_fiber_batch(
        virgin["id"],
        batch_code="FB-01",
        input_kg=2000.0,
        blend_polymer_lot_id=blend["id"],
        blend_input_kg=2000.0,
        denier_target=1200.0,
        filament_count=72,
        dye_method="SOLUTION_DYED",
        solution_color_code="SC-BEIGE-01",
    )
    style = fixtures.create_active_style()
    machine = fixtures.create_tufting_machine()
    run = fixtures.create_scheduled_run(style["id"], machine["id"], fiber_batch["id"])
    run = fixtures.advance_run_to_backed(run["id"], **dict(_BACKING))
    roll = fixtures.doff_roll_good(run["id"])
    product_test = fixtures.record_product_test(
        style["id"], roll["id"], test_type="WEAR_TARR", result_value=4.2
    )
    return {
        "virgin_lot": virgin,
        "blend_lot": blend,
        "fiber_batch": fiber_batch,
        "style": style,
        "machine": machine,
        "run": run,
        "roll_good": roll,
        "product_test": product_test,
    }


def _style_with_two_released_batches():
    """One ACTIVE style, one tufter, and two RELEASED fiber batches off one lot."""
    lot = fixtures.create_polymer_lot(
        lot_code="PL-N66-01",
        polymer_type="NYLON_66",
        received_kg=9000.0,
        melt_flow_index=18.0,
    )
    batch_one = fixtures.create_released_fiber_batch(
        lot["id"], batch_code="FB-01", input_kg=4000.0
    )
    batch_two = fixtures.create_released_fiber_batch(
        lot["id"], batch_code="FB-02", input_kg=4000.0
    )
    style = fixtures.create_active_style()
    machine = fixtures.create_tufting_machine()
    return {
        "polymer_lot": lot,
        "fiber_batch_one": batch_one,
        "fiber_batch_two": batch_two,
        "style": style,
        "machine": machine,
    }


class TestStyleRecycledContentAccountingBases:
    def test_recycled_content_read_reports_thirty_under_mass_balance_and_zero_under_segregation(
        self, api
    ):
        """One blended batch reads 30.00 pct on mass balance and 0.00 pct on physical
        segregation off the same 4000.000 kg of qualifying mass.

        PRD: "each contribution credits its kilogram figure multiplied by its lot's
        `recycled_content_pct` divided by 100, so a 2000 kg contribution from a lot
        declared at 60.00 percent recycled credits 1200 kg of recycled mass"
        PRD: "a contribution credits its full kilogram figure only when its lot's
        `segregated` flag is true **and** its lot's `recycled_content_pct` is exactly
        100.00, and credits nothing otherwise; that same 2000 kg blended contribution
        therefore credits 0 kg"

        Design: Difficulty/dual_variant_calc/style_recycled_content_mass_balance_vs_physical_segregation
        """
        ctx = _blended_recycled_style()

        data = validate_success(
            api.get_style_recycled_content(ctx["style"]["id"], CERTIFIER)
        )

        assert data["mass_balance_pct"] == pytest.approx(30.00, abs=0.01), (
            f"expected mass_balance_pct 30.00 from 1200 credited kg of 4000.000 "
            f"qualifying kg, got {data['mass_balance_pct']}"
        )
        assert data["physical_segregation_pct"] == pytest.approx(0.00, abs=0.01), (
            "a non-segregated 60.00 pct lot credits nothing under physical "
            f"segregation, expected 0.00, got {data['physical_segregation_pct']}"
        )
        assert data["qualifying_kg"] == pytest.approx(4000.000, abs=0.001), (
            f"expected qualifying_kg 4000.000 (2000.000 primary + 2000.000 blend), "
            f"got {data['qualifying_kg']}"
        )
        assert data["qualifying_fiber_batch_ids"] == [ctx["fiber_batch"]["id"]], (
            f"expected the one creeled batch to be the qualifying set, got "
            f"{data['qualifying_fiber_batch_ids']}"
        )

        batch = fixtures.refresh_fiber_batch(ctx["fiber_batch"]["id"])
        assert batch["extruded_kg"] == pytest.approx(3860.000, abs=0.001), (
            f"expected extruded_kg 3860.000 from 4000.000 drawn kg at the 0.965 "
            f"spinning yield, got {batch['extruded_kg']}"
        )
        assert batch["denier_actual"] == pytest.approx(1200.0, abs=0.05), (
            f"expected denier_actual 1200.0, got {batch['denier_actual']}"
        )

    def test_nsf_140_fails_under_physical_segregation_and_passes_under_mass_balance(
        self, api
    ):
        """The same rows refuse an NSF_140 on physical segregation at 0.00 pct and
        issue it on mass balance at 30.00 pct.

        PRD: "The gate compares that rounded percentage against the minimum of 25.00
        percent: a percentage strictly below it is refused with
        `ERR_RECYCLED_CONTENT_INSUFFICIENT`"
        PRD: "On a successful `NSF_140` issuance the percentage computed under the
        requested `accounting_basis` is persisted on the certificate as
        `recorded_recycled_content_pct`"

        Design: Difficulty/dual_variant_calc/style_recycled_content_mass_balance_vs_physical_segregation
        """
        ctx = _blended_recycled_style()
        style_id = ctx["style"]["id"]
        test_ids = [ctx["product_test"]["id"]]

        refused = api.create_certification(
            factories.create_certification_payload(
                style_id,
                test_ids,
                cert_type="NSF_140",
                accounting_basis="PHYSICAL_SEGREGATION",
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            CERTIFIER,
        )
        validate_error(refused, "ERR_RECYCLED_CONTENT_INSUFFICIENT")

        issued = api.create_certification(
            factories.create_certification_payload(
                style_id,
                test_ids,
                cert_type="NSF_140",
                accounting_basis="MASS_BALANCE",
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            CERTIFIER,
        )
        cert = validate_success(issued, expected_status=201)

        assert cert["accounting_basis"] == "MASS_BALANCE", (
            f"expected accounting_basis MASS_BALANCE, got {cert['accounting_basis']}"
        )
        assert cert["status"] == "ACTIVE", (
            f"expected status ACTIVE on a fresh certificate, got {cert['status']}"
        )
        assert cert["recorded_recycled_content_pct"] == pytest.approx(30.00, abs=0.01), (
            "expected recorded_recycled_content_pct 30.00 under MASS_BALANCE, got "
            f"{cert['recorded_recycled_content_pct']}"
        )

        listed, meta = validate_paginated(
            api.list_certifications(
                CERTIFIER, params={"style_id": style_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"only the mass-balance certificate should exist, got "
            f"{meta['total_count']} certificates"
        )
        assert listed[0]["id"] == cert["id"], (
            f"expected the mass-balance certificate {cert['id']}, got {listed[0]['id']}"
        )


class TestCertificateRevocationGatesTheTufter:
    def test_revoking_the_last_flammability_certificate_suspends_the_style_and_holds_its_scheduled_run(
        self, api
    ):
        """Revocation suspends the style and holds only its SCHEDULED run.

        PRD: "A `CertificationOfficer` may revoke one, optionally supplying a
        `reason`, which sets `status` to `REVOKED`, terminal."
        PRD: "the style transitions `ACTIVE` to `SUSPENDED`. That suspension carries
        one cascade hop: every production run of the style whose status is
        `SCHEDULED` transitions `SCHEDULED` to `HELD`"

        Design: Difficulty/cross_entity_state_dependency/tufter_load_setup_gated_on_style_status_driven_by_certificate_revocation
        """
        ctx = _style_with_two_released_batches()
        style_id = ctx["style"]["id"]
        run_one = fixtures.create_scheduled_run(
            style_id, ctx["machine"]["id"], ctx["fiber_batch_one"]["id"], run_code="PR-01"
        )
        fixtures.advance_run_to_backed(run_one["id"], **dict(_BACKING))
        roll = fixtures.doff_roll_good(run_one["id"])
        pill_test = fixtures.record_product_test(
            style_id, roll["id"], test_type="FLAMMABILITY_PILL", result_value=18.0
        )
        cert = fixtures.issue_certification(
            style_id,
            [pill_test["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2027-08-01T00:00:00Z",
        )
        fixtures.release_roll_good(roll["id"])
        run_two = fixtures.create_scheduled_run(
            style_id,
            ctx["machine"]["id"],
            ctx["fiber_batch_two"]["id"],
            run_code="PR-02",
            scheduled_start_utc=SECOND_RUN_START,
            scheduled_end_utc=SECOND_RUN_END,
        )
        fixtures.set_clock(SECOND_RUN_START, ADMIN)

        revoked = validate_success(
            api.revoke_certification(
                cert["id"], factories.revoke_certification_payload(), CERTIFIER
            )
        )

        assert revoked["status"] == "REVOKED", (
            f"expected status REVOKED after the revoke, got {revoked['status']}"
        )
        style = fixtures.refresh_style(style_id)
        assert style["status"] == "SUSPENDED", (
            "losing the last effective DOC_FF_1_70 must suspend the style, got "
            f"{style['status']}"
        )
        held = fixtures.refresh_run(run_two["id"])
        assert held["status"] == "HELD", (
            f"expected the SCHEDULED run PR-02 to be HELD, got {held['status']}"
        )
        untouched = fixtures.refresh_run(run_one["id"])
        assert untouched["status"] == "RELEASED", (
            "a run past SCHEDULED is not held by the suspension, expected RELEASED, "
            f"got {untouched['status']}"
        )

    def test_held_run_cannot_load_setup_until_a_replacement_certificate_reinstates_the_style(
        self, api
    ):
        """Load-setup on the held run is refused at 409 and then succeeds unchanged
        once a fresh certificate returns the style to ACTIVE.

        PRD: "The style must still be in `ACTIVE` at this moment — a run that was
        held because its style was suspended cannot be loaded, and the refusal is
        `ERR_STYLE_NOT_ACTIVE`."
        PRD: "When a fresh effective `DOC_FF_1_70` certificate is subsequently issued
        for the style, the style transitions `SUSPENDED` back to `ACTIVE`, and the
        mirrored cascade hop releases every run of the style in `HELD` back to
        `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/tufter_load_setup_gated_on_style_status_driven_by_certificate_revocation
        """
        ctx = _style_with_two_released_batches()
        style_id = ctx["style"]["id"]
        run_one = fixtures.create_scheduled_run(
            style_id, ctx["machine"]["id"], ctx["fiber_batch_one"]["id"], run_code="PR-01"
        )
        fixtures.advance_run_to_backed(run_one["id"], **dict(_BACKING))
        roll = fixtures.doff_roll_good(run_one["id"])
        pill_test = fixtures.record_product_test(
            style_id, roll["id"], test_type="FLAMMABILITY_PILL", result_value=18.0
        )
        cert = fixtures.issue_certification(
            style_id,
            [pill_test["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2027-08-01T00:00:00Z",
        )
        fixtures.release_roll_good(roll["id"])
        run_two = fixtures.create_scheduled_run(
            style_id,
            ctx["machine"]["id"],
            ctx["fiber_batch_two"]["id"],
            run_code="PR-02",
            scheduled_start_utc=SECOND_RUN_START,
            scheduled_end_utc=SECOND_RUN_END,
        )
        fixtures.set_clock(SECOND_RUN_START, ADMIN)
        fixtures.revoke_certification(cert["id"])

        refused = api.load_setup_production_run(
            run_two["id"], factories.load_setup_payload(), PLANNER
        )

        assert refused.status_code == 409, (
            "loading a run held by its style's suspension must be refused at 409, "
            f"got {refused.status_code}"
        )
        validate_error_is_one_of(refused, ["ERR_STYLE_NOT_ACTIVE", "ERR_INVALID_STATE"])
        still_held = fixtures.refresh_run(run_two["id"])
        assert still_held["status"] == "HELD", (
            f"the refused setup must leave PR-02 in HELD, got {still_held['status']}"
        )
        assert still_held["gauge_loaded_code"] is None, (
            "a refused setup writes nothing, expected gauge_loaded_code null, got "
            f"{still_held['gauge_loaded_code']}"
        )
        assert still_held["stitch_rate_per_inch"] is None, (
            "a refused setup writes nothing, expected stitch_rate_per_inch null, got "
            f"{still_held['stitch_rate_per_inch']}"
        )

        replacement = validate_success(
            api.create_certification(
                factories.create_certification_payload(
                    style_id,
                    [pill_test["id"]],
                    cert_type="DOC_FF_1_70",
                    expires_at_utc="2027-12-31T00:00:00Z",
                ),
                CERTIFIER,
            ),
            expected_status=201,
        )
        assert replacement["status"] == "ACTIVE", (
            f"expected the replacement certificate ACTIVE, got {replacement['status']}"
        )
        reinstated = fixtures.refresh_style(style_id)
        assert reinstated["status"] == "ACTIVE", (
            f"a fresh effective DOC_FF_1_70 must reinstate the style, got "
            f"{reinstated['status']}"
        )
        released_run = fixtures.refresh_run(run_two["id"])
        assert released_run["status"] == "SCHEDULED", (
            f"the HELD run must return to SCHEDULED, got {released_run['status']}"
        )

        loaded = validate_success(
            api.load_setup_production_run(
                run_two["id"], factories.load_setup_payload(), PLANNER
            )
        )
        assert loaded["status"] == "TUFTING", (
            f"the same setup must now start tufting, got {loaded['status']}"
        )
        assert loaded["stitch_rate_per_inch"] == pytest.approx(10.0, abs=0.05), (
            f"expected stitch_rate_per_inch 10.0 persisted on the run, got "
            f"{loaded['stitch_rate_per_inch']}"
        )


class TestStyleReadAndCreationValidation:
    def test_get_style_with_unknown_id_returns_style_not_found(self, api):
        """A syntactically valid but unpersisted style id resolves to the
        entity-specific ERR_STYLE_NOT_FOUND at 404.

        PRD: "Every resource named by a path segment must exist, validated in the
        order the segments appear in the URL. The first segment that resolves to
        nothing decides the error: `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_POLYMER_LOT_NOT_FOUND`, `ERR_RECLAMATION_BATCH_NOT_FOUND`,
        `ERR_FIBER_BATCH_NOT_FOUND`, `ERR_STYLE_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`,
        `ERR_VESSEL_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`,
        `ERR_DYE_LOT_NOT_FOUND`, `ERR_ROLL_GOOD_NOT_FOUND`,
        `ERR_PRODUCT_TEST_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
        `ERR_CUT_ORDER_NOT_FOUND` or `ERR_CUT_ALLOCATION_NOT_FOUND`, each with HTTP
        404."

        Design: Corner/entities/get_style_with_unknown_id_returns_style_not_found
        """
        existing = fixtures.create_style()

        response = api.get_style("00000000-0000-4000-8000-000000000404", PLANNER)

        assert response.status_code == 404, (
            f"an unknown style id must return 404, got {response.status_code}"
        )
        error = validate_error(response, "ERR_STYLE_NOT_FOUND")
        assert isinstance(error["message"], str) and error["message"].strip(), (
            f"the error envelope must carry a human-readable message, got "
            f"{error.get('message')!r}"
        )

        untouched = fixtures.refresh_style(existing["id"])
        assert untouched["status"] == "DRAFT", (
            f"the unrelated style must be untouched at DRAFT, got {untouched['status']}"
        )

    def test_create_style_missing_pattern_repeat_returns_invalid_request(self, api):
        """Omitting pattern_repeat_mm is a shape violation and creates no style row.

        PRD: "Every required field is present, every enum value lies in its declared
        set, every numeric lies in its declared range"
        PRD: "Failures here are `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_style_missing_pattern_repeat_returns_invalid_request
        """
        payload = factories.create_style_payload()
        payload.pop("pattern_repeat_mm")

        response = api.create_style(payload, PLANNER)

        validate_error(response, "ERR_INVALID_REQUEST")

        data, meta = validate_paginated(
            api.list_styles(PLANNER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"a rejected draft must not be persisted, got {meta['total_count']} styles"
        )
        assert data == [], f"expected an empty style list, got {data}"

    def test_reusing_a_style_code_returns_duplicate_code(self, api):
        """style_code is a natural key: a second draft under the same code is refused
        even though every other field differs.

        PRD: "A `MillPlanner` drafts one by supplying a `style_code` unique across
        styles"
        PRD: "The supplied code is not already in use: `account_code`, a polymer
        lot's `lot_code`"
        PRD: "A collision is `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/validations/reusing_a_style_code_returns_duplicate_code
        """
        first = fixtures.create_style()

        response = api.create_style(
            factories.create_style_payload(
                style_code="ST-SD-01",
                line_type="CUSTOM",
                gauge_code="G_1_8",
                pile_construction="LOOP",
                pile_height_mm=6.0,
                pattern_repeat_mm=250.0,
                plies=2,
                target_face_weight_oz=28.0,
                dye_method="PIECE_DYED",
                solution_color_code=None,
                list_price_cents_per_yard=5100,
            ),
            PLANNER,
        )

        validate_error(response, "ERR_DUPLICATE_CODE")

        data, meta = validate_paginated(
            api.list_styles(PLANNER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1, (
            f"the collision must not mint a second style, got {meta['total_count']}"
        )
        assert data[0]["id"] == first["id"], (
            f"expected the original style {first['id']}, got {data[0]['id']}"
        )
        assert data[0]["line_type"] == "RUNNING_LINE", (
            f"the original style keeps its line_type, got {data[0]['line_type']}"
        )
        assert data[0]["gauge_code"] == "G_1_10", (
            f"the original style keeps its gauge_code, got {data[0]['gauge_code']}"
        )


class TestStyleActivation:
    def test_activate_draft_style_moves_to_active(self, api):
        """The single activate call is the only door from DRAFT to ACTIVE and leaves
        the style's backorder posture alone.

        PRD: "Activation moves the style from `DRAFT` to `ACTIVE`, making it both
        schedulable and orderable"
        PRD: "A new style begins with `status` of `DRAFT`, `open_backorder_yards` of 0
        and `replenishment_flag` of `NONE`."
        PRD: "`version` — an integer that starts at 1 on creation and increases by
        exactly 1 on every mutation of the record."

        Design: Corner/state_machines/activate_draft_style_moves_to_active
        """
        draft = fixtures.create_style()
        assert draft["status"] == "DRAFT", (
            f"a freshly drafted style starts at DRAFT, got {draft['status']}"
        )

        activated = validate_success(api.activate_style(draft["id"], PLANNER))

        assert activated["status"] == "ACTIVE", (
            f"expected ACTIVE after activation, got {activated['status']}"
        )
        assert activated["open_backorder_yards"] == pytest.approx(0, abs=0.01), (
            f"activation must not move open_backorder_yards, got "
            f"{activated['open_backorder_yards']}"
        )
        assert activated["replenishment_flag"] == "NONE", (
            f"activation must not raise the replenishment flag, got "
            f"{activated['replenishment_flag']}"
        )
        assert activated["version"] == 2, (
            f"version starts at 1 and advances by one on the activation, expected 2, "
            f"got {activated['version']}"
        )

    def test_activate_style_twice_second_call_returns_invalid_state(self, api):
        """Activation is not idempotent: a second call from ACTIVE is refused and
        performs no write at all.

        PRD: "The target resource is in a status from which the requested transition
        is declared. The generic failure is `ERR_INVALID_STATE` (409)"
        PRD: "`version` — an integer that starts at 1 on creation and increases by
        exactly 1 on every mutation of the record."

        Design: Corner/state_machines/activate_style_twice_second_call_returns_invalid_state
        """
        style = fixtures.create_active_style()
        assert style["version"] == 2, (
            f"the activated style should sit at version 2, got {style['version']}"
        )

        response = api.activate_style(style["id"], PLANNER)

        validate_error(response, "ERR_INVALID_STATE")

        after = validate_success(api.get_style(style["id"], PLANNER))
        assert after["status"] == "ACTIVE", (
            f"the style stays ACTIVE after the refused activation, got {after['status']}"
        )
        assert after["version"] == 2, (
            f"a refused transition writes nothing, expected version 2, got "
            f"{after['version']}"
        )


class TestProductTests:
    def test_product_test_response_omits_version_and_updated_at(self, api):
        """A recorded lab result is an immutable record: neither create nor read
        carries version or updated_at.

        PRD: "A product test is an immutable laboratory record: it carries only `id`
        and `created_at`."
        PRD: "Both `updated_at` and `version` are absent from a `ProductTest` payload
        entirely, and no operation ever modifies a test once recorded."
        PRD: "The server stamps `tested_by_user_id` from the acting `X-User-ID` and
        `tested_at_utc` from the logical clock"

        Design: Corner/entities/product_test_response_omits_version_and_exposes_no_update_endpoint
        """
        ctx = _backed_solution_dyed_run_with_roll()

        created = validate_success(
            api.create_product_test(
                factories.create_product_test_payload(
                    ctx["style"]["id"],
                    ctx["roll_good"]["id"],
                    test_type="WEAR_TARR",
                    result_value=4.0,
                ),
                QA,
            ),
            expected_status=201,
        )

        assert_append_only_fields(created)
        assert "version" not in created, (
            f"a ProductTest must not carry version, got {created.get('version')!r}"
        )
        assert "updated_at" not in created, (
            f"a ProductTest must not carry updated_at, got {created.get('updated_at')!r}"
        )
        assert created["verdict"] == "PASS", (
            f"a WEAR_TARR reading of 4.0 passes the 3.0 floor, got {created['verdict']}"
        )
        assert created["result_value"] == pytest.approx(4.0, abs=0.05), (
            f"expected result_value 4.0, got {created['result_value']}"
        )
        assert created["tested_by_user_id"] == QA_TECH_ID, (
            f"expected tested_by_user_id {QA_TECH_ID}, got {created['tested_by_user_id']}"
        )
        assert created["tested_at_utc"].startswith("2026-08-05T08:00:00"), (
            f"tested_at_utc must be stamped from the logical clock at "
            f"{RUN_WINDOW_OPEN}, got {created['tested_at_utc']}"
        )

        read = validate_success(api.get_product_test(created["id"], CERTIFIER))
        assert "version" not in read, (
            f"the read must not carry version either, got {read.get('version')!r}"
        )
        assert "updated_at" not in read, (
            f"the read must not carry updated_at either, got {read.get('updated_at')!r}"
        )
        assert read["id"] == created["id"], (
            f"expected to read back test {created['id']}, got {read['id']}"
        )

    def test_product_test_verdict_thresholds_are_inclusive_in_both_directions(self, api):
        """WEAR_TARR 3.0 and STAIN_AATCC175 8.0 pass on the at-least side while
        FLAMMABILITY_PILL 25.4 passes and 25.5 fails on the at-most side.

        PRD: "A `WEAR_TARR` test yields `PASS` when its `result_value` is at least
        3.0. A `STAIN_AATCC175` test yields `PASS` when its `result_value` is at least
        8.0. A `FLAMMABILITY_PILL` test yields `PASS` when its `result_value` is at
        most 25.4 millimetres of char radius"
        PRD: "All three comparisons are inclusive, and any reading that fails its
        comparison yields `FAIL`."

        Design: Corner/calculations/product_test_verdict_thresholds_are_inclusive_in_both_directions
        """
        ctx = _backed_solution_dyed_run_with_roll()
        style_id = ctx["style"]["id"]
        roll_id = ctx["roll_good"]["id"]

        cases = [
            ("WEAR_TARR", 3.0, "PASS"),
            ("WEAR_TARR", 2.9, "FAIL"),
            ("STAIN_AATCC175", 8.0, "PASS"),
            ("FLAMMABILITY_PILL", 25.4, "PASS"),
            ("FLAMMABILITY_PILL", 25.5, "FAIL"),
        ]
        for test_type, result_value, expected_verdict in cases:
            recorded = validate_success(
                api.create_product_test(
                    factories.create_product_test_payload(
                        style_id,
                        roll_id,
                        test_type=test_type,
                        result_value=result_value,
                    ),
                    QA,
                ),
                expected_status=201,
            )
            assert recorded["verdict"] == expected_verdict, (
                f"a {test_type} reading of {result_value} must be "
                f"{expected_verdict}, got {recorded['verdict']}"
            )

        _, meta = validate_paginated(
            api.list_product_tests(
                QA,
                params={
                    "roll_good_id": roll_id,
                    "verdict": "FAIL",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 2, (
            f"exactly the 2.9 wear reading and the 25.5 pill reading fail, got "
            f"{meta['total_count']} FAIL results"
        )

        roll = fixtures.refresh_roll_good(roll_id)
        assert roll["qa_status"] == "PENDING", (
            f"recording tests must not disposition the roll, expected PENDING, got "
            f"{roll['qa_status']}"
        )


class TestCertificateIssuance:
    def test_reissuing_same_cert_type_supersedes_the_prior_certificate(self, api):
        """A second DOC_FF_1_70 for the style flips the first to SUPERSEDED rather
        than creating a second live certificate.

        PRD: "Any prior certificate for the same style with the same `cert_type` and a
        `status` of `ACTIVE` transitions `ACTIVE` to `SUPERSEDED`, which is terminal —
        a style holds at most one live certificate per type."
        PRD: "An optional `accounting_basis` declares the recycled-content accounting
        model and takes one of `MASS_BALANCE`, `PHYSICAL_SEGREGATION` or
        `NOT_APPLICABLE`, defaulting to `NOT_APPLICABLE`"

        Design: Corner/state_machines/reissuing_same_cert_type_supersedes_the_prior_certificate
        """
        ctx = _backed_solution_dyed_run_with_roll()
        style_id = ctx["style"]["id"]
        roll_id = ctx["roll_good"]["id"]
        first_test = fixtures.record_product_test(
            style_id, roll_id, test_type="FLAMMABILITY_PILL", result_value=18.0
        )
        second_test = fixtures.record_product_test(
            style_id, roll_id, test_type="FLAMMABILITY_PILL", result_value=12.0
        )
        first_cert = fixtures.issue_certification(
            style_id,
            [first_test["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2027-08-01T00:00:00Z",
        )

        second_cert = validate_success(
            api.create_certification(
                factories.create_certification_payload(
                    style_id,
                    [second_test["id"]],
                    cert_type="DOC_FF_1_70",
                    expires_at_utc="2028-08-01T00:00:00Z",
                ),
                CERTIFIER,
            ),
            expected_status=201,
        )

        assert second_cert["status"] == "ACTIVE", (
            f"the reissued certificate must be ACTIVE, got {second_cert['status']}"
        )
        assert second_cert["expires_at_utc"].startswith("2028-08-01T00:00:00"), (
            f"expected the new expiry 2028-08-01T00:00:00Z, got "
            f"{second_cert['expires_at_utc']}"
        )
        assert second_cert["accounting_basis"] == "NOT_APPLICABLE", (
            f"a DOC_FF_1_70 defaults accounting_basis to NOT_APPLICABLE, got "
            f"{second_cert['accounting_basis']}"
        )

        superseded = fixtures.refresh_certification(first_cert["id"])
        assert superseded["status"] == "SUPERSEDED", (
            f"the prior DOC_FF_1_70 must be SUPERSEDED, got {superseded['status']}"
        )
        assert superseded["expires_at_utc"].startswith("2027-08-01T00:00:00"), (
            f"the superseded certificate keeps its own expiry, got "
            f"{superseded['expires_at_utc']}"
        )
        assert superseded["source_test_ids"] == [first_test["id"]], (
            f"the superseded certificate keeps its own evidence, got "
            f"{superseded['source_test_ids']}"
        )

        active, meta = validate_paginated(
            api.list_certifications(
                CERTIFIER,
                params={
                    "style_id": style_id,
                    "cert_type": "DOC_FF_1_70",
                    "status": "ACTIVE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"a style holds at most one live certificate per type, got "
            f"{meta['total_count']} active DOC_FF_1_70 certificates"
        )
        assert active[0]["id"] == second_cert["id"], (
            f"expected the reissued certificate {second_cert['id']}, got "
            f"{active[0]['id']}"
        )

        style = fixtures.refresh_style(style_id)
        assert style["status"] == "ACTIVE", (
            f"the style stays ACTIVE across the reissue, got {style['status']}"
        )

    def test_green_label_plus_without_both_passing_tests_returns_cert_evidence_missing(
        self, api
    ):
        """GREEN_LABEL_PLUS needs a passing stain test as well as a passing wear test,
        and a failing stain test does not satisfy the stain arm.

        PRD: "A `GREEN_LABEL_PLUS` certificate requires at least one
        `STAIN_AATCC175` test with a `verdict` of `PASS` and at least one `WEAR_TARR`
        test with a `verdict` of `PASS`, both on the style."
        PRD: "A failure of any part of this check yields `ERR_CERT_EVIDENCE_MISSING`
        at HTTP 422."

        Design: Corner/validations/green_label_plus_without_both_passing_tests_returns_cert_evidence_missing
        """
        ctx = _backed_solution_dyed_run_with_roll()
        style_id = ctx["style"]["id"]
        roll_id = ctx["roll_good"]["id"]
        wear = fixtures.record_product_test(
            style_id, roll_id, test_type="WEAR_TARR", result_value=4.0
        )
        failing_stain = fixtures.record_product_test(
            style_id, roll_id, test_type="STAIN_AATCC175", result_value=7.9
        )
        assert wear["verdict"] == "PASS", (
            f"a WEAR_TARR reading of 4.0 passes, got {wear['verdict']}"
        )
        assert failing_stain["verdict"] == "FAIL", (
            f"a STAIN_AATCC175 reading of 7.9 fails the 8.0 floor, got "
            f"{failing_stain['verdict']}"
        )

        wear_only = api.create_certification(
            factories.create_certification_payload(
                style_id,
                [wear["id"]],
                cert_type="GREEN_LABEL_PLUS",
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            CERTIFIER,
        )
        validate_error(wear_only, "ERR_CERT_EVIDENCE_MISSING")

        with_failing_stain = api.create_certification(
            factories.create_certification_payload(
                style_id,
                [wear["id"], failing_stain["id"]],
                cert_type="GREEN_LABEL_PLUS",
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            CERTIFIER,
        )
        validate_error(with_failing_stain, "ERR_CERT_EVIDENCE_MISSING")

        passing_stain = fixtures.record_product_test(
            style_id, roll_id, test_type="STAIN_AATCC175", result_value=8.0
        )
        assert passing_stain["verdict"] == "PASS", (
            f"a STAIN_AATCC175 reading of 8.0 passes inclusively, got "
            f"{passing_stain['verdict']}"
        )

        issued = validate_success(
            api.create_certification(
                factories.create_certification_payload(
                    style_id,
                    [wear["id"], passing_stain["id"]],
                    cert_type="GREEN_LABEL_PLUS",
                    expires_at_utc="2027-08-01T00:00:00Z",
                ),
                CERTIFIER,
            ),
            expected_status=201,
        )
        assert issued["status"] == "ACTIVE", (
            f"expected the issued certificate ACTIVE, got {issued['status']}"
        )
        assert issued["cert_type"] == "GREEN_LABEL_PLUS", (
            f"expected cert_type GREEN_LABEL_PLUS, got {issued['cert_type']}"
        )
        assert issued["certified_by_user_id"] == CERT_OFFICER_ID, (
            f"expected certified_by_user_id {CERT_OFFICER_ID}, got "
            f"{issued['certified_by_user_id']}"
        )
        assert issued["accounting_basis"] == "NOT_APPLICABLE", (
            f"a non-NSF_140 certificate defaults to NOT_APPLICABLE, got "
            f"{issued['accounting_basis']}"
        )

        _, meta = validate_paginated(
            api.list_certifications(
                CERTIFIER, params={"style_id": style_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"only the third attempt may have created a certificate, got "
            f"{meta['total_count']}"
        )

    def test_issuing_a_certificate_links_the_style_and_its_evidence_both_ways(self, api):
        """The certificate echoes the cited test, the style-scoped certificate list
        finds it, and the style-scoped test list still resolves the evidence.

        PRD: "The server stamps `certified_by_user_id` from the acting `X-User-ID`,
        stamps `issued_at_utc` from the logical clock, and sets `status` to `ACTIVE`."
        PRD: "for other certificate types that field stays null"
        PRD: "Tests may be read individually or listed filtered by `style_id`,
        `roll_good_id`, `test_type` and `verdict`."

        Design: Corner/endpoints/issuing_a_certificate_links_the_style_and_its_evidence_both_ways
        """
        ctx = _backed_solution_dyed_run_with_roll()
        style_id = ctx["style"]["id"]
        pill_test = fixtures.record_product_test(
            style_id,
            ctx["roll_good"]["id"],
            test_type="FLAMMABILITY_PILL",
            result_value=18.0,
        )

        cert = validate_success(
            api.create_certification(
                factories.create_certification_payload(
                    style_id,
                    [pill_test["id"]],
                    cert_type="DOC_FF_1_70",
                    expires_at_utc="2027-08-01T00:00:00Z",
                ),
                CERTIFIER,
            ),
            expected_status=201,
        )

        assert cert["source_test_ids"] == [pill_test["id"]], (
            f"expected the certificate to echo the cited test, got "
            f"{cert['source_test_ids']}"
        )
        assert cert["style_id"] == style_id, (
            f"expected style_id {style_id} on the certificate, got {cert['style_id']}"
        )
        assert cert["status"] == "ACTIVE", (
            f"a fresh certificate is ACTIVE, got {cert['status']}"
        )
        assert cert["issued_at_utc"].startswith("2026-08-05T08:00:00"), (
            f"issued_at_utc must be stamped from the logical clock at "
            f"{RUN_WINDOW_OPEN}, got {cert['issued_at_utc']}"
        )
        assert cert["certified_by_user_id"] == CERT_OFFICER_ID, (
            f"expected certified_by_user_id {CERT_OFFICER_ID}, got "
            f"{cert['certified_by_user_id']}"
        )
        assert cert["recorded_recycled_content_pct"] is None, (
            "recorded_recycled_content_pct stays null outside NSF_140, got "
            f"{cert['recorded_recycled_content_pct']}"
        )

        read = validate_success(api.get_certification(cert["id"], PLANNER))
        assert read["source_test_ids"] == [pill_test["id"]], (
            f"the read must return the same evidence pointer, got "
            f"{read['source_test_ids']}"
        )

        certs, cert_meta = validate_paginated(
            api.list_certifications(
                PLANNER,
                params={
                    "style_id": style_id,
                    "cert_type": "DOC_FF_1_70",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert cert_meta["total_count"] == 1, (
            f"the style-scoped certificate list must find exactly one, got "
            f"{cert_meta['total_count']}"
        )
        assert certs[0]["id"] == cert["id"], (
            f"expected certificate {cert['id']} in the style-scoped list, got "
            f"{certs[0]['id']}"
        )

        tests, test_meta = validate_paginated(
            api.list_product_tests(
                PLANNER, params={"style_id": style_id, "limit": 10, "offset": 0}
            )
        )
        assert test_meta["total_count"] == 1, (
            f"the style-scoped test list must still resolve the evidence, got "
            f"{test_meta['total_count']}"
        )
        assert tests[0]["id"] == pill_test["id"], (
            f"expected the cited test {pill_test['id']}, got {tests[0]['id']}"
        )
        assert tests[0]["tested_by_user_id"] == QA_TECH_ID, (
            f"the evidence was produced by {QA_TECH_ID}, got "
            f"{tests[0]['tested_by_user_id']}"
        )

    def test_certificate_issued_by_the_testing_technician_returns_segregation_of_duties(
        self, api
    ):
        """The role is right and the evidence is right; only the acting user id
        matches the technician who ran the cited test.

        PRD: "At issuance, the officer's own identifier is compared against
        `tested_by_user_id` on every test named in `source_test_ids`; if it matches
        even one of them, issuance is refused with `ERR_SEGREGATION_OF_DUTIES` and
        HTTP status 409."

        Design: Corner/rbac/certificate_issued_by_the_testing_technician_returns_segregation_of_duties
        """
        ctx = _backed_solution_dyed_run_with_roll()
        style_id = ctx["style"]["id"]
        pill_test = fixtures.record_product_test(
            style_id,
            ctx["roll_good"]["id"],
            test_type="FLAMMABILITY_PILL",
            result_value=18.0,
        )
        payload = factories.create_certification_payload(
            style_id,
            [pill_test["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2027-08-01T00:00:00Z",
        )

        self_certified = api.create_certification(
            payload, make_certification_officer_headers(QA_TECH_ID)
        )

        validate_error(self_certified, "ERR_SEGREGATION_OF_DUTIES")

        issued = validate_success(
            api.create_certification(payload, CERTIFIER), expected_status=201
        )
        assert issued["certified_by_user_id"] == CERT_OFFICER_ID, (
            f"the identical payload under a different officer must record "
            f"{CERT_OFFICER_ID}, got {issued['certified_by_user_id']}"
        )

        _, meta = validate_paginated(
            api.list_certifications(
                CERTIFIER, params={"style_id": style_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused self-certification must write nothing, got "
            f"{meta['total_count']} certificates after both calls"
        )

        evidence = validate_success(api.get_product_test(pill_test["id"], CERTIFIER))
        assert evidence["tested_by_user_id"] == QA_TECH_ID, (
            f"expected tested_by_user_id {QA_TECH_ID} on the evidence, got "
            f"{evidence['tested_by_user_id']}"
        )


class TestRecycledContentDiagnostic:
    def test_recycled_content_read_reports_zero_under_both_bases_for_a_virgin_style(
        self, api
    ):
        """A GREIGE run already qualifies, so the read names its batch and its full
        4000.000 kg while both bases read 0.00 on virgin feedstock.

        PRD: "the qualifying mass set is assembled by walking the style's production
        runs whose status is `GREIGE`, `BACKED` or `RELEASED`"
        PRD: "The same computation is also exposed as a read-only diagnostic on a
        style, which reports `mass_balance_pct` and `physical_segregation_pct` — the
        percentage under each basis — together with `qualifying_kg`, the total
        qualifying mass, and `qualifying_fiber_batch_ids`, the deduplicated list of
        fiber batches that contributed."

        Design: Corner/endpoints/recycled_content_read_reports_zero_under_both_bases_for_a_virgin_style
        """
        lot = fixtures.create_polymer_lot(
            lot_code="PL-N66-01",
            polymer_type="NYLON_66",
            received_kg=5000.0,
            melt_flow_index=18.0,
        )
        fiber_batch = fixtures.create_released_fiber_batch(
            lot["id"], batch_code="FB-01", input_kg=4000.0
        )
        style = fixtures.create_active_style()
        machine = fixtures.create_tufting_machine()
        run = fixtures.create_scheduled_run(
            style["id"], machine["id"], fiber_batch["id"]
        )
        fixtures.advance_run_to_greige(run["id"])

        data = validate_success(
            api.get_style_recycled_content(style["id"], CERTIFIER)
        )

        assert data["mass_balance_pct"] == pytest.approx(0.00, abs=0.01), (
            f"virgin feedstock credits nothing on mass balance, got "
            f"{data['mass_balance_pct']}"
        )
        assert data["physical_segregation_pct"] == pytest.approx(0.00, abs=0.01), (
            f"virgin feedstock credits nothing on physical segregation, got "
            f"{data['physical_segregation_pct']}"
        )
        assert data["qualifying_kg"] == pytest.approx(4000.000, abs=0.001), (
            f"a GREIGE run already contributes its creel, expected qualifying_kg "
            f"4000.000, got {data['qualifying_kg']}"
        )
        assert data["qualifying_fiber_batch_ids"] == [fiber_batch["id"]], (
            f"expected the greige run's batch in the qualifying set, got "
            f"{data['qualifying_fiber_batch_ids']}"
        )

        greige_run = fixtures.refresh_run(run["id"])
        assert greige_run["status"] == "GREIGE", (
            f"the contributing run must be GREIGE, got {greige_run['status']}"
        )


class TestLogicalClockAdvanceReport:
    def test_advancing_the_clock_reports_lapsed_certs_suspended_styles_and_held_runs(
        self, api
    ):
        """A certificate expiring at exactly the new instant lapses, its style
        suspends, and only the SCHEDULED run is held.

        PRD: "The response reports the resulting `current_utc` together with three
        arrays recording what the move set in motion: `lapsed_certification_ids`,
        `suspended_style_ids` and `held_production_run_ids`."
        PRD: "Advancing the logical clock to or past a certificate's `expires_at_utc`
        sets `status` to `LAPSED`, terminal, and the clock response lists every
        certificate so lapsed in `lapsed_certification_ids`."
        PRD: "when the affected style is left with no effective `DOC_FF_1_70`
        certificate, the style transitions `ACTIVE` to `SUSPENDED` and its
        `SCHEDULED` runs are held"

        Design: Corner/endpoints/advancing_the_clock_reports_lapsed_certs_suspended_styles_and_held_runs
        """
        ctx = _style_with_two_released_batches()
        style_id = ctx["style"]["id"]
        run_one = fixtures.create_scheduled_run(
            style_id, ctx["machine"]["id"], ctx["fiber_batch_one"]["id"], run_code="PR-01"
        )
        fixtures.advance_run_to_backed(run_one["id"], **dict(_BACKING))
        roll = fixtures.doff_roll_good(run_one["id"])
        pill_test = fixtures.record_product_test(
            style_id, roll["id"], test_type="FLAMMABILITY_PILL", result_value=18.0
        )
        cert = fixtures.issue_certification(
            style_id,
            [pill_test["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2026-08-10T00:00:00Z",
        )
        run_two = fixtures.create_scheduled_run(
            style_id,
            ctx["machine"]["id"],
            ctx["fiber_batch_two"]["id"],
            run_code="PR-02",
            scheduled_start_utc=SECOND_RUN_START,
            scheduled_end_utc=SECOND_RUN_END,
        )

        report = validate_success(
            api.set_clock(
                factories.set_clock_payload("2026-08-10T00:00:00Z"), ADMIN
            )
        )

        assert report["current_utc"].startswith("2026-08-10T00:00:00"), (
            f"expected current_utc at 2026-08-10T00:00:00Z, got {report['current_utc']}"
        )
        assert report["lapsed_certification_ids"] == [cert["id"]], (
            "the certificate expiring at exactly the new instant must lapse, got "
            f"{report['lapsed_certification_ids']}"
        )
        assert report["suspended_style_ids"] == [style_id], (
            f"the style losing its last certificate must suspend, got "
            f"{report['suspended_style_ids']}"
        )
        assert report["held_production_run_ids"] == [run_two["id"]], (
            f"only the SCHEDULED run may be held, got "
            f"{report['held_production_run_ids']}"
        )

        lapsed = fixtures.refresh_certification(cert["id"])
        assert lapsed["status"] == "LAPSED", (
            f"expected the certificate LAPSED, got {lapsed['status']}"
        )
        style = fixtures.refresh_style(style_id)
        assert style["status"] == "SUSPENDED", (
            f"expected the style SUSPENDED, got {style['status']}"
        )
        held = fixtures.refresh_run(run_two["id"])
        assert held["status"] == "HELD", (
            f"expected the scheduled run HELD, got {held['status']}"
        )
        untouched = fixtures.refresh_run(run_one["id"])
        assert untouched["status"] == "BACKED", (
            f"the run that produced the evidence is left alone, expected BACKED, got "
            f"{untouched['status']}"
        )
