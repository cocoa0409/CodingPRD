"""Cast endorsement workflows: type gating, policy-state dependency, and
read-after-write visibility (PRD §3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    create_cast_endorsement_payload, create_policy_payload,
    assert_cast_endorsement,
    set_logical_clock, create_production, create_and_bind_policy,
    add_cast_member, setup_cast_policy_bound, create_issued_endorsement,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_cast_endorsement_type_mismatch_returns_invalid(api):
    """PRD §3.2: "a `STUNT_RIDER` endorsement requires `role_tier` to be
    `STUNT`. Any mismatch is rejected with `ERR_CAST_ENDORSEMENT_INVALID`
    (HTTP 422)"

    Design: Corner/validations/cast_endorsement_type_mismatch_returns_invalid
    """
    prod, cast_policy, members = setup_cast_policy_bound(
        cast_members=[{"role_tier": "PRINCIPAL", "essential_element": False,
                       "exam_outcome": "CLEARED"}])
    endo = validate_success(
        api.create_cast_endorsement(
            prod["id"],
            create_cast_endorsement_payload(members[0]["id"], cast_policy["id"],
                                            endorsement_type="STUNT_RIDER"),
            UW),
        201)
    res = api.issue_cast_endorsement(prod["id"], endo["id"], UW)
    validate_error(res, "ERR_CAST_ENDORSEMENT_INVALID", expected_status=422)


def test_endorsement_issue_rejected_when_policy_not_bound(api):
    """PRD §3.2: "Any mismatch is rejected with `ERR_CAST_ENDORSEMENT_INVALID`
    (HTTP 422), and the policy holding the endorsement must itself be `BOUND`,
    `ENDORSED_PENDING`, or `ACTIVE`."

    The endorsement here is type-consistent (STUNT_RIDER on a STUNT member
    with a CLEARED exam), so the sole failing rule is the referenced policy
    sitting in QUOTED. The PRD names the rejection but not a unique error for
    it: the state-machine reading yields ERR_INVALID_STATE while the
    referenced-target reading yields ERR_REFERENCED_STATE_INVALID — both are
    accepted.

    Design: Difficulty/cross_entity_state_dependency/endorsement_issue_requires_policy_bound
    """
    set_logical_clock()
    prod = create_production(production_type="FEATURE")
    member = add_cast_member(prod["id"], exam_outcome="CLEARED", role_tier="STUNT")
    # CAST policy created but deliberately left QUOTED (never bound).
    cast_policy = validate_success(
        api.create_policy(
            prod["id"],
            create_policy_payload(coverage_line="CAST", carrier_code="CHUBB"),
            BROKER),
        201)
    endo = validate_success(
        api.create_cast_endorsement(
            prod["id"],
            create_cast_endorsement_payload(member["id"], cast_policy["id"],
                                            endorsement_type="STUNT_RIDER"),
            UW),
        201)
    res = api.issue_cast_endorsement(prod["id"], endo["id"], UW)
    actual = validate_error_is_one_of(
        res, ["ERR_INVALID_STATE", "ERR_REFERENCED_STATE_INVALID"])
    assert actual in ("ERR_INVALID_STATE", "ERR_REFERENCED_STATE_INVALID")


def test_endorsement_issue_succeeds_when_policy_bound(api):
    """PRD §3.2: "Issuing an endorsement (`DRAFT` → `ISSUED`) gates on the
    match between type and cast member. A `PHYSICAL_CLEARANCE` endorsement
    requires the cast member's exam status to be `CLEARED` or `CONDITIONAL`; an
    `ESSENTIAL_ELEMENT` endorsement requires `essential_element` to be true; a
    `STUNT_RIDER` endorsement requires `role_tier` to be `STUNT`."

    Positive control for the policy-state dependency: same endorsement shape
    as the rejection case, but the CAST policy is BOUND, so issuance succeeds.

    Design: Difficulty/cross_entity_state_dependency/endorsement_issue_requires_policy_bound
    """
    prod, cast_policy, members = setup_cast_policy_bound(
        cast_members=[{"role_tier": "STUNT", "essential_element": False,
                       "exam_outcome": "CLEARED"}])
    endo = create_issued_endorsement(prod["id"], members[0]["id"],
                                     cast_policy["id"], "STUNT_RIDER")
    assert endo["status"] == "ISSUED"
    assert_cast_endorsement(endo)


def test_endorsee_immediately_visible_after_issue(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "Issuing an endorsement (`DRAFT` → `ISSUED`) gates on the match
    between type and cast member."

    Design: Corner/consistency_model/endorsee_immediately_visible_after_issue
    """
    prod, cast_policy, members = setup_cast_policy_bound(
        cast_members=[{"role_tier": "PRINCIPAL", "essential_element": True,
                       "exam_outcome": "CLEARED"}])
    endo = validate_success(
        api.create_cast_endorsement(
            prod["id"],
            create_cast_endorsement_payload(members[0]["id"], cast_policy["id"],
                                            endorsement_type="ESSENTIAL_ELEMENT"),
            UW),
        201)
    assert endo["status"] == "DRAFT"
    issued = validate_success(api.issue_cast_endorsement(prod["id"], endo["id"], UW), 200)
    assert issued["status"] == "ISSUED"
    # Immediate follow-up read reflects the transition with no lag.
    fetched = validate_success(api.get_cast_endorsement(prod["id"], endo["id"], UW), 200)
    assert fetched["status"] == "ISSUED"
