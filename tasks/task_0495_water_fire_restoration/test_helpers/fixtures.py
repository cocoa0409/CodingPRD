"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test). These helpers build the multi-step preconditions tests need,
using only PRD-declared endpoints, and return the created resources.

Identity threading: when a job has been dispatched to a Technician, that
Technician's id is used as X-User-ID for every ownership-relevant Technician
call via make_technician_headers(tech_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_admin_headers,
    make_dispatcher_headers,
    make_estimator_headers,
    make_adjuster_headers,
)
from .factories import (
    create_claim_payload,
    create_job_payload,
    create_technician_payload,
    create_equipment_unit_payload,
    create_chamber_payload,
    create_placement_payload,
    create_reading_payload,
    create_estimate_payload,
    create_contents_payload,
)

# Canonical opaque-role headers used throughout setup.
ADJUSTER = TEST_USERS["adjuster_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic builders
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the logical clock as PlatformAdmin."""
    return get_success_data(_api.set_clock(iso, ADMIN))


def create_claim(**overrides) -> dict:
    """Open a claim as Adjuster. Returns the claim resource."""
    return get_success_data(_api.create_claim(create_claim_payload(**overrides), ADJUSTER))


def create_technician(**overrides) -> dict:
    """Register a technician as PlatformAdmin. Returns the technician resource."""
    return get_success_data(
        _api.create_technician(create_technician_payload(**overrides), ADMIN)
    )


def create_unit(**overrides) -> dict:
    """Register an equipment unit as PlatformAdmin. Returns the unit resource."""
    return get_success_data(
        _api.create_equipment_unit(create_equipment_unit_payload(**overrides), ADMIN)
    )


def create_job(claim_id, **overrides) -> dict:
    """Create a loss job (FNOL intake) as Dispatcher. Returns the job resource."""
    return get_success_data(
        _api.create_job(create_job_payload(claim_id, **overrides), DISPATCHER)
    )


def create_fire_job(claim_id, loss_type="FIRE", property_address="X") -> dict:
    """Create a FIRE/SMOKE loss job omitting the WATER-only water_category /
    water_class fields entirely (they are not supplied for non-WATER losses)."""
    payload = {
        "claim_id": claim_id,
        "property_address": property_address,
        "loss_type": loss_type,
    }
    return get_success_data(_api.create_job(payload, DISPATCHER))


def tech_headers(tech_id: str) -> dict:
    """Ownership-threaded Technician headers for a dispatched technician."""
    return make_technician_headers(tech_id)


# ---------------------------------------------------------------------------
# Tier 1: claim + job + dispatched technician
# ---------------------------------------------------------------------------
def setup_dispatched_job(loss_type="WATER", certification="ASD",
                         claim_overrides=None, job_overrides=None):
    """Claim + technician + FNOL job dispatched to that technician.

    Returns dict with: claim, technician, job (post-dispatch), tech_id, tech_hdr.
    """
    claim_overrides = claim_overrides or {}
    job_overrides = job_overrides or {}
    claim = create_claim(**claim_overrides)
    tech = create_technician(certification=certification)
    job = create_job(claim["id"], loss_type=loss_type, **job_overrides)
    job = get_success_data(
        _api.dispatch_job(job["id"], {"technician_id": tech["id"]}, DISPATCHER)
    )
    return {
        "claim": claim,
        "technician": tech,
        "job": job,
        "tech_id": tech["id"],
        "tech_hdr": tech_headers(tech["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2: a chamber on a dispatched job (sizing computed)
# ---------------------------------------------------------------------------
def setup_job_with_chamber(loss_type="WATER", certification="ASD",
                           chamber_overrides=None, claim_overrides=None,
                           job_overrides=None):
    """Dispatched job + one OPEN chamber R1. Returns the dispatched-job dict
    plus 'chamber'."""
    ctx = setup_dispatched_job(
        loss_type=loss_type,
        certification=certification,
        claim_overrides=claim_overrides,
        job_overrides=job_overrides,
    )
    chamber_overrides = chamber_overrides or {}
    chamber = get_success_data(
        _api.create_chamber(
            create_chamber_payload(ctx["job"]["id"], **chamber_overrides), ctx["tech_hdr"]
        )
    )
    ctx["chamber"] = chamber
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: equip a chamber to satisfy its required counts, then progress state
# ---------------------------------------------------------------------------
def _place_units(job_id, chamber_id, tech_hdr, n_air=1, n_dehu=1, tag_prefix="U"):
    """Register and place n_air air movers + n_dehu dehumidifiers in a chamber.
    Returns (air_placements, dehu_placements)."""
    air_pl, dehu_pl = [], []
    for i in range(n_air):
        unit = create_unit(asset_tag=f"{tag_prefix}-AM-{i}", kind="AIR_MOVER")
        pl = get_success_data(
            _api.create_placement(
                create_placement_payload(job_id, chamber_id, unit["id"]), tech_hdr
            )
        )
        air_pl.append(pl)
    for i in range(n_dehu):
        unit = create_unit(asset_tag=f"{tag_prefix}-DH-{i}", kind="DEHUMIDIFIER")
        pl = get_success_data(
            _api.create_placement(
                create_placement_payload(job_id, chamber_id, unit["id"]), tech_hdr
            )
        )
        dehu_pl.append(pl)
    return air_pl, dehu_pl


def setup_monitoring_job(chamber_overrides=None, claim_overrides=None,
                         job_overrides=None, certification="ASD"):
    """Dispatched WATER job -> chamber R1 (1 AM + 1 DEHU placed) ->
    start-mitigation -> begin-monitoring. Chamber stays OPEN (no readings yet).

    Returns dict: claim, technician, job (MONITORING), chamber, tech_id, tech_hdr,
    air_placement, dehu_placement.
    """
    ctx = setup_job_with_chamber(
        certification=certification,
        chamber_overrides=chamber_overrides,
        claim_overrides=claim_overrides,
        job_overrides=job_overrides,
    )
    job_id = ctx["job"]["id"]
    air_pl, dehu_pl = _place_units(job_id, ctx["chamber"]["id"], ctx["tech_hdr"])
    get_success_data(_api.start_mitigation(job_id, ctx["tech_hdr"]))
    get_success_data(_api.begin_monitoring(job_id, ctx["tech_hdr"]))
    ctx["job"] = get_success_data(_api.get_job(job_id, DISPATCHER))
    ctx["air_placement"] = air_pl[0]
    ctx["dehu_placement"] = dehu_pl[0]
    return ctx


def create_and_approve_estimate(job_id, line_items=None, estimated_drying_days=1):
    """Read the job's current version, create a DRAFT estimate (OCC-guarded) and
    approve it (settling the claim). Returns the approved estimate resource."""
    line_items = line_items or [{"qty": 1, "unit_price_cents": 5000}]
    job = get_success_data(_api.get_job(job_id, DISPATCHER))
    est = get_success_data(
        _api.create_estimate(
            create_estimate_payload(
                job_id,
                job["version"],
                estimated_drying_days=estimated_drying_days,
                line_items=line_items,
            ),
            ESTIMATOR,
        )
    )
    return get_success_data(_api.approve_estimate(est["id"], ADJUSTER))


def create_draft_estimate(job_id, line_items=None, estimated_drying_days=1):
    """Create a single DRAFT estimate on a job with the current job version."""
    line_items = line_items or [{"qty": 1, "unit_price_cents": 5000}]
    job = get_success_data(_api.get_job(job_id, DISPATCHER))
    return get_success_data(
        _api.create_estimate(
            create_estimate_payload(
                job_id,
                job["version"],
                estimated_drying_days=estimated_drying_days,
                line_items=line_items,
            ),
            ESTIMATOR,
        )
    )


def dry_chamber(chamber_id, tech_hdr, moisture_content_pct=15,
                temp_f=72, relative_humidity_pct=38):
    """Log a reading that drives the chamber dry (mc <= dry_standard + 4)."""
    return get_success_data(
        _api.create_reading(
            chamber_id,
            create_reading_payload(
                temp_f=temp_f,
                relative_humidity_pct=relative_humidity_pct,
                moisture_content_pct=moisture_content_pct,
            ),
            tech_hdr,
        )
    )


def remove_placement(placement_id, tech_hdr):
    """Remove (pull) an ACTIVE placement, returning the unit to the pool."""
    return get_success_data(_api.remove_placement(placement_id, tech_hdr))


# ---------------------------------------------------------------------------
# Tier 4 / 5: full lifecycle through to completion-ready and COMPLETED
# ---------------------------------------------------------------------------
def setup_completion_ready(claim_overrides=None):
    """Drive a WATER job to MONITORING with: chamber R1 DRIED, an APPROVED
    estimate, and all equipment removed — i.e. ready to complete.

    Returns dict: claim, technician, job (MONITORING, drying_status
    DRY_STANDARD_MET), chamber (DRIED), estimate (APPROVED), tech_id, tech_hdr.
    """
    if claim_overrides is None:
        claim_overrides = {"coverage_limit_cents": 9_000_000}
    ctx = setup_monitoring_job(claim_overrides=claim_overrides)
    job_id = ctx["job"]["id"]
    tech_hdr = ctx["tech_hdr"]
    estimate = create_and_approve_estimate(job_id)
    dry_chamber(ctx["chamber"]["id"], tech_hdr)
    remove_placement(ctx["air_placement"]["id"], tech_hdr)
    remove_placement(ctx["dehu_placement"]["id"], tech_hdr)
    ctx["estimate"] = estimate
    ctx["job"] = get_success_data(_api.get_job(job_id, DISPATCHER))
    ctx["chamber"] = get_success_data(_api.get_chamber(ctx["chamber"]["id"], tech_hdr))
    return ctx


def setup_completed_job(claim_overrides=None):
    """Full lifecycle through COMPLETED. Returns the same dict as
    setup_completion_ready with job advanced to COMPLETED."""
    ctx = setup_completion_ready(claim_overrides=claim_overrides)
    job_id = ctx["job"]["id"]
    ctx["job"] = get_success_data(_api.complete_job(job_id, ctx["tech_hdr"]))
    return ctx


# ---------------------------------------------------------------------------
# Contents helpers
# ---------------------------------------------------------------------------
def add_contents(job_id, tech_hdr, description, declared_value_cents):
    """Pack out a contents item. Returns the item resource."""
    return get_success_data(
        _api.create_contents(
            create_contents_payload(
                job_id, description=description, declared_value_cents=declared_value_cents
            ),
            tech_hdr,
        )
    )
