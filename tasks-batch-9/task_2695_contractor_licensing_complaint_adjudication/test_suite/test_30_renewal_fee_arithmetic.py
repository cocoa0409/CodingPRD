"""Renewal fee assembly and the bond-continuity measurement behind it.

The renewal fee is built in three ordered stages, and the branch that decides
whether a delinquency surcharge applies — and where the new term's expiry is
anchored — is keyed on the clock relative to the licence's ``expires_on``. The
tests here drive a licence to the exact expiry date, so the timely branch runs,
and they exercise the half-open merging rule that lets two abutting bonds cover
a whole term without an uncovered day.
"""

from test_helpers import fixtures as H
from test_helpers import validate_success


def _c10_licence_with_bond_through_2029(api):
    """A C-10 licence issued 2026-08-01 under one bond running to 2029-01-01."""
    H.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = H.mint_active_license(api)
    H.verify_bond(
        api,
        ctx.license_id,
        amount_cents=1500000,
        effective_date="2026-08-01",
        expiration_date="2029-01-01",
    )
    return ctx


def _c10_licence_with_two_adjacent_bonds(api):
    """A C-10 licence covered by bonds meeting exactly at 2027-08-01."""
    H.set_clock(api, "2026-08-01T00:00:00Z")
    ctx = H.mint_active_license(api)
    first = H.verify_bond(
        api,
        ctx.license_id,
        amount_cents=1500000,
        effective_date="2026-08-01",
        expiration_date="2027-08-01",
        carrier_name="Surety One",
        policy_number="BND-ADJ-1",
    )
    second = H.verify_bond(
        api,
        ctx.license_id,
        amount_cents=1500000,
        effective_date="2027-08-01",
        expiration_date="2029-01-01",
        carrier_name="Surety Two",
        policy_number="BND-ADJ-2",
    )
    return ctx, first, second


def test_timely_renewal_on_the_expiry_date_charges_no_delinquency_surcharge(api):
    """A renewal on the expiry date itself skips stage two entirely.

    "Stage two adds a delinquency surcharge, but only when the renewal is
    delinquent: when the clock date is strictly past the licence's
    `expires_on`, half of the stage-one subtotal is added, rounded half up to
    whole cents; when the renewal is timely, nothing is added." "Renewed timely
    instead, the same licence pays 65,000 plus 6,500, or 71,500."

    Design: Corner/calculations/corner_timely_renewal_charges_no_delinquency_surcharge
    """
    ctx = _c10_licence_with_bond_through_2029(api)

    H.set_clock(api, "2028-07-01T00:00:00Z")
    banked = H.bank_ce_hours(api, ctx, 4, "2028-07-01")
    assert banked["ce_hours_completed"] == 4

    H.set_clock(api, "2028-08-01T00:00:00Z")
    renewed = validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    assert renewed["last_renewal_fee_cents"] == 71500


def test_timely_renewal_anchors_the_new_term_on_the_previous_expiry(api):
    """The new expiry is the old expiry plus 24 months, not the clock plus 24.

    "When the renewal is timely — the clock date on or before `expires_on` —
    the new `expires_on` is the *previous* `expires_on` advanced by twenty-four
    months, anchored on the old expiry rather than on the clock, and no
    delinquency surcharge is assessed."

    Design: Corner/calculations/corner_timely_renewal_charges_no_delinquency_surcharge
    """
    ctx = _c10_licence_with_bond_through_2029(api)

    H.set_clock(api, "2028-07-01T00:00:00Z")
    H.bank_ce_hours(api, ctx, 4, "2028-07-01")

    H.set_clock(api, "2028-08-01T00:00:00Z")
    renewed = validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    assert renewed["expires_on"] == "2030-08-01"


def test_renewal_restamps_the_term_counters_and_clears_the_ce_bank(api):
    """Renewal rebases the term dates, the count and the CE bank.

    "Either way, `last_renewed_on` is set to the clock date, `renewal_count`
    rises by one, and `ce_hours_completed` is reset to zero for the fresh term."
    "A renewal from `EXPIRED` returns the licence to `ACTIVE`; a renewal from
    `ACTIVE` is a self-loop that leaves the licensure dimension where it was."

    Design: Corner/calculations/corner_timely_renewal_charges_no_delinquency_surcharge
    """
    ctx = _c10_licence_with_bond_through_2029(api)

    H.set_clock(api, "2028-07-01T00:00:00Z")
    H.bank_ce_hours(api, ctx, 4, "2028-07-01")

    H.set_clock(api, "2028-08-01T00:00:00Z")
    validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    licence = H.read_license(api, ctx.license_id)
    assert licence["last_renewed_on"] == "2028-08-01"
    assert licence["renewal_count"] == 1
    assert licence["ce_hours_completed"] == 0
    assert licence["status"] == "ACTIVE"


def test_adjacent_bond_intervals_merge_and_clear_the_continuity_gate(api):
    """Bonds meeting at 2027-08-01 leave no uncovered day, so renewal proceeds.

    "Those contributed periods are then merged: two periods that overlap merge,
    and — because they are half-open — two periods that merely meet at a
    boundary are adjacent and also merge into one continuous period with no gap
    between them." "First, bond continuity: the uncovered-day measurement of
    §3.5 must come to zero over the expiring term, and any gap at all refuses
    the renewal with `ERR_COVERAGE_CONTINUITY_GAP`."

    Design: Corner/calculations/corner_adjacent_bond_intervals_merge_to_zero_gap_days
    """
    ctx, _first, _second = _c10_licence_with_two_adjacent_bonds(api)

    H.set_clock(api, "2028-07-01T00:00:00Z")
    H.bank_ce_hours(api, ctx, 8, "2028-07-01")

    H.set_clock(api, "2028-08-01T00:00:00Z")
    renewed = validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    assert renewed["renewal_count"] == 1
    assert renewed["expires_on"] == "2030-08-01"


def test_renewal_at_full_ce_hours_pays_base_plus_the_ten_percent_assessment(api):
    """No shortfall means stage one is the bare base fee, assessed at ten percent.

    "Stage one begins with the classification's `renewal_base_fee_cents` and
    adds a continuing-education shortfall charge of 50 dollars — 5,000 cents —
    for each whole hour of shortfall, where the shortfall is the
    classification's `required_ce_hours` less the licence's
    `ce_hours_completed`, treated as zero when the licensee is at or above
    requirement." "Stage three applies the recovery-fund assessment, and the
    rate depends on how large the stage-two subtotal is: a stage-two subtotal of
    at least 1,000 dollars — 100,000 cents — is assessed at fifteen percent, and
    anything below that threshold at ten percent."

    Design: Corner/calculations/corner_adjacent_bond_intervals_merge_to_zero_gap_days
    """
    ctx, _first, _second = _c10_licence_with_two_adjacent_bonds(api)

    H.set_clock(api, "2028-07-01T00:00:00Z")
    banked = H.bank_ce_hours(api, ctx, 8, "2028-07-01")
    assert banked["ce_hours_completed"] == 8

    H.set_clock(api, "2028-08-01T00:00:00Z")
    renewed = validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    assert renewed["last_renewal_fee_cents"] == 49500


def test_a_successor_bond_starting_on_the_predecessors_expiry_is_verified(api):
    """Abutting bond periods do not overlap, so both instruments stand verified.

    "Because the periods are half-open, a record starting exactly on another's
    `expiration_date` does *not* overlap and may be verified; a genuine overlap
    draws `ERR_COVERAGE_PERIOD_OVERLAP`."

    Design: Corner/calculations/corner_adjacent_bond_intervals_merge_to_zero_gap_days
    """
    ctx, first, second = _c10_licence_with_two_adjacent_bonds(api)

    assert first["status"] == "VERIFIED"
    assert first["expiration_date"] == "2027-08-01"
    assert second["status"] == "VERIFIED"
    assert second["effective_date"] == "2027-08-01"
    assert ctx.license_id == first["license_id"] == second["license_id"]
