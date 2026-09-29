"""Which `error_id` comes back when one request breaks two rules at once.

Both pairs here are engineered so that a single call violates two separate
checks. The earlier check in the declared sequence must be the one reported, and
a twin call that violates only the later check proves the later check was live.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    make_dispute_reviewer_headers,
    make_shipper_headers,
    validate_error,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _resolved_and_open_notice_scenario():
    """Two identical shipments: notice A ends up `UPHELD`, notice B stays `ISSUED`,
    and the clock is then pushed past both dispute deadlines."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    first = fx.setup_issued_notice_scenario(
        env=env, pro_number="PRO9001", measured_total_weight_lb=520
    )
    second = fx.setup_issued_notice_scenario(
        env=env, pro_number="PRO9002", measured_total_weight_lb=520
    )

    dispute = fx.file_dispute(
        first["notice_id"], env["customer_id"], evidence_doc_count=1
    )
    fx.set_clock("2026-01-15T00:00:00Z")
    fx.resolve_dispute(
        dispute["id"], "UPHELD_CARRIER", resolution_note="Dimensioner evidence stands."
    )
    fx.set_clock("2026-03-01T00:00:00Z")

    return {
        "customer_id": env["customer_id"],
        "notice_a_id": first["notice_id"],
        "notice_b_id": second["notice_id"],
    }


def _self_issued_dispute_scenario():
    """The notice is issued by auditor aud-9, so a reviewer acting as aud-9 is
    reviewing its own issuance."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_captured_shipment_with_draft_notice(
        env=env, pro_number="PRO9101", measured_total_weight_lb=520
    )
    fx.issue_notice(scenario["notice_id"], auditor_user_id="aud-9")
    dispute = fx.file_dispute(
        scenario["notice_id"],
        scenario["customer_id"],
        claim_basis="EXCEPTION_AGREEMENT",
        evidence_doc_count=1,
    )
    scenario["dispute_id"] = dispute["id"]
    return scenario


def _malformed_partial_body():
    """A `PARTIAL` outcome with no `outcome_class_code` at all."""
    return {"outcome": "PARTIAL", "resolution_note": "Split the difference."}


def _late_filing_payload(notice_id):
    return factories.create_dispute_payload(
        notice_id, claim_basis="DENSITY_RECOMPUTE", evidence_doc_count=2
    )


# ==========================================================================
# State (step 9) beats the temporal window (step 13)
# ==========================================================================


def test_filing_on_a_resolved_notice_reports_the_state_code_not_the_window_code():
    """Notice A is both undisputable and past its deadline; the state code wins.

    PRD: "When several checks could reject the same request, the order in which
    they are evaluated is normative, because the client must be able to predict
    which `error_id` comes back. Checks are applied in the following sequence,
    and the first one that fails terminates the request"

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_dispute_window_on_resolved_notice
    """
    scenario = _resolved_and_open_notice_scenario()

    response = api_client.create_dispute(
        _late_filing_payload(scenario["notice_a_id"]),
        make_shipper_headers(scenario["customer_id"]),
    )

    body = validate_error(response, ApiErrorId.ERR_NOTICE_NOT_DISPUTABLE.value)
    assert body["error_id"] != ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, (
        "the state check sits earlier in the sequence than the temporal check"
    )


def test_filing_on_a_still_issued_notice_reports_the_closed_window():
    """Notice B isolates the temporal check, which does fire on its own.

    PRD: "that the current logical instant is at or before the notice's
    `dispute_deadline_at`, or `ERR_DISPUTE_WINDOW_CLOSED`"

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_dispute_window_on_resolved_notice
    """
    scenario = _resolved_and_open_notice_scenario()

    response = api_client.create_dispute(
        _late_filing_payload(scenario["notice_b_id"]),
        make_shipper_headers(scenario["customer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value)


def test_neither_refused_filing_disturbs_either_notice():
    """A refused filing is inert: no round is counted and no status moves.

    PRD: "Filing requires that the notice's `status` is `ISSUED` — a notice in
    any other status is rejected with `ERR_NOTICE_NOT_DISPUTABLE`"

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_dispute_window_on_resolved_notice
    """
    scenario = _resolved_and_open_notice_scenario()

    api_client.create_dispute(
        _late_filing_payload(scenario["notice_a_id"]),
        make_shipper_headers(scenario["customer_id"]),
    )
    api_client.create_dispute(
        _late_filing_payload(scenario["notice_b_id"]),
        make_shipper_headers(scenario["customer_id"]),
    )
    notice_a = fx.get_notice(scenario["notice_a_id"])
    notice_b = fx.get_notice(scenario["notice_b_id"])

    assert notice_a["status"] == "UPHELD"
    assert notice_a["dispute_round_count"] == 1, (
        "only the one successful filing in February counted a round"
    )
    assert notice_b["status"] == "ISSUED"
    assert notice_b["dispute_round_count"] == 0
    assert notice_b["dispute_deadline_at"].startswith("2026-02-09T08:00:00"), (
        f"a 30-day window from 2026-01-10T08:00:00Z closes on 2026-02-09T08:00:00Z, "
        f"got {notice_b['dispute_deadline_at']}"
    )


# ==========================================================================
# Segregation of duties (step 11) beats referential coherence (step 17)
# ==========================================================================


def test_self_review_is_refused_before_the_malformed_partial_outcome():
    """The reviewer is the notice's own issuer and the body is malformed; the
    segregation-of-duties code wins.

    PRD: "A `DisputeReviewer` may not request a supplement on, nor resolve, a
    dispute whose correction notice carries an `issued_by_user_id` equal to the
    reviewer's own `X-User-ID`. Either violation is rejected with
    `ERR_SOD_VIOLATION` at HTTP 403."

    Design: Difficulty/priority_pair_validation_conflict/sod_check_beats_partial_outcome_referential_check
    """
    scenario = _self_issued_dispute_scenario()

    response = api_client.resolve_dispute(
        scenario["dispute_id"],
        _malformed_partial_body(),
        make_dispute_reviewer_headers("aud-9"),
    )

    body = validate_error(response, ApiErrorId.ERR_SOD_VIOLATION.value)
    assert body["error_id"] != ApiErrorId.ERR_INVALID_PARTIAL_OUTCOME.value, (
        "segregation of duties sits earlier in the sequence than referential coherence"
    )


def test_an_untainted_reviewer_reaches_the_referential_check_instead():
    """The identical malformed body from a different reviewer is rejected on shape.

    PRD: "The reviewer supplies an `outcome` of `UPHELD_CARRIER`, `PARTIAL` or
    `OVERTURNED`, optionally a `resolution_note`, and an `outcome_class_code`
    that must be present when the outcome is `PARTIAL` and must be absent for the
    other two."

    Design: Difficulty/priority_pair_validation_conflict/sod_check_beats_partial_outcome_referential_check
    """
    scenario = _self_issued_dispute_scenario()

    response = api_client.resolve_dispute(
        scenario["dispute_id"],
        _malformed_partial_body(),
        make_dispute_reviewer_headers("rev-7"),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_PARTIAL_OUTCOME.value)


def test_both_refused_resolutions_leave_the_dispute_open_and_unattributed():
    """No reviewer is stamped and no outcome is recorded by a rejected resolution.

    PRD: "and in every case `outcome`, `outcome_class_code`, `reviewer_user_id`
    and `resolved_at` are recorded."

    Design: Difficulty/priority_pair_validation_conflict/sod_check_beats_partial_outcome_referential_check
    """
    scenario = _self_issued_dispute_scenario()

    api_client.resolve_dispute(
        scenario["dispute_id"],
        _malformed_partial_body(),
        make_dispute_reviewer_headers("aud-9"),
    )
    api_client.resolve_dispute(
        scenario["dispute_id"],
        _malformed_partial_body(),
        make_dispute_reviewer_headers("rev-7"),
    )
    dispute = fx.get_dispute(scenario["dispute_id"])
    notice = fx.get_notice(scenario["notice_id"])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert dispute["status"] == "OPEN"
    assert dispute["outcome"] is None
    assert dispute["reviewer_user_id"] is None
    assert notice["issued_by_user_id"] == "aud-9"
    assert notice["status"] == "DISPUTED"
    assert shipment["assessed_total_cents"] == 45314, (
        f"12500 plus a frozen 28314 delta plus a 4500 fee is 45314, "
        f"got {shipment['assessed_total_cents']}"
    )
