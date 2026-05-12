"""Inspection outcome routing: PASS -> APPROVED, FAIL -> REWORK_PENDING,
rework cap exceeded -> ARBITRATING. Pricing: piece-rate, bonus, penalty.
Covers PRD §3.4, §3.6, §2.6 (precision)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_expert_annotator,
    create_junior_annotator,
    create_senior_annotator,
    finalize_inspection,
    finalize_inspection_payload,
    find_audit_entries,
    find_external_events,
    find_ledger_entries,
    get_package,
    list_audit,
    list_external,
    make_annotator_headers,
    setup_in_progress_package,
    setup_inspecting_package,
    setup_payroll_with_one_approved_package,
    setup_submitted_package,
    start_inspection,
    submit_labels,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.4 -- PASS path
# =========================================================================
class TestInspectionPass:

    def test_pass_transitions_to_approved(self, api, qa_reviewer_headers):
        """PRD §3.4: 'When defects_found divided by sample_size is at
        most 0.10, the inspection's outcome resolves to PASS and the
        package transitions from INSPECTING to APPROVED.'

        Claim: PASS finalize -> package.status = APPROVED.
        """
        state = setup_inspecting_package(package_size=10)
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=0)
        pkg = get_package(pkg["id"])
        assert pkg["status"] == "APPROVED"

    def test_pass_writes_piece_rate_in_withheld(
        self, api, qa_reviewer_headers,
    ):
        """PRD §3.4: 'A piece-rate SalaryLedgerEntry is created (kind
        PIECE_RATE, settlement_state WITHHELD, signed gross_amount_cents
        computed by §3.6's piece-rate calculation).'

        Claim: after PASS finalize, a PIECE_RATE entry exists for the
        package with settlement_state == WITHHELD.
        """
        # Use the payroll fixture solely to read the ledger via /payroll-periods.
        state = setup_payroll_with_one_approved_package(
            package_size=10, unit_price_cents=100,
        )
        period = state["period"]
        # Before settle, entries are still WITHHELD.
        from test_helpers import list_ledger
        entries = list_ledger(period["id"])
        pr = find_ledger_entries(
            entries, package_id=state["package"]["id"], kind="PIECE_RATE",
        )
        assert len(pr) == 1, f"expected 1 PIECE_RATE entry, got {pr!r}"
        assert pr[0]["settlement_state"] == "WITHHELD"

    def test_pass_emits_im_and_storage_events(self, api):
        """PRD §3.4: 'An IM event of event_type package.approved and a
        STORAGE event of event_type package.approved are queued.'

        Claim: after PASS finalize, two ExternalEvent rows exist with
        event_type=='package.approved' (one IM, one STORAGE) for the
        package.
        """
        state = setup_inspecting_package(package_size=10)
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=0)
        events = list_external()
        per_pkg = find_external_events(
            events, event_type="package.approved", payload_ref_id=pkg["id"],
        )
        target_systems = {e["target_system"] for e in per_pkg}
        assert "IM" in target_systems, (
            f"expected IM event for package.approved, got {per_pkg!r}"
        )
        assert "STORAGE" in target_systems, (
            f"expected STORAGE event for package.approved, got {per_pkg!r}"
        )

    def test_pass_writes_status_change_audit_row(self, api):
        """PRD §3.4: 'An audit-log row of event_type STATUS_CHANGE
        records the transition.'
        PRD §2.7: 'Every state transition that touches a TaskPackage
        writes one AuditLog row of event_type equal to STATUS_CHANGE,
        with subject_kind set to TASK_PACKAGE, subject_id set to the
        package id, from_value set to the prior state name and to_value
        set to the new state name.'

        Claim: after PASS finalize, an AuditLog row exists with
        subject_kind=TASK_PACKAGE, subject_id=pkg.id,
        event_type=STATUS_CHANGE, from_value=INSPECTING, to_value=APPROVED.
        """
        state = setup_inspecting_package(package_size=10)
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=0)
        rows = list_audit(subject_kind="TASK_PACKAGE", subject_id=pkg["id"])
        approve_rows = [
            r for r in rows
            if r.get("event_type") == "STATUS_CHANGE"
            and r.get("to_value") == "APPROVED"
        ]
        assert approve_rows, (
            f"missing STATUS_CHANGE -> APPROVED audit row, got {rows!r}"
        )
        assert approve_rows[0]["from_value"] == "INSPECTING"


# =========================================================================
# §3.4 -- FAIL with rework available
# =========================================================================
class TestInspectionFailRework:

    def test_fail_transitions_to_rework_pending(self, api, qa_reviewer_headers):
        """PRD §3.4: 'If the package's rework_round plus 1 is at most 2
        (the maximum), the package transitions from INSPECTING to
        REWORK_PENDING: rework_round increments by 1 (this INSPECTING
        evaluation counts as a completed round)'.

        Claim: FAIL on a rework_round=0 package -> status REWORK_PENDING
        and rework_round == 1.

        Setup: seed prior PASS history so that the single FAIL we issue
        in the test body doesn't push rolling_pass_rate below 0.70 and
        trigger PRD §3.2's suspension cascade (which would revert the
        REWORK_PENDING package back to POOL).
        """
        state = setup_inspecting_package(package_size=10, seed_pass_count=10)
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(
            pkg["id"], insp["id"], "FAIL",
            defects_found=insp["sample_size"],
        )
        pkg = get_package(pkg["id"])
        assert pkg["status"] == "REWORK_PENDING"
        assert pkg["rework_round"] == 1


# =========================================================================
# §3.4 -- Rework cap exceeded -> ARBITRATING
# =========================================================================
class TestArbitrationOnRewordCap:

    def test_third_fail_routes_to_arbitrating(self, api, qa_reviewer_headers):
        """PRD §3.4: 'If rework_round plus 1 would exceed 2, the package
        transitions from INSPECTING to ARBITRATING instead: the just-
        finalised inspection's outcome is overwritten to DISPUTED to
        record the override, and an expert arbiter is selected by the
        rule in §3.8.'

        Claim: third consecutive FAIL drives the package into ARBITRATING.

        Setup: seed 17 PASS history so the 3 FAILs we issue keep the
        rolling pass rate at 17/20 = 0.85 >= 0.70 (PRD §3.2).
        """
        # We must also have at least one EXPERT-tier ACTIVE annotator who
        # is not the package owner so the arbiter selection succeeds.
        create_expert_annotator()  # eligible arbiter exists
        state = setup_inspecting_package(package_size=10, seed_pass_count=17)
        pkg, insp1 = state["package"], state["inspection"]
        annotator = state["annotator"]

        # Round 0 -> REWORK_PENDING
        finalize_inspection(
            pkg["id"], insp1["id"], "FAIL",
            defects_found=insp1["sample_size"],
        )
        # Rework cycle 1
        from test_helpers import (
            api_client as ac,
            get_success_data,
            start_inspection as si,
            submit_labels,
        )
        ac.rework_claim(
            pkg["id"], make_annotator_headers(annotator["id"]),
        )
        submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
        insp2 = si(pkg["id"])
        finalize_inspection(
            pkg["id"], insp2["id"], "FAIL",
            defects_found=insp2["sample_size"],
        )
        # Rework cycle 2 -> third FAIL
        ac.rework_claim(
            pkg["id"], make_annotator_headers(annotator["id"]),
        )
        submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
        insp3 = si(pkg["id"])
        finalize_inspection(
            pkg["id"], insp3["id"], "FAIL",
            defects_found=insp3["sample_size"],
        )
        pkg = get_package(pkg["id"])
        assert pkg["status"] == "ARBITRATING"


# =========================================================================
# §3.6 -- Piece-rate calculation (round per item, then sum)
# =========================================================================
class TestPieceRate:

    def test_easy_junior_piece_rate(self, api, qa_reviewer_headers):
        """PRD §3.6: 'A difficulty multiplier is applied -- 1.00 at EASY
        ... A tier multiplier is applied -- 0.80 at JUNIOR ... The
        per-item rate before rounding is the base unit price multiplied
        by the difficulty multiplier multiplied by the tier multiplier.
        The rounding order is pinned: each item's rate is rounded to
        integer cents first using round-half-up, and the package's
        gross_amount_cents is the rounded per-item value multiplied by
        item_count.'

        Claim: EASY (1.00) JUNIOR (0.80) with unit_price_cents=100 and
        item_count=10 -> per-item rate 80; gross = 80*10 = 800.
        """
        state = setup_payroll_with_one_approved_package(
            package_size=10, unit_price_cents=100, difficulty="EASY",
            annotator_score=70.0,
        )
        from test_helpers import list_ledger
        entries = list_ledger(state["period"]["id"])
        pr = find_ledger_entries(
            entries, package_id=state["package"]["id"], kind="PIECE_RATE",
        )
        assert len(pr) == 1
        assert pr[0]["gross_amount_cents"] == 800

    def test_round_per_item_pinned_order(self, api, qa_reviewer_headers):
        """PRD §3.6: 'The rounding order is pinned: each item's rate is
        rounded to integer cents first using round-half-up, and the
        package's gross_amount_cents is the rounded per-item value
        multiplied by item_count. This pinning is deliberate -- two
        identical inputs always produce the same ledger amount -- and it
        differs from the alternative of summing first and rounding once
        at the end.'

        Claim: with unit_price_cents=7, MEDIUM (1.5) SENIOR (1.00),
        item_count=10 (the PRD-mandated minimum package_size), per-item
        raw = 10.5 -> round_half_up = 11; gross = 11*10 = 110.
        (Sum-then-round would give round_half_up(10.5*10) = 105.)
        """
        state = setup_payroll_with_one_approved_package(
            package_size=10, unit_price_cents=7, difficulty="MEDIUM",
            annotator_score=85.0,
        )
        from test_helpers import list_ledger
        entries = list_ledger(state["period"]["id"])
        pr = find_ledger_entries(
            entries, package_id=state["package"]["id"], kind="PIECE_RATE",
        )
        assert len(pr) == 1
        assert pr[0]["gross_amount_cents"] == 110, (
            f"expected 110 (per-item-first), got {pr[0]['gross_amount_cents']}"
        )


# =========================================================================
# §3.6 -- Bonus and penalty
# =========================================================================
class TestBonusPenalty:

    def test_bonus_triggered_at_inclusive_band(
        self, api, qa_reviewer_headers,
    ):
        """PRD §3.6: 'When the package pass rate is at or above the
        target plus 0.05 (the bonus band), a SalaryLedgerEntry of kind
        BONUS is written with gross_amount_cents equal to the
        round-half-up of the gross piece-rate amount multiplied by 0.10;
        the comparison is inclusive, so a package pass rate exactly
        equal to the target plus 0.05 triggers the bonus.'

        Claim: JUNIOR EASY package_size=20, unit=100, target=0.85.
        defects_found=2 -> pass_rate=0.90 = target+0.05 (inclusive
        bonus boundary). The defect ratio is 2/20 = 0.10, exactly at
        the PASS-routing threshold so the outcome resolves to PASS.
        Gross piece-rate = round(100*1.00*0.80)*20 = 80*20 = 1600.
        Bonus = round_half_up(1600 * 0.10) = 160.
        """
        from test_helpers import (
            setup_inspecting_package,
            list_ledger,
            create_payroll_period,
            advance_clock,
            lock_payroll,
        )
        state = setup_inspecting_package(
            package_size=20, unit_price_cents=100,
            pass_rate_target=0.85, difficulty="EASY",
            annotator_score=70.0,
        )
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=2)
        # Open a wide period covering today; lock to view ledger.
        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        bonus = find_ledger_entries(
            entries, package_id=pkg["id"], kind="BONUS",
        )
        assert len(bonus) == 1
        assert bonus[0]["gross_amount_cents"] == 160

    def test_penalty_triggered_at_inclusive_band(
        self, api, qa_reviewer_headers,
    ):
        """PRD §3.6: 'When the package pass rate is at or below the
        target minus 0.10 (the penalty band), a SalaryLedgerEntry of
        kind PENALTY is written with gross_amount_cents equal to the
        negative of the round-half-up of the gross piece-rate amount
        multiplied by 0.20.'

        Claim: target=0.80, JUNIOR EASY unit=100 size=20, defects=4 ->
        pass_rate=0.80-0.20=0.60? Use defects_found = 4. pass_rate = 1 -
        4/20 = 0.80. We need <= 0.70 (target - 0.10). defects=6 ->
        pass_rate=0.70, exactly at the inclusive penalty boundary.
        Gross piece-rate = 80*20=1600; PENALTY = round(1600*0.20) = 320,
        signed -320.
        """
        from test_helpers import (
            setup_inspecting_package,
            list_ledger,
            create_payroll_period,
            advance_clock,
            lock_payroll,
        )
        state = setup_inspecting_package(
            package_size=20, unit_price_cents=100,
            pass_rate_target=0.80, difficulty="EASY",
            annotator_score=70.0,
        )
        pkg, insp = state["package"], state["inspection"]
        # PRD: PASS routes when defects/sample_size <= 0.10. defects=2,
        # sample_size=20 -> 0.10 -> PASS. To get pass_rate=0.70 the
        # finalize would have to be FAIL. The bonus/penalty entry per
        # PRD §3.6 is written 'Immediately after the PIECE_RATE entry is
        # written'. Piece-rate is only written on transition to APPROVED
        # (see PRD §3.4). Thus PENALTY for low pass_rate cannot fire
        # under the INSPECTING -> APPROVED branch when the rate is
        # actually 0.70 (which would route to REWORK_PENDING).
        # However the PRD §3.6 PENALTY rule is anchored against the band
        # (inclusive, target-0.10). To create a PASS finalization that
        # nevertheless lands in the penalty band, the target must be set
        # so that target-PENALTY_BAND >= MAX_DEFECT_RATIO inverse i.e.
        # the package_pass_rate >= 0.90 (the PASS threshold) AND <=
        # target-0.10. Set target=1.00, defects=2 -> pass_rate=0.90;
        # target-PENALTY_BAND = 0.90; 0.90 <= 0.90 -> PENALTY fires.
        #
        # We rebuild the scenario with target=1.00.
        state = setup_inspecting_package(
            package_size=20, unit_price_cents=100,
            pass_rate_target=1.00, difficulty="EASY",
            annotator_score=70.0,
        )
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=2)
        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        penalty = find_ledger_entries(
            entries, package_id=pkg["id"], kind="PENALTY",
        )
        assert len(penalty) == 1
        # PIECE_RATE gross = 80*20 = 1600; PENALTY = round(1600*0.20) =
        # 320; signed -320.
        assert penalty[0]["gross_amount_cents"] == -320

    def test_no_bonus_or_penalty_in_neutral_band(
        self, api, qa_reviewer_headers,
    ):
        """PRD §3.6: 'Otherwise no bonus or penalty entry is written.'

        Claim: target=0.80, pass_rate=0.85? actually 0.85 IS at the
        bonus boundary. We need a pass rate strictly between target-0.10
        and target+0.05. Use target=0.80, defects_found=2,
        sample_size=20 -> pass_rate=0.90 -- inside the bonus band (0.85
        <= 0.90), so it triggers bonus. Use defects_found=3,
        sample_size=20, target=0.90: pass_rate=0.85; band: target+0.05 =
        0.95, target-0.10 = 0.80; 0.80 < 0.85 < 0.95 -> neutral; no
        bonus, no penalty.
        """
        from test_helpers import (
            setup_inspecting_package,
            list_ledger,
            create_payroll_period,
            advance_clock,
            lock_payroll,
        )
        state = setup_inspecting_package(
            package_size=20, unit_price_cents=100,
            pass_rate_target=0.90, difficulty="EASY",
            annotator_score=70.0,
        )
        pkg, insp = state["package"], state["inspection"]
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=3)
        period = create_payroll_period(
            opens_at="2026-01-01T00:00:00.000Z",
            closes_at="2027-01-01T00:00:00.000Z",
            tax_rate=0.10,
        )
        advance_clock("2027-01-01T00:00:00.000Z")
        period = lock_payroll(period["id"])
        entries = list_ledger(period["id"])
        bonus = find_ledger_entries(entries, package_id=pkg["id"], kind="BONUS")
        penalty = find_ledger_entries(entries, package_id=pkg["id"], kind="PENALTY")
        assert bonus == []
        assert penalty == []
