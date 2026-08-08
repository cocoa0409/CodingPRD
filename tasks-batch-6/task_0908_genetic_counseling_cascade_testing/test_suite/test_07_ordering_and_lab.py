"""Test-order submission preconditions: signed-consent gate, validation precedence
(consent before capacity), lab aggregate capacity, and lab-load release on cancel.

Translates queue-A difficulty instances (consent-required, safety-before-temporal,
lab capacity) and a queue-B corner instance (cancel releases lab load).
"""
from test_helpers import (
    validate_success, validate_error, make_counselor_headers,
    create_consent_payload,
    create_family, create_counselor, create_lab, create_case, add_member,
    assess_risk, create_signed_testing_consent, create_order, submit_order,
)


# --------------------------------------------------------------------------- #
# Shared scenario builders
# --------------------------------------------------------------------------- #
def _lab_full_scenario(case2_has_signed_consent: bool):
    """Lab capacity 1; case1 consented with a submitted order (fills the lab); case2
    risk-assessed with an overlapping drafted order. case2's consent is optionally
    signed."""
    fam = create_family(budget=10000)
    gc = create_counselor()
    lab = create_lab(capacity=1)

    case1 = create_case(fam["id"], gc["id"], patient_name="P1", covered_sessions=2)
    add_member(case1["id"], gc["id"], relationship="SIBLING", degree=1, affected=True,
               age_of_onset=55)
    assess_risk(case1["id"], gc["id"])
    create_signed_testing_consent(case1["id"], gc["id"])
    order1 = create_order(case1["id"], lab["id"], gc["id"], panel_name="Panel1",
                          list_price_cents=200000, processing_start="2026-05-02T09:00:00Z",
                          processing_end="2026-05-20T09:00:00Z")
    submit_order(order1["id"], gc["id"])

    case2 = create_case(fam["id"], gc["id"], patient_name="P2", sex="MALE",
                        covered_sessions=2)
    add_member(case2["id"], gc["id"], relationship="SIBLING", degree=1, affected=True,
               age_of_onset=55)
    assess_risk(case2["id"], gc["id"])
    if case2_has_signed_consent:
        create_signed_testing_consent(case2["id"], gc["id"])
    order2 = create_order(case2["id"], lab["id"], gc["id"], panel_name="Panel2",
                          list_price_cents=200000, processing_start="2026-05-05T09:00:00Z",
                          processing_end="2026-05-18T09:00:00Z")
    return {"gc_id": gc["id"], "lab_id": lab["id"], "case2_id": case2["id"],
            "order2_id": order2["id"]}


# --------------------------------------------------------------------------- #
# Difficulty: order_submit_requires_signed_consent
# --------------------------------------------------------------------------- #
def _risk_assessed_with_unsigned_consent_and_order():
    fam = create_family(budget=10000)
    gc = create_counselor()
    lab = create_lab(capacity=5)
    case = create_case(fam["id"], gc["id"], covered_sessions=2)
    add_member(case["id"], gc["id"], relationship="SIBLING", degree=1, affected=True,
               age_of_onset=60)
    assess_risk(case["id"], gc["id"])
    # consent created but deliberately NOT signed
    from test_helpers import api_client
    api_client.create_consent(create_consent_payload(case["id"], "TESTING"),
                              make_counselor_headers(gc["id"]))
    order = create_order(case["id"], lab["id"], gc["id"], list_price_cents=200000,
                         processing_end="2026-05-10T09:00:00Z")
    return {"gc_id": gc["id"], "order_id": order["id"]}


def test_submit_without_signed_consent_rejected(api):
    """PRD 3.5: "a TESTING-type consent record for the case must be SIGNED (else
    ERR_CONSENT_REQUIRED)".

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_signed_consent
    """
    ctx = _risk_assessed_with_unsigned_consent_and_order()
    res = api.submit_order(ctx["order_id"], make_counselor_headers(ctx["gc_id"]))
    validate_error(res, "ERR_CONSENT_REQUIRED", expected_status=409)


def test_submit_without_signed_consent_leaves_order_draft(api):
    """PRD 3.5: "a TESTING-type consent record for the case must be SIGNED (else
    ERR_CONSENT_REQUIRED)". PRD 3.5: "On success the order moves from DRAFT to
    SUBMITTED".

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_signed_consent
    """
    ctx = _risk_assessed_with_unsigned_consent_and_order()
    hdr = make_counselor_headers(ctx["gc_id"])
    api.submit_order(ctx["order_id"], hdr)
    order = validate_success(api.get_order(ctx["order_id"], hdr), 200)
    assert order["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Difficulty: submit_no_consent_lab_full_safety_beats_temporal
# --------------------------------------------------------------------------- #
def test_missing_consent_preempts_lab_capacity(api):
    """PRD 3.5: "The order must be DRAFT (else ERR_ORDER_INVALID_STATE); the case must
    be at RISK_ASSESSED (else ERR_CASE_INVALID_CLINICAL_STATE); a TESTING-type consent
    record for the case must be SIGNED (else ERR_CONSENT_REQUIRED); and the lab must
    have processing capacity for the window (else ERR_LAB_CAPACITY_EXCEEDED)." PRD 2.5:
    "The remaining domain rules — consent presence, cascade actionability, temporal
    overlap, uniqueness and structural constraints, and fiscal sufficiency — follow".

    Design: Difficulty/priority_pair_validation_conflict/submit_no_consent_lab_full_safety_beats_temporal
    """
    ctx = _lab_full_scenario(case2_has_signed_consent=False)
    res = api.submit_order(ctx["order2_id"], make_counselor_headers(ctx["gc_id"]))
    validate_error(res, "ERR_CONSENT_REQUIRED", expected_status=409)


def test_missing_consent_lab_full_leaves_order_draft(api):
    """PRD 3.5: "a TESTING-type consent record for the case must be SIGNED (else
    ERR_CONSENT_REQUIRED)". PRD 3.5: "On success the order moves from DRAFT to SUBMITTED,
    the lab's current_processing_load is recomputed to reflect the reserved slot, and
    the case advances from RISK_ASSESSED to TESTING".

    Design: Difficulty/priority_pair_validation_conflict/submit_no_consent_lab_full_safety_beats_temporal
    """
    ctx = _lab_full_scenario(case2_has_signed_consent=False)
    hdr = make_counselor_headers(ctx["gc_id"])
    api.submit_order(ctx["order2_id"], hdr)
    order = validate_success(api.get_order(ctx["order2_id"], hdr), 200)
    assert order["status"] == "DRAFT"
    case = validate_success(api.get_case(ctx["case2_id"], hdr), 200)
    assert case["clinical_status"] == "RISK_ASSESSED"


# --------------------------------------------------------------------------- #
# Difficulty: lab_aggregate_capacity_exceeded
# --------------------------------------------------------------------------- #
def test_lab_capacity_exceeded_on_overlapping_window(api):
    """PRD 2.9: "When an order is submitted, the system counts how many of the lab's
    already-submitted orders have processing windows that overlap the new order's
    window; if admitting the new order would push the count of simultaneously-overlapping
    windows beyond max_concurrent_capacity, submission is rejected with
    ERR_LAB_CAPACITY_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/lab_aggregate_capacity_exceeded
    """
    ctx = _lab_full_scenario(case2_has_signed_consent=True)
    res = api.submit_order(ctx["order2_id"], make_counselor_headers(ctx["gc_id"]))
    validate_error(res, "ERR_LAB_CAPACITY_EXCEEDED", expected_status=409)


def test_lab_capacity_rejection_leaves_order_draft(api):
    """PRD 2.9: "if admitting the new order would push the count of
    simultaneously-overlapping windows beyond max_concurrent_capacity, submission is
    rejected with ERR_LAB_CAPACITY_EXCEEDED." PRD 3.5: "On success the order moves from
    DRAFT to SUBMITTED".

    Design: Difficulty/resource_temporal_overlap/lab_aggregate_capacity_exceeded
    """
    ctx = _lab_full_scenario(case2_has_signed_consent=True)
    hdr = make_counselor_headers(ctx["gc_id"])
    api.submit_order(ctx["order2_id"], hdr)
    order = validate_success(api.get_order(ctx["order2_id"], hdr), 200)
    assert order["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Corner: order_cancel_releases_lab_load
# --------------------------------------------------------------------------- #
def test_cancel_submitted_order_releases_lab_load(api):
    """PRD 3.5: "An order may instead be cancelled while it is DRAFT or SUBMITTED,
    moving it to CANCELLED, releasing any reserved lab slot, and recomputing
    current_processing_load". PRD 2.9: a lab "exposes current_processing_load, the count
    of that lab's orders currently in SUBMITTED status."

    Design: Corner/state_machines/order_cancel_releases_lab_load
    """
    fam = create_family(budget=10000)
    gc = create_counselor()
    lab = create_lab(capacity=3)
    case = create_case(fam["id"], gc["id"], covered_sessions=1)
    add_member(case["id"], gc["id"], relationship="SIBLING", degree=1, affected=True,
               age_of_onset=60)
    assess_risk(case["id"], gc["id"])
    create_signed_testing_consent(case["id"], gc["id"])
    order = create_order(case["id"], lab["id"], gc["id"], list_price_cents=100000,
                         processing_end="2026-05-10T09:00:00Z")
    submit_order(order["id"], gc["id"])

    hdr = make_counselor_headers(gc["id"])
    cancelled = validate_success(api.cancel_order(order["id"], hdr), 200)
    assert cancelled["status"] == "CANCELLED"
    lab_after = validate_success(api.get_lab(lab["id"], hdr), 200)
    assert lab_after["current_processing_load"] == 0
