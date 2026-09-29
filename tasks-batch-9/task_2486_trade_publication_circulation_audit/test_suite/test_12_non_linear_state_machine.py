"""Non-linear lifecycles: two independent dimensions on one row, and a bounded review loop."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INFO_REQUEST_LIMIT_REACHED,
    ERR_INVALID_STATE,
    ERR_REQUEST_NOT_UNDER_REVIEW,
)
from test_helpers.assertions import assert_ledger_buckets, assert_pct
from test_helpers.factories import (
    request_info_payload,
    resubmit_payload,
    undeliverable_event_payload,
    verify_payload,
)
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


def bounce(subscriber_id, reason_code):
    response = api_client.record_undeliverable_event(
        subscriber_id, undeliverable_event_payload(reason_code=reason_code), MANAGER_HEADERS
    )
    return validate_success(response, 200)


def test_delivery_and_qualification_dimensions_advance_at_different_sweeps():
    """The flag tier leaves qualification alone; only the drop tier drags it along.

    "The recipient's `qualification_status` is untouched — a still-qualified
    recipient can be undeliverable, and that combination is exactly what the
    two-dimension design exists to represent."

    Design: Difficulty/non_linear_state_machine/subscriber_parallel_delivery_and_qualification_dimensions
    """
    publication = register_publication(
        name="Parallel Dimensions Monthly",
        industry_code="MANUFACTURING",
        undeliverable_restrict_pct=5.00,
    )
    add_complete_rule_set(publication["id"])
    steady = add_subscriber(
        publication["id"],
        company_name="Quebec Paid Presses",
        subscription_class="PAID",
        copies=950,
        paid_amount_cents=76000,
    )
    assert steady["qualification_status"] == "UNQUALIFIED"

    wanderer = add_subscriber(
        publication["id"],
        company_name="Romeo Directed Presses",
        subscription_class="CONTROLLED",
        copies=50,
    )
    document = attach_source_document(
        wanderer["id"], SPECIALIST_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    request = open_request(
        wanderer["id"],
        document["id"],
        wanderer["version"],
        headers=SPECIALIST_HEADERS,
        signed_at="2026-07-01T00:00:00Z",
    )
    review_request(request["id"])
    verify_request(request["id"], decision_reason="qualified")
    assert read_subscriber(wanderer["id"])["qualification_status"] == "QUALIFIED"

    first_bounce = bounce(wanderer["id"], "RETURNED_NO_FORWARDING")
    assert first_bounce["undeliverable_count"] == 1
    assert first_bounce["delivery_status"] == "DELIVERABLE"

    flagging = run_hygiene_sweep(publication["id"], run_type="UNDELIVERABLE_SWEEP")
    # One bounce is at least one but strictly fewer than the default threshold of 2.
    assert flagging["undeliverable_flagged_count"] == 1
    assert flagging["removed_count"] == 0
    assert flagging["requalification_required_count"] == 0

    flagged = read_subscriber(wanderer["id"])
    assert flagged["delivery_status"] == "UNDELIVERABLE"
    assert flagged["qualification_status"] == "QUALIFIED"

    after_flag = read_publication(publication["id"])
    assert_ledger_buckets(
        after_flag,
        total=1000,
        deliverable=950,
        undeliverable=50,
        removed=0,
    )
    assert_pct(after_flag["undeliverable_pct"], 5.00)

    second_bounce = bounce(wanderer["id"], "RETURNED_NO_FORWARDING")
    assert second_bounce["undeliverable_count"] == 2
    # The counter moved but the status did not; only a sweep acts on it.
    assert second_bounce["delivery_status"] == "UNDELIVERABLE"

    dropping = run_hygiene_sweep(publication["id"], run_type="UNDELIVERABLE_SWEEP")
    assert dropping["removed_count"] == 1
    assert dropping["requalification_required_count"] == 1
    assert dropping["undeliverable_flagged_count"] == 0

    dropped = read_subscriber(wanderer["id"])
    assert dropped["delivery_status"] == "REMOVED"
    assert dropped["qualification_status"] == "REQUALIFICATION_REQUIRED"

    after_drop = read_publication(publication["id"])
    assert_ledger_buckets(
        after_drop,
        total=1000,
        deliverable=950,
        undeliverable=0,
        removed=50,
    )
    # Both buckets sit in the numerator, so the ratio does not move.
    assert_pct(after_drop["undeliverable_pct"], 5.00)

    # The other recipient was never touched on either dimension.
    untouched = read_subscriber(steady["id"])
    assert untouched["qualification_status"] == "UNQUALIFIED"
    assert untouched["delivery_status"] == "DELIVERABLE"
    assert untouched["undeliverable_count"] == 0


def test_dropped_pending_recipient_is_reinstated_by_its_in_flight_verification():
    """A drop does not kill the request in flight, and verifying it walks delivery back.

    "The pending case has a deliberate wrinkle: the in-flight qualification request
    keeps its own status untouched, so it may still be reviewed and verified, and
    that verification will reinstate delivery exactly as §3.4 describes."

    Design: Difficulty/non_linear_state_machine/subscriber_parallel_delivery_and_qualification_dimensions
    """
    publication = register_publication(
        name="Reinstatement Monthly", industry_code="MANUFACTURING"
    )
    add_complete_rule_set(publication["id"])
    recipient = add_subscriber(
        publication["id"],
        company_name="Sierra Directed Presses",
        subscription_class="CONTROLLED",
        copies=100,
    )
    document = attach_source_document(
        recipient["id"], SPECIALIST_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    request = open_request(
        recipient["id"],
        document["id"],
        recipient["version"],
        headers=SPECIALIST_HEADERS,
        signed_at="2026-07-01T00:00:00Z",
    )
    reviewed = review_request(request["id"])
    assert reviewed["status"] == "UNDER_REVIEW"
    assert read_subscriber(recipient["id"])["qualification_status"] == "PENDING_QUALIFICATION"

    bounce(recipient["id"], "RETURNED_NO_FORWARDING")
    twice = bounce(recipient["id"], "RETURNED_NO_FORWARDING")
    assert twice["undeliverable_count"] == 2

    dropping = run_hygiene_sweep(publication["id"], undeliverable_threshold=2)
    # Dropped straight from DELIVERABLE, so the flag tier never applied.
    assert dropping["undeliverable_flagged_count"] == 0
    assert dropping["removed_count"] == 1
    assert dropping["requalification_required_count"] == 1

    dropped = read_subscriber(recipient["id"])
    assert dropped["delivery_status"] == "REMOVED"
    assert dropped["qualification_status"] == "REQUALIFICATION_REQUIRED"
    removed_ledger = read_publication(publication["id"])
    assert_ledger_buckets(
        removed_ledger, total=100, deliverable=0, undeliverable=0, removed=100
    )
    assert_pct(removed_ledger["undeliverable_pct"], 100.00)

    # The request itself was never touched by the sweep.
    in_flight = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert in_flight["status"] == "UNDER_REVIEW"
    assert in_flight["computed_score"] == 100

    verified = verify_request(request["id"], decision_reason="re-attested and verified")
    assert verified["status"] == "VERIFIED"

    reinstated = read_subscriber(recipient["id"])
    assert reinstated["delivery_status"] == "DELIVERABLE"
    assert reinstated["qualification_status"] == "QUALIFIED"
    # Verification is the only path back, and it clears the bounce history.
    assert reinstated["undeliverable_count"] == 0

    clean_ledger = read_publication(publication["id"])
    assert_ledger_buckets(
        clean_ledger, total=100, deliverable=100, undeliverable=0, removed=0
    )
    assert_pct(clean_ledger["undeliverable_pct"], 0.00)
    assert clean_ledger["audit_posture"] == "OPEN"


def opened_request(publication_name, company_name):
    """A publication with the full policy and one request ready for review."""
    publication = register_publication(
        name=publication_name, industry_code="MANUFACTURING"
    )
    add_complete_rule_set(publication["id"])
    recipient = add_subscriber(
        publication["id"],
        company_name=company_name,
        subscription_class="CONTROLLED",
        copies=40,
    )
    document = attach_source_document(
        recipient["id"], SPECIALIST_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    request = open_request(
        recipient["id"],
        document["id"],
        recipient["version"],
        headers=SPECIALIST_HEADERS,
        request_channel="TELEPHONE",
        signed_at="2026-08-01T00:00:00Z",
    )
    return publication, recipient, request


def ask_for_information(request_id, note):
    response = api_client.request_info_qualification_request(
        request_id, request_info_payload(info_request_note=note), SPECIALIST_HEADERS
    )
    return validate_success(response, 200)


def resubmit(request_id, **overrides):
    response = api_client.resubmit_qualification_request(
        request_id, resubmit_payload(**overrides), SPECIALIST_HEADERS
    )
    return validate_success(response, 200)


def test_third_information_request_is_refused_after_two_full_laps():
    """The loop is bounded by a counter that survives every lap, not by a state.

    "The loop is bounded at two round trips: the increment is only permitted while
    `info_request_count` is strictly below 2, so a third information request on the
    same paperwork is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED` and HTTP 409."

    Design: Difficulty/non_linear_state_machine/request_info_cycle_third_round_rejected
    """
    _, recipient, request = opened_request(
        "Bounded Loop Monthly", "Tango Directed Presses"
    )

    first_review = review_request(request["id"])
    # 45 + 30 + 25 with no channel bonus for TELEPHONE and a signature 0 months old.
    assert first_review["computed_score"] == 100
    assert first_review["info_request_count"] == 0

    first_ask = ask_for_information(request["id"], "please supply the plant address")
    assert first_ask["status"] == "INFO_REQUESTED"
    assert first_ask["info_request_count"] == 1

    back = resubmit(request["id"])
    assert back["status"] == "SUBMITTED"
    # Resubmission discards the stored score but never the lap counter.
    assert back["computed_score"] == 0
    assert back["info_request_count"] == 1

    second_review = review_request(request["id"])
    assert second_review["status"] == "UNDER_REVIEW"
    assert second_review["computed_score"] == 100
    assert second_review["info_request_count"] == 1

    second_ask = ask_for_information(request["id"], "the job title is still ambiguous")
    assert second_ask["info_request_count"] == 2

    resubmit(request["id"])
    third_review = review_request(request["id"])
    assert third_review["status"] == "UNDER_REVIEW"
    assert third_review["info_request_count"] == 2

    response = api_client.request_info_qualification_request(
        request["id"],
        request_info_payload(info_request_note="one more question"),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_INFO_REQUEST_LIMIT_REACHED, 409)

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["info_request_count"] == 2
    assert read_subscriber(recipient["id"])["qualification_status"] == "PENDING_QUALIFICATION"


def test_information_request_lap_resets_the_score_and_guards_the_other_exits():
    """INFO_REQUESTED is not UNDER_REVIEW, and the re-entry recomputes the score afresh.

    "Resubmission resets `computed_score` to 0, because the stored score described
    paperwork that no longer necessarily exists; the score is only recomputed when
    the request next enters review."

    Design: Difficulty/non_linear_state_machine/request_info_cycle_third_round_rejected
    """
    _, recipient, request = opened_request(
        "Lap Bookkeeping Monthly", "Uniform Directed Presses"
    )
    assert review_request(request["id"])["computed_score"] == 100

    asked = ask_for_information(request["id"], "confirm the purchasing role")
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["info_request_count"] == 1
    # Asking does not itself discard the score; only resubmission does.
    assert asked["computed_score"] == 100

    validate_error(
        api_client.review_qualification_request(
            request["id"], {"review_note": "reviewing mid-loop"}, SPECIALIST_HEADERS
        ),
        ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api_client.verify_qualification_request(
            request["id"], verify_payload(decision_reason="verifying mid-loop"), SPECIALIST_HEADERS
        ),
        ERR_REQUEST_NOT_UNDER_REVIEW,
        409,
    )

    restated = resubmit(request["id"], attested_purchasing_authority="NONE")
    assert restated["status"] == "SUBMITTED"
    assert restated["computed_score"] == 0
    assert restated["attested_purchasing_authority"] == "NONE"
    assert restated["info_request_count"] == 1

    rescored = review_request(request["id"])
    # 45 for job function plus 30 for industry; the restated authority scores 0.
    assert rescored["computed_score"] == 75
    assert rescored["info_request_count"] == 1

    verified = verify_request(request["id"], decision_reason="revised claim accepted")
    assert verified["status"] == "VERIFIED"
    assert verified["computed_score"] == 75

    qualified = read_subscriber(recipient["id"])
    assert qualified["qualification_status"] == "QUALIFIED"
    assert qualified["qualification_score"] == 75
    assert qualified["purchasing_authority_level"] == "NONE"
