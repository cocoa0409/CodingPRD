"""Warranty claims: coverage windows, review cycle, segregation of duties (PRD §2.8, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client as _api,
    assert_instant_equals,
    book_transport,
    canonical_community_scenario,
    create_claim,
    fund_application,
    get_success_data,
    issue_title_for_order,
    make_customer_headers,
    make_service_manager_headers,
    progress_to_financing_approved,
    set_clock,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
INSTALLER = TEST_USERS["installer_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _installed_scenario(job_start="2026-08-20T08:00:00Z", delivered_clock="2026-08-20T10:00:00Z", set_clock_time=None):
    """Canonical community order through set completion (unit INSTALLED).

    PRD §3.6 gates booking on deal_status exactly FINANCING_APPROVED, and §3.5
    funding bubbles the order FINANCING_APPROVED -> AWAITING_DELIVERY, so the
    booking is placed between financing approval and funding."""
    scn = canonical_community_scenario()
    progress_to_financing_approved(scn)
    book_transport(scn, distance_miles=180, scheduled_start_date=job_start)
    issue_title_for_order(scn)
    fund_application(scn)
    set_clock(delivered_clock)
    validate_success(_api.dispatch_transport_job(scn["job"]["id"], COORDINATOR))
    validate_success(_api.deliver_transport_job(scn["job"]["id"], COORDINATOR))
    if set_clock_time:
        set_clock(set_clock_time)
    scn["job"] = validate_success(_api.complete_set_transport_job(scn["job"]["id"], INSTALLER))
    scn["unit"] = get_success_data(_api.get_home_unit(scn["unit"]["id"], ADMIN))
    return scn


# --- review cycle (cyclic state machine) ----------------------------------------

def test_warranty_info_request_cycles_back_to_under_review(api):
    """PRD §3.8: "`DENY` moves the claim to `DENIED`, and `REQUEST_INFO` moves it
    to `INFO_REQUESTED`; both stamp `reviewed_by` as well. The claim is never
    stuck: a buyer may resubmit from `INFO_REQUESTED` — returning it to
    `UNDER_REVIEW` with the `description` replaced by the new text — and may
    likewise appeal from `DENIED` back into `UNDER_REVIEW` the same way, in each
    case only as the order's own customer (else `ERR_UNAUTHORIZED`)."

    Design: Difficulty/non_linear_state_machine/warranty_info_request_cycle
    """
    scn = _installed_scenario()
    claim = create_claim(scn, claim_type="FACTORY_DEFECT", description="Roof seam leak", estimated_cost_cents=240_000)

    reviewed = validate_success(
        api.review_warranty_claim(claim["id"], {"decision": "REQUEST_INFO"}, make_service_manager_headers("svc-1"))
    )
    assert reviewed["status"] == "INFO_REQUESTED"

    resubmitted = validate_success(
        api.resubmit_warranty_claim(
            claim["id"],
            {"description": "Roof seam leak with photos attached"},
            make_customer_headers(scn["customer"]["id"]),
        )
    )
    assert resubmitted["status"] == "UNDER_REVIEW", "the claim cycles back, not a new claim"
    assert resubmitted["description"] == "Roof seam leak with photos attached"
    assert resubmitted["id"] == claim["id"]


def test_warranty_cycle_then_approve(api):
    """PRD §3.8: "`APPROVE` requires the offered `approved_cost_cents` to be no
    greater than the claim's `estimated_cost_cents`, else
    `ERR_CLAIM_AMOUNT_EXCESS`; the approved amount and the reviewer's `X-User-ID`
    are recorded in `reviewed_by`."

    Design: Difficulty/non_linear_state_machine/warranty_info_request_cycle
    """
    scn = _installed_scenario()
    claim = create_claim(scn, claim_type="FACTORY_DEFECT", description="Roof seam leak", estimated_cost_cents=240_000)

    validate_success(api.review_warranty_claim(claim["id"], {"decision": "REQUEST_INFO"}, make_service_manager_headers("svc-1")))
    validate_success(
        api.resubmit_warranty_claim(
            claim["id"], {"description": "Roof seam leak with photos attached"}, make_customer_headers(scn["customer"]["id"])
        )
    )
    approved = validate_success(
        api.review_warranty_claim(
            claim["id"], {"decision": "APPROVE", "approved_cost_cents": 200_000}, make_service_manager_headers("svc-1")
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_cost_cents"] == 200_000
    assert approved["description"] == "Roof seam leak with photos attached"


# --- coverage window anchors ------------------------------------------------------

def test_install_anchored_window_expires_before_delivery_anchored(api):
    """PRD §3.8: "A `FACTORY_DEFECT` claim is covered from the unit's
    `delivered_at` through 365 days after it; an `INSTALLATION_DAMAGE` claim is
    covered from the unit's `set_completed_at` through 90 days after it — a late
    set date can therefore make an installation claim valid on dates when a
    factory claim would already be expired, and vice versa."
    PRD §3.8: "Both windows are inclusive at the end: a claim filed exactly at
    the window's end instant is still in coverage, and anything later is rejected
    with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/dual_variant_calc/delivery_vs_install_anchored_warranty_window
    """
    scn = _installed_scenario(job_start="2026-09-01T08:00:00Z", delivered_clock="2026-09-01T10:00:00Z", set_clock_time="2026-09-05T10:00:00Z")
    # install window: 2026-09-05T10:00:00Z + 90 days = 2026-12-04T10:00:00Z (inclusive)
    set_clock("2026-12-05T00:00:00Z")
    resp = api.create_warranty_claim(
        {
            "home_unit_id": scn["unit"]["id"],
            "sales_order_id": scn["order"]["id"],
            "claim_type": "INSTALLATION_DAMAGE",
            "description": "Skirting misaligned",
            "estimated_cost_cents": 120_000,
        },
        make_customer_headers(scn["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_delivery_anchored_window_still_open_when_install_closed(api):
    """PRD §3.8: "A `FACTORY_DEFECT` claim is covered from the unit's
    `delivered_at` through 365 days after it; an `INSTALLATION_DAMAGE` claim is
    covered from the unit's `set_completed_at` through 90 days after it — a late
    set date can therefore make an installation claim valid on dates when a
    factory claim would already be expired, and vice versa."
    PRD §3.8: "Both windows are inclusive at the end: a claim filed exactly at
    the window's end instant is still in coverage, and anything later is rejected
    with `ERR_WARRANTY_EXPIRED`."
    PRD §3.8: "Coverage is anchored per claim type, and the computed
    `coverage_window_end` is stored on the claim at creation."

    Design: Difficulty/dual_variant_calc/delivery_vs_install_anchored_warranty_window
    """
    scn = _installed_scenario(job_start="2026-09-01T08:00:00Z", delivered_clock="2026-09-01T10:00:00Z", set_clock_time="2026-09-05T10:00:00Z")
    set_clock("2026-12-05T00:00:00Z")
    claim = validate_success(
        api.create_warranty_claim(
            {
                "home_unit_id": scn["unit"]["id"],
                "sales_order_id": scn["order"]["id"],
                "claim_type": "FACTORY_DEFECT",
                "description": "Roof seam leak",
                "estimated_cost_cents": 240_000,
            },
            make_customer_headers(scn["customer"]["id"]),
        ),
        expected_status=201,
    )
    # delivery anchor: 2026-09-01T10:00:00Z + 365 days = 2027-09-01T10:00:00Z.
    assert_instant_equals(claim["coverage_window_end"], "2027-09-01T10:00:00Z")


def test_warranty_claim_on_final_day_inclusive(api):
    """PRD §3.8: "Both windows are inclusive at the end: a claim filed exactly at
    the window's end instant is still in coverage, and anything later is rejected
    with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/boundary_precision_check/warranty_final_day_inclusive
    """
    scn = _installed_scenario(job_start="2026-09-01T08:00:00Z", delivered_clock="2026-09-01T10:00:00Z", set_clock_time="2026-09-05T10:00:00Z")
    set_clock("2027-09-01T10:00:00Z")  # exactly the factory window end
    claim = validate_success(
        api.create_warranty_claim(
            {
                "home_unit_id": scn["unit"]["id"],
                "sales_order_id": scn["order"]["id"],
                "claim_type": "FACTORY_DEFECT",
                "description": "Final-day leak report",
                "estimated_cost_cents": 100_000,
            },
            make_customer_headers(scn["customer"]["id"]),
        ),
        expected_status=201,
    )
    assert_instant_equals(claim["coverage_window_end"], "2027-09-01T10:00:00Z")


def test_warranty_claim_one_second_past_window_rejected(api):
    """PRD §3.8: "Both windows are inclusive at the end: a claim filed exactly at
    the window's end instant is still in coverage, and anything later is rejected
    with `ERR_WARRANTY_EXPIRED`."
    PRD §2.6: "Datetime comparisons (rate locks, warranty windows) are evaluated
    at second precision, and window ends are inclusive: an instant exactly equal
    to the window end is still inside coverage."

    Design: Difficulty/boundary_precision_check/warranty_final_day_inclusive
    """
    scn = _installed_scenario(job_start="2026-09-01T08:00:00Z", delivered_clock="2026-09-01T10:00:00Z", set_clock_time="2026-09-05T10:00:00Z")
    set_clock("2027-09-01T10:00:01Z")  # one second past the inclusive end
    resp = api.create_warranty_claim(
        {
            "home_unit_id": scn["unit"]["id"],
            "sales_order_id": scn["order"]["id"],
            "claim_type": "FACTORY_DEFECT",
            "description": "One second late",
            "estimated_cost_cents": 100_000,
        },
        make_customer_headers(scn["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


# --- review cap, resolution, segregation ------------------------------------------

def test_review_claim_amount_excess_rejected(api):
    """PRD §3.8: "`APPROVE` requires the offered `approved_cost_cents` to be no
    greater than the claim's `estimated_cost_cents`, else
    `ERR_CLAIM_AMOUNT_EXCESS`; the approved amount and the reviewer's `X-User-ID`
    are recorded in `reviewed_by`."

    Design: Corner/validations/review_claim_amount_excess_rejected
    """
    scn = _installed_scenario()
    claim = create_claim(scn, claim_type="INSTALLATION_DAMAGE", description="Skirting misaligned", estimated_cost_cents=200_000)

    resp = api.review_warranty_claim(
        claim["id"], {"decision": "APPROVE", "approved_cost_cents": 200_001}, make_service_manager_headers("svc-1")
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_EXCESS)

    approved = validate_success(
        api.review_warranty_claim(
            claim["id"], {"decision": "APPROVE", "approved_cost_cents": 200_000}, make_service_manager_headers("svc-1")
        )
    )
    assert approved["status"] == "APPROVED" and approved["approved_cost_cents"] == 200_000


def test_warranty_resolved_terminal_lockdown(api):
    """PRD §3.8: "Resolution closes an `APPROVED` claim into `RESOLVED`, but
    segregation of duties forbids the resolver from being the reviewer: the
    resolving `X-User-ID` must differ from the claim's `reviewed_by`, else
    `ERR_SEGREGATION_OF_DUTIES`, and the resolver's id is stamped into
    `resolved_by`."
    PRD §2.8: "(all action endpoints): the target resource is in a state from
    which the requested transition exists — this covers idempotent re-fires and
    terminal lockdown — else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/warranty_resolved_terminal_lockdown
    """
    scn = _installed_scenario()
    claim = create_claim(scn, claim_type="INSTALLATION_DAMAGE", description="Skirting misaligned", estimated_cost_cents=120_000)
    validate_success(
        api.review_warranty_claim(claim["id"], {"decision": "APPROVE", "approved_cost_cents": 120_000}, make_service_manager_headers("svc-1"))
    )
    resolved = validate_success(api.resolve_warranty_claim(claim["id"], make_service_manager_headers("svc-2")))
    assert resolved["status"] == "RESOLVED"

    resp = api.review_warranty_claim(claim["id"], {"decision": "DENY"}, make_service_manager_headers("svc-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    view = get_success_data(api.get_warranty_claim(claim["id"], TEST_USERS["service_headers"]))
    assert view["status"] == "RESOLVED", "terminal state untouched by the rejected review"


def test_warranty_resolve_same_user_rejected(api):
    """PRD §3.8: "Resolution closes an `APPROVED` claim into `RESOLVED`, but
    segregation of duties forbids the resolver from being the reviewer: the
    resolving `X-User-ID` must differ from the claim's `reviewed_by`, else
    `ERR_SEGREGATION_OF_DUTIES`, and the resolver's id is stamped into
    `resolved_by`."

    Design: Corner/rbac/warranty_resolve_same_user_rejected
    """
    scn = _installed_scenario()
    claim = create_claim(scn, claim_type="INSTALLATION_DAMAGE", description="Skirting misaligned", estimated_cost_cents=120_000)
    validate_success(
        api.review_warranty_claim(claim["id"], {"decision": "APPROVE", "approved_cost_cents": 120_000}, make_service_manager_headers("svc-1"))
    )

    resp = api.resolve_warranty_claim(claim["id"], make_service_manager_headers("svc-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resolved = validate_success(api.resolve_warranty_claim(claim["id"], make_service_manager_headers("svc-2")))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by"] == "svc-2"
    assert resolved["reviewed_by"] == "svc-1"
