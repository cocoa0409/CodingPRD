"""Multi-hop cascades in which one call mutates entities several relationships away."""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Audit settlement: five hops from one settle call
# ---------------------------------------------------------------------------


def _engagement_ready_to_settle():
    """An audited quarter restated upward, with a seizure and a live review pending.

    The 2026Q2 report carries 6 250 000 of net regular sales, so the unbounded top tier
    rates it at 500 000, and the restatement to 6 562 500 recomputes it at 525 000.
    """
    context = setup_licensed_operation(
        minimum_guarantee_cents=4000000,
        required_advance_cents=1000000,
        central_licensing_flag=False,
    )
    licensee_id = context["licensee"]["id"]

    lines = simple_report_lines(context["authorization"]["id"], 6250000, units=12500)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    file_report(report["id"], licensee_id)
    context["report"] = accept_report(report["id"])

    # One counterfeit seizure is on file, worth 15 points on its own.
    create_seizure_factor(licensee_id)
    # And one design is mid-review, so a hold is observable three entities away.
    context = setup_submission_in_review(context=context)

    engagement = create_audit_engagement(context["agreement"]["id"], ["2026Q2"])
    begin_fieldwork(engagement["id"])
    context["engagement"] = issue_findings(
        engagement["id"], [audited_quarter("2026Q2", 6562500)]
    )
    return context


def test_settlement_restates_the_report_and_reverses_then_reapplies_the_ledger(api):
    """PRD §3.8: "the previously accepted posting is undone by adding the old
    `recoupment_applied_cents` back to `unrecouped_advance_cents`, subtracting it from
    `recouped_advance_cents` and subtracting the old `royalty_due_cents` from
    `cumulative_royalty_cents`; then steps two through six of the payable waterfall re-run
    with the adjusted royalty in place of the original"

    Design: Difficulty/transitive_cascade/audit_settlement_five_hop_cascade_to_review_hold
    """
    context = _engagement_ready_to_settle()
    engagement = context["engagement"]
    report_id = context["report"]["id"]

    assert engagement["recomputed_royalty_cents"] == 525000
    assert engagement["reported_royalty_cents"] == 500000
    assert engagement["underreported_royalty_cents"] == 25000
    assert engagement["underreport_rate_bps"] == 500
    assert engagement["cost_shift_applied"] is True
    assert engagement["audit_cost_recovery_cents"] == 750000
    assert engagement["interest_cents"] == 375
    assert engagement["recovery_assessed_cents"] == 775375
    assert engagement["findings_round"] == 1
    assert engagement["findings_quarter"] == "2026Q3"
    assert get_report(report_id)["status"] == "UNDER_AUDIT"

    settled = settle_engagement(engagement["id"])
    assert settled["status"] == "SETTLED"
    assert settled["settlement_basis"] == "FINDINGS"
    assert settled["settled_amount_cents"] == 775375
    assert settled["settled_by_user_id"] == "u_fin_2"

    adjusted = get_report(report_id)
    assert adjusted["status"] == "ADJUSTED"
    assert adjusted["adjusted_royalty_due_cents"] == 525000
    assert adjusted["recoupment_applied_cents"] == 525000

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["unrecouped_advance_cents"] == 475000
    assert agreement["recouped_advance_cents"] == 525000
    assert agreement["cumulative_royalty_cents"] == 525000
    # Three of the term's eight quarters have elapsed: 4 000 000 * 3 / 8 less 525 000.
    assert agreement["mg_accrued_shortfall_cents"] == 975000
    assert agreement["advance_paid_cents"] == 1000000
    assert_advance_ledger_conserved(agreement)


def test_settlement_reaches_the_risk_index_the_posture_and_the_review_hold(api):
    """PRD §3.8: "Fifth, because any agreement arriving in `PROBATION` or `FROZEN` holds
    reviews, every submission of those agreements whose `status` is `SUBMITTED`,
    `IN_REVIEW` or `SAMPLE_REQUESTED` has `review_hold` set to true."

    Design: Difficulty/transitive_cascade/audit_settlement_five_hop_cascade_to_review_hold
    """
    context = _engagement_ready_to_settle()
    submission_id = context["submission"]["id"]

    assert get_agreement(context["agreement"]["id"])["compliance_posture"] == "CLEAR"
    assert get_submission(submission_id)["review_hold"] is False

    settle_engagement(context["engagement"]["id"])

    licensee = get_licensee(context["licensee"]["id"])
    # The 15-point seizure plus the brand-new 20-point underreporting factor.
    assert licensee["compliance_risk_index"] == 35
    assert licensee["risk_index_as_of_quarter"] == "2026Q3"
    assert licensee["outstanding_recovery_cents"] == 775375

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["compliance_posture"] == "PROBATION"
    assert agreement["posture_as_of_quarter"] == "2026Q3"

    held = get_submission(submission_id)
    assert held["review_hold"] is True
    assert held["status"] == "IN_REVIEW"


# ---------------------------------------------------------------------------
# Group-licensing opt-out: three hops across three entity types
# ---------------------------------------------------------------------------


def _approved_sku_pinning_a_player_group_mark():
    club = create_club()
    player = create_player(club["id"], group_licensing_opt_in=True)
    league_mark = create_league_mark()
    group_mark = create_player_group_mark(player["id"], royalty_share_bps=1000)

    context = setup_licensed_operation()
    context = setup_approved_submission(
        mark_ids=[league_mark["id"], group_mark["id"]],
        context=context,
        product_name="Player Name Jersey",
        retail_price_cents=14999,
    )
    context["club"] = club
    context["player"] = player
    context["league_mark"] = league_mark
    context["group_mark"] = group_mark
    assert context["agreement"]["approved_sku_count"] == 1
    assert get_authorization(context["authorization"]["id"])["status"] == "AUTHORIZED"
    return context


def test_opting_out_withdraws_the_mark_revokes_the_sku_and_suspends_the_channel(api):
    """PRD §3.1: "Setting `opt_in` to false pulls the player out of the league
    group-licensing programme: every mark right belonging to that player whose
    `owner_type` is `PLAYER_GROUP` and whose `status` is `ACTIVE` or `RESTRICTED` moves to
    `WITHDRAWN`, which in turn revokes the approved submissions that pinned those marks and
    can suspend retailer authorizations, exactly as a manual withdrawal would."

    Design: Difficulty/transitive_cascade/player_group_optout_three_hop_cascade_to_authorization
    """
    context = _approved_sku_pinning_a_player_group_mark()

    player = set_group_licensing(context["player"]["id"], False)
    assert player["group_licensing_opt_in"] is False

    withdrawn = get_mark(context["group_mark"]["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_at"] is not None
    assert_timestamp_format(withdrawn["withdrawn_at"])
    # Only the player's own group mark is pulled; the league mark is untouched.
    assert get_mark(context["league_mark"]["id"])["status"] == "ACTIVE"

    submission = get_submission(context["submission"]["id"])
    assert submission["status"] == "REVOKED"
    assert submission["revocation_reason"] == "MARK_WITHDRAWN"

    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 0

    authorization = get_authorization(context["authorization"]["id"])
    assert authorization["status"] == "SUSPENDED"
    assert authorization["suspension_reason"] == "NO_APPROVED_SKUS"


def test_opting_back_in_restores_only_the_mark_and_never_the_revoked_sku(api):
    """PRD §3.1: "Setting `opt_in` to true reverses only the mark statuses: every
    `PLAYER_GROUP` mark of that player in `WITHDRAWN` returns to `ACTIVE`, while
    submissions that were already revoked stay revoked."

    Design: Difficulty/transitive_cascade/player_group_optout_three_hop_cascade_to_authorization
    """
    context = _approved_sku_pinning_a_player_group_mark()
    player_id = context["player"]["id"]

    set_group_licensing(player_id, False)
    restored = set_group_licensing(player_id, True)
    assert restored["group_licensing_opt_in"] is True

    mark = get_mark(context["group_mark"]["id"])
    assert mark["status"] == "ACTIVE"
    assert mark["withdrawn_at"] is None
    assert mark["status_reason"] is None

    # The other two hops are irreversible: REVOKED is terminal.
    assert get_submission(context["submission"]["id"])["status"] == "REVOKED"
    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 0
    assert get_authorization(context["authorization"]["id"])["status"] == "SUSPENDED"
