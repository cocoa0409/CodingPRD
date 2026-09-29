"""Predatory-screening verdicts, the allocation waterfall, invoice pricing
boundaries and the annual-spend analytics arithmetic.

Every test builds its own world from an empty database and drives the logical
clock explicitly, so each arithmetic outcome is reproducible from first
principles.
"""

import pytest

from test_helpers import (
    AUTHOR_GUIDANCE,
    approve_invoice_for_payment,
    create_decision_payload,
    create_screening_run_payload,
    open_fund,
    open_fund_request,
    pay_invoice,
    read_article,
    read_author,
    read_fund,
    read_grant,
    receive_invoice,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    setup_active_agreement,
    setup_fund_route_article,
    setup_publisher_with_journal,
    start_review,
    validate_invoice,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# local preambles
# --------------------------------------------------------------------------- #
def _setup_hybrid_agreement_at_twenty_percent(clock: str) -> dict:
    """Publisher MERID with a HYBRID journal listed at 380000 cents, covered by
    an ACTIVE agreement discounting 0.20 with a quota of five articles."""
    set_clock(clock)
    return setup_active_agreement(
        publisher_code="MERID",
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
        journal_overrides={
            "issn": "2041-1723",
            "title": "Meridian Journal of Cell Signalling",
            "oa_model": "HYBRID",
            "list_apc_cents": 380000,
            "required_embargo_months": 12,
        },
    )


def _register_faculty_author(**overrides) -> dict:
    defaults = {
        "full_name": "Ilse Vermeer",
        "email": "ilse.vermeer@uni.example",
        "orcid": "0000-0002-1111-2222",
        "department_code": "CEL",
        "affiliation_status": "ELIGIBLE_FACULTY",
        "appointment_from": "2024-01-01",
        "appointment_until": "2028-12-31",
        "annual_cap_cents": 500000,
    }
    defaults.update(overrides)
    return register_author(**defaults)


# --------------------------------------------------------------------------- #
# predatory-venue screening
# --------------------------------------------------------------------------- #
def test_screening_score_of_forty_six_lands_in_the_watchlist_band(api, librarian_headers):
    """A run scoring exactly 46 sits inside the watchlist band and pins its guidance.

    PRD §3.1: "A freshly registered publisher has not been screened: its `screening_status` is `UNSCREENED`, its `predatory_score` is absent, its `active_agreement_count` is zero, and the signal snapshot fields and `author_guidance` and `last_screened_at` are all absent."
    PRD §3.1: "A screening run supplies six signals about the publisher, all of which overwrite whatever the previous run recorded — earlier runs are never averaged in."
    PRD §3.1: "Twenty-five points are added when the publisher is not indexed in DOAJ."
    PRD §3.1: "Fifteen points are added when it is not a COPE member."
    PRD §3.1: "Twenty points are added when the editorial board could not be verified."
    PRD §3.1: "The retraction signal contributes the retraction rate per thousand multiplied by five and rounded half up to a whole number, but capped so that it can never contribute more than twenty-five points."
    PRD §3.1: "Fifteen points are added when the median peer-review turnaround is strictly less than fourteen days, on the reasoning that a two-week median is implausibly fast for genuine review; a median of exactly fourteen days adds nothing."
    PRD §3.1: "Finally, a transparency credit is subtracted: one tenth of the `apc_transparency_score`, rounded half up to a whole number."
    PRD §3.1: "A score of at least 35 but below 60 is `WATCHLIST`."
    PRD §3.1: "For `WATCHLIST` it reads "Venue on watchlist: confirm indexing and peer-review claims before submitting.""
    PRD §3.1: "The run also stamps `last_screened_at` from the logical clock and increments the publisher's `version` by one."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    Design: Corner/calculations/corner_screening_score_lands_in_the_watchlist_band
    """
    set_clock("2026-08-04T00:00:00Z")
    publisher = register_publisher(
        publisher_code="BORDER",
        name="Borderline Publishing House",
        country_code="IN",
    )
    assert publisher["screening_status"] == "UNSCREENED", (
        "a freshly registered publisher has not been screened, got "
        f"{publisher['screening_status']!r}"
    )
    assert publisher["version"] == 1, (
        f"version starts at 1 on creation, got {publisher['version']}"
    )

    data = validate_success(
        api.create_screening_run(
            publisher["id"],
            create_screening_run_payload(
                doaj_indexed=False,
                cope_member=False,
                editorial_board_verified=True,
                retraction_rate_per_1000=2.0,
                peer_review_days_median=30,
                apc_transparency_score=40,
            ),
            librarian_headers,
        )
    )

    assert data["predatory_score"] == 46, (
        "25 (no DOAJ) + 15 (no COPE) + 0 (board verified) + 10 (2.0 * 5, under the "
        "25 cap) + 0 (30 days is not below 14) - 4 (one tenth of 40) is 46, got "
        f"{data['predatory_score']}"
    )
    assert data["screening_status"] == "WATCHLIST", (
        f"46 is at least 35 and below 60, so the verdict is WATCHLIST, got "
        f"{data['screening_status']!r}"
    )
    assert data["author_guidance"] == AUTHOR_GUIDANCE["WATCHLIST"], (
        f"WATCHLIST pins its own guidance string, got {data['author_guidance']!r}"
    )
    assert data["last_screened_at"].startswith("2026-08-04T00:00:00"), (
        "last_screened_at is stamped from the logical clock, got "
        f"{data['last_screened_at']!r}"
    )
    assert data["version"] == 2, (
        f"the run increments the publisher's version by one, got {data['version']}"
    )
    assert data["retraction_rate_per_1000"] == 2.0, (
        "the run records the retraction signal it was given, got "
        f"{data['retraction_rate_per_1000']}"
    )
    assert data["apc_transparency_score"] == 40, (
        "the run records the transparency signal it was given, got "
        f"{data['apc_transparency_score']}"
    )


def test_screening_applies_the_retraction_cap_and_the_clamp_floor(api, librarian_headers):
    """A retraction rate of 20.0 contributes 25, not 100, and a negative total clamps to 0.

    PRD §3.1: "Twenty-five points are added when the publisher is not indexed in DOAJ."
    PRD §3.1: "Fifteen points are added when it is not a COPE member."
    PRD §3.1: "Twenty points are added when the editorial board could not be verified."
    PRD §3.1: "The retraction signal contributes the retraction rate per thousand multiplied by five and rounded half up to a whole number, but capped so that it can never contribute more than twenty-five points."
    PRD §3.1: "Fifteen points are added when the median peer-review turnaround is strictly less than fourteen days, on the reasoning that a two-week median is implausibly fast for genuine review; a median of exactly fourteen days adds nothing."
    PRD §3.1: "Finally, a transparency credit is subtracted: one tenth of the `apc_transparency_score`, rounded half up to a whole number."
    PRD §3.1: "The running total is then clamped into the range from 0 to 100 inclusive — a negative total becomes zero and a total above one hundred becomes one hundred — and the clamped value is stored as `predatory_score`."
    PRD §3.1: "A score of 85 or more is `BLOCKED`."
    PRD §3.1: "Anything below 35 is `CLEARED`."
    PRD §3.1: "For `BLOCKED` it reads "Venue blocked: eligibility checks are refused; contact the scholarly communications office.""
    PRD §3.1: "For `CLEARED` the guidance reads "Venue cleared: institutional APC funds and agreement coverage may be used.""
    Design: Corner/calculations/corner_screening_retraction_cap_and_clamp_floor_are_applied
    """
    capped_publisher = register_publisher(
        publisher_code="APEXR", name="Apex Rapid Publishing", country_code="US"
    )
    clean_publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )

    capped = validate_success(
        api.create_screening_run(
            capped_publisher["id"],
            create_screening_run_payload(
                doaj_indexed=False,
                cope_member=False,
                editorial_board_verified=False,
                retraction_rate_per_1000=20.0,
                peer_review_days_median=7,
                apc_transparency_score=100,
            ),
            librarian_headers,
        )
    )
    clean = validate_success(
        api.create_screening_run(
            clean_publisher["id"],
            create_screening_run_payload(
                doaj_indexed=True,
                cope_member=True,
                editorial_board_verified=True,
                retraction_rate_per_1000=0.0,
                peer_review_days_median=30,
                apc_transparency_score=100,
            ),
            librarian_headers,
        )
    )

    assert capped["predatory_score"] == 90, (
        "25 + 15 + 20 + 25 (20.0 * 5 capped at 25) + 15 - 10 is 90; capping after "
        "the clamp instead would report 100, got "
        f"{capped['predatory_score']}"
    )
    assert capped["screening_status"] == "BLOCKED", (
        f"90 is at least 85, so the verdict is BLOCKED, got {capped['screening_status']!r}"
    )
    assert capped["author_guidance"] == AUTHOR_GUIDANCE["BLOCKED"], (
        f"BLOCKED pins its own guidance string, got {capped['author_guidance']!r}"
    )

    assert clean["predatory_score"] == 0, (
        "all-clean signals with a transparency credit of 10 give a running total of "
        f"-10, which the clamp floor pins to 0, got {clean['predatory_score']}"
    )
    assert clean["screening_status"] == "CLEARED", (
        f"0 is below 35, so the verdict is CLEARED, got {clean['screening_status']!r}"
    )
    assert clean["author_guidance"] == AUTHOR_GUIDANCE["CLEARED"], (
        f"CLEARED pins its own guidance string, got {clean['author_guidance']!r}"
    )


def test_second_screening_run_overwrites_rather_than_averaging_the_first(
    api, librarian_headers
):
    """A blocked publisher re-screened with clean signals scores 0, not the average 45.

    PRD §3.1: "A screening run supplies six signals about the publisher, all of which overwrite whatever the previous run recorded — earlier runs are never averaged in."
    PRD §3.1: "The running total is then clamped into the range from 0 to 100 inclusive — a negative total becomes zero and a total above one hundred becomes one hundred — and the clamped value is stored as `predatory_score`."
    PRD §3.1: "A score of 85 or more is `BLOCKED`."
    PRD §3.1: "Anything below 35 is `CLEARED`."
    PRD §3.1: "The run also stamps `last_screened_at` from the logical clock and increments the publisher's `version` by one."
    Design: Corner/calculations/corner_screening_uses_only_the_current_run_signals
    """
    publisher = register_publisher(
        publisher_code="APEXR", name="Apex Rapid Publishing", country_code="US"
    )

    first = validate_success(
        api.create_screening_run(
            publisher["id"],
            create_screening_run_payload(
                doaj_indexed=False,
                cope_member=False,
                editorial_board_verified=False,
                retraction_rate_per_1000=20.0,
                peer_review_days_median=7,
                apc_transparency_score=100,
            ),
            librarian_headers,
        )
    )
    assert first["predatory_score"] == 90, (
        f"the all-bad run scores 90, got {first['predatory_score']}"
    )
    assert first["screening_status"] == "BLOCKED", (
        f"90 is at least 85, so the verdict is BLOCKED, got {first['screening_status']!r}"
    )
    assert first["version"] == 2, (
        f"the first run takes the publisher's version to 2, got {first['version']}"
    )

    second = validate_success(
        api.create_screening_run(
            publisher["id"],
            create_screening_run_payload(
                doaj_indexed=True,
                cope_member=True,
                editorial_board_verified=True,
                retraction_rate_per_1000=0.0,
                peer_review_days_median=30,
                apc_transparency_score=100,
            ),
            librarian_headers,
        )
    )

    assert second["predatory_score"] == 0, (
        "the second run's signals overwrite the first, giving 0; averaging the two "
        f"runs would report 45, got {second['predatory_score']}"
    )
    assert second["screening_status"] == "CLEARED", (
        f"0 is below 35, so the verdict is CLEARED, got {second['screening_status']!r}"
    )
    assert second["version"] == 3, (
        f"the second run takes the publisher's version to 3, got {second['version']}"
    )
    assert second["doaj_indexed"] is True, (
        "the run overwrites the recorded doaj_indexed signal, got "
        f"{second['doaj_indexed']!r}"
    )
    assert second["peer_review_days_median"] == 30, (
        "the run overwrites the recorded peer_review_days_median signal, got "
        f"{second['peer_review_days_median']}"
    )


# --------------------------------------------------------------------------- #
# annual spend analytics
# --------------------------------------------------------------------------- #
def test_average_paid_net_rounds_half_up_at_the_half_cent(api, fund_manager_headers):
    """Paid nets of 250001 and 250000 average to 250000.5, which rounds up to 250001.

    PRD §2.7: "Wherever a fractional multiplication must be reduced to cents, the result is rounded half up: a value whose fractional part is exactly one half rounds away from zero to the next whole cent."
    PRD §3.9: "The fiscal-year window runs from 1 July of the year before the requested `fiscal_year` through 30 June of the requested `fiscal_year`, inclusive at both ends."
    PRD §3.9: "From the invoice ledger, the report takes every invoice whose `status` is `PAID` and whose `invoice_date` falls inside the fiscal-year window, further narrowed to the requested `publisher_id` when one is supplied: `paid_invoice_count` is how many such invoices there are, and `avg_paid_net_cents` is the sum of their `net_cents` divided by that count and rounded half up to whole cents — or exactly zero when there are no such invoices, since division by zero is never attempted."
    PRD §3.9: "From the allocation ledger, the report takes every allocation line whose fund carries the requested `fiscal_year`: `total_committed_cents` is the sum of `amount_cents` over lines whose status is `ENCUMBERED`, and `total_disbursed_cents` is the same sum over lines whose status is `DISBURSED`; released lines are excluded from both."
    PRD §3.9: "Across the whole determination population, `hybrid_article_count` counts those whose journal has an `oa_model` of `HYBRID` and `fully_oa_article_count` counts those whose journal has an `oa_model` of `FULLY_OA`."
    PRD §3.9: "The `top_publisher_code` names the publisher with the largest paid net spend: the eligible pool is the publishers appearing among the paid invoices above, they are ranked by the sum of their invoices' `net_cents` descending with `publisher_code` ascending as the tie-break, and the winner's `publisher_code` is reported — or nothing at all when the pool is empty."
    PRD §3.9: "The `negotiation_leverage_ratio` expresses savings against cash actually paid: it is `ta_savings_cents` divided by `total_disbursed_cents`, except that the divisor is floored at 1 so that a year with no disbursement yields the savings figure rather than an undefined value, and the quotient is rounded half up to four decimal places."
    PRD §3.4: "It qualifies when, and only when, all four of these hold: the article names a grant; that grant's `status` is `ACTIVE`; the grant's funder has a `mandate_type` of either `GOLD_OA` or `IMMEDIATE_CC_BY`; the funder's `apc_allowable` is true; and the journal's `oa_model` is `FULLY_OA`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.7: "The `entitled_discount_pct` — the discount the institution is actually entitled to — depends on the route: when the determination's route is `TA_FULL` or `TA_CAPPED`, it is that determination's `discount_pct_applied`, because the agreement fixes the discount; when the route is `FUND_APC` or `AUTHOR_PAYS`, there is no agreement and the entitlement comes instead from the publisher's volume tier described below."
    PRD §3.7: "Tier boundaries are inclusive: prior paid net spend of fifty thousand dollars or more (5000000 cents) earns a twenty percent entitlement, at least twenty thousand dollars (2000000 cents) earns fifteen percent, at least five thousand dollars (500000 cents) earns ten percent, and anything below five thousand dollars earns nothing at all."
    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    Design: Corner/calculations/corner_analytics_average_paid_net_rounds_half_up_at_half_cent
    """
    set_clock("2026-08-10T00:00:00Z")
    publisher = register_publisher(
        publisher_code="SELKIE", name="Selkie Press", country_code="IE"
    )
    odd_journal = register_journal(
        publisher["id"],
        issn="2050-084X",
        title="Selkie Journal of Marine Ecology",
        oa_model="FULLY_OA",
        list_apc_cents=250001,
        required_embargo_months=12,
    )
    even_journal = register_journal(
        publisher["id"],
        issn="2397-3374",
        title="Selkie Journal of Coastal Genomics",
        oa_model="FULLY_OA",
        list_apc_cents=250000,
        required_embargo_months=12,
    )
    author = _register_faculty_author(
        full_name="Maeve Lynch",
        email="maeve.lynch@uni.example",
        orcid="0000-0002-7654-3210",
        department_code="MAR",
    )

    first_article = record_article(
        odd_journal["id"],
        author["id"],
        manuscript_title="Half-cent average, first article",
        accepted_on="2026-08-05",
    )
    first_determination = run_eligibility_check(
        first_article["id"], author["id"], basis="PROVISIONAL"
    )
    assert first_determination["route"] == "AUTHOR_PAYS", (
        "an article with no grant does not qualify for the fund route, so the route "
        f"is AUTHOR_PAYS, got {first_determination['route']!r}"
    )

    second_article = record_article(
        even_journal["id"],
        author["id"],
        manuscript_title="Half-cent average, second article",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(second_article["id"], author["id"], basis="PROVISIONAL")

    first_invoice = receive_invoice(
        publisher["id"],
        first_article["id"],
        "SELKIE-3001",
        250001,
        0.0,
        0.0,
        "2026-08-10",
    )
    assert first_invoice["net_cents"] == 250001, (
        "prior paid net spend is below 500000, so the entitlement is nothing at all "
        f"and net_cents is the full base, got {first_invoice['net_cents']}"
    )
    validate_invoice(first_invoice["id"])
    approve_invoice_for_payment(first_invoice["id"])
    pay_invoice(first_invoice["id"], "WIRE-90001")

    second_invoice = receive_invoice(
        publisher["id"],
        second_article["id"],
        "SELKIE-3002",
        250000,
        0.0,
        0.0,
        "2026-08-10",
    )
    assert second_invoice["net_cents"] == 250000, (
        "prior paid net spend of 250001 is still below the 500000 tier boundary, so "
        f"net_cents is the full base, got {second_invoice['net_cents']}"
    )
    validate_invoice(second_invoice["id"])
    approve_invoice_for_payment(second_invoice["id"])
    pay_invoice(second_invoice["id"], "WIRE-90002")

    report = validate_success(
        api.get_annual_spend(fund_manager_headers, params={"fiscal_year": 2027})
    )

    assert report["paid_invoice_count"] == 2, (
        "both invoices are PAID with an invoice_date inside the FY2027 window, got "
        f"{report['paid_invoice_count']}"
    )
    assert report["avg_paid_net_cents"] == 250001, (
        "500001 over 2 is 250000.5, which rounds half up to 250001; truncation or "
        f"round-half-even would report 250000, got {report['avg_paid_net_cents']}"
    )
    assert report["total_disbursed_cents"] == 0, (
        "no allocation line exists, so nothing is disbursed, got "
        f"{report['total_disbursed_cents']}"
    )
    assert report["top_publisher_code"] == "SELKIE", (
        "the only publisher in the paid pool holds the largest paid net spend, got "
        f"{report['top_publisher_code']!r}"
    )
    assert report["fully_oa_article_count"] == 2, (
        "both journals are FULLY_OA, got " f"{report['fully_oa_article_count']}"
    )
    assert report["negotiation_leverage_ratio"] == pytest.approx(0.0, abs=0.01), (
        "no agreement covered either article, so savings are zero and the ratio is "
        f"0.0, got {report['negotiation_leverage_ratio']}"
    )


def test_leverage_ratio_applies_the_denominator_floor_of_one(api, librarian_headers):
    """Savings of 76000 with nothing disbursed divide by the floor of 1, not by zero.

    PRD §3.4: "The `discount_pct_applied` is that agreement's `discount_pct`, and the discounted price is `list_base_cents` multiplied by one minus the discount, rounded half up to whole cents — this is the only rounding step in the whole determination."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    PRD §3.9: "From the determination ledger, the report takes the effective determination of every article whose `accepted_on` falls inside the fiscal-year window: `ta_articles_covered` counts those whose route is `TA_FULL` or `TA_CAPPED`, and `ta_savings_cents` sums, over exactly that same subset, the `list_base_cents` less the `covered_amount_cents` less the `author_share_cents` of each determination — the portion of list price that the negotiated discount removed altogether."
    PRD §3.9: "Across the whole determination population, `hybrid_article_count` counts those whose journal has an `oa_model` of `HYBRID` and `fully_oa_article_count` counts those whose journal has an `oa_model` of `FULLY_OA`."
    PRD §3.9: "The `negotiation_leverage_ratio` expresses savings against cash actually paid: it is `ta_savings_cents` divided by `total_disbursed_cents`, except that the divisor is floored at 1 so that a year with no disbursement yields the savings figure rather than an undefined value, and the quotient is rounded half up to four decimal places."
    PRD §3.9: "From the invoice ledger, the report takes every invoice whose `status` is `PAID` and whose `invoice_date` falls inside the fiscal-year window, further narrowed to the requested `publisher_id` when one is supplied: `paid_invoice_count` is how many such invoices there are, and `avg_paid_net_cents` is the sum of their `net_cents` divided by that count and rounded half up to whole cents — or exactly zero when there are no such invoices, since division by zero is never attempted."
    PRD §3.9: "The `top_publisher_code` names the publisher with the largest paid net spend: the eligible pool is the publishers appearing among the paid invoices above, they are ranked by the sum of their invoices' `net_cents` descending with `publisher_code` ascending as the tie-break, and the winner's `publisher_code` is reported — or nothing at all when the pool is empty."
    PRD §3.9: "The headline `total_allocated_cents` then depends on the `basis`: on the encumbrance basis it is `total_committed_cents` plus `total_disbursed_cents`, and on the cash basis it is `total_disbursed_cents` alone."
    Design: Corner/calculations/corner_analytics_leverage_ratio_applies_the_denominator_floor
    """
    scenario = _setup_hybrid_agreement_at_twenty_percent("2026-08-10T00:00:00Z")
    author = _register_faculty_author()
    article = record_article(
        scenario["journal"]["id"],
        author["id"],
        manuscript_title="Savings without cash movement",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(
        article["id"], author["id"], basis="PROVISIONAL"
    )

    assert determination["route"] == "TA_FULL", (
        f"FULL_APC coverage routes to TA_FULL, got {determination['route']!r}"
    )
    assert determination["list_base_cents"] == 380000, (
        "the provisional base is the journal's list charge, got "
        f"{determination['list_base_cents']}"
    )
    assert determination["covered_amount_cents"] == 304000, (
        "380000 times one minus 0.20 is 304000, covered in full, got "
        f"{determination['covered_amount_cents']}"
    )
    assert determination["author_share_cents"] == 0, (
        f"TA_FULL leaves the author nothing to pay, got {determination['author_share_cents']}"
    )

    report = validate_success(
        api.get_annual_spend(
            librarian_headers, params={"fiscal_year": 2027, "basis": "ENCUMBRANCE"}
        )
    )

    assert report["ta_articles_covered"] == 1, (
        f"the single TA_FULL article is counted, got {report['ta_articles_covered']}"
    )
    assert report["ta_savings_cents"] == 76000, (
        "380000 less 304000 covered less 0 author share is 76000, got "
        f"{report['ta_savings_cents']}"
    )
    assert report["hybrid_article_count"] == 1, (
        f"the journal is HYBRID, got {report['hybrid_article_count']}"
    )
    assert report["fully_oa_article_count"] == 0, (
        f"no FULLY_OA journal is involved, got {report['fully_oa_article_count']}"
    )
    assert report["paid_invoice_count"] == 0, (
        f"no invoice was ever raised, got {report['paid_invoice_count']}"
    )
    assert report["avg_paid_net_cents"] == 0, (
        "an empty paid population reports exactly zero rather than attempting a "
        f"division, got {report['avg_paid_net_cents']}"
    )
    assert report["top_publisher_code"] is None, (
        f"an empty paid pool names no publisher, got {report['top_publisher_code']!r}"
    )
    assert report["total_allocated_cents"] == 0, (
        "nothing is committed and nothing is disbursed, got "
        f"{report['total_allocated_cents']}"
    )
    assert report["negotiation_leverage_ratio"] == pytest.approx(76000.0, abs=0.01), (
        "76000 divided by the floored divisor of 1 is 76000.0, got "
        f"{report['negotiation_leverage_ratio']}"
    )


# --------------------------------------------------------------------------- #
# the allocation waterfall
# --------------------------------------------------------------------------- #
def test_waterfall_skips_the_affiliation_ineligible_fund_and_caps_the_next(
    api, fund_manager_headers
):
    """The rank-1 fund is filtered out on affiliation; rank 2 caps at 100000 and rank 3 fills the rest.

    PRD §3.5: "Otherwise a request ceiling is set to the smallest of three independent limits: the request's own `requested_cents`, the effective determination's `eligible_request_cents`, and the author's remaining allowance."
    PRD §3.5: "The candidate funds are those whose `status` is `OPEN` — frozen funds are excluded outright — whose `fiscal_year` equals the fiscal year of the current clock date, whose period contains the clock date so that `period_from` is on or before it and `period_to` is on or after it, and whose `eligible_affiliation_statuses` list contains the author's `affiliation_status`."
    PRD §3.5: "Candidates are drawn in ascending `priority_rank`, with `created_at` ascending as the tie-break of last resort; ties cannot actually arise because a fiscal year admits each rank only once."
    PRD §3.5: "Otherwise the fund's own availability is computed as `total_budget_cents` less `committed_cents` less `spent_cents`, and the amount taken from this fund is the smallest of three quantities: the amount still to be filled, that availability, and the fund's `per_article_cap_cents`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §3.5: "The approved total is the request ceiling less whatever remained unfilled."
    PRD §3.5: "Otherwise `FundRequest.approved_cents` is set to that total, `FundRequest.author_share_cents` becomes `requested_cents` less the approved total, and `FundRequest.fully_funded` is true exactly when the approved total equals `requested_cents`."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    PRD §3.5: "A new request has `status` `SUBMITTED` and `revision_round` of zero, with `info_needed`, `response_note`, `reviewed_by_user_id`, `decided_by_user_id` and `decision_reason` all absent, `approved_cents` and `author_share_cents` at zero and `fully_funded` false."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §2.8: "`Author.apc_committed_cents` is the `ENCUMBRANCE_INCLUSIVE` figure for that author in the current fiscal year, and `Author.apc_disbursed_cents` is the `CASH_BASIS` figure for the same scope."
    Design: Corner/calculations/corner_waterfall_skips_affiliation_ineligible_fund_and_applies_per_article_cap
    """
    set_clock("2026-08-10T00:00:00Z")
    scenario = setup_fund_route_article(
        accepted_on="2026-08-05",
        list_apc_cents=250000,
        publisher_code="HALDEN",
        author_overrides={
            "full_name": "Tomas Berg",
            "email": "tomas.berg@uni.example",
            "orcid": "0000-0001-5109-3700",
            "department_code": "MET",
            "affiliation_status": "ELIGIBLE_FACULTY",
            "appointment_from": "2024-01-01",
            "appointment_until": "2028-12-31",
            "annual_cap_cents": 500000,
        },
        funder_overrides={
            "name": "National Research Council",
            "funder_code": "NRC",
            "mandate_type": "GOLD_OA",
            "max_embargo_months": 6,
            "deposit_deadline_days": 90,
            "license_required": "CC_BY",
            "apc_allowable": True,
        },
        grant_overrides={
            "grant_number": "NRC-2026-0451",
            "award_from": "2026-01-01",
            "award_until": "2027-12-31",
        },
        article_overrides={"manuscript_title": "Waterfall across two eligible funds"},
    )
    assert scenario["determination"]["route"] == "FUND_APC", (
        "a FULLY_OA journal with an active GOLD_OA grant and no agreement routes to "
        f"FUND_APC, got {scenario['determination']['route']!r}"
    )
    assert scenario["determination"]["eligible_request_cents"] == 250000, (
        "the whole list base is eligible to be requested, got "
        f"{scenario['determination']['eligible_request_cents']}"
    )

    postdoc_fund = open_fund(
        fund_code="OA-POSTDOC-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_POSTDOC"],
        per_article_cap_cents=500000,
    )
    department_fund = open_fund(
        fund_code="OA-DEPT-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=2,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=100000,
    )
    central_fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=3,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY", "ELIGIBLE_POSTDOC"],
        per_article_cap_cents=500000,
    )

    request = open_fund_request(
        scenario["article"]["id"],
        scenario["author"]["id"],
        250000,
        justification="Fully OA journal with no transformative agreement.",
    )
    assert request["status"] == "SUBMITTED", (
        f"a new request starts SUBMITTED, got {request['status']!r}"
    )
    assert request["revision_round"] == 0, (
        f"a new request starts at revision_round zero, got {request['revision_round']}"
    )
    start_review(request["id"])

    decided = validate_success(
        api.decide_fund_request(
            request["id"],
            create_decision_payload("APPROVE", "Cap and fund capacity available."),
            fund_manager_headers,
        )
    )

    assert decided["status"] == "APPROVED", (
        f"the approval moves the request to APPROVED, got {decided['status']!r}"
    )
    assert decided["approved_cents"] == 250000, (
        "100000 from the rank-2 fund plus 150000 from the rank-3 fund is 250000, got "
        f"{decided['approved_cents']}"
    )
    assert decided["author_share_cents"] == 0, (
        "requested less approved is zero, got " f"{decided['author_share_cents']}"
    )
    assert decided["fully_funded"] is True, (
        f"approved equals requested, so the request is fully funded, got "
        f"{decided['fully_funded']!r}"
    )

    rows, meta = validate_paginated(
        api.list_fund_request_allocations(
            request["id"], fund_manager_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        "only the two affiliation-eligible funds contributed a line, got "
        f"total_count {meta['total_count']}"
    )
    assert len(rows) == 2, f"expected exactly two allocation lines, got {len(rows)}"

    by_sequence = {row["sequence_index"]: row for row in rows}
    assert set(by_sequence) == {1, 2}, (
        f"the sequence counter runs 1 then 2, got {sorted(by_sequence)}"
    )
    assert by_sequence[1]["fund_id"] == department_fund["id"], (
        "the rank-2 fund is drawn first once the rank-1 fund is filtered out, got "
        f"{by_sequence[1]['fund_id']!r}"
    )
    assert by_sequence[1]["amount_cents"] == 100000, (
        "the rank-2 fund is limited by its per-article cap of 100000, got "
        f"{by_sequence[1]['amount_cents']}"
    )
    assert by_sequence[1]["status"] == "ENCUMBERED", (
        f"a new allocation line is ENCUMBERED, got {by_sequence[1]['status']!r}"
    )
    assert by_sequence[2]["fund_id"] == central_fund["id"], (
        f"the rank-3 fund supplies the remainder, got {by_sequence[2]['fund_id']!r}"
    )
    assert by_sequence[2]["amount_cents"] == 150000, (
        "250000 less the 100000 already taken is 150000, got "
        f"{by_sequence[2]['amount_cents']}"
    )
    assert by_sequence[2]["status"] == "ENCUMBERED", (
        f"a new allocation line is ENCUMBERED, got {by_sequence[2]['status']!r}"
    )

    skipped = read_fund(postdoc_fund["id"])
    assert skipped["committed_cents"] == 0, (
        "the rank-1 fund does not list the author's affiliation status, so it never "
        f"enters the candidate set, got committed_cents {skipped['committed_cents']}"
    )
    assert skipped["available_cents"] == 500000, (
        f"the untouched fund keeps its whole budget available, got "
        f"{skipped['available_cents']}"
    )

    drawn = read_fund(department_fund["id"])
    assert drawn["committed_cents"] == 100000, (
        f"committed_cents sums the fund's ENCUMBERED lines, got {drawn['committed_cents']}"
    )
    assert drawn["available_cents"] == 400000, (
        f"500000 less 100000 committed is 400000, got {drawn['available_cents']}"
    )
    assert drawn["status"] == "OPEN", (
        "100000 is far below ninety-eight percent of the budget, so the fund stays "
        f"OPEN, got {drawn['status']!r}"
    )

    remainder = read_fund(central_fund["id"])
    assert remainder["committed_cents"] == 150000, (
        f"committed_cents sums the fund's ENCUMBERED lines, got {remainder['committed_cents']}"
    )
    assert remainder["available_cents"] == 350000, (
        f"500000 less 150000 committed is 350000, got {remainder['available_cents']}"
    )

    article = read_article(scenario["article"]["id"])
    assert article["funding_status"] == "FUNDED", (
        "a fully funded request moves the article to FUNDED, got "
        f"{article['funding_status']!r}"
    )

    author = read_author(scenario["author"]["id"])
    assert author["apc_committed_cents"] == 250000, (
        "the encumbrance-inclusive figure counts both new lines, got "
        f"{author['apc_committed_cents']}"
    )
    assert author["apc_disbursed_cents"] == 0, (
        "no money has left the institution yet, got " f"{author['apc_disbursed_cents']}"
    )


# --------------------------------------------------------------------------- #
# invoice validation boundary
# --------------------------------------------------------------------------- #
def test_variance_of_exactly_one_hundred_cents_is_within_tolerance(
    api, librarian_headers
):
    """A variance of exactly 100 validates; one cent more disputes.

    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    PRD §3.7: "Second, `vat_cents` is that already-rounded `net_cents` multiplied by the invoice's `vat_pct`, rounded half up to whole cents — the tax is computed on the rounded net, not on the unrounded net."
    PRD §3.7: "Third, `expected_amount_cents` is `net_cents` plus `vat_cents` with no further rounding applied to the sum."
    PRD §3.7: "Finally, `variance_cents` is the invoice's `invoice_amount_cents` less the `expected_amount_cents`, and may be negative when the publisher under-billed."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    PRD §3.7: "Otherwise, if the absolute value of `variance_cents` is no more than one hundred cents — one US dollar — the outcome is `WITHIN_TOLERANCE`."
    PRD §3.7: "Otherwise the outcome is `AMOUNT_VARIANCE`."
    PRD §3.7: "A `MATCH` or a `WITHIN_TOLERANCE` moves the invoice from `RECEIVED` to `VALIDATED` and records no dispute."
    PRD §3.7: "A `DISCOUNT_SHORTFALL` or an `AMOUNT_VARIANCE` moves the invoice from `RECEIVED` to `DISPUTED` and sets `dispute_reason` to that same outcome value."
    PRD §3.7: "The `entitled_discount_pct` — the discount the institution is actually entitled to — depends on the route: when the determination's route is `TA_FULL` or `TA_CAPPED`, it is that determination's `discount_pct_applied`, because the agreement fixes the discount; when the route is `FUND_APC` or `AUTHOR_PAYS`, there is no agreement and the entitlement comes instead from the publisher's volume tier described below."
    Design: Corner/calculations/corner_variance_tolerance_boundary_at_exactly_one_hundred_cents
    """
    scenario = _setup_hybrid_agreement_at_twenty_percent("2026-08-12T00:00:00Z")
    author = _register_faculty_author()

    on_boundary_article = record_article(
        scenario["journal"]["id"],
        author["id"],
        manuscript_title="Variance exactly at the tolerance",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(
        on_boundary_article["id"], author["id"], basis="PROVISIONAL"
    )
    assert determination["route"] == "TA_FULL", (
        f"FULL_APC coverage routes to TA_FULL, got {determination['route']!r}"
    )

    over_boundary_article = record_article(
        scenario["journal"]["id"],
        author["id"],
        manuscript_title="Variance one cent past the tolerance",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(over_boundary_article["id"], author["id"], basis="PROVISIONAL")

    on_boundary_invoice = receive_invoice(
        scenario["publisher"]["id"],
        on_boundary_article["id"],
        "MERID-9101",
        322340,
        0.20,
        0.06,
        "2026-08-12",
    )
    over_boundary_invoice = receive_invoice(
        scenario["publisher"]["id"],
        over_boundary_article["id"],
        "MERID-9102",
        322341,
        0.20,
        0.06,
        "2026-08-12",
    )

    accepted = validate_success(
        api.validate_publisher_invoice(on_boundary_invoice["id"], librarian_headers)
    )
    disputed = validate_success(
        api.validate_publisher_invoice(over_boundary_invoice["id"], librarian_headers)
    )

    assert accepted["net_cents"] == 304000, (
        "380000 times one minus the entitled 0.20 is 304000, got "
        f"{accepted['net_cents']}"
    )
    assert accepted["vat_cents"] == 18240, (
        "0.06 of the already-rounded 304000 is 18240, got " f"{accepted['vat_cents']}"
    )
    assert accepted["expected_amount_cents"] == 322240, (
        "304000 plus 18240 with no further rounding is 322240, got "
        f"{accepted['expected_amount_cents']}"
    )
    assert accepted["variance_cents"] == 100, (
        f"322340 less 322240 is exactly 100, got {accepted['variance_cents']}"
    )
    assert accepted["validation_outcome"] == "WITHIN_TOLERANCE", (
        "a variance of no more than one hundred cents is WITHIN_TOLERANCE, got "
        f"{accepted['validation_outcome']!r}"
    )
    assert accepted["status"] == "VALIDATED", (
        f"WITHIN_TOLERANCE moves the invoice to VALIDATED, got {accepted['status']!r}"
    )
    assert accepted.get("dispute_reason") is None, (
        f"a validated invoice records no dispute, got {accepted.get('dispute_reason')!r}"
    )

    assert disputed["expected_amount_cents"] == 322240, (
        "the second invoice prices identically, got "
        f"{disputed['expected_amount_cents']}"
    )
    assert disputed["variance_cents"] == 101, (
        f"322341 less 322240 is 101, got {disputed['variance_cents']}"
    )
    assert disputed["validation_outcome"] == "AMOUNT_VARIANCE", (
        "one cent past the tolerance is AMOUNT_VARIANCE, got "
        f"{disputed['validation_outcome']!r}"
    )
    assert disputed["status"] == "DISPUTED", (
        f"AMOUNT_VARIANCE moves the invoice to DISPUTED, got {disputed['status']!r}"
    )
    assert disputed["dispute_reason"] == "AMOUNT_VARIANCE", (
        "dispute_reason carries the outcome value, got "
        f"{disputed['dispute_reason']!r}"
    )


# --------------------------------------------------------------------------- #
# mandate exemption
# --------------------------------------------------------------------------- #
def test_articles_outside_a_mandate_are_exempt_and_survive_a_later_sweep(
    api, librarian_headers
):
    """No grant, or a grant whose funder mandates nothing, means EXEMPT and no sweep effect.

    PRD §3.8: "If the article names no grant, or if the grant's funder has a `mandate_type` of `NONE`, the article is `EXEMPT` outright with no `deposit_deadline_on` and no `embargo_until`; an exempt article never enters the sweep and counts as satisfying its grant for roll-up purposes."
    PRD §3.4: "It qualifies when, and only when, all four of these hold: the article names a grant; that grant's `status` is `ACTIVE`; the grant's funder has a `mandate_type` of either `GOLD_OA` or `IMMEDIATE_CC_BY`; the funder's `apc_allowable` is true; and the journal's `oa_model` is `FULLY_OA`."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.9: "Phase one expires agreements: every transformative agreement in `DRAFT`, `ACTIVE` or `EXHAUSTED` whose `effective_until` is on or before the clock date moves to `EXPIRED`, with the publisher's `active_agreement_count` recomputed and the publisher's `version` incremented for those that were `ACTIVE`."
    PRD §3.9: "Phase two closes grants: every `ACTIVE` grant whose `award_until` is strictly before the clock date moves to `CLOSED`."
    PRD §3.9: "Phase three catches missed deposit deadlines: every article whose `compliance_status` is still `PENDING_DEPOSIT` and whose `deposit_deadline_on` is strictly before the clock date moves to `NON_COMPLIANT`, and the owning grant's `mandate_status` moves to `BREACHED`."
    PRD §3.9: "Phase four releases elapsed embargoes: every article whose `compliance_status` is `EMBARGOED` and whose `embargo_until` is on or before the clock date moves to `COMPLIANT`, with the grant's `compliant_output_count` and `mandate_status` recomputed."
    PRD §3.9: "Its response carries `swept_at_utc` as the logical-clock instant of the run, `agreements_expired_count`, `grants_closed_count`, `articles_marked_non_compliant_count` and `articles_promoted_compliant_count`, each being the number of rows the corresponding phase actually changed."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "Otherwise, if the grant has at least one article and every one of them is `COMPLIANT` or `EXEMPT`, the `mandate_status` is `SATISFIED`."
    Design: Corner/calculations/corner_articles_outside_a_mandate_are_exempt_and_never_swept
    """
    set_clock("2026-08-10T00:00:00Z")
    base = setup_publisher_with_journal(
        publisher_code="HALDEN",
        publisher_name="Halden Open Science",
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = _register_faculty_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
    )
    funder = register_funder(
        name="Unconditional Legacy Trust",
        funder_code="ULT",
        mandate_type="NONE",
        max_embargo_months=12,
        deposit_deadline_days=90,
        license_required="ANY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="ULT-2026-77",
        award_from="2026-01-01",
        award_until="2027-12-31",
    )

    grantless_article = record_article(
        base["journal"]["id"],
        author["id"],
        manuscript_title="No grant at all",
        accepted_on="2026-08-05",
    )
    assert grantless_article["compliance_status"] == "EXEMPT", (
        "an article naming no grant is EXEMPT outright, got "
        f"{grantless_article['compliance_status']!r}"
    )
    assert grantless_article.get("deposit_deadline_on") is None, (
        "an exempt article carries no deposit deadline, got "
        f"{grantless_article.get('deposit_deadline_on')!r}"
    )
    assert grantless_article.get("embargo_until") is None, (
        "an exempt article carries no embargo, got "
        f"{grantless_article.get('embargo_until')!r}"
    )

    unmandated_article = record_article(
        base["journal"]["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Grant without a mandate",
        accepted_on="2026-08-05",
    )
    assert unmandated_article["compliance_status"] == "EXEMPT", (
        "a grant whose funder mandates NONE leaves the article EXEMPT, got "
        f"{unmandated_article['compliance_status']!r}"
    )
    assert unmandated_article.get("deposit_deadline_on") is None, (
        "an exempt article carries no deposit deadline, got "
        f"{unmandated_article.get('deposit_deadline_on')!r}"
    )

    determination = run_eligibility_check(
        unmandated_article["id"], author["id"], basis="PROVISIONAL"
    )
    assert determination["route"] == "AUTHOR_PAYS", (
        "a NONE mandate is neither GOLD_OA nor IMMEDIATE_CC_BY, so the fund route is "
        f"not available, got {determination['route']!r}"
    )
    assert determination["determination_reason"] == "NO_COVERAGE_AUTHOR_PAYS", (
        f"the pinned reason is NO_COVERAGE_AUTHOR_PAYS, got "
        f"{determination['determination_reason']!r}"
    )
    assert determination["eligible_request_cents"] == 0, (
        "an author-pays article may request no subsidy, got "
        f"{determination['eligible_request_cents']}"
    )

    set_clock("2027-06-01T00:00:00Z")
    sweep = validate_success(api.create_compliance_sweep(librarian_headers))

    assert sweep["articles_marked_non_compliant_count"] == 0, (
        "an exempt article never enters the sweep, got "
        f"{sweep['articles_marked_non_compliant_count']}"
    )
    assert sweep["articles_promoted_compliant_count"] == 0, (
        "no article sits in EMBARGOED, got "
        f"{sweep['articles_promoted_compliant_count']}"
    )
    assert sweep["grants_closed_count"] == 0, (
        "the award runs to 2027-12-31, which is not strictly before the clock date, "
        f"got {sweep['grants_closed_count']}"
    )
    assert sweep["agreements_expired_count"] == 0, (
        f"no agreement exists, got {sweep['agreements_expired_count']}"
    )
    assert sweep["swept_at_utc"].startswith("2027-06-01T00:00:00"), (
        f"swept_at_utc is the logical-clock instant of the run, got "
        f"{sweep['swept_at_utc']!r}"
    )

    assert read_article(grantless_article["id"])["compliance_status"] == "EXEMPT", (
        "the grantless article is still EXEMPT after the sweep"
    )
    assert read_article(unmandated_article["id"])["compliance_status"] == "EXEMPT", (
        "the unmandated article is still EXEMPT after the sweep"
    )

    grant_after = read_grant(grant["id"])
    assert grant_after["status"] == "ACTIVE", (
        f"the award has not run out, got {grant_after['status']!r}"
    )
    assert grant_after["output_count"] == 1, (
        f"one article references the grant, got {grant_after['output_count']}"
    )
    assert grant_after["compliant_output_count"] == 1, (
        f"an EXEMPT article counts towards the roll-up, got "
        f"{grant_after['compliant_output_count']}"
    )
    assert grant_after["mandate_status"] == "SATISFIED", (
        "every article of the grant is EXEMPT, got "
        f"{grant_after['mandate_status']!r}"
    )
