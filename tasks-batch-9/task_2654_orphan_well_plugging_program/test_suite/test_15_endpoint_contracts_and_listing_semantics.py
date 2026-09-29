"""Endpoint contracts: what one call answers with, and what a list call promises."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_cents,
    assert_field_sequence,
    assert_fields,
    assert_id_set,
    assert_null_fields,
    assert_page,
    assert_score,
)

LOW_SCORE_WELL = dict(
    spud_year=1961,
    total_depth_ft=1200,
    casing_strings=1,
    methane_scfd=100,
    groundwater_depth_ft=600,
    population_within_1000ft=0,
    surface_disturbance_acres=0.5,
)
HIGH_SCORE_WELL = dict(
    spud_year=1982,
    total_depth_ft=9000,
    casing_strings=4,
    methane_scfd=500,
    groundwater_depth_ft=40,
    population_within_1000ft=25,
    surface_disturbance_acres=5.0,
)


def _paginated(response):
    """The rows and the four pagination fields every list response must carry."""
    rows, meta = validate_paginated(response)
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, "meta is missing the pagination field %s: %r" % (
            field,
            meta,
        )
    return rows, meta


def test_well_filters_intersect_and_the_score_filter_includes_its_edge(api):
    """Two filters on one call narrow to their intersection, not to their union.

    A minimum screening score of 59.90 keeps the well scoring exactly 59.90 and one
    hundredth more drops it; the same threshold combined with the second operator returns
    that operator's single well rather than every well at or above the score.

    PRD: "Wells can be listed with filters `operator_id`, `status`, `access_status` and
    `min_screening_score` (returning only wells whose screening score is at least the
    supplied value), plus `limit` and `offset`." ... "`total_count` (the number of rows
    matching the filter before the page window is applied)"

    Design: Corner/endpoints/well_list_filters_compose_conjunctively_and_the_score_filter_is_inclusive
    """
    first = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    second = fx.make_operator(
        api,
        name="Shoshone Shell Co",
        region_code="CO",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=250000,
    )
    low = fx.make_well(api, first["id"], **LOW_SCORE_WELL)
    mid = fx.make_well(api, first["id"])
    high = fx.make_well(api, first["id"], **HIGH_SCORE_WELL)
    other = fx.make_well(api, second["id"])

    assert_score(low["screening_score"], 11.50, "low screening_score")
    assert_score(mid["screening_score"], 59.90, "mid screening_score")
    assert_score(high["screening_score"], 100.00, "high screening_score")
    assert_score(other["screening_score"], 59.90, "other operator screening_score")

    by_operator = api.list_wells(users.ADMIN, {"operator_id": first["id"]})
    rows, meta = _paginated(by_operator)
    assert by_operator.status_code == 200, "the filtered list must answer HTTP 200"
    assert meta["total_count"] == 3, "expected three wells, got %r" % (meta,)
    assert meta["has_more"] is False, "three of three rows leaves nothing behind"
    assert_id_set(rows, [low["id"], mid["id"], high["id"]])
    assert other["id"] not in {row["id"] for row in rows}, (
        "the other operator's well must not appear under this operator's filter"
    )

    at_the_edge = assert_page(
        api.list_wells(
            users.ADMIN, {"operator_id": first["id"], "min_screening_score": 59.90}
        ),
        2,
        expected_total=2,
    )
    assert_id_set(at_the_edge, [mid["id"], high["id"]])

    above_the_edge = assert_page(
        api.list_wells(
            users.ADMIN, {"operator_id": first["id"], "min_screening_score": 59.91}
        ),
        1,
        expected_total=1,
    )
    assert_id_set(above_the_edge, [high["id"]])

    intersection = assert_page(
        api.list_wells(
            users.ADMIN, {"operator_id": second["id"], "min_screening_score": 59.90}
        ),
        1,
        expected_total=1,
    )
    assert_id_set(intersection, [other["id"]])

    empty = api.list_wells(users.ADMIN, {"status": "INACTIVE", "operator_id": first["id"]})
    assert empty.status_code == 200, "an empty result set is still HTTP 200"
    empty_rows, empty_meta = _paginated(empty)
    assert empty_rows == [], "expected an empty data array, got %r" % (empty_rows,)
    assert empty_meta["total_count"] == 0, "expected total_count 0, got %r" % (empty_meta,)


def test_well_pages_do_not_overlap_and_the_last_page_clears_has_more(api):
    """total_count counts the filtered set while has_more describes the page.

    Two rows of three carry has_more true, the remaining row carries false, an offset
    past the end is an empty page rather than a missing resource, and the two pages
    together hold each well exactly once.

    PRD: "Every list endpoint accepts two optional query parameters. `limit` controls
    page size: it defaults to 10, may not be smaller than 1, and may not be larger than
    100. `offset` controls the starting position: it defaults to 0 and may not be
    negative." ... "and `has_more` (true when rows remain beyond the current page)"

    Design: Corner/endpoints/well_list_pages_without_overlap_and_flags_has_more
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    first = fx.make_well(api, operator["id"], **LOW_SCORE_WELL)
    second = fx.make_well(api, operator["id"])
    third = fx.make_well(api, operator["id"], **HIGH_SCORE_WELL)
    every_id = [first["id"], second["id"], third["id"]]

    page_one = api.list_wells(
        users.ADMIN, {"operator_id": operator["id"], "limit": 2, "offset": 0}
    )
    rows_one, meta_one = _paginated(page_one)
    assert page_one.status_code == 200, "the first page must answer HTTP 200"
    assert len(rows_one) == 2, "expected two rows on the first page, got %d" % (
        len(rows_one),
    )
    assert meta_one["limit"] == 2, "expected the effective limit 2, got %r" % (meta_one,)
    assert meta_one["offset"] == 0, "expected the effective offset 0, got %r" % (meta_one,)
    assert meta_one["total_count"] == 3, "expected total_count 3, got %r" % (meta_one,)
    assert meta_one["has_more"] is True, "a row remains beyond the first page"

    page_two = api.list_wells(
        users.ADMIN, {"operator_id": operator["id"], "limit": 2, "offset": 2}
    )
    rows_two, meta_two = _paginated(page_two)
    assert len(rows_two) == 1, "expected one row on the second page, got %d" % (
        len(rows_two),
    )
    assert meta_two["limit"] == 2, "expected the effective limit 2, got %r" % (meta_two,)
    assert meta_two["offset"] == 2, "expected the effective offset 2, got %r" % (meta_two,)
    assert meta_two["total_count"] == 3, "expected total_count 3, got %r" % (meta_two,)
    assert meta_two["has_more"] is False, "nothing remains beyond the second page"

    past_the_end = api.list_wells(
        users.ADMIN, {"operator_id": operator["id"], "limit": 2, "offset": 3}
    )
    rows_past, meta_past = _paginated(past_the_end)
    assert past_the_end.status_code == 200, "an offset past the end is still HTTP 200"
    assert rows_past == [], "expected no rows past the end, got %r" % (rows_past,)
    assert meta_past["total_count"] == 3, "the filtered set is still three rows"
    assert meta_past["has_more"] is False, "there is nothing beyond an exhausted list"

    walked = [row["id"] for row in rows_one] + [row["id"] for row in rows_two]
    assert len(walked) == len(set(walked)), (
        "the two pages repeated a well: %r" % (walked,)
    )
    assert set(walked) == set(every_id), (
        "the two pages together must hold exactly the three wells, got %r" % (walked,)
    )

    defaulted = api.list_wells(users.ADMIN, {"operator_id": operator["id"]})
    rows_default, meta_default = _paginated(defaulted)
    assert len(rows_default) == 3, "the default page holds all three wells"
    assert meta_default["limit"] == 10, "expected the declared default limit 10, got %r" % (
        meta_default,
    )
    assert meta_default["offset"] == 0, "expected the declared default offset 0, got %r" % (
        meta_default,
    )


def test_a_wells_production_list_shows_only_its_own_months_in_month_order(api):
    """The nested collection is scoped by its path and ordered by month, not by insert.

    Three months appended 2026-03, 2026-01, 2026-02 read back in calendar order, the
    sibling well's single month never appears in the first well's list, and the two wells
    aggregate their barrels of oil equivalent independently.

    PRD: "Production records are append-only ledger lines and are listed for a well
    ordered by `month` ascending, with `limit` and `offset` for paging." ... "When the
    reported `month` is later than the value already stored, the well's
    `last_production_month` advances to it"

    Design: Corner/endpoints/nested_production_list_is_scoped_to_its_parent_and_ordered_by_month
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    first = fx.make_well(api, operator["id"])
    second = fx.make_well(api, operator["id"])

    fx.report_production(api, first["id"], "2026-03", oil_bbl=3.0)
    fx.report_production(api, first["id"], "2026-01", oil_bbl=1.0)
    fx.report_production(api, first["id"], "2026-02", oil_bbl=2.0)
    fx.report_production(api, second["id"], "2026-02", oil_bbl=99.0)

    own = api.list_production_records(first["id"], users.REVIEWER)
    assert own.status_code == 200, "the nested list must answer HTTP 200"
    rows = assert_page(own, 3, expected_total=3)
    assert_field_sequence(rows, "month", ["2026-01", "2026-02", "2026-03"])
    assert_field_sequence(rows, "oil_bbl", [1.0, 2.0, 3.0])
    for row in rows:
        assert_fields(row, well_id=first["id"])
    assert 99.0 not in [row["oil_bbl"] for row in rows], (
        "the sibling well's month leaked into this well's list: %r" % (rows,)
    )

    sibling = assert_page(
        api.list_production_records(second["id"], users.REVIEWER, {"limit": 5, "offset": 0}),
        1,
        expected_total=1,
    )
    assert_field_sequence(sibling, "month", ["2026-02"])
    assert_field_sequence(sibling, "oil_bbl", [99.0])
    assert_fields(sibling[0], well_id=second["id"])

    assert_score(
        fx.read_well(api, first["id"])["cumulative_boe_60mo"],
        6.00,
        "first well cumulative_boe_60mo",
    )
    assert_score(
        fx.read_well(api, second["id"])["cumulative_boe_60mo"],
        99.00,
        "second well cumulative_boe_60mo",
    )
    assert_fields(fx.read_well(api, first["id"]), last_production_month="2026-03")


def test_an_enforcement_call_answers_with_the_operator_and_makes_the_version_stale(api):
    """One action endpoint dispatches on its action and returns the whole operator.

    An undeclared action never reaches the state machine, the declared one answers 200
    with the modified operator rather than 201, and because that success bumps the
    version, the very same version number is stale on the next call.

    PRD: "Take an enforcement action against an operator: DECLARE_INSOLVENT, REVOKE, or
    FORFEIT_BOND." ... "endpoints that modify an existing resource, and all read
    endpoints, respond with HTTP 200" ... "A mismatch with the operator's current
    `version` is rejected with `ERR_STALE_OPERATOR_VERSION` (HTTP 412)."

    Design: Corner/endpoints/enforcement_action_endpoint_returns_the_updated_operator_and_bumps_version
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=400000,
    )
    assert_fields(operator, status="ACTIVE", version=1)
    assert_cents(operator["required_bond_cents"], 0, "required_bond_cents")

    undeclared = api.operator_enforcement(
        operator["id"],
        f.enforcement_payload("SUSPEND", 1, "licence suspension"),
        users.ADMIN,
    )
    validate_error(undeclared, e.ERR_INVALID_REQUEST, 422)
    untouched = fx.read_operator(api, operator["id"])
    assert_fields(untouched, status="ACTIVE", version=1)

    declared = validate_success(
        api.operator_enforcement(
            operator["id"],
            f.enforcement_payload("DECLARE_INSOLVENT", 1, "receiver appointed"),
            users.ADMIN,
        ),
        200,
    )
    assert_fields(
        declared,
        status="INSOLVENT",
        insolvency_declared_at="2026-08-01T00:00:00Z",
        version=2,
    )
    assert_cents(declared["bond_amount_cents"], 400000, "bond_amount_cents")
    assert_null_fields(declared, "bond_forfeited_at")

    stale = api.operator_enforcement(
        operator["id"],
        f.enforcement_payload("FORFEIT_BOND", 1, "bond called"),
        users.ADMIN,
    )
    validate_error(stale, e.ERR_STALE_OPERATOR_VERSION, 412)

    after = fx.read_operator(api, operator["id"])
    assert_fields(after, status="INSOLVENT", version=2)
    assert_cents(after["bond_amount_cents"], 400000, "bond_amount_cents after the refusal")
    assert_null_fields(after, "bond_forfeited_at")
    assert_page(
        api.list_funding_sources(users.FUNDING, {"kind": "FORFEITED_BOND"}),
        0,
        expected_total=0,
    )


def test_an_operator_read_reflects_its_wells_without_any_write_to_the_operator(api):
    """The operator's counters and requirement are derived from its inventory.

    Nothing is ever posted to the operator: its requirement of 500000 cents and its two
    well counts arrive from the wells alone, and confirming an orphan determination on one
    of those wells moves `orphan_candidate_count` from 0 to 1 while leaving the well count
    and the blanket requirement exactly where they were.

    PRD: "Those two counters are derived, never supplied: `active_well_count` is the number
    of wells whose `operator_id` is this operator and whose `status` is anything other than
    `PLUGGED` or `RECLAIMED`, while `orphan_candidate_count` is the narrower number of
    wells whose `operator_id` is this operator and whose `status` is `ORPHAN_CANDIDATE`,
    `ORPHAN_CONFIRMED` or `PLUGGING_SCHEDULED`." ... "Under the `BLANKET` variant the base
    amounts of all included wells are summed first"

    Design: Corner/endpoints/operator_read_recomputes_its_aggregates_with_no_write_to_the_operator
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=100000,
    )
    kept = fx.make_well(api, operator["id"])
    classified = fx.make_well(api, operator["id"])

    before = validate_success(api.get_operator(operator["id"], users.FUNDING), 200)
    assert_cents(before["required_bond_cents"], 500000, "required_bond_cents")
    assert_fields(before, active_well_count=2, orphan_candidate_count=0)
    assert_fields(before, status="DELINQUENT", financial_assurance_tier="BLANKET")
    assert_cents(before["bond_amount_cents"], 100000, "bond_amount_cents")

    determination = fx.open_determination(api, classified["id"])
    fx.submit_determination(api, determination["id"])
    fx.decide_determination(api, determination["id"], "CONFIRM")

    after = validate_success(api.get_operator(operator["id"], users.FUNDING), 200)
    assert_fields(after, orphan_candidate_count=1, active_well_count=2)
    assert_cents(
        after["required_bond_cents"],
        500000,
        "required_bond_cents after the confirmation",
    )
    assert_cents(after["bond_amount_cents"], 100000, "bond_amount_cents")

    assert_fields(fx.read_well(api, classified["id"]), status="ORPHAN_CONFIRMED")
    assert_fields(fx.read_well(api, kept["id"]), status="PRODUCING")


def test_agreement_and_denial_resolutions_write_different_pairs_of_states(api):
    """One resolution endpoint dispatches on its outcome and projects onto the well.

    The executed agreement and the denial each write their own row state and their own
    access dimension on the well, and the citation offered to the agreement branch is
    never stored, because only the entry order records the statute it relies on.

    PRD: "Executing the agreement - available only on a row whose `mode` is `AGREEMENT` -
    moves the row `REQUESTED → AGREEMENT_EXECUTED`, sets `resolved_at` to the logical
    clock, and mirrors the well to `ACCESS_PENDING → AGREEMENT_EXECUTED`." ... "Ordering
    entry - available only on a row whose `mode` is `STATUTORY_ENTRY` - moves the row
    `REQUESTED → ENTRY_ORDERED`, stores the supplied `legal_authority_citation`" ...
    "Denying the request moves the row `REQUESTED → DENIED`, sets `resolved_at`, and
    mirrors the well to `ACCESS_PENDING → ACCESS_DENIED`."

    Design: Corner/endpoints/access_resolution_dispatches_on_outcome_and_projects_onto_the_well
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    negotiated_well = fx.make_well(api, operator["id"])
    refused_well = fx.make_well(api, operator["id"])

    negotiated = fx.open_site_access(
        api,
        negotiated_well["id"],
        mode="AGREEMENT",
        surface_owner_name="Halvorsen Ranch",
        compensation_cents=150000,
    )
    refused = fx.open_site_access(
        api,
        refused_well["id"],
        mode="AGREEMENT",
        surface_owner_name="Bar T Grazing Assn",
    )
    assert_fields(
        negotiated,
        status="REQUESTED",
        waiting_period_days=0,
        window_end_at="2026-08-01T00:00:00Z",
    )
    assert_cents(negotiated["compensation_cents"], 150000, "compensation_cents")
    assert_cents(refused["compensation_cents"], 0, "defaulted compensation_cents")
    assert_null_fields(negotiated, "legal_authority_citation", "resolved_at")
    assert_fields(
        fx.read_well(api, negotiated_well["id"]),
        access_status="ACCESS_PENDING",
        status="PRODUCING",
    )
    assert_fields(
        fx.read_well(api, refused_well["id"]),
        access_status="ACCESS_PENDING",
        status="PRODUCING",
    )

    executed = validate_success(
        api.resolve_site_access(
            negotiated["id"],
            f.site_access_resolution_payload("EXECUTE_AGREEMENT", "W.S. 30-5-104"),
            users.ADMIN,
        ),
        200,
    )
    assert_fields(
        executed, status="AGREEMENT_EXECUTED", resolved_at="2026-08-01T00:00:00Z"
    )
    assert_null_fields(executed, "legal_authority_citation")
    assert_null_fields(
        fx.read_site_access(api, negotiated["id"]), "legal_authority_citation"
    )
    assert_fields(
        fx.read_well(api, negotiated_well["id"]),
        access_status="AGREEMENT_EXECUTED",
        status="PRODUCING",
    )

    denied = validate_success(
        api.resolve_site_access(
            refused["id"], f.site_access_resolution_payload("DENY"), users.ADMIN
        ),
        200,
    )
    assert_fields(denied, status="DENIED", resolved_at="2026-08-01T00:00:00Z")
    assert_fields(
        fx.read_well(api, refused_well["id"]),
        access_status="ACCESS_DENIED",
        status="PRODUCING",
    )


def test_moving_the_clock_returns_no_row_and_restamps_nothing(api):
    """The clock call answers with an empty payload and only later writes can see it.

    The default instant is the declared one rather than wall-clock time, so the well
    created before the move and the well created after it carry two different creation
    stamps, while the access row written under the old instant keeps every stamp it had.

    PRD: "Before any client sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time." ... "The clock
    capability responds with HTTP 200 and an empty data object." ... "Creating the request
    stamps `notice_sent_at` from the logical clock and derives `window_end_at` as that
    instant plus `waiting_period_days` days." ... "when it is omitted it defaults to 30 for
    `STATUTORY_ENTRY` mode and to 0 for `AGREEMENT` mode" ... "When `last_production_month`
    is null, meaning the well never produced, `idle_months` is the sentinel value 999."

    Design: Corner/endpoints/clock_endpoint_moves_the_instant_and_returns_no_entity
    """
    operator = fx.make_operator(
        api,
        name="Cottonwood Energy LLC",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=500000,
    )
    early_well = fx.make_well(api, operator["id"])
    access = fx.open_site_access(
        api, early_well["id"], mode="STATUTORY_ENTRY", surface_owner_name="Halvorsen Ranch"
    )
    assert_fields(
        access,
        status="REQUESTED",
        waiting_period_days=30,
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-31T00:00:00Z",
    )

    moved = api.set_clock("2026-10-15T00:00:00Z", users.ADMIN)
    assert moved.status_code == 200, "the clock call must answer HTTP 200, got %d" % (
        moved.status_code,
    )
    payload = moved.json()["data"]
    assert isinstance(payload, dict), "expected an empty data object, got %r" % (payload,)
    assert payload == {}, "the clock call must return no entity, got %r" % (payload,)
    for absent in ("id", "version", "created_at"):
        assert absent not in payload, (
            "the clock payload carried the row field %s: %r" % (absent, payload)
        )

    late_well = fx.make_well(api, operator["id"])
    assert_fields(late_well, created_at="2026-10-15T00:00:00Z", idle_months=999)
    assert_fields(
        fx.read_well(api, early_well["id"]), created_at="2026-08-01T00:00:00Z"
    )

    unchanged = fx.read_site_access(api, access["id"])
    assert_fields(
        unchanged,
        status="REQUESTED",
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-31T00:00:00Z",
    )
    assert_fields(
        fx.read_well(api, early_well["id"]), access_status="ACCESS_PENDING"
    )
