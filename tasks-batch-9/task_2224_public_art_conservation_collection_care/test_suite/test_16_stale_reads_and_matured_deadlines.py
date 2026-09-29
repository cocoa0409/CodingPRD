"""Stale parent reads and matured deadlines.

Two writes in this system prove they have seen the current state of a parent
record before they may act: drafting a treatment proposal against an `Artwork`
and reserving money against a `FundingPool` (PRD §2.11).  Separately, a matured
consultation deadline and a matured notice waiting period are realised only when
the cycle checkpoint is invoked (PRD §3.9) — moving the logical clock past a
deadline changes nothing on its own.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_no_version_change
from test_helpers.factories import (
    funding_allocation_payload,
    treatment_proposal_payload,
)
from test_helpers.fixtures import (
    create_conservator,
    create_pool,
    current_artwork_version,
    current_pool_version,
    open_consultation,
    read_artwork,
    read_consultation,
    read_notice,
    read_pool,
    reserve_allocation,
    send_notice,
    set_clock,
    setup_assessment_finalized,
    setup_register,
    setup_scheduled_visit,
)


# --------------------------------------------------------------------------
# The artwork version token on a proposal draft (PRD §2.11)
# --------------------------------------------------------------------------
def test_drafting_a_proposal_on_an_artwork_version_read_before_a_relocation_is_rejected(
    api,
):
    """PRD §2.11: "If that value does not equal the artwork's current `version`, the draft is rejected with `ERR_STALE_ARTWORK_VERSION` (HTTP 412)."
    PRD §2.5: "`version` (integer): a counter that increments by exactly one on every mutation of the record."
    PRD §3.7: "Setting `to_storage` to true withdraws a work from public view, moving custody `ON_VIEW → IN_STORAGE`; supplying a `to_site_id` reinstalls a stored work, moving custody `IN_STORAGE → ON_VIEW`."

    Design: Corner/complexity_layers/a_stale_artwork_version_is_rejected_when_drafting_a_proposal
    """
    # The artist has a waiver on file, so withdrawing the work into storage
    # needs no moral-rights notice and the registrar's move goes through.
    register = setup_register(api, artist={"moral_rights_waiver_on_file": True})
    artwork = register["artwork"]
    conservator = create_conservator(api)
    assessment = setup_assessment_finalized(api, artwork["id"])

    observed_version = current_artwork_version(api, artwork["id"])

    relocated = validate_success(
        api.relocate_artwork(
            artwork["id"],
            {"to_storage": True, "relocation_note": "into storage for the winter"},
            TEST_USERS["registrar_headers"],
        )
    )
    assert relocated["custody_status"] == "IN_STORAGE"
    assert relocated["version"] == observed_version + 1, (
        "a relocation performed by the registrar is a mutation of the artwork, "
        f"so its version must move from {observed_version}"
    )

    # Correct in every other respect, but carrying the version observed before
    # that relocation.
    stale_draft = api.create_treatment_proposal(
        treatment_proposal_payload(
            artwork["id"],
            conservator["id"],
            assessment["id"],
            observed_version,
        ),
        TEST_USERS["chief_conservator_headers"],
    )
    validate_error(stale_draft, ApiErrorId.ERR_STALE_ARTWORK_VERSION.value)

    after_rejection = read_artwork(api, artwork["id"])
    assert_no_version_change(relocated, after_rejection, "artwork")
    assert after_rejection["custody_status"] == "IN_STORAGE"

    proposals, meta = validate_paginated(
        api.list_treatment_proposals(
            TEST_USERS["chief_conservator_headers"],
            params={"artwork_id": artwork["id"]},
        )
    )
    assert meta["total_count"] == 0, "a refused draft must create nothing"
    assert proposals == []


def test_drafting_a_proposal_after_re_reading_the_moved_artwork_version_succeeds(api):
    """PRD §2.11: "Drafting a treatment proposal must carry `expected_artwork_version`, a non-optional field holding the `version` of the target `Artwork` as the client last observed it."
    PRD §3.4: "A successful draft is created in `DRAFT` with an empty `line_items`, an `estimate_total_cents` of zero, `withdraw_reason` of `NONE` and `pinned_estimate_total_cents` null; it also increments the referenced artwork's own `version`, which is precisely why a subsequent draft against the same work needs a re-read."

    Design: Corner/complexity_layers/a_stale_artwork_version_is_rejected_when_drafting_a_proposal
    """
    register = setup_register(api, artist={"moral_rights_waiver_on_file": True})
    artwork = register["artwork"]
    conservator = create_conservator(api)
    assessment = setup_assessment_finalized(api, artwork["id"])

    validate_success(
        api.relocate_artwork(
            artwork["id"],
            {"to_storage": True},
            TEST_USERS["registrar_headers"],
        )
    )

    fresh_version = current_artwork_version(api, artwork["id"])
    proposal = validate_success(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                artwork["id"],
                conservator["id"],
                assessment["id"],
                fresh_version,
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        201,
    )
    assert proposal["status"] == "DRAFT"
    assert proposal["line_items"] == []
    assert proposal["estimate_total_cents"] == 0
    assert proposal["withdraw_reason"] == "NONE"
    assert proposal.get("pinned_estimate_total_cents") is None

    # The accepted draft itself moves the work again, which is why the next
    # draft would need its own re-read.
    assert read_artwork(api, artwork["id"])["version"] == fresh_version + 1

    proposals, meta = validate_paginated(
        api.list_treatment_proposals(
            TEST_USERS["chief_conservator_headers"],
            params={"artwork_id": artwork["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in proposals] == [proposal["id"]]


# --------------------------------------------------------------------------
# The pool version token on a reservation (PRD §2.11)
# --------------------------------------------------------------------------
def test_reserving_funds_a_second_time_from_one_pool_read_is_rejected_as_stale(api):
    """PRD §2.11: "If that value does not equal the pool's current `version`, the reservation is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)."
    PRD §3.10: "A successful reservation is created in `RESERVED` with `release_reason` of `NONE` and `released_at` null, lowers the pool's `available_cents` by `amount_cents`, and increments the pool's own `version` — which is what makes a second reservation from a stale read fail."

    Design: Corner/complexity_layers/a_stale_pool_version_is_rejected_when_reserving_funds
    """
    state = setup_scheduled_visit(api)
    visit_id = state["visit"]["id"]
    pool = create_pool(api)

    observed_version = current_pool_version(api, pool["id"])
    first = reserve_allocation(
        api,
        pool["id"],
        purpose="MAINTENANCE",
        amount_cents=100_000,
        visit_id=visit_id,
    )
    assert first["status"] == "RESERVED"
    assert first["release_reason"] == "NONE"
    assert first.get("released_at") is None

    pool_after_first = read_pool(api, pool["id"])
    assert pool_after_first["version"] == observed_version + 1
    assert pool_after_first["available_cents"] == pool["available_cents"] - 100_000

    # The token is the version observed before that first reservation.
    stale_reservation = api.create_funding_allocation(
        funding_allocation_payload(
            pool["id"],
            observed_version,
            purpose="MAINTENANCE",
            amount_cents=100_000,
            visit_id=visit_id,
        ),
        TEST_USERS["finance_headers"],
    )
    validate_error(stale_reservation, ApiErrorId.ERR_STALE_POOL_VERSION.value)

    pool_after_rejection = read_pool(api, pool["id"])
    assert_no_version_change(pool_after_first, pool_after_rejection, "funding pool")
    assert (
        pool_after_rejection["available_cents"] == pool_after_first["available_cents"]
    ), "a refused reservation may not be charged against the balance"

    allocations, meta = validate_paginated(
        api.list_funding_allocations(
            TEST_USERS["finance_headers"], params={"pool_id": pool["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in allocations] == [first["id"]]


def test_reserving_funds_again_after_re_reading_the_pool_version_succeeds(api):
    """PRD §2.11: "Reserving a funding allocation must carry `expected_pool_version`, a non-optional field holding the `version` of the target `FundingPool` as the client last observed it."
    PRD §3.10: "A successful reservation is created in `RESERVED` with `release_reason` of `NONE` and `released_at` null, lowers the pool's `available_cents` by `amount_cents`, and increments the pool's own `version` — which is what makes a second reservation from a stale read fail."

    Design: Corner/complexity_layers/a_stale_pool_version_is_rejected_when_reserving_funds
    """
    state = setup_scheduled_visit(api)
    visit_id = state["visit"]["id"]
    pool = create_pool(api)
    opening_available = pool["available_cents"]

    reserve_allocation(
        api,
        pool["id"],
        purpose="MAINTENANCE",
        amount_cents=100_000,
        visit_id=visit_id,
    )

    second = validate_success(
        api.create_funding_allocation(
            funding_allocation_payload(
                pool["id"],
                current_pool_version(api, pool["id"]),
                purpose="MAINTENANCE",
                amount_cents=100_000,
                visit_id=visit_id,
            ),
            TEST_USERS["finance_headers"],
        ),
        201,
    )
    assert second["status"] == "RESERVED"

    pool_now = read_pool(api, pool["id"])
    assert pool_now["available_cents"] == opening_available - 200_000, (
        "two accepted reservations of 100000 each must both be visible"
    )
    assert pool_now["version"] == pool["version"] + 2

    _, meta = validate_paginated(
        api.list_funding_allocations(
            TEST_USERS["finance_headers"], params={"pool_id": pool["id"]}
        )
    )
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------
# Matured deadlines and the cycle checkpoint (PRD §3.9)
# --------------------------------------------------------------------------
def test_the_cycle_checkpoint_run_before_either_deadline_matures_moves_nothing(api):
    """PRD §3.9: "It moves every `PENDING` artist consultation whose `due_at` is at or before the logical clock to `LAPSED`."
    PRD §3.9: "It moves every `SENT` moral-rights notice whose `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`."
    PRD §3.9: "The checkpoint reports what it did, echoing the `cycle_year` it ran for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed` and `artworks_returned_to_monitored`."

    Design: Corner/complexity_layers/matured_deadlines_only_fire_when_the_cycle_actually_runs
    """
    register = setup_register(api)
    artwork = register["artwork"]
    artist = register["artist"]

    consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="RELOCATION"
    )
    notice = send_notice(api, artwork["id"], artist["id"], action_type="RELOCATION")
    assert consultation["status"] == "PENDING"
    assert notice["status"] == "SENT"
    # Default clock plus the artist's default 30-day response window and
    # 90-day notice wait.
    assert consultation["due_at"].startswith("2026-08-31T00:00:00")
    assert notice["earliest_action_at"].startswith("2026-10-30T00:00:00")

    set_clock(api, "2026-08-30T23:59:59Z")
    report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert report["cycle_year"] == 2026
    assert report["consultations_lapsed"] == 0, "one second before due_at nothing lapses"
    assert report["notices_elapsed"] == 0
    assert report["artworks_rescored"] == 0
    assert report["artworks_returned_to_monitored"] == 0

    consultation_now = read_consultation(api, consultation["id"])
    assert consultation_now["status"] == "PENDING"
    assert_no_version_change(consultation, consultation_now, "consultation")

    notice_now = read_notice(api, notice["id"])
    assert notice_now["status"] == "SENT"
    assert_no_version_change(notice, notice_now, "moral-rights notice")


def test_a_consultation_at_its_due_instant_lapses_only_once_the_checkpoint_runs(api):
    """PRD §3.6: "The cycle checkpoint moves every `PENDING` consultation whose `due_at` is at or before the logical clock to `LAPSED`, and a lapsed consultation clears the approval gate exactly as a concurrence does."
    PRD §3.6: "A `CONCUR` moves the row `PENDING → CONCURRED` and an `OBJECT` moves it `PENDING → OBJECTED`; both stamp `responded_at` from the logical clock, and both require the logical clock to be strictly before `due_at`."
    PRD §3.9: "The checkpoint reports what it did, echoing the `cycle_year` it ran for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed` and `artworks_returned_to_monitored`."

    Design: Corner/complexity_layers/matured_deadlines_only_fire_when_the_cycle_actually_runs
    """
    register = setup_register(api)
    artwork = register["artwork"]
    artist = register["artist"]

    consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="RELOCATION"
    )
    notice = send_notice(api, artwork["id"], artist["id"], action_type="RELOCATION")

    # The clock now equals due_at, but no checkpoint has run.
    set_clock(api, "2026-08-31T00:00:00Z")
    still_pending = read_consultation(api, consultation["id"])
    assert still_pending["status"] == "PENDING", (
        "maturity is realised by the checkpoint, not by the clock move"
    )
    assert_no_version_change(consultation, still_pending, "consultation")

    report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert report["consultations_lapsed"] == 1, "due_at at the clock exactly matures"
    assert report["notices_elapsed"] == 0, "the notice wait runs until 2026-10-30"

    lapsed = read_consultation(api, consultation["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed.get("responded_at") is None, "silence stamps no response"
    assert lapsed["version"] == still_pending["version"] + 1

    assert read_notice(api, notice["id"])["status"] == "SENT"


def test_a_matured_notice_elapses_at_the_checkpoint_and_still_counts_as_open(api):
    """PRD §3.6: "Alternatively the cycle checkpoint moves a `SENT` notice whose `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`."
    PRD §3.6: "Creation stamps `sent_at` from the logical clock, derives `earliest_action_at` by advancing that instant by the artist's `notice_wait_days`, sets `status` to `SENT`, leaves `acknowledged_at` and `consumed_by_ref` null, and raises the work's `open_notice_count` by one — that counter being maintained as the number of the work's notices sitting in `SENT`, `ACKNOWLEDGED` or `WAIT_ELAPSED`."

    Design: Corner/complexity_layers/matured_deadlines_only_fire_when_the_cycle_actually_runs
    """
    register = setup_register(api)
    artwork = register["artwork"]
    artist = register["artist"]

    open_consultation(api, artwork["id"], artist["id"], subject="RELOCATION")
    notice = send_notice(api, artwork["id"], artist["id"], action_type="RELOCATION")
    assert read_artwork(api, artwork["id"])["open_notice_count"] == 1

    # Clear the consultation deadline first so this checkpoint speaks only of
    # the notice.
    set_clock(api, "2026-08-31T00:00:00Z")
    validate_success(api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"]))

    set_clock(api, "2026-10-30T00:00:00Z")
    unmatured = read_notice(api, notice["id"])
    assert unmatured["status"] == "SENT", (
        "the waiting period has run out but the checkpoint has not fired yet"
    )

    report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert report["notices_elapsed"] == 1
    assert report["consultations_lapsed"] == 0, "that row lapsed at the earlier run"

    elapsed = read_notice(api, notice["id"])
    assert elapsed["status"] == "WAIT_ELAPSED"
    assert elapsed.get("acknowledged_at") is None, "no artist acknowledgement was made"
    assert elapsed["version"] == unmatured["version"] + 1

    assert read_artwork(api, artwork["id"])["open_notice_count"] == 1, (
        "WAIT_ELAPSED still counts as an open notice"
    )


def test_a_repeated_cycle_checkpoint_leaves_already_matured_rows_alone(api):
    """PRD §3.9: "It moves every `PENDING` artist consultation whose `due_at` is at or before the logical clock to `LAPSED`."
    PRD §3.9: "It moves every `SENT` moral-rights notice whose `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`."
    PRD §2.6: "Every stamped instant, every deadline and every year comparison is derived from a single logical clock, which reads exactly `2026-08-01T00:00:00Z` until it is moved."

    Design: Corner/complexity_layers/matured_deadlines_only_fire_when_the_cycle_actually_runs
    """
    register = setup_register(api)
    artwork = register["artwork"]
    artist = register["artist"]

    consultation = open_consultation(
        api, artwork["id"], artist["id"], subject="RELOCATION"
    )
    notice = send_notice(api, artwork["id"], artist["id"], action_type="RELOCATION")

    set_clock(api, "2026-10-30T00:00:00Z")
    first_report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert first_report["consultations_lapsed"] == 1
    assert first_report["notices_elapsed"] == 1

    consultation_after = read_consultation(api, consultation["id"])
    notice_after = read_notice(api, notice["id"])
    assert consultation_after["status"] == "LAPSED"
    assert notice_after["status"] == "WAIT_ELAPSED"

    second_report = validate_success(
        api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"])
    )
    assert second_report["consultations_lapsed"] == 0, (
        "a LAPSED row is outside the checkpoint's input set"
    )
    assert second_report["notices_elapsed"] == 0, (
        "a WAIT_ELAPSED row is outside the checkpoint's input set"
    )
    assert second_report["artworks_rescored"] == 0
    assert second_report["artworks_returned_to_monitored"] == 0

    assert_no_version_change(
        consultation_after, read_consultation(api, consultation["id"]), "consultation"
    )
    assert_no_version_change(
        notice_after, read_notice(api, notice["id"]), "moral-rights notice"
    )
    assert read_artwork(api, artwork["id"])["open_notice_count"] == 1
