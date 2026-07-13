"""The creative review loop, approval version-pinning, and the wrap-up cascade."""

from test_helpers import (
    ApiErrorId,
    assert_deliverable,
    assert_media_budget_conserved,
    open_deliverable,
    place_insertion_order,
    register_placement,
    reserve_insertion_order,
    setup_base,
    setup_media_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDeliverableRevisionLoop:
    """Difficulty: non_linear_state_machine / deliverable_revision_loop_cycles_back_to_submitted."""

    @staticmethod
    def _cycle_twice_then_approve(api, base, deliverable_id):
        validate_success(api.submit_deliverable(deliverable_id, base["kai_headers"]))
        validate_success(api.request_changes_deliverable(
            deliverable_id, {"feedback": "Logo too small in the end frame."},
            base["reviewer_headers"]))
        validate_success(api.submit_deliverable(deliverable_id, base["kai_headers"]))
        validate_success(api.request_changes_deliverable(
            deliverable_id, {"feedback": "Colour grade is still cold."},
            base["reviewer_headers"]))
        validate_success(api.submit_deliverable(deliverable_id, base["kai_headers"]))
        return validate_success(api.approve_deliverable(deliverable_id, base["reviewer_headers"]))

    def test_two_revision_cycles_leave_three_asset_versions_and_two_rounds(self, api):
        """PRD §3.4: "Submitting an asset cut for review moves the deliverable to `SUBMITTED` and
        adds exactly 1 to `current_asset_version`. Submission is legal from two places: from
        `DRAFT`, for the first cut, and from `CHANGES_REQUESTED`, which is the return edge of the
        revision loop."
        PRD §3.4: "Requesting changes bounces the cut back: it moves the deliverable
        `SUBMITTED → CHANGES_REQUESTED`, adds exactly 1 to `revision_round`, and stores the
        supplied `feedback` string in `last_feedback`."

        Design: Difficulty/non_linear_state_machine/deliverable_revision_loop_cycles_back_to_submitted
        """
        base = setup_base()
        deliverable = open_deliverable(base)
        assert deliverable["current_asset_version"] == 0
        assert deliverable["revision_round"] == 0

        final = self._cycle_twice_then_approve(api, base, deliverable["id"])

        assert_deliverable(final)
        assert final["status"] == "APPROVED"
        assert final["current_asset_version"] == 3, "three submits, each adding exactly 1"
        assert final["revision_round"] == 2, "two request-changes rounds, each adding exactly 1"
        assert final["last_feedback"] == "Colour grade is still cold."

    def test_approval_pins_the_asset_version_the_client_signed(self, api):
        """PRD §3.4: "It moves the deliverable `SUBMITTED → APPROVED` — a terminal state — and
        freezes `approved_asset_version` to whatever `current_asset_version` reads at that
        moment, so the agency can always prove which cut the client actually signed."
        PRD §3.4: "First, if the campaign has at least one deliverable and every one of them is
        now `APPROVED`, the campaign advances `IN_FLIGHT → WRAP_UP`."

        Design: Difficulty/non_linear_state_machine/deliverable_revision_loop_cycles_back_to_submitted
        """
        base = setup_base()
        deliverable = open_deliverable(base)

        final = self._cycle_twice_then_approve(api, base, deliverable["id"])

        assert final["approved_asset_version"] == 3
        assert final["approved_asset_version"] == final["current_asset_version"]

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "WRAP_UP"


class TestWrapUpCascade:
    """Difficulty: transitive_cascade /
    deliverable_approval_wraps_campaign_then_locks_plan_then_cancels_reserved_io."""

    @staticmethod
    def _setup(api):
        base = setup_base()
        video = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
        display = register_placement(publisher_name="BannerNet", channel="DISPLAY", min_dark_days=0)
        plan = setup_media_plan(
            base, approve=True, approved_budget_cents=10_000_000,
            allowed_channels=["VIDEO", "DISPLAY"],
        )
        io_placed = reserve_insertion_order(
            base, plan["id"], video["id"], flight_start="2026-06-05",
            flight_end="2026-06-20", gross_cents=4_000_000,
        )
        place_insertion_order(base, io_placed["id"])
        io_reserved = reserve_insertion_order(
            base, plan["id"], display["id"], flight_start="2026-06-05",
            flight_end="2026-06-20", gross_cents=3_000_000,
        )
        deliverable = open_deliverable(base, submit=True)
        base.update({"plan": plan, "io_placed": io_placed, "io_reserved": io_reserved,
                     "deliverable": deliverable})
        return base

    def test_approving_the_last_deliverable_wraps_the_campaign_and_locks_the_plan(self, api):
        """PRD §3.4: "First, if the campaign has at least one deliverable and every one of them
        is now `APPROVED`, the campaign advances `IN_FLIGHT → WRAP_UP`. Second, caused by that,
        every media plan of that campaign sitting in `APPROVED` moves `APPROVED → LOCKED`."
        PRD §3.4: "It moves the deliverable `SUBMITTED → APPROVED` — a terminal state — and
        freezes `approved_asset_version` to whatever `current_asset_version` reads at that
        moment, so the agency can always prove which cut the client actually signed."

        Design: Difficulty/transitive_cascade/deliverable_approval_wraps_campaign_then_locks_plan_then_cancels_reserved_io
        """
        base = self._setup(api)

        approved = validate_success(
            api.approve_deliverable(base["deliverable"]["id"], base["reviewer_headers"])
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_asset_version"] == 1

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "WRAP_UP"

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["status"] == "LOCKED"

    def test_the_lock_cancels_only_reserved_orders_and_releases_their_budget(self, api):
        """PRD §3.4: "Third, caused by *that*, every insertion order on each newly locked plan
        whose status is `RESERVED` moves `RESERVED → CANCELLED`, and its `gross_cents` is
        released back into the plan's `uncommitted_cents`. The cascade is deliberately
        conditional at the third hop: orders already `PLACED` or `DELIVERED` are real
        commitments to a publisher and are left untouched."
        PRD §2.9: "**Media budget.** A media plan's `approved_budget_cents` always equals its
        `uncommitted_cents` plus the sum of `gross_cents` across every insertion order on that
        plan whose status is `RESERVED`, `PLACED` or `DELIVERED`. Cancelled orders hold no
        budget; delivered orders still do."

        Design: Difficulty/transitive_cascade/deliverable_approval_wraps_campaign_then_locks_plan_then_cancels_reserved_io
        """
        base = self._setup(api)
        plan_before = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan_before["uncommitted_cents"] == 3_000_000

        validate_success(api.approve_deliverable(base["deliverable"]["id"], base["reviewer_headers"]))

        io_reserved = validate_success(
            api.get_insertion_order(base["io_reserved"]["id"], base["mia_headers"])
        )
        io_placed = validate_success(
            api.get_insertion_order(base["io_placed"]["id"], base["mia_headers"])
        )
        assert io_reserved["status"] == "CANCELLED"
        assert io_placed["status"] == "PLACED", "a PLACED order is a real publisher commitment"

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 6_000_000
        assert_media_budget_conserved(plan, [io_reserved, io_placed])


def test_approving_a_draft_deliverable_is_rejected(api):
    """PRD §3.4: "Approval is legal only from `SUBMITTED` and only while the owning campaign is
    `IN_FLIGHT` (a campaign in `ON_HOLD` raises `ERR_CAMPAIGN_ON_HOLD`)."
    PRD §3.4: "A new deliverable sits in `DRAFT` with `current_asset_version` 0,
    `revision_round` 0, `approved_asset_version` null and `last_feedback` null."

    Design: Corner/state_machines/deliverable_approve_from_draft_returns_invalid_state
    """
    base = setup_base()
    deliverable = open_deliverable(base)

    resp = api.approve_deliverable(deliverable["id"], base["reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409

    after = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
    assert after["status"] == "IN_FLIGHT"

    listed, _meta = validate_paginated(
        api.list_campaign_deliverables(base["campaign_id"], base["am_headers"])
    )
    stored = next(d for d in listed if d["id"] == deliverable["id"])
    assert stored["status"] == "DRAFT"
    assert stored["current_asset_version"] == 0
    assert stored["approved_asset_version"] is None


def test_a_fourth_request_for_changes_breaches_the_revision_cap(api):
    """PRD §3.4: "The loop is not infinite — the agency contracts for a maximum of three
    revision rounds, so a request for changes on a deliverable whose `revision_round` has
    already reached 3 is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    PRD §3.4: "Requesting changes bounces the cut back: it moves the deliverable
    `SUBMITTED → CHANGES_REQUESTED`, adds exactly 1 to `revision_round`, and stores the supplied
    `feedback` string in `last_feedback`."

    Design: Corner/state_machines/deliverable_fourth_request_changes_hits_revision_limit
    """
    base = setup_base()
    deliverable = open_deliverable(base)

    for round_no in (1, 2, 3):
        validate_success(api.submit_deliverable(deliverable["id"], base["kai_headers"]))
        validate_success(api.request_changes_deliverable(
            deliverable["id"], {"feedback": f"Round {round_no}"}, base["reviewer_headers"]))
    validate_success(api.submit_deliverable(deliverable["id"], base["kai_headers"]))

    resp = api.request_changes_deliverable(
        deliverable["id"], {"feedback": "Round 4"}, base["reviewer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value)
    assert resp.status_code == 422

    listed, _meta = validate_paginated(
        api.list_campaign_deliverables(base["campaign_id"], base["am_headers"])
    )
    stored = next(d for d in listed if d["id"] == deliverable["id"])
    assert stored["revision_round"] == 3
    assert stored["current_asset_version"] == 4
    assert stored["status"] == "SUBMITTED"
    assert stored["last_feedback"] == "Round 3", "the rejected call must not overwrite the feedback"


def test_campaign_deliverables_reverse_lookup_is_scoped_to_that_campaign(api):
    """PRD §3.3: "Campaigns may be listed and filtered by `client_id`, by `sow_id`, and by
    `status`, and reverse-lookup reads return a campaign's deliverables or its vendor costs,
    each of which may itself be narrowed by `status`."
    PRD §2.3: "On every list response the `meta` object carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before pagination is applied) and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/endpoints/campaign_deliverables_subresource_lists_only_that_campaigns_children
    """
    from test_helpers import add_campaign

    base = setup_base()
    second = add_campaign(base, name="Autumn Push")

    first_deliverable = open_deliverable(base)
    second_deliverable = open_deliverable(base, campaign_id=second["id"],
                                          title="Autumn key visual")

    resp = api.list_campaign_deliverables(base["campaign_id"], base["am_headers"])
    data, meta = validate_paginated(resp)

    assert meta["total_count"] == 1
    assert [d["id"] for d in data] == [first_deliverable["id"]]
    assert all(d["id"] != second_deliverable["id"] for d in data)
