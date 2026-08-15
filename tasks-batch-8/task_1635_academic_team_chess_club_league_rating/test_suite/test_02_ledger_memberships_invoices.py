"""Club ledger, membership dues, and season invoice claims (PRD §2.4, §2.7, §2.8, §3.2, §3.9)."""

from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    build_user_headers,
    club_balance,
    create_active_season,
    create_club,
    create_coach,
    create_ledger_adjustment_payload,
    create_membership,
    create_player,
    create_waived_membership,
    fund_club,
    get_club,
    make_club_coach_headers,
    pay_membership,
    setup_one_club,
    setup_open_tournament_with_section,
    create_entry,
    validate_error,
    validate_paginated,
    validate_success,
    waive_membership,
)

def test_ledger_entry_immutability(api, federation_admin_headers, treasurer_headers, auditor_headers):
    """PRD §2.4: "Two resources are deliberately immutable event rows and carry only `id`
    and `created_at`: a `LedgerEntry` and a `RatingEvent` have no `updated_at` and no
    `version` at all. The single post-creation mutation the server ever performs on a
    ledger row is setting its `reversed_by_id` when a reversal posts; the row's amount
    and type never change."

    Design: Corner/entities/ledger_entry_immutability
    """
    season = create_active_season()
    club = create_club(season["id"])
    entry = fund_club(club["id"], 1200, poster_user_id="treasurer-1", memo="seed")
    assert_ledger_entry(entry)
    created_at = entry["created_at"]

    validate_success(api.reverse_ledger_entry(entry["id"], {}, auditor_headers), 201)

    original = validate_success(api.get_ledger_entry(entry["id"], auditor_headers))
    assert original["amount_cents"] == 1200, "the row's amount never changes"
    assert original["entry_type"] == "ADJUSTMENT", "the row's type never changes"
    assert original["created_at"] == created_at
    assert original.get("reversed_by_id"), "reversed_by_id is set once a reversal posts"
    assert "updated_at" not in original and "version" not in original

def test_reversal_restores_club_balance(api, federation_admin_headers, auditor_headers):
    """PRD §2.8: "The club's `account_balance_cents` is always derived, never stored
    independently: it is the sum of `amount_cents` over every ledger row the club has,
    including reversing rows."
    PRD §2.8: "a reversal is a new `REVERSAL` row whose amount is the negation of the
    original's, linked back to it through `reversal_of_id`".

    Design: Difficulty/compensating_invariant/ledger_reversal_balance_conservation
    """
    season = create_active_season()
    club = create_club(season["id"])
    assert club_balance(club["id"]) == 0

    entry = fund_club(club["id"], 5000)
    assert club_balance(club["id"]) == 5000

    validate_success(api.reverse_ledger_entry(entry["id"], {}, auditor_headers), 201)
    balance = club_balance(club["id"])
    assert balance == 0, f"post + reverse must conserve the pre-post balance, got {balance}"

def test_reversal_row_links_and_original_keeps_amount(api, federation_admin_headers, auditor_headers):
    """PRD §2.8: "Corrections therefore never edit history — a reversal is a new
    `REVERSAL` row whose amount is the negation of the original's, linked back to it
    through `reversal_of_id`, while the original row keeps its amount and has its
    `reversed_by_id` set to the reversal's id."

    Design: Difficulty/compensating_invariant/ledger_reversal_balance_conservation
    """
    season = create_active_season()
    club = create_club(season["id"])
    entry = fund_club(club["id"], 5000)

    reversal = validate_success(
        api.reverse_ledger_entry(entry["id"], {"memo": "erroneous funding"}, auditor_headers), 201
    )
    assert_ledger_entry(reversal)
    assert reversal["entry_type"] == "REVERSAL"
    assert reversal["amount_cents"] == -5000
    assert reversal["reversal_of_id"] == entry["id"]

    original = validate_success(api.get_ledger_entry(entry["id"], federation_admin_headers))
    assert original["amount_cents"] == 5000, "original row keeps its amount"
    assert original["reversed_by_id"] == reversal["id"]

def test_already_reversed_and_reversing_a_reversal_rejected(api, auditor_headers):
    """PRD §3.2: "An entry that has already been reversed — and any `REVERSAL` row
    itself — cannot be reversed; such attempts fail with `ERR_ALREADY_REVERSED`."

    Design: Corner/validations/validation_already_reversed
    """
    season = create_active_season()
    club = create_club(season["id"])
    entry = fund_club(club["id"], 1200, poster_user_id="treasurer-1", memo="seed")
    reversal = validate_success(api.reverse_ledger_entry(entry["id"], {}, auditor_headers), 201)

    res = api.reverse_ledger_entry(entry["id"], {}, auditor_headers)
    validate_error(res, ApiErrorId.ERR_ALREADY_REVERSED)

    # The reversal row was posted by auditor-1; a different auditor must attempt the
    # second reversal so the rung-9 SoD check passes and the rung-11 rule fires.
    res2 = api.reverse_ledger_entry(
        reversal["id"], {}, build_user_headers("auditor-2", "Auditor")
    )
    validate_error(res2, ApiErrorId.ERR_ALREADY_REVERSED)

def test_sod_same_user_reversal_forbidden(api):
    """PRD §3.2: "Segregation of duties is enforced: the auditor's `X-User-ID` must
    differ from the original row's `posted_by_user_id`, or the reversal fails with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/sod_same_user_reversal_forbidden
    """
    season = create_active_season()
    club = create_club(season["id"])
    entry = fund_club(club["id"], 1200, poster_user_id="shared-user-1", memo="seed")

    same_user_as_auditor = build_user_headers("shared-user-1", "Auditor")
    res = api.reverse_ledger_entry(entry["id"], {}, same_user_as_auditor)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

def test_membership_double_pay_rejected(api, federation_admin_headers, treasurer_headers):
    """PRD §3.2: "Payment requires the membership to be `INVOICED` (otherwise
    `ERR_MEMBERSHIP_NOT_PAYABLE`)".
    PRD §3.2: "A successful payment posts a `MEMBERSHIP_DUE` ledger entry debiting
    exactly `fee_cents` with `membership_id` set on the row".

    Design: Corner/state_machines/membership_double_pay_rejected
    """
    ctx = setup_one_club(fund=10000)
    club = ctx["club"]
    player = create_player(club["id"], full_name="P")
    membership = create_membership(player["id"], ctx["season"]["id"])
    assert membership["fee_cents"] == 2500  # default clock is before the dues deadline

    paid = pay_membership(membership["id"], treasurer_headers)
    assert paid["status"] == "PAID"

    res = api.pay_membership(membership["id"], treasurer_headers)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_PAYABLE)
    assert club_balance(club["id"]) == 7500, "exactly one 2500 debit may post"

def test_club_auto_delinquent_on_negative_balance(api, federation_admin_headers):
    """PRD §3.2: "The club's `account_balance_cents` is recomputed as the sum of
    `amount_cents` over all of the club's ledger rows, and then standing is
    re-evaluated: a club in `GOOD_STANDING` whose balance has fallen below zero flips
    to `DELINQUENT`, and a club in `DELINQUENT` whose balance has returned to zero or
    above flips back to `GOOD_STANDING`."

    Design: Corner/state_machines/club_auto_delinquent_on_negative_balance
    """
    season = create_active_season()
    club = create_club(season["id"])
    fund_club(club["id"], 500, memo="seed")
    fund_club(club["id"], -800, memo="fine")

    after = get_club(club["id"])
    assert after["account_balance_cents"] == -300
    assert after["status"] == "DELINQUENT", "auto-transition fires on the same post"

def test_membership_fee_deadline_boundary(api, federation_admin_headers):
    """PRD §3.2: "The invoiced `fee_cents` is computed at creation from the logical
    clock: a membership created at or before the season's `dues_deadline` pays
    `regular_due_cents`, and one created after pays `late_due_cents` — the boundary is
    inclusive, so a creation exactly at the deadline pays the regular amount."
    PRD §2.5: "Every timestamp the system stamps — a membership's `paid_at`, a pairing's
    `confirmed_at`, the base instant from which a bid's `offer_deadline` is computed,
    and every deadline comparison in fee calculations — reads this clock."

    Design: Corner/calculations/membership_fee_deadline_boundary
    """
    season = create_active_season()
    club = create_club(season["id"])
    p1 = create_player(club["id"], full_name="P1")
    p2 = create_player(club["id"], full_name="P2")

    validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, federation_admin_headers)
    )
    m1 = create_membership(p1["id"], season["id"])
    assert m1["fee_cents"] == 2500, "creation exactly at the deadline pays regular"

    validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:01Z"}, federation_admin_headers)
    )
    m2 = create_membership(p2["id"], season["id"])
    assert m2["fee_cents"] == 3750, "one second after the deadline pays late"

def test_invoice_tier_boundary(api, treasurer_headers):
    """PRD §3.9: "Fourth, the `credit_tier_pct` is 0.10 when the subtotal reaches 80,000
    cents, else 0.05 when it reaches 40,000 cents, else 0 — the boundaries are
    inclusive, so a subtotal of exactly 40,000 cents earns the five-percent tier while
    39,999 cents earns nothing."

    Design: Corner/calculations/invoice_tier_boundary
    """
    season = create_active_season(regular_due_cents=20000, late_due_cents=30000)
    club1 = create_club(season["id"], name="C1")
    club2 = create_club(season["id"], name="C2")
    fund_club(club1["id"], 45000)
    fund_club(club2["id"], 45000)
    p1 = create_player(club1["id"], full_name="P1")
    p2 = create_player(club2["id"], full_name="P2")
    pay_membership(create_membership(p1["id"], season["id"])["id"], treasurer_headers)
    pay_membership(create_membership(p2["id"], season["id"])["id"], treasurer_headers)

    # club1: dues 20000 + entry 19999 = subtotal 39999 -> no credit
    t1, s1 = setup_open_tournament_with_section(
        season["id"], tournament_overrides={"name": "TA", "entry_fee_cents": 19999}
    )
    # club2: dues 20000 + entry 20000 = subtotal exactly 40000 -> 5% tier
    t2, s2 = setup_open_tournament_with_section(
        season["id"], tournament_overrides={"name": "TB", "entry_fee_cents": 20000,
                                            "start_date": "2026-10-09", "end_date": "2026-10-10"}
    )
    coach1 = make_club_coach_headers_for_club(api, club1["id"])
    coach2 = make_club_coach_headers_for_club(api, club2["id"])
    create_entry(s1["id"], p1["id"], coach1["X-User-ID"])
    create_entry(s2["id"], p2["id"], coach2["X-User-ID"])

    inv1 = validate_success(
        api.get_season_invoice(club1["id"], treasurer_headers, params={"season_id": season["id"]})
    )
    assert inv1["dues_subtotal_cents"] == 20000
    assert inv1["entries_subtotal_cents"] == 19999
    assert inv1["volume_credit_cents"] == 0, "39999 earns nothing"
    assert inv1["total_cents"] == 39999

    inv2 = validate_success(
        api.get_season_invoice(club2["id"], treasurer_headers, params={"season_id": season["id"]})
    )
    assert inv2["dues_subtotal_cents"] == 20000
    assert inv2["entries_subtotal_cents"] == 20000
    assert inv2["volume_credit_cents"] == 2000, "exactly 40000 earns the 5% tier"
    assert inv2["total_cents"] == 38000

def make_club_coach_headers_for_club(api, club_id):
    """Create a coach row for the club and return entity-backed headers for them."""
    coach = create_coach(club_id)
    return make_club_coach_headers(coach["id"])

def _setup_invoice_eval_order(api, treasurer_headers):
    """Club with two PAID memberships (20000 each), one WAIVED, and three early-bird
    entries at 932 each."""
    season = create_active_season(regular_due_cents=20000, late_due_cents=30000)
    club = create_club(season["id"], name="Alpha")
    fund_club(club["id"], 45000)
    players = [create_player(club["id"], full_name=f"P{i}") for i in range(1, 4)]
    pay_membership(create_membership(players[0]["id"], season["id"])["id"], treasurer_headers)
    pay_membership(create_membership(players[1]["id"], season["id"])["id"], treasurer_headers)
    waive_membership(create_membership(players[2]["id"], season["id"])["id"])
    tournament, section = setup_open_tournament_with_section(
        season["id"],
        tournament_overrides={
            "name": "Open", "entry_fee_cents": 1035,
            "early_bird_deadline": "2026-09-15T00:00:00Z", "early_bird_discount_pct": 0.10,
        },
    )
    coach_headers = make_club_coach_headers_for_club(api, club["id"])
    for player in players:
        create_entry(section["id"], player["id"], coach_headers["X-User-ID"])
    return season, club

def test_invoice_subtotals_and_pre_credit_tier(api, treasurer_headers):
    """PRD §3.9: "First, `dues_subtotal_cents` sums `fee_cents` over the memberships of
    the club's players for the season that are `PAID` — memberships that are `WAIVED`,
    `INVOICED`, or `REFUNDED` contribute zero. Second, `entries_subtotal_cents` sums,
    over all tournament entries of the club's players in the season's tournaments, each
    entry's `fee_cents` minus its `refund_cents`. Third, the subtotal is the sum of
    those two."

    Design: Difficulty/combinatorial_formula/season_invoice_credit_evaluation_order
    """
    season, club = _setup_invoice_eval_order(api, treasurer_headers)
    inv = validate_success(
        api.get_season_invoice(club["id"], treasurer_headers, params={"season_id": season["id"]})
    )
    assert inv["dues_subtotal_cents"] == 40000, "two PAID memberships; WAIVED contributes 0"
    assert inv["entries_subtotal_cents"] == 2796, "3 x 932 per-entry rounded fees"
    assert inv["credit_tier_pct"] == 0.05, "tier keys on the pre-credit subtotal 42796"

def test_invoice_credit_and_total_after_tier(api, treasurer_headers):
    """PRD §3.9: "Fifth, `volume_credit_cents` is the round-half-up of the subtotal
    multiplied by the tier; rounding happens only at this step. Sixth, `total_cents` is
    the subtotal minus the credit."
    PRD §2.6: "Wherever a calculation requires rounding — entry fees, half-fee refunds,
    volume credits, and every rating update — the rule is round half up, defined as the
    floor of the value plus one half, applied identically to positive and negative
    values."

    Design: Difficulty/combinatorial_formula/season_invoice_credit_evaluation_order
    """
    season, club = _setup_invoice_eval_order(api, treasurer_headers)
    inv = validate_success(
        api.get_season_invoice(club["id"], treasurer_headers, params={"season_id": season["id"]})
    )
    # subtotal 42796 -> 5% -> round_half_up(2139.8) = 2140 -> total 40656
    assert inv["volume_credit_cents"] == 2140
    assert inv["total_cents"] == 40656

def test_exact_balance_charge_succeeds(api, treasurer_headers):
    """PRD §3.2: "if subtracting the fee would drive the club's `account_balance_cents`
    below zero, the payment is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."
    A charge leaving the balance at exactly zero does not drive it below zero.

    Design: Difficulty/boundary_precision_check/exact_balance_charge_succeeds
    """
    season = create_active_season()
    club = create_club(season["id"], name="Alpha")
    fund_club(club["id"], 2500)
    player = create_player(club["id"], full_name="PA")
    membership = create_membership(player["id"], season["id"])

    paid = validate_success(api.pay_membership(membership["id"], treasurer_headers))
    assert paid["status"] == "PAID"
    assert club_balance(club["id"]) == 0, "charge leaving exactly zero succeeds (>= 0)"

def test_one_cent_short_charge_rejected(api, treasurer_headers):
    """PRD §3.2: "if subtracting the fee would drive the club's `account_balance_cents`
    below zero, the payment is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/exact_balance_charge_succeeds
    """
    season = create_active_season()
    club = create_club(season["id"], name="Beta")
    fund_club(club["id"], 2499)
    player = create_player(club["id"], full_name="PB")
    membership = create_membership(player["id"], season["id"])

    res = api.pay_membership(membership["id"], treasurer_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
    after = validate_success(api.get_membership(membership["id"], treasurer_headers))
    assert after["status"] == "INVOICED", "rejected payment changes nothing"

def test_validation_duplicate_membership(api, federation_admin_headers):
    """PRD §3.2: "Creating a membership takes a `player_id` and a `season_id`; only one
    membership may exist per player-and-season pair, and a duplicate attempt is
    rejected with `ERR_DUPLICATE_MEMBERSHIP`."

    Design: Corner/validations/validation_duplicate_membership
    """
    ctx = setup_one_club()
    player = create_player(ctx["club"]["id"], full_name="P")
    create_membership(player["id"], ctx["season"]["id"])
    res = api.create_membership(
        {"player_id": player["id"], "season_id": ctx["season"]["id"]}, federation_admin_headers
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

def test_refund_unpaid_membership_rejected(api, treasurer_headers):
    """PRD §3.2: "Refunding a membership that is not `PAID` fails with
    `ERR_MEMBERSHIP_NOT_REFUNDABLE`."

    Design: Corner/errors/refund_unpaid_membership_rejected
    """
    ctx = setup_one_club()
    player = create_player(ctx["club"]["id"], full_name="P")
    membership = create_membership(player["id"], ctx["season"]["id"])
    res = api.refund_membership(membership["id"], treasurer_headers)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_REFUNDABLE)

def test_occ_ledger_stale_club_version(api, federation_admin_headers, treasurer_headers):
    """PRD §2.7: "Posting a manual adjustment to a club's ledger requires
    `expected_club_version` matching the club's current `version`. A manual adjustment
    is always legitimate product-wise, so the OCC check is the sole guard: a post whose
    `expected_club_version` no longer matches because a prior ledger post advanced the
    club's version is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_ledger_stale_club_version
    """
    season = create_active_season()
    club = create_club(season["id"])
    stale_version = club["version"]
    fund_club(club["id"], 500, memo="first")  # advances the club version

    res = api.post_ledger_entry(
        club["id"],
        create_ledger_adjustment_payload(300, stale_version, memo="second-stale"),
        treasurer_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    after = get_club(club["id"])
    assert after["account_balance_cents"] == 500, "the rejected write changed nothing"
    assert after["version"] != stale_version

def test_rbac_treasurer_cannot_reverse_ledger(api, treasurer_headers):
    """PRD §2.1: "Access to each operation is further restricted by role; an attempt to
    perform an action outside of the caller's designated role is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 assigns POST /api/ledger-entries/{ledgerEntryId}/reverse to "Auditor" only.

    Design: Corner/rbac/rbac_treasurer_cannot_reverse_ledger
    """
    season = create_active_season()
    club = create_club(season["id"])
    entry = fund_club(club["id"], 1200, memo="seed")
    res = api.reverse_ledger_entry(entry["id"], {}, treasurer_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

def test_rbac_auditor_cannot_post_adjustment(api, auditor_headers):
    """PRD §2.1: "Access to each operation is further restricted by role; an attempt to
    perform an action outside of the caller's designated role is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 assigns POST /api/clubs/{clubId}/ledger-entries to "Treasurer" only.

    Design: Corner/rbac/rbac_auditor_cannot_post_adjustment
    """
    season = create_active_season()
    club = create_club(season["id"])
    res = api.post_ledger_entry(
        club["id"], create_ledger_adjustment_payload(100, club["version"], memo="x"), auditor_headers
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
