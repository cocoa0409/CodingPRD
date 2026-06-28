"""Listing/pagination, reverse-reachability reads, RBAC (auth/role/ownership), and quote-accept
optimistic concurrency. Translates Corner queue sections endpoints, rbac, and
cross_cutting_complexity_layers.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    build_user_headers,
    create_homeowner_payload, create_project_payload, create_quote_payload,
    create_quote_accept_payload,
    setup_designed_project, setup_in_manufacture, make_homeowner_headers, TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
MF = TEST_USERS["manufacturer_headers"]


# ─── endpoints: listing & reverse-reachability ─────────────────────────────

def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/endpoints/list_projects_pagination_envelope
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="e1@x.com"), SD))
    for addr in ("E1a", "E1b"):
        get_success_data(api.create_project(create_project_payload(
            ho["id"], address_line=addr, structure_type="SCREEN_ROOM", material="ALUMINUM"), SD))
    data, meta = validate_paginated(api.list_projects(
        SD, params={"homeowner_id": ho["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_projects_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range from 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/endpoints/list_projects_invalid_pagination_rejected
    """
    res = api.list_projects(SD, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_project_quotes_reverse_reachability_both_revisions(api):
    """PRD §3.2: "The act of quoting creates a `Quote` referencing the project's `project_id`,
    with a system-assigned `revision_no` (a 1-based counter equal to one more than the highest
    existing `revision_no` on the project, never less than 1)"
    PRD §3.5: "it creates a new `FINAL`-variant `Quote` with `revision_no` one greater than the
    current highest"

    Design: Corner/endpoints/project_quotes_reverse_reachability_returns_both_revisions
    """
    # PRD-faithful path to two revisions on one project: the ESTIMATE (revision_no 1) issued
    # on the DESIGNED project, then the FINAL (revision_no 2) created when production starts.
    # (Issuing requires a DESIGNED project, so two ESTIMATE quotes are not reachable.)
    ho, pj, q1, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    body = api.list_project_quotes(pj["id"], SD).json()
    quotes = {x["id"]: x for x in body["data"]}
    estimate = [x for x in body["data"] if x["variant"] == "ESTIMATE"][0]
    final = [x for x in body["data"] if x["variant"] == "FINAL"][0]
    assert quotes[q1["id"]]["revision_no"] == 1, quotes
    assert estimate["revision_no"] == 1, quotes
    assert final["revision_no"] == 2, quotes


# ─── rbac ──────────────────────────────────────────────────────────────────

def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of these six
    known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    res = api.create_homeowner(create_homeowner_payload(email="rb1@x.com"), {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_wrong_role_forbidden_on_create_project(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/wrong_role_forbidden_on_create_project
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="rb2@x.com"), SD))
    # POST /projects is exclusive to SalesDesigner; calling as Homeowner -> ERR_FORBIDDEN_ROLE.
    res = api.create_project(create_project_payload(
        ho["id"], address_line="RB2", structure_type="SCREEN_ROOM", material="ALUMINUM"),
        make_homeowner_headers(ho["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_non_owner_homeowner_cannot_accept_quote(api):
    """PRD §2.1: "When a `Homeowner` attempts to cancel a project, accept or reject a quote,
    submit a financing application, or resubmit a permit on a project they do not own, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/non_owner_homeowner_cannot_accept_quote
    """
    # Owner ho1 has DESIGNED project + ISSUED quote; intruder ho2 tries to accept.
    ho1, pj, m = setup_designed_project(
        homeowner_overrides={"email": "owner@x.com"},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    ho2 = get_success_data(api.create_homeowner(
        create_homeowner_payload(email="intruder@x.com"), SD))
    q = get_success_data(api.create_quote(create_quote_payload(pj["id"]), SD))
    pv = get_success_data(api.get_project(pj["id"], SD))["version"]
    res = api.accept_quote(q["id"], create_quote_accept_payload(pv),
                           make_homeowner_headers(ho2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
    q_after = get_success_data(api.get_quote(q["id"], SD))
    assert q_after["status"] == "ISSUED", q_after


# ─── cross_cutting_complexity_layers: OCC ──────────────────────────────────

# NOTE: test_quote_accept_stale_project_version_conflict was removed here. Its only
# PRD-described trigger (PRD §2.6: a re-measure supersedes the outstanding estimate, bumps
# Project.version, then the client accepts the now-superseded quote) collides with the fixed
# precedence in PRD §2.7, which checks state legality (quote must be ISSUED — ERR_INVALID_STATE,
# 5th) strictly before the optimistic-concurrency check (ERR_STALE_PROJECT_VERSION, 6th). The
# re-measure leaves the quote SUPERSEDED and the project no longer QUOTED, so a §2.7-faithful
# implementation returns ERR_INVALID_STATE, not ERR_STALE_PROJECT_VERSION. No PRD-documented
# transition advances Project.version while leaving the quote ISSUED and the project QUOTED, so
# the asserted ERR_STALE_PROJECT_VERSION outcome is not uniquely derivable (ERROR PRECEDENCE
# collapse between §2.6 and §2.7). Deleted per the PRD-First contract.


def test_quote_accept_correct_version_increments_version(api):
    """PRD §2.6: "the request body must carry `expected_project_version`, a non-optional field
    holding the `version` of the owning `Project` as the client last observed it."
    PRD §3.2: "Acceptance — which requires the quote to be `ISSUED`, to belong to the
    homeowner's project, and to pass the optimistic-concurrency check on
    `expected_project_version` described in §2.6 — sets the accepted quote to `ACCEPTED`, sets
    every other `ISSUED` quote on the project to `SUPERSEDED`, points `accepted_quote_id` at the
    accepted quote, advances the project `QUOTED → PERMITTING`, and increments `Project.version`
    by one."

    Design: Corner/cross_cutting_complexity_layers/quote_accept_correct_version_increments_version
    """
    ho, pj, m1 = setup_designed_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    q = get_success_data(api.create_quote(create_quote_payload(pj["id"]), SD))
    pv = get_success_data(api.get_project(pj["id"], SD))["version"]
    accepted = validate_success(api.accept_quote(
        q["id"], create_quote_accept_payload(pv), make_homeowner_headers(ho["id"])), 200)
    assert accepted["status"] == "ACCEPTED", accepted
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "PERMITTING", pj_after
    assert pj_after["version"] == pv + 1, pj_after
