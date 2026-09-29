"""Read-after-write behaviour: a mutation's effects are visible on the very next read."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_ledger_buckets
from test_helpers.factories import reclassify_payload
from test_helpers.fixtures import (
    add_subscriber,
    open_statement,
    read_publication,
    read_statement,
    register_publication,
)
from test_helpers.test_users import MANAGER_HEADERS


def test_reclassify_response_and_publication_ledger_are_immediately_consistent():
    """The reclassify response, the parent ledger and the draft's stale flag move together.

    "Reclassification is precisely compensating on the ledger: the old class bucket
    falls by the recipient's `copies` and the new class bucket rises by the same
    amount, so `copies_on_file_total` is untouched and the class-axis conserved
    quantity of §2.10 still holds. Every `DRAFT` statement of the publication is
    marked stale, and the recipient's `version` advances by 1."

    Design: Corner/consistency_model/reclassify_response_and_publication_ledger_are_immediately_consistent
    """
    publication = register_publication(
        name="Immediate Consistency Monthly", industry_code="HEALTHCARE"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Papa Clinical",
        job_function_code="CLINICAL_MGMT",
        industry_code="HEALTHCARE",
        subscription_class="CONTROLLED",
        copies=250,
    )

    before = read_publication(publication["id"])
    assert before["copies_on_file_total"] == 250
    assert before["controlled_copies_on_file"] == 250
    assert before["paid_copies_on_file"] == 0
    assert_ledger_buckets(before)

    statement = open_statement(
        publication["id"],
        period_start="2026-04-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    assert statement["status"] == "DRAFT"
    assert statement["breakdown_stale"] is False

    # The mutation's own response already carries the new class and the money.
    reclassified = validate_success(
        api_client.reclassify_subscriber(
            subscriber["id"],
            reclassify_payload("PAID", paid_amount_cents=24900),
            MANAGER_HEADERS,
        ),
        200,
    )
    assert reclassified["subscription_class"] == "PAID"
    assert reclassified["paid_amount_cents"] == 24900
    assert reclassified["version"] == subscriber["version"] + 1

    # A read taken immediately afterwards shows both class buckets already moved.
    after = read_publication(publication["id"])
    assert after["copies_on_file_total"] == 250
    assert after["controlled_copies_on_file"] == 0
    assert after["paid_copies_on_file"] == 250
    assert_ledger_buckets(after)

    # And the draft is already flagged, with no settle step or re-read delay.
    assert read_statement(statement["id"])["breakdown_stale"] is True
