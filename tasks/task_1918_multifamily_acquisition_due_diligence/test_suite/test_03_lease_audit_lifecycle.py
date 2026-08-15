"""Lease-file audit against the rent roll: threshold, flag/resolve loop, waiver."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_lease,
    add_rent_roll_entry,
    add_unit,
    create_kicked_off_acquisition,
    get_acquisition,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]


def _flagged_lease_scenario(api, *, contract=150000, reported=152000):
    """IN_DILIGENCE acquisition with a lease that auto-flags at audit
    (variance reported - contract = reported - contract, >= the 500-cent
    materiality threshold)."""
    acq = create_kicked_off_acquisition(property_name="Flag Deal")
    unit = add_unit(acq["id"])
    lease = add_lease(unit["id"], contract_rent_cents=contract)
    add_rent_roll_entry(unit["id"], reported_rent_cents=reported,
                        reported_deposit_cents=150000)
    return acq, unit, lease


class TestLeaseAuditThresholdAndReflagCycle:
    def test_audit_flag_then_resolve_then_reflag_cycle(self, api):
        """PRD §3.3: "When the absolute variance is at least 500 cents, the
        lease instead lands `DISCREPANCY_FLAGGED`, the entry becomes
        `MISMATCHED`, and `audit_result` records `OVERSTATED` when the reported
        rent exceeds the contract rent or `UNDERSTATED` when it falls short."
        PRD §3.3: "Resolution by an `AcquisitionsAnalyst` moves
        `DISCREPANCY_FLAGGED` to `RESOLVED`; the request carries a
        `resolution_note` and may carry `corrected_contract_rent_cents`, which
        when supplied replaces `contract_rent_cents` and triggers recomputation
        of `variance_cents`. Resolution sets the rent roll entry back to
        `VERIFIED`, recomputes `lease_audited` (which may promote the unit from
        `CLEARING` to `VERIFIED`), and recomputes the acquisition rollup and
        posture."

        Design: Difficulty/non_linear_state_machine/lease_file_reflag_cycle
        """
        acq, unit, lease = _flagged_lease_scenario(api)

        flagged = validate_success(api.audit_lease_file(lease["id"], ANALYST))
        assert flagged["status"] == "DISCREPANCY_FLAGGED"
        assert flagged["variance_cents"] == 2000
        acq_now = get_acquisition(acq["id"])
        assert acq_now["rent_roll_variance_cents"] == 2000
        assert acq_now["readiness_posture"] == "BLOCKED"

        resolved = validate_success(api.resolve_lease_file(
            lease["id"], {"resolution_note": "seller confirmed lease amendment"},
            ANALYST))
        assert resolved["status"] == "RESOLVED"
        acq_now = get_acquisition(acq["id"])
        assert acq_now["rent_roll_variance_cents"] == 0
        assert acq_now["readiness_posture"] == "ON_TRACK"

        reflagged = validate_success(api.flag_lease_file(
            lease["id"], "amendment not countersigned", ANALYST))
        assert reflagged["status"] == "DISCREPANCY_FLAGGED"

        rr_rows, _ = validate_paginated(
            api.list_unit_rent_roll_entries(unit["id"], ANALYST))
        assert rr_rows[0]["verification_status"] == "MISMATCHED"
        acq_now = get_acquisition(acq["id"])
        assert acq_now["rent_roll_variance_cents"] == 2000
        assert acq_now["readiness_posture"] == "BLOCKED"

        resolved2 = validate_success(api.resolve_lease_file(
            lease["id"], {"resolution_note": "countersigned copy received"},
            ANALYST))
        assert resolved2["status"] == "RESOLVED"
        assert get_acquisition(acq["id"])["rent_roll_variance_cents"] == 0

    def test_reflag_resolved_lease_restores_open_variance(self, api):
        """PRD §3.3: "The third path is the revision loop: an analyst may
        re-flag a lease in `AUDITED` or `RESOLVED` by supplying a `reason`,
        sending it back to `DISCREPANCY_FLAGGED`. Re-flagging cascades in order
        — the rent roll entry returns to `MISMATCHED`; because the entry
        mismatched, the unit's `lease_audited` flips false and a `VERIFIED`
        unit demotes to `CLEARING`; because the unit demoted, the acquisition's
        `readiness_posture` recomputes."
        PRD §3.3: "Only open exposure counts: `AUDITED`, `RESOLVED`, and
        `WAIVED` leases contribute zero."

        Design: Difficulty/non_linear_state_machine/lease_file_reflag_cycle
        """
        acq, unit, lease = _flagged_lease_scenario(api)
        get_success_data(api.audit_lease_file(lease["id"], ANALYST))
        get_success_data(api.resolve_lease_file(
            lease["id"], {"resolution_note": "amended"}, ANALYST))
        assert get_acquisition(acq["id"])["rent_roll_variance_cents"] == 0

        # The revision loop is repeatable: RESOLVED -> DISCREPANCY_FLAGGED.
        reflagged = get_success_data(api.flag_lease_file(
            lease["id"], "new evidence", ANALYST))
        assert reflagged["status"] == "DISCREPANCY_FLAGGED"
        acq_now = get_acquisition(acq["id"])
        assert acq_now["rent_roll_variance_cents"] == 2000, (
            "re-flagged lease re-enters the open-exposure sum"
        )
        assert acq_now["readiness_posture"] == "BLOCKED"

        # And RESOLVED again — the loop closes cleanly a second time.
        resolved = get_success_data(api.resolve_lease_file(
            lease["id"], {"resolution_note": "cured again"}, ANALYST))
        assert resolved["status"] == "RESOLVED"
        assert get_acquisition(acq["id"])["rent_roll_variance_cents"] == 0


class TestLeaseWaiver:
    def test_lease_waive_moves_variance_out_of_open_exposure(self, api):
        """PRD §3.3: "Waiver by an `UnderwritingManager` moves
        `DISCREPANCY_FLAGGED` to the terminal `WAIVED` state on the strength of
        a `waiver_note`; the lease records `waived_variance_cents` equal to the
        variance the buyer accepted, leaves the open-variance sum (so the
        acquisition rollup recomputes downward), and recomputes `lease_audited`
        and posture."
        PRD §3.9: "The posture is `BLOCKED` when any of three conditions
        holds: any lease file of a non-excluded unit stands
        `DISCREPANCY_FLAGGED`; ..."

        Design: Corner/state_machines/lease_waive_moves_variance_out_of_open_exposure
        """
        acq, unit, lease = _flagged_lease_scenario(api)
        flagged = get_success_data(api.audit_lease_file(lease["id"], ANALYST))
        assert flagged["status"] == "DISCREPANCY_FLAGGED"
        assert flagged["variance_cents"] == 2000

        waived = validate_success(api.waive_lease_file(
            lease["id"], "buyer accepts 2000 exposure", UM1))
        assert waived["status"] == "WAIVED"
        assert waived["waived_variance_cents"] == 2000

        acq_now = get_acquisition(acq["id"])
        assert acq_now["rent_roll_variance_cents"] == 0, (
            "WAIVED leases leave the open-exposure sum"
        )
        assert acq_now["readiness_posture"] == "ON_TRACK"


class TestAuditPreconditions:
    def test_audit_without_rent_roll_returns_missing_entry(self, api):
        """PRD §3.3: "The audit requires that an entry exist for the unit,
        else `ERR_RENT_ROLL_ENTRY_MISSING` (HTTP 422)."

        Design: Corner/validations/audit_without_rent_roll_returns_missing_entry
        """
        acq = create_kicked_off_acquisition(property_name="Miss RR")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])

        resp = api.audit_lease_file(lease["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RENT_ROLL_ENTRY_MISSING, 422)
        after = get_success_data(api.get_lease_file(lease["id"], ANALYST))
        assert after["status"] == "UPLOADED", "a failed audit must not mutate"

    def test_duplicate_rent_roll_entry_rejected(self, api):
        """PRD §3.3: "At most one rent roll entry may exist per unit; a second
        attempt is rejected with `ERR_RENT_ROLL_ENTRY_EXISTS`."

        Design: Corner/validations/duplicate_rent_roll_entry_rejected
        """
        acq = create_kicked_off_acquisition(property_name="Dup RR")
        unit = add_unit(acq["id"])
        add_rent_roll_entry(unit["id"])

        resp = api.create_rent_roll_entry(
            {"unit_id": unit["id"], "reported_resident_name": "R One",
             "reported_rent_cents": 151000, "reported_concession_cents": 0,
             "reported_deposit_cents": 150000,
             "move_in_date": "2025-09-01T00:00:00Z"},
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_RENT_ROLL_ENTRY_EXISTS, 409)
