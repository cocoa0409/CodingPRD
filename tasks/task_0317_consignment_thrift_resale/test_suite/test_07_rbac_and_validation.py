"""RBAC, authentication, reference resolution, and the item-grade OCC increment.

Covers the validations- and rbac-section corner instances plus the FK
reverse-reachability of items under a batch and the item-version increment on a
successful grade.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_version_incremented,
    create_intake_batch_payload, create_item_payload, grade_accept_payload,
    create_consignor_payload, create_settlement_payload, redeem_payload,
    TEST_USERS,
    set_clock, setup_agreement,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]


# ─── Corner: authentication header validation ────────────────────────────────

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header on a protected endpoint is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    _, _, agreement = setup_agreement(consignor_email="hdr@x.com")
    res = api.create_intake_batch(create_intake_batch_payload(agreement["id"]), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Corner: body FK reference resolution ────────────────────────────────────

def test_reference_not_found_on_item_create_bad_batch(api):
    """PRD §2.5: "When a creation payload names a foreign resource — a
    `consignor_id`, an `agreement_id`, a `batch_id`, an `item_id`, or a
    `markdown_schedule_id` — and that identifier does not resolve to an existing
    row, the request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/reference_not_found_on_item_create_bad_batch
    """
    res = api.create_item(
        create_item_payload("00000000-0000-4000-8000-000000000000", title="Orphan"),
        GRADER)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=404)


# ─── Corner: store-credit redemption fiscal limit ────────────────────────────

def test_insufficient_store_credit_redeem_returns_422(api):
    """PRD §3.6: "A redemption that would drive the consignor's posted store-credit
    balance below zero is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`."

    Design: Corner/validations/insufficient_store_credit_redeem_returns_422
    """
    cons = validate_success(api.create_consignor(
        create_consignor_payload(full_name="Broke Bo", email="broke@x.com"), ADMIN), 201)
    res = api.redeem_store_credit(cons["id"], redeem_payload(5000), CASHIER)
    validate_error(res, "ERR_INSUFFICIENT_STORE_CREDIT", expected_status=422)


# ─── Corner: RBAC exclusive-operation denials ────────────────────────────────

def test_cashier_cannot_grade_item_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation per the matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/cashier_cannot_grade_item_returns_forbidden
    """
    _, _, agreement = setup_agreement(consignor_email="rb@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    item = validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat"), GRADER), 201)
    res = api.grade_item(
        item["id"], grade_accept_payload(5000, item["version"]), CASHIER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_intakegrader_cannot_open_settlement_returns_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation per the matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/intakegrader_cannot_open_settlement_returns_forbidden
    """
    res = api.create_settlement(create_settlement_payload("2026-06-20"), GRADER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner: FK reverse-reachability (items under a batch) ───────────────────

def test_batch_items_reverse_reachable(api):
    """PRD §4: "GET `/intake-batches/{id}/items` — List items in a batch".
    PRD §3.2: "Individual garments are added to an `OPEN` batch by an
    `IntakeGrader` or `StoreAdmin`, who supplies the `batch_id`".

    Design: Corner/endpoints/fk_item_to_batch_reverse_reachable_via_batch_items
    """
    _, _, agreement = setup_agreement(consignor_email="fk@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat 1"), GRADER), 201)
    validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat 2"), GRADER), 201)
    items = validate_success(api.list_batch_items(batch["id"], GRADER), 200)
    assert len(items) == 2, f"expected 2 items in batch, got {len(items)}"


# ─── Corner: item version increments on grade (OCC) ──────────────────────────

def test_grade_with_current_version_succeeds_and_increments(api):
    """PRD §2.8: "Grading an item requires the request to carry
    `expected_item_version`, which must equal the target `Item`'s current
    `version`."
    PRD §3.2: "Both decisions increment the item's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_item_version_increments_on_grade
    """
    _, _, agreement = setup_agreement(consignor_email="occ@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    item = validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat"), GRADER), 201)
    before_version = item["version"]
    graded = validate_success(api.grade_item(
        item["id"], grade_accept_payload(5000, item["version"]), GRADER), 200)
    assert graded["grading_status"] == "ACCEPTED"
    assert_version_incremented(graded["version"], before_version)
