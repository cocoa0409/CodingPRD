"""Duplicate clustering: attach (SUBMITTED -> DUPLICATE), radius boundary,
category mismatch, the canonical-not-resolved close guard, and OCC on cluster
create.

Queue A (Difficulty): the SUBMITTED branching fork into DUPLICATE, the inclusive
150m radius boundary, and the cluster-close-blocked-until-canonical-resolved
dependency. Queue B (Corner): the category-mismatch and outside-radius attach
rejections and the stale canonical version OCC failure.
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
    factories as fac,
    TEST_USERS,
)
from test_helpers.api_errors import ApiErrorId

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: SUBMITTED branching fork into DUPLICATE
# ---------------------------------------------------------------------------
def test_attach_moves_request_to_duplicate(api):
    """PRD §3.7: "A dispatcher attaches a `SUBMITTED` request to an `OPEN` cluster as a
    duplicate member, moving that request `SUBMITTED → DUPLICATE`."
    PRD §3.7: "On a successful attach the request's `cluster_id` is set to the cluster."

    Design: Difficulty/non_linear_state_machine/service_request_branching_submitted_fork
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    dup = fx.create_request(
        env["citizen"]["id"], env["category"]["id"], description="dup",
        lat=41.8810, lng=-87.6300,
    )
    data = validate_success(
        api.add_cluster_member(env["cluster"]["id"], {"request_id": dup["id"]}, DISPATCHER),
        200,
    )
    assert data["status"] == "DUPLICATE"
    assert data["cluster_id"] == env["cluster"]["id"]


def test_attach_recomputes_member_count(api):
    """PRD §3.7: "the cluster's `member_count` is recomputed as the number of requests
    whose `cluster_id` is this cluster and whose `status` is `DUPLICATE` (which
    excludes the canonical request)."

    Design: Difficulty/non_linear_state_machine/service_request_branching_submitted_fork
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    dup = fx.create_request(
        env["citizen"]["id"], env["category"]["id"], description="dup",
        lat=41.8810, lng=-87.6300,
    )
    api.add_cluster_member(env["cluster"]["id"], {"request_id": dup["id"]}, DISPATCHER)
    cluster = validate_success(api.get_duplicate_cluster(env["cluster"]["id"], DISPATCHER), 200)
    assert cluster["member_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — Difficulty: inclusive 150m radius boundary
# ---------------------------------------------------------------------------
def test_member_at_exactly_radius_is_eligible(api):
    """PRD §3.7: "That radius is 150 meters, measured by the haversine distance of
    §2.9 from the candidate's `(lat, lng)` to the cluster's `(center_lat, center_lng)`;
    the boundary is inclusive, so a request lying exactly at 150 meters is eligible, and
    one farther than 150 meters is rejected with `ERR_OUTSIDE_CLUSTER_RADIUS` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/cluster_member_at_exactly_150m_radius_eligible
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    edge = fx.create_request(
        env["citizen"]["id"], env["category"]["id"], description="edge",
        lat=41.88134746676249, lng=-87.6300,
    )
    data = validate_success(
        api.add_cluster_member(env["cluster"]["id"], {"request_id": edge["id"]}, DISPATCHER),
        200,
    )
    assert data["status"] == "DUPLICATE"


def test_member_at_exactly_radius_counts_toward_member_count(api):
    """PRD §3.7: "the boundary is inclusive, so a request lying exactly at 150 meters
    is eligible."
    PRD §3.7: "the cluster's `member_count` is recomputed as the number of requests
    whose `cluster_id` is this cluster and whose `status` is `DUPLICATE`."

    Design: Difficulty/boundary_precision_check/cluster_member_at_exactly_150m_radius_eligible
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    edge = fx.create_request(
        env["citizen"]["id"], env["category"]["id"], description="edge",
        lat=41.88134746676249, lng=-87.6300,
    )
    api.add_cluster_member(env["cluster"]["id"], {"request_id": edge["id"]}, DISPATCHER)
    cluster = validate_success(api.get_duplicate_cluster(env["cluster"]["id"], DISPATCHER), 200)
    assert cluster["member_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — Difficulty: cluster close blocked until canonical resolved
# ---------------------------------------------------------------------------
def test_cluster_close_blocked_while_canonical_submitted(api):
    """PRD §3.7: "A dispatcher closes a cluster, moving it `OPEN → MERGED_CLOSED`, but
    only once the canonical request has itself reached `RESOLVED` or `CLOSED`; an
    attempt to close earlier is rejected with `ERR_CANONICAL_NOT_RESOLVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cluster_close_blocked_until_canonical_resolved
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    resp = api.close_duplicate_cluster(env["cluster"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CANONICAL_NOT_RESOLVED.value, 409)


def test_cluster_stays_open_after_blocked_close(api):
    """PRD §3.7: "but only once the canonical request has itself reached `RESOLVED` or
    `CLOSED`; an attempt to close earlier is rejected with `ERR_CANONICAL_NOT_RESOLVED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cluster_close_blocked_until_canonical_resolved
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    api.close_duplicate_cluster(env["cluster"]["id"], DISPATCHER)
    cluster = validate_success(api.get_duplicate_cluster(env["cluster"]["id"], DISPATCHER), 200)
    assert cluster["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B — Corner: category mismatch rejected
# ---------------------------------------------------------------------------
def test_cluster_member_category_mismatch_rejected(api):
    """PRD §3.7: "that the request's `category_id` equal the cluster's `category_id`
    (else `ERR_CLUSTER_CATEGORY_MISMATCH`, HTTP 409)."

    Design: Corner/validations/cluster_member_category_mismatch_rejected
    """
    dept = fx.create_department(backlog_threshold=5)
    cat_p = fx.create_category(dept["id"], requires_geolocation=True, name="Pothole", code="POTHOLE")
    cat_g = fx.create_category(dept["id"], requires_geolocation=True, name="Graffiti", code="GRAFFITI")
    citizen = fx.create_citizen()
    canon = fx.create_request(citizen["id"], cat_p["id"], description="canon", lat=41.8800, lng=-87.6300)
    cluster = validate_success(
        api.create_duplicate_cluster(
            fac.create_duplicate_cluster_payload(cat_p["id"], canon["id"], canon["version"]),
            DISPATCHER,
        ),
        201,
    )
    other = fx.create_request(citizen["id"], cat_g["id"], description="other", lat=41.8801, lng=-87.6300)
    resp = api.add_cluster_member(cluster["id"], {"request_id": other["id"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CLUSTER_CATEGORY_MISMATCH.value, 409)


# ---------------------------------------------------------------------------
# Queue B — Corner: outside radius rejected
# ---------------------------------------------------------------------------
def test_cluster_member_outside_radius_rejected(api):
    """PRD §3.7: "one farther than 150 meters is rejected with
    `ERR_OUTSIDE_CLUSTER_RADIUS` (HTTP 409)."

    Design: Corner/validations/cluster_member_outside_radius_rejected
    """
    env = fx.setup_cluster_on_canonical(lat=41.8800, lng=-87.6300)
    far = fx.create_request(
        env["citizen"]["id"], env["category"]["id"], description="far",
        lat=41.8816, lng=-87.6300,
    )
    resp = api.add_cluster_member(env["cluster"]["id"], {"request_id": far["id"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_CLUSTER_RADIUS.value, 409)


# ---------------------------------------------------------------------------
# Queue B — Corner: OCC stale canonical version on cluster create
# ---------------------------------------------------------------------------
def test_occ_stale_canonical_version_on_cluster_create(api):
    """PRD §2.7: "When a dispatcher creates a duplicate cluster, the create request must
    carry `expected_canonical_version`, and that value must equal the current `version`
    of the canonical `ServiceRequest` the cluster is anchored to. ... If
    `expected_canonical_version` does not equal the canonical request's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_canonical_version_on_cluster_create
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=True)
    citizen = fx.create_citizen()
    canon = fx.create_request(citizen["id"], category["id"], description="canon", lat=41.8800, lng=-87.6300)
    stale_version = canon["version"]
    fx.triage_request(canon["id"])  # advances canonical version
    resp = api.create_duplicate_cluster(
        fac.create_duplicate_cluster_payload(category["id"], canon["id"], stale_version),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
