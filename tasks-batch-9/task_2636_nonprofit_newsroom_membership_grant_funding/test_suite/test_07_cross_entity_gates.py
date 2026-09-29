"""Gates whose decisive input lives on a different entity than the one written.

In each case the request under test is byte-identical before and after the other
entity changes, so the gate cannot be attributed to the request's own payload.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    file_disclosure,
    read_coverage_area,
    read_funder,
    read_gift_offer,
    read_proposal,
    read_sustainability,
    read_transparency_report,
    ratify_gift_offer,
    review_gift_offer,
    setup_disclosed_and_cleared_funder,
    setup_gift_offer_in_review,
    setup_period_and_area,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    DO2_HEADERS,
    ED2_HEADERS,
    FC_HEADERS,
    draft_proposal,
    open_fiscal_period,
    proposal_pipeline_action,
    register_coverage_area,
)
from test_helpers.test_users import USER_IDS

_CLIMATE_DISCLOSURE = (
    "Sable Ridge funds climate coverage; the climate desk retains sole "
    "editorial control."
)


def _setup_cleared_gift_offer_from_a_high_risk_funder():
    """A 200000-cent designated offer, CLEARED, from a funder whose independence
    risk score is 48: at the ratification floor but under the hard bar."""
    period, area = setup_period_and_area(
        area_code="CLIMATE", area_name="Climate and energy"
    )
    pair = setup_disclosed_and_cleared_funder(
        area["id"],
        legal_name="Sable Ridge Foundation",
        basis="AUDITED",
        audited_advocacy_index=7,
        affiliated=True,
        self_attested_advocacy=True,
        disclosure_text=_CLIMATE_DISCLOSURE,
    )
    ctx = setup_gift_offer_in_review(
        offered_amount_cents=200000,
        designation="PROGRAM_RESTRICTED",
        coverage_area_id=area["id"],
        period=period,
        funder=pair["funder"],
    )
    ctx["offer"] = review_gift_offer(
        ctx["offer"]["id"],
        "CLEAR",
        ED2_HEADERS,
        review_note="No conditions; disclosure current.",
    )
    ctx["area"] = area
    ctx["disclosure"] = pair["disclosure"]
    return ctx


class TestGiftAcceptanceIsGatedByTheFundersRiskScore:
    """A small gift needs board ratification purely because of the funder."""

    def test_a_small_gift_needs_ratification_on_the_funders_score_alone(self):
        """200000 is far below the 2500000 amount trigger and carries no fee, yet
        the funder's score of 48 has reached 40, so ratification is required.

        PRD: "Third, and also keyed on the gross, `board_ratification_required`
        becomes true when either `offered_amount_cents` has reached **2500000
        cents** (25,000 dollars) or the funder's current `independence_risk_score`
        has reached 40; otherwise it is false."

        Design: Difficulty/cross_entity_state_dependency/ce_gift_acceptance_gated_by_funder_risk_derived_board_ratification
        """
        ctx = _setup_cleared_gift_offer_from_a_high_risk_funder()

        assert read_funder(ctx["funder"]["id"])["independence_risk_score"] == 48

        offer = ctx["offer"]
        assert offer["status"] == "CLEARED"
        assert offer["stewardship_fee_cents"] == 0
        assert offer["net_acceptable_amount_cents"] == 200000
        assert offer["board_ratification_required"] is True
        assert offer["board_ratified_by_user_id"] is None
        assert offer["acceptance_gate_score"] == 48

    def test_the_unratified_acceptance_is_refused_and_writes_nothing(self):
        """The offer stays CLEARED and the cascade's contribution is never minted.

        PRD: "If `board_ratification_required` is true,
        `board_ratified_by_user_id` must be non-null, or
        `ERR_BOARD_RATIFICATION_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/ce_gift_acceptance_gated_by_funder_risk_derived_board_ratification
        """
        ctx = _setup_cleared_gift_offer_from_a_high_risk_funder()

        response = api_client.accept_gift_offer(
            ctx["offer"]["id"], {"received_date": "2026-08-20"}, DO2_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_BOARD_RATIFICATION_REQUIRED)

        assert read_gift_offer(ctx["offer"]["id"])["status"] == "CLEARED"
        rows, meta = validate_paginated(
            api_client.list_contributions(
                FC_HEADERS, params={"gift_offer_id": ctx["offer"]["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_ratification_is_a_self_loop_that_only_names_the_ratifier(self):
        """The board's ruling leaves the offer in CLEARED and changes exactly one
        field, which is what makes the following acceptance a clean comparison.

        PRD: "Ratification is a self-loop: the offer stays in `CLEARED` and only
        `board_ratified_by_user_id` changes, stamped with the ratifier's
        `X-User-ID`, alongside an optional `ratification_note`."

        Design: Difficulty/cross_entity_state_dependency/ce_gift_acceptance_gated_by_funder_risk_derived_board_ratification
        """
        ctx = _setup_cleared_gift_offer_from_a_high_risk_funder()

        ratified = ratify_gift_offer(
            ctx["offer"]["id"],
            ratification_note="Board reviewed the independence file and ratified the gift.",
        )
        assert ratified["status"] == "CLEARED"
        assert ratified["board_ratified_by_user_id"] == USER_IDS["board_oversight"]

    def test_the_identical_acceptance_succeeds_once_the_board_has_ratified(self):
        """Nothing about the request changes; only the ratification field does.

        PRD: "Acceptance takes the offer to the terminal status `ACCEPTED` and
        writes a contribution the client never asked for: a row on the
        `MAJOR_GIFT` revenue stream carrying this offer's `funder_id` and
        `gift_offer_id`, an `amount_cents` equal to `net_acceptable_amount_cents`
        - the **net**, not the gross - settlement status `INITIATED` and
        acknowledgment status `UNACKNOWLEDGED`."

        Design: Difficulty/cross_entity_state_dependency/ce_gift_acceptance_gated_by_funder_risk_derived_board_ratification
        """
        ctx = _setup_cleared_gift_offer_from_a_high_risk_funder()
        ratify_gift_offer(ctx["offer"]["id"])

        response = api_client.accept_gift_offer(
            ctx["offer"]["id"], {"received_date": "2026-08-20"}, DO2_HEADERS
        )
        assert response.status_code == 200
        assert read_gift_offer(ctx["offer"]["id"])["status"] == "ACCEPTED"

    def test_the_cascade_writes_one_initiated_major_gift_row(self):
        """The only discovery channel is the contributions list filtered by the
        offer, and the new row is not yet recognized revenue.

        PRD: "A `MAJOR_GIFT` carries no benefits, so `quid_pro_quo_cents` is 0 and
        `deductible_cents` is the whole `amount_cents`."

        Design: Difficulty/cross_entity_state_dependency/ce_gift_acceptance_gated_by_funder_risk_derived_board_ratification
        """
        ctx = _setup_cleared_gift_offer_from_a_high_risk_funder()
        ratify_gift_offer(ctx["offer"]["id"])
        api_client.accept_gift_offer(
            ctx["offer"]["id"], {"received_date": "2026-08-20"}, DO2_HEADERS
        )

        rows, meta = validate_paginated(
            api_client.list_contributions(
                FC_HEADERS, params={"gift_offer_id": ctx["offer"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        row = rows[0]
        assert row["revenue_stream"] == "MAJOR_GIFT"
        assert row["amount_cents"] == 200000
        assert row["funder_id"] == ctx["funder"]["id"]
        assert row["gift_offer_id"] == ctx["offer"]["id"]
        assert row["settlement_status"] == "INITIATED"
        assert row["acknowledgment_status"] == "UNACKNOWLEDGED"
        assert row["quid_pro_quo_cents"] == 0
        assert row["deductible_cents"] == 200000

        assert read_sustainability(ctx["period"]["id"])["recognized_revenue_cents"] == 0


_GRAYLAND_CLIMATE = (
    "Grayland funds climate coverage; the climate desk retains sole editorial "
    "control."
)
_GRAYLAND_HOUSING = (
    "Grayland also funds housing coverage; the housing desk retains sole "
    "editorial control."
)


def _setup_housing_proposal_from_a_climate_disclosed_funder():
    """A restricted proposal on HOUSING awaiting review, filed by a funder that
    only holds a disclosure for its affiliated beat CLIMATE."""
    period = open_fiscal_period()
    climate = register_coverage_area(area_code="CLIMATE", name="Climate and energy")
    housing = register_coverage_area(
        area_code="HOUSING", name="Housing and homelessness"
    )
    pair = setup_disclosed_and_cleared_funder(
        climate["id"],
        legal_name="Grayland Foundation",
        basis="AUDITED",
        audited_advocacy_index=7,
        affiliated=True,
        self_attested_advocacy=True,
        disclosure_text=_GRAYLAND_CLIMATE,
    )
    proposal = draft_proposal(
        pair["funder"]["id"],
        period["id"],
        title="Eviction filings tracker",
        requested_amount_cents=300000,
        restriction_type="PROGRAM_RESTRICTED",
        coverage_area_id=housing["id"],
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-02-28",
        reporting_cadence="NONE",
        award_probability_bps=6000,
    )
    proposal = proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")
    return {
        "period": period,
        "climate": climate,
        "housing": housing,
        "funder": pair["funder"],
        "climate_disclosure": pair["disclosure"],
        "proposal": proposal,
    }


def _clear_in_review(proposal_id, review_note):
    return api_client.grant_proposal_internal_review(
        proposal_id, {"decision": "CLEAR", "review_note": review_note}, ED2_HEADERS
    )


class TestProposalClearanceNeedsTheExactFunderAndBeatPair:
    """A disclosure for another beat of the same funder does not carry over."""

    def test_the_funder_is_cleared_at_forty_eight_and_the_proposal_awaits_review(self):
        """The funder was cleared only because its affiliated beat holds a
        disclosure, and the proposal restricts spending to a different beat.

        PRD: "If the recomputed score has reached the disclosure floor of 40 or
        more, then `affiliated_coverage_area_id` must be non-null and an `ACTIVE`
        firewall disclosure must exist for that exact funder-and-beat pair; a
        missing one is `ERR_DISCLOSURE_REQUIRED`, and a disclosure for some
        *other* beat does not satisfy the requirement."

        Design: Difficulty/cross_entity_state_dependency/ce_proposal_clearance_requires_disclosure_for_exact_funder_area_pair
        """
        ctx = _setup_housing_proposal_from_a_climate_disclosed_funder()

        funder = read_funder(ctx["funder"]["id"])
        assert funder["independence_risk_score"] == 48
        assert funder["status"] == "CLEARED"
        assert ctx["proposal"]["status"] == "INDEPENDENCE_REVIEW"

    def test_clearance_is_refused_while_only_the_climate_disclosure_exists(self):
        """The proposal is untouched by the refusal, so the second attempt later
        differs only in the disclosure set.

        PRD: "and for a restricted proposal an `ACTIVE` firewall disclosure must
        exist for the exact funder-and-beat pair (`ERR_DISCLOSURE_REQUIRED`) with
        none covering that pair sitting in `REATTESTATION_REQUIRED`
        (`ERR_DISCLOSURE_STALE`)."

        Design: Difficulty/cross_entity_state_dependency/ce_proposal_clearance_requires_disclosure_for_exact_funder_area_pair
        """
        ctx = _setup_housing_proposal_from_a_climate_disclosed_funder()

        response = _clear_in_review(
            ctx["proposal"]["id"], "First attempt, relying on the climate disclosure."
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_REQUIRED)

        unchanged = read_proposal(ctx["proposal"]["id"])
        assert unchanged["status"] == "INDEPENDENCE_REVIEW"
        assert unchanged["cleared_by_user_id"] is None

    def test_the_second_disclosure_does_not_supersede_the_first(self):
        """Two beats of one funder hold two live disclosures at once, filed
        against the funder's current version.

        PRD: "Where the filing supersedes an earlier disclosure, that earlier row
        moves to the terminal status `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/ce_proposal_clearance_requires_disclosure_for_exact_funder_area_pair
        """
        ctx = _setup_housing_proposal_from_a_climate_disclosed_funder()

        housing_disclosure = file_disclosure(
            ctx["funder"]["id"],
            ctx["housing"]["id"],
            read_funder(ctx["funder"]["id"])["version"],
            disclosure_text=_GRAYLAND_HOUSING,
        )
        assert housing_disclosure["status"] == "ACTIVE"
        assert housing_disclosure["funder_id"] == ctx["funder"]["id"]
        assert housing_disclosure["coverage_area_id"] == ctx["housing"]["id"]

        climate_disclosure = validate_success(
            api_client.get_firewall_disclosure(
                ctx["climate_disclosure"]["id"], ED2_HEADERS
            )
        )
        assert climate_disclosure["status"] == "ACTIVE"

    def test_the_identical_ruling_clears_once_the_housing_pair_is_disclosed(self):
        """The same director, the same decision, a different disclosure set.

        PRD: "`CLEAR` moves the proposal to `CLEARED` and sets
        `cleared_by_user_id` to the ruling director's `X-User-ID`."

        Design: Difficulty/cross_entity_state_dependency/ce_proposal_clearance_requires_disclosure_for_exact_funder_area_pair
        """
        ctx = _setup_housing_proposal_from_a_climate_disclosed_funder()
        _clear_in_review(ctx["proposal"]["id"], "First attempt.")
        file_disclosure(
            ctx["funder"]["id"],
            ctx["housing"]["id"],
            read_funder(ctx["funder"]["id"])["version"],
            disclosure_text=_GRAYLAND_HOUSING,
        )

        response = _clear_in_review(
            ctx["proposal"]["id"], "Housing disclosure now on file."
        )
        assert response.status_code == 200
        cleared = read_proposal(ctx["proposal"]["id"])
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director_2"]

    def test_each_beat_counts_the_one_funder_disclosed_against_it(self):
        """Both beats report a single disclosed funder, and a merely CLEARED
        proposal has not yet moved the restricted-grant count.

        PRD: "`disclosed_funder_count` counts the distinct funders that currently
        hold an `ACTIVE` firewall disclosure for this beat."

        Design: Difficulty/cross_entity_state_dependency/ce_proposal_clearance_requires_disclosure_for_exact_funder_area_pair
        """
        ctx = _setup_housing_proposal_from_a_climate_disclosed_funder()
        file_disclosure(
            ctx["funder"]["id"],
            ctx["housing"]["id"],
            read_funder(ctx["funder"]["id"])["version"],
            disclosure_text=_GRAYLAND_HOUSING,
        )
        _clear_in_review(ctx["proposal"]["id"], "Housing disclosure now on file.")

        assert read_coverage_area(ctx["housing"]["id"])["disclosed_funder_count"] == 1
        assert read_coverage_area(ctx["climate"]["id"])["disclosed_funder_count"] == 1

        report = read_transparency_report(ctx["housing"]["id"])
        assert ctx["funder"]["id"] in report["disclosed_funder_ids"]
        assert report["restricted_grant_count"] == 0
