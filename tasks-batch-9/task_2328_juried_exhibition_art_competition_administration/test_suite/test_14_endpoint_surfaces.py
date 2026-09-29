"""Endpoint surfaces read as their own contracts: the artist patch window, the
hardship waiver, the score read-back, the award link record, the capacity-bound
promotion, and the sweep's partial effect."""

import pytest

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    JURY_CHAIR_A,
    JURY_CHAIR_A_USER_ID,
    ApiErrorId,
    assert_same_instant,
    api_client,
    create_award_payload,
    create_score_payload,
    fixtures,
    make_artist_headers,
    make_juror_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# An artist registered with every optional attribute omitted, so each declared
# default is observable before the patches move it.
DEFAULTED_ARTIST = {
    "legal_name": "Ana Ruiz",
    "email": "ana.ruiz@example.org",
    "residency_state_code": "CA",
}

# ─── Waiver ───────────────────────────────────────────

WAIVER_CLOCK = "2026-09-20T12:00:00Z"
ANY_AMOUNT_CENTS = 3713
TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]
ONE_WORK = [fixtures.WORK_RIDGE_LINE]

# ─── Scores ───────────────────────────────────────────

TECHNIQUE, ORIGINALITY, RELEVANCE = 7, 8, 9
COMPOSITE_SCORE = 7.85

# ─── Awards ───────────────────────────────────────────

SPONSOR_CONTRIBUTION_CENTS = 1000000
SPONSOR_BUDGET_CENTS = 300000
PURCHASE_PRIZE_CENTS = 250000

# ─── Promotion ────────────────────────────────────────

TOP_CARD = (9, 9, 9)
SECOND_CARD = (7, 8, 9)

# ─── Sweep ────────────────────────────────────────────

RETURNING_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 400000,
    },
]

RETURN_CARRIER = "Crate & Freight"
RETURN_TRACKING_NUMBER = "CF-7781"
DEADLINE_PLUS_THIRTY_ONE_DAYS = "2027-02-12T00:00:00Z"
PICKUP_FEE_AT_DAY_THIRTY_TWO = 48000


# ─── The artist patch window ───────────────────────────

def test_patching_an_artist_touches_only_the_administrative_fields(api):
    """PRD §3.2: "Three further attributes may be set at registration or later:
    `member_status`, either `MEMBER` or `NON_MEMBER` (the default), which decides
    the entry-fee discount; `tax_form_on_file`, false by default, which gates
    every payout; and `payout_method`, either `CHECK` (the default) or `ACH`."

    PRD §3.2: "Administrative updates to an artist record may be made by the
    artist themselves on their own record, or by a `CallManager`; only a
    `CallManager` may supply `payout_hold` to lift a hold the system has imposed."

    PRD §2.4: "**`version` (integer)** — a counter that begins at 1 on creation
    and increments by exactly 1 on every mutation of that record."

    Design: Corner/endpoints/artist_patch_updates_only_the_declared_mutable_fields
    """
    created = validate_success(
        api.create_artist(dict(DEFAULTED_ARTIST), CALL_MANAGER), 201
    )
    assert created["member_status"] == "NON_MEMBER"
    assert created["tax_form_on_file"] is False
    assert created["payout_method"] == "CHECK"
    assert created["payout_hold"] is False
    assert created["unclaimed_forfeit_count"] == 0
    assert created["version"] == 1

    first_patch = validate_success(
        api.patch_artist(
            created["id"],
            {"member_status": "MEMBER", "tax_form_on_file": True},
            CALL_MANAGER,
        )
    )
    assert first_patch["member_status"] == "MEMBER"
    assert first_patch["tax_form_on_file"] is True
    assert first_patch["payout_method"] == "CHECK", "an unnamed key is left alone"
    assert first_patch["version"] == 2

    second_patch = validate_success(
        api.patch_artist(
            created["id"],
            {"payout_method": "ACH", "payout_hold": False},
            CALL_MANAGER,
        )
    )
    assert second_patch["payout_method"] == "ACH"
    assert second_patch["payout_hold"] is False
    assert second_patch["member_status"] == "MEMBER"
    assert second_patch["tax_form_on_file"] is True
    assert second_patch["version"] == 3

    for field, expected in DEFAULTED_ARTIST.items():
        assert second_patch[field] == expected, f"{field} is outside the surface"

    read_by_finance = validate_success(api.get_artist(created["id"], FINANCE_A))
    assert read_by_finance["id"] == created["id"]
    assert read_by_finance["version"] == 3
    assert read_by_finance["unclaimed_forfeit_count"] == 0
    assert read_by_finance["payout_method"] == "ACH"


# ─── The hardship waiver ───────────────────────────────

def test_a_waiver_admits_the_entry_without_any_payment(api):
    """PRD §3.3: "A waiver sets `fee_waived` to true, sets `entry_fee_cents` to 0
    and `fee_paid_cents` to 0, advances the entry to `SUBMITTED`, stamps
    `submitted_at`, and performs the same `DRAFT → SUBMITTED` cascade over the
    entry's works."

    PRD §3.3: "A waiver requires the exhibition to be `OPEN_FOR_ENTRIES`,
    `works_count` to be at least 1, and every work to have at least one `PRIMARY`
    image."

    Design: Corner/endpoints/entry_fee_waiver_zeroes_the_fee_and_submits_the_entry
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, TWO_WORKS
    )
    assert entry["status"] == "DRAFT"

    fixtures.set_clock(WAIVER_CLOCK)
    waived = validate_success(api.waive_entry_fee(entry["id"], CALL_MANAGER))

    assert waived["status"] == "SUBMITTED"
    assert waived["fee_waived"] is True
    assert waived["entry_fee_cents"] == 0
    assert waived["fee_paid_cents"] == 0
    assert_same_instant(
        waived["submitted_at"], WAIVER_CLOCK, "stamped from the logical clock"
    )
    assert waived["works_count"] == len(TWO_WORKS)

    for artwork in artworks:
        assert fixtures.read_artwork(artwork["id"])["status"] == "SUBMITTED"

    late_payment = api_client.pay_entry_fee(
        entry["id"], {"amount_cents": ANY_AMOUNT_CENTS},
        make_artist_headers(artist["id"]),
    )
    validate_error(late_payment, ApiErrorId.ERR_ENTRY_STATE_INVALID.value, 409)


# ─── The score read-back ───────────────────────────────

def test_the_score_read_surfaces_agree_with_the_provisional_mean(api):
    """PRD §3.5: "The raw value is `technique` multiplied by the exhibition's
    `score_weight_technique`, plus `originality` multiplied by
    `score_weight_originality`, plus `relevance` multiplied by
    `score_weight_relevance`."

    PRD §3.5: "The **provisional** figure, `provisional_mean_score`, is the
    arithmetic mean of `composite_score` over *every* score in that ordering,
    rounded half up to two decimal places, and it is refreshed on every submission
    while the round is `OPEN`; it is the live figure a chair watches, and a late
    high score raises it."

    PRD §3.5: "The **certified** figure, `certified_mean_score`, is the arithmetic
    mean of `composite_score` over only the **first `quorum_required` elements**
    of that same ordering, rounded half up to two decimal places, and it is
    written once, at the moment the round completes."

    Design: Corner/endpoints/scores_listing_composite_values_reconcile_with_the_provisional_mean
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    _, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, ONE_WORK
    )
    artwork_id = artworks[0]["id"]

    juror = fixtures.invite_and_confirm_juror(expertise_categories=["PAINTING"])
    jury_round, juror = fixtures.setup_open_round(exhibition["id"], juror=juror)
    juror_headers = make_juror_headers(juror["id"])

    score = validate_success(
        api.submit_score(
            jury_round["id"],
            create_score_payload(artwork_id, TECHNIQUE, ORIGINALITY, RELEVANCE),
            juror_headers,
        ),
        201,
    )
    assert score["expertise_match"] is True, "PAINTING is in the juror's expertise"
    assert score["voided_by_conflict"] is False
    assert score["composite_score"] == pytest.approx(COMPOSITE_SCORE, abs=0.01)
    assert score["juror_id"] == juror["id"], "taken from the headers, never the body"
    assert_same_instant(score["submitted_at"], fixtures.CLOCK_SCORING)

    listed, meta = validate_paginated(
        api.list_scores(
            JURY_CHAIR_A,
            params={"jury_round_id": jury_round["id"], "artwork_id": artwork_id},
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == score["id"]
    assert listed[0]["composite_score"] == pytest.approx(COMPOSITE_SCORE, abs=0.01)

    read_by_juror = validate_success(api.get_score(score["id"], juror_headers))
    assert read_by_juror["composite_score"] == pytest.approx(
        COMPOSITE_SCORE, abs=0.01
    )
    assert read_by_juror["expertise_match"] is True

    artwork = fixtures.read_artwork(artwork_id)
    assert artwork["provisional_mean_score"] == pytest.approx(
        COMPOSITE_SCORE, abs=0.01
    )
    assert artwork["valid_score_count"] == 1
    assert artwork["certified_mean_score"] is None, (
        "certification waits for the round to complete"
    )


# ─── The award link record ─────────────────────────────

def test_proposing_a_purchase_award_links_three_entities_and_commits_nothing(api):
    """PRD §3.8: "An **Award** is proposed by a `JuryChair` naming the
    `exhibition_id`, the `artwork_id` being honoured, a `category` of
    `BEST_IN_SHOW`, `JURORS_CHOICE`, `MEDIUM_MERIT` or `PURCHASE_AWARD`, and a
    cash `prize_cents`."

    PRD §3.8: "The award is created at `status` `PROPOSED` with
    `proposed_by_user_id` set to the acting chair's opaque identity."

    PRD §3.8: "A new sponsor's `purchase_award_committed_cents` — the sum of
    `prize_cents` over that sponsor's `CONFIRMED` awards — starts at 0."

    Design: Corner/endpoints/award_creation_links_exhibition_artwork_and_sponsor
    """
    ctx = fixtures.setup_results_published_show(works=ONE_WORK)
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["artworks"][0]["id"]
    sponsor = fixtures.register_sponsor(
        exhibition_id,
        contribution_cents=SPONSOR_CONTRIBUTION_CENTS,
        purchase_award_budget_cents=SPONSOR_BUDGET_CENTS,
    )

    award = validate_success(
        api.create_award(
            create_award_payload(
                exhibition_id, artwork_id, "PURCHASE_AWARD",
                PURCHASE_PRIZE_CENTS, sponsor_id=sponsor["id"],
            ),
            JURY_CHAIR_A,
        ),
        201,
    )
    assert award["status"] == "PROPOSED"
    assert award["exhibition_id"] == exhibition_id
    assert award["artwork_id"] == artwork_id
    assert award["sponsor_id"] == sponsor["id"]
    assert award["prize_cents"] == PURCHASE_PRIZE_CENTS
    assert award["proposed_by_user_id"] == JURY_CHAIR_A_USER_ID
    assert award["confirmed_by_user_id"] is None

    unchanged_sponsor = fixtures.read_sponsor(sponsor["id"])
    assert unchanged_sponsor["purchase_award_committed_cents"] == 0
    assert unchanged_sponsor["recognition_tier"] == "SILVER"

    exhibition = fixtures.read_exhibition(exhibition_id)
    assert exhibition["award_committed_cents"] == 0, "a proposal commits nothing"
    assert fixtures.read_artwork(artwork_id)["status"] == "ACCEPTED"

    _, sales_meta = validate_paginated(
        api.list_sales(FINANCE_A, params={"artwork_id": artwork_id})
    )
    assert sales_meta["total_count"] == 0, "the sale waits for confirmation"

    listed, meta = validate_paginated(
        api.list_awards(
            FINANCE_A,
            params={"exhibition_id": exhibition_id, "sponsor_id": sponsor["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == award["id"]


# ─── Promotion against live capacity ───────────────────

def test_a_waitlisted_work_cannot_be_promoted_into_a_full_show(api):
    """PRD §3.6: "Promotion requires that `accepted_count` be strictly below
    `acceptance_capacity`, else `ERR_ACCEPTANCE_CAPACITY_REACHED`, and requires
    `expected_exhibition_version` to match."

    PRD §3.6: "Note that promotion is not bound by the per-medium cap — that cap
    governs the automated run only."

    Design: Corner/endpoints/promotion_beyond_acceptance_capacity_rejected
    """
    ctx = fixtures.setup_results_published_show(
        works=[fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT],
        scores=[TOP_CARD, SECOND_CARD],
        exhibition_overrides={"acceptance_capacity": 1, "waitlist_capacity": 1},
    )
    exhibition_id = ctx["exhibition"]["id"]
    result = ctx["acceptance_result"]
    accepted_id = ctx["artworks"][0]["id"]
    waitlisted_id = ctx["artworks"][1]["id"]

    assert result["accepted_artwork_ids"] == [accepted_id]
    assert result["waitlisted_artwork_ids"] == [waitlisted_id]
    assert result["accepted_count"] == 1
    assert result["waitlisted_count"] == 1

    filled = fixtures.read_exhibition(exhibition_id)
    assert filled["accepted_count"] == filled["acceptance_capacity"]

    refused = api.promote_artwork(
        waitlisted_id, {"expected_exhibition_version": filled["version"]},
        JURY_CHAIR_A,
    )
    validate_error(
        refused, ApiErrorId.ERR_ACCEPTANCE_CAPACITY_REACHED.value, 409
    )

    assert fixtures.read_artwork(waitlisted_id)["status"] == "WAITLISTED"
    after = fixtures.read_exhibition(exhibition_id)
    assert after["accepted_count"] == 1
    assert after["waitlisted_count"] == 1
    assert after["version"] == filled["version"], (
        "a refused promotion does not bump the parent"
    )


# ─── The sweep's partial effect ────────────────────────

def test_the_sweep_forfeits_the_pickup_work_and_leaves_the_courier_work_alone(api):
    """PRD §3.10: "The sweep considers the exhibition's works whose `status` is
    `RETURN_PENDING` or `RETURN_SCHEDULED`, whose `return_method` is either null or
    `ARTIST_PICKUP`, and whose `claim_deadline_at` is at or before the clock."

    PRD §3.10: "Works on a `COURIER` return are deliberately excluded, because the
    council controls that transit and cannot hold the artist responsible for it."

    PRD §3.10: "Second, when that count reaches 2, the artist's `payout_hold` is
    set to true."

    Design: Corner/endpoints/unclaimed_sweep_skips_courier_shipments_and_forfeits_only_pickups
    """
    ctx = fixtures.setup_on_view_show(works=RETURNING_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    courier_id, pickup_id = (
        ctx["artworks"][0]["id"], ctx["artworks"][1]["id"]
    )

    fixtures.close_show(exhibition_id)
    fixtures.file_condition_report(courier_id, "DEINSTALL", "A", photo_count=2)
    scheduled = fixtures.arrange_return(
        courier_id, "COURIER",
        carrier=RETURN_CARRIER, tracking_number=RETURN_TRACKING_NUMBER,
    )

    assert scheduled["status"] == "RETURN_SCHEDULED"
    assert scheduled["return_method"] == "COURIER"
    assert scheduled["return_carrier"] == RETURN_CARRIER
    assert scheduled["return_tracking_number"] == RETURN_TRACKING_NUMBER
    unscheduled = fixtures.read_artwork(pickup_id)
    assert unscheduled["status"] == "RETURN_PENDING"
    assert unscheduled["return_method"] is None

    fixtures.set_clock(DEADLINE_PLUS_THIRTY_ONE_DAYS)
    sweep = fixtures.run_unclaimed_sweep(exhibition_id)

    assert sweep["swept_artwork_ids"] == [pickup_id]
    assert sweep["forfeited_artwork_ids"] == [pickup_id]
    assert sweep["storage_fee_total_cents"] == PICKUP_FEE_AT_DAY_THIRTY_TWO

    untouched = fixtures.read_artwork(courier_id)
    assert untouched["storage_fee_cents"] == 0
    assert untouched["status"] == "RETURN_SCHEDULED"

    forfeited = fixtures.read_artwork(pickup_id)
    assert forfeited["status"] == "UNCLAIMED_FORFEIT"
    assert forfeited["storage_fee_cents"] == PICKUP_FEE_AT_DAY_THIRTY_TWO

    artist = fixtures.read_artist(ctx["artist"]["id"])
    assert artist["unclaimed_forfeit_count"] == 1
    assert artist["payout_hold"] is False, "the hold waits for a second forfeit"
