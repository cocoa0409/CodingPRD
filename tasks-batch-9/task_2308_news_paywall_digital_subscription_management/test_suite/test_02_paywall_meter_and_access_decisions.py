"""Rule selection, the effective allowance, and the meter's inclusive boundary."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_article,
    create_paywall_rule,
    create_registered_reader,
    decide_access,
    make_reader_headers,
    read_reader,
    set_clock_date,
    validate_paginated,
)


def _arrange_high_propensity_reader_under_an_override_of_one():
    """A three-axis rule with an allowance override of 1 facing a HIGH reader."""
    set_clock_date("2026-09-01")
    rule = create_paywall_rule(
        name="Business news, high propensity",
        action="METER",
        priority=10,
        content_type_match="NEWS",
        section_match="business",
        propensity_band_match="HIGH",
        meter_allowance_override=1,
        status="ACTIVE",
    )
    first = create_article(
        headline="Markets open higher",
        content_type="NEWS",
        section="business",
        access_class="METERED",
    )
    second = create_article(
        headline="Bond yields slip",
        content_type="NEWS",
        section="business",
        access_class="METERED",
    )
    reader = create_registered_reader("reader3@mail.test", propensity_band="HIGH")
    return {
        "rule": rule,
        "first": first,
        "second": second,
        "reader": reader,
        "reader_headers": make_reader_headers(reader["id"]),
    }


def test_three_axis_rule_scores_full_specificity_and_grants_the_first_metered_read():
    """A rule matching all three axes scores 111 and supplies the allowance base.

    PRD: "It is the sum of three contributions: one hundred if `content_type_match` is anything other than `ANY`, ten if `section_match` is anything other than `ANY`, and one if `propensity_band_match` is anything other than `ANY`."
    PRD: "The first candidate under that ordering is selected: its `action` becomes the gate, its `meter_allowance_override` (or the site default of four when the override is null) becomes the allowance base, and its identifier is recorded as `applied_rule_id`."
    PRD: "Take the allowance base from rule selection and adjust it by the reader's propensity band: a `HIGH`-propensity reader loses two articles from the allowance, a `MEDIUM`-propensity reader is unchanged, and a `LOW`-propensity reader gains two."
    PRD: "The result is then floored at one — the effective allowance is the greater of one and the adjusted base — so no combination of a zero override and a `HIGH` band can ever produce a zero or negative allowance."

    Design: Difficulty/combinatorial_formula/effective_allowance_from_override_band_and_floor
    """
    state = _arrange_high_propensity_reader_under_an_override_of_one()
    assert state["rule"]["specificity_score"] == 111

    event = decide_access(
        state["reader"]["id"], state["first"]["id"], state["reader_headers"]
    )

    assert event["decision"] == "GRANTED_METERED"
    assert event["effective_allowance"] == 1
    assert event["meter_index"] == 1
    assert event["applied_rule_id"] == state["rule"]["id"]
    assert event["event_type"] == "ARTICLE_VIEW_GRANTED"


def test_second_metered_read_is_blocked_at_the_floored_allowance_of_one():
    """One granted article exhausts a floored allowance of one, so the next is blocked.

    PRD: "Finally the allowance boundary is applied: if `metered_distinct_article_count` is greater than or equal to the effective allowance, the verdict is `BLOCKED_METER`; otherwise the article's identifier is appended to `metered_article_ids`, the counter is updated to the new length, and the verdict is `GRANTED_METERED` with `meter_index` set to that new length."
    PRD: "Granted events recompute the reader's `engagement_score` and re-derive their `churn_risk_band`; blocked events carry a `weight` of 0 and leave the score exactly where it was."

    Design: Difficulty/combinatorial_formula/effective_allowance_from_override_band_and_floor
    """
    state = _arrange_high_propensity_reader_under_an_override_of_one()
    decide_access(state["reader"]["id"], state["first"]["id"], state["reader_headers"])

    blocked = decide_access(
        state["reader"]["id"], state["second"]["id"], state["reader_headers"]
    )

    assert blocked["decision"] == "BLOCKED_METER"
    assert blocked["effective_allowance"] == 1
    assert blocked["event_type"] == "ARTICLE_VIEW_BLOCKED"
    assert blocked["weight"] == 0
    assert read_reader(state["reader"]["id"])["metered_distinct_article_count"] == 1


def _arrange_site_default_meter_with_three_articles_already_read():
    """No rules at all, a MEDIUM reader, and three of five articles already spent."""
    set_clock_date("2026-09-01")
    reader = create_registered_reader("meter@mail.test", propensity_band="MEDIUM")
    headers = make_reader_headers(reader["id"])
    articles = [
        create_article(
            headline=f"Article A{index}",
            content_type="NEWS",
            section="news",
            access_class="METERED",
            published_at="2026-08-15T00:00:00Z",
        )
        for index in range(1, 6)
    ]
    for article in articles[:3]:
        decide_access(reader["id"], article["id"], headers)
    return {"reader": reader, "reader_headers": headers, "articles": articles}


def test_fourth_distinct_article_is_granted_and_the_fifth_is_blocked_by_the_meter():
    """With the site default of four, the fourth grant is the last one.

    PRD: "When the candidate pool is empty, that is **not** an error: the gate falls back to `METER`, the allowance base falls back to the site default of four, and `applied_rule_id` is left null."
    PRD: "The comparison is inclusive on the counter side, which means an allowance of four grants exactly four distinct articles and blocks the fifth."

    Design: Difficulty/boundary_precision_check/meter_allowance_boundary_grants_exactly_four_distinct_articles
    """
    state = _arrange_site_default_meter_with_three_articles_already_read()

    fourth = decide_access(
        state["reader"]["id"], state["articles"][3]["id"], state["reader_headers"]
    )
    fifth = decide_access(
        state["reader"]["id"], state["articles"][4]["id"], state["reader_headers"]
    )

    assert fourth["decision"] == "GRANTED_METERED"
    assert fourth["meter_index"] == 4
    assert fourth["effective_allowance"] == 4
    assert fourth["event_type"] == "ARTICLE_VIEW_GRANTED"
    assert fourth["weight"] == 3
    assert fifth["decision"] == "BLOCKED_METER"
    assert fifth["event_type"] == "ARTICLE_VIEW_BLOCKED"
    assert fifth["weight"] == 0
    assert fifth["effective_allowance"] == 4


def test_re_reading_the_first_article_is_free_and_does_not_move_the_meter_counter():
    """A re-read returns the article's existing one-based position and spends nothing.

    PRD: "Then re-reads are honoured for free, because the meter counts **distinct** articles: if the article's identifier is already inside `metered_article_ids`, the verdict is `GRANTED_METERED` with `meter_index` set to that article's existing one-based position in the list, and the counter is not incremented."
    PRD: "Every access decision appends exactly one reader event."

    Design: Difficulty/boundary_precision_check/meter_allowance_boundary_grants_exactly_four_distinct_articles
    """
    state = _arrange_site_default_meter_with_three_articles_already_read()
    decide_access(
        state["reader"]["id"], state["articles"][3]["id"], state["reader_headers"]
    )
    decide_access(
        state["reader"]["id"], state["articles"][4]["id"], state["reader_headers"]
    )

    repeat = decide_access(
        state["reader"]["id"], state["articles"][0]["id"], state["reader_headers"]
    )

    assert repeat["decision"] == "GRANTED_METERED"
    assert repeat["meter_index"] == 1
    reader = read_reader(state["reader"]["id"])
    assert reader["metered_distinct_article_count"] == 4
    assert reader["meter_period_started_on"] == "2026-09-01"
    rows, meta = validate_paginated(
        api_client.list_reader_events(
            OPS_AGENT_HEADERS, {"reader_id": state["reader"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 6
    assert len(rows) == 6


def test_five_granted_views_and_one_block_score_fifteen_and_band_the_reader_medium():
    """Five grants at weight 3 total 15.00, and 15.00 sits in the MEDIUM band.

    PRD: "The class weights are: a granted article view counts 3, a newsletter open counts 2, an app open counts 1, and a posted comment counts 5, while a blocked article view, an editorial intervention, a product intervention and a price-increase notice all count 0 — blocked paywall hits and outbound messages never move the score."
    PRD: "Absent that override, the band is read off the two-decimal `engagement_score` with strictly-less-than comparisons: below 5 is `SEVERE`, from 5 up to but not including 15 is `HIGH`, from 15 up to but not including 30 is `MEDIUM`, and 30 or above is `LOW`."

    Design: Difficulty/boundary_precision_check/meter_allowance_boundary_grants_exactly_four_distinct_articles
    """
    state = _arrange_site_default_meter_with_three_articles_already_read()
    decide_access(
        state["reader"]["id"], state["articles"][3]["id"], state["reader_headers"]
    )
    decide_access(
        state["reader"]["id"], state["articles"][4]["id"], state["reader_headers"]
    )
    decide_access(
        state["reader"]["id"], state["articles"][0]["id"], state["reader_headers"]
    )

    reader = read_reader(state["reader"]["id"])
    assert float(reader["engagement_score"]) == 15.00
    assert reader["churn_risk_band"] == "MEDIUM"
