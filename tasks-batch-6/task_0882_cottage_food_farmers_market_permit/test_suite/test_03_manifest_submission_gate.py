"""Market manifest submission gate: ordered compliance checks and precedence."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error,
    make_producer_headers, TEST_USERS,
    create_permit_payload, create_product_payload, create_manifest_payload,
    create_policy, register_producer, create_registered_producer,
    create_class_a_issued_permit, create_approved_product, declare_product,
    create_market, create_draft_manifest, submit_manifest,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _submitted_permit_scenario(api, business_name):
    """Registered producer, approved product, market (CLASS_A), permit only SUBMITTED,
    and a DRAFT manifest referencing that permit. Returns (producer_id, manifest_id)."""
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name=business_name)
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_A"), ph), 201)
    validate_success(api.submit_permit(permit["id"], ph), 200)
    product = create_approved_product(api, pid)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]])
    return pid, manifest["id"]


def test_manifest_submit_requires_issued_permit(api):
    """PRD §3.4: "The linked permit's `status` must be `ISSUED`, else
    `ERR_PERMIT_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_requires_issued_permit
    """
    pid, mid = _submitted_permit_scenario(api, "Not Issued Co")
    resp = api.submit_manifest(mid, make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value, 409)


def test_manifest_submit_unissued_permit_keeps_manifest_draft(api):
    """PRD §3.4: "The linked permit's `status` must be `ISSUED`, else
    `ERR_PERMIT_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_requires_issued_permit
    """
    pid, mid = _submitted_permit_scenario(api, "Not Issued Co 2")
    validate_error(api.submit_manifest(mid, make_producer_headers(pid)),
                   ApiErrorId.ERR_PERMIT_NOT_ISSUED.value, 409)
    after = validate_success(api.get_manifest(mid, INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def _safety_vs_venue_scenario(api, business_name):
    """Issued CLASS_A permit + a DECLARED (unapproved) product + market allowing only
    CLASS_B; a DRAFT manifest referencing the unapproved product. Both the product-safety
    gate and the venue-class gate would fail."""
    producer = create_registered_producer(api, business_name=business_name)
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = declare_product(api, pid, name="Unreviewed Loaf", unit_price_cents=600)
    market = create_market(api, allowed_classes=["CLASS_B"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]])
    return pid, manifest["id"]


def test_product_safety_gate_beats_venue_class_gate(api):
    """PRD §2.10: "then product safety gates, then venue-class restriction, then temporal
    checks, then duplicate-manifest detection, and finally market-day capacity."
    PRD §3.4: "A product that is not approved on the compliance axis yields
    `ERR_PRODUCT_NOT_APPROVED`;"

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_manifest_submit
    """
    pid, mid = _safety_vs_venue_scenario(api, "Dual Fail Foods")
    resp = api.submit_manifest(mid, make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_APPROVED.value, 422)


def test_product_safety_gate_conflict_keeps_manifest_draft(api):
    """PRD §2.10: "then product safety gates, then venue-class restriction, then temporal
    checks, then duplicate-manifest detection, and finally market-day capacity."
    PRD §3.4: "A product that is not approved on the compliance axis yields
    `ERR_PRODUCT_NOT_APPROVED`;"

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_manifest_submit
    """
    pid, mid = _safety_vs_venue_scenario(api, "Dual Fail Foods 2")
    validate_error(api.submit_manifest(mid, make_producer_headers(pid)),
                   ApiErrorId.ERR_PRODUCT_NOT_APPROVED.value, 422)
    after = validate_success(api.get_manifest(mid, INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def _posture_vs_referential_scenario(api, business_name):
    """PENDING_VERIFICATION producer (never verified), a DRAFT permit (not issued), a
    product, and a DRAFT manifest. Both the posture gate and the permit-issued gate would
    fail."""
    producer = register_producer(api, business_name=business_name)
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_A"), ph), 201)
    product = validate_success(api.create_product(create_product_payload(pid, name="Some Bread", unit_price_cents=600), ph), 201)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(pid, market["id"], permit["id"], [product["id"]]), ph), 201)
    return pid, manifest["id"]


def test_producer_posture_gate_beats_permit_issued_gate(api):
    """PRD §3.4: "1. The acting producer must be `REGISTERED`, else
    `ERR_PRODUCER_NOT_REGISTERED`. 2. The linked permit's `status` must be `ISSUED`, else
    `ERR_PERMIT_NOT_ISSUED`."

    Design: Difficulty/priority_pair_validation_conflict/producer_posture_beats_referential_on_manifest_submit
    """
    pid, mid = _posture_vs_referential_scenario(api, "Unverified Co")
    resp = api.submit_manifest(mid, make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_REGISTERED.value, 409)


def test_producer_posture_conflict_keeps_manifest_draft(api):
    """PRD §3.4: "1. The acting producer must be `REGISTERED`, else
    `ERR_PRODUCER_NOT_REGISTERED`. 2. The linked permit's `status` must be `ISSUED`, else
    `ERR_PERMIT_NOT_ISSUED`."

    Design: Difficulty/priority_pair_validation_conflict/producer_posture_beats_referential_on_manifest_submit
    """
    pid, mid = _posture_vs_referential_scenario(api, "Unverified Co 2")
    validate_error(api.submit_manifest(mid, make_producer_headers(pid)),
                   ApiErrorId.ERR_PRODUCER_NOT_REGISTERED.value, 409)
    after = validate_success(api.get_manifest(mid, INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def _duplicate_manifest_scenario(api, business_name):
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name=business_name)
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, unit_price_cents=300)
    market = create_market(api, allowed_classes=["CLASS_A"])
    m1 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-15")
    submit_manifest(api, pid, m1["id"])
    m2 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-15")
    return pid, m2["id"]


def test_duplicate_manifest_same_producer_market_date_rejected(api):
    """PRD §3.4: "No other non-terminal manifest may already exist for the same
    combination of producer, market, and event date, else `ERR_DUPLICATE_MANIFEST`."

    Design: Difficulty/resource_temporal_overlap/duplicate_manifest_same_market_date_point
    """
    pid, m2 = _duplicate_manifest_scenario(api, "Dup Co")
    resp = api.submit_manifest(m2, make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MANIFEST.value, 409)


def test_duplicate_manifest_keeps_second_manifest_draft(api):
    """PRD §3.4: "No other non-terminal manifest may already exist for the same
    combination of producer, market, and event date, else `ERR_DUPLICATE_MANIFEST`."

    Design: Difficulty/resource_temporal_overlap/duplicate_manifest_same_market_date_point
    """
    pid, m2 = _duplicate_manifest_scenario(api, "Dup Co 2")
    validate_error(api.submit_manifest(m2, make_producer_headers(pid)),
                   ApiErrorId.ERR_DUPLICATE_MANIFEST.value, 409)
    after = validate_success(api.get_manifest(m2, INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def test_manifest_submit_label_not_approved_rejected(api):
    """PRD §3.4: "one that is not label-approved yields `ERR_LABEL_NOT_APPROVED`;"

    Design: Corner/validations/manifest_submit_label_not_approved_returns_error
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Lbl Co")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = declare_product(api, pid, name="Focaccia", unit_price_cents=400)
    validate_success(api.review_food(product["id"], {"decision": "APPROVE"}, INSPECTOR), 200)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]])
    resp = api.submit_manifest(manifest["id"], make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED.value, 422)
    after = validate_success(api.get_manifest(manifest["id"], INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def test_manifest_submit_permit_expired_rejected(api):
    """PRD §3.4: "The permit must not be expired at the event: the `event_date` must be
    on or before the calendar date of the permit's `expires_at`, else
    `ERR_PERMIT_EXPIRED`."

    Design: Corner/validations/manifest_submit_permit_expired_returns_error
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Exp Co")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)  # term 2026-05-01 .. 2027-05-01
    product = create_approved_product(api, pid, unit_price_cents=300)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2027-07-01")
    resp = api.submit_manifest(manifest["id"], make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED.value, 409)
    after = validate_success(api.get_manifest(manifest["id"], INSPECTOR), 200)
    assert after["status"] == "DRAFT"


def test_reject_draft_manifest_rejected(api):
    """PRD §3.4: "Any manifest action attempted from an illegal state is rejected with
    `ERR_MANIFEST_INVALID_STATE`."

    Design: Corner/state_machines/manifest_reject_from_draft_returns_invalid_state
    """
    producer = create_registered_producer(api, business_name="RejCo")
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_A"), ph), 201)
    product = declare_product(api, pid, name="Draft Prod", unit_price_cents=300)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]])
    from test_helpers import make_market_manager_headers
    resp = api.reject_manifest(manifest["id"], make_market_manager_headers(market["id"]))
    validate_error(resp, ApiErrorId.ERR_MANIFEST_INVALID_STATE.value, 409)
    after = validate_success(api.get_manifest(manifest["id"], INSPECTOR), 200)
    assert after["status"] == "DRAFT"
