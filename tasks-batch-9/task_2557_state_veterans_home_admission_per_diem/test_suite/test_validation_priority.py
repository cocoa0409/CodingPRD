"""When one request breaks two rules, the reported error is pinned by rung order.

Each scenario below violates two independent rules at once, and then repairs the
higher-ranked one without touching the lower-ranked one, so the second attempt
surfaces the rule that was being masked. That pairing is what proves an ordering
rather than a coincidence.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAIM_MONTH_NOT_CLOSED,
    ERR_HOME_NOT_RECOGNIZED,
    ERR_NO_AVAILABLE_BED,
    ERR_RESIDENT_STATE_INVALID,
)


def _hospitalized_resident_and_a_full_target_unit(api):
    """A hospitalised resident in unit A, and a unit B whose only bed is out of service.

    Unit B is certified and its posture permits transfers in, and the resident's
    active plan matches unit B's care level, so nothing but the occupancy state and
    the missing bed can reject the move.
    """
    scenario = fx.admitted_resident_with_care_plan(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    target = fx.add_unit(
        api,
        scenario,
        care_level="NURSING",
        licensed_bed_count=1,
        out_of_service_bed_count=1,
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-05", clock="2026-08-05T00:00:00Z")
    return scenario, target


def test_target_unit_with_its_only_bed_out_of_service_has_no_free_bed(api):
    """Taking the single bed out of service leaves the unit with nothing to offer.

    Per the PRD: "`out_of_service_bed_count`, the number of beds physically
    unavailable for renovation or infection control, is optional, defaults to 0,
    must not be negative and must not exceed `licensed_bed_count`." With one
    licensed bed out of service the unit has no free bed and is restricted, which
    still permits a transfer in.

    Design: Difficulty/priority_pair_validation_conflict/resident_state_beats_no_available_bed_on_transfer
    """
    _scenario, target = _hospitalized_resident_and_a_full_target_unit(api)

    unit = fx.read_unit(api, target["id"])
    assert unit["available_bed_count"] == 0
    assert unit["operational_posture"] == "RESTRICTED"


def test_resident_state_is_reported_before_the_capacity_rule_on_transfer(api):
    """A hospitalised resident transferring into a full unit hears about their own state.

    Per the PRD: "8. **State preconditions** on the record being moved — the
    applicant, assessment, resident, care plan, income record, claim, trust-fund
    posting or home recognition posture, each with its own rejection code as §3
    describes." Capacity is rung fifteen, so it never speaks first.

    Design: Difficulty/priority_pair_validation_conflict/resident_state_beats_no_available_bed_on_transfer
    """
    scenario, target = _hospitalized_resident_and_a_full_target_unit(api)

    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-05"),
        ERR_RESIDENT_STATE_INVALID,
        409,
    )

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["care_unit_id"] == scenario.unit_id


def test_capacity_rule_surfaces_once_the_resident_state_is_repaired(api):
    """Readmitting the resident leaves only the capacity violation standing.

    Per the PRD: "15. **Capacity rules** — `ERR_NO_AVAILABLE_BED` and
    `ERR_BED_HOLD_EXHAUSTED`, then the claim-census rule
    `ERR_CLAIM_CENSUS_EMPTY`." The identical request now reports the rule the
    state check had been masking, and the resident has not moved.

    Design: Difficulty/priority_pair_validation_conflict/resident_state_beats_no_available_bed_on_transfer
    """
    scenario, target = _hospitalized_resident_and_a_full_target_unit(api)
    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-05"),
        ERR_RESIDENT_STATE_INVALID,
        409,
    )

    fx.readmit(api, scenario.resident_id, "2026-08-06", clock="2026-08-06T00:00:00Z")

    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-06"),
        ERR_NO_AVAILABLE_BED,
        409,
    )

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["care_unit_id"] == scenario.unit_id
    assert resident["occupancy_status"] == "ADMITTED"
    assert fx.read_unit(api, target["id"])["occupied_bed_count"] == 0


def _suspended_home_with_a_current_month_draft(api):
    """A draft bill for the current month at a home whose recognition is suspended.

    The suspension is recorded before the claim exists, because suspending a home
    voids the drafts it already holds.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=2)
    suspended = fx.set_recognition(api, home["id"], "SUSPEND", "2026-09-01", "state program review")
    claim = validate_success(
        fx.open_claim(api, home["id"], unit["id"], "2026-09", "AUDITED_BASIS"), 201
    )
    return home, unit, claim, suspended


def test_suspended_home_is_reported_before_the_open_month_on_submission(api):
    """A suspended home blocks submission before the month's closure is examined.

    Per the PRD: "10. **Recognition and certification gates** —
    `ERR_HOME_NOT_RECOGNIZED` and `ERR_UNIT_NOT_CERTIFIED`." The temporal rules
    that would object to billing the current month sit four rungs lower.

    Design: Difficulty/priority_pair_validation_conflict/home_recognition_beats_claim_month_not_closed_on_submit
    """
    _home, _unit, claim, suspended = _suspended_home_with_a_current_month_draft(api)
    assert suspended["recognition_status"] == "SUSPENDED"

    validate_error(fx.submit_claim(api, claim["id"]), ERR_HOME_NOT_RECOGNIZED, 409)


def test_open_month_surfaces_once_recognition_is_restored(api):
    """Restoring recognition without moving the clock exposes the not-yet-closed month.

    Per the PRD: "The `claim_month` must be strictly earlier than the month of the
    current logical clock, because the census month must be closed, or
    `ERR_CLAIM_MONTH_NOT_CLOSED` (HTTP 409) — a claim for the current month is
    never submittable however complete it looks." The claim is left untouched by
    both refusals.

    Design: Difficulty/priority_pair_validation_conflict/home_recognition_beats_claim_month_not_closed_on_submit
    """
    home, _unit, claim, _suspended = _suspended_home_with_a_current_month_draft(api)
    validate_error(fx.submit_claim(api, claim["id"]), ERR_HOME_NOT_RECOGNIZED, 409)

    restored = fx.set_recognition(api, home["id"], "RESTORE", "2026-09-01", "review closed")
    assert restored["recognition_status"] == "RECOGNIZED"
    assert restored["recognition_suspended_reason"] is None

    validate_error(fx.submit_claim(api, claim["id"]), ERR_CLAIM_MONTH_NOT_CLOSED, 409)

    refreshed = fx.read_claim(api, claim["id"])
    assert refreshed["status"] == "DRAFT"
    assert refreshed["submitted_at"] is None
