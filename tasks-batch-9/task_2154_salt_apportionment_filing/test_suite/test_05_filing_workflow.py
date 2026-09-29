"""Freezing, review, approval, transmission and the return listing."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_ratio,
    compute_factors,
    create_election,
    create_filing,
    make_controller_headers,
    make_state_analyst_headers,
    read_filing,
    read_group,
    read_registration,
    set_clock,
    setup_bare_registration,
    setup_computed_filing,
    setup_draft_filing,
    setup_filing_in_review,
    setup_locked_filing,
    setup_state_profile,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import REFERENCE_CREDITS, REFERENCE_MODIFICATIONS
from test_helpers.fixtures import add_credit_claim, add_modification
from test_helpers.api_client import api_client
from prd_bench_local_runner.testing import get_success_data

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
CTRL = TEST_USERS["controller_headers"]
AUD = TEST_USERS["auditor_headers"]


def _approved_filing_with_election(*, election_basis, filing_basis,
                                   state_permits_early_revocation=False):
    """An APPROVED CA 2026 return linked to a five-year election covering it."""
    ctx = setup_state_profile(registration_overrides={
        "state_permits_early_revocation": state_permits_early_revocation,
    })
    election = create_election(
        ctx["registration_id"], election_basis=election_basis,
        effective_tax_year=2024, binding_years=5,
    )
    filing = create_filing(
        ctx["registration_id"], tax_year=2026, filing_basis=filing_basis,
        federal_taxable_income=5000000, election_id=election["id"],
    )
    for line in REFERENCE_MODIFICATIONS:
        add_modification(filing["id"], dict(line))
    compute_factors(filing["id"], "JOYCE")
    for spec in REFERENCE_CREDITS:
        add_credit_claim(filing["id"], **dict(spec))
    get_success_data(api_client.lock_factors(filing["id"], {}, SA))
    get_success_data(api_client.submit_review(
        filing["id"], {"preparer_note": "prepared"},
        make_state_analyst_headers("analyst-01"),
    ))
    get_success_data(api_client.approve_filing(
        filing["id"], {"approval_note": "reviewed"},
        make_controller_headers("controller-01"),
    ))
    ctx["election"] = election
    ctx["election_id"] = election["id"]
    ctx["filing_id"] = filing["id"]
    return ctx


# ─── The freeze depends on the registration, a different entity ───────────────

def test_freeze_is_refused_while_the_registration_is_incomplete(api):
    """PRD 3.7: "The registration's `registration_status` must be `REGISTERED`, or the rejection carries `ERR_REGISTRATION_NOT_COMPLETE`."
    PRD 3.7: "Freezing a computed return is what ends the data-entry phase: a `StateAnalyst` or a `TaxManager` moves it from `DRAFT` (or from `AMENDED`, after an amendment reopened it) to `FACTORS_LOCKED`, after which no further modification lines and no further credit claims may be created against it."

    Design: Difficulty/cross_entity_state_dependency/lock_factors_gated_by_registration_status
    """
    ctx = setup_computed_filing(variant="JOYCE", complete_registration=False)
    assert read_registration(ctx["registration_id"])["registration_status"] == (
        "REGISTRATION_REQUIRED"
    )

    response = api.lock_factors(ctx["filing_id"], {}, SA)

    validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_COMPLETE.value)
    assert response.status_code == 422
    assert read_filing(ctx["filing_id"])["preparation_status"] == "DRAFT"


def test_freeze_succeeds_once_the_registration_is_completed(api):
    """PRD 3.2: "A `TaxManager` supplies the `state_account_number` the revenue department issued; the axis moves `REGISTRATION_REQUIRED → REGISTERED`, `registered_on_date` is stamped from the logical clock, the group's `open_registration_obligations` decrements by 1, the group's `compliance_posture` is re-derived — returning `EXPOSED` to `COMPLIANT` once the counter reaches 0 — and the registration's `version` advances."
    PRD 3.7: "The registration's `registration_status` must be `REGISTERED`, or the rejection carries `ERR_REGISTRATION_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/lock_factors_gated_by_registration_status
    """
    ctx = setup_computed_filing(variant="JOYCE", complete_registration=False)
    validate_error(
        api.lock_factors(ctx["filing_id"], {}, SA),
        ApiErrorId.ERR_REGISTRATION_NOT_COMPLETE.value,
    )

    registration = validate_success(api.complete_registration(
        ctx["registration_id"], {"state_account_number": "CA-55443322"}, TM
    ))
    assert registration["registration_status"] == "REGISTERED"
    assert read_group(ctx["group_id"])["open_registration_obligations"] == 0

    frozen = validate_success(api.lock_factors(ctx["filing_id"], {}, SA))

    assert frozen["preparation_status"] == "FACTORS_LOCKED"
    assert_ratio(frozen["apportionment_percentage"], 0.200000,
                 "apportionment_percentage is unchanged by either freeze attempt")


# ─── Transmission depends on the governing election ───────────────────────────

def test_transmission_is_blocked_while_the_governing_election_is_revoked(api):
    """PRD 3.3: "A successful revocation records the `revocation_tax_year` and the `reason`, advances the election's `version`, and contracts the election's occupied interval to run from its `effective_tax_year` through the year immediately preceding `revocation_tax_year` — which is precisely what frees the later years for a different election."
    PRD 3.7: "When the return carries a non-null `election_id`, that election must still be `ELECTED` and the return's `filing_basis` must equal the election's `election_basis`; a mismatch or a lapsed election is rejected with `ERR_ELECTION_BASIS_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/file_gated_by_governing_election_status
    """
    ctx = _approved_filing_with_election(
        election_basis="COMBINED_UNITARY", filing_basis="COMBINED_UNITARY",
        state_permits_early_revocation=True,
    )

    revoked = validate_success(api.revoke_election(
        ctx["election_id"],
        {"revocation_tax_year": 2026, "reason": "State combined regime replaced"},
        TM,
    ))
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_tax_year"] == 2026

    response = api.file_filing(
        ctx["filing_id"], {"confirmation_number": "CA-EFILE-2026-0021"},
        make_controller_headers("controller-01"),
    )

    validate_error(response, ApiErrorId.ERR_ELECTION_BASIS_MISMATCH.value)
    filing = read_filing(ctx["filing_id"])
    assert filing["preparation_status"] == "APPROVED"
    assert filing["filed_on_date"] is None


def test_transmission_is_unblocked_once_the_election_is_reinstated(api):
    """PRD 3.3: "Reinstatement takes a new `effective_tax_year` and a new `binding_years`, moves the election `REVOKED → ELECTED`, replaces both fields, recomputes `expires_after_tax_year` from them, clears `revocation_tax_year` back to null, increments `reinstatement_count` by 1 and advances the election's `version`."
    PRD 3.7: "Transmission is the moment the return becomes the state's business. A `Controller` or `TaxManager` supplies the `confirmation_number` the state's e-file system issued, the return moves `APPROVED → FILED`, the confirmation is stored and `filed_on_date` is stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/file_gated_by_governing_election_status
    """
    ctx = _approved_filing_with_election(
        election_basis="COMBINED_UNITARY", filing_basis="COMBINED_UNITARY",
        state_permits_early_revocation=True,
    )
    validate_success(api.revoke_election(
        ctx["election_id"],
        {"revocation_tax_year": 2026, "reason": "State combined regime replaced"},
        TM,
    ))
    validate_error(
        api.file_filing(
            ctx["filing_id"], {"confirmation_number": "CA-EFILE-2026-0021"},
            make_controller_headers("controller-01"),
        ),
        ApiErrorId.ERR_ELECTION_BASIS_MISMATCH.value,
    )

    reinstated = validate_success(api.reinstate_election(
        ctx["election_id"], {"effective_tax_year": 2026, "binding_years": 3}, TM
    ))
    assert reinstated["status"] == "ELECTED"
    assert reinstated["effective_tax_year"] == 2026
    assert reinstated["expires_after_tax_year"] == 2028
    assert reinstated["reinstatement_count"] == 1
    assert reinstated["revocation_tax_year"] is None

    filed = validate_success(api.file_filing(
        ctx["filing_id"], {"confirmation_number": "CA-EFILE-2026-0021"},
        make_controller_headers("controller-01"),
    ))
    assert filed["preparation_status"] == "FILED"
    assert filed["confirmation_number"] == "CA-EFILE-2026-0021"


# ─── Basis mismatch outranks the passed filing deadline ───────────────────────

def test_basis_mismatch_is_reported_ahead_of_the_passed_filing_deadline(api):
    """PRD 2.11: "A return whose basis contradicts its governing election *and* which is being transmitted after its due date fails at band 23 with `ERR_ELECTION_BASIS_MISMATCH`, not at band 34."
    PRD 3.7: "When the return carries a non-null `election_id`, that election must still be `ELECTED` and the return's `filing_basis` must equal the election's `election_basis`; a mismatch or a lapsed election is rejected with `ERR_ELECTION_BASIS_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/election_basis_referential_beats_filing_deadline_temporal
    """
    ctx = _approved_filing_with_election(
        election_basis="SEPARATE_ENTITY", filing_basis="COMBINED_UNITARY",
    )
    assert read_filing(ctx["filing_id"])["original_due_date"].startswith(
        "2027-04-15T00:00:00"
    )
    set_clock("2027-06-01T00:00:00Z")

    response = api.file_filing(
        ctx["filing_id"], {"confirmation_number": "CA-EFILE-2026-0009"},
        make_controller_headers("controller-01"),
    )

    error = validate_error(response, ApiErrorId.ERR_ELECTION_BASIS_MISMATCH.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_FILING_DEADLINE_PASSED.value


def test_a_rejected_transmission_leaves_the_return_approved_and_unstamped(api):
    """PRD 3.7: "Transmission is the moment the return becomes the state's business. A `Controller` or `TaxManager` supplies the `confirmation_number` the state's e-file system issued, the return moves `APPROVED → FILED`, the confirmation is stored and `filed_on_date` is stamped from the logical clock."
    PRD 2.11: "A return whose basis contradicts its governing election *and* which is being transmitted after its due date fails at band 23 with `ERR_ELECTION_BASIS_MISMATCH`, not at band 34."

    Design: Difficulty/priority_pair_validation_conflict/election_basis_referential_beats_filing_deadline_temporal
    """
    ctx = _approved_filing_with_election(
        election_basis="SEPARATE_ENTITY", filing_basis="COMBINED_UNITARY",
    )
    set_clock("2027-06-01T00:00:00Z")

    validate_error(
        api.file_filing(
            ctx["filing_id"], {"confirmation_number": "CA-EFILE-2026-0009"},
            make_controller_headers("controller-01"),
        ),
        ApiErrorId.ERR_ELECTION_BASIS_MISMATCH.value,
    )

    filing = read_filing(ctx["filing_id"])
    assert filing["preparation_status"] == "APPROVED"
    assert filing["filed_on_date"] is None
    assert filing["confirmation_number"] is None


# ─── The preparation axis ─────────────────────────────────────────────────────

def test_approval_of_a_draft_return_is_refused(api):
    """PRD 3.7: "The preparation axis of a return runs `DRAFT → FACTORS_LOCKED → IN_REVIEW → APPROVED → FILED`, with two loops back — a rejection loop and an amendment loop — and no terminal state at all."
    PRD 2.11: "7. The return's `preparation_status` is a legal source state for the requested operation (`ERR_INVALID_FILING_STATE`)."

    Design: Corner/state_machines/approve_from_draft_returns_invalid_filing_state
    """
    ctx = setup_computed_filing(variant="JOYCE")

    response = api.approve_filing(
        ctx["filing_id"], {"approval_note": "premature"},
        make_controller_headers("controller-01"),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_FILING_STATE.value)
    assert response.status_code == 409
    filing = read_filing(ctx["filing_id"])
    assert filing["preparation_status"] == "DRAFT"
    assert filing["approver_user_id"] is None


def test_second_submit_for_review_is_refused_and_keeps_the_first_preparer(api):
    """PRD 3.7: "Submitting for review is where the audit trail begins. A `StateAnalyst` or a `Controller` moves the return `FACTORS_LOCKED → IN_REVIEW`, optionally attaching a `preparer_note`, and the service records that caller's `X-User-ID` as the return's `preparer_user_id`."
    PRD 2.11: "7. The return's `preparation_status` is a legal source state for the requested operation (`ERR_INVALID_FILING_STATE`)."

    Design: Corner/state_machines/submit_review_twice_returns_invalid_filing_state
    """
    ctx = setup_locked_filing()

    first = validate_success(api.submit_review(
        ctx["filing_id"], {"preparer_note": "first"},
        make_state_analyst_headers("analyst-01"),
    ))
    assert first["preparation_status"] == "IN_REVIEW"
    assert first["preparer_user_id"] == "analyst-01"

    second = api.submit_review(
        ctx["filing_id"], {"preparer_note": "second"},
        make_state_analyst_headers("analyst-99"),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_FILING_STATE.value)

    assert read_filing(ctx["filing_id"])["preparer_user_id"] == "analyst-01", (
        "A refused re-submission must not overwrite the recorded preparer"
    )


def test_rejection_reopens_the_return_for_further_modification_lines(api):
    """PRD 3.7: "Rejection sends the work back: a `Controller` or `TaxManager` supplies a `rejection_reason`, the return moves `IN_REVIEW → DRAFT`, `approver_user_id` is cleared to null, and modification lines and credit claims become creatable again."
    PRD 3.5: "Each line's `line_amount` is its `raw_amount` multiplied by its `allocation_ratio`, rounded half up to 2 decimal places, and its `sequence_number` is its 1-based position among the return's modification lines ordered by `created_at` ascending."

    Design: Corner/state_machines/reject_returns_filing_to_draft_and_clears_approver
    """
    ctx = setup_filing_in_review(preparer_user_id="analyst-01")

    rejected = validate_success(api.reject_filing(
        ctx["filing_id"], {"rejection_reason": "Recheck CA throwback sales"},
        make_controller_headers("controller-01"),
    ))
    assert rejected["preparation_status"] == "DRAFT"
    assert rejected["approver_user_id"] is None
    assert rejected["preparer_user_id"] == "analyst-01"

    line = validate_success(api.create_modification(ctx["filing_id"], {
        "modification_code": "EXTRA_ADDBACK", "direction": "ADDITION",
        "raw_amount": 1000.00, "allocation_ratio": 0.5,
    }, SA), 201)
    assert_money(line["line_amount"], 500.00, "new line_amount")

    assert_money(read_filing(ctx["filing_id"])["modification_total"], 1176.57,
                 "modification_total after the extra line")


def test_the_preparer_may_not_approve_the_return_they_submitted(api):
    """PRD 3.7: "The one thing approval will not tolerate is the same person doing both jobs: when the approving caller's `X-User-ID` equals the return's stored `preparer_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.7: "Approval is then a `Controller` or `TaxManager` action moving the return `IN_REVIEW → APPROVED`, optionally attaching an `approval_note`, and recording the approving caller's `X-User-ID` as `approver_user_id`."

    Design: Corner/validations/segregation_of_duties_blocks_self_approval
    """
    ctx = setup_filing_in_review(
        preparer_user_id="controller-07", preparer_role="Controller",
    )
    assert read_filing(ctx["filing_id"])["preparer_user_id"] == "controller-07"

    response = api.approve_filing(
        ctx["filing_id"], {"approval_note": "self approval"},
        make_controller_headers("controller-07"),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert response.status_code == 403
    blocked = read_filing(ctx["filing_id"])
    assert blocked["preparation_status"] == "IN_REVIEW"
    assert blocked["approver_user_id"] is None

    approved = validate_success(api.approve_filing(
        ctx["filing_id"], {"approval_note": "independent review"},
        make_controller_headers("controller-08"),
    ))
    assert approved["preparation_status"] == "APPROVED"
    assert approved["approver_user_id"] == "controller-08"


def test_transmission_after_the_due_date_is_refused(api):
    """PRD 3.7: "And the current logical clock must be at or before the return's `extended_due_date` when one has been set, or at or before its `original_due_date` when none has; the boundary instant itself is allowed, and a strictly later instant is rejected with `ERR_FILING_DEADLINE_PASSED`."

    Design: Corner/validations/filing_after_due_date_returns_deadline_error
    """
    ctx = setup_filing_in_review()
    validate_success(api.approve_filing(
        ctx["filing_id"], {"approval_note": "reviewed"},
        make_controller_headers("controller-01"),
    ))
    set_clock("2027-04-16T00:00:00Z")

    response = api.file_filing(
        ctx["filing_id"], {"confirmation_number": "CA-EFILE-LATE"},
        make_controller_headers("controller-01"),
    )

    validate_error(response, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value)
    filing = read_filing(ctx["filing_id"])
    assert filing["preparation_status"] == "APPROVED"
    assert filing["filed_on_date"] is None


def test_transmission_at_the_exact_due_date_instant_succeeds(api):
    """PRD 3.7: "And the current logical clock must be at or before the return's `extended_due_date` when one has been set, or at or before its `original_due_date` when none has; the boundary instant itself is allowed, and a strictly later instant is rejected with `ERR_FILING_DEADLINE_PASSED`."
    PRD 2.5: "Where a rule says an action must occur "at or before" a deadline, the boundary instant itself is allowed — a request handled exactly at the deadline succeeds, and only a strictly later instant fails."

    Design: Corner/validations/filing_at_exact_due_date_instant_succeeds
    """
    ctx = setup_filing_in_review()
    validate_success(api.approve_filing(
        ctx["filing_id"], {"approval_note": "reviewed"},
        make_controller_headers("controller-01"),
    ))
    set_clock("2027-04-15T00:00:00Z")

    filed = validate_success(api.file_filing(
        ctx["filing_id"], {"confirmation_number": "CA-EFILE-ONTIME"},
        make_controller_headers("controller-01"),
    ))

    assert filed["preparation_status"] == "FILED"
    assert filed["filed_on_date"].startswith("2027-04-15T00:00:00"), (
        f"filed_on_date must be stamped from the logical clock, got {filed['filed_on_date']}"
    )
    assert filed["confirmation_number"] == "CA-EFILE-ONTIME"


def test_return_listing_filters_by_registration_and_tax_year(api):
    """PRD 2.3: "Returns may be filtered by `registration_id`, `election_id`, `primary_legal_entity_id`, `tax_year` and `preparation_status`."
    PRD 2.3: "For list responses the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` is true when `offset` plus the number of returned records is less than `total_count`."

    Design: Corner/endpoints/filings_list_filters_by_registration_and_tax_year
    """
    ctx = setup_draft_filing()
    older = create_filing(
        ctx["registration_id"], tax_year=2025, filing_basis="COMBINED_UNITARY",
        federal_taxable_income=4000000,
    )

    rows, meta = validate_paginated(api.list_filings(AUD, {
        "registration_id": ctx["registration_id"], "tax_year": 2025,
        "limit": 10, "offset": 0,
    }))

    assert len(rows) == 1 and rows[0]["id"] == older["id"], (
        "The tax_year filter must return only the 2025 return"
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["original_due_date"].startswith("2026-04-15T00:00:00")

    _, unfiltered_meta = validate_paginated(api.list_filings(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert unfiltered_meta["total_count"] == 2


def test_separate_entity_return_without_a_primary_member_is_rejected(api):
    """PRD 3.4: "The primary member is **required** when `filing_basis` is `SEPARATE_ENTITY` and ignored otherwise; omitting it on a separate-entity return is rejected with `ERR_PRIMARY_ENTITY_REQUIRED`, and naming a member that belongs to some other group is rejected with `ERR_ENTITY_NOT_IN_GROUP`."

    Design: Corner/validations/separate_entity_filing_without_primary_entity_returns_error
    """
    ctx = setup_bare_registration(group_overrides={"name": "Primary Entity Group"})

    response = api.create_filing(ctx["registration_id"], {
        "tax_year": 2026, "filing_basis": "SEPARATE_ENTITY",
        "federal_taxable_income": 1000000,
    }, SA)

    validate_error(response, ApiErrorId.ERR_PRIMARY_ENTITY_REQUIRED.value)
    rows, _ = validate_paginated(api.list_filings(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert rows == [], "A rejected return create must persist nothing"
