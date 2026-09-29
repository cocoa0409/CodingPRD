"""What intake stores, what intake derives, and how the resulting rows are read back."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client

UNKNOWN_MANUSCRIPT_ID = "11111111-2222-4333-8444-555555555555"


def _setup_three_submitted_manuscripts():
    world = fx.setup_submitted_manuscript()
    world["extra"] = [
        fx.create_manuscript(
            world["journal"]["id"], world["author"], world["author_headers"], page_count=8
        ),
        fx.create_manuscript(
            world["journal"]["id"], world["author"], world["author_headers"], page_count=9
        ),
    ]
    return world


def _list_submitted(journal_id, offset):
    return api_client.list_manuscripts(
        SYSTEM_ADMIN_HEADERS,
        params={
            "journal_id": journal_id,
            "status": "SUBMITTED",
            "limit": 2,
            "offset": offset,
        },
    )


def test_manuscript_read_returns_the_stored_submission_fields():
    """Every field the author supplied at submission comes back on the read.

    PRD: "The submission carries the `journal_id`, the `corresponding_author_id` — which must equal the acting `X-User-ID`, since an author may only submit on their own behalf — a `title`, a `subject_area` slug, and an `oa_license` chosen from `CC_BY`, `CC_BY_NC`, `CC_BY_NC_ND` and `GREEN_SELF_ARCHIVE`."

    Design: Corner/entities/manuscript_retrieval_returns_stored_submission_fields
    """
    world = fx.setup_submitted_manuscript(
        manuscript_overrides={"page_count": 20, "figure_count": 5, "oa_license": "CC_BY_NC"}
    )
    submitted = world["manuscript"]

    read = validate_success(
        api_client.get_manuscript(submitted["id"], world["author_headers"])
    )

    a.assert_fields(
        read,
        id=submitted["id"],
        journal_id=world["journal"]["id"],
        corresponding_author_id=world["author"]["id"],
        title=submitted["title"],
        subject_area="BIOCHEMISTRY",
        oa_license="CC_BY_NC",
        page_count=20,
        figure_count=5,
    )


def test_manuscript_intake_derives_status_round_and_pending_integrity():
    """A brand-new submission is unscreened, in its zeroth round and awaiting the desk.

    PRD: "The manuscript begins at `SUBMITTED` with `revision_round` 0 and `integrity_status` `PENDING`, since nothing has been screened yet."

    Design: Corner/entities/manuscript_retrieval_returns_stored_submission_fields
    """
    world = fx.setup_submitted_manuscript(
        manuscript_overrides={"page_count": 20, "figure_count": 5}
    )

    read = fx.get_manuscript(world["manuscript"]["id"])

    a.assert_fields(
        read, status="SUBMITTED", revision_round=0, integrity_status="PENDING"
    )
    a.assert_mutable_record_fields(read, expected_version=1)


def test_compliant_submission_starts_every_workflow_quantity_neutral():
    """Within policy on all three formatting tests, and carrying no workflow history yet.

    PRD: "Several other derived quantities on a manuscript start at their neutral values and are maintained by the workflows that follow: `submitted_review_count` at 0, `review_shortfall_flag` false, `handling_gap_flag` false, `consensus_index_at_last_decision` absent, `decision_count` at 0, and `publication_date`, `embargo_end_date`, `doi` and `retracted_at` all absent."

    Design: Corner/entities/manuscript_retrieval_returns_stored_submission_fields
    """
    world = fx.setup_submitted_manuscript(
        manuscript_overrides={"page_count": 20, "figure_count": 5}
    )

    read = fx.get_manuscript(world["manuscript"]["id"])

    a.assert_fields(
        read,
        formatting_status="COMPLIANT",
        submitted_review_count=0,
        review_shortfall_flag=False,
        handling_gap_flag=False,
        decision_count=0,
    )
    assert read.get("consensus_index_at_last_decision") is None
    assert read.get("publication_date") is None
    assert read.get("embargo_end_date") is None
    assert read.get("doi") is None
    assert read.get("retracted_at") is None


def test_first_submission_takes_sequence_number_one_from_the_intake_counter():
    """The sequence number is minted from the journal's counter, not from the request.

    PRD: "It receives a `journal_sequence_number` equal to the journal's `manuscript_intake_count` plus 1, and the journal's `manuscript_intake_count` then rises by 1 — this is the deterministic component of the DOI the article will eventually carry, and because the intake counter never decreases, no two manuscripts on one journal ever share a sequence number."

    Design: Corner/entities/manuscript_computed_status_doi_and_sequence_input_ignored
    """
    world = fx.setup_submitted_manuscript()

    read = fx.get_manuscript(world["manuscript"]["id"])

    a.assert_fields(read, journal_sequence_number=1, status="SUBMITTED")
    assert read.get("doi") is None
    assert fx.get_journal(world["journal"]["id"])["manuscript_intake_count"] == 1


def test_second_submission_takes_the_next_sequence_number():
    """Two submissions to one journal never share a sequence number.

    PRD: "A journal's `manuscript_intake_count` counts every manuscript ever submitted to it and never decreases, which is what makes a manuscript's `journal_sequence_number` permanently unique within its journal even after desk rejections and retractions."

    Design: Corner/entities/manuscript_computed_status_doi_and_sequence_input_ignored
    """
    world = fx.setup_submitted_manuscript()

    second = fx.create_manuscript(
        world["journal"]["id"], world["author"], world["author_headers"], page_count=8
    )

    a.assert_fields(second, journal_sequence_number=2)
    assert fx.get_manuscript(world["manuscript"]["id"])["journal_sequence_number"] == 1
    assert fx.get_journal(world["journal"]["id"])["manuscript_intake_count"] == 2


def test_filtered_manuscript_list_returns_the_first_page_of_three():
    """A limit of two over three matching rows reports more to come.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters before the window was applied, and `has_more`, which is true exactly when `offset` plus the number of returned rows is strictly less than `total_count`."

    Design: Corner/entities/manuscripts_list_filtered_by_journal_and_status_paginates
    """
    world = _setup_three_submitted_manuscripts()

    rows, meta = validate_paginated(_list_submitted(world["journal"]["id"], 0))

    assert len(rows) == 2, f"Expected 2 rows on the first page, got {len(rows)}"
    a.assert_fields(meta, total_count=3, limit=2, offset=0, has_more=True)
    for row in rows:
        a.assert_fields(row, journal_id=world["journal"]["id"], status="SUBMITTED")


def test_filtered_manuscript_list_second_page_exhausts_the_matches():
    """The remaining row arrives on the second page and the two pages cover the whole set.

    PRD: "List results are ordered by `created_at` ascending unless a subsection below states otherwise."

    Design: Corner/entities/manuscripts_list_filtered_by_journal_and_status_paginates
    """
    world = _setup_three_submitted_manuscripts()
    first_page, _meta = validate_paginated(_list_submitted(world["journal"]["id"], 0))

    rows, meta = validate_paginated(_list_submitted(world["journal"]["id"], 2))

    assert len(rows) == 1, f"Expected 1 row on the second page, got {len(rows)}"
    a.assert_fields(meta, total_count=3, limit=2, offset=2, has_more=False)
    expected_ids = {world["manuscript"]["id"]} | {m["id"] for m in world["extra"]}
    assert {row["id"] for row in first_page + rows} == expected_ids


def test_unknown_manuscript_id_is_a_not_found_read():
    """A syntactically valid identifier that matches no row is refused, not answered.

    PRD: "Every path parameter references an existing row of its entity — otherwise the matching not-found error for that entity (404), on every endpoint that has a path parameter."

    Design: Corner/entities/manuscript_not_found_for_unknown_id
    """
    fx.setup_submitted_manuscript()

    response = api_client.get_manuscript(UNKNOWN_MANUSCRIPT_ID, SYSTEM_ADMIN_HEADERS)

    error = validate_error(
        response, ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND.value, expected_status=404
    )
    assert error["message"], "Expected a human-readable message on the error envelope"
