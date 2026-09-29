"""Adjudicating who bears the relocation cost, and the two evidentiary variants."""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    draft_determination,
    identify_conflict,
    issue_determination,
    read_conflict,
    read_determination,
    read_investigation,
    read_project,
    record_investigation,
    register_facility,
    register_owner,
    register_project,
    select_resolution,
    validate_success,
    make_right_of_way_adjudicator_headers,
    world_determination_drafted,
    world_registry,
)


def _twin_easement_corridor(api, *, project_name, investigations):
    """Two byte-identical PRIVATE_EASEMENT facilities, each with a conflict and a
    determination waiting in review.  ``investigations`` maps the facility key
    ("a" or "b") to the ``measured_depth_in`` of one QL_A vacuum test hole."""
    project = register_project(api, name=project_name)
    owner = register_owner(api)
    facility_a = register_facility(api, owner["id"])
    facility_b = register_facility(api, owner["id"], station_begin=200.0, station_end=240.0)
    facilities = {"a": facility_a, "b": facility_b}
    stations = {"a": 120.0, "b": 220.0}
    readings = {}
    for key, depth in investigations.items():
        readings[key] = record_investigation(
            api,
            project["id"],
            facilities[key]["id"],
            quality_level="QL_A",
            method="VACUUM_TEST_HOLE",
            measured_depth_in=depth,
            station_at_investigation=stations[key],
        )
    conflicts = {}
    determinations = {}
    for key in ("a", "b"):
        conflict = identify_conflict(
            api,
            project["id"],
            facilities[key]["id"],
            conflict_station=stations[key],
            clearance_deficiency_in=18,
        )
        select_resolution(api, conflict["id"], "RELOCATE")
        determination = draft_determination(api, conflict["id"])
        conflicts[key] = conflict
        determinations[key] = determination
    return {
        "project": project,
        "owner": owner,
        "facilities": facilities,
        "conflicts": conflicts,
        "determinations": determinations,
        "readings": readings,
    }


def test_an_untested_record_issues_on_the_record_basis_at_the_full_state_share(api):
    """PRD 3.4: "The variant is chosen first. If any `QL_A` investigation of the
    conflicting facility carries `contradicts_record` true, the variant is
    `FIELD_BASIS`; otherwise it is `RECORD_BASIS`."

    Design: Difficulty/dual_variant_calc/prior_rights_record_basis_versus_field_basis_share
    """
    world = world_determination_drafted(api)
    adjudicator = make_right_of_way_adjudicator_headers()

    validate_success(
        api.submit_prior_rights_for_review(world["determination_id"], adjudicator)
    )
    issued = validate_success(api.issue_prior_rights(world["determination_id"], adjudicator))

    assert issued["evidence_variant"] == "RECORD_BASIS"
    assert issued["final_state_share_pct"] == 100
    assert issued["status"] == "ISSUED"
    assert issued["first_issued_by_user_id"] == ADJUDICATOR_USER_ID

    conflict = read_conflict(api, world["conflict_id"])
    assert conflict["state_share_pct"] == 100
    assert conflict["status"] == "RESPONSIBILITY_SET"


def test_a_field_contradiction_costs_the_record_basis_credit_and_forty_five_more(api):
    """PRD 3.4: "The gap between the variants is deliberately large — a
    pre-acquisition `PRIVATE_EASEMENT` facility of a private owner lands at 100
    under `RECORD_BASIS` and at 55 under `FIELD_BASIS` — because a field
    contradiction means the State is being asked to pay for an interest nobody can
    document where it actually is."

    Design: Difficulty/dual_variant_calc/prior_rights_record_basis_versus_field_basis_share
    """
    world = _twin_easement_corridor(
        api, project_name="SR-14 Widening Section 3", investigations={"b": 60}
    )
    adjudicator = make_right_of_way_adjudicator_headers()
    assert world["readings"]["b"]["contradicts_record"] is True

    issued = {}
    for key in ("a", "b"):
        determination_id = world["determinations"][key]["id"]
        validate_success(api.submit_prior_rights_for_review(determination_id, adjudicator))
        issued[key] = validate_success(
            api.issue_prior_rights(determination_id, adjudicator)
        )

    assert issued["a"]["evidence_variant"] == "RECORD_BASIS"
    assert issued["a"]["final_state_share_pct"] == 100
    assert issued["b"]["evidence_variant"] == "FIELD_BASIS"
    assert issued["b"]["final_state_share_pct"] == 55
    assert (
        issued["a"]["final_state_share_pct"] - issued["b"]["final_state_share_pct"] == 45
    )

    conflict_a = read_conflict(api, world["conflicts"]["a"]["id"])
    conflict_b = read_conflict(api, world["conflicts"]["b"]["id"])
    assert conflict_a["state_share_pct"] == 100
    assert conflict_b["state_share_pct"] == 55
    assert conflict_a["status"] == "RESPONSIBILITY_SET"
    assert conflict_b["status"] == "RESPONSIBILITY_SET"


def test_a_depth_disagreement_of_exactly_six_inches_does_not_contradict_the_record(api):
    """PRD 3.2: "The comparison is strictly greater than the tolerance: a
    disagreement of exactly 6 inches does not contradict the record."

    Design: Difficulty/boundary_precision_check/depth_tolerance_boundary_flips_evidence_variant_at_seven_inches
    """
    world = world_registry(api, project_overrides={"name": "SR-14 Test Hole Program"})
    reading = record_investigation(
        api,
        world["project_id"],
        world["facility_id"],
        quality_level="QL_A",
        method="VACUUM_TEST_HOLE",
        measured_depth_in=54,
        station_at_investigation=120.0,
    )
    assert reading["contradicts_record"] is False
    assert read_investigation(api, reading["id"])["contradicts_record"] is False

    conflict = identify_conflict(api, world["project_id"], world["facility_id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])
    issued = issue_determination(api, determination["id"])

    assert issued["evidence_variant"] == "RECORD_BASIS"
    assert issued["final_state_share_pct"] == 100
    assert read_conflict(api, conflict["id"])["state_share_pct"] == 100


def test_one_inch_past_the_depth_tolerance_flips_the_variant_and_the_share(api):
    """PRD 3.2: "It is set to true when the investigation was taken at quality level
    `QL_A` and the absolute difference between its `measured_depth_in` and the
    facility's `depth_in` of record is greater than 6 inches — the depth tolerance."

    Design: Difficulty/boundary_precision_check/depth_tolerance_boundary_flips_evidence_variant_at_seven_inches
    """
    world = _twin_easement_corridor(
        api,
        project_name="SR-14 Test Hole Program",
        investigations={"a": 54, "b": 55},
    )
    adjudicator = make_right_of_way_adjudicator_headers()

    assert world["readings"]["a"]["contradicts_record"] is False
    assert world["readings"]["b"]["contradicts_record"] is True

    issued = {}
    for key in ("a", "b"):
        determination_id = world["determinations"][key]["id"]
        validate_success(api.submit_prior_rights_for_review(determination_id, adjudicator))
        issued[key] = validate_success(
            api.issue_prior_rights(determination_id, adjudicator)
        )

    assert issued["a"]["evidence_variant"] == "RECORD_BASIS"
    assert issued["a"]["final_state_share_pct"] == 100
    assert issued["b"]["evidence_variant"] == "FIELD_BASIS"
    assert issued["b"]["final_state_share_pct"] == 55

    assert read_conflict(api, world["conflicts"]["a"]["id"])["state_share_pct"] == 100
    assert read_conflict(api, world["conflicts"]["b"]["id"])["state_share_pct"] == 55


def test_revising_a_returned_determination_lands_in_draft_at_a_recomputed_share(api):
    """PRD 3.4: "Revising moves it back to `DRAFT` — the same revise action serves
    both `RETURNED_FOR_REVISION → DRAFT` and `APPEALED → DRAFT` — overwriting
    `claimed_basis` and `narrative` from the request body, each of which may be
    supplied alone, and recomputing `evidence_variant` and
    `provisional_state_share_pct` under the record-basis variant."

    Design: Corner/state_machines/determination_revise_reenters_draft_and_reissues_at_a_new_share
    """
    world = world_determination_drafted(api)
    adjudicator = make_right_of_way_adjudicator_headers()
    drafted = world["determination"]
    assert drafted["provisional_state_share_pct"] == 100
    assert drafted["evidence_variant"] == "RECORD_BASIS"

    validate_success(
        api.submit_prior_rights_for_review(world["determination_id"], adjudicator)
    )
    returned = validate_success(
        api.return_prior_rights_for_revision(
            world["determination_id"],
            {"revision_note": "No recorded instrument attached; the easement claim is unsupported."},
            adjudicator,
        )
    )
    assert returned["status"] == "RETURNED_FOR_REVISION"

    revised = validate_success(
        api.revise_prior_rights(
            world["determination_id"],
            {
                "claimed_basis": "UNDOCUMENTED",
                "narrative": "Claim restated as undocumented occupancy after record search failed.",
            },
            adjudicator,
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["provisional_state_share_pct"] == 95
    assert revised["appeal_round"] == 0

    validate_success(
        api.submit_prior_rights_for_review(world["determination_id"], adjudicator)
    )
    issued = validate_success(api.issue_prior_rights(world["determination_id"], adjudicator))
    assert issued["final_state_share_pct"] == 95
    assert issued["status"] == "ISSUED"
    assert issued["first_issued_by_user_id"] == ADJUDICATOR_USER_ID

    conflict = read_conflict(api, world["conflict_id"])
    assert conflict["state_share_pct"] == 95
    assert conflict["status"] == "RESPONSIBILITY_SET"

    project = read_project(api, world["project_id"])
    assert project["estimated_state_liability_cents"] == 0
    assert read_determination(api, world["determination_id"])["status"] == "ISSUED"
