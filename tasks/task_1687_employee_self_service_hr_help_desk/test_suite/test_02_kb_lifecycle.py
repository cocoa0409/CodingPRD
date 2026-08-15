"""Knowledge base lifecycle (PRD §3.3, §3.4, §3.6): authorship, review loop,
publish segregation of duties, revision chains, view telemetry, employee
search scoping, and deflection metrics."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_employee_headers,
    make_helpdesk_agent_headers,
    assert_kb_article,
    assert_instant_equals,
    make_team,
    make_category,
    make_sla_policy,
    make_employee,
    make_agent,
    author_article,
    submit_review,
    publish_article,
    make_published_article,
    record_article_view,
    create_ticket_for,
    set_clock_to,
)

ADMIN = TEST_USERS["admin_headers"]
KM1 = TEST_USERS["km1_headers"]
KM2 = TEST_USERS["km2_headers"]


def _kb_category():
    team = make_team("KB Team")
    category = make_category(team["id"])
    return team, category


def test_kb_author_cannot_publish_and_rework_loop(api):
    """PRD §3.3: "Publishing is restricted to a `KnowledgeManager` who is not the
    author: the author attempting to publish their own article is rejected with
    `ERR_AUTHOR_CANNOT_PUBLISH`."
    PRD §3.3: "A `KnowledgeManager` may return an in-review article to `DRAFT` for
    rework, optionally attaching a `note`."
    PRD §3.3: "A successful publish stamps `published_at` and `published_by_user_id`."

    Design: Corner/state_machines/kb_author_cannot_publish_and_rework_loop
    """
    _team, category = _kb_category()
    article = author_article(category["id"], KM1, title="SoD Doc")
    article = submit_review(article["id"], KM1)
    assert article["status"] == "IN_REVIEW"

    resp = api.publish_kb_article(article["id"], KM1)
    validate_error(resp, ApiErrorId.ERR_AUTHOR_CANNOT_PUBLISH.value)

    # Rework loop: IN_REVIEW -> DRAFT -> IN_REVIEW -> PUBLISHED.
    reworked = validate_success(
        api.return_article_draft(article["id"], {"note": "needs work"}, KM2)
    )
    assert reworked["status"] == "DRAFT"
    submit_review(article["id"], KM1)
    published = publish_article(article["id"], KM2)
    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == "km-2"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00Z")


def test_archive_draft_rejected(api):
    """PRD §3.3: "Finally, a `KnowledgeManager` may archive a published article,
    moving `PUBLISHED` to `ARCHIVED` and removing it from employee-visible search
    results."
    PRD §2.10: "The target entity must sit in a from-state of the requested
    transition. Failures: `ERR_TICKET_INVALID_STATE`, `ERR_DCR_INVALID_STATE`,
    `ERR_ARTICLE_INVALID_STATE`, `ERR_SURVEY_INVALID_STATE`,
    `ERR_WINDOW_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, or
    `ERR_EMPLOYEE_INVALID_STATE` (all 409)."

    Design: Corner/state_machines/archive_draft_rejected
    """
    _team, category = _kb_category()
    article = author_article(category["id"], KM1, title="Draft Doc")
    assert article["status"] == "DRAFT"

    resp = api.archive_kb_article(article["id"], KM1)
    validate_error(resp, ApiErrorId.ERR_ARTICLE_INVALID_STATE.value)

    data = validate_success(api.get_kb_article(article["id"], KM1))
    assert data["status"] == "DRAFT", "article must remain DRAFT after a rejected archive"


def test_article_view_increments_view_count(api):
    """PRD §3.3: "Two computed counters track each article's performance:
    `view_count`, the number of recorded article views, and
    `deflection_fail_count`, the number of those views whose `deflection_outcome` is
    `TICKET_CREATED` (§3.4)."
    PRD §3.4: "Article views are append-only telemetry, and the article's
    `view_count` is recomputed as views accumulate."

    Design: Corner/entities/article_view_increments_view_count
    """
    _team, category = _kb_category()
    article = make_published_article(category["id"], title="View Me")
    employee = make_employee()

    record_article_view(article["id"], employee["id"])
    record_article_view(article["id"], employee["id"])

    data = validate_success(api.get_kb_article(article["id"], KM1))
    assert_kb_article(data)
    assert data["view_count"] == 2, f"expected view_count 2, got {data['view_count']}"
    assert data["deflection_fail_count"] == 0


def test_kb_search_employee_sees_published_only(api):
    """PRD §3.3: "The article list accepts a query string `q`, matched as a
    case-insensitive substring over `title` and `keywords`, plus the filters
    `category_id`, `status`, and `supersedes_article_id`."
    PRD §3.3: "Callers in the `Employee` role see `PUBLISHED` articles only, and an
    employee asking directly for a non-published article receives
    `ERR_ARTICLE_NOT_FOUND`, indistinguishable from absence."

    Design: Corner/endpoints/kb_search_employee_sees_published_only
    """
    _team, category = _kb_category()
    published = make_published_article(category["id"], title="Password Reset")
    draft = author_article(category["id"], KM1, title="Password Policy Internal")
    employee = make_employee()
    emp_headers = make_employee_headers(employee["id"])

    data, meta = validate_paginated(api.list_kb_articles(emp_headers, params={"q": "Password"}))
    assert meta["total_count"] == 1, f"employee search must see only PUBLISHED, got {meta['total_count']}"
    assert data[0]["id"] == published["id"]

    resp = api.get_kb_article(draft["id"], emp_headers)
    validate_error(resp, ApiErrorId.ERR_ARTICLE_NOT_FOUND.value)

    data_km, meta_km = validate_paginated(api.list_kb_articles(KM1, params={"q": "Password"}))
    assert meta_km["total_count"] == 2, f"KnowledgeManager must see both, got {meta_km['total_count']}"


def test_publishing_revision_supersedes_previous_head(api):
    """PRD §3.3: "When the article is a revision, publishing has an atomic extra
    step: the article named by `supersedes_article_id` must currently be `PUBLISHED`
    — if the chain head has moved on, the publish fails with
    `ERR_ARTICLE_INVALID_STATE` — and on success the referenced article flips from
    `PUBLISHED` to `SUPERSEDED` in the same transaction, so each revision chain
    conserves exactly one published head; both articles' versions increment."

    Design: Difficulty/compensating_invariant/kb_chain_single_published_head_conserved
    """
    _team, category = _kb_category()
    art_a = make_published_article(category["id"], title="VPN Setup v1")
    assert art_a["status"] == "PUBLISHED"

    art_b = author_article(category["id"], KM1, title="VPN Setup v2",
                           supersedes_article_id=art_a["id"])
    submit_review(art_b["id"], KM1)
    published_b = publish_article(art_b["id"], KM2)
    assert published_b["status"] == "PUBLISHED"

    art_a_after = validate_success(api.get_kb_article(art_a["id"], KM1))
    assert art_a_after["status"] == "SUPERSEDED", (
        "the compensating supersede transition must fire with the revision's publish"
    )


def test_revision_chain_conserves_single_published_head(api):
    """PRD §3.3: "When the article is a revision, publishing has an atomic extra
    step: the article named by `supersedes_article_id` must currently be `PUBLISHED`
    — if the chain head has moved on, the publish fails with
    `ERR_ARTICLE_INVALID_STATE` — and on success the referenced article flips from
    `PUBLISHED` to `SUPERSEDED` in the same transaction, so each revision chain
    conserves exactly one published head; both articles' versions increment."

    Design: Difficulty/compensating_invariant/kb_chain_single_published_head_conserved
    """
    _team, category = _kb_category()
    art_a = make_published_article(category["id"], title="VPN Setup v1")
    art_b = author_article(category["id"], KM1, title="VPN Setup v2",
                           supersedes_article_id=art_a["id"])
    submit_review(art_b["id"], KM1)
    publish_article(art_b["id"], KM2)

    data, meta = validate_paginated(
        api.list_kb_articles(KM1, params={"category_id": category["id"], "status": "PUBLISHED"})
    )
    assert meta["total_count"] == 1, (
        f"exactly one PUBLISHED head per revision chain, got {meta['total_count']}"
    )
    assert data[0]["id"] == art_b["id"]


def test_helpdesk_agent_cannot_publish(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint, or who
    violates a record-level ownership scope, is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §3.3: "Publishing is restricted to a `KnowledgeManager` who is not the
    author: the author attempting to publish their own article is rejected with
    `ERR_AUTHOR_CANNOT_PUBLISH`."

    Design: Corner/rbac/helpdesk_agent_cannot_publish
    """
    team = make_team("RB Team")
    agent = make_agent(team["id"], tier="T1")
    category = make_category(team["id"])
    agent_headers = make_helpdesk_agent_headers(agent["id"])
    article = author_article(category["id"], agent_headers, title="Agent Doc")
    article = submit_review(article["id"], agent_headers)
    assert article["status"] == "IN_REVIEW"

    resp = api.publish_kb_article(article["id"], agent_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    data = validate_success(api.get_kb_article(article["id"], KM1))
    assert data["status"] == "IN_REVIEW", "article must remain IN_REVIEW after a rejected publish"


def test_deflection_rate_two_thirds(api):
    """PRD §3.4: "If candidates exist, the one with the latest `viewed_at` is chosen
    — ties broken by the later view `created_at` — and is consumed: the ticket's
    `source_article_id` is set to that article, and the view's `deflection_outcome`
    flips to `TICKET_CREATED`, feeding both the article's `deflection_fail_count` and
    the deflection-rate metric of §3.6."
    PRD §3.6: "The deflection metric for a `category_id` considers article views of
    that category's articles whose `viewed_at` falls inside the trailing thirty days,
    both ends inclusive: it reports the category, the `window_days`, the total
    `view_count`, the `ticket_created_count` of views whose `deflection_outcome` is
    `TICKET_CREATED`, and the `deflection_rate` — one minus the ratio of
    ticket-creating views to all views, rounded half-up to four decimal places, and
    exactly 0.0 when there are no views at all."

    Design: Corner/calculations/deflection_rate_two_thirds
    """
    team = make_team("DEFL Team")
    category = make_category(team["id"])
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    article = make_published_article(category["id"], title="Deflect Me")
    e1 = make_employee(employee_number="E202", full_name="D One", email="d1@x.com")
    e2 = make_employee(employee_number="E203", full_name="D Two", email="d2@x.com")
    e3 = make_employee(employee_number="E204", full_name="D Three", email="d3@x.com")
    for emp in (e1, e2, e3):
        record_article_view(article["id"], emp["id"])

    set_clock_to("2026-08-01T00:30:00Z")
    ticket = create_ticket_for(e1["id"], category["id"], subject="still stuck")

    assert ticket["source_article_id"] == article["id"], (
        "the ticket must link the recent same-category view"
    )

    metrics = validate_success(
        api.get_deflection_metrics(ADMIN, params={"category_id": category["id"]})
    )
    assert metrics["view_count"] == 3
    assert metrics["ticket_created_count"] == 1
    assert metrics["deflection_rate"] == pytest.approx(0.6667, abs=1e-6), (
        f"1 - 1/3 rounds half-up to 0.6667 at 4dp, got {metrics['deflection_rate']}"
    )


def test_deflection_window_sixty_minutes_boundary(api):
    """PRD §3.4: "The server scans the caller's recent article views for candidates:
    views by the same employee, of articles in the ticket's category, viewed no
    earlier than sixty minutes before ticket creation (the boundary included), whose
    `deflection_outcome` is still `NONE`."

    Design: Corner/calculations/deflection_window_60min_boundary
    """
    team = make_team("DW Team")
    category = make_category(team["id"])
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    article = make_published_article(category["id"], title="Win Doc")
    e1 = make_employee(employee_number="E205", full_name="W One", email="w1@x.com")
    e2 = make_employee(employee_number="E206", full_name="W Two", email="w2@x.com")
    v1 = record_article_view(article["id"], e1["id"])
    v2 = record_article_view(article["id"], e2["id"])

    # Exactly sixty minutes after the views: the boundary is included.
    set_clock_to("2026-08-01T01:00:00Z")
    t1 = create_ticket_for(e1["id"], category["id"], subject="t1")
    # Sixty-one minutes after the view: outside the window.
    set_clock_to("2026-08-01T01:01:00Z")
    t2 = create_ticket_for(e2["id"], category["id"], subject="t2")

    assert t1["source_article_id"] == article["id"], "60 minutes exactly: inclusive boundary, must link"
    assert t2["source_article_id"] is None, "61 minutes: outside the deflection window"

    views, _meta = validate_paginated(
        api.list_article_views(ADMIN, params={"article_id": article["id"]})
    )
    by_id = {v["id"]: v for v in views}
    assert by_id[v1["id"]]["deflection_outcome"] == "TICKET_CREATED"
    assert by_id[v2["id"]]["deflection_outcome"] == "NONE"
