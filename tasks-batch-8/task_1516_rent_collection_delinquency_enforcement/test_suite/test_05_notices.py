"""Delinquency notices: drafting lifecycle fields, issuance/service gates,
closed-day coverage overlap, the supersede side effect, OCC on creation, and
the sweep's cure/expire verdicts."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    create_notice,
    create_notice_payload,
    issue_notice,
    lease_version,
    list_notices,
    post_payment,
    record_payment,
    run_sweep,
    serve_notice,
    set_clock,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_notice_serve_from_draft_rejected(api):
    """PRD 3.7: "Service documentation follows issuance: a `PropertyManager` records
    service on an `ISSUED` notice — serving from any other status is rejected with
    `ERR_NOTICE_INVALID_TRANSITION` — by supplying the statutory `service_method`, one
    of `PERSONAL`, `POSTED_AND_MAILED`, or `CERTIFIED_MAIL`, and the `served_date`."

    Design: Corner/state_machines/notice_serve_from_draft_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [charge["id"]])

    response = api.transition_notice(
        notice["id"], {"action": "SERVE", "service_method": "PERSONAL", "served_date": "2026-08-01"}, PM
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_INVALID_TRANSITION)


def test_notice_coverage_closed_day_overlap_adjacent_ok(api):
    """PRD 3.7: "Because only one open statutory demand may cover a given day, the
    closed-day coverage window of the issuing notice must not share a single calendar
    day with any other notice of the same lease in `ISSUED` or `SERVED` status; an
    overlap is rejected with `ERR_NOTICE_PERIOD_OVERLAP`."
    PRD 3.7: "The draft's coverage window is computed from the covered charges:
    `period_start_date` is the earliest covered charge's period start and
    `period_end_date` is the latest covered charge's period end, and the window is read
    as closed calendar days, both endpoints included."

    Design: Difficulty/resource_temporal_overlap/notice_coverage_closed_day_overlap
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent_aug = add_charge(lease_id, amount_cents=200000)
    rent_sep = add_charge(
        lease_id, amount_cents=200000,
        period_start_date="2026-09-01", period_end_date="2026-09-30", due_date="2026-09-01",
    )
    n1 = create_notice(lease_id, [rent_aug["id"]])
    issued = issue_notice(n1["id"])
    assert issued["status"] == "ISSUED"

    n2 = create_notice(lease_id, [rent_sep["id"]])
    issued2 = issue_notice(n2["id"])
    assert issued2["status"] == "ISSUED", (
        "Coverage 2026-09-01..2026-09-30 shares no calendar day with 2026-08-01..2026-08-31"
    )


def test_notice_coverage_closed_day_overlap_rejected(api):
    """PRD 3.7: "Because only one open statutory demand may cover a given day, the
    closed-day coverage window of the issuing notice must not share a single calendar
    day with any other notice of the same lease in `ISSUED` or `SERVED` status; an
    overlap is rejected with `ERR_NOTICE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/notice_coverage_closed_day_overlap
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent_aug = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(
        lease_id, kind="DAMAGE_FEE", amount_cents=5000,
        period_start_date="2026-08-15", period_end_date="2026-09-15", due_date="2026-08-15",
    )
    n1 = create_notice(lease_id, [rent_aug["id"]])
    issue_notice(n1["id"])

    n3 = create_notice(lease_id, [damage["id"]])
    response = api.transition_notice(n3["id"], {"action": "ISSUE"}, PM)
    validate_error(response, ApiErrorId.ERR_NOTICE_PERIOD_OVERLAP)


def test_notice_cured_by_full_payment_before_deadline(api):
    """PRD 3.6: "The notice duty examines notices in `ISSUED` or `SERVED` status. A
    notice whose covered charges all show zero outstanding, while the current date is
    still on or before its `cure_deadline_date`, transitions to `CURED` — this holds
    whether the notice was merely `ISSUED` or already `SERVED`."
    PRD 3.7: "At issuance the demanded amount freezes forever at its issued value,
    `issued_date` is set to the current date, and `cure_deadline_date` becomes the
    issued date plus the property's `notice_cure_period_days`."

    Design: Corner/calculations/notice_cured_by_full_payment_before_deadline
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [charge["id"]])
    issued = issue_notice(notice["id"])
    assert issued["cure_deadline_date"] == "2026-08-11", (
        f"issued 2026-08-01 + 10 days must read 2026-08-11, got {issued['cure_deadline_date']!r}"
    )

    set_clock("2026-08-05T00:00:00Z")
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=200000, received_date="2026-08-05")
    post_payment(payment["id"])

    report = run_sweep()
    assert report["notices_cured_count"] == 1
    assert report["late_fees_assessed_count"] == 0
    listed = list_notices(lease_id)
    assert listed[0]["status"] == "CURED"
    assert listed[0]["amount_demanded_cents"] == 204000, "The demand freezes at its issued value"


def test_notice_expires_after_cure_deadline(api):
    """PRD 3.6: "A notice whose `cure_deadline_date` has passed with any covered
    charge still showing a positive outstanding balance transitions to `EXPIRED`, again
    from either `ISSUED` or `SERVED`."

    Design: Corner/calculations/notice_expires_after_cure_deadline
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [charge["id"]])
    issue_notice(notice["id"])

    set_clock("2026-08-11T00:00:00Z")
    report1 = run_sweep()
    assert report1["notices_expired_count"] == 0, (
        "2026-08-11 is the deadline itself; today <= cure_deadline_date keeps the notice alive"
    )

    set_clock("2026-08-12T00:00:00Z")
    report2 = run_sweep()
    assert report2["notices_expired_count"] == 1
    listed = list_notices(lease_id)
    assert listed[0]["status"] == "EXPIRED"


def test_serve_date_window_inclusive_boundary(api):
    """PRD 3.7: "The served date must satisfy the full window from `issued_date`
    through `cure_deadline_date`, inclusive at both ends; a date outside that window is
    rejected with `ERR_NOTICE_SERVICE_WINDOW`."

    Design: Corner/validations/serve_date_window_inclusive_boundary
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent_aug = add_charge(lease_id, amount_cents=200000)
    rent_sep = add_charge(
        lease_id, amount_cents=200000,
        period_start_date="2026-09-01", period_end_date="2026-09-30", due_date="2026-09-01",
    )
    n1 = create_notice(lease_id, [rent_aug["id"]])
    issue_notice(n1["id"])

    set_clock("2026-08-11T00:00:00Z")
    n2 = create_notice(lease_id, [rent_sep["id"]])
    issue_notice(n2["id"])

    served = serve_notice(n1["id"], "POSTED_AND_MAILED", "2026-08-11")
    assert served["status"] == "SERVED", "Service on the cure deadline day is allowed (inclusive upper bound)"

    response = api.transition_notice(
        n2["id"], {"action": "SERVE", "service_method": "CERTIFIED_MAIL", "served_date": "2026-08-22"}, PM
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_SERVICE_WINDOW)


def test_occ_notice_create_stale_version_rejected(api):
    """PRD 2.8: "Each of these creation requests must carry `expected_lease_version`,
    a non-optional field holding the `version` of the target lease as the client last
    observed it. If the lease's current `version` no longer matches — because another
    writer has advanced it since the client last read the lease — the creation is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.7: "Creating a notice cancels any existing `DRAFT` notice on the same lease
    — the older draft moves to `CANCELLED` with its `cancel_reason` set to `SUPERSEDED`
    — and the creation increments the lease's `version`, which is precisely the
    mutation the optimistic-concurrency guard exists to make observable."

    Design: Corner/cross_cutting_layers/occ_notice_create_stale_version_rejected
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)
    lv = lease_version(lease_id)

    first = validate_success(api.create_notice(create_notice_payload(lease_id, [charge["id"]], lv), PM), 201)
    assert first["status"] == "DRAFT"

    response = api.create_notice(create_notice_payload(lease_id, [charge["id"]], lv), PM)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    listed = list_notices(lease_id)
    assert len(listed) == 1
    assert listed[0]["status"] == "DRAFT", "The rejected creation must supersede nothing"


def test_supersede_cancels_existing_draft_notice(api):
    """PRD 3.7: "A lease carries at most one draft notice at a time. Creating a notice
    cancels any existing `DRAFT` notice on the same lease — the older draft moves to
    `CANCELLED` with its `cancel_reason` set to `SUPERSEDED` — and the creation
    increments the lease's `version`, which is precisely the mutation the
    optimistic-concurrency guard exists to make observable."

    Design: Corner/cross_cutting_layers/supersede_cancels_existing_draft_notice
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    charge = add_charge(lease_id, amount_cents=200000)

    lv = lease_version(lease_id)
    n1 = validate_success(api.create_notice(create_notice_payload(lease_id, [charge["id"]], lv), PM), 201)
    lv2 = lease_version(lease_id)
    assert lv2 == lv + 1, "Notice creation increments the lease version by exactly 1"
    n2 = validate_success(api.create_notice(create_notice_payload(lease_id, [charge["id"]], lv2), PM), 201)

    listed = {n["id"]: n for n in list_notices(lease_id)}
    assert len(listed) == 2
    assert listed[n1["id"]]["status"] == "CANCELLED"
    assert listed[n1["id"]]["cancel_reason"] == "SUPERSEDED"
    assert listed[n2["id"]]["status"] == "DRAFT"
    assert listed[n2["id"]]["cancel_reason"] is None
