"""Composite setup helpers — build multi-entity state via PRD-declared endpoints.

Every fixture builds its preconditions from scratch using API calls; the runner
restarts the server (fresh DB) before each test, so no state can be assumed.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bin_payload,
    create_lot_payload,
    create_reading_payload,
    create_fumigation_payload,
    create_permit_payload,
    create_contract_payload,
    create_loadout_payload,
    create_policy_payload,
    create_claim_payload,
    create_applicator_payload,
    deliver_payload,
)
from .test_users import (
    TEST_USERS,
    make_site_manager_headers,
    make_farm_owner_headers,
    make_applicator_headers,
    make_safety_officer_headers,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]
SO = TEST_USERS["safety_officer_headers"]


# ---------- Tier 1: single-entity state progression ----------

def create_bin(name="BIN-1", capacity_bu=5000.00, crop="CORN"):
    return get_success_data(api_client.create_bin(create_bin_payload(
        name=name, capacity_bu=capacity_bu, crop=crop), SM))


def create_lot(bin_id, original_bu=1000.00, fill_moisture_pct=15.0,
               fill_date="2026-08-01T00:00:00Z", grade="GRADE_1", crop="CORN",
               fill_basis_cents=-25, reference_price_cents_per_bu=430):
    return get_success_data(api_client.create_lot(create_lot_payload(
        bin_id,
        crop=crop, grade=grade, fill_date=fill_date, original_bu=original_bu,
        fill_moisture_pct=fill_moisture_pct, fill_basis_cents=fill_basis_cents,
        reference_price_cents_per_bu=reference_price_cents_per_bu,
    ), SM))


def create_contract(contracted_bu=2000.00, crop="CORN",
                    window_start="2026-08-01T00:00:00Z",
                    window_end="2026-12-31T23:59:59Z",
                    basis_cents_per_bu=-20, futures_ref_cents_per_bu=450,
                    early_bonus_cents_per_bu=None, early_cutoff=None):
    kw = {}
    if early_bonus_cents_per_bu is not None:
        kw["early_bonus_cents_per_bu"] = early_bonus_cents_per_bu
    if early_cutoff is not None:
        kw["early_cutoff"] = early_cutoff
    return get_success_data(api_client.create_contract(create_contract_payload(
        crop=crop, contracted_bu=contracted_bu, window_start=window_start,
        window_end=window_end, basis_cents_per_bu=basis_cents_per_bu,
        futures_ref_cents_per_bu=futures_ref_cents_per_bu, **kw), FO))


def create_applicator(name="Alice A", license_no="LIC-A",
                      cert_expires_at="2027-06-01T00:00:00Z"):
    return get_success_data(api_client.create_applicator(create_applicator_payload(
        name=name, license_no=license_no, cert_expires_at=cert_expires_at), SM))


def create_policy(crop="CORN", coverage_limit_cents=1_000_000,
                  deductible_cents=5_000, valuation_clause="SPOT",
                  period_start="2026-07-01T00:00:00Z",
                  period_end="2026-12-31T23:59:59Z"):
    return get_success_data(api_client.create_policy(create_policy_payload(
        crop=crop, coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents, valuation_clause=valuation_clause,
        period_start=period_start, period_end=period_end), FO))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# ---------- Tier 2/3: hierarchy + lifecycle shortcuts ----------

def setup_bin_with_lot(bin_name="BIN-1", capacity_bu=5000.00,
                       original_bu=1000.00, fill_moisture_pct=15.0,
                       fill_date="2026-08-01T00:00:00Z", crop="CORN"):
    """Returns (bin, lot)."""
    b = create_bin(name=bin_name, capacity_bu=capacity_bu, crop=crop)
    lot = create_lot(b["id"], original_bu=original_bu,
                     fill_moisture_pct=fill_moisture_pct,
                     fill_date=fill_date, crop=crop)
    return b, lot


def setup_bin_lot_contract(bin_name="BIN-1", capacity_bu=5000.00,
                           original_bu=1000.00, fill_moisture_pct=15.0,
                           contracted_bu=2000.00, **contract_kw):
    """Returns (bin, lot, contract)."""
    b, lot = setup_bin_with_lot(
        bin_name=bin_name, capacity_bu=capacity_bu,
        original_bu=original_bu, fill_moisture_pct=fill_moisture_pct,
        crop=contract_kw.pop("crop", "CORN"),
    )
    con = create_contract(contracted_bu=contracted_bu, **contract_kw)
    return b, lot, con


def setup_bin_lot_contract_loadout(
    bin_name="BIN-1", capacity_bu=5000.00, original_bu=1000.00,
    fill_moisture_pct=15.0, contracted_bu=2000.00, planned_bu=100.00,
    scheduled_start="2026-08-10T08:00:00Z",
    scheduled_end="2026-08-10T12:00:00Z",
    **contract_kw,
):
    """Returns (bin, lot, contract, loadout)."""
    b, lot, con = setup_bin_lot_contract(
        bin_name=bin_name, capacity_bu=capacity_bu,
        original_bu=original_bu, fill_moisture_pct=fill_moisture_pct,
        contracted_bu=contracted_bu, **contract_kw,
    )
    lo = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"],
        planned_bu=planned_bu,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    ), SM))
    return b, lot, con, lo


def setup_dispatched_loadout(**kw):
    """Returns (bin, lot, contract, loadout) with transport DISPATCHED."""
    b, lot, con, lo = setup_bin_lot_contract_loadout(**kw)
    get_success_data(api_client.dispatch_loadout(lo["id"], SM))
    lo = get_success_data(api_client.get_loadout(lo["id"], SM))
    return b, lot, con, lo


def setup_delivered_loadout(delivered_at="2026-08-10T10:00:00Z",
                            scale_tickets=None, **kw):
    """Returns (bin, lot, contract, loadout) with transport DELIVERED."""
    b, lot, con, lo = setup_dispatched_loadout(**kw)
    tickets = scale_tickets or [
        {"ticket_no": "T1", "gross_bu": kw.get("planned_bu", 100.00),
         "moisture_pct": 15.0}
    ]
    get_success_data(api_client.deliver_loadout(
        lo["id"],
        deliver_payload(delivered_at=delivered_at, scale_tickets=tickets), SM))
    lo = get_success_data(api_client.get_loadout(lo["id"], SM))
    return b, lot, con, lo


def setup_settled_loadout(**kw):
    """Returns (bin, lot, contract, loadout) settled (settlement=SETTLED)."""
    b, lot, con, lo = setup_delivered_loadout(**kw)
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    lo = get_success_data(api_client.get_loadout(lo["id"], SM))
    return b, lot, con, lo


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, SM))


def get_bin(bin_id):
    return get_success_data(api_client.get_bin(bin_id, SM))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, SM))


def get_loadout(loadout_id):
    return get_success_data(api_client.get_loadout(loadout_id, SM))


def get_permit(permit_id):
    return get_success_data(api_client.get_permit(permit_id, SM))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, SM))


def get_fumigation(fum_id):
    return get_success_data(api_client.get_fumigation(fum_id, SM))


# ---------- Alert / fumigation helpers ----------

def create_hotspot_reading(bin_id, recorded_at="2026-08-05T10:00:00Z",
                           ambient_temp_f=60.0, cable_temps_f=None,
                           insect_activity=False):
    """Post a reading guaranteed to trigger the hotspot delta rule
    (90.0 - 60.0 = 30.0 >= 30.0)."""
    cables = cable_temps_f if cable_temps_f is not None else [90.0]
    return get_success_data(api_client.create_reading(create_reading_payload(
        bin_id, recorded_at=recorded_at, ambient_temp_f=ambient_temp_f,
        cable_temps_f=cables, insect_activity=insect_activity), SM))


def get_first_alert_for_bin(bin_id):
    data = get_success_data(api_client.list_alerts(SM, params={"bin_id": bin_id}))
    assert isinstance(data, list) and len(data) >= 1, (
        f"Expected at least one alert on bin {bin_id}, got {data!r}"
    )
    return data[0]


def create_confirmed_loss_alert(bin_id, loss_bu, recorded_at="2026-08-05T10:00:00Z",
                                close_clock=None):
    """Hotspot reading -> alert; optionally advance the clock; close CONFIRMED_LOSS.
    Returns the alert dict after closure."""
    create_hotspot_reading(bin_id, recorded_at=recorded_at)
    alert = get_first_alert_for_bin(bin_id)
    if close_clock is not None:
        set_clock(close_clock)
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": loss_bu}, SM))
    return get_success_data(api_client.get_alert(alert["id"], SM))


def setup_confirmed_loss_claim(policy_kw=None, loss_bu=100.00,
                               bin_name="BIN-CL", close_clock=None,
                               recorded_at="2026-08-05T10:00:00Z"):
    """Bin + CONFIRMED_LOSS alert + policy + SUBMITTED claim.
    Returns (bin, alert, policy, claim)."""
    b = create_bin(name=bin_name)
    alert = create_confirmed_loss_alert(
        b["id"], loss_bu=loss_bu, recorded_at=recorded_at, close_clock=close_clock)
    pol = create_policy(**(policy_kw or {}))
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM))
    return b, alert, pol, claim


def setup_active_fumigation(bin_name="BIN-F", product="PHOSPHINE",
                            application_start="2026-08-01T00:00:00Z",
                            application_end="2026-08-01T06:00:00Z",
                            cert_expires_at="2027-06-01T00:00:00Z"):
    """Bin + applicator + ACTIVE fumigation. Returns (bin, applicator, fumigation)."""
    b = create_bin(name=bin_name)
    app = create_applicator(cert_expires_at=cert_expires_at)
    hdrs = make_applicator_headers(app["id"])
    fum = get_success_data(api_client.create_fumigation(
        create_fumigation_payload(
            b["id"], app["id"], product=product,
            application_start=application_start, application_end=application_end),
        hdrs))
    return b, app, fum
