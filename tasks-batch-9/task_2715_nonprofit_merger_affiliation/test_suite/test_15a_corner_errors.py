"""Refusal-path compliance tests, part one.

Each test drives one refusal the PRD names and then re-reads the affected rows to
prove the refusal changed nothing. The admission ladder of PRD 2.7 is strictly
ordered and short-circuiting, so every probe here is built so that exactly one
rule can speak.

The harness restarts the server and empties the registry before every test, so
each test builds its own preconditions through the API.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AG_FILING_NOT_FOUND,
    ERR_ALIGNMENT_RATING_INSUFFICIENT,
    ERR_BOARD_APPROVAL_NOT_FOUND,
    ERR_DILIGENCE_REQUEST_NOT_FOUND,
    ERR_EIN_ALREADY_REGISTERED,
    ERR_HDV_EXCEEDS_FUND_VALUE,
    ERR_INTEGRATION_TASK_NOT_FOUND,
    ERR_INVALID_APPROVAL_STATE,
    ERR_LETTER_OF_INTENT_NOT_FOUND,
    ERR_NO_ELIGIBLE_VOTES,
    ERR_PROGRAM_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STRUCTURE_TYPE_MISMATCH,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_money_equals,
    assert_null,
    assert_seat_ledger_conserved,
    assert_status,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    INTEGRATION_MANAGER,
    NO_HEADERS,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    UNKNOWN_ROLE,
    make_board_secretary_headers,
    make_headers,
    make_strategy_officer_headers,
)


def test_unknown_row_lookups_each_return_their_own_not_found_code(api):
    """Each entity that can be named only by path id answers with its own not-found code,
    and the continuity decision resolves the deal before the program.

    PRD 2.7 orders the existence block: the restructuring named in a body is resolved at
    rule 5 and the program at rule 6, the letter of intent at rule 7, the diligence
    request at rule 8, the board approval at rule 10, the attorney-general filing at
    rule 11 and the integration task at rule 12, each answering its own
    ERR_*_NOT_FOUND. PRD 2.2 requires every error body to carry both error_id and
    message, and PRD 2.4 bumps a version only on a successful mutation, so none of the
    six refusals may touch the deal.

    Design: Corner/errors/unknown_row_lookups_each_return_their_own_not_found_code
    """
    ctx = fx.setup_deal_exploratory(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    probes = [
        (
            api.continuity_decision(
                NON_EXISTENT_UUID, f.continuity_decision_payload(deal_id), INTEGRATION_MANAGER
            ),
            ERR_PROGRAM_NOT_FOUND,
        ),
        (
            api.withdraw_letter_of_intent(
                NON_EXISTENT_UUID,
                f.withdraw_payload(withdrawal_reason="probe"),
                make_strategy_officer_headers(org_a),
            ),
            ERR_LETTER_OF_INTENT_NOT_FOUND,
        ),
        (
            api.respond_diligence_request(
                NON_EXISTENT_UUID,
                f.diligence_respond_payload(response_ref="RESP-9999"),
                make_strategy_officer_headers(org_a),
            ),
            ERR_DILIGENCE_REQUEST_NOT_FOUND,
        ),
        (
            api.certify_board_approval(
                NON_EXISTENT_UUID,
                f.certify_payload(
                    fiduciary_memo_ref="MEMO-X", certifying_secretary_ref="SEC-X"
                ),
                make_board_secretary_headers(org_a),
            ),
            ERR_BOARD_APPROVAL_NOT_FOUND,
        ),
        (
            api.record_ag_decision(
                NON_EXISTENT_UUID, f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR
            ),
            ERR_AG_FILING_NOT_FOUND,
        ),
        (
            api.get_integration_task(NON_EXISTENT_UUID, PLATFORM_ADMIN),
            ERR_INTEGRATION_TASK_NOT_FOUND,
        ),
    ]
    for response, expected in probes:
        validate_error(response, expected, 404)
        body = response.json()["data"]
        assert isinstance(body.get("message"), str) and body["message"], (
            f"the {expected} body must carry a message, got {body!r}"
        )

    assert_version_is(fx.read_deal(api, deal_id), 1, "restructuring")


def test_create_organization_with_a_missing_x_user_id_header_is_refused(api):
    """Authentication and authorisation are separate rules: absent or unrecognised identity
    is a 401, while a declared role that is not on the endpoint's list is a 403.

    PRD 2.7 rule 1 refuses a request that carries no X-User-ID and X-User-Role pair, or
    one whose role is not one of the seven declared roles, with ERR_UNAUTHENTICATED
    before anything else is looked at; only then does rule 2 compare the recognised role
    against the endpoint's authorised roles and answer ERR_ROLE_NOT_PERMITTED. PRD 4
    restricts organization registration to PlatformAdmin, so a StrategyOfficer reaches
    rule 2 and stops there. Neither refusal may create a row.

    Design: Corner/errors/create_organization_with_a_missing_x_user_id_header_is_refused
    """
    payload = dict(fx.ORG_A)

    validate_error(api.create_organization(payload, NO_HEADERS), ERR_UNAUTHENTICATED, 401)
    validate_error(api.create_organization(payload, UNKNOWN_ROLE), ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.create_organization(payload, make_headers("so-001", "StrategyOfficer")),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    rows, meta = validate_paginated(api.list_organizations(PLATFORM_ADMIN))
    assert rows == [], f"no organization may exist after three refusals, got {rows!r}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta}"


def test_a_second_organization_with_the_same_ein_is_rejected(api):
    """A second registration under an already-registered EIN is refused as a business-rule
    conflict, and the incumbent row is untouched.

    PRD 3.1 states that the EIN is unique across the registry and that a duplicate
    answers ERR_EIN_ALREADY_REGISTERED. PRD 2.7 places that check in the substantive
    band, after body validation, so a well-formed duplicate is a 422 rather than a 400,
    and PRD 2.6 leaves no partial write behind: the incumbent keeps its own field values
    and no second row appears.

    Design: Corner/errors/a_second_organization_with_the_same_ein_is_rejected
    """
    org_a = fx.create_organization(api, fx.ORG_A)

    validate_error(
        api.create_organization(
            {
                "legal_name": "Riverside Youth Alliance (Delaware)",
                "ein": "11-1111111",
                "state_code": "NY",
                "mission_code": "FS-FOOD_SECURITY",
                "annual_expense_cents": 4000000,
                "unrestricted_net_assets_cents": 1000000,
            },
            PLATFORM_ADMIN,
        ),
        ERR_EIN_ALREADY_REGISTERED,
        422,
    )

    rows, meta = validate_paginated(api.list_organizations(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"the duplicate must not be stored, got {meta}"
    assert [r["id"] for r in rows] == [org_a["id"]], (
        "only the incumbent registration may remain"
    )
    incumbent = validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN))
    assert_field(incumbent, "state_code", "CA")
    assert_field(incumbent, "mission_code", "YM-YOUTH_MENTORING")


def test_an_all_abstain_board_is_rejected(api):
    """An all-abstain board meets quorum yet casts no votes, so the resolution is refused
    for want of a denominator and the deal stays where it was.

    PRD 3.7 derives eligible_seats as seats_total less recusals, quorum_required as
    eligible_seats divided by two rounded up, attendance as votes_for plus votes_against
    plus abstentions, and votes_cast as votes_for plus votes_against with abstentions
    excluded. Eight abstentions on fifteen unrecused seats satisfy the ceiling
    (8 <= 15) and the quorum floor (8 >= 8) and still leave votes_cast at 0, which
    PRD 3.7 refuses with ERR_NO_ELIGIBLE_VOTES because an all-abstain board records no
    decision. PRD 2.6 leaves no row and no version bump behind, so the corrected request
    may reuse the same expected_restructuring_version; six votes to two then yields an
    approval_ratio of 0.7500, which clears the 0.6667 a MERGER requires, so the
    resolution is RECORDED and the deal advances to BOARD_APPROVAL.

    Design: Corner/errors/an_all_abstain_board_is_rejected
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    secretary = make_board_secretary_headers(ctx["org_a"]["id"])
    pinned_version = fx.deal_version(api, deal_id, secretary)

    validate_error(
        api.create_board_approval(
            f.board_approval_payload(
                deal_id,
                pinned_version,
                "INITIATOR",
                seats_total=15,
                recusals=0,
                votes_for=0,
                votes_against=0,
                abstentions=8,
                conflict_disclosures_count=0,
            ),
            secretary,
        ),
        ERR_NO_ELIGIBLE_VOTES,
        422,
    )

    deal = fx.read_deal(api, deal_id)
    assert_status(deal, "STRUCTURE_SELECTED")
    assert_version_is(deal, pinned_version, "restructuring")
    rows, meta = validate_paginated(api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN))
    assert rows == [], f"the refusal must not record a resolution, got {rows!r}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta}"

    approval = validate_success(
        api.create_board_approval(
            f.board_approval_payload(
                deal_id,
                pinned_version,
                "INITIATOR",
                seats_total=15,
                recusals=0,
                votes_for=6,
                votes_against=2,
                abstentions=0,
                conflict_disclosures_count=0,
            ),
            secretary,
        ),
        201,
    )
    assert_decimal_equals(approval["approval_ratio"], 0.75, 4, "approval_ratio")
    assert_field(approval, "decision", "APPROVED")
    assert_status(approval, "RECORDED")
    assert_status(fx.read_deal(api, deal_id), "BOARD_APPROVAL")


def _approval(api, deal_id, approval_id):
    rows, _ = validate_paginated(api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN))
    row = find_by_id(rows, approval_id)
    assert row is not None, f"resolution {approval_id} must remain listed on the deal"
    return row


def test_a_second_certification_of_the_same_approval_is_rejected(api):
    """Certifying an already-certified resolution and rescinding an already-rescinded one
    are both refused, and neither refusal moves a seat.

    PRD 3.7 certifies only a resolution in RECORDED and refuses any other status with
    ERR_INVALID_APPROVAL_STATE, and rescinds only a resolution in CERTIFIED with the
    same code. PRD 3.7 allocates the initiator the governing letter's
    board_seat_split_initiator and the target the remainder of combined_board_seats, so
    a 15-seat letter split 8 leaves the pool empty once both parties certify; rescission
    returns exactly those 7 seats once, zeroes the resolution's allocated_seats and the
    party's governance_seats, and reverts the deal REGULATORY_REVIEW -> BOARD_APPROVAL
    because the both-parties-certified condition no longer holds. PRD 2.8 requires
    reserved_seat_pool plus the allocated seats of every certified resolution to equal
    combined_board_seats at every instant.

    Design: Corner/errors/a_second_certification_of_the_same_approval_is_rejected
    """
    ctx = fx.setup_deal_regulatory_review(api)
    deal_id = ctx["deal"]["id"]
    ba_i, ba_t = ctx["approval_initiator"]["id"], ctx["approval_target"]["id"]
    secretary_a = make_board_secretary_headers(ctx["org_a"]["id"])
    secretary_b = make_board_secretary_headers(ctx["org_b"]["id"])

    assert_status(fx.read_deal(api, deal_id), "REGULATORY_REVIEW")
    assert_field(fx.read_deal(api, deal_id), "reserved_seat_pool", 0)
    assert_seat_ledger_conserved(fx.dossier(api, deal_id))

    validate_error(
        api.certify_board_approval(
            ba_i,
            f.certify_payload(
                fiduciary_memo_ref="MEMO-A-2", certifying_secretary_ref="SEC-A-3"
            ),
            secretary_a,
        ),
        ERR_INVALID_APPROVAL_STATE,
        409,
    )
    initiator = _approval(api, deal_id, ba_i)
    assert_field(initiator, "fiduciary_memo_ref", "MEMO-A-1")
    assert_field(initiator, "allocated_seats", 8)
    assert_field(fx.read_deal(api, deal_id), "reserved_seat_pool", 0)
    assert_seat_ledger_conserved(fx.dossier(api, deal_id))

    rescinded = validate_success(
        api.rescind_board_approval(
            ba_t,
            f.rescind_payload(rescission_reason="Minutes corrected on review"),
            secretary_b,
        ),
        200,
    )
    assert_status(rescinded, "RESCINDED")
    assert_field(rescinded, "allocated_seats", 0)
    deal = fx.read_deal(api, deal_id)
    assert_field(deal, "reserved_seat_pool", 7)
    assert_status(deal, "BOARD_APPROVAL")
    assert_field(
        validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN)),
        "governance_seats",
        0,
    )
    assert_seat_ledger_conserved(fx.dossier(api, deal_id))

    validate_error(
        api.rescind_board_approval(
            ba_t,
            f.rescind_payload(rescission_reason="Filed twice by the clerk"),
            secretary_b,
        ),
        ERR_INVALID_APPROVAL_STATE,
        409,
    )
    assert_field(fx.read_deal(api, deal_id), "reserved_seat_pool", 7)
    assert_seat_ledger_conserved(fx.dossier(api, deal_id))


def test_select_structure_with_a_structure_the_letter_never_proposed_is_rejected(api):
    """A deal may only commit to the structure its executed letter proposed, and the
    mismatch is refused before either fiscal gate is consulted.

    PRD 3.3 states that the chosen structure_type must equal the proposed_structure_type
    of the deal's EXECUTED letter of intent with the highest round_no, and that a
    mismatch answers ERR_STRUCTURE_TYPE_MISMATCH; PRD 2.7 places that check ahead of the
    alignment-rating and reserve-floor gates, so a mismatch on an otherwise fundable
    deal reports the mismatch. PRD 2.6 records nothing on a refusal, so structure_type
    stays null and unrestricted_transfer_value_cents stays 0; on success PRD 3.3 records
    both request fields and advances DILIGENCE_CLOSED -> STRUCTURE_SELECTED.

    Design: Corner/errors/select_structure_with_a_structure_the_letter_never_proposed_is_rejected
    """
    ctx = fx.setup_deal_diligence_closed(api)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])

    validate_error(
        api.select_structure(
            deal_id,
            f.select_structure_payload(structure_type="PARENT_SUBSIDIARY"),
            officer,
        ),
        ERR_STRUCTURE_TYPE_MISMATCH,
        422,
    )

    deal = fx.read_deal(api, deal_id)
    assert_null(deal, "structure_type")
    assert_status(deal, "DILIGENCE_CLOSED")
    assert_money_equals(
        deal["unrestricted_transfer_value_cents"], 0, "unrestricted_transfer_value_cents"
    )

    committed = validate_success(
        api.select_structure(deal_id, f.select_structure_payload(structure_type="MERGER"), officer),
        200,
    )
    assert_field(committed, "structure_type", "MERGER")
    assert_status(committed, "STRUCTURE_SELECTED")


def test_select_structure_on_a_not_viable_rating_is_rejected(api):
    """A NOT_VIABLE diligence-adjusted rating blocks structure selection even when the
    reserve floor is comfortably cleared, and clearing the finding cannot rescue it.

    PRD 3.3 requires the deal's latest DILIGENCE_ADJUSTED snapshot to be rated STRONG or
    MODERATE and answers ERR_ALIGNMENT_RATING_INSUFFICIENT otherwise, and only then
    checks the 3.00-month reserve floor. PRD 3.2 scores unrelated mission codes at 12.00,
    awards 0.00 overlap points when neither party has an admitted program, and awards
    20.00 sustainability points for a reserve of at least three but under six months, so
    the composite is 32.00 and bands below 40.00 as NOT_VIABLE. PRD 3.2 also nets only
    findings still OPEN, RESPONDED or ESCALATED, so the open 1000000 exposure leaves
    82333340 available and a reserve of 4.94 months, while a later snapshot over the
    cleared finding sees 83333340 available and exactly 5.00 months and still scores
    32.00. PRD 3.2 numbers each snapshot one plus the count of prior snapshots of the
    same deal and the same variant, so the second diligence-adjusted snapshot is
    sequence_no 2.

    Design: Corner/errors/select_structure_on_a_not_viable_rating_is_rejected
    """
    ctx = {
        "org_a": fx.create_organization(
            api, dict(fx.ORG_A, unrestricted_net_assets_cents=50000004)
        ),
        "org_b": fx.create_organization(
            api,
            dict(
                fx.ORG_B,
                legal_name="Northshore Meals on Wheels",
                mission_code="FS-FOOD_SECURITY",
                unrestricted_net_assets_cents=33333336,
            ),
        ),
    }
    fx.setup_deal_diligence(api, ctx)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])

    finding = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(deal_id, exposure_cents=1000000), DILIGENCE_LEAD
        ),
        201,
    )
    adj1 = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"), officer
        ),
        201,
    )
    assert_decimal_equals(adj1["mission_alignment_points"], 12.00, 2, "mission_alignment_points")
    assert_decimal_equals(adj1["program_overlap_points"], 0.00, 2, "program_overlap_points")
    assert_decimal_equals(adj1["reserve_months"], 4.94, 2, "reserve_months")
    assert_decimal_equals(adj1["sustainability_points"], 20.00, 2, "sustainability_points")
    assert_decimal_equals(adj1["composite_score"], 32.00, 2, "composite_score")
    assert_field(adj1, "composite_rating", "NOT_VIABLE")

    validate_success(
        api.respond_diligence_request(finding["id"], f.diligence_respond_payload(), officer)
    )
    validate_success(
        api.clear_diligence_request(finding["id"], f.diligence_clear_payload(), DILIGENCE_LEAD_2)
    )
    assert_status(fx.read_deal(api, deal_id), "DILIGENCE_CLOSED")

    validate_error(
        api.select_structure(deal_id, f.select_structure_payload(), officer),
        ERR_ALIGNMENT_RATING_INSUFFICIENT,
        422,
    )

    adj2 = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"), officer
        ),
        201,
    )
    assert_money_equals(
        adj2["available_unrestricted_cents"], 83333340, "available_unrestricted_cents"
    )
    assert_decimal_equals(adj2["reserve_months"], 5.00, 2, "reserve_months")
    assert_decimal_equals(adj2["sustainability_points"], 20.00, 2, "sustainability_points")
    assert_decimal_equals(adj2["composite_score"], 32.00, 2, "composite_score")
    assert_field(adj2, "composite_rating", "NOT_VIABLE")
    assert_field(adj2, "sequence_no", 2)

    validate_error(
        api.select_structure(deal_id, f.select_structure_payload(), officer),
        ERR_ALIGNMENT_RATING_INSUFFICIENT,
        422,
    )
    deal = fx.read_deal(api, deal_id)
    assert_status(deal, "DILIGENCE_CLOSED")
    assert_null(deal, "structure_type")


def test_a_fund_whose_historic_dollar_value_exceeds_its_value_is_rejected(api):
    """A historic dollar value one cent above the fund's own value is refused, while a
    value exactly equal to it is a lawful fully unspendable endowment.

    PRD 2.7 rule 31 and PRD 3.6 both state that historic_dollar_value_cents may not
    exceed principal_cents plus accumulated_appreciation_cents, and that a larger value
    is refused with ERR_HDV_EXCEEDS_FUND_VALUE because the judicial spending-rate slice
    would otherwise be computed against value the fund does not hold. The bound is
    "does not exceed", so 48000001 against 40000000 plus 8000000 is refused and 48000000
    is admitted. PRD 3.6 starts an accepted fund at transfer_status HELD with
    transferable_amount_cents, transferred_amount_cents, retained_amount_cents and
    unwind_count all 0, and PRD 3.1 counts the whole value of a fund that has not moved
    against its holder's restricted_corpus_cents.

    Design: Corner/errors/a_fund_whose_historic_dollar_value_exceeds_its_value_is_rejected
    """
    org_a = fx.create_organization(api, fx.ORG_A)
    payload = f.restricted_fund_payload(
        org_a["id"],
        fund_name="Founders Endowment",
        fund_type="PERM_ENDOWMENT",
        principal_cents=40000000,
        accumulated_appreciation_cents=8000000,
        historic_dollar_value_cents=48000001,
        restriction_purpose_code="SC-SCHOLARSHIPS",
    )

    validate_error(
        api.create_restricted_fund(payload, TRUST_COUNSEL), ERR_HDV_EXCEEDS_FUND_VALUE, 422
    )

    rows, meta = validate_paginated(
        api.list_restricted_funds(TRUST_COUNSEL, {"org_id": org_a["id"]})
    )
    assert rows == [], f"the refused registration must leave no fund, got {rows!r}"
    assert meta["total_count"] == 0, f"total_count expected 0, got {meta}"
    assert_money_equals(
        validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN))[
            "restricted_corpus_cents"
        ],
        0,
        "restricted_corpus_cents",
    )

    payload["historic_dollar_value_cents"] = 48000000
    fund = validate_success(api.create_restricted_fund(payload, TRUST_COUNSEL), 201)
    assert_field(fund, "transfer_status", "HELD")
    assert_money_equals(fund["transferable_amount_cents"], 0, "transferable_amount_cents")
    assert_money_equals(fund["transferred_amount_cents"], 0, "transferred_amount_cents")
    assert_money_equals(fund["retained_amount_cents"], 0, "retained_amount_cents")
    assert_field(fund, "unwind_count", 0)
    assert_money_equals(
        validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN))[
            "restricted_corpus_cents"
        ],
        48000000,
        "restricted_corpus_cents",
    )
