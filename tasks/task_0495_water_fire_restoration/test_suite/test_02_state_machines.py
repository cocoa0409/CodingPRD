"""State machines: chamber OPEN<->DRIED cycling, job branch+revert,
dispatch certification gate, mitigation/monitoring/completion preconditions,
contents chain-of-custody, drying_status bubble-up.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_chamber_payload,
    create_reading_payload,
    create_contents_payload,
    setup_dispatched_job,
    setup_job_with_chamber,
    setup_monitoring_job,
    setup_completion_ready,
    create_claim,
    create_job,
    create_technician,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ADJUSTER,
    _place_units,
)


# ===========================================================================
# Chamber cyclic OPEN <-> DRIED (Difficulty/non_linear_state_machine)
# ===========================================================================
class TestChamberCycling:
    def test_dry_reading_drives_open_to_dried(self):
        """PRD §3.4: "an `OPEN` chamber whose reading makes it dry moves to
        `DRIED`, and a `DRIED` chamber whose new reading makes it no longer dry
        reverts to `OPEN` (a re-wetting reading reopens a previously dried
        chamber)."
        PRD §3.4: "The chamber's `is_dry` flag is true when that latest moisture
        content is **less than or equal to** the chamber's `dry_standard_pct` plus
        a tolerance of 4 percentage points; the boundary is inclusive, so a latest
        reading exactly at the dry standard plus 4 counts as dry."

        Design: Difficulty/non_linear_state_machine/chamber_cyclic_open_dried_open
        """
        ctx = setup_job_with_chamber(certification="WRT")
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # mc=16 <= 12+4 -> dry
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=78, relative_humidity_pct=55,
                                                      moisture_content_pct=16), tech_hdr)
        )
        ch = get_success_data(api.get_chamber(ch_id, tech_hdr))
        assert ch["status"] == "DRIED"
        assert ch["is_dry"] is True

    def test_rewetting_reading_reverts_dried_to_open(self):
        """PRD §3.4: "a `DRIED` chamber whose new reading makes it no longer dry
        reverts to `OPEN` (a re-wetting reading reopens a previously dried
        chamber). These transitions are cyclic and driven entirely by readings,
        with no separate client request."

        Design: Difficulty/non_linear_state_machine/chamber_cyclic_open_dried_open
        """
        ctx = setup_job_with_chamber(certification="WRT")
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=78, relative_humidity_pct=55,
                                                      moisture_content_pct=16), tech_hdr)
        )
        assert get_success_data(api.get_chamber(ch_id, tech_hdr))["status"] == "DRIED"
        # re-wet: mc=20 > 12+4 -> OPEN again
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=85, relative_humidity_pct=60,
                                                      moisture_content_pct=20), tech_hdr)
        )
        ch = get_success_data(api.get_chamber(ch_id, tech_hdr))
        assert ch["status"] == "OPEN"
        assert ch["is_dry"] is False


# ===========================================================================
# Job branch-with-revert MONITORING <-> MITIGATION
# (Difficulty/non_linear_state_machine)
# ===========================================================================
class TestJobRevertLoop:
    def test_reopen_mitigation_reverts_monitoring(self):
        """PRD §3.7: "A `Technician` reopens mitigation on a `MONITORING` job,
        reverting it `MONITORING → MITIGATION` to add drying capacity. This is
        only meaningful when there is still wet work to do: at least one
        non-`DECOMMISSIONED` chamber must have `is_dry` false, otherwise the reopen
        is rejected with `ERR_NOTHING_TO_REOPEN`."

        Design: Difficulty/non_linear_state_machine/job_monitoring_revert_to_mitigation
        """
        # MONITORING job with chamber still wet (no dry reading logged)
        ctx = setup_monitoring_job(certification="WRT")
        job_id = ctx["job"]["id"]
        resp = api.reopen_mitigation(job_id, ctx["tech_hdr"])
        data = validate_success(resp, 200)
        assert data["status"] == "MITIGATION"

    def test_begin_monitoring_resumes_after_reopen(self):
        """PRD §3.7: "The loop `MONITORING → MITIGATION → MONITORING` lets the crew
        add chambers or placements before resuming monitoring."
        PRD §3.4: "The job advances from mitigation into daily monitoring when a
        `Technician` begins monitoring, moving it `MITIGATION → MONITORING`."

        Design: Difficulty/non_linear_state_machine/job_monitoring_revert_to_mitigation
        """
        ctx = setup_monitoring_job(certification="WRT")
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(api.reopen_mitigation(job_id, tech_hdr))
        # equipment still satisfies the single chamber's required counts
        resp = api.begin_monitoring(job_id, tech_hdr)
        data = validate_success(resp, 200)
        assert data["status"] == "MONITORING"


# ===========================================================================
# Depth-2 cascade: dry reading -> chamber DRIED -> job DRY_STANDARD_MET
# (Difficulty/transitive_cascade)
# ===========================================================================
class TestReadingBubbleUp:
    def test_dry_reading_sets_chamber_dried(self):
        """PRD §2.5: "A chamber may auto-transition between `OPEN` and `DRIED` as a
        direct consequence, with no separate client request."

        Design: Difficulty/transitive_cascade/reading_depth2_chamber_dried_job_drystandard
        """
        ctx = setup_monitoring_job(certification="ASD")
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        ch = get_success_data(api.get_chamber(ch_id, tech_hdr))
        assert ch["status"] == "DRIED"

    def test_chamber_dried_bubbles_to_job_dry_standard_met(self):
        """PRD §3.4: "when every non-`DECOMMISSIONED` chamber on the job is
        `DRIED`, the job's `drying_status` becomes `DRY_STANDARD_MET`".

        Design: Difficulty/transitive_cascade/reading_depth2_chamber_dried_job_drystandard
        """
        ctx = setup_monitoring_job(certification="ASD")
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(
            api.create_reading(ch_id,
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        job = get_success_data(api.get_job(job_id, DISPATCHER))
        assert job["drying_status"] == "DRY_STANDARD_MET"


# ===========================================================================
# Dispatch certification gate (Corner/state_machines)
# ===========================================================================
class TestDispatchGate:
    def test_inactive_technician_unavailable(self):
        """PRD §3.2: "the referenced technician must exist and be available —
        `active` must be true — otherwise the dispatch is rejected with
        `ERR_TECHNICIAN_UNAVAILABLE`."

        Design: Corner/state_machines/error_dispatch_inactive_technician_unavailable
        """
        from test_helpers.fixtures import ADMIN
        claim = create_claim()
        tech = get_success_data(
            api.create_technician(
                {"full_name": "Inactive", "certification": "WRT", "active": False}, ADMIN
            )
        )
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        resp = api.dispatch_job(job["id"], {"technician_id": tech["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE.value)

    def test_certification_mismatch_on_water_job(self):
        """PRD §3.2: "if the job's `loss_type` is `WATER`, the technician's
        `certification` must be `WRT` or `ASD`; if the `loss_type` is `FIRE` or
        `SMOKE`, **or** the job's `antimicrobial_required` flag is true, the
        technician's `certification` must be `AMRT` or `ASD`. A certification that
        fails to match is rejected with `ERR_CERTIFICATION_MISMATCH`."

        Design: Corner/state_machines/error_dispatch_certification_mismatch
        """
        from test_helpers.fixtures import ADMIN
        claim = create_claim()
        tech = get_success_data(
            api.create_technician({"full_name": "Mold", "certification": "AMRT"}, ADMIN)
        )
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        resp = api.dispatch_job(job["id"], {"technician_id": tech["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISMATCH.value)


# ===========================================================================
# Mitigation / monitoring / completion preconditions (Corner/state_machines)
# ===========================================================================
class TestLifecyclePreconditions:
    def test_start_mitigation_without_chambers_rejected(self):
        """PRD §3.3: "This requires that at least one non-`DECOMMISSIONED` drying
        chamber already exists on the job; a start-mitigation attempt against a job
        with zero such chambers is rejected with `ERR_NO_CHAMBERS`."

        Design: Corner/state_machines/start_mitigation_without_chambers_returns_no_chambers
        """
        ctx = setup_dispatched_job(certification="WRT")
        resp = api.start_mitigation(ctx["job"]["id"], ctx["tech_hdr"])
        validate_error(resp, ApiErrorId.ERR_NO_CHAMBERS.value)
        job = get_success_data(api.get_job(ctx["job"]["id"], DISPATCHER))
        assert job["status"] == "DISPATCHED"

    def test_complete_without_approved_estimate_rejected(self):
        """PRD §3.7: "And an `APPROVED` scope estimate must exist for the job, else
        `ERR_NO_APPROVED_ESTIMATE`."

        Design: Corner/state_machines/complete_without_approved_estimate_returns_no_approved_estimate
        """
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # dry the chamber, remove all placements, but DO NOT create any estimate
        get_success_data(
            api.create_reading(ctx["chamber"]["id"],
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        get_success_data(api.remove_placement(ctx["air_placement"]["id"], tech_hdr))
        get_success_data(api.remove_placement(ctx["dehu_placement"]["id"], tech_hdr))
        resp = api.complete_job(job_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_ESTIMATE.value)

    def test_complete_with_active_placement_rejected(self):
        """PRD §3.7: "No equipment placement on the job may still be `ACTIVE`; a
        lingering active placement is rejected with `ERR_EQUIPMENT_STILL_DEPLOYED`."

        Design: Corner/state_machines/complete_with_active_placement_returns_equipment_still_deployed
        """
        from test_helpers.fixtures import create_and_approve_estimate
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        create_and_approve_estimate(job_id)
        # dry the chamber but leave placements ACTIVE
        get_success_data(
            api.create_reading(ctx["chamber"]["id"],
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        resp = api.complete_job(job_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_STILL_DEPLOYED.value)

    def test_reopen_mitigation_all_dry_rejected(self):
        """PRD §3.7: "at least one non-`DECOMMISSIONED` chamber must have `is_dry`
        false, otherwise the reopen is rejected with `ERR_NOTHING_TO_REOPEN`."

        Design: Corner/state_machines/reopen_mitigation_when_all_dry_returns_nothing_to_reopen
        """
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        get_success_data(
            api.create_reading(ctx["chamber"]["id"],
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        assert get_success_data(api.get_chamber(ctx["chamber"]["id"], tech_hdr))["status"] == "DRIED"
        resp = api.reopen_mitigation(job_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_REOPEN.value)

    def test_decommission_chamber_with_active_equipment_rejected(self):
        """PRD §3.3: "but only if no `ACTIVE` placement still references it; an
        attempt to decommission a chamber that still holds equipment is rejected
        with `ERR_CHAMBER_HAS_EQUIPMENT`."

        Design: Corner/state_machines/decommission_chamber_with_active_equipment_returns_chamber_has_equipment
        """
        ctx = setup_job_with_chamber(certification="ASD")
        job_id = ctx["job"]["id"]
        ch_id = ctx["chamber"]["id"]
        tech_hdr = ctx["tech_hdr"]
        _place_units(job_id, ch_id, tech_hdr, n_air=1, n_dehu=0, tag_prefix="DCM")
        resp = api.decommission_chamber(ch_id, tech_hdr)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_HAS_EQUIPMENT.value)
        assert get_success_data(api.get_chamber(ch_id, tech_hdr))["status"] == "OPEN"


# ===========================================================================
# Terminal-state lockdown and invalid transitions (Corner/state_machines)
# ===========================================================================
class TestTerminalAndInvalid:
    def test_cancel_completed_job_rejected(self):
        """PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_from_completed_terminal_returns_invalid_state
        """
        from test_helpers.fixtures import setup_completed_job
        ctx = setup_completed_job(claim_overrides={"coverage_limit_cents": 9_000_000})
        assert ctx["job"]["status"] == "COMPLETED"
        assert ctx["job"]["warranty_expires_on"] is not None
        resp = api.cancel_job(ctx["job"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_store_already_stored_item_rejected(self):
        """PRD §3.6: "a `PACKED_OUT` item can be moved into storage
        (`PACKED_OUT → STORED`)".
        PRD §2.10: "(6) state validity — the target resource must be in a state
        that admits the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/contents_store_then_store_again_returns_invalid_state
        """
        ctx = setup_job_with_chamber(certification="WRT")
        item = get_success_data(
            api.create_contents(
                create_contents_payload(ctx["job"]["id"], description="Lamp",
                                        declared_value_cents=5000),
                ctx["tech_hdr"],
            )
        )
        get_success_data(api.store_contents(item["id"], ctx["tech_hdr"]))
        resp = api.store_contents(item["id"], ctx["tech_hdr"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Completion happy path + side effects (Corner/state_machines)
# ===========================================================================
class TestCompletion:
    def test_complete_happy_path(self):
        """PRD §3.7: "On successful completion the job's `status` becomes
        `COMPLETED`, `completed_at` is stamped with the logical clock's current
        instant, and `warranty_expires_on` is set to `completed_at` plus the
        warranty window."
        PRD §3.7: "The job's `drying_status` must be `DRY_STANDARD_MET` —
        equivalently, every non-`DECOMMISSIONED` chamber must be `DRIED`".

        Design: Corner/state_machines/chamber_dried_complete_happy_path
        """
        ctx = setup_completion_ready(claim_overrides={"coverage_limit_cents": 9_000_000})
        resp = api.complete_job(ctx["job"]["id"], ctx["tech_hdr"])
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"
        assert data["drying_status"] == "DRY_STANDARD_MET"

    def test_complete_returns_stored_contents_and_stamps_warranty(self):
        """PRD §3.7: "As a finalizing side effect, every contents item still in
        `STORED` on the job is moved to `RETURNED`."
        PRD §3.7: "`warranty_expires_on` is set to `completed_at` plus the warranty
        window."

        Design: Corner/state_machines/contents_store_then_return_then_complete_cascade
        """
        from test_helpers.fixtures import set_clock, add_contents
        set_clock("2026-03-01T00:00:00Z")
        ctx = setup_monitoring_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 9_000_000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        item = add_contents(job_id, tech_hdr, "Painting", 9000)
        get_success_data(api.store_contents(item["id"], tech_hdr))
        from test_helpers.fixtures import create_and_approve_estimate
        create_and_approve_estimate(job_id)
        get_success_data(
            api.create_reading(ctx["chamber"]["id"],
                               create_reading_payload(temp_f=72, relative_humidity_pct=38,
                                                      moisture_content_pct=15), tech_hdr)
        )
        get_success_data(api.remove_placement(ctx["air_placement"]["id"], tech_hdr))
        get_success_data(api.remove_placement(ctx["dehu_placement"]["id"], tech_hdr))
        resp = api.complete_job(job_id, tech_hdr)
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"
        assert data["warranty_expires_on"] is not None
        returned = get_success_data(api.get_contents(item["id"], tech_hdr))
        assert returned["status"] == "RETURNED"
