"""Composite setup helpers.

Multi-step preconditions shared by many tests live here. Every helper builds
its state from scratch against a freshly restarted server using only
PRD-declared endpoints, and uses the lenient get_success_data() validator so
setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories
from . import constants as C
from .test_users import (
    make_committee_admin_headers,
    make_agency_reviewer_headers,
    make_safety_inspector_headers,
    make_entrant_headers,
    make_judge_headers,
    make_marshal_headers,
)

COMMITTEE = make_committee_admin_headers()
AGENCY = make_agency_reviewer_headers()


def _ok(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {step}: {resp.text}"
    return data


def set_clock(to_iso8601: str):
    _ok(api_client.set_clock(to_iso8601, COMMITTEE), "set_clock")


# ---------------------------------------------------------------------------
# Tier 1/2: parade scaffold, permit pipeline, operational parade
# ---------------------------------------------------------------------------

def create_parade(**overrides):
    """Create a parade edition. Returns the parade dict (DRAFT/RESTRICTED)."""
    resp = api_client.create_parade(factories.create_parade_payload(**overrides), COMMITTEE)
    return _ok(resp, "create_parade")


def add_route_segment(parade_id: str, **overrides):
    resp = api_client.create_route_segment(
        parade_id, factories.create_route_segment_payload(**overrides), COMMITTEE
    )
    return _ok(resp, "create_route_segment")


def add_staging_area(parade_id: str, **overrides):
    resp = api_client.create_staging_area(
        parade_id, factories.create_staging_area_payload(**overrides), COMMITTEE
    )
    return _ok(resp, "create_staging_area")


def create_permit(parade_id: str):
    resp = api_client.create_permit(parade_id, COMMITTEE)
    return _ok(resp, "create_permit")


def request_endorsement(permit_id: str, agency_type: str, expected_permit_version: int):
    resp = api_client.create_endorsement(
        permit_id,
        factories.create_endorsement_payload(agency_type, expected_permit_version),
        COMMITTEE,
    )
    return _ok(resp, f"create_endorsement({agency_type})")


def request_all_endorsements(permit):
    """Create the four agency endorsements, OCC-chained via the permit
    version read-back recorded on each new endorsement. Returns the list."""
    endorsements = []
    version = permit["version"]
    for agency_type in C.AGENCY_TYPES:
        endorsement = request_endorsement(permit["id"], agency_type, version)
        version = endorsement["permit_version"]
        endorsements.append(endorsement)
    return endorsements


def approve_dispersal_plan_for_parade(parade_id: str, **overrides):
    plan = _ok(
        api_client.create_dispersal_plan(
            parade_id, factories.create_dispersal_plan_payload(**overrides), COMMITTEE
        ),
        "create_dispersal_plan",
    )
    _ok(api_client.submit_dispersal_plan(plan["id"], COMMITTEE), "submit_dispersal_plan")
    plan = _ok(api_client.approve_dispersal_plan(plan["id"], AGENCY), "approve_dispersal_plan")
    return plan


def setup_permit_pending_parade(name="Permit Pending Parade", **parade_overrides):
    """Parade with segment + staging, permit created with four PENDING
    endorsements, and the parade moved DRAFT -> PERMIT_PENDING.

    Returns dict(parade, permit, segment, staging, endorsements).
    """
    parade = create_parade(name=name, **parade_overrides)
    segment = add_route_segment(parade["id"])
    staging = add_staging_area(parade["id"])
    permit = create_permit(parade["id"])
    endorsements = request_all_endorsements(permit)
    parade = _ok(api_client.submit_parade_permit(parade["id"], COMMITTEE), "submit_parade_permit")
    permit = _ok(api_client.get_permit(permit["id"], COMMITTEE), "get_permit")
    return {
        "parade": parade,
        "permit": permit,
        "segment": segment,
        "staging": staging,
        "endorsements": endorsements,
    }


def setup_operational_parade(name="Operational Parade", staging_overrides=None, **parade_overrides):
    """Full pipeline: dispersal APPROVED + permit GRANTED, so the parade is
    PERMIT_GRANTED with posture OPERATIONAL.

    Returns dict(parade, permit, segment, staging, dispersal_plan, endorsements).
    """
    parade = create_parade(name=name, **parade_overrides)
    segment = add_route_segment(parade["id"])
    staging = add_staging_area(parade["id"], **(staging_overrides or {}))
    dispersal_plan = approve_dispersal_plan_for_parade(parade["id"])
    permit = create_permit(parade["id"])
    endorsements = request_all_endorsements(permit)
    _ok(api_client.submit_parade_permit(parade["id"], COMMITTEE), "submit_parade_permit")
    _ok(api_client.submit_permit(permit["id"], COMMITTEE), "submit_permit")
    for endorsement in endorsements:
        _ok(api_client.endorse_endorsement(endorsement["id"], AGENCY), "endorse")
    permit = _ok(api_client.grant_permit(permit["id"], AGENCY), "grant_permit")
    parade = _ok(api_client.get_parade(parade["id"], COMMITTEE), "get_parade")
    return {
        "parade": parade,
        "permit": permit,
        "segment": segment,
        "staging": staging,
        "dispersal_plan": dispersal_plan,
        "endorsements": endorsements,
    }


# ---------------------------------------------------------------------------
# Tier 2/3: entries, floats, lineup
# ---------------------------------------------------------------------------

def create_entry(parade_id: str, entrant_id="entrant_1", **overrides):
    resp = api_client.create_entry(
        parade_id, factories.create_entry_payload(**overrides), make_entrant_headers(entrant_id)
    )
    return _ok(resp, "create_entry")


def create_approved_entry(parade_id: str, entrant_id="entrant_1", category="BAND",
                          assigned_category=None, **overrides):
    """Create an entry and walk it SUBMITTED -> UNDER_REVIEW -> APPROVED."""
    entry = create_entry(parade_id, entrant_id, requested_category=category, **overrides)
    _ok(api_client.start_review(entry["id"], COMMITTEE), "start_review")
    entry = _ok(
        api_client.approve_entry(
            entry["id"], {"assigned_category": assigned_category or category}, COMMITTEE
        ),
        "approve_entry",
    )
    return entry


def create_certified_float_entry(parade_id: str, entrant_id="entrant_1", inspector_id="insp_1",
                                 category="FLOAT", pass_score=85, pay_fee=True, **overrides):
    """APPROVED FLOAT/VEHICLE entry + float certified by a passed inspection.

    Returns (entry, float_obj).
    """
    entry = create_approved_entry(parade_id, entrant_id, category=category, **overrides)
    float_obj = _ok(
        api_client.create_float(
            entry["id"], factories.create_float_payload(), make_entrant_headers(entrant_id)
        ),
        "create_float",
    )
    inspection = _ok(
        api_client.schedule_inspection(
            float_obj["id"], factories.schedule_inspection_payload(),
            make_safety_inspector_headers(inspector_id),
        ),
        "schedule_inspection",
    )
    _ok(
        api_client.pass_inspection(
            inspection["id"], {"checklist_score": pass_score},
            make_safety_inspector_headers(inspector_id),
        ),
        "pass_inspection",
    )
    if pay_fee:
        _ok(api_client.pay_fee(entry["id"], make_entrant_headers(entrant_id)), "pay_fee")
    entry = _ok(api_client.get_entry(entry["id"], COMMITTEE), "get_entry")
    return entry, float_obj


def create_tentative_assignment(parade_id: str, entry_id: str, staging_area_id: str,
                                position_number=1, arrive_at="2026-07-04T07:30:00Z",
                                depart_at="2026-07-04T08:00:00Z"):
    resp = api_client.create_lineup_assignment(
        parade_id,
        factories.create_lineup_assignment_payload(
            entry_id, staging_area_id,
            position_number=position_number, arrive_at=arrive_at, depart_at=depart_at,
        ),
        COMMITTEE,
    )
    return _ok(resp, "create_lineup_assignment")


def confirm_assignment(assignment_id: str):
    return _ok(api_client.confirm_assignment(assignment_id, COMMITTEE), "confirm_assignment")


def create_confirmed_assignment(parade_id: str, entry_id: str, staging_area_id: str, **kwargs):
    assignment = create_tentative_assignment(parade_id, entry_id, staging_area_id, **kwargs)
    return confirm_assignment(assignment["id"])


def create_approved_intro_item(parade_id: str, entry_id: str, sequence_index=1,
                               duration_minutes=1.0):
    item = _ok(
        api_client.create_script_item(
            parade_id,
            factories.create_script_item_payload(
                item_type="ENTRY_INTRO", sequence_index=sequence_index,
                duration_minutes=duration_minutes, entry_id=entry_id,
            ),
            COMMITTEE,
        ),
        "create ENTRY_INTRO script item",
    )
    return _ok(api_client.approve_script_item(item["id"], COMMITTEE), "approve script item")


# ---------------------------------------------------------------------------
# Tier 5: locked / published parades
# ---------------------------------------------------------------------------

def setup_locked_parade(name="Locked Parade", **kwargs):
    """Operational parade + one APPROVED BAND entry + one TENTATIVE assignment,
    then locked. Returns dict(ctx..., entry, assignment, lock_version).
    """
    ctx = setup_operational_parade(name=name, **kwargs)
    entry = create_approved_entry(ctx["parade"]["id"], "entrant_1", category="BAND")
    assignment = create_tentative_assignment(
        ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
    )
    parade = _ok(api_client.lock_parade(ctx["parade"]["id"], COMMITTEE), "lock_parade")
    ctx.update({"parade": parade, "entry": entry, "assignment": assignment,
                "lock_version": parade["version"]})
    return ctx


def setup_published_parade(name="Published Parade", confirm=False, **kwargs):
    """Locked parade published via OCC. Returns ctx with publish_version."""
    ctx = setup_locked_parade(name=name, **kwargs)
    if confirm:
        _ok(api_client.pay_fee(ctx["entry"]["id"], make_entrant_headers("entrant_1")), "pay_fee")
        confirm_assignment(ctx["assignment"]["id"])
    parade = _ok(
        api_client.publish_lineup(
            ctx["parade"]["id"], {"expected_parade_version": ctx["lock_version"]}, COMMITTEE
        ),
        "publish_lineup",
    )
    ctx.update({"parade": parade, "publish_version": parade["version"]})
    return ctx


# ---------------------------------------------------------------------------
# Sponsors and script
# ---------------------------------------------------------------------------

def create_active_sponsor(parade_id: str, tier="GOLD", **overrides):
    sponsor = _ok(
        api_client.create_sponsor(
            parade_id, factories.create_sponsor_payload(tier=tier, **overrides), COMMITTEE
        ),
        "create_sponsor",
    )
    return _ok(api_client.activate_sponsor(sponsor["id"], COMMITTEE), "activate_sponsor")


def create_approved_sponsor_read(parade_id: str, sponsor_id: str, duration_minutes: float,
                                 sequence_index: int):
    item = _ok(
        api_client.create_script_item(
            parade_id,
            factories.create_script_item_payload(
                item_type="SPONSOR_READ", sequence_index=sequence_index,
                duration_minutes=duration_minutes, sponsor_id=sponsor_id,
            ),
            COMMITTEE,
        ),
        "create SPONSOR_READ script item",
    )
    return _ok(api_client.approve_script_item(item["id"], COMMITTEE), "approve script item")


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------

def create_submitted_sheet(entry_id: str, judge_id: str, total: int):
    sheet = _ok(
        api_client.create_score_sheet(
            entry_id, factories.create_score_sheet_payload(total=total),
            make_judge_headers(judge_id),
        ),
        "create_score_sheet",
    )
    return _ok(
        api_client.submit_score_sheet(sheet["id"], make_judge_headers(judge_id)),
        "submit_score_sheet",
    )


def create_finalized_sheet(entry_id: str, judge_id: str, total: int):
    sheet = create_submitted_sheet(entry_id, judge_id, total)
    return _ok(api_client.finalize_score_sheet(sheet["id"], COMMITTEE), "finalize_score_sheet")
