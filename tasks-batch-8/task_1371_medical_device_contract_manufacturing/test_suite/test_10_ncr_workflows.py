"""Nonconformance reports: supplier-fault cascades, closure segregation."""
from test_helpers import (
    QE_ALICE,
    ApiErrorId,
    add_component,
    create_lot,
    create_ncr,
    create_part,
    create_qualified_supplier,
    create_validated_stack,
    contain_ncr,
    disposition_ncr,
    get_lot,
    get_part,
    get_supplier,
    make_quality_manager_headers,
    qe,
    qm,
    validate_error,
    validate_success,
    api_client,
)


class TestNcrSupplierFaultDispositionChain:
    def _setup(self):
        stack = create_validated_stack("DEV-N")
        qs = create_qualified_supplier("SUP-N", "Norge Med")
        part1 = create_part(qs["supplier"]["id"], "PN-N1", description="pump", receive_qty=100)
        part2 = create_part(qs["supplier"]["id"], "PN-N2", description="sensor", receive_qty=100)
        lot1 = create_lot("LT-N1", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot1["id"], part1["id"], quantity_used=10, supplier_lot_number="SL-N1")
        lot2 = create_lot("LT-N2", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot2["id"], part2["id"], quantity_used=10, supplier_lot_number="SL-N2")
        return qs, part1, part2, lot1, lot2

    def test_first_supplier_fault_disposition_holds_part_and_lot(self, api):
        """PRD section 3.7: "when `fault` is `SUPPLIER`, the severity penalty — 5
        points for `MINOR`, 15 for `MAJOR`, 30 for `CRITICAL` — is recorded as
        `penalty_points_applied`, added to the supplier's
        `applied_penalty_points`, and `quality_score` is recomputed" and "when
        `supplier_part_id` is also set, that part moves to `ON_HOLD` and its
        in-flight lots are held `SUPPLIER_QUALITY`."

        Design: Difficulty/transitive_cascade/ncr_supplier_fault_disposition_chain
        """
        qs, part1, _part2, lot1, _lot2 = self._setup()
        ncr1 = create_ncr(
            ncr_code="NCR-N1", severity="CRITICAL", description="pump crack",
            supplier_part_id=part1["id"],
        )
        contain_ncr(ncr1["id"])
        dispositioned = disposition_ncr(ncr1["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        assert dispositioned["penalty_points_applied"] == 30

        assert get_supplier(qs["supplier"]["id"])["quality_score"] == 70
        assert get_part(part1["id"])["status"] == "ON_HOLD"
        held = get_lot(lot1["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "SUPPLIER_QUALITY"

    def test_second_critical_ncr_crosses_auto_suspend_threshold(self, api):
        """PRD section 2.9: "Whenever a recomputation leaves `quality_score`
        below 50 on a supplier that is `QUALIFIED`, the supplier is automatically
        suspended — with the same part-and-lot cascade as a manual suspension
        (§3.4)." and PRD section 3.4: "every `QUALIFIED` part of the supplier
        moves to `ON_HOLD`, and every lot in `IN_PRODUCTION` or `COMPLETED` whose
        recorded components include any of those parts is placed `ON_HOLD` with
        `hold_reason` `SUPPLIER_QUALITY`."

        Design: Difficulty/transitive_cascade/ncr_supplier_fault_disposition_chain
        """
        qs, part1, part2, lot1, lot2 = self._setup()
        ncr1 = create_ncr(
            ncr_code="NCR-N1", severity="CRITICAL", description="pump crack",
            supplier_part_id=part1["id"],
        )
        contain_ncr(ncr1["id"])
        disposition_ncr(ncr1["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")

        ncr2 = create_ncr(
            ncr_code="NCR-N2", severity="CRITICAL", description="sensor drift",
            supplier_part_id=part2["id"],
        )
        contain_ncr(ncr2["id"])
        dispositioned2 = disposition_ncr(ncr2["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        assert dispositioned2["penalty_points_applied"] == 30

        supplier = get_supplier(qs["supplier"]["id"])
        assert supplier["quality_score"] == 40, (
            f"100 - 30 - 30 must equal 40, got {supplier['quality_score']}"
        )
        assert supplier["status"] == "SUSPENDED", "40 < 50 must auto-suspend"
        assert get_part(part2["id"])["status"] == "ON_HOLD"
        held2 = get_lot(lot2["id"])
        assert held2["hold_status"] == "ON_HOLD"
        assert held2["hold_reason"] == "SUPPLIER_QUALITY"
        held1 = get_lot(lot1["id"])
        assert held1["hold_status"] == "ON_HOLD", "lot1 must still be held from the first disposition"


class TestNcrClosure:
    def test_ncr_close_segregation_of_duties(self, api):
        """PRD section 2.6: "The operator closing a nonconformance report must
        not be its `initiator_user_id`." and PRD section 3.7: "Closure is
        reserved for a `QualityManager` who is not the report's initiator
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/ncr_close_segregation_of_duties
        """
        qs = create_qualified_supplier("SUP-NS", "NS Co")
        part = create_part(qs["supplier"]["id"], "PN-NS", description="nut")
        ncr = create_ncr(
            ncr_code="NCR-NS", severity="MINOR", description="rust",
            supplier_part_id=part["id"], author=QE_ALICE,
        )
        contain_ncr(ncr["id"])
        disposition_ncr(ncr["id"], "USE_AS_IS", "INTERNAL")

        resp = api.close_ncr(ncr["id"], make_quality_manager_headers(QE_ALICE))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_ncr(ncr["id"], qm()))
        assert current["status"] == "DISPOSITIONED"

        closed = validate_success(api.close_ncr(ncr["id"], qm()))
        assert closed["status"] == "CLOSED"
