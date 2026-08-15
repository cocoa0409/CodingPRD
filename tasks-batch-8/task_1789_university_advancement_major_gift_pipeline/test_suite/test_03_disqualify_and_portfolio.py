"""Disqualification cascade, portfolio capacity boundary, assign/release
counter conservation, fundraiser deactivation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_prospect, create_fundraiser, rate_prospect, assign_prospect,
    move_prospect, get_prospect, get_fundraiser, create_proposal_for,
    create_submitted_proposal, setup_rated_assigned_prospect,
    create_assignment_payload, create_prospect_payload,
)

RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]


class TestDisqualifyCascade:
    def test_disqualify_cascades_assignment_release_and_proposal_rejection(self, api):
        """PRD §3.2: "Disqualification sets `research_status` to `DISQUALIFIED`
        while leaving `moves_stage` unchanged, and then cascades: every `ACTIVE`
        assignment of the prospect is released with `released_reason`
        `DISQUALIFIED`, decrementing each owning fundraiser's
        `current_prospect_count`; and every proposal of the prospect in `DRAFT`,
        `UNDER_REVIEW`, `NEGOTIATING`, or `RETURNED` status is rejected with
        `decision_rationale` set to `PROSPECT_DISQUALIFIED`, with the owning
        fundraisers' `current_open_ask_cents` recomputed."

        Design: Corner/state_machines/disqualify_cascades_assignment_release_and_proposal_rejection
        """
        f, p, asg = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_submitted_proposal(p["id"], f["id"], 5000000)
        assert prop["status"] == "UNDER_REVIEW"

        resp = api.disqualify_prospect(p["id"], DIR)
        data = validate_success(resp)
        assert data["research_status"] == "DISQUALIFIED"

        rows, _meta = validate_paginated(api.list_prospect_assignments(p["id"], DIR))
        assert rows[0]["status"] == "RELEASED"
        assert rows[0]["released_reason"] == "DISQUALIFIED"

        prop_after = validate_success(api.get_proposal(prop["id"], VP))
        assert prop_after["status"] == "REJECTED"
        assert prop_after["decision_rationale"] == "PROSPECT_DISQUALIFIED"

        f_after = get_fundraiser(f["id"])
        assert f_after["current_prospect_count"] == 0
        assert f_after["current_open_ask_cents"] == 0


class TestPortfolioCapacityBoundary:
    """Queue A: boundary_precision_check / portfolio_capacity_boundary_at_exact_max."""

    def test_assignment_at_max_count_succeeds_and_next_rejected(self, api):
        """PRD §3.1: "Creation is refused when the fundraiser is not `ACTIVE`
        (`ERR_FUNDRAISER_INACTIVE`), when the prospect already has an `ACTIVE`
        assignment to any fundraiser (`ERR_PROSPECT_ALREADY_ASSIGNED`), when the
        fundraiser's `current_prospect_count` has already reached
        `max_prospect_count` — that is, when the count is greater than or equal
        to the maximum (`ERR_PORTFOLIO_CAPACITY_EXCEEDED`) — and when adding the
        prospect's open proposals would push `current_open_ask_cents` above
        `max_open_ask_cents` (`ERR_OPEN_ASK_LOAD_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/portfolio_capacity_boundary_at_exact_max
        """
        f = create_fundraiser(max_prospect_count=2)
        p1 = create_prospect(full_name="P One", contact_email="p1@x.com")
        p2 = create_prospect(full_name="P Two", contact_email="p2@x.com")
        p3 = create_prospect(full_name="P Three", contact_email="p3@x.com")

        assign_prospect(f["id"], p1["id"])
        f_mid = get_fundraiser(f["id"])
        assert f_mid["current_prospect_count"] == 1

        assign_prospect(f["id"], p2["id"])
        f_end = get_fundraiser(f["id"])
        assert f_end["current_prospect_count"] == 2  # exactly the max is allowed

        resp = api.create_assignment(
            f["id"], create_assignment_payload(p3["id"], f_end["version"]), DIR,
        )
        validate_error(resp, ApiErrorId.ERR_PORTFOLIO_CAPACITY_EXCEEDED)
        assert get_fundraiser(f["id"])["current_prospect_count"] == 2

    def test_released_assignment_frees_capacity_slot(self, api):
        """PRD §3.1: "Creation is refused when the fundraiser is not `ACTIVE`
        (`ERR_FUNDRAISER_INACTIVE`), when the prospect already has an `ACTIVE`
        assignment to any fundraiser (`ERR_PROSPECT_ALREADY_ASSIGNED`), when the
        fundraiser's `current_prospect_count` has already reached
        `max_prospect_count` — that is, when the count is greater than or equal
        to the maximum (`ERR_PORTFOLIO_CAPACITY_EXCEEDED`) — and when adding the
        prospect's open proposals would push `current_open_ask_cents` above
        `max_open_ask_cents` (`ERR_OPEN_ASK_LOAD_EXCEEDED`)."
        PRD §3.1: "Release decrements `current_prospect_count`, recomputes
        `current_open_ask_cents` to subtract the released prospect's open
        proposals, and advances the fundraiser's `version`."

        Design: Difficulty/boundary_precision_check/portfolio_capacity_boundary_at_exact_max
        """
        f = create_fundraiser(max_prospect_count=1)
        p1 = create_prospect(full_name="P One", contact_email="p1@x.com")
        p2 = create_prospect(full_name="P Two", contact_email="p2@x.com")
        asg = assign_prospect(f["id"], p1["id"])

        # At capacity: a second assignment is refused.
        f_mid = get_fundraiser(f["id"])
        resp = api.create_assignment(
            f["id"], create_assignment_payload(p2["id"], f_mid["version"]), DIR,
        )
        validate_error(resp, ApiErrorId.ERR_PORTFOLIO_CAPACITY_EXCEEDED)

        # Release frees the slot; the same prospect can then be assigned.
        resp = api.release_assignment(asg["id"], {"released_reason": "REBALANCING"}, DIR)
        validate_success(resp)
        f_after = get_fundraiser(f["id"])
        assert f_after["current_prospect_count"] == 0
        assign_prospect(f["id"], p2["id"])
        assert get_fundraiser(f["id"])["current_prospect_count"] == 1


class TestAssignReleaseConservation:
    """Queue A: compensating_invariant / assign_release_restores_portfolio_counters."""

    def test_assign_then_release_restores_counters(self, api):
        """PRD §3.1: "A successful assignment is created `ACTIVE`, increments the
        fundraiser's `current_prospect_count` by one, folds the prospect's open
        proposals into `current_open_ask_cents`, and advances the fundraiser's
        `version` by 1."
        PRD §3.1: "Release decrements `current_prospect_count`, recomputes
        `current_open_ask_cents` to subtract the released prospect's open
        proposals, and advances the fundraiser's `version`."

        Design: Difficulty/compensating_invariant/assign_release_restores_portfolio_counters
        """
        f = create_fundraiser(max_prospect_count=5)
        assert f["current_prospect_count"] == 0
        assert f["current_open_ask_cents"] == 0

        p = create_prospect()
        rate_prospect(p["id"])
        asg = assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")
        prop = create_submitted_proposal(p["id"], f["id"], 5000000)

        f_mid = get_fundraiser(f["id"])
        assert f_mid["current_prospect_count"] == 1
        assert f_mid["current_open_ask_cents"] == 5000000  # UNDER_REVIEW counts

        resp = api.release_assignment(asg["id"], {"released_reason": "REBALANCING"}, DIR)
        released = validate_success(resp)
        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "REBALANCING"

        f_end = get_fundraiser(f["id"])
        assert f_end["current_prospect_count"] == 0
        assert f_end["current_open_ask_cents"] == 0

        # Release does not cascade into the proposal.
        prop_after = validate_success(api.get_proposal(prop["id"], VP))
        assert prop_after["status"] == "UNDER_REVIEW"

    def test_open_ask_load_during_assignment_window(self, api):
        """PRD §2.9: "A fundraiser's `current_open_ask_cents` is the sum of
        `ask_amount_cents` over proposals in the open proposal states whose
        prospect currently has an `ACTIVE` assignment to that fundraiser, and
        `current_prospect_count` is the number of `ACTIVE` assignments the
        fundraiser holds."

        Design: Difficulty/compensating_invariant/assign_release_restores_portfolio_counters
        """
        f = create_fundraiser(max_prospect_count=5)
        p = create_prospect()
        rate_prospect(p["id"])
        asg = assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")
        create_submitted_proposal(p["id"], f["id"], 5000000)

        f_mid = get_fundraiser(f["id"])
        assert f_mid["current_prospect_count"] == 1
        assert f_mid["current_open_ask_cents"] == 5000000

        api.release_assignment(asg["id"], {"released_reason": "GRADUATED"}, DIR)
        f_end = get_fundraiser(f["id"])
        assert f_end["current_prospect_count"] == 0
        assert f_end["current_open_ask_cents"] == 0


class TestFundraiserDeactivation:
    def test_fundraiser_deactivate_blocked_then_allowed(self, api):
        """PRD §3.1: "Deactivation requires `status` `ACTIVE` (otherwise
        `ERR_INVALID_MOVES_TRANSITION`) and a `current_prospect_count` of exactly
        zero; attempting it while any assignment is still `ACTIVE` fails with
        `ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS`."
        PRD §3.1: "Creation is refused when the fundraiser is not `ACTIVE`
        (`ERR_FUNDRAISER_INACTIVE`)."

        Design: Corner/state_machines/fundraiser_deactivate_blocked_then_allowed
        """
        f = create_fundraiser()
        p1 = create_prospect(full_name="P One", contact_email="p1@x.com")
        p2 = create_prospect(full_name="P Two", contact_email="p2@x.com")
        asg = assign_prospect(f["id"], p1["id"])

        resp = api.deactivate_fundraiser(f["id"], VP)
        validate_error(resp, ApiErrorId.ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS)

        api.release_assignment(asg["id"], {"released_reason": "REBALANCING"}, DIR)
        resp = api.deactivate_fundraiser(f["id"], VP)
        data = validate_success(resp)
        assert data["status"] == "INACTIVE"

        f_late = get_fundraiser(f["id"])
        resp = api.create_assignment(
            f["id"], create_assignment_payload(p2["id"], f_late["version"]), DIR,
        )
        validate_error(resp, ApiErrorId.ERR_FUNDRAISER_INACTIVE)
