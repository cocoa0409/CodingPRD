"""Changeover records: level/downtime matrix, rework loop, invalid transitions,
segregation of duties."""
from test_helpers import (
    ApiErrorId,
    assert_changeover_record,
    create_line,
    create_manual_changeover,
    create_product,
    make_quality_inspector_headers,
    make_sanitation_tech_headers,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]


def _two_products_d6(sku_a="CO-A", sku_b="CO-B", class_a="CORN_ONLY", class_b="CORN_ONLY"):
    pa = create_product(sku_code=sku_a, diameter_in="D6", allergen_class=class_a,
                        unit_weight_g=30)
    pb = create_product(sku_code=sku_b, diameter_in="D6", allergen_class=class_b,
                        unit_weight_g=31)
    return pa, pb


class TestChangeoverMatrix:
    def test_allergen_downgrade_forces_full_sanitation(self, api):
        """PRD §3.6: "Allergen classes are ranked: `CORN_ONLY` is rank 0,
        `WHEAT_FLOUR` is rank 1, `SOY_BLENDED` is rank 2." and "When the
        from-product's rank exceeds the to-product's rank — an allergen
        downgrade, moving to a stricter product — the level is
        `FULL_SANITATION`."
        SOY_BLENDED (rank 2) -> CORN_ONLY (rank 0) forces FULL_SANITATION.

        Design: Difficulty/combinatorial_formula/changeover_matrix_allergen_downgrade_full_sanitation
        """
        line = create_line(line_code="L-CO")
        soy, corn = _two_products_d6("SOY-6-12", "CORN-6-12B", "SOY_BLENDED", "CORN_ONLY")
        record = validate_success(
            api.create_changeover(
                {
                    "line_id": line["id"],
                    "from_product_id": soy["id"],
                    "to_product_id": corn["id"],
                },
                make_sanitation_tech_headers("san-01"),
            ),
            201,
        )
        assert_changeover_record(record)
        assert record["required_level"] == "FULL_SANITATION"
        assert record["changeover_status"] == "REQUIRED"

    def test_full_sanitation_suppresses_diameter_penalty(self, api):
        """PRD §3.6: "Base downtime is 30 minutes for `FLUSH`, 60 for `WET_WASH`,
        120 for `FULL_SANITATION`. A diameter penalty of 15 additional minutes
        applies when the two products' `diameter_in` values differ and the level
        is not `FULL_SANITATION`. `required_downtime_min` is the base plus the
        diameter penalty."
        Even with a diameter change, FULL_SANITATION stays exactly 120 minutes —
        the penalty is suppressed.

        Design: Difficulty/combinatorial_formula/changeover_matrix_allergen_downgrade_full_sanitation
        """
        line = create_line(line_code="L-CO")
        soy = create_product(sku_code="SOY-6-12", diameter_in="D6",
                             allergen_class="SOY_BLENDED", unit_weight_g=32)
        corn = create_product(sku_code="CORN-8-12B", diameter_in="D8",
                              allergen_class="CORN_ONLY", unit_weight_g=30)
        record = validate_success(
            api.create_changeover(
                {
                    "line_id": line["id"],
                    "from_product_id": soy["id"],
                    "to_product_id": corn["id"],
                },
                make_sanitation_tech_headers("san-01"),
            ),
            201,
        )
        assert record["required_level"] == "FULL_SANITATION"
        assert record["required_downtime_min"] == 120, (
            "diameter penalty is suppressed at FULL_SANITATION: 120, not 135"
        )


class TestChangeoverReworkLoop:
    def test_fail_increments_fail_count(self, api):
        """PRD §3.6: "Failure returns it from `IN_PROGRESS` to `FAILED` and
        increments `fail_count` by one." Level check — same allergen class with
        differing diameters: "When both products share the same allergen class,
        the level is `FLUSH` if their `diameter_in` values match, else
        `WET_WASH`." plus "A diameter penalty of 15 additional minutes applies
        when the two products' `diameter_in` values differ and the level is not
        `FULL_SANITATION`." -> WET_WASH 60 + 15 = 75.

        Design: Difficulty/non_linear_state_machine/changeover_failed_rework_loop
        """
        line = create_line(line_code="L-RW")
        p6 = create_product(sku_code="CORN-6-A", diameter_in="D6", unit_weight_g=30)
        p8 = create_product(sku_code="CORN-8-A", diameter_in="D8", unit_weight_g=42)
        record = create_manual_changeover(line["id"], p6["id"], p8["id"])
        assert record["required_level"] == "WET_WASH"
        assert record["required_downtime_min"] == 75
        validate_success(
            api.begin_changeover(record["id"], make_sanitation_tech_headers("san-01"))
        )
        failed = validate_success(
            api.fail_changeover(record["id"], make_quality_inspector_headers("qi-01"))
        )
        assert failed["changeover_status"] == "FAILED"
        assert failed["fail_count"] == 1

    def test_failed_record_rebegins_and_verifies(self, api):
        """PRD §3.6: "A `FAILED` record can be re-begun by a `SanitationTech`,
        looping back to `IN_PROGRESS`." and "Verification advances the record from
        `IN_PROGRESS` to `VERIFIED` and recomputes the owning line's
        `line_posture`."

        Design: Difficulty/non_linear_state_machine/changeover_failed_rework_loop
        """
        line = create_line(line_code="L-RW")
        p6 = create_product(sku_code="CORN-6-A", diameter_in="D6", unit_weight_g=30)
        p8 = create_product(sku_code="CORN-8-A", diameter_in="D8", unit_weight_g=42)
        record = create_manual_changeover(line["id"], p6["id"], p8["id"])
        validate_success(
            api.begin_changeover(record["id"], make_sanitation_tech_headers("san-01"))
        )
        validate_success(
            api.fail_changeover(record["id"], make_quality_inspector_headers("qi-01"))
        )
        rebegun = validate_success(
            api.begin_changeover(record["id"], make_sanitation_tech_headers("san-02"))
        )
        assert rebegun["changeover_status"] == "IN_PROGRESS"
        verified = validate_success(
            api.verify_changeover(record["id"], make_quality_inspector_headers("qi-01"))
        )
        assert verified["changeover_status"] == "VERIFIED"

    def test_verify_from_required_rejected(self, api):
        """PRD §3.6: "Verification advances the record from `IN_PROGRESS` to
        `VERIFIED` and recomputes the owning line's `line_posture`." A record
        still in REQUIRED has nothing to verify; the from-state check fails with
        ERR_CHANGEOVER_INVALID_STATE (§5).

        Design: Corner/state_machines/sm_changeover_verify_from_required_rejected
        """
        line = create_line(line_code="L-CV")
        pa, pb = _two_products_d6("CV-A", "CV-B", "CORN_ONLY", "WHEAT_FLOUR")
        record = create_manual_changeover(line["id"], pa["id"], pb["id"])
        validate_error(
            api.verify_changeover(record["id"], make_quality_inspector_headers("qi-01")),
            ApiErrorId.ERR_CHANGEOVER_INVALID_STATE,
        )


class TestSegregationOfDuties:
    def test_performer_cannot_verify_own_changeover(self, api):
        """PRD §3.6: "Segregation of duties is enforced at both gates: the
        verifying or failing inspector's `X-User-ID` must differ from the
        recorded `performed_by` — a match is rejected with `ERR_SOD_VIOLATION`."
        san-01 performed the work; an inspector presenting X-User-ID san-01 is
        rejected, while qi-02 verifies successfully.

        Design: Corner/rbac/rbac_sod_performer_cannot_verify_own_changeover
        """
        line = create_line(line_code="L-SOD")
        pa, pb = _two_products_d6("SOD-A", "SOD-B")
        record = create_manual_changeover(
            line["id"], pa["id"], pb["id"], performer="san-01"
        )
        validate_success(
            api.begin_changeover(record["id"], make_sanitation_tech_headers("san-01"))
        )
        validate_error(
            api.verify_changeover(record["id"], make_quality_inspector_headers("san-01")),
            ApiErrorId.ERR_SOD_VIOLATION,
        )
        verified = validate_success(
            api.verify_changeover(record["id"], make_quality_inspector_headers("qi-02"))
        )
        assert verified["changeover_status"] == "VERIFIED"
