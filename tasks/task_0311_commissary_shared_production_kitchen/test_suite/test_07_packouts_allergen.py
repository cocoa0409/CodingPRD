"""Event packouts: batch-completion gate, allergen sealing gate, and
packed-unit roll-up.

Translates corner queue instances:
  endpoints / packout_seal_clean_allergens_succeeds
  validations / packout_batch_not_completed_rejected
  errors / error_allergen_conflict_triggered
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_member, create_ingredient,
    create_published_recipe, create_planned_batch,
    setup_member_with_completed_batch,
)

FM = TEST_USERS["facility_manager_headers"]


# ── Corner: endpoints / packout_seal_clean_allergens_succeeds ──

def test_seal_packout_with_disjoint_allergens_succeeds(api):
    """PRD 3.12: "Sealing a packout is the safety gate. It is permitted only while
    the packout is DRAFT (otherwise ERR_INVALID_STATE) and only when the
    packout's combined_allergen_tags shares no allergen code with the
    allergen_free_required list — the two sets must be disjoint." A {MILK} packout
    requiring free-of PEANUT seals successfully; packed_unit_count is the summed
    actual_yield_units (10).

    Design: Corner/endpoints/packout_seal_clean_allergens_succeeds
    """
    member, ingredient, recipe, batch = setup_member_with_completed_batch(
        allergen_tags=["MILK"], planned_yield_units=10, planned_qty=1.0)
    mo = make_member_operator_headers(member["id"])
    packout = validate_success(api.create_packout(member["id"], {
        "event_name": "CleanGala",
        "batch_ids": [batch["id"]],
        "allergen_free_required": ["PEANUT"],
    }, mo), 201)
    sealed = validate_success(api.seal_packout(member["id"], packout["id"], mo), 200)
    assert sealed["status"] == "SEALED"
    assert sealed["packed_unit_count"] == 10, f"got {sealed['packed_unit_count']}"


# ── Corner: errors / error_allergen_conflict_triggered ──

def test_seal_packout_with_conflicting_allergen_rejected(api):
    """PRD 3.12: "If they intersect in even one code, the seal is rejected with
    ERR_ALLERGEN_CONFLICT". A PEANUT-carrying packout that the event requires to
    be free of PEANUT cannot be sealed.

    Design: Corner/errors/error_allergen_conflict_triggered
    """
    member, ingredient, recipe, batch = setup_member_with_completed_batch(
        allergen_tags=["PEANUT"], planned_yield_units=10, planned_qty=1.0)
    mo = make_member_operator_headers(member["id"])
    packout = validate_success(api.create_packout(member["id"], {
        "event_name": "NutGala",
        "batch_ids": [batch["id"]],
        "allergen_free_required": ["PEANUT"],
    }, mo), 201)
    res = api.seal_packout(member["id"], packout["id"], mo)
    validate_error(res, "ERR_ALLERGEN_CONFLICT")


# ── Corner: validations / packout_batch_not_completed_rejected ──

def test_create_packout_with_planned_batch_rejected(api):
    """PRD 3.12: "Creating a packout requires the acting member to be ACTIVE
    (otherwise ERR_MEMBER_NOT_ACTIVE) and requires that every id in batch_ids
    reference a COMPLETED production batch owned by this member (otherwise
    ERR_BATCH_NOT_COMPLETED)." A packout referencing a PLANNED batch is rejected.

    Design: Corner/validations/packout_batch_not_completed_rejected
    """
    member = register_member(business_name="Bnc")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="BncIng", unit_cost_cents=100)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="BncR")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=10)
    res = api.create_packout(member["id"], {
        "event_name": "Gala",
        "batch_ids": [batch["id"]],
    }, mo)
    validate_error(res, "ERR_BATCH_NOT_COMPLETED")
