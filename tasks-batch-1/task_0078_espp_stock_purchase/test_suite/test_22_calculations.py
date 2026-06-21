"""Corner section: calculations (PRD §3.3, §3.8).

Contribution withholding floor, qualifying gain-limited variant, and disqualifying
capital-loss variant.
"""
from test_helpers import (
    get_success_data,
    create_disposition_payload,
    setup_enrolled_participant,
    setup_settled_purchase,
    make_participant_headers,
    make_admin_headers,
)


def test_contribution_withholding_floor_applied(api):
    """PRD §3.3: "The system computes the withheld amount_cents by multiplying
    gross_pay_cents by the enrollment's contribution_rate_pct, dividing by 100, and
    taking the floor of the result."

    gross 333333 at 7.5% => 24999.975 => floor => 24999.

    Design: Corner/calculations/contribution_withholding_floor_applied
    """
    _, _, _, enrollment = setup_enrolled_participant(rate_pct=7.5)
    contribution = get_success_data(
        api.create_contribution(
            {
                "enrollment_id": enrollment["id"],
                "pay_date": "2024-02-01T00:00:00.000Z",
                "gross_pay_cents": 333333,
            },
            make_admin_headers("admin1"),  # contributions recorded by PlanAdministrator
        )
    )
    assert contribution["amount_cents"] == 24999, contribution


def _settled_2022_lot(api, rate_pct=15):
    return setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=rate_pct,
    )


def test_qualifying_gain_limited_variant(api):
    """PRD §3.8: "When the actual gain is the smaller, ordinary income is capped by the
    economic gain (the case of a low or loss sale) ... The adjusted basis is then the
    purchase cost plus the ordinary income, and the capital_gain_cents is the sale
    proceeds minus that adjusted basis."

    Qualifying sale (2024-06-30) of 100 shares at 900c, paid 850c, grant_fmv 1000:
    actual_gain = 100*(900-850) = 5000; statutory = 100*(1000-850) = 15000;
    ordinary = min = 5000; capital_gain = 90000 - (85000+5000) = 0.

    Design: Corner/calculations/qualifying_gain_limited_variant
    """
    ctx = _settled_2022_lot(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2024-06-30T00:00:00.000Z", shares_sold=100,
                sale_price_per_share_cents=900,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "QUALIFYING", disp
    assert disp["ordinary_income_cents"] == 5000, disp
    assert disp["capital_gain_cents"] == 0, disp


def test_disqualifying_capital_loss_variant(api):
    """PRD §3.8: "For a disqualifying disposition, the ordinary_income_cents is fixed at
    the spread at purchase regardless of the sale price ... the adjusted basis is the
    purchase cost ... plus that ordinary income, and the capital_gain_cents is the sale
    proceeds ... minus the adjusted basis. The sale price therefore affects only the
    capital-gain figure on a disqualifying sale, never the ordinary-income spread."

    Disqualifying sale (2022-12-31) of 100 shares at 1000c, paid 850, purchase_fmv 1200:
    ordinary = 100*(1200-850) = 35000; basis = 85000+35000 = 120000;
    capital_gain = 100000 - 120000 = -20000.

    Design: Corner/calculations/disqualifying_capital_loss_variant
    """
    ctx = _settled_2022_lot(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2022-12-31T00:00:00.000Z", shares_sold=100,
                sale_price_per_share_cents=1000,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "DISQUALIFYING", disp
    assert disp["ordinary_income_cents"] == 35000, disp
    assert disp["capital_gain_cents"] == -20000, disp
