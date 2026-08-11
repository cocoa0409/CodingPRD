"""Permits and municipal notification, documentation package lifecycle, and the
provisional/final invoicing pipeline with all of its submission gates."""
import pytest

from test_helpers import (
    add_artifact,
    api_client,
    approve_permit,
    assert_invoice_invariants,
    assert_same_instant,
    create_invoice,
    create_package,
    create_paid_invoice,
    create_service,
    deactivate_service,
    file_permit_case,
    get_job,
    get_package,
    intake_job,
    make_customer_headers,
    make_subcontractor_headers,
    open_permit_case,
    pay_invoice,
    record_permit_decision,
    record_removal,
    schedule_visit,
    set_clock,
    setup_billing_ready,
    setup_complete_package,
    setup_network,
    setup_on_site_job,
    setup_removed_job,
    setup_secured_job,
    submit_invoice,
    validate_error,
    validate_paginated,
    validate_success,
    verify_repair,
)


def test_permit_open_case_uniqueness_rejected(api, dispatcher_headers):
    """PRD §3.7: "Only one open case of each kind may exist per job — where open
    means `PENDING`, and additionally `FILED` for a permit awaiting a decision —
    and a second open case of the same kind is rejected with
    `ERR_PERMIT_CASE_OPEN`."

    Design: Corner/state_machines/permit_open_case_uniqueness_rejected
    """
    net = setup_network(num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    first = open_permit_case(job["id"], "PERMIT")
    assert first["status"] == "PENDING"

    res = api.create_permit_case(job["id"], {"kind": "PERMIT"}, dispatcher_headers)
    validate_error(res, "ERR_PERMIT_CASE_OPEN")

    cases, meta = validate_paginated(api.list_permit_cases(job["id"], dispatcher_headers))
    assert meta["total_count"] == 1, "only one open case of the kind may exist"


def test_permit_rejected_allows_replacement_case(api, dispatcher_headers):
    """PRD §3.7: "A `REJECTED` permit is terminal for that case, but not for the
    job: once no open case of that kind remains, the dispatcher may open a
    replacement permit case."

    Design: Corner/state_machines/permit_rejected_allows_replacement_case
    """
    net = setup_network(num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    first = open_permit_case(job["id"], "PERMIT")
    file_permit_case(first["id"], "SEA-P-100")
    decided = record_permit_decision(first["id"], "REJECTED", decision_note="facade too fragile")
    assert decided["status"] == "REJECTED"

    replacement = open_permit_case(job["id"], "PERMIT")
    assert replacement["status"] == "PENDING"
    assert replacement["id"] != first["id"]


def test_notification_late_filing_penalty_billed(api, dispatcher_headers):
    """PRD §3.7: "A late filing is not a dead end: filing late clears the job's
    `compliance_breach` latch, but the market's `late_notification_fee_cents`
    remains billable, because the case's `penalty_billed` flag stays false until
    an invoice actually bills it (§3.8)."
    PRD §3.8: "Fourth, `penalty_cents`: the market's `late_notification_fee_cents`
    whenever the job carries a late-`FILED` notification whose penalty has not yet
    been billed — billing it here flips that case's `penalty_billed` to true, so
    the penalty lands exactly once, on the first invoice created after the late
    filing — and zero otherwise."

    Design: Corner/state_machines/notification_late_filing_penalty_billed
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")  # work: 1 sheet = 4500
    first = open_permit_case(ctx["job"]["id"], "NOTIFICATION")
    assert_same_instant(first["deadline_at"], "2026-05-02T00:00:00Z"), "secured_at + 24h"

    set_clock("2026-05-02T01:00:00Z")  # one hour past the deadline: sweep expires it
    assert get_job(ctx["job"]["id"])["compliance_breach"] is True

    expired = validate_success(
        api.list_permit_cases(ctx["job"]["id"], dispatcher_headers), 200)[0]
    assert expired["status"] == "EXPIRED"

    # Replacement case (the first is terminal), filed late against the same deadline.
    second = open_permit_case(ctx["job"]["id"], "NOTIFICATION")
    filed = file_permit_case(second["id"], "SEA-N-100")
    assert filed["is_late"] is True
    assert get_job(ctx["job"]["id"])["compliance_breach"] is False, (
        "the late filing clears the breach latch")

    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    assert_invoice_invariants(invoice)
    assert invoice["penalty_cents"] == 15000, "late fee bills on the first invoice after filing"
    assert invoice["total_cents"] == 19500, "work 4500 + penalty 15000, no discount tier"

    cases, _ = validate_paginated(api.list_permit_cases(ctx["job"]["id"], dispatcher_headers))
    second_after = next(c for c in cases if c["id"] == second["id"])
    assert second_after["penalty_billed"] is True, "billed exactly once"


def test_notification_pending_submit_rejected(api, dispatcher_headers):
    """PRD §3.8: "In a market whose `notification_required` is set, no
    notification case may still be `PENDING` (`ERR_NOTIFICATION_PENDING` —
    consulting the case at this point may lazily expire it first), and the job's
    `compliance_breach` latch must be clear (`ERR_NOTIFICATION_DEADLINE_EXPIRED`)."

    Design: Corner/endpoints/notification_pending_submit_rejected
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    approve_permit(ctx, "SEA-P-200")
    setup_complete_package(ctx)
    notification = open_permit_case(ctx["job"]["id"], "NOTIFICATION")
    assert notification["status"] == "PENDING"  # deadline not yet reached at default clock

    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    res = api.submit_invoice(invoice["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_NOTIFICATION_PENDING")
    after = validate_success(api.get_invoice(invoice["id"], dispatcher_headers), 200)
    assert after["status"] == "DRAFT"


def test_package_auto_complete_threshold_crossing(api, dispatcher_headers):
    """PRD §3.8: "The package is born `INCOMPLETE` and promotes itself
    automatically to `COMPLETE` the moment all three conditions hold: the
    authorization is signed, the measurement sheet is recorded, and `photo_count`
    is at least `required_photo_count` — exactly meeting the photo requirement is
    sufficient."
    PRD §3.8: "Alongside them sits `required_photo_count`, twice the number of the
    job's scope items currently in `INSTALLED` status, recomputed whenever a scope
    item is installed or voided."

    Design: Corner/state_machines/package_auto_complete_threshold_crossing
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")  # 1 installed item
    pkg = create_package(ctx["job"]["id"])
    assert pkg["required_photo_count"] == 2
    assert pkg["status"] == "INCOMPLETE"

    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "PHOTO")
    assert pkg["status"] == "INCOMPLETE", "1 photo short of the requirement"
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "PHOTO")
    assert pkg["status"] == "INCOMPLETE", "photos alone do not complete the package"
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "AUTHORIZATION")
    assert pkg["status"] == "INCOMPLETE", "measurement sheet still missing"
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "MEASUREMENT_SHEET")
    assert pkg["status"] == "COMPLETE", "all three conditions met exactly at the final artifact"
    assert pkg["photo_count"] == 2
    assert pkg["authorization_signed"] is True
    assert pkg["measurement_sheet_recorded"] is True


def test_package_locked_artifacts_rejected(api, dispatcher_headers):
    """PRD §3.8: "Artifacts are accepted only while the package is unlocked —
    once `LOCKED`, adds fail with `ERR_PACKAGE_LOCKED` — and each accepted
    artifact advances the package's `version` by one."

    Design: Corner/endpoints/package_locked_artifacts_rejected
    """
    ctx = setup_secured_job(priority="P3", market_preset="PDX", incident_type="FIRE")
    setup_complete_package(ctx)
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    submit_invoice(invoice["id"])

    pkg = get_package(ctx["job"]["id"])
    assert pkg["status"] == "LOCKED"
    # Even with the current OCC version, the lock gate fires.
    res = api.add_artifact(
        pkg["id"],
        {"kind": "PHOTO", "expected_package_version": pkg["version"]},
        dispatcher_headers)
    validate_error(res, "ERR_PACKAGE_LOCKED")


def test_occ_stale_version_artifact_add_rejected(api, dispatcher_headers):
    """PRD §2.9: "The request must carry `expected_package_version`, holding the
    `version` of the `DocumentPackage` as the client last observed it. Each
    artifact addition advances the package's `version`, so a mismatch means the
    client's view of the package's completeness is stale; the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_artifact_add_rejected
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    pkg = create_package(ctx["job"]["id"])
    stale_version = pkg["version"]

    res = api.add_artifact(pkg["id"], {"kind": "PHOTO", "expected_package_version": stale_version},
                           dispatcher_headers)
    validate_success(res, 200)

    res = api.add_artifact(pkg["id"], {"kind": "PHOTO", "expected_package_version": stale_version},
                           dispatcher_headers)
    validate_error(res, "ERR_STALE_VERSION")
    pkg_after = get_package(ctx["job"]["id"])
    assert pkg_after["photo_count"] == 1, "the stale writer's artifact must not land"


def test_invoice_variant_gating(api, dispatcher_headers):
    """PRD §3.8: "a `PROVISIONAL` requires the job to be `SECURED` and exists for
    insurance pre-authorization; a `FINAL` requires the job to be `REMOVED` and an
    existing `PROVISIONAL` invoice to serve as the variance baseline; any other
    combination is rejected with `ERR_INVOICE_VARIANT_INVALID`."

    Design: Corner/calculations/invoice_variant_gating
    """
    ctx = setup_on_site_job(priority="P3", market_preset="PDX", with_assessment=True)
    assert ctx["job"]["work_status"] == "ON_SITE"

    res = api.create_invoice(ctx["job"]["id"], {"variant": "PROVISIONAL"}, dispatcher_headers)
    validate_error(res, "ERR_INVOICE_VARIANT_INVALID")

    res = api.create_invoice(ctx["job"]["id"], {"variant": "FINAL"}, dispatcher_headers)
    validate_error(res, "ERR_INVOICE_VARIANT_INVALID")


def test_uniqueness_constraint_error_family(api, dispatcher_headers, admin_headers):
    """PRD §3.1: "A coverage row for a pair that already exists is rejected with
    `ERR_DUPLICATE_COVERAGE`."
    PRD §3.8: "a second attempt is rejected with `ERR_DUPLICATE_PACKAGE` — created
    by a `Dispatcher` once the job has reached `SECURED` or any later state."
    PRD §3.8: "Only one open invoice — one in `DRAFT`, `SUBMITTED`, or `DISPUTED`
    — may exist per job at a time (`ERR_INVOICE_OPEN_EXISTS`)."

    Design: Corner/endpoints/uniqueness_constraint_error_family
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    create_package(ctx["job"]["id"])
    create_invoice(ctx["job"]["id"], "PROVISIONAL")  # stays DRAFT (open)

    res = api.create_coverage(
        {"subcontractor_id": ctx["assignee"]["id"], "market_id": ctx["market"]["id"],
         "max_concurrent_jobs": 5, "rank": 9},
        admin_headers)
    validate_error(res, "ERR_DUPLICATE_COVERAGE")

    res = api.create_document_package(ctx["job"]["id"], dispatcher_headers)
    validate_error(res, "ERR_DUPLICATE_PACKAGE")

    res = api.create_invoice(ctx["job"]["id"], {"variant": "PROVISIONAL"}, dispatcher_headers)
    validate_error(res, "ERR_INVOICE_OPEN_EXISTS")


def test_invoice_submit_blocked_by_incomplete_package(api, dispatcher_headers):
    """PRD §3.8: "The job's document package must have reached completeness at
    least once — a package in `COMPLETE`, `LOCKED`, or `AMENDED` passes, and only
    a still-`INCOMPLETE` package fails with `ERR_DOCS_INCOMPLETE`."
    PRD §3.8: "A successful submission moves the invoice `DRAFT` → `SUBMITTED`
    (or, on resubmission, `DISPUTED` → `SUBMITTED`, re-running the identical gate
    set), stamps `submitted_at`, and locks the package (`COMPLETE` → `LOCKED`, or
    `AMENDED` → `LOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_by_package_and_permit
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")  # 1 installed -> 2 photos required
    approve_permit(ctx, "SEA-P-004")
    pkg = create_package(ctx["job"]["id"])
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "PHOTO")  # 1 of 2 photos: INCOMPLETE
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")

    res = api.submit_invoice(invoice["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_DOCS_INCOMPLETE")

    add_artifact(ctx["job"]["id"], pkg["id"], "PHOTO")
    add_artifact(ctx["job"]["id"], pkg["id"], "AUTHORIZATION")
    pkg = add_artifact(ctx["job"]["id"], pkg["id"], "MEASUREMENT_SHEET")
    assert pkg["status"] == "COMPLETE"

    submitted = submit_invoice(invoice["id"])
    assert submitted["status"] == "SUBMITTED"
    assert get_package(ctx["job"]["id"])["status"] == "LOCKED", (
        "the DRAFT -> SUBMITTED transition locks the package")


def test_invoice_submit_blocked_by_unapproved_permit(api, dispatcher_headers):
    """PRD §3.8: "In a market whose `permit_required` is set, an `APPROVED` permit
    case must exist on the job, else `ERR_PERMIT_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_by_package_and_permit
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    setup_complete_package(ctx)  # documentation gate satisfied
    open_permit_case(ctx["job"]["id"], "PERMIT")  # PENDING, never filed
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")

    res = api.submit_invoice(invoice["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_PERMIT_NOT_APPROVED")
    after = validate_success(api.get_invoice(invoice["id"], dispatcher_headers), 200)
    assert after["status"] == "DRAFT"


def test_permit_gate_precedes_docs_gate(api, dispatcher_headers):
    """PRD §2.7: "(iii) an approved permit before invoice submission in permit
    jurisdictions (`ERR_PERMIT_NOT_APPROVED`); (iv) the documentation package
    having reached completeness at least once before invoice submission
    (`ERR_DOCS_INCOMPLETE`)"

    Design: Corner/validations/permit_gate_precedes_docs_gate
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    open_permit_case(ctx["job"]["id"], "PERMIT")  # PENDING: permit gate fails
    create_package(ctx["job"]["id"])  # empty: docs gate also fails
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")

    res = api.submit_invoice(invoice["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_PERMIT_NOT_APPROVED")
    assert res.json()["data"]["error_id"] != "ERR_DOCS_INCOMPLETE", (
        "the permit sub-gate must mask the documentation sub-gate")


def test_invoice_dispute_resubmit_cycle(api, dispatcher_headers):
    """PRD §3.8: "The owning customer — `X-User-ID` must equal the job's
    `customer_id`, else `ERR_FORBIDDEN` — may dispute a submitted invoice,
    optionally supplying a `reason`; this moves the invoice `SUBMITTED` →
    `DISPUTED` and unlocks the package as `AMENDED`."
    PRD §3.8: "Payment is recorded by a `Dispatcher` against a submitted invoice,
    moving it `SUBMITTED` → `PAID` and stamping `paid_at`. `PAID` is terminal."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
    """
    ctx = setup_secured_job(priority="P3", market_preset="PDX", incident_type="FIRE")
    setup_complete_package(ctx)
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    assert invoice["total_cents"] == 4000, "1 sheet x 4000 at the P3 multiplier 1.00"

    submitted = submit_invoice(invoice["id"])
    assert submitted["status"] == "SUBMITTED"

    disputed = validate_success(
        api.dispute_invoice(invoice["id"], {"reason": "quantity mismatch"},
                            make_customer_headers(ctx["customer"]["id"])), 200)
    assert disputed["status"] == "DISPUTED"

    resubmitted = submit_invoice(invoice["id"])
    assert resubmitted["status"] == "SUBMITTED", "resubmission re-runs the identical gate set"

    paid = pay_invoice(invoice["id"])
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None


def test_package_locks_and_amends_with_invoice_cycle(api, dispatcher_headers):
    """PRD §3.8: "The package's remaining lifecycle is slaved to billing: when an
    invoice of the parent job is submitted, the package moves `COMPLETE` →
    `LOCKED`; when that submitted invoice is disputed, it moves `LOCKED` →
    `AMENDED`, reopening it for corrective artifacts; and on resubmission it locks
    again, `AMENDED` → `LOCKED`."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
    """
    ctx = setup_secured_job(priority="P3", market_preset="PDX", incident_type="FIRE")
    setup_complete_package(ctx)
    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")

    submit_invoice(invoice["id"])
    assert get_package(ctx["job"]["id"])["status"] == "LOCKED"

    api.dispute_invoice(invoice["id"], {"reason": "quantity mismatch"},
                        make_customer_headers(ctx["customer"]["id"]))
    assert get_package(ctx["job"]["id"])["status"] == "AMENDED"

    submit_invoice(invoice["id"])
    assert get_package(ctx["job"]["id"])["status"] == "LOCKED"


def test_variance_cap_exceeded_then_override(api, dispatcher_headers):
    """PRD §3.8: "Finally, for a `FINAL` invoice, its `work_subtotal_cents` may
    not exceed 120% of the provisional invoice's `work_subtotal_cents` — the
    provisional subtotal multiplied by 1.20 and rounded half up — unless the
    dispatcher supplies `variance_override` as true, else
    `ERR_VARIANCE_CAP_EXCEEDED`."

    Design: Corner/calculations/variance_cap_exceeded_then_override
    """
    # Planned: 1 opening of 48x36in -> 1 sheet -> work 4000 (cap 4800).
    # Installed: 3 openings -> 36 sqft -> 2 sheets -> work 8000, over the cap.
    ctx = setup_removed_job(
        priority="P3", market_preset="PDX",
        scope_specs=[{"kind": "BOARD", "opening_count": 1, "width_in": 48,
                      "height_in": 36, "door_count": 0}],
        install_specs=[{"opening_count": 3, "width_in": 48, "height_in": 36, "door_count": 0}],
    )
    assert ctx["provisional_invoice"]["work_subtotal_cents"] == 4000

    final = create_invoice(ctx["job"]["id"], "FINAL")
    assert final["work_subtotal_cents"] == 8000

    res = api.submit_invoice(final["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_VARIANCE_CAP_EXCEEDED")

    submitted = submit_invoice(final["id"], variance_override=True)
    assert submitted["status"] == "SUBMITTED"
    assert_invoice_invariants(submitted)
    assert submitted["total_cents"] == 33000, "work 8000 + removal 25000, tier 0"


def test_discount_tier_evaluation_order(api, dispatcher_headers):
    """PRD §3.8: "Fifth, the volume tier is looked up on that pre-discount total:
    at least 500,000 cents ($5,000.00) earns a 10% discount rate; at least 200,000
    cents ($2,000.00) but below that earns 5%; below that, no discount."
    PRD §3.8: "Sixth, `discount_cents` is the `work_subtotal_cents` multiplied by
    the tier percentage, rounded half up to whole cents — note the discount keys
    off the work subtotal even though the tier is keyed on the pre-discount total."

    Design: Difficulty/combinatorial_formula/discount_tier_evaluation_order
    """
    # 82 openings of 48x48in = 1312 sqft -> ceil(1312/32) = 41 sheets exactly.
    ctx = setup_secured_job(
        priority="P2", market_preset="PDX", incident_type="VANDALISM",
        scope_specs=[{"kind": "BOARD", "opening_count": 82, "width_in": 48,
                      "height_in": 48, "door_count": 0}],
    )
    assert ctx["scope_items"][0]["planned_qty"] == 41

    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    assert_invoice_invariants(invoice)
    assert invoice["work_subtotal_cents"] == 205000, "41 x 4000 x 1.25"
    assert invoice["pre_discount_total_cents"] == 205000
    # Tier keyed on the PRE-discount 205000 (>= 200000 -> 5%); the post-discount
    # total 194750 falls below 200000, so a post-discount-keyed tier gives 205000.
    assert invoice["discount_cents"] == 10250
    assert invoice["total_cents"] == 194750


def test_discount_tier_boundary_at_2000_dollars(api, dispatcher_headers):
    """PRD §3.8: "Fifth, the volume tier is looked up on that pre-discount total:
    at least 500,000 cents ($5,000.00) earns a 10% discount rate; at least 200,000
    cents ($2,000.00) but below that earns 5%; below that, no discount."

    Design: Difficulty/combinatorial_formula/discount_tier_evaluation_order
    """
    # 80 openings of 48x48in = 1280 sqft -> 40 sheets -> work exactly 200000:
    # the inclusive lower bound of the 5% tier.
    ctx = setup_secured_job(
        priority="P2", market_preset="PDX", incident_type="VANDALISM",
        scope_specs=[{"kind": "BOARD", "opening_count": 80, "width_in": 48,
                      "height_in": 48, "door_count": 0}],
    )
    assert ctx["scope_items"][0]["planned_qty"] == 40

    invoice = create_invoice(ctx["job"]["id"], "PROVISIONAL")
    assert_invoice_invariants(invoice)
    assert invoice["work_subtotal_cents"] == 200000
    assert invoice["pre_discount_total_cents"] == 200000
    assert invoice["discount_cents"] == 10000, "exactly 200000 earns the 5% tier"
    assert invoice["total_cents"] == 190000


def _setup_patrol_billing_job():
    """SEA P2 job SECURED with 1 installed BOARD item; permit approved; package
    COMPLETE; notification filed on time; provisional invoice PAID; a PATROL
    service with three visits, each checked in on its own day."""
    ctx = setup_secured_job(priority="P2", incident_type="STORM")
    setup_billing_ready(ctx)
    ctx["provisional_invoice"] = create_paid_invoice(ctx, "PROVISIONAL")

    svc = create_service(ctx["job"]["id"], "PATROL",
                         "2026-05-02T08:00:00Z", "2026-05-05T08:00:00Z")
    visits = []
    for day in ("2026-05-02", "2026-05-03", "2026-05-04"):
        visits.append(schedule_visit(svc["id"], f"{day}T08:00:00Z", f"{day}T20:00:00Z"))
    for day, visit in zip(("2026-05-02", "2026-05-03", "2026-05-04"), visits):
        set_clock(f"{day}T12:00:00Z")
        res = validate_success(
            api_client.check_in_patrol_visit(
                visit["id"], {"outcome": "CHECKED_IN"},
                make_subcontractor_headers(ctx["assignee"]["id"])), 200)
        assert res["status"] == "CHECKED_IN"
    ctx["patrol_service"] = svc
    ctx["visits"] = visits
    return ctx


def test_patrol_fee_per_visit_rounding(api, dispatcher_headers):
    """PRD §3.6: "At creation each visit is priced: its `fee_cents` is the
    market's `patrol_visit_fee_cents` multiplied by the parent job's priority
    multiplier (§3.8), rounded half up to whole cents, per visit, before any
    summation."
    PRD §3.8: "the job's priority multiplier — 1.50 for `P1`, 1.25 for `P2`, 1.00
    for `P3`"

    Design: Difficulty/combinatorial_formula/patrol_fee_per_visit_rounding_order
    """
    ctx = _setup_patrol_billing_job()
    for visit in ctx["visits"]:
        # round_half_up(7499 * 1.25) = round_half_up(9373.75) = 9374 per visit.
        assert visit["fee_cents"] == 9374


def test_patrol_fee_invoice_sum_of_rounded_visits(api, dispatcher_headers):
    """PRD §2.8: "invoice work lines are each rounded to whole cents first and
    only then summed into the work subtotal, and patrol fees are rounded per
    visit at creation and only then summed onto a final invoice — rounding after
    summation produces a different number and is incorrect."
    PRD §3.8: "Second, the `service_subtotal_cents`: on a final invoice, the
    `service_total_cents` of every `COMPLETED` power or lighting service plus the
    sum of the per-visit `fee_cents` of all patrol visits in a terminal state
    (`CHECKED_IN` or `MISSED`); on a provisional invoice it is zero."

    Design: Difficulty/combinatorial_formula/patrol_fee_per_visit_rounding_order
    """
    ctx = _setup_patrol_billing_job()
    assert ctx["provisional_invoice"]["total_cents"] == 5625, (
        "1 sheet at 4500 with the P2 multiplier 1.25")

    verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    deactivate_service(ctx["patrol_service"]["id"])
    record_removal(ctx["job"]["id"], ctx["assignee"]["id"])

    final = create_invoice(ctx["job"]["id"], "FINAL")
    assert_invoice_invariants(final)
    assert final["work_subtotal_cents"] == 5625, "installed actuals match the plan here"
    assert final["service_subtotal_cents"] == 28122, (
        "3 x 9374 summed after per-visit rounding; sum-then-round would give 28121")
    assert final["removal_fee_cents"] == 25000
    assert final["total_cents"] == 58747


def _setup_divergence_job():
    """SEA P2 job: BOARD planned 4x(48x36in) installed 6 openings; TARP planned
    10x15ft installed 10x16ft; FENCE planned 40ft installed 42ft; permit approved;
    package COMPLETE; notification filed on time; provisional PAID; job REMOVED."""
    ctx = setup_secured_job(
        priority="P2", incident_type="STORM",
        scope_specs=[
            {"kind": "BOARD", "opening_count": 4, "width_in": 48, "height_in": 36,
             "door_count": 0},
            {"kind": "TARP", "length_ft": 10, "width_ft": 15},
            {"kind": "FENCE", "linear_ft": 40},
        ],
        install_specs=[
            {"opening_count": 6, "width_in": 48, "height_in": 36, "door_count": 0},
            {"length_ft": 10, "width_ft": 16},
            {"linear_ft": 42},
        ],
    )
    setup_billing_ready(ctx)
    ctx["provisional_invoice"] = create_paid_invoice(ctx, "PROVISIONAL")
    verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    record_removal(ctx["job"]["id"], ctx["assignee"]["id"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def test_invoice_provisional_totals(api, dispatcher_headers):
    """PRD §3.8: "First, the work lines: a provisional invoice bills every scope
    item not in `VOIDED` status at its `planned_qty`, while a final invoice bills
    only `INSTALLED` items at their `actual_qty`."
    PRD §3.8: "Third, `removal_fee_cents`: the market's `removal_flat_fee_cents`
    on a final invoice, zero on a provisional."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
    """
    ctx = _setup_divergence_job()
    prov = ctx["provisional_invoice"]
    assert_invoice_invariants(prov)
    # BOARD 2 sheets x 4500 x 1.25 = 11250; TARP 188 sqft x 85 x 1.25 = 19975;
    # FENCE 40 ft x 1200 x 1.25 = 60000.
    assert prov["work_subtotal_cents"] == 91225
    assert prov["service_subtotal_cents"] == 0
    assert prov["removal_fee_cents"] == 0
    assert prov["pre_discount_total_cents"] == 91225
    assert prov["discount_cents"] == 0
    assert prov["total_cents"] == 91225


def test_invoice_final_diverges_from_provisional(api, dispatcher_headers):
    """PRD §3.8: "First, the work lines: a provisional invoice bills every scope
    item not in `VOIDED` status at its `planned_qty`, while a final invoice bills
    only `INSTALLED` items at their `actual_qty`."
    PRD §3.8: "Third, `removal_fee_cents`: the market's `removal_flat_fee_cents`
    on a final invoice, zero on a provisional."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
    """
    ctx = _setup_divergence_job()
    final = create_invoice(ctx["job"]["id"], "FINAL")
    assert_invoice_invariants(final)
    # Actuals: BOARD 6 openings -> 3 sheets x 4500 x 1.25 = 16875;
    # TARP 200 sqft x 85 x 1.25 = 21250; FENCE 42 ft x 1200 x 1.25 = 63000.
    assert final["work_subtotal_cents"] == 101125
    assert final["removal_fee_cents"] == 25000
    assert final["pre_discount_total_cents"] == 126125
    assert final["discount_cents"] == 0, "126125 is below the 200000 tier floor"
    assert final["total_cents"] == 126125
    assert final["total_cents"] != ctx["provisional_invoice"]["total_cents"], (
        "same job, two variants, divergent totals")


def _setup_temporal_vs_fiscal_job(install_over_plan=False):
    """SEA P3 job: planned BOARD 2 openings 48x36in (1 sheet, work 4500); permit
    APPROVED; package COMPLETE; provisional PAID; NOTIFICATION case left unfiled
    and swept to EXPIRED 25h after securing; job REMOVED; FINAL DRAFT.
    install_over_plan=True installs 5 openings (2 sheets, work 9000 > 5400 cap)."""
    install = ({"opening_count": 5, "width_in": 48, "height_in": 36, "door_count": 0}
               if install_over_plan else
               {"opening_count": 2, "width_in": 48, "height_in": 36, "door_count": 0})
    ctx = setup_secured_job(
        priority="P3", incident_type="FIRE",
        scope_specs=[{"kind": "BOARD", "opening_count": 2, "width_in": 48,
                      "height_in": 36, "door_count": 0}],
        install_specs=[install],
    )
    approve_permit(ctx, "SEA-P-003")
    setup_complete_package(ctx)
    ctx["provisional_invoice"] = create_paid_invoice(ctx, "PROVISIONAL")
    ctx["notification_case"] = open_permit_case(ctx["job"]["id"], "NOTIFICATION")
    set_clock("2026-05-02T01:00:00Z")  # 25h past secured_at: sweep expires the case
    verify_repair(ctx["job"]["id"], ctx["customer"]["id"], "VERIFIED")
    record_removal(ctx["job"]["id"], ctx["assignee"]["id"])
    ctx["final_invoice"] = create_invoice(ctx["job"]["id"], "FINAL")
    return ctx


def test_submit_temporal_failure_beats_fiscal(api, dispatcher_headers):
    """PRD §3.8: "Submission is the gate-laden step, and the gates run in the
    validation precedence of §2.7 — safety and regulatory before temporal before
    fiscal."
    PRD §2.7: "invoice submission blocked while a required notification is still
    pending (`ERR_NOTIFICATION_PENDING`) or lapsed unfiled
    (`ERR_NOTIFICATION_DEADLINE_EXPIRED`)"
    PRD §2.7: "the final-invoice variance cap (`ERR_VARIANCE_CAP_EXCEEDED`) and
    the all-invoices-paid precondition of job closure (`ERR_INVOICES_UNPAID`)."

    Design: Difficulty/priority_pair_validation_conflict/submit_temporal_failure_beats_fiscal
    """
    ctx = _setup_temporal_vs_fiscal_job(install_over_plan=True)
    assert ctx["final_invoice"]["work_subtotal_cents"] == 9000, (
        "variance over the 4500 provisional exceeds the 5400 cap: fiscal failure armed")

    cases, _ = validate_paginated(api.list_permit_cases(ctx["job"]["id"], dispatcher_headers))
    notification = next(c for c in cases if c["kind"] == "NOTIFICATION")
    assert notification["status"] == "EXPIRED", "temporal failure armed"

    res = api.submit_invoice(ctx["final_invoice"]["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_NOTIFICATION_DEADLINE_EXPIRED")
    assert res.json()["data"]["error_id"] != "ERR_VARIANCE_CAP_EXCEEDED", (
        "the temporal gate must mask the fiscal gate")


def test_notification_expired_alone_blocks_submit(api, dispatcher_headers):
    """PRD §3.8: "In a market whose `notification_required` is set, no
    notification case may still be `PENDING` (`ERR_NOTIFICATION_PENDING` —
    consulting the case at this point may lazily expire it first), and the job's
    `compliance_breach` latch must be clear (`ERR_NOTIFICATION_DEADLINE_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/submit_temporal_failure_beats_fiscal
    """
    # Installed actuals equal the plan (work 4500 <= 5400 cap): only the
    # expired-notification failure is armed.
    ctx = _setup_temporal_vs_fiscal_job(install_over_plan=False)
    assert ctx["final_invoice"]["work_subtotal_cents"] == 4500
    assert get_job(ctx["job"]["id"])["compliance_breach"] is True

    res = api.submit_invoice(ctx["final_invoice"]["id"], {}, dispatcher_headers)
    validate_error(res, "ERR_NOTIFICATION_DEADLINE_EXPIRED")
    after = validate_success(api.get_invoice(ctx["final_invoice"]["id"], dispatcher_headers), 200)
    assert after["status"] == "DRAFT"
