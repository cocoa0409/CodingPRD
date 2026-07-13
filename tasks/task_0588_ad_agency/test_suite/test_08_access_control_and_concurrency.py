"""Authentication, role and ownership boundaries, and the two stale-version guards."""

from test_helpers import (
    ApiErrorId,
    assemble_invoice,
    create_client_payload,
    create_insertion_order_payload,
    create_sow_payload,
    create_time_entry_payload,
    log_time,
    make_account_manager_headers,
    make_agency_admin_headers,
    make_client_reviewer_headers,
    make_creative_lead_headers,
    register_client,
    register_placement,
    register_staff,
    retainer_version,
    reserve_insertion_order,
    set_clock,
    setup_approved_senior_hour,
    setup_base,
    setup_media_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUIDS = [f"00000000-0000-4000-8000-00000000000{d}" for d in range(1, 10)]


# --------------------------------------------------------------------------
# Authentication, roles and ownership
# --------------------------------------------------------------------------


def test_a_request_without_auth_headers_is_unauthenticated(api, no_auth_headers):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID` and
    `X-User-Role`. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_user_role_header_returns_unauthenticated
    """
    resp = api.create_client(create_client_payload(), no_auth_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401


def test_a_creative_lead_may_not_issue_an_invoice(api):
    """PRD §2.1: "Once the caller is authenticated, the role is checked against the set of roles
    authorised for the endpoint being called (see the table in section 4); a caller whose role is
    not in that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "**Issuing** is the `AgencyAdmin`'s act and the head of the system's longest
    cascade. It is legal only from `approval_status` `DRAFT` and requires the
    `expected_retainer_version` guard of section 2.7."

    Design: Corner/rbac/creative_lead_cannot_issue_an_invoice
    """
    base = setup_base(retainer_funding=5_000_000)
    setup_approved_senior_hour(base)
    invoice = assemble_invoice(base, billing_mode="FINAL")
    version = retainer_version(base["retainer_id"])

    resp = api.issue_invoice(
        invoice["id"], {"expected_retainer_version": version}, base["dana_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert resp.status_code == 403

    after = validate_success(api.get_invoice(invoice["id"], base["admin_headers"]))
    assert after["approval_status"] == "DRAFT"

    retainer = validate_success(api.get_retainer(base["retainer_id"], base["admin_headers"]))
    assert retainer["balance_cents"] == 5_000_000, "no cash moved"


def test_a_client_reviewer_may_not_countersign_another_advertisers_sow(api):
    """PRD §2.1: "For a `ClientReviewer`, `X-User-ID` must equal the advertiser the target
    resource resolves to: the `client_id` of a statement of work being countersigned, the
    `client_id` of an invoice being paid, and — for a media plan being signed off or a
    deliverable being reviewed — the `client_id` of the campaign that owns it."
    PRD §2.1: "A violation of any of these ownership rules is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/client_reviewer_cannot_countersign_another_clients_sow
    """
    set_clock("2026-06-01T00:00:00Z")
    admin = make_agency_admin_headers()

    acme = register_client(name="Acme Retail", industry="RETAIL", billing_email="ap@acme.test")
    borea = register_client(name="Borea Bank", industry="FINANCE", billing_email="ap@borea.test")
    rate_card = validate_success(api.create_rate_card(
        {"name": "Standard 2026", "rate_junior_cents_per_hour": 12_000,
         "rate_senior_cents_per_hour": 20_000, "rate_director_cents_per_hour": 32_000}, admin), 201)
    ravi = register_staff(full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000)

    acme_sow = validate_success(api.create_sow(
        create_sow_payload(acme["id"], rate_card["id"], title="Acme SOW"),
        make_account_manager_headers(ravi["id"])), 201)

    resp = api.countersign_sow(acme_sow["id"], make_client_reviewer_headers(borea["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert resp.status_code == 403

    sow = validate_success(api.get_sow(acme_sow["id"], admin))
    assert sow["status"] == "DRAFT"
    assert sow["pinned_rate_senior_cents_per_hour"] is None


def test_an_account_manager_may_not_approve_the_time_they_logged_themselves(api):
    """PRD §2.1: "The agency operates a segregation of duties between the person who records work
    and the person who signs off on it: an `AccountManager` approving a time entry must not be
    the same `StaffMember` who logged it. Self-approval is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.5: "Approval moves the entry `SUBMITTED → APPROVED`, stamps the approver's
    `X-User-ID` into `approved_by_staff_id`, and splits the entry's minutes into a regular leg
    and an overtime leg."

    Design: Corner/rbac/account_manager_cannot_approve_their_own_time_entry
    """
    base = setup_base()
    own_entry = log_time(base, "ravi", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    assert own_entry["staff_id"] == base["ravi_id"]

    resp = api.approve_time_entry(own_entry["id"], base["am_headers"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert resp.status_code == 403

    unchanged = validate_success(api.get_time_entry(own_entry["id"], base["admin_headers"]))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["approved_by_staff_id"] is None

    # A different StaffMember acting as AccountManager approves the very same entry.
    other_manager = make_account_manager_headers(base["dana_id"])
    approved = validate_success(api.approve_time_entry(own_entry["id"], other_manager))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_staff_id"] == base["dana_id"]
    assert approved["billable_amount_cents"] == 12_000, "60 minutes at the pinned JUNIOR rate"


def test_nobody_may_log_another_persons_hours(api):
    """PRD §2.1: "For the three staff roles, logging time requires that `X-User-ID` equal the
    `staff_id` named in the request body: nobody may log another person's hours. A violation of
    any of these ownership rules is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.5: "Logging time is the one write that any of the three staff roles may perform, and
    each of them may log only their own hours: the `staff_id` in the payload must equal the
    caller's `X-User-ID`."

    Design: Corner/rbac/staff_member_cannot_log_time_under_someone_elses_staff_id
    """
    base = setup_base()

    resp = api.create_time_entry(
        create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                  "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z"),
        make_creative_lead_headers(base["kai_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert resp.status_code == 403

    _rows, meta = validate_paginated(api.list_time_entries(
        base["admin_headers"], params={"campaign_id": base["campaign_id"]}))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Not-found resolution
# --------------------------------------------------------------------------


def test_approving_an_unknown_time_entry_is_not_found(api):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a live resource, checked
    left to right — otherwise the matching not-found error for the entity that failed
    (`ERR_CLIENT_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`,
    `ERR_VENDOR_COST_NOT_FOUND`, `ERR_MEDIA_PLAN_NOT_FOUND`, `ERR_INSERTION_ORDER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`), all HTTP
    404."

    Design: Corner/errors/approve_time_entry_with_unknown_id_returns_time_entry_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    ravi = register_staff(full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000)

    resp = api.approve_time_entry(UNKNOWN_UUIDS[3], make_account_manager_headers(ravi["id"]))
    validate_error(resp, ApiErrorId.ERR_TIME_ENTRY_NOT_FOUND.value)
    assert resp.status_code == 404


def test_every_not_found_code_names_the_entity_that_failed_to_resolve(api):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a live resource, checked
    left to right — otherwise the matching not-found error for the entity that failed
    (`ERR_CLIENT_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`,
    `ERR_VENDOR_COST_NOT_FOUND`, `ERR_MEDIA_PLAN_NOT_FOUND`, `ERR_INSERTION_ORDER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`), all HTTP
    404."
    PRD §2.8: "Every foreign key carried in the request body resolves, checked in the order the
    fields are listed for that endpoint — otherwise the matching not-found error, including
    `ERR_MEDIA_PLACEMENT_NOT_FOUND` when an insertion order names a publisher slot that does not
    exist."

    Design: Corner/errors/remaining_entity_specific_not_found_codes_are_all_reachable
    """
    set_clock("2026-06-01T00:00:00Z")
    admin = make_agency_admin_headers()
    client = register_client()
    ravi = register_staff(full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000)
    mia = register_staff(full_name="Mia Chen", grade="SENIOR", cost_rate_cents_per_hour=6_000)
    am = make_account_manager_headers(ravi["id"])

    # An unknown rate_card_id on a SOW whose client_id does resolve.
    validate_error(
        api.create_sow(create_sow_payload(client["id"], UNKNOWN_UUIDS[0], title="X"), am),
        ApiErrorId.ERR_RATE_CARD_NOT_FOUND.value,
    )
    validate_error(api.get_retainer(UNKNOWN_UUIDS[1], admin),
                   ApiErrorId.ERR_RETAINER_NOT_FOUND.value)
    validate_error(api.get_sow(UNKNOWN_UUIDS[2], admin), ApiErrorId.ERR_SOW_NOT_FOUND.value)
    validate_error(api.get_campaign(UNKNOWN_UUIDS[3], admin),
                   ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value)
    validate_error(api.submit_deliverable(UNKNOWN_UUIDS[4], make_creative_lead_headers(mia["id"])),
                   ApiErrorId.ERR_DELIVERABLE_NOT_FOUND.value)
    validate_error(api.approve_vendor_cost(UNKNOWN_UUIDS[5], {"actual_amount_cents": 100}, am),
                   ApiErrorId.ERR_VENDOR_COST_NOT_FOUND.value)
    validate_error(api.get_media_plan(UNKNOWN_UUIDS[6], admin),
                   ApiErrorId.ERR_MEDIA_PLAN_NOT_FOUND.value)
    validate_error(api.get_invoice(UNKNOWN_UUIDS[7], admin),
                   ApiErrorId.ERR_INVOICE_NOT_FOUND.value)
    validate_error(
        api.get_staff_utilization(UNKNOWN_UUIDS[8], admin,
                                  params={"period_start": "2026-06-01",
                                          "period_end": "2026-06-08"}),
        ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND.value,
    )


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------


def test_a_stale_media_plan_version_blocks_the_insertion_order(api):
    """PRD §2.7: "The first guard sits on insertion-order creation. The request must carry
    `expected_media_plan_version`, holding the `version` of the target `MediaPlan` as the client
    last read it. If that value does not equal the plan's current `version`, the create is
    rejected with `ERR_STALE_MEDIA_PLAN_VERSION` (HTTP 412) and no budget is committed."
    PRD §3.7: "An accepted order is created in `RESERVED`, and the plan's `uncommitted_cents` is
    reduced by the order's `gross_cents`; the plan's `version` moves with it."

    Design: Corner/cross_cutting_layers/insertion_order_create_with_stale_media_plan_version_returns_412
    """
    base = setup_base()
    first_slot = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
    second_slot = register_placement(publisher_name="TubeCo", channel="VIDEO", min_dark_days=0)
    plan = setup_media_plan(base, approve=True, approved_budget_cents=10_000_000,
                            allowed_channels=["VIDEO"])
    observed_version = plan["version"]
    assert observed_version == 2, "create (v1) then approve (v2)"

    reserve_insertion_order(
        base, plan["id"], first_slot["id"], expected_version=observed_version,
        flight_start="2026-06-05", flight_end="2026-06-20", gross_cents=1_000_000,
    )
    moved_on = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert moved_on["version"] == 3
    assert moved_on["uncommitted_cents"] == 9_000_000

    # The buyer is still holding the version they read before the first order landed.
    resp = api.create_insertion_order(
        create_insertion_order_payload(
            plan["id"], second_slot["id"], observed_version,
            flight_start="2026-06-05", flight_end="2026-06-20", gross_cents=2_000_000,
        ),
        base["mia_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_MEDIA_PLAN_VERSION.value)
    assert resp.status_code == 412

    after = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert after["uncommitted_cents"] == 9_000_000, "the rejected create committed nothing"


def test_a_stale_retainer_version_blocks_the_invoice_issue(api):
    """PRD §2.7: "The second guard sits on invoice issue. The request must carry
    `expected_retainer_version`, holding the `version` of the `Retainer` that the invoice draws
    down, as the client last read it. If that value does not equal the retainer's current
    `version`, the issue is rejected with `ERR_STALE_RETAINER_VERSION` (HTTP 412) and no cash
    moves."
    PRD §3.1: "Topping the retainer up adds the supplied `amount_cents` to both figures."

    Design: Corner/cross_cutting_layers/invoice_issue_with_stale_retainer_version_returns_412
    """
    base = setup_base(retainer_funding=5_000_000)
    setup_approved_senior_hour(base)
    invoice = assemble_invoice(base, billing_mode="FINAL")

    stale_version = retainer_version(base["retainer_id"])
    assert stale_version == 1

    funded = validate_success(api.fund_retainer(
        base["retainer_id"], {"amount_cents": 100_000}, base["admin_headers"]))
    assert funded["version"] == 2
    assert funded["balance_cents"] == 5_100_000

    resp = api.issue_invoice(
        invoice["id"], {"expected_retainer_version": stale_version}, base["admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_STALE_RETAINER_VERSION.value)
    assert resp.status_code == 412

    still_draft = validate_success(api.get_invoice(invoice["id"], base["admin_headers"]))
    assert still_draft["approval_status"] == "DRAFT"
    assert validate_success(
        api.get_retainer(base["retainer_id"], base["admin_headers"]))["balance_cents"] == 5_100_000

    issued = validate_success(api.issue_invoice(
        invoice["id"], {"expected_retainer_version": funded["version"]}, base["admin_headers"]))
    assert issued["approval_status"] == "ISSUED"
    assert issued["retainer_applied_cents"] == 20_600
    assert validate_success(
        api.get_retainer(base["retainer_id"], base["admin_headers"]))["balance_cents"] == 5_079_400
