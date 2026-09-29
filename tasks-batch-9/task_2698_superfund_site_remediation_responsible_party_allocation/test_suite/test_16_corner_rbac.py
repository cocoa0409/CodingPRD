"""Role and identity probes: who may act, and on whose record.

Two separate gates are exercised here. The first is the role gate that closes
an exclusive operation to every role but its owner. The second is the identity
gate that binds an entity-backed actor to its own record. Alongside them sit
the two segregation-of-duties rules that compare one project-manager
identifier against another, and the shared reads and comments that stay open to
everybody.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_ledger_figures,
    assert_pagination_meta,
    assert_percentage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_alternative,
    add_sample,
    add_waste_in,
    cast_ballot,
    create_decree,
    create_investigation,
    create_party,
    create_rod,
    create_site,
    file_comment,
    issue_notice,
    list_site_on_npl,
    open_balloting,
    open_comment_period,
    open_round,
    read_investigation,
    read_party,
    read_rod,
    read_round,
    read_site,
    record_election,
    review_investigation,
    set_clock,
    share_for,
    sign_rod,
    site_version,
    submit_investigation,
    verify_waste_in,
)
from test_helpers.test_users import (
    AUTHOR_PM_ID,
    REVIEWER_PM_ID,
    SIGNER_PM_ID,
    TEST_USERS,
    make_contractor_headers,
    make_prp_representative_headers,
)

AUTHOR = TEST_USERS["author_pm_headers"]
REVIEWER = TEST_USERS["reviewer_pm_headers"]
SIGNER = TEST_USERS["signer_pm_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COMMUNITY = TEST_USERS["community_headers"]


class TestExclusiveOperationsRefuseTheWrongRole:
    def test_five_exclusive_operations_are_each_refused_at_the_role_gate(self):
        """The role gate answers before any state or reference rule can.

        PRD: "When both headers are well formed but the declared role is not authorised for the endpoint being called, the refusal is `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_facilitator_cannot_lodge_a_decree_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Pellham Junction Wood Treating", epa_region=4, hrs_score=49.30
        )
        list_site_on_npl(site["id"], "FR-2027-PJW-0201")
        prp_a = create_party(
            site["id"],
            legal_name="Pellham Junction Wood Treating Co",
            party_type="OWNER_OPERATOR",
            viability_score=76,
        )
        prp_b = create_party(
            site["id"],
            legal_name="Junction Tie & Timber",
            party_type="GENERATOR",
            viability_score=52,
        )
        issue_notice(prp_a["id"], "GNL-2027-8201")
        issue_notice(prp_b["id"], "GNL-2027-8202")
        record_election(prp_a["id"], "PARTICIPATE")
        record_election(prp_b["id"], "PARTICIPATE")
        decree = create_decree(
            site["id"],
            [prp_a["id"], prp_b["id"]],
            scope_type="RD_RA_CONSENT_DECREE",
            oversight_cost_cap_cents=100_000_000,
            stipulated_penalty_per_day_cents=150_000,
            performance_deadline="2029-06-30",
            scope_summary="RD/RA for the former treating yard",
        )
        current_version = site_version(site["id"], FACILITATOR)

        # Lodging belongs to settlement counsel, so the facilitator is turned
        # away before the missing adopted allocation can be noticed.
        validate_error(
            api_client.lodge_consent_decree(decree["id"], FACILITATOR),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        # Opening a round belongs to the facilitator, and a current
        # `expected_site_version` does not buy counsel the operation.
        validate_error(
            api_client.create_allocation_round(
                site["id"],
                factories.allocation_round_payload(
                    expected_site_version=current_version
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_site(
                factories.site_payload(
                    name="Community Nominated Site", epa_region=4, hrs_score=41.00
                ),
                COMMUNITY,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        # The party's own representative is refused on role grounds, not
        # because the party has already been noticed.
        validate_error(
            api_client.issue_notice(
                prp_b["id"],
                factories.notice_payload("GNL-2027-8299"),
                make_prp_representative_headers(prp_b["id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        # The contractor identity names no contract at all, and the role gate
        # still decides first.
        validate_error(
            api_client.create_waste_in_record(
                site["id"],
                factories.waste_in_payload(
                    prp_id=prp_a["id"],
                    volume_tons=100,
                    toxicity_class="III",
                    evidence_grade="C",
                    disposal_year=1979,
                ),
                make_contractor_headers("no-such-contract"),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        # The denials are operation-scoped: the same facilitator still reads.
        shared_read = validate_success(
            api_client.get_consent_decree(decree["id"], FACILITATOR)
        )
        assert shared_read["legal_status"] == "NEGOTIATING"
        assert shared_read["lodged_at"] in (None, "")
        assert read_party(prp_b["id"])["status"] == "PARTICIPATING"
        _, rounds_meta = validate_paginated(
            api_client.list_site_allocation_rounds(site["id"], FACILITATOR)
        )
        assert_pagination_meta(rounds_meta, total_count=0)
        _, waste_meta = validate_paginated(
            api_client.list_site_waste_in_records(site["id"], AUTHOR)
        )
        assert_pagination_meta(waste_meta, total_count=0)


def _trestle_row_with_a_party_from_another_site():
    """Two noticed parties on one listed site, plus an outsider identity."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Trestle Row Plating", epa_region=3, hrs_score=50.20)
    list_site_on_npl(site["id"], "FR-2027-TRP-0201")
    other_site = create_site(
        name="Bell Hollow Landfill", epa_region=3, hrs_score=44.80
    )
    foreign_prp = create_party(
        other_site["id"],
        legal_name="Bell Hollow Hauling",
        party_type="TRANSPORTER",
        viability_score=33,
    )
    prp_a = create_party(
        site["id"],
        legal_name="Trestle Row Plating Works",
        party_type="OWNER_OPERATOR",
        viability_score=88,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Row Street Anodizing",
        party_type="GENERATOR",
        viability_score=61,
    )
    issue_notice(prp_a["id"], "GNL-2027-8301")
    issue_notice(prp_b["id"], "GNL-2027-8302")
    return site, prp_a, prp_b, foreign_prp


class TestEntityBackedIdentityIsBoundToItsOwnRecord:
    def test_one_representative_cannot_record_another_partys_election(self):
        """The election is the party's own word, spoken through its own counsel.

        PRD: "Every one of these elections requires that the acting representative's `X-User-ID` be the party's own `id`."

        Design: Corner/rbac/corner_party_representative_cannot_ballot_for_another_party_returns_4XX
        """
        _, prp_a, prp_b, _ = _trestle_row_with_a_party_from_another_site()
        before = read_party(prp_b["id"])

        validate_error(
            api_client.record_response(
                prp_b["id"],
                factories.response_payload("PARTICIPATE"),
                make_prp_representative_headers(prp_a["id"]),
            ),
            ApiErrorId.ERR_ACTOR_IDENTITY_MISMATCH.value,
            403,
        )
        refused = read_party(prp_b["id"])
        assert refused["status"] == "NOTIFIED"
        assert refused["version"] == before["version"]

        # The endpoint is not simply closed: the party's own representative
        # makes the identical call and it lands.
        accepted = validate_success(
            api_client.record_response(
                prp_b["id"],
                factories.response_payload("PARTICIPATE"),
                make_prp_representative_headers(prp_b["id"]),
            )
        )
        assert accepted["status"] == "PARTICIPATING"

    def test_a_party_of_another_site_cannot_ballot_on_this_rounds_shares(self):
        """The ballot identity is checked before the participation posture.

        PRD: "Each party's representative then casts a `ballot` of `ACCEPT`, `REJECT` or `ABSTAIN`, optionally with a `ballot_rationale`, on that party's own share; the acting `X-User-ID` must be the balloting party's `id`."

        Design: Corner/rbac/corner_party_representative_cannot_ballot_for_another_party_returns_4XX
        """
        site, prp_a, prp_b, foreign_prp = _trestle_row_with_a_party_from_another_site()
        record_election(prp_a["id"], "PARTICIPATE")
        record_election(prp_b["id"], "PARTICIPATE")
        record_a = add_waste_in(
            site["id"],
            prp_a["id"],
            volume_tons=3960,
            toxicity_class="II",
            evidence_grade="A",
            disposal_year=1968,
        )
        record_b = add_waste_in(
            site["id"],
            prp_b["id"],
            volume_tons=40,
            toxicity_class="IV",
            evidence_grade="B",
            disposal_year=1981,
        )
        verify_waste_in(record_a["id"], 3960)
        verify_waste_in(record_b["id"], 40)
        create_investigation(
            site["id"], exposure_medium="SOIL", scope_summary="OU-1 chromium in soil"
        )
        allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
        open_balloting(allocation_round["id"])

        validate_error(
            api_client.cast_ballot(
                allocation_round["id"],
                factories.ballot_payload("ACCEPT"),
                make_prp_representative_headers(foreign_prp["id"]),
            ),
            ApiErrorId.ERR_ACTOR_IDENTITY_MISMATCH.value,
            403,
        )
        untouched = read_round(allocation_round["id"])
        assert untouched["balloted_count"] == 0
        assert_percentage(untouched["accept_share_pct"], 0.00, "accept_share_pct")

        cast_ballot(allocation_round["id"], prp_a["id"], "ACCEPT")
        after = read_round(allocation_round["id"])
        assert after["status"] == "BALLOTING"
        assert after["balloted_count"] == 1
        assert_percentage(after["accept_share_pct"], 99.28, "accept_share_pct")
        assert share_for(allocation_round["id"], prp_a["id"])["ballot"] == "ACCEPT"


class TestTheAuthorMayNotReviewTheirOwnInvestigation:
    def test_neither_review_decision_is_open_to_the_author(self):
        """The duties rule is on the actor, not on the decision value.

        PRD: "A project manager records a `decision` of `APPROVE` or `REQUEST_REVISION`, optionally with a `review_note`, but never on their own work: if the reviewer's `X-User-ID` equals the investigation's `authored_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_author_cannot_review_own_investigation_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(name="Calder Slough Refinery", epa_region=9, hrs_score=58.70)
        list_site_on_npl(site["id"], "FR-2027-CSR-0201")
        investigation = create_investigation(
            site["id"],
            exposure_medium="SOIL",
            scope_summary="OU-1 refinery sludge lagoons",
        )
        add_sample(
            investigation["id"],
            medium="SOIL",
            contaminant="BENZENE",
            concentration_ug_per_l=12.0,
            qa_status="VALID",
            collected_at="2027-01-25T09:00:00Z",
            lab_reference="LAB-CSR-0001",
        )
        add_alternative(
            investigation["id"],
            label="A - excavation and offsite disposal",
            capital_cost_cents=938_888_889,
            annual_om_cost_cents=40_000_000,
            om_years=2,
            discount_rate_bp=2000,
            effectiveness_score=84,
            implementability_score=71,
        )
        submit_investigation(investigation["id"])

        for decision, note in (
            ("APPROVE", "Self-review."),
            ("REQUEST_REVISION", "Self-review of a revision request."),
        ):
            validate_error(
                api_client.review_remedial_investigation(
                    investigation["id"],
                    factories.review_payload(decision, note),
                    AUTHOR,
                ),
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            )
        refused = read_investigation(investigation["id"])
        assert refused["status"] == "UNDER_REVIEW"
        assert refused["approved_by_user_id"] in (None, "")
        assert refused["revision_round_count"] == 0

        approved = review_investigation(
            investigation["id"],
            "APPROVE",
            "Independent review complete.",
            REVIEWER,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == REVIEWER_PM_ID
        assert approved["authored_by_user_id"] == AUTHOR_PM_ID
        assert read_site(site["id"])["listing_status"] == "RI_FS_UNDERWAY"


def _ashgrove_tannery_awaiting_signature():
    """A decision document whose comment window has closed with one comment."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Ashgrove Tannery", epa_region=2, hrs_score=46.90)
    list_site_on_npl(site["id"], "FR-2027-AGT-0201")
    investigation = create_investigation(
        site["id"], exposure_medium="SOIL", scope_summary="OU-1 chromium sludge beds"
    )
    add_sample(
        investigation["id"],
        medium="SOIL",
        contaminant="CHROMIUM_VI",
        concentration_ug_per_l=12.0,
        qa_status="VALID",
        collected_at="2027-01-26T09:00:00Z",
        lab_reference="LAB-AGT-0001",
    )
    alternative = add_alternative(
        investigation["id"],
        label="A - stabilisation and cap",
        capital_cost_cents=938_888_889,
        annual_om_cost_cents=40_000_000,
        om_years=2,
        discount_rate_bp=2000,
        effectiveness_score=79,
        implementability_score=83,
    )
    submit_investigation(investigation["id"])
    review_investigation(investigation["id"], "APPROVE", headers=REVIEWER)
    decision = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Stabilise the sludge beds and cap",
    )
    set_clock("2027-03-01T09:00:00Z")
    open_comment_period(decision["id"])
    file_comment(
        decision["id"],
        "Ashgrove Neighbours",
        "Confirm the cap will be maintained.",
        COMMUNITY,
    )
    set_clock("2027-04-01T09:00:00Z")
    return site, investigation, alternative, decision


class TestTheApproverMayNotSignTheDecisionThatCitesTheirApproval:
    def test_the_investigation_approver_is_refused_at_the_signature(self):
        """The stored approver identifier is what the signature check excludes.

        PRD: "The signer must not be the user who approved the cited investigation: if `X-User-ID` equals that investigation's `approved_by_user_id`, the signature is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_approver_cannot_sign_the_rod_returns_4XX
        """
        site, _, alternative, decision = _ashgrove_tannery_awaiting_signature()

        validate_error(
            api_client.sign_record_of_decision(
                decision["id"],
                factories.signature_payload(
                    "Maintenance commitment added.", alternative["id"]
                ),
                REVIEWER,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        refused = read_rod(decision["id"])
        assert refused["status"] == "PUBLIC_COMMENT"
        assert refused["signed_at"] in (None, "")
        assert refused["signed_by_user_id"] in (None, "")
        assert refused["selected_alternative_id"] in (None, "")
        # The community was heard, so the refusal is the duties rule rather
        # than the involvement rule that sits behind it.
        assert refused["public_comments_count"] == 1
        assert read_site(site["id"])["listing_status"] == "RI_FS_UNDERWAY"

    def test_a_manager_outside_the_approval_chain_signs_and_the_remedy_lands(self):
        """A third identifier completes the chain and the selection is stamped.

        PRD: "The document's `status` becomes `SIGNED`, `signed_by_user_id` records the signer, `signed_at` records the logical clock instant, and `responsiveness_summary` captures the supplied text."

        Design: Corner/rbac/corner_approver_cannot_sign_the_rod_returns_4XX
        """
        site, investigation, alternative, decision = (
            _ashgrove_tannery_awaiting_signature()
        )

        signed = sign_rod(
            decision["id"],
            alternative_id=alternative["id"],
            responsiveness_summary="Maintenance commitment added.",
            headers=SIGNER,
        )
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == SIGNER_PM_ID
        assert signed["selected_alternative_id"] == alternative["id"]
        assert signed["responsiveness_summary"] == "Maintenance commitment added."
        assert read_site(site["id"])["listing_status"] == "ROD_SIGNED"
        selected, _ = validate_paginated(
            api_client.list_remedy_alternatives(investigation["id"], AUTHOR)
        )
        assert selected[0]["selected_by_rod_id"] == decision["id"]


def _grantley_fields_in_public_comment():
    """A decision document open for comment, plus one noticed party."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Grantley Fields Dump", epa_region=7, hrs_score=43.20)
    list_site_on_npl(site["id"], "FR-2027-GFD-0201")
    prp_a = create_party(
        site["id"],
        legal_name="Grantley Fields Disposal Co",
        party_type="OWNER_OPERATOR",
        viability_score=64,
    )
    issue_notice(prp_a["id"], "GNL-2027-8401")
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 municipal and industrial fill",
    )
    add_sample(
        investigation["id"],
        medium="GROUNDWATER",
        contaminant="VINYL_CHLORIDE",
        concentration_ug_per_l=12.0,
        qa_status="VALID",
        collected_at="2027-01-27T09:00:00Z",
        lab_reference="LAB-GFD-0001",
    )
    add_alternative(
        investigation["id"],
        label="A - pump and treat",
        capital_cost_cents=938_888_889,
        annual_om_cost_cents=40_000_000,
        om_years=2,
        discount_rate_bp=2000,
        effectiveness_score=74,
        implementability_score=80,
    )
    submit_investigation(investigation["id"])
    review_investigation(investigation["id"], "APPROVE", headers=REVIEWER)
    decision = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Pump and treat with monitoring",
    )
    opened = open_comment_period(decision["id"])
    return site, prp_a, investigation, opened


class TestSharedOperationsStayOpenToEveryRole:
    def test_every_role_reads_the_collections_and_the_computed_ledger(self):
        """A shared read is shared: no role is shut out of the record.

        PRD: "Where the Authorized Role(s) column reads "All roles", all six declared roles may call the endpoint; every list endpoint additionally accepts the `limit` and `offset` parameters described in §2.3."

        Design: Corner/rbac/corner_shared_reads_and_public_comments_work_for_every_role
        """
        site, prp_a, investigation, _ = _grantley_fields_in_public_comment()

        sites, sites_meta = validate_paginated(
            api_client.list_sites(COMMUNITY, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(
            sites_meta, total_count=1, has_more=False, limit=10, offset=0
        )
        assert [row["id"] for row in sites] == [site["id"]]

        ledger = validate_success(api_client.get_cost_ledger(site["id"], COMMUNITY))
        assert_ledger_figures(ledger, 0, 0, 0, 0)
        assert ledger["ledger_balanced"] is True

        alternatives, alternatives_meta = validate_paginated(
            api_client.list_remedy_alternatives(
                investigation["id"],
                make_prp_representative_headers(prp_a["id"]),
                {"limit": 10, "offset": 0},
            )
        )
        assert_pagination_meta(alternatives_meta, total_count=1)
        assert alternatives[0]["label"] == "A - pump and treat"

        for reader in (FACILITATOR, COUNSEL):
            parties, parties_meta = validate_paginated(
                api_client.list_site_prps(site["id"], reader, {"limit": 10, "offset": 0})
            )
            assert_pagination_meta(parties_meta, total_count=1)
            assert parties[0]["id"] == prp_a["id"]

    def test_both_commenting_roles_file_and_the_counter_and_version_advance(self):
        """Commenting carries no identity binding to the document commented on.

        PRD: "While the window is open, a community member or a party's representative files a comment by supplying a `commenter_name` and the `comment_text`. Each accepted comment increases the document's `public_comments_count` by 1 and bumps the document's `version`; comment bodies themselves are not separately addressable resources."

        Design: Corner/rbac/corner_shared_reads_and_public_comments_work_for_every_role
        """
        _, prp_a, _, opened = _grantley_fields_in_public_comment()

        validate_success(
            api_client.file_public_comment(
                opened["id"],
                factories.public_comment_payload(
                    "Grantley Fields Residents",
                    "Extend the monitoring network north of the fill.",
                ),
                COMMUNITY,
            )
        )
        validate_success(
            api_client.file_public_comment(
                opened["id"],
                factories.public_comment_payload(
                    "Counsel for Grantley Fields Disposal Co",
                    "The pumping rate assumption should be documented.",
                ),
                make_prp_representative_headers(prp_a["id"]),
            )
        )

        commented = read_rod(opened["id"])
        assert commented["public_comments_count"] == 2
        assert commented["status"] == "PUBLIC_COMMENT"
        assert commented["version"] == opened["version"] + 2
