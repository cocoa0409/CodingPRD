"""Drafting, quoting, countering and issuing the licence."""
from test_helpers import (
    ApiErrorId,
    RIGHTS_ADMIN_DRAFTER_ID,
    RIGHTS_ADMIN_ISSUER_ID,
    RIGHTS_ADMIN_THIRD_ID,
    accept_license_deal,
    assert_instant_equals,
    assert_license_deal,
    create_composer,
    create_deliverable,
    draft_license_deal,
    get_demo,
    get_license_deal,
    get_project,
    make_client_rep_headers,
    make_producer_headers,
    make_rights_admin_headers,
    pitch_demo,
    propose_license_deal,
    select_demo,
    set_clock,
    setup_engagement,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    setup_license_deal,
    submit_demo,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_license_deal_payload


def _term_deal_env():
    """IN_PRODUCTION engagement whose approved brief names two markets."""
    set_clock("2026-09-01T00:00:00Z")
    return setup_engagement_in_production(
        budget_cents=4_000_000, target_markets=["US_NATIONAL", "US_REGIONAL"],
        required_lengths=[60, 30, 15], demo_fee_cents=150_000, submitted_length_seconds=60,
        demo_title="Sunrise Pop")


def test_licence_quote_prices_the_approved_brief_market_list(api):
    """PRD §3.6: "The quote is priced over the `target_markets` array of the
    engagement's `APPROVED` creative brief — everything the client *said* it wanted at
    brief time, regardless of what the deal actually grants — and it is rewritten every
    time the deal is drafted, proposed or countered."
    PRD §3.6: "For a `TERM` deal it is `creative_fee_cents` multiplied by 40 percent,
    then multiplied by `term_months` divided by twelve, and rounded half-up to whole
    cents — an annual rate of forty percent of the creative fee, pro-rated over the
    term."
    PRD §2.9: "A tier carries a flat per-market licence charge: 325,000 cents for a
    `TIER_1` market, 150,000 cents for a `TIER_2` market and 60,000 cents for a `TIER_3`
    market."

    Design: Difficulty/dual_variant_calc/license_fee_quoted_brief_markets_vs_invoiced_granted_markets
    """
    env = _term_deal_env()
    deal = draft_license_deal(env, license_structure="TERM", term_months=12,
                              market_codes=["US_NATIONAL"], creative_fee_cents=800_000)
    assert_license_deal(deal)
    assert deal["license_fee_quoted_cents"] == 795_000, (
        "Structure 320000 plus the brief's TIER_1 325000 and TIER_2 150000 is 795000; "
        f"got {deal['license_fee_quoted_cents']}")
    assert deal["license_fee_invoiced_cents"] == 0, (
        f"The invoice is written only at issuance; got {deal['license_fee_invoiced_cents']}")

    proposed = validate_success(api.propose_license_deal(
        deal["id"], make_rights_admin_headers(RIGHTS_ADMIN_DRAFTER_ID)))
    assert proposed["status"] == "PROPOSED", f"Expected PROPOSED, got {proposed['status']}"
    assert proposed["license_fee_quoted_cents"] == 795_000, (
        "Proposing refreshes the same forward-looking quote; "
        f"got {proposed['license_fee_quoted_cents']}")


def test_issuance_invoices_only_the_granted_markets(api):
    """PRD §3.6: "The invoice is priced over the deal's own `market_codes` **as they
    stand at that instant**, including every market a re-use extension has since added,
    and it is written at issuance and rewritten after each re-use extension and at each
    renewal."
    PRD §3.6: "For otherwise identical data the invoice is strictly smaller than the
    quote whenever the brief listed markets the deal did not grant, and strictly larger
    once re-use extensions have pushed the granted set past the brief."
    PRD §3.6: "On success the acting operator is recorded in `activated_by_user_id`,
    `effective_start_utc` is stamped from the logical clock, and `effective_end_utc` is
    set to `effective_start_utc` advanced by `term_months` multiplied by thirty days for
    a `TERM` grant, or left null for a `BUYOUT` grant, which is perpetual."

    Design: Difficulty/dual_variant_calc/license_fee_quoted_brief_markets_vs_invoiced_granted_markets
    """
    env = _term_deal_env()
    deal = draft_license_deal(env, license_structure="TERM", term_months=12,
                              market_codes=["US_NATIONAL"], creative_fee_cents=800_000)
    propose_license_deal(deal["id"], drafter=RIGHTS_ADMIN_DRAFTER_ID)
    accept_license_deal(deal["id"], env["client"]["id"])

    issued = validate_success(api.activate_license_deal(
        deal["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert issued["status"] == "ACTIVE", f"Expected ACTIVE, got {issued['status']}"
    assert issued["license_fee_quoted_cents"] == 795_000, (
        f"The quote is untouched by issuance; got {issued['license_fee_quoted_cents']}")
    assert issued["license_fee_invoiced_cents"] == 645_000, (
        "Structure 320000 plus only the granted TIER_1 325000 is 645000; "
        f"got {issued['license_fee_invoiced_cents']}")
    assert (issued["license_fee_quoted_cents"] - issued["license_fee_invoiced_cents"]) == 150_000, (
        "The ungranted TIER_2 market is exactly the 150000-cent difference")
    assert_instant_equals(issued["effective_start_utc"], "2026-09-01T00:00:00Z",
                          "effective_start_utc")
    assert_instant_equals(issued["effective_end_utc"], "2027-08-27T00:00:00Z",
                          "effective_end_utc")


def test_buyout_deal_carrying_term_months_is_rejected(api):
    """PRD §3.6: "The draft names its `license_structure`, which is either `BUYOUT` or
    `TERM`; a `term_months` value, which is mandatory for a `TERM` grant, forbidden on a
    `BUYOUT` grant, and when present must be 12, 24 or 36; a non-empty, duplicate-free
    `market_codes` array naming the territories actually granted; a `creative_fee_cents`
    figure strictly greater than zero that both fee variants scale from; and the
    `expected_project_version` guard of §2.8."
    PRD §2.5: "**Term coherence.** On licence-deal drafting and on client counter-offers,
    `term_months` is present when `license_structure` is `TERM` and absent when it is
    `BUYOUT` — otherwise `ERR_TERM_MONTHS_REQUIRED` (400)."

    Design: Corner/validations/corner_buyout_deal_carrying_term_months_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    project = get_project(env["project"]["id"])

    validate_error(
        api.create_license_deal(
            create_license_deal_payload(
                project["id"], env["demo"]["id"], project["version"],
                license_structure="BUYOUT", term_months=12, market_codes=["US_NATIONAL"],
                creative_fee_cents=400_000),
            make_rights_admin_headers()),
        ApiErrorId.ERR_TERM_MONTHS_REQUIRED.value, 400)

    _, meta = validate_paginated(api.list_license_deals(
        make_producer_headers(), params={"project_id": project["id"]}))
    assert meta["total_count"] == 0, f"No deal may be stored; got {meta['total_count']}"


def test_third_counter_round_is_rejected(api):
    """PRD §3.6: "The advertiser's representative may push it back, moving it
    `PROPOSED → DRAFT` with a `counter_note` explaining the position, a replacement
    `market_codes` array and, for a term grant, a replacement `term_months`; the counter
    payload **replaces** the deal's `term_months` and `market_codes` outright rather
    than merging into them, `counter_round_count` increases by one, and the quote is
    recomputed afterwards."
    PRD §3.6: "A deal whose `counter_round_count` has already reached two rounds cannot
    be countered again and is refused with `ERR_COUNTER_LIMIT_REACHED`."

    Design: Corner/validations/corner_third_counter_round_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    deal = setup_license_deal(env, stage="PROPOSED", license_structure="TERM", term_months=12,
                              market_codes=["US_NATIONAL"], creative_fee_cents=800_000)
    for note in ("drop the regional market", "shorten the term"):
        countered = validate_success(api.counter_license_deal(
            deal["id"],
            {"counter_note": note, "market_codes": ["US_NATIONAL"], "term_months": 12},
            make_client_rep_headers(env["client"]["id"])))
        assert countered["status"] == "DRAFT", f"A counter returns the deal to DRAFT; got {countered['status']}"
        propose_license_deal(deal["id"], drafter=RIGHTS_ADMIN_DRAFTER_ID)

    validate_error(
        api.counter_license_deal(
            deal["id"],
            {"counter_note": "one more please", "market_codes": ["US_LOCAL"], "term_months": 12},
            make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_COUNTER_LIMIT_REACHED.value, 422)

    after = get_license_deal(deal["id"])
    assert after["status"] == "PROPOSED", f"Expected PROPOSED, got {after['status']}"
    assert after["counter_round_count"] == 2, (
        f"The refused round must not increment; got {after['counter_round_count']}")
    assert after["market_codes"] == ["US_NATIONAL"], (
        f"The refused counter payload must not replace the market set; got {after['market_codes']}")


def test_deal_and_delivery_lifecycle_guards_reject_wrong_states(api):
    """PRD §3.6: "Any of these three moves attempted from a status that does not permit
    it is refused with `ERR_LICENSE_DEAL_INVALID_STATE`, and both countering and
    accepting require the acting `ClientRep` to own the engagement."
    PRD §3.8: "A `MusicHouseProducer` opens the delivery package for a deal whose status
    is `ACCEPTED`, `ACTIVE` or `RENEWAL_DUE`; any other status is refused with
    `ERR_LICENSE_DEAL_INVALID_STATE`, and a deal that already owns a package is refused
    with `ERR_DELIVERABLE_ALREADY_EXISTS` — there is **at most one package per deal**,
    and the package remembers its `license_deal_id`."
    PRD §3.8: "Attempting either move from the wrong audio state is refused with
    `ERR_DELIVERABLE_INVALID_STATE`."
    PRD §3.7: "The rights desk renews a deal that is `RENEWAL_DUE`, moving it
    `RENEWAL_DUE → ACTIVE`; a deal in any other status, and any `BUYOUT` deal, is
    refused with `ERR_LICENSE_NOT_RENEWABLE`."
    PRD §3.6: "A `RightsAdmin` drafts against a `project_id` that must be
    `IN_PRODUCTION` and a `demo_id` that must be `SELECTED` and must belong to that same
    engagement — a demo that is in any other status, or that belongs to a different
    engagement, is refused with `ERR_DEMO_NOT_SELECTED`."

    Design: Corner/errors/corner_deal_and_deliverable_lifecycle_guards_reject_wrong_states
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    winner_composer = create_composer(index=0)
    loser_composer = create_composer(index=1)
    winner = pitch_demo(env["project"]["id"], winner_composer["id"], title="Cut One",
                        demo_fee_cents=100_000, submitted_length_seconds=30)
    loser = pitch_demo(env["project"]["id"], loser_composer["id"], title="Cut Two",
                       demo_fee_cents=100_000, submitted_length_seconds=30)
    submit_demo(winner["id"], winner_composer["id"])
    submit_demo(loser["id"], loser_composer["id"])
    validate_success(api.shortlist_demo(winner["id"], make_client_rep_headers(env["client"]["id"])))
    select_demo(winner["id"], env["client"]["id"])
    env["demo"] = get_demo(winner["id"])
    deal = setup_license_deal(env, stage="ACTIVE", license_structure="BUYOUT",
                              market_codes=["US_NATIONAL"], creative_fee_cents=400_000)
    deliverable = create_deliverable(deal["id"])

    validate_error(
        api.accept_license_deal(deal["id"], make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_LICENSE_DEAL_INVALID_STATE.value, 409)
    validate_error(
        api.create_deliverable(deal["id"], make_producer_headers()),
        ApiErrorId.ERR_DELIVERABLE_ALREADY_EXISTS.value, 409)
    validate_error(
        api.approve_master(deliverable["id"], make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_DELIVERABLE_INVALID_STATE.value, 409)
    validate_error(
        api.renew_license_deal(deal["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_LICENSE_NOT_RENEWABLE.value, 409)

    project = get_project(env["project"]["id"])
    validate_error(
        api.create_license_deal(
            create_license_deal_payload(project["id"], loser["id"], project["version"],
                                        license_structure="BUYOUT",
                                        market_codes=["US_NATIONAL"],
                                        creative_fee_cents=400_000),
            make_rights_admin_headers(RIGHTS_ADMIN_DRAFTER_ID)),
        ApiErrorId.ERR_DEMO_NOT_SELECTED.value, 422)

    after = get_license_deal(deal["id"])
    assert after["status"] == "ACTIVE", f"Expected ACTIVE, got {after['status']}"
    assert after["renewal_count"] == 0
    assert validate_success(api.get_deliverable(
        deliverable["id"], make_producer_headers()))["master_status"] == "PENDING"
    _, meta = validate_paginated(api.list_deliverables(deal["id"], make_producer_headers()))
    assert meta["total_count"] == 1, (
        f"The deal must still own exactly one package; got {meta['total_count']}")
    assert get_demo(loser["id"])["status"] == "ARCHIVED"


def test_drafting_operator_cannot_issue_the_same_licence(api):
    """PRD §2.1: "Those two recorded values drive the segregation-of-duties rule — the
    rights desk requires two distinct operator identifiers to draft and to issue the
    same deal, and an attempt to issue a deal by the same operator identifier that
    drafted it is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD §3.6: "Issuance may never be performed by the same operator who drafted it: the
    acting `X-User-ID` must differ from `drafted_by_user_id`, and an attempt by the
    drafting operator is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_drafting_rights_admin_cannot_activate_the_same_deal
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    deal = setup_license_deal(env, stage="ACCEPTED", drafter=RIGHTS_ADMIN_DRAFTER_ID,
                              license_structure="BUYOUT", market_codes=["US_NATIONAL"],
                              creative_fee_cents=400_000)
    assert deal["drafted_by_user_id"] == RIGHTS_ADMIN_DRAFTER_ID

    validate_error(
        api.activate_license_deal(deal["id"],
                                  make_rights_admin_headers(RIGHTS_ADMIN_DRAFTER_ID)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = get_license_deal(deal["id"])
    assert after["status"] == "ACCEPTED", f"Expected ACCEPTED, got {after['status']}"
    assert after["activated_by_user_id"] is None, (
        f"Expected activated_by_user_id null, got {after['activated_by_user_id']}")
    assert after["license_fee_invoiced_cents"] == 0, (
        f"No invoice may be written; got {after['license_fee_invoiced_cents']}")


def test_stale_engagement_version_blocks_a_second_draft(api):
    """PRD §2.8: "Drafting a licence deal (`POST /license-deals`) requires a
    non-optional `expected_project_version` field carrying the client's last observed
    `version` of the target engagement."
    PRD §2.8: "If `expected_project_version` does not equal the engagement's current
    `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412."
    PRD §2.8: "A successful draft increments the engagement's `version` by 1."

    Design: Corner/cross_cutting_layers/corner_stale_project_version_on_a_second_deal_create_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    observed_version = get_project(env["project"]["id"])["version"]
    first = draft_license_deal(env, expected_project_version=observed_version,
                               license_structure="BUYOUT", market_codes=["US_NATIONAL"],
                               creative_fee_cents=400_000)

    validate_error(
        api.create_license_deal(
            create_license_deal_payload(
                env["project"]["id"], env["demo"]["id"], observed_version,
                license_structure="TERM", term_months=12, market_codes=["US_NATIONAL"],
                creative_fee_cents=500_000),
            make_rights_admin_headers(RIGHTS_ADMIN_THIRD_ID)),
        ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

    _, meta = validate_paginated(api.list_license_deals(
        make_producer_headers(), params={"project_id": env["project"]["id"]}))
    assert meta["total_count"] == 1, (
        f"The stale draft must not be stored; got {meta['total_count']}")
    assert get_license_deal(first["id"])["status"] == "DRAFT"


def test_fresh_engagement_version_lets_a_new_deal_supersede_the_prior_draft(api):
    """PRD §2.8: "A new deal legitimately supersedes any `DRAFT` or `PROPOSED` deal
    already sitting on that engagement, so the write is always semantically valid — the
    version check is the only thing that stops a writer from superseding a deal it never
    observed."
    PRD §3.6: "Drafting a new deal supersedes the engagement's earlier attempts: every
    existing deal of that engagement in `DRAFT` moves `DRAFT → SUPERSEDED` and every one
    in `PROPOSED` moves `PROPOSED → SUPERSEDED`, with no fiscal effect in either case."

    Design: Corner/cross_cutting_layers/corner_fresh_project_version_lets_a_new_deal_supersede_the_prior_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=100_000)
    first = draft_license_deal(env, license_structure="BUYOUT", market_codes=["US_NATIONAL"],
                               creative_fee_cents=400_000)
    refreshed_version = get_project(env["project"]["id"])["version"]

    response = api.create_license_deal(
        create_license_deal_payload(
            env["project"]["id"], env["demo"]["id"], refreshed_version,
            license_structure="TERM", term_months=12, market_codes=["US_NATIONAL"],
            creative_fee_cents=800_000),
        make_rights_admin_headers(RIGHTS_ADMIN_THIRD_ID))
    second = validate_success(response, 201)
    assert second["status"] == "DRAFT", f"Expected DRAFT, got {second['status']}"
    assert second["license_fee_quoted_cents"] == 645_000, (
        "Structure 320000 plus the brief's single TIER_1 market is 645000; "
        f"got {second['license_fee_quoted_cents']}")
    assert get_license_deal(first["id"])["status"] == "SUPERSEDED", (
        "The earlier DRAFT deal must be superseded by the new one")

    _, meta = validate_paginated(api.list_license_deals(
        make_producer_headers(), params={"project_id": env["project"]["id"]}))
    assert meta["total_count"] == 2, f"Both deals must remain readable; got {meta['total_count']}"


def test_brief_market_code_outside_the_vocabulary_is_rejected(api):
    """PRD §2.9: "Any market code outside these seven — wherever it appears, in a
    brief's `target_markets`, in a deal's `market_codes`, in a counter-offer, or as the
    `market_code` of a re-use extension — is rejected with `ERR_UNKNOWN_MARKET_CODE`
    before any pricing runs."

    Design: Corner/validations/corner_brief_with_an_unknown_market_code_is_rejected
    """
    env = setup_engagement(with_brief=False, budget_cents=4_000_000)

    validate_error(
        api.create_brief(env["project"]["id"],
                         {"tempo_bpm": 110, "mood_tags": ["cosy"],
                          "target_markets": ["US_NATIONAL", "MARS_ORBIT"],
                          "required_lengths": [30]},
                         make_producer_headers()),
        ApiErrorId.ERR_UNKNOWN_MARKET_CODE.value, 400)

    project = get_project(env["project"]["id"])
    assert project["status"] == "DRAFT", (
        f"A rejected brief must leave the engagement in DRAFT; got {project['status']}")
    _, meta = validate_paginated(api.list_project_briefs(
        env["project"]["id"], make_producer_headers()))
    assert meta["total_count"] == 0, f"No brief may be attached; got {meta['total_count']}"
