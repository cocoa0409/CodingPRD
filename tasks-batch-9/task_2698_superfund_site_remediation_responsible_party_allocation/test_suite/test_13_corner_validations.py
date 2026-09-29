"""Validation-order probes: shape gates, path precedence, windows, tolerances.

These exercise the ordered validation sequence — which of two applicable rules
answers first, when a rule is conditional on some other record existing, and
where an inclusive tolerance or a closed time window actually sits.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_oversight_figures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    alternatives_of,
    award_contract,
    create_approved_investigation,
    create_investigation,
    create_signed_rod,
    create_site,
    create_rod,
    create_solicitation,
    file_comment,
    list_site_on_npl,
    open_comment_period,
    read_contract,
    read_rod,
    read_site,
    set_clock,
    site_version,
)
from test_helpers.test_users import SIGNER_PM_ID, TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
COMMUNITY = TEST_USERS["community_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]

UNKNOWN_SITE_ID = "6b1f2c47-0000-4000-8000-000000000abc"
UNKNOWN_PRP_ID = "6b1f2c47-0000-4000-8000-000000000def"


def _kettle_bluff_site_without_parties():
    """A listed site with an investigation but not one party named."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Kettle Bluff Landfill", epa_region=7, hrs_score=36.80)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-KBL-0201")
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 landfill gas and leachate",
    )
    return site


class TestAllocationWeightNormalisation:
    def test_weights_that_miss_ten_thousand_by_one_basis_point_are_refused(self):
        """The triple must total exactly 10,000 basis points.

        PRD: "Any other total is refused with `ERR_WEIGHTS_NOT_NORMALIZED` (HTTP 422)."

        Design: Corner/validations/corner_allocation_weights_that_miss_10000_by_one_bp_return_4XX
        """
        site = _kettle_bluff_site_without_parties()
        version_before = site_version(site["id"], FACILITATOR)

        refusal = api_client.create_allocation_round(
            site["id"],
            factories.allocation_round_payload(
                expected_site_version=version_before,
                weight_volume_bp=5000,
                weight_toxicity_bp=3000,
                weight_ownership_bp=1999,
            ),
            FACILITATOR,
        )
        validate_error(refusal, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED, 422)

        rounds, meta = validate_paginated(
            api_client.list_site_allocation_rounds(site["id"], AUTHOR)
        )
        assert meta["total_count"] == 0
        assert rounds == []
        assert read_site(site["id"])["version"] == version_before

    def test_the_normalisation_check_answers_before_the_no_basis_check(self):
        """This site would also fail the allocation-basis rule, but that runs later.

        PRD: "Requests are validated in a strictly ordered sequence, and the **first** failing check determines the response."

        Design: Corner/validations/corner_allocation_weights_that_miss_10000_by_one_bp_return_4XX
        """
        site = _kettle_bluff_site_without_parties()

        refusal = api_client.create_allocation_round(
            site["id"],
            factories.allocation_round_payload(
                expected_site_version=site_version(site["id"], FACILITATOR),
                weight_volume_bp=5000,
                weight_toxicity_bp=3000,
                weight_ownership_bp=1999,
            ),
            FACILITATOR,
        )
        body = validate_error(refusal, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED, 422)
        assert body["error_id"] != ApiErrorId.ERR_NO_ALLOCATION_BASIS


class TestPathExistenceOutranksBodyReference:
    def test_an_unknown_site_in_the_path_answers_before_an_unknown_party_in_the_body(
        self,
    ):
        """Both identifiers are unknown, and the path one is reported.

        PRD: "The error reported is the one belonging to the first identifier in the path that does not resolve — `ERR_SITE_NOT_FOUND`, `ERR_PRP_NOT_FOUND`, `ERR_WASTE_IN_RECORD_NOT_FOUND`, `ERR_REMEDIAL_INVESTIGATION_NOT_FOUND`, `ERR_RECORD_OF_DECISION_NOT_FOUND`, `ERR_ALLOCATION_ROUND_NOT_FOUND`, `ERR_CONSENT_DECREE_NOT_FOUND`, `ERR_REMEDIATION_CONTRACT_NOT_FOUND` or `ERR_COST_RECOVERY_ACTION_NOT_FOUND`, all HTTP 404."

        Design: Corner/validations/corner_unknown_site_outranks_unknown_prp_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        real_site = create_site(
            name="Ivy Shoals Foundry", epa_region=4, hrs_score=44.00
        )
        real_site = list_site_on_npl(
            real_site["id"], listing_reference="FR-2027-ISF-0104"
        )

        refusal = api_client.create_waste_in_record(
            UNKNOWN_SITE_ID,
            factories.waste_in_payload(
                prp_id=UNKNOWN_PRP_ID,
                volume_tons=50,
                toxicity_class="III",
                evidence_grade="C",
                disposal_year=1981,
            ),
            AUTHOR,
        )
        body = validate_error(refusal, ApiErrorId.ERR_SITE_NOT_FOUND, 404)
        assert body["error_id"] != ApiErrorId.ERR_PRP_NOT_FOUND

        records, meta = validate_paginated(
            api_client.list_site_waste_in_records(real_site["id"], AUTHOR)
        )
        assert meta["total_count"] == 0
        assert records == []
        assert read_site(real_site["id"])["verified_waste_volume_tons"] == 0


def _nettle_fork_open_comment_period():
    """A decision document whose comment window runs 2027-03-01 to 2027-03-31."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Nettle Fork Wood Treating", epa_region=4, hrs_score=43.70
    )
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-NFW-0201")
    investigation = create_approved_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        samples=[
            {
                "contaminant": "PENTACHLOROPHENOL",
                "concentration_ug_per_l": 25.0,
                "qa_status": "VALID",
                "collected_at": "2027-01-25T10:00:00Z",
                "lab_reference": "LAB-NFW-0001",
            }
        ],
    )
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Groundwater extraction with in situ oxidation",
    )
    set_clock("2027-03-01T09:00:00Z")
    opened = open_comment_period(rod["id"])
    return {"site": site, "rod": opened}


class TestPublicCommentWindow:
    def test_a_comment_filed_inside_the_window_is_accepted(self):
        """The window is thirty days from the instant the period opened.

        PRD: "On acceptance the system stamps `comment_period_start` with the current logical clock and derives `comment_period_end` as that instant plus `comment_period_days` days."

        Design: Corner/validations/corner_public_comment_inside_the_window_passes_and_after_close_returns_4XX
        """
        world = _nettle_fork_open_comment_period()
        rod = world["rod"]
        assert rod["comment_period_start"].startswith("2027-03-01T09:00:00")
        assert rod["comment_period_end"].startswith("2027-03-31T09:00:00")

        set_clock("2027-03-15T12:00:00Z")
        filed = file_comment(
            rod["id"],
            commenter_name="Nettle Fork Neighbours Association",
            comment_text="Please add long-term private well sampling.",
        )
        assert filed["public_comments_count"] == 1
        assert filed["status"] == "PUBLIC_COMMENT"

    def test_the_same_body_is_refused_once_the_window_has_closed(self):
        """Only the logical clock moved, and the tally does not budge.

        PRD: "A comment filed after the window has closed — that is, when the logical clock has moved strictly past `comment_period_end` — or filed against a document that is not currently in `PUBLIC_COMMENT`, is refused with `ERR_COMMENT_PERIOD_CLOSED`."

        Design: Corner/validations/corner_public_comment_inside_the_window_passes_and_after_close_returns_4XX
        """
        world = _nettle_fork_open_comment_period()
        rod_id = world["rod"]["id"]

        set_clock("2027-03-15T12:00:00Z")
        file_comment(
            rod_id,
            commenter_name="Nettle Fork Neighbours Association",
            comment_text="Please add long-term private well sampling.",
        )

        set_clock("2027-04-01T09:00:00Z")
        refusal = api_client.file_public_comment(
            rod_id,
            factories.public_comment_payload(
                commenter_name="Nettle Fork Neighbours Association",
                comment_text="Late follow-up on the same request.",
            ),
            COMMUNITY,
        )
        validate_error(refusal, ApiErrorId.ERR_COMMENT_PERIOD_CLOSED, 409)

        after = read_rod(rod_id)
        assert after["public_comments_count"] == 1
        assert after["status"] == "PUBLIC_COMMENT"


class TestOversightCapIsConditionalOnAGoverningDecree:
    def test_a_posting_with_no_governing_instrument_is_accepted(self):
        """With no entered instrument there is no cap and no utilisation figure.

        PRD: "Where a governing instrument exists, `oversight_cap_utilization_pct` is the billed total multiplied by 100, divided by the cap, rounded half up to two decimal places; where the site has no governing instrument it is reported as empty, and no cap check applies."

        Design: Corner/validations/corner_oversight_cap_rule_applies_only_when_a_governing_decree_is_entered
        """
        set_clock("2027-05-19T08:00:00Z")
        site = create_site(name="Quarry Head Coke Plant", epa_region=5, hrs_score=50.10)
        site = list_site_on_npl(site["id"], listing_reference="FR-2027-QHC-0519")

        posted = validate_success(
            api_client.post_oversight_cost(
                site["id"],
                factories.oversight_cost_payload(
                    incurred_cents=9_000_000,
                    cost_category="RI_FS_OVERSIGHT",
                    incurred_on="2027-05-19",
                ),
                AUTHOR,
            )
        )
        assert posted["oversight_cap_utilization_pct"] is None
        assert posted["cost_posture"] == "OPEN"

    def test_the_whole_subtotal_is_rated_at_the_second_tier(self):
        """A nine-million-cent subtotal bills at 1275 basis points.

        PRD: "The `oversight_indirect_cents` figure is therefore the whole `oversight_direct_cents` subtotal multiplied by the selected rate in basis points, divided by 10,000, rounded half up to whole cents; and `oversight_billed_cents` is the direct subtotal plus that indirect figure."

        Design: Corner/validations/corner_oversight_cap_rule_applies_only_when_a_governing_decree_is_entered
        """
        set_clock("2027-05-19T08:00:00Z")
        site = create_site(name="Quarry Head Coke Plant", epa_region=5, hrs_score=50.10)
        site = list_site_on_npl(site["id"], listing_reference="FR-2027-QHC-0519")

        validate_success(
            api_client.post_oversight_cost(
                site["id"],
                factories.oversight_cost_payload(
                    incurred_cents=9_000_000,
                    cost_category="RI_FS_OVERSIGHT",
                    incurred_on="2027-05-19",
                ),
                AUTHOR,
            )
        )
        after = read_site(site["id"])
        assert_oversight_figures(
            after,
            direct=9_000_000,
            rate_bp=1275,
            indirect=1_147_500,
            billed=10_147_500,
        )
        assert after["total_response_cost_cents"] == 10_147_500
        assert after["unrecovered_cost_cents"] == 10_147_500


def _vail_junction_two_solicitations():
    """A signed decision with two identical solicitations at a one-billion estimate."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Vail Junction Rail Yard", epa_region=8, hrs_score=52.30)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-VJR-0201")
    investigation = create_approved_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        samples=[
            {
                "contaminant": "BENZENE",
                "concentration_ug_per_l": 25.0,
                "qa_status": "VALID",
                "collected_at": "2027-01-18T09:30:00Z",
                "lab_reference": "LAB-VJR-0001",
            }
        ],
        alternatives=[
            {
                "label": "A - excavation with off-site disposal",
                "capital_cost_cents": 938_888_889,
                "annual_om_cost_cents": 40_000_000,
                "om_years": 2,
                "discount_rate_bp": 2000,
                "effectiveness_score": 75,
                "implementability_score": 80,
            }
        ],
    )
    rod = create_signed_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        open_at="2027-03-01T09:00:00Z",
        sign_at="2027-04-01T09:00:00Z",
    )
    contract_pass = create_solicitation(
        site["id"],
        rod["id"],
        engineer_estimate_cents=1_000_000_000,
        solicitation_reference="SOL-VJR-0001",
    )
    contract_fail = create_solicitation(
        site["id"],
        rod["id"],
        engineer_estimate_cents=1_000_000_000,
        solicitation_reference="SOL-VJR-0002",
    )
    return {
        "site": site,
        "investigation": investigation,
        "rod": rod,
        "contract_pass": contract_pass,
        "contract_fail": contract_fail,
    }


class TestBidTolerance:
    def test_a_bid_exactly_at_the_tolerance_is_awarded(self):
        """One hundred and fifteen percent of the estimate is still acceptable.

        PRD: "Bid reasonableness is tested against a tolerance of 1,500 basis points over the engineer's estimate: the `awarded_amount_cents` may not exceed the `engineer_estimate_cents` multiplied by one plus 1,500 divided by 10,000 — that is, 115 percent of the estimate — and a bid exactly at the tolerance passes."

        Design: Corner/validations/corner_bid_exactly_at_the_tolerance_is_awarded_and_one_cent_over_returns_4XX
        """
        world = _vail_junction_two_solicitations()

        awarded = award_contract(
            world["contract_pass"]["id"],
            awarded_amount_cents=1_150_000_000,
            contractor_name="Sandhill Environmental JV",
            max_concurrent_windows=2,
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 1_150_000_000

        site = read_site(world["site"]["id"])
        assert site["listing_status"] == "CONSTRUCTION"
        assert site["total_response_cost_cents"] == 1_150_000_000
        assert site["unrecovered_cost_cents"] == 1_150_000_000
        assert site["recovered_cost_cents"] == 0

        rod = read_rod(world["rod"]["id"])
        assert rod["status"] == "SIGNED"
        assert rod["signed_by_user_id"] == SIGNER_PM_ID
        assert rod["selected_alternative_id"] == alternatives_of(
            world["investigation"]["id"]
        )[0]["id"]

    def test_a_bid_one_cent_above_the_tolerance_is_refused(self):
        """The sibling contract stays in solicitation with nothing stamped.

        PRD: "A bid above it is refused with `ERR_BID_EXCEEDS_ESTIMATE` (HTTP 422)."

        Design: Corner/validations/corner_bid_exactly_at_the_tolerance_is_awarded_and_one_cent_over_returns_4XX
        """
        world = _vail_junction_two_solicitations()

        refusal = api_client.award_contract(
            world["contract_fail"]["id"],
            factories.award_payload(
                awarded_amount_cents=1_150_000_001,
                contractor_name="Sandhill Environmental JV",
                max_concurrent_windows=2,
            ),
            AUTHOR,
        )
        validate_error(refusal, ApiErrorId.ERR_BID_EXCEEDS_ESTIMATE, 422)

        after = read_contract(world["contract_fail"]["id"])
        assert after["status"] == "SOLICITATION"
        assert after["awarded_amount_cents"] in (None, 0)
        assert after["contractor_name"] in (None, "")
