"""Inclusive thresholds probed at the exact instant they bind, and one step either side."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD
from test_helpers.assertions import assert_ledger_buckets, assert_pct
from test_helpers.factories import undeliverable_event_payload, verify_payload
from test_helpers.fixtures import (
    add_complete_rule_set,
    add_subscriber,
    attach_source_document,
    open_request,
    read_publication,
    read_subscriber,
    register_publication,
    review_request,
    run_hygiene_sweep,
    verify_request,
)
from test_helpers.test_users import MANAGER_HEADERS, SPECIALIST_HEADERS


def reviewed_request(publication_id, company_name, signed_at, request_channel):
    """One recipient, one card and one reviewed request whose score is now pinned."""
    recipient = add_subscriber(
        publication_id,
        company_name=company_name,
        subscription_class="CONTROLLED",
        copies=25,
    )
    document = attach_source_document(
        recipient["id"], MANAGER_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    request = open_request(
        recipient["id"],
        document["id"],
        recipient["version"],
        headers=SPECIALIST_HEADERS,
        request_channel=request_channel,
        signed_at=signed_at,
        # Outside the PURCHASING_AUTHORITY rule's allowed values, so that dimension
        # scores nothing and the base score is 45 + 30 = 75.
        attested_purchasing_authority="NONE",
    )
    return recipient, review_request(request["id"])


def test_score_exactly_at_the_threshold_qualifies_and_one_month_less_does_not():
    """Seventy qualifies; the smallest step in signature age drops it to sixty-five.

    "Qualification then turns on two tests whose order is pinned. A request qualifies
    its recipient when `computed_score` is at least 70 **and** every rule marked
    `is_mandatory` scored more than zero points for this request's attestations."

    Design: Difficulty/boundary_precision_check/qualification_score_exactly_at_threshold_boundary
    """
    publication = register_publication(
        name="Threshold Boundary Monthly", industry_code="MANUFACTURING"
    )
    add_complete_rule_set(publication["id"])

    # Thirteen complete months old at the default clock: one month past the twelfth,
    # so the staleness penalty is exactly 5 points.
    at_boundary, on_score = reviewed_request(
        publication["id"], "Delta Boundary Works", "2025-07-01T00:00:00Z", "TELEPHONE"
    )
    assert on_score["computed_score"] == 70

    # Fourteen complete months: two months past the twelfth, so 10 points.
    below_boundary, short_score = reviewed_request(
        publication["id"], "Echo Boundary Works", "2025-06-01T00:00:00Z", "TELEPHONE"
    )
    assert short_score["computed_score"] == 65

    verified = verify_request(
        on_score["id"], decision_reason="score exactly at threshold"
    )
    assert verified["status"] == "VERIFIED"
    assert verified["computed_score"] == 70

    qualified = read_subscriber(at_boundary["id"])
    assert qualified["qualification_status"] == "QUALIFIED"
    assert qualified["qualification_score"] == 70
    assert qualified["qualified_at"].startswith("2026-08-01T00:00:00")
    # Thirty-six months of validity by default.
    assert qualified["qualification_expires_at"].startswith("2029-08-01T00:00:00")

    response = api_client.verify_qualification_request(
        short_score["id"],
        verify_payload(decision_reason="score one step below threshold"),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD, 422)

    refused = validate_success(
        api_client.get_qualification_request(short_score["id"], SPECIALIST_HEADERS), 200
    )
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["computed_score"] == 65
    unqualified = read_subscriber(below_boundary["id"])
    assert unqualified["qualification_status"] == "PENDING_QUALIFICATION"
    assert unqualified["qualification_score"] == 0


def test_twelfth_month_is_the_last_month_of_the_bonus_and_the_first_before_the_penalty():
    """At twelve complete months the bonus still pays and no penalty has started yet.

    "a request whose `request_channel` is `DIRECT_MAIL` earns 10 bonus points, and
    one whose channel is `WEB` or `EMAIL` earns 5, but only while the signature is no
    more than twelve complete months old — inside one year."

    Design: Difficulty/boundary_precision_check/qualification_score_exactly_at_threshold_boundary
    """
    publication = register_publication(
        name="Bonus Window Monthly", industry_code="MANUFACTURING"
    )
    add_complete_rule_set(publication["id"])

    # Exactly twelve complete months: the bonus survives and the penalty has not begun.
    inside, inside_score = reviewed_request(
        publication["id"], "Foxtrot Window Works", "2025-08-01T00:00:00Z", "DIRECT_MAIL"
    )
    assert inside_score["computed_score"] == 85

    # One month later the bonus is gone and the first penalty step applies: 75 - 5.
    outside, outside_score = reviewed_request(
        publication["id"], "Golf Window Works", "2025-07-01T00:00:00Z", "DIRECT_MAIL"
    )
    assert outside_score["computed_score"] == 70
    # A single month of signature age is worth fifteen points at this boundary.
    assert inside_score["computed_score"] - outside_score["computed_score"] == 15

    assert verify_request(inside_score["id"])["status"] == "VERIFIED"
    assert read_subscriber(inside["id"])["qualification_score"] == 85

    # Seventy is at least seventy, so the far side of the bonus window still qualifies.
    assert verify_request(outside_score["id"])["status"] == "VERIFIED"
    assert read_subscriber(outside["id"])["qualification_score"] == 70


def bounce_twice(subscriber_id):
    for _ in range(2):
        response = api_client.record_undeliverable_event(
            subscriber_id, undeliverable_event_payload(), MANAGER_HEADERS
        )
        latest = validate_success(response, 200)
    assert latest["undeliverable_count"] == 2
    return latest


def test_hygiene_ratio_exactly_at_the_restrict_threshold_restricts_and_widening_relaxes():
    """Five percent on the nose restricts; widening the file to 4.95 relaxes it again.

    "Otherwise, if the publication's hygiene ratio `undeliverable_pct` is greater
    than or equal to its `undeliverable_restrict_pct` policy threshold, the posture
    is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/undeliverable_pct_exactly_at_restrict_boundary
    """
    publication = register_publication(
        name="Restrict Boundary Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    bulk = add_subscriber(
        publication["id"],
        company_name="Hotel Bulk Works",
        subscription_class="PAID",
        copies=950,
        paid_amount_cents=76000,
    )
    wanderer = add_subscriber(
        publication["id"],
        company_name="India Bulk Works",
        subscription_class="CONTROLLED",
        copies=50,
    )
    # No qualification rules were added, so neither recipient is qualified.
    assert wanderer["qualification_status"] == "UNQUALIFIED"
    assert wanderer["delivery_status"] == "DELIVERABLE"
    bounce_twice(wanderer["id"])

    sweep = run_hygiene_sweep(
        publication["id"], run_type="UNDELIVERABLE_SWEEP", undeliverable_threshold=2
    )
    assert sweep["removed_count"] == 1
    # The dropped recipient was UNQUALIFIED, so there was nothing to requalify.
    assert sweep["requalification_required_count"] == 0
    assert sweep["posture_before"] == "OPEN"
    assert sweep["posture_after"] == "RESTRICTED"

    restricted = read_publication(publication["id"])
    assert_ledger_buckets(
        restricted, total=1000, deliverable=950, undeliverable=0, removed=50
    )
    # 50 of 1,000 is exactly 5.00, and the comparison is greater-than-or-equal.
    assert_pct(restricted["undeliverable_pct"], 5.00)
    assert restricted["audit_posture"] == "RESTRICTED"

    add_subscriber(
        publication["id"],
        company_name="Juliet Bulk Works",
        subscription_class="CONTROLLED",
        copies=10,
    )
    relaxed = read_publication(publication["id"])
    assert relaxed["copies_on_file_total"] == 1010
    assert relaxed["controlled_copies_on_file"] == 60
    # The same 50 copies are now 4.95 percent, which is below the threshold.
    assert_pct(relaxed["undeliverable_pct"], 4.95)
    assert relaxed["audit_posture"] == "OPEN"
    assert read_subscriber(bulk["id"])["delivery_status"] == "DELIVERABLE"


def test_rounding_the_hygiene_ratio_is_what_decides_the_posture_at_the_boundary():
    """A raw ratio of 4.995 percent rounds up to 5.00 and restricts; 4.90 does not.

    "Riding on top is the hygiene ratio `undeliverable_pct`: the sum of
    `undeliverable_copies` and `removed_copies`, multiplied by 100, divided by
    `copies_on_file_total`, and rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/undeliverable_pct_exactly_at_restrict_boundary
    """
    rounds_up = register_publication(
        name="Rounds Up Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    add_subscriber(
        rounds_up["id"],
        company_name="Kilo Ratio Works",
        subscription_class="PAID",
        copies=951,
        paid_amount_cents=76080,
    )
    up_wanderer = add_subscriber(
        rounds_up["id"],
        company_name="Lima Ratio Works",
        subscription_class="CONTROLLED",
        copies=50,
    )
    bounce_twice(up_wanderer["id"])

    stays_open = register_publication(
        name="Stays Open Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    add_subscriber(
        stays_open["id"],
        company_name="Mike Ratio Works",
        subscription_class="PAID",
        copies=951,
        paid_amount_cents=76080,
    )
    open_wanderer = add_subscriber(
        stays_open["id"],
        company_name="November Ratio Works",
        subscription_class="CONTROLLED",
        copies=49,
    )
    bounce_twice(open_wanderer["id"])

    up_sweep = run_hygiene_sweep(rounds_up["id"], run_type="UNDELIVERABLE_SWEEP")
    assert up_sweep["removed_count"] == 1
    restricted = read_publication(rounds_up["id"])
    assert_ledger_buckets(
        restricted, total=1001, deliverable=951, undeliverable=0, removed=50
    )
    # 50 of 1,001 is 4.9950…, which rounds to 5.00 and therefore restricts.
    assert_pct(restricted["undeliverable_pct"], 5.00)
    assert up_sweep["posture_after"] == "RESTRICTED"
    assert restricted["audit_posture"] == "RESTRICTED"

    open_sweep = run_hygiene_sweep(stays_open["id"], run_type="UNDELIVERABLE_SWEEP")
    assert open_sweep["removed_count"] == 1
    unrestricted = read_publication(stays_open["id"])
    assert_ledger_buckets(
        unrestricted, total=1000, deliverable=951, undeliverable=0, removed=49
    )
    # One copy fewer in the numerator is 4.90, and nothing rounds it up to 5.00.
    assert_pct(unrestricted["undeliverable_pct"], 4.90)
    assert open_sweep["posture_before"] == "OPEN"
    assert open_sweep["posture_after"] == "OPEN"
    assert unrestricted["audit_posture"] == "OPEN"
