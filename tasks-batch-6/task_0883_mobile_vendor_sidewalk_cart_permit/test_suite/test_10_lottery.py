"""Prime-spot lottery: deterministic ranking, created_at tie-break, entry
eligibility, and draw idempotency (Corner: calculations, validations,
state_machines)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    make_vendor_headers, create_lottery_entry_payload, create_permit_payload,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]


# --------------------------------------------------------------------------- #
# Corner calculations: lottery_ranking_awards_highest_score
# --------------------------------------------------------------------------- #
def test_lottery_awards_highest_rank_score(api):
    """PRD §3.6: "Each eligible entry receives a deterministic rank_score equal to the
    vendor's seniority_years times 10, plus the vendor's compliance_score times 1,
    minus the permit's violation_points times 5. Eligible entries are ordered by
    rank_score descending"

    Design: Corner/calculations/lottery_ranking_awards_highest_score
    """
    lot = fx.setup_prime_zone_with_lottery(capacity_slots=1, spot_positions=(50,))
    zone, spots, commissary, lottery = lot["zone"], lot["spots"], lot["commissary"], lot["lottery"]
    # Vendor A seniority 5 -> rank 5*10 + 100 - 0 = 150.
    _, _, ea = fx.create_prime_entrant(zone["id"], commissary["id"], 5, lottery["id"], [spots[0]["id"]])
    # Vendor B seniority 8 -> rank 8*10 + 100 - 0 = 180 (higher).
    _, _, eb = fx.create_prime_entrant(zone["id"], commissary["id"], 8, lottery["id"], [spots[0]["id"]])
    get_success_data(api.draw_lottery(lottery["id"], PO))
    entry_b = validate_success(api.get_lottery_entry(eb["id"], PO), 200)
    entry_a = validate_success(api.get_lottery_entry(ea["id"], PO), 200)
    assert entry_b["status"] == "AWARDED"
    assert entry_a["status"] == "WAITLISTED"


# --------------------------------------------------------------------------- #
# Corner calculations: lottery_tie_break_created_at_asc
# --------------------------------------------------------------------------- #
def test_lottery_tie_broken_by_created_at(api):
    """PRD §3.6: "Eligible entries are ordered by rank_score descending, and ties are
    broken by the entry's created_at ascending — never by id and never randomly."

    Design: Corner/calculations/lottery_tie_break_created_at_asc
    """
    lot = fx.setup_prime_zone_with_lottery(capacity_slots=1, spot_positions=(50,))
    zone, spots, commissary, lottery = lot["zone"], lot["spots"], lot["commissary"], lot["lottery"]
    # Two entrants with identical seniority/compliance/points -> equal rank_score 150.
    _, _, ea = fx.create_prime_entrant(zone["id"], commissary["id"], 5, lottery["id"], [spots[0]["id"]])
    _, _, eb = fx.create_prime_entrant(zone["id"], commissary["id"], 5, lottery["id"], [spots[0]["id"]])
    get_success_data(api.draw_lottery(lottery["id"], PO))
    entry_a = validate_success(api.get_lottery_entry(ea["id"], PO), 200)
    entry_b = validate_success(api.get_lottery_entry(eb["id"], PO), 200)
    # ea was created before eb -> ea wins the single spot.
    assert entry_a["status"] == "AWARDED"
    assert entry_b["status"] == "WAITLISTED"


# --------------------------------------------------------------------------- #
# Corner validations: lottery_entry_without_issued_permit_rejected
# --------------------------------------------------------------------------- #
def test_lottery_entry_requires_issued_permit(api):
    """PRD §3.6: "A vendor enters under one of its issued permits by supplying
    permit_id and an ordered preferred_spot_ids list, most-preferred first; entry
    requires that the referenced permit is ISSUED, otherwise ERR_NOT_ELIGIBLE_LOTTERY."

    Design: Corner/validations/lottery_entry_without_issued_permit_rejected
    """
    lot = fx.setup_prime_zone_with_lottery(capacity_slots=1, spot_positions=(50,))
    zone, spots, commissary, lottery = lot["zone"], lot["spots"], lot["commissary"], lot["lottery"]
    vendor = fx.create_vendor()
    cart = fx.create_cart(vendor["id"], commissary["id"], inspect=False, approve=False)
    # Permit only SUBMITTED, never ISSUED.
    permit = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    res = api.create_lottery_entry(
        lottery["id"], create_lottery_entry_payload(permit["id"], [spots[0]["id"]]),
        make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_NOT_ELIGIBLE_LOTTERY", expected_status=422)


# --------------------------------------------------------------------------- #
# Corner state_machines: draw_already_drawn_lottery_not_open
# --------------------------------------------------------------------------- #
def test_draw_already_drawn_lottery_rejected(api):
    """PRD §3.6: "A PermitOfficer draws the lottery, moving it OPEN → DRAWN; a draw on
    a non-open lottery is rejected with ERR_LOTTERY_NOT_OPEN"

    Design: Corner/state_machines/draw_already_drawn_lottery_not_open
    """
    lot = fx.setup_prime_zone_with_lottery(capacity_slots=1, spot_positions=(50,))
    lottery = lot["lottery"]
    get_success_data(api.draw_lottery(lottery["id"], PO))
    res = api.draw_lottery(lottery["id"], PO)
    validate_error(res, "ERR_LOTTERY_NOT_OPEN", expected_status=409)
