"""Composite setup helpers for the Home Health Nurse Dispatch PRD.

These encapsulate the multi-step preambles that the design recipes share:
pin clock -> create active PDGM rate config -> create clinician(s) -> create
patient -> record SOC OASIS -> open episode -> attach plan -> activate. Every
helper uses get_success_data (lenient) so setup failures surface clearly.

Clinician ownership (PRD §2.1): visit confirm/complete are ownership-gated on
the acting X-User-ID == visit.clinician_id, so those calls thread the real
clinician id through make_clinician_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clinician_payload,
    companion_shift_payload,
    oasis_payload,
    patient_payload,
    plan_payload,
    rate_config_payload,
    visit_payload,
)
from .test_users import TEST_USERS, make_clinician_headers

INTAKE = TEST_USERS["intake_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]

DEFAULT_CLOCK = "2026-02-01T08:00:00Z"


# --------------------------------------------------------------------------
# Primitive setup helpers
# --------------------------------------------------------------------------
def set_clock(now_utc, api=api_client):
    return get_success_data(api.set_clock(now_utc, BILLING))


def create_rate_config(api=api_client, **overrides):
    return get_success_data(api.create_rate_config(rate_config_payload(**overrides), BILLING))


def create_clinician(api=api_client, **overrides):
    return get_success_data(api.create_clinician(clinician_payload(**overrides), SCHEDULER))


def create_patient(api=api_client, **overrides):
    return get_success_data(api.create_patient(patient_payload(**overrides), INTAKE))


def create_oasis(patient_id, clinician_id, api=api_client, **overrides):
    return get_success_data(
        api.create_oasis(oasis_payload(patient_id, clinician_id, **overrides), INTAKE)
    )


def open_episode(patient_id, soc_oasis_id, api=api_client, **overrides):
    body = {"patient_id": patient_id, "soc_oasis_id": soc_oasis_id}
    body.update(overrides)
    return get_success_data(api.create_episode(body, INTAKE))


def add_plan(episode_id, expected_episode_version, api=api_client, **overrides):
    return get_success_data(
        api.create_plan(episode_id, plan_payload(expected_episode_version, **overrides), INTAKE)
    )


def activate(episode_id, api=api_client):
    return get_success_data(api.activate_episode(episode_id, INTAKE))


# --------------------------------------------------------------------------
# Roster: an active rate config + one RN clinician (+ optional HHA)
# --------------------------------------------------------------------------
def setup_roster(api=api_client, clock=DEFAULT_CLOCK, rate_overrides=None,
                 rn_overrides=None, with_hha=False):
    """Pin clock, create active rate config, RN clinician (and HHA if asked)."""
    set_clock(clock, api)
    rate = create_rate_config(api, **(rate_overrides or {}))
    rn = create_clinician(api, **(rn_overrides or {"full_name": "RN One", "discipline": "RN"}))
    out = {"rate": rate, "rn": rn}
    if with_hha:
        out["hha"] = create_clinician(api, full_name="HHA One", discipline="HHA")
    return out


# --------------------------------------------------------------------------
# A DRAFT episode (roster + patient + SOC OASIS + episode), no plan yet.
# Returns dict with rate, rn, patient, oasis, episode, version.
# --------------------------------------------------------------------------
def setup_draft_episode(api=api_client, clock=DEFAULT_CLOCK, rate_overrides=None,
                        rn_overrides=None, oasis_overrides=None, with_hha=False):
    roster = setup_roster(api, clock, rate_overrides, rn_overrides, with_hha)
    patient = create_patient(api)
    oasis = create_oasis(patient["id"], roster["rn"]["id"], api, **(oasis_overrides or {}))
    episode = open_episode(patient["id"], oasis["id"], api)
    out = {
        "rate": roster["rate"],
        "rn": roster["rn"],
        "patient": patient,
        "oasis": oasis,
        "episode": episode,
        "version": episode["version"],
    }
    if with_hha:
        out["hha"] = roster["hha"]
    return out


# --------------------------------------------------------------------------
# An ACTIVE episode: draft + plan + activate.
# Returns same keys as setup_draft_episode, plus 'plan' and refreshed 'episode'.
# --------------------------------------------------------------------------
def setup_active_episode(api=api_client, clock=DEFAULT_CLOCK, rate_overrides=None,
                         rn_overrides=None, oasis_overrides=None, plan_overrides=None,
                         with_hha=False):
    base = setup_draft_episode(api, clock, rate_overrides, rn_overrides,
                               oasis_overrides, with_hha)
    plan = add_plan(base["episode"]["id"], base["version"], api, **(plan_overrides or {}))
    activate(base["episode"]["id"], api)
    episode = get_success_data(api.get_episode(base["episode"]["id"], INTAKE))
    base["plan"] = plan
    base["episode"] = episode
    base["version"] = episode["version"]
    return base


# --------------------------------------------------------------------------
# Visit lifecycle helpers (clinician-owned via ownership headers).
# --------------------------------------------------------------------------
def schedule_visit(episode_id, clinician_id, api=api_client, **overrides):
    return get_success_data(
        api.create_visit(episode_id, visit_payload(clinician_id, **overrides), SCHEDULER)
    )


def confirm_visit(visit_id, clinician_id, api=api_client):
    return get_success_data(api.confirm_visit(visit_id, make_clinician_headers(clinician_id)))


def complete_visit(visit_id, clinician_id, api=api_client):
    return get_success_data(api.complete_visit(visit_id, make_clinician_headers(clinician_id)))


def schedule_confirm_complete(episode_id, clinician_id, complete_clock, api=api_client,
                              **visit_overrides):
    """Schedule a visit, confirm it, advance clock, complete it. Returns the
    completed visit. complete_clock must be at/after scheduled_end."""
    v = schedule_visit(episode_id, clinician_id, api, **visit_overrides)
    confirm_visit(v["id"], clinician_id, api)
    set_clock(complete_clock, api)
    return complete_visit(v["id"], clinician_id, api)


# --------------------------------------------------------------------------
# Companion shift helpers.
# --------------------------------------------------------------------------
def book_companion_shift(episode_id, hha_id, api=api_client, **overrides):
    return get_success_data(
        api.create_companion_shift(episode_id, companion_shift_payload(hha_id, **overrides), SCHEDULER)
    )


def deliver_companion_shift(shift_id, api=api_client):
    return get_success_data(api.deliver_companion_shift(shift_id, SCHEDULER))


# --------------------------------------------------------------------------
# Mileage helpers.
# --------------------------------------------------------------------------
def file_mileage_claim(visit_id, clinician_id, api=api_client, claimed_miles=20.0):
    return get_success_data(
        api.create_mileage_claim(visit_id, {"claimed_miles": claimed_miles},
                                 make_clinician_headers(clinician_id))
    )


# --------------------------------------------------------------------------
# A fully finalized (DISCHARGED) episode with one completed visit.
# Returns dict with episode, patient, rn, visit, and the finalize response.
# --------------------------------------------------------------------------
def setup_finalized_episode(api=api_client, clock=DEFAULT_CLOCK, rate_overrides=None,
                            plan_overrides=None, oasis_overrides=None):
    rate_overrides = rate_overrides or {
        "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
        "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
        "functional_weight_high": 1.00, "lupa_threshold": 1,
    }
    oasis_overrides = oasis_overrides or {
        "clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0,
    }
    plan_overrides = plan_overrides or {"planned_rn_visits": 1}
    base = setup_active_episode(api, clock, rate_overrides=rate_overrides,
                                oasis_overrides=oasis_overrides, plan_overrides=plan_overrides)
    ep_id = base["episode"]["id"]
    rn_id = base["rn"]["id"]
    visit = schedule_confirm_complete(ep_id, rn_id, "2026-02-03T11:00:00Z", api)
    fin = get_success_data(api.finalize_episode(ep_id, BILLING))
    base["visit"] = visit
    base["episode"] = fin
    return base
