"""Composite setup helpers for the AMC API test suite.

Most interesting claims require the system to be walked several API calls into a
specific state (an order DELIVERED, an order COMPLETED after a revision round, an
ROV UNDER_REVIEW, etc.). These helpers encapsulate those multi-step preambles so
tests focus on assertions, not plumbing.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server (empty DB) before every test.

Identity threading: the LenderUser and Appraiser roles are entity-backed
(PRD §2.1). Helpers that act as those roles call make_lender_user_headers /
make_appraiser_headers with the real entity id, never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
    make_lender_user_headers,
)
from . import factories


COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Clock control ──────────────────────────────────────────────────────
def pin_clock(to_iso8601: str):
    """Pin the server clock to a fixed UTC instant (PlatformAdmin, PRD §3.9)."""
    get_success_data(api_client.set_clock(factories.set_clock_payload(to_iso8601), ADMIN))


# ─── Tier 1: reference entities ─────────────────────────────────────────
def create_appraiser(license_state="CA", base_fee_share_pct=0.50, full_name="Test Appraiser"):
    """Create one ACTIVE appraiser. Returns the appraiser dict."""
    return get_success_data(api_client.create_appraiser(
        factories.create_appraiser_payload(
            full_name=full_name, license_state=license_state, base_fee_share_pct=base_fee_share_pct,
        ),
        COORD,
    ))


def create_lender(panel_ids=None, budget_cents=1_000_000, name="Test Lender"):
    """Create a lender with the given panel and monthly budget. Returns the lender dict."""
    return get_success_data(api_client.create_lender(
        factories.create_lender_payload(
            name=name,
            approved_panel_appraiser_ids=panel_ids if panel_ids is not None else [],
            monthly_fee_budget_cents=budget_cents,
        ),
        COORD,
    ))


def create_property(state_code="CA", street_address="1 Test St"):
    """Create a subject property. Returns the property dict."""
    return get_success_data(api_client.create_property(
        factories.create_property_payload(street_address=street_address, state_code=state_code),
        COORD,
    ))


def create_order(lender_id, property_id, order_fee_cents=50000, product_type="URAR_1004",
                 rush=None, as_lender_id=None):
    """Place an order. By default the AMCCoordinator places it; pass as_lender_id to
    place as the owning LenderUser (entity-backed identity). Returns the order dict."""
    overrides = {"order_fee_cents": order_fee_cents, "product_type": product_type}
    if rush is not None:
        overrides["rush"] = rush
    headers = make_lender_user_headers(as_lender_id) if as_lender_id else COORD
    return get_success_data(api_client.create_order(
        factories.create_order_payload(lender_id, property_id, **overrides),
        headers,
    ))


# ─── Tier 2: bundled reference scenario ─────────────────────────────────
def setup_order_ready_to_assign(order_fee_cents=50000, base_fee_share_pct=0.50,
                                product_type="URAR_1004", rush=None, state_code="CA"):
    """One ACTIVE appraiser on a lender's panel, a matching-state property, and a
    placed order. Returns dict with appraiser, lender, property, order."""
    appraiser = create_appraiser(license_state=state_code, base_fee_share_pct=base_fee_share_pct)
    lender = create_lender(panel_ids=[appraiser["id"]])
    prop = create_property(state_code=state_code)
    order = create_order(lender["id"], prop["id"], order_fee_cents=order_fee_cents,
                         product_type=product_type, rush=rush)
    return {"appraiser": appraiser, "lender": lender, "property": prop, "order": order}


def assign_order(order_id, expected_order_version):
    """Run the rotation selector and create the offered assignment. Returns the assignment dict."""
    return get_success_data(api_client.create_assignment(
        order_id, factories.assignment_create_payload(expected_order_version), COORD,
    ))


def accept_assignment(assignment_id, appraiser_id,
                      inspection_start="2026-06-02T15:00:00Z",
                      inspection_end="2026-06-02T17:00:00Z"):
    """Accept the assignment as its owning appraiser (entity-backed identity)."""
    return get_success_data(api_client.accept_assignment(
        assignment_id,
        factories.accept_assignment_payload(inspection_start, inspection_end),
        make_appraiser_headers(appraiser_id),
    ))


def submit_report(assignment_id, appraiser_id, opinion_of_value_cents=500000,
                  uad_condition_rating="C3", uad_quality_rating="Q4", comparable_count=5):
    """Submit (or resubmit) the report as the owning appraiser. Returns the report dict."""
    return get_success_data(api_client.submit_report(
        assignment_id,
        factories.submit_report_payload(
            opinion_of_value_cents=opinion_of_value_cents,
            uad_condition_rating=uad_condition_rating,
            uad_quality_rating=uad_quality_rating,
            comparable_count=comparable_count,
        ),
        make_appraiser_headers(appraiser_id),
    ))


def open_review(report_id):
    """Open a compliance review (ComplianceReviewer). Returns the review dict."""
    return get_success_data(api_client.open_compliance_review(report_id, {}, REVIEWER))


def finalize_review(review_id, finding_codes=None):
    """Finalize a compliance review (ComplianceReviewer). Returns the review dict."""
    return get_success_data(api_client.finalize_compliance_review(
        review_id, factories.finalize_review_payload(finding_codes=finding_codes), REVIEWER,
    ))


def current_order_version(order_id):
    """Read the order's current version (for OCC-guarded calls)."""
    return get_success_data(api_client.get_order(order_id, COORD))["version"]


# ─── Tier 3: lifecycle shortcuts ────────────────────────────────────────
def setup_order_in_qc(order_fee_cents=50000, base_fee_share_pct=0.50, comparable_count=5,
                      product_type="URAR_1004"):
    """Walk an order to IN_QC: assign, accept, submit report, open compliance review (PENDING).
    Returns dict: appraiser, lender, property, order, assignment, report, review."""
    base = setup_order_ready_to_assign(order_fee_cents=order_fee_cents,
                                       base_fee_share_pct=base_fee_share_pct,
                                       product_type=product_type)
    order = base["order"]
    asg = assign_order(order["id"], order["version"])
    accept_assignment(asg["id"], base["appraiser"]["id"])
    report = submit_report(asg["id"], base["appraiser"]["id"], comparable_count=comparable_count)
    review = open_review(report["id"])
    base.update({"assignment": asg, "report": report, "review": review})
    return base


def setup_order_delivered(order_fee_cents=50000, base_fee_share_pct=0.50,
                          opinion_of_value_cents=500000, product_type="URAR_1004"):
    """Walk an order to DELIVERED via a clean PASS review (comparable_count 5, no findings).
    Returns dict: appraiser, lender, property, order, assignment, report, review."""
    base = setup_order_in_qc(order_fee_cents=order_fee_cents,
                             base_fee_share_pct=base_fee_share_pct,
                             comparable_count=5, product_type=product_type)
    # Resubmit-free path: report had 5 comparables, finalize PASS.
    # opinion is already the default; submit_report used default 500000.
    finalize_review(base["review"]["id"])
    return base


def setup_order_delivered_with_value(opinion_of_value_cents, base_fee_share_pct=0.50,
                                     order_fee_cents=50000):
    """Like setup_order_delivered but pins the report's opinion_of_value (hence the
    delivered appraised_value_cents). Returns the same dict shape."""
    base = setup_order_ready_to_assign(order_fee_cents=order_fee_cents,
                                       base_fee_share_pct=base_fee_share_pct)
    order = base["order"]
    asg = assign_order(order["id"], order["version"])
    accept_assignment(asg["id"], base["appraiser"]["id"])
    report = submit_report(asg["id"], base["appraiser"]["id"],
                           opinion_of_value_cents=opinion_of_value_cents, comparable_count=5)
    review = open_review(report["id"])
    finalize_review(review["id"])
    base.update({"assignment": asg, "report": report, "review": review})
    return base


def setup_order_completed_after_one_revision(order_fee_cents=50000, base_fee_share_pct=0.60):
    """Drive an order through exactly one compliance-FAIL revision round, then COMPLETE it.

    Sequence: assign -> accept -> submit (2 comps, USPAP-min NOT met) -> open review ->
    finalize FAIL (USPAP finding) [revision_round -> 1] -> resubmit (4 comps) ->
    open new review -> finalize PASS [DELIVERED] -> complete [FINAL fee split].

    Returns dict: appraiser, lender, property, order, assignment, report, plus
    order_after_complete and fee_split (the FINAL split read after completion).
    """
    base = setup_order_ready_to_assign(order_fee_cents=order_fee_cents,
                                       base_fee_share_pct=base_fee_share_pct)
    order = base["order"]
    asg = assign_order(order["id"], order["version"])
    accept_assignment(asg["id"], base["appraiser"]["id"])
    report = submit_report(asg["id"], base["appraiser"]["id"], comparable_count=2)
    cr1 = open_review(report["id"])
    finalize_review(cr1["id"], finding_codes=["USPAP_1004_MIN_COMPS"])  # FAIL -> revision round 1
    submit_report(asg["id"], base["appraiser"]["id"], comparable_count=4)  # resubmit
    cr2 = open_review(report["id"])
    finalize_review(cr2["id"])  # PASS -> DELIVERED
    v = current_order_version(order["id"])
    order_after = get_success_data(api_client.complete_order(
        order["id"], factories.assignment_create_payload(v), COORD,
    ))
    fee_split = get_success_data(api_client.get_order_fee_split(order["id"], COORD))[0]
    base.update({
        "assignment": asg, "report": report,
        "order_after_complete": order_after, "fee_split": fee_split,
    })
    return base


def setup_order_completed_clean(order_fee_cents=60000, base_fee_share_pct=0.50,
                                product_type="URAR_1004",
                                placed_at="2026-06-01T00:00:00Z",
                                accepted_at="2026-06-02T00:00:00Z",
                                completed_at="2026-06-04T00:00:00Z"):
    """Drive a clean (revision-free, PASS) order to COMPLETED with the clock pinned at
    each stage so SLA/turnaround math is deterministic. Returns dict with appraiser,
    lender, property, order, assignment, plus assignment_after_complete & order_after_complete.
    """
    pin_clock(placed_at)
    base = setup_order_ready_to_assign(order_fee_cents=order_fee_cents,
                                       base_fee_share_pct=base_fee_share_pct,
                                       product_type=product_type)
    order = base["order"]
    asg = assign_order(order["id"], order["version"])
    pin_clock(accepted_at)
    accept_assignment(asg["id"], base["appraiser"]["id"],
                      inspection_start="2026-06-03T15:00:00Z",
                      inspection_end="2026-06-03T17:00:00Z")
    report = submit_report(asg["id"], base["appraiser"]["id"], comparable_count=5)
    review = open_review(report["id"])
    finalize_review(review["id"])  # PASS -> DELIVERED
    pin_clock(completed_at)
    v = current_order_version(order["id"])
    order_after = get_success_data(api_client.complete_order(
        order["id"], factories.assignment_create_payload(v), COORD,
    ))
    asg_after = get_success_data(api_client.get_assignment(asg["id"], COORD))
    base.update({
        "assignment": asg, "report": report,
        "order_after_complete": order_after, "assignment_after_complete": asg_after,
    })
    return base


# ─── Tier 4: ROV setups ─────────────────────────────────────────────────
def setup_rov_under_review(requested_value_cents, opinion_of_value_cents=500000,
                           base_fee_share_pct=0.50, order_fee_cents=50000,
                           second_review=False):
    """Deliver an order at `opinion_of_value_cents`, open an ROV at `requested_value_cents`,
    and move it to UNDER_REVIEW. If second_review is True, additionally open and PASS a
    second (post-delivery) compliance review on the report.

    Returns dict: appraiser, lender, property, order, assignment, report, rov.
    """
    base = setup_order_delivered_with_value(opinion_of_value_cents,
                                            base_fee_share_pct=base_fee_share_pct,
                                            order_fee_cents=order_fee_cents)
    rov = get_success_data(api_client.create_reconsideration(
        base["order"]["id"],
        factories.reconsideration_payload(requested_value_cents),
        make_lender_user_headers(base["lender"]["id"]),
    ))
    get_success_data(api_client.start_review_reconsideration(rov["id"], COORD))
    if second_review:
        cr2 = open_review(base["report"]["id"])
        finalize_review(cr2["id"])  # PASS
    base["rov"] = rov
    return base
