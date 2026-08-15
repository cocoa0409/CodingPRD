"""Transitive cascades: clock-sweep depth-3 chain; adjudicate OVERTURN depth-2 chain."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_issued_intervention,
    create_restricted_order_with_request, create_overturned_intervention,
    create_audit_intervention_payload,
    api_client,
)


def test_clock_sweep_expires_request_then_order_then_intervention(api):
    """PRD Section 3.2: "Finally, the clock sweep expires any `SUBMITTED`
    request once the clock reaches `submitted_at` plus the hospital's
    `restricted_auto_expire_hours`: the request becomes `EXPIRED`, the order's
    `approval_status` becomes `EXPIRED`, and a waiting order is discontinued
    with `stopped_at` stamped." and PRD Section 3.3: "discontinuation of the
    parent order or discharge of the patient moves `DOCUMENTED` or
    `RECOMMENDED` interventions to `SUPERSEDED` as part of the cleanup
    cascades."

    Design: Difficulty/transitive_cascade/clock_sweep_approval_order_intervention_cascade
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
        is_restricted=True, has_po_form=False,
    )
    order, request = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    # Documented (not yet issued) intervention against the awaiting order.
    res = api.create_audit_intervention(
        create_audit_intervention_payload(
            order["id"], ph["id"],
            recommendation_text="Planned early stop once culture results finalize",
        ),
        make_pharmacist_headers(ph["id"]),
    )
    intervention = get_success_data(res)

    set_clock(hid, "2026-08-04T00:00:01Z")

    fetched_request = validate_success(
        api.get_approval_request(request["id"], make_physician_headers(md["id"])), 200
    )
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    fetched_intervention = validate_success(
        api.get_audit_intervention(intervention["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_request["status"] == "EXPIRED"
    assert fetched_order["approval_status"] == "EXPIRED"
    assert fetched_order["therapy_status"] == "DISCONTINUED"
    assert fetched_intervention["recommendation_status"] == "SUPERSEDED"


def test_expiry_cascade_stamps_stopped_at_on_waiting_order(api):
    """PRD Section 3.2: "a waiting order is discontinued with `stopped_at`
    stamped." and PRD Section 2.5: "When an operation mutates more than one
    resource — for example a decision that moves both an approval request and
    its parent order — each mutated resource independently refreshes its
    `updated_at` and increments its `version`."

    Design: Difficulty/transitive_cascade/clock_sweep_approval_order_intervention_cascade
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
    order, _ = create_restricted_order_with_request(
        patient, drug, md, route="IV", dose_mg=1000, frequency_per_day=3
    )
    set_clock(hid, "2026-08-04T00:00:01Z")
    fetched_order = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched_order["therapy_status"] == "DISCONTINUED"
    assert fetched_order["stopped_at"] == "2026-08-04T00:00:01Z"


def _drive_prescriber_to_watch():
    """Two OVERTURN-adjudicated interventions against the same prescriber.

    Returns (hospital, md, ph, director) with md at unresolved_noncompliance_count 2.
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    drug1 = create_drug(
        hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
        is_restricted=False, has_po_form=False,
    )
    drug2 = create_drug(
        hid, drug_name="AZITHROMYCIN", drug_class="MACROLIDE",
        is_restricted=False, has_po_form=True,
    )
    order1 = create_order(patient, drug1, md, route="IV", dose_mg=1000, frequency_per_day=1)
    order2 = create_order(patient, drug2, md, route="PO", dose_mg=500, frequency_per_day=1)
    i1 = create_overturned_intervention(order1, ph, md, director)
    i2 = create_overturned_intervention(
        order2, ph, md, director,
        intervention_type="DOSE_OPTIMIZATION",
        recommendation_text="Reduce dose to 250mg daily given renal function",
    )
    return hospital, md, ph, director, i1, i2


def test_overturn_increments_noncompliance_count_once_per_intervention(api):
    """PRD Section 3.3: "A verdict of `OVERTURN` ends the matter in
    `REJECTED_FINAL`: the prescriber's `unresolved_noncompliance_count`
    increments by one and their standing is recomputed."

    Design: Difficulty/transitive_cascade/adjudicate_overturn_standing_cascade
    """
    _, md, _, _, i1, i2 = _drive_prescriber_to_watch()
    assert i1["recommendation_status"] == "REJECTED_FINAL"
    assert i2["recommendation_status"] == "REJECTED_FINAL"
    prescriber = validate_success(
        api.get_practitioner(md["id"], make_physician_headers(md["id"])), 200
    )
    assert prescriber["unresolved_noncompliance_count"] == 2


def test_standing_reaches_watch_at_exactly_two(api):
    """PRD Section 3.3: "Standing follows a simple ladder over the count of a
    prescriber's interventions resolved `REJECTED_FINAL`: three or more makes
    the prescriber `SUSPENDED`, exactly two puts them on `WATCH`, and anything
    less is `GOOD`."

    Design: Difficulty/transitive_cascade/adjudicate_overturn_standing_cascade
    """
    _, md, _, _, _, _ = _drive_prescriber_to_watch()
    prescriber = validate_success(
        api.get_practitioner(md["id"], make_physician_headers(md["id"])), 200
    )
    assert prescriber["unresolved_noncompliance_count"] == 2
    assert prescriber["stewardship_standing"] == "WATCH"
