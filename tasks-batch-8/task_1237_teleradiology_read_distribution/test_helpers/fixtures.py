"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so no state is
ever carried over). Setup calls use the lenient get_success_data() validator
so failures surface as clear setup errors.

Common idioms:
- The logical clock starts at exactly 2026-05-01T00:00:00Z. Most read-flow
  fixtures advance it to 2026-05-10T10:00:00Z so that shifts spanning
  2026-05-09..2026-05-12 are swept ACTIVE and grants valid
  2026-01-01..2026-12-31 are in-window.
- Ownership-gated calls always use make_radiologist_headers(rad_id) /
  make_hospital_user_headers(hosp_id), never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_billing_period_payload,
    create_credential_grant_payload,
    create_hospital_payload,
    create_report_payload,
    create_radiologist_payload,
    create_routing_policy_payload,
    create_shift_payload,
    create_study_payload,
    seed_finalized_studies_payload,
)
from .test_users import (
    TEST_USERS,
    make_hospital_user_headers,
    make_radiologist_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]
QA = TEST_USERS["qa_headers"]

# Canonical logical-clock instant used by read-flow fixtures: shifts spanning
# 2026-05-09..2026-05-12 are ACTIVE at this time.
WORK_CLOCK = "2026-05-10T10:00:00Z"
SHIFT_WINDOW = ("2026-05-09T00:00:00Z", "2026-05-12T00:00:00Z")
GRANT_WINDOW = ("2026-01-01", "2026-12-31")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def create_active_hospital(name="Test Hospital", state_code="CA", **overrides):
    """Create a hospital and activate it. Returns the activated hospital dict."""
    hosp = get_success_data(api_client.create_hospital(
        create_hospital_payload(name=name, state_code=state_code, **overrides), ADMIN))
    return get_success_data(api_client.activate_hospital(hosp["id"], ADMIN))


def create_radiologist(**overrides):
    """Create a radiologist (status ACTIVE by default). Returns radiologist dict."""
    return get_success_data(api_client.create_radiologist(
        create_radiologist_payload(**overrides), ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_granted_credential(radiologist_id, hospital_id, **overrides):
    """Create a credential grant and move it PENDING -> GRANTED."""
    grant = get_success_data(api_client.create_credential_grant(
        create_credential_grant_payload(radiologist_id, hospital_id, **overrides), ADMIN))
    return get_success_data(api_client.grant_credential(grant["id"], ADMIN))


def create_active_shift(radiologist_id, modalities=("CT",),
                        starts_at=SHIFT_WINDOW[0], ends_at=SHIFT_WINDOW[1]):
    """Create a shift whose window straddles WORK_CLOCK. Caller must advance the
    logical clock into the window for the sweep to flip it ACTIVE."""
    return get_success_data(api_client.create_shift(
        create_shift_payload(radiologist_id, starts_at=starts_at, ends_at=ends_at,
                             modalities=list(modalities)), ADMIN))


def create_routing_policy(hospital_id, modality="CT", body_part_group="NEURO",
                          priority="ROUTINE", required_subspecialty="NEURORAD",
                          prelim_required=False):
    """Create a routing policy with a fresh OCC read of the hospital version."""
    hosp = get_success_data(api_client.get_hospital(hospital_id, ADMIN))
    return get_success_data(api_client.create_routing_policy(
        create_routing_policy_payload(
            hospital_id, hosp["version"], modality=modality,
            body_part_group=body_part_group, priority=priority,
            required_subspecialty=required_subspecialty,
            prelim_required=prelim_required), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: routing-ready hospital + credentialed radiologist
# ---------------------------------------------------------------------------

def setup_routing_ready_hospital(name="Routing Hosp", state_code="CA",
                                 modality="CT", body_part_group="NEURO",
                                 priority="ROUTINE",
                                 required_subspecialty="NEURORAD",
                                 prelim_required=False,
                                 clock=WORK_CLOCK, **hospital_overrides):
    """ACTIVE hospital + one ACTIVE routing policy + logical clock advanced.
    Returns hospital dict."""
    hosp = create_active_hospital(name=name, state_code=state_code, **hospital_overrides)
    create_routing_policy(hosp["id"], modality=modality,
                          body_part_group=body_part_group, priority=priority,
                          required_subspecialty=required_subspecialty,
                          prelim_required=prelim_required)
    if clock is not None:
        set_clock(clock)
    return hosp


def setup_credentialed_radiologist(hospital_id, full_name="Rad One",
                                   subspecialties=("NEURORAD",),
                                   license_states=("CA",),
                                   shift_modalities=("CT",),
                                   shift_window=SHIFT_WINDOW,
                                   grant_window=GRANT_WINDOW,
                                   **rad_overrides):
    """Radiologist + GRANTED credential + shift for the given hospital.
    Returns (radiologist, grant, shift)."""
    rad = create_radiologist(full_name=full_name,
                             subspecialties=list(subspecialties),
                             license_states=list(license_states), **rad_overrides)
    grant = create_granted_credential(
        rad["id"], hospital_id,
        valid_from=grant_window[0], valid_until=grant_window[1])
    shift = create_active_shift(rad["id"], modalities=tuple(shift_modalities),
                                starts_at=shift_window[0], ends_at=shift_window[1])
    return rad, grant, shift


def setup_assignment_ready(modality="CT", body_part_group="NEURO", priority="ROUTINE",
                           prelim_required=False, clock=WORK_CLOCK,
                           hospital_name="Assign Hosp", rad_name="Rad One",
                           shift_modalities=None, rad_overrides=None,
                           hospital_overrides=None):
    """Full assignment-ready fixture: ACTIVE hospital, routing policy, one
    credentialed radiologist with an ACTIVE modality-matching shift, clock set.
    Returns dict(hospital, radiologist, policy)."""
    hospital_overrides = hospital_overrides or {}
    hosp = setup_routing_ready_hospital(
        name=hospital_name, modality=modality, body_part_group=body_part_group,
        priority=priority, prelim_required=prelim_required, clock=clock,
        **hospital_overrides)
    rad, _grant, _shift = setup_credentialed_radiologist(
        hosp["id"], full_name=rad_name,
        shift_modalities=tuple(shift_modalities or [modality]),
        **(rad_overrides or {}))
    return {"hospital": hosp, "radiologist": rad}


# ---------------------------------------------------------------------------
# Tier 3: study lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_study(hospital_id, accession_number, modality="CT",
                 body_part_group="NEURO", priority="ROUTINE", patient_ref="MRN-1",
                 **overrides):
    """Create a study as its owning hospital user. Returns study dict."""
    return get_success_data(api_client.create_study(
        create_study_payload(hospital_id, accession_number, modality=modality,
                             body_part_group=body_part_group, priority=priority,
                             patient_ref=patient_ref, **overrides),
        make_hospital_user_headers(hospital_id)))


def create_routed_study(hospital_id, accession_number, **overrides):
    """Create + route a study. Returns the QUEUED study dict."""
    study = create_study(hospital_id, accession_number, **overrides)
    return get_success_data(api_client.route_study(study["id"], DISPATCH))


def assign_study(study_id, radiologist_id=None):
    """Assign a study with a fresh OCC read. radiologist_id None => auto-select.
    Returns the Assignment dict."""
    study = get_success_data(api_client.get_study(study_id, DISPATCH))
    payload = create_assignment_payload(study_id, study["version"])
    if radiologist_id is not None:
        payload["radiologist_id"] = radiologist_id
    return get_success_data(api_client.create_assignment(payload, DISPATCH))


def accept_assignment(assignment):
    """The assignment's radiologist accepts. Returns updated Assignment."""
    return get_success_data(api_client.accept_assignment(
        assignment["id"], make_radiologist_headers(assignment["radiologist_id"])))


def sign_report(report_id, radiologist_id):
    """The report's author signs. Returns updated Report."""
    return get_success_data(api_client.sign_report(
        report_id, make_radiologist_headers(radiologist_id)))


def create_draft_report(assignment_id, radiologist_id, report_type, **overrides):
    return get_success_data(api_client.create_report(
        create_report_payload(assignment_id, report_type, **overrides),
        make_radiologist_headers(radiologist_id)))


def setup_study_in_progress(accession_number="ACC-IP", modality="CT",
                            priority="ROUTINE", prelim_required=False,
                            rad_overrides=None, hospital_overrides=None):
    """Study driven RECEIVED -> QUEUED -> ASSIGNED -> IN_PROGRESS.
    Returns dict(hospital, radiologist, study, assignment)."""
    ctx = setup_assignment_ready(modality=modality, priority=priority,
                                 prelim_required=prelim_required,
                                 rad_overrides=rad_overrides,
                                 hospital_overrides=hospital_overrides)
    study = create_routed_study(ctx["hospital"]["id"], accession_number,
                                modality=modality, priority=priority)
    asg = assign_study(study["id"], ctx["radiologist"]["id"])
    accept_assignment(asg)
    study = get_success_data(api_client.get_study(study["id"], DISPATCH))
    return {"hospital": ctx["hospital"], "radiologist": ctx["radiologist"],
            "study": study, "assignment": asg}


def setup_prelim_signed_study(accession_number="ACC-PS", modality="CT",
                              priority="STAT", prelim_critical=False):
    """prelim_required flow driven to PRELIMINARY_SIGNED.
    Returns dict(hospital, prelim_radiologist, study, assignment, prelim_report)."""
    ctx = setup_assignment_ready(modality=modality, priority=priority,
                                 prelim_required=True)
    study = create_routed_study(ctx["hospital"]["id"], accession_number,
                                modality=modality, priority=priority)
    asg = assign_study(study["id"], ctx["radiologist"]["id"])
    accept_assignment(asg)
    rep = create_draft_report(asg["id"], ctx["radiologist"]["id"], "PRELIMINARY",
                              critical_finding=prelim_critical)
    rep = sign_report(rep["id"], ctx["radiologist"]["id"])
    study = get_success_data(api_client.get_study(study["id"], DISPATCH))
    return {"hospital": ctx["hospital"], "prelim_radiologist": ctx["radiologist"],
            "study": study, "assignment": asg, "prelim_report": rep}


def setup_final_signed_study(accession_number="ACC-FS", modality="CT",
                             priority="STAT", discrepancy_grade=0,
                             final_critical=False, prelim_required=True):
    """Full prelim -> final flow with two distinct radiologists, driven to
    FINAL_SIGNED. Returns dict with both radiologists, both reports, study,
    and both assignments."""
    ctx = setup_assignment_ready(modality=modality, priority=priority,
                                 prelim_required=prelim_required)
    hosp = ctx["hospital"]
    rad_pre = ctx["radiologist"]
    rad_fin, _g2, _s2 = setup_credentialed_radiologist(
        hosp["id"], full_name="Final Reader",
        shift_modalities=[modality])
    study = create_routed_study(hosp["id"], accession_number,
                                modality=modality, priority=priority)
    # Preliminary read by rad_pre.
    asg1 = assign_study(study["id"], rad_pre["id"])
    accept_assignment(asg1)
    rep_pre = create_draft_report(asg1["id"], rad_pre["id"], "PRELIMINARY")
    rep_pre = sign_report(rep_pre["id"], rad_pre["id"])
    # Final read by rad_fin.
    asg2 = assign_study(study["id"], rad_fin["id"])
    accept_assignment(asg2)
    rep_fin = create_draft_report(asg2["id"], rad_fin["id"], "FINAL",
                                  discrepancy_grade=discrepancy_grade,
                                  critical_finding=final_critical)
    rep_fin = sign_report(rep_fin["id"], rad_fin["id"])
    study = get_success_data(api_client.get_study(study["id"], DISPATCH))
    return {"hospital": hosp, "prelim_radiologist": rad_pre,
            "final_radiologist": rad_fin, "study": study,
            "prelim_assignment": asg1, "final_assignment": asg2,
            "prelim_report": rep_pre, "final_report": rep_fin}


# ---------------------------------------------------------------------------
# Tier 4: billing helpers
# ---------------------------------------------------------------------------

def setup_billing_period(hospital_id, period_start="2026-05-01",
                         period_end="2026-05-31", close=True):
    """Create a billing period; close it by default. Returns period dict."""
    per = get_success_data(api_client.create_billing_period(
        create_billing_period_payload(hospital_id, period_start=period_start,
                                      period_end=period_end), ADMIN))
    if close:
        per = get_success_data(api_client.close_billing_period(per["id"], ADMIN))
    return per


def seed_studies(hospital_id, count, received_at, final_signed_at, **overrides):
    """Seed finalized studies. Returns the seed response data (created_count,
    study_ids)."""
    return get_success_data(api_client.seed_finalized_studies(
        seed_finalized_studies_payload(hospital_id, count, received_at,
                                       final_signed_at, **overrides), ADMIN))


def generate_invoice(period_id):
    """Generate an invoice with a fresh OCC read of the period version."""
    per = get_success_data(api_client.get_billing_period(period_id, ADMIN))
    return get_success_data(api_client.generate_invoice(
        period_id, {"expected_billing_period_version": per["version"]}, ADMIN))


def setup_invoiced_period(hospital_id, seed_count=1,
                          received_at="2026-05-04T10:00:00Z",
                          final_signed_at="2026-05-04T12:00:00Z",
                          period_start="2026-05-01", period_end="2026-05-31",
                          **seed_overrides):
    """Seed finalized studies + closed period + generated invoice.
    Returns dict(period, invoice, seed)."""
    seed = seed_studies(hospital_id, seed_count, received_at, final_signed_at,
                        **seed_overrides)
    per = setup_billing_period(hospital_id, period_start, period_end, close=True)
    inv = generate_invoice(per["id"])
    return {"period": per, "invoice": inv, "seed": seed}
