"""Recall liability (estimated vs final), depth-3 cascade, and reinstatement."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    TEST_USERS,
    create_policy, record_sale,
    setup_approved_manifest, setup_registered_producer_with_approved_product,
    create_registered_producer, create_approved_product,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_recall_estimated_liability_uses_severity_projection(api):
    """PRD §3.7: "The estimated liability, `estimated_liability_cents`, is the
    severity-projected unit count multiplied by the product's `unit_price_cents`, where
    the projected units are 10 for `LOW`, 50 for `MEDIUM`, and 200 for `HIGH`."

    Design: Difficulty/dual_variant_calc/recall_estimated_vs_final_liability
    """
    s = setup_registered_producer_with_approved_product(api, unit_price_cents=800)
    resp = api.create_recall({"producer_id": s["producer"]["id"], "product_id": s["product"]["id"],
                              "reason": "ILLNESS_OUTBREAK", "severity": "HIGH"}, ADMIN)
    recall = validate_success(resp, 201)
    assert recall["estimated_liability_cents"] == 160000


def test_recall_final_liability_uses_actual_units(api):
    """PRD §3.7: "the server computes `final_liability_cents` as `recalled_units`
    multiplied by the product's `unit_price_cents`; this final figure diverges from the
    initial estimate whenever the actual returned units differ from the severity
    projection."

    Design: Difficulty/dual_variant_calc/recall_estimated_vs_final_liability
    """
    s = setup_registered_producer_with_approved_product(api, unit_price_cents=800)
    recall = validate_success(api.create_recall(
        {"producer_id": s["producer"]["id"], "product_id": s["product"]["id"],
         "reason": "ILLNESS_OUTBREAK", "severity": "HIGH"}, ADMIN), 201)
    resolved = validate_success(api.resolve_recall(recall["id"], {"recalled_units": 25}, ADMIN), 200)
    assert resolved["final_liability_cents"] == 20000
    assert resolved["estimated_liability_cents"] != resolved["final_liability_cents"]


def _recall_cascade_setup(api):
    scenario = setup_approved_manifest(api, unit_price_cents=700)
    recall = validate_success(api.create_recall(
        {"producer_id": scenario["producer"]["id"], "product_id": scenario["product"]["id"],
         "reason": "CONTAMINATION", "severity": "MEDIUM"}, ADMIN), 201)
    return scenario, recall


def test_recall_cascade_recalls_product_and_suspends_permit(api):
    """PRD §3.7: "The cascade then, in order, moves the target product's
    `compliance_status` to `RECALLED`; suspends the producer's `ISSUED` permit and moves
    the producer's `status` to `SUSPENDED`; and voids every non-terminal manifest bound
    to that permit, freeing each held day-slot and bumping the owning market's `version`."

    Design: Difficulty/transitive_cascade/recall_initiate_depth3_cascade
    """
    scenario, _ = _recall_cascade_setup(api)
    product = get_success_data(api.get_product(scenario["product"]["id"], INSPECTOR))
    permit = get_success_data(api.get_permit(scenario["permit"]["id"], INSPECTOR))
    assert product["compliance_status"] == "RECALLED"
    assert permit["status"] == "SUSPENDED"


def test_recall_cascade_voids_bound_manifest(api):
    """PRD §3.7: "and voids every non-terminal manifest bound to that permit, freeing
    each held day-slot and bumping the owning market's `version`."

    Design: Difficulty/transitive_cascade/recall_initiate_depth3_cascade
    """
    scenario, _ = _recall_cascade_setup(api)
    manifest = get_success_data(api.get_manifest(scenario["manifest"]["id"], INSPECTOR))
    assert manifest["status"] == "VOIDED"


def test_resolve_already_resolved_recall_rejected(api):
    """PRD §3.7: "A resolve attempted against a recall that is not in `INITIATED` is
    rejected with `ERR_RECALL_INVALID_STATE`."

    Design: Corner/state_machines/recall_resolve_from_resolved_returns_invalid_state
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="RecCo")
    pid = producer["id"]
    product = create_approved_product(api, pid, name="RecProd", unit_price_cents=500)
    recall = validate_success(api.create_recall(
        {"producer_id": pid, "product_id": product["id"], "reason": "MISLABEL", "severity": "LOW"}, ADMIN), 201)
    validate_success(api.resolve_recall(recall["id"], {"recalled_units": 5}, ADMIN), 200)
    resp = api.resolve_recall(recall["id"], {"recalled_units": 3}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECALL_INVALID_STATE.value, 409)
    after = get_success_data(api.get_recall(recall["id"], INSPECTOR))
    assert after["status"] == "RESOLVED"


def test_reinstate_suspended_producer_returns_registered(api):
    """PRD §3.1: "Reinstatement moves the producer from `SUSPENDED` back to `REGISTERED`;
    if any `RecallEvent` for the producer is still in `INITIATED` status, the
    reinstatement is refused with `ERR_RECALL_INVALID_STATE`."

    Design: Corner/endpoints/reinstate_suspended_producer_returns_registered
    """
    scenario = setup_approved_manifest(api, unit_price_cents=300)
    pid = scenario["producer"]["id"]
    record_sale(api, pid, scenario["manifest"]["id"], 7500001)  # breach cap -> SUSPENDED
    suspended = get_success_data(api.get_producer(pid, INSPECTOR))
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_producer(pid, ADMIN), 200)
    assert reinstated["status"] == "REGISTERED"
