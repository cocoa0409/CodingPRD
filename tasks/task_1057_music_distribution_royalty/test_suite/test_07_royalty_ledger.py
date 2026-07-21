"""Opening statements, ingesting royalty lines, the append-only ledger and reconciliation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_royalty_statement, assert_royalty_line,
    set_clock, create_plan, create_artist, create_active_subscription,
    setup_world, open_statement, ingest_batch, royalty_line_payload,
    read_statement, read_artist, CLOCK_BASE, PERIOD_MAY, PERIOD_JAN, PERIOD_FEB,
    make_finance_headers, FIN_RECONCILER, FIN_CLOSER,
)


def _ledger_world(email="ledger@example.com"):
    """An artist with one track and one store, ready to receive reported revenue."""
    return setup_world(artist_overrides={"email": email})


def test_new_statement_opens_with_every_derived_figure_at_zero(api, finance_headers):
    """PRD §3.7: "A newly opened statement is in `OPEN` with every derived figure at zero —
    `line_count`, `gross_cents`, `content_id_gross_cents`, `commission_cents`,
    `content_id_bonus_cents`, `provisional_net_cents` and `net_cents` — and with
    `reconciled_by_user_id` and `closed_by_user_id` both null."
    PRD §3.7: "The interval is half-open: `period_start` is inclusive, `period_end` is exclusive."

    Design: Difficulty/resource_temporal_overlap/artist_statement_period_halfopen_pairwise_overlap
    """
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist = create_artist(email="pyxis0@example.com")
    create_active_subscription(artist["id"], plan["id"])

    statement = validate_success(
        api.create_royalty_statement(
            {"artist_id": artist["id"], "period_start": PERIOD_JAN[0],
             "period_end": PERIOD_JAN[1]},
            finance_headers),
        201,
    )

    assert_royalty_statement(statement)
    assert statement["status"] == "OPEN"
    for field in ("line_count", "gross_cents", "content_id_gross_cents", "commission_cents",
                  "content_id_bonus_cents", "provisional_net_cents", "net_cents"):
        assert statement[field] == 0, f"{field} must open at zero"
    assert statement["reconciled_by_user_id"] is None
    assert statement["closed_by_user_id"] is None


def test_adjacent_period_is_accepted_but_a_straddling_period_overlaps(api, finance_headers):
    """PRD §3.7: "No two statements of the same artist may overlap — a new statement is rejected
    with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409) whenever any existing statement of that artist,
    in any status whatsoever including already-closed ones, has a `period_start` strictly earlier
    than the new `period_end` while the new `period_start` is strictly earlier than that existing
    statement's `period_end`."
    PRD §3.7: "Because the intervals are half-open, exact adjacency is fine: a statement beginning
    precisely where another ends does not overlap it."

    Design: Difficulty/resource_temporal_overlap/artist_statement_period_halfopen_pairwise_overlap
    """
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist = create_artist(email="pyxis@example.com")
    create_active_subscription(artist["id"], plan["id"])
    open_statement(artist["id"], PERIOD_JAN)

    adjacent = validate_success(
        api.create_royalty_statement(
            {"artist_id": artist["id"], "period_start": PERIOD_FEB[0],
             "period_end": PERIOD_FEB[1]},
            finance_headers),
        201,
    )
    assert adjacent["status"] == "OPEN"

    straddling = api.create_royalty_statement(
        {"artist_id": artist["id"], "period_start": "2026-01-15T00:00:00Z",
         "period_end": "2026-02-15T00:00:00Z"},
        finance_headers,
    )
    validate_error(straddling, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP.value)

    _rows, meta = validate_paginated(
        api.list_royalty_statements(finance_headers, params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 2


def test_royalty_lines_are_append_only_and_carry_no_version(api, finance_headers):
    """PRD §2.4: "The one exception is the royalty line. Royalty lines are append-only ledger
    entries: once ingested they are never edited, so a royalty line carries only `id` and
    `created_at` — it has no `updated_at` and no `version` field at all."

    Design: Corner/entities/royalty_line_is_immutable_append_only_with_no_version_field
    """
    world = _ledger_world("cirrus@example.com")
    statement = open_statement(world["artist_id"], PERIOD_MAY)
    ingest_batch(statement["id"], statement["version"], [
        royalty_line_payload(world["track"]["id"], world["store"]["id"], 500,
                             "2026-05-05T00:00:00Z", units=100),
    ])

    lines, meta = validate_paginated(
        api.list_royalty_lines(finance_headers,
                               params={"royalty_statement_id": statement["id"]})
    )

    assert meta["total_count"] == 1
    line = lines[0]
    assert_royalty_line(line)
    assert line["gross_cents"] == 500
    assert line["source"] == "STREAMING"
    assert "version" not in line, "a royalty line has no version field at all"
    assert "updated_at" not in line, "a royalty line has no updated_at"
    assert read_statement(statement["id"])["line_count"] == 1


def test_statement_aggregates_accumulate_across_two_ingest_batches(api, finance_headers):
    """PRD §3.7: "Ingestion is permitted from `OPEN`, which it moves to `INGESTING`, and from
    `INGESTING`, which it leaves in `INGESTING` — a statement may absorb as many successive
    batches as the feed requires."
    PRD §3.7: "The aggregates are defined over every line whose `royalty_statement_id` matches the
    statement, with no status filter of any kind because lines are append-only: `line_count` is
    the number of such lines, `gross_cents` is the sum of their `gross_cents`, and
    `content_id_gross_cents` is the sum of `gross_cents` restricted to lines whose `source` is
    `CONTENT_ID`."

    Design: Corner/calculations/statement_gross_aggregates_across_two_ingest_batches
    """
    world = setup_world(
        artist_overrides={"email": "musca@example.com"},
        extra_stores=[{"code": "YOUTUBE", "name": "YouTube", "delivery_lead_days": 3}],
    )
    store_spot, store_yt = world["stores"]
    track_id = world["track"]["id"]
    statement = open_statement(world["artist_id"], PERIOD_MAY)

    after_first = validate_success(
        api.ingest_royalty_lines(
            statement["id"], statement["version"],
            [royalty_line_payload(track_id, store_spot["id"], 400, "2026-05-05T00:00:00Z",
                                  units=1000),
             royalty_line_payload(track_id, store_yt["id"], 300, "2026-05-06T00:00:00Z",
                                  source="CONTENT_ID", units=900)],
            finance_headers)
    )
    assert after_first["status"] == "INGESTING"

    after_second = validate_success(
        api.ingest_royalty_lines(
            statement["id"], after_first["version"],
            [royalty_line_payload(track_id, store_spot["id"], 200, "2026-05-07T00:00:00Z",
                                  source="DOWNLOAD", units=500)],
            finance_headers)
    )

    assert after_second["status"] == "INGESTING"
    assert after_second["line_count"] == 3
    assert after_second["gross_cents"] == 900
    assert after_second["content_id_gross_cents"] == 300

    _all_lines, meta_all = validate_paginated(
        api.list_royalty_lines(finance_headers,
                               params={"royalty_statement_id": statement["id"]})
    )
    assert meta_all["total_count"] == 3

    _yt_lines, meta_yt = validate_paginated(
        api.list_royalty_lines(finance_headers, params={"store_id": store_yt["id"]})
    )
    assert meta_yt["total_count"] == 1


def test_ingest_with_a_stale_statement_version_is_refused(api, finance_headers):
    """PRD §2.7: "Appending a batch of royalty lines to a statement requires
    `expected_statement_version`, carrying the client's last observed `version` of the target
    statement."
    PRD §3.7: "The request carries `expected_statement_version`, which must equal the statement's
    current `version` or the batch is rejected with `ERR_STALE_VERSION` (HTTP 412), together with
    `lines`, an array of reported royalty lines."

    Design: Corner/cross_cutting_layers/royalty_ingest_with_stale_statement_version_returns_412
    """
    world = _ledger_world("lac2@example.com")
    statement = open_statement(world["artist_id"], PERIOD_MAY)
    version_1 = statement["version"]
    line = royalty_line_payload(world["track"]["id"], world["store"]["id"], 500,
                                "2026-05-05T00:00:00Z", units=100)

    after = ingest_batch(statement["id"], version_1, [line])
    version_2 = after["version"]
    assert version_2 == version_1 + 1

    replay = api.ingest_royalty_lines(statement["id"], version_1, [line], finance_headers)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)

    stored = read_statement(statement["id"])
    assert stored["line_count"] == 1, "the replayed batch must append nothing"
    assert stored["gross_cents"] == 500


def test_batch_with_a_line_outside_the_period_is_rejected_in_full(api, finance_headers):
    """PRD §3.7: "Every line's `reported_at` must fall inside the statement's half-open period —
    at or after `period_start` and strictly before `period_end` — and a batch containing even one
    line outside that window is rejected in full with `ERR_LINE_OUTSIDE_PERIOD` (HTTP 422)."

    Design: Corner/validations/ingest_line_reported_outside_period_is_rejected
    """
    world = _ledger_world("tuc2@example.com")
    statement = open_statement(world["artist_id"], PERIOD_MAY)

    resp = api.ingest_royalty_lines(
        statement["id"], statement["version"],
        [royalty_line_payload(world["track"]["id"], world["store"]["id"], 100,
                              "2026-06-01T00:00:00Z", units=10)],
        finance_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LINE_OUTSIDE_PERIOD.value)

    stored = read_statement(statement["id"])
    assert stored["line_count"] == 0
    assert stored["status"] == "OPEN", "a rejected batch leaves the statement untouched"


def test_reconcile_and_close_of_a_line_free_statement_yield_zero_throughout(api):
    """PRD §3.7: "It may be performed from `INGESTING`, and also from `OPEN` for a statement that
    never received a single line, in which case `commission_cents` and `provisional_net_cents` are
    both simply 0."
    PRD §3.8: "Step five is unchanged: the same 2000-basis-point cap on `gross_cents` limits it
    from above, the same 50-cent floor lifts it from below, and a statement with zero gross has
    zero commission."

    Design: Corner/calculations/reconcile_with_zero_lines_yields_zero_commission_and_zero_net
    """
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist = create_artist(email="crux@example.com")
    create_active_subscription(artist["id"], plan["id"])
    statement = open_statement(artist["id"], PERIOD_MAY)

    reconciled = validate_success(
        api.reconcile_statement(statement["id"], make_finance_headers(FIN_RECONCILER))
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["commission_cents"] == 0
    assert reconciled["provisional_net_cents"] == 0

    closed = validate_success(
        api.close_statement(statement["id"], make_finance_headers(FIN_CLOSER))
    )

    assert closed["status"] == "CLOSED"
    assert closed["gross_cents"] == 0
    assert closed["commission_cents"] == 0
    assert closed["content_id_bonus_cents"] == 0
    assert closed["net_cents"] == 0

    _payouts, meta = validate_paginated(
        api.list_payouts(make_finance_headers(FIN_CLOSER),
                         params={"royalty_statement_id": statement["id"]})
    )
    assert meta["total_count"] == 0
    assert read_artist(artist["id"])["lifetime_gross_cents"] == 0
