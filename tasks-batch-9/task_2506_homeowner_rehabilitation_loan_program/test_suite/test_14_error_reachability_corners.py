"""Refusals that must each answer in their own voice: lookups, four-eyes, ceilings."""

import pytest

from test_helpers import (
    LOAN_OFFICER_USER_ID,
    NON_EXISTENT_UUID,
    PROGRAM_MANAGER_USER_ID,
    api_client,
    assert_draw_request,
    assert_program_year_ledger_conserved,
    assert_unset,
    create_bid_payload,
    create_complaint_payload,
    create_draw_request_payload,
    create_loan_payload,
    make_applicant_headers,
    make_contractor_headers,
    make_loan_officer_headers,
    make_program_manager_headers,
    make_rehab_specialist_headers,
    record_lien_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INSPECTOR,
    LOAN_OFFICER,
    PROGRAM_MANAGER,
    REHAB,
    approve_draw,
    approve_write_up,
    award,
    build_contractor,
    build_draw_request,
    complete_draw_inspection,
    place_bid,
    record_lien,
    refresh_application,
    refresh_bid,
    refresh_contractor,
    refresh_draw,
    refresh_loan,
    refresh_program_year,
    refresh_solicitation,
    refresh_write_up,
    setup_case,
    tabulate,
)

# One read per addressed family, each against an identifier that resolves to
# nothing, paired with the identifier the failure must carry.
LOOKUPS = (
    ("get_program_year", "ERR_PROGRAM_YEAR_NOT_FOUND"),
    ("get_applicant", "ERR_APPLICANT_NOT_FOUND"),
    ("get_application", "ERR_APPLICATION_NOT_FOUND"),
    ("get_inspection", "ERR_INSPECTION_NOT_FOUND"),
    ("get_write_up", "ERR_WRITE_UP_NOT_FOUND"),
    ("get_work_item", "ERR_WORK_ITEM_NOT_FOUND"),
    ("get_contractor", "ERR_CONTRACTOR_NOT_FOUND"),
    ("get_solicitation", "ERR_SOLICITATION_NOT_FOUND"),
    ("get_bid", "ERR_BID_NOT_FOUND"),
    ("get_loan", "ERR_LOAN_NOT_FOUND"),
    ("get_draw_request", "ERR_DRAW_NOT_FOUND"),
    ("get_change_order", "ERR_CHANGE_ORDER_NOT_FOUND"),
    ("get_complaint", "ERR_COMPLAINT_NOT_FOUND"),
)

DUAL_USER_ID = "u-dual"
SECOND_WINDOW = {
    "proposed_start_date": "2026-09-07",
    "proposed_end_date": "2026-11-01",
}
THIRD_WINDOW = {
    "proposed_start_date": "2026-09-06",
    "proposed_end_date": "2026-11-15",
}


class TestEveryLookupFamilyHasItsOwnNotFound:
    """Thirteen families, thirteen identifiers, one empty database."""

    @pytest.mark.parametrize(
        "read_method, expected_error_id",
        LOOKUPS,
        ids=[error_id for _, error_id in LOOKUPS],
    )
    def test_each_addressed_family_answers_with_its_own_identifier(
        self, read_method, expected_error_id
    ):
        """The failure names the entity the path addresses, not a neighbouring one.

        PRD: "Every identifier in the request path resolves to an existing row —
        otherwise the entity-specific 404 identifier listed in §2.4. Applies to
        every endpoint that has a path parameter."

        Design: Corner/errors/all_thirteen_entity_lookup_errors_are_reachable_and_distinct_not_found
        """
        response = getattr(api_client, read_method)(
            NON_EXISTENT_UUID, PROGRAM_MANAGER
        )

        error = validate_error(response, expected_error_id, 404)
        assert error["message"].strip(), (
            f"{expected_error_id} carries a readable explanation, got "
            f"{error['message']!r}"
        )

    def test_the_identifiers_are_distinct_and_a_filter_miss_is_not_a_failure(self):
        """No shared not-found identifier, and an unmatched filter is an empty page.

        PRD: "The 404 error identifier is selected by the entity the unresolved
        segment addresses: `ERR_PROGRAM_YEAR_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_WRITE_UP_NOT_FOUND`,
        `ERR_WORK_ITEM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
        `ERR_SOLICITATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`,
        `ERR_DRAW_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND` or
        `ERR_COMPLAINT_NOT_FOUND`."

        PRD: "The `meta` object of a collection response carries `limit`,
        `offset`, `total_count` and `has_more`; `total_count` is the number of rows
        matching the filters before pagination is applied, and `has_more` is true
        when rows remain beyond the current window."

        Design: Corner/errors/all_thirteen_entity_lookup_errors_are_reachable_and_distinct_not_found
        """
        seen = []
        for read_method, expected_error_id in LOOKUPS:
            error = validate_error(
                getattr(api_client, read_method)(NON_EXISTENT_UUID, PROGRAM_MANAGER),
                expected_error_id,
                404,
            )
            seen.append(error["error_id"])

        assert len(set(seen)) == len(LOOKUPS), (
            "Each family answers with a distinct identifier rather than one "
            f"shared not-found identifier, got {sorted(set(seen))}"
        )

        bid_rows, bid_meta = validate_paginated(
            api_client.list_bids(PROGRAM_MANAGER, {"solicitation_id": NON_EXISTENT_UUID})
        )
        draw_rows, draw_meta = validate_paginated(
            api_client.list_draw_requests(
                PROGRAM_MANAGER, {"loan_id": NON_EXISTENT_UUID}
            )
        )

        assert bid_rows == []
        assert bid_meta["total_count"] == 0, (
            "A filter that matches nothing is an empty page, not a failure, got "
            f"{bid_meta['total_count']}"
        )
        assert bid_meta["has_more"] is False
        assert draw_rows == []
        assert draw_meta["total_count"] == 0


class TestWarrantyGateBeforeCloseOut:
    """A case that was never closed out has no warranty window to invoke."""

    def test_a_complaint_on_a_case_that_was_never_closed_out_is_refused(
        self, application, contractor
    ):
        """No warranty period at all is treated as outside the window, not before it.

        PRD: "Filing is accepted only while the logical clock is at or before the
        case's `warranty_expires_at`: a complaint filed exactly at that instant is
        still accepted, one instant later is refused with `ERR_WARRANTY_EXPIRED`,
        and a complaint against a case that has never been closed out and
        therefore has no warranty period is likewise refused with
        `ERR_WARRANTY_EXPIRED`."

        PRD: "An `Applicant` may file a complaint on their own case, and a
        `RehabSpecialist` may file one on the household's behalf."

        Design: Corner/errors/filing_a_complaint_before_close_out_is_refused_because_no_warranty_exists_yet
        """
        assert application["workflow_state"] == "INTAKE"
        assert_unset(application, "warranty_expires_at")
        payload = create_complaint_payload(
            contractor["id"],
            application["id"],
            description="Roof flashing leaks at the valley",
        )

        response = api_client.create_complaint(payload, REHAB)

        validate_error(response, "ERR_WARRANTY_EXPIRED", 409)
        firm = refresh_contractor(contractor["id"])
        assert firm["open_complaint_count"] == 0, (
            "The refused filing does not reach the firm's counters, got "
            f"{firm['open_complaint_count']}"
        )
        assert firm["performance_score"] == 100
        assert firm["approved_list_status"] == "APPROVED"
        _, meta = validate_paginated(
            api_client.list_complaints(REHAB, {"contractor_id": contractor["id"]})
        )
        assert meta["total_count"] == 0, (
            f"Nothing is filed against the firm, got {meta['total_count']}"
        )

        household_filing = api_client.create_complaint(
            payload, make_applicant_headers(application["applicant_id"])
        )

        validate_error(household_filing, "ERR_WARRANTY_EXPIRED", 409)
        assert_unset(refresh_application(application["id"]), "warranty_expires_at")


class TestFourEyesOnApprovals:
    """Both four-eyes pairings are decided on the acting user, never on the role."""

    def test_the_preparer_cannot_approve_their_own_write_up(self):
        """One user wearing both hats is refused; a different approver succeeds.

        PRD: "The program enforces two four-eyes pairings, and both are checked
        against `X-User-ID`."

        PRD: "Approval carries two additional gates beyond the write-up's own
        state: the case must currently be in `INSPECTED`, and the approver must not
        be the preparer — an `X-User-ID` equal to `prepared_by_user_id` is refused
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/the_same_user_cannot_prepare_and_approve_one_write_up
        """
        case = setup_case(
            stage="writeup_submitted",
            prepared_by=make_rehab_specialist_headers(DUAL_USER_ID),
        )
        write_up_id = case["write_up"]["id"]
        application_id = case["application"]["id"]
        assert case["write_up"]["state"] == "SUBMITTED"
        assert case["write_up"]["prepared_by_user_id"] == DUAL_USER_ID

        response = api_client.approve_write_up(
            write_up_id, make_program_manager_headers(DUAL_USER_ID)
        )

        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
        refused = refresh_write_up(write_up_id)
        assert refused["state"] == "SUBMITTED", (
            f"The refused approval leaves the scope submitted, got {refused['state']}"
        )
        assert_unset(refused, "approved_by_user_id")
        assert refresh_application(application_id)["workflow_state"] == "INSPECTED"

        approved = approve_write_up(write_up_id)

        assert approved["state"] == "APPROVED", (
            "The identical approval by a different user succeeds, got "
            f"{approved['state']}"
        )
        assert approved["approved_by_user_id"] == PROGRAM_MANAGER_USER_ID
        assert (
            refresh_application(application_id)["workflow_state"] == "WRITEUP_APPROVED"
        )

    def test_the_inspector_cannot_approve_the_draw_they_passed(self):
        """The second pairing is measured against the draw inspection's inspector.

        PRD: "The approver must not be the inspector: the acting `X-User-ID` must
        differ from the `performed_by_user_id` of the `DRAW` inspection that passed
        this draw, or the approval is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/the_same_user_cannot_prepare_and_approve_one_write_up
        """
        case = setup_case(stage="lien_recorded")
        draw = build_draw_request(
            case["loan"]["id"],
            case["contractor"]["id"],
            requested_amount_cents=1_000_000,
        )
        inspection = complete_draw_inspection(
            case["application"]["id"], draw["id"], headers=INSPECTOR
        )
        inspector_user_id = inspection["performed_by_user_id"]
        assert refresh_draw(draw["id"])["status"] == "INSPECTION_PASSED"

        response = api_client.approve_draw_request(
            draw["id"], make_loan_officer_headers(inspector_user_id)
        )

        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
        refused = refresh_draw(draw["id"])
        assert refused["status"] == "INSPECTION_PASSED"
        assert_unset(refused, "approved_by_user_id")
        assert_unset(refused, "approved_amount_cents")

        approved = approve_draw(draw["id"])

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == LOAN_OFFICER_USER_ID, (
            "A loan officer who did not inspect may certify the draw, got "
            f"{approved['approved_by_user_id']}"
        )
        assert approved["approved_amount_cents"] == 1_000_000
        assert approved["retainage_cents"] == 100_000
        assert approved["net_payment_cents"] == 900_000


class TestDrawGatesFireInTheirOwnRight:
    """The state gate and the fiscal gate on a draw are separately reachable."""

    def test_no_draw_exists_until_the_lien_secures_the_contract(self):
        """A structured note is not yet a payable contract, whatever the amount.

        PRD: "A draw against a loan whose lien is not recorded — that is, a loan
        without `lien_recorded_at` set and whose `status` is neither
        `LIEN_RECORDED` nor `DISBURSING` — is refused with
        `ERR_LIEN_NOT_RECORDED`."

        PRD: "The recording fee is then disbursed immediately: the note's
        `disbursed_cents` increases by `lien_recording_fee_cents`, the program
        year's `committed_amount_cents` decreases by that same fee, and its
        `disbursed_amount_cents` increases by that same fee — so the fee passes
        straight through the committed bucket into the disbursed bucket in one
        step."

        Design: Corner/errors/both_gates_on_draw_creation_fire_in_their_own_right
        """
        case = setup_case(stage="structured")
        loan_id = case["loan"]["id"]
        contractor_id = case["contractor"]["id"]

        response = api_client.create_draw_request(
            create_draw_request_payload(
                loan_id, contractor_id, requested_amount_cents=1_000_000
            ),
            case["contractor_headers"],
        )

        validate_error(response, "ERR_LIEN_NOT_RECORDED", 409)
        assert refresh_loan(loan_id)["status"] == "STRUCTURED"
        _, meta = validate_paginated(
            api_client.list_draw_requests(LOAN_OFFICER, {"loan_id": loan_id})
        )
        assert meta["total_count"] == 0, (
            f"The refused request stores no draw, got {meta['total_count']}"
        )

        secured = record_lien(loan_id)

        assert secured["status"] == "LIEN_RECORDED"
        assert secured["approved_project_cost_cents"] == 2_000_000
        assert secured["lien_recording_fee_cents"] == 15_000
        assert secured["principal_cents"] == 2_015_000
        assert secured["contract_earned_cents"] == 0
        assert secured["disbursed_cents"] == 15_000, (
            "Recording pays the financed fee straight out, got "
            f"{secured['disbursed_cents']}"
        )

        accepted = build_draw_request(
            loan_id, contractor_id, requested_amount_cents=1_000_000
        )

        assert_draw_request(accepted)
        assert accepted["status"] == "SUBMITTED", (
            f"The identical request is accepted once secured, got {accepted['status']}"
        )

    def test_the_contract_balance_gate_measures_the_contract_not_the_principal(self):
        """2,100,000 and even the 2,015,000 principal exceed the 2,000,000 contract.

        PRD: "And the draw must fit inside the construction contract:
        `requested_amount_cents` must be at or below the loan's
        `approved_project_cost_cents` less its `contract_earned_cents`, so a draw
        for exactly the remaining balance is allowed while anything larger is
        refused with `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE`."

        Design: Corner/errors/both_gates_on_draw_creation_fire_in_their_own_right
        """
        case = setup_case(stage="lien_recorded")
        application_id = case["application"]["id"]
        loan_id = case["loan"]["id"]
        contractor_id = case["contractor"]["id"]
        assert case["loan"]["approved_project_cost_cents"] == 2_000_000
        assert case["loan"]["principal_cents"] == 2_015_000

        over_contract = build_draw_request(
            loan_id, contractor_id, requested_amount_cents=2_100_000
        )
        complete_draw_inspection(application_id, over_contract["id"])

        validate_error(
            api_client.approve_draw_request(over_contract["id"], LOAN_OFFICER),
            "ERR_DRAW_EXCEEDS_CONTRACT_BALANCE",
            422,
        )

        at_principal = build_draw_request(
            loan_id, contractor_id, requested_amount_cents=2_015_000
        )
        complete_draw_inspection(application_id, at_principal["id"])

        validate_error(
            api_client.approve_draw_request(at_principal["id"], LOAN_OFFICER),
            "ERR_DRAW_EXCEEDS_CONTRACT_BALANCE",
            422,
        )
        assert refresh_draw(over_contract["id"])["status"] == "INSPECTION_PASSED"
        assert refresh_draw(at_principal["id"])["status"] == "INSPECTION_PASSED"
        loan = refresh_loan(loan_id)
        assert loan["contract_earned_cents"] == 0, (
            "Neither refusal certifies any work, got "
            f"{loan['contract_earned_cents']}"
        )
        assert loan["disbursed_cents"] == 15_000
        assert loan["retainage_held_cents"] == 0
        assert loan["status"] == "LIEN_RECORDED"

    def test_a_draw_for_exactly_the_remaining_balance_is_certified(self):
        """The whole 2,000,000 contract in one draw sits inside the gate.

        PRD: "On an ordinary draw, `retainage_cents` is ten percent of the approved
        amount, rounded half up to whole cents, and `net_payment_cents` is the
        approved amount less that retainage."

        Design: Corner/errors/both_gates_on_draw_creation_fire_in_their_own_right
        """
        case = setup_case(stage="lien_recorded")
        draw = build_draw_request(
            case["loan"]["id"],
            case["contractor"]["id"],
            requested_amount_cents=2_000_000,
        )
        complete_draw_inspection(case["application"]["id"], draw["id"])

        approved = validate_success(
            api_client.approve_draw_request(draw["id"], LOAN_OFFICER), 200
        )

        assert approved["status"] == "APPROVED", (
            "A draw for exactly the remaining balance is allowed, got "
            f"{approved['status']}"
        )
        assert approved["approved_amount_cents"] == 2_000_000
        assert approved["retainage_cents"] == 200_000
        assert approved["net_payment_cents"] == 1_800_000


class TestTwoFiscalCeilings:
    """The per-household maximum and the annual allocation guard different steps."""

    def test_the_allocation_is_tested_when_the_lien_is_recorded(self):
        """A note may exist that the year's remaining allocation cannot support.

        PRD: "Recording proceeds only from a note in `STRUCTURED`, only from a
        compliance posture of `CLEAR` or `CLEARED_WITH_PROTOCOL` — with the two
        clearance identifiers of §3.4 guarding the other postures — and only when
        the program year's `uncommitted_amount_cents` is at least the note's
        `principal_cents`; an insufficient balance is refused with
        `ERR_ALLOCATION_INSUFFICIENT`."

        Design: Corner/errors/the_program_year_allocation_and_the_per_loan_cap_are_separate_ceilings
        """
        case = setup_case(
            stage="structured",
            program_year_overrides={"allocation_budget_cents": 1_500_000},
        )
        loan_id = case["loan"]["id"]
        assert case["loan"]["principal_cents"] == 2_015_000
        assert case["program_year"]["uncommitted_amount_cents"] == 1_500_000

        response = api_client.record_lien(
            loan_id, record_lien_payload(), LOAN_OFFICER
        )

        validate_error(response, "ERR_ALLOCATION_INSUFFICIENT", 409)
        refused = refresh_loan(loan_id)
        assert refused["status"] == "STRUCTURED", (
            f"The note is not secured, got {refused['status']}"
        )
        assert_unset(refused, "lien_recorded_at")
        assert_unset(refused, "lien_position")
        assert refused["disbursed_cents"] == 0
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 0, (
            "The failed recording commits nothing, not even the fee, got "
            f"{program_year['committed_amount_cents']}"
        )
        assert program_year["disbursed_amount_cents"] == 0
        assert program_year["uncommitted_amount_cents"] == 1_500_000
        assert_program_year_ledger_conserved(program_year)
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "AWARDED"
        )

    def test_the_per_household_maximum_is_tested_when_the_note_is_structured(self):
        """A 2,000,000 contract cannot be financed under a 1,900,000 per-unit cap.

        PRD: "The awarded amount is first tested against the program year's
        per-household maximum: an awarded bid greater than `max_loan_amount_cents`
        cannot be financed at all and is refused with `ERR_LOAN_LIMIT_EXCEEDED`."

        PRD: "Note the deliberate ordering of the three fiscal gates on loan
        structuring and lien recording: the per-household maximum (priority 20) is
        tested when the loan is structured, while allocation sufficiency (priority
        21) is tested only when the lien is recorded, so a loan may exist as a
        structured note that the allocation cannot yet support."

        Design: Corner/errors/the_program_year_allocation_and_the_per_loan_cap_are_separate_ceilings
        """
        case = setup_case(
            stage="awarded",
            program_year_overrides={"max_loan_amount_cents": 1_900_000},
        )
        application_id = case["application"]["id"]
        assert case["solicitation"]["status"] == "AWARDED", (
            "The award itself is not guarded by the per-household maximum"
        )

        response = api_client.create_loan(
            create_loan_payload(
                application_id, structure_type="DEFERRED", forgiveness_term_months=60
            ),
            LOAN_OFFICER,
        )

        validate_error(response, "ERR_LOAN_LIMIT_EXCEEDED", 422)
        assert refresh_solicitation(case["solicitation"]["id"])["status"] == "AWARDED"
        assert refresh_application(application_id)["workflow_state"] == "AWARDED"
        _, meta = validate_paginated(
            api_client.list_loans(LOAN_OFFICER, {"application_id": application_id})
        )
        assert meta["total_count"] == 0, (
            f"No note is written for the case, got {meta['total_count']}"
        )
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 0
        assert program_year["uncommitted_amount_cents"] == 50_000_000


class TestBiddingGatesEachAnswerSeparately:
    """One solicitation, three refusals, each with its own identifier."""

    @pytest.fixture
    def two_bid_solicitation(self):
        """An OPEN solicitation requiring two bids and holding one 2,000,000 bid."""
        return setup_case(
            stage="bids_placed", solicitation_overrides={"min_bids_required": 2}
        )

    def test_tabulating_below_the_minimum_leaves_the_solicitation_open(
        self, two_bid_solicitation
    ):
        """One bid of the two required is refused without closing the window.

        PRD: "Tabulation requires that the solicitation's `bid_count` be at least
        its `min_bids_required`; otherwise the request is refused with
        `ERR_INSUFFICIENT_BIDS` and the solicitation stays `OPEN` so that further
        bids can still arrive."

        Design: Corner/errors/the_three_bidding_gates_each_answer_with_their_own_error
        """
        case = two_bid_solicitation
        solicitation_id = case["solicitation"]["id"]
        assert case["solicitation"]["min_bids_required"] == 2
        assert case["solicitation"]["bid_count"] == 1

        response = api_client.tabulate_solicitation(solicitation_id, REHAB)

        validate_error(response, "ERR_INSUFFICIENT_BIDS", 409)
        solicitation = refresh_solicitation(solicitation_id)
        assert solicitation["status"] == "OPEN", (
            f"The window stays open for further bids, got {solicitation['status']}"
        )
        assert solicitation["bid_count"] == 1
        assert solicitation["responsive_bid_count"] == 0
        assert refresh_bid(case["bid"]["id"])["status"] == "SUBMITTED", (
            "The refused tabulation classifies nothing"
        )
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_OPEN"
        )

    def test_a_second_live_bid_from_the_same_firm_is_refused(
        self, two_bid_solicitation
    ):
        """The one-live-bid rule is per firm, so a second firm is still welcome.

        PRD: "One live bid per firm per solicitation is allowed: a firm that
        already holds a bid on that solicitation in `SUBMITTED`, `RESPONSIVE`,
        `NON_RESPONSIVE` or `AWARDED` is refused with `ERR_DUPLICATE_BID`, while a
        bid previously rejected by a reopen, or withdrawn by the program, does not
        block a fresh submission."

        Design: Corner/errors/the_three_bidding_gates_each_answer_with_their_own_error
        """
        case = two_bid_solicitation
        solicitation_id = case["solicitation"]["id"]
        contractor_id = case["contractor"]["id"]

        response = api_client.create_bid(
            create_bid_payload(
                solicitation_id,
                contractor_id,
                amount_cents=1_950_000,
                **SECOND_WINDOW,
            ),
            make_contractor_headers(contractor_id),
        )

        validate_error(response, "ERR_DUPLICATE_BID", 409)
        assert refresh_solicitation(solicitation_id)["bid_count"] == 1, (
            "The undercutting second bid is not counted"
        )
        rows, meta = validate_paginated(
            api_client.list_bids(REHAB, {"solicitation_id": solicitation_id})
        )
        assert [row["id"] for row in rows] == [case["bid"]["id"]]
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 2_000_000

        second_firm = build_contractor(legal_name="Borough Builders Inc")
        accepted = place_bid(
            solicitation_id,
            second_firm["id"],
            amount_cents=1_950_000,
            **THIRD_WINDOW,
        )

        assert accepted["status"] == "SUBMITTED", (
            "A different firm at the same figure is accepted, got "
            f"{accepted['status']}"
        )
        assert refresh_solicitation(solicitation_id)["bid_count"] == 2

    def test_only_a_responsive_bid_can_be_awarded(self, two_bid_solicitation):
        """The out-of-band bid is refused at award even though it is the only other one.

        PRD: "The named bid must be in `RESPONSIVE` and must belong to the
        addressed solicitation, otherwise the request is refused with
        `ERR_BID_NOT_RESPONSIVE` — a non-responsive, rejected or program-withdrawn
        bid can never be awarded."

        Design: Corner/errors/the_three_bidding_gates_each_answer_with_their_own_error
        """
        case = two_bid_solicitation
        solicitation_id = case["solicitation"]["id"]
        second_firm = build_contractor(legal_name="Borough Builders Inc")
        over_ceiling = place_bid(
            solicitation_id,
            second_firm["id"],
            amount_cents=2_420_001,
            **THIRD_WINDOW,
        )

        tabulated = tabulate(solicitation_id)

        assert tabulated["status"] == "TABULATED"
        assert tabulated["bid_count"] == 2
        assert tabulated["responsive_bid_count"] == 1
        assert refresh_bid(case["bid"]["id"])["status"] == "RESPONSIVE"
        assert refresh_bid(over_ceiling["id"])["status"] == "NON_RESPONSIVE"

        response = api_client.award_solicitation(
            solicitation_id, {"bid_id": over_ceiling["id"]}, PROGRAM_MANAGER
        )

        validate_error(response, "ERR_BID_NOT_RESPONSIVE", 422)
        refused = refresh_solicitation(solicitation_id)
        assert refused["status"] == "TABULATED", (
            f"The refused award leaves the solicitation tabulated, got {refused['status']}"
        )
        assert_unset(refused, "award_bid_id")
        assert_unset(refresh_application(case["application"]["id"]), "awarded_contractor_id")

        awarded = award(solicitation_id, case["bid"]["id"])

        assert awarded["status"] == "AWARDED"
        assert awarded["award_bid_id"] == case["bid"]["id"]
        application = refresh_application(case["application"]["id"])
        assert application["workflow_state"] == "AWARDED"
        assert application["awarded_contractor_id"] == case["contractor"]["id"]
