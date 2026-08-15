"""Lot hold model and release safety gates."""
from test_helpers import (
    ApiErrorId,
    add_component,
    complete_lot,
    create_completed_lot,
    create_label,
    create_lot,
    create_ncr,
    create_part,
    create_protocol,
    create_qualified_supplier,
    create_releasable_lot,
    create_validated_stack,
    get_lot,
    get_part,
    approve_label,
    print_label,
    qe,
    qm,
    record_sterility,
    release_lot,
    validate_error,
    validate_success,
    walk_protocol_to_validated,
    api_client,
)


def _stack_with_part(prefix, claim_months=20):
    stack = create_validated_stack(prefix, claim_months=claim_months)
    qs = create_qualified_supplier(f"SUP-{prefix.removeprefix('DEV-')}", f"{prefix} Supplier")
    part = create_part(qs["supplier"]["id"], f"PN-{prefix.removeprefix('DEV-')}", receive_qty=100)
    return stack, qs, part


class TestDeviceLotParallelDispositionAndHold:
    def _setup_held_ready_lot(self):
        stack, _qs, part = _stack_with_part("DEV-P")
        bundle = create_releasable_lot(stack, part, lot_number="LT-P", supplier_lot_number="SL-P")
        return stack, bundle

    def test_hold_blocks_release_while_disposition_stays_completed(self, api):
        """PRD section 2.8: "A device lot carries two parallel, independent state
        dimensions." and PRD section 3.6: "its hold must be `CLEAR`
        (`ERR_LOT_ON_HOLD`)".

        Design: Difficulty/non_linear_state_machine/device_lot_parallel_disposition_and_hold
        """
        _stack, bundle = self._setup_held_ready_lot()
        lot_id = bundle["lot"]["id"]

        held = validate_success(api.place_hold(lot_id, qe()))
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "MANUAL"
        assert held["disposition_status"] == "COMPLETED", (
            "the hold dimension must not disturb the disposition dimension"
        )

        resp = api.release_lot(lot_id, qm())
        validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD)
        current = get_lot(lot_id)
        assert current["disposition_status"] == "COMPLETED"

    def test_release_hold_clears_and_release_succeeds(self, api):
        """PRD section 3.6: "A successful release returns the lot to `CLEAR` and
        resets `hold_reason` to `NONE`." and "a `MANUAL` hold always clears".

        Design: Difficulty/non_linear_state_machine/device_lot_parallel_disposition_and_hold
        """
        _stack, bundle = self._setup_held_ready_lot()
        lot_id = bundle["lot"]["id"]

        validate_success(api.place_hold(lot_id, qe()))
        cleared = validate_success(api.release_hold(lot_id, qe()))
        assert cleared["hold_status"] == "CLEAR"
        assert cleared["hold_reason"] == "NONE"
        assert cleared["disposition_status"] == "COMPLETED"

        released = release_lot(lot_id)
        assert released["disposition_status"] == "RELEASED"


class TestLotReleaseRequiresValidatedProtocol:
    def _setup_lot_with_draft_protocol(self):
        from test_helpers import create_approved_dmr, create_line

        line = create_line("L-X2")
        dmr = create_approved_dmr(device_code="DEV-X2")
        protocol = create_protocol("VP-X2", dmr["id"], line["id"])
        stack = {"line": line, "dmr": dmr, "protocol": protocol}
        qs = create_qualified_supplier("SUP-X2", "Xtwo")
        part = create_part(qs["supplier"]["id"], "PN-X2", description="cap", receive_qty=100)
        bundle = create_releasable_lot(stack, part, lot_number="LT-X2", supplier_lot_number="SL-X2")
        return stack, bundle

    def test_release_rejected_while_protocol_not_validated(self, api):
        """PRD section 3.6: "the validation protocol the lot was produced under
        must be `VALIDATED` (`ERR_PROTOCOL_NOT_VALIDATED`)" and "the protocol
        need not be `VALIDATED` yet: production under validation-in-progress is
        permitted, while release is not".

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_validated_protocol
        """
        _stack, bundle = self._setup_lot_with_draft_protocol()
        resp = api.release_lot(bundle["lot"]["id"], qm())
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_VALIDATED)
        current = get_lot(bundle["lot"]["id"])
        assert current["disposition_status"] == "COMPLETED"

    def test_release_succeeds_once_protocol_validated(self, api):
        """PRD section 3.6: "the validation protocol the lot was produced under
        must be `VALIDATED` (`ERR_PROTOCOL_NOT_VALIDATED`)" — after the protocol
        completes IQ/OQ/PQ and becomes `VALIDATED`, the same release succeeds.

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_validated_protocol
        """
        stack, bundle = self._setup_lot_with_draft_protocol()
        walk_protocol_to_validated(stack["protocol"]["id"])
        released = release_lot(bundle["lot"]["id"])
        assert released["disposition_status"] == "RELEASED"


class TestHoldResolutionConditions:
    def test_ncr_open_hold_blocked_until_ncr_dispositioned(self, api):
        """PRD section 3.6: "Releasing a hold re-verifies the reason's resolution
        condition and fails with `ERR_HOLD_CONDITION_UNRESOLVED` when it is not
        met: an `NCR_OPEN` hold clears only when no nonconformance report of the
        lot remains `OPEN` or `CONTAINED`" and PRD section 3.7: "when the
        referenced lot is `IN_PRODUCTION` or `COMPLETED`, it is placed `ON_HOLD`
        with `hold_reason` `NCR_OPEN`."

        Design: Corner/state_machines/hold_release_blocked_while_ncr_contained
        """
        stack, _qs, part = _stack_with_part("DEV-HR")
        lot = create_lot("LT-HR", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot["id"], part["id"], quantity_used=10, supplier_lot_number="SL-HR")
        ncr = create_ncr(ncr_code="NCR-HR", severity="MINOR", description="bend", lot_id=lot["id"])
        held = get_lot(lot["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "NCR_OPEN"
        complete_lot(lot["id"])
        validate_success(api.contain_ncr(ncr["id"], qe()))

        resp = api.release_hold(lot["id"], qe())
        validate_error(resp, ApiErrorId.ERR_HOLD_CONDITION_UNRESOLVED)

        validate_success(
            api.disposition_ncr(ncr["id"], {"disposition": "REWORK", "fault": "INTERNAL"}, qe())
        )
        cleared = validate_success(api.release_hold(lot["id"], qe()))
        assert cleared["hold_status"] == "CLEAR"
        assert cleared["hold_reason"] == "NONE"

    def test_sterility_result_recorded_once(self, api):
        """PRD section 3.6: "Sterility is recorded once, by a `QualityEngineer`,
        on a `COMPLETED` lot (any other disposition is `ERR_INVALID_STATE_TRANSITION`)
        whose `sterility_result` is still `PENDING` — a lot already resulted
        answers `ERR_STERILITY_ALREADY_RESULTED`."

        Design: Corner/state_machines/sterility_result_recorded_once
        """
        stack, _qs, part = _stack_with_part("DEV-SR")
        lot = create_completed_lot(stack, part, lot_number="LT-SR", supplier_lot_number="SL-SR")
        record_sterility(lot["id"], "PASSED")

        resp = api.record_sterility_result(lot["id"], {"result": "FAILED"}, qe())
        validate_error(resp, ApiErrorId.ERR_STERILITY_ALREADY_RESULTED)
        current = get_lot(lot["id"])
        assert current["sterility_result"] == "PASSED"

    def test_sterility_failure_hold_never_clearable(self, api):
        """PRD section 3.6: "A `FAILED` result immediately places the lot
        `ON_HOLD` with `hold_reason` `STERILITY_FAILURE`, a hold that can never
        be cleared." and "`STERILITY_FAILURE` and `FIELD_ACTION` holds never
        clear through this operation" — and release is blocked while held
        (`ERR_LOT_ON_HOLD`).

        Design: Corner/state_machines/sterility_failure_hold_never_clearable
        """
        stack, _qs, part = _stack_with_part("DEV-SF")
        lot = create_completed_lot(stack, part, lot_number="LT-SF", supplier_lot_number="SL-SF")
        failed = record_sterility(lot["id"], "FAILED")
        assert failed["hold_status"] == "ON_HOLD"
        assert failed["hold_reason"] == "STERILITY_FAILURE"

        resp = api.release_hold(lot["id"], qe())
        validate_error(resp, ApiErrorId.ERR_HOLD_CONDITION_UNRESOLVED)
        resp = api.release_lot(lot["id"], qm())
        validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD)
        scrapped = validate_success(api.scrap_lot(lot["id"], qe()))
        assert scrapped["disposition_status"] == "SCRAPPED"


class TestReleaseSafetyGates:
    def test_release_without_printed_label_rejected(self, api):
        """PRD section 3.6: "at least one label of the lot must be `PRINTED` with
        a `label_revision` equal to the lot's pinned DMR `revision_code`
        (`ERR_NO_PRINTED_LABEL`)".

        Design: Corner/endpoints/release_without_printed_label_rejected
        """
        stack, _qs, part = _stack_with_part("DEV-NL")
        lot = create_completed_lot(stack, part, lot_number="LT-NL", supplier_lot_number="SL-NL")
        record_sterility(lot["id"], "PASSED")
        label = create_label(lot["id"])
        approve_label(label["id"])

        resp = api.release_lot(lot["id"], qm())
        validate_error(resp, ApiErrorId.ERR_NO_PRINTED_LABEL)
        current = get_lot(lot["id"])
        assert current["disposition_status"] == "COMPLETED"

    def test_release_sterility_pending_rejected(self, api):
        """PRD section 3.6: "when the lot's DMR is sterile, `sterility_result`
        must be `PASSED` (`ERR_STERILITY_NOT_PASSED`)".

        Design: Corner/endpoints/release_sterility_pending_rejected
        """
        stack, _qs, part = _stack_with_part("DEV-SP")
        lot = create_completed_lot(stack, part, lot_number="LT-SP", supplier_lot_number="SL-SP")
        label = create_label(lot["id"])
        approve_label(label["id"])
        print_label(label["id"])

        resp = api.release_lot(lot["id"], qm())
        validate_error(resp, ApiErrorId.ERR_STERILITY_NOT_PASSED)
        current = get_lot(lot["id"])
        assert current["disposition_status"] == "COMPLETED"
        assert current["sterility_result"] == "PENDING"

    def test_immediate_visibility_after_release(self, api):
        """PRD section 2.8: "The consistency model is **immediate**: every
        mutation and every cascade it triggers is visible in that same request's
        response and in all subsequent reads — there is no eventual-consistency
        window anywhere in the system."

        Design: Corner/consistency_model/immediate_visibility_after_release
        """
        stack, _qs, part = _stack_with_part("DEV-IC")
        bundle = create_releasable_lot(stack, part, lot_number="LT-IC", supplier_lot_number="SL-IC")

        released = release_lot(bundle["lot"]["id"])
        assert released["disposition_status"] == "RELEASED"

        reloaded = get_part(part["id"])
        assert reloaded["quantity_committed"] == 0
        assert reloaded["quantity_in_released_lots"] == 10
