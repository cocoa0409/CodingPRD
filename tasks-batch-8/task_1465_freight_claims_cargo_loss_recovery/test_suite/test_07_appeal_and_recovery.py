"""Decline, appeal, and recovery: the cyclic decline/appeal path with its
round budget, optimistic concurrency on appeal intake, and the indemnity-first
gate on subrogation."""
from test_helpers import (
    ApiErrorId,
    assert_appeal,
    assert_subrogation,
    create_appeal_payload,
    create_salvage_payload,
    create_subrogation_payload,
    get_claim,
    get_success_data,
    set_clock,
    setup_claim_declined,
    setup_claim_paid,
    setup_claim_under_review,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADJUSTER = TEST_USERS["adjuster_headers"]
MANAGER = TEST_USERS["manager_headers"]
SALVAGE = TEST_USERS["salvage_headers"]
SUBRO = TEST_USERS["subro_headers"]


class TestDeclineAppealCycle:
    def test_upheld_appeal_returns_claim_to_declined_with_round_counted(self, api):
        """PRD §3.7: "The new appeal opens in `OPEN` state with a `round_number` that is 1-indexed and unique within the claim, records its `opened_by_user_id`, increments the claim's `appeal_round`, moves the claim from `DECLINED` to `APPEALED`, appends an `APPEAL_OPENED` event, and increments the claim's `version`."
        PRD §3.7: "An `UPHOLD_DECLINE` decision returns the claim to `DECLINED`, where a further appeal round remains possible only if the round budget has not been exhausted."

        Design: Difficulty/non_linear_state_machine/claim_decline_appeal_cycle
        """
        ctx = setup_claim_declined()
        claim_id = ctx["claim"]["id"]
        # Round 1: appeal, then UPHOLD_DECLINE -> back to DECLINED.
        version = get_claim(claim_id)["version"]
        appeal1 = validate_success(
            api.open_appeal(claim_id, create_appeal_payload(version), ADJUSTER), 201
        )
        assert_appeal(appeal1)
        assert appeal1["state"] == "OPEN"
        assert get_claim(claim_id)["filing_status"] == "APPEALED"
        validate_success(
            api.decide_appeal(
                claim_id, appeal1["id"], {"decision": "UPHOLD_DECLINE"}, MANAGER
            ),
            200,
        )
        claim = get_claim(claim_id)
        assert claim["filing_status"] == "DECLINED"
        assert claim["appeal_round"] == 1
        # Round 2 still fits the budget.
        version = claim["version"]
        appeal2 = validate_success(
            api.open_appeal(
                claim_id,
                create_appeal_payload(version, justification="Second appeal"),
                ADJUSTER,
            ),
            201,
        )
        assert appeal2["round_number"] == 2
        claim = get_claim(claim_id)
        assert claim["filing_status"] == "APPEALED"
        assert claim["appeal_round"] == 2

    def test_overturn_replaces_liability_and_reopens_review(self, api):
        """PRD §3.7: "An `OVERTURN` decision demands that the deciding manager not be the user who opened the appeal — a same-user decide is `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — and carries a `decided_amount_cents`; it replaces the claim's `computed_liability_cents` with the decided amount, superseding the prior assessment for settlement purposes, recomputes `net_exposure_cents` against the salvage credit with the zero floor, and returns the claim to `UNDER_REVIEW` for a fresh offer cycle."

        Design: Difficulty/non_linear_state_machine/claim_decline_appeal_cycle
        """
        # Assessment computes 30_000; the overturned appeal replaces it.
        ctx = setup_claim_declined(claim_over={"claimed_amount_cents": 30_000})
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["computed_liability_cents"] == 30_000
        version = get_claim(claim_id)["version"]
        appeal = validate_success(
            api.open_appeal(claim_id, create_appeal_payload(version), ADJUSTER), 201
        )
        decided = validate_success(
            api.decide_appeal(
                claim_id,
                appeal["id"],
                {"decision": "OVERTURN", "decided_amount_cents": 40_000},
                MANAGER,
            ),
            200,
        )
        assert decided["state"] == "DECIDED"
        assert decided["decision"] == "OVERTURN"
        claim = get_claim(claim_id)
        assert claim["filing_status"] == "UNDER_REVIEW"
        assert claim["computed_liability_cents"] == 40_000
        assert claim["net_exposure_cents"] == 40_000


class TestAppealGuards:
    def test_appeal_round_exhausted_after_two(self, api):
        """PRD §3.7: "A `ClaimsAdjuster` may open an appeal — the claim must be `DECLINED`, its `appeal_round` must still be below 2 (a claim that has already consumed two rounds is refused with `ERR_APPEAL_ROUND_EXHAUSTED`), and the request must carry `expected_claim_version` per §2.6, because another writer may have advanced the round counter and changed eligibility since the client last read the claim."

        Design: Corner/validations/appeal_round_exhausted_after_two
        """
        ctx = setup_claim_declined()
        claim_id = ctx["claim"]["id"]
        for round_no in (1, 2):
            version = get_claim(claim_id)["version"]
            appeal = validate_success(
                api.open_appeal(claim_id, create_appeal_payload(version), ADJUSTER),
                201,
            )
            validate_success(
                api.decide_appeal(
                    claim_id, appeal["id"], {"decision": "UPHOLD_DECLINE"}, MANAGER
                ),
                200,
            )
        claim = get_claim(claim_id)
        assert claim["appeal_round"] == 2
        assert claim["filing_status"] == "DECLINED"
        resp = api.open_appeal(
            claim_id, create_appeal_payload(claim["version"]), ADJUSTER
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ROUND_EXHAUSTED)

    def test_appeal_with_stale_claim_version_rejected(self, api):
        """PRD §2.6: "If that value does not match the claim's current `version` — because another writer has since advanced it, for example by posting an assessment, executing a salvage credit, or posting a reserve, all of which legitimately alter the claim's exposure figures and bump its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The three guarded operations are: extending a settlement offer on a claim under review, declining a claim under review, and opening an appeal on a declined claim."
        PRD §3.7: "A `ClaimsAdjuster` may open an appeal — the claim must be `DECLINED`, its `appeal_round` must still be below 2 (a claim that has already consumed two rounds is refused with `ERR_APPEAL_ROUND_EXHAUSTED`), and the request must carry `expected_claim_version` per §2.6, because another writer may have advanced the round counter and changed eligibility since the client last read the claim."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_appeal_create
        """
        # Claim is DECLINED; a salvage execution after the client read the
        # claim advances its version while the claim stays DECLINED, so the
        # appeal carries a stale expected_claim_version. The claim being
        # DECLINED (an executable state per §3.5), the §2.7 clock sweep itself
        # executes the due disposition and advances the claim's version.
        ctx = setup_claim_under_review()
        claim_id = ctx["claim"]["id"]
        get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=1_000,
                    handling_cost_cents=0,
                    scheduled_at="2026-06-11T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        version = get_claim(claim_id)["version"]
        get_success_data(
            api.decline_claim(claim_id, {"expected_claim_version": version}, ADJUSTER)
        )
        stale_version = get_claim(claim_id)["version"]
        set_clock("2026-06-12T00:00:00Z")
        assert get_claim(claim_id)["filing_status"] == "DECLINED"
        assert get_claim(claim_id)["version"] > stale_version, (
            "The scheduled salvage execution must have advanced the claim version"
        )
        resp = api.open_appeal(
            claim_id, create_appeal_payload(stale_version), ADJUSTER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSubrogationGate:
    def test_subrogation_on_unpaid_claim_rejected(self, api):
        """PRD §3.8: "A `SubrogationSpecialist` opens a subrogation case only against a claim in `PAID` or `CLOSED_WITH_PAYMENT` — pursuing a third party before the shipper is made whole is refused with `ERR_CLAIM_NOT_PAID`."

        Design: Difficulty/cross_entity_state_dependency/subrogation_requires_paid_claim
        """
        ctx = setup_claim_under_review(negligence_flag="THIRD_PARTY")
        resp = api.open_subrogation(
            ctx["claim"]["id"], create_subrogation_payload(), SUBRO
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAID)

    def test_subrogation_on_paid_claim_opens(self, api):
        """PRD §3.8: "A `SubrogationSpecialist` opens a subrogation case only against a claim in `PAID` or `CLOSED_WITH_PAYMENT` — pursuing a third party before the shipper is made whole is refused with `ERR_CLAIM_NOT_PAID`."
        PRD §3.8: "The case names a `responsible_party_kind` of `THIRD_PARTY_CARRIER`, `WAREHOUSE`, `BROKER`, `SHIPPER_VENDOR`, or `OTHER`, the `responsible_party_name`, and a `target_recovery_cents` greater than zero; it opens in `OPEN` state with `recovered_cents` and `recovery_ratio_bp` at zero."

        Design: Difficulty/cross_entity_state_dependency/subrogation_requires_paid_claim
        """
        ctx = setup_claim_paid(amount_cents=40_000, reserve_amount_cents=40_000)
        assert ctx["claim"]["filing_status"] == "PAID"
        case = validate_success(
            api.open_subrogation(
                ctx["claim"]["id"], create_subrogation_payload(), SUBRO
            ),
            201,
        )
        assert_subrogation(case)
        assert case["state"] == "OPEN"
        assert case["recovered_cents"] == 0
        assert case["recovery_ratio_bp"] == 0
