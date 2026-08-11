"""Shipment lifecycle: classification, packaging chain, document gate,
reject/rework cycle, amendment cycles, and shipping-name normalization."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_carrier, submit_registration, approve_registration,
    create_approved_carrier_paid, create_standard_catalog, create_material,
    create_packaging_spec, create_shipment, classify_shipment,
    create_classified_shipment, create_verified_shipment,
    create_documented_shipment, create_and_certify_paper, list_invoices,
    pay_outstanding,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, OFFICER_B, REGULATOR, _ok
from test_helpers.factories import create_shipment_payload, create_shipping_paper_payload


# ---------------------------------------------------------------------------
# non_linear_state_machine / shipment_reject_rework_cycle
# ---------------------------------------------------------------------------

def test_reject_moves_documented_shipment_and_certified_paper_to_amendment(api):
    """PRD §3.4: "From there a `Regulator` may reject it — only `DOCUMENTED` is
    rejectable, else `ERR_SHIPMENT_NOT_DOCUMENTED`, optionally supplying a
    `reason` — which moves the shipment to `REJECTED` and, as the linked
    consequence, moves its `CERTIFIED` paper to `UNDER_AMENDMENT` with
    `amendment_count` incremented by 1."

    Design: Difficulty/non_linear_state_machine/shipment_reject_rework_cycle
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"])

    rejected = validate_success(api.reject_shipment(shipment["id"], {"reason": "PSN audit failure"}, REGULATOR))
    assert rejected["status"] == "REJECTED"
    papers, _ = validate_paginated(
        api.list_shipping_papers(shipment["id"], REGULATOR))
    assert papers[0]["status"] == "UNDER_AMENDMENT"
    assert papers[0]["amendment_count"] == 1


def test_rework_returns_to_draft_and_full_rewalk_reaches_documented(api):
    """PRD §3.4: "The officer then reworks the shipment — only `REJECTED` is
    reworkable, else `ERR_SHIPMENT_NOT_REJECTED` — returning it to `DRAFT` with
    `normalized_shipping_name` and `classified_by_user_id` cleared, ready for
    another pass."
    PRD §3.4: "Documenting the shipment requires `PACKAGING_VERIFIED`
    (`ERR_SHIPMENT_NOT_PACKAGING_VERIFIED`) and requires the shipment's paper to
    exist and be `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`)".

    Design: Difficulty/non_linear_state_machine/shipment_reject_rework_cycle
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"])
    _ok(api.reject_shipment(shipment["id"], {"reason": "PSN audit failure"}, REGULATOR), "reject")

    reworked = validate_success(api.rework_shipment(shipment["id"], OFFICER_A))
    assert reworked["status"] == "DRAFT"

    # Re-walk: re-classify, re-verify, re-certify the UNDER_AMENDMENT paper, re-document
    _ok(api.classify_shipment(shipment["id"], OFFICER_A), "re-classify")
    _ok(api.verify_packaging(shipment["id"], OFFICER_A), "re-verify")
    papers, _ = validate_paginated(
        api.list_shipping_papers(shipment["id"], REGULATOR))
    recertified = validate_success(api.certify_shipping_paper(papers[0]["id"], OFFICER_B))
    assert recertified["status"] == "CERTIFIED"
    documented = validate_success(api.document_shipment(shipment["id"], OFFICER_A))
    assert documented["status"] == "DOCUMENTED"


# ---------------------------------------------------------------------------
# non_linear_state_machine / shipping_paper_amendment_cycle
# ---------------------------------------------------------------------------

def test_amend_opens_certified_paper_and_increments_count(api):
    """PRD §3.4: "amending requires `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`) and
    likewise moves the paper to `UNDER_AMENDMENT` with `amendment_count`
    incremented".

    Design: Difficulty/non_linear_state_machine/shipping_paper_amendment_cycle
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"])
    paper = create_and_certify_paper(shipment["id"])

    amended = validate_success(api.amend_shipping_paper(
        paper["id"], {"emergency_response_summary": "Isolate 50m, upwind"}, OFFICER_B))
    assert amended["status"] == "UNDER_AMENDMENT"
    assert amended["amendment_count"] == 1


def test_recertify_after_amendment_does_not_double_count_and_copies_erg(api):
    """PRD §3.4: "A certified paper records the certifier as
    `certified_by_user_id`, copies the shipment material's `erg_guide_number`
    into its `er_response_guide_number`, and moves to `CERTIFIED`."
    PRD §3.4: "after which it must be re-certified before the shipment can
    document again."

    Design: Difficulty/non_linear_state_machine/shipping_paper_amendment_cycle
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"])
    paper = create_and_certify_paper(shipment["id"])
    _ok(api.amend_shipping_paper(paper["id"], {"emergency_response_summary": "Isolate 50m, upwind"}, OFFICER_B), "amend")

    recertified = validate_success(api.certify_shipping_paper(paper["id"], OFFICER_B))
    assert recertified["status"] == "CERTIFIED"
    assert recertified["amendment_count"] == 1, "amendment cycle must not double-count"
    assert recertified["er_response_guide_number"] == "128"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / document_requires_paper_certified
# ---------------------------------------------------------------------------

def test_document_rejected_while_paper_is_draft(api):
    """PRD §3.4: "Documenting the shipment requires `PACKAGING_VERIFIED`
    (`ERR_SHIPMENT_NOT_PACKAGING_VERIFIED`) and requires the shipment's paper to
    exist and be `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/document_requires_paper_certified
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"])
    # paper exists but stays DRAFT
    _ok(api.create_shipping_paper(shipment["id"], create_shipping_paper_payload(), OFFICER_A), "paper")
    _ok(api.verify_packaging(shipment["id"], OFFICER_A), "verify")

    resp = api.document_shipment(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_PAPER_NOT_CERTIFIED)


def test_document_succeeds_after_paper_certified_by_other_officer(api):
    """PRD §3.4: "Documenting the shipment requires `PACKAGING_VERIFIED`
    (`ERR_SHIPMENT_NOT_PACKAGING_VERIFIED`) and requires the shipment's paper to
    exist and be `CERTIFIED` (`ERR_PAPER_NOT_CERTIFIED`); success lands the
    shipment in `DOCUMENTED`."
    PRD §3.4: "if the certifying officer's `X-User-ID` equals the shipment's
    `classified_by_user_id`, the request is rejected with `ERR_SOD_VIOLATION`
    (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/document_requires_paper_certified
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"])
    paper = _ok(api.create_shipping_paper(shipment["id"], create_shipping_paper_payload(), OFFICER_A), "paper")
    _ok(api.verify_packaging(shipment["id"], OFFICER_A), "verify")

    # officer-b (not the classifier) certifies
    certified = validate_success(api.certify_shipping_paper(paper["id"], OFFICER_B))
    assert certified["status"] == "CERTIFIED"
    documented = validate_success(api.document_shipment(shipment["id"], OFFICER_A))
    assert documented["status"] == "DOCUMENTED"


# ---------------------------------------------------------------------------
# Corner/state_machines/classify_from_classified_returns_invalid_state
# ---------------------------------------------------------------------------

def test_classify_from_classified_returns_invalid_state(api):
    """PRD §3.4: "Classification requires `DRAFT` (`ERR_SHIPMENT_NOT_DRAFT`
    otherwise)".
    PRD §3.4: "The shipment starts in `DRAFT`".

    Design: Corner/state_machines/classify_from_classified_returns_invalid_state
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    assert shipment["status"] == "DRAFT"
    _ok(api.classify_shipment(shipment["id"], OFFICER_A), "classify")

    resp = api.classify_shipment(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DRAFT)


# ---------------------------------------------------------------------------
# Corner/state_machines/cancel_cancelled_shipment_rejected
# ---------------------------------------------------------------------------

def test_cancel_cancelled_shipment_rejected(api):
    """PRD §3.4: "Cancellation is an officer action available while the shipment
    is `DRAFT`, `CLASSIFIED`, or `PACKAGING_VERIFIED`, otherwise
    `ERR_SHIPMENT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_cancelled_shipment_rejected
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    cancelled = validate_success(api.cancel_shipment(shipment["id"], OFFICER_A))
    assert cancelled["status"] == "CANCELLED"

    resp = api.cancel_shipment(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_CANCELLABLE)


# ---------------------------------------------------------------------------
# Corner/validations/shipping_name_normalization_and_mismatch
# ---------------------------------------------------------------------------

def test_classify_normalizes_case_and_whitespace(api):
    """PRD §3.4: "the officer's `declared_shipping_name` is normalized —
    uppercased, trimmed, with inner whitespace collapsed — and must equal the
    material's `proper_shipping_name` normalized the same way, failing with
    `ERR_SHIPPING_NAME_MISMATCH` (HTTP 422) when they differ. On success the
    normalized value is stored as `normalized_shipping_name`".

    Design: Corner/validations/shipping_name_normalization_and_mismatch
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"],
                               declared_shipping_name="  flammable   liquid, n.o.s. ")
    classified = validate_success(api.classify_shipment(shipment["id"], OFFICER_A))
    assert classified["status"] == "CLASSIFIED"
    assert classified["normalized_shipping_name"] == "FLAMMABLE LIQUID, N.O.S."


def test_classify_mismatched_name_returns_422(api):
    """PRD §3.4: "must equal the material's `proper_shipping_name` normalized
    the same way, failing with `ERR_SHIPPING_NAME_MISMATCH` (HTTP 422) when they
    differ."

    Design: Corner/validations/shipping_name_normalization_and_mismatch
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"],
                               declared_shipping_name="GASOLINE")
    resp = api.classify_shipment(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SHIPPING_NAME_MISMATCH)


# ---------------------------------------------------------------------------
# Corner/validations/packaging_capacity_inclusive_boundary
# ---------------------------------------------------------------------------

def test_verify_packaging_at_exact_capacity_passes(api):
    """PRD §3.4: "finally `quantity_kg` must not exceed the spec's
    `max_net_quantity_kg`, with equality allowed
    (`ERR_QUANTITY_EXCEEDS_CAPACITY`)."

    Design: Corner/validations/packaging_capacity_inclusive_boundary
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"],
                                          quantity_kg=500.0)
    verified = validate_success(api.verify_packaging(shipment["id"], OFFICER_A))
    assert verified["status"] == "PACKAGING_VERIFIED"


def test_verify_packaging_one_tenth_over_capacity_fails(api):
    """PRD §3.4: "finally `quantity_kg` must not exceed the spec's
    `max_net_quantity_kg`, with equality allowed
    (`ERR_QUANTITY_EXCEEDS_CAPACITY`)."

    Design: Corner/validations/packaging_capacity_inclusive_boundary
    """
    carrier, material, spec = create_approved_carrier_paid(), *create_standard_catalog()
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"],
                                          quantity_kg=500.1)
    resp = api.verify_packaging(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_CAPACITY)


# ---------------------------------------------------------------------------
# Corner/validations/packing_group_incompatible_rejected
# ---------------------------------------------------------------------------

def test_packing_group_incompatible_rejected(api):
    """PRD §3.3: "Packing-group compatibility is directional: `PG_I` packaging
    accepts `PG_I`, `PG_II`, and `PG_III` material; `PG_II` packaging accepts
    `PG_II` and `PG_III`; `PG_III` packaging accepts only `PG_III`."
    PRD §3.4: "then the material's packing group must be compatible with the
    spec's `max_packing_group` per the directional rule of §3.3
    (`ERR_PACKING_GROUP_INCOMPATIBLE`)".

    Design: Corner/validations/packing_group_incompatible_rejected
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material = create_material(packing_group="PG_I")  # PG_I material
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_3"], max_packing_group="PG_II")
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"])

    resp = api.verify_packaging(shipment["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_PACKING_GROUP_INCOMPATIBLE)
