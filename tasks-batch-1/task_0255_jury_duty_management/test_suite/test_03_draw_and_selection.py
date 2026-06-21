"""Drawing jurors: pool-cardinality boundary, dedupe exclusion, system fields,
and the service-term optimistic-concurrency check.

Translates difficulty-design `boundary_precision_check / pool_exhausted_empty_set_boundary`
(queue A) and corner-design instances from §1.9 sections `validations`, `entities`,
and `errors` (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    draw_payload,
    TEST_USERS,
    setup_open_term_with_qualified_jurors, get_term, draw,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]


def test_draw_exactly_one_from_single_juror_pool_succeeds(api):
    """PRD §3.2: "If the eligible pool holds fewer than `count` jurors, the draw is
    rejected with `ERR_POOL_EXHAUSTED` (HTTP 409) and no summons is created."
    PRD §3.2: "one summons in `SUMMONED` status is created for each drawn juror."

    Design: Difficulty/boundary_precision_check/pool_exhausted_empty_set_boundary
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "TH"}
    )
    # eligible_pool_size (1) >= count (1): the boundary at equality succeeds.
    resp = api.draw(term["id"], draw_payload(1, open_v), _ADMIN)
    data = validate_success(resp, 201)
    assert len(data) == 1, f"drawing count 1 from a 1-juror pool must yield 1 summons, got {len(data)}"
    assert data[0]["status"] == "SUMMONED"


def test_draw_two_from_single_juror_pool_exhausted(api):
    """PRD §3.2: "If the eligible pool holds fewer than `count` jurors, the draw is
    rejected with `ERR_POOL_EXHAUSTED` (HTTP 409) and no summons is created."

    Design: Difficulty/boundary_precision_check/pool_exhausted_empty_set_boundary
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "TH2"}
    )
    # eligible_pool_size (1) < count (2): just past the boundary, rejected.
    resp = api.draw(term["id"], draw_payload(2, open_v), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_POOL_EXHAUSTED.value)
    assert get_term(term["id"])["summoned_count"] == 0, "no summons may be created on a short pool"


def test_already_summoned_juror_excluded_from_redraw(api):
    """PRD §3.2: "The eligible set comprises jurors of the term whose
    `qualification_status` is `QUALIFIED`, whose `disqualified` flag is false, and
    who do not already hold a non-cancelled summons in this term."
    PRD §3.2: "If the eligible pool holds fewer than `count` jurors, the draw is
    rejected with `ERR_POOL_EXHAUSTED` (HTTP 409) and no summons is created."

    Design: Corner/validations/duplicate_summons_in_draw_excluded
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "V3"}
    )
    draw(term["id"], open_v, count=1)
    v_after = get_term(term["id"])["version"]
    # The only juror now holds a non-cancelled summons → excluded → empty pool.
    resp = api.draw(term["id"], draw_payload(1, v_after), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_POOL_EXHAUSTED.value)


def test_drawn_summons_has_server_minted_fields(api):
    """PRD §3.2: "one summons in `SUMMONED` status is created for each drawn juror."
    PRD §3.2: "Each new summons records its `service_term_id`, the `juror_id` of the
    drawn juror, and a `badge_number` — a monotone per-term sequence minted at
    issuance that serves as the stable check-in ordering handle."

    Design: Corner/entities/system_fields_input_ignored_on_summons
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "C6"}
    )
    resp = api.draw(term["id"], draw_payload(1, open_v), _ADMIN)
    data = validate_success(resp, 201)
    summons = data[0]
    assert summons["status"] == "SUMMONED"
    assert isinstance(summons["badge_number"], int) and summons["badge_number"] >= 1, (
        f"badge_number must be a server-assigned integer >= 1, got {summons['badge_number']!r}"
    )


def test_stale_term_version_on_second_draw_rejected(api):
    """PRD §2.6: "A draw consumes qualified jurors from the shared pool and
    increments the term's `version` by one; therefore, if
    `expected_service_term_version` does not equal the term's current `version`,
    the draw is rejected with `ERR_STALE_TERM_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_term_version_on_second_draw
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=2, term_overrides={"name": "ER3"}
    )
    draw(term["id"], open_v, count=1)  # consumes one juror, bumps version
    # Second draw carries the pre-first-draw version → stale.
    resp = api.draw(term["id"], draw_payload(1, open_v), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_TERM_VERSION.value)
    assert get_term(term["id"])["summoned_count"] == 1, "no second summons may be created"
