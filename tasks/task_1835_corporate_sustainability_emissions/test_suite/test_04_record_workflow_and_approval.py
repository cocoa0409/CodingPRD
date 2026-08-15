"""Activity-record workflow: state machine edges, segregation of duties at
approval, the >= 1000 evidence mandate, and immediate response consistency."""
import pytest

from test_helpers import (
    ANALYST, MANAGER, ApiErrorId, get_activity_record, make_analyst_headers,
    make_collecting_cycle, make_factor, make_site, review_record,
    submit_record, transition_payload, upload_and_verify_evidence,
    validate_error, validate_success,
)


def _setup_record():
    site = make_site()
    factor = make_factor()
    cycle = make_collecting_cycle()
    return site, factor, cycle


def test_record_cannot_skip_review_to_approved(api, analyst_headers):
    """PRD §3.3: "A steward moves a record from `SUBMITTED` to `UNDER_REVIEW`
    to hand it to the analytics team" and PRD §2.10: "State gates — the
    target entity's own state permits the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/record_cannot_skip_review_to_approved
    """
    site, factor, cycle = _setup_record()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    resp = api.transition_activity_record(
        record["id"], transition_payload("APPROVED"), analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_activity_record(record["id"])["status"] == "SUBMITTED"


def test_record_reject_resubmit_loop(api, analyst_headers, steward_headers):
    """PRD §3.3: "Rejection moves the record from `UNDER_REVIEW` to
    `REJECTED` and requires a non-empty `reason` — an empty one fails with
    `ERR_INVALID_REQUEST` — which is stored as `reject_reason`" and "A
    rejected record is not dead: the steward may resubmit it, returning it
    from `REJECTED` to `SUBMITTED` with `reject_reason` cleared to null, so
    the `REJECTED` → `SUBMITTED` → `UNDER_REVIEW` revision loop is cyclic by
    design."

    Design: Corner/state_machines/record_reject_resubmit_loop
    """
    site, factor, cycle = _setup_record()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    review_record(record["id"])

    rejected = validate_success(
        api.transition_activity_record(
            record["id"], transition_payload("REJECTED", reason="Unreadable invoice"),
            analyst_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "Unreadable invoice"

    resubmitted = validate_success(
        api.transition_activity_record(
            record["id"], transition_payload("SUBMITTED"), steward_headers
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted.get("reject_reason") is None, (
        "resubmit clears the stored reject_reason to null"
    )


def test_approve_large_record_evidence_gate_boundary(api, analyst_headers, steward_headers):
    """PRD §3.3: "if the record's `quantity` is 1000 or more, at least one
    evidence item on the record must be `VERIFIED` (`ERR_EVIDENCE_REQUIRED`)".

    Design: Corner/validations/approve_large_record_evidence_gate_boundary
    """
    site, factor, cycle = _setup_record()
    small = submit_record(
        cycle["id"], site["id"], factor["id"], quantity=999.99,
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    review_record(small["id"])
    large = submit_record(
        cycle["id"], site["id"], factor["id"], quantity=1000,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    review_record(large["id"])

    # 999.99 < 1000: below the mandate, approval succeeds with no evidence.
    small_approved = validate_success(
        api.transition_activity_record(
            small["id"], transition_payload("APPROVED"), analyst_headers
        )
    )
    assert small_approved["status"] == "APPROVED"

    # Exactly 1000 triggers the mandate.
    blocked = api.transition_activity_record(
        large["id"], transition_payload("APPROVED"), analyst_headers
    )
    validate_error(blocked, ApiErrorId.ERR_EVIDENCE_REQUIRED, 422)

    upload_and_verify_evidence(large["id"], seed=55)
    approved = validate_success(
        api.transition_activity_record(
            large["id"], transition_payload("APPROVED"), analyst_headers
        )
    )
    assert approved["status"] == "APPROVED"


def test_approve_segregation_beats_factor_freshness(api):
    """PRD §3.3: "Approval — `UNDER_REVIEW` to `APPROVED` — carries the
    strictest preconditions, evaluated after the cycle gate and in this
    order: the approver must not be the user who submitted the record
    (`ERR_SEGREGATION_OF_DUTIES`, per §2.9); if the record's `quantity` is
    1000 or more, at least one evidence item on the record must be `VERIFIED`
    (`ERR_EVIDENCE_REQUIRED`); and the referenced factor must still be
    `PUBLISHED` with the record's period fully inside its closed validity
    window — the same freshness check as at creation, re-run at approval,
    failing as `ERR_FACTOR_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/approve_record_safety_beats_referential
    """
    site, factor, cycle = _setup_record()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    review_record(record["id"])
    # Retire the referenced factor after submission so the referential leg fails.
    validate_success(
        api.transition_emission_factor(factor["id"], transition_payload("RETIRED"), MANAGER)
    )

    # Same user id as the submitter, acting in the analyst role: SoD fires first.
    same_user = api.transition_activity_record(
        record["id"], transition_payload("APPROVED"), make_analyst_headers("steward-1")
    )
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    # A different analyst now surfaces the referential failure.
    other = api.transition_activity_record(
        record["id"], transition_payload("APPROVED"), ANALYST
    )
    validate_error(other, ApiErrorId.ERR_FACTOR_NOT_PUBLISHED, 422)


def test_approve_with_retired_factor_fails_and_record_unchanged(api, analyst_headers):
    """PRD §3.3: "the referenced factor must still be `PUBLISHED` with the
    record's period fully inside its closed validity window — the same
    freshness check as at creation, re-run at approval, failing as
    `ERR_FACTOR_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/approve_record_safety_beats_referential
    """
    site, factor, cycle = _setup_record()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=10)
    review_record(record["id"])
    validate_success(
        api.transition_emission_factor(factor["id"], transition_payload("RETIRED"), MANAGER)
    )

    resp = api.transition_activity_record(
        record["id"], transition_payload("APPROVED"), analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_FACTOR_NOT_PUBLISHED, 422)
    after = get_activity_record(record["id"])
    assert after["status"] == "UNDER_REVIEW", "a rejected approval leaves the record in place"
    assert after.get("tco2e") is None and after.get("factor_value_snapshot") is None


def test_approval_response_immediate_consistency(api, analyst_headers):
    """PRD §3.3: "On approval the system pins the factor value:
    `factor_value_snapshot` copies the factor's current
    `value_tco2e_per_unit` and is immutable thereafter, `tco2e` is computed
    as the `quantity` multiplied by that snapshot, rounded half-up to four
    decimal places, and `reviewed_by_user_id` records the approver." PRD
    §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/approval_response_immediate_consistency
    """
    site, factor, cycle = _setup_record()
    record = submit_record(cycle["id"], site["id"], factor["id"], quantity=100)
    review_record(record["id"])
    approved = validate_success(
        api.transition_activity_record(
            record["id"], transition_payload("APPROVED"), analyst_headers
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["tco2e"] == pytest.approx(50.0, abs=0.00005), (
        "round_half_up(100 x 0.5, 4) = 50.0000"
    )
    assert approved["factor_value_snapshot"] == pytest.approx(0.5, abs=1e-9)
    assert approved["reviewed_by_user_id"] == "analyst-1"
