"""The borrowing base: advance rates, prior-lien floors, perfection filtering,
provisional vs harvest true-up variants, supersede/version bumps, UCC filing
lifecycle, and release deficiency (PRD sections 2.6, 3.3, 3.4).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, add_collateral, add_assigned_policy,
    create_approved_loan, create_budget, create_budget_payload,
    create_collateral_payload, create_ucc_filing_payload, fresh_loan_version,
    get_borrower, get_loan, get_success_data, get_summary,
    make_borrower_headers, record_actuals_payload, set_clock,
    setup_activatable_loan, setup_loan_with_approved_budget,
    setup_loan_with_draw, single_margin_notice, validate_error,
    validate_paginated, validate_success,
)
from test_helpers import appraise_payload

OFFICER = TEST_USERS["loan_officer_headers"]
SYSTEM = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Dual variant: provisional (projected) vs harvest true-up (actual)
# ---------------------------------------------------------------------------

def test_borrowing_base_provisional_then_harvest_trueup(api):
    """PRD section 3.3: "while the feeding budget is `APPROVED`, it is 60% (6000
    basis points) of `projected_revenue_cents`, floored to whole cents, and with no
    `APPROVED` budget the crop component is zero; once the feeding budget is
    `ACTUALIZED`, it is 60% of `actual_revenue_cents`, floored to whole cents —
    identical collateral and commitment produce a different base whenever actual
    revenue differs from the projection." PRD section 3.3: "the appraised value is
    multiplied by the advance rate for its `collateral_type`: 75% (7500 basis
    points) for `CHATTEL_CROP`, 70% for `EQUIPMENT`, 80% for `REAL_ESTATE`."

    Design: Difficulty/dual_variant_calc/borrowing_base_provisional_vs_harvest_trueup
    """
    ctx = setup_activatable_loan()  # EQUIPMENT 10,000,000 PERFECTED + budget 20,000,000 APPROVED
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 19_000_000, \
        "provisional: 7,000,000 collateral (70% of 10,000,000) + 12,000,000 crop (60% of 20,000,000)"

    resp = api.record_budget_actuals(ctx["bud"]["id"],
                                     record_actuals_payload(actual_revenue_cents=10_000_000),
                                     OFFICER)
    budget = validate_success(resp, 200)
    assert budget["status"] == "ACTUALIZED"
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 13_000_000, \
        "true-up: 7,000,000 collateral + 6,000,000 crop (60% of 10,000,000 actual)"


def test_borrowing_base_trueup_above_projection(api):
    """PRD section 3.3: "once the feeding budget is `ACTUALIZED`, it is 60% of
    `actual_revenue_cents`, floored to whole cents — identical collateral and
    commitment produce a different base whenever actual revenue differs from the
    projection." PRD section 3.3: "afterward `borrowing_base_cents` is the lesser
    of the approved commitment and the raw base."

    Design: Difficulty/dual_variant_calc/borrowing_base_provisional_vs_harvest_trueup
    """
    ctx = setup_activatable_loan()
    assert get_summary(ctx["loan"]["id"])["borrowing_base_cents"] == 19_000_000

    resp = api.record_budget_actuals(ctx["bud"]["id"],
                                     record_actuals_payload(actual_revenue_cents=30_000_000),
                                     OFFICER)
    assert validate_success(resp, 200)["status"] == "ACTUALIZED"
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 25_000_000, \
        "true-up above projection: 7,000,000 + 18,000,000 (60% of 30,000,000); cap 50,000,000 never binds"


# ---------------------------------------------------------------------------
# Multi-input assembly: state filtering, per-line floors, nested min
# ---------------------------------------------------------------------------

def test_borrowing_base_unperfected_excluded_then_perfected_included(api):
    """PRD section 3.3: "For every collateral item of the loan that is `PLEDGED`
    and `PERFECTED` — `UNPERFECTED` and `RELEASED` items are excluded — the
    appraised value is multiplied by the advance rate for its `collateral_type`:
    75% (7500 basis points) for `CHATTEL_CROP`, 70% for `EQUIPMENT`, 80% for
    `REAL_ESTATE`." PRD section 3.3: "Each per-collateral product is floored to
    whole cents first, then the item's `prior_lien_cents` is subtracted, with the
    contribution floored at zero so a senior lien can never make a line negative."

    Design: Difficulty/combinatorial_formula/borrowing_base_multi_input_nested_min_state_filter
    """
    ctx = setup_loan_with_approved_budget()  # crop leg: 60% of 20,000,000 = 12,000,000
    col_re, _ = add_collateral(ctx, collateral_type="REAL_ESTATE",
                               appraised_value_cents=8_000_000,
                               prior_lien_cents=1_000_000, description="160 acres",
                               filing_number="UCC-26-RE")
    col_eq, _ = add_collateral(ctx, collateral_type="EQUIPMENT",
                               appraised_value_cents=10_000_000,
                               description="Combine", filing_number="UCC-26-EQ")
    col_cc, _ = add_collateral(ctx, collateral_type="CHATTEL_CROP",
                               appraised_value_cents=5_000_000,
                               description="Growing corn", perfect=False)

    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 24_400_000, \
        "5,400,000 RE net (6,400,000 - 1,000,000 lien) + 7,000,000 EQ + 12,000,000 crop; UNPERFECTED chattel excluded"

    get_success_data(api.create_ucc_filing(
        create_ucc_filing_payload(collateral_id=col_cc["id"],
                                  filing_number="UCC-26-CC",
                                  filed_date="2026-03-06T00:00:00Z"),
        OFFICER))
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 28_150_000, \
        "chattel perfected: + 3,750,000 (75% of 5,000,000); commitment cap 50,000,000 never binds"


def test_borrowing_base_prior_lien_floored_at_zero(api):
    """PRD section 3.3: "Each per-collateral product is floored to whole cents
    first, then the item's `prior_lien_cents` is subtracted, with the contribution
    floored at zero so a senior lien can never make a line negative."

    Design: Difficulty/combinatorial_formula/borrowing_base_multi_input_nested_min_state_filter
    """
    ctx = setup_loan_with_approved_budget()  # crop leg 12,000,000
    add_collateral(ctx, collateral_type="REAL_ESTATE",
                   appraised_value_cents=1_000_000, prior_lien_cents=2_000_000,
                   description="Encumbered lot", filing_number="UCC-26-L1")
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 12_000_000, \
        "800,000 advance less 2,000,000 lien is floored at zero — never a negative line"


# ---------------------------------------------------------------------------
# UCC filing lifecycle: uniqueness, continuation window, lapse cascade
# ---------------------------------------------------------------------------

def test_duplicate_filing_number_rejected(api):
    """PRD section 3.4: "The officer files one by supplying the `collateral_id`, a
    `filing_number` that must be unique across the association — a duplicate is
    rejected with `ERR_FILING_NUMBER_TAKEN` — the `jurisdiction`, and the effective
    `filed_date`."

    Design: Corner/validations/duplicate_filing_number_rejected
    """
    ctx = create_approved_loan()
    col1, _ = add_collateral(ctx, perfect=False, description="Sprayer")
    col2, _ = add_collateral(ctx, perfect=False, description="Planter",
                             appraised_value_cents=4_000_000)
    get_success_data(api.create_ucc_filing(
        create_ucc_filing_payload(collateral_id=col1["id"], filing_number="UCC-DUP"),
        OFFICER))
    resp = api.create_ucc_filing(
        create_ucc_filing_payload(collateral_id=col2["id"], filing_number="UCC-DUP",
                                  filed_date="2026-03-06T00:00:00Z"),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_FILING_NUMBER_TAKEN)
    collateral = get_success_data(api.get_collateral(col2["id"], OFFICER))
    assert collateral["perfection_state"] == "UNPERFECTED", \
        "the rejected second filing perfects nothing"


def test_ucc_continuation_window_boundary(api):
    """PRD section 3.4: "A continuation statement may be filed only inside the
    statutory window — on or after the day 180 days before the current `lapse_date`
    and strictly before the `lapse_date` itself; outside that window the
    continuation is rejected with `ERR_CONTINUATION_WINDOW_NOT_OPEN`." PRD section
    3.4: "A successful continuation moves `FILED` → `CONTINUED`, and a filing
    already `CONTINUED` may be continued again on the same terms, each continuation
    adding another five calendar years to the `lapse_date`."

    Design: Corner/validations/ucc_continuation_before_window_rejected_then_at_open_continues
    """
    ctx = create_approved_loan()
    col, fil = add_collateral(ctx)  # filed 2026-03-05, lapse 2031-03-05
    assert fil["lapse_date"].startswith("2031-03-05"), \
        "lapse_date is filed_date plus five calendar years"

    set_clock("2030-09-05T00:00:00Z")  # one day before the window opens
    resp = api.continue_ucc_filing(fil["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_CONTINUATION_WINDOW_NOT_OPEN)

    set_clock("2030-09-06T00:00:00Z")  # exactly lapse_date - 180 days; window open
    data = validate_success(api.continue_ucc_filing(fil["id"], OFFICER), 200)
    assert data["status"] == "CONTINUED"
    assert data["lapse_date"].startswith("2036-03-05"), \
        "continuation adds five calendar years to the lapse date"


def test_collateral_release_would_create_deficiency_rejected(api):
    """PRD section 3.4: "A `LoanOfficer` may release a `PLEDGED` item only when,
    after its removal, the recomputed borrowing base would still cover the
    outstanding principal — concretely, the outstanding principal must remain at or
    below the lesser of the approved commitment and the recomputed base; otherwise
    the release is rejected with `ERR_RELEASE_WOULD_CREATE_DEFICIENCY`."

    Design: Corner/validations/collateral_release_would_create_deficiency_rejected
    """
    ctx = setup_loan_with_draw(amount_cents=19_000_000)  # base 19,000,000, drawn in full
    resp = api.release_collateral(ctx["col"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_RELEASE_WOULD_CREATE_DEFICIENCY)
    collateral = get_success_data(api.get_collateral(ctx["col"]["id"], OFFICER))
    assert collateral["status"] == "PLEDGED"
    filing = get_success_data(api.get_ucc_filing(ctx["fil"]["id"], OFFICER))
    assert filing["status"] == "FILED", "the rejected release terminates nothing"


def test_filing_lapse_review_cascade_unperfects_rebases_and_margins(api):
    """PRD section 3.4: "When the periodic review finds a `FILED` or `CONTINUED`
    filing whose `lapse_date` is at or before the clock, the filing lapses: its
    status becomes `LAPSED`, the collateral's `perfection_state` is recomputed and
    falls to `UNPERFECTED` when no other live filing remains, the collateral drops
    out of the borrowing base, and the standard cascade runs". PRD section 3.8:
    "When the deficiency is positive and no `ISSUED` notice already exists for the
    loan, a `MarginCallNotice` is created in `ISSUED` status recording that
    `deficiency_cents`." PRD section 3.1: "A borrower moves from `ACTIVE` to
    `SUSPENDED` whenever any of three conditions comes to hold: its
    `active_covenant_breach_count` reaches at least 2, any of its loans carries a
    `payment_posture` of `DELINQUENT` or `DEFAULT`, or any margin call notice on
    its loans stands `ESCALATED`."

    Design: Difficulty/transitive_cascade/filing_lapse_review_cascade_unperfects_rebases_and_margins
    """
    ctx = setup_loan_with_draw(amount_cents=19_000_000)  # base 19,000,000, drawn full
    set_clock("2031-03-05T00:00:00Z")  # filing's lapse_date (filed 2026-03-05 + 5y)
    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))

    filing = get_success_data(api.get_ucc_filing(ctx["fil"]["id"], OFFICER))
    assert filing["status"] == "LAPSED"
    collateral = get_success_data(api.get_collateral(ctx["col"]["id"], OFFICER))
    assert collateral["perfection_state"] == "UNPERFECTED"

    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 12_000_000, \
        "the lapsed equipment line drops out; only the 60% crop leg remains"
    assert summary["payment_posture"] == "DELINQUENT", \
        "coverage 12,000,000 - 19,000,000 is negative"
    loan = get_loan(ctx["loan"]["id"])
    assert loan["consecutive_delinquent_reviews"] == 1, \
        "first delinquent review close increments to 1, not yet DEFAULT"

    notice = single_margin_notice(ctx["loan"]["id"])
    assert notice["status"] == "ISSUED"
    assert notice["deficiency_cents"] == 7_000_000, \
        "19,000,000 outstanding less min(50,000,000, 12,000,000) base"
    assert get_borrower(ctx["bor"]["id"])["status"] == "SUSPENDED"


def test_second_live_filing_preserves_perfection_through_lapse(api):
    """PRD section 3.4: "When the periodic review finds a `FILED` or `CONTINUED`
    filing whose `lapse_date` is at or before the clock, the filing lapses: its
    status becomes `LAPSED`, the collateral's `perfection_state` is recomputed and
    falls to `UNPERFECTED` when no other live filing remains, the collateral drops
    out of the borrowing base, and the standard cascade runs". PRD section 3.4:
    "Perfection is derived: a collateral item is `PERFECTED` exactly when at least
    one of its UCC filings stands `FILED` or `CONTINUED`, and `UNPERFECTED`
    otherwise."

    Design: Difficulty/transitive_cascade/filing_lapse_review_cascade_unperfects_rebases_and_margins
    """
    ctx = setup_activatable_loan()
    col, fil1 = ctx["col"], ctx["fil"]  # filed 2026-03-05, lapse 2031-03-05
    fil2 = get_success_data(api.create_ucc_filing(
        create_ucc_filing_payload(collateral_id=col["id"], filing_number="UCC-26-002",
                                  filed_date="2026-04-01T00:00:00Z"),
        OFFICER))
    get_success_data(api.activate_loan(ctx["loan"]["id"], OFFICER))

    set_clock("2031-03-05T00:00:00Z")  # lapses fil1 only; fil2 lapses 2031-04-01
    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))

    assert get_success_data(api.get_ucc_filing(fil1["id"], OFFICER))["status"] == "LAPSED"
    assert get_success_data(api.get_ucc_filing(fil2["id"], OFFICER))["status"] == "FILED"
    collateral = get_success_data(api.get_collateral(col["id"], OFFICER))
    assert collateral["perfection_state"] == "PERFECTED", \
        "a second live filing keeps the collateral PERFECTED through the first lapse"
    summary = get_summary(ctx["loan"]["id"])
    assert summary["borrowing_base_cents"] == 19_000_000, "base unchanged"
    assert summary["payment_posture"] == "CURRENT"
    _data, meta = validate_paginated(
        api.list_margin_call_notices(OFFICER, {"loan_account_id": ctx["loan"]["id"]}))
    assert meta["total_count"] == 0, "no deficiency — no margin call notice created"


# ---------------------------------------------------------------------------
# Budget supersede + optimistic concurrency on the loan version
# ---------------------------------------------------------------------------

def test_budget_supersede_replaces_draft(api):
    """PRD section 3.3: "A new budget enters `DRAFT`, and filing a newer draft
    supersedes the prior draft of the same loan to `SUPERSEDED`." PRD section 2.6:
    "So do creating, approving, or recording actuals on one of its crop budgets;
    releasing one of its collateral items; creating or terminating one of its UCC
    filings; paying one of its insurance claims; disbursing or rescinding one of
    its draws; creating or reversing one of its repayments; and creating,
    rejecting, executing, or withdrawing one of its restructure plans."

    Design: Corner/state_machines/budget_supersede_replaces_draft
    """
    ctx = create_approved_loan()
    loan_id = ctx["loan"]["id"]
    v1 = ctx["loan"]["version"]

    b1 = get_success_data(api.create_crop_budget(
        create_budget_payload(loan_account_id=loan_id, acres=900,
                              projected_revenue_cents=18_000_000,
                              projected_expenses_cents=11_000_000,
                              expected_loan_version=v1),
        make_borrower_headers(ctx["bor"]["id"])), 201)
    v2 = fresh_loan_version(loan_id)
    assert v2 == v1 + 1, "a budget create increments the loan version by exactly 1"

    b2 = get_success_data(api.create_crop_budget(
        create_budget_payload(loan_account_id=loan_id, acres=950,
                              projected_revenue_cents=19_000_000,
                              projected_expenses_cents=11_500_000,
                              expected_loan_version=v2),
        make_borrower_headers(ctx["bor"]["id"])), 201)
    assert b2["status"] == "DRAFT"
    first = get_success_data(api.get_crop_budget(b1["id"], OFFICER))
    assert first["status"] == "SUPERSEDED", "the newer draft supersedes the prior draft"


def test_occ_budget_create_stale_version_returns_412(api):
    """PRD section 2.6: "Creating a crop budget requires the request to carry
    `expected_loan_version` equal to the target loan's current `version`. A newer
    budget supersedes an existing `DRAFT` budget, and the loan's borrowing base
    anchors to the newest budget, so a writer holding a stale loan version would
    silently build on a superseded projection; if the loan's version has advanced
    since the client last observed it, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_budget_create_stale_version_returns_412
    """
    ctx = create_approved_loan()
    loan_id = ctx["loan"]["id"]
    v1 = ctx["loan"]["version"]
    borrower = make_borrower_headers(ctx["bor"]["id"])

    b1 = get_success_data(api.create_crop_budget(
        create_budget_payload(loan_account_id=loan_id, expected_loan_version=v1),
        borrower), 201)

    resp = api.create_crop_budget(
        create_budget_payload(loan_account_id=loan_id, acres=950,
                              projected_revenue_cents=19_000_000,
                              expected_loan_version=v1),  # stale replay
        borrower)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    v2 = fresh_loan_version(loan_id)
    assert v2 == v1 + 1
    b2 = get_success_data(api.create_crop_budget(
        create_budget_payload(loan_account_id=loan_id, acres=950,
                              projected_revenue_cents=19_000_000,
                              expected_loan_version=v2),  # fresh retry
        borrower), 201)
    assert b2["status"] == "DRAFT"
    assert get_success_data(api.get_crop_budget(b1["id"], OFFICER))["status"] == "SUPERSEDED"


def test_occ_appraise_stale_collateral_version_returns_412(api):
    """PRD section 2.6: "Recording an appraisal requires
    `expected_collateral_version` matching the collateral's current `version`.
    Each new appraisal supersedes the prior value and immediately reshapes the
    borrowing base, so an appraisal keyed to a stale collateral version is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_appraise_stale_collateral_version_returns_412
    """
    ctx = create_approved_loan()
    col = get_success_data(api.create_collateral(
        create_collateral_payload(loan_account_id=ctx["loan"]["id"]),
        OFFICER), 201)
    cv1 = col["version"]

    data = validate_success(api.appraise_collateral(
        col["id"], appraise_payload(appraised_value_cents=9_000_000,
                                    expected_collateral_version=cv1),
        OFFICER), 200)
    assert data["appraised_value_cents"] == 9_000_000, "the first appraisal lands"

    resp = api.appraise_collateral(
        col["id"], appraise_payload(appraised_value_cents=8_000_000,
                                    expected_collateral_version=cv1),  # stale
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    collateral = get_success_data(api.get_collateral(col["id"], OFFICER))
    assert collateral["appraised_value_cents"] == 9_000_000, \
        "the rejected appraisal changes nothing"
    assert collateral["version"] == cv1 + 1, \
        "exactly one appraisal mutated the collateral"
