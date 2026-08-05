"""Enforcement: citation fine variants (standard vs repeat, min/max clamp), the
dispute→dismiss branch, segregation of duties, and complaint escalation/resolution.

Translates Difficulty instances (dual_variant_calc citation fine,
combinatorial_formula repeat-fine clamp, non_linear_state_machine dispute branch)
and Corner error/state_machine instances.
"""
from test_helpers import (
    validate_success, validate_error,
    adjudicate_payload, resolve_complaint_payload,
    make_officer_headers, make_resident_headers,
)
from test_helpers.fixtures import (
    create_zone, register_household,
    issue_citation, dispute_citation, adjudicate_citation, accumulate_upheld_citations,
    file_complaint, resolve_complaint, set_clock,
    setup_full_zone_with_waitlisted_app, SUP,
)


# --------------------------------------------------------------------------
# dual_variant_calc / citation_fine_standard_vs_repeat_offender
# --------------------------------------------------------------------------
def test_repeat_offender_fine_after_two_prior_upheld(api):
    """PRD §3.8: "Otherwise the citation is the `REPEAT_OFFENDER` variant: a raw amount
    is the base multiplied by two raised to the power of (the prior upheld count minus
    the repeat threshold of 2, then plus one), and the `fine_amount_cents` is that raw
    amount clamped to be at least 2500 cents and at most 25000 cents, with
    `fine_variant` recorded as `REPEAT_OFFENDER`."

    Design: Difficulty/dual_variant_calc/citation_fine_standard_vs_repeat_offender
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    accumulate_upheld_citations(api, zone["id"], "RPT7", 2, hh["id"], permit_id=None)
    cit = issue_citation(api, zone["id"], "RPT7", "NO_PERMIT")
    assert cit["prior_upheld_count"] == 2
    assert cit["fine_variant"] == "REPEAT_OFFENDER"
    assert cit["fine_amount_cents"] == 15000  # 7500 * 2^(2-2+1)


def test_standard_fine_for_clean_plate(api):
    """PRD §3.8: "If the prior upheld count is strictly less than the repeat threshold
    of 2, the citation is the `STANDARD` variant and its `fine_amount_cents` is the base
    fine, with `fine_variant` recorded as `STANDARD`."

    Design: Difficulty/dual_variant_calc/citation_fine_standard_vs_repeat_offender
    """
    zone = create_zone(api)
    cit = issue_citation(api, zone["id"], "CLEAN7", "NO_PERMIT")
    assert cit["fine_variant"] == "STANDARD"
    assert cit["fine_amount_cents"] == 7500  # base NO_PERMIT fine


# --------------------------------------------------------------------------
# combinatorial_formula / repeat_fine_escalation_min_max_clamp
# --------------------------------------------------------------------------
def test_repeat_fine_clamped_to_max(api):
    """PRD §3.8: "the `fine_amount_cents` is that raw amount clamped to be at least 2500
    cents and at most 25000 cents, with `fine_variant` recorded as `REPEAT_OFFENDER`."

    Design: Difficulty/combinatorial_formula/repeat_fine_escalation_min_max_clamp
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    accumulate_upheld_citations(api, zone["id"], "RPT9", 3, hh["id"], permit_id=None)
    cit = issue_citation(api, zone["id"], "RPT9", "NO_PERMIT")
    # raw = 7500 * 2^(3-2+1) = 30000, clamped down to MAX 25000.
    assert cit["fine_amount_cents"] == 25000


def test_repeat_fine_records_prior_count_and_variant(api):
    """PRD §3.8: "The system then counts the prior upheld citations on the same plate in
    the same zone — citations with that `license_plate` and `zone_id` whose status is
    `UPHELD` — and snapshots that count into the citation's `prior_upheld_count`."

    Design: Difficulty/combinatorial_formula/repeat_fine_escalation_min_max_clamp
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    accumulate_upheld_citations(api, zone["id"], "RPT9", 3, hh["id"], permit_id=None)
    cit = issue_citation(api, zone["id"], "RPT9", "NO_PERMIT")
    assert cit["prior_upheld_count"] == 3
    assert cit["fine_variant"] == "REPEAT_OFFENDER"


# --------------------------------------------------------------------------
# non_linear_state_machine / citation_dispute_branch_to_dismissed
# --------------------------------------------------------------------------
def _disputed_citation(api):
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    cit = issue_citation(api, zone["id"], "BR1", "ZONE_VIOLATION", officer="officer-1")
    dispute_citation(api, cit["id"], hh["id"])
    return cit


def test_dispute_dismissed_sets_status(api):
    """PRD §3.8: "A dismiss outcome drives the citation `DISPUTED → DISMISSED`, records
    the officer as `adjudicator_id`, and leaves no fine owed."

    Design: Difficulty/non_linear_state_machine/citation_dispute_branch_to_dismissed
    """
    cit = _disputed_citation(api)
    result = validate_success(
        api.adjudicate_citation(cit["id"], adjudicate_payload("DISMISSED"), make_officer_headers("officer-2")), 200)
    assert result["status"] == "DISMISSED"


def test_dispute_dismissed_records_adjudicator(api):
    """PRD §3.8: "A dismiss outcome drives the citation `DISPUTED → DISMISSED`, records
    the officer as `adjudicator_id`, and leaves no fine owed."

    Design: Difficulty/non_linear_state_machine/citation_dispute_branch_to_dismissed
    """
    cit = _disputed_citation(api)
    result = validate_success(
        api.adjudicate_citation(cit["id"], adjudicate_payload("DISMISSED"), make_officer_headers("officer-2")), 200)
    assert result["adjudicator_id"] == "officer-2"


# --------------------------------------------------------------------------
# transitive_cascade / uphold_revokes_permit_promotes_waitlist
# --------------------------------------------------------------------------
def _cascade_setup(api):
    """Capacity-1 zone: H1 permit with 2 prior UPHELD citations, H2 WAITLISTED."""
    s = setup_full_zone_with_waitlisted_app(api, holder_plate="CAS1", waiter_plate="CAS2")
    accumulate_upheld_citations(api, s["zone"]["id"], "CAS1", 2, s["h1"]["id"], permit_id=s["permit1"]["id"])
    return s


def _third_upheld(api, s):
    cit = issue_citation(api, s["zone"]["id"], "CAS1", "EXPIRED_PERMIT",
                         permit_id=s["permit1"]["id"], officer="officer-1")
    dispute_citation(api, cit["id"], s["h1"]["id"])
    adjudicate_citation(api, cit["id"], "UPHELD", officer="officer-2")


def test_third_upheld_citation_revokes_permit(api):
    """PRD §3.8: "first, if the citation names a `permit_id` and that permit's
    `upheld_citation_count` — the count of upheld citations against it — has reached the
    revocation threshold of 3, the permit is revoked"

    Design: Difficulty/transitive_cascade/uphold_revokes_permit_promotes_waitlist
    """
    s = _cascade_setup(api)
    _third_upheld(api, s)
    permit = validate_success(api.get_permit(s["permit1"]["id"], SUP), 200)
    assert permit["status"] == "REVOKED"


def test_revocation_promotes_waitlist_and_issues_permit(api):
    """PRD §3.8: "second, revoking that permit frees a zone slot and promotes the oldest
    `WAITING` waitlist entry; third, the promoted entry's application is approved and a
    new permit is issued, exactly as in §3.6."

    Design: Difficulty/transitive_cascade/uphold_revokes_permit_promotes_waitlist
    """
    s = _cascade_setup(api)
    _third_upheld(api, s)
    entry = validate_success(api.get_waitlist_entry(s["entry2"]["id"], SUP), 200)
    assert entry["status"] == "PROMOTED"
    app2 = validate_success(api.get_permit_application(s["app2"]["id"], SUP), 200)
    assert app2["status"] == "APPROVED"
    assert app2["permit_id"] is not None
    zone_after = validate_success(api.get_zone(s["zone"]["id"], SUP), 200)
    assert zone_after["active_permit_count"] == 1


# --------------------------------------------------------------------------
# Corner/errors/adjudicate_own_citation_rejected_sod
# --------------------------------------------------------------------------
def test_adjudicate_own_citation_rejected(api):
    """PRD §3.8: "A `DISPUTED` citation is adjudicated by an `EnforcementOfficer` who
    supplies an `outcome`, but that officer must not be the one who issued it — the
    adjudicating `X-User-ID` must differ from the citation's `issuing_officer_id`, or
    the request fails with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/adjudicate_own_citation_rejected_sod
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    cit = issue_citation(api, zone["id"], "SOD1", "ZONE_VIOLATION", officer="officer-1")
    dispute_citation(api, cit["id"], hh["id"])
    resp = api.adjudicate_citation(cit["id"], adjudicate_payload("UPHELD"), make_officer_headers("officer-1"))
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# --------------------------------------------------------------------------
# Corner/state_machines/pay_already_paid_citation_returns_invalid_state
# --------------------------------------------------------------------------
def test_pay_already_paid_citation_rejected(api):
    """PRD §2.7: "(4) whether the target resource is in a legal state for the requested
    transition (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §3.8: "A resident may pay an `ISSUED` citation, driving it `ISSUED → PAID`, or
    dispute it, driving it `ISSUED → DISPUTED`."

    Design: Corner/state_machines/pay_already_paid_citation_returns_invalid_state
    """
    zone = create_zone(api)
    hh = register_household(api, zone["id"])
    cit = issue_citation(api, zone["id"], "PAY1", "ZONE_VIOLATION", officer="officer-1")
    validate_success(api.pay_citation(cit["id"], make_resident_headers(hh["id"])), 200)
    resp = api.pay_citation(cit["id"], make_resident_headers(hh["id"]))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


# --------------------------------------------------------------------------
# Corner/errors/escalate_complaint_without_plate_returns_error
# --------------------------------------------------------------------------
def test_escalate_complaint_without_plate_rejected(api):
    """PRD §3.9: "An escalate outcome drives it `OPEN → ESCALATED`, but only when the
    complaint carries a non-null `target_plate` — otherwise the request fails with
    `ERR_ESCALATION_REQUIRES_PLATE` (HTTP 422)."

    Design: Corner/errors/escalate_complaint_without_plate_returns_error
    """
    zone = create_zone(api)
    complaint = file_complaint(api, zone["id"], complaint_type="OTHER",
                               description="general noise", resident_id="resident-y")
    resp = api.resolve_complaint(complaint["id"], resolve_complaint_payload("ESCALATED"),
                                 make_officer_headers("officer-1"))
    validate_error(resp, "ERR_ESCALATION_REQUIRES_PLATE", expected_status=422)


# --------------------------------------------------------------------------
# Corner/state_machines/resolve_already_resolved_complaint_returns_invalid_state
# --------------------------------------------------------------------------
def test_resolve_already_resolved_complaint_rejected(api):
    """PRD §3.9: "Resolving a complaint that is not `OPEN` fails as an invalid state."

    Design: Corner/state_machines/resolve_already_resolved_complaint_returns_invalid_state
    """
    zone = create_zone(api)
    complaint = file_complaint(api, zone["id"], complaint_type="SIGNAGE",
                               description="faded sign", resident_id="resident-x")
    resolve_complaint(api, complaint["id"], "RESOLVED", resolution_note="repainted", officer="officer-1")
    resp = api.resolve_complaint(complaint["id"], resolve_complaint_payload("DISMISSED"),
                                 make_officer_headers("officer-1"))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
