"""The two dual-variant calculations: yield on cost and the fraud risk score.

Each calculation is run twice against the same row by two variants that write disjoint
field groups, and each test pins both variants at once so a single-variant implementation
cannot pass by computing one of them well.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import assert_fields, assert_money_group, created, ok
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_05,
    CLOCK_SEP_06,
    FRAUD_VARIANT_POST,
    FRAUD_VARIANT_PRE,
    IDENTITY_VERIFIED,
    LEASE_EXECUTED,
)
from test_helpers.test_users import make_vendor_headers


def test_underwritten_and_realized_yield_diverge_by_28_bps_on_one_case(api):
    """Executing the lease leaves both variants on the row, 28 bps apart.

    PRD SS3.2: "The same case realized against three completed work orders costing 310000,
    640000 and 570000 and an executed lease at 208000 a month yields a basis of 27270000
    and a realized yield of 531 basis points -- twenty-eight basis points below the
    underwritten figure on the same home."  PRD SS3.2 also fixes the underwritten group:
    "yields a basis of 27229843 ... effective gross income of 2425200 ... net operating
    income of 1521184 and an underwritten yield of 559 basis points."  And PRD SS3.2:
    "`disposition_flagged` is true exactly when that score is below zero, which is to say
    when the approved case's realized yield sits strictly below the market's disposition
    floor."

    Design: Difficulty/dual_variant_calc/yield_on_cost_underwritten_versus_realized_diverges_28_bps
    """
    ctx = x.acquired_home(api, general_template=False)
    vendor = x.create_vendor(api, ctx.market_id)
    x.certify_vendor(api, vendor["id"], "HVAC", expires_on="2027-01-31")
    project = get_success_data(
        api.create_renovation_project(f.renovation_project_payload(ctx.home_id, 1600000), x.OPS)
    )
    paint = get_success_data(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    hvac = get_success_data(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.templates.hvac["id"],
                fulfillment_channel="VENDOR",
                quoted_cost_cents=640000,
                project_id=project["id"],
            ),
            x.OPS,
        )
    )
    floor = get_success_data(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.templates.floor["id"],
                quantity=1150,
                crew_size=2,
                quoted_cost_cents=570000,
                project_id=project["id"],
            ),
            x.OPS,
        )
    )
    x.set_clock(api, CLOCK_AUG_05)
    get_success_data(api.lock_project_scope(project["id"], f.lock_scope_payload(), x.OPS))
    get_success_data(api.dispatch_work_order(paint["id"], {}, x.OPS))
    get_success_data(api.dispatch_work_order(hvac["id"], {"vendor_id": vendor["id"]}, x.OPS))
    get_success_data(api.accept_work_order(hvac["id"], {}, make_vendor_headers(vendor["id"])))
    get_success_data(api.dispatch_work_order(floor["id"], {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_06)
    get_success_data(
        api.complete_work_order(paint["id"], f.complete_work_order_payload(310000, "2026-09-06"), x.OPS)
    )
    get_success_data(
        api.complete_work_order(
            hvac["id"],
            f.complete_work_order_payload(640000, "2026-09-06"),
            make_vendor_headers(vendor["id"]),
        )
    )
    get_success_data(
        api.complete_work_order(floor["id"], f.complete_work_order_payload(570000, "2026-09-06"), x.OPS)
    )
    prospect = x.verified_prospect(api, ctx.market_id)
    screening = x.screened_application(api, ctx.home_id, prospect.prospect_id)
    lease = x.funded_draft_lease(api, screening.application_id)

    executed = ok(api.execute_lease(lease["id"], f.execute_lease_payload(), x.AGENT))
    assert_fields(executed, status=LEASE_EXECUTED)

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_money_group(
        case,
        underwritten_all_in_basis_cents=27229843,
        underwritten_effective_gross_income_cents=2425200,
        underwritten_noi_cents=1521184,
        realized_renovation_cost_cents=1520000,
        realized_all_in_basis_cents=27270000,
        realized_noi_cents=1448541,
    )
    assert_fields(case, underwritten_yield_on_cost_bps=559, realized_yield_on_cost_bps=531)
    assert case["underwritten_yield_on_cost_bps"] - case["realized_yield_on_cost_bps"] == 28

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_fields(home, hold_sell_score_bps=-9, disposition_flagged=True)


def test_fraud_score_falls_3757_bps_from_pre_to_post_verification(api):
    """One prospect scores 4850 at registration and 1093 after verifying.

    PRD SS3.6: "A prospect declaring 700000 with credit `B` and no evictions scores
    identity 10000, income 0 (since the raw coverage figure of 11111 exceeds 10,000 and the
    factor floors), history 1500 and device 7000, which weighs out to 35000000 plus 0 plus
    3000000 plus 10500000, or 48500000, and after the single final division 4850 basis
    points. The same prospect then verifies with a document score of 9200, liveness true, a
    verified income of 560000, a device reputation of 8800 and 15 km of geo distance:
    identity becomes 800, income becomes 1111, history stays 1500, device becomes 1200, and
    the score falls to 1093 basis points -- 3757 basis points of divergence between the two
    variants for the same person in the same market, which is exactly why the variant that
    produced a score is recorded alongside it."

    Design: Difficulty/dual_variant_calc/fraud_score_pre_versus_post_verification_diverges_3757_bps
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)

    registered = created(api.create_prospect(f.prospect_payload(market["id"]), x.ANON))
    assert_fields(
        registered,
        fraud_risk_score_bps=4850,
        fraud_score_variant=FRAUD_VARIANT_PRE,
        verification_attempt_count=0,
    )
    pre_score = registered["fraud_risk_score_bps"]

    verified = ok(
        api.verify_identity(
            registered["id"],
            f.identity_verification_payload(registered["version"]),
            x.make_prospect_headers(registered["id"]),
        )
    )
    assert_fields(
        verified,
        fraud_risk_score_bps=1093,
        fraud_score_variant=FRAUD_VARIANT_POST,
        identity_status=IDENTITY_VERIFIED,
        verification_attempt_count=1,
        version=registered["version"] + 1,
    )
    assert pre_score - verified["fraud_risk_score_bps"] == 3757
