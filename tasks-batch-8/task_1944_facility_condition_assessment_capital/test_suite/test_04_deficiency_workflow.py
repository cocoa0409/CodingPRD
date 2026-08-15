"""Deficiency priority scoring, the dual-axis remediation/verification
lifecycle, defer/reopen conservation, and finding-stream guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_deficiency,
    create_deficiency,
    create_deficiency_payload,
    get_asset_system,
    get_deficiency,
    get_facility,
    list_system_snapshots,
    setup_facility_with_system,
    setup_system_with_deficiency,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CONSULTANT, MANAGER


class TestPriorityScore:
    @pytest.mark.parametrize(
        "flags,expected",
        [
            ({}, 3.00),                                             # 0.6*3 + 0.4*3
            ({"is_code_violation": True}, 13.00),                   # +10 branch
            ({"is_accessibility_violation": True}, 8.00),           # +5 branch
            ({"is_code_violation": True,
              "is_accessibility_violation": True}, 18.00),          # branches compose
        ],
        ids=["no-flags", "code-only", "accessibility-only", "both-flags"],
    )
    def test_priority_score_flag_combinations(self, api, flags, expected):
        """PRD §3.4: "Every deficiency receives a computed `priority_score` at
        creation: the severity multiplied by a weight of 0.6, plus the urgency
        multiplied by a weight of 0.4, plus a bonus of 10 when the finding is a
        code violation, plus a further bonus of 5 when it is an accessibility
        violation — the total rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/priority_score_weighted_multi_input
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "PLUMBING", "name": "Domestic Water",
             "install_year": 2015, "design_life_years": 20,
             "replacement_cost_cents": 30000000, "condition_rating": 3})
        payload = create_deficiency_payload(
            system["id"], description="combo", cost_estimate_cents=1000000,
            severity=3, urgency=3, recommended_year=2027, **flags)
        deficiency = validate_success(api.create_deficiency(payload,
                                                            CONSULTANT), 201)
        assert_deficiency(deficiency)
        assert deficiency["priority_score"] == pytest.approx(expected,
                                                             abs=1e-9)

    @pytest.mark.parametrize(
        "severity,urgency,expected",
        [
            (5, 1, 3.40),   # 0.6*5 + 0.4*1 — severity-dominant
            (1, 5, 2.60),   # 0.6*1 + 0.4*5 — urgency-dominant
            (5, 5, 5.00),   # top of both scales
        ],
        ids=["severity-dominant", "urgency-dominant", "max-both"],
    )
    def test_priority_score_weighting(self, api, severity, urgency, expected):
        """PRD §3.4: "the severity multiplied by a weight of 0.6, plus the
        urgency multiplied by a weight of 0.4, plus a bonus of 10 when the
        finding is a code violation, plus a further bonus of 5 when it is an
        accessibility violation — the total rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/priority_score_weighted_multi_input
        """
        _facility, system = setup_facility_with_system()
        deficiency = create_deficiency(system["id"], description="weighted",
                                       cost_estimate_cents=1000000,
                                       severity=severity, urgency=urgency,
                                       recommended_year=2027)
        assert deficiency["priority_score"] == pytest.approx(expected,
                                                             abs=1e-9)


class TestDualAxisCloseOut:
    def test_parallel_dimensions_and_verification_rejection_compensation(
            self, api):
        """PRD §3.4: "A new deficiency starts life with `remediation_status`
        of `OPEN` and `verification_status` of `UNVERIFIED` — two parallel
        state dimensions that evolve independently."
        PRD §3.5: "Rejecting corrected work requires the same preconditions
        but moves `verification_status` to `REJECTED` and, as compensation,
        drives `remediation_status` back to `IN_PROGRESS` — the finding
        re-enters the backlog set, so the facility's backlog and index are
        recomputed, and the deficiency's `version` increments."
        PRD §3.5: "success moves verification to `VERIFIED`, which is the
        terminal close-out state for a finding, and appends a ConditionSnapshot
        to the owning AssetSystem recording its current rating and remaining
        life."

        Design: Difficulty/non_linear_state_machine/deficiency_parallel_remediation_verification_dimensions
        """
        _facility, system, deficiency = setup_system_with_deficiency(
            {"description": "Controller obsolete",
             "cost_estimate_cents": 2000000, "severity": 3, "urgency": 3,
             "recommended_year": 2027},
            {"system_category": "CONVEYANCE", "name": "Elevator 1",
             "install_year": 2011, "design_life_years": 25,
             "replacement_cost_cents": 90000000, "condition_rating": 3})
        did = deficiency["id"]
        assert deficiency["remediation_status"] == "OPEN"
        assert deficiency["verification_status"] == "UNVERIFIED"

        started = validate_success(api.start_remediation(did, MANAGER))
        assert started["remediation_status"] == "IN_PROGRESS"
        assert started["verification_status"] == "UNVERIFIED", (
            "the verification axis is untouched by remediation progress")

        corrected = validate_success(api.complete_remediation(did, MANAGER))
        assert corrected["remediation_status"] == "CORRECTED"
        assert corrected["verification_status"] == "UNVERIFIED", (
            "dimensions are independent: CORRECTED does not imply VERIFIED")

        rejected = validate_success(api.reject_verification(did, CONSULTANT))
        assert rejected["verification_status"] == "REJECTED"
        assert rejected["remediation_status"] == "IN_PROGRESS", (
            "verification rejection drives remediation backwards")

        recorrected = validate_success(api.complete_remediation(did, MANAGER))
        assert recorrected["remediation_status"] == "CORRECTED", (
            "the remediation axis stays usable after a verification rejection")
        # Verification REJECTED is not UNVERIFIED: the verify precondition of
        # PRD section 3.5 ("with `verification_status` still `UNVERIFIED`") is
        # not met, so a later verify attempt is a state error (PRD section
        # 2.7 check 5).
        validate_error(api.verify_deficiency(did, CONSULTANT),
                       ApiErrorId.ERR_INVALID_STATE)

        # A finding that was never rejected verifies cleanly and appends a
        # ConditionSnapshot to the owning system (PRD section 3.5).
        d2 = create_deficiency(system["id"], description="Follow-up finding",
                               cost_estimate_cents=500000, severity=3,
                               urgency=3, recommended_year=2027)
        validate_success(api.start_remediation(d2["id"], MANAGER))
        validate_success(api.complete_remediation(d2["id"], MANAGER))
        snapshots_before = len(list_system_snapshots(system["id"]))
        verified = validate_success(api.verify_deficiency(d2["id"], CONSULTANT))
        assert verified["remediation_status"] == "CORRECTED"
        assert verified["verification_status"] == "VERIFIED", "terminal pair"
        snapshots_after = list_system_snapshots(system["id"])
        assert len(snapshots_after) == snapshots_before + 1, (
            "verify appends a ConditionSnapshot to the owning system")

    def test_verification_actions_require_corrected_state(self, api):
        """PRD §3.5: "Verifying corrected work requires `remediation_status`
        of `CORRECTED` with `verification_status` still `UNVERIFIED`"
        PRD §2.7: "**State legality** — the target resource must be in a state
        that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/deficiency_parallel_remediation_verification_dimensions
        """
        _facility, _system, deficiency = setup_system_with_deficiency()
        did = deficiency["id"]

        # OPEN: both verification actions illegal.
        validate_error(api.verify_deficiency(did, CONSULTANT),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.reject_verification(did, CONSULTANT),
                       ApiErrorId.ERR_INVALID_STATE)

        # IN_PROGRESS: still not CORRECTED.
        validate_success(api.start_remediation(did, MANAGER))
        validate_error(api.verify_deficiency(did, CONSULTANT),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.reject_verification(did, CONSULTANT),
                       ApiErrorId.ERR_INVALID_STATE)

        after = get_deficiency(did)
        assert after["remediation_status"] == "IN_PROGRESS"
        assert after["verification_status"] == "UNVERIFIED"


class TestVerifyFromOpen:
    def test_verify_from_open_remediation_rejected(self, api):
        """PRD §3.5: "Verifying corrected work requires `remediation_status`
        of `CORRECTED` with `verification_status` still `UNVERIFIED`"
        PRD §2.7: "verify requires `remediation_status` of `CORRECTED`, and so
        on); otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/verify_from_open_remediation_rejected
        """
        _facility, _system, deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 1000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027},
            {"system_category": "HVAC", "name": "S", "install_year": 2015,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 4})
        assert deficiency["remediation_status"] == "OPEN"
        resp = api.verify_deficiency(deficiency["id"], CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeferReopenConservation:
    def test_defer_reopen_round_trip_conserves_backlog_and_fci(self, api):
        """PRD §3.5: "deferring moves `remediation_status` from `OPEN` to
        `DEFERRED`, and reopening reverses it from `DEFERRED` back to `OPEN`."
        PRD §2.4: "`backlog_cost_cents`, the sum of `cost_estimate_cents` over
        the facility's deficiencies whose `remediation_status` is either
        `OPEN` or `IN_PROGRESS` (the deferred-maintenance backlog)"
        PRD §3.5: "though the deficiency's `version` still increments on
        each."

        Design: Difficulty/compensating_invariant/defer_reopen_leaves_backlog_and_fci_unchanged
        """
        facility, _system, deficiency = setup_system_with_deficiency(
            {"description": "Seat mechanism wear",
             "cost_estimate_cents": 10000000, "severity": 3, "urgency": 3,
             "recommended_year": 2028},
            {"system_category": "INTERIOR", "name": "Seating",
             "install_year": 2010, "design_life_years": 20,
             "replacement_cost_cents": 200000000, "condition_rating": 3})
        before = get_facility(facility["id"])
        assert before["backlog_cost_cents"] == 10000000
        assert before["facility_condition_index"] == pytest.approx(0.05,
                                                                   abs=1e-9)

        deferred = validate_success(api.defer_deficiency(deficiency["id"],
                                                         MANAGER))
        assert deferred["remediation_status"] == "DEFERRED"
        reopened = validate_success(api.reopen_deficiency(deficiency["id"],
                                                          MANAGER))
        assert reopened["remediation_status"] == "OPEN"
        assert reopened["version"] == deficiency["version"] + 2, (
            "two transitions, two version increments")

        after = get_facility(facility["id"])
        assert after["backlog_cost_cents"] == before["backlog_cost_cents"], (
            "round trip OPEN -> DEFERRED -> OPEN conserves the backlog")
        assert after["facility_condition_index"] == pytest.approx(
            before["facility_condition_index"], abs=1e-9)

    def test_defer_and_reopen_state_legality(self, api):
        """PRD §3.5: "deferring moves `remediation_status` from `OPEN` to
        `DEFERRED`, and reopening reverses it from `DEFERRED` back to `OPEN`."
        PRD §2.7: "**State legality** — the target resource must be in a state
        that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/defer_reopen_leaves_backlog_and_fci_unchanged
        """
        _facility, _system, deficiency = setup_system_with_deficiency()
        did = deficiency["id"]

        # reopen requires DEFERRED: illegal from OPEN.
        validate_error(api.reopen_deficiency(did, MANAGER),
                       ApiErrorId.ERR_INVALID_STATE)

        # defer requires OPEN: illegal from IN_PROGRESS.
        validate_success(api.start_remediation(did, MANAGER))
        validate_error(api.defer_deficiency(did, MANAGER),
                       ApiErrorId.ERR_INVALID_STATE)
        assert get_deficiency(did)["remediation_status"] == "IN_PROGRESS"


class TestDerivedFieldReconciliation:
    def test_complete_remediation_reconciles_backlog_immediately(self, api):
        """PRD §3.5: "Completing remediation moves `remediation_status` from
        `IN_PROGRESS` to `CORRECTED`, which finally lifts the cost out of the
        backlog set and recomputes the facility's `backlog_cost_cents` and
        `facility_condition_index` accordingly."
        PRD §2.9: "Consistency is immediate, not eventual: whenever a child
        mutation changes an input to a parent's derived field, the parent's
        derived fields are recomputed as part of the same operation"

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_complete_remediation
        """
        facility, _system, deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 10000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027},
            {"system_category": "HVAC", "name": "S", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 100000000,
             "condition_rating": 3})
        validate_success(api.start_remediation(deficiency["id"], MANAGER))
        mid = get_facility(facility["id"])
        assert mid["backlog_cost_cents"] == 10000000, (
            "IN_PROGRESS remains in the backlog set")

        completed = validate_success(
            api.complete_remediation(deficiency["id"], MANAGER))
        assert completed["remediation_status"] == "CORRECTED"
        after = get_facility(facility["id"])
        assert after["backlog_cost_cents"] == 0, (
            "CORRECTED leaves the backlog set in the same read sequence")
        assert after["facility_condition_index"] == pytest.approx(0.0,
                                                                  abs=1e-9)


class TestFindingStreamGuards:
    def test_deficiency_on_retired_system_rejected(self, api):
        """PRD §3.4: "And a deficiency may not be recorded on a system whose
        lifecycle `status` is `RETIRED`; that attempt is an
        `ERR_REFERENTIAL_CONFLICT`."

        Design: Corner/validations/deficiency_on_retired_system_rejected
        """
        facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "S", "install_year": 2000,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 2})
        retired = validate_success(api.retire_asset_system(system["id"],
                                                           MANAGER))
        assert retired["status"] == "RETIRED"
        resp = api.create_deficiency(
            create_deficiency_payload(system["id"], description="d",
                                      cost_estimate_cents=1000000, severity=3,
                                      urgency=3, recommended_year=2027),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_CONFLICT)

    def test_retire_with_open_deficiency_rejected(self, api):
        """PRD §3.8: "A `FacilityManager` may retire a system only while it is
        `ACTIVE` and only when none of its deficiencies have
        `remediation_status` of `OPEN` or `IN_PROGRESS` — retiring with
        unresolved findings is `ERR_REFERENTIAL_CONFLICT`."

        Design: Corner/validations/retire_with_open_deficiency_rejected
        """
        _facility, system, _deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 1000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027},
            {"system_category": "HVAC", "name": "S", "install_year": 2000,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 2})
        resp = api.retire_asset_system(system["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_CONFLICT)
        assert get_asset_system(system["id"])["status"] == "ACTIVE"

    def test_code_violation_low_severity_rejected(self, api):
        """PRD §3.4: "A deficiency flagged as a code violation or an
        accessibility violation must carry a `severity` of at least 3 —
        flagging life-safety or compliance exposure as minor is rejected with
        `ERR_CODE_SEVERITY_TOO_LOW`."
        PRD §3.4: "the severity multiplied by a weight of 0.6, plus the
        urgency multiplied by a weight of 0.4, plus a bonus of 10 when the
        finding is a code violation, plus a further bonus of 5 when it is an
        accessibility violation — the total rounded half-up to 2 decimal
        places."

        Design: Corner/validations/code_violation_low_severity_rejected
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "CONVEYANCE", "name": "Lift",
             "install_year": 2015, "design_life_years": 20,
             "replacement_cost_cents": 30000000, "condition_rating": 3})
        low = api.create_deficiency(
            create_deficiency_payload(
                system["id"], description="no ramp",
                cost_estimate_cents=2000000, severity=2, urgency=4,
                is_accessibility_violation=True, recommended_year=2027),
            CONSULTANT,
        )
        validate_error(low, ApiErrorId.ERR_CODE_SEVERITY_TOO_LOW)

        ok = validate_success(api.create_deficiency(
            create_deficiency_payload(
                system["id"], description="ramp", cost_estimate_cents=2000000,
                severity=3, urgency=4, is_accessibility_violation=True,
                recommended_year=2027),
            CONSULTANT,
        ), 201)
        # severity 3 is at the inclusive floor; 0.6*3 + 0.4*4 + 5 = 8.40.
        assert ok["priority_score"] == pytest.approx(8.40, abs=1e-9)

    def test_recommended_year_below_base_rejected(self, api):
        """PRD §3.4: "The recommended year must not be earlier than 2026 —
        the base year — and must lie between 2000 and 2200; a year before 2026
        is rejected with `ERR_YEAR_OUT_OF_RANGE`."

        Design: Corner/validations/recommended_year_below_base_rejected
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "S", "install_year": 2015,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        resp = api.create_deficiency(
            create_deficiency_payload(system["id"], description="d",
                                      cost_estimate_cents=1000000, severity=3,
                                      urgency=3, recommended_year=2025),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_YEAR_OUT_OF_RANGE)


class TestValidationCascadeOrdering:
    def test_safety_error_precedes_temporal_error_on_deficiency_create(
            self, api):
        """PRD §2.7: "Every request is screened by an ordered validation
        cascade, and the order is part of the contract — it determines which
        error a request with multiple problems surfaces."
        PRD §2.7: "8. **Code/accessibility hygiene** — a deficiency flagged as
        a code or accessibility violation must carry adequate severity;
        otherwise `ERR_CODE_SEVERITY_TOO_LOW`."
        PRD §2.7: "9. **Temporal range** — recommended and planned years must
        fall inside their permitted windows; otherwise
        `ERR_YEAR_OUT_OF_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_deficiency_create
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "ENVELOPE", "name": "Curtain Wall",
             "install_year": 2000, "design_life_years": 30,
             "replacement_cost_cents": 120000000, "condition_rating": 2})
        # severity 2 + code flag violates check 8; recommended_year 2020
        # violates check 9; check 8 is earlier in the ordered cascade.
        resp = api.create_deficiency(
            create_deficiency_payload(
                system["id"],
                description="Sealant failure w/ code issue and stale year",
                cost_estimate_cents=5000000, severity=2, urgency=3,
                is_code_violation=True, recommended_year=2020),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_CODE_SEVERITY_TOO_LOW)

        data, meta = _list_system_deficiencies(api, system["id"])
        assert meta["total_count"] == 0 and data == [], (
            "a rejected create leaves no Deficiency row behind")

    def test_safety_and_temporal_errors_fire_in_isolation(self, api):
        """PRD §3.4: "A deficiency flagged as a code violation or an
        accessibility violation must carry a `severity` of at least 3 —
        flagging life-safety or compliance exposure as minor is rejected with
        `ERR_CODE_SEVERITY_TOO_LOW`."
        PRD §3.4: "The recommended year must not be earlier than 2026 — the
        base year — and must lie between 2000 and 2200; a year before 2026 is
        rejected with `ERR_YEAR_OUT_OF_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_deficiency_create
        """
        _facility, system = setup_facility_with_system()
        # Only the safety rule violated (year valid).
        safety_only = api.create_deficiency(
            create_deficiency_payload(system["id"], severity=2, urgency=3,
                                      is_code_violation=True,
                                      recommended_year=2027),
            CONSULTANT,
        )
        validate_error(safety_only, ApiErrorId.ERR_CODE_SEVERITY_TOO_LOW)

        # Only the temporal rule violated (no flags, severity adequate).
        temporal_only = api.create_deficiency(
            create_deficiency_payload(system["id"], severity=3, urgency=3,
                                      recommended_year=2020),
            CONSULTANT,
        )
        validate_error(temporal_only, ApiErrorId.ERR_YEAR_OUT_OF_RANGE)


def _list_system_deficiencies(api, system_id):
    return validate_paginated(api.list_system_deficiencies(system_id,
                                                           CONSULTANT))
