"""Commissions: hold-reason release gates, bucket conservation across the
regulatory cascade and release, year-to-date premium reconciliation on issue
and rescind, and the payment gate (PRD sections 2.9, 3.3, 3.5, 3.6, 3.7).

Note: the PRD never publishes the per-line base commission rates (section 3.6
names "the base commission rate fixed for the application's
`line_of_authority`" without a rate table), so absolute `amount_cents`
expectations are always read back from the API and compared, never hard-coded.
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_commission_entry,
    create_producer,
    get_entry_for_application,
    get_producer,
    issue_application,
    setup_approved_application,
    setup_held_commission_via_suspension,
    setup_issued_application,
    setup_jit_scenario,
    submit_application,
    validate_error,
    validate_success,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


def test_release_rejected_while_jit_appointment_pending():
    """PRD section 3.6: "For `APPOINTMENT_PENDING`, release requires an
    `ACTIVE` appointment covering the application's line in the application's
    state, held by the producer or the affiliated agency, else
    `ERR_APPOINTMENT_NOT_ACTIVE`." The just-in-time appointment is still
    `JIT_PENDING`, so the hold cannot be released.

    Design: Difficulty/cross_entity_state_dependency/commission_release_requires_appointment_active
    """
    bundle = setup_jit_scenario(npn="NPN-2018", line_of_authority="LIFE",
                                premium_cents=10_000_000)
    entry = bundle["entry"]
    assert entry["status"] == "HELD"
    assert entry["hold_reason"] == "APPOINTMENT_PENDING"

    resp = api_client.release_commission_entry(entry["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_ACTIVE)
    assert get_entry_for_application(bundle["application"]["id"])["status"] == "HELD"


def test_release_succeeds_after_jit_appointment_filed():
    """PRD section 3.6: "A successful release moves the entry to `PAYABLE`,
    clears `hold_reason`, and recomputes the producer's held total." and "The
    producer's `commission_held_cents` is the sum of `amount_cents` across
    their `HELD` entries, recomputed on every commission status change."

    Design: Difficulty/cross_entity_state_dependency/commission_release_requires_appointment_active
    """
    bundle = setup_jit_scenario(npn="NPN-2019", line_of_authority="LIFE",
                                premium_cents=10_000_000)
    entry = bundle["entry"]

    filed = validate_success(
        api_client.file_appointment(bundle["jit_appointment"]["id"], LC), 200
    )
    assert filed["status"] == "ACTIVE"

    released = validate_success(
        api_client.release_commission_entry(entry["id"], OFFICER_B), 200
    )
    assert_commission_entry(released)
    assert released["status"] == "PAYABLE"
    assert released["hold_reason"] is None
    assert get_producer(bundle["producer"]["id"])["commission_held_cents"] == 0


def test_regulatory_hold_blocks_release_until_license_reinstated():
    """PRD section 3.6: "For `REGULATORY_HOLD`, release requires the producer's
    license in the application's state to be `ACTIVE` again, else
    `ERR_REGULATORY_HOLD_ACTIVE`." PRD section 3.7: "every one of the
    producer's entries with status `PAYABLE` is re-held as `HELD` with
    `hold_reason` `REGULATORY_HOLD`".

    Design: Difficulty/compensating_invariant/commission_hold_release_bucket_conservation
    """
    bundle = setup_held_commission_via_suspension(npn="NPN-2020")
    entry = bundle["entry"]
    assert entry["status"] == "HELD"
    assert entry["hold_reason"] == "REGULATORY_HOLD"
    assert bundle["license"]["status"] == "SUSPENDED"

    blocked = api_client.release_commission_entry(entry["id"], OFFICER_B)
    validate_error(blocked, ApiErrorId.ERR_REGULATORY_HOLD_ACTIVE)

    reinstated = validate_success(
        api_client.reinstate_license(bundle["license"]["id"], OFFICER_B), 200
    )
    assert reinstated["status"] == "ACTIVE"


def test_hold_release_round_trip_conserves_amount():
    """PRD section 3.6: "The producer's `commission_held_cents` is the sum of
    `amount_cents` across their `HELD` entries, recomputed on every commission
    status change." The cascade moves the bucket (held total 0 -> amount) and
    the reinstate-plus-release round trip restores it (amount -> 0) without
    creating or destroying a cent of the entry's amount.

    Design: Difficulty/compensating_invariant/commission_hold_release_bucket_conservation
    """
    bundle = setup_held_commission_via_suspension(npn="NPN-2021")
    entry = bundle["entry"]
    producer_id = bundle["producer"]["id"]
    amount = entry["amount_cents"]
    assert amount > 0

    # After the cascade, the held bucket carries exactly the entry's amount.
    assert get_producer(producer_id)["commission_held_cents"] == amount

    # Reinstate the license, then release: the bucket empties, the amount holds.
    validate_success(api_client.reinstate_license(bundle["license"]["id"], OFFICER_B), 200)
    released = validate_success(
        api_client.release_commission_entry(entry["id"], OFFICER_B), 200
    )
    assert released["status"] == "PAYABLE"
    assert released["hold_reason"] is None
    assert released["amount_cents"] == amount, (
        "round trip conserves the entry amount; only the bucket moved"
    )
    assert get_producer(producer_id)["commission_held_cents"] == 0


def test_issue_adds_premium_to_ytd():
    """PRD section 3.5: "On issue the application becomes `ISSUED` with
    `issued_at` stamped, the `eligibility_snapshot` is re-evaluated, the
    producer's year-to-date issued premium is recomputed with this application
    now in the input set". PRD section 3.6: "`ytd_issued_premium_cents`, is the
    sum of `premium_cents` over the producer's applications in `ISSUED` status
    whose `issued_at` falls within the logical clock's current calendar year".

    Design: Difficulty/compensating_invariant/ytd_premium_issue_rescind_reconciliation
    """
    bundle = setup_approved_application(
        npn="NPN-2022", line_of_authority="LIFE", premium_cents=75_000_000
    )
    producer_id = bundle["producer"]["id"]
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 0

    issued = issue_application(bundle["application"]["id"])
    assert issued["status"] == "ISSUED"
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 75_000_000


def test_rescind_removes_premium_from_ytd_and_forfeits():
    """PRD section 3.5: "a `LicensingCoordinator` rescinds an `ISSUED`
    application to `RESCINDED`, terminal. The application leaves the
    year-to-date input set (the producer's total is recomputed), and its
    commission entry — whatever its status — is forfeited, with the held total
    recomputed."

    Design: Difficulty/compensating_invariant/ytd_premium_issue_rescind_reconciliation
    """
    bundle = setup_issued_application(
        npn="NPN-2023", line_of_authority="LIFE", premium_cents=75_000_000
    )
    producer_id = bundle["producer"]["id"]
    app_id = bundle["application"]["id"]
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 75_000_000

    rescinded = validate_success(api_client.rescind_application(app_id, LC), 200)
    assert rescinded["status"] == "RESCINDED"
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 0
    assert get_entry_for_application(app_id)["status"] == "FORFEITED"


def test_pay_from_held_rejected():
    """PRD section 2.9: "Domain-specific state errors are reported first:
    filing a `LAPSED` just-in-time appointment yields
    `ERR_JIT_FILING_WINDOW_CLOSED`, and paying a commission entry that is not
    `PAYABLE` yields `ERR_COMMISSION_NOT_PAYABLE`."

    Design: Corner/state_machines/commission_pay_from_held_rejected
    """
    bundle = setup_jit_scenario(npn="NPN-3012", line_of_authority="LIFE",
                                premium_cents=1_000_000)
    entry = bundle["entry"]
    assert entry["status"] == "HELD"

    resp = api_client.pay_commission_entry(entry["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_COMMISSION_NOT_PAYABLE)
    assert get_entry_for_application(bundle["application"]["id"])["status"] == "HELD"


def test_release_unlicensed_hold_rejected():
    """PRD section 3.5: "a `LICENSE_GAP` starts `HELD` with `hold_reason`
    `UNLICENSED_AT_SALE`." PRD section 3.6: "A hold whose `hold_reason` is
    `UNLICENSED_AT_SALE` is never releasable — release is always rejected with
    `ERR_HOLD_NOT_RELEASABLE`."

    Design: Corner/validations/release_unlicensed_hold_rejected
    """
    producer = create_producer(npn="NPN-3024", full_name="Unlicensed",
                               resident_state_code="TX")
    application = submit_application(
        producer["id"], state_code="TX", line_of_authority="LIFE",
        applicant_name="U", premium_cents=1_000_000,
    )
    assert application["eligibility_snapshot"] == "LICENSE_GAP"
    entry = get_entry_for_application(application["id"])
    assert entry["status"] == "HELD"
    assert entry["hold_reason"] == "UNLICENSED_AT_SALE"

    resp = api_client.release_commission_entry(entry["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_RELEASABLE)
    assert get_entry_for_application(application["id"])["status"] == "HELD"


def test_ytd_calendar_year_window_excludes_prior_year():
    """PRD section 3.6: "The year-to-date figure behind the volume multiplier,
    exposed on the producer as `ytd_issued_premium_cents`, is the sum of
    `premium_cents` over the producer's applications in `ISSUED` status whose
    `issued_at` falls within the logical clock's current calendar year — from
    January 1 at 00:00:00 UTC inclusive up to the following January 1
    exclusive."

    Design: Corner/calculations/ytd_calendar_year_window_excludes_prior_year
    """
    bundle = setup_issued_application(
        npn="NPN-3017", line_of_authority="LIFE", premium_cents=5_000_000
    )
    producer_id = bundle["producer"]["id"]

    advance_clock("2026-12-31T00:00:00Z")
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 5_000_000, (
        "the 2026 issue is inside the 2026 calendar-year window"
    )

    advance_clock("2027-01-01T00:00:00Z")
    assert get_producer(producer_id)["ytd_issued_premium_cents"] == 0, (
        "the 2027 window [2027-01-01, 2028-01-01) excludes the 2026 issue"
    )
