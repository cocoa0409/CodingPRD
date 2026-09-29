"""Transitive cascades: one marketplace decision that propagates five levels,
and the counter-notice acceptance that unwinds four of them."""

from test_helpers import (
    COUNSEL,
    LIAISON,
    ENFORCEMENT_STATUS_REINSTATED,
    ENFORCEMENT_STATUS_REMOVED,
    SELLER_STATUS_ACTIVE,
    SELLER_STATUS_UNDER_INVESTIGATION,
    VIOLATION_TYPE_TRADEMARK,
    add_business_days,
    assert_instant_equals,
    assert_metrics,
    assert_score_2dp,
    assert_seller_strikes,
    create_claim,
    create_counter_notice,
    create_listing,
    create_takedown,
    fill_and_seal_package,
    preliminary_score,
    read_case,
    read_claim,
    read_listing,
    read_metrics,
    read_seller,
    read_takedown,
    resolve_counter_notice,
    screen_listing,
    set_clock,
    setup_removed_takedown,
    setup_second_removal_on_same_seller,
    submit_takedown,
    substantiate_claim,
    substantiation_base,
    validate_paginated,
    validate_success,
)


def _second_notice_awaiting_decision(api, ctx, tag="2"):
    """A second listing on the same seller carried up to a SUBMITTED notice."""
    listing = create_listing(api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=0)
    listing = screen_listing(api, listing["id"], 1.00, 1.00)
    claim = create_claim(api, ctx["brand"]["id"], listing["id"], ctx["registration"]["id"],
                         claimed_violation_type=VIOLATION_TYPE_TRADEMARK)
    claim = substantiate_claim(api, claim["id"])
    package = fill_and_seal_package(api, claim["id"], tag=tag)
    takedown = create_takedown(api, ctx["enrollment"]["id"], claim["id"], package["id"])
    ctx["listing_2"] = listing
    ctx["claim_2"] = claim
    ctx["package_2"] = package
    ctx["takedown_2"] = submit_takedown(api, takedown["id"], ctx["representative"]["id"])
    return ctx


def _cases_for_seller(api, seller_id):
    rows, _meta = validate_paginated(api.list_cases(headers=COUNSEL, seller_id=seller_id))
    return rows


def test_second_removal_propagates_five_levels_and_opens_a_case(api):
    """PRD §3.8: "On the **removed** branch the notice advances `SUBMITTED → APPROVED_REMOVED`, and a five-level cascade runs inside the same request."
    PRD §3.8: "A takedown-removal strike, worth 12.55 base points effective at this `decided_at`, enters the ledger against the seller that owns that listing, and both of that seller's strike variants are recomputed across its cluster."
    PRD §3.8: "If the recompute takes the cluster total to at least 25.00 the seller escalates out of `ACTIVE`, and if that escalation happens and no enforcement case for the pairing of the claim's brand and that seller is currently `OPEN`, one is auto-created with its `originating_takedown_id` set to this notice."
    PRD §3.8: "Finally the parent claim advances `SUBSTANTIATED → ENFORCED`."
    PRD §3.8: "`counter_notice_deadline_at` is computed by advancing `decided_at` by ten business days, opening the seller's contest window."

    Design: Difficulty/transitive_cascade/second_removal_cascades_five_levels_into_an_auto_created_case
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z",
                                 marketplace_case_ref="MP-1")
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 12.55, 12.55,
                          SELLER_STATUS_ACTIVE)
    set_clock(api, "2026-08-17T09:00:00Z")
    ctx = _second_notice_awaiting_decision(api, ctx)

    # The seller's own 12.55 points lift the history term to 0.3333, so the second
    # claim scores 60 * 1.0000 + 25 * 1.00 + 15 * 0.3333.
    assert_score_2dp(ctx["claim_2"]["substantiation_score"], 90.00, "substantiation_score")
    assert_score_2dp(ctx["claim_2"]["substantiation_score"],
                     substantiation_base(1.0000, 1.00, 12.55), "substantiation_score")
    assert_score_2dp(ctx["claim_2"]["preliminary_score"], 72.00, "preliminary_score")
    assert_score_2dp(ctx["claim_2"]["preliminary_score"],
                     preliminary_score(1.0000, 1.00, 12.55), "preliminary_score")
    assert _cases_for_seller(api, ctx["seller"]["id"]) == [], (
        "No case exists for the pairing before the second removal")

    decided = validate_success(api.decide_takedown(
        ctx["takedown_2"]["id"], "REMOVED", "MP-2", headers=LIAISON), 200)

    assert decided["status"] == "APPROVED_REMOVED", f"got {decided['status']}"
    assert_instant_equals(decided["decided_at"], "2026-08-17T09:00:00Z", "decided_at")
    assert_instant_equals(decided["counter_notice_deadline_at"], "2026-08-31T09:00:00Z",
                          "counter_notice_deadline_at")
    assert_instant_equals(decided["counter_notice_deadline_at"],
                          add_business_days("2026-08-17T09:00:00Z", 10),
                          "counter_notice_deadline_at")
    assert read_listing(api, ctx["listing_2"]["id"])["enforcement_status"] == (
        ENFORCEMENT_STATUS_REMOVED)
    assert read_claim(api, ctx["claim_2"]["id"])["status"] == "ENFORCED"
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 25.10, 25.10,
                          SELLER_STATUS_UNDER_INVESTIGATION)

    cases = _cases_for_seller(api, ctx["seller"]["id"])
    assert len(cases) == 1, f"Exactly one case is auto-created, got {len(cases)}"
    case = cases[0]
    assert case["brand_id"] == ctx["brand"]["id"]
    assert case["seller_id"] == ctx["seller"]["id"]
    assert case["originating_takedown_id"] == ctx["takedown_2"]["id"], (
        f"The case names the escalating notice, got {case['originating_takedown_id']}")
    assert case["case_status"] == "OPEN", f"got {case['case_status']}"
    assert case["correspondence_status"] == "NONE", f"got {case['correspondence_status']}"
    assert case["litigation_status"] == "NONE", f"got {case['litigation_status']}"


def test_a_third_removal_escalates_nothing_and_opens_no_second_case(api):
    """PRD §3.8: "If the recompute takes the cluster total to at least 25.00 the seller escalates out of `ACTIVE`, and if that escalation happens and no enforcement case for the pairing of the claim's brand and that seller is currently `OPEN`, one is auto-created with its `originating_takedown_id` set to this notice."
    PRD §3.3: "To make the thresholds concrete: a single fresh takedown-removal strike is 12.55 points and leaves the seller `ACTIVE`; two fresh takedown-removal strikes total 25.10 and escalate the seller to `UNDER_INVESTIGATION`; one fresh seizure-confirmed strike is 25.15 and escalates on its own; one fresh cease-and-desist-ignored strike is 5.05."
    PRD §3.8: "Every row touched anywhere in that cascade has its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/second_removal_cascades_five_levels_into_an_auto_created_case
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z",
                                 marketplace_case_ref="MP-1")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    cases = _cases_for_seller(api, ctx["seller"]["id"])
    assert len(cases) == 1, f"The second removal opens exactly one case, got {len(cases)}"
    case_before = read_case(api, cases[0]["id"])

    ctx = setup_second_removal_on_same_seller(api, ctx, tag="3")

    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 37.65, 37.65,
                          SELLER_STATUS_UNDER_INVESTIGATION)
    cases_after = _cases_for_seller(api, ctx["seller"]["id"])
    assert len(cases_after) == 1, (
        f"A seller already escalated opens no further case, got {len(cases_after)}")
    case_after = read_case(api, case_before["id"])
    assert case_after["originating_takedown_id"] == case_before["originating_takedown_id"], (
        "The surviving case keeps naming the notice that escalated the seller")
    assert case_after["version"] == case_before["version"], (
        f"The case is not part of the third cascade, got version {case_after['version']}")


def test_accepted_counter_notice_unwinds_the_removal_four_levels(api):
    """PRD §3.8: "On the **accepted** branch the counter notice moves `FILED → ACCEPTED`, `resolved_at` is stamped from the logical clock, and a four-level reversal cascade runs."
    PRD §3.8: "The parent notice moves `COUNTER_NOTICED → REINSTATED`. The listing moves `REMOVED → REINSTATED`. The takedown-removal strike attributed by that notice drops out of the ledger — because the notice no longer sits in `APPROVED_REMOVED` — and both strike variants are recomputed for the seller's whole cluster, de-escalating the seller from `UNDER_INVESTIGATION` back to `ACTIVE` when the cluster total falls below 25.00. And the parent claim falls `ENFORCED → SUBSTANTIATED`."
    PRD §3.8: "The counter notice lands in status `FILED` with `filed_at` stamped from the logical clock, `resolved_at` and `rebuttal_ref` null, and `response_due_at` computed by advancing `filed_at` by ten business days — the brand's window to rebut."

    Design: Difficulty/transitive_cascade/counter_notice_acceptance_reverses_the_removal_chain_four_levels
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z",
                                 marketplace_case_ref="MP-1")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    assert_instant_equals(ctx["takedown_2"]["counter_notice_deadline_at"],
                          "2026-08-31T09:00:00Z", "counter_notice_deadline_at")

    set_clock(api, "2026-08-19T09:00:00Z")
    counter = create_counter_notice(api, ctx["takedown_2"]["id"], ctx["seller"]["id"],
                                   sworn_statement_ref="CN-SWORN-1")
    assert counter["status"] == "FILED", f"got {counter['status']}"
    assert_instant_equals(counter["response_due_at"], "2026-09-02T09:00:00Z", "response_due_at")
    assert read_takedown(api, ctx["takedown_2"]["id"])["status"] == "COUNTER_NOTICED"

    resolved = resolve_counter_notice(api, counter["id"], "ACCEPTED")

    assert resolved["status"] == "ACCEPTED", f"got {resolved['status']}"
    assert_instant_equals(resolved["resolved_at"], "2026-08-19T09:00:00Z", "resolved_at")
    assert_instant_equals(resolved["response_due_at"], "2026-09-02T09:00:00Z", "response_due_at")
    assert read_takedown(api, ctx["takedown_2"]["id"])["status"] == "REINSTATED"
    assert read_listing(api, ctx["listing_2"]["id"])["enforcement_status"] == (
        ENFORCEMENT_STATUS_REINSTATED)
    assert read_claim(api, ctx["claim_2"]["id"])["status"] == "SUBSTANTIATED"
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 12.55, 12.55,
                          SELLER_STATUS_ACTIVE)

    assert read_takedown(api, ctx["takedown"]["id"])["status"] == "APPROVED_REMOVED", (
        "The first removal is untouched by the reversal")
    assert read_listing(api, ctx["listing"]["id"])["enforcement_status"] == (
        ENFORCEMENT_STATUS_REMOVED)
    surviving = _cases_for_seller(api, ctx["seller"]["id"])
    assert len(surviving) == 1 and surviving[0]["case_status"] == "OPEN", (
        "The auto-created case survives the reversal")


def test_reversal_moves_the_notice_back_into_the_decided_metric_counts(api):
    """PRD §3.11: "`decided_takedown_count` counts those takedowns whose `status` is `APPROVED_REMOVED`, `REJECTED` or `REINSTATED`."
    PRD §3.11: "A notice currently at `COUNTER_NOTICED` is excluded even though it was once `APPROVED_REMOVED` — only the current status matters."
    PRD §3.11: "`repeat_infringer_count` counts cluster roots — never alias rows — whose `cluster_strike_points` has reached 25.00 and that have at least one strike attributable to this brand somewhere in the cluster."
    PRD §3.11: "`listing_removal_rate` is `removed_takedown_count` divided by `decided_takedown_count`, rounded to four decimal places using ROUND_HALF_UP."

    Design: Difficulty/transitive_cascade/counter_notice_acceptance_reverses_the_removal_chain_four_levels
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z",
                                 marketplace_case_ref="MP-1")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   decided_takedown_count=2, removed_takedown_count=2,
                   listing_removal_rate=1.0000, repeat_infringer_count=1,
                   open_case_count=1, enforcement_spend_cents=0)

    set_clock(api, "2026-08-19T09:00:00Z")
    counter = create_counter_notice(api, ctx["takedown_2"]["id"], ctx["seller"]["id"],
                                   sworn_statement_ref="CN-SWORN-1")
    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   decided_takedown_count=1, removed_takedown_count=1,
                   listing_removal_rate=1.0000, repeat_infringer_count=1,
                   open_case_count=1)

    resolve_counter_notice(api, counter["id"], "ACCEPTED")

    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   decided_takedown_count=2, removed_takedown_count=1,
                   listing_removal_rate=0.5000, repeat_infringer_count=0,
                   open_case_count=1, enforcement_spend_cents=0)
