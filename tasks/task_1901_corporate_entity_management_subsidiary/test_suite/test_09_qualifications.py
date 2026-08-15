"""Foreign qualification claims: the withdrawal cycle, duplicate suppression,
exit clearance, and the good-standing posture gate."""
from test_helpers import (
    ApiErrorId,
    SEC1,
    adopt_resolution,
    appoint_agent,
    create_agent,
    create_jurisdiction_nv,
    create_qualification_payload,
    fetch_entity,
    list_filings,
    run_sweep,
    set_clock,
    setup_base_entity,
    setup_entity_with_qualification,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_qualification_abort_withdrawal_cycle(api):
    """PRD 3.8: "Commencing withdrawal transitions from `QUALIFIED` to
    `WITHDRAWAL_PENDING` and requires an `AUTHORIZE_WITHDRAWAL` resolution with
    matching `jurisdiction_id` in `ADOPTED` or `EFFECTIVE` status."
    PRD 3.8: "Aborting withdrawal returns the qualification to `QUALIFIED`."
    PRD 3.8: "Attempting to finalize or abort from a non-`WITHDRAWAL_PENDING`
    status is rejected with `ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING`."

    Design: Corner/state_machines/qualification_abort_withdrawal_cycle
    """
    ctx = setup_entity_with_qualification(confirm=True)
    entity, j3, qualification = ctx["entity"], ctx["j3"], ctx["qualification"]
    adopt_resolution(
        entity["id"], "AUTHORIZE_WITHDRAWAL", {"jurisdiction_id": j3["id"]}, "2026-08-15"
    )

    commenced = validate_success(api.commence_withdrawal(qualification["id"], SEC1))
    assert commenced["status"] == "WITHDRAWAL_PENDING"

    aborted = validate_success(api.abort_withdrawal(qualification["id"], SEC1))
    assert aborted["status"] == "QUALIFIED", "cycle QUALIFIED -> PENDING -> QUALIFIED"

    response = api.finalize_withdrawal(qualification["id"], SEC1)
    validate_error(response, ApiErrorId.ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING)


def test_duplicate_qualification_rejected(api):
    """PRD 3.8: "A duplicate qualification for the same entity and jurisdiction
    in `PENDING`, `QUALIFIED`, or `WITHDRAWAL_PENDING` status is rejected with
    `ERR_QUALIFICATION_EXISTS`."

    Design: Corner/errors/duplicate_qualification_rejected
    """
    ctx = setup_entity_with_qualification(confirm=False)
    entity, j3, aa3 = ctx["entity"], ctx["j3"], ctx["aa3"]

    response = api.create_qualification(
        entity["id"], create_qualification_payload(j3["id"], aa3["id"]), SEC1
    )
    validate_error(response, ApiErrorId.ERR_QUALIFICATION_EXISTS)

    rows, meta = validate_paginated(
        api.list_qualifications(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 1


def test_exit_clearance_blocks_withdrawal(api):
    """PRD 3.8: "Finalizing withdrawal transitions to `WITHDRAWN` after exit
    clearance: no filing of this entity in this jurisdiction may be in
    `OVERDUE`, `SUBMITTED`, or `REJECTED` status; otherwise the request is
    rejected with `ERR_EXIT_CLEARANCE_FAILED`."

    Design: Corner/errors/exit_clearance_blocks_withdrawal
    """
    ctx = setup_entity_with_qualification(confirm=True)
    entity, j3, qualification = ctx["entity"], ctx["j3"], ctx["qualification"]

    # The J3 period-2026 ANNUAL_REPORT is due 2026-09-30; at 2026-10-05 it is
    # OVERDUE (past due, within grace + 30, so the entity is DELINQUENT only).
    set_clock("2026-10-05T00:00:00Z")
    run_sweep()
    overdue = list_filings(entity["id"], jurisdiction_id=j3["id"], status="OVERDUE")
    assert len(overdue) == 1

    adopt_resolution(
        entity["id"], "AUTHORIZE_WITHDRAWAL", {"jurisdiction_id": j3["id"]}, "2026-10-05"
    )
    commenced = validate_success(api.commence_withdrawal(qualification["id"], SEC1))
    assert commenced["status"] == "WITHDRAWAL_PENDING"

    response = api.finalize_withdrawal(qualification["id"], SEC1)
    validate_error(response, ApiErrorId.ERR_EXIT_CLEARANCE_FAILED)

    current = validate_success(api.get_qualification(qualification["id"], SEC1))
    assert current["status"] == "WITHDRAWAL_PENDING"
    still_overdue = list_filings(entity["id"], jurisdiction_id=j3["id"], status="OVERDUE")
    assert len(still_overdue) == 1, "the rejected finalize leaves the OVERDUE filing untouched"


def _setup_delinquent_entity_with_j3_coverage():
    """ACTIVE entity whose own J1 period-2026 filings are OVERDUE (posture
    DELINQUENT), holding J3 agent coverage and an ADOPTED AUTHORIZE_QUALIFICATION
    resolution."""
    ctx = setup_base_entity(legal_name="Gate Corp")
    entity = ctx["entity"]
    j3 = create_jurisdiction_nv()
    ag3 = create_agent(j3["id"], name="NV Agent Co", address="9 Agent Rd")
    aa3 = appoint_agent(entity["id"], ag3["id"], j3["id"], start_date="2026-06-01")
    adopt_resolution(
        entity["id"], "AUTHORIZE_QUALIFICATION", {"jurisdiction_id": j3["id"]}, "2026-06-01"
    )
    # Past the J1 due date 2026-12-31 but within grace (10) + 30: DELINQUENT.
    set_clock("2027-01-05T00:00:00Z")
    run_sweep()
    ctx.update({"j3": j3, "ag3": ag3, "aa3": aa3})
    return ctx


def test_qualification_requires_good_standing_rejected(api):
    """PRD 3.8: "The entity's `compliance_posture` must be `GOOD_STANDING`;
    otherwise the request is rejected with `ERR_POSTURE_NOT_GOOD_STANDING`."
    PRD 3.13: "If neither condition holds, `suspended_since` is cleared, and
    posture is `DELINQUENT` if any filing is `OVERDUE`, else `GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/qualification_requires_good_standing
    """
    ctx = _setup_delinquent_entity_with_j3_coverage()
    entity, j3, aa3 = ctx["entity"], ctx["j3"], ctx["aa3"]

    current = fetch_entity(entity["id"])
    assert current["compliance_posture"] == "DELINQUENT", (
        "overdue within grace + 30 days: not SUSPENDED, but not GOOD_STANDING either"
    )

    response = api.create_qualification(
        entity["id"], create_qualification_payload(j3["id"], aa3["id"]), SEC1
    )
    validate_error(response, ApiErrorId.ERR_POSTURE_NOT_GOOD_STANDING)


def test_qualification_requires_good_standing_creates_nothing(api):
    """PRD 3.8: "The entity's `compliance_posture` must be `GOOD_STANDING`;
    otherwise the request is rejected with `ERR_POSTURE_NOT_GOOD_STANDING`."
    PRD 3.13: "A hard overdue exists when any filing is `OVERDUE` and today is
    strictly more than 30 days past the filing's `due_date` plus the
    jurisdiction's `grace_period_days`."

    Design: Difficulty/cross_entity_state_dependency/qualification_requires_good_standing
    """
    ctx = _setup_delinquent_entity_with_j3_coverage()
    entity, j3, aa3 = ctx["entity"], ctx["j3"], ctx["aa3"]

    response = api.create_qualification(
        entity["id"], create_qualification_payload(j3["id"], aa3["id"]), SEC1
    )
    validate_error(response, ApiErrorId.ERR_POSTURE_NOT_GOOD_STANDING)

    rows, meta = validate_paginated(
        api.list_qualifications(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 0 and rows == []

    current = fetch_entity(entity["id"])
    assert current["compliance_posture"] == "DELINQUENT"
    assert current["suspended_since"] is None, (
        "2027-01-05 is not strictly more than 30 days past grace end 2027-01-10"
    )
