"""OOS finalize basis + cascade, ISS scoring order and variants, and the OCC snapshot guard.

Difficulty translations: empty OOS basis boundary, the depth-4 OOS cascade to an
auto-provisional snapshot, the pinned per-inspection-round-then-average order, and the
provisional-vs-certified ISS divergence. Corner translations: the OCC version guard
(success and stale rejection).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_domain,
    setup_referred_overweight_screening,
    create_carrier,
    create_screening,
    create_inspection,
    add_violation,
    finalize,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _get_carrier(carrier_id):
    return validate_success(api_client.get_carrier(carrier_id, ADMIN))


def _current_snapshot(carrier_id):
    data, _ = validate_paginated(api_client.list_score_snapshots(carrier_id, ADMIN))
    current = [s for s in data if s["is_current"]]
    return current[0] if current else None


# --- Difficulty: empty OOS basis boundary ---

def test_oos_finalize_with_no_violations_rejected(api):
    """PRD §3.5: "Finalizing with `result` `OOS` requires that the inspection already
    have at least one violation whose `oos` flag is true; with no such violation the
    finalize is rejected with `ERR_NO_OOS_BASIS`."

    Design: Difficulty/boundary_precision_check/finalize_oos_empty_violation_set
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-844-L", "legal_name": "Lima Lines"},
        station_overrides={"name": "I-35", "state_code": "TX"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"])
    resp = api.finalize_inspection(inspection["id"], {"result": "OOS"}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_NO_OOS_BASIS)


def test_oos_finalize_with_only_non_oos_violation_rejected(api):
    """PRD §3.5: "Finalizing with `result` `OOS` requires that the inspection already
    have at least one violation whose `oos` flag is true; with no such violation the
    finalize is rejected with `ERR_NO_OOS_BASIS`."

    Design: Difficulty/boundary_precision_check/finalize_oos_empty_violation_set
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-844-L2", "legal_name": "Lima Lines"},
        station_overrides={"name": "I-35", "state_code": "TX"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"])
    add_violation(inspection["id"], code="396.3", category="VEHICLE", severity_weight=5, oos=False)
    resp = api.finalize_inspection(inspection["id"], {"result": "OOS"}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_NO_OOS_BASIS)


# --- Difficulty: OOS cascade to auto-provisional snapshot ---

def _oos_cascade_setup(usdot):
    """Two OOS violations summing 8 severity; raw = 8*1.5 = 12 -> iss 12 >= 10 (review),
    oos_points 8 < 20. Returns carrier_id."""
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": usdot, "legal_name": "Golf Logistics"},
        station_overrides={"name": "I-10", "state_code": "CA"})
    inspection = create_inspection(d["screening"]["id"], d["bay"]["id"])
    add_violation(inspection["id"], code="393.75", category="WEIGHT", severity_weight=4, oos=True)
    add_violation(inspection["id"], code="393.9", category="VEHICLE", severity_weight=4, oos=True)
    finalize(inspection["id"], "OOS")
    return d["carrier"]["id"]


def test_oos_finalize_cascades_points_and_review(api):
    """PRD §3.5: "The sum of the `severity_weight` of the inspection's out-of-service
    violations is added to the carrier's `oos_points`, and that amount is stored on the
    inspection as `oos_points_applied`."
    PRD §2.7: "When the provisional `iss_score` reaches at least `10`, an `ACTIVE`
    carrier moves to `UNDER_REVIEW`."

    Design: Difficulty/transitive_cascade/inspection_oos_cascade_to_score_snapshot
    """
    carrier_id = _oos_cascade_setup("DOT-844-G")
    carrier = _get_carrier(carrier_id)
    assert carrier["oos_points"] == 8
    assert carrier["status"] == "UNDER_REVIEW"
    assert carrier["prism_flagged"] is True


def test_oos_finalize_auto_creates_provisional_snapshot(api):
    """PRD §3.5: "Whenever this operation drives the carrier into `UNDER_REVIEW`, the
    carrier's `prism_flagged` is set to true and a provisional current snapshot is
    auto-created: the new snapshot's `is_current` is true and the carrier's prior
    current snapshot has its `is_current` flipped to false."

    Design: Difficulty/transitive_cascade/inspection_oos_cascade_to_score_snapshot
    """
    carrier_id = _oos_cascade_setup("DOT-844-G2")
    snap = _current_snapshot(carrier_id)
    assert snap is not None
    assert snap["method"] == "PROVISIONAL"
    assert snap["is_current"] is True
    assert snap["iss_score"] == 12


# --- Difficulty: pinned per-inspection-round-then-average order ---

def _two_oos_inspections(usdot, sev1, sev2):
    """Two inspections each finalized OOS with a single WEIGHT/oos violation of the given
    severity. Returns carrier_id."""
    d = setup_domain(carrier_overrides={"usdot_number": usdot, "legal_name": "Delta Transit"},
                     station_overrides={"name": "I-80", "state_code": "CA"})
    s1 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-4", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    i1 = create_inspection(s1["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T08:00:00Z", scheduled_end="2026-03-02T09:00:00Z")
    add_violation(i1["id"], code="393.75", category="WEIGHT", severity_weight=sev1, oos=True)
    finalize(i1["id"], "OOS")
    s2 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-4", gross_weight_lbs=87000, heaviest_axle_lbs=21000)
    i2 = create_inspection(s2["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T10:00:00Z", scheduled_end="2026-03-02T11:00:00Z")
    add_violation(i2["id"], code="393.9", category="VEHICLE", severity_weight=sev2, oos=True)
    finalize(i2["id"], "OOS")
    return d["carrier"]["id"]


def test_iss_rounds_each_inspection_before_averaging(api):
    """PRD §3.6: "Otherwise, for each included inspection compute a raw value equal to
    the sum of the `severity_weight` of that inspection's violations, multiplied by 1.5
    when the inspection's `oos_flag` is true and by 1.0 otherwise; cap that raw value at
    100; and round it to the nearest whole number using round-half-up. This
    per-inspection rounding happens first, before any averaging. Then sum the rounded
    per-inspection values, divide by the number of included inspections, and round that
    average to the nearest whole number using round-half-up."

    Design: Difficulty/combinatorial_formula/iss_score_round_per_inspection_then_average
    """
    # raws 4.5 -> 5 and 6.0 -> 6; (5+6)/2 = 5.5 -> 6 (averaging raws first gives 5.25 -> 5).
    carrier_id = _two_oos_inspections("DOT-844-D", sev1=3, sev2=4)
    assert _get_carrier(carrier_id)["iss_score"] == 6


def test_iss_pinned_order_when_average_of_rounded_rounds_up(api):
    """PRD §3.6: "This per-inspection rounding happens first, before any averaging. Then
    sum the rounded per-inspection values, divide by the number of included inspections,
    and round that average to the nearest whole number using round-half-up."
    PRD §3.6: "The order of operations is fixed and load-bearing: rounding each
    inspection to an integer before averaging, then rounding the average, is not
    interchangeable with averaging the raw values and rounding once."

    Design: Difficulty/combinatorial_formula/iss_score_round_per_inspection_then_average
    """
    # raws 4.5 -> 5 and 1.5 -> 2; (5+2)/2 = 3.5 -> 4 (averaging raws first gives 3.0 -> 3).
    carrier_id = _two_oos_inspections("DOT-844-D2", sev1=3, sev2=1)
    assert _get_carrier(carrier_id)["iss_score"] == 4


# --- Difficulty: provisional vs certified ISS divergence ---

def _pending_vs_finalized(usdot):
    """inspection #1 finalized OOS (raw 12); inspection #2 IN_PROGRESS with a sev-10
    non-OOS violation. Returns carrier_id."""
    d = setup_domain(carrier_overrides={"usdot_number": usdot, "legal_name": "Bravo Lines"},
                     station_overrides={"name": "US-101", "state_code": "CA"})
    s1 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-2", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    i1 = create_inspection(s1["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T08:00:00Z", scheduled_end="2026-03-02T09:00:00Z")
    add_violation(i1["id"], code="393.75", category="WEIGHT", severity_weight=4, oos=True)
    add_violation(i1["id"], code="393.9", category="VEHICLE", severity_weight=4, oos=True)
    finalize(i1["id"], "OOS")
    s2 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-2", gross_weight_lbs=87000, heaviest_axle_lbs=21000)
    i2 = create_inspection(s2["id"], d["bay"]["id"], level="LEVEL_II",
                           scheduled_start="2026-03-02T10:00:00Z", scheduled_end="2026-03-02T11:00:00Z")
    add_violation(i2["id"], code="396.3", category="VEHICLE", severity_weight=10, oos=False)
    return d["carrier"]["id"]


def test_provisional_iss_includes_in_progress_inspection(api):
    """PRD §3.6: "The **provisional** variant — which drives the carrier's live
    `iss_score` field and the auto-created snapshots — includes inspections whose
    `status` is `IN_PROGRESS`, `REINSPECTION`, `CLEARED`, or `OOS_ISSUED`, and excludes
    `CANCELLED` inspections."

    Design: Difficulty/dual_variant_calc/iss_score_provisional_vs_certified_diverges
    """
    # OOS_ISSUED raw 12 -> 12; IN_PROGRESS raw 10 -> 10; (12+10)/2 = 11.
    carrier_id = _pending_vs_finalized("DOT-844-B")
    assert _get_carrier(carrier_id)["iss_score"] == 11


def test_certified_snapshot_excludes_pending_inspection(api):
    """PRD §3.6: "The **certified** variant — which drives a certified snapshot and the
    carrier's `certified_iss_score` — includes only finalized inspections, those whose
    `status` is `CLEARED` or `OOS_ISSUED`; a pending `IN_PROGRESS` inspection's
    violations are excluded, so the certified score can diverge from the provisional
    one."

    Design: Difficulty/dual_variant_calc/iss_score_provisional_vs_certified_diverges
    """
    carrier_id = _pending_vs_finalized("DOT-844-B2")
    version = _get_carrier(carrier_id)["version"]
    snap = validate_success(
        api.create_score_snapshot(carrier_id, {"expected_carrier_version": version}, ADMIN),
        expected_status=201)
    assert snap["method"] == "CERTIFIED"
    assert snap["iss_score"] == 12  # only the finalized OOS inspection (raw 12)
    carrier = _get_carrier(carrier_id)
    assert carrier["certified_iss_score"] == 12
    assert carrier["iss_score"] != snap["iss_score"]


# --- Corner: OCC version guard ---

def test_certified_snapshot_with_matching_version_succeeds(api):
    """PRD §2.9: "The create request must carry `expected_carrier_version`, and its value
    must equal the carrier's current `version` at the moment the request is processed."
    PRD §3.6: "If no inspection qualifies, the score is 0."

    Design: Corner/cross_cutting_complexity_layers/score_snapshot_correct_version_succeeds
    """
    carrier = create_carrier(usdot_number="DOT-C22", legal_name="Corner TwentyTwo")
    version = _get_carrier(carrier["id"])["version"]
    resp = api.create_score_snapshot(carrier["id"], {"expected_carrier_version": version}, ADMIN)
    snap = validate_success(resp, expected_status=201)
    assert snap["method"] == "CERTIFIED"
    assert snap["is_current"] is True
    assert snap["iss_score"] == 0


def test_certified_snapshot_with_stale_version_rejected(api):
    """PRD §2.9: "If an intervening operation — for instance an inspection finalize that
    cascaded an `oos_points`, `iss_score`, or `version` bump onto the carrier — has
    advanced the carrier's `version` since the client last read it, the request is
    rejected with `ERR_STALE_CARRIER_VERSION` and HTTP status 412, preventing the client
    from computing a snapshot against a carrier view it has not actually observed."

    Design: Corner/cross_cutting_complexity_layers/score_snapshot_stale_version_returns_412
    """
    carrier = create_carrier(usdot_number="DOT-C23", legal_name="Corner TwentyThree")
    v1 = carrier["version"]
    # First snapshot succeeds and bumps the carrier version past v1.
    validate_success(
        api.create_score_snapshot(carrier["id"], {"expected_carrier_version": v1}, ADMIN),
        expected_status=201)
    resp = api.create_score_snapshot(carrier["id"], {"expected_carrier_version": v1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_CARRIER_VERSION)
