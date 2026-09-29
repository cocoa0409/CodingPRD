"""Corner cases where one machine's trigger must leave the other machines alone, and
where a lifecycle cascade must reach children sitting in two different states."""

from test_helpers import (
    AUDITOR_HEADERS,
    AccountStatus,
    ApiErrorId,
    BillingMode,
    ContractStatus,
    SettlementState,
    VerificationStatus,
    WorkStatus,
    assert_instant,
    fixtures,
    get_success_data,
    validate_error,
)


def test_no_work_trigger_ever_moves_the_verification_dimension(api):
    """PRD §3.3: "Neither dimension reads the other except where a rule below says so
    explicitly."
    PRD §3.7: "Closing out stamps `work_completed_at` from the logical clock, recomputes
    `serviced_line_count` and `billable_line_count`, and runs the **provisional** variant of
    the visit charge. It does not touch `settlement_state`, which stays `UNSETTLED`, moves
    nothing on any brewer ledger, and decides no balance proposal."
    PRD §3.7: "The `signer_name` is captured, `signed_at` is stamped from the clock, the
    settled charge variant runs with no withholding, `settlement_state` becomes `SETTLED`, and
    the brewer waterfall runs."

    Design: Corner/state_machines/corner_work_and_verification_dimensions_only_move_on_their_own_triggers
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse")
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")
    lot = fixtures.create_chemical_lot(api, lot_code="C-2001")
    booked = fixtures.book_visit(api, venue["account"]["id"], technician["id"])
    assert booked["work_status"] == WorkStatus.SCHEDULED
    assert booked["verification_status"] == VerificationStatus.UNVERIFIED
    assert booked["settlement_state"] == SettlementState.UNSETTLED

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    started = fixtures.start_visit(api, booked["id"], technician["id"])
    assert started["work_status"] == WorkStatus.IN_PROGRESS
    # Opening the job moved the field-work dimension and nothing else.
    assert started["verification_status"] == VerificationStatus.UNVERIFIED
    assert started["settlement_state"] == SettlementState.UNSETTLED

    fixtures.log_cleaning_cycle(
        api,
        booked["id"],
        venue["lines"][0]["id"],
        lot["id"],
        technician["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    completed = fixtures.complete_work_on(api, booked["id"], technician["id"])
    assert completed["work_status"] == WorkStatus.WORK_COMPLETE
    assert completed["verification_status"] == VerificationStatus.UNVERIFIED
    assert completed["settlement_state"] == SettlementState.UNSETTLED
    assert completed["provisional_charge_cents"] == 12093
    assert_instant(
        completed["work_completed_at"], "2026-08-05T10:00:00Z", label="work_completed_at"
    )

    fixtures.set_clock(api, "2026-08-05T11:00:00Z")
    signed = fixtures.sign_visit(
        api, booked["id"], venue["account"]["id"], signer_name="Ana Ortiz"
    )

    assert signed["verification_status"] == VerificationStatus.SIGNED
    assert signed["settlement_state"] == SettlementState.SETTLED
    # The verification trigger left the work dimension exactly where the crew left it.
    assert signed["work_status"] == WorkStatus.WORK_COMPLETE
    assert_instant(
        signed["work_completed_at"], "2026-08-05T10:00:00Z", label="work_completed_at"
    )
    assert signed["settled_charge_cents"] == 12093


def test_terminating_a_venue_expires_the_draft_and_the_active_contract_together(api):
    """PRD §3.9: "Terminating an account is available from either `ACTIVE` or `SUSPENDED`,
    moves it to `TERMINATED`, and likewise requires that no visit on the account be
    `SCHEDULED` or `IN_PROGRESS`, else `ERR_ACCOUNT_HAS_OPEN_VISITS`. Termination expires the
    commercial relationship wholesale: every contract on the account whose status is `DRAFT`,
    `ACTIVE` or `SUSPENDED` moves to `EXPIRED`, processed in ascending `created_at` order.
    This is the only path by which a `DRAFT` contract ever reaches `EXPIRED`."
    PRD §3.1: "The account is created in `ACTIVE` with `version` 1, `billing_mode`
    `DIRECT_BILL`, `lines_out_of_service_count` 0, `open_complaint_count` 0 and
    `suspended_reason` `NONE`; its `status` may later be `ACTIVE`, `SUSPENDED` or
    `TERMINATED`, and `suspended_reason` may later be `NONE`, `LINE_COMPLIANCE_THRESHOLD` or
    `MANUAL`."

    Design: Corner/state_machines/corner_terminating_an_account_expires_its_draft_and_active_contracts_together
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Anchor Alehouse")
    account_id = venue["account"]["id"]
    contract_a = venue["contract"]
    contract_b = fixtures.draft_contract(
        api,
        account_id,
        fixtures.read_account(api, account_id)["version"],
        cleaning_frequency_days=14,
        contracted_line_count=4,
        per_line_rate_cents=3900,
        visit_base_fee_cents=7000,
    )
    assert contract_a["status"] == ContractStatus.ACTIVE
    assert contract_b["status"] == ContractStatus.DRAFT
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")
    lot = fixtures.create_chemical_lot(api, lot_code="C-2001")
    visit = fixtures.book_visit(api, account_id, technician["id"])

    validate_error(
        api.set_account_status(account_id, AccountStatus.TERMINATED, AUDITOR_HEADERS),
        ApiErrorId.ACCOUNT_HAS_OPEN_VISITS,
        409,
    )

    # The refusal applied no part of the cascade.
    assert fixtures.read_account(api, account_id)["status"] == AccountStatus.ACTIVE
    assert fixtures.read_contract(api, contract_a["id"])["status"] == ContractStatus.ACTIVE
    assert fixtures.read_contract(api, contract_b["id"])["status"] == ContractStatus.DRAFT

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.start_visit(api, visit["id"], technician["id"])
    fixtures.log_cleaning_cycle(
        api,
        visit["id"],
        venue["lines"][0]["id"],
        lot["id"],
        technician["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.complete_work_on(api, visit["id"], technician["id"])

    terminated = get_success_data(
        api.set_account_status(account_id, AccountStatus.TERMINATED, AUDITOR_HEADERS),
        expected_status=200,
    )

    assert terminated["status"] == AccountStatus.TERMINATED
    assert terminated["billing_mode"] == BillingMode.DIRECT_BILL
    assert fixtures.read_contract(api, contract_a["id"])["status"] == ContractStatus.EXPIRED
    # The DRAFT child is in the cascade set, not only the ACTIVE one.
    assert fixtures.read_contract(api, contract_b["id"])["status"] == ContractStatus.EXPIRED
    # A visit that already reached a terminal work state is untouched.
    assert fixtures.read_visit(api, visit["id"])["work_status"] == WorkStatus.WORK_COMPLETE
