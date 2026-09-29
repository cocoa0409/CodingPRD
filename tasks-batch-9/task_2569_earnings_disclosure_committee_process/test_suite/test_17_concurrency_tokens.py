"""Two parent-version tokens, each invalidated by a different kind of write.

A document create is guarded by the owning cycle's version, which an unrelated
sub-certification assignment bumps; a tie-out create is guarded by its own
document's version, which the previous line of the same schedule bumps.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_money
from test_helpers.factories import document_payload, tie_out_item_payload
from test_helpers.fixtures import (
    add_milestone,
    assign_subcert,
    build_committee,
    build_cycle,
    create_document,
    open_close,
    refresh_cycle,
    refresh_document,
)
from test_helpers.test_users import admin_headers

OCC_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
FILING_TITLE = "Form 10-Q FY2026-Q2"
RELEASE_TITLE = "Q2 Earnings Release"


def _open_cycle(api, name):
    committee = build_committee(
        api,
        seats=OCC_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name=name,
    )
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    opened = open_close(api, committee, cycle["id"])
    assert opened["status"] == "CLOSE_OPEN"
    return committee, cycle


def _token_invalidated_by_a_sibling(api):
    """The cycle version is read first, then a sub-certification assignment — which
    touches no document at all — advances it."""
    committee, cycle = _open_cycle(api, "OCC Cycle Charter")
    observed = refresh_cycle(api, cycle["id"])["version"]
    assign_subcert(
        api, committee, cycle["id"], "fin", "REVENUE", due_utc="2026-08-04T17:00:00Z"
    )
    return committee, cycle, observed


def _start_document(api, committee, cycle_id, doc_type, title, expected_cycle_version,
                    safe_harbor_present=None):
    return api.create_document(
        document_payload(
            cycle_id, doc_type, committee.mid("fin"), expected_cycle_version,
            title=title, safe_harbor_present=safe_harbor_present,
        ),
        committee.controller("fin"),
    )


def test_a_sibling_write_invalidates_the_cycle_token_a_document_create_carries(api):
    """The client's cycle version was correct when it was read and is stale by one
    by the time it is used, because assigning a sub-certification mutated the
    parent cycle; the create is refused at 412, nothing is written, and the same
    request re-issued with the re-read version is accepted.

    PRD 2.8: "Creating a draft document requires `expected_cycle_version`, carrying the client's last observed `version` of the target `ReportingCycle`."

    PRD 2.8: "If the cycle's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row, again including cascaded mutations."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_cycle_version_blocks_a_document_create_and_the_fresh_one_lands
    """
    committee, cycle, observed = _token_invalidated_by_a_sibling(api)

    validate_error(
        _start_document(
            api, committee, cycle["id"], "PERIODIC_FILING", FILING_TITLE, observed
        ),
        "ERR_STALE_CYCLE_VERSION",
        412,
    )
    empty, meta = validate_paginated(
        api.list_documents(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert empty == []
    assert meta["total_count"] == 0

    current = refresh_cycle(api, cycle["id"])["version"]
    assert current == observed + 1

    created = validate_success(
        _start_document(
            api, committee, cycle["id"], "PERIODIC_FILING", FILING_TITLE, current
        ),
        201,
    )
    assert created["status"] == "DRAFT"
    assert created["revision_round"] == 0
    assert created["tie_out_status"] == "NOT_STARTED"
    assert created["version"] == 1


def test_the_accepted_token_is_consumed_by_the_write_that_accepted_it(api):
    """Creating the document advances the cycle's version in its turn, so replaying
    the token that had just been accepted is refused as well: one token buys one
    write, and the second draft never reaches the collection.

    PRD 2.8: "In each case the version field is a **required, non-optional** input on the request — omitting it is a request-shape failure, not a silent pass — and the value the client supplies must equal the parent's current `version` at the moment the request is processed."

    PRD 2.8: "If the cycle's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_cycle_version_blocks_a_document_create_and_the_fresh_one_lands
    """
    committee, cycle, _ = _token_invalidated_by_a_sibling(api)
    consumed = refresh_cycle(api, cycle["id"])["version"]

    first = validate_success(
        _start_document(
            api, committee, cycle["id"], "PERIODIC_FILING", FILING_TITLE, consumed
        ),
        201,
    )
    after = refresh_cycle(api, cycle["id"])["version"]
    assert after == consumed + 1

    validate_error(
        _start_document(
            api, committee, cycle["id"], "EARNINGS_RELEASE", RELEASE_TITLE, consumed,
            safe_harbor_present=True,
        ),
        "ERR_STALE_CYCLE_VERSION",
        412,
    )

    rows, meta = validate_paginated(
        api.list_documents(admin_headers(), cycle_id=cycle["id"], limit=10, offset=0)
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert refresh_document(api, committee, first["id"])["status"] == "DRAFT"


def _draft_schedule(api):
    """A DRAFT periodic filing with no tie-out lines yet, and the document version
    as the client last saw it."""
    committee, cycle = _open_cycle(api, "OCC Document Charter")
    document = create_document(
        api, committee, cycle["id"], "PERIODIC_FILING", "fin", title=FILING_TITLE
    )
    assert document["version"] == 1
    assert document["tie_out_status"] == "NOT_STARTED"
    return committee, document


def _append_line(api, committee, document_id, line_label, reported_value,
                 source_record_value, tolerance_bp, expected_document_version):
    return api.create_tie_out_item(
        document_id,
        tie_out_item_payload(
            line_label, reported_value, source_record_value, tolerance_bp,
            committee.mid("fin"), expected_document_version,
        ),
        committee.controller("fin"),
    )


def test_the_first_append_invalidates_the_token_the_second_append_still_holds(api):
    """The token that was correct a moment ago is stale for the very next line of
    the same schedule, because appending a line mutates the parent document; the
    client must re-read between consecutive appends, and once it does the identical
    request is accepted.

    PRD 2.8: "Creating a tie-out item requires `expected_document_version`, carrying the client's last observed `version` of the target `DraftDocument`."

    PRD 2.8: "If the document's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_DOCUMENT_VERSION` (HTTP 412)."

    PRD 2.8: "This guard exists because a tie-out create re-derives every sibling item's effective tolerance from a document-wide tier multiplier; a writer holding a stale view of the document would re-classify siblings it had never read."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_document_version_blocks_a_tie_out_create_after_its_own_sibling_write
    """
    committee, document = _draft_schedule(api)
    observed = document["version"]

    first = validate_success(
        _append_line(
            api, committee, document["id"], "Total revenue", 4120000.0, 4120000.0, 25,
            observed,
        ),
        201,
    )
    assert first["status"] == "MATCHED"
    assert first["raw_variance_bp"] == 0
    assert first["effective_tolerance_bp"] == 25

    validate_error(
        _append_line(
            api, committee, document["id"], "Operating income", 1030000.0, 1030000.0, 40,
            observed,
        ),
        "ERR_STALE_DOCUMENT_VERSION",
        412,
    )

    after_first = refresh_document(api, committee, document["id"])
    assert after_first["version"] == observed + 1
    assert after_first["tie_out_status"] == "PASSED"

    second = validate_success(
        _append_line(
            api, committee, document["id"], "Operating income", 1030000.0, 1030000.0, 40,
            after_first["version"],
        ),
        201,
    )
    assert second["status"] == "MATCHED"

    after_second = refresh_document(api, committee, document["id"])
    assert after_second["version"] == after_first["version"] + 1


def test_the_refused_append_leaves_the_schedule_exactly_two_lines_long(api):
    """The refusal writes nothing at all: the line it named is absent until the
    retry puts it there once, so the schedule holds two matched lines whose
    effective tolerances still come from the tight tier, and the label the rejected
    request used is not duplicated.

    PRD 3.6: "The item's `status` becomes `MATCHED` when its `raw_variance_bp` is less than or equal to its `effective_tolerance_bp`, and `VARIANCE` otherwise."

    PRD 3.6: "It is `NOT_STARTED` when the non-waived set is empty, `PASSED` when every item in that set is `MATCHED`, and `FAILED` otherwise."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_document_version_blocks_a_tie_out_create_after_its_own_sibling_write
    """
    committee, document = _draft_schedule(api)
    observed = document["version"]

    validate_success(
        _append_line(
            api, committee, document["id"], "Total revenue", 4120000.0, 4120000.0, 25,
            observed,
        ),
        201,
    )
    validate_error(
        _append_line(
            api, committee, document["id"], "Operating income", 1030000.0, 1030000.0, 40,
            observed,
        ),
        "ERR_STALE_DOCUMENT_VERSION",
        412,
    )
    only_one, first_meta = validate_paginated(
        api.list_tie_out_items(
            admin_headers(), document_id=document["id"], limit=10, offset=0
        )
    )
    assert len(only_one) == 1
    assert first_meta["total_count"] == 1

    fresh = refresh_document(api, committee, document["id"])["version"]
    validate_success(
        _append_line(
            api, committee, document["id"], "Operating income", 1030000.0, 1030000.0, 40,
            fresh,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_tie_out_items(
            admin_headers(), document_id=document["id"], limit=10, offset=0
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["line_label"] for row in rows) == [
        "Operating income",
        "Total revenue",
    ]
    assert [row["status"] for row in rows] == ["MATCHED", "MATCHED"]
    assert sorted(row["effective_tolerance_bp"] for row in rows) == [25, 40]

    schedule = refresh_document(api, committee, document["id"])
    assert schedule["tie_out_status"] == "PASSED"
    assert schedule["tie_out_total_variance_bp"] == 0
    assert_money(schedule["tie_out_tier_multiplier"], 1.00)
