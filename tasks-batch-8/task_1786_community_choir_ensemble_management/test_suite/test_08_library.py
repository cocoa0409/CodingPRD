"""Music library: checkout gates, overdue fines, conservation of copies."""
from test_helpers import (
    ApiErrorId,
    assert_copy_conservation,
    assert_music_score,
    checkout_score,
    create_checkout_payload,
    create_open_season_with_section,
    create_score,
    enroll_member,
    run_checkpoint,
    set_clock,
    validate_error,
    validate_success,
)


class TestCheckoutLifecycle:
    def test_checkout_double_return_rejected(self, api, librarian_headers):
        """PRD §3.5: "Returns and losses close the loop, and both require the
        checkout to be `CHECKED_OUT` or `OVERDUE` — anything else is rejected
        with `ERR_CHECKOUT_NOT_ACTIVE`."

        Design: Corner/state_machines/checkout_double_return_rejected
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        score = create_score(copy_count=1)
        checkout = checkout_score(score["id"], member["id"])

        returned = validate_success(
            api.return_checkout(checkout["id"], librarian_headers))
        assert returned["status"] == "RETURNED"

        resp = api.return_checkout(checkout["id"], librarian_headers)
        validate_error(resp, ApiErrorId.ERR_CHECKOUT_NOT_ACTIVE)

        data = validate_success(api.get_checkout(checkout["id"],
                                                 librarian_headers))
        assert data["status"] == "RETURNED", "terminal state unchanged"

    def test_retired_score_blocks_checkout(self, api, librarian_headers):
        """PRD §3.5: "The score must be `ACTIVE`, else `ERR_SCORE_RETIRED`" and
        "the Librarian may retire a score: `ACTIVE` to `RETIRED` is terminal,
        blocks new checkouts, and leaves existing checkouts untouched."

        Design: Corner/validations/retired_score_blocks_checkout
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        score = create_score(copy_count=1)
        retired = validate_success(api.retire_score(score["id"],
                                                    librarian_headers))
        assert retired["status"] == "RETIRED"

        resp = api.create_checkout(
            create_checkout_payload(score["id"], member["id"]),
            librarian_headers)
        validate_error(resp, ApiErrorId.ERR_SCORE_RETIRED)

    def test_no_copies_available_rejected(self, api, librarian_headers):
        """PRD §3.5: "at least one copy must be available, else
        `ERR_NO_COPIES_AVAILABLE`" and "thereafter `copies_available` is
        computed as `copy_count` minus open checkouts minus `copies_lost`."

        Design: Corner/validations/no_copies_available_rejected
        """
        season, section = create_open_season_with_section(target_max=4)
        m1 = enroll_member(season["id"], section["id"], "A One", "a1@x.org",
                           "2026-08-02T10:00:00Z")
        m2 = enroll_member(season["id"], section["id"], "A Two", "a2@x.org",
                           "2026-08-02T11:00:00Z")
        score = create_score(copy_count=1)
        checkout_score(score["id"], m1["id"])

        score_data = validate_success(api.get_score(score["id"],
                                                    librarian_headers))
        assert score_data["copies_available"] == 0

        resp = api.create_checkout(
            create_checkout_payload(score["id"], m2["id"]),
            librarian_headers)
        validate_error(resp, ApiErrorId.ERR_NO_COPIES_AVAILABLE)


class TestLibraryHold:
    def test_library_hold_blocks_new_checkout(self, api, librarian_headers):
        """PRD §3.5: "and the member must not already carry an `OVERDUE`
        checkout — the library hold — else `ERR_LIBRARY_HOLD`."
        PRD §3.5: "At each checkpoint, a checkout whose `due_date` has passed
        moves from `CHECKED_OUT` to `OVERDUE`, and the fine clock starts:
        `fine_cents` is set to a weekly fine of 200 cents on the transition"

        Design: Corner/validations/library_hold_blocks_new_checkout
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        score = create_score(copy_count=2)
        checkout = checkout_score(score["id"], member["id"],
                                  "2026-08-10T00:00:00Z")

        set_clock("2026-08-20T00:00:00Z")
        run_checkpoint(season["id"])

        checkout_data = validate_success(
            api.get_checkout(checkout["id"], librarian_headers))
        assert checkout_data["status"] == "OVERDUE"
        assert checkout_data["fine_cents"] == 200

        resp = api.create_checkout(
            create_checkout_payload(score["id"], member["id"],
                                    "2026-09-01T00:00:00Z"),
            librarian_headers)
        validate_error(resp, ApiErrorId.ERR_LIBRARY_HOLD)

    def test_library_hold_release_after_return(self, api, librarian_headers,
                                               director_headers):
        """PRD §3.5: "Returning sets `returned_at`, moves the checkout to
        `RETURNED`, recomputes the score's `copies_available`, posts any
        accrued `fine_cents` to the member's `ledger_balance_cents` when the
        return came from `OVERDUE`, and re-evaluates the member's library
        hold."

        Design: Corner/cross_cutting_layers/library_hold_release_after_return
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        score = create_score(copy_count=2)
        checkout = checkout_score(score["id"], member["id"],
                                  "2026-08-10T00:00:00Z")
        set_clock("2026-08-20T00:00:00Z")
        run_checkpoint(season["id"])

        returned = validate_success(
            api.return_checkout(checkout["id"], librarian_headers))
        assert returned["status"] == "RETURNED"
        assert returned["fine_cents"] == 200

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["ledger_balance_cents"] == 200, \
            "the accrued fine posts to the member ledger on return"

        # Hold cleared: a fresh checkout succeeds.
        second = validate_success(api.create_checkout(
            create_checkout_payload(score["id"], member["id"],
                                    "2026-09-01T00:00:00Z"),
            librarian_headers), 201)
        assert second["status"] == "CHECKED_OUT"


class TestCopyConservation:
    def test_library_copy_conservation(self, api, librarian_headers,
                                       director_headers):
        """PRD §3.5: "thereafter `copies_available` is computed as
        `copy_count` minus open checkouts minus `copies_lost`."
        PRD §3.5: "Marking a copy lost moves the checkout to `LOST`, sets
        `charge_cents` to the score's `replacement_cost_cents` and posts it to
        `ledger_balance_cents` — together with the accrued fine when the
        checkout was `OVERDUE` — and increments `copies_lost`."

        Design: Difficulty/compensating_invariant/library_copy_conservation
        """
        season, section = create_open_season_with_section(target_max=4)
        m1 = enroll_member(season["id"], section["id"], "A One", "a1@x.org",
                           "2026-08-02T10:00:00Z")
        m2 = enroll_member(season["id"], section["id"], "A Two", "a2@x.org",
                           "2026-08-02T11:00:00Z")
        score = create_score(copy_count=3, replacement_cost_cents=7000)
        assert_music_score(score)
        assert score["copies_available"] == 3

        co1 = checkout_score(score["id"], m1["id"])
        co2 = checkout_score(score["id"], m2["id"])
        mid = validate_success(api.get_score(score["id"], librarian_headers))
        assert mid["copies_available"] == 1
        assert_copy_conservation(mid, open_checkouts=2)

        # Return compensates: the copy goes back on the shelf.
        returned = validate_success(
            api.return_checkout(co1["id"], librarian_headers))
        assert returned["status"] == "RETURNED"
        after_return = validate_success(
            api.get_score(score["id"], librarian_headers))
        assert after_return["copies_available"] == 2
        assert_copy_conservation(after_return, open_checkouts=1)

        # Mark-lost moves the copy into copies_lost and charges the member.
        lost = validate_success(
            api.mark_checkout_lost(co2["id"], librarian_headers))
        assert lost["status"] == "LOST"
        assert lost["charge_cents"] == 7000

        final = validate_success(api.get_score(score["id"], librarian_headers))
        assert final["copies_available"] == 2
        assert final["copies_lost"] == 1
        assert_copy_conservation(final, open_checkouts=0)

        member_data = validate_success(api.get_member(m2["id"],
                                                      director_headers))
        assert member_data["ledger_balance_cents"] == 7000

    def test_overdue_checkout_marked_lost_charges_fine_and_replacement(
            self, api, librarian_headers, director_headers):
        """PRD §3.5: "Marking a copy lost moves the checkout to `LOST`, sets
        `charge_cents` to the score's `replacement_cost_cents` and posts it to
        `ledger_balance_cents` — together with the accrued fine when the
        checkout was `OVERDUE` — and increments `copies_lost`."

        Design: Difficulty/compensating_invariant/library_copy_conservation
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        score = create_score(copy_count=2, replacement_cost_cents=7000)
        checkout = checkout_score(score["id"], member["id"],
                                  "2026-08-10T00:00:00Z")
        set_clock("2026-08-20T00:00:00Z")
        run_checkpoint(season["id"])  # -> OVERDUE, fine 200

        lost = validate_success(
            api.mark_checkout_lost(checkout["id"], librarian_headers))
        assert lost["status"] == "LOST"
        assert lost["fine_cents"] == 200
        assert lost["charge_cents"] == 7000

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["ledger_balance_cents"] == 7200, \
            "replacement cost plus the accrued overdue fine"

        score_data = validate_success(api.get_score(score["id"],
                                                    librarian_headers))
        assert score_data["copies_lost"] == 1
        assert score_data["copies_available"] == 1
        assert_copy_conservation(score_data, open_checkouts=0)
