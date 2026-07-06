"""Multi-entity cascades and conserved-quantity compensation: plat recordation,
application withdrawal, plat vacate, and the fee-liability / agenda-slot ledgers
(PRD §2.10, §3.2, §3.8)."""
from test_helpers import (
    validate_success,
    make_applicant_headers,
    build_scheduled, build_recorded_plat,
    pay_fee, impact_fee_of,
)
from test_helpers import api_client as api


# --- Plat recordation cascade (depth 4) -----------------------------------

def test_record_cascades_plat_and_assessment(clerk_headers):
    """PRD §3.8: "Recording a PENDING plat moves it to RECORDED and cascades: the assessment
    moves from PROVISIONAL to ASSESSED with final_fee_cents computed and total_fee_cents set
    to it".

    Design: Difficulty/transitive_cascade/plat_record_cascade_fee_app_parcel
    """
    ctx = build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                              recorded_lot_count=4, recorded_gross_acres=10)
    plat = api.get_plat(ctx["plat"]["id"], clerk_headers).json()["data"]
    assert plat["status"] == "RECORDED", f"plat must be RECORDED, got {plat['status']}"
    assert ctx["assessment"]["status"] == "ASSESSED", \
        f"assessment must be ASSESSED after recordation, got {ctx['assessment']['status']}"


def test_record_cascades_application_and_parcel(clerk_headers):
    """PRD §3.8: "the parent application moves from EFFECTIVE to RECORDED with its
    review_window_closed_at stamped; and the parcel moves from ENTITLED to SUBDIVIDED."

    Design: Difficulty/transitive_cascade/plat_record_cascade_fee_app_parcel
    """
    ctx = build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                              recorded_lot_count=4, recorded_gross_acres=10)
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    parcel = api.get_parcel(ctx["parcel"]["id"], clerk_headers).json()["data"]
    assert app["status"] == "RECORDED", f"application must cascade to RECORDED, got {app['status']}"
    assert parcel["status"] == "SUBDIVIDED", f"parcel must cascade to SUBDIVIDED, got {parcel['status']}"


# --- Application withdrawal cascade over the agenda ------------------------

def test_withdraw_removes_agenda_item(clerk_headers):
    """PRD §3.2: "Withdrawal from SCHEDULED additionally cascades over the agenda: every
    still-PLACED agenda item for the application is set to REMOVED, and each removed item
    returns one slot to its hearing (that hearing's agenda_slots_remaining increases by one)."

    Design: Difficulty/transitive_cascade/withdraw_cascade_agenda_and_slots
    """
    ctx = build_scheduled(app_type="VARIANCE")
    headers = make_applicant_headers(ctx["applicant"]["id"])
    withdrawn = validate_success(api.withdraw_application(ctx["app"]["id"], headers), 200)
    assert withdrawn["status"] == "WITHDRAWN", f"application must be WITHDRAWN, got {withdrawn['status']}"
    item = api.get_agenda_item(ctx["item"]["id"], clerk_headers).json()["data"]
    assert item["status"] == "REMOVED", f"agenda item must be REMOVED, got {item['status']}"


def test_withdraw_restores_hearing_slot(clerk_headers):
    """PRD §3.2: "each removed item returns one slot to its hearing (that hearing's
    agenda_slots_remaining increases by one)."

    Design: Difficulty/transitive_cascade/withdraw_cascade_agenda_and_slots
    """
    ctx = build_scheduled(app_type="VARIANCE")
    headers = make_applicant_headers(ctx["applicant"]["id"])
    api.withdraw_application(ctx["app"]["id"], headers)
    hearing = api.get_hearing(ctx["hearing"]["id"], clerk_headers).json()["data"]
    assert hearing["agenda_slots_remaining"] == 5, \
        f"withdrawal must restore the slot to full capacity 5, got {hearing['agenda_slots_remaining']}"


# --- Fee-liability ledger restored on plat vacate -------------------------

def test_vacate_voids_assessment_and_zeroes_ledger(clerk_headers):
    """PRD §3.8: "Vacating a RECORDED plat is the compensating action: the plat moves to
    VACATED, its assessment (whether ASSESSED or PAID) moves to VOIDED, the parcel's
    assessed_fee_cents is reduced by that assessment's total_fee_cents".
    PRD §2.10: "recording a plat adds that assessment's final fee to the parcel's
    assessed_fee_cents, and vacating a recorded plat removes it again, so that a
    record-then-vacate sequence restores the parcel's prior liability exactly."

    Design: Difficulty/compensating_invariant/fee_liability_restored_on_plat_vacate
    """
    ctx = build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                              recorded_lot_count=4, recorded_gross_acres=10)
    pay_fee(ctx["assessment"]["id"], 2152500, ctx["applicant"]["id"])
    validate_success(api.vacate_plat(ctx["plat"]["id"], clerk_headers), 200)
    fee = impact_fee_of(ctx["plat"]["id"])
    assert fee["status"] == "VOIDED", f"assessment must be VOIDED after vacate, got {fee['status']}"
    parcel = api.get_parcel(ctx["parcel"]["id"], clerk_headers).json()["data"]
    assert parcel["assessed_fee_cents"] == 0, \
        f"record-then-vacate must restore assessed_fee_cents to 0, got {parcel['assessed_fee_cents']}"


def test_vacate_reverts_application_and_parcel(clerk_headers):
    """PRD §3.8: "the parent application moves from RECORDED back to EFFECTIVE, and the parcel
    moves from SUBDIVIDED back to ENTITLED."

    Design: Difficulty/compensating_invariant/fee_liability_restored_on_plat_vacate
    """
    ctx = build_recorded_plat(declared_lot_count=4, declared_gross_acres=10,
                              recorded_lot_count=4, recorded_gross_acres=10)
    pay_fee(ctx["assessment"]["id"], 2152500, ctx["applicant"]["id"])
    api.vacate_plat(ctx["plat"]["id"], clerk_headers)
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    parcel = api.get_parcel(ctx["parcel"]["id"], clerk_headers).json()["data"]
    assert app["status"] == "EFFECTIVE", f"application must revert to EFFECTIVE, got {app['status']}"
    assert parcel["status"] == "ENTITLED", f"parcel must revert to ENTITLED, got {parcel['status']}"


# --- Agenda-slot conserved quantity on withdrawal -------------------------

def test_withdraw_restores_slots_to_full_capacity(clerk_headers):
    """PRD §3.4: "At any time, agenda_slots_remaining equals agenda_capacity minus the count
    of agenda items on the hearing whose status is not REMOVED."
    PRD §3.2: "each removed item returns one slot to its hearing (that hearing's
    agenda_slots_remaining increases by one)."

    Design: Difficulty/compensating_invariant/agenda_slots_restored_on_withdraw
    """
    ctx = build_scheduled(app_type="VARIANCE")
    headers = make_applicant_headers(ctx["applicant"]["id"])
    before = api.get_hearing(ctx["hearing"]["id"], clerk_headers).json()["data"]["agenda_slots_remaining"]
    assert before == 4, f"one placement on a capacity-5 hearing leaves 4 slots, got {before}"
    api.withdraw_application(ctx["app"]["id"], headers)
    after = api.get_hearing(ctx["hearing"]["id"], clerk_headers).json()["data"]["agenda_slots_remaining"]
    assert after == 5, f"withdrawal must restore slots to the full capacity 5, got {after}"


def test_withdrawn_item_marked_removed(clerk_headers):
    """PRD §3.2: "every still-PLACED agenda item for the application is set to REMOVED".

    Design: Difficulty/compensating_invariant/agenda_slots_restored_on_withdraw
    """
    ctx = build_scheduled(app_type="VARIANCE")
    headers = make_applicant_headers(ctx["applicant"]["id"])
    api.withdraw_application(ctx["app"]["id"], headers)
    item = api.get_agenda_item(ctx["item"]["id"], clerk_headers).json()["data"]
    assert item["status"] == "REMOVED", f"the placed item must be REMOVED, got {item['status']}"
