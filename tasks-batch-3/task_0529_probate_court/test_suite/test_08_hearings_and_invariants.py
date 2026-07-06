"""Hearing scheduling conflicts and conservation invariants (Difficulty queue:
resource_temporal_overlap, compensating_invariant)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_estate, schedule_hearing,
    create_estate_with_appointed_pr,
    add_beneficiary, list_asset, appraise_asset, marshal_asset,
    advance_open_to_accounting, file_final_accounting, approve_final_accounting,
    propose_distribution, approve_distribution,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


# --------------------------------------------------------------------------- #
# resource_temporal_overlap
# --------------------------------------------------------------------------- #
def test_courtroom_half_open_overlap_rejected(api):
    """PRD §3.11: "The new hearing conflicts with an existing scheduled hearing
    sharing its `courtroom_code` when the new hearing's `start_at` is before the
    existing hearing's `end_at` and the existing hearing's `start_at` is before the
    new hearing's `end_at`; a conflict is rejected with `ERR_COURTROOM_CONFLICT`."

    Existing C1 10:00-11:00; a new C1 10:30-11:30 (different judge to isolate the
    courtroom rule) overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/courtroom_half_open_overlap_rejected_adjacency_allowed
    """
    est = create_estate(gross_estate_value_cents=300_000)
    schedule_hearing(est["id"], "C1", "judge-1",
                     "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    resp = api.create_hearing({
        "estate_id": est["id"], "hearing_type": "ACCOUNTING",
        "courtroom_code": "C1", "judge_user_id": "judge-9",
        "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_COURTROOM_CONFLICT)


def test_courtroom_adjacency_allowed(api):
    """PRD §3.11: "Because the interval is half-open, exact adjacency — where the
    new hearing's `start_at` equals the existing hearing's `end_at` — is permitted,
    so back-to-back hearings in the same room are allowed."

    Existing C1 10:00-11:00; a new C1 11:00-12:00 is back-to-back and accepted.

    Design: Difficulty/resource_temporal_overlap/courtroom_half_open_overlap_rejected_adjacency_allowed
    """
    est = create_estate(gross_estate_value_cents=300_000)
    schedule_hearing(est["id"], "C1", "judge-1",
                     "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    resp = api.create_hearing({
        "estate_id": est["id"], "hearing_type": "ACCOUNTING",
        "courtroom_code": "C1", "judge_user_id": "judge-9",
        "start_at": "2026-06-01T11:00:00Z", "end_at": "2026-06-01T12:00:00Z",
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED", (
        f"back-to-back hearing (start==prev end) should be accepted, got {data['status']}")


def test_judge_calendar_buffer_overlap_rejected(api):
    """PRD §3.11: "Expand the new hearing's window by 30 minutes on each side, then
    the new hearing conflicts with an existing scheduled hearing sharing its
    `judge_user_id` when the new hearing's `start_at` minus 30 minutes is at or
    before the existing hearing's `end_at` and the existing hearing's `start_at` is
    at or before the new hearing's `end_at` plus 30 minutes; a conflict is rejected
    with `ERR_JUDGE_CALENDAR_CONFLICT`." PRD §3.11: "a gap of exactly 30 minutes
    between two of a judge's hearings still collides — the gap between them must
    strictly exceed the recess."

    Existing judge-7 10:00-11:00; a new judge-7 11:15-12:00 (gap 15 < 30, different
    courtroom to isolate the judge rule) collides.

    Design: Difficulty/resource_temporal_overlap/judge_calendar_buffer_overlap_rejected
    """
    est = create_estate(gross_estate_value_cents=300_000)
    schedule_hearing(est["id"], "C1", "judge-7",
                     "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    resp = api.create_hearing({
        "estate_id": est["id"], "hearing_type": "ACCOUNTING",
        "courtroom_code": "C2", "judge_user_id": "judge-7",
        "start_at": "2026-06-01T11:15:00Z", "end_at": "2026-06-01T12:00:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_JUDGE_CALENDAR_CONFLICT)


# --------------------------------------------------------------------------- #
# compensating_invariant
# --------------------------------------------------------------------------- #
def test_bond_obligation_approve_discharge_net_zero(api):
    """PRD §2.7: "approving a bond and then appointing the representative it backs
    raises this quantity by the bond's penal amount, and discharging the
    representative (which exonerates that bond) lowers it by exactly the same
    amount, so an error-free approve-then-discharge round trip nets to zero."
    PRD §3.4: "On discharge, if the representative holds a `bond_id`, that bond is
    cascaded to `EXONERATED`".

    Drive a FULL estate to CLOSED with an APPROVED bond (penal 3250000), then
    discharge: the bond is EXONERATED and the outstanding bond obligation (sum of
    penal over APPROVED bonds) returns to 0.

    Design: Difficulty/compensating_invariant/bond_obligation_approve_discharge_net_zero
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    # Drive to CLOSED: no assets/claims, so all accountings balance trivially (0 == 0).
    advance_open_to_accounting(est["id"])
    final = file_final_accounting(est["id"])        # -> DISTRIBUTING
    approve_final_accounting(est["id"], final["id"])  # -> CLOSED

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    discharged = validate_success(
        api.discharge_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    assert discharged["status"] == "DISCHARGED"

    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "EXONERATED", (
        f"bond should be EXONERATED on discharge, got {bond_after['status']}")

    # Outstanding bond obligation = sum of penal over APPROVED bonds -> 0.
    bonds = validate_success(api.list_bonds(CLERK, params={"estate_id": est["id"]}))
    if isinstance(bonds, dict):
        bonds = bonds.get("data", bonds)
    approved_total = sum(
        b["penal_amount_cents"] for b in bonds if b["status"] == "APPROVED")
    assert approved_total == 0, (
        f"outstanding bond obligation should return to 0, got {approved_total}")


def test_cash_pool_propose_approve_return_net_zero(api):
    """PRD §2.7: "because only payment debits the pool — neither proposing,
    approving, nor returning a distribution moves cash — a distribution taken from
    `PROPOSED` through `APPROVED` to `RETURNED` leaves the pool untouched, a
    net-zero round trip distinct from the bond invariant."

    Marshaling CASH 1000000 sets the pool to 1000000; a distribution driven
    PROPOSE -> APPROVE -> RETURN debits nothing, leaving marshaled_cash_cents at
    1000000.

    Design: Difficulty/compensating_invariant/cash_pool_propose_approve_return_net_zero
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    ben = add_beneficiary(est["id"], share_bps=10_000)
    asset = list_asset(est["id"], "CASH", 1_000_000, "Cash")
    appraise_asset(est["id"], asset["id"], 1_000_000)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    file_final_accounting(est["id"])                 # -> DISTRIBUTING

    dist = propose_distribution(est["id"], ben["id"], 400_000)
    approve_distribution(est["id"], dist["id"])

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    returned = validate_success(
        api.return_distribution(dist["id"], {"expected_estate_version": v}, REP))
    assert returned["status"] == "RETURNED"

    est_after = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after["marshaled_cash_cents"] == 1_000_000, (
        f"propose/approve/return should leave the pool at 1000000, got "
        f"{est_after['marshaled_cash_cents']}")


# --------------------------------------------------------------------------- #
# Second tests (≥2 per instance)
# --------------------------------------------------------------------------- #
def test_judge_calendar_exact_recess_gap_still_collides(api):
    """PRD §3.11: "Because both edges compare with 'at or before,' a gap of exactly
    30 minutes between two of a judge's hearings still collides — the gap between
    them must strictly exceed the recess."

    Existing judge-7 10:00-11:00; a new judge-7 11:30-12:00 has a gap of exactly 30
    minutes and is still rejected ERR_JUDGE_CALENDAR_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/judge_calendar_buffer_overlap_rejected
    """
    est = create_estate(gross_estate_value_cents=300_000)
    schedule_hearing(est["id"], "C1", "judge-7",
                     "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    resp = api.create_hearing({
        "estate_id": est["id"], "hearing_type": "ACCOUNTING",
        "courtroom_code": "C2", "judge_user_id": "judge-7",
        "start_at": "2026-06-01T11:30:00Z", "end_at": "2026-06-01T12:00:00Z",
    }, CLERK)
    validate_error(resp, ApiErrorId.ERR_JUDGE_CALENDAR_CONFLICT)


def test_discharge_exonerates_bond_side_effect(api):
    """PRD §3.4: "On discharge, if the representative holds a `bond_id`, that bond
    is cascaded to `EXONERATED` (the compensating counterpart to the
    approve-and-bind step, restoring the outstanding bond obligation to its
    pre-appointment value)".

    The discharge cascade itself: after a CLOSED-estate discharge the backing bond
    is EXONERATED (the compensating half of the bond-obligation round trip).

    Design: Difficulty/compensating_invariant/bond_obligation_approve_discharge_net_zero
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    advance_open_to_accounting(est["id"])
    final = file_final_accounting(est["id"])
    approve_final_accounting(est["id"], final["id"])   # -> CLOSED

    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(
        api.discharge_representative(rep["id"], {"expected_estate_version": v}, JUDGE))
    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "EXONERATED", (
        f"discharge should exonerate the bond, got {bond_after['status']}")


def test_cash_pool_unchanged_through_propose_and_approve(api):
    """PRD §2.7: "because only payment debits the pool — neither proposing,
    approving, nor returning a distribution moves cash".

    Isolating the propose+approve legs: after PROPOSE then APPROVE (before any
    return), the 1,000,000 pool is still untouched, since neither leg moves cash.

    Design: Difficulty/compensating_invariant/cash_pool_propose_approve_return_net_zero
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=6_000_000)
    ben = add_beneficiary(est["id"], share_bps=10_000)
    asset = list_asset(est["id"], "CASH", 1_000_000, "Cash")
    appraise_asset(est["id"], asset["id"], 1_000_000)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    file_final_accounting(est["id"])                 # -> DISTRIBUTING

    dist = propose_distribution(est["id"], ben["id"], 400_000)
    est_after_propose = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after_propose["marshaled_cash_cents"] == 1_000_000, (
        f"PROPOSE must not move cash, got {est_after_propose['marshaled_cash_cents']}")

    approve_distribution(est["id"], dist["id"])
    est_after_approve = get_success_data(api.get_estate(est["id"], CLERK))
    assert est_after_approve["marshaled_cash_cents"] == 1_000_000, (
        f"APPROVE must not move cash, got {est_after_approve['marshaled_cash_cents']}")
