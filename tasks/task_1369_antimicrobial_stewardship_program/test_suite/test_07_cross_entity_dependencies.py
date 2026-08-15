"""Cross-entity state dependencies: guideline adoption gating; decide-after-withdraw."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_director_headers,
    make_microbiologist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    create_order, create_antibiogram_with_row,
    create_empiric_guideline_payload, create_restricted_order_with_request,
    api_client, ApiErrorId,
)


def _setup_draft_guideline_on_draft_antibiogram():
    """DRAFT guideline referencing a still-DRAFT antibiogram with one row."""
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
        is_restricted=False, has_po_form=True,
    )
    antibiogram, _ = create_antibiogram_with_row(hospital, mb, patient, drug)
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(hid, "UTI", drug["id"], antibiogram["id"]),
        make_director_headers(director["id"]),
    )
    guideline = get_success_data(res)
    return hospital, director, antibiogram, guideline


def test_adoption_rejected_when_antibiogram_not_published(api):
    """PRD Section 3.7: "its source antibiogram must be `PUBLISHED` and of the
    same hospital (`ERR_ANTIBIOGRAM_NOT_PUBLISHED`)".

    Design: Difficulty/cross_entity_state_dependency/guideline_adoption_requires_published_antibiogram
    """
    hospital, director, antibiogram, guideline = _setup_draft_guideline_on_draft_antibiogram()
    fresh = get_success_data(
        api_client.get_hospital(hospital["id"], make_director_headers(director["id"]))
    )
    res = api.adopt_empiric_guideline(
        guideline["id"],
        {"expected_hospital_version": fresh["version"]},
        make_director_headers(director["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ANTIBIOGRAM_NOT_PUBLISHED)


def test_failed_adoption_leaves_guideline_draft(api):
    """PRD Section 3.7: "Adoption moves the guideline to `ADOPTED`, records the
    `pct_susceptible_at_adoption` snapshot of the first-line drug, retires
    whichever guideline previously stood `ADOPTED` for the same hospital and
    syndrome, and increments the hospital's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/guideline_adoption_requires_published_antibiogram
    """
    hospital, director, antibiogram, guideline = _setup_draft_guideline_on_draft_antibiogram()
    fresh = get_success_data(
        api_client.get_hospital(hospital["id"], make_director_headers(director["id"]))
    )
    res = api.adopt_empiric_guideline(
        guideline["id"],
        {"expected_hospital_version": fresh["version"]},
        make_director_headers(director["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ANTIBIOGRAM_NOT_PUBLISHED)
    fetched = validate_success(
        api.get_empiric_guideline(guideline["id"], make_director_headers(director["id"])), 200
    )
    # The rejected adoption must not have moved the guideline out of DRAFT.
    assert fetched["status"] == "DRAFT"


def _setup_withdrawn_approval():
    """Restricted order + SUBMITTED request, then withdrawn by the requester."""
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
    res = api_client.withdraw_approval_request(
        request["id"], {"withdrawer_id": md["id"]}, make_physician_headers(md["id"])
    )
    get_success_data(res)
    return hospital, md, ph, order, request


def test_decide_after_withdraw_rejected_not_pending(api):
    """PRD Section 3.2: "The request must still be in `SUBMITTED` or
    `ESCALATED` (`ERR_APPROVAL_NOT_PENDING`)" and "The requester themselves may
    retract a `SUBMITTED` request by withdrawing it: the supplied
    `withdrawer_id` must equal the `requester_id` (`ERR_NOT_REQUEST_OWNER`),
    and the request moves to `WITHDRAWN` while the order's `approval_status`
    reverts to `NOT_REQUIRED` and an `AWAITING_APPROVAL` order is moved to
    `DISCONTINUED` with `stopped_at` stamped."

    Design: Difficulty/cross_entity_state_dependency/approval_decision_gated_on_order_approval_pending
    """
    _, md, ph, order, request = _setup_withdrawn_approval()
    res = api.decide_approval_request(
        request["id"],
        {"decision": "APPROVED", "decider_id": ph["id"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPROVAL_NOT_PENDING)


def test_decide_after_withdraw_does_not_resurrect_order(api):
    """PRD Section 3.2: "the request moves to `WITHDRAWN` while the order's
    `approval_status` reverts to `NOT_REQUIRED` and an `AWAITING_APPROVAL`
    order is moved to `DISCONTINUED` with `stopped_at` stamped."

    Design: Difficulty/cross_entity_state_dependency/approval_decision_gated_on_order_approval_pending
    """
    _, md, ph, order, request = _setup_withdrawn_approval()
    res = api.decide_approval_request(
        request["id"],
        {"decision": "APPROVED", "decider_id": ph["id"]},
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPROVAL_NOT_PENDING)
    fetched = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    assert fetched["approval_status"] == "NOT_REQUIRED"
    assert fetched["therapy_status"] == "DISCONTINUED"
