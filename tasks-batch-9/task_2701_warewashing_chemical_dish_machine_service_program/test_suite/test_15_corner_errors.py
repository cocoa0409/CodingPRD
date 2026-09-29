"""
Error distinguishability: same-status gates on one workflow must keep their own codes,
and a state gate must answer before anything the request tries to override.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CASE_NOT_IN_REVIEW,
    ERR_REVIEW_NOT_DRAFT,
    ERR_REVIEW_NOT_PUBLISHED,
    ERR_TICKET_NOT_DISPATCHABLE,
)
from test_helpers.assertions import assert_workload
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    BASIS_AS_CALIBRATED,
    CASE_EVIDENCE_GATHERING,
    CERT_L2,
    CLASS_THEFT_SUSPECT,
    DECISION_DISMISS,
    REMEDIATION_NONE,
    REVIEW_DRAFT,
    REVIEW_ESCALATED,
    REVIEW_PUBLISHED,
    TICKET_DISPATCHED,
)


def test_three_gates_on_one_workflow_keep_three_distinct_codes(api):
    """
    Three state gates on the same escalation path all answer 409 and none of them
    collapses into the generic transition error: re-publishing a published review
    reports that it is no longer a draft, escalating a review that was never published
    reports that it is not published, and adjudicating a case whose evidence has not
    been submitted reports that it is not in review — so the state error arrives before
    the segregation-of-duties test is ever reached.

    PRD §3.7: "It requires `status` `DRAFT`, refusing a review already `PUBLISHED`,
    `ESCALATED` or `CLOSED` with `ERR_REVIEW_NOT_DRAFT`."

    PRD §3.8: "The named review must stand in `PUBLISHED`, else
    `ERR_REVIEW_NOT_PUBLISHED`: a `DRAFT` review must be published before it can be
    escalated, and an `ESCALATED` or `CLOSED` review is beyond escalation."

    PRD §3.8: "Deciding a case requires `case_status` `PENDING_REVIEW`, else
    `ERR_CASE_NOT_IN_REVIEW`, and requires an auditor who is neither the case's
    `opened_by_user_id` nor the `published_by_user_id` of the review the case was opened
    against, else `ERR_SEGREGATION_OF_DUTIES` — converting a variance into a chargeback
    therefore takes two independent auditors beyond the one who drafted the review. The
    segregation test is evaluated after the state test, so a wrongly staged case reports
    its state error first."

    Design: Corner/errors/each_review_and_case_state_gate_returns_its_own_error_code
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-02T00:00:00Z")
    X.record_delivery(api, base, unit_count=1, delivered_at="2026-08-02T00:00:00Z")
    X.ingest_reading(api, placement["id"], "2026-08-02T00:00:00Z", 100)

    window = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-08T00:00:00Z",
        "basis": BASIS_AS_CALIBRATED,
        "opening_inventory_ml": 20000,
        "ending_inventory_ml": 0,
    }
    # Two drafts may cover the identical window; only publication claims it.
    to_publish = X.draft_review(api, base, **window)
    stays_draft = X.draft_review(api, base, **window)
    assert to_publish["expected_consumption_ml"] == 800
    assert to_publish["actual_consumption_ml"] == 40000
    assert to_publish["classification"] == CLASS_THEFT_SUSPECT

    published = X.publish_review(api, to_publish["id"])
    assert published["status"] == REVIEW_PUBLISHED
    assert (
        get_success_data(
            api.get_usage_variance_review(stays_draft["id"], AUDITOR_1_HEADERS)
        )["status"]
        == REVIEW_DRAFT
    )

    validate_error(
        api.publish_usage_variance_review(to_publish["id"], AUDITOR_1_HEADERS),
        ERR_REVIEW_NOT_DRAFT,
        409,
    )

    validate_error(
        api.create_investigation_case(
            F.investigation_case_payload(stays_draft["id"]), AUDITOR_1_HEADERS
        ),
        ERR_REVIEW_NOT_PUBLISHED,
        409,
    )

    case = X.open_case(api, to_publish["id"])
    assert case["case_status"] == CASE_EVIDENCE_GATHERING
    assert case["remediation"] == REMEDIATION_NONE
    assert case["evidence_item_count"] == 0
    assert (
        get_success_data(
            api.get_usage_variance_review(to_publish["id"], AUDITOR_1_HEADERS)
        )["status"]
        == REVIEW_ESCALATED
    )

    validate_error(
        api.review_investigation_case(
            case["id"], F.case_review_payload(DECISION_DISMISS), AUDITOR_2_HEADERS
        ),
        ERR_CASE_NOT_IN_REVIEW,
        409,
    )


def test_dispatch_is_neither_idempotent_nor_a_reassignment_tool(api):
    """
    A second dispatch of the same job neither re-runs the selector nor swaps engineers:
    it is refused, and so is the attempt to force a different engineer onto it, because
    the state gate runs before the override is even considered. The first assignment and
    the untouched engineer's load are exactly as the first dispatch left them.

    PRD §3.5: "A `PlatformAdmin` dispatches a ticket, which requires `status` `QUEUED`;
    a ticket already `DISPATCHED`, `ON_SITE`, `PENDING_VERIFICATION`, `CLOSED` or
    `CANCELLED` is refused with `ERR_TICKET_NOT_DISPATCHABLE`."

    PRD §3.5: "**Tie-breaking** among candidates still level on both keys goes to the
    earlier `created_at`, so the longest-tenured engineer wins; the entity identifier is
    never used as a tie-break."

    Design: Corner/errors/only_a_queued_ticket_can_be_dispatched
    """
    base = X.program_base(api)
    senior = base["technician"]
    X.set_clock(api, "2026-08-01T01:00:00Z")
    junior = X.create_technician(
        api, name="Marta Blum", region_code="NW", certification_level=CERT_L2
    )
    assert senior["certification_level"] == CERT_L2

    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    ticket = X.file_ticket(api, base, placement["id"])

    dispatched = X.dispatch_ticket(api, ticket["id"])
    assert dispatched["status"] == TICKET_DISPATCHED
    assert dispatched["assigned_technician_id"] == senior["id"]

    validate_error(
        api.dispatch_service_ticket(
            ticket["id"], PLATFORM_ADMIN_HEADERS, F.dispatch_payload()
        ),
        ERR_TICKET_NOT_DISPATCHABLE,
        409,
    )
    validate_error(
        api.dispatch_service_ticket(
            ticket["id"], PLATFORM_ADMIN_HEADERS, F.dispatch_payload(junior["id"])
        ),
        ERR_TICKET_NOT_DISPATCHABLE,
        409,
    )

    settled = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert settled["assigned_technician_id"] == senior["id"]
    assert_workload(
        get_success_data(api.get_technician(junior["id"], PLATFORM_ADMIN_HEADERS)), 0
    )
    assert_workload(
        get_success_data(api.get_technician(senior["id"], PLATFORM_ADMIN_HEADERS)), 1
    )
