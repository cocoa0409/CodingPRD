"""Numeric boundaries, temporal constraints, and conserved-quantity invariants:
the 1099 threshold crossing at exactly 60000, the empty certification set,
rotation cooldown and inclusive due-window boundaries, the wave billable invariant,
and the ytd_paid invariant under a blocked void.

Covers difficulty rules boundary_precision_check, resource_temporal_overlap, and
compensating_invariant.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, fixtures
from test_helpers.test_users import (
    make_shopper_headers,
    make_qa_validator_headers,
    make_finance_officer_headers,
    make_client_manager_headers,
)


# ---------------------------------------------------------------------------
# boundary_precision_check / tax_1099_threshold_exact_60000_crosses
# ---------------------------------------------------------------------------
def _build_60000_batch(api, tax_id_on_file):
    """Validated assignment whose Reimbursement.amount_cents is exactly 60000
    (receipt 48000 capped 50000 -> reimbursable 48000; base_fee 10000 HIGH bonus
    0.20 -> fee 12000). Collected into an OPEN batch. Returns (shopper_id, asg_id,
    reimb, batch_id)."""
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    # Location at shopper home -> travel 0.
    location = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0)
    script = fixtures.create_and_publish_script(
        cid, scenario_family="RETAIL", weights_json={"greeting": 1.0},
        required_photo_count=0, receipt_required=True, reimburse_cap_cents=50000,
        base_fee_cents=10000,
    )
    wave = fixtures.create_and_publish_wave(cid)
    shopper = fixtures.register_shopper(tax_id_on_file=tax_id_on_file, home_lat=40.0, home_lng=-74.0)
    fixtures.certify_shopper(shopper["id"], scenario_family="RETAIL")
    sid = shopper["id"]
    asg = fixtures.create_in_field_assignment(
        cid, wave["id"], sid, location["id"], script["id"], "2026-06-25T00:00:00Z",
    )
    aid = asg["id"]
    fixtures.add_reviewed_evidence(aid, sid, "RECEIPT", "APPROVE",
                                   object_uri="s3://e/r.jpg", receipt_amount_cents=48000)
    fixtures.create_scorecard(aid, sid, {"greeting": 88})
    validate_success(api.submit_assignment(aid, make_shopper_headers(sid)))
    validate_success(api.validate_assignment(aid, make_qa_validator_headers()))
    reimb = fixtures.get_assignment_reimbursement(aid)
    batch = validate_success(
        api.create_payout_batch({"shopper_id": sid, "reimbursement_ids": [reimb["id"]]},
                                make_finance_officer_headers()),
        expected_status=201,
    )
    return sid, aid, reimb, batch["id"]


def test_reimbursement_amount_is_60000_at_threshold(api):
    """PRD 3.9: "Each validation books a Reimbursement that records the owning
    assignment_id, the payee shopper_id, and an amount_cents equal to the final
    reimbursable amount plus the shopper fee."

    Design: Difficulty/boundary_precision_check/tax_1099_threshold_exact_60000_crosses
    """
    _, _, reimb, _ = _build_60000_batch(api, tax_id_on_file=False)
    # reimbursable min(48000,50000)+0 = 48000; fee 10000 + round_half_up(2000) = 12000; total 60000.
    assert reimb["amount_cents"] == 60000, (
        f"Reimbursement.amount_cents expected 60000, got {reimb['amount_cents']}"
    )


def test_pay_at_exactly_60000_requires_tax_id_on_file(api):
    """PRD 3.9: "The batch's requires_1099 is true exactly when the new
    year-to-date is at least 60000 cents and the prior year-to-date was below 60000
    cents. A batch crossing exactly to 60000 cents triggers 1099 reporting..."
    PRD 2.8: "Paying a batch that has been determined to require 1099 reporting
    demands that the payee shopper's tax_id_on_file flag is true; if a 1099-required
    batch is paid for a shopper whose tax_id_on_file is false, the request is
    rejected with ERR_TAX_ID_REQUIRED."

    Design: Difficulty/boundary_precision_check/tax_1099_threshold_exact_60000_crosses
    """
    _, _, _, batch_id = _build_60000_batch(api, tax_id_on_file=False)
    resp = api.pay_payout_batch(batch_id, make_finance_officer_headers())
    validate_error(resp, ApiErrorId.ERR_TAX_ID_REQUIRED.value)


# ---------------------------------------------------------------------------
# boundary_precision_check / certification_attempts_empty_set_zero_certification_score
# ---------------------------------------------------------------------------
def test_new_shopper_has_zero_certification_score(api):
    """PRD 3.1: "A newly registered shopper starts in REGISTERED status with a
    reliability_score of 100.0 and a certification_score of 0."

    Design: Difficulty/boundary_precision_check/certification_attempts_empty_set_zero_certification_score
    """
    shopper = fixtures.register_shopper(tax_id_on_file=False, home_lat=40.0, home_lng=-74.0)
    assert shopper["certification_score"] == 0, (
        f"certification_score expected 0 at registration, got {shopper['certification_score']}"
    )
    assert shopper["status"] == "REGISTERED"


def test_failing_certification_attempt_leaves_score_and_status_unchanged(api):
    """PRD 3.2: "The attempt's outcome is computed: it is PASSED when the raw_score
    is at least 70, and FAILED otherwise."
    PRD 3.2: "A failing attempt (a raw_score below 70) leaves the shopper REGISTERED
    and leaves certification_score unchanged."

    Design: Difficulty/boundary_precision_check/certification_attempts_empty_set_zero_certification_score
    """
    shopper = fixtures.register_shopper(tax_id_on_file=False, home_lat=40.0, home_lng=-74.0)
    sid = shopper["id"]
    attempt = validate_success(
        api.create_certification_attempt(sid, {"raw_score": 69, "scenario_family": "RETAIL"},
                                         make_qa_validator_headers()),
        expected_status=201,
    )
    assert attempt["outcome"] == "FAILED", (
        f"outcome expected FAILED for raw_score 69, got {attempt['outcome']}"
    )
    refreshed = validate_success(api.get_shopper(sid, make_qa_validator_headers()))
    assert refreshed["certification_score"] == 0, (
        f"certification_score expected 0 after FAILED attempt, got {refreshed['certification_score']}"
    )
    assert refreshed["status"] == "REGISTERED", (
        f"status expected REGISTERED after FAILED attempt, got {refreshed['status']}"
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap / rotation_cooldown_blocks_same_location_within_window
# ---------------------------------------------------------------------------
def test_rotation_cooldown_blocks_same_location_within_window(api):
    """PRD 3.4: "Finally, a rotation cooldown applies: the shopper must not have
    another assignment to the same location whose due_at falls within
    rotation_cooldown_days before the new due_at; a too-soon repeat at the same
    location is rejected with ERR_ROTATION_COOLDOWN."

    Design: Difficulty/resource_temporal_overlap/rotation_cooldown_blocks_same_location_within_window
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
        rotation_cooldown_days=30, window_start="2026-06-01T00:00:00Z",
        window_end="2026-07-30T00:00:00Z",
    )
    cid, wave_id = cat["client"]["id"], cat["wave"]["id"]
    loc_id, script_id, sid = cat["location"]["id"], cat["script"]["id"], cat["shopper"]["id"]
    fixtures.create_assignment(cid, wave_id, sid, loc_id, script_id, "2026-06-10T00:00:00Z")
    cm = make_client_manager_headers(cid)
    payload = fixtures.factories.create_assignment_payload(
        wave_id, sid, loc_id, script_id, "2026-06-25T00:00:00Z",
    )
    resp = api.create_assignment(payload, cm)
    validate_error(resp, ApiErrorId.ERR_ROTATION_COOLDOWN.value)


def test_rotation_cooldown_allows_same_location_after_window(api):
    """PRD 3.4: "Finally, a rotation cooldown applies: the shopper must not have
    another assignment to the same location whose due_at falls within
    rotation_cooldown_days before the new due_at; a too-soon repeat at the same
    location is rejected with ERR_ROTATION_COOLDOWN."

    A second assignment whose due_at is more than rotation_cooldown_days after the
    prior due_at is outside the cooldown and is accepted.

    Design: Difficulty/resource_temporal_overlap/rotation_cooldown_blocks_same_location_within_window
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
        rotation_cooldown_days=30, window_start="2026-06-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )
    cid, wave_id = cat["client"]["id"], cat["wave"]["id"]
    loc_id, script_id, sid = cat["location"]["id"], cat["script"]["id"], cat["shopper"]["id"]
    fixtures.create_assignment(cid, wave_id, sid, loc_id, script_id, "2026-06-10T00:00:00Z")
    cm = make_client_manager_headers(cid)
    # 2026-07-20 is 40 days after 2026-06-10, beyond the 30-day cooldown.
    payload = fixtures.factories.create_assignment_payload(
        wave_id, sid, loc_id, script_id, "2026-07-20T00:00:00Z",
    )
    asg = validate_success(api.create_assignment(payload, cm), expected_status=201)
    assert asg["status"] == "ASSIGNED", "same-location assignment beyond cooldown must be accepted"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / due_at_outside_wave_window_inclusive_boundary
# ---------------------------------------------------------------------------
def test_due_at_at_window_end_is_accepted(api):
    """PRD 3.4: "The due_at must fall within the wave's field window, at or after
    field_window_start and at or before field_window_end (both ends inclusive); a
    deadline outside that window is rejected with ERR_DUE_OUTSIDE_WINDOW."

    Design: Difficulty/resource_temporal_overlap/due_at_outside_wave_window_inclusive_boundary
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
        window_start="2026-06-01T00:00:00Z", window_end="2026-06-30T00:00:00Z",
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    payload = fixtures.factories.create_assignment_payload(
        cat["wave"]["id"], cat["shopper"]["id"], cat["location"]["id"],
        cat["script"]["id"], "2026-06-30T00:00:00Z",  # exactly field_window_end
    )
    asg = validate_success(api.create_assignment(payload, cm), expected_status=201)
    assert asg["status"] == "ASSIGNED", "due_at == field_window_end must be accepted (inclusive)"


def test_due_at_past_window_end_is_rejected(api):
    """PRD 3.4: "The due_at must fall within the wave's field window, at or after
    field_window_start and at or before field_window_end (both ends inclusive); a
    deadline outside that window is rejected with ERR_DUE_OUTSIDE_WINDOW."

    Design: Difficulty/resource_temporal_overlap/due_at_outside_wave_window_inclusive_boundary
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
        window_start="2026-06-01T00:00:00Z", window_end="2026-06-30T00:00:00Z",
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    payload = fixtures.factories.create_assignment_payload(
        cat["wave"]["id"], cat["shopper"]["id"], cat["location"]["id"],
        cat["script"]["id"], "2026-07-01T00:00:00Z",  # one day past field_window_end
    )
    resp = api.create_assignment(payload, cm)
    validate_error(resp, ApiErrorId.ERR_DUE_OUTSIDE_WINDOW.value)


# ---------------------------------------------------------------------------
# compensating_invariant / wave_validated_count_invariant_under_validate...
# ---------------------------------------------------------------------------
def test_wave_billable_equals_validated_count_times_fee(api):
    """PRD 3.6: "The platform counts the assignments in the wave whose status is
    VALIDATED, stores that count as validated_shop_count, and sets
    client_billable_cents to that count multiplied by the owning client's
    fee_per_completed_shop_cents (an exact integer multiply, no rounding)."

    Two validations in one wave keep the billable invariant exact (no off-by-one).

    Design: Difficulty/compensating_invariant/wave_validated_count_invariant_under_validate_then_reject_overturn
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    loc1 = fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0, label="L1")
    loc2 = fixtures.create_location(cid, scenario_family="RETAIL", lat=41.0, lng=-75.0, label="L2")
    script = fixtures.create_and_publish_script(cid, scenario_family="RETAIL",
                                                weights_json={"greeting": 1.0})
    wave = fixtures.create_and_publish_wave(cid)
    wave_id = wave["id"]

    def validate_one(loc_id, due_at, home_lat, home_lng):
        sh = fixtures.register_shopper(tax_id_on_file=True, home_lat=home_lat, home_lng=home_lng)
        fixtures.certify_shopper(sh["id"], scenario_family="RETAIL")
        asg = fixtures.create_in_field_assignment(cid, wave_id, sh["id"], loc_id, script["id"], due_at)
        fixtures.add_approved_photo(asg["id"], sh["id"])
        fixtures.create_scorecard(asg["id"], sh["id"], {"greeting": 88})
        validate_success(api.submit_assignment(asg["id"], make_shopper_headers(sh["id"])))
        validate_success(api.validate_assignment(asg["id"], make_qa_validator_headers()))

    validate_one(loc1["id"], "2026-06-10T00:00:00Z", 40.0, -74.0)
    validate_one(loc2["id"], "2026-06-12T00:00:00Z", 41.0, -75.0)
    cm = make_client_manager_headers(cid)
    wave_now = validate_success(api.get_wave(wave_id, cm))
    assert wave_now["validated_shop_count"] == 2, (
        f"validated_shop_count expected 2, got {wave_now['validated_shop_count']}"
    )
    assert wave_now["client_billable_cents"] == 30000, (
        f"client_billable_cents expected 30000 (2 * 15000), got {wave_now['client_billable_cents']}"
    )
    fixtures.assertions.assert_wave_billable_invariant(wave_now, 15000)


def test_wave_billable_invariant_holds_after_single_validation(api):
    """PRD 3.6: "The wave's billable counter is recomputed from scratch on every
    change rather than nudged, to keep it from drifting. The platform counts the
    assignments in the wave whose status is VALIDATED, stores that count as
    validated_shop_count, and sets client_billable_cents to that count multiplied by
    the owning client's fee_per_completed_shop_cents (an exact integer multiply, no
    rounding)."

    A single validation against a distinct fee value confirms the exact-multiply
    invariant client_billable_cents == validated_shop_count * fee with no drift.

    Design: Difficulty/compensating_invariant/wave_validated_count_invariant_under_validate_then_reject_overturn
    """
    cat = fixtures.setup_validated_assignment(
        due_at="2026-06-10T00:00:00Z", loc_lat=40.0, loc_lng=-74.0,
        fee_per_completed_shop_cents=27000,
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    wave = validate_success(api.get_wave(cat["wave"]["id"], cm))
    assert wave["validated_shop_count"] == 1, (
        f"validated_shop_count expected 1, got {wave['validated_shop_count']}"
    )
    assert wave["client_billable_cents"] == 27000, (
        f"client_billable_cents expected 27000 (1 * 27000), got {wave['client_billable_cents']}"
    )
    fixtures.assertions.assert_wave_billable_invariant(wave, 27000)


# ---------------------------------------------------------------------------
# compensating_invariant / ytd_paid_invariant_under_pay_then_void_blocked...
# ---------------------------------------------------------------------------
def test_void_on_paid_batch_is_rejected_invalid_state(api):
    """PRD 3.9: "A FinanceOfficer may void an OPEN batch, moving it OPEN -> VOIDED..."
    Void is defined only from OPEN, so a PAID batch cannot be voided.

    Design: Difficulty/compensating_invariant/ytd_paid_invariant_under_pay_then_void_blocked_keeps_total
    """
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-10T00:00:00Z", tax_id_on_file=True)
    batch_id = cat["batch"]["id"]
    validate_success(api.pay_payout_batch(batch_id, make_finance_officer_headers()))
    resp = api.void_payout_batch(batch_id, make_finance_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_ytd_paid_conserved_when_void_blocked(api):
    """PRD 3.9: "On payment the batch becomes PAID, each member reimbursement becomes
    PAID, the shopper's ytd_paid_cents is incremented by the batch's
    gross_amount_cents, and the platform evaluates the 1099 threshold."

    The blocked void leaves ytd_paid_cents at exactly the paid gross (2400: fee at
    reliability 100, reimbursable 0 with travel 0 and no receipt).

    Design: Difficulty/compensating_invariant/ytd_paid_invariant_under_pay_then_void_blocked_keeps_total
    """
    # Location at shopper home (travel 0); no receipt -> reimbursable 0; base_fee 2000
    # at reliability 100 -> HIGH bonus 0.20 -> fee 2400 -> amount_cents 2400.
    cat = fixtures.setup_batched_reimbursement(
        due_at="2026-06-10T00:00:00Z", tax_id_on_file=True, loc_lat=40.0, loc_lng=-74.0,
    )
    sid, batch_id = cat["shopper"]["id"], cat["batch"]["id"]
    paid = validate_success(api.pay_payout_batch(batch_id, make_finance_officer_headers()))
    assert paid["gross_amount_cents"] == 2400, (
        f"gross_amount_cents expected 2400, got {paid['gross_amount_cents']}"
    )
    api.void_payout_batch(batch_id, make_finance_officer_headers())  # blocked, no mutation
    shopper = validate_success(api.get_shopper(sid, make_finance_officer_headers()))
    assert shopper["ytd_paid_cents"] == 2400, (
        f"ytd_paid_cents expected 2400 (conserved), got {shopper['ytd_paid_cents']}"
    )
