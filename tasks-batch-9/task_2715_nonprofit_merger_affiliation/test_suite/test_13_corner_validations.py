"""Corner-case validation tests for the nonprofit merger and affiliation API.

Every test in this module asserts one validation rule of the PRD: the exact
error_id the request admission ladder of PRD 2.7 selects when several rules
apply, the boundary value a threshold rule must accept, and the derived state a
refusal must leave untouched. Money is always integer cents and every
precondition is built through the API, because the server is restarted and the
database emptied before each individual test.
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
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_CONFLICT_DISCLOSURE_MISSING,
    ERR_FUND_NOT_DEAL_PARTY_ASSET,
    ERR_INTEGRATION_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_JUDICIAL_ORDER_REQUIRED,
    ERR_RESTRICTED_ASSETS_UNRESOLVED,
    ERR_RESTRUCTURING_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SELF_RESTRUCTURING,
    ERR_VOTE_TALLY_EXCEEDS_SEATS,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_money_equals,
    assert_null,
    assert_status,
    assert_three_fractional_digits,
)
from test_helpers.constants import DEFAULT_CLOCK_ISO
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def _error_body(response):
    """The error envelope's data block, for the error_id / message shape checks."""
    return response.json()["data"]


def test_self_restructuring_is_refused_and_persists_nothing(api):
    """Naming the same organization as both parties of a deal is refused with
    ERR_SELF_RESTRUCTURING and no Restructuring row is created.

    PRD 3.2 states that "The two organizations must be different - naming the same
    organization twice is refused with ERR_SELF_RESTRUCTURING". Because both
    references resolve to a real organization, the existence rule of PRD 2.7 rule 4
    is satisfied and the request is well formed, so the 422 business rule at PRD 2.7
    rule 23 is the one that speaks. PRD 2.5 adds that "A request refused by any
    validation ... increments nothing and mutates nothing", so the deal list must
    still be empty afterwards.

    Design: Corner/validations/a_restructuring_of_an_organization_with_itself_is_refused
    """
    org_a = fx.create_organization(api, fx.ORG_A)
    officer = make_strategy_officer_headers(org_a["id"])

    response = api.create_restructuring(
        f.restructuring_payload(org_a["id"], org_a["id"], confidentiality_tier="STANDARD"),
        officer,
    )
    validate_error(response, ERR_SELF_RESTRUCTURING)

    body = _error_body(response)
    assert body["error_id"], "the error envelope must carry a non-empty error_id"
    assert body["message"], "the error envelope must carry a non-empty message"

    rows, meta = validate_paginated(
        api.list_restructurings(
            officer, {"initiator_org_id": org_a["id"], "limit": 100, "offset": 0}
        )
    )
    assert rows == [], f"the refused self-deal must not be persisted, got {rows!r}"
    assert meta["total_count"] == 0, (
        f"total_count must be 0 after the refusal, got {meta['total_count']}"
    )


def test_historic_dollar_value_equal_to_the_fund_value_is_accepted(api):
    """A historic dollar value exactly equal to principal plus appreciation is
    accepted, and the judicial release still frees the truncated seven percent slice.

    PRD 3.6 states that "The historic dollar value may not exceed principal_cents
    plus accumulated_appreciation_cents", so a value equal to that sum satisfies the
    rule guarded at PRD 2.7 rule 31 and the registration must succeed. PRD 3.6 then
    fixes the judicial release for a PERM_ENDOWMENT as "the excess of the fund value
    over historic_dollar_value_cents, floored at 0 ... plus a capped slice equal to
    seven percent of historic_dollar_value_cents, that slice being truncated toward
    zero": 0 + 4340000 on a fund worth 62000000. PRD 3.1 makes the holder's
    restricted_corpus_cents the full value of a fund that is not TRANSFERRED.

    Design: Corner/validations/a_historic_dollar_value_equal_to_the_fund_value_is_accepted
    """
    org_a = fx.create_organization(api, fx.ORG_A)

    fund_payload = f.restricted_fund_payload(
        org_a["id"],
        fund_name="Underwater Legacy Endowment",
        fund_type="PERM_ENDOWMENT",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=62000000,
        restriction_purpose_code="SC-SCHOLARSHIP",
        restriction_conflict=True,
        donor_of_record_reachable=False,
    )
    fund = validate_success(api.create_restricted_fund(fund_payload, TRUST_COUNSEL), 201)
    assert_money_equals(
        fund["historic_dollar_value_cents"], 62000000, "historic_dollar_value_cents"
    )

    # An unreachable donor of record may be taken straight to court on the
    # DONOR_UNREACHABLE basis (PRD 3.6).
    validate_success(
        api.file_petition(
            fund["id"],
            f.file_petition_payload(
                petition_basis="DONOR_UNREACHABLE", court_docket_no="SUP-CT-2026-0708"
            ),
            TRUST_COUNSEL,
        )
    )
    modified = validate_success(
        api.record_court_decision(
            fund["id"], f.court_decision_payload("GRANTED"), TRUST_COUNSEL
        )
    )
    assert_status(modified, "MODIFIED", "transfer_status")
    assert_money_equals(
        modified["transferable_amount_cents"], 4340000, "transferable_amount_cents"
    )

    org_row = validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN))
    assert_money_equals(
        org_row["restricted_corpus_cents"], 62000000, "restricted_corpus_cents"
    )


def test_role_check_precedes_body_validation_which_precedes_existence(api):
    """The admission ladder answers the forbidden role first, the malformed body
    second and the unresolvable deal reference only last.

    PRD 2.7 evaluates "strictly in ascending order and short-circuits on the first
    violation": rule 1 authentication, rule 2 "The supplied role is authorized for
    the target endpoint per §4 - otherwise ERR_ROLE_NOT_PERMITTED", rule 3 "required
    fields are present and non-null ... otherwise ERR_INVALID_REQUEST", and rule 5
    "The Restructuring named by a path segment or by the restructuring_id body field
    exists, otherwise ERR_RESTRUCTURING_NOT_FOUND". PRD 4 authorizes only
    DiligenceLead on POST /diligence-requests, and PRD 3.4 makes summary a required
    field of that create.

    Design: Corner/validations/role_check_precedes_body_validation_which_precedes_existence
    """
    ghost_deal_id = NON_EXISTENT_UUID
    ghost_org_id = "11111111-1111-4111-8111-111111111111"

    body_missing_summary = {
        "restructuring_id": ghost_deal_id,
        "workstream": "FINANCE",
        "severity": "HIGH",
        "exposure_cents": 100000,
    }

    # Three defects at once: forbidden role, missing summary, unresolvable deal.
    role_response = api.create_diligence_request(
        body_missing_summary, make_strategy_officer_headers(ghost_org_id)
    )
    validate_error(role_response, ERR_ROLE_NOT_PERMITTED)

    # Role defect removed: the body defect now speaks.
    body_response = api.create_diligence_request(body_missing_summary, DILIGENCE_LEAD)
    validate_error(body_response, ERR_INVALID_REQUEST)

    # Body defect removed: the unresolvable deal reference finally speaks.
    complete_body = f.diligence_request_payload(
        ghost_deal_id,
        summary="Placeholder finding against a deal that does not exist",
        exposure_cents=100000,
    )
    missing_response = api.create_diligence_request(complete_body, DILIGENCE_LEAD)
    validate_error(missing_response, ERR_RESTRUCTURING_NOT_FOUND)

    for response in (role_response, body_response, missing_response):
        payload = _error_body(response)
        assert payload["error_id"], "every refusal must carry a non-empty error_id"
        assert payload["message"], "every refusal must carry a non-empty message"


def test_a_third_organizations_fund_cannot_be_transferred_under_this_deal(api):
    """A fund whose holder is neither party of the deal is refused with
    ERR_FUND_NOT_DEAL_PARTY_ASSET and no corpus moves.

    PRD 3.6 requires that "The fund's org_id must be one of the deal's two party
    organizations and the counterparty must be the other, else
    ERR_FUND_NOT_DEAL_PARTY_ASSET", and PRD 2.7 rule 26 places that check ahead of
    the authority rule at rule 30 - which this CONSENT_GRANTED fund would in any
    case satisfy. PRD 3.6 also derives the deal posture from its party funds alone,
    so a deal whose party-fund set is empty stays NOT_ASSESSED.

    Design: Corner/validations/a_fund_held_by_a_third_organization_cannot_be_transferred_under_this_deal
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    assert_status(ctx["deal"], "STRUCTURE_SELECTED")

    org_c = fx.create_organization(
        api,
        f.organization_payload(
            legal_name="Delta Regional Food Bank",
            ein="33-3333333",
            state_code="CA",
            mission_code="FS-FOOD_BANK",
            annual_expense_cents=60000000,
            unrestricted_net_assets_cents=12000000,
        ),
    )
    fund_c = fx.setup_fund_consent_granted(
        api,
        org_c["id"],
        fund_name="Delta Pantry Expansion Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=9000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="PA-PANTRY",
        restriction_conflict=False,
        donor_of_record_reachable=True,
    )
    assert_status(fund_c, "CONSENT_GRANTED", "transfer_status")

    response = api.transfer_restricted_fund(
        fund_c["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
    )
    validate_error(response, ERR_FUND_NOT_DEAL_PARTY_ASSET)

    fund_after = validate_success(api.get_restricted_fund(fund_c["id"], TRUST_COUNSEL))
    assert_status(fund_after, "CONSENT_GRANTED", "transfer_status")
    assert_null(fund_after, "transferred_to_org_id")
    assert_null(fund_after, "transfer_restructuring_id")

    for org_id, expected in (
        (org_c["id"], 9000000),
        (ctx["org_a"]["id"], 0),
        (ctx["org_b"]["id"], 0),
    ):
        org_row = validate_success(api.get_organization(org_id, PLATFORM_ADMIN))
        assert_money_equals(
            org_row["restricted_corpus_cents"], expected, f"restricted_corpus_cents of {org_id}"
        )

    deal_after = fx.read_deal(api, deal_id)
    assert_field(deal_after, "restricted_asset_posture", "NOT_ASSESSED")


def test_the_logical_clock_refuses_to_move_backwards(api):
    """The logical clock rejects an earlier instant with ERR_CLOCK_NOT_MONOTONIC while
    accepting a re-set to the instant it already holds.

    PRD 2.4 states that "The server's startup default clock value is exactly
    2026-08-01T00:00:00Z", that "The clock is monotonic - a requested value earlier
    than the value currently held is rejected with ERR_CLOCK_NOT_MONOTONIC", and that
    "the response reports the new current_utc alongside the previous_utc it
    replaced". PRD 2.7 rule 51 phrases the accepted case inclusively: "A requested
    logical clock value is at least the value currently held". Timestamps render with
    exactly three fractional digits per PRD 2.4.

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards
    """
    first = validate_success(api.set_clock(f.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN))
    assert_field(first, "current_utc", "2026-09-01T00:00:00.000Z")
    assert_field(first, "previous_utc", DEFAULT_CLOCK_ISO)
    assert_three_fractional_digits(first["current_utc"], "current_utc")
    assert_three_fractional_digits(first["previous_utc"], "previous_utc")

    validate_error(
        api.set_clock(f.clock_payload("2026-08-15T00:00:00Z"), PLATFORM_ADMIN),
        ERR_CLOCK_NOT_MONOTONIC,
    )

    # The comparison is >= and not >, so re-setting the held value is accepted.
    third = validate_success(api.set_clock(f.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN))
    assert_field(third, "current_utc", "2026-09-01T00:00:00.000Z")
    assert_field(third, "previous_utc", "2026-09-01T00:00:00.000Z")


def test_consummation_waits_for_every_integration_task_to_reach_a_terminal_status(api):
    """Consummation is refused with ERR_INTEGRATION_INCOMPLETE while any integration
    task is still PLANNED, and succeeds once the last task turns terminal.

    PRD 3.8 states that at closing "every integration task of the deal must be
    COMPLETE or CANCELLED; a task still PLANNED, HELD or IN_PROGRESS blocks the close
    with ERR_INTEGRATION_INCOMPLETE" - an aggregate over the children, not a count.
    PRD 3.8 also fixes the closing rewrite: "a MERGER makes the initiator SURVIVOR
    and the target DISSOLVED", while only a PARENT_SUBSIDIARY transaction sets
    parent_org_id on the absorbed organization.

    Design: Corner/validations/consummation_waits_for_every_integration_task_to_reach_a_terminal_status
    """
    ctx = fx.setup_deal_integration(api, legal_costs_cents=1000000)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])
    assert_status(ctx["filing"], "APPROVED")
    assert_status(ctx["deal"], "INTEGRATION")

    task_one = fx.create_task(
        api,
        deal_id,
        workstream="STAFFING",
        crew_code="CREW-HR",
        title="Merge the payroll calendars",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-10",
    )
    task_two = fx.create_task(
        api,
        deal_id,
        workstream="BRANDING",
        crew_code="CREW-COMMS",
        title="Retire the target wordmark",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-05",
    )

    fx.complete_task(api, task_one["id"])

    closing = f.consummate_payload(closing_memo_ref="CLOSE-2026-0001")
    validate_error(api.consummate(deal_id, closing, officer), ERR_INTEGRATION_INCOMPLETE)
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")

    fx.complete_task(api, task_two["id"])
    for task_id in (task_one["id"], task_two["id"]):
        task_row = validate_success(api.get_integration_task(task_id, INTEGRATION_MANAGER))
        assert_status(task_row, "COMPLETE")

    closed = validate_success(api.consummate(deal_id, closing, officer))
    assert_status(closed, "CONSUMMATED")

    org_a_after = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b_after = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_field(org_a_after, "affiliation_role", "SURVIVOR")
    assert_field(org_b_after, "affiliation_role", "DISSOLVED")
    assert_null(org_b_after, "parent_org_id")


def test_donor_consent_transfer_is_refused_only_for_the_conflicting_restriction(api):
    """Two identically consented funds diverge at transfer: the unconflicted one
    moves, the conflicting one is refused with ERR_JUDICIAL_ORDER_REQUIRED.

    PRD 3.6 states that "A conflicting restriction does not block the solicitation
    itself - the donor is entitled to be asked ... it blocks only the later
    consent-based transfer", and that "A fund whose restriction_conflict is true may
    not move on a DONOR_CONSENT basis at all and answers ERR_JUDICIAL_ORDER_REQUIRED"
    (PRD 2.7 rule 29). PRD 3.6 fixes the consent release at "principal_cents plus
    accumulated_appreciation_cents" and derives the deal posture as
    RESTRICTED_PENDING while the unresolved count is greater than zero.

    Design: Corner/validations/donor_consent_transfer_is_refused_only_for_the_conflicting_restriction
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a_id = ctx["org_a"]["id"]

    fund_clean = fx.create_fund(
        api,
        org_a_id,
        fund_name="Clean Restriction Program Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        historic_dollar_value_cents=0,
        restriction_purpose_code="AF-AFTERSCHOOL",
        restriction_conflict=False,
        donor_of_record_reachable=True,
    )
    fund_conflicted = fx.create_fund(
        api,
        org_a_id,
        fund_name="Conflicting Purpose Program Fund",
        fund_type="TEMP_RESTRICTED",
        principal_cents=8000000,
        accumulated_appreciation_cents=0,
        historic_dollar_value_cents=0,
        restriction_purpose_code="CO-COUNTY_ONLY",
        restriction_conflict=True,
        donor_of_record_reachable=True,
    )

    # The conflict does not block the solicitation of either donor.
    validate_success(
        api.seek_consent(
            fund_clean["id"], f.seek_consent_payload(consent_method="WRITTEN"), TRUST_COUNSEL
        )
    )
    validate_success(
        api.seek_consent(
            fund_conflicted["id"],
            f.seek_consent_payload(consent_method="ELECTRONIC"),
            TRUST_COUNSEL,
        )
    )
    granted_clean = validate_success(
        api.record_consent(fund_clean["id"], f.record_consent_payload("GRANTED"), TRUST_COUNSEL)
    )
    granted_conflicted = validate_success(
        api.record_consent(
            fund_conflicted["id"], f.record_consent_payload("GRANTED"), TRUST_COUNSEL
        )
    )
    assert_money_equals(
        granted_clean["transferable_amount_cents"], 62000000, "transferable_amount_cents"
    )
    assert_money_equals(
        granted_conflicted["transferable_amount_cents"], 8000000, "transferable_amount_cents"
    )

    transferred = validate_success(
        api.transfer_restricted_fund(
            fund_clean["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
        )
    )
    assert_status(transferred, "TRANSFERRED", "transfer_status")

    validate_error(
        api.transfer_restricted_fund(
            fund_conflicted["id"], f.transfer_payload(deal_id, "DONOR_CONSENT"), TRUST_COUNSEL
        ),
        ERR_JUDICIAL_ORDER_REQUIRED,
    )
    conflicted_after = validate_success(
        api.get_restricted_fund(fund_conflicted["id"], TRUST_COUNSEL)
    )
    assert_status(conflicted_after, "CONSENT_GRANTED", "transfer_status")

    org_a_after = validate_success(api.get_organization(org_a_id, PLATFORM_ADMIN))
    org_b_after = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_money_equals(
        org_a_after["restricted_corpus_cents"], 8000000, "initiator restricted_corpus_cents"
    )
    assert_money_equals(
        org_b_after["restricted_corpus_cents"], 62000000, "target restricted_corpus_cents"
    )

    deal_after = fx.read_deal(api, deal_id)
    assert_field(deal_after, "unresolved_restricted_fund_count", 1)
    assert_field(deal_after, "restricted_asset_posture", "RESTRICTED_PENDING")


def test_the_consummation_gate_reads_a_posture_that_an_unwind_reverted(api):
    """Unwinding a transferred fund reverts the deal posture and the very same
    consummation request is then refused with ERR_RESTRICTED_ASSETS_UNRESOLVED.

    PRD 3.8 requires at closing that "The deal's restricted_asset_posture must be
    NOT_ASSESSED ... or CLEARED; no party fund may remain in HELD, CONSENT_SOUGHT,
    CONSENT_DENIED, CONSENT_GRANTED, PETITION_FILED or MODIFIED, and a violation
    answers ERR_RESTRICTED_ASSETS_UNRESOLVED" (PRD 2.7 rule 46). PRD 3.6 states that
    an unwind returns a DONOR_CONSENT transfer "TRANSFERRED -> CONSENT_GRANTED",
    restores both parties' restricted_corpus_cents and reverts the posture "CLEARED
    -> RESTRICTED_PENDING", while a re-transfer flips it back at the moment the
    unresolved count reaches zero. PRD 3.7 fixes the recited asset value as
    unrestricted_transfer_value_cents plus the transferred fund amounts, and the
    statutory waiting period of a NOTICE at twenty calendar days.

    Design: Corner/validations/the_consummation_gate_reads_a_posture_that_an_unwind_reverted
    """
    ctx = fx.setup_deal_regulatory_review(api)
    deal_id = ctx["deal"]["id"]
    officer = make_strategy_officer_headers(ctx["org_a"]["id"])
    assert_status(ctx["deal"], "REGULATORY_REVIEW")

    fund = fx.setup_fund_consent_granted(api, ctx["org_a"]["id"])
    fx.transfer_fund(api, fund["id"], deal_id, "DONOR_CONSENT")

    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(deal_id, state_code="CA", filing_type="NOTICE", legal_costs_cents=1000000),
            TRUST_COUNSEL,
        ),
        201,
    )
    assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        262000000,
        "transferred_charitable_asset_value_cents",
    )
    assert_field(filing, "statutory_waiting_days", 20)
    validate_success(
        api.record_ag_decision(filing["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR)
    )
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")

    unwound = validate_success(
        api.unwind_restricted_fund(
            fund["id"],
            f.unwind_payload(unwind_reason="Counsel re-opened the purpose analysis before closing"),
            TRUST_COUNSEL,
        )
    )
    assert_status(unwound, "CONSENT_GRANTED", "transfer_status")
    assert_field(unwound, "unwind_count", 1)

    org_a_after = validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN))
    org_b_after = validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN))
    assert_money_equals(
        org_a_after["restricted_corpus_cents"], 62000000, "initiator restricted_corpus_cents"
    )
    assert_money_equals(
        org_b_after["restricted_corpus_cents"], 0, "target restricted_corpus_cents"
    )
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "RESTRICTED_PENDING")

    closing = f.consummate_payload(closing_memo_ref="CLOSE-2026-0002")
    validate_error(api.consummate(deal_id, closing, officer), ERR_RESTRICTED_ASSETS_UNRESOLVED)
    assert_status(fx.read_deal(api, deal_id), "INTEGRATION")

    retransferred = fx.transfer_fund(api, fund["id"], deal_id, "DONOR_CONSENT")
    assert_money_equals(
        retransferred["transferred_amount_cents"], 62000000, "transferred_amount_cents"
    )
    assert_field(fx.read_deal(api, deal_id), "restricted_asset_posture", "CLEARED")

    closed = validate_success(api.consummate(deal_id, closing, officer))
    assert_status(closed, "CONSUMMATED")
    assert_field(
        validate_success(api.get_organization(ctx["org_a"]["id"], PLATFORM_ADMIN)),
        "affiliation_role",
        "SURVIVOR",
    )
    assert_field(
        validate_success(api.get_organization(ctx["org_b"]["id"], PLATFORM_ADMIN)),
        "affiliation_role",
        "DISSOLVED",
    )


def test_the_tally_ceiling_is_checked_before_the_quorum_floor(api):
    """Minutes whose attendance exceeds the eligible seats are refused with
    ERR_VOTE_TALLY_EXCEEDS_SEATS even though the same figures clear quorum.

    PRD 3.5 states that the fiduciary checks "speak in exactly this sequence:
    conflict_disclosures_count must be at least recusals ...; attendance must not
    exceed eligible_seats, else ERR_VOTE_TALLY_EXCEEDS_SEATS; attendance must be at
    least quorum_required, else ERR_QUORUM_NOT_MET", which PRD 2.7 fixes as rules 36,
    37 and 38. With seats_total 15 and recusals 1 the eligible seats are 14 and the
    quorum is 7, so an attendance of 15 violates only the ceiling. PRD 2.5 adds that
    a refused request "increments nothing and mutates nothing", so the identical
    version pin still holds for the corrected tally, whose ratio is 10/14 = 0.7143
    and therefore APPROVED against a MERGER's 0.6667.

    Design: Corner/validations/the_tally_ceiling_is_checked_before_the_quorum_floor
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    secretary = make_board_secretary_headers(ctx["org_a"]["id"])
    pinned_version = fx.deal_version(api, deal_id)

    impossible_minutes = f.board_approval_payload(
        deal_id, pinned_version, "INITIATOR", abstentions=1
    )
    validate_error(
        api.create_board_approval(impossible_minutes, secretary), ERR_VOTE_TALLY_EXCEEDS_SEATS
    )

    rows, meta = validate_paginated(api.list_deal_board_approvals(deal_id, PLATFORM_ADMIN))
    assert rows == [], f"the refused resolution must not be persisted, got {rows!r}"
    assert meta["total_count"] == 0, (
        f"total_count must be 0 after the refusal, got {meta['total_count']}"
    )
    assert_status(fx.read_deal(api, deal_id), "STRUCTURE_SELECTED")

    corrected_minutes = f.board_approval_payload(
        deal_id, pinned_version, "INITIATOR", abstentions=0
    )
    approval = validate_success(api.create_board_approval(corrected_minutes, secretary), 201)
    assert_field(approval, "eligible_seats", 14)
    assert_field(approval, "quorum_required", 7)
    assert_field(approval, "votes_cast", 14)
    assert_decimal_equals(approval["approval_ratio"], 0.7143, 4, "approval_ratio")
    assert_field(approval, "decision", "APPROVED")


def test_every_recused_seat_needs_a_disclosed_conflict(api):
    """Recusing more directors than the conflict disclosures on file is refused with
    ERR_CONFLICT_DISCLOSURE_MISSING even though the vote itself is sound.

    PRD 3.5 requires that "conflict_disclosures_count must be at least recusals,
    since every recused seat must be backed by a disclosed conflict in the fiduciary
    record, else ERR_CONFLICT_DISCLOSURE_MISSING", and PRD 2.7 rule 36 places that
    check ahead of the tally, quorum and eligible-vote rules. With seats_total 15 and
    recusals 3 the eligible seats are 12, the quorum is 6 and the attendance of 10
    yields a ratio of 8/10 = 0.8000, so documenting the third conflict changes nothing
    about the vote and the identical tally is recorded as RECORDED, per PRD 3.5's
    "RECORDED when decision is APPROVED".

    Design: Corner/validations/every_recused_seat_needs_a_disclosed_conflict
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    secretary = make_board_secretary_headers(ctx["org_a"]["id"])
    pinned_version = fx.deal_version(api, deal_id)

    undocumented = f.board_approval_payload(
        deal_id,
        pinned_version,
        "INITIATOR",
        recusals=3,
        votes_for=8,
        votes_against=2,
        abstentions=0,
        conflict_disclosures_count=2,
    )
    validate_error(
        api.create_board_approval(undocumented, secretary), ERR_CONFLICT_DISCLOSURE_MISSING
    )

    documented = f.board_approval_payload(
        deal_id,
        pinned_version,
        "INITIATOR",
        recusals=3,
        votes_for=8,
        votes_against=2,
        abstentions=0,
        conflict_disclosures_count=3,
    )
    approval = validate_success(api.create_board_approval(documented, secretary), 201)
    assert_field(approval, "eligible_seats", 12)
    assert_field(approval, "quorum_required", 6)
    assert_field(approval, "votes_cast", 10)
    assert_decimal_equals(approval["approval_ratio"], 0.8000, 4, "approval_ratio")
    assert_field(approval, "decision", "APPROVED")
    assert_status(approval, "RECORDED")
    assert_field(approval, "conflict_disclosures_count", 3)
