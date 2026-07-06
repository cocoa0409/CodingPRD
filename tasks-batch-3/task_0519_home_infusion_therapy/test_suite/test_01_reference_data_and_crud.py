"""Reference-data creation, CRUD basics, defaults, FK integrity, RBAC, pagination.

Translates Queue B (Corner) instances from sections: entities, endpoints, rbac.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
BILLER = TEST_USERS["biller_headers"]


def test_create_patient_returns_201_with_system_fields(api):
    """PRD 2.4: "The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource."
    PRD 3.1: "the patient's own `status` begins `ACTIVE` and becomes `DISCHARGED` only through patient lifecycle handling."

    Design: Corner/entities/create_patient_returns_201_with_system_fields
    """
    plan = fixtures.create_payer_plan()
    resp = api.create_patient(
        F.create_patient_payload(full_name="Eve", service_state="CA", payer_plan_id=plan["id"]),
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["created_at"], "created_at must be present"


def test_get_patient_not_found_returns_404(api):
    """PRD 2.6: "A reference that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_required_field_returns_invalid_request(api):
    """PRD 2.8: "structural validity of the body — required fields present and well-typed, enum members drawn from the allowed set, numeric constraints honored (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/create_order_missing_required_field_returns_invalid_request
    """
    drug = fixtures.create_drug()
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    referral = fixtures.create_accepted_referral(patient["id"])
    payload = F.create_order_payload(referral_id=referral["id"], drug_id=drug["id"])
    del payload["daily_dose_mg"]
    resp = api.create_order(payload, PHARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_drug_invalid_therapy_category_enum_returns_invalid_request(api):
    """PRD 2.8: "enum members drawn from the allowed set, numeric constraints honored (`ERR_INVALID_REQUEST`, HTTP 422)."
    PRD 3.1: "The `therapy_category` must be one of `ANTI_INFECTIVE`, `AMINOGLYCOSIDE_OR_VANCO`, `TPN`, `IMMUNE_GLOBULIN`, or `CHEMO`."

    Design: Corner/entities/create_drug_invalid_therapy_category_enum_returns_invalid_request
    """
    payload = F.create_drug_payload(therapy_category="NOT_A_CATEGORY")
    resp = api.create_drug(payload, PHARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_drug_default_flags_applied_when_omitted(api):
    """PRD 3.1: "Two booleans may be supplied and each defaults to false when omitted: `is_specialty ... and requires_trough_lab ... On registration the server sets `on_hand_vials` equal to `lot_total_vials`."

    Design: Corner/entities/create_drug_default_flags_applied_when_omitted
    """
    payload = F.create_drug_payload(lot_total_vials=100)
    del payload["is_specialty"]
    del payload["requires_trough_lab"]
    resp = api.create_drug(payload, PHARM)
    data = validate_success(resp, expected_status=201)
    assert data["is_specialty"] is False
    assert data["requires_trough_lab"] is False
    assert data["on_hand_vials"] == 100


def test_order_system_fields_input_ignored(api):
    """PRD 3.2: "The server copies `patient_id` onto the order from the referral, sets `administered_days` to 0, and places the order in `DRAFT`."

    Design: Corner/entities/order_system_fields_input_ignored
    """
    drug = fixtures.create_drug()
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    referral = fixtures.create_accepted_referral(patient["id"])
    resp = api.create_order(
        F.create_order_payload(referral_id=referral["id"], drug_id=drug["id"]),
        PHARM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["administered_days"] == 0
    assert data["patient_id"] == patient["id"]


def test_list_drug_catalog_paginated_envelope(api):
    """PRD 2.3: "The pagination block exposed in the `meta` object reports `limit`, `offset`, `total_count` (the count of all matching resources before the window is applied), and `has_more` (true when resources remain beyond the current window)."

    Design: Corner/entities/list_drug_catalog_paginated_envelope
    """
    fixtures.create_drug(generic_name="a", therapy_category="ANTI_INFECTIVE")
    fixtures.create_drug(generic_name="b", therapy_category="TPN")
    resp = api.list_drugs(PHARM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit 1 should return 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True


def test_order_requires_accepted_referral_parent(api):
    """PRD 3.2: "From there the coordinator either accepts it, moving `RECEIVED` to `ACCEPTED`, or rejects it ... Once a referral is `ACCEPTED`, a `Pharmacist` builds the infusion order against it."
    PRD 2.8: "state legality, i.e. the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/entities/order_requires_accepted_referral_parent
    """
    drug = fixtures.create_drug()
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    # RECEIVED referral, not accepted
    referral = validate_success(
        api.create_referral(F.create_referral_payload(patient_id=patient["id"]), INTAKE),
        expected_status=201,
    )
    resp = api.create_order(
        F.create_order_payload(referral_id=referral["id"], drug_id=drug["id"]),
        PHARM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_flat_topology_fk_integrity_payer_plan_must_exist(api):
    """PRD 2.6: "each identifier must resolve to an existing entity ... A reference that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/flat_topology_fk_integrity_payer_plan_must_exist
    """
    resp = api.create_patient(
        F.create_patient_payload(
            full_name="Pat FK", service_state="CA", payer_plan_id=NON_EXISTENT_UUID
        ),
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_claim_create_correct_order_version_succeeds(api):
    """PRD 2.7: "The server compares `expected_order_version` against the order's current `version`."
    PRD 3.12: "The new claim begins in `DRAFT` with `variant` `ESTIMATE`, and on creation the server computes the estimate figures and reads — but does not change — the payer plan's accumulators."

    Design: Corner/endpoints/claim_create_correct_order_version_succeeds
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=3, order_overrides={"daily_dose_mg": 1000}
    )
    ver = fixtures.get_order_version(ctx["order"]["id"])
    resp = api.create_claim(
        F.create_claim_payload(order_id=ctx["order"]["id"], expected_order_version=ver),
        BILLER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["variant"] == "ESTIMATE"


def test_order_summary_computed_read_returns_administered_days(api):
    """PRD 3.7: "On every completion the server recomputes the order's `administered_days` as the count of that order's nursing visits that are in `COMPLETED`."

    Design: Corner/endpoints/order_summary_computed_read_returns_administered_days
    """
    ctx = fixtures.setup_active_order_with_completed_visits(num_completed=1, scheduled_days=5)
    resp = api.get_order(ctx["order"]["id"], PHARM)
    data = validate_success(resp)
    assert data["administered_days"] == 1
    assert data["status"] == "ACTIVE"


def test_list_compounds_filtered_by_pump(api):
    """PRD 2.3: "Lists are always returned sorted by `created_at` in ascending order, so the oldest matching resource appears first."
    PRD 3.4: "A compound batch ties a released order to a physical pump and a delivery window. A Pharmacist creates the compound with the order_id, the pump_id of the
    paired pump."

    Design: Corner/endpoints/list_compounds_filtered_by_pump_reverse_reachability
    """
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={"vial_size_mg": 1000},
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 7},
    )
    pump = fixtures.create_pump()
    compound = validate_success(
        api.create_compound(
            F.create_compound_payload(order_id=ctx["order"]["id"], pump_id=pump["id"]),
            PHARM,
        ),
        expected_status=201,
    )
    resp = api.list_compounds(PHARM, params={"pump_id": pump["id"]})
    data, _ = validate_paginated(resp)
    assert any(c["id"] == compound["id"] for c in data), "compound on the pump must be listed"


# --- RBAC ---
def test_nurse_cannot_post_drug_catalog(api):
    """PRD 2.1: "When the headers are present but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/nurse_cannot_post_drug_catalog
    """
    nurse = fixtures.create_nurse()
    headers = make_visiting_nurse_headers(nurse["id"])
    resp = api.create_drug(F.create_drug_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_biller_can_create_payer_plan(api):
    """PRD 2.1: "A `Biller` owns payer plans and the claim lifecycle."

    Design: Corner/rbac/biller_can_create_payer_plan_shared_get_allowed
    """
    resp = api.create_payer_plan(
        F.create_payer_plan_payload(plan_code="PRBOK"), BILLER
    )
    data = validate_success(resp, expected_status=201)
    assert data["plan_code"] == "PRBOK"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_payer_plan(F.create_payer_plan_payload(plan_code="PNH"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
