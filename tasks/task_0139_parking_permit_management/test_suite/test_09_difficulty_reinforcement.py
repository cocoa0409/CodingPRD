"""Second, distinct translations of each depth (difficulty) instance — each asserts
a different facet of the same rule (a complementary boundary side, an alternate
branch, or a distinct observable side effect) so every difficulty instance carries
two independent tests.

All citations are verbatim from PRD.md and uniquely determine the asserted outcome.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_garage_with_zone,
    setup_transient_facility,
    setup_transient_session_with_validation,
    setup_open_transient_session,
    setup_published_event_session,
    setup_submitted_appeal,
    create_garage,
    create_motorist,
    create_merchant,
    issue_validation,
    create_plate_read,
    create_event_window,
    publish_event_window,
    issue_citation,
    issue_n_citations_same_plate,
    submit_appeal,
    decide_appeal,
    request_permit,
    activate_permit,
    add_waitlist_entry,
    create_space,
    open_session,
    close_session,
    set_clock,
    get_zone,
    get_merchant,
    get_garage,
    get_space,
    get_citation,
    get_motorist,
    get_waitlist_entry,
    get_permit,
    make_motorist_headers,
    create_session_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_permit_session_zero_regardless_of_long_stay(api):
    """PRD §3.6: "A `PERMIT` session is always billed zero, regardless of how long
    the vehicle stayed, because the monthly permit fee already covers it."
    PRD §3.6: "the metered amount becomes the smaller of its current value and the
    cap."

    A 600-min PERMIT stay still bills 0, while an identical TRANSIENT stay bills the
    capped 4000 — the divergence is keyed only on session_kind, not duration.

    Design: Difficulty/dual_variant_calc/transient_charge_permit_zero_vs_transient_metered
    """
    set_clock("2026-06-01T09:00:00Z")
    facility = setup_garage_with_zone(
        zone_type="MIXED", permit_capacity=5, num_spaces=0,
        rate_overrides={"hourly_cents": 500, "daily_cap_cents": 4000,
                        "monthly_permit_cents": 9000, "grace_minutes": 15})
    garage, zone = facility["garage"], facility["zone"]
    create_space(zone["id"], label="S1")
    create_space(zone["id"], label="S2")
    motorist = create_motorist("dv2@x.com", default_plate="LNG123")
    permit = request_permit(zone["id"], motorist["id"], "LNG123")
    activate_permit(permit["id"], zone["version"])
    set_clock("2026-06-01T10:00:00Z")
    perm_sess = open_session(garage["id"], "LNG123", "2026-06-01T10:00:00Z", permit_id=permit["id"])
    trans_sess = open_session(garage["id"], "TRN999", "2026-06-01T10:00:00Z")
    perm_exit = close_session(perm_sess["id"], "2026-06-01T20:00:00Z")  # 600 min
    trans_exit = close_session(trans_sess["id"], "2026-06-01T20:00:00Z")
    assert perm_exit["gross_charge_cents"] == 0
    assert trans_exit["gross_charge_cents"] == 4000


def test_citation_fine_tier_two_at_two_priors(api):
    """PRD §3.9: "exactly two priors apply 2.00".
    PRD §3.9: "The `amount_due_cents` is the `base_fine_cents` multiplied by the
    applicable multiplier, rounded to the nearest whole cent using round-half-up."

    Third citation (2 priors) base 5000 → 10000 — the tier-2 multiplier point, a
    different prior-count boundary than the 0/1 instance.

    Design: Difficulty/dual_variant_calc/citation_fine_first_offense_vs_repeat_offender
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    issue_n_citations_same_plate(garage["id"], zone["id"], "TWO111", 2, base_fine_cents=5000)
    r3 = create_plate_read(garage["id"], "TWO111", zone["id"], "2026-06-01T11:00:00Z")
    c3 = issue_citation(garage["id"], "TWO111", r3["id"], base_fine_cents=5000)
    assert c3["prior_citation_count"] == 2
    assert c3["amount_due_cents"] == 10000


def test_event_priced_flat_added_after_cap_when_cap_not_binding(api):
    """PRD §3.6: "the metered amount is multiplied by the window's `multiplier` and
    the product is rounded to the nearest whole cent using round-half-up — this
    multiplier step is the only place rounding occurs in the pipeline."
    PRD §3.6: "Finally, if an event window applied, the window's
    `flat_surcharge_cents` is added once, after the cap rather than before it."

    A 60-min stay at 500/h: metered 500, ×2.0 = 1000 (under the 4000 cap), + flat
    1000 = 2000 — exposes the multiplier-then-flat order when the cap does not bind.

    Design: Difficulty/combinatorial_formula/event_priced_metered_then_capped_then_flat_order
    """
    ctx = setup_published_event_session(
        window_start_utc="2026-06-01T09:00:00Z", window_end_utc="2026-06-01T18:00:00Z",
        multiplier=2.0, flat_surcharge_cents=1000, entry_at_utc="2026-06-01T10:00:00Z",
        plate="EVT222",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15)
    exited = close_session(ctx["session"]["id"], "2026-06-01T11:00:00Z")
    assert exited["gross_charge_cents"] == 2000


def test_validation_three_way_min_raw_discount_dominates(api):
    """PRD §3.7: "The applied discount is then the smallest of three quantities: the
    raw discount, the gross charge, and the merchant's remaining
    `validation_budget_cents`".
    PRD §3.7: "The session's `net_charge_cents` is the gross charge minus the applied
    discount, which is at least zero by construction."

    FLAT_CENTS 400 raw, gross 1500, budget 10000 → raw is the min → applied 400,
    net 1100 — the branch where the raw discount dominates (complement of budget-clip).

    Design: Difficulty/combinatorial_formula/validation_discount_three_way_min_budget_clip
    """
    ctx = setup_transient_session_with_validation(
        discount_kind="FLAT_CENTS", discount_value=400, merchant_budget=10000,
        plate="RAW111", entry_at_utc="2026-06-01T10:00:00Z",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15)
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z",
                           validation_id=ctx["validation"]["id"])
    assert exited["gross_charge_cents"] == 1500
    assert exited["net_charge_cents"] == 1100
    assert get_merchant(ctx["merchant"]["id"])["validation_budget_cents"] == 9600


def test_merchant_budget_conserved_under_percent_forty(api):
    """PRD §3.7: "a `PERCENT` validation yields the gross multiplied by
    `discount_value` divided by one hundred, rounded down to the nearest whole cent".
    PRD §3.7: "the merchant's `validation_budget_cents` is debited by exactly the
    applied amount".

    PERCENT-40 on gross 1500 → applied 600; budget 10000→9400 and 9400+600 == 10000,
    conserving the merchant economic quantity at a different discount point.

    Design: Difficulty/compensating_invariant/merchant_budget_conserved_under_validation_redemption
    """
    ctx = setup_transient_session_with_validation(
        discount_kind="PERCENT", discount_value=40, merchant_budget=10000,
        plate="PCT111", entry_at_utc="2026-06-01T10:00:00Z",
        hourly_cents=500, daily_cap_cents=4000, monthly_permit_cents=9000, grace_minutes=15)
    exited = close_session(ctx["session"]["id"], "2026-06-01T12:30:00Z",
                           validation_id=ctx["validation"]["id"])
    assert exited["net_charge_cents"] == 900
    applied = 600
    budget_after = get_merchant(ctx["merchant"]["id"])["validation_budget_cents"]
    assert budget_after == 9400
    assert budget_after + applied == 10000


def test_zone_capacity_conserved_with_two_active_one_revoked(api):
    """PRD §3.3: "The zone's `permits_active_count` is incremented by one".
    PRD §3.3: "Revocation lowers the zone's `permits_active_count` by one".

    capacity 3: activate two (count 2) then revoke one → count 1, capacity 3, so the
    slot accounting (active + free == capacity) holds with no leak.

    Design: Difficulty/compensating_invariant/zone_capacity_conserved_under_revoke_without_promotion
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=3)
    zone = facility["zone"]
    m1 = create_motorist("zk1@x.com", default_plate="ZK1111")
    m2 = create_motorist("zk2@x.com", default_plate="ZK2222")
    p1 = request_permit(zone["id"], m1["id"], "ZK1111")
    activate_permit(p1["id"], zone["version"])
    z_v1 = get_zone(zone["id"])["version"]
    p2 = request_permit(zone["id"], m2["id"], "ZK2222")
    activate_permit(p2["id"], z_v1)
    assert get_zone(zone["id"])["permits_active_count"] == 2
    validate_success(api.revoke_permit(p1["id"], ADMIN))
    z = get_zone(zone["id"])
    assert z["permits_active_count"] == 1
    assert z["permit_capacity"] == 3


def test_appeal_decide_succeeds_when_citation_still_issued(api):
    """PRD §3.9: "Deciding requires the appeal to be `SUBMITTED` and its linked
    citation to still be `ISSUED`."

    Positive branch of the Appeal→Citation state pair: the citation is still ISSUED,
    so the decide succeeds and the appeal reaches UPHELD.

    Design: Difficulty/cross_entity_state_dependency/appeal_decide_depends_on_citation_state_pair
    """
    ctx = setup_submitted_appeal(plate="OKI111", base_fine_cents=5000, email="oki@x.com")
    citation, appeal = ctx["citation"], ctx["appeal"]
    assert get_citation(citation["id"])["status"] == "ISSUED"
    decided = validate_success(api.decide_appeal(appeal["id"], {"decision": "UPHELD"}, OFFICER))
    assert decided["status"] == "UPHELD"


def test_citation_fork_appeals_reach_terminal_states(api):
    """PRD §3.9: "When the decision upholds the appeal, the appeal moves from
    `SUBMITTED` to `UPHELD`".
    PRD §3.9: "When the decision dismisses the appeal, the appeal moves from
    `SUBMITTED` to `DISMISSED`".

    Distinct observable of the fork: the two appeals themselves diverge to UPHELD
    and DISMISSED terminal states from a shared SUBMITTED origin.

    Design: Difficulty/non_linear_state_machine/citation_fork_join_via_appeal_branches
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    motorist = create_motorist("fk2@x.com", default_plate="FK2111")
    r1 = create_plate_read(garage["id"], "FK2111", zone["id"], "2026-06-01T08:00:00Z")
    c1 = issue_citation(garage["id"], "FK2111", r1["id"], base_fine_cents=5000)
    r2 = create_plate_read(garage["id"], "FK2111", zone["id"], "2026-06-01T09:00:00Z")
    c2 = issue_citation(garage["id"], "FK2111", r2["id"], base_fine_cents=5000)
    a1 = submit_appeal(c1["id"], motorist["id"], reason="a")
    a2 = submit_appeal(c2["id"], motorist["id"], reason="b")
    decided1 = decide_appeal(a1["id"], "UPHELD")
    decided2 = decide_appeal(a2["id"], "DISMISSED")
    assert decided1["status"] == "UPHELD"
    assert decided2["status"] == "DISMISSED"


def test_permit_active_branch_to_expired(api):
    """PRD §3.3: "The sweep expires an `ACTIVE` permit — moving it from `ACTIVE` to
    `EXPIRED` — only when the current clock instant is at or after the permit's
    `valid_until_utc`".
    PRD §3.3: "The terminal states `REVOKED`, `EXPIRED`, and `REJECTED` admit no
    further transitions."

    The ACTIVE state's other branch (→EXPIRED via sweep) is exercised, complementing
    the REVOKED/REJECTED forks of the same branching machine.

    Design: Difficulty/non_linear_state_machine/permit_revert_loop_requested_active_revoked
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    motorist = create_motorist("exb@x.com", default_plate="EXB111")
    p = request_permit(zone["id"], motorist["id"], "EXB111")
    activate_permit(p["id"], zone["version"])
    set_clock("2026-07-02T00:00:00Z")
    swept = validate_success(api.expire_check_permit(p["id"], ADMIN))
    assert swept["status"] == "EXPIRED"
    assert get_zone(zone["id"])["permits_active_count"] == 0


def test_state_beats_temporal_on_voided_session_exit(api):
    """PRD §2.9: "a state violation surfaces before a capacity or concurrency
    conflict."
    PRD §3.5: "Exit requires the session to be `OPEN`, rejecting otherwise with
    `ERR_INVALID_STATE`".

    A VOIDED session presented an expired validation at exit returns the state error
    (the session is not OPEN), confirming the state check pre-empts the temporal
    validation-redeemability check from a different terminal state than CLOSED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_session_exit
    """
    facility = setup_transient_facility(num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                        monthly_permit_cents=9000, grace_minutes=15)
    garage = facility["garage"]
    merchant = create_merchant(garage["id"], validation_budget_cents=10000)
    validation = issue_validation(garage["id"], merchant["id"], "FLAT_CENTS", 300,
                                  expires_at_utc="2026-06-01T09:00:00Z")
    set_clock("2026-06-01T10:00:00Z")
    sess = open_session(garage["id"], "VST111", "2026-06-01T10:00:00Z")
    validate_success(api.void_session(sess["id"], ADMIN))
    resp = api.exit_session(
        sess["id"], {"exit_at_utc": "2026-06-01T12:00:00Z", "validation_id": validation["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_zone_type_forbidden_pre_empts_capacity_distinct_plate(api):
    """PRD §2.9: "Only after these structural checks pass does the system evaluate
    domain-specific business constraints — zone-type eligibility, uniqueness,
    validation redeemability, event-window well-formedness, stall occupancy, gate
    admission, permit capacity, merchant budget, and finally the
    optimistic-concurrency token."

    A TRANSIENT zone (permit_capacity 0) violates both zone-type and capacity; the
    earlier-listed zone-type eligibility wins → ERR_ZONE_TYPE_FORBIDDEN.

    Design: Difficulty/priority_pair_validation_conflict/zone_type_beats_capacity_on_permit_activate
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    zone = facility["zone"]
    motorist = create_motorist("ztb@x.com", default_plate="ZTB111")
    permit = request_permit(zone["id"], motorist["id"], "ZTB111")
    resp = api.activate_permit(permit["id"], {"expected_zone_version": zone["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_TYPE_FORBIDDEN.value)


def test_event_window_adjacent_publish_allowed(api):
    """PRD §3.2: "The half-open interval runs from `window_start_utc` up to but not
    including `window_end_utc`".
    PRD §3.2: "Publishing is rejected with `ERR_EVENT_WINDOW_OVERLAP` if the
    window's half-open interval overlaps that of any other already-`PUBLISHED`
    window for the same garage."

    [12:00,18:00) is adjacent to a PUBLISHED [09:00,12:00); because end is exclusive
    there is no overlap, so the second publish succeeds — the adjacency-allowed side
    of the half-open interval geometry.

    Design: Difficulty/resource_temporal_overlap/event_window_half_open_overlap_on_publish
    """
    garage = create_garage(name="G")
    e1 = create_event_window(garage["id"], "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z",
                             flat_surcharge_cents=1000, name="E1")
    publish_event_window(e1["id"])
    e2 = create_event_window(garage["id"], "2026-06-01T12:00:00Z", "2026-06-01T18:00:00Z",
                             flat_surcharge_cents=500, name="E2")
    published = validate_success(api.publish_event_pricing(e2["id"], ADMIN))
    assert published["status"] == "PUBLISHED"


def test_space_freed_after_exit_admits_new_entry(api):
    """PRD §3.5: "On a successful exit the session's `exit_at_utc` is recorded,
    `gross_charge_cents` is computed per §3.6, `net_charge_cents` is computed per
    §3.7, the session's `status` becomes `CLOSED`, the space's `is_occupied` becomes
    false, and the garage's `occupied_count` is recomputed downward by one."
    PRD §3.5: "if no `AVAILABLE` and unoccupied space remains in an eligible zone —
    that is, the stall the gate would assign is already held by a time-overlapping
    `OPEN` occupation — the entry is rejected with `ERR_SPACE_OCCUPIED`."

    The single stall, once its OPEN occupation closes, is no longer time-overlapping,
    so a subsequent entry is admitted — the complement of the occupied-rejection.

    Design: Difficulty/resource_temporal_overlap/space_single_occupant_overlap_on_entry
    """
    ctx = setup_open_transient_session(plate="FRE111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    close_session(ctx["session"]["id"], "2026-06-01T11:00:00Z")
    second = validate_success(api.create_session(
        create_session_payload(ctx["garage"]["id"], "FRE222", "2026-06-01T11:05:00Z"), ADMIN),
        expected_status=201)
    assert second["status"] == "OPEN"


def test_grace_boundary_on_thirty_minute_grace(api):
    """PRD §3.6: "If the duration is at or below the rate plan's `grace_minutes`, the
    charge is exactly zero and computation stops".
    PRD §3.6: "every started hour is billed."

    With grace 30: exactly 30 min bills 0 (<= grace); 31 min bills one started hour =
    500 — the same `<= grace` boundary verified at a different grace threshold.

    Design: Difficulty/boundary_precision_check/grace_minutes_boundary_exact_vs_over
    """
    facility = setup_transient_facility(num_spaces=2, hourly_cents=500, daily_cap_cents=4000,
                                        monthly_permit_cents=9000, grace_minutes=30)
    garage = facility["garage"]
    set_clock("2026-06-01T10:00:00Z")
    s30 = open_session(garage["id"], "G30111", "2026-06-01T10:00:00Z")
    s31 = open_session(garage["id"], "G31111", "2026-06-01T10:00:00Z")
    e30 = close_session(s30["id"], "2026-06-01T10:30:00Z")
    e31 = close_session(s31["id"], "2026-06-01T10:31:00Z")
    assert e30["gross_charge_cents"] == 0
    assert e31["gross_charge_cents"] == 500


def test_zone_capacity_under_boundary_admits_activation(api):
    """PRD §3.3: "the zone's `permits_active_count` must be strictly less than its
    `permit_capacity`".
    PRD §3.3: "On successful activation, the permit's `status` becomes `ACTIVE`".

    capacity 2 with count 1: 1 < 2 is true, so the second activation succeeds — the
    admitted side of the strict-less-than boundary (complement of the at-capacity
    rejection).

    Design: Difficulty/boundary_precision_check/zone_capacity_strict_less_than_boundary_on_activate
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=2)
    zone = facility["zone"]
    m1 = create_motorist("ub1@x.com", default_plate="UB1111")
    m2 = create_motorist("ub2@x.com", default_plate="UB2222")
    p1 = request_permit(zone["id"], m1["id"], "UB1111")
    activate_permit(p1["id"], zone["version"])
    z_v1 = get_zone(zone["id"])["version"]
    p2 = request_permit(zone["id"], m2["id"], "UB2222")
    activated = activate_permit(p2["id"], z_v1)
    assert activated["status"] == "ACTIVE"
    assert get_zone(zone["id"])["permits_active_count"] == 2


def test_revoke_cascade_creates_requested_permit_for_promoted_entry(api):
    """PRD §3.4: "Promotion creates a brand-new `Permit` in `REQUESTED` status,
    copying the entry's `zone_id`, `motorist_id`, and `plate` onto it".
    PRD §3.4: "promotion does not itself activate the new permit — it only creates a
    `REQUESTED` permit."

    Distinct observable of hop-3: the permit referenced by the promoted entry's
    promoted_permit_id exists in REQUESTED status with the entry's plate copied.

    Design: Difficulty/transitive_cascade/revoke_cascades_capacity_then_waitlist_promotion_depth3
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=1)
    zone = facility["zone"]
    m0 = create_motorist("rc0@x.com", default_plate="RC0000")
    m1 = create_motorist("rc1@x.com", default_plate="RC1111")
    p = request_permit(zone["id"], m0["id"], "RC0000")
    activate_permit(p["id"], zone["version"])
    w1 = add_waitlist_entry(zone["id"], m1["id"], "RC1111")
    validate_success(api.revoke_permit(p["id"], ADMIN))
    entry = get_waitlist_entry(w1["id"])
    assert entry["status"] == "PROMOTED"
    new_permit = get_permit(entry["promoted_permit_id"])
    assert new_permit["status"] == "REQUESTED"
    assert new_permit["plate"] == "RC1111"
    assert new_permit["zone_id"] == zone["id"]
