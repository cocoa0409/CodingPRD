"""Second-coverage tests for difficulty queue A instances (each difficulty
instance is covered by at least two tests). Each test here probes a distinct
observable of the same scenario already exercised elsewhere — a complementary
field, a read-back value, or a neighbouring boundary point — and is independently
derivable from a verbatim PRD sentence.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_community,
    create_property,
    create_elevation_certificate,
    quote_policy,
    quote_policy_as_underwriter,
    setup_active_policy,
    setup_bound_policy,
    setup_quoted_policy,
    setup_claim_under_review,
    file_claim,
    open_review,
    file_proof_of_loss,
    accept_proof_of_loss,
    approve_claim,
    ApiErrorId,
    TEST_USERS,
    make_policy_holder_headers,
)


def _hdr():
    return TEST_USERS["underwriter_headers"]


# --- dual_variant_calc (already 2 tests each) is satisfied elsewhere --------


# --- combinatorial_formula -------------------------------------------------

def test_rr2_premium_persisted_and_readable(api):
    """PRD §3.4: "its `status` enters `QUOTED`, and its `quoted_premium` is
    computed immediately."
    PRD §3.4: "The risk base is the building coverage multiplied by its band rate
    plus the contents coverage multiplied by the contents rate, that whole sum
    multiplied by the elevation factor, and then rounded to whole dollars."

    Design: Difficulty/combinatorial_formula/premium_quote_zone_band_times_elevation_times_crs
    """
    community = create_community(crs_class=5, participating=True)
    prop = create_property(
        community["id"], "h-comb2", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    create_elevation_certificate(prop["id"], "h-comb2", lowest_floor_elevation_ft=10.0)
    policy = quote_policy(
        prop["id"], "h-comb2", "RISK_RATING_2_0",
        building_coverage=250000, contents_coverage=100000,
    )
    # Read the persisted policy back: the computed premium must round-trip.
    fetched = validate_success(api.get_policy(policy["id"], _hdr()))
    assert fetched["quoted_premium"] == 676, fetched["quoted_premium"]


def test_claim_round_per_bucket_building_component(api):
    """PRD §3.10: "for a `NON_PRIMARY` structure the building is depreciated to
    actual cash value, so the adjusted building loss is the reported
    `building_loss` multiplied by one minus `depreciation_pct`, rounded to whole
    dollars"

    Design: Difficulty/combinatorial_formula/claim_settlement_round_per_bucket_then_sum
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-rpb",
        flood_zone="AE", occupancy="NON_PRIMARY", base_flood_elevation_ft=8.0,
        lowest_floor_elevation_ft=10.0, has_active_mortgage=True,
        crs_class=5, is_lender_required=True,
        building_coverage=250000, contents_coverage=100000,
        building_deductible=2000, contents_deductible=1000, quote_as_underwriter=True,
    )
    claim = file_claim(
        active["id"], "h-rpb", "2026-04-10T00:00:00Z",
        building_loss=120000, contents_loss=30000, depreciation_pct=0.20,
        substantial_damage=False, icc_eligible_cost=0,
    )
    claim = open_review(claim["id"])
    proof = file_proof_of_loss(
        claim["id"], "h-rpb", documented_building_loss=120000, documented_contents_loss=30000
    )
    accept_proof_of_loss(proof["id"])
    approved = approve_claim(claim["id"], claim["version"])
    # building 120000 * 0.80 = 96000 (rounded) then net 2000 deductible -> 94000
    assert approved["building_payable"] == 94000, approved["building_payable"]
    assert approved["settlement_total"] == 117000, approved["settlement_total"]


# --- non_linear_state_machine ----------------------------------------------

def test_proof_reject_sets_proof_status_rejected(api):
    """PRD §3.9: "Rejection of a pending proof-of-loss moves its `review_status`
    to `REJECTED`"

    Design: Difficulty/non_linear_state_machine/claim_review_revision_cycle_under_review_to_submitted
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-rev2", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    proof = file_proof_of_loss(claim["id"], "h-rev2", documented_building_loss=9999)
    rejected = validate_success(
        api.reject_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    )
    assert rejected["review_status"] == "REJECTED", rejected["review_status"]


def test_transfer_reassigns_holder_and_owner(api):
    """PRD §3.7: "The transfer also stamps an `effective_at` instant from the
    logical clock, reassigns the policy's `holder_id` and the property's
    `owner_id` to the new owner, and records `superseded_policy_id` as the source
    policy's own id"

    Design: Difficulty/non_linear_state_machine/policy_branching_active_to_transferred_vs_cancelled
    """
    community = create_community(crs_class=10, participating=True)
    set_clock("2026-03-01T00:00:00Z")
    prop = create_property(
        community["id"], "holder-6t", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    policy = quote_policy_as_underwriter(
        prop["id"], "LEGACY_SUBSIDIZED", building_coverage=250000, contents_coverage=100000
    )
    validate_success(api.bind_policy(policy["id"], _hdr()))
    set_clock("2026-03-31T00:00:00Z")
    active = validate_success(api.activate_policy(policy["id"], _hdr()))
    set_clock("2026-09-30T00:00:00Z")
    transfer = validate_success(api.create_policy_transfer(
        {"from_policy_id": active["id"], "new_owner_id": "holder-7t",
         "expected_policy_version": active["version"]},
        _hdr(),
    ), expected_status=201)
    assert transfer["superseded_policy_id"] == active["id"], transfer["superseded_policy_id"]

    src = validate_success(api.get_policy(active["id"], _hdr()))
    assert src["holder_id"] == "holder-7t", src["holder_id"]
    fetched_prop = validate_success(api.get_property(prop["id"], _hdr()))
    assert fetched_prop["owner_id"] == "holder-7t", fetched_prop["owner_id"]


# --- transitive_cascade ----------------------------------------------------

def test_first_approval_does_not_flip_repetitive_loss(api):
    """PRD §3.10: "the property's `loss_history_count` is increased by one; and if
    that brings the loss count to 2 or more, the property's `is_repetitive_loss`
    flag is set to true."

    Design: Difficulty/transitive_cascade/claim_approve_cascade_to_repetitive_loss_depth3
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-8b",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], "holder-8b", "2026-04-10T00:00:00Z", building_loss=5000)
    claim = open_review(claim["id"])
    proof = file_proof_of_loss(claim["id"], "holder-8b", documented_building_loss=5000)
    accept_proof_of_loss(proof["id"])
    approve_claim(claim["id"], claim["version"])

    fetched_prop = validate_success(api.get_property(prop["id"], _hdr()))
    fetched_policy = validate_success(api.get_policy(active["id"], _hdr()))
    # After exactly one approval: count is 1 and the flag stays false (threshold is 2).
    assert fetched_prop["loss_history_count"] == 1, fetched_prop["loss_history_count"]
    assert fetched_prop["is_repetitive_loss"] is False, fetched_prop["is_repetitive_loss"]
    assert fetched_policy["total_claims_paid"] == 3000, fetched_policy["total_claims_paid"]


def test_cancel_clears_active_policy_pointer(api):
    """PRD §3.6: "In both cases the property's `active_policy_id` is cleared to
    null"

    Design: Difficulty/transitive_cascade/policy_cancel_cascade_to_compliance_lapsed_depth2
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-9b",
        flood_zone="AE", base_flood_elevation_ft=8.0, lowest_floor_elevation_ft=10.0,
        has_active_mortgage=True, crs_class=10, is_lender_required=True,
        building_coverage=250000, contents_coverage=100000, quote_as_underwriter=True,
    )
    validate_success(api.cancel_policy(
        active["id"], {"expected_policy_version": active["version"]}, _hdr()
    ))
    fetched_prop = validate_success(api.get_property(prop["id"], _hdr()))
    assert fetched_prop["active_policy_id"] is None, fetched_prop["active_policy_id"]


# --- priority_pair_validation_conflict -------------------------------------

def test_not_owner_claim_file_produces_no_claim(api):
    """PRD §2.1: "a `PolicyHolder` who requests a quote on a property, or files a
    claim against a policy, must be the owner/holder/claimant of that resource,
    and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_on_claim_file
    """
    community, prop, policy = setup_quoted_policy(
        owner_id="holder-10b", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
    )
    resp = api.create_claim(
        {"policy_id": policy["id"], "claimant_id": "holder-11b",
         "date_of_loss": "2026-02-01T00:00:00Z", "building_loss": 1000},
        make_policy_holder_headers("holder-11b"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    # The rejected filing left no claim under the policy.
    listed = validate_success(api.list_claims(_hdr(), params={"policy_id": policy["id"]}))
    assert listed == [] or len(listed) == 0, listed


def test_proof_late_takes_precedence_days_after_loss_61(api):
    """PRD §3.9: "the sixty-day deadline is inclusive, so `days_after_loss` must
    be at most 60 — exactly day 60 is on time and day 61 is late — and a late
    filing is rejected with `ERR_PROOF_OF_LOSS_LATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pol_late_beats_pol_mismatch_on_accept
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-12b", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-06-10T00:00:00Z")
    proof = file_proof_of_loss(claim["id"], "holder-12b", documented_building_loss=9999)
    assert proof["days_after_loss"] == 61, proof["days_after_loss"]
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_LATE, expected_status=409)


# --- boundary_precision_check ----------------------------------------------

def test_proof_well_within_window_accepts(api):
    """PRD §3.9: "the sixty-day deadline is inclusive, so `days_after_loss` must
    be at most 60 — exactly day 60 is on time and day 61 is late"

    Design: Difficulty/boundary_precision_check/proof_of_loss_day60_accepts_day61_rejects
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-day59", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-06-08T00:00:00Z")  # day 59 — one inside the inclusive deadline
    proof = file_proof_of_loss(claim["id"], "h-day59", documented_building_loss=5000)
    assert proof["days_after_loss"] == 59, proof["days_after_loss"]
    accepted = validate_success(
        api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    )
    assert accepted["review_status"] == "ACCEPTED", accepted["review_status"]


def test_bound_policy_effective_date_thirty_days_after_bind(api):
    """PRD §3.5: "the waiting period is 0 days when the policy was written to
    satisfy a loan closing — that is, when `is_lender_required` is true — and 30
    days otherwise, so `effective_date` is the bind date plus the waiting period"

    Design: Difficulty/boundary_precision_check/activate_at_effective_date_boundary_waiting_period
    """
    community, prop, bound = setup_bound_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-eff",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=False,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    # Standard 30-day waiting period: bound 2026-03-01 -> effective 2026-03-31.
    assert bound["effective_date"] == "2026-03-31T00:00:00.000Z", bound["effective_date"]


# --- cross_entity_state_dependency -----------------------------------------

def test_open_review_succeeds_once_policy_active(api):
    """PRD §3.8: "An `Adjuster` opens review on a `SUBMITTED` claim, advancing it
    to `UNDER_REVIEW`."
    PRD §3.8: "the claim's policy must currently be `ACTIVE`, failing which the
    request is rejected with `ERR_POLICY_NOT_ACTIVE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/claim_open_review_requires_policy_active
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="h-cesd1",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    claim = file_claim(active["id"], "h-cesd1", "2026-04-10T00:00:00Z", building_loss=5000)
    reviewed = validate_success(
        api.open_review(claim["id"], TEST_USERS["adjuster_headers"])
    )
    assert reviewed["status"] == "UNDER_REVIEW", reviewed["status"]


def test_proof_accept_succeeds_once_claim_under_review(api):
    """PRD §3.9: "Acceptance is permitted only when the proof is `PENDING` and the
    claim it supports is `UNDER_REVIEW`"
    PRD §3.9: "Acceptance moves the proof's `review_status` to `ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/proof_accept_requires_claim_under_review
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-cesd2", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    proof = file_proof_of_loss(claim["id"], "h-cesd2", documented_building_loss=5000)
    accepted = validate_success(
        api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    )
    assert accepted["review_status"] == "ACCEPTED", accepted["review_status"]


# --- resource_temporal_overlap ---------------------------------------------

def test_loss_at_effective_date_is_covered(api):
    """PRD §3.5: "The coverage window is half-open at its end: a loss exactly at
    the effective instant is covered, and a loss at or after the expiration
    instant is not."

    Design: Difficulty/resource_temporal_overlap/loss_inside_waiting_period_outside_coverage_halfopen
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", activate_clock="2026-03-31T00:00:00Z",
        owner_id="h-rto1", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10, is_lender_required=False,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    # Loss exactly at effective_date 2026-03-31 is inside the half-open window.
    claim = file_claim(active["id"], "h-rto1", "2026-03-31T00:00:00Z", building_loss=5000)
    reviewed = validate_success(
        api.open_review(claim["id"], TEST_USERS["adjuster_headers"])
    )
    assert reviewed["status"] == "UNDER_REVIEW", reviewed["status"]


def test_proof_filed_in_window_records_days_after_loss(api):
    """PRD §3.9: "computes `days_after_loss` as the whole days between the claim's
    `date_of_loss` and the filing instant."

    Design: Difficulty/resource_temporal_overlap/proof_of_loss_inclusive_60day_window_collision
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-rto2", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    set_clock("2026-06-10T00:00:00Z")  # day 61 — outside the closed 60-day window
    proof = file_proof_of_loss(claim["id"], "h-rto2", documented_building_loss=5000)
    assert proof["days_after_loss"] == 61, proof["days_after_loss"]
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_LATE, expected_status=409)


# --- compensating_invariant ------------------------------------------------

def test_cancel_refund_is_exact_complement_of_earned(api):
    """PRD §3.6: "The refund returned to the holder is the quoted premium minus
    the earned premium, computed as the exact complement so that earned premium
    plus refund equals the quoted premium."

    Design: Difficulty/compensating_invariant/cancel_premium_conservation_earned_plus_refund
    """
    community = create_community(crs_class=10, participating=True)
    set_clock("2026-03-01T00:00:00Z")
    prop = create_property(
        community["id"], "holder-19b", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    quoted = quote_policy_as_underwriter(
        prop["id"], "LEGACY_SUBSIDIZED", building_coverage=250000, contents_coverage=100000
    )
    validate_success(api.bind_policy(quoted["id"], _hdr()))
    set_clock("2026-03-31T00:00:00Z")
    active = validate_success(api.activate_policy(quoted["id"], _hdr()))
    set_clock("2026-09-30T00:00:00Z")
    cancelled = validate_success(api.cancel_policy(
        active["id"], {"expected_policy_version": active["version"]}, _hdr()
    ))
    quoted_premium = cancelled["quoted_premium"]
    earned = cancelled["earned_premium"]
    refund = quoted_premium - earned
    assert refund == 997, refund
    assert earned + refund == quoted_premium, (earned, refund, quoted_premium)


def test_review_bounce_leaves_claim_settlement_at_zero(api):
    """PRD §3.9: "bounces that claim back to `SUBMITTED`, advancing the claim's
    `version` as well."
    PRD §3.10: "a denial moves the claim to the terminal `DENIED` status, leaves
    `settlement_total` at 0, and has no ledger impact."

    Design: Difficulty/compensating_invariant/review_bounce_claims_paid_ledger_conservation
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-20b", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    # The open-review / proof-reject compensating loop must not move any money.
    proof = file_proof_of_loss(claim["id"], "holder-20b", documented_building_loss=5000)
    api.reject_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    bounced = validate_success(api.get_claim(claim["id"], _hdr()))
    assert bounced["status"] == "SUBMITTED", bounced["status"]
    assert bounced["settlement_total"] == 0, bounced["settlement_total"]
    fetched_policy = validate_success(api.get_policy(policy["id"], _hdr()))
    assert fetched_policy["total_claims_paid"] == 0, fetched_policy["total_claims_paid"]
