"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.

Identity threading: ChargeNurse and StaffNurse are entity-backed roles, so
helpers create a real charge-qualified nurse per scenario and thread its id
into ChargeNurse headers, and use the assignment-owning nurse's id for
StaffNurse headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ICU_RATIOS, MED_SURG_RATIOS, MONDAY
from .factories import (
    create_nurse_payload,
    create_offer_payload,
    create_report_payload,
    create_shift_payload,
    create_snapshot_payload,
    create_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_charge_nurse_headers,
    make_staff_nurse_headers,
)

ADMIN = TEST_USERS["nurse_admin_headers"]
FLOAT_COORD = TEST_USERS["float_coordinator_headers"]
REGULATOR = TEST_USERS["regulator_headers"]

ALL_UNIT_TYPES = ["ICU", "STEP_DOWN", "MED_SURG", "TELEMETRY", "EMERGENCY"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 1 — configuration primitives (units, matrix, nurses)
# ---------------------------------------------------------------------------

def create_unit(name="4 West ICU", unit_type="ICU", bed_count=12,
                incentive_budget_cents=500000, auto_incentive_multiplier=None):
    payload = create_unit_payload(
        name=name, unit_type=unit_type, bed_count=bed_count,
        incentive_budget_cents=incentive_budget_cents,
    )
    if auto_incentive_multiplier is not None:
        payload["auto_incentive_multiplier"] = auto_incentive_multiplier
    return _ok("create_unit", api_client.create_unit(payload, ADMIN))


def create_full_matrix(unit_type="ICU", ratios=None):
    """Create all four acuity-level matrix rules for a unit type."""
    ratios = ratios or (ICU_RATIOS if unit_type == "ICU" else MED_SURG_RATIOS)
    rules = []
    for level, ratio in ratios.items():
        resp = api_client.create_matrix_rule(
            {"unit_type": unit_type, "acuity_level": level,
             "patients_per_nurse": ratio},
            ADMIN,
        )
        rules.append(_ok(f"create_matrix_rule[{level}]", resp))
    return rules


def create_nurse(full_name="Test Nurse", employment_type="CORE",
                 competencies=None, base_hourly_rate_cents=5000,
                 home_unit_id="__UNSET__", charge_qualified=False):
    payload = create_nurse_payload(
        full_name=full_name, employment_type=employment_type,
        competencies=competencies or ["ICU"],
        base_hourly_rate_cents=base_hourly_rate_cents,
        charge_qualified=charge_qualified,
    )
    if home_unit_id != "__UNSET__":
        payload["home_unit_id"] = home_unit_id
    elif employment_type == "CORE":
        raise AssertionError(
            "Setup failed at create_nurse: CORE nurse requires home_unit_id"
        )
    return _ok("create_nurse", api_client.create_nurse(payload, ADMIN))


def create_charge_nurse(home_unit_id, full_name="Charge Nurse"):
    """A real charge-qualified nurse whose id backs ChargeNurse headers."""
    return create_nurse(
        full_name=full_name, employment_type="CORE",
        competencies=ALL_UNIT_TYPES, base_hourly_rate_cents=7000,
        home_unit_id=home_unit_id, charge_qualified=True,
    )


def charge_headers(nurse):
    return make_charge_nurse_headers(nurse["id"])


def staff_headers(nurse):
    return make_staff_nurse_headers(nurse["id"])


# ---------------------------------------------------------------------------
# Tier 2 — census, shift stand-up
# ---------------------------------------------------------------------------

def submit_snapshot(unit_id, shift_date=MONDAY, shift_code="DAY",
                    census=(4, 0, 0, 0), as_headers=None):
    payload = create_snapshot_payload(
        unit_id=unit_id, shift_date=shift_date, shift_code=shift_code,
        census_low=census[0], census_moderate=census[1],
        census_high=census[2], census_critical=census[3],
    )
    return _ok("submit_snapshot",
               api_client.create_acuity_snapshot(
                   payload, as_headers or TEST_USERS["charge_nurse_headers"]))


def create_shift(unit_id, shift_date=MONDAY, shift_code="DAY"):
    payload = create_shift_payload(unit_id=unit_id, shift_date=shift_date,
                                   shift_code=shift_code)
    return _ok("create_shift", api_client.create_shift(payload, ADMIN))


def setup_unit_with_shift(name="4 West ICU", unit_type="ICU",
                          census=(4, 0, 0, 0), shift_date=MONDAY,
                          shift_code="DAY", budget=500000, auto_mult=None,
                          ratios=None):
    """Unit + full matrix + snapshot + shift + a real charge nurse.

    Returns dict(unit, shift, charge_nurse, charge_headers).
    """
    unit = create_unit(name=name, unit_type=unit_type,
                       incentive_budget_cents=budget,
                       auto_incentive_multiplier=auto_mult)
    create_full_matrix(unit_type, ratios)
    cn = create_charge_nurse(unit["id"], full_name=f"{name} Charge")
    ch = charge_headers(cn)
    snapshot = submit_snapshot(unit["id"], shift_date, shift_code, census,
                               as_headers=ch)
    shift = create_shift(unit["id"], shift_date, shift_code)
    return {"unit": unit, "snapshot": snapshot, "shift": shift,
            "charge_nurse": cn, "charge_headers": ch}


# ---------------------------------------------------------------------------
# Tier 3 — assignment lifecycle shortcuts
# ---------------------------------------------------------------------------

def propose_assignment(shift_id, nurse_id, as_headers, is_charge=False):
    """Charge nurse proposes a direct assignment, refreshing the OCC token.

    GETs the shift for its current version, then posts the create with that
    expected_shift_version. Returns the PROPOSED assignment.
    """
    shift = _ok("get_shift(version)",
                api_client.get_shift(shift_id, ADMIN))
    payload = {"nurse_id": nurse_id,
               "expected_shift_version": shift["version"]}
    if is_charge:
        payload["is_charge"] = True
    return _ok("propose_assignment",
               api_client.create_assignment(shift_id, payload, as_headers))


def accept_assignment(assignment_id, nurse_id):
    """The assignment-owning nurse accepts (ownership-gated headers)."""
    return _ok("accept_assignment",
               api_client.accept_assignment(
                   assignment_id, make_staff_nurse_headers(nurse_id)))


def decline_assignment(assignment_id, nurse_id):
    return _ok("decline_assignment",
               api_client.decline_assignment(
                   assignment_id, make_staff_nurse_headers(nurse_id)))


def confirm_assignment(assignment_id, as_headers):
    return _ok("confirm_assignment",
               api_client.confirm_assignment(assignment_id, as_headers))


def cancel_assignment(assignment_id, as_headers):
    return _ok("cancel_assignment",
               api_client.cancel_assignment(assignment_id, as_headers))


def complete_assignment(assignment_id, actual_hours_worked, missed_breaks,
                        as_headers):
    return _ok("complete_assignment",
               api_client.complete_assignment(
                   assignment_id,
                   {"actual_hours_worked": actual_hours_worked,
                    "missed_breaks": missed_breaks},
                   as_headers))


def get_shift(shift_id):
    return _ok("get_shift", api_client.get_shift(shift_id, ADMIN))


def get_unit(unit_id):
    return _ok("get_unit", api_client.get_unit(unit_id, ADMIN))


def get_week_ledger(nurse_id, week_start=MONDAY):
    return _ok("get_week_ledger",
               api_client.get_week_ledger(
                   nurse_id, ADMIN, params={"week_start": week_start}))


def walk_to_accepted(shift_id, nurse, charge_hdrs, is_charge=False):
    """propose -> accept. Returns the ACCEPTED assignment."""
    asg = propose_assignment(shift_id, nurse["id"], charge_hdrs,
                             is_charge=is_charge)
    return accept_assignment(asg["id"], nurse["id"])


def walk_to_confirmed(shift_id, nurse, charge_hdrs, is_charge=False):
    """propose -> accept -> confirm. Returns the CONFIRMED assignment."""
    asg = walk_to_accepted(shift_id, nurse, charge_hdrs, is_charge=is_charge)
    return confirm_assignment(asg["id"], charge_hdrs)


def walk_to_completed(shift_id, nurse, charge_hdrs, actual_hours_worked=12.0,
                      missed_breaks=0, is_charge=False):
    """propose -> accept -> confirm -> complete. Returns COMPLETED assignment."""
    asg = walk_to_confirmed(shift_id, nurse, charge_hdrs, is_charge=is_charge)
    return complete_assignment(asg["id"], actual_hours_worked, missed_breaks,
                               charge_hdrs)


# ---------------------------------------------------------------------------
# Tier 3b — staffed-shift composites
# ---------------------------------------------------------------------------

def setup_staffed_shift(num_accepted=0, num_confirmed=0, charge_first=True,
                        name="Staffed ICU", census=(4, 0, 0, 0),
                        shift_date=MONDAY, shift_code="DAY", budget=500000,
                        auto_mult=None, rate=5000):
    """Shift with a mix of ACCEPTED and CONFIRMED CORE-nurse assignments.

    The first assignment is is_charge when charge_first is set. Returns
    dict(scenario..., nurses, assignments).
    """
    sc = setup_unit_with_shift(name=name, census=census, shift_date=shift_date,
                               shift_code=shift_code, budget=budget,
                               auto_mult=auto_mult)
    nurses, assignments = [], []
    total = num_accepted + num_confirmed
    for i in range(total):
        nurse = create_nurse(
            full_name=f"{name} Nurse {i}", employment_type="CORE",
            competencies=["ICU"], base_hourly_rate_cents=rate,
            home_unit_id=sc["unit"]["id"],
            charge_qualified=(charge_first and i == 0),
        )
        nurses.append(nurse)
        asg = walk_to_accepted(sc["shift"]["id"], nurse, sc["charge_headers"],
                               is_charge=(charge_first and i == 0))
        if i >= num_accepted:
            asg = confirm_assignment(asg["id"], sc["charge_headers"])
        assignments.append(asg)
    sc.update({"nurses": nurses, "assignments": assignments})
    return sc


def setup_nurse_with_completions(date_actuals, rate=5000, name="OT ICU"):
    """One nurse completes assignments across same-week DAY shifts.

    date_actuals: list of (shift_date, actual_hours_worked) completed in
    order. Returns dict(unit, nurse, shifts, assignments, charge_headers).
    """
    sc = setup_unit_with_shift(name=name, census=(4, 0, 0, 0))
    nurse = create_nurse(full_name=f"{name} Nurse", employment_type="CORE",
                         competencies=["ICU"], base_hourly_rate_cents=rate,
                         home_unit_id=sc["unit"]["id"])
    # setup_unit_with_shift already created a shift for MONDAY on this unit;
    # PRD enforces one shift per unit/date/code (ERR_SHIFT_ALREADY_EXISTS),
    # so reuse that shift instead of creating a duplicate.
    shifts = {sc["shift"]["shift_date"]: sc["shift"]}
    assignments = []
    for shift_date, actual in date_actuals:
        if shift_date not in shifts:
            submit_snapshot(sc["unit"]["id"], shift_date, "DAY", (4, 0, 0, 0),
                            as_headers=sc["charge_headers"])
            shifts[shift_date] = create_shift(sc["unit"]["id"], shift_date,
                                              "DAY")
        asg = walk_to_completed(shifts[shift_date]["id"], nurse,
                                sc["charge_headers"],
                                actual_hours_worked=actual)
        assignments.append(asg)
    sc.update({"nurse": nurse, "shifts": shifts, "assignments": assignments})
    return sc


# ---------------------------------------------------------------------------
# Tier 4 — float pool / incentive / sitter / reporting composites
# ---------------------------------------------------------------------------

def create_float_nurse(full_name="Float Nurse", competencies=None, rate=6000):
    return create_nurse(full_name=full_name, employment_type="FLOAT_POOL",
                        competencies=competencies or ["ICU"],
                        base_hourly_rate_cents=rate, home_unit_id=None)


def create_float_request(shift_id):
    return _ok("create_float_request",
               api_client.create_float_request({"shift_id": shift_id},
                                               FLOAT_COORD))


def create_offer(shift_id, premium_multiplier=1.5, flat_bonus_cents=0):
    payload = create_offer_payload(shift_id=shift_id,
                                   premium_multiplier=premium_multiplier,
                                   flat_bonus_cents=flat_bonus_cents)
    return _ok("create_offer", api_client.create_incentive_offer(payload,
                                                                 ADMIN))


def create_sitter(unit_id, as_headers, patient_ref="P-0001",
                  start_at="2026-08-10T09:00:00Z",
                  end_at="2026-08-10T13:00:00Z"):
    payload = {"unit_id": unit_id, "patient_ref": patient_ref,
               "start_at": start_at, "end_at": end_at}
    return _ok("create_sitter",
               api_client.create_sitter_request(payload, as_headers))


def create_report(report_date):
    return _ok("create_report",
               api_client.create_compliance_report(
                   create_report_payload(report_date=report_date), ADMIN))


def setup_claimed_offer(name="Claim ICU", rate=5000, premium_multiplier=1.5,
                        flat_bonus_cents=2000, census=(2, 3, 2, 1)):
    """CRITICAL shift + OFFERED offer + nurse who has claimed it.

    Returns dict(scenario..., offer, nurse, assignment) with the claimed
    assignment in ACCEPTED status.
    """
    sc = setup_unit_with_shift(name=name, census=census)
    offer = create_offer(sc["shift"]["id"],
                         premium_multiplier=premium_multiplier,
                         flat_bonus_cents=flat_bonus_cents)
    nurse = create_nurse(full_name=f"{name} Claimer", employment_type="CORE",
                         competencies=["ICU"], base_hourly_rate_cents=rate,
                         home_unit_id=sc["unit"]["id"])
    claimed = _ok("claim_offer",
                  api_client.claim_incentive_offer(offer["id"],
                                                   staff_headers(nurse)))
    assignment = _ok("get_claimed_assignment",
                     api_client.get_assignment(claimed["claimed_assignment_id"],
                                               ADMIN))
    sc.update({"offer": claimed, "nurse": nurse, "assignment": assignment})
    return sc


def setup_locked_day(date=MONDAY, name="Lock ICU", census=(4, 0, 0, 0),
                     nurses=0, charge_first=True):
    """Shift with `nurses` ACCEPTED assignments, then LOCKED.

    Returns the staffed scenario dict with the locked shift under 'shift'.
    """
    sc = setup_staffed_shift(num_accepted=nurses, charge_first=charge_first,
                             name=name, census=census, shift_date=date)
    locked = _ok("lock_shift",
                 api_client.lock_shift(sc["shift"]["id"],
                                       sc["charge_headers"]))
    sc["shift"] = locked
    return sc
