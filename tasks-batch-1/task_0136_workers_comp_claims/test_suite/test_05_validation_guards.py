"""Validation guards and ordering: priority-pair conflicts, cross-entity state
dependencies, IME/RTW temporal overlaps, and the field/business validation corners.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_reported_claim,
    setup_lost_time_claim,
    setup_acknowledged_froi,
    setup_transmitted_froi,
    setup_wage_statement,
    setup_reserve,
    setup_disputed_rating,
    setup_scheduled_ime,
    setup_accepted_rtw,
    read_claim,
    set_clock,
    make_employer_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
)
from test_helpers import factories as f

ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["medical_reviewer_headers"]


# ─── Priority-pair conflicts ─────────────────────────

def test_sroi_transmit_nonexistent_report_returns_not_found(api):
    """PRD §2.10: "every path identifier and every foreign key in a request body must
    reference an existing resource, validated in order, with the first unresolved reference
    yielding ERR_NOT_FOUND."
    PRD §2.11: "Existence of every referenced resource is checked next (ERR_NOT_FOUND),
    followed by the state-machine check ... Business rules follow: EDI sequencing
    (ERR_FROI_NOT_ACKNOWLEDGED)."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_referential_on_sroi_transmit
    """
    resp = api.transmit_injury_report(NON_EXISTENT_UUID, ADJUSTER)
    # existence (priority 4) fires before the FROI-sequencing referential check (priority 6)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_transmit_with_unresolved_path_id_returns_not_found_not_referential(api):
    """PRD §2.11: "Existence of every referenced resource is checked next (ERR_NOT_FOUND),
    followed by the state-machine check that the target is in a state from which the requested
    transition is defined (ERR_INVALID_STATE). Business rules follow: EDI sequencing
    (ERR_FROI_NOT_ACKNOWLEDGED)."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_referential_on_sroi_transmit
    """
    # A well-formed but non-existent report id: existence (priority 4) must fire before any
    # FROI-sequencing referential check (priority 6).
    bogus = "11111111-1111-4111-8111-111111111111"
    resp = api.transmit_injury_report(bogus, ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Cross-entity state dependency ───────────────────

def test_lost_time_accept_requires_acknowledged_froi(api):
    """PRD §3.3: "Acceptance into the lost-time path has two preconditions beyond the claim
    being in REPORTED: the claim's FROI must be ACKNOWLEDGED, and a reserve row must already
    exist for the claim. Attempting a lost-time acceptance without an acknowledged first
    report is rejected with ERR_RATING_NOT_FINALIZED (the same guard that protects
    permanent-disability payments)."

    Design: Difficulty/cross_entity_state_dependency/claim_accept_requires_froi_acknowledged
    """
    ctx = setup_reported_claim(disability_days=10)
    claim_id = ctx["claim"]["id"]
    setup_transmitted_froi(claim_id)  # FROI transmitted but NOT acknowledged
    setup_reserve(claim_id, severity_tier="MODERATE", projected_weeks=12)

    resp = api.accept_claim(claim_id, {"disability_days": 10}, ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_RATING_NOT_FINALIZED.value)
    assert read_claim(claim_id)["status"] == "REPORTED"


def test_finalize_disputed_rating_requires_completed_ime(api):
    """PRD §3.8: "A disputed rating can be finalized (moving it DISPUTED → FINALIZED, setting
    finalized_pct to whole_body_pct, and cascading the claim to MMI) only once an IME order
    for that claim has reached COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/rating_finalize_from_disputed_requires_ime_completed
    """
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    claim_id = ctx["claim"]["id"]
    rating, ime = setup_disputed_rating(claim_id, whole_body_pct=15)
    assert ime["status"] == "SCHEDULED"

    resp = api.finalize_impairment_rating(rating["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_impairment_rating(rating["id"], ADJUSTER))["status"] == "DISPUTED"


def test_lost_time_accept_succeeds_once_froi_acknowledged(api):
    """PRD §3.3: "Acceptance into the lost-time path has two preconditions beyond the claim
    being in REPORTED: the claim's FROI must be ACKNOWLEDGED, and a reserve row must already
    exist for the claim."
    PRD §3.3: "When disability_days is greater than 0, acceptance moves the claim
    REPORTED → LOST_TIME and increments the employer's open_claim_count by one."

    Design: Difficulty/cross_entity_state_dependency/claim_accept_requires_froi_acknowledged
    """
    ctx = setup_reported_claim(disability_days=10)
    claim_id = ctx["claim"]["id"]
    setup_acknowledged_froi(claim_id)  # FROI now ACKNOWLEDGED
    setup_reserve(claim_id, severity_tier="MODERATE", projected_weeks=12)

    accepted = validate_success(api.accept_claim(claim_id, {"disability_days": 10}, ADJUSTER), 200)
    assert accepted["status"] == "LOST_TIME", "accept succeeds once the FROI gate is satisfied"


def test_disputed_rating_finalizes_after_ime_completed(api):
    """PRD §3.8: "A disputed rating can be finalized (moving it DISPUTED → FINALIZED, setting
    finalized_pct to whole_body_pct, and cascading the claim to MMI) only once an IME order
    for that claim has reached COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/rating_finalize_from_disputed_requires_ime_completed
    """
    set_clock("2026-03-01T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    claim_id = ctx["claim"]["id"]
    rating, ime = setup_disputed_rating(claim_id, whole_body_pct=15)
    get_success_data(api.complete_ime_order(ime["id"], REVIEWER))  # SCHEDULED -> COMPLETED unblocks finalize

    finalized = validate_success(api.finalize_impairment_rating(rating["id"], REVIEWER), 200)
    assert finalized["status"] == "FINALIZED", "finalize is unlocked once the IME is COMPLETED"


# ─── Temporal overlaps ───────────────────────────────

def test_ime_window_half_open_overlap_rejected(api):
    """PRD §3.9: "The window may not overlap another non-terminal IME order for the same
    claim; overlap is judged on half-open intervals where touching endpoints do not count as
    overlapping, and a conflicting window is rejected with ERR_IME_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/ime_window_half_open_same_claim_overlap
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_scheduled_ime(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T12:00:00Z", "Dr A")

    resp = api.create_ime_order(
        f.create_ime_order_payload(claim_id, "2026-03-10T11:00:00Z", "2026-03-10T13:00:00Z", "Dr B"),
        ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_IME_WINDOW_CONFLICT.value)


def test_ime_window_contained_overlap_rejected(api):
    """PRD §3.9: "The window may not overlap another non-terminal IME order for the same
    claim; overlap is judged on half-open intervals where touching endpoints do not count as
    overlapping, and a conflicting window is rejected with ERR_IME_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/ime_window_half_open_same_claim_overlap
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_scheduled_ime(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T14:00:00Z", "Dr A")
    # a second window strictly inside the first strictly intersects it
    resp = api.create_ime_order(
        f.create_ime_order_payload(claim_id, "2026-03-10T11:00:00Z", "2026-03-10T12:00:00Z", "Dr B"),
        ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_IME_WINDOW_CONFLICT.value)


def test_ime_window_touching_endpoints_accepted(api):
    """PRD §3.9: "overlap is judged on half-open intervals where touching endpoints do not
    count as overlapping."

    Design: Difficulty/boundary_precision_check/ime_window_touching_endpoints_no_overlap
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_scheduled_ime(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z", "Dr First")

    second = validate_success(
        api.create_ime_order(
            f.create_ime_order_payload(claim_id, "2026-03-10T11:00:00Z", "2026-03-10T12:00:00Z", "Dr Second"),
            ADJUSTER,
        ),
        201,
    )
    assert second["status"] == "SCHEDULED", "windows touching at 11:00 do not overlap"


def test_ime_window_one_second_earlier_conflicts(api):
    """PRD §3.9: "The window may not overlap another non-terminal IME order for the same
    claim; overlap is judged on half-open intervals where touching endpoints do not count as
    overlapping, and a conflicting window is rejected with ERR_IME_WINDOW_CONFLICT."

    Design: Difficulty/boundary_precision_check/ime_window_touching_endpoints_no_overlap
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_scheduled_ime(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z", "Dr First")

    resp = api.create_ime_order(
        f.create_ime_order_payload(claim_id, "2026-03-10T10:59:59Z", "2026-03-10T12:00:00Z", "Dr Second"),
        ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_IME_WINDOW_CONFLICT.value)


def test_rtw_offer_within_buffer_of_accepted_conflicts(api):
    """PRD §3.10: "Its window may not overlap an already-accepted offer for the same claim,
    and a required buffer gap of 7 days must separate consecutive light-duty assignments —
    an offer that begins within 7 days of a prior accepted offer's end is treated as
    overlapping and is rejected with ERR_RTW_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/rtw_window_buffer_gap_same_claim_overlap
    """
    set_clock("2026-02-15T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    employer_id = ctx["employer"]["id"]
    claim_id = ctx["claim"]["id"]
    setup_accepted_rtw(
        claim_id, employer_id, light_duty_weekly_cents=90_000,
        start_date="2026-03-01T00:00:00Z", end_date="2026-03-10T00:00:00Z",
    )

    headers = make_employer_headers(employer_id)
    resp = api.create_rtw_offer(
        f.create_rtw_offer_payload(claim_id, 80_000, "2026-03-12T00:00:00Z", "2026-03-20T00:00:00Z"),
        headers,
    )
    # start 03-12 is within 7-day buffer of prior accepted end 03-10
    validate_error(resp, ApiErrorId.ERR_RTW_WINDOW_CONFLICT.value)


def test_rtw_offer_past_buffer_accepted(api):
    """PRD §3.10: "a required buffer gap of 7 days must separate consecutive light-duty
    assignments — an offer that begins within 7 days of a prior accepted offer's end is
    treated as overlapping and is rejected with ERR_RTW_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/rtw_window_buffer_gap_same_claim_overlap
    """
    set_clock("2026-02-15T00:00:00Z")
    ctx = setup_lost_time_claim(
        disability_days=10, projected_weeks=12, with_wage_statement=False,
        date_of_injury="2026-02-01T00:00:00Z",
    )
    employer_id = ctx["employer"]["id"]
    claim_id = ctx["claim"]["id"]
    setup_accepted_rtw(
        claim_id, employer_id, light_duty_weekly_cents=90_000,
        start_date="2026-03-01T00:00:00Z", end_date="2026-03-10T00:00:00Z",
    )

    headers = make_employer_headers(employer_id)
    accepted = validate_success(
        api.create_rtw_offer(
            f.create_rtw_offer_payload(claim_id, 80_000, "2026-03-17T00:00:00Z", "2026-03-25T00:00:00Z"),
            headers,
        ),
        201,
    )
    assert accepted["status"] == "OFFERED", "start 03-17 is >= end 03-10 + 7-day buffer"


# ─── Validation corners ──────────────────────────────

def test_invalid_mtc_for_froi_rejected(api):
    """PRD §3.2: "The maintenance code must agree with the report kind: a FROI requires the
    code 00, while a SROI requires one of IP, CB, SX, or FN; any other pairing is rejected
    with ERR_INVALID_MTC."

    Design: Corner/validations/invalid_mtc_for_froi_returns_422
    """
    ctx = setup_reported_claim()
    resp = api.create_injury_report(
        f.create_injury_report_payload(ctx["claim"]["id"], "FROI", "IP"), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_MTC.value)


def test_claim_created_past_statute_rejected(api):
    """PRD §3.2: "A statute-of-limitations guard applies at creation: a claim whose
    date_of_injury is more than the statutory filing window — 730 days, that is two years —
    before the current logical time may not be opened, and the attempt is rejected with
    ERR_STATUTE_EXPIRED."

    Design: Corner/validations/claim_created_past_statute_returns_422
    """
    employer = get_success_data(api.create_employer(f.create_employer_payload(), ADMIN))
    policy = get_success_data(
        api.create_policy(
            f.create_policy_payload(employer["id"], policy_number="C-SOL-x", expiration_date="2031-01-01T00:00:00Z"),
            ADMIN,
        )
    )
    worker = get_success_data(api.create_worker(f.create_worker_payload(employer["id"]), ADMIN))
    set_clock("2030-01-01T00:00:00Z")

    resp = api.create_claim(
        f.create_claim_payload(policy["id"], worker["id"], date_of_injury="2026-02-01T00:00:00Z"), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_STATUTE_EXPIRED.value)


def test_duplicate_reserve_per_claim_rejected(api):
    """PRD §3.4: "at most one reserve may exist per claim, and a second attempt is rejected
    with ERR_DUPLICATE_RESOURCE."

    Design: Corner/validations/duplicate_reserve_per_claim_returns_409
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_reserve(claim_id, severity_tier="MINOR", projected_weeks=4)

    resp = api.create_reserve(
        f.create_reserve_payload(claim_id, severity_tier="MODERATE", projected_weeks=12), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_oversized_payment_returns_reserve_insufficient(api):
    """PRD §3.6: "A payment may not draw down more indemnity than is outstanding: if the
    computed amount_cents would exceed the claim's indemnity_reserve_cents, the payment is
    rejected with ERR_RESERVE_INSUFFICIENT."

    Design: Corner/validations/reserve_insufficient_on_oversized_payment_returns_422
    """
    # reserve with projected_weeks=1 -> indemnity_reserve_cents 100005; PPD would be 4500225
    ctx = setup_lost_time_claim(
        disability_days=10, severity_tier="MINOR", projected_weeks=1, average_weekly_wage_cents=150_000
    )
    claim_id = ctx["claim"]["id"]
    rating = get_success_data(
        api.create_impairment_rating(f.create_impairment_rating_payload(claim_id, 15, "IME"), REVIEWER)
    )
    get_success_data(api.finalize_impairment_rating(rating["id"], REVIEWER))

    resp = api.create_benefit_payment(
        f.create_benefit_payment_payload(claim_id, "PPD", impairment_rating_id=rating["id"]), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_RESERVE_INSUFFICIENT.value)


def test_ppd_with_non_finalized_rating_rejected(api):
    """PRD §3.6: "the impairment_rating_id field is required and must reference a finalized
    rating; a permanent-partial payment that references a rating not in FINALIZED status is
    rejected with ERR_RATING_NOT_FINALIZED."

    Design: Corner/validations/ppd_with_non_finalized_rating_returns_409
    """
    ctx = setup_lost_time_claim(
        disability_days=10, severity_tier="SEVERE", projected_weeks=60, average_weekly_wage_cents=150_000
    )
    claim_id = ctx["claim"]["id"]
    rating = get_success_data(
        api.create_impairment_rating(f.create_impairment_rating_payload(claim_id, 15, "TREATING"), REVIEWER)
    )  # PROPOSED, not finalized

    resp = api.create_benefit_payment(
        f.create_benefit_payment_payload(claim_id, "PPD", impairment_rating_id=rating["id"]), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_RATING_NOT_FINALIZED.value)
