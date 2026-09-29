"""Refusal checks: which code answers an unknown id, which of two competing
refusals speaks, and what a refused call leaves behind."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_score,
    award_payload,
    build_board_approved_with_shared_facility,
    build_agreement,
    build_context,
    build_developer,
    build_disposition_request,
    build_facility_replacement,
    build_negotiation_period,
    build_proposal,
    build_shared_facility,
    build_site,
    build_staging_window,
    create_disposition_request_payload,
    create_maintenance_charge_payload,
    create_proposal_payload,
    decide_staging_window,
    determination_payload,
    execute_agreement_payload,
    maintenance_line_item,
    make_developer_headers,
    read_agreement,
    read_shared_facility,
    read_site,
    replacement_status_payload,
    report_replacement_status,
    staging_decision_payload,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_disposition_payload,
)

MAPLE_SITE = {
    "site_code": "TJD-C-045",
    "name": "Maple Court Parcel",
    "address_line": "45 Maple Ct",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


def _site(site_code: str, name: str, address_line: str) -> dict:
    site = dict(MAPLE_SITE)
    site.update(site_code=site_code, name=name, address_line=address_line)
    return site


UNKNOWN_PATH_IDS = (
    ("get_site", "40000000-0000-4000-8000-000000000001",
     ApiErrorId.SITE_NOT_FOUND),
    ("get_assessment", "40000000-0000-4000-8000-000000000002",
     ApiErrorId.ASSESSMENT_NOT_FOUND),
    ("get_solicitation", "40000000-0000-4000-8000-000000000003",
     ApiErrorId.SOLICITATION_NOT_FOUND),
    ("get_developer", "40000000-0000-4000-8000-000000000004",
     ApiErrorId.DEVELOPER_NOT_FOUND),
    ("get_proposal", "40000000-0000-4000-8000-000000000005",
     ApiErrorId.PROPOSAL_NOT_FOUND),
    ("get_negotiation_period", "40000000-0000-4000-8000-000000000006",
     ApiErrorId.NEGOTIATION_PERIOD_NOT_FOUND),
    ("get_valuation", "40000000-0000-4000-8000-000000000007",
     ApiErrorId.VALUATION_NOT_FOUND),
    ("get_agreement", "40000000-0000-4000-8000-000000000008",
     ApiErrorId.AGREEMENT_NOT_FOUND),
    ("get_disposition_request", "40000000-0000-4000-8000-000000000009",
     ApiErrorId.DISPOSITION_REQUEST_NOT_FOUND),
    ("get_facility_replacement", "40000000-0000-4000-8000-00000000000a",
     ApiErrorId.FACILITY_REPLACEMENT_NOT_FOUND),
    ("get_shared_facility", "40000000-0000-4000-8000-00000000000b",
     ApiErrorId.SHARED_FACILITY_NOT_FOUND),
    ("get_staging_window", "40000000-0000-4000-8000-00000000000c",
     ApiErrorId.STAGING_WINDOW_NOT_FOUND),
)


class TestNotFoundFamily:
    """Twelve single-resource routes, twelve distinct 404 codes."""

    def test_each_route_answers_an_unknown_id_with_its_own_not_found_code(
            self, api, real_estate_officer):
        """PRD §2.9 resolves path segments left to right, "in this order: site,
        then assessment, then solicitation, then proposal, then
        negotiation period, then valuation, then agreement, then disposition
        request, then facility replacement, then shared facility, then staging
        window. The first segment that names a record which does not exist decides
        the response, with its own not-found code: `ERR_SITE_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`,
        `ERR_PROPOSAL_NOT_FOUND`, `ERR_NEGOTIATION_PERIOD_NOT_FOUND`,
        `ERR_VALUATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_DISPOSITION_REQUEST_NOT_FOUND`, `ERR_FACILITY_REPLACEMENT_NOT_FOUND`,
        `ERR_SHARED_FACILITY_NOT_FOUND` or `ERR_STAGING_WINDOW_NOT_FOUND`, all at
        HTTP 404." The developer read is governed by the same rule of PRD §2.11 —
        "Existence of every path-segment record, left to right (§2.9)" — and PRD §5
        registers `ERR_DEVELOPER_NOT_FOUND` at HTTP 404 as the developer's own
        member of that family. PRD §5 also fixes the envelope every one of them
        carries: "Every error response uses the envelope of §2.2, with the
        identifier below in `data.error_id` and a human-readable `message`."

        Design: Corner/errors/corner_unknown_path_ids_return_entity_specific_not_found
        """
        for method_name, unknown_id, expected in UNKNOWN_PATH_IDS:
            response = getattr(api, method_name)(unknown_id, real_estate_officer)

            error = validate_error(response, expected, expected_status=404)
            assert error["error_id"] == expected, method_name


class TestReleaseStateGate:
    """The parcel state gate speaks before the readiness gate it precedes."""

    def test_releasing_a_never_assessed_parcel_reports_the_state_not_the_score(
            self, api, real_estate_officer):
        """PRD §3.1: "Releasing a site for solicitation advances it
        `ASSESSED → SOLICITATION_READY` and bumps its `version` by 1, and is
        refused in two ways: a site whose status is not `ASSESSED` reports
        `ERR_INVALID_SITE_STATE`, and a site whose `readiness_tier` is anything
        other than `READY` reports `ERR_SITE_NOT_READY`." A parcel that has never
        been assessed fails both, and PRD §2.11 fixes which one answers: the
        lifecycle-state checks run "in the order of the state rules listed in §3 —
        site state, then site readiness", and "Nothing later in the order can mask
        something earlier." PRD §3.1 also says why the score is absent: the site's
        readiness fields "are always a copy of the most recently certified
        assessment, and are null whenever no certified assessment exists."

        Design: Corner/errors/corner_release_on_inventoried_site_returns_invalid_site_state
        """
        site = build_site(**_site("TJD-C-046", "Maple Bend Parcel",
                                  "46 Maple Bnd"))
        assert site["status"] == "INVENTORIED"
        assert site["readiness_composite_score"] is None
        assert site["readiness_tier"] is None

        response = api.release_site_for_solicitation(site["id"],
                                                     real_estate_officer)

        error = validate_error(response, ApiErrorId.INVALID_SITE_STATE)
        assert error["error_id"] != ApiErrorId.SITE_NOT_READY
        after = read_site(site["id"])
        assert after["status"] == "INVENTORIED"
        assert after["readiness_composite_score"] is None


class TestAwardBeforeClose:
    """An award needs a closed competition; the same award afterwards runs the
    whole cascade."""

    def test_awarding_an_issued_solicitation_waits_for_the_close(
            self, api, real_estate_officer):
        """PRD §3.4: "Six preconditions are checked. The solicitation must be
        `CLOSED`, otherwise `ERR_SOLICITATION_NOT_CLOSED`." That precondition is
        first, and PRD §2.11 says "Nothing later in the order can mask something
        earlier", so an award aimed at a still-`ISSUED` solicitation reports it
        rather than any later rank or interval complaint. Once closed — "On success
        the solicitation moves `ISSUED → CLOSED` and every responsive proposal is
        assigned a `rank`" — the same award is legal, and PRD §3.4 runs the cascade:
        "The solicitation moves `CLOSED → AWARDED`. The awarded proposal moves
        `SUBMITTED → SELECTED` or `SHORTLISTED → SELECTED` (hop 1)", and "Because
        that period became `ACTIVE`, the site moves
        `SOLICITATION_READY → UNDER_AGREEMENT` with its `version` bumped by 1".

        Design: Corner/errors/corner_award_before_close_then_shortlist_after_award_rejected
        """
        ctx = build_context(stage="PROPOSAL",
                            site_overrides=_site("TJD-C-047",
                                                 "Maple Grove Parcel",
                                                 "47 Maple Grv"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False})
        solicitation_id = ctx["solicitation"]["id"]
        proposal_id = ctx["proposal"]["id"]
        assert ctx["solicitation"]["status"] == "ISSUED"
        assert ctx["proposal"]["status"] == "SUBMITTED"
        payload = award_payload(proposal_id, "2026-08-15", "2027-01-15")

        early = api.award_solicitation(solicitation_id, payload,
                                       real_estate_officer)

        validate_error(early, ApiErrorId.SOLICITATION_NOT_CLOSED)
        closed = validate_success(api.close_solicitation(solicitation_id,
                                                         real_estate_officer))
        assert closed["status"] == "CLOSED"
        awarded = validate_success(api.award_solicitation(solicitation_id,
                                                          payload,
                                                          real_estate_officer))
        assert awarded["status"] == "AWARDED"
        proposal = validate_success(api.get_proposal(proposal_id,
                                                     real_estate_officer))
        assert proposal["status"] == "SELECTED"
        assert read_site(ctx["site"]["id"])["status"] == "UNDER_AGREEMENT"


class TestOffRankAward:
    """Deviating from the agency's own ranking is allowed, but only on the
    record."""

    def test_the_rank_two_proposal_needs_a_written_reason_before_it_can_win(
            self, api, real_estate_officer):
        """PRD §3.4: "The named proposal must have `rank` equal to 1, or else a
        non-empty `deviation_justification` must be present, otherwise
        `ERR_RANK_DEVIATION_UNJUSTIFIED` — the agency may deviate from its own
        ranking, but only on the record." The ranks come from the close: "every
        responsive proposal is assigned a `rank`. The candidate set is exactly those
        proposals whose status is `SUBMITTED` or `SHORTLISTED`", "Candidates are
        ordered by `evaluation_score` descending", and "Ranks are then assigned as
        contiguous integers starting at 1 with no gaps." The two scores follow PRD
        §3.3, whose worked case gives the richer bid "the raw sum is 84.79, the
        penalty is 0.00, and the `evaluation_score` is 84.79", while the leaner bid
        is valued "at its `proposed_annual_rent_cents` capitalised over twenty
        years" for value points of "forty multiplied by that value basis and divided
        by the solicitation's `benchmark_value_cents`" — 32.99 — plus affordable
        points of 17.50 for five points of headroom over the minimum, ridership
        points of 8.00 at "fifty boardings per point" and design points of 12.00 at
        "fifteen hundredths of a point for each point of `design_compliance_score`",
        giving 70.49. On the justified award PRD §3.4 runs the cascade — "The
        awarded proposal moves `SUBMITTED → SELECTED` or `SHORTLISTED → SELECTED`
        (hop 1)", "a new exclusive negotiation period is created over the supplied
        interval with `status` `ACTIVE`, `extension_count` 0" and "every non-awarded
        proposal of *this* solicitation whose status was `SUBMITTED` or
        `SHORTLISTED` also moves to `REJECTED`."

        Design: Corner/errors/corner_award_off_rank_requires_deviation_justification
        """
        ctx = build_context(
            stage="PROPOSAL",
            site_overrides=_site("TJD-C-048", "Maple Yard Parcel",
                                 "48 Maple Yrd"),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"benchmark_value_cents": 48_500_000,
                                    "affordable_housing_min_pct": 15,
                                    "min_proposals_required": 2,
                                    "joint_use_required": False},
            proposal_overrides={"proposed_structure": "GROUND_LEASE",
                                "proposed_annual_rent_cents": 2_400_000,
                                "affordable_units": 50, "total_units": 200,
                                "transit_ridership_uplift": 600,
                                "design_compliance_score": 88,
                                "joint_use_committed": False})
        solicitation_id = ctx["solicitation"]["id"]
        proposal_a = ctx["proposal"]
        developer_b = build_developer(legal_name="Birch Yard Development Co",
                                      contact_email="dev-b@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        proposal_b = validate_success(api.create_proposal(
            solicitation_id,
            create_proposal_payload(developer_b["id"],
                                    proposed_structure="GROUND_LEASE",
                                    proposed_annual_rent_cents=2_000_000,
                                    affordable_units=40, total_units=200,
                                    transit_ridership_uplift=400,
                                    design_compliance_score=80,
                                    joint_use_committed=False),
            make_developer_headers(developer_b["id"])), expected_status=201)
        assert_score(proposal_a["evaluation_score"], 84.79, "evaluation_score")
        assert_score(proposal_b["evaluation_score"], 70.49, "evaluation_score")
        closed = validate_success(api.close_solicitation(solicitation_id,
                                                         real_estate_officer))
        assert closed["responsive_proposal_count"] == 2
        assert validate_success(api.get_proposal(
            proposal_a["id"], real_estate_officer))["rank"] == 1
        assert validate_success(api.get_proposal(
            proposal_b["id"], real_estate_officer))["rank"] == 2

        unjustified = api.award_solicitation(
            solicitation_id, award_payload(proposal_b["id"], "2026-08-15",
                                           "2027-01-15"),
            real_estate_officer)

        validate_error(unjustified, ApiErrorId.RANK_DEVIATION_UNJUSTIFIED)
        awarded = validate_success(api.award_solicitation(
            solicitation_id,
            award_payload(proposal_b["id"], "2026-08-15", "2027-01-15",
                          deviation_justification=(
                              "Rank 1 proposer withdrew financing commitment "
                              "on 2026-08-10")),
            real_estate_officer))
        assert awarded["status"] == "AWARDED"
        assert validate_success(api.get_proposal(
            proposal_b["id"], real_estate_officer))["status"] == "SELECTED"
        assert validate_success(api.get_proposal(
            proposal_a["id"], real_estate_officer))["status"] == "REJECTED"
        periods, meta = validate_paginated(api.list_negotiation_periods(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert meta["total_count"] == 1
        assert periods[0]["proposal_id"] == proposal_b["id"]
        assert periods[0]["status"] == "ACTIVE"
        assert periods[0]["extension_count"] == 0


class TestAgencyReviewIsNotDraftingAndNotApproved:
    """A record parked in review answers both the backwards call and the
    forwards one."""

    def test_neither_a_second_submission_nor_an_early_execution_is_accepted(
            self, api, real_estate_officer):
        """PRD §3.7: "Five checks then run, and their relative order is fixed. The
        agreement's `negotiation_status` must be `DRAFTING`, otherwise
        `ERR_AGREEMENT_NOT_DRAFTING`", so an agreement already advanced by "On
        success the agreement advances `DRAFTING → AGENCY_REVIEW`" cannot be
        submitted twice. Execution is not yet available either: "Four preconditions
        apply, in order: the agreement's `negotiation_status` must be
        `BOARD_APPROVED`, otherwise `ERR_AGREEMENT_NOT_BOARD_APPROVED`; its
        `federal_approval_status` must be `NOT_REQUIRED` or `FTA_APPROVED`,
        otherwise `ERR_FEDERAL_APPROVAL_PENDING`" — the state check is first, so it
        answers even though the federal gate on this federally funded parcel would
        also fail. PRD §3.6 fixes what a refused execution must not have written:
        `execution_date` is among the fields "all of which begin null."

        Design: Corner/errors/corner_second_submit_and_early_execute_rejected_on_agency_review
        """
        ctx = build_context(stage="AGENCY_REVIEW", negotiation_via="direct",
                            period_start_date="2026-08-15",
                            period_end_date="2026-10-15",
                            site_overrides=_site("TJD-C-049",
                                                 "Maple Ridge Parcel",
                                                 "49 Maple Rdg"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        agreement_id = ctx["agreement"]["id"]
        assert ctx["agreement"]["negotiation_status"] == "AGENCY_REVIEW"
        assert ctx["agreement"]["federal_approval_status"] == "NOT_SUBMITTED"

        resubmit = api.submit_agreement_for_review(agreement_id,
                                                   real_estate_officer)

        validate_error(resubmit, ApiErrorId.AGREEMENT_NOT_DRAFTING)
        early_execution = api.execute_agreement(
            agreement_id, execute_agreement_payload("2026-08-25"),
            real_estate_officer)
        error = validate_error(early_execution,
                               ApiErrorId.AGREEMENT_NOT_BOARD_APPROVED)
        assert error["error_id"] != ApiErrorId.FEDERAL_APPROVAL_PENDING
        after = read_agreement(agreement_id)
        assert after["negotiation_status"] == "AGENCY_REVIEW"
        assert after["execution_date"] is None


class TestPendingDispositionGate:
    """One filing at a time, one answer per filing, and the ledger holds
    through both."""

    def test_a_pending_filing_blocks_a_refiling_and_execution_until_it_is_answered(
            self, api, grants_compliance_officer, real_estate_officer):
        """PRD §3.8: "The agreement's `federal_approval_status` must be
        `NOT_SUBMITTED`, otherwise `ERR_FEDERAL_APPROVAL_PENDING` — which is
        precisely what stops a second filing while one is already `SUBMITTED`." The
        same status blocks signing, since PRD §3.7 requires that "its
        `federal_approval_status` must be `NOT_REQUIRED` or `FTA_APPROVED`,
        otherwise `ERR_FEDERAL_APPROVAL_PENDING`". PRD §3.8 pins the pledge — "a
        parcel appraised at 48,500,000 cents with a federal interest of two and a
        half percent has a basis of 1,212,500 cents; an agreement disposing of sixty
        percent of the parcel pledges 727,500 cents and leaves 485,000 cents
        unencumbered" — and the filing's effect: "the request is created with
        `determination` `PENDING` and `determined_at` null, the agreement moves
        `NOT_SUBMITTED → SUBMITTED` on its federal dimension, the site's
        `federal_interest_encumbered_cents` is increased by the pledged amount".
        Only one answer is allowed: "The request must still be `PENDING`, otherwise
        `ERR_DISPOSITION_ALREADY_DETERMINED`", and a favourable one moves "the
        agreement `SUBMITTED → FTA_APPROVED` on its federal dimension" while "The
        site's encumbrance stays exactly where it is — an approved disposition
        consumes the pledged federal interest rather than releasing it." Execution
        then succeeds, and PRD §3.7 keeps the parcel: "Under `GROUND_LEASE` the
        agency keeps the fee, so the site's status is deliberately left at
        `UNDER_AGREEMENT` for the duration of the lease".

        Design: Corner/errors/corner_pending_disposition_blocks_refiling_execution_and_redetermination
        """
        ctx = build_context(stage="BOARD_APPROVED", negotiation_via="award",
                            site_overrides=_site("TJD-C-050",
                                                 "Maple Junction Parcel",
                                                 "50 Maple Jct"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            agreement_overrides={"site_area_share_pct": 60},
                            resolution_number="R-2026-150")
        agreement_id = ctx["agreement"]["id"]
        request = build_disposition_request(agreement_id)
        assert_money(request["federal_interest_amount_cents"], 727_500,
                     "federal_interest_amount_cents")
        assert request["determination"] == "PENDING"
        site_after_filing = read_site(ctx["site"]["id"])
        assert_money(site_after_filing["federal_interest_encumbered_cents"],
                     727_500, "federal_interest_encumbered_cents")
        assert_money(site_after_filing["federal_interest_unencumbered_cents"],
                     485_000, "federal_interest_unencumbered_cents")

        refile = api.create_disposition_request(
            agreement_id, create_disposition_request_payload(
                "Duplicate filing attempt"), grants_compliance_officer)

        validate_error(refile, ApiErrorId.FEDERAL_APPROVAL_PENDING)
        blocked = api.execute_agreement(agreement_id,
                                        execute_agreement_payload("2026-08-25"),
                                        real_estate_officer)
        validate_error(blocked, ApiErrorId.FEDERAL_APPROVAL_PENDING)
        determined = validate_success(api.record_disposition_determination(
            request["id"], determination_payload("APPROVED"),
            grants_compliance_officer))
        assert determined["determination"] == "APPROVED"
        again = api.record_disposition_determination(
            request["id"], determination_payload("APPROVED"),
            grants_compliance_officer)
        validate_error(again, ApiErrorId.DISPOSITION_ALREADY_DETERMINED)
        executed = validate_success(api.execute_agreement(
            agreement_id, execute_agreement_payload("2026-08-25"),
            real_estate_officer))
        assert executed["negotiation_status"] == "EXECUTED"
        assert executed["federal_approval_status"] == "FTA_APPROVED"
        site_after = read_site(ctx["site"]["id"])
        assert_money(site_after["federal_interest_encumbered_cents"], 727_500,
                     "federal_interest_encumbered_cents")
        assert site_after["status"] == "UNDER_AGREEMENT"
        period = validate_success(api.get_negotiation_period(
            ctx["period"]["id"], real_estate_officer))
        assert period["status"] == "CONVERTED"
        requests, meta = validate_paginated(
            api.list_agreement_disposition_requests(agreement_id,
                                                    grants_compliance_officer))
        assert meta["total_count"] == 1
        assert requests[0]["id"] == request["id"]


class TestDecidedStagingWindowIsFinal:
    """A refused window cannot be approved afterwards, and never took a bay."""

    def test_approving_an_already_rejected_window_is_refused_and_takes_no_bays(
            self, api, transit_operations_manager):
        """PRD §3.9: "Both branches require the window to be in `REQUESTED`, an
        already-decided window reporting `ERR_STAGING_WINDOW_NOT_REQUESTED`." The
        rejection wrote nothing to the facility: "`REQUESTED → REJECTED` records the
        supplied `rejection_reason` and touches neither the facility's
        `available_bay_capacity` nor its `version` — a rejected window consumes
        nothing." Only approval spends bays — "`REQUESTED → APPROVED` decreases the
        shared facility's `available_bay_capacity` by the window's `bays_occupied`" —
        so the refused approval leaves the ledger of PRD §3.9 at its registered
        total: `available_bay_capacity` "is the `total_bay_capacity` less the sum of
        `bays_occupied` across that facility's `APPROVED` windows".

        Design: Corner/errors/corner_second_decision_on_decided_staging_window_rejected
        """
        ctx = build_board_approved_with_shared_facility(
            negotiation_via="award",
            site_overrides=_site("TJD-C-051", "Maple Plaza Parcel",
                                 "51 Maple Plz"),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            resolution_number="R-2026-151",
            facility_overrides={"total_bay_capacity": 6})
        facility_id = ctx["facility"]["id"]
        window = build_staging_window(ctx["agreement"]["id"], facility_id,
                                      ctx["developer"]["id"], bays_occupied=2,
                                      purpose="Hoarding and site fencing")
        rejected = decide_staging_window(
            window["id"], "REJECT",
            rejection_reason="Bay layout conflicts with the winter shuttle plan")
        assert rejected["status"] == "REJECTED"
        assert read_shared_facility(facility_id)["available_bay_capacity"] == 6

        response = api.decide_staging_window(window["id"],
                                            staging_decision_payload("APPROVE"),
                                            transit_operations_manager)

        validate_error(response, ApiErrorId.STAGING_WINDOW_NOT_REQUESTED)
        after = validate_success(api.get_staging_window(
            window["id"], transit_operations_manager))
        assert after["status"] == "REJECTED"
        assert read_shared_facility(facility_id)["available_bay_capacity"] == 6


class TestMaintenanceChargeShapeGates:
    """A charge needs at least one line and a forward-running period; the
    accepted one splits per line."""

    def test_an_empty_array_and_a_reversed_period_are_both_refused(
            self, api, transit_operations_manager):
        """PRD §3.9 requires "`period_end` required to be strictly later than
        `period_start`, otherwise `ERR_INVALID_INTERVAL`" and, of the costs, "The
        array must contain at least one entry; an empty array is refused with
        `ERR_EMPTY_LINE_ITEMS`." The accepted charge follows PRD §3.9's allocation:
        "`effective_share_applied` is one whole when the facility's
        `maintenance_responsibility` is `DEVELOPER`, zero when it is `AGENCY`, and
        the facility's `cost_share_pct_developer` as it stands at request time when
        it is `SHARED`", then "each line item's `cost_cents` is multiplied by
        `effective_share_applied` and" rounded half up to a whole cent immediately,
        so that "those rounded per-line amounts are accumulated into
        `developer_share_cents`. `total_cost_cents` is the plain sum of every line
        item's `cost_cents`, and `agency_share_cents` is `total_cost_cents` less
        `developer_share_cents`". Three lines of 41,250 at 0.35 each round to 14,438,
        so the developer owes 43,314 of the 123,750 total and the agency absorbs
        80,436.

        Design: Corner/errors/corner_maintenance_charge_empty_items_and_reversed_period_rejected
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="direct",
                            period_start_date="2026-08-15",
                            period_end_date="2027-01-15",
                            site_overrides=_site("TJD-C-052",
                                                 "Maple Terrace Parcel",
                                                 "52 Maple Ter"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        agreement_id = ctx["agreement"]["id"]
        facility = build_shared_facility(ctx["site"]["id"],
                                         maintenance_responsibility="SHARED",
                                         cost_share_pct_developer=0.35)

        empty = api.create_maintenance_charge(
            facility["id"],
            create_maintenance_charge_payload(agreement_id, [],
                                              period_start="2026-09-01",
                                              period_end="2026-09-30"),
            transit_operations_manager)

        validate_error(empty, ApiErrorId.EMPTY_LINE_ITEMS)
        reversed_period = api.create_maintenance_charge(
            facility["id"],
            create_maintenance_charge_payload(
                agreement_id,
                [maintenance_line_item("Plaza sweeping", 41_250)],
                period_start="2026-09-30", period_end="2026-09-01"),
            transit_operations_manager)
        validate_error(reversed_period, ApiErrorId.INVALID_INTERVAL)
        charge = validate_success(api.create_maintenance_charge(
            facility["id"],
            create_maintenance_charge_payload(
                agreement_id,
                [maintenance_line_item("Plaza sweeping", 41_250),
                 maintenance_line_item("Lighting maintenance", 41_250),
                 maintenance_line_item("Elevator inspection", 41_250)],
                period_start="2026-09-01", period_end="2026-09-30"),
            transit_operations_manager), expected_status=201)
        assert_score(charge["effective_share_applied"], 0.35,
                     "effective_share_applied")
        assert_money(charge["total_cost_cents"], 123_750, "total_cost_cents")
        assert_money(charge["developer_share_cents"], 43_314,
                     "developer_share_cents")
        assert_money(charge["agency_share_cents"], 80_436, "agency_share_cents")
        charges, meta = validate_paginated(api.list_facility_maintenance_charges(
            facility["id"], transit_operations_manager))
        assert meta["total_count"] == 1
        assert charges[0]["id"] == charge["id"]


LOCAL_ONLY_TRANSIT_SITE = {
    "site_code": "TJD-C-053",
    "name": "Maple Depot Parcel",
    "address_line": "53 Maple Dpt",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "LOCAL_ONLY",
    "federal_interest_pct": 0,
    "transit_facility_present": True,
}


class TestDeficientReplacementBlocksExecution:
    """A shortfall on one displaced facility stops the signature, even with a
    sibling delivered in full."""

    def test_the_deficit_blocks_execution_until_a_corrected_capacity_cures_it(
            self, api, real_estate_officer, transit_operations_manager):
        """PRD §3.9 derives the shortfall: "the `capacity_deficit` is derived as the
        amount by which `original_capacity` exceeds `replacement_capacity`, or 0 when
        the replacement is at least as large — never a negative number." It then
        branches on that number: "A report of `COMPLETE` from `INTERIM_IN_PLACE`
        lands on `INTERIM_IN_PLACE → COMPLETE` only when `capacity_deficit` is
        exactly 0", while "When the deficit is greater than 0 the very same report
        lands on `INTERIM_IN_PLACE → DEFICIENT` instead — the status recorded is
        `DEFICIENT`, not the `COMPLETE` that was asked for — and from that moment
        execution of the agreement is blocked with
        `ERR_FACILITY_REPLACEMENT_DEFICIENT`. The deficit is cured by filing a
        corrected `replacement_capacity`, which recomputes `capacity_deficit`; once
        it reaches 0 a fresh report advances `DEFICIENT → COMPLETE`". The sibling
        already satisfies PRD §3.7's presence gate — "if the parcel's
        `transit_facility_present` is true, at least one transit facility replacement
        of this agreement must have reached `INTERIM_IN_PLACE` or `COMPLETE`" — and
        the federal gate is inert because PRD §3.6 says `federal_approval_status`
        "starts at `NOT_REQUIRED` when the site's `federal_interest_pct` is exactly
        0". PRD §3.1's federal penalty of "one tenth of a point for each whole
        percent of `federal_interest_pct` on the parcel" therefore costs this parcel
        nothing, leaving 73.25 less "three points for each recorded encumbrance" at
        70.25, and PRD §3.2 puts the floor at "the appraised value less the
        transit-supportive credit, but never below the federal interest floor".
        Execution then keeps the parcel, since "Under `GROUND_LEASE` the agency keeps
        the fee, so the site's status is deliberately left at `UNDER_AGREEMENT`".

        Design: Corner/errors/corner_deficient_facility_replacement_blocks_execution_until_cured
        """
        ctx = build_context(stage="BOARD_APPROVED", negotiation_via="award",
                            site_overrides=dict(LOCAL_ONLY_TRANSIT_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            resolution_number="R-2026-153")
        agreement_id = ctx["agreement"]["id"]
        site_before = read_site(ctx["site"]["id"])
        assert_score(site_before["readiness_composite_score"], 70.25,
                     "readiness_composite_score")
        assert site_before["readiness_tier"] == "READY"
        assert ctx["agreement"]["federal_approval_status"] == "NOT_REQUIRED"
        assert_money(ctx["valuation"]["permissible_floor_cents"], 36_375_000,
                     "permissible_floor_cents")
        delivered = build_facility_replacement(agreement_id,
                                               facility_type="BUS_BAY",
                                               original_capacity=10,
                                               replacement_capacity=10,
                                               interim_capacity=8)
        report_replacement_status(delivered["id"], "INTERIM_IN_PLACE")
        delivered = report_replacement_status(delivered["id"], "COMPLETE")
        assert delivered["status"] == "COMPLETE"
        assert delivered["capacity_deficit"] == 0
        short = build_facility_replacement(agreement_id,
                                           facility_type="PARK_AND_RIDE",
                                           original_capacity=10,
                                           replacement_capacity=6,
                                           interim_capacity=5)
        report_replacement_status(short["id"], "INTERIM_IN_PLACE")
        short = report_replacement_status(short["id"], "COMPLETE")
        assert short["status"] == "DEFICIENT"
        assert short["capacity_deficit"] == 4

        blocked = api.execute_agreement(agreement_id,
                                        execute_agreement_payload("2026-08-25"),
                                        real_estate_officer)

        validate_error(blocked, ApiErrorId.FACILITY_REPLACEMENT_DEFICIENT)
        cured = validate_success(api.report_facility_replacement_status(
            short["id"],
            replacement_status_payload("COMPLETE", replacement_capacity=10),
            transit_operations_manager))
        assert cured["status"] == "COMPLETE"
        assert cured["capacity_deficit"] == 0
        executed = validate_success(api.execute_agreement(
            agreement_id, execute_agreement_payload("2026-08-25"),
            real_estate_officer))
        assert executed["negotiation_status"] == "EXECUTED"
        assert executed["execution_date"] == "2026-08-25"
        assert read_site(ctx["site"]["id"])["status"] == "UNDER_AGREEMENT"
        period = validate_success(api.get_negotiation_period(
            ctx["period"]["id"], real_estate_officer))
        assert period["status"] == "CONVERTED"


class TestFederalInterestIsSpentOnce:
    """Two deals on one parcel cannot pledge the same federal interest twice."""

    def test_the_second_filing_waits_until_the_first_pledge_is_withdrawn(
            self, api, grants_compliance_officer, real_estate_officer):
        """PRD §3.8: "The slice this filing pledges is
        `federal_interest_amount_cents`: the site's `federal_interest_basis_cents`
        multiplied by the agreement's `site_area_share_pct` and divided by 100,
        rounded half up to a whole cent", and "If the site's
        `federal_interest_unencumbered_cents` is strictly less than that amount, the
        filing is refused with `ERR_FEDERAL_INTEREST_INSUFFICIENT`." The concrete
        figures are the PRD's own: "a parcel appraised at 48,500,000 cents with a
        federal interest of two and a half percent has a basis of 1,212,500 cents; an
        agreement disposing of sixty percent of the parcel pledges 727,500 cents and
        leaves 485,000 cents unencumbered." Withdrawal is the way back: "The request
        moves `PENDING → WITHDRAWN` with `determined_at` stamped, the agreement moves
        `SUBMITTED → NOT_SUBMITTED` on its federal dimension so a corrected filing
        can be made, the site's `federal_interest_encumbered_cents` is decreased and
        its `federal_interest_unencumbered_cents` increased by this request's
        `federal_interest_amount_cents`", and "withdrawal touches only the ledger and
        the federal dimension, and never disturbs the valuation, the staging windows
        or `negotiation_status`."

        Design: Corner/errors/corner_second_filing_exceeding_unencumbered_federal_interest_rejected
        """
        ctx = build_context(stage="AGENCY_REVIEW", negotiation_via="direct",
                            period_start_date="2026-08-15",
                            period_end_date="2026-10-15",
                            site_overrides=_site("TJD-C-054",
                                                 "Maple Wharf Parcel",
                                                 "54 Maple Whf"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False,
                                                 "site_area_share_pct": 60})
        site_id = ctx["site"]["id"]
        assert_money(ctx["site"]["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert_money(ctx["site"]["federal_interest_unencumbered_cents"],
                     1_212_500, "federal_interest_unencumbered_cents")
        developer_b = build_developer(legal_name="Birch Wharf Partners LLC",
                                      contact_email="dev-w@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        proposal_b = build_proposal(ctx["solicitation"]["id"],
                                    developer_b["id"],
                                    joint_use_committed=False)
        period_b = build_negotiation_period(site_id, proposal_b["id"],
                                            "2026-10-16", "2026-12-15")
        agreement_b = build_agreement(site_id, developer_b["id"],
                                      proposal_b["id"], ctx["valuation"]["id"],
                                      joint_use_committed=False,
                                      site_area_share_pct=60)
        agreement_b = submit_agreement(agreement_b["id"])
        assert agreement_b["negotiation_status"] == "AGENCY_REVIEW"
        request_a = build_disposition_request(ctx["agreement"]["id"])
        assert_money(request_a["federal_interest_amount_cents"], 727_500,
                     "federal_interest_amount_cents")
        after_first = read_site(site_id)
        assert_money(after_first["federal_interest_encumbered_cents"], 727_500,
                     "federal_interest_encumbered_cents")
        assert_money(after_first["federal_interest_unencumbered_cents"], 485_000,
                     "federal_interest_unencumbered_cents")

        second = api.create_disposition_request(
            agreement_b["id"], create_disposition_request_payload(
                "Second joint development parcel disposition"),
            grants_compliance_officer)

        validate_error(second, ApiErrorId.FEDERAL_INTEREST_INSUFFICIENT)
        withdrawn = validate_success(api.withdraw_disposition_request(
            request_a["id"],
            withdraw_disposition_payload("First developer paused financing"),
            grants_compliance_officer))
        assert withdrawn["determination"] == "WITHDRAWN"
        assert read_agreement(
            ctx["agreement"]["id"])["federal_approval_status"] == "NOT_SUBMITTED"
        refiled = validate_success(api.create_disposition_request(
            agreement_b["id"], create_disposition_request_payload(
                "Second joint development parcel disposition, refiled"),
            grants_compliance_officer), expected_status=201)
        assert_money(refiled["federal_interest_amount_cents"], 727_500,
                     "federal_interest_amount_cents")
        site_after = read_site(site_id)
        assert_money(site_after["federal_interest_encumbered_cents"], 727_500,
                     "federal_interest_encumbered_cents")
        assert_money(site_after["federal_interest_unencumbered_cents"], 485_000,
                     "federal_interest_unencumbered_cents")
        assert read_agreement(
            agreement_b["id"])["federal_approval_status"] == "SUBMITTED"
        for period_id in (ctx["period"]["id"], period_b["id"]):
            period = validate_success(api.get_negotiation_period(
                period_id, real_estate_officer))
            assert period["status"] == "ACTIVE"


class TestAffordableCommitmentShortfall:
    """The agency will take more affordable housing than was bid, never less."""

    def test_a_short_commitment_is_refused_until_it_matches_the_bid(
            self, api, real_estate_officer):
        """PRD §3.7: "`affordable_units_committed` must be at least the
        `affordable_units` the selected proposal offered, otherwise
        `ERR_AFFORDABLE_COMMITMENT_SHORTFALL` — the agency will accept more
        affordable housing than was bid but never less". Raising the commitment on
        the record is enough, because PRD §3.6 recomputes the money from the stored
        inputs and PRD §3.7 confirms "the three computed money fields
        `capital_credit_cents`, `annual_revenue_to_agency_cents` and
        `consideration_value_cents` are recomputed from the stored inputs so that the
        fiscal tests run against fresh figures". That credit does not move: PRD §3.6
        gives a pre-credit subtotal in the band "at least 2,500,000 but below
        5,000,000 earns eight hundredths", plus the bonus of "If the committed
        affordable share — `affordable_units_committed` divided by `total_units`, as
        a fraction — is at least twenty hundredths, three hundredths are added to the
        rate", and both 45 and 50 units out of 200 clear that share. The accepted submission then advances
        as PRD §3.7 says: "On success the agreement advances
        `DRAFTING → AGENCY_REVIEW`".

        Design: Corner/errors/corner_submit_with_short_affordable_commitment_rejected
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="award",
                            period_start_date="2026-08-15",
                            period_end_date="2027-01-15",
                            site_overrides=_site("TJD-C-055",
                                                 "Maple Landing Parcel",
                                                 "55 Maple Lnd"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"affordable_units": 50,
                                                "total_units": 200,
                                                "joint_use_committed": False},
                            agreement_overrides={"affordable_units_committed": 45,
                                                 "total_units": 200,
                                                 "joint_use_committed": False})
        agreement_id = ctx["agreement"]["id"]
        assert ctx["agreement"]["affordable_units_committed"] == 45
        assert_money(ctx["agreement"]["capital_credit_cents"], 286_000,
                     "capital_credit_cents")

        short = api.submit_agreement_for_review(agreement_id,
                                                real_estate_officer)

        validate_error(short, ApiErrorId.AFFORDABLE_COMMITMENT_SHORTFALL)
        patched = validate_success(api.update_agreement(
            agreement_id, {"affordable_units_committed": 50},
            real_estate_officer))
        assert patched["affordable_units_committed"] == 50
        assert_money(patched["capital_credit_cents"], 286_000,
                     "capital_credit_cents")
        submitted = validate_success(api.submit_agreement_for_review(
            agreement_id, real_estate_officer))
        assert submitted["negotiation_status"] == "AGENCY_REVIEW"
        assert read_agreement(
            agreement_id)["negotiation_status"] == "AGENCY_REVIEW"
