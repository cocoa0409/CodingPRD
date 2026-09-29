"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
and uses the lenient `get_success_data()` validator, so a broken precondition
surfaces as a clear setup failure instead of a confusing assertion error.

Identity threading is mandatory: a `SellerOperator` call always carries the acting
`SellerAccount.id` and an `FcOperator` call always carries the acting
`FulfillmentCenter.id`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_UTC
from .factories import (
    fulfillment_center_payload,
    inbound_plan_payload,
    line_item_payload,
    multi_channel_order_payload,
    receipt_payload,
    received_line,
    reimbursement_claim_payload,
    removal_order_payload,
    restock_quota_payload,
    seller_payload,
    sku_listing_payload,
    unfulfillable_classification_payload,
    velocity_forecast_payload,
)
from .test_users import (
    ADJUDICATOR,
    ADMIN,
    make_fc_operator_headers,
    make_seller_operator_headers,
)


# --------------------------------------------------------------------------- #
# Tier 1 — single-step primitives
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Answers with the resulting `current_utc`."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def register_seller(**overrides) -> dict:
    return get_success_data(api_client.create_seller(seller_payload(**overrides), ADMIN))


def register_fulfillment_center(**overrides) -> dict:
    return get_success_data(
        api_client.create_fulfillment_center(fulfillment_center_payload(**overrides), ADMIN)
    )


def create_listing(seller_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sku_listing(
            sku_listing_payload(seller_id, **overrides),
            make_seller_operator_headers(seller_id),
        )
    )


def open_quota(seller_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_restock_quota(seller_id, restock_quota_payload(**overrides), ADMIN)
    )


def read_seller(seller_id: str) -> dict:
    return get_success_data(
        api_client.get_seller(seller_id, make_seller_operator_headers(seller_id))
    )


def seller_version(seller_id: str) -> int:
    return read_seller(seller_id)["version"]


def read_fulfillment_center(fc_id: str) -> dict:
    return get_success_data(
        api_client.get_fulfillment_center(fc_id, make_fc_operator_headers(fc_id))
    )


def set_receiving_posture(fc_id: str, **payload) -> dict:
    """Revise a centre's `receiving_status` and/or `receiving_capacity_units_per_window`."""
    return get_success_data(
        api_client.update_fulfillment_center(fc_id, payload, make_fc_operator_headers(fc_id))
    )


def read_listing(listing_id: str, seller_id: str) -> dict:
    return get_success_data(
        api_client.get_sku_listing(listing_id, make_seller_operator_headers(seller_id))
    )


def read_plan(plan_id: str, seller_id: str) -> dict:
    return get_success_data(
        api_client.get_inbound_shipment_plan(plan_id, make_seller_operator_headers(seller_id))
    )


def read_lot(lot_id: str, seller_id: str) -> dict:
    return get_success_data(
        api_client.get_inventory_lot(lot_id, make_seller_operator_headers(seller_id))
    )


def lot_version(lot_id: str, seller_id: str) -> int:
    return read_lot(lot_id, seller_id)["version"]


def read_quota(quota_id: str, seller_id: str) -> dict:
    """Read one quota period back out of the seller's quota list (newest first)."""
    body = get_success_data(
        api_client.list_restock_quotas(
            seller_id, make_seller_operator_headers(seller_id), params={"limit": 100}
        )
    )
    for row in body:
        if row["id"] == quota_id:
            return row
    raise AssertionError(f"Setup step failed: quota {quota_id} not found for seller {seller_id}")


def newest_quota(seller_id: str) -> dict:
    """The seller's most recent quota period — quota lists are newest first."""
    body = get_success_data(
        api_client.list_restock_quotas(seller_id, make_seller_operator_headers(seller_id))
    )
    assert body, "Setup step failed: seller has no quota periods"
    return body[0]


def read_removal_order(removal_order_id: str, seller_id: str) -> dict:
    return get_success_data(
        api_client.get_removal_order(
            removal_order_id, make_seller_operator_headers(seller_id)
        )
    )


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_reimbursement_claim(claim_id, ADJUDICATOR))


# --------------------------------------------------------------------------- #
# Tier 2 — plan lifecycle steps
# --------------------------------------------------------------------------- #
def create_plan(
    seller_id: str,
    fc_id: str,
    appointment_window_start: str = "2026-08-10T00:00:00Z",
    appointment_window_end: str = "2026-08-11T00:00:00Z",
    expected_seller_account_version: int = None,
    **overrides,
) -> dict:
    """Draft a plan, quoting the seller's current `version` unless one is supplied."""
    version = (
        expected_seller_account_version
        if expected_seller_account_version is not None
        else seller_version(seller_id)
    )
    return get_success_data(
        api_client.create_inbound_shipment_plan(
            inbound_plan_payload(
                seller_id, fc_id, version,
                appointment_window_start=appointment_window_start,
                appointment_window_end=appointment_window_end,
                **overrides,
            ),
            make_seller_operator_headers(seller_id),
        )
    )


def add_line_item(plan_id: str, seller_id: str, listing_id: str, units: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_line_item(
            plan_id,
            line_item_payload(listing_id, units, **overrides),
            make_seller_operator_headers(seller_id),
        )
    )


def confirm_plan(plan_id: str, seller_id: str, **payload) -> dict:
    return get_success_data(
        api_client.confirm_plan(plan_id, payload, make_seller_operator_headers(seller_id))
    )


def ship_plan(plan_id: str, seller_id: str, **payload) -> dict:
    return get_success_data(
        api_client.ship_plan(plan_id, payload, make_seller_operator_headers(seller_id))
    )


def revert_plan(plan_id: str, seller_id: str, **payload) -> dict:
    return get_success_data(
        api_client.revert_plan_to_draft(plan_id, payload, make_seller_operator_headers(seller_id))
    )


def cancel_plan(plan_id: str, seller_id: str, **payload) -> dict:
    return get_success_data(
        api_client.cancel_plan(plan_id, payload, make_seller_operator_headers(seller_id))
    )


def receive_plan(plan_id: str, fc_id: str, lines: list, **overrides) -> dict:
    """Record a receipt as the destination centre's operator.

    `lines` is a list of (line_item_id, received_units[, unfulfillable_units]) tuples
    or of already-built received-line dicts.
    """
    built = []
    for line in lines:
        if isinstance(line, dict):
            built.append(line)
        else:
            built.append(received_line(*line))
    return get_success_data(
        api_client.receive_plan(
            plan_id, receipt_payload(built, **overrides), make_fc_operator_headers(fc_id)
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2 — lot, removal, claim, forecast and order steps
# --------------------------------------------------------------------------- #
def lots_for_listing(listing_id: str, seller_id: str) -> list:
    return get_success_data(
        api_client.list_inventory_lots(
            make_seller_operator_headers(seller_id),
            params={"sku_listing_id": listing_id, "limit": 100},
        )
    )


def first_lot_for_listing(listing_id: str, seller_id: str) -> dict:
    lots = lots_for_listing(listing_id, seller_id)
    assert lots, f"Setup step failed: no inventory lot exists for listing {listing_id}"
    return lots[0]


def classify_unfulfillable(lot_id: str, fc_id: str, units: int,
                           disposition_reason: str = "CUSTOMER_DAMAGE") -> dict:
    return get_success_data(
        api_client.classify_unfulfillable(
            lot_id,
            unfulfillable_classification_payload(units, disposition_reason),
            make_fc_operator_headers(fc_id),
        )
    )


def request_removal(lot_id: str, seller_id: str, requested_units: int,
                    expected_inventory_lot_version: int = None, **overrides) -> dict:
    version = (
        expected_inventory_lot_version
        if expected_inventory_lot_version is not None
        else lot_version(lot_id, seller_id)
    )
    return get_success_data(
        api_client.create_removal_order(
            removal_order_payload(lot_id, version, requested_units, **overrides),
            make_seller_operator_headers(seller_id),
        )
    )


def complete_removal(removal_order_id: str, fc_id: str, **payload) -> dict:
    return get_success_data(
        api_client.complete_removal_order(
            removal_order_id, payload, make_fc_operator_headers(fc_id)
        )
    )


def cancel_removal(removal_order_id: str, seller_id: str, **payload) -> dict:
    return get_success_data(
        api_client.cancel_removal_order(
            removal_order_id, payload, make_seller_operator_headers(seller_id)
        )
    )


def file_claim(lot_id: str, seller_id: str, claim_type: str, claimed_units: int,
               evidence_document_count: int, evidence_reference: str = "CASE-1",
               **overrides) -> dict:
    return get_success_data(
        api_client.file_reimbursement_claim(
            reimbursement_claim_payload(
                lot_id, claim_type, claimed_units,
                evidence_document_count, evidence_reference, **overrides,
            ),
            make_seller_operator_headers(seller_id),
        )
    )


def request_claim_info(claim_id: str, information_request_note: str = "Send the carrier POD") -> dict:
    return get_success_data(
        api_client.request_claim_info(
            claim_id, {"information_request_note": information_request_note}, ADJUDICATOR
        )
    )


def resubmit_claim(claim_id: str, seller_id: str, evidence_document_count: int,
                   evidence_reference: str) -> dict:
    return get_success_data(
        api_client.resubmit_claim(
            claim_id,
            {
                "evidence_document_count": evidence_document_count,
                "evidence_reference": evidence_reference,
            },
            make_seller_operator_headers(seller_id),
        )
    )


def decide_claim(claim_id: str, decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(api_client.decide_claim(claim_id, payload, ADJUDICATOR))


def create_forecast(listing_id: str, seller_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_velocity_forecast(
            listing_id,
            velocity_forecast_payload(**overrides),
            make_seller_operator_headers(seller_id),
        )
    )


def place_multi_channel_order(seller_id: str, listing_id: str, units: int,
                              billable_weight_lb: float, destination_zone: str,
                              fulfillment_channel: str, self_fulfilled_cost_cents: int,
                              **overrides) -> dict:
    return get_success_data(
        api_client.create_multi_channel_order(
            multi_channel_order_payload(
                listing_id, units, billable_weight_lb, destination_zone,
                fulfillment_channel, self_fulfilled_cost_cents, **overrides,
            ),
            make_seller_operator_headers(seller_id),
        )
    )


def run_storage_billing(run_note: str = None) -> dict:
    payload = {} if run_note is None else {"run_note": run_note}
    return get_success_data(api_client.create_storage_billing_run(payload, ADMIN))


# --------------------------------------------------------------------------- #
# Tier 3 — the shared onboarding baseline
# --------------------------------------------------------------------------- #
def setup_baseline(clock: str = CLOCK_STARTUP_UTC, seller=None, center=None,
                   listing=None, quota=None, with_quota: bool = True,
                   with_listing: bool = True) -> dict:
    """Clock + seller + fulfillment centre + listing + ACTIVE quota period.

    Returns {"seller", "center", "listing", "quota", "seller_id", "fc_id",
    "listing_id", "quota_id", "seller_headers", "fc_headers"}.
    """
    if clock is not None:
        set_clock(clock)
    seller_row = register_seller(**(seller or {}))
    center_row = register_fulfillment_center(**(center or {}))
    listing_row = create_listing(seller_row["id"], **(listing or {})) if with_listing else None
    quota_row = open_quota(seller_row["id"], **(quota or {})) if with_quota else None
    return {
        "seller": seller_row,
        "center": center_row,
        "listing": listing_row,
        "quota": quota_row,
        "seller_id": seller_row["id"],
        "fc_id": center_row["id"],
        "listing_id": listing_row["id"] if listing_row else None,
        "quota_id": quota_row["id"] if quota_row else None,
        "seller_headers": make_seller_operator_headers(seller_row["id"]),
        "fc_headers": make_fc_operator_headers(center_row["id"]),
    }


def create_confirmed_plan(seller_id: str, fc_id: str, listing_id: str, units: int,
                          appointment_window_start: str = "2026-08-10T00:00:00Z",
                          appointment_window_end: str = "2026-08-11T00:00:00Z",
                          line_overrides: dict = None) -> dict:
    """Draft a plan with one line item and confirm it. Returns {"plan", "line_item"}."""
    plan = create_plan(seller_id, fc_id, appointment_window_start, appointment_window_end)
    line = add_line_item(plan["id"], seller_id, listing_id, units, **(line_overrides or {}))
    plan = confirm_plan(plan["id"], seller_id)
    return {"plan": plan, "line_item": line}


def create_in_transit_plan(seller_id: str, fc_id: str, listing_id: str, units: int,
                           appointment_window_start: str = "2026-08-10T00:00:00Z",
                           appointment_window_end: str = "2026-08-11T00:00:00Z",
                           line_overrides: dict = None) -> dict:
    """Draft → confirm → ship. Returns {"plan", "line_item"}."""
    built = create_confirmed_plan(
        seller_id, fc_id, listing_id, units,
        appointment_window_start, appointment_window_end, line_overrides,
    )
    built["plan"] = ship_plan(built["plan"]["id"], seller_id)
    return built


# --------------------------------------------------------------------------- #
# Tier 4 — accumulation / threshold targeting
# --------------------------------------------------------------------------- #
def setup_received_lot(units: int = 100, unfulfillable_units: int = 0,
                       appointment_window_start: str = "2026-08-01T00:00:00Z",
                       appointment_window_end: str = "2026-08-02T00:00:00Z",
                       line_overrides: dict = None, **baseline_kwargs) -> dict:
    """Baseline + a plan fully received into one lot.

    Adds {"plan", "line_item", "lot", "lot_id"} to the baseline dict.
    """
    ctx = setup_baseline(**baseline_kwargs)
    built = create_in_transit_plan(
        ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], units,
        appointment_window_start, appointment_window_end, line_overrides,
    )
    receive_plan(
        built["plan"]["id"], ctx["fc_id"],
        [(built["line_item"]["id"], units - unfulfillable_units, unfulfillable_units)],
    )
    lot = first_lot_for_listing(ctx["listing_id"], ctx["seller_id"])
    ctx.update({
        "plan": read_plan(built["plan"]["id"], ctx["seller_id"]),
        "line_item": built["line_item"],
        "lot": lot,
        "lot_id": lot["id"],
    })
    return ctx


def setup_partially_received_plan(declared_units: int, received_units: int,
                                  unfulfillable_units: int = 0,
                                  appointment_window_start: str = "2026-08-01T00:00:00Z",
                                  appointment_window_end: str = "2026-08-02T00:00:00Z",
                                  line_overrides: dict = None,
                                  **baseline_kwargs) -> dict:
    """Baseline + a shipped plan received short, so the lot carries `missing_units`
    and the seller carries `open_discrepancy_units`.

    Adds {"plan", "line_item", "receipt", "lot", "lot_id"} to the baseline dict.
    """
    ctx = setup_baseline(**baseline_kwargs)
    built = create_in_transit_plan(
        ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], declared_units,
        appointment_window_start, appointment_window_end, line_overrides,
    )
    receipt = receive_plan(
        built["plan"]["id"], ctx["fc_id"],
        [(built["line_item"]["id"], received_units, unfulfillable_units)],
    )
    lots = lots_for_listing(ctx["listing_id"], ctx["seller_id"])
    lot = lots[0] if lots else None
    ctx.update({
        "plan": read_plan(built["plan"]["id"], ctx["seller_id"]),
        "line_item": built["line_item"],
        "receipt": receipt,
        "lot": lot,
        "lot_id": lot["id"] if lot else None,
    })
    return ctx


def setup_lot_with_split_pools(fulfillable_units: int, unfulfillable_units: int,
                               **baseline_kwargs) -> dict:
    """A single lot holding an exact fulfillable / unfulfillable split, reached by a
    full receipt followed by an unfulfillable classification."""
    total = fulfillable_units + unfulfillable_units
    ctx = setup_received_lot(units=total, **baseline_kwargs)
    if unfulfillable_units:
        classify_unfulfillable(ctx["lot_id"], ctx["fc_id"], unfulfillable_units)
    ctx["lot"] = read_lot(ctx["lot_id"], ctx["seller_id"])
    return ctx


def setup_suppressed_listing_via_stranding(fulfillable_units: int = 0,
                                           unfulfillable_units: int = 60,
                                           **baseline_kwargs) -> dict:
    """Drive a listing to `SUPPRESSED` with `suppression_reason` of
    `STRANDED_INVENTORY` by classifying its whole fulfillable pool unfulfillable."""
    ctx = setup_lot_with_split_pools(fulfillable_units, unfulfillable_units, **baseline_kwargs)
    ctx["listing"] = read_listing(ctx["listing_id"], ctx["seller_id"])
    return ctx


def setup_claimable_discrepancy(declared_units: int = 200, received_units: int = 150,
                                **baseline_kwargs) -> dict:
    """A lot sitting at `DISCREPANCY_OPEN` from a short receipt, ready for a
    `LOST_INBOUND` claim."""
    return setup_partially_received_plan(declared_units, received_units, **baseline_kwargs)
