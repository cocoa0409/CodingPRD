"""Corner-case compliance tests for the API's derived figures, part two.

This file continues the derived-figure coverage of
`test_12a_corner_calculations.py` with the restricted-fund release rules, the
organization restricted corpus, the deal-level restricted-asset posture, the
attorney-general fee tiers and the reconciliation dossier.

Every figure here is exact integer cents unless the PRD names a decimal width:
monetary division rounds half up to a whole cent, except the endowment
spending-rate slice, which is "truncated toward zero rather than rounded half up"
(PRD 2.6, PRD 3.6). The harness restarts the server and empties the registry
before every test, so each test builds all of its own preconditions.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_money_equals,
    assert_pair_corpus_equals,
    assert_seat_ledger_conserved,
    assert_status,
    find_by_id,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
)


# ----------------------------------------------------------------------
# Organization restricted corpus (PRD 3.1, PRD 3.6)
# ----------------------------------------------------------------------
def test_restricted_corpus_aggregates_retained_and_received_amounts_across_funds(api):
    """After a partial judicial transfer the holder's corpus counts its untransferred fund in full plus the retained slice, while the recipient counts only the transferred slice.

    PRD 3.1 makes `restricted_corpus_cents` "the sum of three disjoint
    contributions": for a fund this organization holds whose `transfer_status` is
    anything other than `TRANSFERRED`, "that fund's `principal_cents` plus its
    `accumulated_appreciation_cents`"; for a fund it holds that is `TRANSFERRED`,
    "only that fund's `retained_amount_cents`"; and for a fund "whose recipient is
    this organization and whose `transfer_status` is `TRANSFERRED`", that fund's
    `transferred_amount_cents`. PRD 3.6 fixes the judicial release for a
    `PERM_ENDOWMENT` as the excess of the fund value over
    `historic_dollar_value_cents` plus seven percent of that historic value
    truncated toward zero, i.e. (62000000 - 45000000) + 3150000 = 20150000, with
    `retained_amount_cents` "the fund value less `transferable_amount_cents`" =
    41850000. So the holder shows 5000000 + 41850000 = 46850000 and the recipient
    20150000, and PRD 2.8 has the pair total unchanged at 67000000. PRD 3.6 also
    counts as unresolved every party fund "whose `transfer_status` is neither
    `TRANSFERRED` nor `RETAINED`", leaving one, so the posture ladder stops at
    `RESTRICTED_PENDING`.

    Design: Corner/calculations/restricted_corpus_aggregates_retained_and_received_amounts_across_funds
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    endowment = fx.create_fund(
        api,
        org_a,
        fund_name="Okafor Endowment for Mentoring",
        fund_type="PERM_ENDOWMENT",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=45000000,
        restriction_purpose_code="ME-MENTORING",
        restriction_conflict=True,
        donor_of_record_reachable=False,
    )
    held = fx.create_fund(
        api,
        org_a,
        fund_name="Small Gifts Program Reserve",
        fund_type="TEMP_RESTRICTED",
        principal_cents=5000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="AF-AFTERSCHOOL",
    )

    # An unreachable donor of record permits the petition straight from HELD.
    validate_success(
        api.file_petition(
            endowment["id"],
            f.file_petition_payload(
                petition_basis="DONOR_UNREACHABLE", court_docket_no="SUP-CT-2026-0442"
            ),
            TRUST_COUNSEL,
        )
    )
    validate_success(
        api.record_court_decision(
            endowment["id"],
            f.court_decision_payload(
                "GRANTED_WITH_CONDITIONS", modified_purpose_code="RE-REGIONAL"
            ),
            TRUST_COUNSEL,
        )
    )

    transferred = fx.transfer_fund(api, endowment["id"], deal_id, "JUDICIAL_MODIFICATION")

    assert_status(transferred, "TRANSFERRED", field="transfer_status")
    assert_money_equals(
        transferred["transferable_amount_cents"], 20150000, "transferable_amount_cents"
    )
    assert_money_equals(
        transferred["transferred_amount_cents"], 20150000, "transferred_amount_cents"
    )
    assert_money_equals(
        transferred["retained_amount_cents"], 41850000, "retained_amount_cents"
    )
    assert_field(transferred, "transferred_to_org_id", org_b)

    still_held = validate_success(api.get_restricted_fund(held["id"], TRUST_COUNSEL))
    assert_status(still_held, "HELD", field="transfer_status")

    holder = validate_success(api.get_organization(org_a, PLATFORM_ADMIN))
    recipient = validate_success(api.get_organization(org_b, PLATFORM_ADMIN))
    assert_money_equals(
        holder["restricted_corpus_cents"], 46850000, "holder restricted_corpus_cents"
    )
    assert_money_equals(
        recipient["restricted_corpus_cents"], 20150000, "recipient restricted_corpus_cents"
    )
    assert (
        holder["restricted_corpus_cents"] + recipient["restricted_corpus_cents"]
        == 67000000
    ), "the party-pair restricted corpus is conserved by a transfer"

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "unresolved_restricted_fund_count", 1)
    assert_field(deal, "restricted_asset_posture", "RESTRICTED_PENDING")


# ----------------------------------------------------------------------
# Attorney-general consideration and filing fee (PRD 3.7)
# ----------------------------------------------------------------------
def test_fee_tier_three_applies_at_exactly_the_upper_ceiling(api):
    """A provisional consideration landing exactly on the ten-million-dollar ceiling falls into the top fee tier, costing 500000 cents rather than 150000.

    PRD 3.7 breaks the fee's circularity by pinning the evaluation order. "Step one
    computes `provisional_consideration_cents`, the fee-**exclusive** provisional
    total: `transferred_charitable_asset_value_cents` plus `legal_costs_cents`" -
    here 999000000 + 1000000 = 1000000000, since the recited asset value is the deal's
    `unrestricted_transfer_value_cents` plus the transferred restricted funds, of
    which there are none. "Step two selects the tier by reading *only* that
    provisional total ... at ten million dollars or above it is five thousand
    dollars. Both tier comparisons are strictly less-than against their ceilings, so
    a provisional total landing exactly on a ceiling falls into the *higher* tier."
    "Step three folds the fee in: `closing_costs_cents` is `legal_costs_cents` plus
    `ag_filing_fee_cents`, and `total_consideration_cents` is
    `transferred_charitable_asset_value_cents` plus `closing_costs_cents`". A recited
    value at or above five million dollars forces `APPROVAL_PETITION`, whose
    `statutory_waiting_days` "starts at forty-five calendar days"; the structure is a
    `MERGER` and no fund carries a judicial basis, so neither surcharge applies, and
    `review_deadline_at` is `submitted_at` - the logical clock's startup default of
    `2026-08-01T00:00:00Z` per PRD 2.4 - advanced by those 45 calendar days.

    Design: Corner/calculations/fee_tier_three_applies_at_exactly_the_upper_ceiling
    """
    ctx = fx.setup_deal_diligence_closed(api)
    ctx = fx.setup_deal_structure_selected(
        api, ctx, unrestricted_transfer_value_cents=999000000
    )
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]
    assert_status(ctx["deal"], "REGULATORY_REVIEW")

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id,
                state_code="CA",
                filing_type="APPROVAL_PETITION",
                legal_costs_cents=1000000,
            ),
            TRUST_COUNSEL,
        ),
        201,
    )

    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"], 999000000,
        "transferred_charitable_asset_value_cents",
    )
    assert_money_equals(
        filing["provisional_consideration_cents"], 1000000000,
        "provisional_consideration_cents",
    )
    assert_money_equals(filing["ag_filing_fee_cents"], 500000, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 1500000, "closing_costs_cents")
    assert_money_equals(
        filing["total_consideration_cents"], 1000500000, "total_consideration_cents"
    )
    assert_field(filing, "statutory_waiting_days", 45)
    assert_field(filing, "submitted_at", "2026-08-01T00:00:00.000Z")
    assert_field(filing, "review_deadline_at", "2026-09-15T00:00:00.000Z")
    assert_status(filing, "SUBMITTED")


# ----------------------------------------------------------------------
# Deal-level restricted-asset posture (PRD 3.6)
# ----------------------------------------------------------------------
def test_denied_consent_blocks_the_posture_until_the_petition_is_filed(api):
    """One denied fund forces the posture to BLOCKED even while two funds are unresolved, and filing the petition drops it exactly one rung to RESTRICTED_PENDING.

    PRD 3.6: `unresolved_restricted_fund_count` is "the number of those funds whose
    `transfer_status` is neither `TRANSFERRED` nor `RETAINED`", and
    `restricted_asset_posture` "is then decided by taking the first matching branch of
    four, in this order: if the party-fund set is empty the posture is
    `NOT_ASSESSED`; otherwise if any party fund is in `CONSENT_DENIED` the posture is
    `BLOCKED`; otherwise if the unresolved count is greater than zero the posture is
    `RESTRICTED_PENDING`; otherwise the posture is `CLEARED`. Order matters - a deal
    holding one denied fund and three unresolved ones is `BLOCKED`, not
    `RESTRICTED_PENDING`." On a denial "`transferable_amount_cents` stays at 0", and
    filing the petition moves the fund to `PETITION_FILED` so that "a posture that
    had been `BLOCKED` clears back to `RESTRICTED_PENDING` once no fund of either
    party remains in `CONSENT_DENIED`" - while the unresolved count, which the
    petition resolves nothing about, stays at 2.

    Design: Corner/calculations/denied_consent_blocks_the_posture_until_the_petition_is_filed
    """
    ctx = fx.setup_deal_exploratory(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    denied = fx.create_fund(
        api,
        org_a,
        fund_name="Ibarra Afterschool Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=8000000,
        accumulated_appreciation_cents=500000,
        historic_dollar_value_cents=0,
        restriction_purpose_code="AF-AFTERSCHOOL",
    )
    untouched = fx.create_fund(
        api,
        org_a,
        fund_name="Anonymous Tutoring Bequest",
        fund_type="TEMP_RESTRICTED",
        principal_cents=3000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="TU-TUTORING",
    )
    validate_success(
        api.seek_consent(denied["id"], f.seek_consent_payload(), TRUST_COUNSEL)
    )

    denied = validate_success(
        api.record_consent(
            denied["id"], f.record_consent_payload("DENIED"), TRUST_COUNSEL
        )
    )
    assert_status(denied, "CONSENT_DENIED", field="transfer_status")
    assert_field(denied, "consent_decision", "DENIED")
    assert_money_equals(
        denied["transferable_amount_cents"], 0, "transferable_amount_cents"
    )

    blocked_deal = fx.read_deal(api, deal_id)
    assert_field(blocked_deal, "restricted_asset_posture", "BLOCKED")
    assert_field(blocked_deal, "unresolved_restricted_fund_count", 2)

    denied = validate_success(
        api.file_petition(
            denied["id"],
            f.file_petition_payload(
                petition_basis="IMPRACTICABLE", court_docket_no="SUP-CT-2026-0517"
            ),
            TRUST_COUNSEL,
        )
    )
    assert_status(denied, "PETITION_FILED", field="transfer_status")

    still_held = validate_success(api.get_restricted_fund(untouched["id"], TRUST_COUNSEL))
    assert_status(still_held, "HELD", field="transfer_status")

    pending_deal = fx.read_deal(api, deal_id)
    assert_field(pending_deal, "unresolved_restricted_fund_count", 2)
    assert_field(pending_deal, "restricted_asset_posture", "RESTRICTED_PENDING")


# ----------------------------------------------------------------------
# Judicial release of a permanent endowment (PRD 3.6)
# ----------------------------------------------------------------------
def test_judicial_spending_slice_truncates_instead_of_rounding(api):
    """The seven-percent spending-rate slice on a historic dollar value of 45000010 truncates 3150000.7 cents down to 3150000, releasing 20149990 rather than 20149991.

    PRD 3.6: under a `JUDICIAL_MODIFICATION` basis, for a `PERM_ENDOWMENT` "the
    releasable amount is the excess of the fund value over
    `historic_dollar_value_cents`, floored at 0 ... plus a capped slice equal to seven
    percent of `historic_dollar_value_cents`, that slice being truncated toward zero
    rather than rounded half up". PRD 2.6 names this the one deliberate exception to
    round-half-up money. The fund value is 50000000 + 12000000 = 62000000, so the
    excess term is 16999990 and the slice is 7% of 45000010 = 3150000.7 cents
    truncated to 3150000, totalling 20149990. PRD 3.6 also holds that a `MODIFIED`
    fund has not left the holder, so PRD 3.1's first contribution still counts its
    whole `principal_cents` plus `accumulated_appreciation_cents` in the corpus.

    Design: Corner/calculations/judicial_spending_slice_truncates_instead_of_rounding
    """
    org = fx.create_organization(api, legal_name="Riverside Youth Alliance")
    fund = fx.create_fund(
        api,
        org["id"],
        fund_name="Vance Perpetual Mentoring Endowment",
        fund_type="PERM_ENDOWMENT",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=45000010,
        restriction_purpose_code="ME-MENTORING",
        restriction_conflict=True,
        donor_of_record_reachable=False,
    )
    validate_success(
        api.file_petition(
            fund["id"],
            f.file_petition_payload(
                petition_basis="DONOR_UNREACHABLE", court_docket_no="SUP-CT-2026-0631"
            ),
            TRUST_COUNSEL,
        )
    )

    modified = validate_success(
        api.record_court_decision(
            fund["id"], f.court_decision_payload("GRANTED"), TRUST_COUNSEL
        )
    )

    assert_status(modified, "MODIFIED", field="transfer_status")
    assert_field(modified, "court_decision", "GRANTED")
    assert_money_equals(
        modified["transferable_amount_cents"], 20149990, "transferable_amount_cents"
    )

    holder = validate_success(api.get_organization(org["id"], PLATFORM_ADMIN))
    assert_money_equals(
        holder["restricted_corpus_cents"], 62000000, "restricted_corpus_cents"
    )


# ----------------------------------------------------------------------
# Reconciliation dossier (PRD 3.9)
# ----------------------------------------------------------------------
def test_dossier_seat_ledger_fields_reconcile_with_the_certified_approvals(api):
    """With only the initiator's resolution certified, the dossier reports a reserved pool of 7 and certified seats of 8, adding to the 15 combined board seats.

    PRD 3.9 has the dossier report "the seat ledger as `reserved_seat_pool`,
    `certified_allocated_seats_total` (the sum of `allocated_seats` over the deal's
    `CERTIFIED` resolutions), `seat_ledger_total` (those two added together) and
    `combined_board_seats`", plus "the two scoring figures side by side as
    `screening_composite_score` and `diligence_adjusted_composite_score`, taken from
    the latest snapshot of each variant, together with their `composite_delta`", and
    "`pair_restricted_corpus_cents` (the sum of `restricted_corpus_cents` across the
    two party organizations)". PRD 3.5 draws the initiator's seats from the governing
    letter's `board_seat_split_initiator` of 8, leaving 15 - 8 = 7 in the pool, and
    the deal stays in `BOARD_APPROVAL` until **both** parties hold a `CERTIFIED`
    resolution, so the target's row is still `RECORDED` with `allocated_seats` 0. PRD
    2.8 makes the pool plus the certified allocations identically equal to
    `combined_board_seats`. Only the figures the PRD pins for this read are asserted.

    Design: Corner/calculations/dossier_seat_ledger_fields_reconcile_with_the_certified_approvals
    """
    ctx = fx.setup_deal_board_approval(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    validate_success(
        api.certify_board_approval(
            ctx["approval_initiator"]["id"],
            f.certify_payload(
                fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"
            ),
            make_board_secretary_headers(org_a),
        )
    )

    dossier = fx.dossier(api, deal_id)

    assert_field(dossier, "deal_status", "BOARD_APPROVAL")
    assert_field(dossier, "structure_type", "MERGER")
    assert_field(dossier, "round_no", 1)
    assert_field(dossier, "combined_board_seats", 15)
    assert_field(dossier, "reserved_seat_pool", 7)
    assert_field(dossier, "certified_allocated_seats_total", 8)
    assert_field(dossier, "seat_ledger_total", 15)
    assert_seat_ledger_conserved(dossier)

    assert_decimal_equals(
        dossier["screening_composite_score"], 60.00, 2, "screening_composite_score"
    )
    assert_decimal_equals(
        dossier["diligence_adjusted_composite_score"], 60.00, 2,
        "diligence_adjusted_composite_score",
    )
    assert_decimal_equals(dossier["composite_delta"], 0.00, 2, "composite_delta")
    assert_money_equals(
        dossier["combined_monthly_expense_cents"], 16666668,
        "combined_monthly_expense_cents",
    )
    assert_field(dossier, "restricted_asset_posture", "NOT_ASSESSED")
    assert_field(dossier, "unresolved_restricted_fund_count", 0)
    assert_pair_corpus_equals(dossier, 0)

    approvals, _meta = validate_paginated(
        api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN)
    )
    target_approval = find_by_id(approvals, ctx["approval_target"]["id"])
    assert target_approval is not None, "the target's recorded resolution must be listed"
    assert_status(target_approval, "RECORDED")
    assert_field(target_approval, "allocated_seats", 0)
