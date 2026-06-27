"""Business-rule validations: priority conflicts, boundary precision, cross-entity
state dependencies, temporal-overlap conflicts, plus corner validation/error
triggers.

Covers difficulty queue-A rules priority_pair_validation_conflict,
boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap,
and the corner-queue validations / errors instances. Each test's Design tag names
its source.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_inspection_payload, create_harvest_payload, create_honey_lot_payload,
    create_contract_payload, create_placement_payload, create_sale_payload,
    TEST_USERS, make_apiary_manager_headers,
    create_apiary, create_registered_apiary, create_hive, create_inspected_hive,
    setup_lot_with_harvests, setup_blocked_lot,
    create_signed_contract, propose_placement, confirm_placement_fresh,
    current_contract_version, reserve_sale, setup_shipped_nuc,
    setup_placed_contract, set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
APIARIST = TEST_USERS["state_apiarist_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]


# ─── priority_pair_validation_conflict / state_beats_safety_on_extract ──────
def test_extract_blocked_lot_reports_invalid_state_over_withdrawal(api):
    """PRD §2.8: "then that the target resource is in a state from which the
    requested transition is allowed (`ERR_INVALID_STATE`); then that the target is
    not already in a terminal state (`ERR_TERMINAL_STATE`). Only after these
    structural checks pass does the system evaluate the domain-specific business
    rules — withdrawal blocks, registration currency, placement eligibility,
    double-booking, site capacity, brood sufficiency, yard capacity, empty-lot,
    time gates, optimistic concurrency, and finally well-formedness and uniqueness
    of the request body."
    PRD §3.7: "Extracting a lot moves it from `DRAFT` to `EXTRACTED`. It is
    permitted only when the lot is `DRAFT`..."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_extract_blocked_lot
    """
    set_clock("2026-02-12T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    # Lot becomes BLOCKED via treatment cascade; hive also under withdrawal.
    lot, _ = setup_blocked_lot(apiary["id"], hive["id"],
                               applied_at="2026-02-10T00:00:00Z", duration_days=42)
    blocked = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert blocked["status"] == "BLOCKED"

    res = api.extract_honey_lot(lot["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_extract_blocked_lot_not_withdrawal_error(api):
    """PRD §2.8: "Only after these structural checks pass does the system evaluate
    the domain-specific business rules — withdrawal blocks, registration currency,
    placement eligibility, double-booking, site capacity, brood sufficiency, yard
    capacity, empty-lot, time gates, optimistic concurrency, and finally
    well-formedness and uniqueness of the request body."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_extract_blocked_lot
    """
    set_clock("2026-02-12T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_blocked_lot(apiary["id"], hive["id"],
                               applied_at="2026-02-10T00:00:00Z", duration_days=42)
    res = api.extract_honey_lot(lot["id"], headers)
    err = res.json()["data"]["error_id"]
    assert err == "ERR_INVALID_STATE"
    assert err != "ERR_HARVEST_BLOCKED_WITHDRAWAL"


# ─── priority_pair_validation_conflict / registration_beats_capacity ────────
def test_confirm_unregistered_full_site_reports_registration_error(api):
    """PRD §2.8: "Only after these structural checks pass does the system evaluate
    the domain-specific business rules — withdrawal blocks, registration currency,
    placement eligibility, double-booking, site capacity, brood sufficiency, yard
    capacity, empty-lot, time gates, optimistic concurrency, and finally
    well-formedness and uniqueness of the request body. The business rules carry
    their own dedicated error codes, introduced in context throughout §3; where two
    business rules could both apply, the lower-numbered concern in this ordering is
    reported first."
    PRD §3.5: "the colony's owning apiary must have `registration_status` equal to
    `ACTIVE`, else `ERR_APIARY_NOT_REGISTERED`"

    Design: Difficulty/priority_pair_validation_conflict/registration_safety_beats_capacity_on_confirm
    """
    set_clock("2026-01-06T00:00:00Z")
    # Unregistered apiary A2 with hive HB. With max_hives_on_site=1, the very first
    # overlapping confirm would reach an aggregate that meets the cap, so both the
    # registration check (p9) and the site-capacity check (p12) would fire for HB.
    a2 = create_apiary(name="A2", latitude=38.6, longitude=-121.6)
    hb = create_inspected_hive(a2["id"], tag="HB", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=1)
    pb = propose_placement(contract["id"], hb["id"])

    v = current_contract_version(contract["id"])
    res = api.confirm_placement(pb["id"], {"expected_contract_version": v}, COORDINATOR)
    validate_error(res, "ERR_APIARY_NOT_REGISTERED")


def test_confirm_unregistered_full_site_not_capacity_error(api):
    """PRD §2.8: "where two business rules could both apply, the lower-numbered
    concern in this ordering is reported first."
    PRD §3.5: "the colony's owning apiary must have `registration_status` equal to
    `ACTIVE`, else `ERR_APIARY_NOT_REGISTERED`"

    Design: Difficulty/priority_pair_validation_conflict/registration_safety_beats_capacity_on_confirm
    """
    set_clock("2026-01-06T00:00:00Z")
    a2 = create_apiary(name="A2", latitude=38.6, longitude=-121.6)
    hb = create_inspected_hive(a2["id"], tag="HB", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=1)
    pb = propose_placement(contract["id"], hb["id"])
    v = current_contract_version(contract["id"])
    res = api.confirm_placement(pb["id"], {"expected_contract_version": v}, COORDINATOR)
    err = res.json()["data"]["error_id"]
    assert err == "ERR_APIARY_NOT_REGISTERED"
    assert err != "ERR_SITE_CAPACITY_EXCEEDED"


# ─── boundary_precision_check / mite threshold at exactly 3.0 ───────────────
def test_treatment_recommended_at_exactly_three(api):
    """PRD §3.3: "The inspection also computes a boolean `treatment_recommended`,
    which is true exactly when `mites_per_100_bees` is at or above the
    mite-treatment threshold of 3.0 mites per 100 bees, and false otherwise — this
    is a precise boundary, so a reading of exactly 3.0 recommends treatment."

    Design: Difficulty/boundary_precision_check/mite_threshold_treatment_recommended_at_exactly_3
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)

    insp = validate_success(api.create_inspection(
        hive["id"], create_inspection_payload(mites_per_100_bees=3.0), headers), 201)
    assert insp["treatment_recommended"] is True


def test_treatment_recommended_below_three_is_false(api):
    """PRD §3.3: "The inspection also computes a boolean `treatment_recommended`,
    which is true exactly when `mites_per_100_bees` is at or above the
    mite-treatment threshold of 3.0 mites per 100 bees, and false otherwise — this
    is a precise boundary, so a reading of exactly 3.0 recommends treatment."

    Design: Difficulty/boundary_precision_check/mite_threshold_treatment_recommended_at_exactly_3
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    insp = validate_success(api.create_inspection(
        hive["id"], create_inspection_payload(mites_per_100_bees=2.9), headers), 201)
    assert insp["treatment_recommended"] is False


# ─── boundary_precision_check / empty lot extract ──────────────────────────
def test_extract_empty_lot_rejected(api):
    """PRD §3.7: "Extracting a lot moves it from `DRAFT` to `EXTRACTED`. It is
    permitted only when the lot is `DRAFT`, when it has at least one `RECORDED`
    harvest — an extraction attempt on a lot with no recorded contributions is
    rejected with `ERR_EMPTY_LOT`..."

    Design: Difficulty/boundary_precision_check/extract_empty_lot_zero_harvests_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    lot = validate_success(api.create_honey_lot(
        create_honey_lot_payload(apiary["id"], lot_code="L1"), headers), 201)

    res = api.extract_honey_lot(lot["id"], headers)
    validate_error(res, "ERR_EMPTY_LOT")


def test_extract_lot_with_one_harvest_succeeds(api):
    """PRD §3.7: "It is permitted only when the lot is `DRAFT`, when it has at least
    one `RECORDED` harvest — an extraction attempt on a lot with no recorded
    contributions is rejected with `ERR_EMPTY_LOT`..."

    Design: Difficulty/boundary_precision_check/extract_empty_lot_zero_harvests_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])

    extracted = validate_success(api.extract_honey_lot(lot["id"], headers), 200)
    assert extracted["status"] == "EXTRACTED"


# ─── cross_entity_state_dependency / placement requires registration active ─
def test_confirm_requires_apiary_registration_active(api):
    """PRD §3.5: "the colony's owning apiary must have `registration_status` equal
    to `ACTIVE`, else `ERR_APIARY_NOT_REGISTERED`"

    Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_apiary_registration_active
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()  # UNREGISTERED
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1)
    placement = propose_placement(contract["id"], hive["id"])

    v = current_contract_version(contract["id"])
    res = api.confirm_placement(placement["id"],
                                {"expected_contract_version": v}, COORDINATOR)
    validate_error(res, "ERR_APIARY_NOT_REGISTERED")
    p_after = validate_success(api.get_placement(placement["id"], COORDINATOR), 200)
    assert p_after["status"] == "PROPOSED"


def test_confirm_succeeds_when_registration_active(api):
    """PRD §3.5: "the colony's owning apiary must have `registration_status` equal
    to `ACTIVE`, else `ERR_APIARY_NOT_REGISTERED`"
    PRD §3.5: "On a successful confirmation the system snapshots the placement's
    `grade` and `contract_rated_strength` using the **forward-projected** variant of
    the colony strength score..."

    Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_apiary_registration_active
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()  # registration_status == ACTIVE
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1)
    placement = propose_placement(contract["id"], hive["id"])

    v = current_contract_version(contract["id"])
    confirmed = validate_success(api.confirm_placement(
        placement["id"], {"expected_contract_version": v}, COORDINATOR), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_nuc_ship_requires_source_hive_not_deadout(api):
    """PRD §3.8: "Shipping a sale moves it from `RESERVED` to `SHIPPED`. It requires
    the source colony to be non-`DEADOUT`, and for a nucleus sale it requires the
    source colony's `brood_frames` to be at least the `frames_drawn`..."

    Design: Difficulty/cross_entity_state_dependency/nuc_ship_requires_source_hive_not_deadout
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=8)
    sale = reserve_sale(apiary["id"], hive["id"], product_type="NUC",
                        frames_drawn=3, price_cents=18000)
    validate_success(api.deadout_hive(hive["id"], headers), 200)

    res = api.ship_sale(sale["id"], COORDINATOR)
    validate_error(res, "ERR_INVALID_STATE")
    sale_after = validate_success(api.get_sale(sale["id"], COORDINATOR), 200)
    assert sale_after["status"] == "RESERVED"


def test_nuc_ship_succeeds_when_source_hive_alive(api):
    """PRD §3.8: "Shipping a sale moves it from `RESERVED` to `SHIPPED`. It requires
    the source colony to be non-`DEADOUT`, and for a nucleus sale it requires the
    source colony's `brood_frames` to be at least the `frames_drawn`; drawing more
    brood frames than the colony holds is rejected with
    `ERR_INSUFFICIENT_BROOD_FRAMES`."

    Design: Difficulty/cross_entity_state_dependency/nuc_ship_requires_source_hive_not_deadout
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=8)  # HEALTHY, alive
    sale = reserve_sale(apiary["id"], hive["id"], product_type="NUC",
                        frames_drawn=3, price_cents=18000)

    shipped = validate_success(api.ship_sale(sale["id"], COORDINATOR), 200)
    assert shipped["status"] == "SHIPPED"


# ─── resource_temporal_overlap / hive double booked ─────────────────────────
def test_hive_double_booked_on_overlapping_windows(api):
    """PRD §3.5: "the colony must not already be `CONFIRMED` on another placement
    whose window overlaps the requested half-open window from `placement_start` up
    to `removal_due`, else `ERR_HIVE_DOUBLE_BOOKED` — note that mere adjacency,
    where one placement's `removal_due` equals another's `placement_start`, does not
    count as an overlap and is allowed"

    Design: Difficulty/resource_temporal_overlap/hive_double_booked_overlapping_placements_single_occupancy
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    # C1: confirm H1 over [2026-02-04, 2026-02-15)
    c1 = create_signed_contract(grower_name="Almond A", required_strong_hives=1,
                                max_hives_on_site=4, bloom_start="2026-02-04T00:00:00Z",
                                bloom_end="2026-02-15T00:00:00Z")
    p1 = propose_placement(c1["id"], hive["id"],
                           placement_start="2026-02-04T00:00:00Z",
                           removal_due="2026-02-15T00:00:00Z")
    confirm_placement_fresh(c1["id"], p1["id"])
    # C2: propose H1 over overlapping [2026-02-14, 2026-02-28)
    c2 = create_signed_contract(grower_name="Almond B", required_strong_hives=1,
                                max_hives_on_site=4, bloom_start="2026-02-14T00:00:00Z",
                                bloom_end="2026-02-28T00:00:00Z")
    p2 = propose_placement(c2["id"], hive["id"],
                           placement_start="2026-02-14T00:00:00Z",
                           removal_due="2026-02-28T00:00:00Z")

    v = current_contract_version(c2["id"])
    res = api.confirm_placement(p2["id"], {"expected_contract_version": v}, COORDINATOR)
    validate_error(res, "ERR_HIVE_DOUBLE_BOOKED")
    p2_after = validate_success(api.get_placement(p2["id"], COORDINATOR), 200)
    assert p2_after["status"] == "PROPOSED"


def test_hive_adjacent_windows_allowed(api):
    """PRD §3.5: "the colony must not already be `CONFIRMED` on another placement
    whose window overlaps the requested half-open window from `placement_start` up
    to `removal_due`, else `ERR_HIVE_DOUBLE_BOOKED` — note that mere adjacency, where
    one placement's `removal_due` equals another's `placement_start`, does not count
    as an overlap and is allowed"

    Design: Difficulty/resource_temporal_overlap/hive_double_booked_overlapping_placements_single_occupancy
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    # C1: confirm H1 over [2026-02-04, 2026-02-15)
    c1 = create_signed_contract(grower_name="Almond A", required_strong_hives=1,
                                max_hives_on_site=4, bloom_start="2026-02-04T00:00:00Z",
                                bloom_end="2026-02-15T00:00:00Z")
    p1 = propose_placement(c1["id"], hive["id"],
                           placement_start="2026-02-04T00:00:00Z",
                           removal_due="2026-02-15T00:00:00Z")
    confirm_placement_fresh(c1["id"], p1["id"])
    # C2: adjacent window [2026-02-15, 2026-02-28) — removal_due == placement_start.
    c2 = create_signed_contract(grower_name="Almond B", required_strong_hives=1,
                                max_hives_on_site=4, bloom_start="2026-02-15T00:00:00Z",
                                bloom_end="2026-02-28T00:00:00Z")
    p2 = propose_placement(c2["id"], hive["id"],
                           placement_start="2026-02-15T00:00:00Z",
                           removal_due="2026-02-28T00:00:00Z")

    v = current_contract_version(c2["id"])
    confirmed = validate_success(api.confirm_placement(
        p2["id"], {"expected_contract_version": v}, COORDINATOR), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_site_capacity_exceeded_over_overlap_window(api):
    """PRD §3.5: "confirming must not push the aggregate count of hives whose windows
    overlap the new window to a value that meets or exceeds `max_hives_on_site`, else
    `ERR_SITE_CAPACITY_EXCEEDED`."

    With max_hives_on_site=2, the first overlapping confirm reaches an aggregate of
    1 (< 2, allowed); a second confirm over the same window would reach 2, which
    meets `max_hives_on_site`, and is rejected.

    Design: Difficulty/resource_temporal_overlap/contract_site_aggregate_capacity_exceeded_over_window
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=2)
    p1 = propose_placement(contract["id"], h1["id"])
    confirm_placement_fresh(contract["id"], p1["id"])
    p2 = propose_placement(contract["id"], h2["id"])

    v = current_contract_version(contract["id"])
    res = api.confirm_placement(p2["id"], {"expected_contract_version": v}, COORDINATOR)
    validate_error(res, "ERR_SITE_CAPACITY_EXCEEDED")
    p2_after = validate_success(api.get_placement(p2["id"], COORDINATOR), 200)
    assert p2_after["status"] == "PROPOSED"


def test_site_capacity_second_confirm_within_cap_allowed(api):
    """PRD §3.5: "confirming must not push the aggregate count of hives whose windows
    overlap the new window to a value that meets or exceeds `max_hives_on_site`, else
    `ERR_SITE_CAPACITY_EXCEEDED`."

    With max_hives_on_site=3, confirming a second overlapping hive reaches an
    aggregate of 2 (< 3) and is allowed.

    Design: Difficulty/resource_temporal_overlap/contract_site_aggregate_capacity_exceeded_over_window
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=2, max_hives_on_site=3)
    p1 = propose_placement(contract["id"], h1["id"])
    confirm_placement_fresh(contract["id"], p1["id"])
    p2 = propose_placement(contract["id"], h2["id"])

    v = current_contract_version(contract["id"])
    confirmed = validate_success(api.confirm_placement(
        p2["id"], {"expected_contract_version": v}, COORDINATOR), 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── Corner / validations ───────────────────────────────────────────────────
def test_harvest_blocked_withdrawal_on_record(api):
    """PRD §3.7: "A harvest may not be recorded while the contributing colony has
    its `harvest_blocked_until` in the future relative to the clock — that attempt
    is `ERR_HARVEST_BLOCKED_WITHDRAWAL`."

    Design: Corner/validations/harvest_blocked_withdrawal_on_record_attempt
    """
    set_clock("2026-02-12T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot = validate_success(api.create_honey_lot(
        create_honey_lot_payload(apiary["id"], lot_code="L1"), headers), 201)
    # APIVAR applied 2026-02-10 -> blocked until 2026-04-07 (> clock 2026-02-12).
    validate_success(api.create_treatment(
        hive["id"],
        {"product": "APIVAR", "applied_at": "2026-02-10T00:00:00Z",
         "duration_days": 42}, headers), 201)

    res = api.create_harvest(
        lot["id"], create_harvest_payload(hive["id"], frames_pulled=4, weight_kg=12.0),
        headers)
    validate_error(res, "ERR_HARVEST_BLOCKED_WITHDRAWAL")


def test_nuc_ship_insufficient_brood_frames(api):
    """PRD §3.8: "for a nucleus sale it requires the source colony's `brood_frames`
    to be at least the `frames_drawn`; drawing more brood frames than the colony
    holds is rejected with `ERR_INSUFFICIENT_BROOD_FRAMES`."

    Design: Corner/validations/nuc_ship_insufficient_brood_frames
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=4)
    sale = reserve_sale(apiary["id"], hive["id"], product_type="NUC",
                        frames_drawn=10, price_cents=18000)

    res = api.ship_sale(sale["id"], COORDINATOR)
    validate_error(res, "ERR_INSUFFICIENT_BROOD_FRAMES")


def test_yard_capacity_exceeded_on_nuc_void(api):
    """PRD §3.8: "Because restoring a colony could overrun the yard, voiding is
    rejected with `ERR_YARD_CAPACITY_EXCEEDED` when restoring would push
    `active_colony_count` above the yard's `max_yard_colonies`."

    Design: Corner/validations/yard_capacity_exceeded_on_nuc_void
    """
    set_clock("2026-04-01T00:00:00Z")
    apiary = create_apiary(max_yard_colonies=1)
    headers = make_apiary_manager_headers(apiary["id"])
    h1 = create_hive(apiary["id"], tag="H1", brood_frames=8)  # count=1
    sale = setup_shipped_nuc(apiary["id"], h1["id"], frames_drawn=3)  # count -> 0
    create_hive(apiary["id"], tag="H2", brood_frames=4)  # count -> 1

    res = api.void_sale(sale["id"], COORDINATOR)  # would push to 2 > cap 1
    validate_error(res, "ERR_YARD_CAPACITY_EXCEEDED")


def test_contract_fulfill_before_bloom_end_too_early(api):
    """PRD §3.6: "A `PLACED` contract is fulfilled — moving from `PLACED` to
    `FULFILLED`, a terminal state that locks the payout as final — only when the
    logical clock has reached or passed `bloom_end` and every `CONFIRMED` placement
    is already `REMOVED` or its `removal_due` is at or before the clock; fulfilling
    too early is `ERR_TOO_EARLY`."

    Design: Corner/validations/contract_fulfill_before_bloom_end_too_early
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract, _ = setup_placed_contract(apiary["id"], [hive["id"]],
                                        required_strong_hives=1,
                                        bloom_start="2026-02-04T00:00:00Z",
                                        bloom_end="2026-03-06T00:00:00Z")
    set_clock("2026-02-10T00:00:00Z")  # < bloom_end 2026-03-06

    res = api.fulfill_contract(contract["id"], COORDINATOR)
    validate_error(res, "ERR_TOO_EARLY")


def test_confirm_quarantine_hive_not_placeable(api):
    """PRD §3.5: "the colony must be `HEALTHY` (and the placement's hive and
    contract must be distinct, existing, non-terminal resources), else
    `ERR_HIVE_NOT_PLACEABLE`"

    Design: Corner/validations/placement_confirm_unhealthy_hive_not_placeable
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1)
    headers = make_apiary_manager_headers(apiary["id"])
    # Quarantine FIRST (PRD §3.2: quarantine cancels any PROPOSED placement of the
    # colony). Proposing the placement afterward leaves a live PROPOSED placement on
    # a non-HEALTHY (QUARANTINE) colony, so confirm reaches the placement-eligibility
    # business rule (hive must be HEALTHY) rather than the structural terminal-state
    # check that a cancelled placement would trip.
    validate_success(api.quarantine_hive(hive["id"], headers), 200)
    placement = propose_placement(contract["id"], hive["id"])

    v = current_contract_version(contract["id"])
    res = api.confirm_placement(placement["id"],
                                {"expected_contract_version": v}, COORDINATOR)
    validate_error(res, "ERR_HIVE_NOT_PLACEABLE")


# ─── Corner / errors ────────────────────────────────────────────────────────
def test_removal_due_before_placement_start_validation(api):
    """PRD §3.10: "Field-level value violations that are not about structure — a
    negative quantity, a `removal_due` at or before its `placement_start`, or a
    `bloom_end` at or before its `bloom_start` — are rejected with `ERR_VALIDATION`."

    Design: Corner/errors/validation_error_removal_due_before_placement_start
    """
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    contract = create_signed_contract(required_strong_hives=1)

    res = api.create_placement(
        contract["id"],
        create_placement_payload(hive["id"],
                                 placement_start="2026-03-06T00:00:00Z",
                                 removal_due="2026-02-04T00:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_VALIDATION")


def test_invalid_enum_floral_source_rejected(api):
    """PRD §3.10: "the system finally checks that the request body is well-formed —
    required fields present, field types correct, and enum values drawn from their
    permitted sets ... A violation of any of these is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/invalid_enum_floral_source_returns_invalid_request
    """
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    res = api.create_honey_lot(
        {"apiary_id": apiary["id"], "lot_code": "L1", "floral_source": "BANANA"},
        headers)
    validate_error(res, "ERR_INVALID_REQUEST")
