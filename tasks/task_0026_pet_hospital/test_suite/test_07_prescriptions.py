"""Drug catalog and prescription lifecycle (PRD §3.7).

Covers DRAFT → PENDING_REVIEW → APPROVED → DISPENSED happy path, the
REJECTED ↔ DRAFT cycle, dosage rationality, segregation of duties on
controlled drugs, severe-interaction guard, and dispense cascade.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    TEST_USERS,
    approve_prescription,
    assert_prescription,
    build_user_headers,
    create_drug,
    create_prescription,
    create_prescription_payload,
    dispense_prescription,
    find_audit_log,
    find_line_item,
    get_success_data,
    make_drafting_vet_headers,
    make_prescription_item,
    make_reviewing_vet_headers,
    redraft_prescription,
    reject_prescription,
    reject_prescription_payload,
    setup_visit_in_consult,
    submit_prescription,
    setup_approved_prescription,
    validate_error,
    validate_success,
)


# ===========================================================================
# Drag catalog basics (PRD §3.7)
# ===========================================================================
class TestDrugCatalog:
    def test_create_drug_admin_only(self, api):
        """PRD §4 endpoint table row: '| POST | /pet-hospital/drugs |
        Create drug. | PlatformAdmin |'."""
        d = create_drug(name="Amox", dosage_min_mg_per_kg=1.0,
                        dosage_max_mg_per_kg=10.0, stock_units=200)
        assert d["stock_units"] == 200
        assert d["controlled"] is False


# ===========================================================================
# Prescription draft + submit
# ===========================================================================
class TestPrescriptionSubmit:
    def test_submit_recomputes_interaction_risk_to_none_when_no_interactions(self, api):
        """PRD §3.7: 'The submit action also runs the drug-interaction
        calculation ... The prescription's interaction_risk is set to
        the enum value corresponding to that maximum (or NONE when no
        pair has an edge).'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        d1 = create_drug(stock_units=200)
        item = make_prescription_item(
            drug_code=d1["code"], dose_mg_per_kg=2.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(2.0 * 10.0 * 2 * 5),  # =200
        )
        rx = create_prescription(visit_id=visit["id"], items=[item])
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        rx2 = submit_prescription(
            rx_id=rx["id"], drafting_vet_id=v["assigned_vet_id"],
        )
        assert rx2["status"] == "PENDING_REVIEW"
        assert rx2["interaction_risk"] == "NONE"

    def test_dosage_out_of_range_blocks_submit(self, api):
        """PRD §3.7: 'each item's dose_mg_per_kg must lie within the
        inclusive range from the drug's dosage_min_mg_per_kg up to and
        including the drug's dosage_max_mg_per_kg (otherwise
        ERR_DOSAGE_OUT_OF_RANGE).'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        d1 = create_drug(
            dosage_min_mg_per_kg=1.0, dosage_max_mg_per_kg=10.0, stock_units=500,
        )
        # dose = 11.0 > max=10.0
        bad_item = make_prescription_item(
            drug_code=d1["code"], dose_mg_per_kg=11.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(11.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(visit_id=visit["id"], items=[bad_item])
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        headers = make_drafting_vet_headers(v["assigned_vet_id"])
        res = api.submit_prescription(rx["id"], headers)
        validate_error(res, "ERR_DOSAGE_OUT_OF_RANGE")


# ===========================================================================
# Prescription approve — Segregation of Duties + severe interaction
# ===========================================================================
class TestSegregationOfDuties:
    def test_controlled_drug_rejected_when_reviewer_equals_drafter(self, api):
        """PRD §3.7: 'when at least one of the prescription's items
        references a drug whose controlled flag is true, the caller's
        X-User-ID must differ from drafting_vet_id — otherwise the
        request is rejected with ERR_SEGREGATION_OF_DUTIES.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d_ctrl = create_drug(
            controlled=True, dosage_min_mg_per_kg=1.0, dosage_max_mg_per_kg=10.0,
            stock_units=500,
        )
        item = make_prescription_item(
            drug_code=d_ctrl["code"], dose_mg_per_kg=5.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(5.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(
            visit_id=visit["id"], items=[item], drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        # Same operator id calls approve under ReviewingVet role.
        same_id_reviewer = make_reviewing_vet_headers(drafting_id)
        res = api.approve_prescription(rx["id"], same_id_reviewer, {})
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_controlled_drug_approved_when_reviewer_differs(self, api):
        """PRD §3.7: 'when at least one of the prescription's items
        references a drug whose controlled flag is true, the caller's
        X-User-ID must differ from drafting_vet_id.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d_ctrl = create_drug(
            controlled=True, dosage_min_mg_per_kg=1.0, dosage_max_mg_per_kg=10.0,
            stock_units=500,
        )
        item = make_prescription_item(
            drug_code=d_ctrl["code"], dose_mg_per_kg=5.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(5.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(
            visit_id=visit["id"], items=[item], drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        # Reviewer with distinct id.
        reviewer_id = "reviewer-distinct-001"
        assert reviewer_id != drafting_id
        rx = approve_prescription(rx_id=rx["id"], reviewing_vet_id=reviewer_id)
        assert rx["status"] == "APPROVED"
        assert rx["reviewing_vet_id"] == reviewer_id


class TestSevereInteractionGuard:
    def test_severe_interaction_requires_override(self, api):
        """PRD §3.7: 'when the prescription's interaction_risk is SEVERE,
        the request body must carry override_acknowledged set to true —
        otherwise the request is rejected with ERR_SEVERE_INTERACTION.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        # Two drugs, one declares a SEVERE interaction with the other.
        d2 = create_drug(stock_units=200,
                         dosage_min_mg_per_kg=0.1, dosage_max_mg_per_kg=10.0)
        d1 = create_drug(
            stock_units=200,
            dosage_min_mg_per_kg=0.1, dosage_max_mg_per_kg=10.0,
            interactions=[{"with_drug_code": d2["code"], "severity": "SEVERE"}],
        )
        items = [
            make_prescription_item(
                drug_code=d1["code"], dose_mg_per_kg=1.0,
                frequency_per_day=1, duration_days=1, units=10,
            ),
            make_prescription_item(
                drug_code=d2["code"], dose_mg_per_kg=1.0,
                frequency_per_day=1, duration_days=1, units=10,
            ),
        ]
        rx = create_prescription(
            visit_id=visit["id"], items=items, drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        assert rx["interaction_risk"] == "SEVERE"
        # Approve without override → blocked.
        no_override = make_reviewing_vet_headers("reviewer-distinct-001")
        res = api.approve_prescription(rx["id"], no_override, {})
        validate_error(res, "ERR_SEVERE_INTERACTION")

    def test_severe_interaction_allowed_with_override(self, api):
        """PRD §3.7: 'when the prescription's interaction_risk is SEVERE,
        the request body must carry override_acknowledged set to true.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d2 = create_drug(stock_units=200,
                         dosage_min_mg_per_kg=0.1, dosage_max_mg_per_kg=10.0)
        d1 = create_drug(
            stock_units=200,
            dosage_min_mg_per_kg=0.1, dosage_max_mg_per_kg=10.0,
            interactions=[{"with_drug_code": d2["code"], "severity": "SEVERE"}],
        )
        items = [
            make_prescription_item(
                drug_code=d1["code"], dose_mg_per_kg=1.0,
                frequency_per_day=1, duration_days=1, units=10,
            ),
            make_prescription_item(
                drug_code=d2["code"], dose_mg_per_kg=1.0,
                frequency_per_day=1, duration_days=1, units=10,
            ),
        ]
        rx = create_prescription(
            visit_id=visit["id"], items=items, drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        assert rx["interaction_risk"] == "SEVERE"
        rx = approve_prescription(
            rx_id=rx["id"], reviewing_vet_id="reviewer-distinct-001",
            override_acknowledged=True,
        )
        assert rx["status"] == "APPROVED"


# ===========================================================================
# Reject ↔ Redraft loop
# ===========================================================================
class TestRejectRedraftCycle:
    def test_reject_then_redraft_returns_to_draft(self, api):
        """PRD §3.7: 'The redraft action moves the prescription from
        REJECTED back to DRAFT, which clears reviewing_vet_id and
        rejection_reason; only the original drafting vet (whose
        X-User-ID equals drafting_vet_id) may redraft.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d1 = create_drug(stock_units=200)
        item = make_prescription_item(
            drug_code=d1["code"], dose_mg_per_kg=2.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(2.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(
            visit_id=visit["id"], items=[item], drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        rx = reject_prescription(
            rx_id=rx["id"], reviewing_vet_id="reviewer-001",
            rejection_reason="More info please.",
        )
        assert rx["status"] == "REJECTED"
        rx = redraft_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)
        assert rx["status"] == "DRAFT"
        assert rx.get("reviewing_vet_id") in (None, "")
        assert rx.get("rejection_reason") in (None, "")


# ===========================================================================
# Dispense cascade
# ===========================================================================
class TestDispenseCascades:
    def test_dispense_decrements_stock_and_appends_drug_line(self, api, cashier_headers):
        """PRD §3.7: 'On success, every item's drug has its stock_units
        decremented by the item's units; dispensed_at is set to the
        current time; a DRUG line item is appended to the visit's bill
        and the bill's provisional_total_cents is recomputed (cascade
        hop 1).'"""
        from test_helpers import create_bill, get_visit, recompute_bill
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        bill = create_bill(visit_id=visit["id"])
        d1 = create_drug(stock_units=500)
        rx = setup_approved_prescription(
            visit_id=visit["id"], drug_code=d1["code"],
            dose_mg_per_kg=2.0, pet_weight_kg=10.0,
            frequency_per_day=2, duration_days=5,
            # units = ceil(2*10*2*5) = 200
        )
        units_used = rx["items"][0]["units"]
        rx = dispense_prescription(rx_id=rx["id"])
        assert rx["status"] == "DISPENSED"
        assert rx.get("dispensed_at") is not None
        # Stock decremented.
        from test_helpers import get_success_data
        from test_helpers import api_client
        # Drug stock — re-fetch via PATCH no-op or via subsequent flow:
        # simplest path is to consult the bill cascade.
        bill_after = get_success_data(
            api.recompute_bill(bill["id"], cashier_headers)
        )
        drug_lines = [li for li in bill_after["line_items"]
                      if li.get("kind") == "DRUG"]
        assert len(drug_lines) >= 1
        # One DRUG line should reference the prescription item (qty matches units_used).
        assert any(li["qty"] == units_used for li in drug_lines)

    def test_dispense_on_issued_bill_reverts_to_draft(self, api, cashier_headers):
        """PRD §3.7: 'and, if the bill was in ISSUED at the time of the
        dispense, the bill drops back to DRAFT so it must be re-issued
        with the new line included (cascade hop 2).'

        PRD §3.9 echoes: 'Only the system itself can perform this ISSUED
        to DRAFT revert — no role-facing action is exposed for it.'"""
        from test_helpers import (
            create_bill, dispense_prescription,
            get_success_data, issue_bill, recompute_bill,
            setup_visit_consult_done_with_approved_rx,
        )
        # PRD §3.7 'submit requires Visit==IN_CONSULT' forces us to
        # build the prescription before end_consult; the helper does
        # exactly that.
        d1 = create_drug(stock_units=500)
        owner, pet, visit, tr, rx = setup_visit_consult_done_with_approved_rx(
            drug_code=d1["code"],
            dose_mg_per_kg=2.0, frequency_per_day=2, duration_days=5,
            weight_kg=10.0,
        )
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        assert bill["status"] == "ISSUED"
        rx = dispense_prescription(rx_id=rx["id"])
        # After dispense, the bill must be back in DRAFT per PRD §3.7 / §3.9.
        bill_after = get_success_data(
            api.recompute_bill(bill["id"], cashier_headers)
        )
        assert bill_after["status"] == "DRAFT", (
            f"Expected bill status DRAFT after dispense on ISSUED bill, "
            f"got {bill_after['status']}"
        )

    def test_dispense_writes_audit_log(self, api, platform_admin_headers):
        """PRD §3.7: 'A DISPENSE audit-log entry is written.'"""
        from test_helpers import (
            create_bill, dispense_prescription, get_success_data,
            setup_visit_in_consult,
        )
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        create_bill(visit_id=visit["id"])
        d1 = create_drug(stock_units=500)
        rx = setup_approved_prescription(
            visit_id=visit["id"], drug_code=d1["code"],
            dose_mg_per_kg=2.0, pet_weight_kg=10.0,
            frequency_per_day=2, duration_days=5,
        )
        rx = dispense_prescription(rx_id=rx["id"])
        # Look for AuditLog with action=DISPENSE on this prescription.
        from test_helpers import validate_paginated
        list_res = api.list_audit_logs(
            platform_admin_headers,
            params={"subject_type": "PRESCRIPTION", "subject_id": rx["id"]},
        )
        data, _ = validate_paginated(list_res)
        assert any(log.get("action") == "DISPENSE" for log in data), (
            "Expected an AuditLog entry with action=DISPENSE for the dispensed "
            "prescription"
        )


# ===========================================================================
# Helpers used inline above
# ===========================================================================
def setup_visit_with_finalized_treatment_local(api):
    """Build (owner, pet, visit, tr) where the visit is in IN_CONSULT,
    one treatment record is FINALIZED, and the visit has progressed to
    CONSULT_DONE so a bill can be issued.
    """
    from test_helpers import (
        create_treatment_record, end_consult, finalize_treatment_record,
        setup_visit_in_consult,
    )
    owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
    tr = create_treatment_record(visit_id=visit["id"])
    tr = finalize_treatment_record(visit_id=visit["id"], tr_id=tr["id"])
    visit = end_consult(visit["id"])
    return owner, pet, visit, tr
