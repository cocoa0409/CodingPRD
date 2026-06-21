"""State machines: the EDI reject/retransmit correction loop, the impairment-rating
dispute-vs-finalize fork, the depth-3 dispute -> IME -> finalize -> MMI cascade,
and the per-machine transition/precondition corners.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_reported_claim,
    setup_medical_only_claim,
    setup_lost_time_claim,
    setup_acknowledged_froi,
    setup_transmitted_froi,
    setup_disputed_rating,
    setup_scheduled_ime,
    setup_offered_rtw,
    read_claim,
    set_clock,
    make_employer_headers,
    TEST_USERS,
    ApiErrorId,
)
from test_helpers import factories as f

ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["medical_reviewer_headers"]


# ─── EDI correction loop ─────────────────────────────

def test_injury_report_reject_then_retransmit_cycle(api):
    """PRD §3.2: "A rejected report is not dead: the correction loop lets an adjuster
    re-transmit it, moving it REJECTED → TRANSMITTED (again subject to the FROI-before-SROI
    gate for subsequent reports), so the EDI cycle can repeat until acknowledgement lands."
    PRD §3.2: "or rejects it, moving it TRANSMITTED → REJECTED and recording the supplied
    rejection_code."

    Design: Difficulty/non_linear_state_machine/injury_report_edi_reject_retransmit_cycle
    """
    ctx = setup_reported_claim()
    froi = setup_transmitted_froi(ctx["claim"]["id"])
    rejected = validate_success(api.reject_injury_report(froi["id"], {"rejection_code": "TR-051"}, ADMIN), 200)
    assert rejected["edi_status"] == "REJECTED"
    assert rejected["rejection_code"] == "TR-051"

    retransmitted = validate_success(api.transmit_injury_report(froi["id"], ADJUSTER), 200)
    assert retransmitted["edi_status"] == "TRANSMITTED", "rejected report re-enters TRANSMITTED"
    assert retransmitted["rejection_code"] == "TR-051", "rejection_code from the REJECTED hop persists"


def test_retransmitted_report_can_be_acknowledged(api):
    """PRD §3.2: "A rejected report is not dead: the correction loop lets an adjuster
    re-transmit it, moving it REJECTED → TRANSMITTED ... so the EDI cycle can repeat until
    acknowledgement lands."
    PRD §3.2: "The carrier-side administrator then either acknowledges a transmitted report,
    moving it TRANSMITTED → ACKNOWLEDGED (a terminal state)."

    Design: Difficulty/non_linear_state_machine/injury_report_edi_reject_retransmit_cycle
    """
    ctx = setup_reported_claim()
    froi = setup_transmitted_froi(ctx["claim"]["id"])
    get_success_data(api.reject_injury_report(froi["id"], {"rejection_code": "TR-051"}, ADMIN))
    get_success_data(api.transmit_injury_report(froi["id"], ADJUSTER))  # REJECTED -> TRANSMITTED
    acked = validate_success(api.ack_injury_report(froi["id"], ADMIN), 200)
    assert acked["edi_status"] == "ACKNOWLEDGED", "the cycle terminates at ACKNOWLEDGED after a reject loop"


# ─── Impairment rating branch ────────────────────────

def test_ime_rating_finalizes_directly_without_dispute(api):
    """PRD §3.8: "An IME-issued rating needs no dispute round: from PROPOSED a reviewer
    finalizes it directly, moving it PROPOSED → FINALIZED, setting finalized_pct to the
    rating's whole_body_pct, and cascading the owning claim to MMI."

    Design: Difficulty/non_linear_state_machine/impairment_rating_branch_dispute_vs_finalize
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    claim_id = ctx["claim"]["id"]
    rating = get_success_data(
        api.create_impairment_rating(f.create_impairment_rating_payload(claim_id, 12, "IME"), REVIEWER)
    )
    finalized = validate_success(api.finalize_impairment_rating(rating["id"], REVIEWER), 200)
    assert finalized["status"] == "FINALIZED"
    assert read_claim(claim_id)["status"] == "MMI", "finalize cascades the claim to MMI"

    ime_list, _ = _list(api.list_claim_ime_orders(claim_id, ADJUSTER))
    assert len(ime_list) == 0, "the IME branch synthesizes no IME order"


def test_dispute_branch_creates_ime_order(api):
    """PRD §3.8: "A TREATING-physician rating may instead be disputed by the adjuster while
    it is PROPOSED, which moves it PROPOSED → DISPUTED and cascades the creation of a fresh
    IME order for the same claim — that order is scheduled to begin at the current logical
    time and end one day later, with examiner_name set to PENDING_ASSIGNMENT, so it is
    immediately completable."

    Design: Difficulty/non_linear_state_machine/impairment_rating_branch_dispute_vs_finalize
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    claim_id = ctx["claim"]["id"]
    rating, ime = setup_disputed_rating(claim_id, whole_body_pct=15)
    assert rating["status"] == "DISPUTED"
    assert ime is not None and ime["status"] == "SCHEDULED", "dispute synthesizes a SCHEDULED IME"


# ─── Depth-3 cascade ─────────────────────────────────

def test_dispute_ime_complete_finalize_cascade_to_mmi(api):
    """PRD §3.8: "A disputed rating can be finalized (moving it DISPUTED → FINALIZED, setting
    finalized_pct to whole_body_pct, and cascading the claim to MMI) only once an IME order
    for that claim has reached COMPLETED."
    PRD §3.9: "A reviewer completes the exam — permitted only once the current logical time
    has reached or passed scheduled_start — moving it SCHEDULED → COMPLETED."

    Design: Difficulty/transitive_cascade/dispute_creates_ime_then_complete_then_finalize_to_mmi
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    claim_id = ctx["claim"]["id"]
    rating, ime = setup_disputed_rating(claim_id, whole_body_pct=15)
    assert ime["status"] == "SCHEDULED"

    completed = validate_success(api.complete_ime_order(ime["id"], REVIEWER), 200)
    assert completed["status"] == "COMPLETED"

    finalized = validate_success(api.finalize_impairment_rating(rating["id"], REVIEWER), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_pct"] == 15
    assert read_claim(claim_id)["status"] == "MMI", "the depth-3 terminal hop"


# ─── Claim state corners ─────────────────────────────

def test_new_claim_starts_reported_unclassified(api):
    """PRD §3.2: "A claim begins life in REPORTED status with claim_class of UNCLASSIFIED
    and a null denial_reason."

    Design: Corner/state_machines/new_claim_starts_in_reported
    """
    ctx = setup_reported_claim()
    claim = ctx["claim"]
    assert claim["status"] == "REPORTED"
    assert claim["claim_class"] == "UNCLASSIFIED"


def test_medical_only_classification_on_zero_disability_accept(api):
    """PRD §3.3: "When the claim's disability_days is 0, acceptance moves the claim
    REPORTED → MEDICAL_ONLY, sets claim_class to MEDICAL_ONLY, and increments the employer's
    open_claim_count by one."

    Design: Corner/state_machines/medical_only_classification_on_zero_disability_accept
    """
    ctx = setup_medical_only_claim()
    claim = ctx["claim"]
    assert claim["status"] == "MEDICAL_ONLY"
    assert claim["claim_class"] == "MEDICAL_ONLY"
    employer = get_success_data(api.get_employer(ctx["employer"]["id"], ADMIN))
    assert employer["open_claim_count"] == 1


def test_deny_already_denied_claim_returns_invalid_state(api):
    """PRD §3.3: "Denial moves the claim REPORTED → DENIED (a terminal state) and records
    the supplied denial_reason."
    PRD §2.11: "the state-machine check that the target is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."

    Design: Corner/state_machines/deny_already_denied_claim_returns_invalid_state
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    get_success_data(api.deny_claim(claim_id, {"denial_reason": "first"}, ADJUSTER))

    resp = api.deny_claim(claim_id, {"denial_reason": "second"}, ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_claim(claim_id)["denial_reason"] == "first", "second deny has no side effect"


def test_close_mmi_blocked_by_outstanding_indemnity_reserve(api):
    """PRD §3.11: "A lost-time claim must first reach maximum medical improvement; from MMI
    it may be closed, moving it MMI → CLOSED, provided the claim's indemnity_reserve_cents has
    been fully drawn down to 0 and no IME order for the claim remains SCHEDULED."

    Design: Corner/state_machines/close_mmi_blocked_by_outstanding_indemnity_reserve
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    claim_id = ctx["claim"]["id"]
    rating = get_success_data(
        api.create_impairment_rating(f.create_impairment_rating_payload(claim_id, 15, "IME"), REVIEWER)
    )
    get_success_data(api.finalize_impairment_rating(rating["id"], REVIEWER))
    assert read_claim(claim_id)["status"] == "MMI"

    resp = api.close_claim(claim_id, ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_claim(claim_id)["status"] == "MMI"


# ─── InjuryReport / IME / RTW corners ────────────────

def test_sroi_transmit_before_froi_ack_rejected(api):
    """PRD §3.2: "a SROI may not be transmitted unless a FROI for the same claim has already
    reached ACKNOWLEDGED, and an attempt to transmit a subsequent report before its first
    report is acknowledged is rejected with ERR_FROI_NOT_ACKNOWLEDGED."

    Design: Corner/state_machines/sroi_transmit_before_froi_ack_returns_froi_not_acknowledged
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_transmitted_froi(claim_id)  # FROI transmitted but NOT acknowledged
    sroi = get_success_data(
        api.create_injury_report(f.create_injury_report_payload(claim_id, "SROI", "IP"), ADJUSTER)
    )
    resp = api.transmit_injury_report(sroi["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_FROI_NOT_ACKNOWLEDGED.value)
    assert get_success_data(api.get_injury_report(sroi["id"], ADJUSTER))["edi_status"] == "DRAFT"


def test_ime_no_show_before_window_end_rejected(api):
    """PRD §3.9: "A reviewer marks a no-show — permitted only once the current logical time
    has reached or passed scheduled_end — moving it SCHEDULED → NO_SHOW."

    Design: Corner/state_machines/ime_no_show_before_window_end_returns_invalid_state
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    ime = setup_scheduled_ime(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z", "Dr A")
    set_clock("2026-03-10T10:30:00Z")  # before scheduled_end 11:00

    resp = api.no_show_ime_order(ime["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_ime_order(ime["id"], ADJUSTER))["status"] == "SCHEDULED"


def test_rtw_offer_expires_when_clock_passes_start(api):
    """PRD §3.10: "an offer left unanswered expires by the passage of time: once the logical
    clock reaches or passes the offer's start_date while it is still OFFERED, the offer
    transitions OFFERED → EXPIRED."
    PRD §3.10: "acceptance is permitted only while the offer's claim is in LOST_TIME and only
    if the current logical time is before the offer's start_date."

    Design: Corner/state_machines/rtw_offer_expires_when_clock_passes_start
    """
    set_clock("2026-02-15T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    employer_id = ctx["employer"]["id"]
    offer = setup_offered_rtw(
        ctx["claim"]["id"], employer_id, light_duty_weekly_cents=90_000,
        start_date="2026-03-01T00:00:00Z", end_date="2026-03-20T00:00:00Z",
    )
    set_clock("2026-03-05T00:00:00Z")  # past start_date

    headers = make_employer_headers(employer_id)
    resp = api.accept_rtw_offer(offer["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_rtw_offer(offer["id"], headers))["status"] == "EXPIRED"


def _list(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})
