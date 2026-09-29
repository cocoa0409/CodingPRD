"""One entity's transition is gated on the state of a different entity.

The decision document never changes while its comment period is refused twice
and then allowed; only the cited investigation moved. The settlement instrument
becomes lodgeable without any write to itself, because the site finally acquired
an adopted allocation round.
"""
from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_percentage,
    assert_share_totals,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_sample,
    add_verified_waste_in,
    cast_ballot,
    create_decree,
    create_investigation,
    create_listed_site,
    create_participating_party,
    create_rod,
    open_balloting,
    open_round,
    read_decree,
    read_investigation,
    read_rod,
    read_round,
    read_site,
    reopen_round,
    review_investigation,
    set_clock,
    submit_investigation,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def _ashwood_draft_rod():
    """A drafted decision document citing an investigation still under review."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(name="Ashwood Landfill", epa_region=6, hrs_score=52.10)
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 landfill leachate plume",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "VINYL_CHLORIDE", 24.0, "VALID",
        "2027-01-12T10:00:00Z", "LAB-A-0001",
    )
    submit_investigation(investigation["id"])
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Cap, gas collection and long-term groundwater monitoring.",
    )
    return site, investigation, rod


class TestCommentPeriodGatedOnTheCitedInvestigation:
    def test_the_same_call_is_refused_from_two_different_foreign_states(self):
        """Under review and awaiting revision both fail the same gate.

        PRD: "Opening the comment period moves the document `DRAFT → PUBLIC_COMMENT`, but only if the cited investigation has reached `APPROVED`; a decision resting on an investigation still in draft, under review or awaiting revision is refused with `ERR_RIFS_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/rod_comment_period_gated_on_the_cited_rifs_status_not_the_rod_status
        """
        _, investigation, rod = _ashwood_draft_rod()

        assert read_investigation(investigation["id"])["status"] == "UNDER_REVIEW"
        validate_error(
            api_client.open_comment_period(rod["id"], AUTHOR),
            ApiErrorId.ERR_RIFS_NOT_APPROVED.value,
        )

        review_investigation(
            investigation["id"],
            "REQUEST_REVISION",
            "Delineate the eastern plume boundary.",
        )
        assert read_investigation(investigation["id"])["status"] == "REVISION_REQUESTED"
        validate_error(
            api_client.open_comment_period(rod["id"], AUTHOR),
            ApiErrorId.ERR_RIFS_NOT_APPROVED.value,
        )

    def test_the_refused_document_is_untouched_by_either_refusal(self):
        """A refused transition stamps no window on the document.

        PRD: "The document records the `site_id` it covers, begins with `status` `DRAFT`, and starts with `public_comments_count` at zero, an empty `responsiveness_summary` and an empty `selected_alternative_id`."

        Design: Difficulty/cross_entity_state_dependency/rod_comment_period_gated_on_the_cited_rifs_status_not_the_rod_status
        """
        _, investigation, rod = _ashwood_draft_rod()
        api_client.open_comment_period(rod["id"], AUTHOR)
        review_investigation(
            investigation["id"],
            "REQUEST_REVISION",
            "Delineate the eastern plume boundary.",
        )
        api_client.open_comment_period(rod["id"], AUTHOR)

        after = read_rod(rod["id"])
        assert after["status"] == "DRAFT"
        assert after["comment_period_start"] in (None, "")
        assert after["comment_period_end"] in (None, "")
        assert after["version"] == rod["version"]

    def test_approval_of_the_foreign_entity_alone_unlocks_the_window(self):
        """The revision cycle closes and the window opens on the clock.

        PRD: "On acceptance the system stamps `comment_period_start` with the current logical clock and derives `comment_period_end` as that instant plus `comment_period_days` days."

        Design: Difficulty/cross_entity_state_dependency/rod_comment_period_gated_on_the_cited_rifs_status_not_the_rod_status
        """
        _, investigation, rod = _ashwood_draft_rod()
        api_client.open_comment_period(rod["id"], AUTHOR)
        review_investigation(
            investigation["id"],
            "REQUEST_REVISION",
            "Delineate the eastern plume boundary.",
        )
        api_client.open_comment_period(rod["id"], AUTHOR)
        submit_investigation(investigation["id"])
        review_investigation(investigation["id"], "APPROVE")

        approved = read_investigation(investigation["id"])
        assert approved["status"] == "APPROVED"
        assert approved["revision_round_count"] == 1
        assert approved["approved_by_user_id"] == "rpm-002"

        set_clock("2027-03-01T09:00:00Z")
        opened = validate_success(api_client.open_comment_period(rod["id"], AUTHOR))
        assert opened["status"] == "PUBLIC_COMMENT"
        assert opened["comment_period_start"].startswith("2027-03-01T09:00:00")
        assert opened["comment_period_end"].startswith("2027-03-31T09:00:00")
        assert opened["public_comments_count"] == 0


def _fallow_yard_failed_round():
    """A decree in negotiation behind a round that the parties voted down."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Fallow Yard Rail Salvage", epa_region=7, hrs_score=43.10
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Fallow Rail Co",
        party_type="OWNER_OPERATOR",
        viability_score=80,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Yardside Painting LLC",
        party_type="GENERATOR",
        viability_score=25,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1968)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "C", 1986)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 lead and PCB in yard soils",
    )
    decree = create_decree(
        site["id"],
        [prp_a["id"], prp_b["id"]],
        scope_type="RD_RA_CONSENT_DECREE",
        scope_summary="Yard-wide soil removal and cover.",
        oversight_cost_cap_cents=12_000_000,
        stipulated_penalty_per_day_cents=180_000,
        performance_deadline="2029-06-30",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    open_balloting(allocation_round["id"])
    cast_ballot(
        allocation_round["id"],
        prp_a["id"],
        "REJECT",
        ballot_rationale="Ownership factor ignored.",
    )
    cast_ballot(allocation_round["id"], prp_b["id"], "ACCEPT")
    return site, prp_a, prp_b, decree, allocation_round


class TestDecreeLodgingGatedOnAnAdoptedRoundExisting:
    def test_a_failed_round_leaves_the_decree_stuck_even_though_a_round_exists(self):
        """The gate reads the site's adopted round, not the mere existence of one.

        PRD: "The site must already have an adopted allocation round, because a settlement whose payment shares have not been agreed has nothing to settle; a lodging attempted before adoption is refused with `ERR_NO_ADOPTED_ALLOCATION`."

        Design: Difficulty/cross_entity_state_dependency/decree_lodging_gated_on_the_sites_allocation_round_reaching_adopted
        """
        site, _, _, decree, allocation_round = _fallow_yard_failed_round()

        failed = read_round(allocation_round["id"])
        assert failed["status"] == "FAILED"
        assert_percentage(failed["accept_share_pct"], 0.72, "accept_share_pct")
        assert read_site(site["id"])["adopted_round_id"] in (None, "")

        validate_error(
            api_client.lodge_consent_decree(decree["id"], COUNSEL),
            ApiErrorId.ERR_NO_ADOPTED_ALLOCATION.value,
        )
        after = read_decree(decree["id"])
        assert after["legal_status"] == "NEGOTIATING"
        assert after["lodged_at"] in (None, "")
        assert after["public_comment_close_at"] in (None, "")

    def test_reopening_from_failure_clears_the_ballot_tally(self):
        """Both reopening paths clear the same fields.

        PRD: "Reopening clears `ballot`, `ballot_rationale` and `ballot_cast_at` on every share, resets `balloted_count` to 0 and `accept_share_pct` to 0.00, re-derives `provisional_pct` against current data, and mints shares for any party that has entered the candidate set since the round was opened."

        Design: Difficulty/cross_entity_state_dependency/decree_lodging_gated_on_the_sites_allocation_round_reaching_adopted
        """
        _, _, _, decree, allocation_round = _fallow_yard_failed_round()
        api_client.lodge_consent_decree(decree["id"], COUNSEL)

        reopened = reopen_round(
            allocation_round["id"], revision_note="Reopened after the failed vote."
        )
        assert reopened["status"] == "DRAFTING"
        assert reopened["balloted_count"] == 0
        assert_percentage(reopened["accept_share_pct"], 0.00, "accept_share_pct")

    def test_adoption_of_the_round_alone_makes_the_decree_lodgeable(self):
        """No write touches the instrument, yet the gate now passes.

        PRD: "Lodging stamps `lodged_at` with the logical clock and derives `public_comment_close_at` as 30 days after that instant."

        Design: Difficulty/cross_entity_state_dependency/decree_lodging_gated_on_the_sites_allocation_round_reaching_adopted
        """
        site, prp_a, prp_b, decree, allocation_round = _fallow_yard_failed_round()
        api_client.lodge_consent_decree(decree["id"], COUNSEL)
        reopen_round(allocation_round["id"], revision_note="Reopened after the failed vote.")
        open_balloting(allocation_round["id"])
        cast_ballot(allocation_round["id"], prp_a["id"], "ACCEPT")
        cast_ballot(allocation_round["id"], prp_b["id"], "ACCEPT")

        # The round's own fields are read from the round endpoint the PRD
        # documents for them; the ballot POST acts on the party's share.
        adopted = read_round(allocation_round["id"])
        assert adopted["status"] == "ADOPTED"
        assert_percentage(adopted["accept_share_pct"], 100.00, "accept_share_pct")
        assert_share_totals(adopted, 100.00, 0.00, 0.00)
        assert read_site(site["id"])["adopted_round_id"] == allocation_round["id"]

        set_clock("2027-04-10T11:00:00Z")
        lodged = validate_success(api_client.lodge_consent_decree(decree["id"], COUNSEL))
        assert lodged["legal_status"] == "LODGED"
        assert lodged["lodged_at"].startswith("2027-04-10T11:00:00")
        assert lodged["public_comment_close_at"].startswith("2027-05-10T11:00:00")
        assert lodged["compliance_status"] == "COMPLIANT"
        assert read_site(site["id"])["cost_posture"] == "OPEN"
