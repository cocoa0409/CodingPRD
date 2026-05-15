"""TransportRoute aggregate tests covering the four-state
``approval_status`` machine, the polyline body-shape rules, and the
two-time-point hazard-class subset re-check.

The route state machine from PRD §3.4 is the four-state cycle
``DRAFT → SUBMITTED → APPROVED`` forward path plus the
``SUBMITTED → REJECTED → DRAFT → SUBMITTED`` reapply-after-reject
cycle, with the same internal-collapse-on-the-submit-handler pattern
as the company's revocation-revision cycle of PRD §3.1.

The two-time-point hazard-class-subset-of-the-parent-company-authorized
check (PRD §2.9 "two-time-point hazard-class subset re-check") fires at
both the operator's submit and the regulator's approve, against the
company's then-current ``hazard_classes_authorized`` list.  A narrowing
of the company's set in the submit-to-approve gap (a regulator
out-of-band-revoked one of the company's authorized hazard-classes) is
the canonical case where the submit passes but the approve fails.

The polyline geometry has the standard WGS-84-degree-range bounds on
each waypoint's lat-and-lon pair and the 2-to-200-waypoint cardinality
bound.
"""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    CANONICAL_POLYLINE,
    HazmatScenario,
    api_client,
    assert_route,
    company_operator_headers,
    create_route_payload,
    get_success_data,
    regulator_headers,
    reject_route_payload,
    setup_approved_company,
    setup_qualified_carrier,
    setup_route_under_company,
    validate_error,
    validate_success,
)
from test_helpers.types import (
    HAZARD_CLASSES_UN,
    RouteApprovalStatus,
)


# ─── Create-and-state-machine forward path ────────────────────────────


def test_route_create_returns_draft(api, approved_company: Dict):
    """PRD §3.4 first paragraph: "The operator files a new route via
    ``POST /v1/companies/{company_id}/routes`` … The response is
    the 201 row in ``approval_status = DRAFT``"."""
    op = company_operator_headers(approved_company["id"])
    payload = create_route_payload()
    resp = api.create_route(approved_company["id"], payload, op)
    rt = validate_success(resp, 201)
    assert_route(rt)
    assert rt["company_id"] == approved_company["id"]
    assert rt["approval_status"] == RouteApprovalStatus.DRAFT.value
    assert rt.get("approved_at") is None
    assert rt.get("approved_by") is None
    assert rt.get("rejection_reason") is None


def test_route_submit_transitions_to_submitted(api, approved_company: Dict):
    """``POST /v1/routes/{route_id}/submit`` is the operator's
    ``DRAFT → SUBMITTED`` transition.  Per PRD §3.4 the submit
    handler also walks the internal ``REJECTED → DRAFT → SUBMITTED``
    on a previously-rejected route."""
    op = company_operator_headers(approved_company["id"])
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    resp = api.submit_route(rt["id"], {}, op)
    sub = validate_success(resp, 200)
    assert sub["approval_status"] == RouteApprovalStatus.SUBMITTED.value
    assert sub["version"] == rt["version"] + 1


def test_route_approve_transitions_to_approved(api, approved_company: Dict):
    """The regulator's ``SUBMITTED → APPROVED`` transition writes
    ``approved_at`` and the regulator's ``X-User-ID`` echo to the
    ``approved_by`` audit field."""
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    sub = get_success_data(api.submit_route(rt["id"], {}, op))
    appr = get_success_data(api.approve_route(sub["id"], {}, reg))
    assert appr["approval_status"] == RouteApprovalStatus.APPROVED.value
    assert appr.get("approved_at") is not None
    assert appr.get("approved_by") is not None
    assert appr.get("rejection_reason") is None  # no prior rejection in this cycle


def test_route_reject_transitions_to_rejected(api, approved_company: Dict):
    """The regulator's ``SUBMITTED → REJECTED`` transition writes
    the required body ``rejection_reason`` onto the row's
    ``rejection_reason`` field for the operator's reapply.
    The audit-trail ``approved_at`` and ``approved_by`` from any
    prior cycle are left untouched per PRD §3.4."""
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    sub = get_success_data(api.submit_route(rt["id"], {}, op))
    rej_payload = reject_route_payload(rejection_reason="Hazard-class scope is too broad.")
    rej = get_success_data(api.reject_route(sub["id"], rej_payload, reg))
    assert rej["approval_status"] == RouteApprovalStatus.REJECTED.value
    assert rej["rejection_reason"] == "Hazard-class scope is too broad."


def test_route_rejection_reason_required(api, approved_company: Dict):
    """PRD §3.4: "Body carries a required ``rejection_reason``" of
    1-to-500 characters.  An empty string is the
    ``ERR_VALIDATION`` 422 body-shape rejection."""
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    sub = get_success_data(api.submit_route(rt["id"], {}, op))
    resp = api.reject_route(sub["id"], reject_route_payload(rejection_reason=""), reg)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── The rejection-and-reapply cycle ──────────────────────────────────


def test_rejected_resubmit_clears_rejection_reason(api, approved_company: Dict):
    """PRD §3.4: "the cycle-closing internal ``REJECTED → DRAFT``
    arc that the same submit endpoint walks internally when the
    source state observed at the handler's entry is ``REJECTED``
    (the operator's reapply after a rejection — the externally
    observable trace is the row's ``approval_status`` flipping
    from ``REJECTED`` to ``SUBMITTED`` in one call, the previous
    ``rejection_reason`` being cleared to null)".

    Walk ``DRAFT → SUBMITTED → REJECTED → SUBMITTED`` and assert
    each transition and the post-cycle row's
    ``rejection_reason`` is null again.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    sub1 = get_success_data(api.submit_route(rt["id"], {}, op))
    rej = get_success_data(api.reject_route(
        sub1["id"],
        reject_route_payload(rejection_reason="Initial rejection."),
        reg,
    ))
    assert rej["rejection_reason"] == "Initial rejection."
    # The reapply: the submit handler observes the REJECTED source
    # state and walks REJECTED → DRAFT → SUBMITTED as one atomic
    # step.  The post-call status is SUBMITTED and the
    # rejection_reason has been cleared.
    sub2 = get_success_data(api.submit_route(rt["id"], {}, op))
    assert sub2["approval_status"] == RouteApprovalStatus.SUBMITTED.value
    assert sub2.get("rejection_reason") is None, (
        f"after the reapply the rejection_reason should be cleared; got {sub2.get('rejection_reason')!r}"
    )
    # The version is bumped by the two state-transitions
    # (reject and re-submit each bump the row's version exactly once).
    assert sub2["version"] >= sub1["version"] + 2


def test_approve_from_approved_is_invalid_state_transition(api, qualified_carrier: HazmatScenario):
    """The route's ``APPROVED`` state has no outgoing forward
    transition in the API surface (the in-prose "out-of-band
    administrative revocation" is not exposed).  A second approve
    on an already-APPROVED row is the ``ERR_INVALID_STATE_TRANSITION``
    409.  The same generic state-tier error fires on any
    submit/approve/reject call whose source state is not in the
    transition's allowed pre-set.
    """
    rt = qualified_carrier.route
    reg = regulator_headers()
    resp = api.approve_route(rt["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── Body-shape on the polyline geometry ──────────────────────────────


def test_polyline_must_have_at_least_two_waypoints(api, approved_company: Dict):
    """PRD §2.4 + §3.4: "the polyline is a 2-to-200-waypoint list of
    ``{lat, lon}`` pairs".  A one-waypoint list (below the lower
    bound) is the body-shape ``ERR_VALIDATION``.
    """
    op = company_operator_headers(approved_company["id"])
    payload = create_route_payload(polyline=[{"lat": 39.0, "lon": 116.0}])
    resp = api.create_route(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_polyline_lat_out_of_range_rejected(api, approved_company: Dict):
    """PRD §2.4: "``lat`` in the inclusive range from -90 to 90".
    A waypoint with lat=91 is the body-shape rejection."""
    op = company_operator_headers(approved_company["id"])
    bad_polyline = [
        {"lat": 91.0, "lon": 0.0},  # lat above the +90 ceiling
        {"lat": 0.0, "lon": 0.0},
    ]
    payload = create_route_payload(polyline=bad_polyline)
    resp = api.create_route(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_polyline_lon_out_of_range_rejected(api, approved_company: Dict):
    """The symmetric lon-range rejection at ±180.  A waypoint with
    lon=181 fails the body-shape check."""
    op = company_operator_headers(approved_company["id"])
    bad_polyline = [
        {"lat": 0.0, "lon": 0.0},
        {"lat": 0.0, "lon": -181.0},  # lon below the -180 floor
    ]
    payload = create_route_payload(polyline=bad_polyline)
    resp = api.create_route(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_route_hazard_classes_must_subset_company_authorized(api, approved_company: Dict):
    """PRD §3.4: "The hazard-class array must be a subset of the
    parent company's ``hazard_classes_authorized`` at the moment of
    the submit — a hazard class that the company is not yet
    licensed for cannot be on a route the company is filing,
    which the submit-time check enforces with ``ERR_VALIDATION``
    422 on a non-subset entry".

    The approved-company fixture's authorized set is the canonical
    ``["3", "8"]`` pair.  A route whose supported list contains a
    class outside that pair is rejected at the create-time check
    (which mirrors the submit-time check per the implementation's
    body-validation-on-create-and-submit symmetry).

    Two valid PRD readings: (a) the create-time body-shape check
    on the hazard-classes-supported-must-be-subset-of-the-
    company-authorized is the rejection point (the create handler
    runs the same predicate as the submit handler in the strict
    early-feedback convention), or (b) the create succeeds with
    the would-be-out-of-subset class on the DRAFT row and the
    submit-time check is the rejection point.  We accept either
    behaviour by trying the chain.
    """
    op = company_operator_headers(approved_company["id"])
    # The approved_company fixture's hazard_classes_authorized is
    # CANONICAL_HAZARD_CLASSES = ["3", "8"].  We list a route
    # supporting ["3", "7"] — "7" (radioactive) is not in the
    # company's authorized set.
    body_classes = ["3", "7"]
    create_resp = api.create_route(
        approved_company["id"],
        create_route_payload(hazard_classes_supported=body_classes),
        op,
    )
    if create_resp.status_code >= 400:
        # Implementation enforces at create-time.
        validate_error(create_resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)
        return
    # Otherwise the rejection is at the submit-time check.
    rt = create_resp.json()["data"]
    submit_resp = api.submit_route(rt["id"], {}, op)
    validate_error(submit_resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_route_two_time_point_hazard_class_check_at_approve(api, approved_company: Dict):
    """PRD §2.9 + §3.4 last-but-three paragraph: "the regulator's
    approve call later re-evaluates the same subset relation
    against the company's ``hazard_classes_authorized`` as it
    stands at the approval moment, which may be a smaller set if
    the company's authorized list has narrowed between the two
    timestamps".

    The standard scaffold has no public API surface for the
    regulator to revoke a single hazard-class from a company's
    authorized list (the only company-side regulator action is the
    full-revoke-of-qualification ``POST /companies/{id}/revoke``),
    so the "narrowing of the company's authorized hazard-class
    set in the submit-to-approve gap" scenario is not reachable
    through the public API in the same shape the PRD's prose
    suggests.  The PRD itself flags this in the §3.4 paragraph:
    "the regulator's revocation-of-a-hazard-class-on-a-company is
    an out-of-band administrative action whose effect on the
    on-disk row is conceptually a flip in the
    ``hazard_classes_authorized`` field with the audit log
    capturing the cause, but the scaffold does not expose the
    corresponding API endpoint".

    The observable test is the symmetric case: the company is
    revoked entirely between the route's submit and the
    regulator's approve.  Revoking the company makes the
    company's effective hazard-class scope nominally "the empty
    set" (a non-APPROVED company has no authorized hazard-class
    scope), so the approve's two-time-point recheck fails.

    The error id on the revoked-company-at-approve case is one of:
    ``ERR_COMPANY_NOT_QUALIFIED`` (the priority-526
    company-qualification check, which the route's approval-leg
    recompute folds into per the chain "the route's
    ``hazard_classes_supported`` must be a subset of the parent
    company's ``hazard_classes_authorized``, and a non-APPROVED
    company's effective authorized list is the empty intersection"),
    or the body-shape ``ERR_VALIDATION`` (the hazard-class subset
    check fires the catch-all on the empty intersection).  Either
    is PRD-consistent.
    """
    from prd_bench_local_runner.testing import validate_error_is_one_of
    from test_helpers.factories import revoke_company_payload

    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    # Create and submit a route.
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    sub = get_success_data(api.submit_route(rt["id"], {}, op))
    # Now revoke the parent company.  The company's
    # ``qualification_status`` flips to REVOKED, and the
    # effective ``hazard_classes_authorized`` scope for the
    # to-be-approved-route's subset check is gone.
    api.revoke_company(approved_company["id"], revoke_company_payload(), reg)
    # The approve attempt should now fail because the company is
    # no longer APPROVED.
    approve_attempt = api.approve_route(sub["id"], {}, reg)
    actual_err = validate_error_is_one_of(
        approve_attempt,
        [
            ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value,
            ApiErrorId.ERR_VALIDATION.value,
        ],
    )
    assert actual_err in {
        ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value,
        ApiErrorId.ERR_VALIDATION.value,
    }


# ─── Route's role-deny defaults ──────────────────────────────────────


def test_operator_cannot_approve_own_route(api, approved_company: Dict):
    """The route-approve endpoint is regulator-only per the PRD's §4
    endpoint table.  The operator hitting it is the priority-200
    role-deny ``ERR_ROLE_NOT_PERMITTED`` 403."""
    op = company_operator_headers(approved_company["id"])
    # Submit a route so it's in the SUBMITTED state for the
    # approve attempt.
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    get_success_data(api.submit_route(rt["id"], {}, op))
    # Operator's approve attempt.
    resp = api.approve_route(rt["id"], {}, op)
    # The role-deny ``ERR_ROLE_NOT_PERMITTED`` fires before the
    # cross-tenant ownership check because the operator's role
    # is not in the endpoint's allow-set at all (the cell is the
    # default-deny, not the conditionally-allow-with-ownership-
    # predicate cell).  An ownership-predicate-conditional cell
    # would give the per-row cross-tenant 403 with the dedicated
    # error id ``ERR_CROSS_TENANT_ACCESS``, but the route-approve
    # endpoint's RBAC cell on the operator row is the default-
    # deny because the regulator's-attestation-is-the-regulator's-
    # authority principle keeps the operator out of the
    # approval pathway entirely.
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


def test_operator_can_read_own_route(api, qualified_carrier: HazmatScenario):
    """The operator's read-own-route via
    ``GET /v1/routes/{route_id}`` is allowed by the
    transitive-tenant predicate (the operator's ``X-User-ID``
    equals the route's ``company_id``).
    """
    op = company_operator_headers(qualified_carrier.company["id"])
    resp = api.get_route(qualified_carrier.route["id"], op)
    rt = validate_success(resp, 200)
    assert rt["id"] == qualified_carrier.route["id"]
    assert rt["approval_status"] == RouteApprovalStatus.APPROVED.value


def test_route_no_list_endpoint(api):
    """PRD §3.4 prose: "The scaffold does not have a route-list
    endpoint at all — the audit of all routes across the system
    is the regulator's iteration through the relevant company's
    permit listings, which transitively name the routes".

    The endpoint table mirrors this: no ``GET /v1/routes`` global
    list is present.  This is the meta-test that the closed
    endpoint surface honours the §3.4 commitment.
    """
    paths = {(e["method"], e["path_tpl"]) for e in api_client.ENDPOINT_TABLE}
    assert ("GET", "/v1/routes") not in paths, (
        "the endpoint table has a global GET /v1/routes which the PRD's §3.4 excludes"
    )
    # The per-id GET /v1/routes/{route_id} is present.
    assert ("GET", "/v1/routes/{route_id}") in paths


def test_route_no_company_id_filter_on_read_per_id(api, qualified_carrier: HazmatScenario):
    """A sanity test that the route's read endpoint is the by-id
    only — no query parameters drive the read, the row is
    addressed by its primary key in the path."""
    op = company_operator_headers(qualified_carrier.company["id"])
    rt = qualified_carrier.route
    resp = api.get_route(rt["id"], op)
    data = validate_success(resp, 200)
    assert data["id"] == rt["id"]
    assert data["company_id"] == qualified_carrier.company["id"]


def test_origin_destination_labels_are_required(api, approved_company: Dict):
    """The two free-text-1-to-200-character label fields are
    required on the create body per PRD §3.4 first paragraph's
    body-field list.  Empty strings fail the lower-bound length
    check."""
    op = company_operator_headers(approved_company["id"])
    payload = create_route_payload(origin_label="", destination_label="X")
    resp = api.create_route(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_hazard_classes_supported_must_be_unique(api, approved_company: Dict):
    """The ``hazard_classes_supported`` array's body-shape rule
    forbids duplicates (the standard "no-duplicates" array
    invariant on every hazard-class-array field across the four
    hazard-class-bearing entities per the PRD's §2.8 last
    paragraph's "non-empty no-duplicate" qualifier on each)."""
    op = company_operator_headers(approved_company["id"])
    payload = create_route_payload(hazard_classes_supported=["3", "3", "8"])
    resp = api.create_route(approved_company["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)
