"""Breadth probes: invalid/valid state transitions and endpoint-conditional
validation errors.

Covers Corner sections `state_machines` and `validations`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_owner_headers,
    setup_active_facility_order,
    setup_citation_issued,
    create_animal,
    create_bite_case,
    create_region,
    mark_animal_escaped,
    euthanize_animal,
    submit_specimen,
    set_clock,
    refetch_order,
)


# ---- state_machines ----

def test_breach_already_breached_order_rejected(api, animal_control_officer_headers):
    """PRD §3.4: "An `ACTIVE` quarantine order resolves in exactly one of three
    ways, and each drives its animal and bite case in lockstep."
    PRD §3.4: "then the state check — the order must currently be `ACTIVE`,
    otherwise `ERR_INVALID_STATE`".

    Design: Corner/state_machines/breach_already_breached_order_rejected
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-C4")
    validate_success(
        api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers), 200)
    resp = api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_close_open_case_rejected_invalid_state(api, epidemiologist_headers):
    """PRD §3.5: "a case whose status is `CONFIRMED_RABID` or `CLEARED` moves to
    the terminal `CLOSED`, after which no further transitions are permitted;
    closing a case in any other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_open_case_rejected_invalid_state
    """
    case = create_bite_case(region_code="RB-C5", wound_category="CATEGORY_I",
                            exposure_type="SCRATCH")
    resp = api.close_bite_case(case["id"], epidemiologist_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_specimen_submission_for_live_animal_rejected(api, veterinarian_headers):
    """PRD §3.5: "Submission requires the referenced animal to be `DECEASED` or
    `EUTHANIZED`; otherwise it is rejected with `ERR_ANIMAL_NOT_DECEASED`."

    Design: Corner/state_machines/specimen_submission_for_live_animal_rejected
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="UNKNOWN")
    case = create_bite_case(region_code="RB-C6", wound_category="CATEGORY_III",
                            body_site="ARM", animal_id=animal["id"])
    resp = api.create_specimen(case["id"], {
        "animal_id": animal["id"], "collected_datetime": "2026-03-01T09:00:00Z",
        "condition": "SATISFACTORY"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_DECEASED)


def test_report_result_on_rejected_specimen_invalid_state(api, veterinarian_headers):
    """PRD §3.5: "An `AUTOLYZED` or `UNSATISFACTORY` specimen is instead
    persisted directly in the terminal status `REJECTED`: it can never be
    tested, no result can be reported on it, and the case remains in
    `LAB_PENDING` awaiting a fresh specimen."
    PRD §3.5: "if the specimen is not `SUBMITTED` the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/report_result_on_autolyzed_rejected_specimen_invalid_state
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="NONE")
    euthanize_animal(animal["id"])
    case = create_bite_case(region_code="RB-C7", wound_category="CATEGORY_III",
                            body_site="HEAD_NECK", animal_id=animal["id"])
    specimen = submit_specimen(case["id"], animal["id"], condition="AUTOLYZED")
    assert specimen["status"] == "REJECTED"
    resp = api.report_result(specimen["id"], {"test_method": "DFA", "result": "NEGATIVE"},
                             veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_animal_capture_at_large_transitions_to_captured(api, animal_control_officer_headers):
    """PRD §3.2: "An animal that is `AT_LARGE` can subsequently be brought in by
    an animal-control capture, which advances it from `AT_LARGE` to `CAPTURED`
    and sets its `control_status` to `CAPTURED`."

    Design: Corner/state_machines/animal_capture_at_large_transitions_to_captured
    """
    animal = create_animal(species="RACCOON", animal_class="WILD",
                           identified=False, vaccination_status="NONE")
    mark_animal_escaped(animal["id"])
    captured = validate_success(
        api.capture_animal(animal["id"], animal_control_officer_headers), 200)
    assert captured["status"] == "CAPTURED"
    assert captured["control_status"] == "CAPTURED"


# ---- validations ----

def test_duplicate_region_code_rejected(api, health_dept_admin_headers):
    """PRD §3.8: "A `HealthDeptAdmin` creates a **SurveillanceRegion** with a
    `region_code`, which must be unique — a duplicate is rejected with
    `ERR_DUPLICATE_REGION_CODE` — and an optional `positive_threshold` defaulting
    to 3."

    Design: Corner/validations/duplicate_region_code_rejected
    """
    create_region("RB-DUP", positive_threshold=3)
    resp = api.create_surveillance_region({"region_code": "RB-DUP", "positive_threshold": 2},
                                          health_dept_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGION_CODE)


def test_facility_order_missing_facility_id_rejected(api, veterinarian_headers):
    """PRD §3.3: "A `FACILITY` order must supply a `facility_id`, and a
    `HOME_CONFINEMENT` order must not supply one; violating this shape is
    rejected with `ERR_FACILITY_REQUIRED`, and — as noted in Section 2.10 — this
    shape check runs before the concurrency check so that a malformed body cannot
    hide a version conflict."

    Design: Corner/validations/facility_order_missing_facility_id_rejected
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC", vaccination_status="CURRENT")
    case = create_bite_case(region_code="RB-C8", wound_category="CATEGORY_II",
                            animal_id=animal["id"])
    resp = api.create_quarantine_order(case["id"], {
        "expected_bite_case_version": case["version"],
        "animal_id": animal["id"],
        "order_type": "FACILITY"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_FACILITY_REQUIRED)


def test_citation_payment_amount_mismatch_rejected(api):
    """PRD §3.7: "the `payment_amount_cents` must exactly equal the citation's
    `total_fine_cents`, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/citation_payment_amount_mismatch_rejected
    """
    state = setup_citation_issued(violations=("QUARANTINE_BREACH",), region_code="RB-C9")
    assert state["citation"]["total_fine_cents"] == 54250
    resp = api.pay_citation(state["citation"]["id"], {"payment_amount_cents": 999},
                            make_owner_headers(state["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)


def test_complete_symptomatic_active_order_returns_safety_error(api, veterinarian_headers):
    """PRD §3.4: "first the safety check — an order may not be completed when the
    observation outcome is `SYMPTOMATIC` or `DECEASED`, in which case it is
    rejected with `ERR_ANIMAL_SYMPTOMATIC` and the animal must instead be
    converted to a specimen".

    Design: Corner/validations/complete_symptomatic_active_order_returns_safety_error
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-C10")
    set_clock("2026-03-11T00:00:00Z")
    resp = api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "SYMPTOMATIC"}, veterinarian_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_SYMPTOMATIC)
    assert refetch_order(state["order"]["id"])["status"] == "ACTIVE"
