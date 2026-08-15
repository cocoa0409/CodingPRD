"""Enrollment notice waves: issuance gates, statutory windows, opt-outs,
rescissions, suspension cascade, and the epoch-advance ops checkpoint."""
from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_epoch,
    advance_through_enrollment,
    bootstrap_authority,
    close_notice_at_deadline,
    create_account_spec,
    create_adopted_product_with_schedule,
    create_executed_contract,
    create_notice,
    create_opt_out_request_payload,
    fmt_iso,
    get_account,
    get_authority,
    get_notice,
    ingest_accounts,
    issue_notice,
    parse_iso,
    record_opt_out,
    set_clock,
    setup_active_authority,
    setup_enrolled_accounts,
    validate_error,
    validate_success,
)

BD = TEST_USERS["board_director_headers"]
PO = TEST_USERS["program_operator_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_notice_issue_rejected_while_authority_suspended(api):
    """PRD §3.2: "A `ProgramOperator` may move a wave from `DRAFT` to `ISSUED` only when all of the following hold: the Authority is `ACTIVE`; `notice_mailed_on` is not earlier than the current logical-clock date; at least one adopted default product exists with an adopted rate schedule covering `enrollment_effective_on` (otherwise `ERR_NO_DEFAULT_PRODUCT`); and `target_service_classes` is non-empty."
    PRD §2.9: "7. **Authority posture** — operations that require a particular program posture (notice issuance requires the Authority `ACTIVE`; line posting requires the parent extract still in `DRAFT`) yield `ERR_AUTHORITY_POSTURE` when the posture is wrong."

    Design: Difficulty/cross_entity_state_dependency/notice_issue_gated_by_authority_posture
    """
    setup_active_authority()
    api.suspend_authority({}, BD)

    notice = create_notice(wave_label="W2", notice_mailed_on="2026-02-01T00:00:00Z")
    authority = get_authority()
    res = api.issue_enrollment_notice(
        notice["id"], {"expected_authority_version": authority["version"]}, PO
    )
    validate_error(res, ApiErrorId.ERR_AUTHORITY_POSTURE)

    after = get_notice(notice["id"])
    assert after["status"] == "DRAFT", "posture-blocked issue must not move the notice"
    assert after["account_count_noticed"] == 0


def test_notice_issue_succeeds_after_reinstate(api):
    """PRD §3.1: "Reinstatement from `SUSPENDED` back to `ACTIVE` has no preconditions."
    PRD §3.2: "A `ProgramOperator` may move a wave from `DRAFT` to `ISSUED` only when all of the following hold: the Authority is `ACTIVE`; `notice_mailed_on` is not earlier than the current logical-clock date; at least one adopted default product exists with an adopted rate schedule covering `enrollment_effective_on` (otherwise `ERR_NO_DEFAULT_PRODUCT`); and `target_service_classes` is non-empty."

    Design: Difficulty/cross_entity_state_dependency/notice_issue_gated_by_authority_posture
    """
    setup_active_authority()
    api.suspend_authority({}, BD)
    notice = create_notice(wave_label="W2", notice_mailed_on="2026-02-01T00:00:00Z")

    validate_success(api.reinstate_authority({}, BD), 200)
    issued = issue_notice(notice["id"])
    assert issued["status"] == "ISSUED", (
        "once the Authority is ACTIVE again the same wave issues"
    )


def test_occ_notice_issue_stale_authority_version(api):
    """PRD §2.8: "First, issuing an enrollment notice wave requires the request to carry `expected_authority_version`, holding the Authority `version` the client last observed. Issuance sweeps account state under policy fields — the rate policy, the default-product requirement — that the observed Authority version governed; if another writer has advanced the Authority's version since the client last read it, the issue is rejected with `ERR_STALE_AUTHORITY_VERSION` (HTTP 412), and the client must re-read and re-issue."
    PRD §3.2: "The wave's `account_count_noticed` is set to the sweep count, and issuance increments the Authority's `version` by 1."

    Design: Corner/complexity_layers/occ_notice_issue_stale_authority_version
    """
    setup_active_authority()
    observed = get_authority()["version"]

    wave1 = create_notice(wave_label="W1")
    validate_success(
        api.issue_enrollment_notice(
            wave1["id"], {"expected_authority_version": observed}, PO
        ),
        200,
    )
    # W1's issue bumped Authority.version, so the previously observed version
    # is now stale.
    assert get_authority()["version"] == observed + 1

    wave2 = create_notice(
        wave_label="W2",
        notice_mailed_on="2026-02-01T00:00:00Z",
        target_service_classes=("SMALL_COMMERCIAL",),
    )
    res = api.issue_enrollment_notice(
        wave2["id"], {"expected_authority_version": observed}, PO
    )
    validate_error(res, ApiErrorId.ERR_STALE_AUTHORITY_VERSION)

    after = get_notice(wave2["id"])
    assert after["status"] == "DRAFT", "stale-version issue must not move the wave"
    assert after["account_count_noticed"] == 0


def test_authority_suspend_cascade_cancels_issued_wave(api):
    """PRD §3.1: "Suspension is permitted only when no enrollment notice is currently in `ENROLLING` status, and it is deliberately disruptive: every notice in `ISSUED` is cancelled, and every account those waves had swept to `NOTICED` reverts to `PROSPECT` with its `current_enrollment_notice_id` nulled."

    Design: Corner/state_machines/authority_suspend_cascade_cancels_issued_wave
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-4001")])
    notice = create_notice()
    issue_notice(notice["id"])
    assert get_account(ids[0])["enrollment_state"] == "NOTICED"

    validate_success(api.suspend_authority({}, BD), 200)

    notice_after = get_notice(notice["id"])
    assert notice_after["status"] == "CANCELLED"

    account_after = get_account(ids[0])
    assert account_after["enrollment_state"] == "PROSPECT"
    assert account_after.get("current_enrollment_notice_id") is None, (
        "suspension nulls the governing notice reference"
    )


def test_notice_close_before_deadline_rejected(api):
    """PRD §3.2: "Once the logical clock reaches the `opt_out_deadline`, the `ProgramOperator` closes the wave, moving it `ISSUED → CLOSED`. Closing before the deadline is a statutory violation and is rejected with `ERR_STATUTE_WINDOW_VIOLATION`."

    Design: Corner/state_machines/notice_close_before_deadline_rejected
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-1001")])
    notice = create_notice()
    issued = issue_notice(notice["id"])
    deadline = parse_iso(issued["opt_out_deadline"])

    # One second before the deadline: statutory violation.
    set_clock(fmt_iso(deadline - timedelta(seconds=1)))
    early = api.close_enrollment_notice(notice["id"], {}, PO)
    validate_error(early, ApiErrorId.ERR_STATUTE_WINDOW_VIOLATION)
    assert get_notice(notice["id"])["status"] == "ISSUED"
    assert get_account(ids[0])["enrollment_state"] == "NOTICED"

    # At the deadline the close succeeds.
    set_clock(fmt_iso(deadline))
    closed = validate_success(api.close_enrollment_notice(notice["id"], {}, PO), 200)
    assert closed["status"] == "CLOSED"


def test_scheduled_epoch_advance_contract_delivery_and_notice_enrollment(api):
    """PRD §2.4: "This is a checkpoint that fires every scheduled transition whose time gate has been met at the current logical instant: closed notice waves flip their noticed accounts into enrollment, and supply contracts cross from execution into delivery and from delivery into closure."
    PRD §2.4: "The run returns a summary payload containing `advanced_notices`, `flipped_accounts`, and `advanced_contracts`, each an integer count of the resources the checkpoint moved."
    PRD §2.4: "Nothing else in the system fires these transitions — a wave that has passed its enrollment effective date simply waits for the next epoch-advance run."

    Design: Corner/complexity_layers/scheduled_epoch_advance_contract_delivery_and_notice_enrollment
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-T01")])
    notice = create_notice()
    issue_notice(notice["id"])
    closed = close_notice_at_deadline(notice["id"])
    effective = parse_iso(closed["enrollment_effective_on"])

    contract = create_executed_contract(
        contract_type="PPA",
        delivery_start="2026-06-01T00:00:00Z",
        delivery_end="2027-06-01T00:00:00Z",
        capacity_mw=10.0,
        total_mwh=43800,
    )
    assert contract["status"] == "EXECUTED"

    # Epoch one second before enrollment_effective_on: no gate is met.
    set_clock(fmt_iso(effective - timedelta(seconds=1)))
    epoch1 = advance_epoch()
    assert epoch1["flipped_accounts"] == 0
    assert epoch1["advanced_notices"] == 0
    assert epoch1["advanced_contracts"] == 0
    assert get_notice(notice["id"])["status"] == "CLOSED"

    # Epoch at 2026-06-01: both the notice's effective instant and the
    # contract's delivery_start have been reached.
    set_clock("2026-06-01T00:00:00Z")
    epoch2 = advance_epoch()
    assert epoch2["flipped_accounts"] == 1
    assert epoch2["advanced_notices"] == 1
    assert epoch2["advanced_contracts"] == 1

    notice_after = get_notice(notice["id"])
    assert notice_after["status"] == "SETTLED"
    assert notice_after["account_count_enrolled"] == 1

    contract_after = validate_success(
        api.get_supply_contract(
            contract["id"], TEST_USERS["portfolio_manager_headers"]
        ),
        200,
    )
    assert contract_after["status"] == "DELIVERING"

    account_after = get_account(ids[0])
    assert account_after["enrollment_state"] == "ENROLLED"


def test_opt_out_rescission_and_at_deadline_rejection_flow(api):
    """PRD §3.3: "For a `NOTICED` account, an `OPT_OUT` election requires that the clock still be before the governing notice's `opt_out_deadline` and that the payload's `enrollment_notice_id` equal the account's `current_enrollment_notice_id` — an election filed under the wrong wave is `ERR_REFERENTIAL_STATE`, and one filed after the deadline is `ERR_STATUTE_WINDOW_VIOLATION`."
    PRD §3.3: "A rescission — a new request whose `reversal_of_request_id` references an earlier `OPT_OUT` request belonging to the same account, made while the clock is still before the deadline — leaves the account `NOTICED` and re-admits it to the sweep, marking the earlier request reversed through the new row."
    PRD §3.2: "At close, the wave's `account_count_opted_out` is recomputed as the number of opt-out requests filed under this notice with `election_type` equal to `OPT_OUT` that have not been rescinded by a later reversal request."
    PRD §3.2: "At that instant the wave moves `CLOSED → ENROLLING`, and every account still `NOTICED` under it flips to `ENROLLED`, takes `product_election` equal to `DEFAULT`, and has its `vintage_year` stamped with the calendar year of `enrollment_effective_on`."

    Design: Corner/state_machines/opt_out_after_deadline_rejected_and_rescission_flow
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-2001")])
    notice = create_notice()
    issue_notice(notice["id"])

    opt_out = validate_success(record_opt_out(ids[0], notice["id"]), 201)
    assert get_account(ids[0])["enrollment_state"] == "OPTED_OUT"

    reversal = validate_success(
        record_opt_out(
            ids[0],
            notice["id"],
            channel="PHONE",
            reversal_of_request_id=opt_out["id"],
        ),
        201,
    )
    assert reversal["reversal_of_request_id"] == opt_out["id"]
    assert get_account(ids[0])["enrollment_state"] == "NOTICED", (
        "a timely rescission re-admits the account to the sweep"
    )

    # At the deadline instant the opt-out window has shut ("still be before").
    notice_now = get_notice(notice["id"])
    set_clock(notice_now["opt_out_deadline"])
    late = api.create_opt_out_request(
        create_opt_out_request_payload(
            service_account_id=ids[0], enrollment_notice_id=notice["id"]
        ),
        CS,
    )
    validate_error(late, ApiErrorId.ERR_STATUTE_WINDOW_VIOLATION)

    closed = close_notice_at_deadline(notice["id"])
    assert closed["account_count_opted_out"] == 0, (
        "the only opt-out was rescinded, so the recomputed count is zero"
    )

    settled, _epoch = advance_through_enrollment(notice["id"])
    account = get_account(ids[0])
    assert account["enrollment_state"] == "ENROLLED"
    assert account["product_election"] == "DEFAULT"
    effective_year = parse_iso(settled["enrollment_effective_on"]).year
    assert account["vintage_year"] == effective_year


def test_opt_out_request_immutability_append_only(api):
    """PRD §2.5: "Two resource families are deliberately lighter: opt-out requests, load forecast snapshots, billing lines, and REC retirements are append-only records — they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them entirely."
    PRD §3.3: "A rescission — a new request whose `reversal_of_request_id` references an earlier `OPT_OUT` request belonging to the same account, made while the clock is still before the deadline — leaves the account `NOTICED` and re-admits it to the sweep, marking the earlier request reversed through the new row."

    Design: Corner/entities/opt_out_request_immutability_append_only
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-IM01")])
    notice = create_notice()
    issue_notice(notice["id"])

    r1 = validate_success(record_opt_out(ids[0], notice["id"]), 201)
    r2 = validate_success(
        record_opt_out(
            ids[0], notice["id"], channel="PHONE", reversal_of_request_id=r1["id"]
        ),
        201,
    )

    r1_after = validate_success(api.get_opt_out_request(r1["id"], CS), 200)
    assert r1_after["channel"] == "WEB", "the original row was never mutated"
    assert r1_after["created_at"] == r1["created_at"]
    assert "version" not in r1_after and "updated_at" not in r1_after, (
        "opt-out requests carry only id and created_at as system fields"
    )
    assert r2["reversal_of_request_id"] == r1["id"]
    assert get_account(ids[0])["enrollment_state"] == "NOTICED"


def test_conditional_action_election_requires_covering_schedule(api):
    """PRD §3.3: "The change requires the account to be `ENROLLED`; requires that a product exist in `ADOPTED` status whose `election_key` equals the requested value; and requires an adopted rate schedule for that product covering the current logical-clock date — a missing default-side prerequisite surfaces as `ERR_NO_DEFAULT_PRODUCT`, a non-adopted or uncovered target as `ERR_REFERENTIAL_STATE`. The change applies to future billing lines only — history is never rewritten, because each posted line snapshots `product_election_at_billing` — and it increments the account's `version` by 1."

    Design: Corner/endpoints/conditional_action_election_requires_covering_schedule
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-E01")]
    )
    account_id = enrolled["account_ids"][0]

    # Adopt an opt-up product with a schedule covering the current clock.
    create_adopted_product_with_schedule(
        product_code="EVERGREEN100",
        election_key="OPT_UP_100",
        renewable_pct=1.00,
        energy_rate=12.10,
    )

    before = get_account(account_id)
    res = api.change_product_election(account_id, {"product_election": "OPT_UP_100"}, CS)
    after = validate_success(res, 200)
    assert after["product_election"] == "OPT_UP_100"
    assert after["version"] == before["version"] + 1, (
        "the election change increments the account version by exactly 1"
    )
    assert after["enrollment_state"] == "ENROLLED", (
        "the product dimension moves independently of the enrollment dimension"
    )


def test_referenced_body_fk_not_found(api):
    """PRD §2.9: "4. **Body reference existence** — a body-carried foreign key that does not resolve (`service_account_id`, `product_id`, `compliance_filing_id`, `supply_contract_id`, `enrollment_notice_id`, `reversal_of_request_id`) yields `ERR_REFERENCED_NOT_FOUND`."

    Design: Corner/validations/referenced_body_fk_not_found
    """
    setup_active_authority()
    notice = create_notice(target_service_classes=("STREETLIGHT",))
    issue_notice(notice["id"])

    res = api.create_opt_out_request(
        create_opt_out_request_payload(
            service_account_id=NON_EXISTENT_UUID, enrollment_notice_id=notice["id"]
        ),
        CS,
    )
    validate_error(res, ApiErrorId.ERR_REFERENCED_NOT_FOUND)
