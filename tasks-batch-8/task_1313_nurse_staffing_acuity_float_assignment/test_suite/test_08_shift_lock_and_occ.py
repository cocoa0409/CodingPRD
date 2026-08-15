"""Shift locking and its cascade, optimistic concurrency on assignment
creation, and validation-order precedence on locked shifts."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_nurse,
    create_offer,
    get_shift,
    get_unit,
    get_week_ledger,
    propose_assignment,
    setup_unit_with_shift,
    validate_error,
    validate_success,
    walk_to_accepted,
)


class TestShiftLockCascade:

    def test_shift_lock_cascade(self):
        """PRD section 3.3: "The lock freezes `posture_at_lock` and
        `counted_at_lock` from their live values and stops all further posture
        recomputation".
        PRD section 3.3: "The lock cascade then resolves everything pending:
        each `PROPOSED` assignment on the shift transitions to `CANCELLED` with
        its projected twelve hours released back to the nurse's week, and any
        float request still `DEPLOYED` behind such an assignment transitions to
        `RELEASED`; every `OFFERED` incentive offer on the shift transitions to
        `EXPIRED` with its budget reserve released per §2.10."

        Design: Corner/state_machines/shift_lock_cascade
        """
        sc = setup_unit_with_shift(name="ICU A7", census=(2, 3, 2, 1))
        assert sc["shift"]["required_nurses"] == 4
        nurse = create_nurse(full_name="Lock Lee", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        asg = propose_assignment(sc["shift"]["id"], nurse["id"],
                                 sc["charge_headers"])
        assert asg["status"] == "PROPOSED"
        offer = create_offer(sc["shift"]["id"], premium_multiplier=1.25)
        # reserve = 0 + round(12 * 6000 * 0.25) = 18000
        assert offer["premium_reserve_cents"] == 18000
        assert get_unit(sc["unit"]["id"])["incentive_reserved_cents"] == 18000

        locked = validate_success(
            api_client.lock_shift(sc["shift"]["id"], sc["charge_headers"]),
            expected_status=200)
        assert locked["status"] == "LOCKED"
        # live posture with zero counted of required 4 was CRITICAL
        assert locked["posture_at_lock"] == "CRITICAL"
        assert locked["counted_at_lock"] == 0

        after_asg = validate_success(
            api_client.get_assignment(asg["id"], ADMIN), expected_status=200)
        assert after_asg["status"] == "CANCELLED", \
            f"PROPOSED must cascade to CANCELLED, got {after_asg['status']}"

        after_offer = validate_success(
            api_client.get_incentive_offer(offer["id"], ADMIN),
            expected_status=200)
        assert after_offer["status"] == "EXPIRED"

        unit = get_unit(sc["unit"]["id"])
        assert unit["incentive_reserved_cents"] == 0, \
            "the 18000 reserve must be released on expiry"

        ledger = get_week_ledger(nurse["id"], "2026-08-10")
        assert ledger["projected_hours"] == 0.0, \
            "the cancelled proposal must release its twelve projected hours"

    def test_shift_lock_twice_rejected(self):
        """PRD section 3.3: "Locking is the `ChargeNurse`'s end-of-planning act
        and is permitted from either `OPEN` or `STAFFED`; attempting it on an
        already-locked shift is rejected with `ERR_SHIFT_NOT_OPEN`."

        Design: Corner/state_machines/shift_lock_twice_rejected
        """
        sc = setup_unit_with_shift(name="ICU A8", census=(4, 0, 0, 0))
        first = api_client.lock_shift(sc["shift"]["id"], sc["charge_headers"])
        validate_success(first, expected_status=200)
        resp = api_client.lock_shift(sc["shift"]["id"], sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)


class TestStaleShiftVersion:

    def test_occ_stale_shift_version_rejected(self):
        """PRD section 2.6: "If another writer has advanced the shift's version
        since that observation — by creating another assignment, or because an
        acuity amendment recomputed the shift — the client's view of the
        shift's staffing state is stale, and the create is rejected with
        `ERR_STALE_SHIFT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_shift_version_rejected
        """
        sc = setup_unit_with_shift(name="ICU X1", census=(2, 3, 2, 1))
        stale_version = sc["shift"]["version"]
        n1 = create_nurse(full_name="Occ One", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"])
        n2 = create_nurse(full_name="Occ Two", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=5000,
                          home_unit_id=sc["unit"]["id"])
        # First create succeeds and advances Shift.version by one (PRD 3.4).
        first = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": n1["id"], "expected_shift_version": stale_version},
            sc["charge_headers"])
        validate_success(first, expected_status=201)

        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": n2["id"], "expected_shift_version": stale_version},
            sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_SHIFT_VERSION)
        assert resp.status_code == 412


class TestStateBeatsSafety:
    """Difficulty instance: state_beats_safety_on_assignment_create."""

    def _setup_locked_shift_with_nurses(self):
        sc = setup_unit_with_shift(name="ICU G", census=(4, 0, 0, 0))
        validate_success(
            api_client.lock_shift(sc["shift"]["id"], sc["charge_headers"]),
            expected_status=200)
        incompetent = create_nurse(
            full_name="Med Surg Mary", employment_type="CORE",
            competencies=["MED_SURG"], base_hourly_rate_cents=4500,
            home_unit_id=sc["unit"]["id"])
        unqualified = create_nurse(
            full_name="Not Qualified", employment_type="CORE",
            competencies=["ICU"], base_hourly_rate_cents=5000,
            home_unit_id=sc["unit"]["id"], charge_qualified=False)
        sc.update({"incompetent": incompetent, "unqualified": unqualified})
        return sc

    def test_locked_shift_beats_competency_failure(self):
        """PRD section 2.5: "The pipeline below is evaluated in this exact
        order, and an earlier failure masks all later ones" — state
        preconditions (item 6: "The target resource's current state permits the
        requested transition") run ahead of business safety rules (item 7).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assignment_create
        """
        sc = self._setup_locked_shift_with_nurses()
        shift = get_shift(sc["shift"]["id"])
        assert shift["status"] == "LOCKED"
        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": sc["incompetent"]["id"],
             "expected_shift_version": shift["version"]},
            sc["charge_headers"])
        # The nurse also lacks ICU competency, but the state error must win.
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)
        assert resp.status_code == 409

    def test_locked_shift_beats_charge_qualification_failure(self):
        """PRD section 2.5: "The pipeline below is evaluated in this exact
        order, and an earlier failure masks all later ones"
        PRD section 2.5: "**Business safety rules.** Competency, charge
        qualification, scheduling overlap, charge-slot capacity, the float
        skill-mix cap, sitter covering-assignment validity, the active-sitter
        lock on cancellation and completion, and the adequately-staffed gate on
        offer creation".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assignment_create
        """
        sc = self._setup_locked_shift_with_nurses()
        shift = get_shift(sc["shift"]["id"])
        resp = api_client.create_assignment(
            sc["shift"]["id"],
            {"nurse_id": sc["unqualified"]["id"], "is_charge": True,
             "expected_shift_version": shift["version"]},
            sc["charge_headers"])
        # is_charge on a non-qualified nurse would fail safety; state wins.
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)
        assert resp.status_code == 409
