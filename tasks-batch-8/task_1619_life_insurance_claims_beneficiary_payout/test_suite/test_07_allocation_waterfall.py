"""The beneficiary allocation waterfall: per-beneficiary round-first ordering
with remainder assignment, pool selection by rank (primary, then contingent,
then estate), and the empty-pool escheatment case with its computed dates."""
from test_helpers import (
    ApiErrorId,
    approve_claim,
    create_policy_with_statute,
    file_claim_with_verified_docs,
    get_beneficiary_claim,
    get_claim,
    list_beneficiary_claims_of,
    list_escheatment_cases,
    set_clock,
    setup_approved_claim,
    validate_success,
)


class TestRoundingOrderAndRemainder:
    def test_allocation_rounds_each_share_then_assigns_remainder(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "For each pool member the raw share is the
        `total_payable_cents` multiplied by the member's `share_percent` and
        divided by 100, and each member's share is rounded half-up to whole
        cents first — the total itself is never rounded."
        PRD §3.6: "The remainder, positive or negative, between the total and
        the sum of the rounded shares is assigned to the pool member with the
        highest `share_percent`; ties break to the earliest designation
        `effective_date`, then to the earliest designation creation timestamp."
        PRD §3.7: "the claims-scoped view accepts a `status` filter and is
        ordered by creation ascending".

        Shares 33.33/33.33/33.34 of 999999 round to 333300/333300/333400 (sum
        1000000); the -1 remainder lands on the largest share holder, yielding
        333300/333300/333399 in creation order.

        Design: Difficulty/combinatorial_formula/allocation_per_beneficiary_rounding_then_remainder
        """
        ctx = setup_approved_claim(
            state="TX",
            face_amount_cents=999999,
            beneficiaries=[
                {"name": "Ann Poe", "type": "PRIMARY", "share": 33.33},
                {"name": "Ben Poe", "type": "PRIMARY", "share": 33.33},
                {"name": "Cat Poe", "type": "PRIMARY", "share": 33.34},
            ],
            policy_overrides={"policy_number": "P-TX-2",
                              "insured_name": "Sam Poe",
                              "insured_dob": "1950-01-01"},
        )
        assert ctx["claim"]["total_payable_cents"] == 999999, (
            "TX grace 365 keeps interest at zero inside the scenario window")

        listed = list_beneficiary_claims_of(ctx["claim"]["id"])
        assert len(listed) == 3
        amounts = [b["allocated_amount_cents"] for b in listed]
        assert amounts == [333300, 333300, 333399], (
            f"Per-beneficiary round-first with remainder to the highest share; "
            f"got {amounts}")

    def test_allocation_conservation_and_payable_transition(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "Pool members move from `VALIDATED` to `PAYABLE` carrying
        their `allocated_amount_cents`; validated claims outside the pool remain
        `VALIDATED`."
        PRD §3.6: "The remainder, positive or negative, between the total and
        the sum of the rounded shares is assigned to the pool member with the
        highest `share_percent`".

        The rounded distribution 333300/333300/333399 sums back to the total —
        the rounding convention never creates or destroys cents.

        Design: Difficulty/combinatorial_formula/allocation_per_beneficiary_rounding_then_remainder
        """
        ctx = setup_approved_claim(
            state="TX",
            face_amount_cents=999999,
            beneficiaries=[
                {"name": "Ann Poe", "type": "PRIMARY", "share": 33.33},
                {"name": "Ben Poe", "type": "PRIMARY", "share": 33.33},
                {"name": "Cat Poe", "type": "PRIMARY", "share": 33.34},
            ],
            policy_overrides={"policy_number": "P-TX-2",
                              "insured_name": "Sam Poe",
                              "insured_dob": "1950-01-01"},
        )
        listed = list_beneficiary_claims_of(ctx["claim"]["id"])
        assert all(b["status"] == "PAYABLE" for b in listed)
        assert sum(b["allocated_amount_cents"] for b in listed) == 999999, (
            "Allocation conservation: rounded shares plus remainder == total")


class TestPoolSelection:
    def test_allocation_contingent_pool_when_no_primary(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "The pool is selected by rank from the claim's beneficiary
        claims in `VALIDATED` status — claims in `SUBMITTED`, `DISPUTED`,
        `REJECTED`, `WITHDRAWN`, or `INTERPLEADED` never participate: if any
        validated claim references a `PRIMARY` designation, those claims form
        the pool; otherwise, if any references a `CONTINGENT` designation,
        those form the pool; otherwise, if an `ESTATE` claimant exists, the
        estate claims form the pool, each treated as holding a share of 100 —
        which the capacity rule of §3.7 guarantees can be at most one;
        otherwise the pool is empty and the proceeds stand unclaimed."

        With zero validated primary claims, the contingent pool takes the whole
        total.

        Design: Corner/calculations/c_allocation_contingent_pool_selected_when_no_primary
        """
        ctx = setup_approved_claim(
            state="TX",
            beneficiaries=[{"name": "Carol Roe", "type": "CONTINGENT",
                            "share": 100}],
            policy_overrides={"policy_number": "P-CALC-1"},
        )
        bc = get_beneficiary_claim(ctx["beneficiary_claims"][0]["id"])
        assert bc["status"] == "PAYABLE"
        assert bc["allocated_amount_cents"] == 10000000
        assert ctx["claim"]["total_payable_cents"] == 10000000

    def test_allocation_estate_pool_when_no_designations(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "otherwise, if an `ESTATE` claimant exists, the estate
        claims form the pool, each treated as holding a share of 100 — which
        the capacity rule of §3.7 guarantees can be at most one; otherwise the
        pool is empty and the proceeds stand unclaimed."
        PRD §3.6: "When the pool is empty, approval additionally opens an
        escheatment case over the claim proceeds" — a non-empty pool opens none.

        Design: Corner/calculations/c_allocation_estate_pool_when_no_designations
        """
        ctx = setup_approved_claim(
            state="TX",
            beneficiaries=[{"name": "Estate of John Roe", "type": "ESTATE",
                            "share": None}],
            policy_overrides={"policy_number": "P-CALC-2"},
        )
        bc = get_beneficiary_claim(ctx["beneficiary_claims"][0]["id"])
        assert bc["status"] == "PAYABLE"
        assert bc["allocated_amount_cents"] == 10000000

        cases = list_escheatment_cases({"claim_id": ctx["claim"]["id"]})
        assert cases == [], "A non-empty pool opens no escheatment case"


class TestEmptyPoolEscheatmentCase:
    def test_escheatment_case_computed_dates(self, api,
                                             compliance_officer_headers):
        """PRD §3.6: "When the pool is empty, approval additionally opens an
        escheatment case over the claim proceeds — `subject_type`
        `CLAIM_PROCEEDS`, status `MONITORING`, `trigger_date` set to the
        `approved_at` date, `amount_cents` snapshotting the unpaid proceeds —
        per the lifecycle in §3.9."
        PRD §3.9: "The `escheat_due_date` is the trigger date advanced by the
        statute's dormancy period in calendar years, and the
        `due_diligence_start_date` is 120 days before the due date."
        PRD §3.9: "an `account_id` is present when the `subject_type` is
        `RETAINED_ASSET_ACCOUNT` and null when it is `CLAIM_PROCEEDS`".

        Approved 2026-04-10 under a 3-year dormancy statute: due 2029-04-10,
        due-diligence start 120 days earlier on 2028-12-11; the amount
        snapshots total_payable 25068493 with nothing paid.

        Design: Corner/entities/c_escheatment_case_computed_dates
        """
        ctx = setup_approved_claim(
            state="IL",
            face_amount_cents=25000000,
            beneficiaries=[],
            approve_clock="2026-04-10T00:00:00Z",
            policy_overrides={"policy_number": "P-COR-4"},
        )
        assert ctx["claim"]["total_payable_cents"] == 25068493
        assert ctx["claim"]["approved_at"] == "2026-04-10"

        cases = list_escheatment_cases({"claim_id": ctx["claim"]["id"]})
        assert len(cases) == 1, "Exactly one proceeds case is opened"
        case = cases[0]
        assert case["subject_type"] == "CLAIM_PROCEEDS"
        assert case["status"] == "MONITORING"
        assert case["account_id"] is None
        assert case["trigger_date"] == "2026-04-10"
        assert case["escheat_due_date"] == "2029-04-10"
        assert case["due_diligence_start_date"] == "2028-12-11"
        assert case["amount_cents"] == 25068493
