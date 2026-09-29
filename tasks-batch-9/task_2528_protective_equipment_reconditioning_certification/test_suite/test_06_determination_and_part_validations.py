"""Determination-signing and replacement-part suitability validation rules.

Each test walks a unit from the dock all the way to the rig — or to an open
draft repair order — through the documented endpoints only, and then provokes
exactly one rule of the determination or part-suitability family.
"""
from test_helpers import (
    INSPECTOR_1,
    PASS_IMPACTS,
    REPAIR_IMPACTS,
    TECHNICIAN_1,
    ApiErrorId,
    api_client,
    assert_part_stock_conserved,
    create_model,
    create_part,
    determine_payload,
    open_repair_order,
    part_line_payload,
    read_part,
    read_repair_order,
    read_shell_test,
    read_unit,
    setup_repair_pending_unit,
    setup_tested_units,
    validate_error,
)


def test_signing_pass_on_a_unit_flagged_for_condemnation_is_rejected():
    """A condemnation mandate overrides a clean rig result.

    The SHELL inspection measured 6.50 mm against a fail threshold of 6.0, which
    made the unit's rolled-up verdict FAIL and flagged it for condemnation, even
    though the rig then produced a severity index of 300.0 and a computed result
    of PASS. Signing PASS must therefore come back as ERR_CONDEMN_REQUIRED, the
    session must stay COMPLETED with no determination on it, and the unit must
    stay in TESTED so that only a CONDEMN can close it out.

    PRD: "And when the unit's `condemn_required` is true, the only determination
    the inspector may sign is `CONDEMN` — anything else is refused with
    `ERR_CONDEMN_REQUIRED` (HTTP 422)."

    Design: Corner/validations/signing_pass_on_a_unit_flagged_for_condemnation_rejected
    """
    ctx = setup_tested_units(unit_count=1, impacts=PASS_IMPACTS, measurement_value=6.50)
    unit_id = ctx["unit"]["id"]
    session_id = ctx["shell_test"]["id"]
    assert ctx["unit"]["condemn_required"] is True
    assert ctx["unit"]["inspection_verdict_summary"] == "FAIL"
    assert ctx["shell_test"]["computed_result"] == "PASS"

    response = api_client.determine_shell_test(
        session_id, determine_payload("PASS"), INSPECTOR_1
    )
    validate_error(response, ApiErrorId.ERR_CONDEMN_REQUIRED.value, 422)

    session = read_shell_test(session_id)
    assert session["status"] == "COMPLETED"
    assert session["computed_result"] == "PASS"
    assert session["severity_index"] == 300.0
    assert session["determination"] is None
    assert session["override_reason"] is None
    assert session["determined_by_user_id"] is None

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "TESTED"
    assert unit["condemn_required"] is True
    assert unit["inspection_verdict_summary"] == "FAIL"
    assert unit["custody_status"] == "AT_PLANT"


def test_a_determination_contradicting_the_rig_without_a_reason_is_rejected():
    """Departing from the machine result demands a written justification.

    The rig computed PASS on a severity index of 300.0 and the unit is not
    flagged for condemnation, so signing REPAIR with no accompanying
    override_reason must come back as ERR_DETERMINATION_MISMATCH and leave the
    session COMPLETED with no determination recorded.

    PRD: "If the two differ and no `override_reason` accompanies the request, the
    signature is refused with `ERR_DETERMINATION_MISMATCH` (HTTP 422)."

    Design: Corner/validations/a_determination_that_contradicts_the_rig_without_a_reason_rejected
    """
    ctx = setup_tested_units(unit_count=1, impacts=PASS_IMPACTS)
    unit_id = ctx["unit"]["id"]
    session_id = ctx["shell_test"]["id"]
    assert ctx["shell_test"]["computed_result"] == "PASS"
    assert ctx["unit"]["condemn_required"] is False

    response = api_client.determine_shell_test(
        session_id, determine_payload("REPAIR"), INSPECTOR_1
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_MISMATCH.value, 422)

    session = read_shell_test(session_id)
    assert session["status"] == "COMPLETED"
    assert session["computed_result"] == "PASS"
    assert session["severity_index"] == 300.0
    assert session["determination"] is None
    assert session["override_reason"] is None
    assert session["determined_by_user_id"] is None

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "TESTED"
    assert unit["current_si"] == 300.0


def test_an_override_cannot_downgrade_a_repair_result_to_pass():
    """An override may only make the verdict harsher, never gentler.

    Readings of 300, 340 and 290 g weight to a severity index of 310.0, which
    lands in the repair band, so the rig computed REPAIR. Signing PASS — the
    least severe verdict — even with a written reason must come back as
    ERR_DETERMINATION_UPGRADE_FORBIDDEN, and neither the determination nor the
    override reason may be recorded on the session.

    PRD: "If an `override_reason` is present but the signed determination is
    *less* severe than `computed_result` under the severity ordering in which
    `PASS` is least severe, `REPAIR` more severe, and `CONDEMN` most severe, the
    signature is refused with `ERR_DETERMINATION_UPGRADE_FORBIDDEN` (HTTP 422)."

    Design: Corner/validations/an_override_cannot_downgrade_a_repair_result_to_pass
    """
    ctx = setup_tested_units(unit_count=1, impacts=REPAIR_IMPACTS)
    unit_id = ctx["unit"]["id"]
    session_id = ctx["shell_test"]["id"]
    assert ctx["shell_test"]["severity_index"] == 310.0
    assert ctx["shell_test"]["computed_result"] == "REPAIR"

    response = api_client.determine_shell_test(
        session_id,
        determine_payload("PASS", override_reason="looked fine on the bench"),
        INSPECTOR_1,
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_UPGRADE_FORBIDDEN.value, 422)

    session = read_shell_test(session_id)
    assert session["status"] == "COMPLETED"
    assert session["severity_index"] == 310.0
    assert session["computed_result"] == "REPAIR"
    assert session["determination"] is None
    assert session["override_reason"] is None
    assert session["determined_by_user_id"] is None

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "TESTED"
    assert unit["current_si"] == 310.0


def test_a_part_line_from_another_models_catalogue_is_rejected():
    """A cage part is only installable on the model it was booked in against.

    The unit was identified as the polycarbonate SF-2026 shell, while the part
    line points at a genuine, in-stock, manufacturer-approved liner booked in
    against a second model AB-2026. The append must therefore come back as
    ERR_PART_MODEL_MISMATCH, the order must keep zero part lines and a zero
    reserved subtotal, and the other model's stock buckets must not move.

    PRD: "a part whose `model_spec_id` differs from the unit's `model_spec_id` is
    refused with `ERR_PART_MODEL_MISMATCH` (HTTP 422)"

    Design: Corner/validations/a_part_line_from_another_models_catalogue_rejected
    """
    ctx = setup_repair_pending_unit()
    other_model = create_model(model_code="AB-2026", shell_material="ABS")
    other_part = create_part(
        other_model["id"],
        part_number="PN-ABS-LINER",
        component_code="LINER",
        oem_approved=True,
        unit_price_cents=3100,
        received_qty=6,
    )
    order = open_repair_order(ctx["unit"]["id"])
    assert order["status"] == "DRAFT"
    order_version = order["version"]

    response = api_client.add_repair_order_part_line(
        order["id"],
        part_line_payload(other_part["id"], 1, lot_code="LOT-9"),
        TECHNICIAN_1,
    )
    validate_error(response, ApiErrorId.ERR_PART_MODEL_MISMATCH.value, 422)

    reread = read_repair_order(order["id"])
    assert reread["status"] == "DRAFT"
    assert reread["part_lines"] == []
    assert reread["reserved_parts_cents"] == 0
    assert reread["installed_parts_cents"] == 0
    assert reread["version"] == order_version

    part = read_part(other_part["id"])
    assert part["received_qty"] == 6
    assert part["on_hand_qty"] == 6
    assert part["reserved_qty"] == 0
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)

    assert read_unit(ctx["unit"]["id"])["recon_status"] == "REPAIR_PENDING"


def test_a_part_line_for_a_non_oem_part_is_rejected():
    """Recertification consumes only components the manufacturer has approved.

    The part is booked in against the very model the unit was identified as, for
    the very component code under repair, and it is in stock — the sole defect is
    that its oem_approved flag is false. The append must therefore come back as
    ERR_PART_NOT_APPROVED, with the order still empty and the grey-market stock
    untouched.

    PRD: "a part whose `oem_approved` is false is refused with
    `ERR_PART_NOT_APPROVED` (HTTP 422)"

    Design: Corner/validations/a_part_line_for_a_non_oem_part_rejected
    """
    ctx = setup_repair_pending_unit()
    grey_part = create_part(
        ctx["model"]["id"],
        part_number="PN-GREY-SHELL",
        component_code="SHELL",
        oem_approved=False,
        unit_price_cents=2900,
        received_qty=5,
    )
    order = open_repair_order(ctx["unit"]["id"])
    assert order["status"] == "DRAFT"
    order_version = order["version"]

    response = api_client.add_repair_order_part_line(
        order["id"],
        part_line_payload(grey_part["id"], 1, lot_code="LOT-7"),
        TECHNICIAN_1,
    )
    validate_error(response, ApiErrorId.ERR_PART_NOT_APPROVED.value, 422)

    reread = read_repair_order(order["id"])
    assert reread["status"] == "DRAFT"
    assert reread["part_lines"] == []
    assert reread["reserved_parts_cents"] == 0
    assert reread["installed_parts_cents"] == 0
    assert reread["version"] == order_version

    part = read_part(grey_part["id"])
    assert part["received_qty"] == 5
    assert part["on_hand_qty"] == 5
    assert part["reserved_qty"] == 0
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)

    assert read_unit(ctx["unit"]["id"])["recon_status"] == "REPAIR_PENDING"
