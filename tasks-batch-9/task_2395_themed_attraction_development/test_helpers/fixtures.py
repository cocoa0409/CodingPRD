"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its state from scratch through published endpoints only, and
uses the lenient success reader so a broken precondition reports as a setup
failure rather than as a confusing assertion failure.

Because a cascading write advances the version of every resource it touches, a
client that intends to keep writing must re-read before every version-pinned
call. These helpers therefore always re-read the parent immediately before a
write that carries an `expected_*_version` field.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_CLOCK_UTC
from .factories import (
    create_design_package_payload,
    create_effect_cue_payload,
    create_ledger_entry_payload,
    create_maintenance_item_payload,
    create_project_payload,
    create_queue_segment_payload,
    create_rehearsal_run_payload,
    create_ride_system_payload,
    create_safety_finding_payload,
    create_safety_review_payload,
    create_show_scene_payload,
    create_value_engineering_item_payload,
    create_ve_ballot_payload,
)
from .test_users import TEST_USERS

OWNER = TEST_USERS["owner_rep_headers"]
SECOND_OWNER = TEST_USERS["second_owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
PROGRAMMER = TEST_USERS["show_programmer_headers"]
REVIEWER = TEST_USERS["third_party_reviewer_headers"]
CONTRACTOR = TEST_USERS["contractor_pm_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


# ─── Version readers ──────────────────────────────────

def project_version(project_id: str) -> int:
    """The programme's current revision counter."""
    return get_success_data(api_client.get_project(project_id, OWNER))["version"]


def package_version(package_id: str) -> int:
    """The design package's current revision counter."""
    return get_success_data(api_client.get_design_package(package_id, OWNER))["version"]


def ride_system_version(ride_system_id: str) -> int:
    """The ride system's current revision counter."""
    return get_success_data(api_client.get_ride_system(ride_system_id, ENGINEER))["version"]


def read_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, OWNER))


# ─── Logical clock ────────────────────────────────────

def set_logical_clock(to_iso8601: str = DEFAULT_LOGICAL_CLOCK_UTC) -> dict:
    """Reposition the server's logical clock to a supplied instant."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# ─── Tier 1: single-step creates and transitions ──────

def open_project(**overrides) -> dict:
    """Open a new themed attraction programme at BLUE_SKY."""
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), OWNER)
    )


def register_ride_system(project_id: str, **overrides) -> dict:
    """Register a candidate ride system against the programme."""
    return get_success_data(
        api_client.create_ride_system(
            create_ride_system_payload(project_id, **overrides), ENGINEER
        )
    )


def add_scene(project_id: str, **overrides) -> dict:
    """Create a storyline scene in DRAFT."""
    return get_success_data(
        api_client.create_show_scene(
            create_show_scene_payload(project_id, **overrides), DESIGNER
        )
    )


def add_prologue_and_chase(project_id: str) -> tuple:
    """The two-beat storyline used by most programmes: Prologue then Chase."""
    sc1 = add_scene(project_id, scene_label="Prologue", sequence_index=1,
                    duration_seconds=180)
    sc2 = add_scene(project_id, scene_label="Chase", sequence_index=2,
                    duration_seconds=120, follows_scene_id=sc1["id"])
    return sc1, sc2


def sequence_scene(scene_id: str, sequence_index: int,
                   follows_scene_id: str = None) -> dict:
    """Lock the scene into the running order."""
    payload = {"sequence_index": sequence_index}
    if follows_scene_id is not None:
        payload["follows_scene_id"] = follows_scene_id
    return get_success_data(
        api_client.sequence_show_scene(scene_id, payload, DESIGNER)
    )


def advance_to(project_id: str, to_phase: str) -> dict:
    """Advance the design phase one rung, pinned to the live programme revision."""
    return get_success_data(
        api_client.advance_phase(
            project_id,
            {"to_phase": to_phase, "expected_project_version": project_version(project_id)},
            OWNER,
        )
    )


def select_ride(ride_system_id: str, project_id: str) -> dict:
    """Select the candidate as the programme's ride system."""
    return get_success_data(
        api_client.select_ride_system(
            ride_system_id,
            {"expected_project_version": project_version(project_id)},
            OWNER,
        )
    )


def mark_engineered(ride_system_id: str, safety_standard: str = "ASTM_F2291",
                    control_system_spec_ref: str = "CS-SPEC-2395-R3") -> dict:
    """Record engineering completion against a declared design standard."""
    return get_success_data(
        api_client.mark_ride_system_engineered(
            ride_system_id,
            {"safety_standard": safety_standard,
             "control_system_spec_ref": control_system_spec_ref},
            ENGINEER,
        )
    )


def commission_ride(ride_system_id: str) -> dict:
    """Commission the ride system after safety clearance."""
    return get_success_data(
        api_client.commission_ride_system(ride_system_id, {}, ENGINEER)
    )


def add_package(project_id: str, ride_system_id: str, **overrides) -> dict:
    """Create a design package and price its cost of work."""
    return get_success_data(
        api_client.create_design_package(
            create_design_package_payload(
                project_id, ride_system_id, project_version(project_id), **overrides
            ),
            DESIGNER,
        )
    )


def submit_package(package_id: str, headers: dict = None) -> dict:
    """Submit the package for owner approval."""
    return get_success_data(
        api_client.submit_design_package(package_id, {}, headers or DESIGNER)
    )


def request_revision(package_id: str, reason: str = "Owner requests a cheaper set package") -> dict:
    return get_success_data(
        api_client.request_package_revision(package_id, {"reason": reason}, OWNER)
    )


def revise_package(package_id: str, base_construction_cost_cents: int) -> dict:
    """Re-price the package during a revision round."""
    return get_success_data(
        api_client.revise_design_package(
            package_id,
            {"base_construction_cost_cents": base_construction_cost_cents,
             "expected_package_version": package_version(package_id)},
            DESIGNER,
        )
    )


def approve_package(package_id: str, headers: dict = None) -> dict:
    """Approve the package and commit its cost of work."""
    return get_success_data(
        api_client.approve_design_package(
            package_id,
            {"expected_package_version": package_version(package_id)},
            headers or OWNER,
        )
    )


def open_review(package_id: str, standard_code: str = "ASTM_F2291") -> dict:
    """Open a third-party review against the package."""
    return get_success_data(
        api_client.create_safety_review(
            create_safety_review_payload(
                package_id, package_version(package_id), standard_code=standard_code
            ),
            REVIEWER,
        )
    )


def clear_review(review_id: str) -> dict:
    """Clear the review."""
    return get_success_data(api_client.clear_safety_review(review_id, {}, REVIEWER))


def raise_finding(review_id: str, **overrides) -> dict:
    """Raise a non-conformance finding against the review."""
    return get_success_data(
        api_client.create_safety_finding(
            create_safety_finding_payload(review_id, **overrides), REVIEWER
        )
    )


def resolve_finding(finding_id: str,
                    remediation_note: str = "Handrail extended and re-surveyed on site") -> dict:
    return get_success_data(
        api_client.resolve_safety_finding(
            finding_id, {"remediation_note": remediation_note}, CONTRACTOR
        )
    )


def close_finding(finding_id: str) -> dict:
    return get_success_data(api_client.close_safety_finding(finding_id, {}, REVIEWER))


def waive_finding(finding_id: str,
                  justification: str = "Owner accepts residual risk for this cycle") -> dict:
    return get_success_data(
        api_client.waive_safety_finding(
            finding_id, {"justification": justification}, OWNER
        )
    )


def propose_ve_item(project_id: str, **overrides) -> dict:
    """Propose a value-engineering saving."""
    return get_success_data(
        api_client.create_value_engineering_item(
            create_value_engineering_item_payload(project_id, **overrides), CONTRACTOR
        )
    )


def open_ve_review(item_id: str) -> dict:
    """Open the three-party ballot and fix the net saving."""
    return get_success_data(
        api_client.open_value_engineering_review(item_id, {}, OWNER)
    )


_BALLOT_HEADERS = {
    "OwnerRep": OWNER,
    "ContractorPM": CONTRACTOR,
    "CreativeDirector": DESIGNER,
}


def cast_ballot(item_id: str, party_role: str, decision: str, **overrides) -> dict:
    """Cast one party's ballot on the item, acting in that party's role."""
    return get_success_data(
        api_client.create_ve_ballot(
            create_ve_ballot_payload(item_id, party_role, decision, **overrides),
            _BALLOT_HEADERS[party_role],
        )
    )


def propose_segment(project_id: str, **overrides) -> dict:
    """Propose a queue segment and compute its guest capacity."""
    return get_success_data(
        api_client.create_queue_segment(
            create_queue_segment_payload(project_id, **overrides), DESIGNER
        )
    )


def accept_segment(segment_id: str, project_id: str) -> dict:
    """Accept the segment into the queue."""
    return get_success_data(
        api_client.accept_queue_segment(
            segment_id, {"expected_project_version": project_version(project_id)}, OWNER
        )
    )


def retire_segment(segment_id: str, project_id: str) -> dict:
    """Retire an accepted segment."""
    return get_success_data(
        api_client.retire_queue_segment(
            segment_id, {"expected_project_version": project_version(project_id)}, OWNER
        )
    )


def place_cue(scene_id: str, **overrides) -> dict:
    """Place a cue on the scene timeline."""
    return get_success_data(
        api_client.create_effect_cue(
            create_effect_cue_payload(scene_id, **overrides), PROGRAMMER
        )
    )


def verify_cue(cue_id: str) -> dict:
    """Mark the cue verified on the programming console."""
    return get_success_data(api_client.verify_effect_cue(cue_id, {}, PROGRAMMER))


def program_scene(scene_id: str, lighting_score: float, audio_score: float,
                  animation_score: float, effects_score: float) -> dict:
    """Record the four discipline scores and roll up show quality."""
    return get_success_data(
        api_client.program_show_scene(
            scene_id,
            {"lighting_score": lighting_score, "audio_score": audio_score,
             "animation_score": animation_score, "effects_score": effects_score},
            PROGRAMMER,
        )
    )


def post_change_order(project_id: str, amount_cents: int,
                      memo: str = "Owner-directed change order") -> dict:
    """Post a change-order entry to the programme cost ledger."""
    return get_success_data(
        api_client.create_ledger_entry(
            create_ledger_entry_payload(
                project_id, project_version(project_id),
                amount_cents=amount_cents, memo=memo,
            ),
            OWNER,
        )
    )


def reverse_entry(entry_id: str, project_id: str,
                  reason: str = "Change order raised against the wrong programme") -> dict:
    """Mint the compensating reversal entry."""
    return get_success_data(
        api_client.reverse_ledger_entry(
            entry_id,
            {"reason": reason, "expected_project_version": project_version(project_id)},
            OWNER,
        )
    )


def book_run(project_id: str, **overrides) -> dict:
    """Book a rehearsal or soft-open window."""
    return get_success_data(
        api_client.create_rehearsal_run(
            create_rehearsal_run_payload(project_id, **overrides), CONTRACTOR
        )
    )


def complete_run(run_id: str, guests_cycled: int, duration_minutes: int) -> dict:
    """Record the run and validate measured throughput."""
    return get_success_data(
        api_client.complete_rehearsal_run(
            run_id,
            {"guests_cycled": guests_cycled, "duration_minutes": duration_minutes},
            CONTRACTOR,
        )
    )


def add_maintenance_item(project_id: str, **overrides) -> dict:
    """Add a maintenance procedure or spare part and compute recommended stock."""
    return get_success_data(
        api_client.create_maintenance_item(
            create_maintenance_item_payload(project_id, **overrides), ENGINEER
        )
    )


def patch_project(project_id: str, **fields) -> dict:
    """Revise the programme's assumptions, pinned to its live revision."""
    payload = dict(fields)
    payload["expected_project_version"] = project_version(project_id)
    return get_success_data(api_client.patch_project(project_id, payload, OWNER))


# ─── Tier 2: programme walked up the delivery ladder ──

def setup_program_at_concept(project_overrides=None, ride_overrides=None) -> dict:
    """Programme at CONCEPT with two DRAFT scenes and one CANDIDATE ride system."""
    project = open_project(**(project_overrides or {}))
    sc1, sc2 = add_prologue_and_chase(project["id"])
    ride = register_ride_system(project["id"], **(ride_overrides or {}))
    advance_to(project["id"], "CONCEPT")
    return {"project": project, "sc1": sc1, "sc2": sc2, "ride_system": ride}


def setup_program_at_schematic(project_overrides=None, ride_overrides=None,
                              mark_ride_engineered: bool = False,
                              safety_standard: str = "ASTM_F2291",
                              control_system_spec_ref: str = "CS-SPEC-2395-R3") -> dict:
    """Programme at SCHEMATIC: ride system SELECTED, both scenes SEQUENCED.

    Reaching SCHEMATIC needs a non-null selected_ride_system_id and at least two
    sequenced scenes, so the chain is: open the programme, write two scenes,
    register the candidate, advance to CONCEPT, select the candidate, sequence
    both scenes, then advance to SCHEMATIC.
    """
    ctx = setup_program_at_concept(project_overrides, ride_overrides)
    select_ride(ctx["ride_system"]["id"], ctx["project"]["id"])
    sequence_scene(ctx["sc1"]["id"], 1)
    sequence_scene(ctx["sc2"]["id"], 2, follows_scene_id=ctx["sc1"]["id"])
    advance_to(ctx["project"]["id"], "SCHEMATIC")
    if mark_ride_engineered:
        mark_engineered(ctx["ride_system"]["id"], safety_standard, control_system_spec_ref)
    return ctx


def setup_program_with_submitted_package(package_overrides=None, **kwargs) -> dict:
    """Programme at SCHEMATIC carrying one SUBMITTED design package."""
    ctx = setup_program_at_schematic(**kwargs)
    package = add_package(ctx["project"]["id"], ctx["ride_system"]["id"],
                          **(package_overrides or {}))
    ctx["package"] = submit_package(package["id"])
    return ctx


def setup_program_with_approved_package(package_overrides=None,
                                       approver_headers=None, **kwargs) -> dict:
    """Programme at DESIGN_DEVELOPMENT carrying one APPROVED design package.

    Approval mints the COMMITMENT ledger entry and recomputes the programme's
    committed cost and posture, so this is the entry point for every budget test.
    """
    ctx = setup_program_with_submitted_package(package_overrides, **kwargs)
    advance_to(ctx["project"]["id"], "DESIGN_DEVELOPMENT")
    ctx["package"] = approve_package(ctx["package"]["id"], approver_headers)
    return ctx


def setup_program_with_cleared_review(**kwargs) -> dict:
    """Programme at DESIGN_DEVELOPMENT with an APPROVED package carrying a
    CLEARED safety review — the clearance the PRODUCTION rung requires."""
    ctx = setup_program_with_approved_package(**kwargs)
    standard = kwargs.get("safety_standard", "ASTM_F2291")
    review = open_review(ctx["package"]["id"], standard_code=standard)
    ctx["review"] = clear_review(review["id"])
    return ctx


def setup_program_at_installation(**kwargs) -> dict:
    """Programme at INSTALLATION with an ENGINEERED ride system and a cleared review."""
    kwargs.setdefault("mark_ride_engineered", True)
    ctx = setup_program_with_cleared_review(**kwargs)
    advance_to(ctx["project"]["id"], "PRODUCTION")
    advance_to(ctx["project"]["id"], "INSTALLATION")
    return ctx


def setup_program_with_commissioned_ride(**kwargs) -> dict:
    """Programme at INSTALLATION with the ride system COMMISSIONED."""
    ctx = setup_program_at_installation(**kwargs)
    ctx["ride_system"] = commission_ride(ctx["ride_system"]["id"])
    return ctx


def setup_program_at_technical_rehearsal(standard_segment=None,
                                         accessible_segment=None, **kwargs) -> dict:
    """Programme at TECHNICAL_REHEARSAL.

    The rung needs the selected system COMMISSIONED, at least one ACCEPTED
    ACCESSIBLE segment, and an accessible share of at least fifteen percent, so
    two segments are proposed and accepted before the advance: a STANDARD
    switchback of 443 guests and an ACCESSIBLE return of 96 guests.
    """
    ctx = setup_program_with_commissioned_ride(**kwargs)
    project_id = ctx["project"]["id"]
    std = propose_segment(
        project_id,
        **(standard_segment or {"segment_label": "Switchback A", "length_meters": 120,
                                "width_meters": 2.4, "routing_type": "STANDARD",
                                "position_index": 1}),
    )
    acc = propose_segment(
        project_id,
        **(accessible_segment or {"segment_label": "Accessible Return",
                                  "length_meters": 72, "width_meters": 2.0,
                                  "routing_type": "ACCESSIBLE", "position_index": 2}),
    )
    ctx["standard_segment"] = accept_segment(std["id"], project_id)
    ctx["accessible_segment"] = accept_segment(acc["id"], project_id)
    advance_to(project_id, "TECHNICAL_REHEARSAL")
    return ctx


# ─── Tier 3: posture-targeting helpers ────────────────

def setup_restricted_program_by_change_order(top_up_cents: int, **kwargs) -> dict:
    """Programme with an APPROVED package plus one change order, so the committed
    cost sits at a chosen distance from the restricted-utilisation threshold."""
    ctx = setup_program_with_approved_package(**kwargs)
    ctx["change_order"] = post_change_order(ctx["project"]["id"], top_up_cents)
    return ctx


def setup_budget_frozen_program(new_ceiling_cents: int = 3000000000, **kwargs) -> dict:
    """Programme frozen on cost alone: the ceiling is cut below the committed cost,
    which cascades every sequenced scene to HELD with hold_reason BUDGET_FREEZE."""
    ctx = setup_program_with_approved_package(**kwargs)
    ctx["project"] = patch_project(ctx["project"]["id"],
                                   budget_ceiling_cents=new_ceiling_cents)
    return ctx


def setup_program_with_open_finding(severity: str = "MAJOR",
                                    remediation_cost_estimate_cents: int = 12000000,
                                    description: str = None, **kwargs) -> dict:
    """Programme with an APPROVED package, an open review and one OPEN finding of
    the requested severity — a critical one freezes the programme outright."""
    ctx = setup_program_with_approved_package(**kwargs)
    review = open_review(ctx["package"]["id"])
    payload = {"severity": severity,
               "remediation_cost_estimate_cents": remediation_cost_estimate_cents}
    if description is not None:
        payload["description"] = description
    ctx["review"] = review
    ctx["finding"] = raise_finding(review["id"], **payload)
    return ctx


def setup_program_with_in_flight_ve_item(item_overrides=None, **kwargs) -> dict:
    """Programme with an APPROVED package and one UNDER_REVIEW value-engineering
    item, so its net saving belongs to the in-flight savings set."""
    ctx = setup_program_with_approved_package(**kwargs)
    item = propose_ve_item(ctx["project"]["id"], **(item_overrides or {}))
    ctx["ve_item"] = open_ve_review(item["id"])
    return ctx


# ─── Tier 4: show-programming helpers ─────────────────

def setup_scene_with_verified_cue(scene_id: str, **overrides) -> dict:
    """Place one cue on the scene timeline and verify it, so the scene owns at
    least one cue and every cue of the scene is VERIFIED."""
    cue = place_cue(scene_id, **overrides)
    return verify_cue(cue["id"])


def setup_programmed_scene(ctx: dict, scene_key: str = "sc1",
                           lighting_score: float = 90.00, audio_score: float = 85.00,
                           animation_score: float = 88.00,
                           effects_score: float = 89.00) -> dict:
    """Take one SEQUENCED scene of a programme through to PROGRAMMED."""
    scene_id = ctx[scene_key]["id"]
    setup_scene_with_verified_cue(scene_id)
    return program_scene(scene_id, lighting_score, audio_score,
                         animation_score, effects_score)


# ─── Tier 5: ledger and listing readers ───────────────

def read_ledger(project_id: str, params=None) -> tuple:
    """The programme cost ledger in chronological order."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(
        api_client.list_project_ledger_entries(project_id, OWNER, params=params)
    )


def read_capacity_summary(project_id: str) -> dict:
    return get_success_data(api_client.get_capacity_summary(project_id, OWNER))


def read_budget_position(project_id: str) -> dict:
    return get_success_data(api_client.get_budget_position(project_id, OWNER))
