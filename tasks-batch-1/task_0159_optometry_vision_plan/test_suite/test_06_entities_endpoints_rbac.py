"""Entity creation and schema validation, system fields, references, immutability,
listing/pagination, benefit-pool subresource, remake surcharge, prescription expiry,
and RBAC denials.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    TEST_USERS,
    setup_active_rx,
    setup_clinic,
    setup_order_after_n_remakes,
    create_optometrist,
    issue_prescription,
    create_open_encounter,
    create_patient_payload,
    create_provider_payload,
    create_prescription_payload,
    create_eligibility_payload,
    create_lab_order_payload,
    make_unknown_role_headers,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]
OPTICIAN_FALLBACK = TEST_USERS["optician_headers"]


# --------------------------------------------------------------------------- #
# Entities — creation, defaults, schema
# --------------------------------------------------------------------------- #
def test_create_patient_returns_201_with_defaults(api):
    """PRD §3.1: "Two further inputs are optional at registration:
    `medical_insurance_on_file`, a boolean that defaults to false ... and
    `recall_interval_months`, an integer between 1 and 36 that defaults to 12."
    PRD §3.1: "its computed `last_routine_exam_date` and its computed `recall_due_date`
    both begin null, and its computed `outstanding_patient_balance_cents` begins at
    zero."

    Design: Corner/entities/create_patient_returns_201_with_defaults
    """
    pat = validate_success(api.create_patient(
        create_patient_payload(full_name="Jane Doe", date_of_birth="1985-04-12",
                               plan_carrier="EYEMED"), FRONT_DESK), 201)
    assert pat["medical_insurance_on_file"] is False
    assert pat["recall_interval_months"] == 12
    assert pat["outstanding_patient_balance_cents"] == 0
    assert pat["last_routine_exam_date"] is None


def test_get_patient_not_found_returns_404(api):
    """PRD §2.5: "the system validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier in the path that does not
    correspond to an existing resource."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    res = api.get_patient("11111111-1111-4111-8111-111111111111", FRONT_DESK)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_patient_missing_required_field_returns_422(api):
    """PRD §2.6: "Request-schema conformance comes fifth: required fields present,
    correct types, legal enum values, and honored numeric ranges — any violation yields
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "Registering a patient captures the patient's `full_name`,
    `date_of_birth` ... and `plan_carrier`."

    Omitting plan_carrier (required, no default) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_missing_required_field_returns_422
    """
    res = api.create_patient({"full_name": "No Carrier", "date_of_birth": "1985-04-12"}, FRONT_DESK)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_patient_invalid_enum_carrier_returns_422(api):
    """PRD §3.1: "`plan_carrier`, which is one of `VSP`, `EYEMED`, or `NONE`."
    PRD §2.6: "legal enum values ... any violation yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_patient_invalid_enum_carrier_returns_422
    """
    res = api.create_patient(
        create_patient_payload(full_name="Bad Enum", plan_carrier="AETNA"), FRONT_DESK)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_provider_invalid_npi_length_returns_422(api):
    """PRD §3.1: "Registering a provider captures a `full_name`, a `role` that is either
    `OPTOMETRIST` or `OPTICIAN`, and an `npi` that must be exactly ten digits."

    Design: Corner/entities/create_provider_invalid_npi_length_returns_422
    """
    res = api.create_provider(
        create_provider_payload(full_name="Short NPI", role="OPTOMETRIST", npi="123"), FRONT_DESK)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_prescription_sphere_not_quarter_step_returns_422(api):
    """PRD §3.3: "the right-eye and left-eye sphere powers `sphere_od` and `sphere_os`,
    each a diopter value from -20.00 to 20.00 that must be a multiple of 0.25."

    Design: Corner/entities/prescription_sphere_not_quarter_step_returns_422
    """
    from test_helpers import setup_clinic
    ctx = setup_clinic(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    enc = create_open_encounter(ctx["pat"]["id"], ctx["od"]["id"])

    res = api.create_prescription(
        ctx["pat"]["id"],
        create_prescription_payload(enc["id"], sphere_od=-1.13, sphere_os=-1.00),
        ctx["od_h"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_system_fields_generated_on_create(api):
    """PRD §2.4: "Each such resource exposes an `id`, a server-minted UUID with no type
    prefix ... and a `version`, an integer that begins at its initial value on creation
    and increments by one with each mutation of the resource."

    Design: Corner/entities/system_fields_generated_on_create_input_ignored
    """
    pat = validate_success(api.create_patient(
        create_patient_payload(full_name="Sys Fields", date_of_birth="1985-04-12",
                               plan_carrier="VSP"), FRONT_DESK), 201)
    assert pat["version"] == 1
    assert is_valid_uuid(pat["id"])


def test_encounter_reference_not_found_returns_404(api):
    """PRD §2.5: "When a creation request names a related resource that does not exist —
    for instance a `patient_id`, `provider_id`, `encounter_id`, `eligibility_id`, or
    `prescription_id` that matches no stored record — the request is rejected with
    `ERR_REFERENCE_NOT_FOUND`. This reference check applies to opening an encounter."

    Design: Corner/entities/encounter_reference_not_found_returns_404
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    od = create_optometrist()
    res = api.create_encounter({
        "patient_id": "22222222-2222-4222-8222-222222222222",
        "provider_id": od["id"],
        "encounter_type": "ROUTINE_VISION",
        "exam_fee_cents": 12000,
        "refraction_fee_cents": 3000,
    }, FRONT_DESK)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


def test_provider_immutable_no_version_field(api):
    """PRD §2.4: "A `Provider` carries only `id` and `created_at` — it has neither an
    `updated_at` nor a `version`, because provider records are not mutated after
    registration."

    Design: Corner/entities/provider_immutable_no_version_field
    """
    prov = validate_success(api.create_provider(
        create_provider_payload(full_name="Immutable P", role="OPTICIAN", npi="3333333333"),
        FRONT_DESK), 201)
    assert is_valid_uuid(prov["id"])
    assert "version" not in prov


# --------------------------------------------------------------------------- #
# Calculations — prescription expiry, remake surcharge
# --------------------------------------------------------------------------- #
def test_contact_rx_expiry_12_months_computed(api):
    """PRD §3.3: "The `expiry_months` validity window is 24 months for an `EYEGLASS`
    prescription and 12 months for a `CONTACT` prescription, and the `expiry_date` is
    the `issue_date` advanced by that many months."

    Design: Corner/calculations/contact_rx_expiry_12_months_computed
    """
    ctx = setup_clinic(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    enc = create_open_encounter(ctx["pat"]["id"], ctx["od"]["id"])
    rx = validate_success(api.create_prescription(
        ctx["pat"]["id"],
        create_prescription_payload(enc["id"], rx_type="CONTACT", issue_date="2026-06-01"),
        ctx["od_h"]), 201)
    assert rx["expiry_months"] == 12
    assert rx["expiry_date"] == "2027-06-01"


def test_remake_surcharge_applied_on_second_remake(api):
    """PRD §3.6: "When sending a remake back to the lab would make the order's
    `remake_count` become two, the system applies a remake surcharge ... If the
    prospective new count is at least two, a surcharge of 2,500 cents is added to the
    order's `patient_materials_cost_cents`; otherwise the surcharge is zero."

    Self-pay STANDARD order: patient_materials = 23000 retail; after the 2nd remake
    send-to-lab a 2500 surcharge is added -> 25500.

    Design: Corner/state_machines/remake_surcharge_applied_on_second_remake
    """
    # One completed remake (remake_count == 1), DISPENSED, then request a 2nd remake.
    ctx = setup_order_after_n_remakes(1)
    order_id, opt_h = ctx["order"]["id"], ctx["opt_h"]
    get_success_data(api.request_lab_order_remake(order_id, {"reason": "r2"}, opt_h))

    sent = validate_success(api.send_lab_order_to_lab(order_id, opt_h), 200)
    assert sent["remake_count"] == 2
    assert sent["patient_materials_cost_cents"] == 25500


# --------------------------------------------------------------------------- #
# Endpoints — listing, subresource
# --------------------------------------------------------------------------- #
def test_list_prescriptions_pagination_envelope(api):
    """PRD §2.3: "Paginated list-based responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Two EYEGLASS prescriptions issued from the same encounter; the second supersedes
    the first, so the patient has two prescriptions on record.

    Design: Corner/endpoints/list_prescriptions_pagination_envelope
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    pat_id, od_h = ctx["pat"]["id"], ctx["od_h"]
    issue_prescription(pat_id, ctx["enc"]["id"], od_h, sphere_od=-1.50, sphere_os=-1.25)

    data, meta = validate_paginated(api.list_patient_prescriptions(pat_id, FRONT_DESK))
    assert meta["total_count"] == 2
    assert len(data) == 2


def test_benefit_pools_subresource_returns_two_pools(api):
    """PRD §3.4: "Opening an eligibility automatically provisions its two benefit pools,
    exactly one of each `pool_type` per eligibility. The `MATERIALS` pool's
    `allotted_cents` is copied from the eligibility's `materials_allowance_cents`."

    Design: Corner/endpoints/benefit_pools_subresource_returns_two_pools
    """
    ctx = setup_clinic(with_optician=False, patient_overrides={"plan_carrier": "VSP"}, elig=True,
                       elig_overrides={"materials_allowance_cents": 40000})
    data, _ = validate_paginated(api.list_eligibility_benefit_pools(ctx["elig"]["id"], FRONT_DESK))
    assert len(data) == 2
    materials = [p for p in data if p["pool_type"] == "MATERIALS"]
    exam = [p for p in data if p["pool_type"] == "EXAM"]
    assert len(materials) == 1 and len(exam) == 1
    assert materials[0]["allotted_cents"] == 40000


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
def test_biller_cannot_place_laborder(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "An `Optician` places, advances, dispenses, remakes, and cancels lab
    orders."

    Design: Corner/rbac/biller_cannot_place_laborder
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    res = api.create_lab_order(create_lab_order_payload(ctx["rx"]["id"]), BILLER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_optician_cannot_adjudicate_claim(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "A `Biller` drafts, adjudicates, settles, denies, voids, and submits
    claims and records carrier acknowledgements."

    Design: Corner/rbac/optician_cannot_adjudicate_claim_peer_isolation
    """
    from test_helpers import setup_finalized_routine_encounter, draft_claim
    ctx = setup_finalized_routine_encounter(
        elig=True, patient_overrides={"plan_carrier": "VSP"},
        elig_overrides={"materials_allowance_cents": 40000})
    claim = draft_claim(ctx["enc"]["id"], eligibility_id=ctx["elig"]["id"])

    res = api.adjudicate_claim(claim["id"], OPTICIAN_FALLBACK)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one of
    these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_patients(make_unknown_role_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")
