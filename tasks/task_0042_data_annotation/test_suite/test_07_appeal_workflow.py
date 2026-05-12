"""Appeal workflow: submission, arbiter assignment, decide UPHOLD/REJECT,
salary adjustments. Covers PRD §3.6, §3.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    arbitrate_payload,
    assign_arbiter,
    create_appeal_payload,
    create_expert_annotator,
    create_junior_annotator,
    create_payroll_period,
    create_senior_annotator,
    decide_appeal,
    decide_appeal_payload,
    finalize_inspection,
    find_ledger_entries,
    get_appeal,
    get_package,
    get_success_data,
    list_ledger,
    lock_payroll,
    make_annotator_headers,
    setup_inspecting_package,
    setup_rejected_package_via_arbitration,
    submit_appeal,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.6, §3.8 -- Arbitration and salary on REJECT
# =========================================================================
class TestArbitrationReject:

    def test_arbitrate_reject_books_flat_penalty(self, api):
        """PRD §3.6: 'When an arbiter rejects a package -- moving it
        from ARBITRATING to REJECTED -- the annotator receives no
        piece-rate credit and is debited a flat 200 cents in a PENALTY
        entry.'

        Claim: arbitrate REJECT writes a PENALTY of -200 cents, no
        PIECE_RATE for the package.
        """
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg = state["package"]
        annotator = state["annotator"]

        # Read the penalty via a wide period that covers the package.
        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        penalties = find_ledger_entries(
            entries, package_id=pkg["id"], kind="PENALTY",
            annotator_id=annotator["id"],
        )
        assert len(penalties) == 1
        assert penalties[0]["gross_amount_cents"] == -200
        # No piece-rate for the rejected package.
        prs = find_ledger_entries(entries, package_id=pkg["id"], kind="PIECE_RATE")
        assert prs == []

    def test_arbiter_must_not_be_owner(self, api):
        """PRD §3.8: 'Only an annotator whose tier is EXPERT and who is
        not the package owner may arbitrate; a violation of either rule
        is rejected with ERR_ARBITER_IS_OWNER.'

        Claim: an EXPERT who is the owner attempting to arbitrate ->
        403 ERR_ARBITER_IS_OWNER.
        """
        # Build a package whose owner is itself an EXPERT, then drive it
        # to ARBITRATING via the rework cap.
        owner = create_expert_annotator()
        # Need a separate EXPERT to satisfy select_arbiter eligibility,
        # otherwise the third-fail transition yields ERR_NO_ELIGIBLE_ARBITER.
        create_expert_annotator()
        # Seed 50 PASS history on the to-be-owner EXPERT so they
        # remain at EXPERT tier (PRD §3.2 EXPERT requires lifetime
        # submitted >= 50). The seed's EASY projects let the annotator
        # build the required submitted_count without hitting the
        # priority-7 tier check on the test's HARD package. After the
        # 3 FAILs in the test body, the annotator's rolling rate drops
        # but stays well above the 0.70 suspension threshold (47/50 =
        # 0.94 lifetime; 17/20 = 0.85 rolling, both > 0.70).
        state = setup_inspecting_package(
            annotator_score=98.0, package_size=10, difficulty="HARD",
            seed_pass_count=50,
        )
        # Replace state["annotator"] with the explicit owner created above
        # is not possible without re-walking. Instead use the natural
        # state["annotator"] (an EXPERT minted by setup) and try to
        # arbitrate as that same annotator.
        owner = state["annotator"]
        pkg = state["package"]
        insp = state["inspection"]
        # Drive to ARBITRATING.
        finalize_inspection(
            pkg["id"], insp["id"], "FAIL",
            defects_found=insp["sample_size"],
        )
        # rework cycles
        get_success_data(api_client.rework_claim(
            pkg["id"], make_annotator_headers(owner["id"])
        ))
        from test_helpers import submit_labels, start_inspection
        submit_labels(pkg["id"], owner["id"], item_count=pkg["item_count"])
        i2 = start_inspection(pkg["id"])
        finalize_inspection(
            pkg["id"], i2["id"], "FAIL", defects_found=i2["sample_size"],
        )
        get_success_data(api_client.rework_claim(
            pkg["id"], make_annotator_headers(owner["id"])
        ))
        submit_labels(pkg["id"], owner["id"], item_count=pkg["item_count"])
        i3 = start_inspection(pkg["id"])
        finalize_inspection(
            pkg["id"], i3["id"], "FAIL", defects_found=i3["sample_size"],
        )
        # Owner attempts to arbitrate his own package.
        res = api.arbitrate_package(
            pkg["id"], arbitrate_payload(decision="APPROVE"),
            make_annotator_headers(owner["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ARBITER_IS_OWNER.value)


# =========================================================================
# §3.8 -- Appeal workflow happy path
# =========================================================================
class TestAppealLifecycle:

    def test_appeal_submitted_in_initial_state(self, api):
        """PRD §3.8: 'A submitting annotator opens an Appeal against a
        finalised inspection by referencing the inspection_id and
        supplying a free-text reason; the appeal enters SUBMITTED.'

        Claim: POST /task-packages/{id}/appeals returns 201 with
        status=SUBMITTED.
        """
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg = state["package"]
        annotator = state["annotator"]
        insp = state["inspection"]
        # File appeal as the package's submitter.
        res = api.create_appeal(
            pkg["id"],
            create_appeal_payload(
                inspection_id=insp["id"], reason="Disputed defects.",
            ),
            make_annotator_headers(annotator["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SUBMITTED"
        assert data["package_id"] == pkg["id"]
        assert data["inspection_id"] == insp["id"]
        assert data["annotator_id"] == annotator["id"]

    def test_assign_arbiter_moves_to_under_review(
        self, api, project_manager_headers,
    ):
        """PRD §3.8: 'A ProjectManager advances it to UNDER_REVIEW by
        assigning an arbiter.'

        Claim: POST /appeals/{id}/assign-arbiter sets arbiter_id and
        moves status to UNDER_REVIEW.
        """
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg, insp, owner = state["package"], state["inspection"], state["annotator"]
        # An eligible additional arbiter is needed (state["arbiter"] is
        # already an EXPERT).
        appeal = submit_appeal(
            pkg["id"], insp["id"], owner["id"],
        )
        res = api.assign_arbiter(appeal["id"], project_manager_headers)
        data = validate_success(res)
        assert data["status"] == "UNDER_REVIEW"
        assert data.get("arbiter_id") not in (None, "")

    def test_decide_uphold_inserts_adjustment_upheld(
        self, api, project_manager_headers,
    ):
        """PRD §3.8: 'An upheld appeal sets the originating
        QualityInspection.outcome to DISPUTED to record the override,
        inserts an ADJUSTMENT_UPHELD entry whose magnitude offsets the
        penalty entries booked from that inspection (the global
        invariant: for that inspection, the sum of penalty debits and
        the matching upholding-adjustment credits is zero).'

        Claim: after UPHOLD on a previously-rejected package, an
        ADJUSTMENT_UPHELD entry exists with magnitude exactly cancelling
        the previous PENALTY (-200 + 200 = 0).
        """
        # We need a separate EXPERT to be the arbiter (not the
        # appellant). Create one before triggering arbitration so that
        # at decide-time the candidate set is non-empty (state["arbiter"]
        # was the prior arbiter and is excluded from this appeal flow
        # only if the candidate set has another candidate).
        create_expert_annotator()
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg, insp, owner = state["package"], state["inspection"], state["annotator"]
        appeal = submit_appeal(pkg["id"], insp["id"], owner["id"])
        api.assign_arbiter(appeal["id"], project_manager_headers)
        appeal = get_appeal(appeal["id"])
        arbiter_id = appeal["arbiter_id"]
        decide_appeal(appeal["id"], arbiter_id, "UPHOLD")

        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        adj = find_ledger_entries(
            entries, package_id=pkg["id"], kind="ADJUSTMENT_UPHELD",
        )
        pen = find_ledger_entries(
            entries, package_id=pkg["id"], kind="PENALTY",
        )
        assert len(adj) == 1
        assert len(pen) == 1
        assert adj[0]["gross_amount_cents"] == -pen[0]["gross_amount_cents"]
        assert adj[0]["gross_amount_cents"] + pen[0]["gross_amount_cents"] == 0

    def test_decide_reject_books_unfounded_penalty(
        self, api, project_manager_headers,
    ):
        """PRD §3.6: 'When an arbiter rejects an appeal as unfounded,
        the appellant is debited a flat 100 cents in an
        ADJUSTMENT_REJECTED entry'.

        Claim: REJECT on appeal writes an ADJUSTMENT_REJECTED of -100.
        """
        create_expert_annotator()
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg, insp, owner = state["package"], state["inspection"], state["annotator"]
        appeal = submit_appeal(pkg["id"], insp["id"], owner["id"])
        api.assign_arbiter(appeal["id"], project_manager_headers)
        appeal = get_appeal(appeal["id"])
        decide_appeal(appeal["id"], appeal["arbiter_id"], "REJECT")

        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        adj_rej = find_ledger_entries(
            entries, annotator_id=owner["id"],
            kind="ADJUSTMENT_REJECTED",
        )
        assert len(adj_rej) == 1
        assert adj_rej[0]["gross_amount_cents"] == -100

    def test_non_assigned_arbiter_cannot_decide(
        self, api, project_manager_headers,
    ):
        """PRD §3.8: 'The assigned arbiter -- an annotator whose id
        equals appeal.arbiter_id (else ERR_NOT_ASSIGNED_ARBITER) --
        decides the appeal as UPHOLD or REJECT.'

        Claim: a different EXPERT (not the assigned arbiter) decides
        -> 403 ERR_NOT_ASSIGNED_ARBITER.
        """
        create_expert_annotator()
        state = setup_rejected_package_via_arbitration(package_size=10)
        pkg, insp, owner = state["package"], state["inspection"], state["annotator"]
        appeal = submit_appeal(pkg["id"], insp["id"], owner["id"])
        api.assign_arbiter(appeal["id"], project_manager_headers)
        # Build an additional EXPERT (not the assigned arbiter).
        other_expert = create_expert_annotator()
        res = api.decide_appeal(
            appeal["id"],
            decide_appeal_payload(decision="UPHOLD"),
            make_annotator_headers(other_expert["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_ARBITER.value)
