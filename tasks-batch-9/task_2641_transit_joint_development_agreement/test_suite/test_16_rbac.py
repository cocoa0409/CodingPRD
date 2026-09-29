"""Role checks: the duties each role holds alone, the reads they all share, and
the identity rules that outlast the role names."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    award_solicitation,
    board_approve_payload,
    build_agreement,
    build_assessment,
    build_context,
    build_developer,
    build_shared_facility,
    build_valuation,
    certify_valuation,
    clock_payload,
    close_solicitation,
    create_facility_replacement_payload,
    create_maintenance_charge_payload,
    create_proposal_payload,
    create_shared_facility_payload,
    create_staging_window_payload,
    create_valuation_payload,
    execute_agreement_payload,
    maintenance_line_item,
    make_board_secretary_headers,
    make_developer_headers,
    make_real_estate_officer_headers,
    read_agreement,
    read_shared_facility,
    read_site,
    replacement_status_payload,
    request_revision_payload,
    set_logical_clock,
    shortlist_proposal,
    staging_decision_payload,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    NO_AUTH_HEADERS,
)

WILLOW_SITE = {
    "site_code": "TJD-C-060",
    "name": "Willow Loop Parcel",
    "address_line": "60 Willow Lp",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "LOCAL_ONLY",
    "federal_interest_pct": 0,
    "transit_facility_present": True,
}

XERIC_SITE = {
    "site_code": "TJD-C-061",
    "name": "Xeric Garden Parcel",
    "address_line": "61 Xeric Gd",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestEveryRoleHoldsItsOwnDuty:
    """One parcel carried from intake to signature, each hop by the role that
    owns it."""

    def test_each_role_completes_the_operations_reserved_to_it(
            self, api, real_estate_officer, board_secretary,
            transit_operations_manager):
        """PRD §2.1 splits the duties: "A `RealEstateOfficer` is agency real estate
        office staff: they own the site inventory, readiness assessments,
        solicitations, developer registration, proposal shortlisting, awards,
        exclusive negotiation periods, and the drafting, submission and execution of
        agreements. A `ValuationOfficer` is independent appraisal staff who record
        fair market value and certify the permissible transfer floor", "A
        `BoardSecretary` is the board clerk who records the board's revision requests
        and approvals", "A `TransitOperationsManager` owns transit facility
        replacement, shared facility registration, staging window decisions and
        maintenance cost allocation", and "A `SystemAdmin` operates the deterministic
        logical clock that every deadline and expiry rule reads." The board's two
        answers are PRD §3.7's: a revision request "advances the agreement
        `AGENCY_REVIEW → REVISION_REQUESTED`", and approval "advances the agreement
        `AGENCY_REVIEW → BOARD_APPROVED`". PRD §3.6 closes the loop: "an amendment
        applied to a `REVISION_REQUESTED` agreement advances it
        `REVISION_REQUESTED → DRAFTING`, closing the negotiation cycle
        `AGENCY_REVIEW → REVISION_REQUESTED → DRAFTING → AGENCY_REVIEW`." On the
        operations side PRD §3.9 allows "`PLANNED → INTERIM_IN_PLACE`",
        "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`", and "Closing an
        `APPROVED` window moves it `APPROVED → CLOSED`"; three maintenance lines of
        41,250 at a `cost_share_pct_developer` of 0.35 split 43,314 to the developer
        and 80,436 to the agency under the waterfall of PRD §3.9. Execution then runs
        the `GROUND_LEASE` branch of PRD §3.7: "the site's status is deliberately
        left at `UNDER_AGREEMENT` for the duration of the lease".

        Design: Corner/rbac/corner_every_role_performs_its_own_exclusive_operations
        """
        ctx = build_context(stage="PROPOSAL",
                            site_overrides=dict(WILLOW_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False})
        site_id = ctx["site"]["id"]
        assert ctx["assessment"]["status"] == "CERTIFIED"
        assert ctx["site"]["status"] == "SOLICITATION_READY"
        assert shortlist_proposal(ctx["proposal"]["id"])["status"] == "SHORTLISTED"
        assert close_solicitation(ctx["solicitation"]["id"])["status"] == "CLOSED"
        awarded = award_solicitation(ctx["solicitation"]["id"],
                                    ctx["proposal"]["id"], "2026-08-15",
                                    "2027-01-15")
        assert awarded["status"] == "AWARDED"
        periods, _ = validate_paginated(api.list_negotiation_periods(
            real_estate_officer, params={"site_id": site_id, "limit": 10,
                                         "offset": 0}))
        assert periods[0]["status"] == "ACTIVE"
        valuation = certify_valuation(build_valuation(site_id)["id"])
        assert valuation["status"] == "CERTIFIED"
        agreement = build_agreement(site_id, ctx["developer"]["id"],
                                    ctx["proposal"]["id"], valuation["id"],
                                    joint_use_committed=False)
        agreement_id = agreement["id"]
        assert submit_agreement(agreement_id)["negotiation_status"] == \
            "AGENCY_REVIEW"

        returned = validate_success(api.request_agreement_revision(
            agreement_id,
            request_revision_payload("Board asks for a rent escalator schedule"),
            board_secretary))

        assert returned["negotiation_status"] == "REVISION_REQUESTED"
        assert returned["revision_notes"] == \
            "Board asks for a rent escalator schedule"
        amended = validate_success(api.update_agreement(
            agreement_id, {"base_rent_cents": 2_000_000}, real_estate_officer))
        assert amended["negotiation_status"] == "DRAFTING"
        resubmitted = validate_success(api.submit_agreement_for_review(
            agreement_id, real_estate_officer))
        assert resubmitted["negotiation_status"] == "AGENCY_REVIEW"
        approved = validate_success(api.board_approve_agreement(
            agreement_id, board_approve_payload("R-2026-151"), board_secretary))
        assert approved["negotiation_status"] == "BOARD_APPROVED"
        assert approved["board_resolution_number"] == "R-2026-151"
        replacement = validate_success(api.create_facility_replacement(
            agreement_id,
            create_facility_replacement_payload(facility_type="BUS_BAY",
                                                original_capacity=10,
                                                replacement_capacity=10,
                                                interim_capacity=8,
                                                milestone_date="2027-06-30"),
            transit_operations_manager), expected_status=201)
        interim = validate_success(api.report_facility_replacement_status(
            replacement["id"],
            replacement_status_payload("INTERIM_IN_PLACE", interim_capacity=8),
            transit_operations_manager))
        assert interim["status"] == "INTERIM_IN_PLACE"
        facility = validate_success(api.create_shared_facility(
            site_id,
            create_shared_facility_payload(facility_type="BUS_BAY",
                                           total_bay_capacity=6,
                                           maintenance_responsibility="SHARED",
                                           cost_share_pct_developer=0.35),
            transit_operations_manager), expected_status=201)
        developer_headers = make_developer_headers(ctx["developer"]["id"])
        seen = validate_success(api.get_shared_facility(facility["id"],
                                                        developer_headers))
        assert seen["available_bay_capacity"] == 6
        window = validate_success(api.create_staging_window(
            create_staging_window_payload(agreement_id, facility["id"],
                                          seen["version"],
                                          start_at="2026-08-16T08:00:00Z",
                                          end_at="2026-08-18T08:00:00Z",
                                          bays_occupied=3,
                                          purpose="Crane pad and hoarding"),
            developer_headers), expected_status=201)
        assert window["status"] == "REQUESTED"
        decided = validate_success(api.decide_staging_window(
            window["id"], staging_decision_payload("APPROVE"),
            transit_operations_manager))
        assert decided["status"] == "APPROVED"
        closed_window = validate_success(api.close_staging_window(
            window["id"], transit_operations_manager))
        assert closed_window["status"] == "CLOSED"
        charge = validate_success(api.create_maintenance_charge(
            facility["id"],
            create_maintenance_charge_payload(
                agreement_id,
                [maintenance_line_item("Bay sweeping", 41_250),
                 maintenance_line_item("Lighting maintenance", 41_250),
                 maintenance_line_item("Signage repair", 41_250)],
                period_start="2026-08-01", period_end="2026-08-31"),
            transit_operations_manager), expected_status=201)
        assert_money(charge["developer_share_cents"], 43_314,
                     "developer_share_cents")
        assert_money(charge["agency_share_cents"], 80_436, "agency_share_cents")
        complete = validate_success(api.report_facility_replacement_status(
            replacement["id"], replacement_status_payload("COMPLETE"),
            transit_operations_manager))
        assert complete["status"] == "COMPLETE"
        executed = validate_success(api.execute_agreement(
            agreement_id, execute_agreement_payload("2026-08-25"),
            real_estate_officer))
        assert executed["negotiation_status"] == "EXECUTED"
        assert read_site(site_id)["status"] == "UNDER_AGREEMENT"
        period = validate_success(api.get_negotiation_period(
            periods[0]["id"], real_estate_officer))
        assert period["status"] == "CONVERTED"
        assert read_shared_facility(facility["id"])["available_bay_capacity"] == 6


class TestReadsAreSharedByEveryRole:
    """The read surface belongs to all seven roles, the clock operator
    included."""

    def test_all_seven_roles_see_the_same_parcel_list_and_agreement(
            self, api, real_estate_officer, valuation_officer, board_secretary,
            grants_compliance_officer, transit_operations_manager,
            system_admin):
        """PRD §2.1: "All seven roles may call every read endpoint." That includes
        the operator whose only write duty is the clock — "A `SystemAdmin` operates
        the deterministic logical clock that every deadline and expiry rule reads" —
        and the entity-backed partner, since PRD §2.1 limits ownership to writes and
        single-proposal reads: "these ownership rules bind only callers acting under
        the `Developer` role". PRD §3.6 fixes what they all see on a fresh draft: "A
        newly drafted agreement opens with `negotiation_status` `DRAFTING`".

        Design: Corner/rbac/corner_all_roles_share_every_get_endpoint
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="direct",
                            site_overrides=dict(XERIC_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False})
        developer_headers = make_developer_headers(ctx["developer"]["id"])
        every_role = (real_estate_officer, valuation_officer, board_secretary,
                      grants_compliance_officer, transit_operations_manager,
                      developer_headers, system_admin)

        for headers in every_role:
            sites, meta = validate_paginated(api.list_sites(
                headers, params={"limit": 10, "offset": 0}))

            assert meta["total_count"] == 1
            assert sites[0]["site_code"] == "TJD-C-061"
        for headers in (system_admin, developer_headers):
            agreement = validate_success(api.get_agreement(
                ctx["agreement"]["id"], headers))
            assert agreement["negotiation_status"] == "DRAFTING"


ARBOR_SITE = {
    "site_code": "TJD-C-062",
    "name": "Yarrow Bend Parcel",
    "address_line": "62 Yarrow Bnd",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


def _site(site_code: str, name: str, address_line: str) -> dict:
    site = dict(ARBOR_SITE)
    site.update(site_code=site_code, name=name, address_line=address_line)
    return site


class TestAuthenticationRunsBeforeAuthorisation:
    """The same appraisal call answers three different ways depending only on
    the headers."""

    def test_missing_headers_report_authentication_and_a_wrong_role_reports_the_role(
            self, api, real_estate_officer, valuation_officer):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
        the seven role names below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the
        named role is not authorised for the endpoint being called, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403). These two checks run before anything else in
        the request pipeline." Recording an appraisal belongs to the appraiser — "A
        `ValuationOfficer` is independent appraisal staff who record fair market value
        and certify the permissible transfer floor" — while certification of a
        readiness assessment and the clock are other people's duties, since the real
        estate officers "own the site inventory, readiness assessments" and "A
        `SystemAdmin` operates the deterministic logical clock that every deadline and
        expiry rule reads." Because those refusals happen before any write, PRD §3.1's
        stamp is still the pinned instant when the rightful role certifies:
        "`certified_at` is stamped with the current logical clock instant".

        Design: Corner/rbac/corner_other_roles_exclusive_operations_and_missing_headers_rejected
        """
        set_logical_clock()
        ctx = build_context(stage="ASSESSED", site_overrides=dict(ARBOR_SITE))
        draft = build_assessment(ctx["site"]["id"])
        assert draft["status"] == "DRAFT"
        payload = create_valuation_payload(ctx["site"]["version"],
                                           method="INCOME_APPROACH",
                                           appraised_value_cents=48_500_000,
                                           transit_supportive_use_pct=60,
                                           affordable_units_pct=25,
                                           transfer_basis="FAIR_MARKET_VALUE",
                                           effective_date="2026-08-20")

        unauthenticated = api.create_valuation(ctx["site"]["id"], payload,
                                               NO_AUTH_HEADERS)

        validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED,
                       expected_status=401)
        wrong_role = api.create_valuation(ctx["site"]["id"], payload,
                                          real_estate_officer)
        validate_error(wrong_role, ApiErrorId.FORBIDDEN_ROLE,
                       expected_status=403)
        validate_error(api.certify_assessment(draft["id"], valuation_officer),
                       ApiErrorId.FORBIDDEN_ROLE, expected_status=403)
        validate_error(api.set_clock(clock_payload("2026-08-02T00:00:00Z"),
                                     valuation_officer),
                       ApiErrorId.FORBIDDEN_ROLE, expected_status=403)
        after = validate_success(api.get_assessment(draft["id"],
                                                    real_estate_officer))
        assert after["status"] == "DRAFT"
        certified = validate_success(api.certify_assessment(
            draft["id"], real_estate_officer))
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")


class TestDeveloperOwnership:
    """The entity-backed role reaches only its own records, and reads the shared
    surface freely."""

    def test_a_peer_developer_is_refused_on_all_three_ownership_surfaces(
            self, api, real_estate_officer):
        """PRD §2.1: "When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of
        the acting registered `Developer` record, and ownership checks on any resource
        that references a developer compare that resource's developer reference to
        `X-User-ID`. Three operations enforce this. When a developer submits a
        proposal, the `developer_id` in the payload must equal `X-User-ID`. When a
        caller holding the `Developer` role reads a single proposal, that proposal's
        `developer_id` must equal `X-User-ID`. When a developer requests a
        construction staging window, the referenced agreement's `developer_id` must
        equal `X-User-ID`. A failure of any of the three is `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)." Everything else stays open, since "All seven roles may call every
        read endpoint." The parcel arrived through PRD §3.5's sole-source route, where
        "A directly granted period is created with `status` `ACTIVE`,
        `extension_count` 0 and `termination_reason` null" and the owning
        solicitation is untouched — "the solicitation that owns the proposal being
        granted exclusivity is excluded" — so PRD §3.3's landing state still holds: "A
        submitted proposal lands in `SUBMITTED` with `rank` null". A refused staging
        request writes nothing, because PRD §3.9 spends bays only on approval:
        "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`".

        Design: Corner/rbac/corner_developer_cannot_act_on_another_developers_resources
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="direct",
                            site_overrides=_site("TJD-C-063",
                                                 "Zelkova Row Parcel",
                                                 "63 Zelkova Rw"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False})
        facility = build_shared_facility(ctx["site"]["id"],
                                         total_bay_capacity=6)
        developer_b = build_developer(legal_name="Birch Yard Development Co",
                                      contact_email="dev-b@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        headers_a = make_developer_headers(ctx["developer"]["id"])
        headers_b = make_developer_headers(developer_b["id"])

        impersonated = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    joint_use_committed=False),
            headers_b)

        validate_error(impersonated, ApiErrorId.NOT_RESOURCE_OWNER,
                       expected_status=403)
        validate_error(api.get_proposal(ctx["proposal"]["id"], headers_b),
                       ApiErrorId.NOT_RESOURCE_OWNER, expected_status=403)
        validate_error(api.create_staging_window(
            create_staging_window_payload(ctx["agreement"]["id"],
                                          facility["id"], facility["version"],
                                          bays_occupied=3,
                                          purpose="Crane pad"),
            headers_b), ApiErrorId.NOT_RESOURCE_OWNER, expected_status=403)
        solicitation = validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], headers_b))
        assert solicitation["status"] == "ISSUED"
        own = validate_success(api.get_proposal(ctx["proposal"]["id"],
                                                headers_a))
        assert own["status"] == "SUBMITTED"
        proposals, meta = validate_paginated(api.list_solicitation_proposals(
            ctx["solicitation"]["id"], real_estate_officer))
        assert meta["total_count"] == 1
        assert proposals[0]["id"] == ctx["proposal"]["id"]
        after = read_shared_facility(facility["id"])
        assert after["version"] == facility["version"]
        assert after["available_bay_capacity"] == 6


class TestSegregationOfDuties:
    """The duty split turns on the operator identity, not on the role name."""

    def test_the_submitting_operator_cannot_approve_until_someone_else_resubmits(
            self, api, real_estate_officer):
        """PRD §2.1: "Recording board approval of an agreement requires the
        `BoardSecretary` role, and the acting `X-User-ID` must differ from the
        `submitted_by_user_id` the agreement recorded when it was submitted for
        review. A single human being may legitimately hold both the real estate
        officer duty and the board secretary duty, so role separation alone is not
        enough; when the two identities coincide the approval is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." PRD §3.7 records the comparand — "On
        success the agreement advances `DRAFTING → AGENCY_REVIEW`,
        `submitted_by_user_id` is set to the submitting operator's `X-User-ID`" and
        "That recorded identity is the sole comparand for the segregation-of-duties
        rule that follows" — and puts the check first: "that check runs before any
        lifecycle-state consideration of the records the approval touches." The
        revision request itself carries no identity test, only the role: it "advances
        the agreement `AGENCY_REVIEW → REVISION_REQUESTED`". PRD §3.6 then resets the
        comparand: "Any amendment clears `submitted_by_user_id` back to null, so the
        segregation-of-duties comparand is always the identity of the *most recent*
        submission."

        Design: Corner/rbac/corner_same_operator_cannot_submit_and_board_approve
        """
        ctx = build_context(stage="AGENCY_REVIEW", negotiation_via="direct",
                            site_overrides=_site("TJD-C-064",
                                                 "Aspen Grove Parcel",
                                                 "64 Aspen Gr"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False},
                            submitter_user_id="reo-001")
        agreement_id = ctx["agreement"]["id"]
        assert ctx["agreement"]["submitted_by_user_id"] == "reo-001"
        wearing_both_hats = make_board_secretary_headers("reo-001")

        same_operator = api.board_approve_agreement(
            agreement_id, board_approve_payload("R-2026-155"),
            wearing_both_hats)

        validate_error(same_operator, ApiErrorId.SEGREGATION_OF_DUTIES,
                       expected_status=403)
        returned = validate_success(api.request_agreement_revision(
            agreement_id,
            request_revision_payload(
                "Route the approval through a second officer"),
            wearing_both_hats))
        assert returned["negotiation_status"] == "REVISION_REQUESTED"
        amended = validate_success(api.update_agreement(
            agreement_id, {"base_rent_cents": 2_000_000}, real_estate_officer))
        assert amended["negotiation_status"] == "DRAFTING"
        assert amended["submitted_by_user_id"] is None
        resubmitted = validate_success(api.submit_agreement_for_review(
            agreement_id, make_real_estate_officer_headers("reo-002")))
        assert resubmitted["submitted_by_user_id"] == "reo-002"
        approved = validate_success(api.board_approve_agreement(
            agreement_id, board_approve_payload("R-2026-155"),
            wearing_both_hats))
        assert approved["negotiation_status"] == "BOARD_APPROVED"
        assert approved["board_resolution_number"] == "R-2026-155"
        assert read_agreement(
            agreement_id)["negotiation_status"] == "BOARD_APPROVED"
