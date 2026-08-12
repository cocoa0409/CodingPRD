"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every test runs against a freshly restarted server (empty database), so every
precondition is built from scratch here using only PRD-declared endpoints.
Atomic helpers perform one API call each; composite fixtures chain them into
the states the test claims need (active project, dredging reach, completed
event, confirmed ticket, shutdown accumulation, accepted reach, ...).

Setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.

Segregation of duties (PRD §2.8): records are submitted/reported/filed by the
canonical operator ids (surv-1 / ops-1) and adjudicated by a *different* id
(eng-1 / site-1); helpers below already thread those ids correctly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_project_payload,
    create_permit_payload,
    create_reach_payload,
    create_plant_payload,
    create_dredge_plan_payload,
    create_survey_payload,
    create_dredge_event_payload,
    create_disposal_site_payload,
    create_placement_ticket_payload,
    create_turbidity_reading_payload,
    create_species_sighting_payload,
    create_standby_claim_payload,
    create_payment_certificate_payload,
)
from .test_users import TEST_USERS

OWNER = TEST_USERS["owner_headers"]  # eng-1
CONTRACTOR = TEST_USERS["contractor_headers"]  # ops-1
SURVEYOR = TEST_USERS["surveyor_headers"]  # surv-1
MONITOR = TEST_USERS["monitor_headers"]  # mon-1
SITE_OP = TEST_USERS["site_operator_headers"]  # site-1


# ─── Atomic helpers (one API call each) ─────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4). Returns current_utc string."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, OWNER)
    return get_success_data(res)["current_utc"]


def create_project(**overrides):
    res = api_client.create_project(create_project_payload(**overrides), OWNER)
    return get_success_data(res)


def add_permit(project_id, **overrides):
    res = api_client.create_permit(create_permit_payload(project_id, **overrides), OWNER)
    return get_success_data(res)


def add_reach(project_id, **overrides):
    res = api_client.create_reach(create_reach_payload(project_id, **overrides), OWNER)
    return get_success_data(res)


def add_plant(**overrides):
    res = api_client.create_plant(create_plant_payload(**overrides), CONTRACTOR)
    return get_success_data(res)


def add_plan(project_id, plant_id, **overrides):
    res = api_client.create_dredge_plan(
        create_dredge_plan_payload(project_id, plant_id, **overrides), CONTRACTOR
    )
    return get_success_data(res)


def submit_plan(plan_id):
    return get_success_data(api_client.submit_dredge_plan(plan_id, CONTRACTOR))


def approve_plan(project_id, plan_id):
    """Approve with the project's CURRENT version (OCC, PRD §2.7)."""
    project = get_success_data(api_client.get_project(project_id, OWNER))
    res = api_client.approve_dredge_plan(
        plan_id, {"expected_project_version": project["version"]}, OWNER
    )
    return get_success_data(res)


def activate_project(project_id):
    return get_success_data(api_client.activate_project(project_id, OWNER))


def submit_survey(reach_id, kind, measured_volume_cy, min_sounding_depth_ft,
                  supersedes_survey_id=None):
    overrides = {
        "kind": kind,
        "measured_volume_cy": measured_volume_cy,
        "min_sounding_depth_ft": min_sounding_depth_ft,
    }
    if supersedes_survey_id is not None:
        overrides["supersedes_survey_id"] = supersedes_survey_id
    res = api_client.create_survey(
        create_survey_payload(reach_id, **overrides), SURVEYOR
    )
    return get_success_data(res)


def accept_survey(reach_id, survey_id):
    """Accept with the reach's CURRENT version (OCC, PRD §2.7); the acceptor
    (eng-1) differs from the submitter (surv-1) per §2.8."""
    reach = get_success_data(api_client.get_reach(reach_id, OWNER))
    res = api_client.accept_survey(
        survey_id, {"expected_reach_version": reach["version"]}, OWNER
    )
    return get_success_data(res)


def reject_survey(survey_id):
    return get_success_data(api_client.reject_survey(survey_id, OWNER))


def begin_dredging(reach_id):
    return get_success_data(api_client.begin_dredging(reach_id, CONTRACTOR))


def open_event(reach_id, plant_id, started_utc, reduced_rate=None):
    overrides = {"started_utc": started_utc}
    if reduced_rate is not None:
        overrides["reduced_rate"] = reduced_rate
    res = api_client.create_dredge_event(
        create_dredge_event_payload(reach_id, plant_id, **overrides), CONTRACTOR
    )
    return get_success_data(res)


def complete_event(event_id):
    return get_success_data(api_client.complete_dredge_event(event_id, CONTRACTOR))


def resume_event(event_id):
    return get_success_data(api_client.resume_dredge_event(event_id, CONTRACTOR))


def get_event(event_id):
    return get_success_data(api_client.get_dredge_event(event_id, OWNER))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, OWNER))


def get_reach(reach_id):
    return get_success_data(api_client.get_reach(reach_id, OWNER))


def get_site(site_id):
    return get_success_data(api_client.get_disposal_site(site_id, OWNER))


def add_site(**overrides):
    res = api_client.create_disposal_site(create_disposal_site_payload(**overrides), OWNER)
    return get_success_data(res)


def report_ticket(event_id, site_id, placed_utc, declared_volume_cy):
    res = api_client.create_placement_ticket(
        create_placement_ticket_payload(
            event_id, site_id, placed_utc=placed_utc,
            declared_volume_cy=declared_volume_cy,
        ),
        CONTRACTOR,
    )
    return get_success_data(res)


def confirm_ticket(ticket_id, witnessed_volume_cy):
    res = api_client.confirm_placement_ticket(
        ticket_id, {"witnessed_volume_cy": witnessed_volume_cy}, SITE_OP
    )
    return get_success_data(res)


def report_sighting(project_id, species_class="FISH",
                    observed_utc="2026-05-10T06:00:00Z"):
    res = api_client.create_species_sighting(
        create_species_sighting_payload(
            project_id, species_class=species_class, observed_utc=observed_utc
        ),
        MONITOR,
    )
    return get_success_data(res)


def clear_sighting(sighting_id):
    return get_success_data(api_client.clear_species_sighting(sighting_id, MONITOR))


def record_reading(project_id, value_ntu, taken_utc):
    res = api_client.create_turbidity_reading(
        create_turbidity_reading_payload(
            project_id, value_ntu=value_ntu, taken_utc=taken_utc
        ),
        MONITOR,
    )
    return get_success_data(res)


def file_claim(project_id, plant_id, period_start_utc, period_end_utc,
               claimed_hours, reason):
    res = api_client.create_standby_claim(
        create_standby_claim_payload(
            project_id, plant_id,
            period_start_utc=period_start_utc, period_end_utc=period_end_utc,
            claimed_hours=claimed_hours, reason=reason,
        ),
        CONTRACTOR,
    )
    return get_success_data(res)


def approve_claim(claim_id):
    return get_success_data(api_client.approve_standby_claim(claim_id, OWNER))


def create_certificate(project_id, certificate_type, period_start_utc,
                       period_end_utc, reach_ids, standby_claim_ids=None):
    overrides = {
        "certificate_type": certificate_type,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
    }
    if standby_claim_ids is not None:
        overrides["standby_claim_ids"] = list(standby_claim_ids)
    res = api_client.create_payment_certificate(
        create_payment_certificate_payload(project_id, reach_ids, **overrides),
        CONTRACTOR,
    )
    return get_success_data(res)


def submit_certificate(cert_id):
    return get_success_data(api_client.submit_payment_certificate(cert_id, CONTRACTOR))


def certify_certificate(cert_id, override_note=None):
    payload = {} if override_note is None else {"override_note": override_note}
    return get_success_data(
        api_client.certify_payment_certificate(cert_id, payload, OWNER)
    )


# ─── Tier 1/2: state progression + hierarchy ────────────────────────────────

def setup_active_project(clock="2026-05-10T00:00:00Z", project_overrides=None,
                         permit_overrides=None, reach_overrides=None,
                         plant_overrides=None, plan_overrides=None):
    """Project + ISSUED permit + reach + plant + APPROVED plan, then ACTIVATED.

    Returns ctx dict with keys: project, permit, reach, plant, plan.
    """
    set_clock(clock)
    project = create_project(**(project_overrides or {}))
    permit = add_permit(project["id"], **(permit_overrides or {}))
    reach = add_reach(project["id"], **(reach_overrides or {}))
    plant = add_plant(**(plant_overrides or {}))
    plan = add_plan(project["id"], plant["id"], **(plan_overrides or {}))
    submit_plan(plan["id"])
    plan = approve_plan(project["id"], plan["id"])
    project = activate_project(project["id"])
    return {
        "project": project,
        "permit": permit,
        "reach": reach,
        "plant": plant,
        "plan": plan,
    }


def setup_dredging_reach(pre_survey_volume=40000, pre_survey_depth=18.5, **kw):
    """Active project + accepted PRE_DREDGE survey + reach in DREDGING.

    Returns ctx dict with added key: survey_pre.
    """
    ctx = setup_active_project(**kw)
    survey_pre = submit_survey(
        ctx["reach"]["id"], "PRE_DREDGE", pre_survey_volume, pre_survey_depth
    )
    accept_survey(ctx["reach"]["id"], survey_pre["id"])
    begin_dredging(ctx["reach"]["id"])
    ctx["survey_pre"] = survey_pre
    ctx["reach"] = get_reach(ctx["reach"]["id"])
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def setup_pre_surveyed_reach(activate=False, **kw):
    """Project with accepted PRE_DREDGE survey but begin-dredging NOT called.

    With activate=True the project is ACTIVATED; otherwise it stays PLANNED
    (used for the project-not-active gate). Returns ctx dict.
    """
    set_clock(kw.pop("clock", "2026-05-10T00:00:00Z"))
    project = create_project(**(kw.pop("project_overrides", None) or {}))
    permit = add_permit(project["id"], **(kw.pop("permit_overrides", None) or {}))
    reach = add_reach(project["id"], **(kw.pop("reach_overrides", None) or {}))
    plant = add_plant(**(kw.pop("plant_overrides", None) or {}))
    plan = add_plan(project["id"], plant["id"], **(kw.pop("plan_overrides", None) or {}))
    submit_plan(plan["id"])
    plan = approve_plan(project["id"], plan["id"])
    if activate:
        project = activate_project(project["id"])
    survey_pre = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
    accept_survey(reach["id"], survey_pre["id"])
    return {
        "project": get_project(project["id"]),
        "permit": permit,
        "reach": get_reach(reach["id"]),
        "plant": plant,
        "plan": plan,
        "survey_pre": survey_pre,
    }


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def setup_completed_event(ctx=None, started_utc="2026-05-10T00:00:00Z",
                          completed_at="2026-05-12T00:00:00Z", **kw):
    """Dredging reach + one event created at `started_utc`, completed after the
    clock advances to `completed_at`. Returns ctx with added key: event."""
    if ctx is None:
        ctx = setup_dredging_reach(**kw)
    event = open_event(ctx["reach"]["id"], ctx["plant"]["id"], started_utc)
    set_clock(completed_at)
    event = complete_event(event["id"])
    ctx["event"] = event
    return ctx


def setup_second_completed_event(ctx, started_utc="2026-05-12T00:00:00Z",
                                 completed_at="2026-05-13T00:00:00Z"):
    """Add a second completed event on the same reach/plant. Key: event2."""
    event2 = open_event(ctx["reach"]["id"], ctx["plant"]["id"], started_utc)
    set_clock(completed_at)
    event2 = complete_event(event2["id"])
    ctx["event2"] = event2
    return ctx


def setup_confirmed_ticket(ctx, event_key="event",
                           placed_utc="2026-05-12T12:00:00Z",
                           declared_volume_cy=1609, witnessed_volume_cy=1609,
                           site_overrides=None):
    """Disposal site + REPORTED ticket + CONFIRMED with witnessed volume.

    Returns ctx with added keys: site, ticket (post-confirm state).
    """
    site = add_site(**(site_overrides or {}))
    ticket = report_ticket(ctx[event_key]["id"], site["id"], placed_utc,
                           declared_volume_cy)
    ticket = confirm_ticket(ticket["id"], witnessed_volume_cy)
    ctx["site"] = site
    ctx["ticket"] = ticket
    return ctx


def setup_species_shutdown(ctx, event_key="event",
                           observed_utc="2026-05-10T06:00:00Z",
                           resume_at="2026-05-10T16:00:00Z",
                           species_class="FISH", resume=True):
    """Sighting at `observed_utc` auto-shuts the ACTIVE event(s) (reason
    SPECIES); clock advances to `resume_at` (past the 6h standdown), the
    sighting is cleared, and (resume=True) the named event is resumed,
    settling (resume_at - observed_utc) hours into shutdown_accumulated_hours.

    Returns ctx with added key: sighting.
    """
    set_clock(observed_utc)
    sighting = report_sighting(ctx["project"]["id"], species_class, observed_utc)
    set_clock(resume_at)
    clear_sighting(sighting["id"])
    if resume:
        ctx[event_key] = resume_event(ctx[event_key]["id"])
    ctx["sighting"] = sighting
    return ctx


def setup_equipment_shutdown(ctx, event_key="event",
                             down_at="2026-05-10T06:00:00Z",
                             up_at="2026-05-10T16:00:00Z", resume=True):
    """Plant OUT_OF_SERVICE auto-shuts its ACTIVE events (reason EQUIPMENT);
    plant back to REGISTERED at `up_at`; (resume=True) the event is resumed.
    """
    set_clock(down_at)
    api_client.patch_plant(ctx["plant"]["id"], {"status": "OUT_OF_SERVICE"}, CONTRACTOR)
    set_clock(up_at)
    api_client.patch_plant(ctx["plant"]["id"], {"status": "REGISTERED"}, CONTRACTOR)
    if resume:
        ctx[event_key] = resume_event(ctx[event_key]["id"])
    return ctx


def setup_approved_claim(ctx, period_start_utc="2026-05-10T06:00:00Z",
                         period_end_utc="2026-05-10T16:00:00Z",
                         claimed_hours=10.0, reason="WEATHER"):
    """File a standby claim and approve it (OwnerEngineer != filer)."""
    claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                       period_start_utc, period_end_utc, claimed_hours, reason)
    claim = approve_claim(claim["id"])
    ctx["claim"] = claim
    return ctx


def setup_accepted_reach(ctx, post_survey_volume=39000, post_survey_depth=25.0,
                         supersedes_survey_id=None):
    """POST_DREDGE survey accepted at a passing depth: reach -> ACCEPTED and
    removed_in_place_cy recomputed. Returns ctx with added key: survey_post."""
    survey_post = submit_survey(
        ctx["reach"]["id"], "POST_DREDGE", post_survey_volume, post_survey_depth,
        supersedes_survey_id=supersedes_survey_id,
    )
    accept_survey(ctx["reach"]["id"], survey_post["id"])
    ctx["survey_post"] = survey_post
    ctx["reach"] = get_reach(ctx["reach"]["id"])
    return ctx
