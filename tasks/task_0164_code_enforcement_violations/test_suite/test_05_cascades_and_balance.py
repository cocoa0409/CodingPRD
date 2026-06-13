"""Cross-entity cascades and conserved-quantity invariants: notice issuance and
abatement completion driving fine creation -> balance -> posture recomputation, and
the dismiss-waives / lien-release compensating invariants on the case balance.

PRD coverage: §2.5 (compound posture recomputed after every child mutation), §3.4
(issuance creates the citation fine and flips posture to ACTIVE), §3.9 (dismissal
waives the fine and restores the balance), §3.10/§3.11 (abatement-cost ledger line
and balance), §3.12 (lien recording/release effects on fines and balance).
"""
from test_helpers import validate_success, validate_paginated
from test_helpers import fixtures as F


OFFICER = F.OFFICER
CLERK = F.CLERK


# ==========================================================================
# Difficulty: transitive_cascade / notice_issue_cascade_depth2_posture_active
# ==========================================================================
def test_case_is_intake_before_notice_issuance(api):
    """PRD §2.5: "A newly opened case starts at `INTAKE`"
    PRD §3.2: "The new case starts with `posture` of `INTAKE`, an
    `outstanding_balance_cents` of zero"

    Design: Difficulty/transitive_cascade/notice_issue_cascade_depth2_posture_active
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    _owner, _prop, case, _insp = F.setup_case_with_substantiation()
    got = validate_success(api.get_case(case["id"], OFFICER))
    assert got["posture"] == "INTAKE", f"expected INTAKE before issuance, got {got['posture']}"


def test_notice_issuance_creates_citation_fine_and_flips_posture(api):
    """PRD §3.4: "It creates the citation ledger line (a `Fine` with `source_kind`
    of `CITATION` and `settlement_status` of `OPEN`) sized by the base of the
    accrual formula. Finally it recomputes the parent case's posture, advancing it
    from `INTAKE` to `ACTIVE`, recomputes `outstanding_balance_cents`, and increments
    the case's `version` by one."

    Design: Difficulty/transitive_cascade/notice_issue_cascade_depth2_posture_active
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    _owner, _prop, case, insp = F.setup_case_with_substantiation()
    notice = F.issue_notice(case["id"], insp["id"], "MAJOR")

    # Link A: a CITATION fine of 20000 exists on the notice.
    fines, _meta = validate_paginated(api.list_notice_fines(notice["id"], OFFICER))
    citation = [f for f in fines if f["source_kind"] == "CITATION"]
    assert len(citation) == 1, f"expected one CITATION fine, got {len(citation)}"
    assert citation[0]["assessed_cents"] == 20000, (
        f"expected citation assessed 20000, got {citation[0]['assessed_cents']}"
    )

    # Link B: balance reflects the fine and posture flips to ACTIVE.
    got = validate_success(api.get_case(case["id"], OFFICER))
    assert got["outstanding_balance_cents"] == 20000, (
        f"expected balance 20000, got {got['outstanding_balance_cents']}"
    )
    assert got["posture"] == "ACTIVE", f"expected ACTIVE after issuance, got {got['posture']}"


# ==========================================================================
# Difficulty: transitive_cascade / abatement_complete_cascade_depth3
# ==========================================================================
def test_abatement_completion_creates_fine_and_raises_balance(api):
    """PRD §3.11: "On completion the order moves to `COMPLETED` and the system
    creates an abatement-cost ledger line: a `Fine` with `source_kind` of
    `ABATEMENT_COST`, `assessed_cents` equal to the supplied `actual_cost_cents`,
    and `settlement_status` of `OPEN`, attached to the case's most recent `UPHELD`
    or `OVERDUE` notice. The case's `outstanding_balance_cents` and posture are then
    recomputed with the abatement cost added."

    Design: Difficulty/transitive_cascade/abatement_complete_cascade_depth3
    """
    # PRD §3.11: the abatement-cost fine attaches to the case's most recent UPHELD or
    # OVERDUE notice, so drive the notice OVERDUE before completing the abatement.
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z",
        overdue_clock="2026-01-25T00:00:00Z",
        occupancy="VACANT",
    )
    case_id = ctx["case"]["id"]
    notice_id = ctx["notice"]["id"]
    order = F.complete_abatement(case_id, "BOARD_UP", actual_cost_cents=30000)
    assert order["status"] == "COMPLETED", f"expected COMPLETED, got {order['status']}"

    # Link B: an ABATEMENT_COST fine of 30000 exists on the notice.
    fines, _meta = validate_paginated(api.list_notice_fines(notice_id, OFFICER))
    abatement = [f for f in fines if f["source_kind"] == "ABATEMENT_COST"]
    assert len(abatement) == 1, f"expected one ABATEMENT_COST fine, got {len(abatement)}"
    assert abatement[0]["assessed_cents"] == 30000, (
        f"expected abatement assessed 30000, got {abatement[0]['assessed_cents']}"
    )

    # Link C/D: balance = 25000 provisional citation (10 days overdue) + 30000
    # abatement; posture ACTIVE (notice OVERDUE).
    got = validate_success(api.get_case(case_id, CLERK))
    assert got["outstanding_balance_cents"] == 55000, (
        f"expected balance 55000, got {got['outstanding_balance_cents']}"
    )
    assert got["posture"] == "ACTIVE", f"expected ACTIVE, got {got['posture']}"


def test_abatement_cost_fine_attaches_open_to_the_notice(api):
    """PRD §3.11: "the system creates an abatement-cost ledger line: a `Fine` with
    `source_kind` of `ABATEMENT_COST`, `assessed_cents` equal to the supplied
    `actual_cost_cents`, and `settlement_status` of `OPEN`, attached to the case's
    most recent `UPHELD` or `OVERDUE` notice."

    Design: Difficulty/transitive_cascade/abatement_complete_cascade_depth3
    """
    # Drive the notice OVERDUE first so the abatement fine attaches to it.
    ctx = F.setup_overdue_notice(
        issue_clock="2026-01-01T00:00:00Z",
        overdue_clock="2026-01-25T00:00:00Z",
        occupancy="VACANT",
    )
    case_id = ctx["case"]["id"]
    notice_id = ctx["notice"]["id"]
    F.complete_abatement(case_id, "BOARD_UP", actual_cost_cents=30000)

    fines, _meta = validate_paginated(api.list_notice_fines(notice_id, CLERK))
    abatement = [f for f in fines if f["source_kind"] == "ABATEMENT_COST"]
    assert len(abatement) == 1, f"expected one ABATEMENT_COST fine on the notice, got {len(abatement)}"
    assert abatement[0]["settlement_status"] == "OPEN", (
        f"expected the abatement fine OPEN, got {abatement[0]['settlement_status']}"
    )
    assert abatement[0]["assessed_cents"] == 30000, (
        f"expected assessed 30000, got {abatement[0]['assessed_cents']}"
    )


# ==========================================================================
# Difficulty: compensating_invariant / dismiss_waives_fine_restores_outstanding_balance
# ==========================================================================
def test_dismissal_waives_fine_and_restores_balance(api):
    """PRD §3.9: "When a hearing is dismissed, the notice goes from `CONTESTED` to
    `DISMISSED`. This is a compensating outcome: the citation fine's
    `settlement_status` is set to `WAIVED`, which removes this notice's fine from the
    outstanding balance, and `fine_total_cents` is frozen to zero. The case's
    `outstanding_balance_cents` is recomputed with that debit removed"

    Design: Difficulty/compensating_invariant/dismiss_waives_fine_restores_outstanding_balance
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner, _prop, case, insp = F.setup_case_with_substantiation()
    bal_before = validate_success(api.get_case(case["id"], CLERK))["outstanding_balance_cents"]
    assert bal_before == 0, f"expected pre-issue balance 0, got {bal_before}"

    notice = F.issue_notice(case["id"], insp["id"], "MAJOR")
    hearing = F.contest_notice(notice["id"], owner["id"], "2026-01-10T00:00:00Z")
    F.set_clock("2026-01-10T00:00:00Z")
    F.decide_hearing(hearing["id"], "DISMISSED")

    notice_after = validate_success(api.get_notice(notice["id"], OFFICER))
    assert notice_after["status"] == "DISMISSED", (
        f"expected DISMISSED, got {notice_after['status']}"
    )
    fines, _meta = validate_paginated(api.list_notice_fines(notice["id"], CLERK))
    citation = [f for f in fines if f["source_kind"] == "CITATION"]
    assert citation and citation[0]["settlement_status"] == "WAIVED", (
        f"expected citation WAIVED, got {citation and citation[0]['settlement_status']}"
    )

    bal_after = validate_success(api.get_case(case["id"], CLERK))["outstanding_balance_cents"]
    assert bal_after == 0, f"expected balance restored to 0, got {bal_after}"


def test_dismissal_freezes_notice_fine_total_to_zero(api):
    """PRD §3.9: "the citation fine's `settlement_status` is set to `WAIVED`, which
    removes this notice's fine from the outstanding balance, and `fine_total_cents`
    is frozen to zero."

    Design: Difficulty/compensating_invariant/dismiss_waives_fine_restores_outstanding_balance
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner, _prop, case, insp = F.setup_case_with_substantiation()
    notice = F.issue_notice(case["id"], insp["id"], "MAJOR")
    hearing = F.contest_notice(notice["id"], owner["id"], "2026-01-10T00:00:00Z")
    F.set_clock("2026-01-10T00:00:00Z")
    F.decide_hearing(hearing["id"], "DISMISSED")

    notice_after = validate_success(api.get_notice(notice["id"], OFFICER))
    assert notice_after["status"] == "DISMISSED", f"expected DISMISSED, got {notice_after['status']}"
    assert notice_after["fine_total_cents"] == 0, (
        f"expected fine_total frozen to 0, got {notice_after['fine_total_cents']}"
    )


# ==========================================================================
# Difficulty: compensating_invariant / lien_release_conserves_payment_coverage
# ==========================================================================
def test_lien_release_after_full_payment_zeroes_balance(api):
    """PRD §3.12: "A `RECORDED` lien is released by a finance clerk once it is paid
    in full — that is, once the case's `payments_applied_cents` is at least the
    lien's `total_cents` ... Releasing moves the lien to `RELEASED`, settles all
    remaining `OPEN` citation and abatement-cost fines on the case to `SETTLED`, and
    recomputes the case's `outstanding_balance_cents` to zero along with its posture."

    Design: Difficulty/compensating_invariant/lien_release_conserves_payment_coverage
    """
    ctx = F.setup_recorded_lien(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    lien = ctx["lien"]
    # principal 25000 (10 days overdue) + admin_fee 1250 (0.05) = 26250
    assert lien["total_cents"] == 26250, f"expected lien total 26250, got {lien['total_cents']}"

    paid = F.post_payment(ctx["case"]["id"], 26250)
    assert paid["payments_applied_cents"] == 26250, (
        f"expected payments_applied 26250 (== lien total), got {paid['payments_applied_cents']}"
    )

    released = validate_success(api.release_lien(lien["id"], CLERK))
    assert released["status"] == "RELEASED", f"expected RELEASED, got {released['status']}"

    case_final = validate_success(api.get_case(ctx["case"]["id"], CLERK))
    assert case_final["outstanding_balance_cents"] == 0, (
        f"expected balance 0 after release, got {case_final['outstanding_balance_cents']}"
    )


def test_lien_release_settles_all_open_fines(api):
    """PRD §3.12: "Releasing moves the lien to `RELEASED`, settles all remaining
    `OPEN` citation and abatement-cost fines on the case to `SETTLED`, and recomputes
    the case's `outstanding_balance_cents` to zero along with its posture."

    Design: Difficulty/compensating_invariant/lien_release_conserves_payment_coverage
    """
    ctx = F.setup_recorded_lien(
        issue_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-25T00:00:00Z"
    )
    lien = ctx["lien"]
    notice_id = ctx["notice"]["id"]
    F.post_payment(ctx["case"]["id"], lien["total_cents"])
    validate_success(api.release_lien(lien["id"], CLERK))

    fines, _meta = validate_paginated(api.list_notice_fines(notice_id, CLERK))
    citation = [f for f in fines if f["source_kind"] == "CITATION"]
    assert citation, "expected a citation fine on the notice"
    assert all(f["settlement_status"] == "SETTLED" for f in citation), (
        f"expected all citation fines SETTLED, got {[f['settlement_status'] for f in citation]}"
    )
