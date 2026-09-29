"""Consumer rights requests: verification, deadlines and the deletion fan-out.

Every test builds its own state from scratch because the server is relaunched
with an empty database before each test.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from test_helpers import (
    ApiClient,
    ApiErrorId,
    REASON_REQUEST_DENIED,
    activate_mapping,
    build_share_disclosure_chain,
    build_verified_delete_request,
    create_approved_assessment,
    create_consumer,
    create_element,
    create_executed_vendor,
    create_mapping,
    create_product,
    create_purpose,
    file_request,
    make_consumer_headers,
    make_privacy_officer_headers,
    read_consumer,
    read_product,
    set_clock,
    tasks_for_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_request,
)

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse a server-rendered ISO 8601 UTC instant, whatever its precision."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant(actual: Any, expected: str, label: str) -> None:
    """Assert a stamped instant equals the expected UTC instant exactly."""
    assert actual is not None, f"{label} must be stamped, got null"
    assert _instant(actual) == _instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def _read_request(request_id: str, api: ApiClient) -> dict[str, Any]:
    return validate_success(
        api.get_consumer_request(request_id, make_privacy_officer_headers())
    )


def _read_task(task_id: str, api: ApiClient) -> dict[str, Any]:
    return validate_success(
        api.get_deletion_task(task_id, make_privacy_officer_headers())
    )


def _read_consent(record_id: str, api: ApiClient) -> dict[str, Any]:
    return validate_success(
        api.get_consent_record(record_id, make_privacy_officer_headers())
    )


def _tasks_by_vendor(request_id: str, api: ApiClient) -> dict[str, dict[str, Any]]:
    return {task["vendor_id"]: task for task in tasks_for_request(request_id, api)}


# ---------------------------------------------------------------------------
# The governing response deadline: a nested minimum
# ---------------------------------------------------------------------------


def test_verified_delete_deadline_takes_the_thirty_day_clock_over_the_extension(
    api: ApiClient,
) -> None:
    """A granted extension is overridden by the verification-anchored DELETE clock.

    PRD §3.7: "It starts from a base deadline of forty-five days after `received_at`."
    PRD §3.7: "If `extension_granted` is true, the extended deadline is a further
    forty-five days beyond the base — the single permitted extension doubles the
    response window to ninety days from receipt — and otherwise the extended
    deadline is simply the base."
    PRD §3.7: "The governing `response_deadline_at` is then whichever is earlier of
    two candidates, depending on the `request_kind`."
    PRD §3.7: "For a `DELETE` request whose `verified_at` is not null, it is the
    earlier of the extended deadline and thirty days after `verified_at`, because
    deletion must complete promptly once identity is settled regardless of the outer
    window."
    PRD §3.7: "**Step five** covers the empty case: when step one selects no vendor at
    all, no deletion task is created, `outstanding_task_count` stays at zero, and the
    request moves `VERIFIED → FULFILLED` inside the very same verification call,
    running fulfilment's own cascade described below."

    Design: Difficulty/combinatorial_formula/request_response_deadline_nested_min_over_extension_and_verification
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)

    request = file_request(consumer["id"], api, request_kind="DELETE")
    extended = validate_success(
        api.extend_consumer_request(request["id"], make_privacy_officer_headers())
    )
    assert extended["extension_granted"] is True
    assert_instant(
        extended["response_deadline_at"],
        "2026-11-08T00:00:00Z",
        "unverified DELETE response_deadline_at",
    )

    set_clock("2026-08-15T00:00:00Z", api)
    verified = validate_success(
        api.verify_consumer_request(
            request["id"],
            {"verification_token": consumer["verification_token"]},
            make_privacy_officer_headers(),
        )
    )

    assert verified["extension_granted"] is True
    assert_instant(verified["verified_at"], "2026-08-15T00:00:00Z", "verified_at")
    assert_instant(
        verified["response_deadline_at"],
        "2026-09-14T00:00:00Z",
        "verified DELETE response_deadline_at",
    )
    assert _instant(verified["response_deadline_at"]) != _instant(
        "2026-11-08T00:00:00Z"
    ), "the extended deadline must not govern once the DELETE clock is shorter"
    assert verified["outstanding_task_count"] == 0
    assert verified["state"] == "FULFILLED"


def test_confirm_request_deadline_stays_thirty_days_from_receipt_after_an_extension(
    api: ApiClient,
) -> None:
    """A CONFIRM request is due thirty days from receipt whatever the extension.

    PRD §3.7: "The deadline computation runs on filing, again on successful
    verification, and again whenever the extension is taken."
    PRD §3.7: "It starts from a base deadline of forty-five days after `received_at`."
    PRD §3.7: "If `extension_granted` is true, the extended deadline is a further
    forty-five days beyond the base — the single permitted extension doubles the
    response window to ninety days from receipt — and otherwise the extended
    deadline is simply the base."
    PRD §3.7: "For a `CONFIRM` request, it is the earlier of the extended deadline
    and thirty days after `received_at`, so a mere confirmation of processing is
    always due within thirty days of receipt no matter what extension was taken."

    Design: Difficulty/combinatorial_formula/request_response_deadline_nested_min_over_extension_and_verification
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)

    filed = validate_success(
        api.create_consumer_request(
            {
                "consumer_id": consumer["id"],
                "request_kind": "CONFIRM",
                "submitted_channel": "IN_APP",
            },
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )
    assert filed["extension_granted"] is False
    assert_instant(filed["received_at"], "2026-08-10T00:00:00Z", "received_at")
    assert_instant(
        filed["response_deadline_at"],
        "2026-09-09T00:00:00Z",
        "CONFIRM response_deadline_at on filing",
    )

    extended = validate_success(
        api.extend_consumer_request(filed["id"], make_privacy_officer_headers())
    )
    assert extended["extension_granted"] is True
    assert_instant(
        extended["response_deadline_at"],
        "2026-09-09T00:00:00Z",
        "CONFIRM response_deadline_at after the extension",
    )
    assert _instant(extended["response_deadline_at"]) != _instant(
        "2026-11-08T00:00:00Z"
    ), "the thirty-day confirmation cap must survive the extension"


# ---------------------------------------------------------------------------
# The bounded verification cycle
# ---------------------------------------------------------------------------


def test_fourth_request_for_identity_information_is_refused_after_three_rounds(
    api: ApiClient,
) -> None:
    """The verification loop is bounded at three rounds.

    PRD §3.7: "This `RECEIVED → VERIFICATION_PENDING → RECEIVED` loop is bounded at
    three rounds: asking again is admitted only while `verification_rounds_used` is
    strictly below three, and the fourth ask is refused with
    `ERR_VERIFICATION_ROUNDS_EXHAUSTED`."
    PRD §3.7: "`verification_window_ends_at` is null in every state other than
    `VERIFICATION_PENDING`."

    Design: Difficulty/non_linear_state_machine/consumer_request_verification_cycle_bounded_at_three_rounds
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )

    for _ in range(3):
        validate_success(
            api.request_more_info(request["id"], make_privacy_officer_headers())
        )
        validate_success(
            api.resubmit_identity(
                request["id"], make_consumer_headers(consumer["id"])
            )
        )

    response = api.request_more_info(request["id"], make_privacy_officer_headers())
    validate_error(response, ApiErrorId.VERIFICATION_ROUNDS_EXHAUSTED.value)

    after = _read_request(request["id"], api)
    assert after["verification_rounds_used"] == 3
    assert after["state"] == "RECEIVED"
    assert after["verification_window_ends_at"] is None


def test_verification_cycle_increments_rounds_and_stamps_then_clears_the_window(
    api: ApiClient,
) -> None:
    """Each traversal of the loop increments the round count and reopens the window.

    PRD §3.7: "When the officer needs more from the requester, asking for additional
    identity information moves the request `RECEIVED → VERIFICATION_PENDING`,
    increments `verification_rounds_used` by one, and sets
    `verification_window_ends_at` to ten days after the logical clock."
    PRD §3.7: "The consumer answers by resubmitting identity information, which moves
    the request `VERIFICATION_PENDING → RECEIVED` and clears
    `verification_window_ends_at` back to null; it is admitted only while the logical
    clock is not later than `verification_window_ends_at`, and a late answer is
    refused with `ERR_VERIFICATION_WINDOW_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/consumer_request_verification_cycle_bounded_at_three_rounds
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )
    assert request["verification_rounds_used"] == 0

    for expected_round in (1, 2):
        pending = validate_success(
            api.request_more_info(request["id"], make_privacy_officer_headers())
        )
        assert pending["state"] == "VERIFICATION_PENDING"
        assert pending["verification_rounds_used"] == expected_round
        assert_instant(
            pending["verification_window_ends_at"],
            "2026-08-20T00:00:00Z",
            "verification_window_ends_at",
        )

        answered = validate_success(
            api.resubmit_identity(
                request["id"], make_consumer_headers(consumer["id"])
            )
        )
        assert answered["state"] == "RECEIVED"
        assert answered["verification_rounds_used"] == expected_round
        assert answered["verification_window_ends_at"] is None


# ---------------------------------------------------------------------------
# The confirmation cascade
# ---------------------------------------------------------------------------


def test_confirming_the_last_deletion_task_fulfills_the_request_and_withdraws_consent(
    api: ApiClient,
) -> None:
    """One confirmation drives task, request, consent record and product counter.

    PRD §3.7: "Notifying a task moves it `PENDING → NOTIFIED`, increments
    `attempt_count` by one, and sets `due_at` to the logical clock plus that vendor's
    `deletion_sla_days` days — so a vendor with a thirty-day SLA is due a month out
    while one with a seven-day SLA is due within the week."
    PRD §3.7: "Recording the vendor's confirmation moves the task
    `NOTIFIED → CONFIRMED` and stamps `confirmed_at` with the logical clock; its
    first cascade hop recomputes the parent request's `outstanding_task_count`, and
    its second hop, because that count has reached zero, moves the parent request
    `VERIFIED → FULFILLED` and runs the request's own fulfilment hops."
    PRD §3.7: "For a `DELETE` request, fulfilment cascades into consent: its third
    hop takes the consumer's consent record whose `record_state` is `ACTIVE` and
    withdraws every granted axis on it — `collection_state` becomes `WITHDRAWN` if it
    was `GRANTED`, `sharing_state` becomes `WITHDRAWN` if it was `GRANTED`, and
    `sale_state` becomes `REVOKED` if it was `AUTHORIZED` — setting
    `last_withdrawn_axis` to `COLLECT`, `last_withdrawn_at` to the logical clock, and
    `processing_halt_deadline_at` to fifteen days after that, and recomputes the
    consumer's `deletion_completed_count`."
    PRD §3.7: "Its fourth hop, because that record's `sharing_state` left `GRANTED`,
    decrements the product's `active_share_consent_count` by one."

    Design: Difficulty/transitive_cascade/deletion_task_confirmation_cascade_fulfills_request_and_withdraws_consent
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    product_id = chain["product"]["id"]

    scenario = build_verified_delete_request(product_id, api)
    assert read_product(product_id, api)["active_share_consent_count"] == 1
    assert len(scenario["tasks"]) == 1
    task_id = scenario["tasks"][0]["id"]

    notified = validate_success(
        api.notify_deletion_task(task_id, make_privacy_officer_headers())
    )
    assert notified["state"] == "NOTIFIED"
    assert notified["attempt_count"] == 1
    assert_instant(notified["due_at"], "2026-09-09T00:00:00Z", "due_at")

    confirmed = validate_success(
        api.confirm_deletion_task(task_id, make_privacy_officer_headers())
    )
    assert confirmed["state"] == "CONFIRMED"
    assert_instant(confirmed["confirmed_at"], "2026-08-10T00:00:00Z", "confirmed_at")
    assert_instant(confirmed["due_at"], "2026-09-09T00:00:00Z", "due_at")

    request = _read_request(scenario["request"]["id"], api)
    assert request["outstanding_task_count"] == 0
    assert request["state"] == "FULFILLED"

    record = _read_consent(scenario["consent_record"]["id"], api)
    assert record["collection_state"] == "WITHDRAWN"
    assert record["sharing_state"] == "WITHDRAWN"
    assert record["last_withdrawn_axis"] == "COLLECT"
    assert_instant(record["last_withdrawn_at"], "2026-08-10T00:00:00Z", "last_withdrawn_at")
    assert_instant(
        record["processing_halt_deadline_at"],
        "2026-08-25T00:00:00Z",
        "processing_halt_deadline_at",
    )

    assert read_consumer(scenario["consumer"]["id"], api)["deletion_completed_count"] == 1
    assert read_product(product_id, api)["active_share_consent_count"] == 0


def test_confirmation_cascade_revokes_an_authorized_sale_axis_as_well(
    api: ApiClient,
) -> None:
    """The consent hop revokes the sale axis alongside collection and sharing.

    PRD §3.7: "Recording the vendor's confirmation moves the task
    `NOTIFIED → CONFIRMED` and stamps `confirmed_at` with the logical clock; its
    first cascade hop recomputes the parent request's `outstanding_task_count`, and
    its second hop, because that count has reached zero, moves the parent request
    `VERIFIED → FULFILLED` and runs the request's own fulfilment hops."
    PRD §3.7: "For a `DELETE` request, fulfilment cascades into consent: its third
    hop takes the consumer's consent record whose `record_state` is `ACTIVE` and
    withdraws every granted axis on it — `collection_state` becomes `WITHDRAWN` if it
    was `GRANTED`, `sharing_state` becomes `WITHDRAWN` if it was `GRANTED`, and
    `sale_state` becomes `REVOKED` if it was `AUTHORIZED` — setting
    `last_withdrawn_axis` to `COLLECT`, `last_withdrawn_at` to the logical clock, and
    `processing_halt_deadline_at` to fifteen days after that, and recomputes the
    consumer's `deletion_completed_count`."
    PRD §3.7: "Its fourth hop, because that record's `sharing_state` left `GRANTED`,
    decrements the product's `active_share_consent_count` by one."

    Design: Difficulty/transitive_cascade/deletion_task_confirmation_cascade_fulfills_request_and_withdraws_consent
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    product_id = chain["product"]["id"]

    scenario = build_verified_delete_request(
        product_id, api, axes=("COLLECT", "SHARE", "SELL")
    )
    record = _read_consent(scenario["consent_record"]["id"], api)
    assert record["sale_state"] == "AUTHORIZED"

    task_id = scenario["tasks"][0]["id"]
    validate_success(api.notify_deletion_task(task_id, make_privacy_officer_headers()))
    validate_success(api.confirm_deletion_task(task_id, make_privacy_officer_headers()))

    assert _read_request(scenario["request"]["id"], api)["state"] == "FULFILLED"

    record = _read_consent(scenario["consent_record"]["id"], api)
    assert record["record_state"] == "ACTIVE"
    assert record["collection_state"] == "WITHDRAWN"
    assert record["sharing_state"] == "WITHDRAWN"
    assert record["sale_state"] == "REVOKED"
    assert record["last_withdrawn_axis"] == "COLLECT"
    assert read_product(product_id, api)["active_share_consent_count"] == 0


# ---------------------------------------------------------------------------
# The zero-cardinality fan-out
# ---------------------------------------------------------------------------


def test_proposed_mapping_selects_no_vendor_and_the_delete_request_self_fulfills(
    api: ApiClient,
) -> None:
    """A mapping still in PROPOSED is outside the fan-out's candidate set.

    PRD §3.7: "**Step one** takes the distinct `vendor_id` values over the
    element-purpose mappings that satisfy all of the following at once: `status` is
    `ACTIVE`; `regulated_flag` is true; `vendor_id` is non-null; the referenced
    processing purpose's `activity_kind` is `SHARE` or `SELL`; the referenced data
    element belongs to the same app product as the requesting consumer; and the
    referenced vendor's `agreement_state` is `EXECUTED`."
    PRD §3.7: "**Step five** covers the empty case: when step one selects no vendor at
    all, no deletion task is created, `outstanding_task_count` stays at zero, and the
    request moves `VERIFIED → FULFILLED` inside the very same verification call,
    running fulfilment's own cascade described below."

    Design: Difficulty/boundary_precision_check/empty_vendor_candidate_set_auto_fulfills_delete_request_at_zero_fanout
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    element = create_element(product["id"], api)
    create_approved_assessment(product["id"], api)
    purpose = create_purpose(
        product["id"],
        api,
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
        description_text="Share with advertising partners",
    )
    vendor = create_executed_vendor(product["id"], api)
    mapping = create_mapping(
        element["id"], purpose["id"], api, vendor_id=vendor["id"]
    )
    assert mapping["status"] == "PROPOSED"

    consumer = create_consumer(product["id"], api)
    request = file_request(consumer["id"], api, request_kind="DELETE")

    verified = validate_success(
        api.verify_consumer_request(
            request["id"],
            {"verification_token": consumer["verification_token"]},
            make_privacy_officer_headers(),
        )
    )
    assert verified["state"] == "FULFILLED"
    assert verified["outstanding_task_count"] == 0
    assert_instant(
        verified["response_deadline_at"],
        "2026-09-09T00:00:00Z",
        "verified DELETE response_deadline_at",
    )

    assert validate_success(
        api.get_element_purpose_mapping(mapping["id"], make_privacy_officer_headers())
    )["status"] == "PROPOSED"
    assert read_consumer(consumer["id"], api)["deletion_completed_count"] == 1

    _, meta = validate_paginated(
        api.list_deletion_tasks(
            make_privacy_officer_headers(), {"consumer_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_active_mapping_over_a_non_regulated_element_selects_no_vendor(
    api: ApiClient,
) -> None:
    """An ACTIVE SHARE mapping whose `regulated_flag` is false is not selected.

    PRD §3.7: "**Step one** takes the distinct `vendor_id` values over the
    element-purpose mappings that satisfy all of the following at once: `status` is
    `ACTIVE`; `regulated_flag` is true; `vendor_id` is non-null; the referenced
    processing purpose's `activity_kind` is `SHARE` or `SELL`; the referenced data
    element belongs to the same app product as the requesting consumer; and the
    referenced vendor's `agreement_state` is `EXECUTED`."
    PRD §3.7: "**Step five** covers the empty case: when step one selects no vendor at
    all, no deletion task is created, `outstanding_task_count` stays at zero, and the
    request moves `VERIFIED → FULFILLED` inside the very same verification call,
    running fulfilment's own cascade described below."

    Design: Difficulty/boundary_precision_check/empty_vendor_candidate_set_auto_fulfills_delete_request_at_zero_fanout
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    element = create_element(
        product["id"],
        api,
        display_name="Marketing newsletter opt-in",
        health_signal_kind="NON_HEALTH",
    )
    assert element["chd_classification"] == "NON_CHD"
    create_approved_assessment(product["id"], api)
    purpose = create_purpose(
        product["id"],
        api,
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
        description_text="Share with advertising partners",
    )
    vendor = create_executed_vendor(product["id"], api)
    mapping = create_mapping(
        element["id"], purpose["id"], api, vendor_id=vendor["id"]
    )
    assert mapping["regulated_flag"] is False
    mapping = activate_mapping(mapping["id"], api)
    assert mapping["status"] == "ACTIVE"
    assert mapping["regulated_flag"] is False

    consumer = create_consumer(product["id"], api)
    request = file_request(consumer["id"], api, request_kind="DELETE")
    verified = validate_success(
        api.verify_consumer_request(
            request["id"],
            {"verification_token": consumer["verification_token"]},
            make_privacy_officer_headers(),
        )
    )
    assert verified["state"] == "FULFILLED"
    assert verified["outstanding_task_count"] == 0

    _, meta = validate_paginated(
        api.list_deletion_tasks(
            make_privacy_officer_headers(), {"consumer_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Request and task state machines
# ---------------------------------------------------------------------------


def test_newly_filed_access_request_starts_in_received_with_a_forty_five_day_deadline(
    api: ApiClient,
) -> None:
    """Filing lands the request in RECEIVED with the base deadline already stamped.

    PRD §3.7: "Filing stamps `received_at` from the logical clock, creates the
    request in `RECEIVED` with `verification_rounds_used` at zero,
    `extension_granted` false, `outstanding_task_count` at zero, and
    `verification_window_ends_at`, `verified_at` and `denial_reason` all null, and
    computes the governing `response_deadline_at`."
    PRD §3.7: "It starts from a base deadline of forty-five days after `received_at`."
    PRD §3.7: "In every other case — an `ACCESS` request, or a `DELETE` request not
    yet verified — the governing deadline is the extended deadline itself."

    Design: Corner/state_machines/initial_state_new_consumer_request_starts_in_received
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)

    filed = validate_success(
        api.create_consumer_request(
            {
                "consumer_id": consumer["id"],
                "request_kind": "ACCESS",
                "submitted_channel": "WEB_FORM",
            },
            make_consumer_headers(consumer["id"]),
        ),
        201,
    )

    assert filed["state"] == "RECEIVED"
    assert_instant(filed["received_at"], "2026-08-10T00:00:00Z", "received_at")
    assert filed["verification_rounds_used"] == 0
    assert filed["extension_granted"] is False
    assert filed["outstanding_task_count"] == 0
    assert filed["verification_window_ends_at"] is None
    assert filed["verified_at"] is None
    assert filed["denial_reason"] is None
    assert_instant(
        filed["response_deadline_at"],
        "2026-09-24T00:00:00Z",
        "ACCESS response_deadline_at",
    )


def test_confirming_a_pending_deletion_task_is_a_from_state_mismatch(
    api: ApiClient,
) -> None:
    """Confirmation is declared only out of NOTIFIED, so PENDING is inadmissible.

    PRD §3.7: "Recording the vendor's confirmation moves the task
    `NOTIFIED → CONFIRMED` and stamps `confirmed_at` with the logical clock; its
    first cascade hop recomputes the parent request's `outstanding_task_count`, and
    its second hop, because that count has reached zero, moves the parent request
    `VERIFIED → FULFILLED` and runs the request's own fulfilment hops."
    PRD §2.7: "From-state admissibility: the target must currently sit in a state
    from which the requested transition is declared."
    PRD §2.7: "A data element action that requires an `ACTIVE` element fails with
    `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in
    `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or
    reissue whose vendor agreement is not `EXECUTED` fails with
    `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`; a target already sitting in one of its
    terminal states fails with `ERR_ALREADY_TERMINAL`; every other from-state
    mismatch fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invalid_transition_confirm_pending_deletion_task_rejected
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    scenario = build_verified_delete_request(chain["product"]["id"], api)
    task_id = scenario["tasks"][0]["id"]
    assert scenario["tasks"][0]["state"] == "PENDING"

    response = api.confirm_deletion_task(task_id, make_privacy_officer_headers())
    validate_error(response, ApiErrorId.INVALID_STATE.value)

    task = _read_task(task_id, api)
    assert task["state"] == "PENDING"
    assert task["confirmed_at"] is None

    request = _read_request(scenario["request"]["id"], api)
    assert request["outstanding_task_count"] == 1
    assert request["state"] == "VERIFIED"


def test_notifying_a_task_whose_vendor_agreement_was_terminated_is_refused(
    api: ApiClient,
) -> None:
    """The notify edge requires the recipient vendor still to be EXECUTED.

    PRD §3.7: "Notification requires the vendor's `agreement_state` to be `EXECUTED`,
    failing which the refusal is `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`, and is admitted
    only while `attempt_count` is strictly below two."
    PRD §3.4: "Hop two, because this vendor's agreement has ended, moves every
    element-purpose mapping whose `vendor_id` names this vendor and whose `status` is
    `ACTIVE` from `ACTIVE → SUSPENDED`, with `suspension_reason` set to
    `VENDOR_AGREEMENT_TERMINATED`."

    Design: Corner/state_machines/precondition_enforcement_notify_requires_executed_vendor_agreement
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    scenario = build_verified_delete_request(chain["product"]["id"], api)
    task_id = scenario["tasks"][0]["id"]

    validate_success(
        api.terminate_vendor_agreement(
            chain["vendor"]["id"], make_privacy_officer_headers()
        )
    )

    response = api.notify_deletion_task(task_id, make_privacy_officer_headers())
    validate_error(response, ApiErrorId.VENDOR_AGREEMENT_NOT_EXECUTED.value)

    task = _read_task(task_id, api)
    assert task["state"] == "PENDING"
    assert task["attempt_count"] == 0
    assert task["due_at"] is None

    mapping = validate_success(
        api.get_element_purpose_mapping(
            chain["mapping"]["id"], make_privacy_officer_headers()
        )
    )
    assert mapping["status"] == "SUSPENDED"


def test_denying_a_verified_request_fails_only_the_still_open_deletion_tasks(
    api: ApiClient,
) -> None:
    """The deny cascade touches open tasks and leaves a confirmed one alone.

    PRD §3.7: "Denying from `VERIFIED` moves it `VERIFIED → DENIED`, records
    `denial_reason`, and additionally moves every deletion task on the request whose
    `state` is `PENDING`, `NOTIFIED` or `FAILED` into `FAILED` — a
    `PENDING → FAILED` move for the untouched ones and a `NOTIFIED → FAILED` move for
    the outstanding ones — with `failure_reason` set to `REQUEST_DENIED` in each case,
    recomputing `outstanding_task_count` as it goes."

    Design: Corner/state_machines/conditional_cascade_denying_verified_request_fails_only_open_tasks
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    element = create_element(product["id"], api)
    create_approved_assessment(product["id"], api)
    purpose_a = create_purpose(
        product["id"],
        api,
        purpose_kind="ADVERTISING",
        activity_kind="SHARE",
        description_text="Share with advertising partners",
    )
    purpose_b = create_purpose(
        product["id"],
        api,
        purpose_kind="ANALYTICS",
        activity_kind="SHARE",
        description_text="Share with the analytics processor",
    )
    vendor_a = create_executed_vendor(product["id"], api)
    vendor_b = create_executed_vendor(
        product["id"], api, vendor_kind="PROCESSOR", deletion_sla_days=15
    )
    mapping_a = create_mapping(
        element["id"], purpose_a["id"], api, vendor_id=vendor_a["id"]
    )
    mapping_b = create_mapping(
        element["id"], purpose_b["id"], api, vendor_id=vendor_b["id"]
    )
    activate_mapping(mapping_a["id"], api)
    activate_mapping(mapping_b["id"], api)

    consumer = create_consumer(product["id"], api)
    request = file_request(consumer["id"], api, request_kind="DELETE")
    request = verify_request(request["id"], consumer["verification_token"], api)

    tasks = _tasks_by_vendor(request["id"], api)
    assert set(tasks) == {vendor_a["id"], vendor_b["id"]}
    task_a_id = tasks[vendor_a["id"]]["id"]
    task_b_id = tasks[vendor_b["id"]]["id"]

    validate_success(api.notify_deletion_task(task_a_id, make_privacy_officer_headers()))
    validate_success(api.confirm_deletion_task(task_a_id, make_privacy_officer_headers()))
    validate_success(api.notify_deletion_task(task_b_id, make_privacy_officer_headers()))
    assert _read_request(request["id"], api)["state"] == "VERIFIED"

    denied = validate_success(
        api.deny_consumer_request(
            request["id"],
            {"denial_reason": "Identity could not be corroborated"},
            make_privacy_officer_headers(),
        )
    )
    assert denied["state"] == "DENIED"
    assert denied["denial_reason"] == "Identity could not be corroborated"

    task_a = _read_task(task_a_id, api)
    assert task_a["state"] == "CONFIRMED"
    assert task_a["failure_reason"] is None

    task_b = _read_task(task_b_id, api)
    assert task_b["state"] == "FAILED"
    assert task_b["failure_reason"] == REASON_REQUEST_DENIED


# ---------------------------------------------------------------------------
# Validations and error triggerability
# ---------------------------------------------------------------------------


def test_resubmitting_identity_after_the_verification_window_closed_is_refused(
    api: ApiClient,
) -> None:
    """A late answer to a request for more identity information is refused.

    PRD §3.7: "When the officer needs more from the requester, asking for additional
    identity information moves the request `RECEIVED → VERIFICATION_PENDING`,
    increments `verification_rounds_used` by one, and sets
    `verification_window_ends_at` to ten days after the logical clock."
    PRD §3.7: "The consumer answers by resubmitting identity information, which moves
    the request `VERIFICATION_PENDING → RECEIVED` and clears
    `verification_window_ends_at` back to null; it is admitted only while the logical
    clock is not later than `verification_window_ends_at`, and a late answer is
    refused with `ERR_VERIFICATION_WINDOW_EXPIRED`."

    Design: Corner/validations/temporal_validation_resubmit_identity_after_the_verification_window_rejected
    """
    set_clock("2026-08-12T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )
    pending = validate_success(
        api.request_more_info(request["id"], make_privacy_officer_headers())
    )
    assert_instant(
        pending["verification_window_ends_at"],
        "2026-08-22T00:00:00Z",
        "verification_window_ends_at",
    )

    set_clock("2026-08-23T00:00:00Z", api)
    response = api.resubmit_identity(
        request["id"], make_consumer_headers(consumer["id"])
    )
    validate_error(response, ApiErrorId.VERIFICATION_WINDOW_EXPIRED.value)

    after = _read_request(request["id"], api)
    assert after["state"] == "VERIFICATION_PENDING"
    assert after["verification_rounds_used"] == 1
    assert_instant(
        after["verification_window_ends_at"],
        "2026-08-22T00:00:00Z",
        "verification_window_ends_at",
    )


def test_second_extension_attempt_is_refused_and_the_deadline_does_not_move(
    api: ApiClient,
) -> None:
    """The response-deadline extension may be taken exactly once.

    PRD §3.7: "A `PrivacyOfficer` may take the extension exactly once, which sets
    `extension_granted` to true and recomputes `response_deadline_at`."
    PRD §3.7: "A second attempt is refused with `ERR_EXTENSION_ALREADY_GRANTED`."
    PRD §3.7: "If `extension_granted` is true, the extended deadline is a further
    forty-five days beyond the base — the single permitted extension doubles the
    response window to ninety days from receipt — and otherwise the extended
    deadline is simply the base."

    Design: Corner/errors/error_extension_already_granted_on_second_extend
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )
    assert_instant(
        request["response_deadline_at"],
        "2026-09-24T00:00:00Z",
        "ACCESS response_deadline_at before the extension",
    )

    extended = validate_success(
        api.extend_consumer_request(request["id"], make_privacy_officer_headers())
    )
    assert extended["extension_granted"] is True
    assert_instant(
        extended["response_deadline_at"],
        "2026-11-08T00:00:00Z",
        "ACCESS response_deadline_at after the extension",
    )

    response = api.extend_consumer_request(
        request["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.EXTENSION_ALREADY_GRANTED.value)

    after = _read_request(request["id"], api)
    assert after["extension_granted"] is True
    assert after["state"] == "RECEIVED"
    assert_instant(
        after["response_deadline_at"],
        "2026-11-08T00:00:00Z",
        "ACCESS response_deadline_at after the refused second extension",
    )


def test_verifying_with_the_wrong_token_leaves_the_request_unverified(
    api: ApiClient,
) -> None:
    """Verification requires the consumer's own minted token.

    PRD §3.7: "A `PrivacyOfficer` verifies the request from `RECEIVED` by submitting
    a `verification_token`, which must equal the token minted for that consumer at
    registration; a mismatch is refused with `ERR_VERIFICATION_TOKEN_MISMATCH`."
    PRD §3.7: "Successful verification moves the request `RECEIVED → VERIFIED`,
    stamps `verified_at` with the logical clock, and recomputes
    `response_deadline_at` — which for a `DELETE` request is where the thirty-day
    fulfilment clock first bites."

    Design: Corner/errors/error_verification_token_mismatch_on_verify
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(consumer["id"], api, request_kind="DELETE")

    response = api.verify_consumer_request(
        request["id"],
        {"verification_token": "not-the-issued-token"},
        make_privacy_officer_headers(),
    )
    validate_error(response, ApiErrorId.VERIFICATION_TOKEN_MISMATCH.value)

    after = _read_request(request["id"], api)
    assert after["state"] == "RECEIVED"
    assert after["verified_at"] is None
    assert after["outstanding_task_count"] == 0

    _, meta = validate_paginated(
        api.list_deletion_tasks(
            make_privacy_officer_headers(), {"consumer_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_fulfilling_after_the_response_deadline_has_passed_is_refused(
    api: ApiClient,
) -> None:
    """Fulfilment is inadmissible once the logical clock is past the deadline.

    PRD §3.7: "Fulfilment of the parent request, whether driven explicitly by the
    officer or by the last task's confirmation, is admitted only from `VERIFIED`,
    only when `outstanding_task_count` is zero — otherwise
    `ERR_DELETION_TASKS_OUTSTANDING` — and only while the logical clock is not later
    than `response_deadline_at`, a late fulfilment being refused with
    `ERR_RESPONSE_DEADLINE_PASSED`."
    PRD §3.7: "It starts from a base deadline of forty-five days after `received_at`."

    Design: Corner/errors/error_response_deadline_passed_on_fulfill
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api)
    request = file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )
    verified = verify_request(request["id"], consumer["verification_token"], api)
    assert verified["state"] == "VERIFIED"

    set_clock("2026-09-25T00:00:00Z", api)
    response = api.fulfill_consumer_request(
        request["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.RESPONSE_DEADLINE_PASSED.value)

    after = _read_request(request["id"], api)
    assert after["state"] == "VERIFIED"
    assert_instant(
        after["response_deadline_at"],
        "2026-09-24T00:00:00Z",
        "ACCESS response_deadline_at",
    )
    assert_instant(after["verified_at"], "2026-08-10T00:00:00Z", "verified_at")


def test_fulfilling_a_delete_request_with_an_outstanding_task_is_refused(
    api: ApiClient,
) -> None:
    """A pending downstream deletion obligation blocks manual fulfilment.

    PRD §3.7: "Fulfilment of the parent request, whether driven explicitly by the
    officer or by the last task's confirmation, is admitted only from `VERIFIED`,
    only when `outstanding_task_count` is zero — otherwise
    `ERR_DELETION_TASKS_OUTSTANDING` — and only while the logical clock is not later
    than `response_deadline_at`, a late fulfilment being refused with
    `ERR_RESPONSE_DEADLINE_PASSED`."
    PRD §3.7: "The request's `outstanding_task_count` is then recomputed as the
    number of its tasks whose `state` is `PENDING`, `NOTIFIED` or `FAILED`."

    Design: Corner/errors/error_deletion_tasks_outstanding_on_fulfill
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    scenario = build_verified_delete_request(chain["product"]["id"], api)
    assert scenario["request"]["outstanding_task_count"] == 1

    response = api.fulfill_consumer_request(
        scenario["request"]["id"], make_privacy_officer_headers()
    )
    validate_error(response, ApiErrorId.DELETION_TASKS_OUTSTANDING.value)

    after = _read_request(scenario["request"]["id"], api)
    assert after["state"] == "VERIFIED"
    assert after["outstanding_task_count"] == 1

    _, meta = validate_paginated(
        api.list_deletion_tasks(
            make_privacy_officer_headers(),
            {"consumer_request_id": scenario["request"]["id"], "state": "PENDING"},
        )
    )
    assert meta["total_count"] == 1


def test_third_notification_attempt_on_a_deletion_task_is_refused(
    api: ApiClient,
) -> None:
    """Notify plus one reissue exhaust the two permitted attempts.

    PRD §3.7: "Reissuing a failed instruction moves the task `FAILED → NOTIFIED`,
    increments `attempt_count` by one, clears `failure_reason` to null, and resets
    `due_at` to the logical clock plus the vendor's `deletion_sla_days` days; reissue
    requires the vendor's `agreement_state` to still be `EXECUTED` and is admitted
    only while `attempt_count` is strictly below two."
    PRD §3.7: "This `NOTIFIED → FAILED → NOTIFIED` loop is therefore bounded at two
    attempts in total, and an attempt beyond that — on notify or on reissue alike —
    is refused with `ERR_TASK_ATTEMPT_LIMIT`."
    PRD §3.7: "Recording a failure moves the task `NOTIFIED → FAILED`, records the
    supplied `failure_reason`, and recomputes the parent request's
    `outstanding_task_count`."

    Design: Corner/errors/error_task_attempt_limit_on_the_third_notification_attempt
    """
    set_clock("2026-08-10T00:00:00Z", api)
    chain = build_share_disclosure_chain(api)
    scenario = build_verified_delete_request(chain["product"]["id"], api)
    task_id = scenario["tasks"][0]["id"]

    first = validate_success(
        api.notify_deletion_task(task_id, make_privacy_officer_headers())
    )
    assert first["attempt_count"] == 1
    validate_success(
        api.fail_deletion_task(
            task_id,
            {"failure_reason": "No acknowledgement from the vendor"},
            make_privacy_officer_headers(),
        )
    )
    second = validate_success(
        api.reissue_deletion_task(task_id, make_privacy_officer_headers())
    )
    assert second["attempt_count"] == 2
    assert second["failure_reason"] is None
    validate_success(
        api.fail_deletion_task(
            task_id,
            {"failure_reason": "Second attempt also unacknowledged"},
            make_privacy_officer_headers(),
        )
    )

    response = api.reissue_deletion_task(task_id, make_privacy_officer_headers())
    validate_error(response, ApiErrorId.TASK_ATTEMPT_LIMIT.value)

    task = _read_task(task_id, api)
    assert task["state"] == "FAILED"
    assert task["attempt_count"] == 2
    assert task["failure_reason"] == "Second attempt also unacknowledged"

    request = _read_request(scenario["request"]["id"], api)
    assert request["state"] == "VERIFIED"
    assert request["outstanding_task_count"] == 1
