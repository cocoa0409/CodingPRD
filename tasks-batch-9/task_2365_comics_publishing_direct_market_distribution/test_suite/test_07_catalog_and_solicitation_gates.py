"""Catalog and solicitation gates: submission window, lock dependency and slot capacity."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_issue_dimensions,
    assert_version_advanced,
    assert_version_unchanged,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


def _listing_without_a_standard_cover() -> dict:
    """An issue in `SCRIPTING` carrying only a ratio cover, drafted into a catalog."""
    state = fixtures.setup_issue_in_scripting()
    fixtures.add_covers(state["issue"]["id"], (fixtures.DEFAULT_COVER_SPECS[1],))
    catalog = fixtures.open_catalog()
    solicitation = fixtures.draft_solicitation(catalog["id"], state["issue"]["id"])
    state.update({"catalog": catalog, "solicitation": solicitation})
    return state


def _submitted_listing_in_an_open_catalog() -> dict:
    """An issue in `SCRIPTING` with a `STANDARD` cover, listed and submitted."""
    state = fixtures.setup_issue_in_scripting()
    fixtures.add_covers(state["issue"]["id"], (fixtures.DEFAULT_COVER_SPECS[0],))
    catalog = fixtures.open_catalog()
    solicitation = fixtures.draft_solicitation(catalog["id"], state["issue"]["id"])
    solicitation = fixtures.submit_solicitation(solicitation["id"])
    state.update({"catalog": catalog, "solicitation": solicitation})
    return state


# ─── Solicitation submission: window before missing cover ─────────────


def test_lapsed_submission_window_is_reported_before_the_missing_standard_cover():
    """A listing that is both late and coverless reports the window refusal.

    PRD: "Beyond path resolution, several checks may be applicable to the same request, and the order in which they are evaluated is part of the contract, because it decides which error a client sees."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_14_beats_referential_priority_25_on_solicitation_submit
    """
    state = _listing_without_a_standard_cover()
    drafted = state["solicitation"]

    # Five days past the 2026-08-20 deadline; the catalog is still OPEN because
    # locking is a manual act, so the transition itself remains legal.
    fixtures.set_clock("2026-08-25T00:00:00Z")
    response = api_client.submit_solicitation(
        drafted["id"], TEST_USERS["managing_editor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_SOLICITATION_WINDOW_CLOSED.value)

    unchanged = fixtures.read_solicitation(drafted["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert_version_unchanged(drafted, unchanged)
    assert fixtures.read_catalog(state["catalog"]["id"])["status"] == "OPEN"


def test_a_coverless_listing_inside_the_window_is_refused_for_its_standard_cover():
    """With the deadline satisfied, the missing `STANDARD` cover is what refuses the submit.

    PRD: "And the issue must already carry at least one `STANDARD` variant cover, since that is the cover the catalog prints and the one retailers order against; without it the attempt is refused with `ERR_STANDARD_COVER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_14_beats_referential_priority_25_on_solicitation_submit
    """
    state = _listing_without_a_standard_cover()
    drafted = state["solicitation"]

    # The deadline instant itself still counts as inside the window.
    fixtures.set_clock("2026-08-20T00:00:00Z")
    response = api_client.submit_solicitation(
        drafted["id"], TEST_USERS["managing_editor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_COVER_REQUIRED.value)

    unchanged = fixtures.read_solicitation(drafted["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert_version_unchanged(drafted, unchanged)


def test_a_listing_submitted_on_the_deadline_instant_with_a_standard_cover_succeeds():
    """The deadline instant is inside the window, so the cured listing submits.

    PRD: "The logical clock must be at or before the catalog's `submission_deadline`, or the attempt is refused with `ERR_SOLICITATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_14_beats_referential_priority_25_on_solicitation_submit
    """
    state = _listing_without_a_standard_cover()
    drafted = state["solicitation"]
    fixtures.add_covers(state["issue"]["id"], (fixtures.DEFAULT_COVER_SPECS[0],))

    fixtures.set_clock("2026-08-20T00:00:00Z")
    submitted = validate_success(
        api_client.submit_solicitation(
            drafted["id"], TEST_USERS["managing_editor_headers"]
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-08-20T00:00:00Z")
    assert_version_advanced(drafted, submitted)


# ─── Acceptance depends on the parent catalog being locked ─────────────


def test_accepting_a_listing_into_an_open_catalog_is_refused():
    """The child listing cannot take a slot while its parent catalog is still `OPEN`.

    PRD: "The catalog must be `LOCKED`, or the attempt is refused with `ERR_CATALOG_NOT_LOCKED`; and its `accepted_slot_count` must still be strictly below `max_slots`, with a full catalog refusing further acceptances via `ERR_CATALOG_SLOTS_EXHAUSTED`."

    Design: Difficulty/cross_entity_state_dependency/solicitation_accept_requires_the_catalog_entity_to_be_locked
    """
    state = _submitted_listing_in_an_open_catalog()
    submitted = state["solicitation"]

    response = api_client.accept_solicitation(
        submitted["id"], TEST_USERS["sales_director_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CATALOG_NOT_LOCKED.value)

    unchanged = fixtures.read_solicitation(submitted["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_version_unchanged(submitted, unchanged)
    catalog = fixtures.read_catalog(state["catalog"]["id"])
    assert catalog["status"] == "OPEN"
    assert catalog["accepted_slot_count"] == 0


def test_the_lock_that_unblocks_acceptance_is_itself_released_by_the_deadline():
    """Only once the clock passes the deadline can the catalog lock and the slot be taken.

    PRD: "The lock moves the catalog `OPEN → LOCKED` and requires the logical clock to be strictly after the `submission_deadline`; an early attempt is refused with `ERR_CATALOG_DEADLINE_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/solicitation_accept_requires_the_catalog_entity_to_be_locked
    """
    state = _submitted_listing_in_an_open_catalog()
    catalog_id = state["catalog"]["id"]

    early = api_client.lock_catalog(catalog_id, TEST_USERS["sales_director_headers"])
    validate_error(early, ApiErrorId.ERR_CATALOG_DEADLINE_NOT_PASSED.value)
    assert fixtures.read_catalog(catalog_id)["status"] == "OPEN"

    fixtures.set_clock("2026-08-21T00:00:00Z")
    locked = validate_success(
        api_client.lock_catalog(catalog_id, TEST_USERS["sales_director_headers"])
    )
    assert locked["status"] == "LOCKED"

    accepted = validate_success(
        api_client.accept_solicitation(
            state["solicitation"]["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 1


def test_publication_waits_on_the_acceptance_that_the_lock_made_possible():
    """A locked catalog with no accepted listing cannot be published; one acceptance frees it.

    PRD: "A `SalesDirector` moves the catalog `LOCKED → PUBLISHED`, which stamps `published_at` from the logical clock and requires at least one accepted listing — a catalog whose `accepted_slot_count` is 0 is refused with `ERR_NO_ACCEPTED_SOLICITATIONS`."

    Design: Difficulty/cross_entity_state_dependency/solicitation_accept_requires_the_catalog_entity_to_be_locked
    """
    state = _submitted_listing_in_an_open_catalog()
    catalog_id = state["catalog"]["id"]

    fixtures.set_clock("2026-08-21T00:00:00Z")
    fixtures.lock_catalog(catalog_id)

    empty = api_client.publish_catalog(catalog_id, TEST_USERS["sales_director_headers"])
    validate_error(empty, ApiErrorId.ERR_NO_ACCEPTED_SOLICITATIONS.value)
    assert fixtures.read_catalog(catalog_id)["status"] == "LOCKED"

    fixtures.accept_solicitation(state["solicitation"]["id"])
    published = validate_success(
        api_client.publish_catalog(catalog_id, TEST_USERS["sales_director_headers"])
    )
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-21T00:00:00Z")


def test_acceptance_alone_leaves_the_issue_unsolicited_until_publication():
    """Taking a slot does not announce the book; the publication fan-out does.

    PRD: "Publication then fans out across that catalog's accepted listings: every issue they reference moves its commercial dimension `UNSOLICITED → SOLICITED`, and each such issue's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/solicitation_accept_requires_the_catalog_entity_to_be_locked
    """
    state = _submitted_listing_in_an_open_catalog()
    issue_id = state["issue"]["id"]

    fixtures.set_clock("2026-08-21T00:00:00Z")
    fixtures.lock_catalog(state["catalog"]["id"])
    fixtures.accept_solicitation(state["solicitation"]["id"])

    after_accept = fixtures.read_issue(issue_id)
    assert_issue_dimensions(
        after_accept, production_status="SCRIPTING", commercial_status="UNSOLICITED"
    )

    fixtures.publish_catalog(state["catalog"]["id"])
    after_publish = fixtures.read_issue(issue_id)
    assert_issue_dimensions(after_publish, commercial_status="SOLICITED")
    assert_version_advanced(after_accept, after_publish)


# ─── Withdrawal restores the catalog's slot capacity ───────────────────


def test_a_full_catalog_refuses_the_waiting_listing_its_slot():
    """With both slots taken the third acceptance is refused and nothing moves.

    PRD: "The catalog must be `LOCKED`, or the attempt is refused with `ERR_CATALOG_NOT_LOCKED`; and its `accepted_slot_count` must still be strictly below `max_slots`, with a full catalog refusing further acceptances via `ERR_CATALOG_SLOTS_EXHAUSTED`."

    Design: Difficulty/compensating_invariant/solicitation_withdrawal_restores_the_catalog_slot_capacity
    """
    state = fixtures.setup_catalog_with_slots()
    catalog = state["catalog"]
    waiting = state["solicitations"][2]

    assert catalog["accepted_slot_count"] == 2
    assert catalog["accepted_slot_count"] == catalog["max_slots"]

    response = api_client.accept_solicitation(
        waiting["id"], TEST_USERS["sales_director_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CATALOG_SLOTS_EXHAUSTED.value)

    unchanged = fixtures.read_solicitation(waiting["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_version_unchanged(waiting, unchanged)
    assert fixtures.read_catalog(catalog["id"])["accepted_slot_count"] == 2


def test_withdrawing_an_accepted_listing_hands_its_slot_to_the_waiting_one():
    """The freed slot is recomputed back to 1 and the waiting listing then fits.

    PRD: "A `SalesDirector` may withdraw a listing that is `SUBMITTED` or `ACCEPTED`, capturing the supplied `reason` into `withdrawn_reason` and refreshing `accepted_slot_count`, provided the catalog has not yet been published; a withdrawal attempt against a published catalog is refused as `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/solicitation_withdrawal_restores_the_catalog_slot_capacity
    """
    state = fixtures.setup_catalog_with_slots()
    catalog_id = state["catalog"]["id"]
    holder = state["solicitations"][1]
    waiting = state["solicitations"][2]

    withdrawn = validate_success(
        api_client.withdraw_solicitation(
            holder["id"],
            factories.withdraw_payload(reason="cover art not cleared"),
            TEST_USERS["sales_director_headers"],
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "cover art not cleared"
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 1

    accepted = validate_success(
        api_client.accept_solicitation(
            waiting["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 2


def test_a_second_withdrawal_of_the_same_listing_earns_no_second_slot_credit():
    """`WITHDRAWN` is terminal, so the slot cannot be released twice.

    PRD: "`WITHDRAWN` is terminal for a listing."

    Design: Difficulty/compensating_invariant/solicitation_withdrawal_restores_the_catalog_slot_capacity
    """
    state = fixtures.setup_catalog_with_slots()
    catalog_id = state["catalog"]["id"]
    holder = state["solicitations"][1]

    withdrawn = fixtures.withdraw_solicitation(holder["id"])
    fixtures.accept_solicitation(state["solicitations"][2]["id"])
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 2

    response = api_client.withdraw_solicitation(
        holder["id"], factories.withdraw_payload(), TEST_USERS["sales_director_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert_version_unchanged(withdrawn, fixtures.read_solicitation(holder["id"]))
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 2


def test_withdrawing_a_listing_that_never_held_a_slot_leaves_the_count_alone():
    """A `SUBMITTED` row occupied no slot, so its withdrawal credits nothing back.

    PRD: "A catalog's `accepted_slot_count` equals the count of that catalog's solicitations whose status is `ACCEPTED`; `DRAFT`, `SUBMITTED` and `WITHDRAWN` rows never occupy a slot."

    Design: Difficulty/compensating_invariant/solicitation_withdrawal_restores_the_catalog_slot_capacity
    """
    state = fixtures.setup_catalog_with_slots()
    catalog_id = state["catalog"]["id"]
    never_accepted = state["solicitations"][2]

    withdrawn = validate_success(
        api_client.withdraw_solicitation(
            never_accepted["id"],
            factories.withdraw_payload(),
            TEST_USERS["sales_director_headers"],
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert fixtures.read_catalog(catalog_id)["accepted_slot_count"] == 2


def test_the_freed_slot_announces_a_different_issue_at_publication():
    """Publication solicits the two issues holding slots and skips the withdrawn one.

    PRD: "Publication then fans out across that catalog's accepted listings: every issue they reference moves its commercial dimension `UNSOLICITED → SOLICITED`, and each such issue's `version` increments."

    Design: Difficulty/compensating_invariant/solicitation_withdrawal_restores_the_catalog_slot_capacity
    """
    state = fixtures.setup_catalog_with_slots()
    catalog_id = state["catalog"]["id"]
    first, second, third = state["issues"]

    fixtures.withdraw_solicitation(state["solicitations"][1]["id"])
    fixtures.accept_solicitation(state["solicitations"][2]["id"])
    published = fixtures.publish_catalog(catalog_id)
    assert published["status"] == "PUBLISHED"

    assert_issue_dimensions(
        fixtures.read_issue(first["id"]), commercial_status="SOLICITED"
    )
    assert_issue_dimensions(
        fixtures.read_issue(third["id"]), commercial_status="SOLICITED"
    )
    assert_issue_dimensions(
        fixtures.read_issue(second["id"]), commercial_status="UNSOLICITED"
    )
