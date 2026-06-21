"""Volunteer credit accrual with running cap at the family's deposit.

Covers: dual_variant_calc (running-cap accrual on the Family domain).

NOTE — combinatorial_formula / volunteer_refund_round_then_sum_mode_b is SKIPPED:
the PRD (§3.8) computes the season-close "refund" as a value but never states it
is written back into any observable Family field (`volunteer_credit_cents` holds
the *accrued* credit, capped at the deposit; no `refund_cents` field is exposed).
A faithful PRD-only implementer could leave `volunteer_credit_cents` at the
accrued total. The mode_b assertion (refund == 2991 read from credit) is therefore
not uniquely derivable from PRD prose, so the instance is left as a PRD gap.
"""
from test_helpers import (
    validate_success,
    make_league_admin_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


def _season_with_family(deposit_cents):
    """League in SEASON with two teams, a field, a referee and one family."""
    s = fx.setup_league_in_season(num_teams=2, num_fields=1, draft_snake=True,
                                  max_games_per_day=10)
    family = fx.create_family(s["league"]["id"], guardian_email="fam@x.com",
                              guardian_name="Fam",
                              volunteer_deposit_cents=deposit_cents)
    s["family"] = family
    return s


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / volunteer_credit_running_cap_vs_refund_fee_diverge...  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_volunteer_credit_running_cap_at_deposit(api):
    """PRD §3.8: "Fulfilling a commitment moves it from `PLEDGED` to the terminal
    `FULFILLED` status and credits the family: the family's
    `volunteer_credit_cents` becomes the smaller of (its current credit plus this
    commitment's `credit_cents`) and the family's posted `volunteer_deposit_cents`."
    PRD §3.8: "The cap is applied on each fulfillment as the running credit
    accrues, not as a single cap at season end, so a family's credit never
    exceeds its deposit."

    Two fulfilled commitments of 3000 on a deposit of 5000: first accrues to 3000,
    second is capped at the deposit 5000 (not 6000).

    Design: Difficulty/dual_variant_calc/volunteer_credit_running_cap_vs_refund_fee_diverge_on_family_domain
    """
    s = _season_with_family(5000)
    fam_id = s["family"]["id"]

    g1 = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    c1 = fx.pledge_commitment(g1["id"], fam_id, "SCOREKEEPER", 3000)
    a1 = fx.propose_assignment(g1["id"], s["referee"]["id"])
    fx.confirm_assignment(a1["id"], s["referee"]["user_id"])
    fx.start_game(g1["id"])
    fx.finalize_game(g1["id"], 3, 1)

    g2 = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][1]["id"], s["teams"][0]["id"], s["field"]["id"],
        "2026-05-02T17:00:00Z", "2026-05-02T19:00:00Z")
    c2 = fx.pledge_commitment(g2["id"], fam_id, "CONCESSIONS", 3000)
    a2 = fx.propose_assignment(g2["id"], s["referee"]["id"])
    fx.confirm_assignment(a2["id"], s["referee"]["user_id"])
    fx.start_game(g2["id"])
    fx.finalize_game(g2["id"], 4, 2)

    fx.fulfill_commitment(c1["id"])
    fam_after_1 = validate_success(api.get_family(fam_id, ADMIN))
    assert fam_after_1["volunteer_credit_cents"] == 3000, \
        fam_after_1["volunteer_credit_cents"]

    fx.fulfill_commitment(c2["id"])
    fam_after_2 = validate_success(api.get_family(fam_id, ADMIN))
    assert fam_after_2["volunteer_credit_cents"] == 5000, \
        fam_after_2["volunteer_credit_cents"]


def test_volunteer_credit_read_back_after_single_fulfill(api):
    """PRD §3.8: "the family's `volunteer_credit_cents` becomes the smaller of
    (its current credit plus this commitment's `credit_cents`) and the family's
    posted `volunteer_deposit_cents`."

    A single fulfilled commitment of 3000 on deposit 5000 leaves credit at 3000
    and is observable on a subsequent GET of the family.

    Design: Difficulty/dual_variant_calc/volunteer_credit_running_cap_vs_refund_fee_diverge_on_family_domain
    """
    s = _season_with_family(5000)
    fam_id = s["family"]["id"]
    g1 = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    c1 = fx.pledge_commitment(g1["id"], fam_id, "SCOREKEEPER", 3000)
    a1 = fx.propose_assignment(g1["id"], s["referee"]["id"])
    fx.confirm_assignment(a1["id"], s["referee"]["user_id"])
    fx.start_game(g1["id"])
    fx.finalize_game(g1["id"], 3, 1)

    fx.fulfill_commitment(c1["id"])
    fam = validate_success(api.get_family(fam_id, ADMIN))
    assert fam["volunteer_credit_cents"] == 3000, fam["volunteer_credit_cents"]
