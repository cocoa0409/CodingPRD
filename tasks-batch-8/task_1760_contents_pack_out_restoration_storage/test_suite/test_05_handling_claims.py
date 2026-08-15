"""Handling claims: ACV vs RCV settlement variants, the settle cascade, the
appeal cycle, and segregation of duties (PRD §2.1, §3.6).
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_claims_adjuster_headers,
    setup_job_with_room, register_item, get_item,
    file_claim, submit_claim_for_review, approve_claim, transition_claim,
    setup_item_in_storage, get_vault,
)

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]
PM1 = TEST_USERS["pm1_headers"]
ADJ1 = TEST_USERS["adj1_headers"]
ADJ2 = TEST_USERS["adj2_headers"]

CLAIM_DATA = {"claim_type": "DAMAGE", "description": "Dropped during pack-out",
              "replacement_cost_cents": 100000, "item_age_years": 5}


def _settle_claim_on_job(policy_coverage_type, claim_number, barcode):
    """Job with the given coverage; one item; identical DAMAGE claim approved by
    adj-1 (filer pm-1). Returns the APPROVED claim."""
    job, room = setup_job_with_room(job_overrides={
        "claim_number": claim_number, "carrier_name": "Acme Mutual",
        "policy_coverage_type": policy_coverage_type})
    item = register_item(room["id"], barcode=barcode, description="Laptop",
                         item_category="ELECTRONICS", declared_value_cents=100000,
                         volume_cu_ft=2)
    claim = file_claim(item["id"], filer_headers=PM1, **CLAIM_DATA)
    submit_claim_for_review(claim["id"], headers=ADJ1)
    return approve_claim(claim["id"], headers=ADJ1)


class TestSettlementVariants:
    def test_acv_settlement_depreciates_by_age(self, api):
        """PRD §3.6: "Under the `ACV` variant, the settlement depreciates the
        replacement cost by age with a cap and a floor. The depreciation percentage
        is the item's `item_age_years` multiplied by 10 percent per year, capped at
        a maximum of 70 percent." and "In other words, the settlement takes the
        larger of the age-depreciated value and the 30-percent floor, and the
        result is rounded half-up once at the end to integer cents."
        PRD §3.6: "The `settlement_variant` is copied at that moment from the job's
        `policy_coverage_type`, resolved from the item through its room to the job,
        and `settlement_amount_cents` is computed per the variant."

        Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_rcv_divergence
        """
        claim = _settle_claim_on_job("ACV", "CLM-DV2A", "BC-DV2A")
        assert claim["settlement_variant"] == "ACV"
        # depreciation min(5*10, 70) = 50 -> 100000 * 50/100 = 50000;
        # floor 30000 does not bind.
        assert claim["settlement_amount_cents"] == 50000, (
            f"ACV settlement must be 50000, got {claim['settlement_amount_cents']}")

    def test_rcv_settlement_full_replacement_under_cap(self, api):
        """PRD §3.6: "Under the `RCV` variant, the settlement is the full
        replacement cost capped at 250000 cents — unless the item has any specialty
        referral in `QA_ACCEPTED` status, in which case the settlement is the full
        replacement cost uncapped."
        PRD §3.6: "Both variants produce integer cents; division uses exact
        rational arithmetic with a single half-up rounding at the end, and
        identical claim data yields different cents under the two variants."

        Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_rcv_divergence
        """
        claim = _settle_claim_on_job("RCV", "CLM-DV2B", "BC-DV2B")
        assert claim["settlement_variant"] == "RCV"
        # min(100000, 250000): cap applies (no QA_ACCEPTED referral) but does not bind.
        assert claim["settlement_amount_cents"] == 100000, (
            f"RCV settlement must be 100000, got {claim['settlement_amount_cents']}")


class TestClaimSettleCascade:
    def _setup(self):
        """ACV job; item (vol 25) IN_STORAGE at rate 100/cu ft; DAMAGE claim
        (replacement 50000, age 2) approved by adj-1 -> settlement 40000."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-TC2", "property_address": "12 Poplar Ave",
                           "policy_coverage_type": "ACV"},
            room_overrides={"name": "Basement", "room_type": "BASEMENT"},
            item_overrides={"barcode": "BC-TC2", "description": "Freezer",
                            "item_category": "APPLIANCE", "declared_value_cents": 50000,
                            "volume_cu_ft": 25},
            vault_overrides={"code": "V-TC2", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 5000, "monthly_rate_cents_per_cu_ft": 100})
        claim = file_claim(ctx["item"]["id"], filer_headers=PM1,
                           claim_type="DAMAGE", description="Crushed in vault",
                           replacement_cost_cents=50000, item_age_years=2)
        submit_claim_for_review(claim["id"], headers=ADJ1)
        ctx["claim"] = approve_claim(claim["id"], headers=ADJ1)
        return ctx

    def test_direct_settle_settles_claim_and_item(self, api):
        """PRD §3.6: "Either path moves the claim to the terminal `SETTLED` and
        cascades into the item: the item's `processing_status` becomes
        `CLAIM_SETTLED` from any non-terminal state, and if the item was
        `IN_STORAGE` its active placement is released with `release_reason`
        `CLAIM`, decrementing vault occupancy and recomputing provisional accrual
        and the job's `accrued_storage_total_cents`."

        Design: Difficulty/transitive_cascade/claim_settle_cascade_depth3
        """
        ctx = self._setup()
        claim = ctx["claim"]
        # depreciation min(2*10, 70) = 20 -> 50000 * 80/100 = 40000; floor 15000 not binding.
        assert claim["settlement_amount_cents"] == 40000, (
            f"precondition: approved at 40000, got {claim['settlement_amount_cents']}")

        settled = get_success_data(transition_claim(claim["id"], "SETTLE", headers=ADJ1))
        assert settled["status"] == "SETTLED"
        assert settled["settlement_amount_cents"] == 40000

        item_after = get_item(ctx["item"]["id"])
        assert item_after["processing_status"] == "CLAIM_SETTLED", (
            f"cascade link 1: item must be CLAIM_SETTLED, got {item_after['processing_status']}")

    def test_direct_settle_releases_placement_with_claim_reason(self, api):
        """PRD §3.6: "if the item was `IN_STORAGE` its active placement is released
        with `release_reason` `CLAIM`, decrementing vault occupancy and recomputing
        provisional accrual and the job's `accrued_storage_total_cents`."

        Design: Difficulty/transitive_cascade/claim_settle_cascade_depth3
        """
        ctx = self._setup()
        get_success_data(transition_claim(ctx["claim"]["id"], "SETTLE", headers=ADJ1))

        placements = get_success_data(api.list_item_placements(ctx["item"]["id"], TECH))
        assert len(placements) == 1
        assert placements[0]["status"] == "RELEASED", (
            f"cascade link 2: placement RELEASED, got {placements[0]['status']}")
        assert placements[0]["release_reason"] == "CLAIM", (
            f"cascade link 2: reason CLAIM, got {placements[0]['release_reason']}")

        vault_after = get_vault(ctx["vault"]["id"])
        assert vault_after["occupied_cu_ft"] == 0, (
            f"cascade link 3: occupancy decremented to 0, got {vault_after['occupied_cu_ft']}")


class TestClaimReviewCycleAndSoD:
    def test_claim_appeal_cycle_reopens_review(self, api):
        """PRD §3.6: "Denial moves the claim to `DENIED`, and an appeal returns it
        from `DENIED` to `UNDER_REVIEW`; the appeal cycle may repeat."
        PRD §3.6: "The claim starts `FILED` with `settlement_variant` and
        `settlement_amount_cents` null and `credited_invoice_id` null."

        Design: Corner/state_machines/claim_appeal_cycle_reopens_review
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-SM4", "property_address": "52 Spruce St"},
            room_overrides={"name": "Den"})
        item = register_item(room["id"], barcode="BC-SM4", description="TV",
                             item_category="ELECTRONICS", declared_value_cents=60000,
                             volume_cu_ft=4)
        claim = file_claim(item["id"], filer_headers=PM1,
                           claim_type="DAMAGE", description="Screen cracked",
                           replacement_cost_cents=60000, item_age_years=3)
        submit_claim_for_review(claim["id"], headers=ADJ1)
        denied = get_success_data(transition_claim(claim["id"], "DENY", headers=ADJ1))
        assert denied["status"] == "DENIED"

        appealed = get_success_data(transition_claim(claim["id"], "APPEAL", headers=ADJ2))
        assert appealed["status"] == "UNDER_REVIEW", (
            f"APPEAL reopens review, got {appealed['status']}")
        assert appealed["settlement_amount_cents"] is None, (
            "no approval has occurred, so the settlement stays null")

    def test_claim_filer_cannot_approve_own_claim(self, api):
        """PRD §3.6: "Approval and denial both require the acting adjuster's
        identity to differ from `filed_by_user_id` — a self-decided claim is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/claim_filer_cannot_approve_own_claim
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-RB3", "property_address": "90 Oak St"},
            room_overrides={"name": "Den"})
        item = register_item(room["id"], barcode="BC-RB3", description="Console",
                             item_category="ELECTRONICS", declared_value_cents=40000,
                             volume_cu_ft=3)
        claim = file_claim(item["id"], filer_headers=PM1,
                           claim_type="DAMAGE", description="Cracked casing",
                           replacement_cost_cents=40000, item_age_years=2)
        assert claim["filed_by_user_id"] == "pm-1"
        submit_claim_for_review(claim["id"], headers=ADJ1)

        res = api.transition_handling_claim(
            claim["id"], {"action": "APPROVE"}, make_claims_adjuster_headers("pm-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        claims = get_success_data(api.list_item_claims(item["id"], ADJ1))
        assert claims[0]["status"] == "UNDER_REVIEW", (
            f"the self-approval must be rejected, got {claims[0]['status']}")
        assert claims[0]["settlement_amount_cents"] is None
