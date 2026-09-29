"""One dossier scored under both review variants, and one withdrawal reviewed
on both effectiveness bases: the same stored facts produce two different
numbers, and both numbers are observable side by side.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import OFFICER_2_HEADERS, OFFICER_HEADERS, REVIEWER_2_HEADERS, REVIEWER_HEADERS
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _dossier_with_divergent_evidence(api):
    """A submitted dossier holding three read-across items and one in-vitro item.

    The listing carries a single ingredient with no data gap, so both review
    modes remain admissible against it.
    """
    bundle = X.registered_facility_with_listing(api)
    X.add_ingredient(
        api, bundle["listing_id"], bundle["agent"],
        F.ingredient_payload(concentration_pct=3.5000),
    )
    dossier = X.open_dossier(api, bundle["listing_id"], bundle["agent"])
    X.attach_items(api, dossier["id"], bundle["agent"], X.DIVERGENT_EVIDENCE)
    submitted = X.submit_dossier(api, dossier["id"], bundle["agent"])
    assert submitted["data_gap_present"] is False
    assert submitted["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
    assert submitted["revision_round"] == 1
    return bundle, submitted


def _items_of_type(api, substantiation_id, evidence_type):
    rows, _ = validate_paginated(
        api.list_review_items(
            substantiation_id, REVIEWER_HEADERS,
            {"limit": K.MAX_LIMIT, "evidence_type": evidence_type},
        )
    )
    return rows


class TestSubstantiationReviewVariantsOnOneDossier:
    """The FULL variant fails evidence the SCREENING variant would clear."""

    def test_full_review_discounts_read_across_and_rules_the_dossier_deficient(self, api):
        """Three board-certified read-across items and one qualified-assessor in-vitro
        item are worth 45.00 under FULL, which is below the inclusive pass mark, so the
        dossier is DEFICIENT and its listing's substantiation dimension fails.

        PRD: "First, every item whose `evidence_type` is `READ_ACROSS_ANALOG` has its value multiplied by 0.5 and the result rounded half up to two decimal places again — read-across evidence is worth half of what it claims once somebody actually reads it."
        PRD: "In either mode a score of **60.00 or more** rules the dossier `ADEQUATE` and anything below 60.00 rules it `DEFICIENT`; the pass mark is inclusive at the boundary."

        Design: Difficulty/dual_variant_calc/substantiation_full_deficient_then_screening_adequate_on_one_dossier
        """
        bundle, submitted = _dossier_with_divergent_evidence(api)

        decided = X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)

        assert decided["adequacy_score"] == 45.00
        assert decided["status"] == K.SUBSTANTIATION_STATUS_DEFICIENT
        assert decided["review_mode"] == K.REVIEW_MODE_FULL
        assert decided["full_reviewer_user_id"] == REVIEWER_HEADERS["X-User-ID"]
        assert decided["screening_reviewer_user_id"] is None

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATION_FAILED
        assert listing["marketable"] is False

    def test_full_contribution_records_the_discount_but_not_the_class_cap(self, api):
        """Each evidence item carries what it would be worth under either variant: the
        read-across items read 20.00 screening against 10.00 full, and the in-vitro item
        reads 15.00 under both because no discount touches it.

        PRD: "`full_contribution` holds the item's value after any read-across discount but **before** the per-class cap is applied, since the cap is a property of the group rather than of the item."

        Design: Difficulty/dual_variant_calc/substantiation_full_deficient_then_screening_adequate_on_one_dossier
        """
        _bundle, submitted = _dossier_with_divergent_evidence(api)
        X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)

        read_across = _items_of_type(api, submitted["id"], K.EVIDENCE_READ_ACROSS)
        assert len(read_across) == 3
        for item in read_across:
            assert item["screening_contribution"] == 20.00
            assert item["full_contribution"] == 10.00

        in_vitro = _items_of_type(api, submitted["id"], K.EVIDENCE_IN_VITRO)
        assert len(in_vitro) == 1
        assert in_vitro[0]["screening_contribution"] == 15.00
        assert in_vitro[0]["full_contribution"] == 15.00

    def test_resubmission_from_deficient_counts_a_second_revision_round(self, api):
        """The deficiency verdict opens the revision edge: resubmitting the very same
        evidence returns the dossier to SUBMITTED at revision_round 2 and puts the
        listing back under substantiation.

        PRD: "From `DEFICIENT` the sponsor may revise and resubmit, which is the `DEFICIENT → SUBMITTED` edge: it again requires at least one evidence item, again increments `revision_round`, and again drives the listing's `safety_status` back to `UNDER_SUBSTANTIATION`."

        Design: Difficulty/dual_variant_calc/substantiation_full_deficient_then_screening_adequate_on_one_dossier
        """
        bundle, submitted = _dossier_with_divergent_evidence(api)
        X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)

        resubmitted = X.submit_dossier(api, submitted["id"], bundle["agent"])

        assert resubmitted["status"] == K.SUBSTANTIATION_STATUS_SUBMITTED
        assert resubmitted["revision_round"] == 2
        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_UNDER_SUBSTANTIATION

    def test_screening_pass_after_a_full_failure_leaves_a_thirty_point_spread(self, api):
        """Scored a second time under SCREENING on identical evidence, the same dossier
        reads 75.00 and is ADEQUATE — a spread of exactly 30.00 against the earlier full
        score — and the latest decision is the one that governs the listing.

        PRD: "Because `review_mode` is caller-supplied, a dossier can legitimately be scored twice under different modes on identical evidence and produce two different values in `adequacy_score`."
        PRD: "Whichever decision came last is the one that governs the listing's `safety_status`."

        Design: Difficulty/dual_variant_calc/substantiation_full_deficient_then_screening_adequate_on_one_dossier
        """
        bundle, submitted = _dossier_with_divergent_evidence(api)
        full = X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)
        X.submit_dossier(api, submitted["id"], bundle["agent"])

        screening = X.decide_dossier(
            api, submitted["id"], K.REVIEW_MODE_SCREENING, REVIEWER_2_HEADERS
        )

        assert screening["adequacy_score"] == 75.00
        assert screening["status"] == K.SUBSTANTIATION_STATUS_ADEQUATE
        assert screening["review_mode"] == K.REVIEW_MODE_SCREENING
        assert screening["screening_reviewer_user_id"] == REVIEWER_2_HEADERS["X-User-ID"]
        assert screening["full_reviewer_user_id"] == REVIEWER_HEADERS["X-User-ID"]
        assert screening["adequacy_score"] - full["adequacy_score"] == 30.00

        listing = X.read_listing(api, bundle["listing_id"])
        assert listing["safety_status"] == K.SAFETY_STATUS_SUBSTANTIATED

    def test_the_failed_review_never_moves_the_submission_dimension(self, api):
        """Neither verdict touches listing_status: the product stays exactly where it was
        in the submission dimension while its substantiation dimension swings from
        failed to substantiated.

        PRD: "A deficiency verdict does **not** touch `listing_status`."

        Design: Difficulty/dual_variant_calc/substantiation_full_deficient_then_screening_adequate_on_one_dossier
        """
        bundle, submitted = _dossier_with_divergent_evidence(api)

        X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_FULL, REVIEWER_HEADERS)
        assert X.read_listing(api, bundle["listing_id"])["listing_status"] == (
            K.LISTING_STATUS_DRAFT
        )

        X.submit_dossier(api, submitted["id"], bundle["agent"])
        X.decide_dossier(api, submitted["id"], K.REVIEW_MODE_SCREENING, REVIEWER_2_HEADERS)
        assert X.read_listing(api, bundle["listing_id"])["listing_status"] == (
            K.LISTING_STATUS_DRAFT
        )


_MIXED_RECOVERY_SPECS = [
    {"lot_code": "LOT-A", "ship_date": "2026-08-02", "delivery_date": "2026-08-04",
     "units_shipped": 600},
    {"lot_code": "LOT-B", "ship_date": "2026-08-02", "delivery_date": "2026-08-04",
     "units_shipped": 500},
    {"lot_code": "LOT-C", "ship_date": "2026-08-02", "delivery_date": "2026-08-04",
     "units_shipped": 400},
]


def _withdrawal_with_mixed_recovery(api):
    """1500 units shipped, 830 asserted or in transit, 700 actually verified.

    The plan is accepted by one officer so that a second officer is free to run
    the effectiveness reviews.
    """
    bundle = X.registered_facility_with_listing(
        api, listing_overrides={"lot_authorized_units": 2000}
    )
    records = X.create_distribution_records(
        api, bundle["listing_id"], bundle["agent"], _MIXED_RECOVERY_SPECS
    )
    recall = X.recall_with_accepted_plan(
        api, bundle["listing_id"], bundle["agent"], officer=OFFICER_HEADERS
    )
    withdrawal = X.open_withdrawal(api, recall, OFFICER_2_HEADERS)
    produced = X.produce_records(
        api, withdrawal["id"], [r["id"] for r in records], bundle["agent"]
    )
    assert produced["shipped_units_total"] == 1500
    agent = bundle["agent"]
    wid = withdrawal["id"]
    X.post_recovery(api, wid, records[0]["id"], 500, agent, K.ENTRY_KIND_REPORTED_RETURN)
    X.post_recovery(api, wid, records[1]["id"], 200, agent, K.ENTRY_KIND_REPORTED_DESTRUCTION)
    X.post_recovery(api, wid, records[2]["id"], 130, agent, K.ENTRY_KIND_IN_TRANSIT_RETURN)
    X.post_recovery(api, wid, records[0]["id"], 400, agent, K.ENTRY_KIND_VERIFIED_RETURN)
    X.post_recovery(api, wid, records[1]["id"], 200, agent, K.ENTRY_KIND_VERIFIED_RETURN)
    X.post_recovery(api, wid, records[2]["id"], 100, agent, K.ENTRY_KIND_VERIFIED_DESTRUCTION)
    return bundle, recall, withdrawal["id"], records


class TestWithdrawalEffectivenessBases:
    """The reported basis and the verified basis disagree on one withdrawal round."""

    def test_reported_basis_reports_progress_and_leaves_recall_and_listing_alone(self, api):
        """830 of 1500 units asserted or in transit is 55.33 percent, recorded under the
        interim marker, and the parent recall keeps executing with the listing's open
        recall still counted against it.

        PRD: "Under `REPORTED_BASIS` the review is a progress report and nothing more."
        PRD: "The verdict is recorded as the interim marker `INTERIM`, `effectiveness_reviewer_user_id` is set to the reviewing officer, the withdrawal takes `RECORDS_PRODUCED → INTERIM_REVIEWED` or self-loops on `INTERIM_REVIEWED`, and `verified_recovery_rate`, the parent recall and the listing are all left strictly untouched."

        Design: Difficulty/dual_variant_calc/withdrawal_reported_basis_versus_verified_basis_recovery_divergence
        """
        bundle, recall, withdrawal_id, _records = _withdrawal_with_mixed_recovery(api)

        reviewed = X.run_effectiveness_check(
            api, withdrawal_id, K.BASIS_REPORTED, OFFICER_2_HEADERS
        )

        assert reviewed["reported_recovered_units"] == 830
        assert reviewed["reported_recovery_rate"] == 55.33
        assert reviewed["verified_recovery_rate"] == 0.00
        assert reviewed["effectiveness_verdict"] == K.VERDICT_INTERIM
        assert reviewed["status"] == K.WITHDRAWAL_STATUS_INTERIM_REVIEWED
        assert reviewed["effectiveness_reviewer_user_id"] == OFFICER_2_HEADERS["X-User-ID"]
        assert reviewed["outstanding_units_total"] == 800

        assert X.read_recall(api, recall["id"])["status"] == K.RECALL_STATUS_EXECUTING
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 1

    def test_verified_basis_pins_the_credit_tier_to_the_provisional_rate(self, api):
        """700 verified of 1500 shipped is a provisional 46.67, which selects the six
        percent tier, shrinks the denominator to 1410 and lifts the final rate to 49.65 —
        still short of the effectiveness threshold.

        PRD: "Step two selects `unreachable_credit_pct` from the **provisional** rate: 0 when it is 90.00 or more, 3 when it is 80.00 or more, and 6 otherwise — the acknowledgement that the harder a recall is going, the more of the distribution chain is genuinely unreachable."
        PRD: "Three more cases: 1500 shipped with 830 units reported-or-in-transit and 700 verified gives a reported rate of 55.33 alongside a provisional 46.67, which selects 6 percent, a 90-unit credit, a 1410 denominator and a verified rate of 49.65 — `NOT_EFFECTIVE`, and a vivid illustration that the two bases disagree in both directions, the reported one inflated by unverified assertions and the verified one inflated by the denominator shrink."

        Design: Difficulty/dual_variant_calc/withdrawal_reported_basis_versus_verified_basis_recovery_divergence
        """
        _bundle, _recall, withdrawal_id, _records = _withdrawal_with_mixed_recovery(api)

        closed = X.run_effectiveness_check(
            api, withdrawal_id, K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert closed["verified_recovered_units"] == 700
        assert closed["provisional_verified_rate"] == 46.67
        assert closed["unreachable_credit_pct"] == 6
        assert closed["adjusted_denominator_units"] == 1410
        assert closed["verified_recovery_rate"] == 49.65
        assert closed["outstanding_units_total"] == 800
        assert closed["effectiveness_verdict"] == K.VERDICT_NOT_EFFECTIVE

    def test_an_ineffective_verified_review_extends_the_recall_without_closing_it(self, api):
        """The shortfall extends rather than closes: the round becomes ineffective, the
        recall is extended with no final rate stored, and the listing's open recall count
        is untouched.

        PRD: "An ineffective verified review takes the withdrawal to `EXTENDED_INEFFECTIVE` and the recall `EXECUTING → EXTENDED`, leaves `open_recall_count` unchanged because the recall is still open business, and writes no closure entry; the parties then open a further withdrawal round, which supersedes the ineffective one and returns the recall to `EXECUTING`, closing the execution cycle."

        Design: Difficulty/dual_variant_calc/withdrawal_reported_basis_versus_verified_basis_recovery_divergence
        """
        bundle, recall, withdrawal_id, _records = _withdrawal_with_mixed_recovery(api)

        closed = X.run_effectiveness_check(
            api, withdrawal_id, K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert closed["status"] == K.WITHDRAWAL_STATUS_EXTENDED_INEFFECTIVE
        parent = X.read_recall(api, recall["id"])
        assert parent["status"] == K.RECALL_STATUS_EXTENDED
        assert parent["effectiveness_rate_final"] is None
        assert X.read_listing(api, bundle["listing_id"])["open_recall_count"] == 1

    def test_both_bases_on_one_round_report_two_different_recovery_rates(self, api):
        """Run in sequence against one unchanged set of recovery entries, the reported
        basis reads 55.33 while the verified basis reads 49.65, and both figures remain
        legible on the same withdrawal.

        PRD: "The reported and in-transit buckets carry no such cap and may legitimately exceed what was shipped, which is one of the reasons the reported basis is only ever an interim view."

        Design: Difficulty/dual_variant_calc/withdrawal_reported_basis_versus_verified_basis_recovery_divergence
        """
        _bundle, _recall, withdrawal_id, _records = _withdrawal_with_mixed_recovery(api)

        interim = X.run_effectiveness_check(
            api, withdrawal_id, K.BASIS_REPORTED, OFFICER_2_HEADERS
        )
        final = X.run_effectiveness_check(
            api, withdrawal_id, K.BASIS_VERIFIED, OFFICER_2_HEADERS
        )

        assert interim["reported_recovery_rate"] == 55.33
        assert final["reported_recovery_rate"] == 55.33
        assert final["verified_recovery_rate"] == 49.65
        assert final["reported_recovery_rate"] != final["verified_recovery_rate"]
