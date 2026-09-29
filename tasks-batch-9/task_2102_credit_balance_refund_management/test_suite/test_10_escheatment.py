"""Unclaimed property: dormancy clocks, due diligence and remittance to the state."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_batch_item,
    advance_to_stale,
    assert_escheatment_record,
    assert_instant_equals,
    attribute_all,
    create_escheatment_record_payload,
    issue_batch,
    list_transactions,
    lock_batch,
    open_batch,
    open_escheatment_record,
    post_txn,
    read_check,
    read_credit_balance,
    read_escheatment,
    run_ops_checkpoint,
    set_clock,
    setup_approved_refund_request,
    setup_multi_credit_scenario,
    setup_refunded_credit,
    setup_stale_check,
    validate_error,
    validate_paginated,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


def _two_stale_checks_with_divergent_activity():
    """Two identical CA checks; only the second account is posted to after issue."""
    scenario = setup_multi_credit_scenario(
        accounts=[
            {"account_number": "ACCT-ES1", "patient_name": "Elena Sharp"},
            {"account_number": "ACCT-ES2", "patient_name": "Evan Sharp"},
        ],
        payer_code="COM", payer_type="COMMERCIAL",
    )
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]]
    )
    requests = [
        setup_approved_refund_request(
            credit_balance, requested_amount_cents=12_000, payee_type="PATIENT",
            payee_state_code="CA", payee_name=name,
        )
        for credit_balance, name in zip(
            scenario["credit_balances"], ("Elena Sharp", "Evan Sharp")
        )
    ]
    batch = open_batch("B-ESC", "2026-08-18T00:00:00Z", "2026-08-20T00:00:00Z")
    checks = [add_batch_item(batch["id"], request["id"]) for request in requests]
    lock_batch(batch["id"])
    set_clock("2026-08-20T00:00:00Z")
    issue_batch(batch["id"], 100001)

    set_clock("2026-11-10T00:00:00Z")
    post_txn(scenario["accounts"][1]["id"], "CHARGE", 100, "SYSTEM")

    advance_to_stale("2027-02-16T00:00:00Z")
    scenario["refund_requests"] = requests
    scenario["checks"] = [read_check(check["id"]) for check in checks]
    return scenario


def test_issue_date_basis_starts_the_dormancy_clock_at_the_issue_instant(api):
    """PRD §3.12: "The record's `state_code` is copied from the check's `payee_state_code`, and that jurisdiction fixes `dormancy_days`: California and Texas each impose 1,095 days — three years — while New York and Florida each impose 1,825 days — five years."
    PRD §3.12: "Under the `ISSUE_DATE` basis — the statutory default — `dormancy_start_at` is simply the check's `issued_at`. Account activity after the check was cut is ignored entirely, so this basis always produces the earliest possible escheat date."
    PRD §3.12: "From there both bases compute the same way: `escheat_due_at` is `dormancy_start_at` plus `dormancy_days` days, and `due_diligence_open_at` is `escheat_due_at` minus 120 days."

    Design: Difficulty/dual_variant_calc/escheat_dormancy_issue_date_vs_last_contact_on_escheatment_record
    """
    scenario = _two_stale_checks_with_divergent_activity()
    assert scenario["checks"][0]["state"] == "STALE"

    record = validate_success(
        api.create_escheatment_record(
            create_escheatment_record_payload(
                scenario["checks"][0]["id"], basis="ISSUE_DATE"
            ),
            COMPLIANCE,
        ),
        201,
    )

    assert_escheatment_record(record)
    assert record["state_code"] == "CA"
    assert record["dormancy_days"] == 1_095
    assert_instant_equals(
        record["dormancy_start_at"], "2026-08-20T00:00:00Z", "dormancy_start_at"
    )
    assert_instant_equals(
        record["escheat_due_at"], "2029-08-19T00:00:00Z", "escheat_due_at"
    )
    assert_instant_equals(
        record["due_diligence_open_at"], "2029-04-21T00:00:00Z",
        "due_diligence_open_at",
    )


def test_last_contact_basis_pushes_the_dormancy_clock_to_the_latest_posting(api):
    """PRD §3.12: "Under the `LAST_CONTACT` basis — used by jurisdictions that reset dormancy whenever the owner is heard from — take the patient account behind the credit balance that the check's refund request was drawn against, find the latest `posted_at` across that account's transactions that have not been reversed, and set `dormancy_start_at` to the later of that instant and the check's `issued_at`. Any non-reversed posting after the issue date therefore pushes the start forward and produces a strictly later escheat date for the very same check."
    PRD §3.12: "From there both bases compute the same way: `escheat_due_at` is `dormancy_start_at` plus `dormancy_days` days, and `due_diligence_open_at` is `escheat_due_at` minus 120 days."

    Design: Difficulty/dual_variant_calc/escheat_dormancy_issue_date_vs_last_contact_on_escheatment_record
    """
    scenario = _two_stale_checks_with_divergent_activity()
    issue_date_record = open_escheatment_record(
        scenario["checks"][0]["id"], basis="ISSUE_DATE"
    )

    last_contact_record = validate_success(
        api.create_escheatment_record(
            create_escheatment_record_payload(
                scenario["checks"][1]["id"], basis="LAST_CONTACT"
            ),
            COMPLIANCE,
        ),
        201,
    )

    assert_instant_equals(
        last_contact_record["dormancy_start_at"], "2026-11-10T00:00:00Z",
        "dormancy_start_at",
    )
    assert_instant_equals(
        last_contact_record["escheat_due_at"], "2029-11-09T00:00:00Z", "escheat_due_at"
    )
    assert_instant_equals(
        last_contact_record["due_diligence_open_at"], "2029-07-12T00:00:00Z",
        "due_diligence_open_at",
    )
    assert last_contact_record["escheat_due_at"] != issue_date_record["escheat_due_at"], (
        "the two bases must produce different escheat dates for identical checks"
    )


def test_missing_due_diligence_outranks_the_dormancy_clock_on_remittance(api):
    """PRD §3.12: "It must have `due_diligence_sent_at` set, which is to say it must be in `DUE_DILIGENCE_SENT`; a record still sitting in `DORMANT` passes the state check but is caught here with `ERR_DUE_DILIGENCE_REQUIRED` (HTTP 409)."
    PRD §3.12: "Because due diligence outranks dormancy in the global ordering of §2.8, a `DORMANT` record whose dormancy has also not elapsed reports the missing-due-diligence error rather than the dormancy error."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_21_beats_temporal_priority_22_on_escheat_remit
    """
    scenario = setup_stale_check(
        account_number="ACCT-DD1", batch_number="B-DD",
        starting_check_number=500001, payee_state_code="CA",
    )
    record = open_escheatment_record(scenario["check"]["id"], basis="ISSUE_DATE")
    assert record["state"] == "DORMANT"

    response = api.remit_escheatment_record(record["id"], {}, COMPLIANCE)
    error = validate_error(response, ApiErrorId.ERR_DUE_DILIGENCE_REQUIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_DORMANCY_NOT_ELAPSED.value


def test_refused_remittance_leaves_the_record_check_and_credit_untouched(api):
    """PRD §3.12: "Remittance is the terminal act. The record must not already be `CLAIMED`, `REMITTED` or `EXEMPT` — those are refused with `ERR_ESCHEATMENT_INVALID_STATE`."
    PRD §3.12: "The record opens in `state` `DORMANT` with `remitted_amount_cents` at 0, `contact_method` null, `due_diligence_sent_at` null and `claimed_at` null."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_21_beats_temporal_priority_22_on_escheat_remit
    """
    scenario = setup_stale_check(
        account_number="ACCT-DD1", batch_number="B-DD",
        starting_check_number=500001, payee_state_code="CA",
    )
    record = open_escheatment_record(scenario["check"]["id"], basis="ISSUE_DATE")
    validate_error(
        api.remit_escheatment_record(record["id"], {}, COMPLIANCE),
        ApiErrorId.ERR_DUE_DILIGENCE_REQUIRED.value,
    )

    stored = read_escheatment(record["id"])
    assert stored["state"] == "DORMANT"
    assert stored["remitted_amount_cents"] == 0
    assert read_check(scenario["check"]["id"])["state"] == "STALE"
    assert read_credit_balance(scenario["credit_balance"]["id"])["status"] == "REFUNDED"


def test_escheatment_record_cannot_be_opened_while_the_check_is_only_issued(api):
    """PRD §3.12: "A `ComplianceOfficer` opens a record against a `check_disbursement_id`, which must name a check in `state` `STALE` — anything else is `ERR_CHECK_INVALID_STATE` — and at most one record may exist per check, a second attempt being refused with `ERR_ESCHEATMENT_ALREADY_EXISTS`."

    Design: Difficulty/cross_entity_state_dependency/escheatment_record_creation_depends_on_check_disbursement_being_stale
    """
    scenario = setup_refunded_credit(
        account_number="ACCT-EC1", batch_number="B-EC", starting_check_number=600001,
        payee_state_code="CA",
    )
    set_clock("2026-09-01T00:00:00Z")
    assert read_check(scenario["check"]["id"])["state"] == "ISSUED"

    response = api.create_escheatment_record(
        create_escheatment_record_payload(
            scenario["check"]["id"], basis="ISSUE_DATE"
        ),
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_CHECK_INVALID_STATE.value)

    _, meta = validate_paginated(
        api.list_escheatment_records(
            COMPLIANCE, params={"check_disbursement_id": scenario["check"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_same_escheatment_record_is_accepted_once_the_sweep_stales_the_check(api):
    """PRD §3.14: "Every check in `state` `ISSUED` whose `stale_at` is at or before the logical clock moves `ISSUED → STALE`. No ledger movement occurs. The number moved is reported as `staled_check_count`."
    PRD §3.12: "A `ComplianceOfficer` opens a record against a `check_disbursement_id`, which must name a check in `state` `STALE` — anything else is `ERR_CHECK_INVALID_STATE` — and at most one record may exist per check, a second attempt being refused with `ERR_ESCHEATMENT_ALREADY_EXISTS`."

    Design: Difficulty/cross_entity_state_dependency/escheatment_record_creation_depends_on_check_disbursement_being_stale
    """
    scenario = setup_refunded_credit(
        account_number="ACCT-EC1", batch_number="B-EC", starting_check_number=600001,
        payee_state_code="CA",
    )
    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api.create_escheatment_record(
            create_escheatment_record_payload(
                scenario["check"]["id"], basis="ISSUE_DATE"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_CHECK_INVALID_STATE.value,
    )

    set_clock("2027-02-16T00:00:00Z")
    checkpoint = run_ops_checkpoint()
    assert checkpoint["staled_check_count"] == 1
    assert read_check(scenario["check"]["id"])["state"] == "STALE"

    record = validate_success(
        api.create_escheatment_record(
            create_escheatment_record_payload(
                scenario["check"]["id"], basis="ISSUE_DATE"
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert record["state"] == "DORMANT"
    assert record["check_disbursement_id"] == scenario["check"]["id"]
    assert_instant_equals(
        record["escheat_due_at"], "2029-08-19T00:00:00Z", "escheat_due_at"
    )


def test_escheat_chain_from_duplicate_record_through_due_diligence_to_remittance(api):
    """PRD §3.12: "Two guards apply: the record must be `DORMANT`, or the attempt fails with `ERR_ESCHEATMENT_INVALID_STATE`; and the logical clock must be at or after `due_diligence_open_at`, or the attempt fails with `ERR_DUE_DILIGENCE_TOO_EARLY` (HTTP 409)."
    PRD §3.12: "Recording the owner-contact letter moves the record `DORMANT → DUE_DILIGENCE_SENT`. The officer supplies a `contact_method` of `FIRST_CLASS_MAIL`, `CERTIFIED_MAIL` or `EMAIL`, which is stored alongside a `due_diligence_sent_at` stamped from the logical clock."
    PRD §3.12: "When remittance succeeds, the record moves `DUE_DILIGENCE_SENT → REMITTED` and its `remitted_amount_cents` is set to the check's `net_check_amount_cents`. Two cascade hops follow. Hop 1 moves the check `STALE → ESCHEATED`, which is terminal for it. Hop 2 moves the owning credit balance `REFUNDED → ESCHEATED`, bumps its `version` by 1 and posts an `ESCHEAT_REMITTANCE` ledger row of positive `net_check_amount_cents` on the account, so the ledger records that the hospital parted with the funds a second time — once to the payee who never cashed the check, and once to the state."

    Design: Corner/endpoints/escheatment_action_endpoints_due_diligence_window_then_remit_cascade
    """
    scenario = setup_stale_check(
        account_number="ACCT-ES9", batch_number="B-ES9",
        starting_check_number=800001, payee_state_code="CA",
    )
    record = open_escheatment_record(scenario["check"]["id"], basis="ISSUE_DATE")

    validate_error(
        api.create_escheatment_record(
            create_escheatment_record_payload(
                scenario["check"]["id"], basis="LAST_CONTACT"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_ESCHEATMENT_ALREADY_EXISTS.value,
    )
    validate_error(
        api.record_due_diligence(
            record["id"], {"contact_method": "CERTIFIED_MAIL"}, COMPLIANCE
        ),
        ApiErrorId.ERR_DUE_DILIGENCE_TOO_EARLY.value,
    )

    set_clock("2029-04-21T00:00:00Z")
    sent = validate_success(
        api.record_due_diligence(
            record["id"], {"contact_method": "CERTIFIED_MAIL"}, COMPLIANCE
        )
    )
    assert sent["state"] == "DUE_DILIGENCE_SENT"
    assert sent["contact_method"] == "CERTIFIED_MAIL"
    assert_instant_equals(
        sent["due_diligence_sent_at"], "2029-04-21T00:00:00Z", "due_diligence_sent_at"
    )

    validate_error(
        api.record_due_diligence(
            record["id"], {"contact_method": "FIRST_CLASS_MAIL"}, COMPLIANCE
        ),
        ApiErrorId.ERR_ESCHEATMENT_INVALID_STATE.value,
    )

    set_clock("2029-08-19T00:00:00Z")
    remitted = validate_success(
        api.remit_escheatment_record(record["id"], {}, COMPLIANCE)
    )
    assert remitted["state"] == "REMITTED"
    assert remitted["remitted_amount_cents"] == 11_720

    assert read_check(scenario["check"]["id"])["state"] == "ESCHEATED"
    assert read_credit_balance(scenario["credit_balance"]["id"])["status"] == "ESCHEATED"

    remittances = list_transactions(
        scenario["account"]["id"], txn_type="ESCHEAT_REMITTANCE"
    )
    assert len(remittances) == 1
    assert remittances[0]["amount_cents"] == 11_720

    _, meta = validate_paginated(
        api.list_escheatment_records(
            COMPLIANCE, params={"check_disbursement_id": scenario["check"]["id"]}
        )
    )
    assert meta["total_count"] == 1
