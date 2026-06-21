"""Cross-aggregate cascades and conserved-quantity invariants: filing/liquidation/
grant reconcile bond liability and statement totals; release schedules onto the
monthly statement and matches the ISF.
"""
import test_helpers as h


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade
# ---------------------------------------------------------------------------
def test_psc_refund_cascade_desaturates_bond(api):
    """PRD §3.10: "increases the bond's `outstanding_liability_cents` by the `adjustment_cents`, which may auto-transition the bond either way between `ACTIVE` and `SATURATED`".
    PRD §3.1: "when a later liquidation or correction reconciliation drops its `outstanding_liability_cents` strictly below its `limit_cents`, a `SATURATED` bond returns to `ACTIVE`."

    Bond limit 54800 saturated by a liquidated entry (owed 54800). Granting a
    refund PSC (delta -200000 -> adjustment -10000) drops the entry's final to
    44800 and the bond's liability to 44800 (< limit), de-saturating it to ACTIVE.

    Design: Difficulty/transitive_cascade/psc_refund_cascade_entry_to_bond_liability_to_bond_desaturate
    """
    ctx = h.setup_liquidated_entry_with_psc(
        api, corrected_value_delta_cents=-200_000, bond_limit_cents=54_800
    )
    granted = h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    assert granted["adjustment_cents"] == -10000, granted
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["final_total_cents"] == 44800, entry
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.OFFICER))
    assert bond["outstanding_liability_cents"] == 44800, bond
    assert bond["status"] == "ACTIVE", bond


def test_psc_refund_cascade_lowers_entry_final_and_bond_liability(api):
    """PRD §3.10: "The grant then adds the `adjustment_cents` to the entry's `final_total_cents` and sets the entry's `total_duties_owed_cents` to that new final total; increases the bond's `outstanding_liability_cents` by the `adjustment_cents`".

    The depth-3 refund cascade's first two hops: a granted refund PSC (delta
    -200000 -> adjustment -10000) drops the entry's final_total_cents from 54800 to
    44800 and the bond's outstanding_liability_cents from 54800 to 44800.

    Design: Difficulty/transitive_cascade/psc_refund_cascade_entry_to_bond_liability_to_bond_desaturate
    """
    ctx = h.setup_liquidated_entry_with_psc(
        api, corrected_value_delta_cents=-200_000, bond_limit_cents=54_800
    )
    entry_before = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry_before["final_total_cents"] == 54800, entry_before
    h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["final_total_cents"] == 44800, entry
    assert entry["total_duties_owed_cents"] == 44800, entry
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.OFFICER))
    assert bond["outstanding_liability_cents"] == 44800, bond


def test_release_cascade_schedules_statement_and_matches_isf(api):
    """PRD §3.5: "the entry is scheduled onto the importer's open monthly statement".
    PRD §3.8: "The entry's `statement_id` is set to that statement, and the statement's `statement_total_cents` and `entry_count` are recomputed."
    PRD §3.5: "the referenced ISF transitions from `FILED` to the terminal `MATCHED` state, recording that the manifest has matched the security filing".

    Releasing a single general entry (owed 54800) creates the 2026-06 statement,
    sets statement_total_cents to 54800 and entry_count to 1, and matches the ISF.

    Design: Difficulty/transitive_cascade/release_cascade_entry_to_statement_schedule_to_total_recompute
    """
    ctx = h.setup_filed_entry(api)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    stmt_id = released["statement_id"]
    assert stmt_id, released
    stmt = h.validate_success(api.get_statement(stmt_id, h.OFFICER))
    assert stmt["statement_total_cents"] == 54800, stmt
    assert stmt["entry_count"] == 1, stmt
    isf = h.validate_success(api.get_isf(ctx["base"]["isf"]["id"], h.OFFICER))
    assert isf["status"] == "MATCHED", isf


def test_release_sets_entry_statement_id_nonnull(api):
    """PRD §3.8: "When an entry is released" ... "it is scheduled onto the open monthly statement for that importer and the calendar month of the current logical clock instant; if no such open statement exists, one is created. The entry's `statement_id` is set to that statement".

    A direct FILED->RELEASED transition populates the entry's statement_id.

    Design: Difficulty/transitive_cascade/release_cascade_entry_to_statement_schedule_to_total_recompute
    """
    ctx = h.setup_filed_entry(api)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["statement_id"] is not None, released


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant
# ---------------------------------------------------------------------------
def test_liquidation_keeps_bond_liability_equal_to_owed_total(api):
    """PRD §3.9: "Liquidation sets `total_duties_owed_cents` equal to `final_total_cents`" ... "The bond's `outstanding_liability_cents` is then increased by that delta".
    PRD §3.10: "The conserved invariant is that after the cascade the bond's
    `outstanding_liability_cents` equals the sum of its secured entries' owed totals."

    A CN USMCA apparel entry reserves 520 at filing; liquidation raises the owed
    total to 69735 (USMCA unverified) and the bond's liability must read exactly
    69735, not the stale 520.

    Design: Difficulty/compensating_invariant/liquidation_keeps_bond_liability_equal_to_sum_of_owed_totals
    """
    ctx = h.setup_liquidated_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 1, "preference_claim": "USMCA"}],
        country_of_origin="CN",
    )
    entry = ctx["entry"]
    assert entry["total_duties_owed_cents"] == 69735, entry
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.OFFICER))
    assert bond["outstanding_liability_cents"] == 69735, bond


def test_liquidation_bond_liability_reflects_final_not_provisional(api):
    """PRD §3.9: "The bond's `outstanding_liability_cents` is then increased by that delta".
    PRD §3.10: "The conserved invariant is that after the cascade the bond's
    `outstanding_liability_cents` equals the sum of its secured entries' owed totals."

    A general entry reserves 54800 at filing; after liquidation (final equals
    provisional here) the bond's liability still equals the single entry's owed
    total of 54800 — the invariant holds with no drift.

    Design: Difficulty/compensating_invariant/liquidation_keeps_bond_liability_equal_to_sum_of_owed_totals
    """
    ctx = h.setup_liquidated_entry(api)
    entry = ctx["entry"]
    assert entry["total_duties_owed_cents"] == 54800, entry
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.OFFICER))
    assert bond["outstanding_liability_cents"] == entry["total_duties_owed_cents"], bond
    assert bond["outstanding_liability_cents"] == 54800, bond


def test_psc_grant_keeps_statement_total_equal_to_owed_total(api):
    """PRD §3.10: "recomputes the monthly statement's `statement_total_cents`".
    PRD §3.8: "The `statement_total_cents` is the sum of `total_duties_owed_cents` over every entry whose `statement_id` equals this statement and whose `status` is `RELEASED` or `LIQUIDATED`".

    A liquidated entry owed 54800 sits on the 2026-06 statement; granting a
    +200000 delta PSC (adjustment +10000) raises both the entry owed total and the
    statement total to 64800.

    Design: Difficulty/compensating_invariant/psc_grant_keeps_statement_total_equal_to_sum_of_entry_owed
    """
    ctx = h.setup_liquidated_entry_with_psc(api, corrected_value_delta_cents=200_000)
    stmt_id = ctx["statement_id"]
    h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["total_duties_owed_cents"] == 64800, entry
    stmt = h.validate_success(api.get_statement(stmt_id, h.OFFICER))
    assert stmt["statement_total_cents"] == 64800, stmt


def test_psc_grant_statement_total_matches_entry_owed_after_cascade(api):
    """PRD §3.8: "The `statement_total_cents` is the sum of `total_duties_owed_cents` over every entry whose `statement_id` equals this statement and whose `status` is `RELEASED` or `LIQUIDATED`".
    PRD §3.10: "recomputes the monthly statement's `statement_total_cents`".

    After granting a +200000 delta PSC on the lone liquidated entry, the
    statement_total_cents equals the entry's new owed total (both 64800) — the
    conserved-quantity invariant holds.

    Design: Difficulty/compensating_invariant/psc_grant_keeps_statement_total_equal_to_sum_of_entry_owed
    """
    ctx = h.setup_liquidated_entry_with_psc(api, corrected_value_delta_cents=200_000)
    stmt_id = ctx["statement_id"]
    h.validate_success(api.grant_psc(ctx["psc"]["id"], h.OFFICER))
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    stmt = h.validate_success(api.get_statement(stmt_id, h.OFFICER))
    assert stmt["statement_total_cents"] == entry["total_duties_owed_cents"], (stmt, entry)
    assert stmt["statement_total_cents"] == 64800, stmt


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers / consistency_model
# ---------------------------------------------------------------------------
def test_occ_correct_version_psc_submission_succeeds(api):
    """PRD §2.7: "Submitting a post-summary correction or protest requires the field `expected_entry_version`, which must carry the `version` of the target entry as the client last observed it."
    PRD §3.10: "A new filing starts in `SUBMITTED` status with `adjustment_cents` of 0."

    A PSC carrying the liquidated entry's current version is accepted (201) and
    created in SUBMITTED status.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_psc_submission_succeeds
    """
    ctx = h.setup_liquidated_entry(api)
    resp = api.create_psc(
        h.create_psc_payload(ctx["entry"]["id"], ctx["entry_version"],
                             corrected_value_delta_cents=100_000),
        ctx["base"]["broker"],
    )
    psc = h.validate_success(resp, expected_status=201)
    assert psc["status"] == "SUBMITTED", psc


def test_version_increments_on_file_mutation(api):
    """PRD §2.4: "The `version` begins at 1 on creation and increments by exactly 1 on every mutation that the system records as a version bump".
    PRD §3.4: "sets the entry `status` to `FILED`, and increments the entry's version."

    A DRAFT entry created at version 1 reads version 2 after filing.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    base = h.setup_base(api)
    entry, _ = h.create_draft_entry_with_lines(api, base, [{}])
    assert entry["version"] == 1, entry
    filed = h.file_entry(api, entry["id"], base["broker"])
    assert filed["version"] == 2, filed


def test_liquidate_reconciles_statement_total_to_final_owed(api):
    """PRD §3.9: "Finally, the monthly statement the entry sits on has its `statement_total_cents` recomputed to reflect the entry's new owed total."

    A CN USMCA apparel entry (provisional 520) on the 2026-06 statement liquidates
    to owed 69735; the statement_total_cents recomputes from 520 to 69735.

    Design: Corner/cross_cutting_complexity_layers/liquidate_reconciles_statement_total_to_final_owed
    """
    ctx = h.setup_released_entry(
        api,
        lines=[{"hts_code": "6109100012", "customs_value_cents": 400_000,
                "quantity": 1, "preference_claim": "USMCA"}],
        country_of_origin="CN",
    )
    stmt_id = ctx["entry"]["statement_id"]
    liquidated = h.liquidate_entry(api, ctx["entry"]["id"], h.OFFICER)
    assert liquidated["total_duties_owed_cents"] == 69735, liquidated
    stmt = h.validate_success(api.get_statement(stmt_id, h.OFFICER))
    assert stmt["statement_total_cents"] == 69735, stmt


def test_immediate_visibility_bond_liability_after_file(api):
    """PRD §3.4: "the securing bond's `outstanding_liability_cents` is increased by the entry's `total_duties_owed_cents`".

    After filing a general ch94 cv 1000000 entry (provisional 54800), an immediate
    GET on the bond reflects outstanding_liability_cents == 54800 with no lag.

    Design: Corner/consistency_model/immediate_visibility_bond_liability_in_file_response
    """
    ctx = h.setup_filed_entry(api)
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.ADMIN))
    assert bond["outstanding_liability_cents"] == 54800, bond
