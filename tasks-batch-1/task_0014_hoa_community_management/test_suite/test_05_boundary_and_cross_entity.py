"""Boundary-precision checks and cross-entity state dependencies (PRD §3.4
lien threshold; §3.7 voter eligibility; §3.6 ACC posture gate; §3.4 lien
satisfy)."""
from test_helpers import (
    ApiErrorId,
    bootstrap_acc_request_on_compliant_property,
    bootstrap_acc_request_on_suspended_property,
    bootstrap_election_open_with_voters,
    bootstrap_lien_via_cascade,
    bootstrap_tenant,
    create_assessment,
    create_owner,
    get_property,
    list_liens_for_property,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_acc_member_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 6 instance 1: lien threshold boundary precision
# ─────────────────────────────────────────────────────────────────────────────

def test_balance_at_exact_threshold_within_grace_does_not_file_lien(api):
    """PRD §3.3: "The transition from `DUE` to `OVERDUE` requires both that
    `outstanding_cents` is greater than zero and that the elapsed time
    since `due_date` strictly exceeds `late_fee_grace_days` whole days."
    PRD §3.4: "After the late-fee recomputation and the property-balance
    refresh, if `account_balance_cents` on the owning property is at least
    the community's `lien_threshold_cents` and no `FILED` `Lien` already
    exists on that property, the system files a `Lien` in the same atomic
    step."

    Setup: lien_threshold=300000, principal=300000 (so outstanding=balance
    = 300000 exactly == threshold), clock at 2026-01-15 (elapsed=14 days,
    not strictly past grace=15). DUE→OVERDUE precondition fails →
    no late_fee recomputation → no lien file step. Balance == threshold
    but COMPLIANT.

    Design: Difficulty/boundary_precision_check/lien_threshold_exact_equality_triggers_filed
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Bound1", owner_email="b1@x.com", owner_name="B1",
        unit_label="B-1", lien_threshold_cents=300000,
    )
    create_assessment(
        prop["id"], kind="SPECIAL", principal_cents=300000,
        due_date="2026-01-01T00:00:00Z",
    )
    set_clock("2026-01-15T00:00:00Z")
    prop_at_boundary = get_property(prop["id"])
    assert prop_at_boundary["account_balance_cents"] == 300000, (
        f"balance must equal principal 300000 when within grace, "
        f"got {prop_at_boundary['account_balance_cents']}"
    )
    assert prop_at_boundary["compliance_posture"] == "COMPLIANT", (
        f"posture must be COMPLIANT inside grace window, "
        f"got {prop_at_boundary['compliance_posture']}"
    )
    assert list_liens_for_property(prop["id"]) == [], (
        "no lien may be filed without OVERDUE transition"
    )


def test_balance_crossing_threshold_after_grace_files_lien_and_suspends(api):
    """PRD §3.4: "After the late-fee recomputation and the property-balance
    refresh, if `account_balance_cents` on the owning property is at least
    the community's `lien_threshold_cents` and no `FILED` `Lien` already
    exists on that property, the system files a `Lien` in the same atomic
    step. The new lien's `principal_at_filing_cents` is snapshotted from
    the property's then-current `account_balance_cents` at filing, its
    `filed_at` is stamped with `current_utc`, and its `status` is `FILED`.
    The same atomic step refreshes the property's `compliance_posture` to
    `SUSPENDED`."

    Setup: same Community + Assessment as the in-grace test, then advance
    clock 2 more days to 2026-01-17 (elapsed=16, strictly > grace=15).
    cycles=1 → per-cycle=2500+30000=32500 → balance=332500 ≥ 300000 →
    lien FILED and posture SUSPENDED.

    Design: Difficulty/boundary_precision_check/lien_threshold_exact_equality_triggers_filed
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Bound1Cross",
        owner_email="b1c@x.com", owner_name="B1C", unit_label="B-1C",
        lien_threshold_cents=300000,
    )
    create_assessment(
        prop["id"], kind="SPECIAL", principal_cents=300000,
        due_date="2026-01-01T00:00:00Z",
    )
    set_clock("2026-01-17T00:00:00Z")
    prop_after = get_property(prop["id"])
    assert prop_after["account_balance_cents"] == 332500, (
        f"balance must be 332500 (principal 300000 + late fee 32500), "
        f"got {prop_after['account_balance_cents']}"
    )
    assert prop_after["compliance_posture"] == "SUSPENDED", (
        f"posture must be SUSPENDED after cascade, "
        f"got {prop_after['compliance_posture']}"
    )
    filed = [le for le in list_liens_for_property(prop["id"])
             if le["status"] == "FILED"]
    assert len(filed) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Rule 6 instance 2: voter with zero properties → ERR_VOTER_INELIGIBLE
# ─────────────────────────────────────────────────────────────────────────────

def test_owner_with_no_property_cannot_cast_vote(api):
    """PRD §3.7: "The voter must be `is_eligible_voter` at vote time and
    must own at least one `Property` in this community; failing either
    test surfaces as `ERR_VOTER_INELIGIBLE`."

    Setup: Election OPEN; Owner1 owns a Property (and is the only eligible
    voter for the snapshot). Owner2 owns ZERO Properties — the empty
    collection edge — and is therefore not is_eligible_voter. Vote attempt
    by Owner2 → ERR_VOTER_INELIGIBLE.

    Design: Difficulty/boundary_precision_check/vote_uniqueness_at_zero_eligible_voter_count_returns_voter_ineligible
    """
    community, _owners, election = bootstrap_election_open_with_voters(
        community_name="Bound2",
        eligible_owner_count=1,  # the one Owner who DOES own a property
        cycle_label="FY-bound2",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    # Add a second owner with NO properties — empty-collection edge.
    no_prop_owner = create_owner(
        community["id"], email="noprop@x.com", full_name="NoProp",
    )
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": no_prop_owner["id"],
            "candidate_name": "Alice",
        },
        make_homeowner_headers(no_prop_owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VOTER_INELIGIBLE)


def test_owner_with_one_property_is_eligible_and_can_cast_vote(api):
    """PRD §3.7: "An `Owner` is considered eligible to vote at this snapshot
    moment when they own at least one `Property` in this community AND
    none of those properties has a `Lien` whose `status` is `FILED`."

    Boundary partner of the empty-collection case: an Owner with exactly
    one (lien-free) Property IS eligible and can cast their ballot
    successfully.

    Design: Difficulty/boundary_precision_check/vote_uniqueness_at_zero_eligible_voter_count_returns_voter_ineligible
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="Bound2Inv",
        eligible_owner_count=1,
        cycle_label="FY-bound2-inv",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    owner = owners[0]
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": owner["id"],
            "candidate_name": "Alice",
        },
        make_homeowner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["state"] == "CAST"
    assert data["election_id"] == election["id"]
    assert data["owner_id"] == owner["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule 7 instance 1: ACC approve requires Property.compliance_posture not SUSPENDED
# ─────────────────────────────────────────────────────────────────────────────

def test_acc_approve_succeeds_when_property_is_compliant(api):
    """PRD §3.6: "They may approve, but only when the underlying property's
    `compliance_posture` is not `SUSPENDED` — a suspended property's ACC
    approval is refused with `ERR_PROPERTY_SUSPENDED`. A successful approval
    moves the status from `SUBMITTED` to `APPROVED` (terminal) and stamps
    `decided_at` with `current_utc`."

    Setup: ACCRequest SUBMITTED on a property with posture COMPLIANT
    (control case). Approve must succeed and set status → APPROVED.

    Design: Difficulty/cross_entity_state_dependency/acc_approve_requires_property_compliance_posture_not_suspended
    """
    _community, _owner, _prop, acc = bootstrap_acc_request_on_compliant_property(
        community_name="X-pair-1", scope="APPEARANCE",
        description="Paint trim",
    )
    resp = api.approve_acc_request(acc["id"], make_acc_member_headers())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "APPROVED", (
        f"COMPLIANT property must allow approval, got {data['status']}"
    )


def test_acc_approve_rejected_when_property_is_suspended(api):
    """PRD §3.6: "They may approve, but only when the underlying property's
    `compliance_posture` is not `SUSPENDED` — a suspended property's ACC
    approval is refused with `ERR_PROPERTY_SUSPENDED`."

    Negative partner of the COMPLIANT test: setting the SAME approval
    against a SUSPENDED property must yield ERR_PROPERTY_SUSPENDED, proving
    the cross-entity precondition is enforced.

    Design: Difficulty/cross_entity_state_dependency/acc_approve_requires_property_compliance_posture_not_suspended
    """
    _community, _owner, _prop, acc, _lien = (
        bootstrap_acc_request_on_suspended_property(
            community_name="X-pair-1-neg", scope="APPEARANCE",
            description="Paint trim",
        )
    )
    resp = api.approve_acc_request(acc["id"], make_acc_member_headers())
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SUSPENDED)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 7 instance 2: Lien satisfy requires Property.account_balance_cents == 0
# ─────────────────────────────────────────────────────────────────────────────

def test_lien_satisfy_rejected_when_property_balance_nonzero(api):
    """PRD §3.4: "The `BoardSecretary` may mark it `SATISFIED` once the
    property's `account_balance_cents` is exactly zero; if the balance is
    anything other than zero, the satisfy action is refused with
    `ERR_BALANCE_NONZERO`."

    Setup: Lien FILED on a Property with positive balance (via the cascade
    bootstrap). Attempting to satisfy must reject with ERR_BALANCE_NONZERO.

    Design: Difficulty/cross_entity_state_dependency/lien_satisfy_requires_property_account_balance_zero
    """
    _community, _owner, _prop, _assess, lien = bootstrap_lien_via_cascade(
        community_name="X-pair-2",
        owner_email="x2@x.com", owner_name="X2", unit_label="X2-1",
    )
    resp = api.satisfy_lien(lien["id"], make_board_secretary_headers())
    validate_error(resp, ApiErrorId.ERR_BALANCE_NONZERO)


def test_lien_satisfy_succeeds_when_property_balance_zero(api):
    """PRD §3.4: "The `BoardSecretary` may mark it `SATISFIED` once the
    property's `account_balance_cents` is exactly zero; if the balance is
    anything other than zero, the satisfy action is refused with
    `ERR_BALANCE_NONZERO`. A successful satisfy refreshes the property's
    `compliance_posture`, which will return to `COMPLIANT` when no other
    `ACTIVE` violation rollups remain on the property."

    Positive partner: drive balance to zero by paying the outstanding
    assessment in full, then satisfy succeeds. After satisfy the property's
    posture must read COMPLIANT (no other ACTIVE rollups).

    Design: Difficulty/cross_entity_state_dependency/lien_satisfy_requires_property_account_balance_zero
    """
    _community, _owner, prop, assessment, lien = bootstrap_lien_via_cascade(
        community_name="X-pair-2-pos",
        owner_email="x2p@x.com", owner_name="X2P", unit_label="X2P-1",
    )
    # Pay the outstanding so account_balance_cents == 0.
    a_now = validate_success(
        api.get_assessment(
            assessment["id"], make_board_secretary_headers(),
        ), expected_status=200,
    )
    owed = a_now["principal_cents"] + a_now["late_fee_cents"] - a_now["paid_cents"]
    from test_helpers import apply_payment
    apply_payment(a_now["id"], owed, a_now["version"])
    prop_zero = get_property(prop["id"])
    assert prop_zero["account_balance_cents"] == 0, (
        f"balance must be 0 after full payment, got {prop_zero['account_balance_cents']}"
    )
    satisfied = validate_success(
        api.satisfy_lien(lien["id"], make_board_secretary_headers()),
        expected_status=200,
    )
    assert satisfied["status"] == "SATISFIED"
    final = get_property(prop["id"])
    assert final["compliance_posture"] == "COMPLIANT", (
        f"posture must return to COMPLIANT after lien satisfy with no other "
        f"ACTIVE rollups, got {final['compliance_posture']}"
    )
