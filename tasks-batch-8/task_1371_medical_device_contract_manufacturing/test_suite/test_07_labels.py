"""UDI label control: check digit, lifecycle gates, void cascades."""
from test_helpers import (
    ApiErrorId,
    UDI_VALID,
    UDI_VALID_ALT,
    add_component,
    approve_dmr,
    approve_label,
    complete_lot,
    create_approved_dmr,
    create_dmr_revision,
    create_label,
    create_line,
    create_lot,
    create_part,
    create_protocol,
    create_qualified_supplier,
    create_completed_lot,
    create_validated_stack,
    create_releasable_lot,
    get_lot,
    po,
    qe,
    qm,
    validate_error,
    validate_success,
    api_client,
)


class TestUdiCheckDigit:
    def test_udi_check_digit_enforced_and_pi_computed(self, api):
        """PRD section 3.6: "each of the thirteen digits is weighted 3 or 1 in
        strict alternation counting from the right, the rightmost of the thirteen
        carrying weight 3; the weighted sum is taken modulo ten; and the expected
        check digit is ten minus that remainder, modulo ten. A mismatch is
        rejected with `ERR_UDI_CHECK_DIGIT_MISMATCH`." and "The server computes
        `udi_pi` as the literal prefix `LOT-` followed by the lot's `lot_number`,
        then `-EXP-`, then the lot's `expiry_date` formatted as YYYYMMDD; it pins
        `label_revision` to the `revision_code` of the lot's DMR revision".

        Design: Corner/calculations/udi_check_digit_enforced
        """
        line = create_line("L-UD")
        dmr = create_approved_dmr(device_code="DEV-UD")
        protocol = create_protocol("VP-UD", dmr["id"], line["id"])
        lot = create_lot(
            "LT-UD", dmr["id"], protocol["id"], quantity=10,
            manufactured_at="2026-08-02T00:00:00Z",
        )

        resp = api.create_label(lot["id"], {"udi_di": "12345678901232"}, po())
        validate_error(resp, ApiErrorId.ERR_UDI_CHECK_DIGIT_MISMATCH)

        label = validate_success(
            api.create_label(lot["id"], {"udi_di": UDI_VALID}, po()), expected_status=201
        )
        assert label["udi_pi"] == "LOT-LT-UD-EXP-20270602", (
            f"provisional expiry 2027-06-02 must appear as EXP-20270602, got {label['udi_pi']}"
        )
        assert label["label_revision"] == "A"
        assert label["status"] == "DRAFT"


class TestLabelLifecycleGates:
    def _lot_with_label(self, prefix):
        line = create_line(f"L-{prefix.removeprefix('DEV-')}")
        dmr = create_approved_dmr(device_code=prefix)
        protocol = create_protocol(f"VP-{prefix.removeprefix('DEV-')}", dmr["id"], line["id"])
        lot = create_lot("LT-" + prefix.removeprefix("DEV-"), dmr["id"], protocol["id"])
        return dmr, protocol, lot

    def test_label_approve_revision_mismatch(self, api):
        """PRD section 3.6: "the label's `label_revision` must equal the
        `revision_code` of the currently `APPROVED` revision of the lot's
        device-code family (`ERR_LABEL_REVISION_MISMATCH`)".

        Design: Corner/endpoints/label_approve_revision_mismatch
        """
        dmr_a, _protocol, lot = self._lot_with_label("DEV-LR")
        label = create_label(lot["id"], UDI_VALID)
        dmr_b = create_dmr_revision(dmr_a, revision_code="B", shelf_life_claim_months=24)
        approve_dmr(dmr_b["id"])

        resp = api.approve_label(label["id"], qm())
        validate_error(resp, ApiErrorId.ERR_LABEL_REVISION_MISMATCH)

    def test_label_second_active_conflict(self, api):
        """PRD section 3.6: "no other label of the same lot may be `APPROVED` or
        `PRINTED` (`ERR_ACTIVE_LABEL_EXISTS`)".

        Design: Corner/endpoints/label_second_active_conflict
        """
        _dmr, _protocol, lot = self._lot_with_label("DEV-LA")
        label1 = create_label(lot["id"], UDI_VALID)
        label2 = create_label(lot["id"], UDI_VALID_ALT)
        approve_label(label1["id"])

        resp = api.approve_label(label2["id"], qm())
        validate_error(resp, ApiErrorId.ERR_ACTIVE_LABEL_EXISTS)
        current = validate_success(api.get_label(label2["id"], qm()))
        assert current["status"] == "DRAFT"

    def test_label_print_requires_completed_lot(self, api):
        """PRD section 3.6: "A `ProductionOperator` then prints an `APPROVED`
        label once the lot is `COMPLETED` (`ERR_LOT_NOT_COMPLETED`)".

        Design: Corner/endpoints/label_print_requires_completed_lot
        """
        _dmr, _protocol, lot = self._lot_with_label("DEV-LP")
        label = create_label(lot["id"], UDI_VALID)
        approve_label(label["id"])

        resp = api.print_label(label["id"], po())
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_COMPLETED)
        current = validate_success(api.get_label(label["id"], qm()))
        assert current["status"] == "APPROVED"
        assert current.get("printed_at") is None

    def test_label_void_terminal_lockdown(self, api):
        """PRD section 3.6: "Voiding moves a label from `DRAFT`, `APPROVED`, or
        `PRINTED` to the terminal `VOID`: a `QualityManager` voids manually with
        `void_reason` `MANUAL`" — and PRD section 2.10 step 7: "terminal states
        accept nothing (`ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/label_void_terminal_lockdown
        """
        _dmr, _protocol, lot = self._lot_with_label("DEV-LV")
        label = create_label(lot["id"], UDI_VALID)
        voided = validate_success(api.void_label(label["id"], qm()))
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "MANUAL"

        resp = api.approve_label(label["id"], qm())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestLotScrapLabelCascade:
    def test_lot_terminal_scrap_lockdown(self, api):
        """PRD section 3.6: "`SCRAPPED` is terminal." and "the lot's labels in
        `DRAFT`, `APPROVED`, or `PRINTED` are voided with `void_reason`
        `LOT_SCRAPPED`" — complete and release on a scrapped lot are undeclared
        transitions (`ERR_INVALID_STATE_TRANSITION`).

        Design: Corner/state_machines/lot_terminal_scrap_lockdown
        """
        stack = create_validated_stack("DEV-SC")
        qs = create_qualified_supplier("SUP-SC", "Scrap Co")
        part = create_part(qs["supplier"]["id"], "PN-SC", description="shell", receive_qty=100)
        lot = create_completed_lot(stack, part, lot_number="LT-SC", supplier_lot_number="SL-SC")
        label = create_label(lot["id"], UDI_VALID)

        scrapped = validate_success(api.scrap_lot(lot["id"], qe()))
        assert scrapped["disposition_status"] == "SCRAPPED"

        resp = api.complete_lot(lot["id"], po())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp = api.release_lot(lot["id"], qm())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        reloaded_label = validate_success(api.get_label(label["id"], qm()))
        assert reloaded_label["status"] == "VOID"
        assert reloaded_label["void_reason"] == "LOT_SCRAPPED"
