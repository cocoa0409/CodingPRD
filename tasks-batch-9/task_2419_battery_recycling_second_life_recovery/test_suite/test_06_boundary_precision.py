"""Inclusive and strict thresholds tested at the exact boundary value."""
from test_helpers import (
    assert_permit_allotment,
    assert_recovery_lot,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

_LI_AND_CU_QUOTES = [
    {"metal": "LI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 8000},
    {"metal": "CU", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 850},
]


# --------------------------------------------------------------------------
# The mass-balance floor is an inclusive lower bound
# --------------------------------------------------------------------------

def test_mass_balance_one_hundredth_below_the_floor_is_rejected(api):
    """A residue that puts the balance at 96.90 percent fails the tolerance gate and
    leaves the lot exactly as it was.

    PRD §3.7: "The gate is on `mass_balance_pct`, which must be at least 97.00 — a
    value of exactly 97.00 passes, and anything below it fails with
    `ERR_MASS_BALANCE_OUT_OF_TOLERANCE`."

    Design: Difficulty/boundary_precision_check/mass_balance_floor_inclusive_at_exactly_97_00
    """
    ctx = fx.build_world(api, stop_after="outputs")

    response = api.finalize_lot(ctx["lot"]["id"], f.finalize_lot_payload(66.9), fx.TECHNICIAN)
    validate_error(response, "ERR_MASS_BALANCE_OUT_OF_TOLERANCE", 422)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "CHARGED"
    assert lot["residue_mass_kg"] is None
    assert lot["mass_balance_pct"] is None


def test_mass_balance_exactly_at_the_floor_finalizes(api):
    """One hundred grammes more residue puts the balance exactly on 97.00, which the
    inclusive floor accepts.

    PRD §3.7: "Its `mass_balance_pct` is the accounted figure divided by
    `charged_mass_kg`, multiplied by one hundred and rounded half up to two decimals."

    Design: Difficulty/boundary_precision_check/mass_balance_floor_inclusive_at_exactly_97_00
    """
    ctx = fx.build_world(api, stop_after="outputs")

    lot = validate_success(
        api.finalize_lot(ctx["lot"]["id"], f.finalize_lot_payload(67.0), fx.TECHNICIAN)
    )

    assert_recovery_lot(lot)
    assert lot["status"] == "FINALIZED"
    assert float(lot["residue_mass_kg"]) == 67.0
    assert float(lot["recovered_mass_kg"]) == 30.000
    assert float(lot["accounted_mass_kg"]) == 97.000
    assert float(lot["unaccounted_mass_kg"]) == 3.000
    assert float(lot["mass_balance_pct"]) == 97.00
    assert float(lot["recycled_content_pct"]) == 30.00


# --------------------------------------------------------------------------
# The daily discharge bucket is a strictly-greater-than ceiling
# --------------------------------------------------------------------------

def _permitted_lot(api):
    """An open lot on a future campaign plus an active water allotment capped at
    five hundred kilogrammes a day."""
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-25T00:00:00.000Z",
        window_end="2026-09-30T00:00:00.000Z",
    )
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"])
    ctx["allotment"] = fx.create_allotment(api, ctx["facility"]["id"])
    return ctx


def test_daily_bucket_accepts_a_total_exactly_equal_to_the_cap(api):
    """Two bookings on the same UTC day summing to exactly the daily cap are both
    accepted.

    PRD §3.8: "refuses with `ERR_DISCHARGE_DAILY_CAP_EXCEEDED` when that total is
    **strictly greater** than the allotment's `daily_cap_kg` — a total exactly equal
    to the cap is accepted."

    Design: Difficulty/boundary_precision_check/discharge_daily_cap_strict_greater_than_at_exactly_cap
    """
    ctx = _permitted_lot(api)
    allotment_id = ctx["allotment"]["id"]

    for event_date, mass in (
        ("2026-08-20T06:00:00.000Z", 300.0),
        ("2026-08-20T18:00:00.000Z", 200.0),
    ):
        response = api.create_discharge_event(
            ctx["lot"]["id"],
            f.create_discharge_event_payload(allotment_id, event_date, mass),
            fx.SUBMITTER,
        )
        event = validate_success(response, expected_status=201)
        assert event["status"] == "POSTED"

    allotment = fx.read_allotment(api, allotment_id)
    assert_permit_allotment(allotment)
    assert float(allotment["consumed_kg"]) == 500.0


def test_one_gramme_beyond_the_daily_cap_is_refused(api):
    """A single further gramme on the same UTC day tips the bucket strictly past the
    cap and is refused without consuming allowance.

    PRD §3.8: "the server sums `mass_kg` over the discharge events of that same
    allotment whose `status` is `POSTED` and whose `event_date` falls on the same UTC
    calendar date"

    Design: Difficulty/boundary_precision_check/discharge_daily_cap_strict_greater_than_at_exactly_cap
    """
    ctx = _permitted_lot(api)
    allotment_id = ctx["allotment"]["id"]
    fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T06:00:00.000Z", 300.0
    )
    fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T18:00:00.000Z", 200.0
    )

    response = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(allotment_id, "2026-08-20T23:00:00.000Z", 0.001),
        fx.SUBMITTER,
    )
    validate_error(response, "ERR_DISCHARGE_DAILY_CAP_EXCEEDED", 422)

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 500.0
    assert allotment["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# A zero contained mass books a zero line and performs no index lookup
# --------------------------------------------------------------------------

def _lfp_priced_without_nickel_or_cobalt_quotes(api):
    ctx = fx.bootstrap_network(api, quotes=_LI_AND_CU_QUOTES)
    fx.advance_intake(
        ctx,
        # PRD §3.5 requires `compliance_state` `MANIFEST_CLOSED` before release, so
        # the shipment is walked through manifest submission and counter-signature.
        stop_after="manifest_closed",
        intake={
            "declared_chemistry": "LFP",
            "gross_mass_kg": 220.0,
            "packaging_tare_kg": 20.0,
            "declared_ni_pct": 5.0,
            "declared_co_pct": 3.0,
            "declared_li_pct": 2.0,
            "declared_cu_pct": 6.0,
        },
        identified_chemistry="LFP",
        modules=(),
        soc_pct=8.0,
    )
    return ctx


def test_release_succeeds_with_no_quote_for_the_zero_recovery_metals(api):
    """An LFP shipment recovers no nickel and no cobalt, so custody release never
    looks for their quotes and the zero lines are still reported.

    PRD §3.5: "If the contained mass multiplied by the recovery factor comes to zero,
    the line amount is zero cents and **no index lookup is performed at all** — this
    is why a chemistry with no nickel content never triggers a missing-quote failure
    for nickel."

    Design: Difficulty/boundary_precision_check/zero_contained_metal_skips_index_lookup_and_books_zero_line
    """
    ctx = _lfp_priced_without_nickel_or_cobalt_quotes(api)
    intake_id = ctx["intake"]["id"]

    released = validate_success(api.release_intake(intake_id, fx.OPERATOR))
    assert released["custody_state"] == "RELEASED"

    settlement = fx.read_settlement(api, fx.settlement_for_intake(api, intake_id)["id"])
    lines = {line["metal"]: line for line in settlement["line_breakdown"]}
    assert float(lines["NI"]["contained_kg"]) == 10.000
    assert lines["NI"]["line_cents"] == 0
    assert float(lines["CO"]["contained_kg"]) == 6.000
    assert lines["CO"]["line_cents"] == 0


def test_zero_lines_contribute_nothing_to_the_gross_or_the_waterfall(api):
    """The gross is the sum of the two priced lines alone and the waterfall runs from
    that figure.

    PRD §3.5: "The settlement's `gross_cents` is the sum of the `line_cents` values,
    each already rounded to whole cents at its own line before the sum is taken."

    Design: Difficulty/boundary_precision_check/zero_contained_metal_skips_index_lookup_and_books_zero_line
    """
    ctx = _lfp_priced_without_nickel_or_cobalt_quotes(api)
    fx.release(api, ctx["intake"]["id"])
    settlement = fx.read_settlement(
        api, fx.settlement_for_intake(api, ctx["intake"]["id"])["id"]
    )

    lines = {line["metal"]: line for line in settlement["line_breakdown"]}
    assert lines["LI"]["line_cents"] == 13200
    assert lines["CU"]["line_cents"] == 3672
    assert settlement["gross_cents"] == 16872
    assert settlement["pre_surcharge_net_cents"] == 14847
    assert settlement["net_payable_cents"] == 14105
