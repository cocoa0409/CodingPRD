"""Component design lifecycle: seal gates, rejection cycle, revision discipline."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_design_engineer_headers,
    make_engineer,
    make_design,
    submit_design,
    seal_submitted_design,
    setup_confirmed_job,
    design_fresh,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]


def _cycle_setup():
    """Confirmed job + DRAFT design TR-CYC authored by eng1."""
    ns = setup_confirmed_job(job_name="Cycle Job", contract=100000)
    ns.dsg = make_design(ns.job["id"], ns.eng1, component_ref="TR-CYC",
                         lumber_grade="SYP_NO1", plating="P18", quantity_required=4,
                         span_ft=30.0, pitch_degrees=22.62)
    return ns


class TestDesignSealRejectionCycle:
    def test_reject_resets_submitter(self, api):
        """PRD §3.3: "Reviewers may instead reject the design back to `DRAFT`, which
        clears `submitted_by_engineer_id` to null so a fresh submission records a
        fresh submitter".

        Design: Difficulty/non_linear_state_machine/design_seal_rejection_cycle
        """
        ns = _cycle_setup()
        submit_design(ns.dsg["id"], ns.eng1)
        rejected = validate_success(api.transition_design(
            ns.dsg["id"], {"to_state": "DRAFT"}, make_design_engineer_headers(ns.eng2["id"])))
        assert rejected["status"] == "DRAFT"
        assert rejected["submitted_by_engineer_id"] is None, \
            "rejection to DRAFT clears the recorded submitter"

    def test_resubmit_then_first_engineer_seals(self, api):
        """PRD §3.3: "Reviewers may instead reject the design back to `DRAFT`, which
        clears `submitted_by_engineer_id` to null so a fresh submission records a
        fresh submitter" and "A successful seal sets `sealed_by_engineer_id` from
        `X-User-ID` and `sealed_at` to the current logical clock".
        PRD §2.10: "Otherwise the job is `AT_RISK` if any of the following holds:
        any of its production batches is in `QC_FAILED` or `REWORK`; any of its
        delivery loads is in `RETURNED`; or any of its component designs is in
        `SEAL_REQUESTED`. Otherwise the job is `GREEN`."

        Design: Difficulty/non_linear_state_machine/design_seal_rejection_cycle
        """
        ns = _cycle_setup()
        submit_design(ns.dsg["id"], ns.eng1)
        validate_success(api.transition_design(
            ns.dsg["id"], {"to_state": "DRAFT"}, make_design_engineer_headers(ns.eng2["id"])))
        resubmitted = submit_design(ns.dsg["id"], ns.eng2)
        assert resubmitted["submitted_by_engineer_id"] == ns.eng2["id"], \
            "fresh submission records the new submitter"
        sealed = seal_submitted_design(ns.dsg["id"], ns.eng1)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ns.eng1["id"], \
            "segregation is enforced per round: eng1 may seal eng2's submission"
        assert sealed["revision_no"] == 1
        job = job_fresh(ns.job["id"])
        assert job["posture"] == "GREEN", "no SEAL_REQUESTED design remains outstanding"


class TestSealStateBeatsSafety:
    def test_seal_draft_with_expired_license_reports_state_guard(self, api):
        """PRD §3.3: "Requesting a seal on a design that is not in `SEAL_REQUESTED`
        is rejected with `ERR_DESIGN_NOT_AWAITING_SEAL`." PRD §2.7: "Only after all
        six universal layers pass do state-machine guards and business rules run, in
        the orders stated within each §3 workflow."

        Design: Difficulty/priority_pair_validation_conflict/seal_state_beats_safety
        """
        ns = setup_confirmed_job(job_name="Seal Job", contract=100000)
        engx = make_engineer("X", license_expiry="2026-01-01T00:00:00Z")
        dsg = make_design(ns.job["id"], ns.eng1, component_ref="TR-S",
                          lumber_grade="SYP_NO1", plating="P18", quantity_required=2,
                          span_ft=28.0, pitch_degrees=22.62)
        # Design is DRAFT and the engineer's license is expired; the state guard
        # ("not in SEAL_REQUESTED") is the reported rejection.
        resp = api.transition_design(dsg["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(engx["id"]))
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_AWAITING_SEAL)
        assert design_fresh(dsg["id"])["status"] == "DRAFT"

    def test_seal_draft_with_out_of_state_license_reports_state_guard(self, api):
        """PRD §3.3: "Requesting a seal on a design that is not in `SEAL_REQUESTED`
        is rejected with `ERR_DESIGN_NOT_AWAITING_SEAL`." PRD §2.7: "Only after all
        six universal layers pass do state-machine guards and business rules run, in
        the orders stated within each §3 workflow."

        Design: Difficulty/priority_pair_validation_conflict/seal_state_beats_safety
        """
        ns = setup_confirmed_job(job_name="Seal Job 2", contract=100000)
        eng_fl = make_engineer("F", license_state="FL")
        dsg = make_design(ns.job["id"], ns.eng1, component_ref="TR-S2",
                          lumber_grade="SYP_NO1", plating="P18", quantity_required=2,
                          span_ft=28.0, pitch_degrees=22.62)
        # Design is DRAFT and the engineer is licensed in the wrong state; the state
        # guard is still the reported rejection.
        resp = api.transition_design(dsg["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(eng_fl["id"]))
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_AWAITING_SEAL)
        assert design_fresh(dsg["id"])["status"] == "DRAFT"


class TestSealSafetyGates:
    def test_seal_with_expired_license_rejected(self, api):
        """PRD §3.3: "A second engineer then seals it — `SEAL_REQUESTED` to `SEALED` —
        passing four safety gates evaluated in this order: first, the sealing
        engineer's `license_expiry` must be on or after the current logical clock,
        else `ERR_ENGINEER_LICENSE_EXPIRED`". PRD §2.5: "Before any call to the
        clock-setting capability, the logical clock reads exactly 2026-08-01T00:00:00Z".

        Design: Corner/errors/seal_with_expired_license_rejected
        """
        ns = setup_confirmed_job(job_name="Lic Job", contract=100000)
        engx = make_engineer("X", license_expiry="2026-01-01T00:00:00Z")
        engy = make_engineer("Y", license_expiry="2026-08-01T00:00:00Z")
        dsg = make_design(ns.job["id"], ns.eng1, lumber_grade="SYP_NO1", plating="P18",
                          quantity_required=4, span_ft=30.0, pitch_degrees=22.62)
        submit_design(dsg["id"], ns.eng1)
        resp = api.transition_design(dsg["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(engx["id"]))
        validate_error(resp, ApiErrorId.ERR_ENGINEER_LICENSE_EXPIRED)
        # Expiry exactly equal to the clock satisfies "on or after" and seals.
        sealed = seal_submitted_design(dsg["id"], engy)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == engy["id"]

    def test_seal_license_state_mismatch_rejected(self, api):
        """PRD §3.3: "second, the sealing engineer's `license_state` must equal the
        job's `jobsite_state`, else `ERR_ENGINEER_LICENSE_STATE_MISMATCH`".

        Design: Corner/errors/seal_license_state_mismatch_rejected
        """
        ns = setup_confirmed_job(job_name="State Job", contract=100000)
        eng_fl = make_engineer("2F", license_state="FL")
        dsg = make_design(ns.job["id"], ns.eng1, lumber_grade="SYP_NO1", plating="P18",
                          quantity_required=4, span_ft=30.0, pitch_degrees=22.62)
        submit_design(dsg["id"], ns.eng1)
        resp = api.transition_design(dsg["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(eng_fl["id"]))
        validate_error(resp, ApiErrorId.ERR_ENGINEER_LICENSE_STATE_MISMATCH)
        assert design_fresh(dsg["id"])["status"] == "SEAL_REQUESTED"

    def test_seal_authority_insufficient_for_wall_panel(self, api):
        """PRD §3.3: "third, a `WALL_PANEL` design requires the sealer's
        `seal_authority` to be `TRUSS_AND_PANEL`, else `ERR_SEAL_AUTHORITY_INSUFFICIENT`".

        Design: Corner/errors/seal_authority_insufficient_for_wall_panel
        """
        ns = setup_confirmed_job(job_name="Auth Job", contract=100000)
        eng_t = make_engineer("2T", seal_authority="TRUSS_ONLY")
        wp = make_design(ns.job["id"], ns.eng1, component_ref="WP-01",
                         component_type="WALL_PANEL", span_ft=8.0, pitch_degrees=0.0,
                         design_load_psf=20.0, lumber_grade="SYP_NO1", plating="P18",
                         quantity_required=6)
        submit_design(wp["id"], ns.eng1)
        tr = make_design(ns.job["id"], ns.eng1, component_ref="TR-01",
                         lumber_grade="SYP_NO1", plating="P18", quantity_required=4,
                         span_ft=30.0, pitch_degrees=22.62)
        submit_design(tr["id"], ns.eng1)
        resp = api.transition_design(wp["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(eng_t["id"]))
        validate_error(resp, ApiErrorId.ERR_SEAL_AUTHORITY_INSUFFICIENT)
        assert design_fresh(wp["id"])["status"] == "SEAL_REQUESTED"
        sealed = seal_submitted_design(tr["id"], eng_t)
        assert sealed["status"] == "SEALED", "TRUSS_ONLY suffices for a ROOF_TRUSS"

    def test_sealer_must_differ_from_submitter(self, api):
        """PRD §3.3: "fourth, segregation of duties requires the sealing engineer's id
        to differ from `submitted_by_engineer_id`, else
        `ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER`".

        Design: Corner/errors/sealer_must_differ_from_submitter
        """
        ns = setup_confirmed_job(job_name="SoD Job", contract=100000)
        dsg = make_design(ns.job["id"], ns.eng1, lumber_grade="SYP_NO1", plating="P18",
                          quantity_required=4, span_ft=30.0, pitch_degrees=22.62)
        submit_design(dsg["id"], ns.eng1)
        resp = api.transition_design(dsg["id"], {"to_state": "SEALED"},
                                     make_design_engineer_headers(ns.eng1["id"]))
        validate_error(resp, ApiErrorId.ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER)
        data = design_fresh(dsg["id"])
        assert data["status"] == "SEAL_REQUESTED"
        assert data["sealed_by_engineer_id"] is None


class TestComponentRefDiscipline:
    def test_duplicate_component_ref_and_broken_revision_chain(self, api):
        """PRD §3.3: "At most one design per (job, `component_ref`) pair may sit in
        `DRAFT` or `SEAL_REQUESTED` at a time, and creating a revision while a
        `SEALED` design exists for the same pair requires `supersedes_design_id`
        naming that current sealed revision. Violating either rule is rejected with
        `ERR_DUPLICATE_COMPONENT_REF` (HTTP 409); supplying a `supersedes_design_id`
        when no `SEALED` revision exists for that `component_ref` is instead rejected
        with `ERR_REVISION_CHAIN_BROKEN` (HTTP 422)."

        Design: Corner/validations/duplicate_component_ref_and_broken_revision_chain
        """
        ns = setup_confirmed_job(job_name="Dup Job", contract=100000)
        dsg = make_design(ns.job["id"], ns.eng1, lumber_grade="SYP_NO1", plating="P18",
                          quantity_required=4, span_ft=30.0, pitch_degrees=22.62)
        version_before = job_fresh(ns.job["id"])["version"]

        # Second open DRAFT for the same (job, component_ref).
        resp1 = api.create_design(
            ns.job["id"],
            {"component_ref": "TR-01", "component_type": "ROOF_TRUSS", "span_ft": 30.0,
             "pitch_degrees": 22.62, "design_load_psf": 40.0, "lumber_grade": "SYP_NO1",
             "plating": "P18", "quantity_required": 4,
             "expected_job_version": job_fresh(ns.job["id"])["version"]},
            make_design_engineer_headers(ns.eng1["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_DUPLICATE_COMPONENT_REF)

        # supersedes_design_id pointing at a DRAFT (no SEALED revision exists).
        resp2 = api.create_design(
            ns.job["id"],
            {"component_ref": "TR-99", "component_type": "ROOF_TRUSS", "span_ft": 30.0,
             "pitch_degrees": 22.62, "design_load_psf": 40.0, "lumber_grade": "SYP_NO1",
             "plating": "P18", "quantity_required": 4, "supersedes_design_id": dsg["id"],
             "expected_job_version": job_fresh(ns.job["id"])["version"]},
            make_design_engineer_headers(ns.eng1["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_REVISION_CHAIN_BROKEN)

        assert job_fresh(ns.job["id"])["version"] == version_before, \
            "rejected creates never mutate the job"


class TestDesignTerminalLockdown:
    def test_void_design_rejects_further_transitions(self, api):
        """PRD §3.3: "a `DRAFT` design may be abandoned to `VOID`" and "any other
        transition request on a design is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/terminal_lockdown_design_void_and_slot_cancelled
        """
        ns = _cycle_setup()
        voided = validate_success(api.transition_design(
            ns.dsg["id"], {"to_state": "VOID"}, make_design_engineer_headers(ns.eng1["id"])))
        assert voided["status"] == "VOID"
        resp = api.transition_design(ns.dsg["id"], {"to_state": "SEAL_REQUESTED"},
                                     make_design_engineer_headers(ns.eng1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert design_fresh(ns.dsg["id"])["status"] == "VOID", "VOID is terminal"
