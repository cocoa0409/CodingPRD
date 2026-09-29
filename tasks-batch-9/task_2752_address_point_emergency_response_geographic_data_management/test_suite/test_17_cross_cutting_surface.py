"""Cross-cutting complexity layers of the County Address and Emergency Response
GIS API.

Corner-design section ``cross_cutting_layers``: optimistic concurrency on the
centerline edit and on the proposal filing, and the freezing of provisioning
pins at seal time so that two packages hold different versions of the same
address point.

Every test builds its own world through documented endpoints; the runner
restarts the server before each test, so the database starts empty.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# cross_cutting_layers / stale_road_version_patch_rejected
# ===========================================================================
def _validated_road_at_version_two(api):
    """One centerline created at version 1 and then validated to version 2."""
    world = fx.setup_draft_road_world(api)
    world["road_v1"] = world["road"]["version"]
    world["road"] = fx.validate_road(api, world["road_id"])
    world["road_v2"] = world["road"]["version"]
    return world


def test_stale_road_version_patch_is_refused_and_changes_nothing(api):
    """A legal patch body carrying the pre-validate version is 412 and a no-op.

    If it does not equal the centerline's current `version`, the edit is rejected with `ERR_STALE_ROAD_VERSION` (HTTP 412).
    Validation sets `qc_dirty` to false, increments the centerline's `version` by 1, triggers a confidence refresh in which the road-status penalty moves from 15 down to 5, and then evaluates pin staleness for the centerline and each recomputed address point.

    Design: Corner/cross_cutting_layers/stale_road_version_patch_rejected
    """
    world = _validated_road_at_version_two(api)
    assert world["road_v1"] == 1
    assert world["road_v2"] == 2

    resp = api.patch_road_centerline(
        world["road_id"],
        f.road_patch_payload(world["road_v1"], primary_name="N Maple Ave"),
        ANALYST_HEADERS,
    )
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.STALE_ROAD_VERSION)

    stored = fx.read_road(api, world["road_id"])
    assert stored["primary_name"] == "N MAPLE STREET"
    assert stored["status"] == "VALIDATED"
    assert stored["version"] == 2
    assert stored["qc_dirty"] is False, "a refused write runs no side effect"


def test_the_identical_patch_with_the_current_road_version_succeeds(api):
    """The same body carrying version 2 lands, demotes the road and dirties it.

    An edit of a `DRAFT` centerline leaves it in `DRAFT` — `DRAFT → DRAFT` is a real transition, not a no-op — while an edit of a `VALIDATED` centerline **demotes** it, `VALIDATED → DRAFT`, because a validated road whose name or ranges have moved must be re-validated before it may be published again.
    The payload carries `expected_road_version` and may carry any subset of `primary_name`, `from_addr_left`, `to_addr_left`, `parity_left`, `from_addr_right`, `to_addr_right` and `parity_right`.

    Design: Corner/cross_cutting_layers/stale_road_version_patch_rejected
    """
    world = _validated_road_at_version_two(api)
    road_id = world["road_id"]

    validate_error(
        api.patch_road_centerline(
            road_id,
            f.road_patch_payload(world["road_v1"], primary_name="N Maple Ave"),
            ANALYST_HEADERS,
        ),
        ApiErrorId.STALE_ROAD_VERSION,
    )

    resp = api.patch_road_centerline(
        road_id,
        f.road_patch_payload(world["road_v2"], primary_name="N Maple Ave"),
        ANALYST_HEADERS,
    )
    assert resp.status_code == 200
    patched = validate_success(resp, 200)
    assert patched["version"] == 3
    assert patched["primary_name"] == "N Maple Ave"
    assert patched["normalized_name"] == "N MAPLE AVENUE"
    assert patched["status"] == "DRAFT", "any edit of a VALIDATED road demotes it"
    assert patched["qc_dirty"] is True
    assert patched["from_addr_left"] == 100, "omitted fields are untouched"
    assert patched["to_addr_left"] == 198


# ===========================================================================
# cross_cutting_layers / stale_case_version_proposal_rejected
# ===========================================================================
def _case_with_one_opener_proposal(api):
    """A ROAD_NAME case at version 2 whose only proposal was filed by the opener."""
    world = fx.setup_draft_road_world(api)
    parties = fx.setup_two_agencies(api, world["j_id"])
    case = fx.setup_discrepancy_case(
        api, world["road_id"], parties["opener_id"], parties["counterparty_id"]
    )
    prop1 = fx.file_proposal(
        api, case["id"], parties["opener_id"], "N MAPLE STREET", case["version"]
    )
    world.update(parties)
    world["case_id"] = case["id"]
    world["case_v1"] = case["version"]
    world["case"] = fx.read_case(api, case["id"])
    world["prop1"] = prop1
    world["prop1_id"] = prop1["id"]
    return world


def test_the_openers_stale_counter_is_412_before_it_is_self_concurrence(api):
    """A stale `expected_case_version` outranks the opener's self-counter refusal.

    The supplied `expected_case_version` must equal the case's `version`, or the filing is refused with `ERR_STALE_CASE_VERSION` (HTTP 412).
    And once a first proposal exists, the acting side must **differ** from the current proposal's `proposed_by_side` — an agency may not counter itself — or the filing is refused with `ERR_SELF_CONCURRENCE` (HTTP 403).

    Design: Corner/cross_cutting_layers/stale_case_version_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)
    assert world["case_v1"] == 1
    assert world["case"]["version"] == 2
    opener_headers = make_agency_liaison_headers(world["opener_id"])

    stale = api.create_proposal(
        world["case_id"],
        f.proposal_payload("N MAPLE AVENUE", world["case_v1"]),
        opener_headers,
    )
    assert stale.status_code == 412
    validate_error(stale, ApiErrorId.STALE_CASE_VERSION)

    fresh_but_self = api.create_proposal(
        world["case_id"],
        f.proposal_payload("N MAPLE AVENUE", 2),
        opener_headers,
    )
    assert fresh_but_self.status_code == 403
    validate_error(fresh_but_self, ApiErrorId.SELF_CONCURRENCE)


def test_the_counterparties_stale_counter_leaves_the_case_untouched(api):
    """An otherwise legal counter-offer that never saw round 1 is 412 and a no-op.

    A mismatch with the case's current `version` is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412).
    In parallel, the case's `round_count` is the count of proposals filed on it, and its `current_proposal_id` is the proposal with the greatest `round_number`.

    Design: Corner/cross_cutting_layers/stale_case_version_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)

    resp = api.create_proposal(
        world["case_id"],
        f.proposal_payload("N MAPLE AVENUE", world["case_v1"]),
        make_agency_liaison_headers(world["counterparty_id"]),
    )
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.STALE_CASE_VERSION)

    stored = fx.read_case(api, world["case_id"])
    assert stored["status"] == "PROPOSAL_PENDING"
    assert stored["round_count"] == 1
    assert stored["version"] == 2
    assert stored["current_proposal_id"] == world["prop1_id"]

    _, meta = validate_paginated(
        api.list_proposals(
            world["case_id"],
            {"limit": 100},
            make_agency_liaison_headers(world["counterparty_id"]),
        )
    )
    assert meta["total_count"] == 1, "the refused filing appended nothing"


def test_the_counterparties_fresh_counter_carries_the_case_to_countered(api):
    """Re-reading the case and re-filing at version 2 opens round 2.

    Every one of these transitions appends a proposal whose `round_number` is one greater than the case's prior `round_count`, sets the case's `round_count` to that new value, updates `current_proposal_id` to the new proposal, and increments the case's `version` by 1.
    Its `proposed_by_side` is derived from the caller: `OPENER` when `X-User-ID` equals the case's `opened_by_agency_id`, and `COUNTERPARTY` when it equals the case's `counterparty_agency_id`.

    Design: Corner/cross_cutting_layers/stale_case_version_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)
    counter_headers = make_agency_liaison_headers(world["counterparty_id"])

    validate_error(
        api.create_proposal(
            world["case_id"],
            f.proposal_payload("N MAPLE AVENUE", world["case_v1"]),
            counter_headers,
        ),
        ApiErrorId.STALE_CASE_VERSION,
    )

    resp = api.create_proposal(
        world["case_id"],
        f.proposal_payload("N MAPLE AVENUE", 2),
        counter_headers,
    )
    assert resp.status_code == 201
    prop2 = validate_success(resp, 201)
    assert prop2["round_number"] == 2
    assert prop2["proposed_by_side"] == "COUNTERPARTY"
    assert prop2["status"] == "PENDING"

    stored = fx.read_case(api, world["case_id"])
    assert stored["status"] == "COUNTERED"
    assert stored["round_count"] == 2
    assert stored["version"] == 3
    assert stored["current_proposal_id"] == prop2["id"]

    rows, meta = validate_paginated(
        api.list_proposals(world["case_id"], {"limit": 100}, counter_headers)
    )
    assert meta["total_count"] == 2
    by_round = {row["round_number"]: row for row in rows}
    assert by_round[1]["id"] == world["prop1_id"]
    assert by_round[1]["status"] == "COUNTERED"
    assert by_round[1]["proposed_by_side"] == "OPENER"
    assert by_round[2]["status"] == "PENDING"


# ===========================================================================
# cross_cutting_layers /
#   two_packages_pin_different_versions_of_the_same_address_point
# ===========================================================================
def _two_packages_pinning_one_point(api):
    """Two sealed snapshots of one jurisdiction, taken one certification apart.

    The point is created on the already-`PUBLISHED` centerline (version 1),
    activated (version 2), stamped by the first certification (version 3) — the
    version the first package pins — and stamped again by the second
    certification (version 4), the version the second package pins.
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    fx.validate_road(api, road["id"])
    world["road"] = fx.publish_road(api, road["id"])
    world["road_id"] = road["id"]

    point = fx.setup_address_point(
        api, road["id"], world["cell_id"], geometry_verified=True
    )
    world["point_id"] = point["id"]
    world["point_created"] = point
    world["point_activated"] = fx.activate_point(api, point["id"])

    report1 = fx.setup_road_scoped_report(api, road["id"])
    fx.certify_report(api, report1["id"])
    world["point_after_first_certification"] = fx.read_point(api, point["id"])

    package1 = fx.setup_package(api, world["j_id"], report1["id"], "MAPPING")
    world["pkg1_id"] = package1["id"]
    world["pkg1_sealed"] = fx.seal_package(api, package1["id"])

    report2 = fx.setup_road_scoped_report(api, road["id"])
    fx.certify_report(api, report2["id"])

    package2 = fx.setup_package(api, world["j_id"], report2["id"], "PUBLIC")
    world["pkg2_id"] = package2["id"]
    world["pkg2_sealed"] = fx.seal_package(api, package2["id"])
    return world


def _pin_of(api, package_id, record_type):
    rows = fx.read_package_records(
        api, package_id, {"record_type": record_type, "limit": 100}
    )
    assert len(rows) == 1, f"expected one {record_type} pin, got {rows}"
    return rows[0]


def test_two_packages_pin_different_versions_of_the_same_address_point(api):
    """Each snapshot froze the point at the version live when it was sealed.

    Each row carries the `package_id` of the snapshot it belongs to, a `record_type` of `ADDRESS_POINT`, `ROAD_CENTERLINE` or `EMERGENCY_SERVICE_BOUNDARY`, a `record_id` holding the pinned record's identifier resolved per that `record_type`, a `pinned_version` equal to that record's `version` at the moment of sealing, a `pin_state` of `FRESH`, and a null `staled_at`.
    A pin is `FRESH` while `pinned_version` still equals the live record's `version`, and it flips to `STALE` the instant that live version advances, stamping `staled_at` with the logical clock instant.

    Design: Corner/cross_cutting_layers/two_packages_pin_different_versions_of_the_same_address_point
    """
    world = _two_packages_pinning_one_point(api)
    assert world["point_created"]["version"] == 1
    assert world["point_activated"]["version"] == 2
    assert world["point_after_first_certification"]["version"] == 3

    old_pin = _pin_of(api, world["pkg1_id"], "ADDRESS_POINT")
    assert old_pin["record_id"] == world["point_id"]
    assert old_pin["pinned_version"] == 3
    assert old_pin["pin_state"] == "STALE"
    assert old_pin["staled_at"] is not None

    new_pin = _pin_of(api, world["pkg2_id"], "ADDRESS_POINT")
    assert new_pin["record_id"] == world["point_id"]
    assert new_pin["pinned_version"] == 4
    assert new_pin["pin_state"] == "FRESH"
    assert new_pin["staled_at"] is None

    live = fx.read_point(api, world["point_id"])
    assert live["version"] == 4
    assert live["status"] == "ACTIVE"
    assert live["certified_confidence_score"] == 96.00


def test_only_the_older_snapshot_carries_drift(api):
    """The second certification drifted package one and left package two clean.

    Whenever any mutation increments the `version` of a record that some `FRESH` pin refers to — matched on the pin's `record_type` together with its `record_id` — that pin flips to `STALE` and its owning package recounts `fresh_pin_count` and `stale_pin_count` and re-derives `drift_detected`, which is true exactly when `stale_pin_count` is greater than zero.
    Pin staleness is then evaluated for each stamped point — and since those points remain live, this is non-destructive drift, so a sealed package pinning one of them stays `SEALED` and merely becomes drifted.

    Design: Corner/cross_cutting_layers/two_packages_pin_different_versions_of_the_same_address_point
    """
    world = _two_packages_pinning_one_point(api)
    assert world["pkg1_sealed"]["record_count"] == 2
    assert world["pkg1_sealed"]["fresh_pin_count"] == 2, "both pins were fresh at seal"
    assert world["pkg2_sealed"]["record_count"] == 2

    drifted = fx.read_package(api, world["pkg1_id"])
    assert drifted["record_count"] == 2
    assert drifted["fresh_pin_count"] == 1
    assert drifted["stale_pin_count"] == 1
    assert drifted["drift_detected"] is True
    assert drifted["status"] == "SEALED", "non-destructive drift never invalidates"
    assert drifted["invalidated_reason"] is None

    clean = fx.read_package(api, world["pkg2_id"])
    assert clean["record_count"] == 2
    assert clean["fresh_pin_count"] == 2
    assert clean["stale_pin_count"] == 0
    assert clean["drift_detected"] is False
    assert clean["status"] == "SEALED"


def test_the_shared_road_pin_stayed_fresh_in_both_snapshots(api):
    """The centerline never moved, so one live version backs both road pins.

    Every mutating act also leaves a `version` trail: because the counter advances by exactly one per mutation and every cascade increments each record it touches, the difference between a package's `pinned_version` for a record and that record's live `version` is a literal count of how many times the record moved since the snapshot was taken.
    Every centerline whose `status` is `PUBLISHED` and whose `jurisdiction_id` is that jurisdiction is in scope as a `ROAD_CENTERLINE` record.

    Design: Corner/cross_cutting_layers/two_packages_pin_different_versions_of_the_same_address_point
    """
    world = _two_packages_pinning_one_point(api)

    live_road = fx.read_road(api, world["road_id"])
    assert live_road["version"] == 3
    assert live_road["status"] == "PUBLISHED"

    for package_id in (world["pkg1_id"], world["pkg2_id"]):
        road_pin = _pin_of(api, package_id, "ROAD_CENTERLINE")
        assert road_pin["record_id"] == world["road_id"]
        assert road_pin["pinned_version"] == 3
        assert road_pin["pin_state"] == "FRESH"
        assert road_pin["staled_at"] is None

    stale_delta = _pin_of(api, world["pkg1_id"], "ADDRESS_POINT")
    live_point = fx.read_point(api, world["point_id"])
    assert live_point["version"] - stale_delta["pinned_version"] == 1
