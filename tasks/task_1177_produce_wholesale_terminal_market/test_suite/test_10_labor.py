"""Cross-dock and repack labor charges: the two ticket variants and the overtime
kink (PRD §3.9)."""
from test_helpers import api_client, setup_accepted_lot, validate_success
from test_helpers import RECEIVER_HEADERS


def _post_ticket(lot_id, **fields):
    payload = {"purchase_lot_id": lot_id, "work_date": "2026-05-01"}
    payload.update(fields)
    return api_client.create_labor_ticket(payload, RECEIVER_HEADERS)


def test_hourly_ticket_charge_for_six_hour_shift(api):
    """PRD §3.9: "For an `HOURLY` ticket, the first 8 hours are paid straight at
    `hourly_rate`; any hours beyond 8 are paid at one and a half times `hourly_rate`.
    The total dollar pay is converted to cents and rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/labor_charge_hourly_vs_piece_same_shift
    """
    base = setup_accepted_lot(defect_pct=0)
    resp = _post_ticket(base["lot"]["id"], ticket_type="HOURLY", hours=6, pieces=400,
                        hourly_rate=20.00, piece_rate=0.25)
    data = validate_success(resp, 201)
    # 6 straight hours * $20.00 = $120.00 -> 12000 cents; `pieces` is ignored on an
    # HOURLY ticket.
    assert data["charge_cents"] == 12000


def test_piece_ticket_charge_for_same_shift(api):
    """PRD §3.9: "For a `PIECE` ticket, the piece pay is `pieces` multiplied by
    `piece_rate`. A guaranteed minimum floor applies: the crew earns at least `hours`
    multiplied by 15.00 dollars, no matter how few pieces were produced. The charge is
    the greater of piece pay and the guaranteed minimum, converted to cents and
    rounded half-up."
    PRD §3.9: "Identical `hours`, `pieces`, and rate numbers can therefore produce a
    different charge under the two variants, which is why the ticket type is part of
    the input rather than inferred."

    Design: Difficulty/dual_variant_calc/labor_charge_hourly_vs_piece_same_shift
    """
    base = setup_accepted_lot(defect_pct=0)
    hourly = validate_success(
        _post_ticket(base["lot"]["id"], ticket_type="HOURLY", hours=6, pieces=400,
                     hourly_rate=20.00, piece_rate=0.25), 201)
    piece = validate_success(
        _post_ticket(base["lot"]["id"], ticket_type="PIECE", hours=6, pieces=400,
                     hourly_rate=20.00, piece_rate=0.25), 201)
    # max(400 * $0.25, 6 * $15.00) = max($100.00, $90.00) = $100.00 -> 10000 cents.
    assert piece["charge_cents"] == 10000
    assert hourly["charge_cents"] == 12000
    assert hourly["charge_cents"] != piece["charge_cents"], (
        "identical shift numerics must diverge across the two variants")


def test_labor_charge_overtime_kink_at_eight_hours(api):
    """PRD §3.9: "For an `HOURLY` ticket, the first 8 hours are paid straight at
    `hourly_rate`; any hours beyond 8 are paid at one and a half times `hourly_rate`.
    The total dollar pay is converted to cents and rounded half-up to integer cents."

    Design: Corner/calculations/labor_charge_overtime_kink_at_eight_hours
    """
    base = setup_accepted_lot(defect_pct=0)
    at_eight = validate_success(
        _post_ticket(base["lot"]["id"], ticket_type="HOURLY", hours=8,
                     hourly_rate=20.00), 201)
    # Exactly at the threshold: 8 * $20.00 = $160.00, no overtime component.
    assert at_eight["charge_cents"] == 16000

    at_ten = validate_success(
        _post_ticket(base["lot"]["id"], ticket_type="HOURLY", hours=10,
                     hourly_rate=20.00), 201)
    # 8 * 20.00 + 2 * 20.00 * 1.5 = $220.00 -> 22000 cents.
    assert at_ten["charge_cents"] == 22000
    # The marginal hour past 8 costs 3000 cents, not 2000: the kink is observable.
    assert (at_ten["charge_cents"] - at_eight["charge_cents"]) == 6000
