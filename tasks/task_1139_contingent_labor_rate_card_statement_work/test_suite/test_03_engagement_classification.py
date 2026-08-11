"""Engagement creation defaults, classification risk + rework loop,
misclassification override, OCC amendments, and existence checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_engagement,
    create_engagement_payload,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def test_engagement_computed_field_input_ignored(api):
    """PRD: "Computed or system-owned fields supplied in a request body are
    ignored silently — they are not an error."
    PRD: "A new engagement is in `DRAFT`, with `misclassification_risk` null,
    `committed_spend_cents` at zero, `awarded_supplier_id` null, and
    `budget_audit_raised` false."
    PRD: "an optional `prorata_conversion` flag (default false)"

    Design: Corner/entities/engagement_computed_field_input_ignored
    """
    payload = create_engagement_payload(
        title="Sneaky", duration_months=3, committed_spend_cents=999999
    )
    engagement = validate_success(api.create_engagement(payload, HM), expected_status=201)
    assert_engagement(engagement)
    assert engagement["committed_spend_cents"] == 0, (
        "client-supplied computed field must be ignored"
    )
    assert engagement["prorata_conversion"] is False, "default false applies"
    assert engagement["misclassification_risk"] is None, "null before first review"
    assert engagement["status"] == "DRAFT"
    assert engagement["awarded_supplier_id"] is None
    assert engagement["budget_audit_raised"] is False


def test_missing_engagement_returns_not_found(api):
    """PRD: "Any identifier that does not resolve to an existing resource
    yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/missing_engagement_returns_not_found
    """
    resp = api.get_engagement(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClassificationReworkCycle:
    def test_rework_loop_is_legal_and_repeatable(self, api):
        """PRD: "A `decision` of `REWORK` sends the engagement `IN_REVIEW` →
        `DRAFT` and records the request's `note` into `classification_note`;
        the loop `DRAFT` → `IN_REVIEW` → `DRAFT` is legal and repeatable."

        Design: Difficulty/non_linear_state_machine/engagement_classification_rework_cycle
        """
        engagement = get_success_data(
            api.create_engagement(create_engagement_payload(title="Cyclic engagement"), HM)
        )
        eid = engagement["id"]
        assert engagement["status"] == "DRAFT"

        in_review = get_success_data(api.submit_engagement_review(eid, HM))
        assert in_review["status"] == "IN_REVIEW"
        back1 = get_success_data(
            api.classification_decision(
                eid, {"decision": "REWORK", "note": "scope unclear"}, ADMIN
            )
        )
        assert back1["status"] == "DRAFT"
        assert back1["classification_note"] == "scope unclear"

        in_review2 = get_success_data(api.submit_engagement_review(eid, HM))
        assert in_review2["status"] == "IN_REVIEW"
        back2 = get_success_data(
            api.classification_decision(
                eid, {"decision": "REWORK", "note": "budget split needed"}, ADMIN
            )
        )
        assert back2["status"] == "DRAFT"
        assert back2["classification_note"] == "budget split needed", (
            "each REWORK records that request's note"
        )

        in_review3 = get_success_data(api.submit_engagement_review(eid, HM))
        assert in_review3["status"] == "IN_REVIEW"
        opened = get_success_data(
            api.classification_decision(eid, {"decision": "APPROVE"}, ADMIN)
        )
        assert opened["status"] == "OPEN", (
            "two full rework loops followed by approval succeed without error"
        )

    def test_final_risk_low_for_requisition_hourly_after_loops(self, api):
        """PRD: "Every other combination is `LOW`. The computed value is
        stored on `misclassification_risk`."
        PRD: "A `decision` of `APPROVE` moves the engagement `IN_REVIEW` →
        `OPEN`, but only when the risk is `LOW` or the request supplies a
        `risk_override_rationale`"

        Design: Difficulty/non_linear_state_machine/engagement_classification_rework_cycle
        """
        engagement = get_success_data(
            api.create_engagement(create_engagement_payload(title="Cyclic"), HM)
        )
        eid = engagement["id"]
        get_success_data(api.submit_engagement_review(eid, HM))
        get_success_data(
            api.classification_decision(eid, {"decision": "REWORK", "note": "rework 1"}, ADMIN)
        )
        in_review = get_success_data(api.submit_engagement_review(eid, HM))
        assert in_review["misclassification_risk"] == "LOW", (
            "REQUISITION + HOURLY computes LOW"
        )
        opened = get_success_data(
            api.classification_decision(eid, {"decision": "APPROVE"}, ADMIN)
        )
        assert opened["status"] == "OPEN"
        assert opened["misclassification_risk"] == "LOW"


class TestMisclassificationHighRisk:
    def _submit_risky_sow(self, api) -> str:
        engagement = get_success_data(
            api.create_engagement(
                create_engagement_payload(
                    title="Risky SOW",
                    engagement_type="SOW",
                    payment_basis="HOURLY",
                    supervision_level="MILESTONE",
                    duration_months=12,
                    budget_cents=5_000_000,
                ),
                HM,
            )
        )
        return engagement["id"]

    def test_high_risk_approve_blocked_without_override(self, api):
        """PRD: "The risk is `HIGH` in exactly two shapes: an `SOW` engagement
        whose `payment_basis` is `HOURLY` or whose `supervision_level` is
        `DAILY` (a statement of work that walks like staff augmentation), or a
        `REQUISITION` whose `payment_basis` is `FIXED` (staff augmentation
        priced like a deliverable)."
        PRD: "approving a `HIGH`-risk engagement without that rationale is
        rejected with `ERR_MISCLASSIFICATION_RISK` (422)"

        Design: Corner/validations/misclassification_high_risk_block_and_override
        """
        eid = self._submit_risky_sow(api)
        reviewed = get_success_data(api.submit_engagement_review(eid, HM))
        assert reviewed["misclassification_risk"] == "HIGH", "SOW paid HOURLY is HIGH"

        resp = api.classification_decision(eid, {"decision": "APPROVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MISCLASSIFICATION_RISK)
        still = get_success_data(api.get_engagement(eid, ADMIN))
        assert still["status"] == "IN_REVIEW", "blocked approval leaves state unchanged"

    def test_high_risk_approve_succeeds_with_override_and_records_note(self, api):
        """PRD: "approving a `HIGH`-risk engagement without that rationale is
        rejected with `ERR_MISCLASSIFICATION_RISK` (422), and when the
        override is used the rationale text becomes the `classification_note`."

        Design: Corner/validations/misclassification_high_risk_block_and_override
        """
        eid = self._submit_risky_sow(api)
        reviewed = get_success_data(api.submit_engagement_review(eid, HM))
        assert reviewed["misclassification_risk"] == "HIGH"

        rationale = "legal reviewed; genuine deliverable-based SOW"
        opened = validate_success(
            api.classification_decision(
                eid,
                {"decision": "APPROVE", "risk_override_rationale": rationale},
                ADMIN,
            )
        )
        assert opened["status"] == "OPEN"
        assert opened["classification_note"] == rationale


class TestEngagementAmendOcc:
    def test_amend_stale_version_rejected_412(self, api):
        """PRD: "If the engagement's current `version` has advanced beyond
        that value — because another writer amended the engagement in the
        meantime — the amendment is rejected with
        `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), preventing the client from
        overwriting an engagement state it never observed."

        Design: Corner/cross_cutting/engagement_amend_occ_stale_and_fresh
        """
        engagement = get_success_data(
            api.create_engagement(create_engagement_payload(title="OCC"), HM)
        )
        observed = engagement["version"]
        first = validate_success(
            api.amend_engagement(
                engagement["id"],
                {"expected_engagement_version": observed, "budget_cents": 1_500_000},
                HM,
            )
        )
        assert first["budget_cents"] == 1_500_000
        assert first["version"] == observed + 1

        resp = api.amend_engagement(
            engagement["id"],
            {"expected_engagement_version": observed, "budget_cents": 2_000_000},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION)
        after = get_success_data(api.get_engagement(engagement["id"], ADMIN))
        assert after["budget_cents"] == 1_500_000, "stale write must not apply"

    def test_amend_fresh_version_chain_succeeds(self, api):
        """PRD: "Amending an engagement requires the request to carry
        `expected_engagement_version`, holding the engagement `version` the
        client last observed."
        PRD: "the concurrency-guarded amendment operation of §2.8, which
        requires `expected_engagement_version` and increments the engagement's
        `version` by one on success."

        Design: Corner/cross_cutting/engagement_amend_occ_stale_and_fresh
        """
        engagement = get_success_data(
            api.create_engagement(create_engagement_payload(title="OCC chain"), HM)
        )
        v1 = engagement["version"]
        second = validate_success(
            api.amend_engagement(
                engagement["id"],
                {"expected_engagement_version": v1, "budget_cents": 1_500_000},
                HM,
            )
        )
        assert second["version"] == v1 + 1
        third = validate_success(
            api.amend_engagement(
                engagement["id"],
                {
                    "expected_engagement_version": second["version"],
                    "budget_cents": 2_000_000,
                },
                HM,
            )
        )
        assert third["budget_cents"] == 2_000_000
        assert third["version"] == second["version"] + 1
