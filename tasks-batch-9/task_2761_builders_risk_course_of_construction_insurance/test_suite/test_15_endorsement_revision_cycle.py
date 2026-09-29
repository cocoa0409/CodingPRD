"""The endorsement revision loop: REQUESTED -> RETURNED_FOR_INFO -> REQUESTED.

Every lap re-prices the additional premium from scratch, and the loop counter
terminates the cycle at three resubmissions.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.constants import add_days
from test_helpers.factories import resubmit_endorsement_payload


def _return_for_info(endorsement, note):
    return get_success_data(api_client.return_endorsement_for_info(
        endorsement["id"], {"info_request_note": note}, fx.UM))


def _resubmit(account, endorsement, days, slip_reason=None):
    revised = add_days(account.policy["adjusted_completion_date"], days)
    payload = resubmit_endorsement_payload(days, revised)
    if slip_reason is not None:
        payload["slip_reason"] = slip_reason
    return get_success_data(api_client.resubmit_endorsement(
        endorsement["id"], payload, fx.UW))


def test_every_resubmission_lap_reprices_the_slip_from_scratch():
    """A resubmission overwrites the requested days, increments
    resubmission_count and recomputes slip_factor and additional_premium_cents
    from scratch against the policy's state as of that request. On a 302-day
    term with a 9107-cent daily base the laps price 45 days at 1.15 (471287),
    30 days at 1.00 (273210), 76 days at 1.40 (968985) and 151 days - exactly
    half the original term - at 1.40 (1925220).

    Design: Difficulty/non_linear_state_machine/endorsement_return_for_info_resubmission_cycle
    """
    account = fx.in_force_account()
    endorsement = fx.file_endorsement(account, 45)

    assert endorsement["slip_factor"] == 1.15, endorsement["slip_factor"]
    assert endorsement["additional_premium_cents"] == 471287, (
        f"9107 * 45 * 1.15 is 471287, got {endorsement['additional_premium_cents']}")
    assert endorsement["resubmission_count"] == 0, endorsement

    _return_for_info(endorsement, "Attach the updated critical-path schedule")
    lap1 = _resubmit(account, endorsement, 30, slip_reason="WEATHER")
    assert lap1["resubmission_count"] == 1, lap1
    assert lap1["slip_factor"] == 1.00, lap1["slip_factor"]
    assert lap1["additional_premium_cents"] == 273210, (
        "30 / 302 falls in the first tier, so the same endorsement re-prices "
        f"downward to 273210, got {lap1['additional_premium_cents']}")

    _return_for_info(endorsement, "Weather logs still missing")
    lap2 = _resubmit(account, endorsement, 76, slip_reason="LABOR_SHORTAGE")
    assert lap2["resubmission_count"] == 2, lap2
    assert lap2["slip_factor"] == 1.40, lap2["slip_factor"]
    assert lap2["additional_premium_cents"] == 968985, lap2

    _return_for_info(endorsement, "Confirm the subcontractor remobilisation date")
    lap3 = _resubmit(account, endorsement, 151, slip_reason="PERMIT_DELAY")
    assert lap3["resubmission_count"] == 3, lap3
    assert lap3["additional_premium_cents"] == 1925220, (
        "a ratio of exactly one half is still admissible, "
        f"got {lap3['additional_premium_cents']}")


def test_the_fourth_resubmission_is_refused_and_the_policy_term_never_moved():
    """resubmission_count must be below 3, so the fourth resubmission is
    refused with ERR_RESUBMISSION_LIMIT_REACHED and the endorsement stays in
    RETURNED_FOR_INFO with its counter at 3. Nothing was ever approved, so the
    policy's cumulative_extension_days and term_end_date are untouched.

    Design: Difficulty/non_linear_state_machine/endorsement_return_for_info_resubmission_cycle
    """
    account = fx.in_force_account()
    endorsement = fx.file_endorsement(account, 45)

    for note, days in (("Attach the updated critical-path schedule", 30),
                       ("Weather logs still missing", 76),
                       ("Confirm the subcontractor remobilisation date", 151)):
        _return_for_info(endorsement, note)
        _resubmit(account, endorsement, days)

    _return_for_info(endorsement, "Final clarification")
    revised = add_days(account.policy["adjusted_completion_date"], 30)
    blocked = api_client.resubmit_endorsement(
        endorsement["id"], resubmit_endorsement_payload(30, revised), fx.UW)
    validate_error(blocked, "ERR_RESUBMISSION_LIMIT_REACHED", expected_status=409)

    stored = get_success_data(api_client.get_extension_endorsement(
        endorsement["id"], fx.UW))
    assert stored["status"] == "RETURNED_FOR_INFO", stored["status"]
    assert stored["resubmission_count"] == 3, stored["resubmission_count"]

    policy = account.refresh_policy()
    assert policy["cumulative_extension_days"] == 0, policy
    assert policy["term_end_date"] == "2027-06-30T00:00:00Z", policy
