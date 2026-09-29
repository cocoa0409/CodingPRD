"""Composite setup helpers that build multi-entity plant state from scratch.

Every helper drives the declared endpoints only; nothing reaches behind the
API. Setup calls use get_success_data() so that a setup failure surfaces as a
loud error rather than a confusing assertion inside the behaviour under test.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import test_users as users
from .api_client import ApiClient
from .factories import (
    DAY0,
    DAY1,
    DAY2,
    batch_recipe_payload,
    bottle_design_payload,
    campaign_payload,
    close_job_payload,
    color_change_payload,
    complaint_payload,
    customer_decision_payload,
    customer_payload,
    forming_machine_payload,
    furnace_payload,
    inspection_result_payload,
    investigate_payload,
    lightweighting_program_payload,
    mold_set_payload,
    production_job_payload,
    return_from_repair_payload,
    settle_payload,
)


# --------------------------------------------------------------------------
# Instant arithmetic against the logical clock
# --------------------------------------------------------------------------
def parse_instant(instant: str) -> datetime:
    """Parse an instant the API accepts or returns into an aware datetime."""
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def render_instant(moment: datetime) -> str:
    """Render an aware datetime as an instant the API accepts."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(instant: str, days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    """An instant offset from another by whole or fractional units."""
    return render_instant(
        parse_instant(instant) + timedelta(days=days, hours=hours, minutes=minutes)
    )


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api.set_clock(current_utc, users.PLANT_MANAGER))


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy, one level at a time
# --------------------------------------------------------------------------
def create_furnace(api: ApiClient, **overrides) -> dict:
    return get_success_data(api.create_furnace(furnace_payload(**overrides), users.PLANT_MANAGER))


def create_customer(api: ApiClient, **overrides) -> dict:
    return get_success_data(api.create_customer(customer_payload(**overrides), users.PLANT_MANAGER))


def create_campaign(api: ApiClient, furnace_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_campaign(campaign_payload(furnace_id, **overrides), users.PLANT_MANAGER)
    )


def activate_campaign(api: ApiClient, campaign_id: str) -> dict:
    return get_success_data(api.activate_campaign(campaign_id, users.PLANT_MANAGER))


def create_active_campaign(api: ApiClient, furnace_id: str, **overrides) -> dict:
    """A campaign carried straight through to ACTIVE."""
    campaign = create_campaign(api, furnace_id, **overrides)
    return activate_campaign(api, campaign["id"])


def create_batch_recipe(api: ApiClient, furnace_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_batch_recipe(batch_recipe_payload(furnace_id, **overrides), users.BATCH_TECH)
    )


def approve_batch_recipe(api: ApiClient, batch_recipe_id: str) -> dict:
    return get_success_data(api.approve_batch_recipe(batch_recipe_id, users.BATCH_TECH))


def create_approved_recipe(api: ApiClient, furnace_id: str, **overrides) -> dict:
    """A recipe whose approved flag is already true, so jobs may start on it."""
    recipe = create_batch_recipe(api, furnace_id, **overrides)
    return approve_batch_recipe(api, recipe["id"])


def create_forming_machine(api: ApiClient, furnace_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_forming_machine(
            forming_machine_payload(furnace_id, **overrides), users.PLANT_MANAGER
        )
    )


def create_design(api: ApiClient, customer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_bottle_design(bottle_design_payload(customer_id, **overrides), users.MOLD_ENGINEER)
    )


def submit_design(api: ApiClient, design_id: str) -> dict:
    return get_success_data(api.submit_bottle_design(design_id, users.MOLD_ENGINEER))


def create_submitted_design(api: ApiClient, customer_id: str, **overrides) -> dict:
    """A design carried to SUBMITTED, where both derived promises exist."""
    design = create_design(api, customer_id, **overrides)
    return submit_design(api, design["id"])


def create_risk_signed_design(
    api: ApiClient, customer_id: str, signer_headers: dict = None, **overrides
) -> dict:
    """A design signed off on risk, ready for a different approver."""
    design = create_submitted_design(api, customer_id, **overrides)
    return get_success_data(
        api.risk_signoff_bottle_design(design["id"], signer_headers or users.QE_RISK_SIGNER)
    )


def create_approved_design(
    api: ApiClient,
    customer_id: str,
    signer_headers: dict = None,
    approver_headers: dict = None,
    **overrides,
) -> dict:
    """A design carried through the full two-person approval to APPROVED."""
    design = create_risk_signed_design(api, customer_id, signer_headers, **overrides)
    return get_success_data(
        api.approve_bottle_design(design["id"], approver_headers or users.QE_APPROVER)
    )


def create_mold_set(api: ApiClient, bottle_design_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_mold_set(mold_set_payload(bottle_design_id, **overrides), users.MOLD_ENGINEER)
    )


def send_mold_set_to_repair(api: ApiClient, mold_set_id: str) -> dict:
    return get_success_data(api.send_mold_set_to_repair(mold_set_id, users.MOLD_ENGINEER))


def return_mold_set(api: ApiClient, mold_set_id: str, condition_score: int) -> dict:
    return get_success_data(
        api.return_mold_set_from_repair(
            mold_set_id, return_from_repair_payload(condition_score), users.MOLD_ENGINEER
        )
    )


def furnace_version(api: ApiClient, furnace_id: str) -> int:
    """The furnace's current version, as the job create guard demands it."""
    furnace = get_success_data(api.get_furnace(furnace_id, users.PLANT_MANAGER))
    return furnace["version"]


def design_version(api: ApiClient, design_id: str) -> int:
    """The design's current version, as the program create guard demands it."""
    design = get_success_data(api.get_bottle_design(design_id, users.MOLD_ENGINEER))
    return design["version"]


def read_furnace(api: ApiClient, furnace_id: str) -> dict:
    return get_success_data(api.get_furnace(furnace_id, users.PLANT_MANAGER))


def read_campaign(api: ApiClient, campaign_id: str) -> dict:
    return get_success_data(api.get_campaign(campaign_id, users.PLANT_MANAGER))


def read_customer(api: ApiClient, customer_id: str) -> dict:
    return get_success_data(api.get_customer(customer_id, users.PLANT_MANAGER))


def read_design(api: ApiClient, design_id: str) -> dict:
    return get_success_data(api.get_bottle_design(design_id, users.MOLD_ENGINEER))


def read_mold_set(api: ApiClient, mold_set_id: str) -> dict:
    return get_success_data(api.get_mold_set(mold_set_id, users.MOLD_ENGINEER))


def read_machine(api: ApiClient, machine_id: str) -> dict:
    return get_success_data(api.get_forming_machine(machine_id, users.PLANT_MANAGER))


def read_job(api: ApiClient, job_id: str) -> dict:
    return get_success_data(api.get_production_job(job_id, users.SCHEDULER))


def read_lot(api: ApiClient, lot_id: str) -> dict:
    return get_success_data(api.get_pack_lot(lot_id, users.QE_INSPECTOR))


def read_program(api: ApiClient, program_id: str) -> dict:
    return get_success_data(api.get_lightweighting_program(program_id, users.QE_APPROVER))


def read_complaint(api: ApiClient, complaint_id: str) -> dict:
    return get_success_data(api.get_complaint(complaint_id, users.QE_INVESTIGATOR))


# --------------------------------------------------------------------------
# Tier 3: the full bring-up shortcut
# --------------------------------------------------------------------------
@dataclass
class PlantContext:
    """Everything a production job needs, already in the right state."""

    furnace: dict
    customer: dict
    campaign: dict
    recipe: dict
    machine: dict
    design: dict
    mold_set: Optional[dict] = None
    extras: dict = field(default_factory=dict)

    @property
    def furnace_id(self) -> str:
        return self.furnace["id"]

    @property
    def customer_id(self) -> str:
        return self.customer["id"]

    @property
    def campaign_id(self) -> str:
        return self.campaign["id"]

    @property
    def recipe_id(self) -> str:
        return self.recipe["id"]

    @property
    def machine_id(self) -> str:
        return self.machine["id"]

    @property
    def design_id(self) -> str:
        return self.design["id"]

    @property
    def mold_set_id(self) -> Optional[str]:
        return None if self.mold_set is None else self.mold_set["id"]

    @property
    def rep_headers(self) -> dict:
        return users.customer_rep(self.customer_id)


def bring_up_plant(
    api: ApiClient,
    furnace: dict = None,
    customer: dict = None,
    campaign: dict = None,
    recipe: dict = None,
    machine: dict = None,
    design: dict = None,
    mold_set: dict = None,
    activate: bool = True,
    approve_recipe: bool = True,
    design_state: str = "APPROVED",
    with_mold_set: bool = True,
) -> PlantContext:
    """Commission a furnace, customer, campaign, recipe, machine, design and tooling.

    design_state selects how far the bottle design is carried: DRAFT, SUBMITTED,
    RISK_SIGNED or APPROVED. activate selects whether the campaign is left in
    PLANNED or carried to ACTIVE.
    """
    furnace_entity = create_furnace(api, **(furnace or {}))
    customer_entity = create_customer(api, **(customer or {}))

    campaign_entity = create_campaign(api, furnace_entity["id"], **(campaign or {}))
    if activate:
        campaign_entity = activate_campaign(api, campaign_entity["id"])

    recipe_overrides = recipe or {}
    recipe_entity = create_batch_recipe(api, furnace_entity["id"], **recipe_overrides)
    if approve_recipe:
        recipe_entity = approve_batch_recipe(api, recipe_entity["id"])

    machine_entity = create_forming_machine(api, furnace_entity["id"], **(machine or {}))

    design_overrides = design or {}
    if design_state == "DRAFT":
        design_entity = create_design(api, customer_entity["id"], **design_overrides)
    elif design_state == "SUBMITTED":
        design_entity = create_submitted_design(api, customer_entity["id"], **design_overrides)
    elif design_state == "RISK_SIGNED":
        design_entity = create_risk_signed_design(api, customer_entity["id"], **design_overrides)
    else:
        design_entity = create_approved_design(api, customer_entity["id"], **design_overrides)

    mold_set_entity = None
    if with_mold_set:
        mold_set_entity = create_mold_set(api, design_entity["id"], **(mold_set or {}))

    return PlantContext(
        furnace=furnace_entity,
        customer=customer_entity,
        campaign=campaign_entity,
        recipe=recipe_entity,
        machine=machine_entity,
        design=design_entity,
        mold_set=mold_set_entity,
    )


# --------------------------------------------------------------------------
# Production jobs
# --------------------------------------------------------------------------
def job_payload_for(api: ApiClient, ctx: PlantContext, **overrides) -> dict:
    """A job payload wired to the context, with the furnace version read fresh."""
    expected = overrides.pop("expected_furnace_version", None)
    if expected is None:
        expected = furnace_version(api, ctx.furnace_id)
    mold_set_id = overrides.pop("mold_set_id", ctx.mold_set_id)
    # The five references default to the context but each may be redirected by
    # keyword, which is how a test builds a deliberately mismatched payload.
    campaign_id = overrides.pop("campaign_id", ctx.campaign_id)
    furnace_id = overrides.pop("furnace_id", ctx.furnace_id)
    forming_machine_id = overrides.pop("forming_machine_id", ctx.machine_id)
    batch_recipe_id = overrides.pop("batch_recipe_id", ctx.recipe_id)
    bottle_design_id = overrides.pop("bottle_design_id", ctx.design_id)
    return production_job_payload(
        campaign_id,
        furnace_id,
        forming_machine_id,
        batch_recipe_id,
        bottle_design_id,
        expected,
        mold_set_id=mold_set_id,
        **overrides,
    )


def schedule_job(api: ApiClient, ctx: PlantContext, **overrides) -> dict:
    """A production job created in SCHEDULED against the context."""
    return get_success_data(
        api.create_production_job(job_payload_for(api, ctx, **overrides), users.SCHEDULER)
    )


def start_job(api: ApiClient, job_id: str) -> dict:
    return get_success_data(api.start_production_job(job_id, users.SCHEDULER))


def close_job(api: ApiClient, job_id: str, outcome: str = "COMPLETED", **overrides) -> dict:
    return get_success_data(
        api.close_production_job(job_id, close_job_payload(outcome, **overrides), users.SCHEDULER)
    )


def cancel_job(api: ApiClient, job_id: str) -> dict:
    return get_success_data(api.cancel_production_job(job_id, users.SCHEDULER))


def running_job(api: ApiClient, ctx: PlantContext, **overrides) -> dict:
    """A job carried to RUNNING, with tooling mounted and the machine busy."""
    job = schedule_job(api, ctx, **overrides)
    return start_job(api, job["id"])


def lot_for_job(api: ApiClient, job_id: str) -> dict:
    """The single pack lot a completed close creates for a job."""
    lots, _meta = validate_paginated(
        api.list_pack_lots(users.QE_INSPECTOR, production_job_id=job_id)
    )
    assert lots, f"no pack lot was created for job {job_id}"
    return lots[0]


def completed_job_with_lot(
    api: ApiClient, ctx: PlantContext, produced_units: int = 3000000, **overrides
):
    """A job driven scheduled -> running -> completed, with its lot read back."""
    job = schedule_job(api, ctx, **overrides)
    start_job(api, job["id"])
    closed = close_job(api, job["id"], "COMPLETED", produced_units=produced_units)
    return closed, lot_for_job(api, job["id"])


# --------------------------------------------------------------------------
# Tier 4: inspection readings and accumulation targeting
# --------------------------------------------------------------------------
def record_reading(api: ApiClient, lot_id: str, headers: dict = None, **overrides) -> dict:
    """One inspection-line reading against a lot."""
    return get_success_data(
        api.record_inspection_result(
            lot_id, inspection_result_payload(**overrides), headers or users.QE_INSPECTOR
        )
    )


def record_readings(api: ApiClient, lot_id: str, readings, headers: dict = None) -> list:
    """Several readings in order, each one recomputing the lot's figures."""
    recorded = []
    for reading in readings:
        recorded.append(record_reading(api, lot_id, headers=headers, **reading))
    return recorded


def release_lot(api: ApiClient, lot_id: str, headers: dict = None) -> dict:
    return get_success_data(api.release_pack_lot(lot_id, headers or users.QE_INSPECTOR))


def rework_release_lot(api: ApiClient, lot_id: str, headers: dict = None) -> dict:
    return get_success_data(api.rework_release_pack_lot(lot_id, headers or users.QE_RELEASER))


def palletize_lot(api: ApiClient, lot_id: str) -> dict:
    return get_success_data(api.palletize_pack_lot(lot_id, users.WAREHOUSE))


def ship_lot(api: ApiClient, lot_id: str) -> dict:
    return get_success_data(api.ship_pack_lot(lot_id, users.WAREHOUSE))


def released_lot(
    api: ApiClient,
    ctx: PlantContext,
    produced_units: int = 3000000,
    readings=None,
    job_overrides: dict = None,
):
    """A lot with at least one reading recorded and a RELEASED quality status."""
    _closed, lot = completed_job_with_lot(
        api, ctx, produced_units=produced_units, **(job_overrides or {})
    )
    record_readings(api, lot["id"], readings or [{"rejected_units": 1}])
    return release_lot(api, lot["id"])


# --------------------------------------------------------------------------
# Tier 5: terminal logistics state
# --------------------------------------------------------------------------
def shipped_lot(
    api: ApiClient,
    ctx: PlantContext,
    produced_units: int = 3000000,
    readings=None,
    job_overrides: dict = None,
) -> dict:
    """A lot carried all the way to SHIPPED, the only state a complaint accepts."""
    lot = released_lot(
        api,
        ctx,
        produced_units=produced_units,
        readings=readings,
        job_overrides=job_overrides,
    )
    set_clock(api, lot["aged_until_at"])
    palletize_lot(api, lot["id"])
    return ship_lot(api, lot["id"])


# --------------------------------------------------------------------------
# Colour changes
# --------------------------------------------------------------------------
def schedule_color_change(api: ApiClient, furnace_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_color_change(color_change_payload(furnace_id, **overrides), users.BATCH_TECH)
    )


def complete_color_change(api: ApiClient, color_change_id: str) -> dict:
    return get_success_data(api.complete_color_change(color_change_id, users.BATCH_TECH))


def completed_color_change(api: ApiClient, furnace_id: str, **overrides) -> dict:
    """A transition completed after its window has elapsed on the logical clock."""
    change = schedule_color_change(api, furnace_id, **overrides)
    set_clock(api, change["window_end_at"])
    return complete_color_change(api, change["id"])


# --------------------------------------------------------------------------
# Lightweighting programs
# --------------------------------------------------------------------------
def create_program(api: ApiClient, design_id: str, **overrides) -> dict:
    expected = overrides.pop("expected_design_version", None)
    if expected is None:
        expected = design_version(api, design_id)
    return get_success_data(
        api.create_lightweighting_program(
            lightweighting_program_payload(design_id, expected, **overrides), users.QE_APPROVER
        )
    )


def assess_program(api: ApiClient, program_id: str) -> dict:
    return get_success_data(api.assess_program_risk(program_id, users.QE_APPROVER))


def assessed_program(api: ApiClient, design_id: str, **overrides) -> dict:
    """A program carried to RISK_ASSESSED, with the whole economics chain computed."""
    program = create_program(api, design_id, **overrides)
    return assess_program(api, program["id"])


def decide_program(api: ApiClient, program_id: str, customer_id: str, decision: str) -> dict:
    return get_success_data(
        api.program_customer_decision(
            program_id, customer_decision_payload(decision), users.customer_rep(customer_id)
        )
    )


def piloted_program(api: ApiClient, design_id: str, customer_id: str, **overrides) -> dict:
    """A program the customer has accepted into PILOT."""
    program = assessed_program(api, design_id, **overrides)
    return decide_program(api, program["id"], customer_id, "PILOT")


def adopted_program(api: ApiClient, design_id: str, customer_id: str, **overrides) -> dict:
    """A program adopted by the plant, which extends warehouse aging."""
    program = piloted_program(api, design_id, customer_id, **overrides)
    return get_success_data(api.adopt_program(program["id"], users.PLANT_MANAGER))


# --------------------------------------------------------------------------
# Complaints
# --------------------------------------------------------------------------
def file_complaint(api: ApiClient, customer_id: str, lot_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_complaint(
            complaint_payload(customer_id, lot_id, **overrides), users.customer_rep(customer_id)
        )
    )


def investigate(
    api: ApiClient, complaint_id: str, attribution: str = "PLANT", headers: dict = None
) -> dict:
    return get_success_data(
        api.investigate_complaint(
            complaint_id, investigate_payload(attribution), headers or users.QE_INVESTIGATOR
        )
    )


def settle(
    api: ApiClient, complaint_id: str, customer_id: str, settlement: str = "CREDIT"
) -> dict:
    return get_success_data(
        api.settle_complaint(
            complaint_id, settle_payload(settlement), users.customer_rep(customer_id)
        )
    )


def credited_complaint(
    api: ApiClient,
    customer_id: str,
    lot_id: str,
    attribution: str = "PLANT",
    **overrides,
) -> dict:
    """A complaint driven filed -> investigated -> credited, updating the customer."""
    complaint = file_complaint(api, customer_id, lot_id, **overrides)
    investigate(api, complaint["id"], attribution)
    return settle(api, complaint["id"], customer_id, "CREDIT")


# Re-exported window anchors so tests can build windows without importing factories.
WINDOW_START = DAY0
WINDOW_MID = DAY1
WINDOW_END = DAY2
