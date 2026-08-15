"""Concessions and net effective rent; complete-diligence gates; lease-flag
demotion cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_lease,
    add_rent_roll_entry,
    add_unit,
    create_concession_payload,
    create_kicked_off_acquisition,
    get_acquisition,
    get_success_data,
    setup_verified_unit,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]


class TestNetEffectiveRent:
    def test_net_effective_rent_excludes_unverified_concessions(self, api):
        """PRD §3.3: "`net_effective_rent_cents` is the lease's
        concession-adjusted monthly rent: take `contract_rent_cents` times
        `term_months`, subtract the sum of `verified_value_cents` over the
        lease's `VERIFIED` concessions only (pending and rejected concessions
        are excluded), divide by `term_months`, and round half up to integer
        cents at that final division."
        PRD §3.3: "Verification by an analyst supplies the accepted
        `verified_value_cents` and moves the concession to `VERIFIED`..."

        Design: Corner/calculations/net_effective_rent_excludes_unverified_concessions
        """
        acq = create_kicked_off_acquisition(property_name="NER Deal")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])
        conc = get_success_data(api.create_concession(
            create_concession_payload(lease["id"]), ANALYST), 201)

        before = get_success_data(api.get_lease_file(lease["id"], ANALYST))
        assert before["net_effective_rent_cents"] == 150_000, (
            "a PENDING concession is excluded from the NER"
        )

        get_success_data(api.verify_concession(conc["id"], 120_000, ANALYST))
        after = get_success_data(api.get_lease_file(lease["id"], ANALYST))
        assert after["net_effective_rent_cents"] == 140_000, (
            "round_half_up((150000 x 12 - 120000) / 12)"
        )


class TestCompleteDiligenceGates:
    def test_complete_diligence_with_unresolved_items_rejected(self, api):
        """PRD §3.1: "Completing diligence moves `IN_DILIGENCE` to
        `DILIGENCE_COMPLETE` and enforces four gates: the posture must not be
        `BLOCKED` (else `ERR_ACQUISITION_BLOCKED`); no lease file belonging to
        a non-`EXCLUDED` unit may remain `UPLOADED` or `DISCREPANCY_FLAGGED`;
        no deposit ledger entry may remain `RECORDED` or `DISPUTED`; and every
        non-`EXCLUDED` unit must have reached `VERIFIED` — the latter three
        violations all surface as `ERR_UNRESOLVED_AUDIT_ITEMS`."

        Design: Corner/validations/complete_diligence_with_unresolved_items_rejected
        """
        acq = create_kicked_off_acquisition(property_name="Unres")
        unit = add_unit(acq["id"])
        add_lease(unit["id"])  # UPLOADED, never audited

        resp = api.complete_diligence(acq["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_AUDIT_ITEMS, 409)
        assert get_acquisition(acq["id"])["status"] == "IN_DILIGENCE"

    def test_complete_diligence_blocked_posture_rejected(self, api):
        """PRD §3.1: "Completing diligence moves `IN_DILIGENCE` to
        `DILIGENCE_COMPLETE` and enforces four gates: the posture must not be
        `BLOCKED` (else `ERR_ACQUISITION_BLOCKED`); ..."
        PRD §3.9: "The posture is `BLOCKED` when any of three conditions
        holds: any lease file of a non-excluded unit stands
        `DISCREPANCY_FLAGGED`; any deposit ledger entry stands `DISPUTED`; or
        the `deferred_maintenance_total_cents` is strictly greater than 5
        percent of the `agreed_purchase_price_cents`..."
        PRD §2.4: "then compliance gates
        (`ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE`, `ERR_ACQUISITION_BLOCKED`,
        `ERR_UNRESOLVED_AUDIT_ITEMS`), then uniqueness and readiness
        constraints ..."

        Design: Corner/validations/complete_diligence_blocked_posture_rejected
        """
        acq = create_kicked_off_acquisition(property_name="Blocked")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])
        add_rent_roll_entry(unit["id"], reported_rent_cents=152_000,
                            reported_deposit_cents=150_000)
        flagged = get_success_data(api.audit_lease_file(lease["id"], ANALYST))
        assert flagged["status"] == "DISCREPANCY_FLAGGED"
        assert get_acquisition(acq["id"])["readiness_posture"] == "BLOCKED"

        resp = api.complete_diligence(acq["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_ACQUISITION_BLOCKED, 409)


class TestLeaseFlagDemotesUnitCascade:
    def test_lease_flag_demotes_unit_and_blocks_posture(self, api):
        """PRD §3.3: "Re-flagging cascades in order — the rent roll entry
        returns to `MISMATCHED`; because the entry mismatched, the unit's
        `lease_audited` flips false and a `VERIFIED` unit demotes to
        `CLEARING`; because the unit demoted, the acquisition's
        `readiness_posture` recomputes."
        PRD §3.2: "If any flag later flips back to false — for example because
        a lease is re-flagged — a `VERIFIED` unit demotes to `CLEARING` and
        posture is again recomputed."
        PRD §3.9: "The posture is `BLOCKED` when any of three conditions
        holds: any lease file of a non-excluded unit stands
        `DISCREPANCY_FLAGGED`; ..."

        Design: Difficulty/transitive_cascade/lease_flag_demotes_unit_and_blocks_posture_cascade
        """
        ctx = setup_verified_unit(property_name="Cascade Three")
        unit_id = ctx["unit"]["id"]
        lease_id = ctx["lease"]["id"]
        assert ctx["unit"]["status"] == "VERIFIED", "precondition"

        flagged = validate_success(api.flag_lease_file(
            lease_id, "signature page mismatch", ANALYST))
        assert flagged["status"] == "DISCREPANCY_FLAGGED"

        rr_rows, _ = validate_paginated(
            api.list_unit_rent_roll_entries(unit_id, ANALYST))
        assert rr_rows[0]["verification_status"] == "MISMATCHED"

        unit_now = get_success_data(api.get_unit(unit_id, ANALYST))
        assert unit_now["status"] == "CLEARING", "VERIFIED demotes to CLEARING"
        assert unit_now["lease_audited"] is False

        assert get_acquisition(ctx["acq"]["id"])["readiness_posture"] == "BLOCKED"

    def test_flag_audited_lease_recomputes_rent_roll_and_posture(self, api):
        """PRD §3.3: "The third path is the revision loop: an analyst may
        re-flag a lease in `AUDITED` or `RESOLVED` by supplying a `reason`,
        sending it back to `DISCREPANCY_FLAGGED`."
        PRD §3.3: "The acquisition-level `rent_roll_variance_cents` is the sum
        of each flagged lease's `variance_cents` — reported minus contract —
        over lease files in `DISCREPANCY_FLAGGED` status whose unit is not
        `EXCLUDED`."

        Design: Difficulty/transitive_cascade/lease_flag_demotes_unit_and_blocks_posture_cascade
        """
        ctx = setup_verified_unit(property_name="Cascade Three B")
        acq_id = ctx["acq"]["id"]
        unit_id = ctx["unit"]["id"]
        lease_id = ctx["lease"]["id"]
        assert get_acquisition(acq_id)["rent_roll_variance_cents"] == 0

        get_success_data(api.flag_lease_file(lease_id, "re-check", ANALYST))
        acq_now = get_acquisition(acq_id)
        # Variance recomputes as reported (150000) - contract (150000) = 0
        # against THIS scenario's matching rent roll; posture still BLOCKED
        # because a flagged lease exists regardless of amount.
        assert acq_now["readiness_posture"] == "BLOCKED"
        unit_now = get_success_data(api.get_unit(unit_id, ANALYST))
        assert unit_now["status"] == "CLEARING"
        rr_rows, _ = validate_paginated(
            api.list_unit_rent_roll_entries(unit_id, ANALYST))
        assert rr_rows[0]["verification_status"] == "MISMATCHED"
