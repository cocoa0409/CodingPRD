"""Onboarding defaults, system-managed fields, and IC-classification compliance."""
from test_helpers import (
    validate_success, validate_error, get_success_data, is_valid_uuid,
    ApiErrorId, TEST_USERS,
    create_operator, create_truck, create_lease, create_verified_operator,
    submit_and_verify_doc, create_active_lease, set_clock,
    create_owner_operator_payload, create_truck_payload,
    create_compliance_document_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Queue B: corner/entities ────────────────────────

def test_owner_operator_classification_defaults_pending_review(api):
    """PRD section 3.1: "The new operator's `classification_status` begins at
    `PENDING_REVIEW` — registration alone establishes nothing about compliance
    posture." PRD section 2.4: "`version` is an integer that starts at 1 and
    increments on every mutation of the resource, including mutations driven by
    system cascades rather than direct client writes."

    Design: Corner/entities/owner_operator_classification_defaults_pending_review
    """
    res = api.create_owner_operator(create_owner_operator_payload(), ADMIN)
    operator = validate_success(res, 201)
    assert operator["classification_status"] == "PENDING_REVIEW"
    assert operator["version"] == 1
    assert is_valid_uuid(operator["id"]), "id must be a server-minted UUID"


def test_truck_create_extra_field_input_ignored(api):
    """PRD section 2.4: "creation payloads that carry fields beyond the
    documented input set have those extras silently ignored — they are neither
    stored nor echoed."

    Design: Corner/entities/truck_create_extra_field_input_ignored
    """
    payload = create_truck_payload()
    payload["fleet_tag"] = "IGNORED"
    truck = validate_success(api.create_truck(payload, ADMIN), 201)
    assert truck["status"] == "AVAILABLE"
    assert "fleet_tag" not in truck, "undeclared body field must not be echoed"


def test_common_fields_version_increments_on_mutation(api):
    """PRD section 2.4: "`version` is an integer that starts at 1 and increments
    on every mutation of the resource, including mutations driven by system
    cascades rather than direct client writes." PRD section 3.3: "Successful
    activation moves the lease `APPLICATION` → `ACTIVE`, flips the truck
    `AVAILABLE` → `LEASED`, and increments the lease `version`."

    Design: Corner/entities/common_fields_version_increments_on_mutation
    """
    operator = create_verified_operator()
    truck = create_truck()
    lease = create_lease(operator["id"], truck["id"])
    assert lease["version"] == 1, "version starts at 1 on create"

    activated = validate_success(api.activate_lease(lease["id"], ADMIN), 200)
    assert activated["version"] == 2, "activate is one mutation: exactly +1"
    assert activated["status"] == "ACTIVE"


# ─── Queue B: corner/state_machines (documents) ──────

def test_doc_reverify_rejected(api):
    """PRD section 3.2: "Either action on a document no longer in `SUBMITTED`
    fails with `ERR_DOC_ALREADY_REVIEWED`."

    Design: Corner/state_machines/doc_reverify_rejected
    """
    operator = create_operator()
    doc = submit_and_verify_doc(operator["id"], "W9")
    assert doc["status"] == "VERIFIED"

    res = api.verify_compliance_document(doc["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_DOC_ALREADY_REVIEWED.value)
    after = validate_success(api.get_compliance_document(doc["id"], OFFICER), 200)
    assert after["status"] == "VERIFIED", "first verification stands"


def test_doc_expiry_flips_operator_flagged(api):
    """PRD section 3.2: "whenever a compliance document is read, and whenever a
    classification check runs, a `VERIFIED` document whose `expires_on` has been
    reached or passed by the logical clock evaluates to `EXPIRED` — and that
    evaluation feeds the classification recompute, dropping a `VERIFIED` operator
    to `FLAGGED`."

    Design: Corner/state_machines/doc_expiry_flips_operator_flagged
    """
    operator = create_verified_operator(doc_expires_on="2026-08-20")
    cls_pre = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert cls_pre["classification_status"] == "VERIFIED"

    set_clock("2026-08-21T00:00:00Z")

    docs = validate_success(
        api.list_compliance_documents(OFFICER, params={"owner_operator_id": operator["id"]}), 200)
    assert len(docs) == 3
    assert all(d["status"] == "EXPIRED" for d in docs), "clock >= expires_on evaluates EXPIRED"

    cls_post = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert cls_post["classification_status"] == "FLAGGED"


def test_doc_reject_flips_operator_flagged_then_reverify_recovers(api):
    """PRD section 3.2: "When any required document is `REJECTED`, or a required
    `VERIFIED` document has reached or passed its `expires_on`, the operator is
    `FLAGGED`." PRD section 3.2: "A `FLAGGED` operator returns to `VERIFIED` only
    when a replacement required document is verified and unexpired, restoring the
    full required set."

    Design: Corner/cross_cutting_layers/doc_reject_flips_operator_flagged_then_reverify_recovers
    """
    operator = create_operator()
    submit_and_verify_doc(operator["id"], "W9")
    submit_and_verify_doc(operator["id"], "OPERATING_AUTHORITY")
    ic_doc = get_success_data(api.create_compliance_document(
        create_compliance_document_payload(operator["id"], "INSURANCE_CERTIFICATE"), OFFICER))

    get_success_data(api.reject_compliance_document(
        ic_doc["id"], {"reason": "expired certificate scan"}, OFFICER))
    cls_flagged = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert cls_flagged["classification_status"] == "FLAGGED"

    submit_and_verify_doc(operator["id"], "INSURANCE_CERTIFICATE")
    cls_verified = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert cls_verified["classification_status"] == "VERIFIED"


# ─── Queue A: difficulty/cross_entity_state_dependency ──

def test_activation_rejected_while_operator_pending_review(api):
    """PRD section 3.3: "the activation additionally requires the operator's
    `classification_status` to be `VERIFIED` at that moment — a `PENDING_REVIEW`
    or `FLAGGED` posture rejects the activation with
    `ERR_COMPLIANCE_REQUIREMENTS_UNMET` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/activation_requires_operator_verified
    """
    operator = create_operator()
    submit_and_verify_doc(operator["id"], "W9")
    submit_and_verify_doc(operator["id"], "OPERATING_AUTHORITY")
    # INSURANCE_CERTIFICATE missing -> PENDING_REVIEW
    pre = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert pre["classification_status"] == "PENDING_REVIEW"

    truck = create_truck()
    lease = create_lease(operator["id"], truck["id"])
    res = api.activate_lease(lease["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_COMPLIANCE_REQUIREMENTS_UNMET.value)

    after = validate_success(api.get_lease_agreement(lease["id"], ADMIN), 200)
    assert after["status"] == "APPLICATION"


def test_activation_succeeds_after_third_required_doc_verified(api):
    """PRD section 3.2: "When every required type has a `VERIFIED` document whose
    `expires_on` lies strictly after the current logical clock, the operator is
    `VERIFIED`." PRD section 3.3: "Successful activation moves the lease
    `APPLICATION` → `ACTIVE`, flips the truck `AVAILABLE` → `LEASED`, and
    increments the lease `version`."

    Design: Difficulty/cross_entity_state_dependency/activation_requires_operator_verified
    """
    operator = create_operator()
    submit_and_verify_doc(operator["id"], "W9")
    submit_and_verify_doc(operator["id"], "OPERATING_AUTHORITY")
    truck = create_truck()
    lease = create_lease(operator["id"], truck["id"])

    submit_and_verify_doc(operator["id"], "INSURANCE_CERTIFICATE")
    cls = validate_success(api.get_owner_operator(operator["id"], ADMIN), 200)
    assert cls["classification_status"] == "VERIFIED"

    activated = validate_success(api.activate_lease(lease["id"], ADMIN), 200)
    assert activated["status"] == "ACTIVE"
    truck_after = validate_success(api.get_truck(truck["id"], ADMIN), 200)
    assert truck_after["status"] == "LEASED", "activation flips the truck to LEASED"


# ─── Queue A: difficulty/priority_pair_validation_conflict ──

def _setup_active_lease_with_expired_docs():
    """Lease activated while docs valid; clock then moved past their expiry so
    the operator's classification flips FLAGGED."""
    scenario = create_active_lease(doc_expires_on="2026-08-20")
    set_clock("2026-08-21T00:00:00Z")
    return scenario


def test_activate_state_error_beats_compliance_error(api):
    """PRD section 2.8: "Fourth, state preconditions of the target resource (the
    per-endpoint 409 state errors such as `ERR_LEASE_NOT_IN_APPLICATION` or
    `ERR_SETTLEMENT_NOT_ISSUED`). Fifth, business-safety rules
    (independent-contractor classification on activation)." PRD section 3.3: "A
    `LeaseAdmin` activates a lease that is still in `APPLICATION` (otherwise
    `ERR_LEASE_NOT_IN_APPLICATION`)".

    Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_compliance_error
    """
    scenario = _setup_active_lease_with_expired_docs()
    lease_id = scenario["lease"]["id"]

    operator = validate_success(
        api.get_owner_operator(scenario["operator"]["id"], ADMIN), 200)
    assert operator["classification_status"] == "FLAGGED", (
        "docs expired: the business-safety rule would also fail")

    res = api.activate_lease(lease_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_IN_APPLICATION.value)

    after = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert after["status"] == "ACTIVE", "failed activation changes nothing"


def test_activate_state_error_not_compliance_error_when_both_fail(api):
    """PRD section 2.8: "When a request fails for more than one reason, the
    surfaced error follows a fixed priority order." and "Fourth, state
    preconditions of the target resource (the per-endpoint 409 state errors such
    as `ERR_LEASE_NOT_IN_APPLICATION` or `ERR_SETTLEMENT_NOT_ISSUED`). Fifth,
    business-safety rules (independent-contractor classification on
    activation)."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_compliance_error
    """
    scenario = _setup_active_lease_with_expired_docs()
    lease_id = scenario["lease"]["id"]

    res = api.activate_lease(lease_id, ADMIN)
    body = res.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_LEASE_NOT_IN_APPLICATION.value, (
        f"state tier (fourth) must surface over business-safety (fifth), got "
        f"{body['data']['error_id']}")
    assert body["data"]["error_id"] != ApiErrorId.ERR_COMPLIANCE_REQUIREMENTS_UNMET.value
