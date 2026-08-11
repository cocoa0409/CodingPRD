"""Title search lifecycle, lien discovery cascade, dispute cycle, refresh
cycle, and nested retrieval (PRD §3.3, §2.4, §2.6, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lien,
    assert_title_search,
    complete_title_search,
    create_aircraft,
    create_buyer_seller,
    create_escrow_file,
    get_escrow_file,
    get_lien,
    lien_by_amount,
    liens_for_file,
    make_finding,
    order_title_search,
    set_clock,
    setup_basic_file,
    setup_file_with_lien,
    setup_file_with_search,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestSearchCompletionCascade:
    def test_completion_creates_one_lien_per_finding_in_order(self, api):
        """PRD §3.3: "Completing the search stamps both `effective_at` and
        `completed_at` to the current logical instant, sets `finding_count` to the
        number of findings entries, and creates one `Lien` in `DISCOVERED` per
        findings entry, in array order."

        Design: Difficulty/transitive_cascade/cas_b_search_complete_lien_posture
        """
        ctx = setup_basic_file(with_lender=True)
        search = order_title_search(ctx["file"]["id"])
        findings = [
            make_finding(ctx["lender"]["id"], 100_000, filed_at="2024-01-15"),
            make_finding(ctx["lender"]["id"], 200_000, lien_type="JUDGMENT",
                         filed_at="2024-06-01"),
        ]
        completed = complete_title_search(search["id"], findings)
        assert_title_search(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["finding_count"] == 2

        liens = liens_for_file(ctx["file"]["id"])
        assert len(liens) == 2
        for lien in liens:
            assert_lien(lien)
            assert lien["status"] == "DISCOVERED"
        assert lien_by_amount(ctx["file"]["id"], 100_000)["lien_type"] == "FAA_RECORDED"
        assert lien_by_amount(ctx["file"]["id"], 200_000)["lien_type"] == "JUDGMENT"

    def test_discovered_lien_blocks_cleared_bubble_up(self, api):
        """PRD §3.3: "Completion also advances a `SEARCH_ORDERED` parent to
        `SEARCH_COMPLETE` and recomputes the file's posture — so a search that
        surfaces a `DISCOVERED` lien leaves the file `LIEN_BLOCKED`, while a clean
        search leaves it `READY` and may immediately bubble the file to `CLEARED`
        (and, if funds already cover `buyer_amount_due_cents`, onward to
        `FUNDED`)."
        PRD §2.9: "A file's posture is `LIEN_BLOCKED` when any of its liens is in
        `DISCOVERED`, `DISPUTED`, or `RELEASE_PENDING`."

        Design: Difficulty/transitive_cascade/cas_b_search_complete_lien_posture
        """
        ctx = setup_file_with_lien(amount_cents=100_000, filed_at="2024-01-15")
        escrow_file = ctx["file"]
        assert escrow_file["status"] == "SEARCH_COMPLETE"
        assert escrow_file["posture"] == "LIEN_BLOCKED"


class TestSearchOrderingGate:
    def test_second_active_search_rejected(self, api):
        """PRD §3.3: "At most one search per file may be in `ACTIVE` or in a
        non-stale `COMPLETED` state at a time; an attempt to order while such a
        search exists is rejected with `ERR_SEARCH_ALREADY_ACTIVE`."

        Design: Corner/validations/v_second_active_search_rejected
        """
        ctx = setup_basic_file()
        order_title_search(ctx["file"]["id"])
        res = api.order_title_search(ctx["file"]["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_SEARCH_ALREADY_ACTIVE, expected_status=409)
        searches = validate_success(
            api.list_title_searches(ctx["file"]["id"], OFFICER), 200
        )
        assert len(searches) == 1


class TestLienDisputeCycle:
    def test_dispute_then_resolve_returns_to_discovered(self, api):
        """PRD §2.9: "A file's posture is `LIEN_BLOCKED` when any of its liens is
        in `DISCOVERED`, `DISPUTED`, or `RELEASE_PENDING`."
        PRD §2.9: "Posture is recomputed on every event that could change it:
        lien discovery, dispute, dispute-resolution, release voiding, release
        recording, trust acceptance, and trust expiry."
        PRD §3.3: "Each created lien copies `escrow_file_id` and `aircraft_id`
        from the parent file, references the search as `title_search_id`, and
        carries the lienor details and `original_amount_cents` from the finding."

        The dispute and resolve-dispute actions walk the lien
        DISCOVERED -> DISPUTED -> DISCOVERED without disturbing its amounts.

        Design: Corner/state_machines/s_lien_dispute_cycle
        """
        ctx = setup_file_with_lien(amount_cents=300_000, lien_type="JUDGMENT",
                                   filed_at="2024-11-01")
        lien = ctx["lien"]
        disputed = validate_success(
            api.dispute_lien(lien["id"], {"reason": "amount contested"}, OFFICER), 200
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["original_amount_cents"] == 300_000

        resolved = validate_success(api.resolve_lien_dispute(lien["id"], OFFICER), 200)
        assert resolved["status"] == "DISCOVERED"
        assert resolved["original_amount_cents"] == 300_000


class TestSearchStalenessRefresh:
    def test_stale_sweep_then_refresh_reactivates_same_search(self, api):
        """PRD §2.4: "A `TitleSearch` in `COMPLETED` whose `effective_at` lies
        strictly more than 30 days in the past transitions to `STALE`."
        PRD §3.3: "An `EscrowOfficer` may refresh a `STALE` search back to
        `ACTIVE`; refreshing stamps a new `effective_at` to the current logical
        instant but does not alter `finding_count` and does not disturb any lien
        previously created — prior liens persist untouched."

        Design: Corner/state_machines/s_search_refresh_cycle
        """
        ctx = setup_file_with_search(findings=[])
        search_id = ctx["search"]["id"]

        set_clock("2026-07-02T00:00:00Z")
        searches = validate_success(
            api.list_title_searches(ctx["file"]["id"], OFFICER), 200
        )
        assert len(searches) == 1
        assert searches[0]["status"] == "STALE"

        refreshed = validate_success(api.refresh_title_search(search_id, OFFICER), 200)
        assert refreshed["id"] == search_id
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["effective_at"][:19] == "2026-07-02T00:00:00"
        assert refreshed["finding_count"] == ctx["search"]["finding_count"]


class TestNestedRetrieval:
    def test_searches_scoped_to_owning_file(self, api):
        """PRD §2.6: "The first identifier that fails to resolve, or whose
        resolved child does not in fact belong to the resolved parent, terminates
        the request with `ERR_NOT_FOUND`."
        PRD §2.3: "`total_count` is the size of the full filtered result set
        before pagination; `has_more` is true when `offset + limit < total_count`."

        A search completed under file A never appears in file B's listing.

        Design: Corner/endpoints/ep_get_nested_child_wrong_parent_returns_404
        """
        ctx_a = setup_basic_file(aircraft_overrides={"n_number": "N151NP",
                                                     "serial_number": "S-32"})
        ctx_b = setup_basic_file(clock=None,
                                 aircraft_overrides={"n_number": "N152NP",
                                                     "serial_number": "S-33"})
        search = order_title_search(ctx_a["file"]["id"])
        completed = complete_title_search(search["id"], [])
        assert completed["escrow_file_id"] == ctx_a["file"]["id"]

        data_b, meta_b = validate_paginated(
            api.list_title_searches(ctx_b["file"]["id"], OFFICER)
        )
        assert meta_b["total_count"] == 0
        assert data_b == []

        data_a, meta_a = validate_paginated(
            api.list_title_searches(ctx_a["file"]["id"], OFFICER)
        )
        assert meta_a["total_count"] == 1
        assert data_a[0]["id"] == search["id"]
