"""Filing adjudication claims: prepare/submit/accept/reject gates, the
sweep-driven OVERDUE transition with posture recompute, segregation of duties
on acceptance, and the fee-accrual conserved quantity."""
from test_helpers import (
    ApiErrorId,
    SEC1,
    SEC2,
    fetch_entity,
    find_filing,
    list_events,
    prepare_filing,
    run_sweep,
    set_clock,
    setup_base_entity,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_filing_accept_from_prepared_rejected(api):
    """PRD 3.6: "Attempting to accept or reject a non-`SUBMITTED` filing is
    rejected with `ERR_FILING_NOT_SUBMITTED`."

    Design: Corner/state_machines/filing_accept_from_prepared_rejected
    """
    ctx = setup_base_entity(legal_name="Skipstep Corp")
    filing = find_filing(ctx["entity"]["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])

    response = api.accept_filing(filing["id"], SEC1)
    validate_error(response, ApiErrorId.ERR_FILING_NOT_SUBMITTED)

    current = validate_success(api.get_filing(filing["id"], SEC1))
    assert current["status"] == "PREPARED"


def test_filing_overdue_auto_transition_on_sweep(api):
    """PRD 3.6: "When the current logical date passes the `due_date`, the filing
    transitions to `OVERDUE`; a filing on its due date is not yet overdue."
    PRD 3.13: "If neither condition holds, `suspended_since` is cleared, and
    posture is `DELINQUENT` if any filing is `OVERDUE`, else `GOOD_STANDING`."
    PRD 3.15: "The sweep response reports `filings_marked_overdue`,
    `resolutions_made_effective`, `resolutions_blocked`, `grants_expired`,
    `certificates_expired`, `certificates_auto_denied`, and `posture_changes`."

    Design: Corner/state_machines/filing_overdue_auto_transition_on_sweep
    """
    ctx = setup_base_entity(legal_name="Overdue Corp")
    entity = ctx["entity"]
    # Both period-2026 filings are due 2026-12-31; 2027-01-05 is past due but
    # within grace (10 days) + 30, so DELINQUENT, not SUSPENDED (PRD 3.13).
    set_clock("2027-01-05T00:00:00Z")

    report = run_sweep()
    assert report["filings_marked_overdue"] == 2

    overdue, meta = validate_paginated(
        api.list_filings(SEC1, params={"entity_id": entity["id"], "status": "OVERDUE"})
    )
    assert meta["total_count"] == 2

    current = fetch_entity(entity["id"])
    assert current["compliance_posture"] == "DELINQUENT"
    assert current["suspended_since"] is None

    events = list_events(entity["id"], event_type="FILING_OVERDUE")
    assert len(events) == 2, "one audit event per filing that flipped OVERDUE"


def test_sod_submitter_cannot_accept_own_filing(api):
    """PRD 3.6: "Acceptance and rejection are adjudicated by a
    `CorporateSecretary` who must differ from the submitter."
    PRD 2.9: "The same `X-User-ID` may not perform both sides of any of these
    pairs; violations are rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.6: "Acceptance transitions the filing to `ACCEPTED` and generates the
    next period's filings for the same jurisdiction and filing type, provided
    none already exist and the entity still owes filings to that jurisdiction."

    Design: Corner/rbac/sod_submitter_cannot_accept_own_filing
    """
    ctx = setup_base_entity(legal_name="Rollover Corp")
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    # sec-01 (a CorporateSecretary) both prepares and submits this filing.
    prepare_filing(filing["id"], headers=SEC1)
    submit_filing(filing["id"], headers=SEC1)

    same_user = api.accept_filing(filing["id"], SEC1)
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    current = validate_success(api.get_filing(filing["id"], SEC1))
    assert current["status"] == "SUBMITTED"

    accepted = validate_success(api.accept_filing(filing["id"], SEC2))
    assert accepted["status"] == "ACCEPTED"

    # Rollover is per (jurisdiction, filing_type): only the FRANCHISE_TAX 2027
    # row appears; the ANNUAL_REPORT 2027 row waits on its own acceptance.
    rollover, meta = validate_paginated(
        api.list_filings(SEC1, params={"entity_id": entity["id"], "period_year": 2027})
    )
    assert meta["total_count"] == 1
    assert rollover[0]["filing_type"] == "FRANCHISE_TAX"
    assert rollover[0]["status"] == "SCHEDULED"


def test_filing_fee_accrues_on_submit(api):
    """PRD 3.6: "At submit time, the system computes the actual franchise tax
    from the entity's current `authorized_shares`, determines `days_late` and
    `penalty_cents`, and sets `fee_cents` to the sum of `report_fee_cents`,
    `tax_assessed_cents`, and `penalty_cents`."
    PRD 3.6: "The submitter's `X-User-ID` is recorded in `submitted_by_user_id`,
    `submitted_date` is set to the current logical date, and the entity's
    `fees_accrued_cents` increases by `fee_cents`."

    Design: Difficulty/compensating_invariant/filing_fee_accrual_reversal
    """
    ctx = setup_base_entity(legal_name="Ledger Corp")
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])

    assert fetch_entity(entity["id"])["fees_accrued_cents"] == 0, "baseline"

    submitted = submit_filing(filing["id"])
    assert submitted["fee_cents"] == 31000, "5000 report fee + 26000 tax + 0 penalty"

    current = fetch_entity(entity["id"])
    assert current["fees_accrued_cents"] == 31000, (
        "the ledger increases by exactly the filing's fee_cents"
    )


def test_filing_fee_accrual_reversed_on_reject(api):
    """PRD 3.6: "Rejection transitions the filing to `REJECTED` and reverses
    the fee accrual exactly, decrementing `fees_accrued_cents` by `fee_cents`."

    Design: Difficulty/compensating_invariant/filing_fee_accrual_reversal
    """
    ctx = setup_base_entity(legal_name="Ledger Corp")
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])
    submit_filing(filing["id"])
    assert fetch_entity(entity["id"])["fees_accrued_cents"] == 31000

    rejected = validate_success(
        api.reject_filing(
            filing["id"], {"reason": "incorrect officer certification block"}, SEC1
        )
    )
    assert rejected["status"] == "REJECTED"

    current = fetch_entity(entity["id"])
    assert current["fees_accrued_cents"] == 0, (
        "the rejection reverses the accrual exactly, returning the ledger to baseline"
    )
