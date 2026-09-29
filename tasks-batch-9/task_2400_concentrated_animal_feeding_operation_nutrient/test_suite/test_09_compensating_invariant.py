"""Reversals that must undo every forward effect exactly: voiding an application
record and cancelling an uncommitted-yet transfer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_null,
    assert_quantity,
    assert_state,
    assert_storage_balance,
)
from test_helpers.fixtures import initiate_transfer, record_application, setup_ready_operation
from test_helpers.test_users import ADMIN_HEADERS


def _recorded_then_voided():
    """A ready operation whose single 300,000-gallon application has been voided
    by a compliance administrator."""
    ctx = setup_ready_operation()
    ctx["event"] = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        applied_on="2026-07-20T00:00:00Z",
    )
    ctx["voided"] = validate_success(
        api_client.void_application_event(ctx["event"]["id"], ADMIN_HEADERS), 200
    )
    return ctx


def _committed_transfer():
    """A ready operation holding a 200,000-gallon reservation against its
    lagoon."""
    ctx = setup_ready_operation(with_hauler=True)
    ctx["transfer"] = initiate_transfer(
        ctx["operation"]["id"],
        ctx["storage"]["id"],
        ctx["hauler"]["id"],
        ctx["operator_headers"],
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )
    return ctx


def test_voiding_credits_both_ledgers_back_to_their_pre_event_values():
    """The allowance ledger and the volume ledger both return to exactly what they
    held before the record existed, while the record keeps its computed nutrients.

    PRD: "The budget's `applied_gallons_to_date` is credited down by `gallons_applied` and its `remaining_gallons` recomputed, restoring the invariant that applied plus remaining equals `allowable_total_gallons`."
    PRD: "The source structure's `cumulative_outflow_gallons` is credited down by `gallons_applied` and its `current_volume_gallons` and `available_capacity_gallons` recomputed, restoring the storage volume-balance invariant, with `days_of_storage_available` following."

    Design: Difficulty/compensating_invariant/void_application_restores_budget_and_storage_ledgers
    """
    ctx = _recorded_then_voided()
    headers = ctx["operator_headers"]

    assert_state(ctx["voided"], "event_status", "VOIDED")
    assert_quantity(ctx["voided"]["n_applied_lbs"], 4680.00, "n_applied_lbs")
    assert_quantity(ctx["voided"]["p2o5_applied_lbs"], 3000.00, "p2o5_applied_lbs")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)
    assert_state(budget, "budget_status", "ACTIVE")

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_storage_balance(
        storage,
        intake=1000000.00,
        outflow=0.00,
        precipitation=0.00,
        current=1000000.00,
        committed=0.00,
        available=3488300.00,
    )
    assert storage["days_of_storage_available"] == 377, (
        "the released headroom restores 377 days of storage, got "
        f"{storage['days_of_storage_available']}"
    )


def test_voiding_re_derives_the_field_stamp_and_the_records_basis_totals():
    """With no surviving record the field's last application reverts to null and
    the records-basis figures fall back to zero, even though the design figure is
    untouched.

    PRD: "The field's `last_application_on` is recomputed from the remaining non-voided records, and the operation's `recorded_annual_manure_gallons` is recomputed as well — the voided volume leaves the records-basis total, which is exactly why that figure and the design figure can diverge."
    PRD: "A field's `last_application_on` starts null and thereafter tracks the `applied_on` of the most recent non-voided land application recorded on that field — that is, the latest among records whose `event_status` is `RECORDED` or `VERIFIED` — reverting to null when no such record remains."
    PRD: "The summary response also breaks those two contributions out as `recorded_land_applied_gallons` and `recorded_transferred_gallons`, reports `total_n_applied_lbs` and `total_p2o5_applied_lbs` for the year, and echoes `design_annual_manure_gallons`, `design_storage_days` and `compliance_posture`."

    Design: Difficulty/compensating_invariant/void_application_restores_budget_and_storage_ledgers
    """
    ctx = _recorded_then_voided()
    headers = ctx["operator_headers"]

    field = validate_success(api_client.get_field(ctx["field"]["id"], headers), 200)
    assert_null(field, "last_application_on")

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], headers), 200
    )
    assert_quantity(
        operation["recorded_annual_manure_gallons"],
        0.00,
        "recorded_annual_manure_gallons",
    )

    summary = validate_success(
        api_client.get_operation_nutrient_summary(
            ctx["operation"]["id"], headers, {"basis": "RECORDS_BASIS", "year": 2026}
        ),
        200,
    )
    assert_quantity(
        summary["recorded_land_applied_gallons"], 0.00, "recorded_land_applied_gallons"
    )
    assert_quantity(summary["total_n_applied_lbs"], 0.00, "total_n_applied_lbs")
    assert_quantity(
        summary["design_annual_manure_gallons"], 3374298.00, "design_annual_manure_gallons"
    )


def test_cancelling_an_initiated_transfer_releases_the_reservation():
    """The reservation is visible as reduced headroom before the cancellation and
    is given straight back afterwards.

    PRD: "Cancelling an `INITIATED` transfer releases `gallons_transferred` from the structure's `committed_outflow_gallons`, restoring `available_capacity_gallons` to its pre-transfer value."
    PRD: "`current_volume_gallons` is always `cumulative_intake_gallons` plus `precipitation_adjustment_gallons` less `cumulative_outflow_gallons`, and `available_capacity_gallons` is always `operating_capacity_gallons` less `current_volume_gallons` less `committed_outflow_gallons`, both rounded half up to 2 decimal places."

    Design: Difficulty/compensating_invariant/cancel_transfer_restores_storage_commitment_balance
    """
    ctx = _committed_transfer()
    headers = ctx["operator_headers"]

    before = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_quantity(
        before["committed_outflow_gallons"], 200000.00, "committed_outflow_gallons"
    )
    assert_quantity(
        before["available_capacity_gallons"], 3288300.00, "available_capacity_gallons"
    )

    cancelled = validate_success(
        api_client.cancel_manure_transfer(ctx["transfer"]["id"], headers), 200
    )
    assert_state(cancelled, "transfer_status", "CANCELLED")

    after = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_quantity(
        after["committed_outflow_gallons"], 0.00, "committed_outflow_gallons"
    )
    assert_quantity(
        after["available_capacity_gallons"], 3488300.00, "available_capacity_gallons"
    )


def test_cancelling_before_acknowledgement_moves_no_liquid_at_all():
    """A reservation that was never acknowledged never debited the tank, so the
    contents and the outflow total are untouched and only the day count moves.

    PRD: "A structure's own `days_of_storage_available` is the greater of zero and its `available_capacity_gallons`, divided by that effective daily production and floored to a whole day, so the figure shrinks as the structure fills and grows again when a transfer is suspended or cancelled."
    PRD: "The transfer is written with `transfer_status` of `INITIATED` and `recipient_ack_signed_at` null, and `gallons_transferred` is added to the source structure's `committed_outflow_gallons`, after which `available_capacity_gallons` and `days_of_storage_available` are recomputed."

    Design: Difficulty/compensating_invariant/cancel_transfer_restores_storage_commitment_balance
    """
    ctx = _committed_transfer()
    headers = ctx["operator_headers"]

    before = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert before["days_of_storage_available"] == 355, (
        "the outstanding reservation leaves 355 days of storage, got "
        f"{before['days_of_storage_available']}"
    )

    validate_success(
        api_client.cancel_manure_transfer(ctx["transfer"]["id"], headers), 200
    )

    after = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_storage_balance(
        after,
        intake=1000000.00,
        outflow=0.00,
        precipitation=0.00,
        current=1000000.00,
        committed=0.00,
        available=3488300.00,
    )
    assert after["days_of_storage_available"] == 377, (
        "releasing the reservation grows the day count back to 377, got "
        f"{after['days_of_storage_available']}"
    )
