"""At the agency: the write gate, evidence-request rounds and the partitioned SLA clock."""

from test_helpers import (
    ApiErrorId,
    assert_sla_partition,
    assert_sla_segment,
    build_scenario,
    issue_rfe,
    list_rfes,
    list_sla_segments,
    new_document_requirement,
    order_summary,
    read_document,
    read_order,
    resubmit_doc,
    review_doc,
    set_clock,
    submit_doc,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_same_instant, parse_instant
from test_helpers.fixtures import AGENCY, CASE_MANAGER, COMPLIANCE, REVIEWER


# ==========================================================================
# The evidence-request re-open cycle and its terminal round
# ==========================================================================
def _order_at_agency_with_one_open_rfe():
    scenario = build_scenario(
        "at_agency", require_passport_doc=True, visa_type="TOURIST", with_consulate=True
    )
    scenario["rfe"] = issue_rfe(scenario["order_id"], "BANK_STATEMENT")
    return scenario


def test_first_insufficient_adjudication_reopens_the_same_evidence_request(api):
    """PRD §3.10: "*`INSUFFICIENT` below the cap* — available from `RESPONDED` while
    `response_count` is below **2** — re-opens the same record rather than escalating: it
    moves `RESPONDED → OPEN`, restamps `issued_at` with the logical clock and recomputes
    `deadline_at` from that new instant."
    PRD §3.10: "Its `deadline_at` is computed by advancing the calendar date of `issued_at`
    by **10** business days on the order consulate's calendar and taking that date at
    17:00:00Z — the deadline instant always lands at the close of the business window."

    Design: Difficulty/non_linear_state_machine/rfe_insufficient_reopen_cycle_on_rfe_entity
    """
    scenario = _order_at_agency_with_one_open_rfe()
    rfe = scenario["rfe"]

    assert_same_instant(
        rfe["deadline_at"],
        "2026-06-15T17:00:00Z",
        "an evidence request issued on 2026-06-01 is due 10 business days later",
    )

    validate_success(api.respond_to_rfe(rfe["id"], CASE_MANAGER))
    reopened = validate_success(
        api.adjudicate_rfe(rfe["id"], {"outcome": "INSUFFICIENT"}, AGENCY)
    )

    assert reopened["rfe_status"] == "OPEN", (
        "below the round cap an INSUFFICIENT verdict re-opens rather than escalating"
    )
    assert reopened["response_count"] == 1
    assert read_order(scenario["order_id"])["workflow_status"] == "RFE_PENDING", (
        "the order stays in RFE_PENDING while the record is re-opened"
    )


def test_second_insufficient_adjudication_abandons_the_order_and_schedules_the_refund(api):
    """PRD §3.10: "*`INSUFFICIENT` at the cap* — from `RESPONDED` with `response_count` at
    2 or above — moves the record `RESPONDED → INSUFFICIENT` and abandons the order."
    PRD §3.10: "Both abandoning branches do the same four things: the order moves
    `RFE_PENDING → ABANDONED`, the open `PAUSED` segment is closed with its `ended_at` and
    `business_minutes` written, `decided_at` is stamped with the logical clock, the
    post-tender refund adjudication of §3.11 runs and sets `refund_scheduled_cents` with
    `payment_status` moving to `REFUND_PENDING`, and a return hop from `AGENCY` to `SERVICE`
    is created in `leg_status` `CREATED` with a `leg_index` one above the highest existing
    hop on the order and a `scheduled_date` equal to the calendar date of the logical clock."
    PRD §3.11: "The stage fraction is read from `furthest_stage_reached`, the high-water
    mark that never falls: **1.00** at `DRAFT`, **1.00** at `QUOTED`, **0.75** at `INTAKE`,
    **0.50** at `READY_FOR_SUBMISSION`, **0.25** at `SUBMITTED` and **0.15** at `AT_AGENCY`."

    Design: Difficulty/non_linear_state_machine/rfe_insufficient_reopen_cycle_on_rfe_entity
    """
    scenario = _order_at_agency_with_one_open_rfe()
    rfe = scenario["rfe"]

    validate_success(api.respond_to_rfe(rfe["id"], CASE_MANAGER))
    validate_success(api.adjudicate_rfe(rfe["id"], {"outcome": "INSUFFICIENT"}, AGENCY))
    validate_success(api.respond_to_rfe(rfe["id"], CASE_MANAGER))
    final = validate_success(
        api.adjudicate_rfe(rfe["id"], {"outcome": "INSUFFICIENT"}, AGENCY)
    )

    assert final["rfe_status"] == "INSUFFICIENT"
    assert final["response_count"] == 2

    stored = read_order(scenario["order_id"])
    assert stored["workflow_status"] == "ABANDONED"
    assert stored["payment_status"] == "REFUND_PENDING"
    # 10500 collected on the SERVICE stream at the 0.15 AT_AGENCY fraction.
    assert stored["refund_scheduled_cents"] == 1575, (
        f"expected the 0.15 stage fraction of 10500, got {stored['refund_scheduled_cents']}"
    )


# ==========================================================================
# The agency-custody write gate pre-empts the resubmission cap
# ==========================================================================
def _order_at_agency_with_capped_optional_slot():
    """An order at AT_AGENCY whose optional BANK_STATEMENT slot is REJECTED and has
    already consumed both of its resubmissions."""
    from test_helpers.fixtures import (
        accept_quote,
        add_photo,
        check_photo,
        new_active_form,
        new_applicant,
        new_catalog_item,
        new_order,
        pay,
        prepare_form,
        quote,
        run_leg,
        submit_order,
        tender_order,
    )

    set_clock()
    form = new_active_form()
    catalog = new_catalog_item(visa_type="TOURIST")
    new_document_requirement(catalog["id"])
    new_document_requirement(
        catalog["id"], doc_type="BANK_STATEMENT", is_required=False,
        validity_rule="NONE", validity_param=None,
    )
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Lock Pair")

    passport = submit_doc(applicant["id"])
    review_doc(passport["id"], "ACCEPT")

    bank = submit_doc(applicant["id"], doc_type="BANK_STATEMENT", issue_date="2026-05-01",
                      expiry_date=None)
    review_doc(bank["id"], "REJECT", "illegible scan")
    resubmit_doc(bank["id"], issue_date="2026-05-05", expiry_date=None)
    review_doc(bank["id"], "REJECT", "still illegible")
    resubmit_doc(bank["id"], issue_date="2026-05-08", expiry_date=None)
    review_doc(bank["id"], "REJECT", "wrong account")

    photo = add_photo(applicant["id"])
    check_photo(photo["id"])
    prepare_form(applicant["id"], form["id"])

    quoted = quote(order["id"])
    pay(order["id"], quoted["total_quoted_cents"])
    accept_quote(order["id"])
    run_leg(order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
            scheduled_date="2026-06-01")
    submit_order(order["id"])
    run_leg(order["id"], leg_index=2, from_holder="SERVICE", to_holder="AGENCY",
            scheduled_date="2026-06-01")
    tender_order(order["id"])
    return order, applicant, bank


def test_agency_custody_lock_pre_empts_the_resubmission_cap(api):
    """PRD §2.7: "Every mutating endpoint that touches that order or any of its descendants
    is therefore refused with `ERR_AGENCY_CUSTODY_LOCK` (HTTP 409), and this refusal is
    evaluated **early** — it pre-empts almost every substantive check in the ladder, so a
    request that would also have failed a state check, a cap check or a fiscal check reports
    the custody lock instead."
    PRD §2.7: "In particular, recording a payment, changing the service level, changing the
    travel dates, submitting or resubmitting a document, uploading or retaking a photo,
    running a photo compliance check, preparing or signing a form, booking or rescheduling
    or recording the outcome of an appointment, creating a courier leg, creating a shipment,
    recording a delivery attempt, recording a pickup, splitting the order, quoting, accepting
    a quote, adding an applicant, acknowledging infeasibility and submitting are all blocked
    while the agency holds the book."

    Design: Difficulty/priority_pair_validation_conflict/custody_lock_preempts_document_resubmission_cap
    """
    order, _applicant, bank = _order_at_agency_with_capped_optional_slot()
    assert read_document(bank["id"])["resubmission_count"] == 2

    resp = api.resubmit_document(bank["id"], {"issue_date": "2026-05-30"}, CASE_MANAGER)
    error = validate_error(resp, ApiErrorId.ERR_AGENCY_CUSTODY_LOCK.value)
    assert error["error_id"] != ApiErrorId.ERR_RESUBMISSION_CAP_EXCEEDED.value, (
        "the earlier rung decides the response"
    )


def test_the_pre_empted_resubmission_changes_nothing_on_the_locked_file(api):
    """PRD §2.9: "Every request is checked against a single, globally ordered ladder of 38
    rungs. Checks run strictly in ascending rung order and **the first failing rung decides
    the response** — no later rung is evaluated once an earlier one has failed."
    PRD §2.7: "**The agency-custody write gate.** While `Order.custody_holder` is `AGENCY`,
    the file is physically inside a government building and the expediter cannot alter it."

    Design: Difficulty/priority_pair_validation_conflict/custody_lock_preempts_document_resubmission_cap
    """
    order, _applicant, bank = _order_at_agency_with_capped_optional_slot()

    resp = api.resubmit_document(bank["id"], {"issue_date": "2026-05-30"}, CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AGENCY_CUSTODY_LOCK.value)

    stored_doc = read_document(bank["id"])
    assert stored_doc["review_status"] == "REJECTED"
    assert stored_doc["resubmission_count"] == 2, "the refused request consumes nothing"

    stored_order = read_order(order["id"])
    assert stored_order["custody_holder"] == "AGENCY"
    assert stored_order["workflow_status"] == "AT_AGENCY"


# ==========================================================================
# The SLA partition, the round cap and the response deadline
# ==========================================================================
def test_paused_segments_account_for_the_whole_clock_stop_versus_gross_gap(api):
    """PRD §3.10: "The **clock-stop** figure — the contractual one — is the sum of
    `business_minutes` over the order's segments with `segment_kind` `RUNNING`, plus, when
    the single open segment is itself `RUNNING`, the business minutes between that
    segment's `started_at` and the end instant."
    PRD §3.10: "The **gross** figure ignores segment kinds entirely and is simply the
    business minutes between the order's `submitted_at` and the end instant, computed in
    one shot."
    PRD §2.11: "And the sum of `business_minutes` over the `RUNNING` segments equals the
    contractual clock-stop SLA figure. Because the segments tile the interval exactly, the
    running total plus the paused total equals the gross total at every instant."

    Design: Corner/calculations/corner_sla_clock_stop_partitions_against_gross_elapsed
    """
    scenario = build_scenario("at_agency", visa_type="PASSPORT_RENEWAL")
    order_id = scenario["order_id"]
    submitted_at = read_order(order_id)["submitted_at"]

    set_clock("2026-06-01T12:00:00Z")
    rfe = issue_rfe(order_id, "BANK_STATEMENT")

    set_clock("2026-06-02T10:00:00Z")
    validate_success(api.respond_to_rfe(rfe["id"], CASE_MANAGER))
    cleared = validate_success(api.adjudicate_rfe(rfe["id"], {"outcome": "CLEARED"}, AGENCY))
    assert cleared["rfe_status"] == "CLEARED"

    set_clock("2026-06-02T15:00:00Z")
    summary = validate_success(api.get_order_summary(order_id, COMPLIANCE))

    assert summary["sla_running_business_minutes"] == 480, (
        "180 minutes before the pause plus 300 after it, got "
        f"{summary['sla_running_business_minutes']}"
    )
    assert summary["sla_paused_business_minutes"] == 360, (
        f"300 minutes on 2026-06-01 plus 60 on 2026-06-02, got "
        f"{summary['sla_paused_business_minutes']}"
    )
    assert summary["sla_gross_business_minutes"] == 840
    assert (
        summary["sla_running_business_minutes"] + summary["sla_paused_business_minutes"]
        == summary["sla_gross_business_minutes"]
    ), "running plus paused equals gross at every instant"

    assert read_order(order_id)["workflow_status"] == "AT_AGENCY"
    segments = list_sla_segments(order_id)
    assert len(segments) == 3, f"submission, pause, resume — expected 3, got {len(segments)}"
    for segment in segments:
        assert_sla_segment(segment)
    assert_sla_partition(segments, submitted_at)
    assert segments[-1]["ended_at"] is None, "the last segment is still open"


def test_a_third_evidence_request_is_refused_at_the_round_cap(api):
    """PRD §3.10: "An `AgencyLiaison` issues one by supplying `requested_doc_type`, driving
    the order `AT_AGENCY → RFE_PENDING`, provided the order's `rfe_round_count` is below
    **2** — a third request is `ERR_RFE_ROUND_CAP_EXCEEDED`. `rfe_round_count` counts every
    evidence-request row under the order whatever its `rfe_status`, so a cleared or expired
    round still consumes one of the two."

    Design: Corner/errors/corner_error_rfe_round_cap_exceeded
    """
    scenario = build_scenario("at_agency", visa_type="PASSPORT_RENEWAL")
    order_id = scenario["order_id"]

    first = issue_rfe(order_id, "BANK_STATEMENT")
    validate_success(api.respond_to_rfe(first["id"], CASE_MANAGER))
    validate_success(api.adjudicate_rfe(first["id"], {"outcome": "CLEARED"}, AGENCY))
    second = issue_rfe(order_id, "EMPLOYMENT_LETTER")
    validate_success(api.respond_to_rfe(second["id"], CASE_MANAGER))
    validate_success(api.adjudicate_rfe(second["id"], {"outcome": "CLEARED"}, AGENCY))

    resp = api.create_rfe(order_id, {"requested_doc_type": "VACCINATION_CERT"}, AGENCY)
    validate_error(resp, ApiErrorId.ERR_RFE_ROUND_CAP_EXCEEDED.value)

    stored = read_order(order_id)
    assert stored["rfe_round_count"] == 2
    assert stored["workflow_status"] == "AT_AGENCY"
    rows = list_rfes(order_id)
    assert len(rows) == 2, f"the refused issuance writes no RFE row, got {len(rows)}"
    assert {r["rfe_status"] for r in rows} == {"CLEARED"}


def test_a_response_after_the_deadline_is_refused_and_the_round_can_expire(api):
    """PRD §3.10: "The response must arrive at or before `deadline_at`, and exact equality
    passes; a later response is `ERR_RFE_DEADLINE_PASSED`."
    PRD §3.10: "*`EXPIRED`* is available from `rfe_status` `OPEN` and requires the logical
    clock to be strictly after `deadline_at`; it moves the record `OPEN → EXPIRED` and
    likewise abandons the order."

    Design: Corner/errors/corner_error_rfe_deadline_passed_on_response
    """
    scenario = build_scenario("at_agency", visa_type="PASSPORT_RENEWAL")
    order_id = scenario["order_id"]
    rfe = issue_rfe(order_id, "BANK_STATEMENT")
    assert_same_instant(rfe["deadline_at"], "2026-06-15T17:00:00Z", "RFE deadline_at")

    set_clock("2026-06-16T09:00:00Z")
    refused = api.respond_to_rfe(rfe["id"], CASE_MANAGER)
    validate_error(refused, ApiErrorId.ERR_RFE_DEADLINE_PASSED.value)

    before = [r for r in list_rfes(order_id) if r["id"] == rfe["id"]][0]
    assert before["rfe_status"] == "OPEN"
    assert before["response_count"] == 0

    expired = validate_success(api.adjudicate_rfe(rfe["id"], {"outcome": "EXPIRED"}, AGENCY))
    assert expired["rfe_status"] == "EXPIRED"

    stored = read_order(order_id)
    assert stored["workflow_status"] == "ABANDONED"
    assert stored["payment_status"] == "REFUND_PENDING"
    assert stored["refund_scheduled_cents"] == 1575
