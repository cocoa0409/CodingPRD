"""Refusal probes: one error identifier per gate, isolated from its neighbours.

Each scenario is built so that exactly one rule can fail, then the refusal is
read back together with the state it was supposed to protect — the point of a
refusal is that nothing moved.
"""
from datetime import datetime

import pytest

from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_days_between,
    assert_ledger_figures,
    assert_pagination_meta,
    assert_percentage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_verified_waste_in,
    add_waste_in,
    adopt_round,
    alternatives_of,
    build_operations_and_maintenance_site,
    cast_ballot,
    create_approved_investigation,
    create_decree,
    create_investigation,
    create_party,
    create_rod,
    create_site,
    enter_decree,
    file_comment,
    issue_action,
    issue_notice,
    list_site_on_npl,
    lodge_decree,
    open_balloting,
    open_comment_period,
    open_round,
    post_oversight,
    prp_version,
    read_action,
    read_contract,
    read_decree,
    read_ledger,
    read_party,
    read_rod,
    read_round,
    read_site,
    record_collection,
    record_defunct,
    record_election,
    record_violation,
    respond_to_action,
    set_clock,
    share_for,
    site_version,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_headers,
    make_prp_representative_headers,
)

AUTHOR = TEST_USERS["author_pm_headers"]
SIGNER = TEST_USERS["signer_pm_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


class TestAuthenticationRunsBeforeEveryOtherCheck:
    def test_an_empty_user_id_header_is_refused_before_the_payload_is_read(self):
        """A well-formed body cannot rescue a request with no acting user.

        PRD: "If either header is missing or empty, or if `X-User-Role` is not one of the six role names below, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/corner_empty_user_id_header_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        anonymous = make_headers("", "RemedialProjectManager")

        response = api_client.create_site(
            factories.site_payload(
                name="Hollis Yard Coal Tar", epa_region=2, hrs_score=44.40
            ),
            anonymous,
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert response.json()["response_type"] == "error"

        rows, meta = validate_paginated(api_client.list_sites(AUTHOR))
        assert_pagination_meta(meta, total_count=0)
        assert rows == []


class TestPathRootedNotFoundCodes:
    def test_each_path_rooted_entity_reports_its_own_not_found_identifier(self):
        """Six unknown identifiers in the same empty namespace, six codes.

        PRD: "The error reported is the one belonging to the first identifier in the path that does not resolve — `ERR_SITE_NOT_FOUND`, `ERR_PRP_NOT_FOUND`, `ERR_WASTE_IN_RECORD_NOT_FOUND`, `ERR_REMEDIAL_INVESTIGATION_NOT_FOUND`, `ERR_RECORD_OF_DECISION_NOT_FOUND`, `ERR_ALLOCATION_ROUND_NOT_FOUND`, `ERR_CONSENT_DECREE_NOT_FOUND`, `ERR_REMEDIATION_CONTRACT_NOT_FOUND` or `ERR_COST_RECOVERY_ACTION_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/corner_unknown_ids_on_every_path_rooted_entity_not_found
        """
        set_clock("2027-01-04T08:00:00Z")
        probes = [
            (
                api_client.get_waste_in_record(
                    "11111111-0000-4000-8000-000000000001", AUTHOR
                ),
                ApiErrorId.ERR_WASTE_IN_RECORD_NOT_FOUND.value,
            ),
            (
                api_client.get_record_of_decision(
                    "11111111-0000-4000-8000-000000000002", AUTHOR
                ),
                ApiErrorId.ERR_RECORD_OF_DECISION_NOT_FOUND.value,
            ),
            (
                api_client.get_allocation_round(
                    "11111111-0000-4000-8000-000000000003", AUTHOR
                ),
                ApiErrorId.ERR_ALLOCATION_ROUND_NOT_FOUND.value,
            ),
            (
                api_client.get_consent_decree(
                    "11111111-0000-4000-8000-000000000004", AUTHOR
                ),
                ApiErrorId.ERR_CONSENT_DECREE_NOT_FOUND.value,
            ),
            (
                api_client.get_remediation_contract(
                    "11111111-0000-4000-8000-000000000005", AUTHOR
                ),
                ApiErrorId.ERR_REMEDIATION_CONTRACT_NOT_FOUND.value,
            ),
            (
                api_client.get_cost_recovery_action(
                    "11111111-0000-4000-8000-000000000006", AUTHOR
                ),
                ApiErrorId.ERR_COST_RECOVERY_ACTION_NOT_FOUND.value,
            ),
        ]
        for response, expected_error_id in probes:
            body = validate_error(response, expected_error_id, 404)
            assert response.json()["response_type"] == "error"
            assert "id" not in body, f"{expected_error_id} must not return a row"


class TestSiteListingPhaseGate:
    def test_a_waste_in_claim_against_a_still_proposed_site_is_refused(self):
        """Reconstruction of the waste stream waits for the listing.

        PRD: "Waste-in submissions, ownership periods and investigations all require the site to be `LISTED` or further along."

        Design: Corner/errors/corner_waste_in_record_on_a_still_proposed_site_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_site(
            name="Tamarack Spur Tie Plant", epa_region=5, hrs_score=31.20
        )
        prp_a = create_party(
            site["id"],
            legal_name="Tamarack Timber Products",
            party_type="OWNER_OPERATOR",
            viability_score=55,
        )
        # No notice is issued here: PRD 3.1 permits notice only while the site's
        # listing_status is neither PROPOSED nor DELETED_FROM_NPL, and this site
        # is deliberately still PROPOSED.
        validate_error(
            api_client.create_waste_in_record(
                site["id"],
                factories.waste_in_payload(
                    prp_id=prp_a["id"],
                    volume_tons=120,
                    toxicity_class="III",
                    evidence_grade="B",
                    disposal_year=1983,
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_SITE_PHASE_INVALID.value,
            409,
        )

        after = read_site(site["id"])
        assert after["listing_status"] == "PROPOSED"
        assert after["verified_waste_volume_tons"] == pytest.approx(0, abs=0.01)
        _, meta = validate_paginated(
            api_client.list_site_waste_in_records(site["id"], AUTHOR)
        )
        assert_pagination_meta(meta, total_count=0)


class TestVerificationCeiling:
    def test_verifying_more_volume_than_was_claimed_is_refused(self):
        """Verification may shrink a claim but never inflate it.

        PRD: "Violating either side of that pairing — a figure above the claim, a non-positive figure, or a figure supplied alongside a rejection — is refused with `ERR_VERIFIED_VOLUME_EXCEEDS_CLAIM` (HTTP 422)."

        Design: Corner/errors/corner_verified_volume_above_the_claim_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Underwood Slip Barge Cleaning", epa_region=5, hrs_score=40.60
        )
        list_site_on_npl(site["id"], "FR-2027-USB-0201")
        prp_a = create_party(
            site["id"],
            legal_name="Underwood Marine Services",
            party_type="OWNER_OPERATOR",
            viability_score=61,
        )
        issue_notice(prp_a["id"], "GNL-2027-7101")
        record_election(prp_a["id"], "PARTICIPATE")
        record = add_waste_in(
            site["id"],
            prp_a["id"],
            500,
            toxicity_class="II",
            evidence_grade="B",
            disposal_year=1978,
        )

        validate_error(
            api_client.verify_waste_in_record(
                record["id"],
                factories.verification_payload(
                    decision="VERIFIED", verified_volume_tons=600
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_VERIFIED_VOLUME_EXCEEDS_CLAIM.value,
            422,
        )

        after = validate_success(api_client.get_waste_in_record(record["id"], AUTHOR))
        assert after["status"] == "SUBMITTED"
        assert after["verified_volume_tons"] is None
        assert after["effective_volume_tons"] == pytest.approx(500, abs=0.01)
        assert read_site(site["id"])["verified_waste_volume_tons"] == pytest.approx(
            0, abs=0.01
        )
        assert read_party(prp_a["id"])["max_toxicity_class"] in (None, "")


class TestAllocationBasis:
    def test_a_round_with_no_waste_and_no_ownership_has_nothing_to_allocate_on(self):
        """Three empty denominators leave no basis at all, normalised or not.

        PRD: "If all three totals are zero — no volume, no toxicity, no ownership days anywhere in the candidate set — there is no basis to allocate on at all, and the request is refused with `ERR_NO_ALLOCATION_BASIS`; this guard applies both when a round is opened and when it is moved to balloting."

        Design: Corner/errors/corner_round_with_no_waste_and_no_ownership_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Pinnacle Draw Battery Salvage", epa_region=6, hrs_score=37.90
        )
        list_site_on_npl(site["id"], "FR-2027-PDB-0201")
        prp_a = create_party(
            site["id"],
            legal_name="Pinnacle Salvage LLC",
            party_type="ARRANGER",
            viability_score=26,
        )
        issue_notice(prp_a["id"], "GNL-2027-7201")
        record_election(prp_a["id"], "PARTICIPATE")
        create_investigation(
            site["id"],
            exposure_medium="SOIL",
            scope_summary="OU-1 lead in surface soil",
        )
        before = site_version(site["id"])

        body = validate_error(
            api_client.create_allocation_round(
                site["id"],
                factories.allocation_round_payload(
                    expected_site_version=before,
                    weight_volume_bp=5000,
                    weight_toxicity_bp=3000,
                    weight_ownership_bp=2000,
                ),
                FACILITATOR,
            ),
            ApiErrorId.ERR_NO_ALLOCATION_BASIS.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED.value

        _, meta = validate_paginated(
            api_client.list_site_allocation_rounds(site["id"], AUTHOR)
        )
        assert_pagination_meta(meta, total_count=0)
        assert site_version(site["id"]) == before


class TestProcurementRequiresASignedDecision:
    def test_a_solicitation_against_a_draft_decision_is_refused(self):
        """Nothing may be bought until the remedy is chosen on the record.

        PRD: "The cited decision document must be `SIGNED`; a solicitation opened against a draft, commenting, amendment-required or withdrawn document is refused with `ERR_ROD_NOT_SIGNED`."

        Design: Corner/errors/corner_contract_against_an_unsigned_rod_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Yarrow Cut Creosote Pond", epa_region=4, hrs_score=46.20
        )
        list_site_on_npl(site["id"], "FR-2027-YCC-0201")
        investigation = create_investigation(
            site["id"],
            exposure_medium="SEDIMENT",
            scope_summary="OU-1 creosote sludge in the pond",
        )
        rod = create_rod(
            site["id"],
            investigation["id"],
            comment_period_days=30,
            proposed_plan_summary="Dredging with on-site solidification",
        )

        validate_error(
            api_client.create_remediation_contract(
                site["id"],
                factories.remediation_contract_payload(
                    record_of_decision_id=rod["id"],
                    solicitation_reference="SOL-YCC-0001",
                    engineer_estimate_cents=800_000_000,
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_ROD_NOT_SIGNED.value,
            409,
        )

        assert read_rod(rod["id"])["status"] == "DRAFT"
        after = read_site(site["id"])
        assert after["listing_status"] == "RI_FS_UNDERWAY"
        assert after["total_response_cost_cents"] == 0
        _, meta = validate_paginated(
            api_client.list_site_remediation_contracts(site["id"], AUTHOR)
        )
        assert_pagination_meta(meta, total_count=0)


def _zephyr_flats_commenting_decision():
    """A decision document open for comment until 2027-03-31T09:00:00Z."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Zephyr Flats Circuit Board", epa_region=9, hrs_score=48.30
    )
    list_site_on_npl(site["id"], "FR-2027-ZFC-0201")
    investigation = create_approved_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        samples=[
            {
                "medium": "GROUNDWATER",
                "contaminant": "TRICHLOROETHENE",
                "concentration_ug_per_l": 25.0,
                "qa_status": "VALID",
                "collected_at": "2027-01-22T11:00:00Z",
                "lab_reference": "LAB-ZFC-0001",
            }
        ],
        alternatives=[
            {
                "label": "A - extraction with air stripping",
                "capital_cost_cents": 938_888_889,
                "annual_om_cost_cents": 40_000_000,
                "om_years": 2,
                "discount_rate_bp": 2000,
                "effectiveness_score": 78,
                "implementability_score": 82,
            }
        ],
    )
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Extraction with air stripping",
    )
    set_clock("2027-03-01T09:00:00Z")
    open_comment_period(rod["id"])
    file_comment(
        rod["id"],
        commenter_name="Zephyr Flats Residents",
        comment_text="Please monitor the school well.",
    )
    return {
        "site": site,
        "investigation": investigation,
        "rod": rod,
        "alternative": alternatives_of(investigation["id"])[0],
    }


class TestSignatureTiming:
    def test_signing_at_the_closing_instant_itself_is_refused(self):
        """The window closes strictly after its end, not at it.

        PRD: "The comment window must have **closed**: the logical clock must be strictly past `comment_period_end`, and a signature attempted at or before that instant is refused with `ERR_COMMENT_PERIOD_OPEN` — note that this is the exact mirror image of the comment-filing rule, so there is no instant at which both filing and signing are legal."

        Design: Corner/errors/corner_signature_at_the_comment_period_end_instant_returns_4XX
        """
        scenario = _zephyr_flats_commenting_decision()
        rod_id = scenario["rod"]["id"]
        assert read_rod(rod_id)["comment_period_end"].startswith("2027-03-31T09:00:00")

        set_clock("2027-03-31T09:00:00Z")
        validate_error(
            api_client.sign_record_of_decision(
                rod_id,
                factories.signature_payload(
                    responsiveness_summary="One comment received and addressed."
                ),
                SIGNER,
            ),
            ApiErrorId.ERR_COMMENT_PERIOD_OPEN.value,
            409,
        )

        after = read_rod(rod_id)
        assert after["status"] == "PUBLIC_COMMENT"
        assert after["public_comments_count"] == 1
        assert after["signed_at"] in (None, "")
        assert after["signed_by_user_id"] in (None, "")
        assert after["selected_alternative_id"] in (None, "")
        alternative = alternatives_of(scenario["investigation"]["id"])[0]
        assert alternative["selected_by_rod_id"] in (None, "")
        assert read_site(scenario["site"]["id"])["listing_status"] == "RI_FS_UNDERWAY"


class TestBallotEligibility:
    def test_a_party_that_never_answered_its_notice_holds_a_share_but_no_vote(self):
        """Candidacy for a share and the right to vote are different things.

        PRD: "Only a party whose `status` is `PARTICIPATING` or `RECALCITRANT` may vote, and a ballot from a party in any other posture is refused with `ERR_PARTY_NOT_PARTICIPATING`."

        Design: Corner/errors/corner_ballot_by_a_party_that_never_answered_its_notice_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Bittern Marsh Fertilizer", epa_region=7, hrs_score=44.90
        )
        list_site_on_npl(site["id"], "FR-2027-BMF-0201")
        prp_a = create_party(
            site["id"],
            legal_name="Bittern Marsh Agchem",
            party_type="OWNER_OPERATOR",
            viability_score=74,
        )
        prp_b = create_party(
            site["id"],
            legal_name="Marshside Blending Co",
            party_type="GENERATOR",
            viability_score=19,
        )
        issue_notice(prp_a["id"], "GNL-2027-7301")
        issue_notice(prp_b["id"], "GNL-2027-7302")
        record_election(prp_a["id"], "PARTICIPATE")
        add_verified_waste_in(
            site["id"], prp_a["id"], 3960, "II", "A", 1966
        )
        add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1987)
        create_investigation(
            site["id"],
            exposure_medium="GROUNDWATER",
            scope_summary="OU-1 nitrates and arsenic",
        )
        allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
        open_balloting(allocation_round["id"])

        validate_error(
            api_client.cast_ballot(
                allocation_round["id"],
                factories.ballot_payload(ballot="ACCEPT"),
                make_prp_representative_headers(prp_b["id"]),
            ),
            ApiErrorId.ERR_PARTY_NOT_PARTICIPATING.value,
            409,
        )

        share_b = share_for(allocation_round["id"], prp_b["id"])
        assert share_b["disposition"] == "PENDING"
        assert share_b["ballot"] in (None, "")
        assert share_b["provisional_pct"] is not None
        assert_percentage(share_b["provisional_pct"], 0.72, field="provisional_pct")
        after = read_round(allocation_round["id"])
        assert after["balloted_count"] == 0
        assert_percentage(after["accept_share_pct"], 0.00, field="accept_share_pct")
        assert after["status"] == "BALLOTING"
        assert read_party(prp_b["id"])["status"] == "NOTIFIED"


UNKNOWN_ALTERNATIVE_ID = "22222222-0000-4000-8000-00000000000a"


def _harkness_mill_ready_to_sign():
    """A decision document past its comment window whose only remedy is weak."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Harkness Mill Solvent Pit", epa_region=1, hrs_score=47.10
    )
    list_site_on_npl(site["id"], "FR-2027-HMS-0201")
    investigation = create_approved_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        samples=[
            {
                "medium": "GROUNDWATER",
                "contaminant": "TETRACHLOROETHENE",
                "concentration_ug_per_l": 25.0,
                "qa_status": "VALID",
                "collected_at": "2027-01-19T08:00:00Z",
                "lab_reference": "LAB-HMS-0001",
            }
        ],
        alternatives=[
            {
                "label": "L - monitored natural attenuation only",
                "capital_cost_cents": 938_888_889,
                "annual_om_cost_cents": 40_000_000,
                "om_years": 2,
                "discount_rate_bp": 2000,
                "effectiveness_score": 55,
                "implementability_score": 90,
            }
        ],
    )
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Attenuation with institutional controls",
    )
    set_clock("2027-03-01T09:00:00Z")
    open_comment_period(rod["id"])
    file_comment(
        rod["id"],
        commenter_name="Harkness Mill Village Board",
        comment_text="Attenuation alone will not protect the village wells.",
    )
    set_clock("2027-04-01T09:00:00Z")
    return {
        "site": site,
        "investigation": investigation,
        "rod": rod,
        "alternative": alternatives_of(investigation["id"])[0],
    }


def _three_signature_attempts(rod_id, weak_alternative_id):
    """Sign with an unknown id, with the weak id, and with no id at all."""
    return (
        api_client.sign_record_of_decision(
            rod_id,
            factories.signature_payload(
                responsiveness_summary="Comment addressed.",
                alternative_id=UNKNOWN_ALTERNATIVE_ID,
            ),
            SIGNER,
        ),
        api_client.sign_record_of_decision(
            rod_id,
            factories.signature_payload(
                responsiveness_summary="Comment addressed.",
                alternative_id=weak_alternative_id,
            ),
            SIGNER,
        ),
        api_client.sign_record_of_decision(
            rod_id,
            factories.signature_payload(responsiveness_summary="Comment addressed."),
            SIGNER,
        ),
    )


class TestRemedySelectionRefusals:
    def test_the_alternative_named_decides_which_of_three_refusals_applies(self):
        """An unknown id, a weak id and no id fail three different rules.

        PRD: "Finally, when the cited investigation has `action_level_exceeded` true, an explicitly named alternative must have an `effectiveness_score` of at least 60; a less protective explicit choice is refused with `ERR_REMEDY_NOT_PROTECTIVE`."

        Design: Corner/errors/corner_three_remedy_selection_refusals_on_one_signature_return_4XX
        """
        scenario = _harkness_mill_ready_to_sign()
        assert scenario["investigation"]["action_level_exceeded"] is True

        unknown, weak, delegated = _three_signature_attempts(
            scenario["rod"]["id"], scenario["alternative"]["id"]
        )
        validate_error(
            unknown, ApiErrorId.ERR_REMEDY_ALTERNATIVE_NOT_FOUND.value, 404
        )
        validate_error(weak, ApiErrorId.ERR_REMEDY_NOT_PROTECTIVE.value, 409)
        validate_error(delegated, ApiErrorId.ERR_NO_ELIGIBLE_REMEDY.value, 409)

    def test_three_refusals_leave_the_document_and_the_remedy_untouched(self):
        """The composite score is the exceeded-action-level weighting throughout.

        PRD: "When the action level has been exceeded, the score is 0.65 times the `effectiveness_score`, plus 0.20 times the `implementability_score`, plus 0.15 times the `cost_score`, rounded half up to two decimal places — permanence dominates, cost barely matters."

        Design: Corner/errors/corner_three_remedy_selection_refusals_on_one_signature_return_4XX
        """
        scenario = _harkness_mill_ready_to_sign()
        _three_signature_attempts(
            scenario["rod"]["id"], scenario["alternative"]["id"]
        )

        after = read_rod(scenario["rod"]["id"])
        assert after["status"] == "PUBLIC_COMMENT"
        assert after["signed_at"] in (None, "")
        assert after["selected_alternative_id"] in (None, "")
        alternative = alternatives_of(scenario["investigation"]["id"])[0]
        assert_percentage(
            alternative["remedy_score"], 65.75, field="remedy_score"
        )
        assert alternative["selected_by_rod_id"] in (None, "")
        assert read_site(scenario["site"]["id"])["listing_status"] == "RI_FS_UNDERWAY"


def _ledger_creek_negotiating_decree():
    """An adopted allocation and a decree still under negotiation."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Ledger Creek Chemical", epa_region=6, hrs_score=54.40)
    list_site_on_npl(site["id"], "FR-2027-LCC-0201")
    prp_a = create_party(
        site["id"],
        legal_name="Ledger Creek Chemical Co",
        party_type="OWNER_OPERATOR",
        viability_score=83,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Creekside Solvent Sales",
        party_type="ARRANGER",
        viability_score=27,
    )
    issue_notice(prp_a["id"], "GNL-2027-8001")
    issue_notice(prp_b["id"], "GNL-2027-8002")
    record_election(prp_a["id"], "PARTICIPATE")
    record_election(prp_b["id"], "PARTICIPATE")
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1970)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1986)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 solvent and metals plume",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    decree = create_decree(
        site["id"],
        [prp_a["id"], prp_b["id"]],
        scope_type="RD_RA_CONSENT_DECREE",
        scope_summary="RD/RA for OU-1",
        oversight_cost_cap_cents=100_000_000,
        stipulated_penalty_per_day_cents=200_000,
        performance_deadline="2028-12-31",
    )
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "round": allocation_round,
        "decree": decree,
    }


def _ledger_creek_open_violation():
    """Carry that decree through lodging and entry to an open violation."""
    scenario = _ledger_creek_negotiating_decree()
    set_clock("2027-03-01T10:00:00Z")
    lodge_decree(scenario["decree"]["id"])
    set_clock("2027-04-05T08:00:00Z")
    enter_decree(scenario["decree"]["id"], "2:27-cv-00190-LCC")
    scenario["decree"] = record_violation(
        scenario["decree"]["id"], "2027-04-05T00:00:00Z", "MISSED_MILESTONE"
    )
    return scenario


class TestDecreeLifecycleRefusals:
    def test_a_compliance_event_before_entry_is_refused(self):
        """Nothing may be recorded against an instrument the court has not entered.

        PRD: "No compliance event of any type may be recorded against an instrument whose `legal_status` is not `ENTERED`; an earlier attempt is refused with `ERR_DECREE_NOT_ENTERED`."

        Design: Corner/errors/corner_four_decree_lifecycle_refusals_return_4XX
        """
        scenario = _ledger_creek_negotiating_decree()
        decree_id = scenario["decree"]["id"]

        validate_error(
            api_client.record_compliance_event(
                decree_id,
                factories.violation_event_payload(
                    effective_at="2027-02-10T00:00:00Z",
                    violation_type="MISSED_MILESTONE",
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_DECREE_NOT_ENTERED.value,
            409,
        )

        after = read_decree(decree_id)
        assert after["legal_status"] == "NEGOTIATING"
        assert after["compliance_status"] == "COMPLIANT"
        assert after["first_noncompliance_date"] in (None, "")
        assert after["open_violation_count"] == 0

    def test_entry_inside_the_thirty_day_lodging_window_is_refused(self):
        """The court may only enter the decree once the window has elapsed.

        PRD: "Entry moves the instrument `LODGED → ENTERED` and requires that the 30-day lodging comment window has fully elapsed: the logical clock must be at or after `public_comment_close_at`, with the closing instant itself qualifying."

        Design: Corner/errors/corner_four_decree_lifecycle_refusals_return_4XX
        """
        scenario = _ledger_creek_negotiating_decree()
        decree_id = scenario["decree"]["id"]

        set_clock("2027-03-01T10:00:00Z")
        lodged = lodge_decree(decree_id)
        assert lodged["legal_status"] == "LODGED"
        assert lodged["lodged_at"].startswith("2027-03-01T10:00:00")
        assert lodged["public_comment_close_at"].startswith("2027-03-31T10:00:00")

        set_clock("2027-03-15T10:00:00Z")
        validate_error(
            api_client.enter_consent_decree(
                decree_id,
                factories.entry_payload(court_docket_number="2:27-cv-00190-LCC"),
                COUNSEL,
            ),
            ApiErrorId.ERR_DECREE_COMMENT_PERIOD_OPEN.value,
            409,
        )
        midway = read_decree(decree_id)
        assert midway["legal_status"] == "LODGED"
        assert midway["court_docket_number"] in (None, "")

        set_clock("2027-04-05T08:00:00Z")
        entered = enter_decree(decree_id, "2:27-cv-00190-LCC")
        assert entered["legal_status"] == "ENTERED"
        assert entered["compliance_status"] == "COMPLIANT"
        assert entered["penalty_cap_cents"] == 10_000_000
        assert entered["first_noncompliance_date"] in (None, "")

    def test_an_open_violation_restricts_the_site_and_blocks_a_new_round(self):
        """A restricted posture stops the allocation stream, not the money stream.

        PRD: "While a site is `RESTRICTED`, three operations are refused with `ERR_SITE_COST_RESTRICTED` (HTTP 409): opening an allocation round, awarding a construction contract, and scheduling a field-work window — oversight postings and recovery actions remain permitted, because a restricted site is one whose exposure is elevated, not one whose books are closed."

        Design: Corner/errors/corner_four_decree_lifecycle_refusals_return_4XX
        """
        scenario = _ledger_creek_open_violation()
        decree = scenario["decree"]
        assert decree["compliance_status"] == "IN_VIOLATION"
        assert decree["first_noncompliance_date"].startswith("2027-04-05")
        assert decree["open_violation_count"] == 1
        assert read_site(scenario["site"]["id"])["cost_posture"] == "RESTRICTED"

        body = validate_error(
            api_client.create_allocation_round(
                scenario["site"]["id"],
                factories.allocation_round_payload(
                    expected_site_version=site_version(scenario["site"]["id"]),
                    weight_volume_bp=5000,
                    weight_toxicity_bp=3000,
                    weight_ownership_bp=2000,
                ),
                FACILITATOR,
            ),
            ApiErrorId.ERR_SITE_COST_RESTRICTED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_SITE_COST_FROZEN.value
        assert read_round(scenario["round"]["id"])["status"] == "ADOPTED"

    def test_a_cure_paying_one_cent_against_a_zero_balance_is_refused(self):
        """A cure must settle the books to the cent, and the balance here is zero.

        PRD: "The supplied `paid_penalty_cents` must equal the outstanding balance — the instrument's `accrued_penalty_cents` less its already-recorded `paid_penalty_cents` — to the cent. Any other amount, over or under, is refused with `ERR_PENALTY_BALANCE_MISMATCH` (HTTP 422)."

        Design: Corner/errors/corner_four_decree_lifecycle_refusals_return_4XX
        """
        scenario = _ledger_creek_open_violation()
        decree_id = scenario["decree"]["id"]
        assert scenario["decree"]["accrued_penalty_cents"] == 0

        validate_error(
            api_client.record_compliance_event(
                decree_id,
                factories.cure_event_payload(
                    paid_penalty_cents=1, effective_at="2027-04-20T00:00:00Z"
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_PENALTY_BALANCE_MISMATCH.value,
            422,
        )

        after = read_decree(decree_id)
        assert after["compliance_status"] == "IN_VIOLATION"
        assert after["accrued_penalty_cents"] == 0
        assert after["paid_penalty_cents"] == 0
        assert after["open_violation_count"] == 1


def _marrow_bend_adopted_with_an_orphan():
    """Three parties, one orphaned mid-ballot, and one oversight posting billed."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Marrow Bend Reclaiming", epa_region=5, hrs_score=51.10)
    list_site_on_npl(site["id"], "FR-2027-MBR-0201")
    prp_a = create_party(
        site["id"],
        legal_name="Marrow Bend Reclaiming Inc",
        party_type="OWNER_OPERATOR",
        viability_score=91,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Halvers Machine Shop",
        party_type="GENERATOR",
        viability_score=44,
    )
    prp_c = create_party(
        site["id"],
        legal_name="Bend Barrel Exchange",
        party_type="TRANSPORTER",
        viability_score=8,
    )
    issue_notice(prp_a["id"], "GNL-2027-8101")
    issue_notice(prp_b["id"], "GNL-2027-8102")
    issue_notice(prp_c["id"], "GNL-2027-8103")
    for party in (prp_a, prp_b, prp_c):
        record_election(party["id"], "PARTICIPATE")
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1964)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1983)
    add_verified_waste_in(site["id"], prp_c["id"], 100, "III", "C", 1985)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 metals in soil and fill",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    open_balloting(allocation_round["id"])
    cast_ballot(allocation_round["id"], prp_a["id"], "ACCEPT")
    cast_ballot(allocation_round["id"], prp_b["id"], "ACCEPT")
    # The third ballot is what makes balloted_count equal share_count, so the
    # round resolves to ADOPTED before the transporter is recorded defunct and
    # the adopted-round orphan cascade can fire.
    cast_ballot(allocation_round["id"], prp_c["id"], "ACCEPT")
    record_defunct(prp_c["id"], "Charter forfeited in 2004; no successor and no assets.")
    post_oversight(
        site["id"],
        4_000_000,
        cost_category="RI_FS_OVERSIGHT",
        incurred_on="2027-02-20",
    )
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "prp_c": prp_c,
        "round": read_round(allocation_round["id"]),
    }


class TestSettlementAndCollectionRefusals:
    def test_an_orphaned_respondent_carries_no_allocated_share_to_sue_over(self):
        """The write-off bucket is not a debtor.

        PRD: "The respondent must hold an `ALLOCATED` share in that adopted round; a respondent who never received a share, or whose share has already been settled, is refused with `ERR_RESPONDENT_NOT_ALLOCATED`."

        Design: Corner/errors/corner_three_settlement_and_collection_refusals_return_4XX
        """
        scenario = _marrow_bend_adopted_with_an_orphan()
        prp_c = scenario["prp_c"]

        validate_error(
            api_client.create_cost_recovery_action(
                scenario["site"]["id"],
                factories.cost_recovery_action_payload(
                    respondent_prp_id=prp_c["id"],
                    action_type="COST_RECOVERY_DEMAND",
                    demanded_cents=91_938,
                    expected_prp_version=prp_version(prp_c["id"]),
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_RESPONDENT_NOT_ALLOCATED.value,
            409,
        )

        assert share_for(scenario["round"]["id"], prp_c["id"])["disposition"] == "ORPHANED"
        assert read_party(prp_c["id"])["status"] == "ORPHAN"
        _, meta = validate_paginated(api_client.list_cost_recovery_actions(COUNSEL))
        assert_pagination_meta(meta, total_count=0)

    def test_the_de_minimis_route_is_closed_to_the_largest_party_only(self):
        """Eligibility is a property of the party, not a switch on the feature.

        PRD: "The respondent's `de_minimis_eligible` flag must be true — an ineligible party is refused with `ERR_NOT_DE_MINIMIS_ELIGIBLE` (HTTP 409) — and the `demanded_cents` must be at or above the computed `premium_floor_cents`, with an offer exactly at the floor accepted and anything below it refused with `ERR_DE_MINIMIS_PREMIUM_INSUFFICIENT` (HTTP 422)."

        Design: Corner/errors/corner_three_settlement_and_collection_refusals_return_4XX
        """
        scenario = _marrow_bend_adopted_with_an_orphan()
        prp_a = scenario["prp_a"]
        prp_b = scenario["prp_b"]

        validate_error(
            api_client.create_cost_recovery_action(
                scenario["site"]["id"],
                factories.cost_recovery_action_payload(
                    respondent_prp_id=prp_a["id"],
                    action_type="DE_MINIMIS_SETTLEMENT",
                    demanded_cents=900_000_000,
                    expected_prp_version=prp_version(prp_a["id"]),
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_NOT_DE_MINIMIS_ELIGIBLE.value,
            409,
        )

        party_a = read_party(prp_a["id"])
        assert party_a["de_minimis_eligible"] is False
        assert party_a["max_toxicity_class"] == "II"
        assert_percentage(
            share_for(scenario["round"]["id"], prp_a["id"])["final_pct"],
            97.31,
            field="final_pct",
        )

        party_b = read_party(prp_b["id"])
        assert party_b["de_minimis_eligible"] is True
        assert party_b["max_toxicity_class"] == "IV"
        assert_percentage(
            party_b["volumetric_share_pct"], 0.98, field="volumetric_share_pct"
        )

    def test_a_receipt_one_cent_over_the_demand_is_refused_and_the_exact_one_closes_it(
        self,
    ):
        """Overpayment is rejected outright, so the ledger closes only on the cent.

        PRD: "Overpayment is refused, never clamped: the receipt may not exceed the amount still outstanding, that is `demanded_cents` minus the `received_cents` already booked, and a larger receipt is rejected with `ERR_OVERPAYMENT_NOT_ALLOWED` (HTTP 422) with nothing recorded."

        Design: Corner/errors/corner_three_settlement_and_collection_refusals_return_4XX
        """
        scenario = _marrow_bend_adopted_with_an_orphan()
        site_id = scenario["site"]["id"]
        prp_a = scenario["prp_a"]

        action = issue_action(
            site_id,
            prp_a["id"],
            4_528_062,
            action_type="COST_RECOVERY_DEMAND",
            expected_prp_version=prp_version(prp_a["id"]),
        )
        assert action["status"] == "OFFERED"
        assert action["received_cents"] == 0
        assert action["premium_floor_cents"] is None
        assert_percentage(
            action["respondent_share_pct_at_offer"],
            97.31,
            field="respondent_share_pct_at_offer",
        )
        respond_to_action(action["id"], prp_a["id"], "ACCEPT")

        validate_error(
            api_client.record_collection(
                action["id"],
                factories.collection_payload(
                    received_cents=4_528_063, receipt_reference="WIRE-MBR-0001"
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_OVERPAYMENT_NOT_ALLOWED.value,
            422,
        )
        midway = read_action(action["id"])
        assert midway["status"] == "ACCEPTED"
        assert midway["received_cents"] == 0

        collected = record_collection(action["id"], 4_528_062, "WIRE-MBR-0002")
        assert collected["status"] == "COLLECTED"
        assert collected["received_cents"] == 4_528_062

        ledger = read_ledger(site_id)
        assert_ledger_figures(ledger, 4_620_000, 4_528_062, 91_938, 0)
        assert ledger["ledger_balanced"] is True
        final_round = read_round(scenario["round"]["id"])
        assert_percentage(
            final_round["allocated_share_total_pct"],
            98.01,
            field="allocated_share_total_pct",
        )
        assert_percentage(final_round["orphan_share_pct"], 1.99, field="orphan_share_pct")
        assert_percentage(
            final_round["settled_share_pct"], 0.00, field="settled_share_pct"
        )


def _windrow_quarry_in_operations_and_maintenance():
    """Construction certified complete at 2029-05-15T10:00:00Z."""
    set_clock("2027-02-01T09:00:00Z")
    return build_operations_and_maintenance_site(
        site_name="Windrow Quarry Disposal",
        epa_region=8,
        hrs_score=45.60,
        exposure_medium="SOIL",
        contaminant="ARSENIC",
        concentration_ug_per_l=25.0,
        collected_at="2027-01-21T13:00:00Z",
        alternative={
            "label": "A - drum removal with cap",
            "capital_cost_cents": 938_888_889,
            "annual_om_cost_cents": 40_000_000,
            "om_years": 2,
            "discount_rate_bp": 2000,
            "effectiveness_score": 81,
            "implementability_score": 77,
        },
        comment_period_days=30,
        open_at="2027-03-01T09:00:00Z",
        sign_at="2027-04-01T09:00:00Z",
        engineer_estimate_cents=800_000_000,
        awarded_amount_cents=800_000_000,
        max_concurrent_windows=2,
        complete_at="2029-05-15T10:00:00Z",
        punch_list_items=0,
        work_window_start="2029-03-01T08:00:00Z",
        work_window_end="2029-03-01T16:00:00Z",
    )


class TestFiveYearReviewTiming:
    def test_a_review_one_day_before_the_due_instant_is_refused(self):
        """The statutory cycle admits the due instant but nothing earlier.

        PRD: "A review is accepted only when the site is in `OM_PHASE` and only when the logical clock has reached `five_year_review_due_at`, with the due instant itself qualifying; an early review is refused with `ERR_FIVE_YEAR_REVIEW_NOT_DUE`."

        Design: Corner/errors/corner_five_year_review_one_day_early_returns_4XX
        """
        scenario = _windrow_quarry_in_operations_and_maintenance()
        site_id = scenario["site"]["id"]
        assert scenario["site"]["listing_status"] == "OM_PHASE"

        set_clock("2034-05-14T10:00:00Z")
        validate_error(
            api_client.record_five_year_review(
                site_id,
                factories.five_year_review_payload(
                    protectiveness_determination="PROTECTIVE",
                    deletion_recommended=False,
                    review_summary="Cap intact; groundwater stable.",
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_FIVE_YEAR_REVIEW_NOT_DUE.value,
            409,
        )

        after = read_site(site_id)
        assert after["listing_status"] == "OM_PHASE"
        assert after["last_five_year_review_at"] in (None, "")
        assert after["five_year_review_due_at"].startswith("2034-05-15T00:00:00")

    def test_completion_normalises_to_midnight_and_schedules_1826_days_out(self):
        """The cycle is anchored on the completion date at midnight UTC.

        PRD: "The site's `five_year_review_due_at` is set to `construction_complete_at` plus 1,826 days — five calendar years including one leap day — also at exactly midnight UTC."

        Design: Corner/errors/corner_five_year_review_one_day_early_returns_4XX
        """
        scenario = _windrow_quarry_in_operations_and_maintenance()
        site = read_site(scenario["site"]["id"])

        assert site["construction_complete_at"].startswith("2029-05-15T00:00:00")
        assert site["five_year_review_due_at"].startswith("2034-05-15T00:00:00")
        completed = datetime.strptime(site["construction_complete_at"][:10], "%Y-%m-%d")
        due = datetime.strptime(site["five_year_review_due_at"][:10], "%Y-%m-%d")
        assert_days_between((due - completed).days, 1826, "five-year review cycle")

        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "CONSTRUCTION_COMPLETE"
        assert contract["punch_list_items"] == 0
        assert contract["work_window_count"] == 1
