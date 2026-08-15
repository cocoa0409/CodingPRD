"""AQL sampling plan: lot-size code letters, acceptance/rejection numbers,
critical and minor defect branches, and the sample-size mismatch guard."""
from test_helpers import (
    ApiErrorId,
    advance_to_production_complete,
    book_inspection,
    create_inspection_payload,
    create_inspector,
    get_inspection,
    get_purchase_order,
    make_inspector_headers,
    make_sourcing_agent_headers,
    record_result,
    setup_po_scenario,
    validate_error,
    validate_success,
)


def _po_complete(ordered_qty):
    ctx = setup_po_scenario(ordered_qty=ordered_qty, unit_price_cents=100,
                            with_inspector=True)
    advance_to_production_complete(ctx)
    return ctx


class TestSampleSizeTable:
    def test_aql_sample_size_table_boundaries(self, api):
        """PRD: "`lot_size` at most 500 → `n` = 50."
        PRD: "`lot_size` between 501 and 1200 inclusive → `n` = 80. Exactly 501 therefore yields 80, not 50."
        PRD: "`lot_size` between 1201 and 3200 inclusive → `n` = 125."

        Design: Corner/calculations/aql_sample_size_table_boundaries
        """
        ctx = _po_complete(ordered_qty=3201)
        expected = {500: 50, 501: 80, 1200: 80, 1201: 125}
        for lot_size, expected_n in expected.items():
            inspector = create_inspector(name=f"I{lot_size}")
            inspection = book_inspection(
                ctx["po"]["id"], ctx["agent"]["id"], inspector["id"],
                inspection_type="PSI", scheduled_date="2026-08-10",
                duration_days=1, lot_size=lot_size,
            )
            assert inspection["sample_size"] == expected_n, (
                f"lot_size {lot_size}: expected sample_size {expected_n}, "
                f"got {inspection['sample_size']}"
            )


class TestAcceptanceBoundary:
    def _two_psi(self):
        """PO (500 units) PRODUCTION_COMPLETE with two PSI bookings, lot 500."""
        ctx = _po_complete(ordered_qty=500)
        in1 = create_inspector("Inspector One")
        in2 = create_inspector("Inspector Two", "CN-North")
        i_pass = book_inspection(ctx["po"]["id"], ctx["agent"]["id"], in1["id"],
                                 inspection_type="PSI", scheduled_date="2026-08-10",
                                 duration_days=1, lot_size=500)
        i_fail = book_inspection(ctx["po"]["id"], ctx["agent"]["id"], in2["id"],
                                 inspection_type="PSI", scheduled_date="2026-08-10",
                                 duration_days=1, lot_size=500)
        return ctx, in1, in2, i_pass, i_fail

    def test_aql_major_defects_at_ac_passes(self, api):
        """PRD: "`n` = 50 → `Ac` 3, `Re` 4."
        PRD: "the inspection is `FAILED` if `defects_critical` is greater than 0; otherwise it is `FAILED` if `defects_major` is at least `Re`; otherwise it is `FAILED` if `defects_minor` is greater than twice `Ac`; otherwise it is `PASSED`. The boundary case `defects_major` exactly equal to `Ac` passes."

        Design: Difficulty/boundary_precision_check/aql_major_defects_ac_re_boundary
        """
        ctx, in1, in2, i_pass, i_fail = self._two_psi()
        assert i_pass["sample_size"] == 50
        recorded = record_result(i_pass["id"], in1["id"],
                                 defects_critical=0, defects_major=3, defects_minor=6)
        assert recorded["result"] == "PASSED"

    def test_aql_major_defects_at_re_fails(self, api):
        """PRD: "`n` = 50 → `Ac` 3, `Re` 4."
        PRD: "otherwise it is `FAILED` if `defects_major` is at least `Re`"

        Design: Difficulty/boundary_precision_check/aql_major_defects_ac_re_boundary
        """
        ctx, in1, in2, i_pass, i_fail = self._two_psi()
        recorded = record_result(i_fail["id"], in2["id"],
                                 defects_critical=0, defects_major=4, defects_minor=0)
        assert recorded["result"] == "FAILED"


class TestCriticalAndMinorBranches:
    def test_aql_critical_defect_auto_fail_and_minor_cap(self, api):
        """PRD: "The result is then determined by three checks applied in order: the inspection is `FAILED` if `defects_critical` is greater than 0; otherwise it is `FAILED` if `defects_major` is at least `Re`; otherwise it is `FAILED` if `defects_minor` is greater than twice `Ac`; otherwise it is `PASSED`."
        PRD: "When the inspection is a `PSI`, the PO's `latest_psi_result` is rewritten to this result"

        Design: Corner/calculations/aql_critical_defect_auto_fail_and_minor_cap
        """
        ctx = _po_complete(ordered_qty=200)
        in1 = create_inspector("I1")
        in2 = create_inspector("I2")
        in3 = create_inspector("I3")
        i_crit = book_inspection(ctx["po"]["id"], ctx["agent"]["id"], in1["id"],
                                 inspection_type="PSI", scheduled_date="2026-08-10",
                                 duration_days=1, lot_size=200)
        i_minf = book_inspection(ctx["po"]["id"], ctx["agent"]["id"], in2["id"],
                                 inspection_type="PSI", scheduled_date="2026-08-10",
                                 duration_days=1, lot_size=200)
        i_minp = book_inspection(ctx["po"]["id"], ctx["agent"]["id"], in3["id"],
                                 inspection_type="PSI", scheduled_date="2026-08-10",
                                 duration_days=1, lot_size=200)

        r_crit = record_result(i_crit["id"], in1["id"], 1, 0, 0)
        assert r_crit["result"] == "FAILED"
        r_minf = record_result(i_minf["id"], in2["id"], 0, 0, 7)
        assert r_minf["result"] == "FAILED"  # minor 7 > 2 * Ac(3) == 6
        r_minp = record_result(i_minp["id"], in3["id"], 0, 0, 6)
        assert r_minp["result"] == "PASSED"  # minor 6 not > 6

        po = get_purchase_order(ctx["po"]["id"])
        assert po["latest_psi_result"] == "PASSED"


class TestSampleMismatch:
    def test_error_aql_sample_mismatch_trigger(self, api):
        """PRD: "The sum of the three defect counts may not exceed `sample_size` (`ERR_AQL_SAMPLE_MISMATCH`, HTTP 422)."

        Design: Corner/errors/error_aql_sample_mismatch_trigger
        """
        ctx = _po_complete(ordered_qty=10)
        inspection = book_inspection(ctx["po"]["id"], ctx["agent"]["id"],
                                     ctx["inspector"]["id"], inspection_type="PSI",
                                     scheduled_date="2026-08-10", duration_days=1,
                                     lot_size=10)
        assert inspection["sample_size"] == 50
        validate_error(
            api.record_inspection_result(
                inspection["id"],
                {"defects_critical": 20, "defects_major": 20, "defects_minor": 20},
                make_inspector_headers(ctx["inspector"]["id"]),
            ),
            ApiErrorId.ERR_AQL_SAMPLE_MISMATCH,
        )
        after = get_inspection(inspection["id"])
        assert after["status"] == "BOOKED"
        assert after["result"] == "NONE"
