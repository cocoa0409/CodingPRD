"""One request that breaks two rules at once reports only the earlier rule.

Each scenario is engineered so a single call violates a pair of checks from
different categories; the response must name the check that sits earlier in the
validation order, and the later breach must leave no trace.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import validate_error
from test_helpers.fixtures import (
    add_alternative,
    add_sample,
    add_verified_waste_in,
    adopt_round,
    alternatives_of,
    create_decree,
    create_investigation,
    create_listed_site,
    create_participating_party,
    create_rod,
    enter_decree,
    lodge_decree,
    open_comment_period,
    open_round,
    read_decree,
    read_rod,
    read_site,
    record_penalty_assessment,
    record_violation,
    review_investigation,
    set_clock,
    submit_investigation,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
SIGNER = TEST_USERS["signer_pm_headers"]


def _belmont_frozen_site():
    """A site frozen by an accruing penalty, with nothing billed yet."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(name="Belmont Tannery", epa_region=1, hrs_score=41.30)
    prp_a = create_participating_party(
        site["id"],
        legal_name="Belmont Leather Co",
        party_type="OWNER_OPERATOR",
        viability_score=76,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Quarry Dye Works LLC",
        party_type="GENERATOR",
        viability_score=33,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1972)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1990)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 chromium in soil and groundwater",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    decree = create_decree(
        site["id"],
        [prp_a["id"], prp_b["id"]],
        scope_type="RD_RA_CONSENT_DECREE",
        scope_summary="RD/RA with a hard oversight reimbursement cap",
        oversight_cost_cap_cents=4_000_000,
        stipulated_penalty_per_day_cents=250_000,
        performance_deadline="2028-09-30",
    )
    set_clock("2027-03-01T10:00:00Z")
    lodge_decree(decree["id"])
    set_clock("2027-04-01T09:00:00Z")
    enter_decree(decree["id"], court_docket_number="1:27-cv-00551-BLT")
    record_violation(
        decree["id"], "2027-04-05T00:00:00Z", violation_type="MISSED_MILESTONE"
    )
    set_clock("2027-05-20T08:00:00Z")
    record_penalty_assessment(decree["id"], "2027-05-20T00:00:00Z")
    return site, decree


def _post_the_over_cap_oversight_cost(site_id):
    """One posting that is both blocked by the freeze and over the fiscal cap."""
    return api_client.post_oversight_cost(
        site_id,
        factories.oversight_cost_payload(
            incurred_cents=9_000_000,
            cost_category="RD_RA_OVERSIGHT",
            incurred_on="2027-05-19",
        ),
        AUTHOR,
    )


class TestFrozenPostureOutranksOversightCapExceeded:
    def test_the_freeze_answers_and_the_fiscal_breach_is_never_reported(self):
        """The earlier state gate wins over the later fiscal gate.

        PRD: "Requests are validated in a strictly ordered sequence, and the **first** failing check determines the response."

        Design: Difficulty/priority_pair_validation_conflict/frozen_site_posture_outranks_oversight_cap_exceeded_returns_4XX
        """
        site, _ = _belmont_frozen_site()

        body = validate_error(
            _post_the_over_cap_oversight_cost(site["id"]),
            ApiErrorId.ERR_SITE_COST_FROZEN.value,
        )
        assert body["error_id"] != ApiErrorId.ERR_OVERSIGHT_CAP_EXCEEDED.value

    def test_the_refused_posting_leaves_every_oversight_field_untouched(self):
        """A refused posting bills nothing at all.

        PRD: "While a site is `FROZEN`, four operations are refused with `ERR_SITE_COST_FROZEN` (HTTP 409): posting oversight cost, opening an allocation round, issuing a recovery action, and scheduling a field-work window."

        Design: Difficulty/priority_pair_validation_conflict/frozen_site_posture_outranks_oversight_cap_exceeded_returns_4XX
        """
        site, _ = _belmont_frozen_site()
        _post_the_over_cap_oversight_cost(site["id"])

        after = read_site(site["id"])
        assert after["cost_posture"] == "FROZEN"
        assert after["oversight_direct_cents"] == 0
        assert after["oversight_indirect_cents"] == 0
        assert after["oversight_billed_cents"] == 0
        assert after["total_response_cost_cents"] == 0

    def test_the_accrued_penalty_that_caused_the_freeze_is_clamped_to_the_cap(self):
        """The gross accrual is clipped to ten percent of the oversight cap.

        PRD: "The `accrued_penalty_cents` is whichever is smaller of the gross accrual and that cap, and `penalty_capped` is set true precisely when the gross accrual exceeded the cap and was clamped down to it, and false otherwise."

        Design: Difficulty/priority_pair_validation_conflict/frozen_site_posture_outranks_oversight_cap_exceeded_returns_4XX
        """
        site, decree = _belmont_frozen_site()
        _post_the_over_cap_oversight_cost(site["id"])

        after = read_decree(decree["id"])
        assert after["accrued_penalty_cents"] == 400_000
        assert after["penalty_capped"] is True
        assert after["days_in_violation"] == 46
        assert after["compliance_status"] == "PENALTY_ACCRUING"


def _cedar_marsh_uncommented_rod():
    """A closed comment window with zero comments, plus a foreign alternative."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Cedar Marsh Wood Preserving", epa_region=4, hrs_score=48.90
    )
    ri1 = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 groundwater creosote plume",
    )
    add_sample(
        ri1["id"], "GROUNDWATER", "NAPHTHALENE", 18.0, "VALID",
        "2027-01-18T10:00:00Z", "LAB-C-0001",
    )
    submit_investigation(ri1["id"])
    review_investigation(ri1["id"], "APPROVE")
    alt_ri1 = add_alternative(
        ri1["id"],
        label="IN_SITU_THERMAL",
        capital_cost_cents=900_000_000,
        annual_om_cost_cents=18_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=80,
        implementability_score=70,
    )
    ri2 = create_investigation(
        site["id"],
        exposure_medium="SEDIMENT",
        scope_summary="OU-2 marsh sediment characterisation",
    )
    alt_x = add_alternative(
        ri2["id"],
        label="SEDIMENT_DREDGING",
        capital_cost_cents=400_000_000,
        annual_om_cost_cents=9_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=88,
        implementability_score=65,
    )
    rod = create_rod(
        site["id"],
        ri1["id"],
        comment_period_days=30,
        proposed_plan_summary="In-situ thermal treatment of the OU-1 source area.",
    )
    set_clock("2027-03-01T09:00:00Z")
    open_comment_period(rod["id"])
    set_clock("2027-04-01T09:00:00Z")
    return site, ri1, ri2, alt_ri1, alt_x, rod


def _sign_with_the_foreign_alternative(rod_id, alt_x_id):
    """One signature that both skips the community and names a foreign remedy."""
    return api_client.sign_record_of_decision(
        rod_id,
        factories.signature_payload(
            responsiveness_summary="No comments received.", alternative_id=alt_x_id
        ),
        SIGNER,
    )


class TestCommunityInvolvementOutranksForeignAlternative:
    def test_the_safety_gate_answers_before_the_referential_gate(self):
        """The community check sits ahead of the alternative-ownership check.

        PRD: "The community must actually have been heard: `public_comments_count` must be at least 1, and a document with no comments on file is refused with `ERR_COMMUNITY_INVOLVEMENT_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/community_involvement_outranks_foreign_alternative_on_rod_signature
        """
        _, _, _, _, alt_x, rod = _cedar_marsh_uncommented_rod()

        body = validate_error(
            _sign_with_the_foreign_alternative(rod["id"], alt_x["id"]),
            ApiErrorId.ERR_COMMUNITY_INVOLVEMENT_INCOMPLETE.value,
        )
        assert body["error_id"] != ApiErrorId.ERR_ALTERNATIVE_NOT_FOR_SITE.value

    def test_the_document_is_still_awaiting_comment_and_carries_no_signature(self):
        """A refused signature stamps nothing on the document.

        PRD: "The document records the `site_id` it covers, begins with `status` `DRAFT`, and starts with `public_comments_count` at zero, an empty `responsiveness_summary` and an empty `selected_alternative_id`."

        Design: Difficulty/priority_pair_validation_conflict/community_involvement_outranks_foreign_alternative_on_rod_signature
        """
        _, _, _, _, alt_x, rod = _cedar_marsh_uncommented_rod()
        _sign_with_the_foreign_alternative(rod["id"], alt_x["id"])

        after = read_rod(rod["id"])
        assert after["status"] == "PUBLIC_COMMENT"
        assert after["public_comments_count"] == 0
        assert after["selected_alternative_id"] in (None, "")
        assert after["signed_by_user_id"] in (None, "")
        assert after["signed_at"] in (None, "")

    def test_no_alternative_of_either_investigation_is_marked_as_selected(self):
        """Neither the foreign remedy nor the home remedy was chosen.

        PRD: "An explicitly named alternative must belong to the very investigation this document cites — an alternative that exists but was screened under a different investigation is refused with `ERR_ALTERNATIVE_NOT_FOR_SITE`, while an `alternative_id` that names no alternative at all anywhere in the system is refused with `ERR_REMEDY_ALTERNATIVE_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/community_involvement_outranks_foreign_alternative_on_rod_signature
        """
        site, ri1, ri2, alt_ri1, alt_x, rod = _cedar_marsh_uncommented_rod()
        _sign_with_the_foreign_alternative(rod["id"], alt_x["id"])

        foreign = [a for a in alternatives_of(ri2["id"]) if a["id"] == alt_x["id"]][0]
        home = [a for a in alternatives_of(ri1["id"]) if a["id"] == alt_ri1["id"]][0]
        assert foreign["selected_by_rod_id"] in (None, "")
        assert home["selected_by_rod_id"] in (None, "")
        assert read_site(site["id"])["listing_status"] == "RI_FS_UNDERWAY"
