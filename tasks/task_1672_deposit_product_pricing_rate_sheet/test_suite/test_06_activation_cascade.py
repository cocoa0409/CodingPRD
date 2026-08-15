"""Activation cascade: supersession, repricing, grandfathering, notices,
exception rebase, cadence, scan actioning, and cascade-driven OCC staleness
(PRD §2.7, §3.2, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_deposit_account,
    deploy_all,
    create_cycle,
    create_draft_sheet,
    create_effective_sheet,
    create_exception,
    create_product,
    create_scan,
    find_cycle,
    list_account_notices,
    list_sheet_deployments,
    open_account,
    promote_sheet_to_scheduled,
    scan_entry,
    send_all_notices,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
BANKER = TEST_USERS["banker_headers"]

VAR_TIERS_V1 = [tier(0, 0, 1_000_000, 100), tier(1, 1_000_000, -1, 150)]
VAR_TIERS_V2 = [tier(0, 0, 1_000_000, 90), tier(1, 1_000_000, -1, 120)]
CD_TIERS = [tier(0, 0, 500_000, 300), tier(1, 500_000, 5_000_000, 375),
            tier(2, 5_000_000, -1, 430)]


def _cascade_scenario(api):
    """S1 (P-VAR) EFFECTIVE 2026-08-15; S1CD (P-CD9) EFFECTIVE 2026-09-01;
    accounts A1 (5,000,000 on P-VAR), A2 (500,000 on P-VAR), A3 (30,000,000 on
    P-CD9); exception X1 UNDER_REVIEW against S1; scan SC1 ANALYZED; successor
    S2 for P-VAR staged for 2026-09-15 with source_scan_id=SC1. Activation of
    S2 is the trigger left to each test."""
    p_var = create_product(product_code="VAR", product_class="SAVINGS", term_months=0,
                           tier_application="WHOLE_BALANCE", rate_cap_bp=500)
    s1 = create_effective_sheet(product_id=p_var["id"], effective_date="2026-08-15",
                                tiers=VAR_TIERS_V1)["sheet"]
    p_cd = create_product(product_code="CD9", product_class="CD", term_months=12,
                          tier_application="WHOLE_BALANCE", rate_cap_bp=900,
                          allows_promos=False)
    s1cd = create_effective_sheet(product_id=p_cd["id"], effective_date="2026-09-01",
                                  tiers=CD_TIERS)["sheet"]

    a1 = open_account(p_var["id"], opening_balance_cents=5_000_000, customer_ref="CA1")
    a2 = open_account(p_var["id"], opening_balance_cents=500_000, customer_ref="CA2",
                      channel="BRANCH")
    a3 = open_account(p_cd["id"], opening_balance_cents=30_000_000, customer_ref="CA3",
                      channel="BRANCH")
    x1 = create_exception(a1["id"], s1["id"], requested_rate_bp=170, term_days=60,
                          submitter_user_id="banker-1")

    sc1 = create_scan(entries=[scan_entry("Alpha", "SAVINGS", 200, 1_000_000)])
    validate_success(api.analyze_competitor_rate_scan(sc1["id"], ANALYST))

    s2 = create_draft_sheet(p_var["id"], effective_date="2026-09-15",
                            tiers=VAR_TIERS_V2, source_scan_id=sc1["id"])
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-15")

    return {"p_var": p_var, "p_cd": p_cd, "s1": s1, "s1cd": s1cd, "s2": s2,
            "a1": a1, "a2": a2, "a3": a3, "x1": x1, "sc1": sc1}


def test_activation_supersedes_incumbent_and_retires_deployments(api, analyst_headers,
                                                                 channel_headers):
    """PRD §3.2: "The new sheet's `supersedes_sheet_id` is set to the prior
    `EFFECTIVE` sheet for the pair (remaining null when this is the pair's
    first activation); the prior sheet transitions `EFFECTIVE → SUPERSEDED`,
    and its `end_date` is truncated to the new sheet's `effective_date`,
    closing its window."
    PRD §3.2: "Every `DEPLOYED` deployment belonging to the superseded sheet
    transitions to `RETIRED`."

    Design: Difficulty/transitive_cascade/activate_cascade_depth3
    """
    sc = _cascade_scenario(api)
    activated = validate_success(api.activate_rate_sheet(sc["s2"]["id"], analyst_headers))
    assert activated["status"] == "EFFECTIVE"
    assert activated["supersedes_sheet_id"] == sc["s1"]["id"]

    old = validate_success(api.get_rate_sheet(sc["s1"]["id"], analyst_headers))
    assert old["status"] == "SUPERSEDED"
    assert old["end_date"] == "2026-09-15"

    for row in list_sheet_deployments(sc["s1"]["id"]):
        assert row["status"] == "RETIRED", f"deployment {row['id']} not retired"


def test_activation_reprices_variable_and_grandfathers_term(api, analyst_headers,
                                                            banker_headers):
    """PRD §3.2: "Every account priced on the superseded sheet whose lifecycle
    is not `CLOSED` is re-priced by product kind: accounts of variable-rate
    products (`term_months` equal to zero) are re-pointed — `sheet_id` set to
    the new sheet, `base_rate_bp` and `current_rate_bp` recomputed, version
    bumped — while accounts of term products keep their `sheet_id` and their
    frozen rate, flipping `rate_source` to `GRANDFATHERED` with a version
    bump."
    PRD §3.1: term accounts "lock their rate at open and turn `GRANDFATHERED`
    when their sheet is later superseded" — A3's sheet S1CD (a different
    product's pair) is not the superseded sheet here, so A3 is untouched.

    Design: Difficulty/transitive_cascade/activate_cascade_depth3
    """
    sc = _cascade_scenario(api)
    validate_success(api.activate_rate_sheet(sc["s2"]["id"], analyst_headers))

    a1 = validate_success(api.get_deposit_account(sc["a1"]["id"], banker_headers))
    assert_deposit_account(a1)
    assert a1["sheet_id"] == sc["s2"]["id"]
    assert a1["current_rate_bp"] == 120  # 5,000,000 falls in the 120 bp tier
    assert a1["version"] > sc["a1"]["version"]

    a2 = validate_success(api.get_deposit_account(sc["a2"]["id"], banker_headers))
    assert a2["current_rate_bp"] == 90  # 500,000 falls in the 90 bp tier

    # A3 is priced on S1CD, which was not superseded by S2's activation: the
    # cascade (scoped to accounts priced on the superseded sheet) leaves it
    # on sheet pricing, rate unchanged.
    a3 = validate_success(api.get_deposit_account(sc["a3"]["id"], banker_headers))
    assert a3["rate_source"] == "SHEET"
    assert a3["current_rate_bp"] == 430
    assert a3["sheet_id"] == sc["s1cd"]["id"]


def test_activation_spawns_notices_rebase_cycle_and_scan_effects(api, analyst_headers,
                                                                 banker_headers,
                                                                 compliance_headers):
    """PRD §3.2: "Each repriced account whose rate dropped by ten basis points
    or more receives an account-level `RATE_CHANGE_ADVERSE` notice on its home
    channel, due five days after the activation date."
    PRD §3.2: "Exception requests priced against the superseded sheet that sit
    in `UNDER_REVIEW` or `RETURNED` move to `REBASE_REQUIRED`."
    PRD §3.2: "The pair's RepricingCycle records `last_reviewed_at` as the
    activation date and recomputes `next_review_due`."
    PRD §3.2: "If the activated sheet names a `source_scan_id` and that scan
    is `ANALYZED`, the scan transitions to `ACTIONED`."

    Design: Difficulty/transitive_cascade/activate_cascade_depth3
    """
    sc = _cascade_scenario(api)
    validate_success(api.activate_rate_sheet(sc["s2"]["id"], analyst_headers))

    # A1 dropped 150 -> 120 (30 bp >= 10): adverse notice due five days out.
    a1_notices = [n for n in list_account_notices(sc["a1"]["id"])
                  if n["notice_type"] == "RATE_CHANGE_ADVERSE"]
    assert len(a1_notices) == 1
    assert a1_notices[0]["required_by_date"] == "2026-09-20"
    assert a1_notices[0]["channel"] == sc["a1"]["channel"]

    x1 = validate_success(api.get_exception_pricing_request(sc["x1"]["id"], banker_headers))
    assert x1["status"] == "REBASE_REQUIRED"

    cycle = find_cycle(sc["p_var"]["id"], "US-WEST")
    assert cycle["last_reviewed_at"] == "2026-09-15"

    scan = validate_success(api.get_competitor_rate_scan(sc["sc1"]["id"], analyst_headers))
    assert scan["status"] == "ACTIONED"


def _cadence_scenario(api):
    """A pair whose cycle (30-day cadence) was created explicitly, then whose
    first sheet activates on 2026-08-15."""
    product = create_product(product_code="CAD")
    cycle = create_cycle(product["id"], cadence_days=30)
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(100))
    return cycle


def test_cadence_current_before_due_date(api, analyst_headers):
    """PRD §3.3: "`next_review_due` is computed as `last_reviewed_at` plus
    `cadence_days`, and is null while the pair has never activated. The
    cycle's `status` is computed on read: `OVERDUE` once `last_reviewed_at` is
    set and logical today reaches `next_review_due` — the due date itself
    already counts as overdue, an inclusive boundary — and `CURRENT` in every
    other case, including never-activated pairs."

    Design: Difficulty/boundary_precision_check/repricing_cadence_due_date_inclusive
    """
    cycle = _cadence_scenario(api)
    set_clock("2026-09-13")
    data = validate_success(api.get_repricing_cycle(cycle["id"], analyst_headers))
    assert data["last_reviewed_at"] == "2026-08-15"
    assert data["next_review_due"] == "2026-09-14"
    assert data["status"] == "CURRENT"


def test_cadence_overdue_on_due_date(api, analyst_headers):
    """PRD §3.3: "The cycle's `status` is computed on read: `OVERDUE` once
    `last_reviewed_at` is set and logical today reaches `next_review_due` —
    the due date itself already counts as overdue, an inclusive boundary — and
    `CURRENT` in every other case, including never-activated pairs."

    Design: Difficulty/boundary_precision_check/repricing_cadence_due_date_inclusive
    """
    cycle = _cadence_scenario(api)
    set_clock("2026-09-14")  # the due date itself
    data = validate_success(api.get_repricing_cycle(cycle["id"], analyst_headers))
    assert data["status"] == "OVERDUE"
    assert data["next_review_due"] == "2026-09-14"


def test_occ_account_version_bumped_by_cascade_goes_stale(api, banker_headers,
                                                          analyst_headers):
    """PRD §2.7: "Adjusting an account balance (`PATCH /deposit-accounts/{id}`)
    requires the non-optional field `expected_account_version`, carrying the
    account `version` the client last observed. If the account's current
    `version` has advanced — including through cascade-driven repricing from
    sheet activation, migration execution, or bundle changes — the adjustment
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_account_version_bumped_by_cascade_goes_stale
    """
    product = create_product(product_code="OCC2")
    s1 = create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                                tiers=single_tier(100))["sheet"]
    account = open_account(product["id"], opening_balance_cents=1_000_000,
                           customer_ref="COCC")
    stale_version = account["version"]

    # A successor sheet activates, repricing the account and bumping its
    # version without the client's involvement.
    s2 = create_draft_sheet(product["id"], effective_date="2026-09-01",
                            tiers=single_tier(120))
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-01")
    validate_success(api.activate_rate_sheet(s2["id"], analyst_headers))

    cascaded = validate_success(api.get_deposit_account(account["id"], banker_headers))
    assert cascaded["current_rate_bp"] == 120
    assert cascaded["version"] > stale_version

    # The pre-cascade version is stale: the legitimate write is rejected.
    resp = api.patch_deposit_account(
        account["id"],
        {"expected_account_version": stale_version, "balance_cents": 2_000_000},
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    # Re-read, then retry with the fresh version: succeeds.
    fresh = validate_success(api.get_deposit_account(account["id"], banker_headers))
    patched = validate_success(api.patch_deposit_account(
        account["id"],
        {"expected_account_version": fresh["version"], "balance_cents": 2_000_000},
        banker_headers))
    assert patched["balance_cents"] == 2_000_000
    assert patched["version"] == fresh["version"] + 1
