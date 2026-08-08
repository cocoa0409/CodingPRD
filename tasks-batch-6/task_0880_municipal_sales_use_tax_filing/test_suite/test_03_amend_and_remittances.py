"""Amend/re-file cycle, remittance application, un-apply cascade, partition invariant."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    make_taxpayer_headers,
    create_active_taxpayer, create_jurisdiction, create_draft_return,
    file_return, create_filed_return, set_clock,
    setup_active_taxpayer_with_filed_return, create_remittance, apply_remittance,
    create_return_line, get_return,
)


def _amend(api, taxpayer_id, return_id, version, jurisdiction_id, gross_sales_cents=500000):
    line = create_return_line(jurisdiction_id, gross_sales_cents=gross_sales_cents)
    return api.amend_return(
        return_id,
        {"expected_return_version": version, "lines": [line]},
        make_taxpayer_headers(taxpayer_id),
    )


def test_return_amend_refile_status_cycle(api):
    """PRD §3.4: "Amendment moves a return from `FILED` to `AMENDING`".
    PRD §3.4: "An amended return re-files through the same filing action, transitioning
    `AMENDING → FILED`, which recomputes `total_taxable_cents`, `tax_due_cents`,
    `vendor_discount_cents`, and `net_return_due_cents` from the amended lines".

    Design: Difficulty/non_linear_state_machine/return_amend_refile_cycle
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    amended = validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))
    assert amended["status"] == "AMENDING"
    refiled = file_return(api, tp["id"], filed["id"])
    assert refiled["status"] == "FILED"


def test_return_amend_refile_recomputes_tax(api):
    """PRD §3.4: "An amended return re-files through the same filing action, transitioning
    `AMENDING → FILED`, which recomputes `total_taxable_cents`, `tax_due_cents`,
    `vendor_discount_cents`, and `net_return_due_cents` from the amended lines".

    Design: Difficulty/non_linear_state_machine/return_amend_refile_cycle
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    filed = create_filed_return(api, tp["id"], lines=[line])
    validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"],
                            gross_sales_cents=500000))
    refiled = file_return(api, tp["id"], filed["id"])
    assert refiled["tax_due_cents"] == 42500


def test_amend_unapplies_remittance_return_state(api):
    """PRD §3.4: "Amendment has a compensating cascade: because the return is leaving
    `FILED`, every `Remittance` whose `applied_return_id` points at this return is
    un-applied — its `applied_amount_cents` resets to 0, its `unapplied_amount_cents`
    returns to the full `amount_cents`, and its `applied_return_id` clears to null."

    Design: Difficulty/transitive_cascade/return_amend_cascades_remittance_unapply
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    tp, jur, filed = setup_active_taxpayer_with_filed_return(api)
    assert filed["net_return_due_cents"] == 68000
    rem = create_remittance(api, tp["id"], amount_cents=100000)
    apply_remittance(api, rem["id"], filed["id"], 68000, tp["id"])
    amended = validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))
    assert amended["status"] == "AMENDING"
    rem_after = validate_success(api.get_remittance(rem["id"], make_taxpayer_headers(tp["id"])))
    assert rem_after["applied_amount_cents"] == 0


def test_amend_unapplies_remittance_restores_unapplied_and_clears_link(api):
    """PRD §3.4: "Amendment has a compensating cascade: because the return is leaving
    `FILED`, every `Remittance` whose `applied_return_id` points at this return is
    un-applied — its `applied_amount_cents` resets to 0, its `unapplied_amount_cents`
    returns to the full `amount_cents`, and its `applied_return_id` clears to null."

    Design: Difficulty/transitive_cascade/return_amend_cascades_remittance_unapply
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    tp, jur, filed = setup_active_taxpayer_with_filed_return(api)
    rem = create_remittance(api, tp["id"], amount_cents=100000)
    apply_remittance(api, rem["id"], filed["id"], 68000, tp["id"])
    validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))
    rem_after = validate_success(api.get_remittance(rem["id"], make_taxpayer_headers(tp["id"])))
    assert rem_after["unapplied_amount_cents"] == 100000
    assert rem_after["applied_return_id"] is None


def test_partition_conserved_after_apply(api):
    """PRD §3.4: "On success the remittance's `applied_amount_cents` increases by the
    requested amount, its `unapplied_amount_cents` becomes `amount_cents` minus the new
    `applied_amount_cents`".
    PRD §3.4: "The invariant `applied_amount_cents + unapplied_amount_cents == amount_cents`
    holds at all times."

    Design: Difficulty/compensating_invariant/remittance_apply_unapply_conserves_amount_partition
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    tp, jur, filed = setup_active_taxpayer_with_filed_return(api)
    rem = create_remittance(api, tp["id"], amount_cents=100000)
    applied = apply_remittance(api, rem["id"], filed["id"], 68000, tp["id"])
    assert applied["applied_amount_cents"] == 68000
    assert applied["unapplied_amount_cents"] == 32000
    assert applied["applied_amount_cents"] + applied["unapplied_amount_cents"] == 100000


def test_partition_conserved_after_unapply(api):
    """PRD §3.4: "The invariant `applied_amount_cents + unapplied_amount_cents == amount_cents`
    holds at all times."
    PRD §3.4: "every `Remittance` whose `applied_return_id` points at this return is
    un-applied — its `applied_amount_cents` resets to 0, its `unapplied_amount_cents`
    returns to the full `amount_cents`".

    Design: Difficulty/compensating_invariant/remittance_apply_unapply_conserves_amount_partition
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    tp, jur, filed = setup_active_taxpayer_with_filed_return(api)
    rem = create_remittance(api, tp["id"], amount_cents=100000)
    apply_remittance(api, rem["id"], filed["id"], 68000, tp["id"])
    validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))
    rem_after = validate_success(api.get_remittance(rem["id"], make_taxpayer_headers(tp["id"])))
    assert rem_after["applied_amount_cents"] == 0
    assert rem_after["unapplied_amount_cents"] == 100000
    assert rem_after["amount_cents"] == 100000


def test_apply_to_draft_return_reports_state_not_fiscal(api):
    """PRD §3.4: "The target return must be in `FILED` status — this state check
    (`ERR_RETURN_NOT_FILED`) is evaluated before the fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/apply_state_beats_fiscal_on_draft_return
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    ret = create_draft_return(api, tp["id"], jurisdiction_id=jur["id"])
    rem = create_remittance(api, tp["id"], amount_cents=100)
    resp = api.apply_remittance(
        rem["id"],
        {"applied_return_id": ret["id"], "apply_amount_cents": 999999},
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FILED, expected_status=409)


def test_apply_to_amending_return_reports_state_not_fiscal(api):
    """PRD §3.4: "The target return must be in `FILED` status — this state check
    (`ERR_RETURN_NOT_FILED`) is evaluated before the fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/apply_state_beats_fiscal_on_draft_return
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"])
    validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))  # -> AMENDING
    rem = create_remittance(api, tp["id"], amount_cents=100)
    resp = api.apply_remittance(
        rem["id"],
        {"applied_return_id": filed["id"], "apply_amount_cents": 999999},
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FILED, expected_status=409)


def test_overapplication_rejected_on_filed_return(api):
    """PRD §3.4: "The requested `apply_amount_cents` may exceed neither the remittance's
    own `unapplied_amount_cents` nor that remaining room; either excess is rejected with
    `ERR_OVERAPPLICATION` (HTTP 422)."

    Design: Corner/validations/overapplication_rejected_on_filed_return
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    tp, jur, filed = setup_active_taxpayer_with_filed_return(api)
    assert filed["net_return_due_cents"] == 68000
    rem = create_remittance(api, tp["id"], amount_cents=200000)
    resp = api.apply_remittance(
        rem["id"],
        {"applied_return_id": filed["id"], "apply_amount_cents": 100000},
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OVERAPPLICATION, expected_status=422)


def test_apply_to_missing_return_not_found(api):
    """PRD §2.9: "an unresolved return yields `ERR_RETURN_NOT_FOUND`".

    Design: Corner/endpoints/apply_return_not_found
    """
    tp = create_active_taxpayer(api)
    rem = create_remittance(api, tp["id"], amount_cents=5000, remittance_type="PREPAYMENT")
    resp = api.apply_remittance(
        rem["id"],
        {"applied_return_id": NON_EXISTENT_UUID, "apply_amount_cents": 1000},
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND, expected_status=404)
