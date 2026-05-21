"""Toll-event pricing tests — class multiplier, interop adjustment,
plate-bill surcharge, per-step rounding, HOV exemption.

PRD §3.3 fixes the pinned order (class → interop → plate-surcharge →
HOV check) and PRD §2.6 fixes per-step rounding.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_and_bind_transponder,
    create_interop_policy_payload,
    create_toll_event_payload,
    create_vehicle,
    ingest_toll_event,
    make_account_holder_headers,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    validate_success,
)


# ---------------------------------------------------------------------------
# Class multiplier — PRD §3.3
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("axle_count,multiplier,base,expected_gross", [
    # PRD §3.3: "`CLASS_2` to 1.00 ... `CLASS_3` to 1.50 ... `CLASS_4`
    # to 2.25 ... `CLASS_5_PLUS` to 3.50"
    (2, 1.00, 200, 200),
    (3, 1.50, 200, 300),
    (3, 1.50, 237, 356),  # 237*1.5 = 355.5 → round-half-up → 356
    (4, 2.25, 200, 450),
    (5, 3.50, 100, 350),
])
def test_class_multiplier_applied_to_base_rate(
    api, axle_count, multiplier, base, expected_gross
):
    """PRD §3.3: "a class multiplier is selected from the table that
    maps `CLASS_2` to 1.00, `CLASS_3` to 1.50, `CLASS_4` to 2.25, and
    `CLASS_5_PLUS` to 3.50; `gross_toll_cents` is the gantry's
    `base_rate_cents` multiplied by that class multiplier, with the
    product rounded half up to whole cents."

    Claim: gross_toll_cents == round_half_up(base * class_mult).
    """
    # Same-agency, transponder ingest so interop_adjust = 0 and
    # plate_surcharge = 0; thus net == gross.
    a = create_account(
        home_agency_code="NY_EZPASS", balance_cents=50000,
        auto_reload_enabled=False,
    )
    v = create_vehicle(a["id"], axle_count=axle_count)
    t = create_and_bind_transponder(a["id"], v["id"])
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS",
        base_rate_cents=base, transponder_serial=t["serial_number"],
    )
    assert data["billing_status"] == "POSTED"
    assert data["capture_method"] == "TRANSPONDER"
    assert data["gross_toll_cents"] == expected_gross
    assert data["net_toll_cents"] == expected_gross


# ---------------------------------------------------------------------------
# Plate-bill surcharge — PRD §3.3
# ---------------------------------------------------------------------------
def test_plate_bill_surcharge_15_percent(api):
    """PRD §3.3: "when `capture_method` is `PLATE`, a plate-bill
    surcharge of fifteen percent of `gross_toll_cents` is added —
    concretely, `gross_toll_cents` multiplied by 1500 basis points (that
    is, 1500 divided by 10000), rounded half up to whole cents at this
    step."

    Claim: base 200 + same-agency + axle_count=2 = gross 200, plate
    capture adds floor(200 * 0.15 + 0.5) = 30 → net = 230.
    """
    a = create_account(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        auto_reload_enabled=False,
    )
    v = create_vehicle(a["id"], plate_state="NY", axle_count=2)
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        plate_number=v["plate_number"], plate_state=v["plate_state"],
    )
    assert data["billing_status"] == "TOLL_BY_PLATE_INVOICED"
    assert data["capture_method"] == "PLATE"
    assert data["gross_toll_cents"] == 200
    assert data["net_toll_cents"] == 230  # 200 + round_half_up(200*0.15)=30


def test_transponder_capture_no_plate_surcharge(api):
    """PRD §3.3: "when `capture_method` is `TRANSPONDER` the plate-bill
    surcharge is zero."

    Claim: transponder-attributed event has no plate surcharge — gross
    == net (no interop adjustment configured).
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=300,
        transponder_serial=t["serial_number"],
    )
    assert data["billing_status"] == "POSTED"
    assert data["capture_method"] == "TRANSPONDER"
    assert data["gross_toll_cents"] == 300
    assert data["net_toll_cents"] == 300


# ---------------------------------------------------------------------------
# Interop adjustment — PRD §2.9, §3.3
# ---------------------------------------------------------------------------
def test_same_agency_has_zero_interop_adjustment(api):
    """PRD §2.9: "When the gantry's `agency_code` matches the account's
    `home_agency_code` no interoperability adjustment is made."

    Claim: same-agency event with base 100 (CLASS_2) and no
    plate-surcharge path = net 100.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=100,
        transponder_serial=t["serial_number"],
    )
    assert data["net_toll_cents"] == 100


def test_cross_agency_surcharge_applied(api):
    """PRD §2.9: "the `InteropPolicy` row keyed by `(home_agency,
    gantry_agency)` supplies `surcharge_bps` and `discount_bps`, and
    the adjustment is `gross_toll_cents` multiplied by the difference
    between `surcharge_bps` and `discount_bps` divided by ten thousand,
    again rounded half up to whole cents at this step."

    Claim: with surcharge=500, discount=200, net=300 surcharge_bps,
    base=200 (CLASS_2): gross=200, interop = round_half_up(200*300/10000)
    = round_half_up(6.0) = 6, net = 206.
    """
    # Build the policy first.
    api.create_interop_policy(
        create_interop_policy_payload(
            home_agency="NY_EZPASS", gantry_agency="NJ_EZPASS",
            surcharge_bps=500, discount_bps=200,
        ),
        TEST_USERS["agency_admin_headers"],
    )
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NJ_EZPASS", base_rate_cents=200,
        transponder_serial=t["serial_number"],
    )
    assert data["gross_toll_cents"] == 200
    assert data["net_toll_cents"] == 206


# ---------------------------------------------------------------------------
# HOV exemption — PRD §3.3
# ---------------------------------------------------------------------------
def test_hov_exemption_zeros_net_toll(api):
    """PRD §3.3: "When all three conditions hold, the event transitions
    from `PENDING` to `EXEMPTED`: `hov_exempt_applied` becomes true,
    both `gross_toll_cents` and `net_toll_cents` are written as zero".

    Claim: HOV-lane + occupants=3 + hov_capable vehicle → EXEMPTED with
    both tolls 0 and hov_exempt_applied true.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        hov_capable=True,
    )
    data = ingest_toll_event(
        gantry_id="HOV1", agency_code="NY_EZPASS", base_rate_cents=300,
        transponder_serial=t["serial_number"],
        hov_lane=True, declared_occupants=3,
    )
    assert data["billing_status"] == "EXEMPTED"
    assert data["hov_exempt_applied"] is True
    assert data["gross_toll_cents"] == 0
    assert data["net_toll_cents"] == 0


def test_hov_exemption_requires_min_three_occupants(api):
    """PRD §3.3: "The HOV exemption applies only when the gantry's
    `hov_lane` is true *and* the `declared_occupants` is at least 3
    *and* the attribution-resolved vehicle's `hov_capable` is true."
    PRD §3.3: "When the gantry is an HOV lane and the claim does not
    satisfy all three conditions — for example because
    `declared_occupants` is less than 3 even though `hov_capable` is
    true — the event is treated as HOV fraud: a violation and fine
    are recorded and the request returns a 409 with
    `ERR_HOV_FRAUD_RECORDED`"

    Claim: HOV-lane with declared_occupants=2 → not EXEMPTED; treated
    as HOV fraud (recorded violation, 409 envelope).
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        hov_capable=True,
    )
    payload = create_toll_event_payload(
        gantry_id="HOV1", agency_code="NY_EZPASS", base_rate_cents=300,
        transponder_serial=t["serial_number"],
        hov_lane=True, declared_occupants=2,
    )
    res = api.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    # PRD §3.3 says return 409 with ERR_HOV_FRAUD_RECORDED.
    assert res.status_code == 409
    body = res.json()
    assert body["data"]["error_id"] == "ERR_HOV_FRAUD_RECORDED"
