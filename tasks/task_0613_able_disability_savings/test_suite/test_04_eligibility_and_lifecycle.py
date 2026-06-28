"""Eligibility, certification windows, account lifecycle loops, death cascade, and
clock-driven expiry — the cross-entity state machinery of the program.

Difficulty (queue A) instances appear with >=2 tests each; corner (queue B)
instances appear once. Each docstring ends with its Design tag.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_certification_payload,
    create_representative_payload,
    make_program_admin_headers,
    make_beneficiary_headers,
    setup_program_and_option,
    setup_certified_beneficiary,
    setup_open_account,
    create_program,
    create_investment_option,
    create_beneficiary,
    create_pending_certification,
    add_representative,
    post_contribution,
    request_distribution,
    record_death,
    file_medicaid_claim,
    get_account,
    get_beneficiary,
    get_certification,
    get_representative,
    get_distribution,
)
from test_helpers.fixtures import ADMIN


# ===========================================================================
# Difficulty: non_linear_state_machine / account_suspend_reinstate_cycle
# ===========================================================================
def test_account_suspend_moves_to_suspended(api):
    """PRD 3.3: "An administrator may suspend an account that is in `OPEN` status, moving it
    to `SUSPENDED`; while suspended, contributions and distributions are blocked."

    Design: Difficulty/non_linear_state_machine/account_suspend_reinstate_cycle
    """
    _, _, _, account = setup_open_account()
    resp = api.suspend_account(account["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "SUSPENDED"


def test_account_reinstate_returns_to_open(api):
    """PRD 3.3: "Reinstatement returns an account from `SUSPENDED` to `OPEN`, but only when
    the beneficiary's `eligibility_status` is `CERTIFIED`; a reinstatement attempted while the
    beneficiary is not certified is rejected with `ERR_NOT_CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/account_suspend_reinstate_cycle
    """
    _, _, _, account = setup_open_account()
    api.suspend_account(account["id"], ADMIN)
    resp = api.reinstate_account(account["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "OPEN", "reinstate returns the account to a prior state (OPEN)"


# ===========================================================================
# Difficulty: transitive_cascade / death_freezes_account_then_revokes_reps_depth3
# ===========================================================================
def _setup_death_scenario(api):
    program, option, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_000_000, account["version"])
    rep = add_representative(
        account["id"], beneficiary["id"], relationship="PARENT",
        authority_start="2026-01-01", authority_end="2030-01-01",
    )
    dist = request_distribution(account["id"], 200_000, beneficiary["id"], category="HEALTH")
    return beneficiary, account, rep, dist


def test_death_freezes_account_and_revokes_reps(api):
    """PRD 3.9: "Recording death sets `is_deceased` to true and freezes the account: an account
    in `OPEN` or `SUSPENDED` moves to `FROZEN_DEATH`. The freeze cascades. Every `ACTIVE`
    `AuthorizedRepresentative` on the account moves to `REVOKED`."

    Design: Difficulty/transitive_cascade/death_freezes_account_then_revokes_reps_depth3
    """
    beneficiary, account, rep, dist = _setup_death_scenario(api)
    record_death(beneficiary["id"])
    assert get_account(account["id"])["status"] == "FROZEN_DEATH"
    assert get_representative(rep["id"])["status"] == "REVOKED"
    assert get_beneficiary(beneficiary["id"])["is_deceased"] is True


def test_death_rejects_pending_distributions(api):
    """PRD 3.9: "Every distribution still in `REQUESTED` or `APPROVED` status moves to
    `REJECTED`, since no further disbursements may be made to a deceased beneficiary."

    Design: Difficulty/transitive_cascade/death_freezes_account_then_revokes_reps_depth3
    """
    beneficiary, account, rep, dist = _setup_death_scenario(api)
    record_death(beneficiary["id"])
    assert get_distribution(dist["id"])["status"] == "REJECTED"


# ===========================================================================
# Difficulty: transitive_cascade / clock_expires_cert_then_suspends_account_depth2
# ===========================================================================
def _setup_clock_expiry(api):
    program, option = setup_program_and_option()
    beneficiary = create_beneficiary(program["id"])
    cert = create_pending_certification(beneficiary["id"], expires_on="2026-06-30")
    validate_success(api.decide_certification(cert["id"], {"decision": "APPROVE"}, ADMIN))
    account = validate_success(
        api.create_account(
            {"beneficiary_id": beneficiary["id"], "investment_option_id": option["id"]}, ADMIN
        ),
        201,
    )
    return beneficiary, cert, account


def test_clock_advance_expires_certification(api):
    """PRD 2.8: "any `Certification` in `CERTIFIED` status whose recertification deadline has
    been reached or passed is moved to `EXPIRED`"

    Design: Difficulty/transitive_cascade/clock_expires_cert_then_suspends_account_depth2
    """
    beneficiary, cert, account = _setup_clock_expiry(api)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", ADMIN))
    assert get_certification(cert["id"])["status"] == "EXPIRED"
    assert get_beneficiary(beneficiary["id"])["eligibility_status"] == "EXPIRED"


def test_clock_expiry_suspends_open_account(api):
    """PRD 2.8: "and if that certification's beneficiary has an `Account` in `OPEN` status,
    the account is moved to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/clock_expires_cert_then_suspends_account_depth2
    """
    beneficiary, cert, account = _setup_clock_expiry(api)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", ADMIN))
    assert get_account(account["id"])["status"] == "SUSPENDED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / account_reinstate_requires_beneficiary_certified
# ===========================================================================
def test_reinstate_with_expired_beneficiary_rejected(api):
    """PRD 3.3: "a reinstatement attempted while the beneficiary is not certified is rejected
    with `ERR_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/account_reinstate_requires_beneficiary_certified
    """
    beneficiary, cert, account = _setup_clock_expiry(api)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", ADMIN))  # SUSPENDED + EXPIRED
    resp = api.reinstate_account(account["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_CERTIFIED.value, 409)


def test_reinstate_blocked_account_stays_suspended(api):
    """PRD 3.3: "Reinstatement returns an account from `SUSPENDED` to `OPEN`, but only when
    the beneficiary's `eligibility_status` is `CERTIFIED`; a reinstatement attempted while the
    beneficiary is not certified is rejected with `ERR_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/account_reinstate_requires_beneficiary_certified
    """
    beneficiary, cert, account = _setup_clock_expiry(api)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", ADMIN))
    api.reinstate_account(account["id"], ADMIN)
    assert get_account(account["id"])["status"] == "SUSPENDED"
    assert get_beneficiary(beneficiary["id"])["eligibility_status"] == "EXPIRED"


# ===========================================================================
# Difficulty: resource_temporal_overlap / cert_window_half_open_adjacency_ok_overlap_rejected
# ===========================================================================
def test_cert_window_adjacent_endpoint_accepted(api):
    """PRD 2.9: "under this half-open rule, two windows that merely share an endpoint — one
    ending on exactly the date the next begins — do not overlap."

    Design: Difficulty/resource_temporal_overlap/cert_window_half_open_adjacency_ok_overlap_rejected
    """
    program, _ = setup_program_and_option()
    beneficiary = create_beneficiary(program["id"])
    create_pending_certification(beneficiary["id"], effective_date="2026-01-01", expires_on="2027-01-01")
    # A window starting exactly on the first's expires_on is adjacency, not overlap.
    resp = api.create_certification(
        beneficiary["id"],
        create_certification_payload(effective_date="2027-01-01", expires_on="2028-01-01"),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"


def test_cert_window_overlap_rejected(api):
    """PRD 3.2: "the proposed window is checked for overlap against every existing certification
    of the beneficiary regardless of that certification's status, using the half-open rule of
    Section 2.9; an overlap is rejected with `ERR_CERT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/cert_window_half_open_adjacency_ok_overlap_rejected
    """
    program, _ = setup_program_and_option()
    beneficiary = create_beneficiary(program["id"])
    create_pending_certification(beneficiary["id"], effective_date="2026-01-01", expires_on="2027-01-01")
    # A window starting 2026-12-31 falls before the first's expires_on -> overlap.
    resp = api.create_certification(
        beneficiary["id"],
        create_certification_payload(effective_date="2026-12-31", expires_on="2027-06-30"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_OVERLAP.value, 409)


# ===========================================================================
# Difficulty: resource_temporal_overlap / rep_authority_closed_shared_endpoint_collides
# ===========================================================================
def test_rep_authority_shared_endpoint_collides(api):
    """PRD 2.9: "Two authority windows on the same account, for the same `relationship`, where
    both representatives are `ACTIVE`, overlap when the new window's `authority_start` is on or
    before the existing window's `authority_end` and the existing window's `authority_start` is
    on or before the new window's `authority_end`; under this closed rule, two authority windows
    that touch at a shared endpoint date do overlap."

    Design: Difficulty/resource_temporal_overlap/rep_authority_closed_shared_endpoint_collides
    """
    _, _, beneficiary, account = setup_open_account()
    add_representative(
        account["id"], beneficiary["id"], full_name="Parent One", relationship="PARENT",
        authority_start="2026-01-01", authority_end="2028-01-01",
    )
    # Second PARENT rep starting exactly on the first's authority_end -> closed-interval collision.
    resp = api.create_representative(
        account["id"],
        create_representative_payload(
            full_name="Parent Two", relationship="PARENT",
            authority_start="2028-01-01", authority_end="2030-01-01",
        ),
        make_beneficiary_headers(beneficiary["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REP_AUTHORITY_OVERLAP.value, 409)


def test_rep_authority_different_relationship_no_collision(api):
    """PRD 3.5: "the proposed window is tested for overlap against every `ACTIVE` representative
    on the same account whose `relationship` matches the new one, using the closed-interval rule
    of Section 2.9 in which a shared endpoint date does collide"

    Design: Difficulty/resource_temporal_overlap/rep_authority_closed_shared_endpoint_collides
    """
    _, _, beneficiary, account = setup_open_account()
    add_representative(
        account["id"], beneficiary["id"], full_name="Parent One", relationship="PARENT",
        authority_start="2026-01-01", authority_end="2028-01-01",
    )
    # A GUARDIAN sharing the same window does NOT match the PARENT relationship, so no collision.
    resp = api.create_representative(
        account["id"],
        create_representative_payload(
            full_name="Guardian G", relationship="GUARDIAN",
            authority_start="2028-01-01", authority_end="2030-01-01",
        ),
        make_beneficiary_headers(beneficiary["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"


# ===========================================================================
# Corner: state_machines / contribution_reverse_twice_returns_invalid_state
# ===========================================================================
def test_contribution_reverse_twice_returns_invalid_state(api):
    """PRD 3.6: "Reversal moves the contribution to `REVERSED`, decreases the account's
    `basis_cents` and `balance_cents` by `amount_cents`, decreases the matching year-to-date
    total by `amount_cents` so that cap headroom is restored, recomputes `ssi_posture`, and
    increments the account's `version` by one. `REVERSED` is terminal for a contribution."
    PRD 2.5: "then, for a state-transition endpoint, whether the target resource is in a legal
    state for the transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/contribution_reverse_twice_returns_invalid_state
    """
    _, _, _, account = setup_open_account()
    contrib = post_contribution(account["id"], 100_000, account["version"])
    validate_success(api.reverse_contribution(contrib["id"], ADMIN))
    resp = api.reverse_contribution(contrib["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner: state_machines / closed_account_settle_again_invalid_state
# ===========================================================================
def test_closed_account_settle_again_invalid_state(api):
    """PRD 3.12: "Settling moves the claim from `FILED` to `SETTLED`, decrements the account's
    `balance_cents` by the claim's `allowed_payback_cents`, records the `residual_to_estate_cents`
    left for the estate, and moves the account from `FROZEN_DEATH` to `CLOSED`."
    PRD 2.5: "then, for a state-transition endpoint, whether the target resource is in a legal
    state for the transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/closed_account_settle_again_invalid_state
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_000_000, account["version"])
    record_death(beneficiary["id"])
    claim = file_medicaid_claim(account["id"], 300_000)
    validate_success(api.settle_medicaid_claim(account["id"], claim["id"], ADMIN))
    resp = api.settle_medicaid_claim(account["id"], claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert get_account(account["id"])["status"] == "CLOSED"


# ===========================================================================
# Corner: state_machines / certify_onset_age_ineligible
# ===========================================================================
def test_certify_onset_age_ineligible(api):
    """PRD 3.2: "the beneficiary's age at disability onset, measured from `birth_date` to
    `disability_onset_date`, must be strictly less than the program's `disability_onset_max_age`
    — otherwise the approval is rejected with `ERR_ONSET_AGE_INELIGIBLE`"

    Design: Corner/state_machines/certify_onset_age_ineligible
    """
    program = create_program(disability_onset_max_age=26)
    # birth 2005-03-01, onset 2031-04-01 -> age 26 at onset, not strictly < 26.
    beneficiary = create_beneficiary(
        program["id"], birth_date="2005-03-01", disability_onset_date="2031-04-01"
    )
    cert = create_pending_certification(beneficiary["id"])
    resp = api.decide_certification(cert["id"], {"decision": "APPROVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ONSET_AGE_INELIGIBLE.value, 409)
    assert get_certification(cert["id"])["status"] == "PENDING"


# ===========================================================================
# Corner: validations / investment_change_limit_third_change_rejected
# ===========================================================================
def test_investment_change_limit_third_change_rejected(api):
    """PRD 3.4: "The change is barred when the number of investment-option changes already made
    in the current calendar year has reached the program's `max_investment_changes_per_year`; an
    attempt that would carry the count beyond that ceiling is rejected with
    `ERR_INVESTMENT_CHANGE_LIMIT`."

    Design: Corner/validations/investment_change_limit_third_change_rejected
    """
    program = create_program(max_investment_changes_per_year=2)
    opt1 = create_investment_option(program["id"], name="Moderate", risk_tier="MODERATE")
    opt2 = create_investment_option(program["id"], name="Aggressive", risk_tier="AGGRESSIVE")
    opt3 = create_investment_option(program["id"], name="Conservative", risk_tier="CONSERVATIVE")
    beneficiary = create_beneficiary(program["id"])
    cert = create_pending_certification(beneficiary["id"])
    validate_success(api.decide_certification(cert["id"], {"decision": "APPROVE"}, ADMIN))
    account = validate_success(
        api.create_account(
            {"beneficiary_id": beneficiary["id"], "investment_option_id": opt1["id"]}, ADMIN
        ),
        201,
    )
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    validate_success(api.change_investment(account["id"], {"investment_option_id": opt2["id"]}, ben_headers))
    validate_success(api.change_investment(account["id"], {"investment_option_id": opt3["id"]}, ben_headers))
    resp = api.change_investment(account["id"], {"investment_option_id": opt1["id"]}, ben_headers)
    validate_error(resp, ApiErrorId.ERR_INVESTMENT_CHANGE_LIMIT.value, 409)
    assert get_account(account["id"])["investment_changes_ytd"] == 2


# ===========================================================================
# Corner: validations / diagnosis_required_on_diagnosis_basis_cert
# ===========================================================================
def test_diagnosis_required_on_diagnosis_basis_cert(api):
    """PRD 3.2: "When the basis is `DISABILITY_DIAGNOSIS`, the request must also carry a
    non-empty `diagnosis_code`; a diagnosis-based certification created without one is rejected
    with `ERR_DIAGNOSIS_REQUIRED`."

    Design: Corner/validations/diagnosis_required_on_diagnosis_basis_cert
    """
    program = create_program()
    beneficiary = create_beneficiary(program["id"])
    resp = api.create_certification(
        beneficiary["id"],
        create_certification_payload(basis="DISABILITY_DIAGNOSIS"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DIAGNOSIS_REQUIRED.value, 422)
