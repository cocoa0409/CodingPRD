"""Cyclic audit-intervention negotiation and parallel order state dimensions."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    drive_intervention_to_appealed, create_restricted_order_with_request,
    api_client,
)


def _setup_issued_intervention():
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


def test_uphold_returns_intervention_to_recommended(api):
    """PRD Section 3.3: "A verdict of `UPHOLD` stands the recommendation back
    up: the intervention returns to `RECOMMENDED` with a fresh `due_at` of the
    clock plus 24 hours, and the prescriber must respond again — the
    negotiation loop that gives this workflow its cyclic shape."

    Design: Difficulty/non_linear_state_machine/audit_intervention_negotiation_cycle
    """
    _, md, ph, director, _, intervention = _setup_issued_intervention()
    appealed = drive_intervention_to_appealed(intervention["id"], ph, md)
    res = api.adjudicate_audit_intervention(
        appealed["id"],
        {"verdict": "UPHOLD", "adjudicator_id": director["id"]},
        make_director_headers(director["id"]),
    )
    upheld = validate_success(res, 200)
    assert upheld["recommendation_status"] == "RECOMMENDED"
    assert upheld["appeal_adjudicator_id"] == director["id"]


def test_uphold_does_not_count_as_noncompliance(api):
    """PRD Section 3.3: "the clock sweep moves a `RECOMMENDED` intervention past
    its `due_at` to `SUPERSEDED` — non-response is deliberately not counted as
    noncompliance" and "Standing follows a simple ladder over the count of a
    prescriber's interventions resolved `REJECTED_FINAL`: three or more makes
    the prescriber `SUSPENDED`, exactly two puts them on `WATCH`, and anything
    less is `GOOD`."

    Design: Difficulty/non_linear_state_machine/audit_intervention_negotiation_cycle
    """
    _, md, ph, director, _, intervention = _setup_issued_intervention()
    appealed = drive_intervention_to_appealed(intervention["id"], ph, md)
    res = api.adjudicate_audit_intervention(
        appealed["id"],
        {"verdict": "UPHOLD", "adjudicator_id": director["id"]},
        make_director_headers(director["id"]),
    )
    validate_success(res, 200)
    prescriber = validate_success(
        api.get_practitioner(md["id"], make_director_headers(director["id"])), 200
    )
    # UPHOLD returns the loop to RECOMMENDED; only REJECTED_FINAL increments the count.
    assert prescriber["unresolved_noncompliance_count"] == 0
    assert prescriber["stewardship_standing"] == "GOOD"


def test_approval_expiry_cascades_into_therapy_dimension(api):
    """PRD Section 3.2: "Finally, the clock sweep expires any `SUBMITTED`
    request once the clock reaches `submitted_at` plus the hospital's
    `restricted_auto_expire_hours`: the request becomes `EXPIRED`, the order's
    `approval_status` becomes `EXPIRED`, and a waiting order is discontinued
    with `stopped_at` stamped."

    Design: Difficulty/non_linear_state_machine/antibiotic_order_parallel_dimensions
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
        is_restricted=True, has_po_form=False,
    )
    order, request = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    set_clock(hid, "2026-08-04T00:00:01Z")
    fetched_request = validate_success(
        api.get_approval_request(request["id"], make_physician_headers(md["id"])), 200
    )
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_request["status"] == "EXPIRED"
    assert fetched_order["approval_status"] == "EXPIRED"
    assert fetched_order["therapy_status"] == "DISCONTINUED"


def test_restricted_order_starts_pending_awaiting_approval(api):
    """PRD Section 3.2: "Ordering a restricted drug instead sets
    `approval_status` to `PENDING` and `therapy_status` to `AWAITING_APPROVAL`;
    the order sits inert — no doses may be recorded against it — until the
    approval workflow resolves."

    Design: Difficulty/non_linear_state_machine/antibiotic_order_parallel_dimensions
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
        is_restricted=True, has_po_form=False,
    )
    order = create_order(patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3)
    # Approval dimension and therapy dimension move independently.
    assert order["approval_status"] == "PENDING"
    assert order["therapy_status"] == "AWAITING_APPROVAL"
