"""Validation precedence, resource-overlap constraints, boundary precision,
duplicate room labels, and cross-entity placement validity.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_claim,
    create_job,
    create_unit,
    create_chamber_payload,
    create_placement_payload,
    create_reading_payload,
    create_estimate_payload,
    setup_dispatched_job,
    setup_job_with_chamber,
    add_contents,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ESTIMATOR,
    ADJUSTER,
    ADMIN,
    _place_units,
)
from test_helpers.test_users import make_technician_headers


# ===========================================================================
# Priority-pair conflicts (Difficulty/priority_pair_validation_conflict)
# ===========================================================================
class TestValidationPrecedence:
    def test_dispatch_state_beats_certification(self):
        """PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`.
        Business-specific safety, referential, fiscal, and concurrency checks
        (priorities 7 and beyond) are evaluated after these six and are described
        alongside the workflows they guard in Section 3."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_state_vs_safety_priority
        """
        claim = create_claim()
        good = get_success_data(
            api.create_technician({"full_name": "Good", "certification": "WRT"}, ADMIN)
        )
        mold = get_success_data(
            api.create_technician({"full_name": "Mold", "certification": "AMRT"}, ADMIN)
        )
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        # Dispatch once -> job leaves FNOL (now DISPATCHED).
        get_success_data(api.dispatch_job(job["id"], {"technician_id": good["id"]}, DISPATCHER))
        # Second dispatch: state-invalid (not FNOL) AND cert-mismatch (AMRT on WATER).
        resp = api.dispatch_job(job["id"], {"technician_id": mold["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_state_beats_over_coverage(self):
        """PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`.
        Business-specific safety, referential, fiscal, and concurrency checks
        (priorities 7 and beyond) are evaluated after these six".

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_fiscal_priority
        """
        claim = create_claim(coverage_limit_cents=30000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        v1 = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        e1 = get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], v1, estimated_drying_days=1,
                                        line_items=[{"qty": 5, "unit_price_cents": 10000}]),
                ESTIMATOR,
            )
        )
        # New DRAFT supersedes E1; E1 -> SUPERSEDED.
        v2 = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], v2, estimated_drying_days=1,
                                        line_items=[{"qty": 5, "unit_price_cents": 10000}]),
                ESTIMATOR,
            )
        )
        assert get_success_data(api.get_estimate(e1["id"], ESTIMATOR))["status"] == "SUPERSEDED"
        # Approving SUPERSEDED E1 (also over the 30000 limit at 50000): state wins.
        resp = api.approve_estimate(e1["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_dispatch_state_conflict_leaves_job_unchanged(self):
        """PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`.
        Business-specific safety, referential, fiscal, and concurrency checks
        (priorities 7 and beyond) are evaluated after these six".

        Design: Difficulty/priority_pair_validation_conflict/dispatch_state_vs_safety_priority
        """
        claim = create_claim()
        good = get_success_data(
            api.create_technician({"full_name": "Good", "certification": "WRT"}, ADMIN)
        )
        mold = get_success_data(
            api.create_technician({"full_name": "Mold", "certification": "AMRT"}, ADMIN)
        )
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        first = get_success_data(
            api.dispatch_job(job["id"], {"technician_id": good["id"]}, DISPATCHER)
        )
        # The rejected second dispatch (state beats cert) must not re-assign.
        resp = api.dispatch_job(job["id"], {"technician_id": mold["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_success_data(api.get_job(job["id"], DISPATCHER))
        assert after["status"] == "DISPATCHED"
        assert after["assigned_technician_id"] == good["id"]

    def test_approve_state_conflict_does_not_settle_claim(self):
        """PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`.
        Business-specific safety, referential, fiscal, and concurrency checks
        (priorities 7 and beyond) are evaluated after these six".

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_fiscal_priority
        """
        claim = create_claim(coverage_limit_cents=30000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        v1 = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        e1 = get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], v1, estimated_drying_days=1,
                                        line_items=[{"qty": 5, "unit_price_cents": 10000}]),
                ESTIMATOR,
            )
        )
        v2 = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        get_success_data(
            api.create_estimate(
                create_estimate_payload(job["id"], v2, estimated_drying_days=1,
                                        line_items=[{"qty": 5, "unit_price_cents": 10000}]),
                ESTIMATOR,
            )
        )
        resp = api.approve_estimate(e1["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        # Claim must remain OPEN — the rejected approval settled nothing.
        assert get_success_data(api.get_claim(claim["id"], ADJUSTER))["status"] == "OPEN"


# ===========================================================================
# Resource temporal overlap (Difficulty/resource_temporal_overlap)
# ===========================================================================
class TestResourceOverlap:
    def test_single_occupancy_collision(self):
        """PRD §3.4: "The placement is valid only when the chosen equipment unit's
        `status` is `AVAILABLE` and the chamber belongs to the same job named by
        the placement's `job_id`; a unit that is already deployed, or a chamber
        that belongs to a different job, is rejected with
        `ERR_EQUIPMENT_NOT_AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_unit_single_occupancy_collision
        """
        ctx = setup_dispatched_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 500000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        ch1 = get_success_data(
            api.create_chamber(create_chamber_payload(job_id, room_label="R1"), tech_hdr)
        )
        ch2 = get_success_data(
            api.create_chamber(create_chamber_payload(job_id, room_label="R2"), tech_hdr)
        )
        unit = create_unit(asset_tag="OCC-AM", kind="AIR_MOVER")
        pl1 = get_success_data(
            api.create_placement(create_placement_payload(job_id, ch1["id"], unit["id"]), tech_hdr)
        )
        deployed = get_success_data(api.get_equipment_unit(unit["id"], DISPATCHER))
        assert deployed["status"] == "DEPLOYED"
        assert deployed["active_placement_id"] == pl1["id"]
        # Second placement of the same (now DEPLOYED) unit collides.
        resp = api.create_placement(
            create_placement_payload(job_id, ch2["id"], unit["id"]), tech_hdr
        )
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE.value)

    def test_collision_leaves_original_occupation_intact(self):
        """PRD §3.4: "As a cross-entity side effect, the deployed unit's `status`
        flips to `DEPLOYED` and its `active_placement_id` is set to this
        placement's id."
        PRD §3.4: "a unit that is already deployed, or a chamber that belongs to a
        different job, is rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_unit_single_occupancy_collision
        """
        ctx = setup_dispatched_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 500000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        ch1 = get_success_data(
            api.create_chamber(create_chamber_payload(job_id, room_label="R1"), tech_hdr)
        )
        ch2 = get_success_data(
            api.create_chamber(create_chamber_payload(job_id, room_label="R2"), tech_hdr)
        )
        unit = create_unit(asset_tag="OCC2-AM", kind="AIR_MOVER")
        pl1 = get_success_data(
            api.create_placement(create_placement_payload(job_id, ch1["id"], unit["id"]), tech_hdr)
        )
        api.create_placement(create_placement_payload(job_id, ch2["id"], unit["id"]), tech_hdr)
        # The first occupation is unaffected by the rejected collision.
        still = get_success_data(api.get_equipment_unit(unit["id"], DISPATCHER))
        assert still["status"] == "DEPLOYED"
        assert still["active_placement_id"] == pl1["id"]
        assert get_success_data(api.get_placement(pl1["id"], DISPATCHER))["status"] == "ACTIVE"

    def test_aggregate_capacity_undersized_blocks_monitoring(self):
        """PRD §3.4: "every `OPEN` chamber must already have `ACTIVE` placements
        totaling at least its `air_movers_required` count of `AIR_MOVER` units and
        at least its `dehumidifiers_required` count of `DEHUMIDIFIER` units. If any
        `OPEN` chamber is under-equipped against either threshold, the transition
        is rejected with `ERR_EQUIPMENT_UNDERSIZED`."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity_undersized
        """
        ctx = setup_dispatched_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000},
                                   job_overrides={"water_category": 2, "water_class": 2})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        chamber = get_success_data(
            api.create_chamber(
                create_chamber_payload(job_id, room_label="R1", floor_area_sqft=700,
                                       wet_wall_linear_ft=40, dehu_ppd_rating=70,
                                       dry_standard_pct=12),
                tech_hdr,
            )
        )
        assert chamber["air_movers_required"] == 13
        # Place only 1 air mover (needs 13) and 0 dehus.
        _place_units(job_id, chamber["id"], tech_hdr, n_air=1, n_dehu=0, tag_prefix="UND")
        get_success_data(api.start_mitigation(job_id, tech_hdr))
        resp = api.begin_monitoring(job_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNDERSIZED.value)

    def test_fully_equipped_chamber_passes_monitoring_gate(self):
        """PRD §3.4: "every `OPEN` chamber must already have `ACTIVE` placements
        totaling at least its `air_movers_required` count of `AIR_MOVER` units and
        at least its `dehumidifiers_required` count of `DEHUMIDIFIER` units."
        PRD §3.4: "The job advances from mitigation into daily monitoring when a
        `Technician` begins monitoring, moving it `MITIGATION → MONITORING`."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity_undersized
        """
        ctx = setup_dispatched_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000},
                                   job_overrides={"water_category": 1, "water_class": 1})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        chamber = get_success_data(
            api.create_chamber(
                create_chamber_payload(job_id, room_label="R1", floor_area_sqft=100,
                                       wet_wall_linear_ft=0, dehu_ppd_rating=70,
                                       dry_standard_pct=12),
                tech_hdr,
            )
        )
        # class-1 100 sqft -> requires 1 AM, 1 DEHU; place exactly those.
        assert chamber["air_movers_required"] == 1
        assert chamber["dehumidifiers_required"] == 1
        _place_units(job_id, chamber["id"], tech_hdr, n_air=1, n_dehu=1, tag_prefix="SAT")
        get_success_data(api.start_mitigation(job_id, tech_hdr))
        data = validate_success(api.begin_monitoring(job_id, tech_hdr), 200)
        assert data["status"] == "MONITORING"


# ===========================================================================
# Boundary precision (Difficulty/boundary_precision_check)
# ===========================================================================
class TestBoundaryPrecision:
    def test_dry_threshold_inclusive_at_boundary(self):
        """PRD §3.4: "The chamber's `is_dry` flag is true when that latest moisture
        content is **less than or equal to** the chamber's `dry_standard_pct` plus
        a tolerance of 4 percentage points; the boundary is inclusive, so a latest
        reading exactly at the dry standard plus 4 counts as dry."

        Design: Difficulty/boundary_precision_check/dry_threshold_inclusive_boundary
        """
        ctx = setup_job_with_chamber(certification="WRT",
                                     chamber_overrides={"room_label": "R1",
                                                        "dry_standard_pct": 12})
        ch1_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # mc=16 == 12+4 -> inclusive -> dry
        get_success_data(
            api.create_reading(ch1_id,
                               create_reading_payload(temp_f=78, relative_humidity_pct=55,
                                                      moisture_content_pct=16), tech_hdr)
        )
        ch1 = get_success_data(api.get_chamber(ch1_id, tech_hdr))
        assert ch1["is_dry"] is True

    def test_dry_threshold_above_boundary_not_dry(self):
        """PRD §3.4: "The chamber's `is_dry` flag is true when that latest moisture
        content is **less than or equal to** the chamber's `dry_standard_pct` plus
        a tolerance of 4 percentage points; the boundary is inclusive, so a latest
        reading exactly at the dry standard plus 4 counts as dry."

        Design: Difficulty/boundary_precision_check/dry_threshold_inclusive_boundary
        """
        ctx = setup_job_with_chamber(certification="WRT",
                                     chamber_overrides={"room_label": "R2",
                                                        "dry_standard_pct": 12})
        ch2_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # mc=17 > 12+4 -> not dry
        get_success_data(
            api.create_reading(ch2_id,
                               create_reading_payload(temp_f=78, relative_humidity_pct=55,
                                                      moisture_content_pct=17), tech_hdr)
        )
        ch2 = get_success_data(api.get_chamber(ch2_id, tech_hdr))
        assert ch2["is_dry"] is False

    def test_waterfall_empty_included_set_allocates_zero(self):
        """PRD §3.6: "Then walk the job's contents items whose status is
        `PACKED_OUT` or `STORED`, in `created_at` ascending order (never by id),
        and for each item allocate the smaller of the remaining pool and the
        item's `declared_value_cents` into that item's `allocated_value_cents`".

        Design: Difficulty/boundary_precision_check/contents_waterfall_empty_included_set
        """
        claim = create_claim(coverage_limit_cents=100000, deductible_cents=0)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        tech_hdr = make_technician_headers("tech-x")
        item = add_contents(job["id"], tech_hdr, "Sofa", 50000)
        # Return it so the included set {PACKED_OUT, STORED} is empty.
        get_success_data(api.return_contents(item["id"], tech_hdr))
        assert get_success_data(api.get_contents(item["id"], tech_hdr))["status"] == "RETURNED"
        resp = api.value_contents(job["id"], ADJUSTER)
        data = validate_success(resp, 200)
        assert data["allocated_total_cents"] == 0
        assert get_success_data(api.get_contents(item["id"], tech_hdr))["allocated_value_cents"] == 0

    def test_waterfall_no_contents_items_allocates_zero(self):
        """PRD §3.6: "Then walk the job's contents items whose status is
        `PACKED_OUT` or `STORED`, in `created_at` ascending order (never by id),
        and for each item allocate the smaller of the remaining pool and the
        item's `declared_value_cents` into that item's `allocated_value_cents`,
        decrementing the remaining pool by the amount allocated."

        Design: Difficulty/boundary_precision_check/contents_waterfall_empty_included_set
        """
        claim = create_claim(coverage_limit_cents=100000, deductible_cents=0)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        # No contents packed out at all -> the included set is empty.
        resp = api.value_contents(job["id"], ADJUSTER)
        data = validate_success(resp, 200)
        assert data["allocated_total_cents"] == 0


# ===========================================================================
# Constraint validations (Corner/validations)
# ===========================================================================
class TestConstraints:
    def test_duplicate_room_label_rejected(self):
        """PRD §3.3: "The `room_label` must be unique among the job's chambers that
        are not `DECOMMISSIONED`; a collision is rejected with
        `ERR_DUPLICATE_ROOM_LABEL`."

        Design: Corner/validations/duplicate_room_label_rejected
        """
        ctx = setup_job_with_chamber(certification="WRT",
                                     chamber_overrides={"room_label": "R1"})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        resp = api.create_chamber(
            create_chamber_payload(job_id, room_label="R1", floor_area_sqft=200),
            tech_hdr,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROOM_LABEL.value)

    def test_place_unit_chamber_job_mismatch_rejected(self):
        """PRD §3.4: "the chamber belongs to the same job named by the placement's
        `job_id`; a unit that is already deployed, or a chamber that belongs to a
        different job, is rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`."

        Design: Corner/validations/place_unavailable_unit_rejected
        """
        claim = create_claim()
        tech = get_success_data(
            api.create_technician({"full_name": "T", "certification": "ASD"}, ADMIN)
        )
        unit = create_unit(asset_tag="MM-AM", kind="AIR_MOVER")
        j1 = create_job(claim["id"], loss_type="WATER",
                        water_category=1, water_class=1, property_address="J1")
        j2 = create_job(claim["id"], loss_type="WATER",
                        water_category=1, water_class=1, property_address="J2")
        get_success_data(api.dispatch_job(j1["id"], {"technician_id": tech["id"]}, DISPATCHER))
        tech_hdr = make_technician_headers(tech["id"])
        c2 = get_success_data(
            api.create_chamber(create_chamber_payload(j2["id"], room_label="C2"), tech_hdr)
        )
        # placement job_id=J1 but chamber_id belongs to J2 -> mismatch
        resp = api.create_placement(
            create_placement_payload(j1["id"], c2["id"], unit["id"]), tech_hdr
        )
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE.value)
