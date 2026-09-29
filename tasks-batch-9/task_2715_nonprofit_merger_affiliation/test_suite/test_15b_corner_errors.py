"""Refusal-path compliance tests, second part: attorney-general filings.

These tests cover the four refusals that guard the attorney-general notice and
approval workflow of PRD 3.7, together with the closing gate that an unresolved
objection keeps shut. Each one drives the request that must be refused, names
the exact error the PRD assigns to it, and then proves the refusal changed
nothing before walking the same request through on its lawful terms.

The harness restarts the server and empties the registry before every test, so
each test registers its own organizations and walks its own deal forward.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AG_APPROVAL_MISSING,
    ERR_AG_FILING_TYPE_MISMATCH,
    ERR_AG_REVIEW_NOT_REQUIRED,
    ERR_AG_STATE_NOT_APPLICABLE,
    ERR_INVALID_FILING_STATE,
    ERR_NO_CHARITABLE_ASSETS_TRANSFERRED,
)
from test_helpers.assertions import (
    assert_field,
    assert_money_equals,
    assert_null,
    assert_status,
    assert_three_fractional_digits,
    find_by_id,
)
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)


def test_an_ag_filing_that_recites_no_transferred_charitable_assets_is_rejected(api):
    """A filing whose derived charitable asset value comes out at zero is refused, even
    though the deal genuinely owes attorney-general review and carries real legal costs.

    PRD 3.7 derives transferred_charitable_asset_value_cents as the deal's
    unrestricted_transfer_value_cents plus the transferred amounts of every restricted
    fund transferred under this deal, and states that "a filing must recite *some*
    transferred charitable asset value: where that derived total comes out at zero, the
    filing is refused with ERR_NO_CHARITABLE_ASSETS_TRANSFERRED". Non-zero
    legal_costs_cents do not rescue it, because the derived asset value is the figure
    tested. PRD 3.7 also fixes ag_review_required at deal creation, true when either
    party is incorporated in one of CA, NY, MA, IL or WA, and leaves the deal sitting in
    REGULATORY_REVIEW until a filing is answered.

    Design: Corner/errors/an_ag_filing_that_recites_no_transferred_charitable_assets_is_rejected
    """
    ctx = fx.setup_deal_structure_selected(api, unrestricted_transfer_value_cents=0)
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]
    assert_status(ctx["deal"], "REGULATORY_REVIEW")

    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, state_code="CA", filing_type="NOTICE", legal_costs_cents=500000
            ),
            TRUST_COUNSEL,
        ),
        ERR_NO_CHARITABLE_ASSETS_TRANSFERRED,
    )

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "ag_review_required", True)
    assert_money_equals(
        deal["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents"
    )
    assert_status(deal, "REGULATORY_REVIEW")

    rows, meta = validate_paginated(api.list_deal_ag_filings(deal_id, TRUST_COUNSEL))
    assert rows == [], f"a refused filing must not be persisted, got {rows!r}"
    assert meta["total_count"] == 0, f"filings total_count expected 0, got {meta}"


def test_ag_filing_rejects_a_foreign_state_and_the_wrong_filing_type(api):
    """A filing state that is neither a party state nor a review state is refused, a review
    state that is not a party state is refused too, and a notice where a petition is owed
    is refused before the lawful petition is finally accepted with all its derived money.

    PRD 3.7 requires the filing's state_code to be the state of incorporation of one of
    the two party organizations *and* to be one of the five review states CA, NY, MA, IL
    and WA, a state failing either test answering ERR_AG_STATE_NOT_APPLICABLE. It then
    validates the type rather than choosing it: a recited asset value of five million
    dollars or more forces APPROVAL_PETITION, and a filing_type that does not equal the
    required type answers ERR_AG_FILING_TYPE_MISMATCH. On the lawful petition the fee is
    tiered off the fee-exclusive provisional total of asset value plus legal costs, which
    is $5,100,000 and so falls in the $1,500 band, closing costs are legal costs plus the
    fee, total consideration is asset value plus closing costs, the statutory waiting
    period is forty-five days for a petition with no surcharge on a MERGER and no judicial
    basis, and the filing is born SUBMITTED with submitted_at from the logical clock —
    which PRD 2.2 fixes at 2026-08-01T00:00:00Z — and review_deadline_at advanced by those
    forty-five calendar days. PRD 3.7 leaves the deal in REGULATORY_REVIEW until the
    bureau answers.

    Design: Corner/errors/ag_filing_rejects_a_foreign_state_and_the_wrong_filing_type
    """
    ctx = fx.setup_deal_structure_selected(api, unrestricted_transfer_value_cents=500000000)
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]
    assert_status(ctx["deal"], "REGULATORY_REVIEW")

    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id,
                state_code="OR",
                filing_type="APPROVAL_PETITION",
                legal_costs_cents=10000000,
            ),
            TRUST_COUNSEL,
        ),
        ERR_AG_STATE_NOT_APPLICABLE,
    )
    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id,
                state_code="NY",
                filing_type="APPROVAL_PETITION",
                legal_costs_cents=10000000,
            ),
            TRUST_COUNSEL,
        ),
        ERR_AG_STATE_NOT_APPLICABLE,
    )
    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, state_code="CA", filing_type="NOTICE", legal_costs_cents=10000000
            ),
            TRUST_COUNSEL,
        ),
        ERR_AG_FILING_TYPE_MISMATCH,
    )

    rows, meta = validate_paginated(api.list_deal_ag_filings(deal_id, TRUST_COUNSEL))
    assert rows == [], f"none of the three refusals may persist a filing, got {rows!r}"
    assert meta["total_count"] == 0, f"filings total_count expected 0, got {meta}"

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id,
                state_code="CA",
                filing_type="APPROVAL_PETITION",
                legal_costs_cents=10000000,
            ),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        500000000,
        "transferred_charitable_asset_value_cents",
    )
    assert_money_equals(
        filing["provisional_consideration_cents"], 510000000, "provisional_consideration_cents"
    )
    assert_money_equals(filing["ag_filing_fee_cents"], 150000, "ag_filing_fee_cents")
    assert_money_equals(filing["closing_costs_cents"], 10150000, "closing_costs_cents")
    assert_money_equals(filing["total_consideration_cents"], 510150000, "total_consideration_cents")
    assert_field(filing, "statutory_waiting_days", 45)
    assert_field(filing, "submitted_at", "2026-08-01T00:00:00.000Z")
    assert_field(filing, "review_deadline_at", "2026-09-15T00:00:00.000Z")
    assert_three_fractional_digits(filing["review_deadline_at"], "review_deadline_at")
    assert_status(filing, "SUBMITTED")
    assert_null(filing, "decision_recorded_at")
    assert_null(filing, "objection_reason")
    assert_status(fx.read_deal(api, deal_id), "REGULATORY_REVIEW")


def test_an_ag_filing_on_a_deal_that_needs_no_ag_review_is_rejected(api):
    """A deal between two organizations incorporated outside the review states is refused a
    filing on the substantive ground rather than on its deal status or on the named state.

    PRD 3.7 states that "attempting a filing on a deal whose ag_review_required is false is
    refused with ERR_AG_REVIEW_NOT_REQUIRED. That refusal, rather than a deal-status
    refusal, is the one that must speak, which is why filing is admitted while the deal is
    either REGULATORY_REVIEW or INTEGRATION: a deal with no attorney-general exposure never
    rests in REGULATORY_REVIEW, so refusing it on deal status would make the substantive
    rule unreachable." PRD 3.1 fixes ag_review_required at creation, false when neither
    party's state_code is CA, NY, MA, IL or WA, and PRD 3.6 confirms that such a deal
    continues REGULATORY_REVIEW to INTEGRATION inside the certifying request, so the deal
    under test is already in INTEGRATION when the filing is attempted. PRD 2.7 orders the
    substantive checks so that rule 32, ag_review_required, speaks before rule 33, the
    filing state.

    Design: Corner/errors/an_ag_filing_on_a_deal_that_needs_no_ag_review_is_rejected
    """
    ctx = {
        "org_a": fx.create_organization(api, dict(fx.ORG_A, state_code="OR")),
        "org_b": fx.create_organization(api, dict(fx.ORG_B, state_code="TX")),
    }
    ctx = fx.setup_deal_exploratory(api, ctx)
    ctx = fx.setup_deal_rationale_built(api, ctx)
    ctx = fx.setup_deal_loi_negotiation(api, ctx)
    ctx = fx.setup_deal_diligence(api, ctx)
    ctx = fx.setup_deal_diligence_closed(api, ctx)
    ctx = fx.setup_deal_structure_selected(api, ctx)
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    deal_id = ctx["deal"]["id"]

    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "ag_review_required", False)
    assert_status(deal, "INTEGRATION")

    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, state_code="OR", filing_type="NOTICE", legal_costs_cents=1000000
            ),
            TRUST_COUNSEL,
        ),
        ERR_AG_REVIEW_NOT_REQUIRED,
    )

    rows, meta = validate_paginated(api.list_deal_ag_filings(deal_id, TRUST_COUNSEL))
    assert rows == [], f"a deal owing no review must hold no filings, got {rows!r}"
    assert meta["total_count"] == 0, f"filings total_count expected 0, got {meta}"
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")


def test_consummation_with_an_objected_filing_is_rejected(api):
    """An objection standing on one filing blocks the close even though a later filing of the
    same deal was approved, the objection cannot be re-answered, and abandoning the deal
    dismantles its letter and both certified resolutions.

    PRD 3.8 states the first consummation gate: where ag_review_required is true the deal
    must hold a filing in APPROVED or DEEMED_APPROVED and must hold **no** filing in
    OBJECTED, else ERR_AG_APPROVAL_MISSING — so the approval is necessary but not
    sufficient. PRD 3.7 states that an objection must carry a non-blank objection_reason,
    leaves the deal sitting in REGULATORY_REVIEW so a fresh filing is required, and admits
    a decision only against a filing still in SUBMITTED, any other status answering
    ERR_INVALID_FILING_STATE; it also tiers the fee off the fee-exclusive provisional total,
    which for $2,000,000 of assets plus legal costs falls in the $1,500 band. PRD 3.9 lets
    either party's officer abandon a deal in INTEGRATION, turning every ISSUED, COUNTERED or
    EXECUTED letter WITHDRAWN with exclusivity RELEASED, and every RECORDED or CERTIFIED
    resolution SUPERSEDED, returning its allocated_seats to reserved_seat_pool, zeroing its
    own allocated_seats and resetting governance_seats to 0 on that party. PRD 2.8 makes the
    restored pool equal combined_board_seats, and PRD 3.8 writes affiliation_role only at
    consummation, so both parties stay INDEPENDENT throughout.

    Design: Corner/errors/consummation_with_an_objected_filing_is_rejected
    """
    ctx = fx.setup_deal_regulatory_review(api)
    deal_id = ctx["deal"]["id"]
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    objected = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, state_code="CA", filing_type="NOTICE", legal_costs_cents=1000000
            ),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_money_equals(
        objected["provisional_consideration_cents"], 201000000, "provisional_consideration_cents"
    )
    assert_money_equals(objected["ag_filing_fee_cents"], 150000, "ag_filing_fee_cents")
    objected = validate_success(
        api.record_ag_decision(
            objected["id"],
            f.ag_decision_payload(
                "OBJECTED",
                objection_reason="Donor-restricted programme funding is unaccounted for",
            ),
            CHARITIES_REGULATOR,
        )
    )
    assert_status(objected, "OBJECTED")
    assert_field(
        objected,
        "objection_reason",
        "Donor-restricted programme funding is unaccounted for",
    )
    assert_status(fx.read_deal(api, deal_id), "REGULATORY_REVIEW")

    approved = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                deal_id, state_code="CA", filing_type="NOTICE", legal_costs_cents=2000000
            ),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_money_equals(
        approved["total_consideration_cents"], 202150000, "total_consideration_cents"
    )
    approved = validate_success(
        api.record_ag_decision(approved["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR)
    )
    assert_status(approved, "APPROVED")
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")

    validate_error(
        api.consummate(deal_id, f.consummate_payload(), make_strategy_officer_headers(org_a)),
        ERR_AG_APPROVAL_MISSING,
    )
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")
    assert_field(
        validate_success(api.get_organization(org_a, PLATFORM_ADMIN)),
        "affiliation_role",
        "INDEPENDENT",
    )

    validate_error(
        api.record_ag_decision(
            objected["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR
        ),
        ERR_INVALID_FILING_STATE,
    )
    rows, _ = validate_paginated(api.list_deal_ag_filings(deal_id, TRUST_COUNSEL))
    still_objected = find_by_id(rows, objected["id"])
    assert still_objected is not None, "the objected filing must remain listed on the deal"
    assert_status(still_objected, "OBJECTED")
    assert_field(
        still_objected,
        "objection_reason",
        "Donor-restricted programme funding is unaccounted for",
    )

    abandoned = validate_success(
        api.abandon(deal_id, f.abandon_payload(), make_strategy_officer_headers(org_b))
    )
    assert_status(abandoned, "ABANDONED")
    assert_field(abandoned, "reserved_seat_pool", 15)
    assert_field(abandoned, "combined_board_seats", 15)

    rows, _ = validate_paginated(api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN))
    assert len(rows) == 2, f"both resolutions must remain listed, got {rows!r}"
    for row in rows:
        assert_status(row, "SUPERSEDED")
        assert_field(row, "allocated_seats", 0)

    letters, _ = validate_paginated(api.list_deal_letters_of_intent(deal_id, PLATFORM_ADMIN))
    assert len(letters) == 1, f"the deal issued exactly one letter, got {letters!r}"
    assert_status(letters[0], "WITHDRAWN")
    assert_field(letters[0], "exclusivity_status", "RELEASED")

    for org_id in (org_a, org_b):
        org = validate_success(api.get_organization(org_id, PLATFORM_ADMIN))
        assert_field(org, "governance_seats", 0)
        assert_field(org, "affiliation_role", "INDEPENDENT")
