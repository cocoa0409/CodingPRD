"""Requests that break two rules at once, where only the earlier rule may speak.

PRD 2.7: "When a request violates more than one rule, exactly one error is
returned: the one belonging to the lowest-numbered rule in the ladder below.
Evaluation is strictly in ascending order and short-circuits on the first
violation, so a later, more specific rule can never mask an earlier, more general
one."
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    PLATFORM_ADMIN,
    make_strategy_officer_headers,
)

LOW_RESERVE_ORG = {
    "annual_expense_cents": 1200000000,
    "unrestricted_net_assets_cents": 100000000,
}


def _error_id(response):
    """The error_id carried by an error envelope, per PRD 2.2."""
    return response.json()["data"]["error_id"]


def _low_reserve_deal_in_diligence(api):
    """A DILIGENCE deal with no findings whose gating snapshot is MODERATE at 1.00 months."""
    ctx = {
        "org_a": fx.create_organization(
            api, legal_name="Alameda Bridge Services", **LOW_RESERVE_ORG
        ),
        "org_b": fx.create_organization(
            api, legal_name="Alameda Neighbor Works", **LOW_RESERVE_ORG
        ),
    }
    fx.create_program(
        api, ctx["org_a"]["id"], name="Peer Mentoring East",
        service_category="YOUTH_MENTORING", county_code="CA-ALAMEDA",
        annual_expense_cents=400000000, clients_served=900,
    )
    fx.create_program(
        api, ctx["org_a"]["id"], name="Pantry Network East",
        service_category="FOOD_SECURITY", county_code="CA-ALAMEDA",
        annual_expense_cents=300000000, clients_served=4000,
    )
    fx.create_program(
        api, ctx["org_b"]["id"], name="Peer Mentoring West",
        service_category="YOUTH_MENTORING", county_code="CA-ALAMEDA",
        annual_expense_cents=350000000, clients_served=700,
    )
    fx.create_program(
        api, ctx["org_b"]["id"], name="Transitional Housing West",
        service_category="HOUSING", county_code="CA-ALAMEDA",
        annual_expense_cents=500000000, clients_served=120,
    )
    ctx = fx.setup_deal_exploratory(api, ctx, confidentiality_tier="STANDARD")
    ctx = fx.setup_deal_rationale_built(api, ctx)
    ctx = fx.setup_deal_loi_negotiation(api, ctx)
    ctx = fx.setup_deal_diligence(api, ctx)
    assert ctx["deal"]["status"] == "DILIGENCE"
    ctx["adjusted"] = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], "DILIGENCE_ADJUSTED"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    return ctx


def _select_structure(api, ctx):
    return api.select_structure(
        ctx["deal"]["id"],
        f.select_structure_payload(),
        make_strategy_officer_headers(ctx["org_a"]["id"]),
    )


def test_the_deal_state_error_speaks_before_the_reserve_floor_error(api):
    """Selecting a structure too early answers the deal-state error, never the reserve floor error.

    PRD 2.7 orders rule 16, "Restructuring.status permits the requested operation -
    otherwise ERR_INVALID_DEAL_STATE. This rule guards structure selection", ahead of
    rule 49, "That same assessment's reserve_months meets the reserve floor -
    otherwise ERR_RESERVE_BELOW_FLOOR". PRD 3.5 makes both violations live at once:
    "Commitment is available only while the deal is DILIGENCE_CLOSED", and "that same
    snapshot's reserve_months must be at least 3.00 months of combined operating
    reserve; anything strictly below that floor answers ERR_RESERVE_BELOW_FLOOR". With
    the deal still in DILIGENCE and the gating snapshot at 1.00 months, only the
    lower-numbered rule may answer.

    Design: Difficulty/priority_pair_validation_conflict/select_structure_deal_state_error_precedes_reserve_floor_error
    """
    ctx = _low_reserve_deal_in_diligence(api)
    a.assert_decimal_equals(ctx["adjusted"]["reserve_months"], 1.00, 2, "reserve_months")
    assert ctx["adjusted"]["reserve_months"] < 3.00, "the reserve floor must genuinely be breached"

    response = _select_structure(api, ctx)

    validate_error(response, err.ERR_INVALID_DEAL_STATE, 409)
    assert _error_id(response) != err.ERR_RESERVE_BELOW_FLOOR, (
        "rule 49 may not pre-empt rule 16"
    )
    assert response.status_code != 422, (
        "the reserve-floor status must not surface while the deal-state rule is violated"
    )


def test_the_refused_selection_leaves_the_deal_uncommitted(api):
    """The refused commitment writes nothing on the deal row.

    PRD 2.5: "A request refused by any validation - including the two version checks
    above - increments nothing and mutates nothing." PRD 3.2 confirms the fields that
    must stay at their opening values until a successful commitment: a deal starts
    with "unrestricted_transfer_value_cents at 0 ... structure_type null", and PRD 3.5
    says only success "records both request fields and advances DILIGENCE_CLOSED ->
    STRUCTURE_SELECTED, with its version rising by one".

    Design: Difficulty/priority_pair_validation_conflict/select_structure_deal_state_error_precedes_reserve_floor_error
    """
    ctx = _low_reserve_deal_in_diligence(api)
    before = fx.read_deal(api, ctx["deal"]["id"])

    validate_error(_select_structure(api, ctx), err.ERR_INVALID_DEAL_STATE, 409)

    after = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(after, "status", "DILIGENCE")
    a.assert_null(after, "structure_type")
    a.assert_money_equals(
        after["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents"
    )
    a.assert_version_is(after, before["version"], "restructuring")


def test_closing_diligence_lets_the_masked_reserve_floor_error_surface(api):
    """Once the deal-state rule is satisfied the reserve floor error is the one that answers.

    PRD 2.7 evaluation "short-circuits on the first violation", so removing the rule-16
    violation must expose the rule-49 one that was there all along. PRD 3.4 supplies
    the removal: "if it has at least one finding and every one of them is either
    CLEARED or WAIVED, the deal advances DILIGENCE -> DILIGENCE_CLOSED". The gating
    snapshot is left untouched by that clearance - PRD 2.4 makes an assessment "an
    immutable snapshot" - so per PRD 3.5 its MODERATE rating still satisfies rule 48
    while its 1.00 months still breaches the 3.00-month floor of rule 49.

    Design: Difficulty/priority_pair_validation_conflict/select_structure_deal_state_error_precedes_reserve_floor_error
    """
    ctx = _low_reserve_deal_in_diligence(api)
    a.assert_field(ctx["adjusted"], "composite_rating", "MODERATE")
    finding = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                ctx["deal"]["id"], severity="LOW", exposure_cents=0
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )
    validate_success(
        api.respond_diligence_request(
            finding["id"],
            f.diligence_respond_payload(),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        )
    )
    validate_success(
        api.clear_diligence_request(finding["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2)
    )
    ctx["deal"] = fx.read_deal(api, ctx["deal"]["id"])
    a.assert_field(ctx["deal"], "status", "DILIGENCE_CLOSED")

    response = _select_structure(api, ctx)

    validate_error(response, err.ERR_RESERVE_BELOW_FLOOR, 422)
    assert _error_id(response) != err.ERR_INVALID_DEAL_STATE, (
        "the deal-state rule is satisfied once diligence has closed"
    )
    a.assert_null(fx.read_deal(api, ctx["deal"]["id"]), "structure_type")


def test_the_gating_snapshot_is_moderate_at_one_month_of_reserve(api):
    """The gating snapshot satisfies the rating rule while breaching only the reserve floor.

    PRD 3.5 runs the alignment rating at rule 48 before the reserve floor at rule 49:
    the snapshot "must exist and must be rated STRONG or MODERATE", and only then must
    its "reserve_months ... be at least 3.00 months". PRD 3.2 derives both figures:
    two parties at 1200000000 cents of annual expense give a combined monthly expense
    of 200000000 cents, against which 200000000 cents of available unrestricted assets
    is exactly 1.00 month, and "anything below one and a half months of reserve earns
    0.00" sustainability points; one overlapping mentoring pair over a denominator of
    two admitted programs each gives an index of exactly 0.5000 and "the full 30.00",
    which with 40.00 mission points for identical codes makes the composite 70.00 and
    the rating MODERATE.

    Design: Difficulty/priority_pair_validation_conflict/select_structure_deal_state_error_precedes_reserve_floor_error
    """
    ctx = _low_reserve_deal_in_diligence(api)
    adj = ctx["adjusted"]

    a.assert_money_equals(
        adj["combined_monthly_expense_cents"], 200000000, "combined_monthly_expense_cents"
    )
    a.assert_money_equals(
        adj["available_unrestricted_cents"], 200000000, "available_unrestricted_cents"
    )
    a.assert_decimal_equals(adj["reserve_months"], 1.00, 2, "reserve_months")
    a.assert_decimal_equals(adj["sustainability_points"], 0.00, 2, "sustainability_points")
    a.assert_decimal_equals(adj["program_overlap_index"], 0.5000, 4, "program_overlap_index")
    a.assert_decimal_equals(adj["program_overlap_points"], 30.00, 2, "program_overlap_points")
    a.assert_decimal_equals(adj["composite_score"], 70.00, 2, "composite_score")
    a.assert_field(adj, "composite_rating", "MODERATE")


def _two_courtships(api):
    """An A-B deal holding an ACTIVE 2026-08-01..2026-09-29 window and an A-C deal awaiting a letter."""
    ctx = fx.setup_deal_loi_negotiation(api)
    a.assert_field(ctx["loi"], "exclusivity_end_date", "2026-09-29")
    ctx["org_c"] = fx.create_organization(api, fx.ORG_C)
    ctx["deal_2"] = validate_success(
        api.create_restructuring(
            f.restructuring_payload(
                ctx["org_a"]["id"], ctx["org_c"]["id"], confidentiality_tier="STANDARD"
            ),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal_2"]["id"], "SCREENING"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    ctx["deal_2"] = fx.read_deal(api, ctx["deal_2"]["id"])
    a.assert_field(ctx["deal_2"], "status", "RATIONALE_BUILT")
    return ctx


def _issue_second_letter(api, ctx, **overrides):
    deal_id = ctx["deal_2"]["id"]
    return api.create_letter_of_intent(
        f.letter_of_intent_payload(deal_id, fx.deal_version(api, deal_id), **overrides),
        make_strategy_officer_headers(ctx["org_a"]["id"]),
    )


def test_the_exclusivity_conflict_speaks_before_the_seat_split_range_error(api):
    """A letter that both overlaps a live window and misallocates the seats answers the conflict.

    PRD 2.7 places rule 40, "The requested exclusivity window does not overlap an
    ACTIVE window of another deal involving either party - otherwise
    ERR_EXCLUSIVITY_CONFLICT", ahead of rule 45, "board_seat_split_initiator is at
    least 1 and at most combined_board_seats minus 1 - otherwise
    ERR_SEAT_SPLIT_OUT_OF_RANGE. This rule guards both letter issuance and letter
    revision." PRD 3.3 makes both violations live: the proposed 2026-09-01 window runs
    thirty days to 2026-09-30 and so shares September days with the live
    2026-08-01..2026-09-29 window of the initiator's other courtship, where "two
    windows that share even a single calendar day conflict", while a split equal to
    combined_board_seats leaves the target with nothing. Only the earlier rule may
    answer.

    Design: Difficulty/priority_pair_validation_conflict/letter_exclusivity_conflict_precedes_seat_split_range_error
    """
    ctx = _two_courtships(api)

    response = _issue_second_letter(
        api,
        ctx,
        board_seat_split_initiator=15,
        exclusivity_days=30,
        exclusivity_start_date="2026-09-01",
    )

    validate_error(response, err.ERR_EXCLUSIVITY_CONFLICT, 409)
    assert _error_id(response) != err.ERR_SEAT_SPLIT_OUT_OF_RANGE, (
        "rule 45 may not pre-empt rule 40"
    )
    assert _error_id(response) != err.ERR_INVALID_REQUEST, (
        "a split equal to combined_board_seats is a business-range breach, not a malformed field"
    )


def test_the_seat_split_range_error_is_genuinely_live_on_a_clear_window(api):
    """The same rejected split answers the range error once the window no longer conflicts.

    PRD 3.3: "The seat split must leave both sides represented: it must be at least 1
    and at most combined_board_seats minus 1, and a split outside that range is
    refused with ERR_SEAT_SPLIT_OUT_OF_RANGE." Moving the requested window to
    2026-09-30 through 2026-10-29 clears the other courtship's window, which ends
    2026-09-29, and PRD 3.3 exempts nothing else here because the cooling-off rule
    applies only "where the most recent RELEASED or EXPIRED window of a party involved
    a different counterparty" and that window is still ACTIVE. With rule 40 satisfied,
    the split of 15 out of 15 seats is the violation that answers.

    Design: Difficulty/priority_pair_validation_conflict/letter_exclusivity_conflict_precedes_seat_split_range_error
    """
    ctx = _two_courtships(api)

    response = _issue_second_letter(
        api,
        ctx,
        board_seat_split_initiator=15,
        exclusivity_days=30,
        exclusivity_start_date="2026-09-30",
    )

    validate_error(response, err.ERR_SEAT_SPLIT_OUT_OF_RANGE, 422)
    assert _error_id(response) != err.ERR_EXCLUSIVITY_CONFLICT, (
        "the requested window no longer overlaps the other courtship"
    )


def test_the_refused_letter_leaves_both_courtships_untouched(api):
    """The doubly-invalid letter creates nothing and disturbs neither deal.

    PRD 2.5: "A request refused by any validation ... increments nothing and mutates
    nothing." The first courtship's letter therefore keeps the ACTIVE
    exclusivity_status that PRD 3.3 assigns a newly issued letter, the second deal
    stays in RATIONALE_BUILT with no letter of its own and an unchanged version, and a
    later well-formed letter proposing a non-overlapping window and a split inside the
    1..combined_board_seats-1 range still succeeds.

    Design: Difficulty/priority_pair_validation_conflict/letter_exclusivity_conflict_precedes_seat_split_range_error
    """
    ctx = _two_courtships(api)
    before = fx.read_deal(api, ctx["deal_2"]["id"])

    validate_error(
        _issue_second_letter(
            api,
            ctx,
            board_seat_split_initiator=15,
            exclusivity_days=30,
            exclusivity_start_date="2026-09-01",
        ),
        err.ERR_EXCLUSIVITY_CONFLICT,
        409,
    )

    after = fx.read_deal(api, ctx["deal_2"]["id"])
    a.assert_field(after, "status", "RATIONALE_BUILT")
    a.assert_version_is(after, before["version"], "second restructuring")
    rows, meta = validate_paginated(
        api.list_deal_letters_of_intent(ctx["deal_2"]["id"], PLATFORM_ADMIN)
    )
    assert rows == [], "the refused issuance must not have created a letter"
    assert meta["total_count"] == 0
    first_rows, _first_meta = validate_paginated(
        api.list_deal_letters_of_intent(ctx["deal"]["id"], PLATFORM_ADMIN)
    )
    first = a.find_by_id(first_rows, ctx["loi"]["id"])
    a.assert_field(first, "status", "ISSUED")
    a.assert_field(first, "exclusivity_status", "ACTIVE")

    accepted = validate_success(
        _issue_second_letter(
            api,
            ctx,
            board_seat_split_initiator=8,
            exclusivity_days=30,
            exclusivity_start_date="2026-09-30",
        ),
        201,
    )
    a.assert_field(accepted, "status", "ISSUED")
    a.assert_field(accepted, "exclusivity_end_date", "2026-10-29")
