"""Impound settlement: RELEASE vs FORFEITURE variants, tiered storage cost, and
invalid re-settlement (Difficulty: dual_variant_calc, combinatorial_formula;
Corner: state_machines)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    TEST_USERS, make_enforcement_headers, OFFICER_ISSUER_ID,
    IMPOUND_RELEASE_10_DAYS, IMPOUND_FORFEIT_WRITEOFF_10_DAYS,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
EO = make_enforcement_headers(OFFICER_ISSUER_ID)


def _approved_cart():
    fx.set_clock("2026-06-01T00:00:00Z")
    vendor = fx.create_vendor()
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"], size_sqft=30)
    return vendor, cart


# --------------------------------------------------------------------------- #
# dual_variant_calc / impound_release_vs_forfeiture_settlement
# --------------------------------------------------------------------------- #
def test_impound_release_charges_base_storage_admin(api):
    """PRD §3.9: "the release_fee_cents charged to the vendor is a base impound fee
    of 10,000 cents plus the tiered storage cost plus an administrative fee of 5,000
    cents, with municipal_writeoff_cents left at 0."

    Design: Difficulty/dual_variant_calc/impound_release_vs_forfeiture_settlement
    """
    _, cart = _approved_cart()
    impound = fx.create_held_impound(cart["id"], reason="HEALTH_HAZARD",
                                     impounded_at="2026-06-01T00:00:00Z")
    settled = validate_success(
        api.release_impound(impound["id"], {"release_at": "2026-06-11T00:00:00Z"}, EO), 200)
    assert settled["release_fee_cents"] == IMPOUND_RELEASE_10_DAYS  # 44500
    assert settled["municipal_writeoff_cents"] == 0
    assert settled["settlement_variant"] == "RELEASE"


def test_impound_forfeiture_records_writeoff_no_charge(api):
    """PRD §3.9: "release_fee_cents is 0 (no charge to the vendor), and
    municipal_writeoff_cents is recorded as the base impound fee of 10,000 cents plus
    the tiered storage cost, with no administrative fee included."

    Design: Difficulty/dual_variant_calc/impound_release_vs_forfeiture_settlement
    """
    _, cart = _approved_cart()
    impound = fx.create_held_impound(cart["id"], reason="ABANDONMENT",
                                     impounded_at="2026-06-01T00:00:00Z")
    settled = validate_success(
        api.forfeit_impound(impound["id"], {"forfeit_at": "2026-06-11T00:00:00Z"}, EO), 200)
    assert settled["municipal_writeoff_cents"] == IMPOUND_FORFEIT_WRITEOFF_10_DAYS  # 39500
    assert settled["release_fee_cents"] == 0
    assert settled["settlement_variant"] == "FORFEITURE"


# --------------------------------------------------------------------------- #
# combinatorial_formula / impound_release_tiered_storage
# --------------------------------------------------------------------------- #
def test_storage_days_rounded_up(api):
    """PRD §3.9: "storage_days is the number of whole days between impounded_at and
    the settlement instant, rounded up to the next whole day and never less than 1."

    Design: Difficulty/combinatorial_formula/impound_release_tiered_storage
    """
    _, cart = _approved_cart()
    impound = fx.create_held_impound(cart["id"], reason="UNPERMITTED",
                                     impounded_at="2026-06-01T00:00:00Z")
    settled = validate_success(
        api.release_impound(impound["id"], {"release_at": "2026-06-11T00:00:00Z"}, EO), 200)
    assert settled["storage_days"] == 10


def test_tiered_storage_crosses_seven_day_boundary(api):
    """PRD §3.9: "Storage cost is tiered — the first 7 storage days are billed at
    2,500 cents per day and every day beyond the seventh at 4,000 cents per day."

    Design: Difficulty/combinatorial_formula/impound_release_tiered_storage
    """
    _, cart = _approved_cart()
    impound = fx.create_held_impound(cart["id"], reason="UNPERMITTED",
                                     impounded_at="2026-06-01T00:00:00Z")
    settled = validate_success(
        api.release_impound(impound["id"], {"release_at": "2026-06-11T00:00:00Z"}, EO), 200)
    # base 10000 + (7*2500 + 3*4000 = 29500) + admin 5000 = 44500
    assert settled["release_fee_cents"] == IMPOUND_RELEASE_10_DAYS


# --------------------------------------------------------------------------- #
# Corner state_machines: impound_release_twice_invalid_state
# --------------------------------------------------------------------------- #
def test_release_already_released_impound_invalid_state(api):
    """PRD §3.9: "Both release and forfeit require the impound to be in HELD."
    PRD §4: "A transition attempted on a resource in an illegal state returns
    ERR_INVALID_STATE; one attempted from a terminal state returns
    ERR_TERMINAL_STATE"

    Releasing an already-RELEASED impound must be rejected. The PRD requires the
    impound to be in HELD, but — unlike the lottery, violation, complaint, and
    permit machines — it never labels the impound's RELEASED/FORFEITED states as
    "terminal". A PRD-faithful implementer may therefore classify the already-
    settled state either as an illegal source state (ERR_INVALID_STATE) or as a
    structurally terminal one (ERR_TERMINAL_STATE); both are 409 members of the
    state-error family. Accept either.

    Design: Corner/state_machines/impound_release_twice_invalid_state
    """
    _, cart = _approved_cart()
    impound = fx.create_held_impound(cart["id"], reason="UNPERMITTED",
                                     impounded_at="2026-06-01T00:00:00Z")
    get_success_data(api.release_impound(impound["id"], {"release_at": "2026-06-05T00:00:00Z"}, EO))
    res = api.release_impound(impound["id"], {"release_at": "2026-06-06T00:00:00Z"}, EO)
    assert res.status_code == 409
    validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_TERMINAL_STATE"])
