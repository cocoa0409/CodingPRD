"""The supplement negotiation cycle and the education hold on dispute filing.

The reviewer-shipper exchange is a bounded cycle: each request buys the shipper
seven more days, and two ceilings close it. Filing itself depends on the shipper
account's education dimension rather than on anything about the notice.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_customer,
    assert_dispute,
    factories,
    make_dispute_reviewer_headers,
    make_shipper_headers,
    validate_error,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _open_dispute_scenario():
    """A notice issued on 2026-01-10 with a 30-day window, disputed once."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_issued_notice_scenario(
        env=env, pro_number="PRO6001", measured_total_weight_lb=520
    )
    dispute = fx.file_dispute(
        scenario["notice_id"],
        scenario["customer_id"],
        claim_basis="EVIDENCE_INSUFFICIENT",
        evidence_doc_count=1,
    )
    scenario["dispute_id"] = dispute["id"]
    scenario["dispute"] = dispute
    return scenario


def _education_scenario():
    """A shipper whose education threshold is a single strike, with one DRAFT notice."""
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        customer_overrides={
            "account_code": "REPEAT",
            "name": "Repeat Offender Co",
            "education_strike_interval": 1,
        },
    )
    scenario = fx.setup_captured_shipment_with_draft_notice(
        env=env, pro_number="PROC101", measured_total_weight_lb=520
    )
    assert scenario["notice"]["notice_type"] == "BOTH"
    return scenario


def _filing_payload(notice_id):
    return factories.create_dispute_payload(
        notice_id, claim_basis="DENSITY_RECOMPUTE", evidence_doc_count=2
    )


# ==========================================================================
# The supplement cycle
# ==========================================================================


def test_supplement_request_extends_the_deadline_by_seven_days():
    """The request moves both rows and buys the shipper a further week.

    PRD: "It moves the dispute `OPEN → SUPPLEMENT_REQUESTED` or `SUPPLEMENTED →
    SUPPLEMENT_REQUESTED`, stamps `reviewer_user_id` with the reviewer's
    `X-User-ID`, moves the notice `DISPUTED → EVIDENCE_REQUESTED`, increments
    `supplement_request_count` and extends `dispute_deadline_at` by a further 7
    days."

    Design: Difficulty/non_linear_state_machine/dispute_supplement_cycle_bounded_by_max_rounds
    """
    scenario = _open_dispute_scenario()
    assert scenario["notice"]["dispute_deadline_at"].startswith("2026-02-09T08:00:00")

    requested = fx.request_supplement(scenario["dispute_id"])
    notice = fx.get_notice(scenario["notice_id"])

    assert_dispute(requested)
    assert requested["status"] == "SUPPLEMENT_REQUESTED"
    assert requested["reviewer_user_id"] == "rev-1"
    assert notice["status"] == "EVIDENCE_REQUESTED"
    assert notice["supplement_request_count"] == 1
    assert notice["dispute_deadline_at"].startswith("2026-02-16T08:00:00"), (
        f"the deadline moves from 2026-02-09 to 2026-02-16, "
        f"got {notice['dispute_deadline_at']}"
    )


def test_supplement_cycle_runs_twice_adding_documents_and_rounds():
    """Each answered request advances the round and adds the supplied documents.

    PRD: "It moves the dispute `SUPPLEMENT_REQUESTED → SUPPLEMENTED`, adds
    `additional_doc_count` to the dispute's `evidence_doc_count`, increments the
    dispute's `round_no`, and returns the notice `EVIDENCE_REQUESTED → DISPUTED`
    while incrementing its `dispute_round_count`."

    Design: Difficulty/non_linear_state_machine/dispute_supplement_cycle_bounded_by_max_rounds
    """
    scenario = _open_dispute_scenario()

    fx.request_supplement(scenario["dispute_id"])
    first_answer = fx.supplement_dispute(
        scenario["dispute_id"], scenario["customer_id"], additional_doc_count=2
    )
    assert first_answer["status"] == "SUPPLEMENTED"
    assert first_answer["round_no"] == 2
    assert first_answer["evidence_doc_count"] == 3

    fx.request_supplement(scenario["dispute_id"])
    notice_after_second_request = fx.get_notice(scenario["notice_id"])
    assert notice_after_second_request["dispute_deadline_at"].startswith(
        "2026-02-23T08:00:00"
    ), f"a second request adds another 7 days, got {notice_after_second_request['dispute_deadline_at']}"

    second_answer = fx.supplement_dispute(
        scenario["dispute_id"], scenario["customer_id"], additional_doc_count=1
    )

    assert second_answer["round_no"] == 3
    assert second_answer["evidence_doc_count"] == 4
    notice = fx.get_notice(scenario["notice_id"])
    assert notice["status"] == "DISPUTED"
    assert notice["dispute_round_count"] == 3


def test_third_supplement_request_is_refused_at_the_two_request_ceiling():
    """Once `supplement_request_count` reaches 2 the cycle is closed.

    PRD: "The request requires that the dispute is `OPEN` or `SUPPLEMENTED` and
    that the notice's `supplement_request_count` is strictly below 2, or
    `ERR_MAX_DISPUTE_ROUNDS`."

    Design: Difficulty/non_linear_state_machine/dispute_supplement_cycle_bounded_by_max_rounds
    """
    scenario = _open_dispute_scenario()
    fx.request_supplement(scenario["dispute_id"])
    fx.supplement_dispute(
        scenario["dispute_id"], scenario["customer_id"], additional_doc_count=2
    )
    fx.request_supplement(scenario["dispute_id"])
    fx.supplement_dispute(
        scenario["dispute_id"], scenario["customer_id"], additional_doc_count=1
    )

    response = api_client.request_dispute_supplement(
        scenario["dispute_id"],
        {"reason_note": "Third request."},
        make_dispute_reviewer_headers("rev-1"),
    )

    validate_error(response, ApiErrorId.ERR_MAX_DISPUTE_ROUNDS.value)
    notice = fx.get_notice(scenario["notice_id"])
    assert notice["supplement_request_count"] == 2
    assert notice["dispute_round_count"] == 3
    assert notice["dispute_deadline_at"].startswith("2026-02-23T08:00:00"), (
        "a refused request must not extend the deadline again"
    )
    assert fx.get_dispute(scenario["dispute_id"])["status"] == "SUPPLEMENTED"


# ==========================================================================
# The education hold
# ==========================================================================


def test_issuance_at_the_education_threshold_flips_the_shipper_to_required():
    """The first strike reaches this shipper's threshold of one.

    PRD: "When an issuance pushes `offender_strike_count` to or past
    `education_threshold_strikes`, `education_status` moves `NONE → REQUIRED`,
    `education_required_at` is stamped with the logical instant, and the shipper
    is blocked from filing any new dispute until education completes; an attempt
    to file while `REQUIRED` is rejected with `ERR_EDUCATION_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/dispute_blocked_by_education_hold_until_education_completes
    """
    scenario = _education_scenario()

    fx.issue_notice(scenario["notice_id"])
    customer = fx.get_customer(scenario["customer_id"])
    notice = fx.get_notice(scenario["notice_id"])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_customer(customer)
    assert customer["offender_strike_count"] == 1
    assert customer["education_status"] == "REQUIRED"
    assert customer["education_required_at"] is not None
    assert customer["education_required_at"].startswith("2026-01-10T08:00:00")
    assert customer["liability_index_rolling"] == 0.00, (
        "no notice has been resolved yet, so nothing contributes to the index"
    )
    assert customer["dispute_window_days"] == 30
    assert notice["dispute_deadline_at"].startswith("2026-02-09T08:00:00")
    assert shipment["assessed_total_cents"] == 45314


def test_dispute_filing_is_blocked_while_education_is_required():
    """The refusal comes from the shipper account's state, not the notice's.

    PRD: "that the shipper's `education_status` is not `REQUIRED`, or
    `ERR_EDUCATION_HOLD`"

    Design: Difficulty/cross_entity_state_dependency/dispute_blocked_by_education_hold_until_education_completes
    """
    scenario = _education_scenario()
    fx.issue_notice(scenario["notice_id"])

    response = api_client.create_dispute(
        _filing_payload(scenario["notice_id"]),
        make_shipper_headers(scenario["customer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_EDUCATION_HOLD.value)
    notice = fx.get_notice(scenario["notice_id"])
    assert notice["status"] == "ISSUED", "the refused filing leaves the notice ISSUED"
    assert notice["dispute_round_count"] == 0


def test_completing_education_unblocks_filing_and_raises_the_threshold():
    """The identical filing succeeds once education is recorded as completed.

    PRD: "moves it `REQUIRED → COMPLETED`, raises `education_threshold_strikes`
    to the shipper's current `offender_strike_count` plus its
    `education_strike_interval`, unblocks dispute filing, and increments the
    account's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/dispute_blocked_by_education_hold_until_education_completes
    """
    scenario = _education_scenario()
    fx.issue_notice(scenario["notice_id"])

    completed = fx.complete_education(scenario["customer_id"])
    assert completed["education_status"] == "COMPLETED"
    assert completed["education_threshold_strikes"] == 2, (
        f"one strike plus an interval of one raises the threshold to 2, "
        f"got {completed['education_threshold_strikes']}"
    )

    dispute = fx.file_dispute(
        scenario["notice_id"],
        scenario["customer_id"],
        claim_basis="DENSITY_RECOMPUTE",
        evidence_doc_count=2,
    )
    notice = fx.get_notice(scenario["notice_id"])

    assert_dispute(dispute)
    assert dispute["round_no"] == 1
    assert dispute["filed_by_customer_id"] == scenario["customer_id"]
    assert notice["status"] == "DISPUTED"
    assert notice["dispute_round_count"] == 1
