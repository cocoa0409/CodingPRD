"""RBAC, portal auth, segregation of duties, OCC stale-version, and computed reads
(breadth).

Translates the corner `rbac`, `cross_cutting_complexity_layers`, `consistency_model`,
and `endpoints` section instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited, set_clock, file_contest,
    schedule_hearing, create_vendor_contract,
    create_program_payload, create_citation_payload, review_payload,
    create_contest_payload, rule_payload,
    setup_cited_citation, setup_hearing_scheduled,
    TEST_USERS, make_review_officer_headers, make_registered_owner_headers,
    make_adjudicator_headers, build_user_headers,
)

SYS = TEST_USERS["system_admin_headers"]
PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")
AUD = TEST_USERS["auditor_headers"]


# ─── rbac ─────────────────────────────────────────────

def test_reviewofficer_cannot_create_program(api):
    """PRD §2.1: "When a request presents valid headers but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/reviewofficer_cannot_create_program
    """
    res = api.create_program(create_program_payload(), RO)
    validate_error(res, "ERR_FORBIDDEN")


def test_adjudicator_cannot_review_citation(api):
    """PRD §2.1: "When a request presents valid headers but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/adjudicator_cannot_review_citation
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    citation = capture_citation(program["id"], camera["id"])
    res = api.review_citation(citation["id"], review_payload("APPROVE"),
                              make_adjudicator_headers("adj-9"))
    validate_error(res, "ERR_FORBIDDEN")


def test_segregation_reviewer_cannot_adjudicate_same_citation(api):
    """PRD §2.1: "an `Adjudicator` may never rule on, or be assigned to, a hearing
    for a citation they themselves reviewed. Concretely, the adjudicator's
    `X-User-ID` must differ from the citation's stored `review_officer_ref`; a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_reviewer_cannot_adjudicate_same_citation
    """
    # Reviewed by ro-1; hearing scheduled with a distinct adjudicator (adj-9), since
    # scheduling itself enforces SoD (PRD §3.5). The ruling is then attempted by the
    # reviewer's identity (ro-1), exercising the ruling-time SoD check.
    ctx = setup_hearing_scheduled(review_officer_id="ro-1", adjudicator_ref="adj-9")
    hearing = ctx["hearing"]
    set_clock("2026-05-15T11:00:00Z")
    res = api.rule_hearing(
        hearing["id"], rule_payload("UPHELD", hearing["version"]),
        make_adjudicator_headers("ro-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
    unchanged = get_success_data(api.get_hearing(hearing["id"], PA))
    assert unchanged["status"] == "SCHEDULED"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
    This is the first check applied to any staff endpoint, evaluated before role
    authorization, existence, or any business rule."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.list_programs(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_portal_auth_wrong_pin_rejected(api):
    """PRD §2.1: "owner-portal operations authenticate by presenting a
    `registered_owner_id` together with the `portal_access_pin` that the server
    minted for that owner at registration time. When the pair does not match a
    registered owner, the request is rejected with `ERR_PORTAL_AUTH_FAILED` (HTTP
    401)."

    Design: Corner/rbac/portal_auth_wrong_pin_rejected
    """
    program = create_program()
    owner = create_owner(program["id"], plate_number="ABC123", full_name="Pat")
    res = api.list_portal_citations(
        make_registered_owner_headers(owner["id"]),
        params={"registered_owner_id": owner["id"], "portal_access_pin": "WRONG-PIN"})
    validate_error(res, "ERR_PORTAL_AUTH_FAILED")


# ─── cross_cutting_complexity_layers (OCC) ────────────

def test_occ_stale_citation_version_on_contest(api):
    """PRD §2.6: "The request must include `expected_citation_version` carrying the
    client's last observed `version` of the target citation. If that value does not
    match the citation's current `version` — because another writer has advanced the
    citation since the owner last read it, for example a review re-decision or an
    escalation sweep that changed the citation's state and bumped its version — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_citation_version_on_contest
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    owner = create_owner(program["id"], plate_number="ABC123", full_name="Pat")
    citation = capture_citation(program["id"], camera["id"])
    stale_version = citation["version"]  # version before the review that produced CITED
    review_to_cited(citation["id"])      # advances citation.version
    res = api.create_contest(
        citation["id"],
        create_contest_payload(owner["id"], owner["portal_access_pin"], stale_version),
        make_registered_owner_headers(owner["id"]))
    validate_error(res, "ERR_STALE_VERSION")
    unchanged = get_success_data(api.get_citation(citation["id"], PA))
    assert unchanged["status"] == "CITED"


def test_occ_correct_citation_version_on_contest_succeeds(api):
    """PRD §3.5: "A successful filing transitions the citation `CITED → CONTESTED`,
    increments the citation's `version` by one, records the filer as
    `submitted_by_owner_id`, and creates a `Contest` in `SUBMITTED` status."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_citation_version_on_contest_succeeds
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    owner = ctx["owner"]
    contest = file_contest(cit["id"], owner["id"], owner["portal_access_pin"],
                           cit["version"])
    updated = get_success_data(api.get_citation(cit["id"], PA))
    assert contest["status"] == "SUBMITTED"
    assert updated["status"] == "CONTESTED"


def test_occ_stale_hearing_version_on_rule(api):
    """PRD §2.6: "The request must include `expected_hearing_version` carrying the
    adjudicator's last observed `version` of the target hearing. If that value does
    not match the hearing's current `version` ... the ruling is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_hearing_version_on_rule
    """
    ctx = setup_hearing_scheduled()
    hearing = ctx["hearing"]
    set_clock("2026-05-15T11:00:00Z")
    stale_version = hearing["version"] - 1
    res = api.rule_hearing(
        hearing["id"], rule_payload("UPHELD", stale_version),
        make_adjudicator_headers("adj-9"))
    validate_error(res, "ERR_STALE_VERSION")
    unchanged = get_success_data(api.get_hearing(hearing["id"], PA))
    assert unchanged["status"] == "SCHEDULED"


# ─── consistency_model ────────────────────────────────

def test_adjudicated_uphold_amount_stands_immediate(api):
    """PRD §3.5: "**`UPHELD`**: the citation is liable at the full statutory amount.
    The citation transitions `HEARING_SCHEDULED → ADJUDICATED_UPHELD`, its
    `adjudicated_amount_cents` is set to its `assessed_amount_cents` (the fine stands
    unchanged, surcharge included), the hearing's `outcome` becomes `UPHELD`, and the
    contest moves `SCHEDULED → DISMISSED`."

    Design: Corner/consistency_model/adjudicated_uphold_amount_stands_immediate
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    contest = ctx["contest"]
    set_clock("2026-05-15T11:00:00Z")
    from test_helpers import rule_hearing
    rule_hearing(hearing["id"], "UPHELD", hearing["version"], adjudicator_ref="adj-9")
    updated = get_success_data(api.get_citation(cit["id"], PA))
    updated_contest = get_success_data(api.get_contest(contest["id"], PA))
    assert updated["status"] == "ADJUDICATED_UPHELD"
    assert updated["adjudicated_amount_cents"] == 12500
    assert updated_contest["status"] == "DISMISSED"


# ─── endpoints (computed reads) ───────────────────────

def test_list_citations_filter_by_owner_reverse_reachability(api):
    """PRD §4: "GET | `/citations` | List citations (filterable) | ProgramAdmin,
    ReviewOfficer, Adjudicator, Auditor".
    PRD §3.3: "it sets `registered_owner_id` to the matched owner's `id`".

    Design: Corner/endpoints/list_citations_filter_by_owner_reverse_reachability
    """
    ctx = setup_cited_citation()
    owner = ctx["owner"]
    data, meta = validate_paginated(
        api.list_citations(AUD, params={"registered_owner_id": owner["id"]}))
    assert meta["total_count"] == 1


def test_get_vendor_contract_surfaces_accrued_share(api):
    """PRD §3.7: "On reaching `PAID`, the applied share is added to the contract's
    `accrued_vendor_share_cents`, which is surfaced for audit and never goes below
    zero."

    Design: Corner/endpoints/get_vendor_contract_surfaces_accrued_share
    """
    program = create_program()
    vendor = create_vendor_contract(program["id"], 0.3)
    vc = get_success_data(api.get_vendor_contract(vendor["id"], AUD))
    assert vc["accrued_vendor_share_cents"] == 0
    assert vc["status"] == "ACTIVE"
