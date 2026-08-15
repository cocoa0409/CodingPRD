"""Compensating invariants: DOT conserved across completion; intervention count
conserved across the appeal cycle."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, record_doses, create_issued_intervention,
    drive_intervention_to_appealed,
    api_client,
)


def _setup_order_with_accrual():
    """Order with 3 doses on 2 distinct dates: dot_calendar 2, dot_dose 0.75."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"], renal_function_crcl=90)
    drug = create_drug(hid)
    set_clock(hid, "2026-08-01T08:00:00Z")
    order = create_order(
        patient, drug, md, route="PO", dose_mg=500, frequency_per_day=4,
        indication="EMPIRIC",
    )
    record_doses(order["id"], md["id"], [
        "2026-08-01T08:00:00Z",
        "2026-08-01T12:00:00Z",
        "2026-08-02T08:00:00Z",
    ])
    return hospital, md, order


def test_completion_preserves_dot_accrual(api):
    """PRD Section 3.2: "Completing — an `AttendingPhysician` action available
    from `ACTIVE`, `REVIEW_REQUIRED`, `DEESCALATED`, or `CONVERTED` — requires
    that no intervention for the order stands in `RECOMMENDED` or `APPEALED`
    (`ERR_OPEN_INTERVENTION_BLOCKS_CLOSE`) and that the patient is still
    admitted (`ERR_PATIENT_DISCHARGED`); it moves the order to `COMPLETED`,
    stamps `stopped_at`, and triggers a final DOT recomputation." and PRD
    Section 3.8: "Under the calendar basis, any calendar UTC date on which at
    least one dose was administered contributes one DOT regardless of how many
    doses fell that day".

    Design: Difficulty/compensating_invariant/dot_conservation_across_complete
    """
    _, md, order = _setup_order_with_accrual()
    before = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert before["dot_calendar"] == 2
    assert before["dot_dose"] == pytest.approx(0.75, abs=0.001)

    completed = validate_success(
        api.complete_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert completed["therapy_status"] == "COMPLETED"
    # The state flip itself introduces zero drift in the accrual.
    assert completed["dot_calendar"] == before["dot_calendar"]
    assert completed["dot_dose"] == pytest.approx(before["dot_dose"], abs=0.001)
    assert completed["administered_doses"] == before["administered_doses"]


def test_completion_does_not_extend_calendar_dot(api):
    """PRD Section 3.8: "`dot_calendar` counts the distinct UTC calendar dates
    on which at least one administration fell between `started_at` and the
    earlier of `stopped_at` or the relevant period end".

    Design: Difficulty/compensating_invariant/dot_conservation_across_complete
    """
    _, md, order = _setup_order_with_accrual()
    validate_success(api.complete_order(order["id"], make_physician_headers(md["id"])), 200)
    after = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    # No new doses after completion -> still 2 distinct dates, 0.75 dose-basis.
    assert after["dot_calendar"] == 2
    assert after["dot_dose"] == pytest.approx(0.75, abs=0.001)


def _setup_intervention_cycle():
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
        is_restricted=False, has_po_form=False,
    )
    order = create_order(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=1,
        indication="EMPIRIC",
    )
    intervention = create_issued_intervention(order, ph)
    return hospital, md, ph, director, order, intervention


def test_appeal_cycle_creates_no_new_intervention_row(api):
    """PRD Section 3.3: "A verdict of `UPHOLD` stands the recommendation back
    up: the intervention returns to `RECOMMENDED` with a fresh `due_at` of the
    clock plus 24 hours, and the prescriber must respond again — the
    negotiation loop that gives this workflow its cyclic shape."

    Design: Difficulty/compensating_invariant/intervention_count_conservation_through_appeal_cycle
    """
    _, md, ph, director, order, intervention = _setup_intervention_cycle()
    appealed = drive_intervention_to_appealed(intervention["id"], ph, md)
    validate_success(
        api.adjudicate_audit_intervention(
            appealed["id"],
            {"verdict": "UPHOLD", "adjudicator_id": director["id"]},
            make_director_headers(director["id"]),
        ), 200,
    )
    data, meta = validate_paginated(
        api.list_audit_interventions(
            make_pharmacist_headers(ph["id"]),
            params={"antibiotic_order_id": order["id"]},
        )
    )
    # The same row cycles; no replacement RECOMMENDED row materializes.
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == intervention["id"]
    assert data[0]["recommendation_status"] == "RECOMMENDED"


def test_appeal_cycle_preserves_intervention_identity(api):
    """PRD Section 3.3: "The auditor — and only the auditor, verified against
    `auditor_id` via the supplied `appealer_id` (`ERR_NOT_AUDIT_OWNER`) — may
    appeal an intervention standing in `REJECTED`
    (`ERR_INTERVENTION_NOT_APPEALABLE`), moving it to `APPEALED`."

    Design: Difficulty/compensating_invariant/intervention_count_conservation_through_appeal_cycle
    """
    _, md, ph, director, order, intervention = _setup_intervention_cycle()
    appealed = drive_intervention_to_appealed(intervention["id"], ph, md)
    upheld = validate_success(
        api.adjudicate_audit_intervention(
            appealed["id"],
            {"verdict": "UPHOLD", "adjudicator_id": director["id"]},
            make_director_headers(director["id"]),
        ), 200,
    )
    # Identity is conserved through REJECTED -> APPEALED -> RECOMMENDED.
    assert upheld["id"] == intervention["id"]
    assert upheld["antibiotic_order_id"] == order["id"]
    assert upheld["auditor_id"] == ph["id"]
