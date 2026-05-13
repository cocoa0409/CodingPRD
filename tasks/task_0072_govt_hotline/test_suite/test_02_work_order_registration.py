"""Work-order registration, anonymity rules, duplicate-call detection,
PATCH amendments, and classification flow.

PRD §3.2, §3.3.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA, HO, DISP,
    assert_work_order,
    classify,
    create_category_rule,
    create_department,
    create_work_order_payload,
    dispatch,
    expected_difficulty_score,
    find_lead_assignment,
    get_work_order,
    register_work_order,
    setup_routing_world,
    unique_jurisdiction_code,
    unique_phone,
    update_work_order_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Registration happy path (PRD §3.2)
# ===========================================================================
class TestWorkOrderRegistration:
    """PRD §3.2: 'A hotline operator registers an incoming call by
    submitting caller_name, caller_phone, anonymous, jurisdiction_code,
    category_code, sub_category_code, content_text, optionally
    audio_url, and optionally urgency.'"""

    def test_register_returns_work_order_in_state_registered(self, api):
        """PRD §3.2: 'the system creates the work order in state
        REGISTERED, server-stamps registered_at...'"""
        world = setup_routing_world()
        payload = create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        resp = api.create_work_order(payload, HO)
        data = validate_success(resp, expected_status=201)
        assert_work_order(data)
        assert data["status"] == "REGISTERED"
        assert data["classification_mode"] == "PENDING", (
            "PRD §3.2: 'classification_mode is initialised to PENDING.'"
        )
        assert data["lead_department_id"] in (None, ""), (
            "PRD §3.2: 'lead_department_id... left null... pending later "
            "transitions.'"
        )
        assert data["urgency"] == "NORMAL", (
            "PRD §3.2: 'urgency... defaults to NORMAL when omitted.'"
        )
        assert data["anonymous"] is False, (
            "PRD §3.2: 'anonymous defaults to false.'"
        )

    def test_difficulty_score_at_registration_uses_joint_factor_zero(self, api):
        """PRD §3.2: 'plus a joint factor of 0 (because at registration
        the case has not yet been classified and joint_handling
        therefore defaults to false).'

        For urgency=NORMAL (weight 1) and difficulty_base=2 the
        registration_variant gives 1 + 2 + 0 = 3 clamped to [1,10] → 3.
        """
        world = setup_routing_world(num_supporting=1, difficulty_base=2)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="NORMAL",
        )
        assert wo["difficulty_score"] == expected_difficulty_score(
            "NORMAL", 2, joint_handling=False,
        )
        assert wo["difficulty_score"] == 3
        assert wo["joint_handling"] is False, (
            "PRD §3.2: 'joint_handling... left null or empty pending later "
            "transitions.'"
        )

    def test_priority_flag_true_when_urgency_at_least_high(self, api):
        """PRD §3.2: 'priority_flag is recomputed (it is true precisely
        when the urgency is at least HIGH or the difficulty score is at
        least 7).'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="HIGH",
        )
        assert wo["priority_flag"] is True

    def test_priority_flag_false_for_low_urgency_low_difficulty(self, api):
        """PRD §3.2: 'true precisely when the urgency is at least HIGH or
        the difficulty score is at least 7.'"""
        world = setup_routing_world(difficulty_base=1)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="LOW",
        )
        assert wo["priority_flag"] is False


# ===========================================================================
# Anonymity rules (PRD §3.2, validation priority 12)
# ===========================================================================
class TestAnonymityRules:
    """PRD §3.2: 'When anonymous is true, both caller_name and
    caller_phone must be omitted or null; when anonymous is false,
    caller_phone is required. Either violation is rejected with
    ERR_ANONYMOUS_PII_LEAK (422).'"""

    def test_anonymous_with_caller_phone_rejected(self, api):
        """PRD §3.2: 'When anonymous is true, both caller_name and
        caller_phone must be omitted or null... Either violation is
        rejected with ERR_ANONYMOUS_PII_LEAK (422).'"""
        world = setup_routing_world()
        # Build a payload that explicitly includes caller_phone despite
        # anonymous=true (factory honours overrides on anonymous=True).
        payload = create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            anonymous=True,
            caller_phone=unique_phone(),
        )
        resp = api.create_work_order(payload, HO)
        validate_error(resp, ApiErrorId.ERR_ANONYMOUS_PII_LEAK.value)

    def test_anonymous_with_caller_name_rejected(self, api):
        """PRD §3.2: 'When anonymous is true, both caller_name and
        caller_phone must be omitted or null... Either violation is
        rejected with ERR_ANONYMOUS_PII_LEAK (422).'"""
        world = setup_routing_world()
        payload = create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            anonymous=True,
            caller_name="John Doe",
        )
        resp = api.create_work_order(payload, HO)
        validate_error(resp, ApiErrorId.ERR_ANONYMOUS_PII_LEAK.value)

    def test_non_anonymous_without_caller_phone_rejected(self, api):
        """PRD §3.2: 'when anonymous is false, caller_phone is required.
        Either violation is rejected with ERR_ANONYMOUS_PII_LEAK (422).'
        """
        world = setup_routing_world()
        payload = {
            "anonymous": False,
            "jurisdiction_code": world["jurisdiction_code"],
            "category_code": world["category_rule"]["category_code"],
            "sub_category_code": world["category_rule"]["sub_category_code"],
            "content_text": "call from missing phone",
        }
        resp = api.create_work_order(payload, HO)
        validate_error(resp, ApiErrorId.ERR_ANONYMOUS_PII_LEAK.value)

    def test_anonymous_call_without_pii_succeeds(self, api):
        """PRD §3.2: 'When anonymous is true, both caller_name and
        caller_phone must be omitted or null.'"""
        world = setup_routing_world()
        payload = create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            anonymous=True,
        )
        resp = api.create_work_order(payload, HO)
        data = validate_success(resp, expected_status=201)
        assert data["anonymous"] is True


# ===========================================================================
# Category-pair validation (PRD §3.2, priority 21)
# ===========================================================================
class TestCategoryPair:
    """PRD §3.2: 'The (category_code, sub_category_code) pair must
    together resolve to an existing CategoryRule; otherwise the
    registration is rejected with ERR_CATEGORY_UNKNOWN (422).'"""

    def test_unknown_category_pair_rejected(self, api):
        """PRD §3.2: 'otherwise the registration is rejected with
        ERR_CATEGORY_UNKNOWN (422).'"""
        # No rule exists for this random pair.
        jc = unique_jurisdiction_code()
        payload = create_work_order_payload(
            jurisdiction_code=jc,
            category_code="UNKNOWN_CAT",
            sub_category_code="UNKNOWN_SUB",
        )
        resp = api.create_work_order(payload, HO)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_UNKNOWN.value)


# ===========================================================================
# Duplicate-call detection (PRD §3.2, priority 24)
# ===========================================================================
class TestDuplicateDetection:
    """PRD §3.2: 'If a non-terminal work order already exists with the
    same caller_phone (or, when anonymous is true, the same content_text
    hash) and the same category_code, and was registered within the
    last 600 seconds (the duplicate-detection window), the new row is
    forcibly linked: its duplicate_of_id is set to the matching prior
    work order's id, its content_text is appended to the prior work
    order's content_text via a system note, and the response carries
    the 409 status with ERR_DUPLICATE_LINKED.'"""

    def test_duplicate_phone_and_category_within_window_409(self, api):
        """PRD §3.2: 'the response carries the 409 status with
        ERR_DUPLICATE_LINKED and the linked work-order id embedded in
        the error message.'"""
        world = setup_routing_world()
        phone = unique_phone()
        payload = create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            caller_phone=phone,
            content_text="second call same phone",
        )
        first = api.create_work_order(create_work_order_payload(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            caller_phone=phone, content_text="first call",
        ), HO)
        first_data = validate_success(first, expected_status=201)
        # Second registration in window must yield ERR_DUPLICATE_LINKED.
        second = api.create_work_order(payload, HO)
        body = second.json()
        assert second.status_code == 409, (
            f"PRD §3.2: response is 409; got {second.status_code}"
        )
        assert body["data"]["error_id"] == "ERR_DUPLICATE_LINKED"

    def test_different_category_same_phone_not_duplicate(self, api):
        """PRD §3.2: 'with the same caller_phone... AND the same
        category_code, and was registered within the last 600 seconds.'

        Different category_code → not a duplicate.
        """
        w1 = setup_routing_world()
        w2 = setup_routing_world()
        phone = unique_phone()
        api.create_work_order(create_work_order_payload(
            jurisdiction_code=w1["jurisdiction_code"],
            category_code=w1["category_rule"]["category_code"],
            sub_category_code=w1["category_rule"]["sub_category_code"],
            caller_phone=phone, content_text="call 1",
        ), HO)
        resp = api.create_work_order(create_work_order_payload(
            jurisdiction_code=w2["jurisdiction_code"],
            category_code=w2["category_rule"]["category_code"],
            sub_category_code=w2["category_rule"]["sub_category_code"],
            caller_phone=phone, content_text="call 2 different category",
        ), HO)
        # Different category — should succeed (201).
        validate_success(resp, expected_status=201)


# ===========================================================================
# PATCH amendments (PRD §3.2)
# ===========================================================================
class TestWorkOrderPatch:
    """PRD §3.2: 'A registered case still in REGISTERED may be amended
    by the operator with PATCH against content_text, category_code,
    sub_category_code, urgency, or audio_url, optionally with a version
    for the OCC check. If category_code, sub_category_code, or urgency
    is changed, the difficulty score is recomputed under the same
    registration formula.'"""

    def test_patch_urgency_recomputes_difficulty(self, api):
        """PRD §3.2: 'If category_code, sub_category_code, or urgency
        is changed, the difficulty score is recomputed under the same
        registration formula.'"""
        world = setup_routing_world(difficulty_base=2)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="NORMAL",
        )
        # urgency=NORMAL → weight=1; base=2; joint_factor=0 → 3
        assert wo["difficulty_score"] == 3
        resp = api.update_work_order(
            wo["id"], update_work_order_payload(urgency="CRITICAL"), HO,
        )
        updated = validate_success(resp)
        # urgency=CRITICAL → weight=5; base=2; joint_factor=0 → 7
        assert updated["difficulty_score"] == 7
        assert updated["urgency"] == "CRITICAL"

    def test_patch_classified_state_rejected(self, api):
        """PRD §3.2: 'A registered case still in REGISTERED may be
        amended by the operator with PATCH.' Outside REGISTERED, PATCH
        should fail the state precondition (PRD §2.6 priority 8 →
        ERR_INVALID_STATE)."""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        resp = api.update_work_order(
            wo["id"], update_work_order_payload(urgency="HIGH"), HO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_patch_version_mismatch_rejected(self, api):
        """PRD §2.4: 'A request body may optionally include a version
        field; when supplied, the server compares it to the current
        resource's version and rejects a mismatch with
        ERR_VERSION_CONFLICT (409).'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        resp = api.update_work_order(
            wo["id"],
            update_work_order_payload(urgency="HIGH", version=999),
            HO,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Classification flow (PRD §3.3)
# ===========================================================================
class TestClassification:
    """PRD §3.3: 'Classification by a Dispatcher advances the case from
    REGISTERED to CLASSIFIED.'"""

    def test_classify_sets_lead_supporting_and_recomputes_score(self, api):
        """PRD §3.3: 'lead_department_id is set; supporting_department_ids
        is populated by mapping each entry of
        CategoryRule.supporting_department_codes... joint_handling
        becomes true precisely when at least one supporting department
        was mapped... The difficulty score is then recomputed under the
        post-classification form.'"""
        world = setup_routing_world(num_supporting=1, difficulty_base=2)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="NORMAL",
        )
        assert wo["difficulty_score"] == 3
        classified = classify(wo["id"])
        assert classified["status"] == "CLASSIFIED"
        assert classified["lead_department_id"] == world["lead_department"]["id"]
        assert classified["joint_handling"] is True
        assert len(classified["supporting_department_ids"]) == 1
        # Post-classification: NORMAL(1) + base(2) + JOINT(2) = 5
        assert classified["difficulty_score"] == 5

    def test_classify_unknown_work_order_404(self, api):
        """PRD §2.5: 'a missing WorkOrder yields
        ERR_WORK_ORDER_NOT_FOUND (404).'"""
        resp = api.classify_work_order(
            NON_EXISTENT_UUID, {"mode": "RULE_BASED"}, DISP,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value)

    def test_classify_rejected_when_no_jurisdiction_match(self, api):
        """PRD §3.3: 'If neither holds — the mapped lead does not serve
        the jurisdiction and no citywide fallback exists —
        classification is rejected with ERR_JURISDICTION_NO_DEPARTMENT
        (422).'"""
        # Set up a routing world where the lead is bound to jurisdiction A
        # and no citywide peer exists, but the work order's jurisdiction is B.
        world = setup_routing_world(jurisdiction_code="J0001")
        # Register the WO against a different jurisdiction.
        wo = register_work_order(
            jurisdiction_code="J9999",
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        resp = api.classify_work_order(
            wo["id"], {"mode": "RULE_BASED"}, DISP,
        )
        validate_error(resp, ApiErrorId.ERR_JURISDICTION_NO_DEPARTMENT.value)

    def test_classify_twice_invalid_state(self, api):
        """PRD §3.3: 'The transition is permitted only when... and
        lead_department_id is still null; otherwise the work-order
        state-permission check fires with ERR_INVALID_STATE.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        resp = api.classify_work_order(
            wo["id"], {"mode": "RULE_BASED"}, DISP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
