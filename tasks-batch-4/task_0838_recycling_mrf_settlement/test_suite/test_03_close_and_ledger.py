"""Closing loads: dual-variant contamination, the ledger cascade, residual bound."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    assert_revenue_posting,
)
from test_helpers.fixtures import (
    setup_audited_load, close_load, get_municipality,
)

SORT = TEST_USERS["sort_manager_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# --- Difficulty: dual-variant contamination (provisional vs final) ----------

def test_provisional_adjustment_at_audit_not_posted(api):
    """PRD §3.4: "A successful audit stores the sampled contamination and
    composition, computes and stores the load's `provisional_adjustment_cents`
    from the sampled figure (the provisional variant of the contamination
    calculation described in §3.5), and moves the load to `AUDITED`."
    PRD §3.5: "The **provisional variant** runs at audit: it uses
    `sampled_contamination_pct` as the contamination input, stores its result in
    `provisional_adjustment_cents`, and does **not** post anything to the ledger."

    Design: Difficulty/dual_variant_calc/dual_contamination_provisional_vs_final_on_load
    """
    ctx = setup_audited_load(api, revenue_share_pct=0.60, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    assert ctx["load"]["provisional_adjustment_cents"] == 6000
    muni = get_municipality(api, ctx["m_id"])
    assert muni["balance_cents"] == 0, "provisional adjustment must not touch the ledger"


def test_final_adjustment_at_close_differs_from_provisional(api):
    """PRD §3.5: "The **final variant** runs at close: its contamination input is
    the residual-derived actual, computed as `residual_tons` divided by `net_tons`,
    multiplied by 100, rounded to four decimal places."
    PRD §3.5: "If contamination is at least the penalty threshold of 12.0 percent,
    the load incurs a penalty: let the points over threshold be the contamination
    percentage minus 12.0; the adjustment is a negative amount whose magnitude is
    `net_tons` multiplied by those points-over multiplied by 150 cents per
    ton-per-point, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/dual_contamination_provisional_vs_final_on_load
    """
    ctx = setup_audited_load(api, revenue_share_pct=0.60, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    load = close_load(api, ctx["load_id"], residual_tons=3.0)
    assert load["final_adjustment_cents"] == -9000
    assert load["provisional_adjustment_cents"] == 6000
    assert load["provisional_adjustment_cents"] != load["final_adjustment_cents"]


# --- Difficulty: close cascade to the municipal ledger ----------------------

def test_close_computes_negative_final_adjustment(api):
    """PRD §3.5: "The final result is stored in `final_adjustment_cents` and is
    posted to the municipality."
    PRD §3.5: "If contamination is at least the penalty threshold of 12.0 percent,
    the load incurs a penalty: let the points over threshold be the contamination
    percentage minus 12.0; the adjustment is a negative amount whose magnitude is
    `net_tons` multiplied by those points-over multiplied by 150 cents per
    ton-per-point, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/close_cascade_final_adjustment_to_municipality_ledger
    """
    ctx = setup_audited_load(api, revenue_share_pct=0.50, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    load = close_load(api, ctx["load_id"], residual_tons=3.0)
    assert load["final_adjustment_cents"] == -9000


def test_close_penalty_posts_to_municipality_lifetime_penalty(api):
    """PRD §3.5: "second, that posting updates the municipality's
    `lifetime_rebate_cents` or `lifetime_penalty_cents` (penalties stored as
    positive magnitude), re-derives `balance_cents`, and increments the
    municipality's `version`."
    PRD §2.6: "`balance_cents`, is derived as `revenue_share_accrued_cents` plus
    `lifetime_rebate_cents` minus `lifetime_penalty_cents`."

    Design: Difficulty/transitive_cascade/close_cascade_final_adjustment_to_municipality_ledger
    """
    ctx = setup_audited_load(api, revenue_share_pct=0.50, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    close_load(api, ctx["load_id"], residual_tons=3.0)
    muni = get_municipality(api, ctx["m_id"])
    assert muni["lifetime_penalty_cents"] == 9000
    assert muni["balance_cents"] == -9000
    data, meta = validate_paginated(
        api.list_revenue_postings(CLERK, params={"municipality_id": ctx["m_id"]}))
    penalties = [p for p in data if p["posting_type"] == "PENALTY"]
    assert len(penalties) == 1
    assert penalties[0]["amount_cents"] == -9000


def test_close_residual_exceeds_net_rejected(api):
    """PRD §3.5: "The residual plus whatever has already been baled must not exceed
    the load's net weight — that is, `residual_tons` plus `baled_tons` must be at
    most `net_tons`, else `ERR_RESIDUAL_EXCEEDS_NET`."

    Design: Corner/validations/corner_residual_exceeds_net_rejected
    """
    ctx = setup_audited_load(api, gross_tons=20, tare_tons=0)
    resp = api.close_inbound_load(ctx["load_id"], {"residual_tons": 25.0}, SORT)
    validate_error(resp, ApiErrorId.ERR_RESIDUAL_EXCEEDS_NET.value)


def test_revenue_posting_is_append_only_without_version(api):
    """PRD §2.4: "A posting has no `updated_at` and no `version`, because it is
    never modified after it is written — a correction is expressed by writing a
    further posting, never by editing an existing one."

    Design: Corner/entities/corner_revenue_posting_is_append_only_no_version
    """
    ctx = setup_audited_load(api, gross_tons=10, tare_tons=0,
                             sampled_contamination_pct=2.0)
    close_load(api, ctx["load_id"], residual_tons=0)  # clean -> REBATE posting
    data, meta = validate_paginated(
        api.list_revenue_postings(CLERK, params={"municipality_id": ctx["m_id"]}))
    assert len(data) == 1
    posting = data[0]
    assert "version" not in posting
    assert "updated_at" not in posting
    assert_revenue_posting(posting)
