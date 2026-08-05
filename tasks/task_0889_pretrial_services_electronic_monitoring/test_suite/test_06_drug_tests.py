"""Drug-test scheduling: aggregate slot capacity, the safety-before-temporal precedence,
and the required DRUG_TESTING condition.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules resource_temporal_overlap.
drugtest_slot_aggregate_capacity and priority_pair_validation_conflict.
drugtest_safety_beats_temporal; and SCAFFOLD_CORNER_DESIGN.yaml validations.
drugtest_without_condition_returns_condition_not_ordered.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    activate_defendant, create_site, create_drug_test_payload, schedule_drug_test,
)

SUPERVISING = TEST_USERS["supervising_headers"]


# ─── resource_temporal_overlap / drugtest_slot_aggregate_capacity ──────────

def test_overlapping_slot_at_capacity_rejected(api):
    """PRD §3.8: "the count of existing tests at that site in `SCHEDULED` or `COLLECTED`
    status whose half-open slots overlap the requested slot must be strictly less than the
    site's `slot_capacity`, otherwise `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/drugtest_slot_aggregate_capacity
    """
    ctx = activate_defendant(ordered_conditions=["DRUG_TESTING"])
    def_id = ctx["defendant"]["id"]
    site = create_site(slot_capacity=1)
    schedule_drug_test(def_id, site["id"], slot_start="2026-06-01T09:00:00Z")
    resp = api.create_drug_test(
        create_drug_test_payload(def_id, site["id"], slot_start="2026-06-01T09:15:00Z"),
        SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED, 409)


def test_adjacent_slot_at_prior_end_accepted(api):
    """PRD §3.8: "the slot occupies the half-open interval from `slot_start` up to but not
    including `slot_end`." (a test starting at the prior slot's end does not overlap and
    fits within capacity).

    Design: Difficulty/resource_temporal_overlap/drugtest_slot_aggregate_capacity
    """
    ctx = activate_defendant(ordered_conditions=["DRUG_TESTING"])
    def_id = ctx["defendant"]["id"]
    site = create_site(slot_capacity=1)
    schedule_drug_test(def_id, site["id"], slot_start="2026-06-01T09:00:00Z")
    data = validate_success(api.create_drug_test(
        create_drug_test_payload(def_id, site["id"], slot_start="2026-06-01T09:30:00Z"),
        SUPERVISING), 201)
    assert data["status"] == "SCHEDULED"


# ─── priority_pair_validation_conflict / drugtest_safety_beats_temporal ────

def test_condition_error_beats_capacity_error(api):
    """PRD §2.10: validation priority "7. Required ordered condition (drug-test scheduling,
    EM activation) ... `ERR_CONDITION_NOT_ORDERED` (409)." precedes "10. Testing-site
    capacity ... `ERR_SLOT_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/drugtest_safety_beats_temporal
    """
    # Defendant A holds the single capacity slot (has DRUG_TESTING ordered).
    ctx_a = activate_defendant(ordered_conditions=["DRUG_TESTING"])
    site = create_site(slot_capacity=1)
    schedule_drug_test(ctx_a["defendant"]["id"], site["id"], slot_start="2026-06-01T09:00:00Z")
    # Defendant B is ACTIVE but lacks DRUG_TESTING, and requests an overlapping slot.
    ctx_b = activate_defendant(ordered_conditions=["CHECK_IN"])
    resp = api.create_drug_test(
        create_drug_test_payload(ctx_b["defendant"]["id"], site["id"],
                                 slot_start="2026-06-01T09:15:00Z"), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_ORDERED, 409)


def test_condition_error_fires_when_only_condition_missing(api):
    """PRD §3.8: "Scheduling requires that the defendant have the `DRUG_TESTING` condition on
    an ordered release order, or it is rejected with `ERR_CONDITION_NOT_ORDERED`."

    Design: Difficulty/priority_pair_validation_conflict/drugtest_safety_beats_temporal
    """
    ctx = activate_defendant(ordered_conditions=["CHECK_IN"])
    site = create_site(slot_capacity=5)
    resp = api.create_drug_test(
        create_drug_test_payload(ctx["defendant"]["id"], site["id"],
                                 slot_start="2026-06-01T09:15:00Z"), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_ORDERED, 409)


# ─── Corner: validations.drugtest_without_condition_returns_condition_not_ordered ──

def test_drug_test_without_ordered_condition_rejected(api):
    """PRD §3.8: "Scheduling requires that the defendant have the `DRUG_TESTING` condition on
    an ordered release order, or it is rejected with `ERR_CONDITION_NOT_ORDERED`."

    Design: Corner/validations/drugtest_without_condition_returns_condition_not_ordered
    """
    ctx = activate_defendant(ordered_conditions=["CHECK_IN"])
    site = create_site(slot_capacity=5)
    resp = api.create_drug_test(
        create_drug_test_payload(ctx["defendant"]["id"], site["id"],
                                 slot_start="2026-06-05T10:00:00Z"), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_ORDERED, 409)
