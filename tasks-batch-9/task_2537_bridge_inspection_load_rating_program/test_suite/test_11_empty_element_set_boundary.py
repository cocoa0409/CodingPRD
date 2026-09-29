"""
Submission with no element rows at all: the empty-set boundary of the six gates.

PRD §3.3: "The report must have at least one element row, else
`ERR_NO_ELEMENT_CONDITIONS`."
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"


def _empty_special_report(client, roster, bridge):
    """A `SPECIAL` report opened but never populated, at the field-day clock."""
    inspection = fx.open_inspection(
        client, bridge["id"], roster, inspection_type="SPECIAL"
    )
    fx.set_clock(client, FIELD_DAY)
    return inspection


def test_a_report_with_no_element_rows_cannot_be_submitted(client, roster, bridge):
    """
    Zero rows is the boundary the gate names, and the report stays in draft with no
    condition arithmetic on it.

    PRD §3.3: "The report must have at least one element row, else
    `ERR_NO_ELEMENT_CONDITIONS`."
    PRD §3.2: "The new report is stamped with `returned_count` 0, `element_count` 0,
    a `bridge_id` copied from the structure being inspected, a null `qa_reviewer_id`
    until a reviewer actually claims it, and every derived condition field null."

    Design: Difficulty/boundary_precision_check/submit_inspection_with_zero_elements_empty_set
    """
    inspection = _empty_special_report(client, roster, bridge)

    response = client.submit_inspection(
        inspection["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_NO_ELEMENT_CONDITIONS, 422)

    report = fx.read_inspection(client, inspection["id"])
    assert report["status"] == "DRAFT"
    assert report["element_count"] == 0
    assert report["bridge_health_index"] is None
    assert report["submitted_at"] is None


def test_the_element_listing_confirms_the_report_is_genuinely_empty(
    client, roster, bridge
):
    """
    The filter on the report is the discovery channel for its rows, and it returns
    an empty page with a zero total.

    PRD §3.2: "Each row carries an `inspection_id` identifying the report it belongs
    to, taken from the report the row is filed against rather than from the payload,
    and the element list may be filtered by that `inspection_id` to recover the rows
    of a given report."
    PRD §2.3: "`total_count` (the number of records matching the filters before
    pagination)".

    Design: Difficulty/boundary_precision_check/submit_inspection_with_zero_elements_empty_set
    """
    inspection = _empty_special_report(client, roster, bridge)

    listing = fx.elements_for_inspection(client, inspection["id"])

    assert listing["rows"] == []
    assert listing["meta"]["total_count"] == 0
    assert listing["meta"]["has_more"] is False


def test_the_structure_still_carries_only_its_seeded_condition(client, roster, bridge):
    """
    A refused submission publishes nothing, so the structure keeps the placeholder
    ratings it was seeded with and the two-year cycle they imply.

    PRD §3.1: "The creation payload accepts `initial_deck_rating`,
    `initial_superstructure_rating` and `initial_substructure_rating`, each an
    integer from 0 through 9 and each defaulting to 7 when omitted."
    PRD §2.11: "Failing either the poor-condition test or the extension test, the
    base is the standard 24 months."

    Design: Difficulty/boundary_precision_check/submit_inspection_with_zero_elements_empty_set
    """
    inspection = _empty_special_report(client, roster, bridge)
    client.submit_inspection(
        inspection["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        roster.inspector_headers,
    )

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["deck_rating"] == 7
    assert structure["superstructure_rating"] == 7
    assert structure["substructure_rating"] == 7
    assert structure["min_nbi_rating"] == 7
    assert structure["bridge_health_index"] is None
    assert structure["last_routine_inspection_date"] is None
    assert structure["inspection_interval_months"] == 24
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )


def test_one_element_row_clears_the_empty_set_gate_and_the_next_gate_speaks(
    client, roster, bridge
):
    """
    Adding a single deck row satisfies the at-least-one-row gate exactly, and the
    next gate in precedence order — element-group coverage — is then the one that
    refuses the submission.

    PRD §3.3: "Element-group coverage depends on type: a `ROUTINE`, `SPECIAL`,
    `DAMAGE` or `FRACTURE_CRITICAL` report must include at least one row in each of
    `DECK_GROUP`, `SUPERSTRUCTURE` and `SUBSTRUCTURE` ... a missing group is
    `ERR_ELEMENT_GROUP_MISSING`."
    PRD §2.8: "16. **At least one element row on submit** —
    `ERR_NO_ELEMENT_CONDITIONS` (422). Applies to inspection submit."
    PRD §2.8: "17. **Element-group coverage** — `ERR_ELEMENT_GROUP_MISSING` (422).
    Applies to inspection submit and load-rating creation."

    Design: Difficulty/boundary_precision_check/submit_inspection_with_zero_elements_empty_set
    """
    inspection = _empty_special_report(client, roster, bridge)
    row = fx.add_element(client, inspection["id"], roster, f.BASELINE_DECK)

    response = client.submit_inspection(
        inspection["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_ELEMENT_GROUP_MISSING, 422)

    report = fx.read_inspection(client, inspection["id"])
    assert report["element_count"] == 1
    assert report["status"] == "DRAFT"
    assert row["element_group"] == "DECK_GROUP"
    a.assert_element_group_for_key(row)
