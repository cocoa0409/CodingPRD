"""Composite setup helpers for the placement/referral workflow.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before each
test. Fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertions.

The workhorse is build_scenario(), which walks the canonical single-inquiry
chain (Cedar Grove / advisor Ann / family Dana) up to a named `stage`:

    approved -> selected -> pending -> moved_in -> issued -> accepted -> paid

It returns a Scenario dict whose keys accumulate as the chain advances.
Lower-level create_* helpers are provided for the multi-entity recipes that
build two communities, two advisors or two inquiries.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_advisor_payload, create_community_payload, create_inventory_payload,
    create_family_payload, create_inquiry_payload, create_assessment_payload,
    create_match_payload, create_tour_payload, create_placement_payload,
    create_guidance_payload, create_survey_payload,
)
from .test_users import (
    TEST_USERS, make_advisor_headers, make_counselor_headers,
    make_community_manager_headers, make_family_headers,
)
from .constants import BASE_CLOCK_ISO

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


def _d(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Low-level creators — each returns the created resource dict.
# ---------------------------------------------------------------------------

def set_clock(api, iso):
    return _d(api.set_clock(iso, ADMIN))


def create_advisor(api, **overrides):
    return _d(api.create_advisor(create_advisor_payload(**overrides), ADMIN))


def create_community(api, **overrides):
    return _d(api.create_community(create_community_payload(**overrides), ADMIN))


def create_inventory(api, community_id, **overrides):
    return _d(api.create_inventory(create_inventory_payload(community_id, **overrides), ADMIN))


def create_family(api, **overrides):
    return _d(api.create_family(create_family_payload(**overrides), ADMIN))


def create_inquiry(api, family_id, **overrides):
    return _d(api.create_inquiry(create_inquiry_payload(family_id, **overrides), ADMIN))


def assign_advisor(api, inquiry_id, advisor_id):
    return _d(api.assign_inquiry(inquiry_id, {"advisor_id": advisor_id}, ADMIN))


def create_approved_assessment(api, inquiry_id, author_advisor_id, **assessment_overrides):
    """Create -> submit -> APPROVE (reviewed by PlatformAdmin) an assessment.
    Returns the approved assessment dict."""
    hdr = make_advisor_headers(author_advisor_id)
    s = _d(api.create_assessment(create_assessment_payload(inquiry_id, **assessment_overrides), hdr))
    api.submit_assessment(s["id"], hdr)
    return _d(api.review_assessment(s["id"], {"decision": "APPROVE"}, ADMIN))


def get_invoice_for_placement(api, placement_id):
    """The invoice is discoverable only by listing filtered by placement_id."""
    data, _meta = _paginated(api.list_invoices(BILLING, params={"placement_id": placement_id}))
    return data[0] if data else None


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Canonical single-inquiry scenario builder.
# ---------------------------------------------------------------------------

_STAGES = ["approved", "matched", "selected", "pending", "moved_in", "issued", "accepted", "paid"]


def build_scenario(api, stage="approved", *,
                   community_overrides=None, inventory_overrides=None,
                   inquiry_overrides=None, assessment_overrides=None,
                   advisor_overrides=None, placement_overrides=None,
                   care_level="ASSISTED_LIVING",
                   move_in_date="2026-06-20", actual_care_level="ASSISTED_LIVING",
                   move_in_clock="2026-06-20T12:00:00Z",
                   pay_amount=None, clock=BASE_CLOCK_ISO):
    """Walk the canonical chain up to `stage`. Returns a Scenario dict.

    Keys populated by stage:
      always:   admin, billing, advisor, advisor_headers, community, cm_headers,
                inventory, inventory_version, family, family_headers, inquiry, assessment
      matched+: match
      selected+: tour  (match SELECTED)
      pending+: placement (PENDING_MOVE_IN)
      moved_in+: placement refreshed (MOVED_IN), invoice (DRAFT)
      issued+/accepted+/paid+: invoice advanced accordingly
    """
    assert stage in _STAGES, f"unknown stage {stage!r}"
    community_overrides = community_overrides or {}
    inventory_overrides = inventory_overrides or {}
    inquiry_overrides = inquiry_overrides or {}
    assessment_overrides = assessment_overrides or {}
    advisor_overrides = advisor_overrides or {}
    placement_overrides = placement_overrides or {}

    sc = {"admin": ADMIN, "billing": BILLING}
    set_clock(api, clock)

    advisor = create_advisor(api, **advisor_overrides)
    sc["advisor"] = advisor
    sc["advisor_headers"] = make_advisor_headers(advisor["id"])

    community = create_community(api, **community_overrides)
    sc["community"] = community
    sc["cm_headers"] = make_community_manager_headers(community["id"])

    inventory = create_inventory(api, community["id"], **inventory_overrides)
    sc["inventory"] = inventory
    sc["inventory_version"] = inventory["version"]

    family = create_family(api)
    sc["family"] = family
    sc["family_headers"] = make_family_headers(family["id"])

    inq_over = dict(inquiry_overrides)
    inq_over.setdefault("requested_care_level", care_level)
    inquiry = create_inquiry(api, family["id"], **inq_over)
    sc["inquiry"] = inquiry
    assign_advisor(api, inquiry["id"], advisor["id"])

    assessment = create_approved_assessment(api, inquiry["id"], advisor["id"], **assessment_overrides)
    sc["assessment"] = assessment
    if stage == "approved":
        sc["inquiry"] = _d(api.get_inquiry(inquiry["id"], ADMIN))
        return sc

    ahdr = sc["advisor_headers"]
    match = _d(api.create_match(create_match_payload(inquiry["id"], community["id"], care_level=care_level), ahdr))
    sc["match"] = match
    if stage == "matched":
        return sc

    api.shortlist_match(match["id"], ahdr)
    tour = _d(api.create_tour(create_tour_payload(match["id"]), ahdr))
    sc["tour"] = tour
    api.complete_tour(tour["id"], {"outcome_rating": 4}, ahdr)
    api.select_match(match["id"], ahdr)
    sc["match"] = _d(api.get_match(match["id"], ADMIN))
    if stage == "selected":
        return sc

    p_over = dict(placement_overrides)
    p_over.setdefault("agreed_move_in_date", move_in_date)
    placement = _d(api.create_placement(
        create_placement_payload(match["id"], inventory["id"], sc["inventory_version"], **p_over), ahdr))
    sc["placement"] = placement
    if stage == "pending":
        return sc

    set_clock(api, move_in_clock)
    placement = _d(api.confirm_move_in(
        placement["id"], {"actual_move_in_date": move_in_date, "actual_care_level": actual_care_level}, sc["cm_headers"]))
    sc["placement"] = placement
    invoice = get_invoice_for_placement(api, placement["id"])
    sc["invoice"] = invoice
    if stage == "moved_in":
        return sc

    invoice = _d(api.issue_invoice(invoice["id"], BILLING))
    sc["invoice"] = invoice
    if stage == "issued":
        return sc

    invoice = _d(api.accept_invoice(invoice["id"], sc["cm_headers"]))
    sc["invoice"] = invoice
    if stage == "accepted":
        return sc

    amount = pay_amount if pay_amount is not None else invoice["final_fee_cents"]
    invoice = _d(api.pay_invoice(invoice["id"], {"amount_cents": amount}, sc["cm_headers"]))
    sc["invoice"] = invoice
    sc["placement"] = _d(api.get_placement(placement["id"], ADMIN))
    return sc


# ---------------------------------------------------------------------------
# Reused multi-entity helpers.
# ---------------------------------------------------------------------------

def setup_guidance_ready(api, *, va_eligible=True, marital_status="MARRIED",
                         budget_monthly_cents=520000, gross_monthly_income_cents=320000,
                         requested_care_level="ASSISTED_LIVING", clock=BASE_CLOCK_ISO,
                         with_match=False):
    """Approved inquiry assigned to Ann (NOT VA-certified) plus a second
    VA-certified, unassigned advisor Ben who can act as the BenefitsCounselor.

    Returns a dict: advisor (Ann), counselor (Ben), counselor_headers,
    community, inventory, family, inquiry, assessment, assessment_version,
    and (when with_match) match.
    """
    set_clock(api, clock)
    ann = create_advisor(api, full_name="Ann Reyes")
    ben = create_advisor(api, full_name="Ben Cho", is_va_certified=True)
    community = create_community(api)
    inventory = create_inventory(api, community["id"])
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"], requested_care_level=requested_care_level,
                             declared_budget_monthly_cents=budget_monthly_cents)
    assign_advisor(api, inquiry["id"], ann["id"])
    assessment = create_approved_assessment(
        api, inquiry["id"], ann["id"], va_eligible=va_eligible, marital_status=marital_status,
        budget_monthly_cents=budget_monthly_cents, gross_monthly_income_cents=gross_monthly_income_cents)
    out = {
        "admin": ADMIN, "advisor": ann, "advisor_headers": make_advisor_headers(ann["id"]),
        "counselor": ben, "counselor_headers": make_counselor_headers(ben["id"]),
        "community": community, "inventory": inventory, "family": family,
        "inquiry": inquiry, "assessment": assessment, "assessment_version": assessment["version"],
    }
    if with_match:
        out["match"] = _d(api.create_match(
            create_match_payload(inquiry["id"], community["id"]), make_advisor_headers(ann["id"])))
    return out


def setup_advisor_with_caseload(api, *, count=2, capacity=2, clock=BASE_CLOCK_ISO):
    """Advisor Ann with `count` ACTIVE caseload assignments (capacity `capacity`).
    Also creates one further NEW, unassigned inquiry Q_next in the same region.

    Returns: advisor, inquiries (assigned list), next_inquiry, family.
    The two default inquiries mirror the design profiles used for the load-index
    numbers: Q1 (ASSISTED_LIVING, 2026-06-20, 520000 -> priority 70.59) and
    Q2 (MEMORY_CARE, 2026-09-30, 400000 -> priority 52.03).
    """
    set_clock(api, clock)
    ann = create_advisor(api, caseload_capacity=capacity)
    family = create_family(api)
    profiles = [
        dict(origin="WEB", requested_care_level="ASSISTED_LIVING",
             target_move_in_date="2026-06-20", declared_budget_monthly_cents=520000),
        dict(origin="PHONE", requested_care_level="MEMORY_CARE",
             target_move_in_date="2026-09-30", declared_budget_monthly_cents=400000),
        dict(origin="PARTNER_REFERRAL", requested_care_level="ASSISTED_LIVING",
             target_move_in_date="2026-07-15", declared_budget_monthly_cents=300000),
    ]
    assigned = []
    for i in range(count):
        inq = create_inquiry(api, family["id"], **profiles[i % len(profiles)])
        assign_advisor(api, inq["id"], ann["id"])
        assigned.append(inq)
    nxt = create_inquiry(api, family["id"], **profiles[count % len(profiles)])
    return {"advisor": ann, "inquiries": assigned, "next_inquiry": nxt, "family": family}

