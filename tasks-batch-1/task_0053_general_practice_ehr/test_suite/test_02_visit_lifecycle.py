"""Visit state machine: initial state, the code/reopen cycle, invalid
transitions, terminal lockdown, and the provider-deactivate panel cascade.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_provider_headers,
    TEST_USERS,
    create_provider,
    create_patient,
    create_visit,
    create_visit_in_progress,
    create_coded_visit,
    create_pcp_bound_patient,
)

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue A: non_linear_state_machine / visit_code_reopen_cycle ───

def test_reopen_returns_visit_to_in_progress(api):
    """PRD §3.4: "A coded visit can be reopened back to `IN_PROGRESS` by the provider
    so that charge lines can be added or corrected; reopening resets
    `billed_total_cents` to 0."

    Design: Difficulty/non_linear_state_machine/visit_code_reopen_cycle
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    prov_hdr = make_provider_headers(provider["id"])
    reopened = validate_success(api.reopen_visit(visit["id"], prov_hdr), 200)
    assert reopened["status"] == "IN_PROGRESS", (
        f"reopen must return CODED visit to IN_PROGRESS, got {reopened['status']}"
    )


def test_reopen_resets_billed_total_to_zero(api):
    """PRD §3.4: "A coded visit can be reopened back to `IN_PROGRESS` by the provider
    so that charge lines can be added or corrected; reopening resets
    `billed_total_cents` to 0."

    Design: Difficulty/non_linear_state_machine/visit_code_reopen_cycle
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    assert visit["billed_total_cents"] == 8000
    prov_hdr = make_provider_headers(provider["id"])
    reopened = validate_success(api.reopen_visit(visit["id"], prov_hdr), 200)
    assert reopened["billed_total_cents"] == 0, (
        f"reopen must reset billed_total_cents to 0, got {reopened['billed_total_cents']}"
    )


# ─── Queue B: state_machines / visit_initial_state_is_scheduled ───

def test_new_visit_starts_scheduled(api):
    """PRD §3.4: "A visit is created in `SCHEDULED` status, and the slot it occupies
    is the half-open interval from `scheduled_start` up to but not including
    `scheduled_end`."

    Design: Corner/state_machines/visit_initial_state_is_scheduled
    """
    provider = create_provider()
    patient = create_patient()
    visit = create_visit(patient["id"], provider["id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["billed_total_cents"] == 0
    assert visit["version"] == 1


# ─── Queue B: state_machines / visit_start_from_scheduled_invalid_state ───

def test_start_from_scheduled_is_invalid_state(api):
    """PRD §3.4: "Starting the encounter advances the visit from `CHECKED_IN` to
    `IN_PROGRESS`; it requires the visit to be `CHECKED_IN` and is restricted to the
    provider whose `id` equals the visit's `provider_id`."

    Design: Corner/state_machines/visit_start_from_scheduled_invalid_state
    """
    provider = create_provider()
    patient = create_patient()
    visit = create_visit(patient["id"], provider["id"])  # still SCHEDULED, never checked in
    prov_hdr = make_provider_headers(provider["id"])
    res = api.start_visit(visit["id"], prov_hdr)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_visit(visit["id"], FD), 200)
    assert after["status"] == "SCHEDULED"


# ─── Queue B: state_machines / visit_cancel_then_cancel_terminal_lockdown ───

def test_cancel_twice_second_is_invalid_state(api):
    """PRD §3.4: "Cancelling a scheduled visit moves it from `SCHEDULED` to
    `CANCELLED` and releases the provider's time slot."

    Design: Corner/state_machines/visit_cancel_then_cancel_terminal_lockdown
    """
    provider = create_provider()
    patient = create_patient()
    visit = create_visit(patient["id"], provider["id"])
    validate_success(api.cancel_visit(visit["id"], FD), 200)
    res = api.cancel_visit(visit["id"], FD)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Queue B: state_machines / provider_deactivate_unbinds_panel_cascade ───

def test_provider_deactivate_clears_panel(api):
    """PRD §3.1: "Deactivation has a cascade: every patient whose bound PCP is this
    provider has their `pcp_id` cleared to null and is thereby unbound, the provider's
    `panel_size` is recomputed to 0, and the provider's `version` increments by 1."

    Design: Corner/state_machines/provider_deactivate_unbinds_panel_cascade
    """
    provider, patient = create_pcp_bound_patient()
    assert provider["panel_size"] == 1
    deactivated = validate_success(api.deactivate_provider(provider["id"], FD), 200)
    assert deactivated["panel_size"] == 0, (
        f"panel_size must recompute to 0 on deactivate, got {deactivated['panel_size']}"
    )
    refreshed_patient = validate_success(api.get_patient(patient["id"], FD), 200)
    assert refreshed_patient["pcp_id"] is None, (
        f"bound patient pcp_id must be cleared to null, got {refreshed_patient['pcp_id']}"
    )
