"""
Endpoint surface: what a partial write touches, what an action pair splits between
its two halves, and what a projection reports when the window is empty.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_ELIGIBLE_TECHNICIAN,
    ERR_UNKNOWN_REFERENCE,
)
from test_helpers.assertions import (
    assert_axes,
    assert_cents,
    assert_equipment_ledger,
    assert_instant_equals,
    assert_lockout,
    assert_pct,
    assert_sweep_counters,
    assert_workload,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    AGREEMENT_ACTIVE,
    AGREEMENT_EXPIRED,
    AGREEMENT_RENEWAL_PENDING,
    BASIS_NAMEPLATE,
    CERT_L1,
    CERT_SANITATION,
    DECISION_REJECTED,
    DELIVERY_DELIVERED,
    DELIVERY_VOIDED,
    DISPENSER_LOCKED_OUT,
    DISPENSER_REMOVED,
    LOCKOUT_AGREEMENT_ENDED,
    OP_OFFLINE,
    OP_UP,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    PLACEMENT_RETRIEVED,
    REVIEW_DRAFT,
    SUSTAINABILITY_BASIS_RATED,
    TECH_AVAILABLE,
    TECH_OFF_DUTY,
    TICKET_DISPATCHED,
    TICKET_QUEUED,
    VISIT_REJECTED,
    VISIT_SCHEDULED,
)


def test_the_roster_update_is_partial_narrow_and_effective_at_once(api):
    """
    The one update endpoint in the API writes only the two roster fields: the first
    call records a certification without touching duty status and ignores the computed
    workload counter offered alongside it, the second takes the engineer off duty
    without undoing the certification, and each partial write costs one version. The
    change bites immediately — with the roster now empty of available engineers the
    only queued job cannot be dispatched, and the refusal mutates nothing.

    PRD §3.3: "The roster is editable in exactly two respects — a technician can be
    taken off duty or brought back, and a certification change can be recorded — so a
    roster update accepts only `status` and `certification_level`. The counters are
    computed and cannot be written. Taking a technician off duty or suspending them
    removes them from the dispatch candidate set immediately but leaves every visit
    already booked in their name untouched and still binding on the schedule."

    PRD §3.5: "When the candidate set comes out empty the request fails with
    `ERR_NO_ELIGIBLE_TECHNICIAN` and **nothing at all is mutated** — the ticket remains
    `QUEUED`, `assigned_technician_id` remains null and `escalation_level` is
    untouched."

    Design: Corner/endpoints/patching_a_technician_changes_the_roster_but_not_the_computed_counters
    """
    base = X.program_base(
        api, technician_overrides={"certification_level": CERT_L1}
    )
    assert base["technician"]["status"] == TECH_AVAILABLE
    assert base["technician"]["version"] == 1
    assert base["technician"]["certification_level"] == CERT_L1

    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    ticket = X.file_ticket(api, base, placement["id"])
    assert ticket["status"] == TICKET_QUEUED

    certified = validate_success(
        api.update_technician(
            base["technician_id"],
            {"certification_level": CERT_SANITATION, "open_ticket_count": 5},
            PLATFORM_ADMIN_HEADERS,
        )
    )
    assert certified["certification_level"] == CERT_SANITATION
    assert certified["status"] == TECH_AVAILABLE
    assert certified["version"] == 2
    assert_workload(certified, 0)

    off_duty = validate_success(
        api.update_technician(
            base["technician_id"],
            {"status": TECH_OFF_DUTY},
            PLATFORM_ADMIN_HEADERS,
        )
    )
    assert off_duty["status"] == TECH_OFF_DUTY
    assert off_duty["certification_level"] == CERT_SANITATION
    assert off_duty["version"] == 3

    validate_error(
        api.dispatch_service_ticket(
            ticket["id"], PLATFORM_ADMIN_HEADERS, F.dispatch_payload()
        ),
        ERR_NO_ELIGIBLE_TECHNICIAN,
        409,
    )

    untouched = get_success_data(
        api.get_service_ticket(ticket["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert untouched["status"] == TICKET_QUEUED
    assert untouched["assigned_technician_id"] is None
    assert untouched["escalation_level"] == 0


def test_the_order_schedules_the_withdrawal_and_only_completion_finishes_it(api):
    """
    Withdrawing equipment is two actions and they divide the work: the order moves the
    lifecycle axis and takes the due date from the request instead of the fourteen-day
    default, leaving the health axis up and the feed merely locked out, while only the
    completion moves the machine to retrieved, forces the health axis offline, drives
    the feed to its terminal state with its lockout reason cleared, and gives the
    customer's equipment ledger back.

    PRD §3.3: "A placement in `INSTALLED` is instead **scheduled**: it moves
    `INSTALLED → RETRIEVAL_SCHEDULED`, `retrieval_due_date` takes the supplied value
    or, when the request omits it, the current clock's date plus 14 days."

    PRD §3.3: "On success the placement moves `RETRIEVAL_SCHEDULED → RETRIEVED`,
    `retrieved_at` is stamped from the clock, `operational_status` is driven to
    `OFFLINE` from whichever of `UP`, `DEGRADED` or `DOWN` it held, every dispenser of
    the placement — whether it stood `ACTIVE` or `LOCKED_OUT` — becomes `REMOVED` with
    its `lockout_reason` cleared to null, the model's `equipment_value_cents` is
    subtracted from the customer's `equipment_on_placement_value_cents` restoring that
    ledger exactly to its pre-placement value, the agreement's `placement_count` falls
    by one with a `version` increment, and the site's `service_posture` is re-derived."

    Design: Corner/endpoints/the_retrieval_pair_takes_an_explicit_due_date_and_strips_the_dispensers
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    assert_equipment_ledger(
        get_success_data(
            api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
        ),
        480000,
    )

    scheduled = validate_success(
        api.create_retrieval_order(
            placement["id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload(retrieval_due_date="2026-09-30"),
        )
    )
    assert_axes(
        scheduled,
        placement_status=PLACEMENT_RETRIEVAL_SCHEDULED,
        operational_status=OP_UP,
    )
    assert scheduled["retrieval_due_date"] == "2026-09-30"
    assert scheduled["retrieved_at"] is None

    assert_lockout(
        get_success_data(
            api.get_dispenser(dispenser["id"], base["technician_headers"])
        ),
        DISPENSER_LOCKED_OUT,
        LOCKOUT_AGREEMENT_ENDED,
    )

    retrieved = validate_success(
        api.complete_retrieval(placement["id"], base["technician_headers"])
    )
    assert_axes(
        retrieved,
        placement_status=PLACEMENT_RETRIEVED,
        operational_status=OP_OFFLINE,
    )
    assert_instant_equals(retrieved["retrieved_at"], "2026-08-01T00:00:00Z", "retrieved_at")

    assert_lockout(
        get_success_data(
            api.get_dispenser(dispenser["id"], base["technician_headers"])
        ),
        DISPENSER_REMOVED,
        None,
    )
    assert_equipment_ledger(
        get_success_data(
            api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
        ),
        0,
    )


def test_one_advance_visits_every_contract_and_moves_only_the_due_ones(api):
    """
    The sweep is a per-row filter rather than an all-or-nothing batch: a single advance
    expires the contract whose term has lapsed, moves the one now inside its notice
    window, and leaves the long contract alone, reporting exactly what it did through
    its counters. Repeating the advance at the very same instant re-reports zeros,
    because nothing is left to move.

    PRD §2.4: "Each advance runs a deterministic sweep, and the response reports what
    the sweep did through three counters — `agreements_moved_to_renewal_pending`,
    `agreements_expired` and `tickets_escalated` — alongside the new `current_utc`, so
    that a caller can assert the sweep ran rather than inferring it."

    Design: Corner/endpoints/one_clock_advance_sweeps_only_the_agreements_that_are_due
    """
    customer = X.create_customer(api)
    detergent = X.create_detergent(api)
    covered = [detergent["id"]]

    short = X.create_active_agreement(
        api,
        customer["id"],
        covered,
        agreement_code="AGR-SHORT",
        minimum_term_months=1,
        renewal_notice_days=5,
    )
    mid = X.create_active_agreement(
        api,
        customer["id"],
        covered,
        agreement_code="AGR-MID",
        minimum_term_months=2,
        renewal_notice_days=5,
    )
    long_term = X.create_active_agreement(
        api,
        customer["id"],
        covered,
        agreement_code="AGR-LONG",
        minimum_term_months=36,
        renewal_notice_days=5,
    )
    assert short["term_end_date"] == "2026-09-01"
    assert mid["term_end_date"] == "2026-10-01"
    assert long_term["term_end_date"] == "2029-08-01"

    swept = X.set_clock(api, "2026-09-28T00:00:00Z")
    assert_sweep_counters(
        swept,
        agreements_moved_to_renewal_pending=1,
        agreements_expired=1,
        tickets_escalated=0,
        current_utc="2026-09-28T00:00:00Z",
    )

    def status_of(agreement_id):
        return get_success_data(
            api.get_service_agreement(agreement_id, ACCOUNT_MANAGER_HEADERS)
        )["status"]

    assert status_of(short["id"]) == AGREEMENT_EXPIRED
    assert status_of(mid["id"]) == AGREEMENT_RENEWAL_PENDING
    assert status_of(long_term["id"]) == AGREEMENT_ACTIVE

    again = X.set_clock(api, "2026-09-28T00:00:00Z")
    assert_sweep_counters(
        again,
        agreements_moved_to_renewal_pending=0,
        agreements_expired=0,
        tickets_escalated=0,
    )


def test_a_redo_may_only_point_at_a_rejected_visit_of_its_own_job(api):
    """
    The optional self-reference is validated against the referenced row's state, not
    merely its existence: pointing it at the rejected first visit books the redo, while
    pointing it at that redo — an id that resolves perfectly — is refused as an unknown
    reference because the redo is only scheduled. The rejection also had to hand the
    job back to the queue and clear its assignment, so the redo needed a fresh dispatch
    before it could be booked at all.

    PRD §3.6: "`follow_up_to_visit_id` is optional and, when present, must reference a
    visit of the **same ticket** whose `visit_status` is `REJECTED`; anything else — a
    visit of another ticket, or a visit that was not rejected — is refused with
    `ERR_UNKNOWN_REFERENCE`."

    PRD §3.6: "The ticket returns `PENDING_VERIFICATION → QUEUED` with
    `assigned_technician_id` cleared, the technician's `open_ticket_count` drops by one
    — restoring the conserved workload counter of §2.10 — and that technician's
    `quality_flag_count` rises by one."

    Design: Corner/endpoints/a_follow_up_visit_may_only_reference_a_rejected_visit_of_its_own_ticket
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    work = X.visit_in_progress(api, base, placement["id"])
    # PRD §3.6 submission "requires `calibration_record_count` to be at least 1 -- a
    # visit with no evidence cannot be submitted". A detergent titration on target
    # drifts 0.00%, so the verdict is PASS and efficacy is NOT_APPLICABLE.
    X.record_calibration(api, base, work["visit_id"], dispenser["id"], 1200)
    X.submit_visit(api, base, work["visit_id"], repair_confirmed=True)

    rejected = X.verify_visit(
        api,
        work["visit_id"],
        decision=DECISION_REJECTED,
        rejection_reason="Racks still came out soiled after the repair",
    )
    assert rejected["visit_status"] == VISIT_REJECTED

    requeued = get_success_data(
        api.get_service_ticket(work["ticket_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert requeued["status"] == TICKET_QUEUED
    assert requeued["assigned_technician_id"] is None

    redispatched = X.dispatch_ticket(api, work["ticket_id"])
    assert redispatched["status"] == TICKET_DISPATCHED
    assert redispatched["assigned_technician_id"] == base["technician_id"]

    redo = X.book_visit(
        api,
        base,
        work["ticket_id"],
        scheduled_start_at="2026-08-01T15:00:00Z",
        scheduled_end_at="2026-08-01T16:00:00Z",
        follow_up_to_visit_id=work["visit_id"],
    )
    assert redo["visit_status"] == VISIT_SCHEDULED
    assert redo["follow_up_to_visit_id"] == work["visit_id"]

    _, meta = validate_paginated(
        api.list_service_visits(
            AUDITOR_1_HEADERS, {"follow_up_to_visit_id": work["visit_id"]}
        )
    )
    assert meta["total_count"] == 1

    validate_error(
        api.create_service_visit(
            F.service_visit_payload(
                work["ticket_id"],
                base["technician_id"],
                scheduled_start_at="2026-08-02T09:00:00Z",
                scheduled_end_at="2026-08-02T10:00:00Z",
                follow_up_to_visit_id=redo["id"],
            ),
            base["technician_headers"],
        ),
        ERR_UNKNOWN_REFERENCE,
        422,
    )


def test_an_empty_window_still_carries_the_unconditional_base_fee(api):
    """
    The degenerate window exposes the fee structure with no arithmetic to hide behind:
    no racks and no drops give no saving and no spend, yet the programme still costs the
    base fee, the lowest rate tier is selected from that pre-credit figure, the fee
    itself is zero because the rate multiplies chemical spend alone, and the credit
    stays at zero rather than going negative. The variance basis is not a sustainability
    basis and is refused outright.

    PRD §3.8: "Besides the window it takes `basis`, which must be either `RATED` or
    `TELEMETRY_MEASURED`, with anything else refused as `ERR_INVALID_REQUEST`."

    PRD §3.8: "`service_fee_cents` is `chemical_spend_cents` multiplied by
    `service_fee_rate`, rounded half up to whole cents. Note that the rate applies to
    the chemical spend alone, not to the gross programme cost that selected it."

    Design: Corner/endpoints/a_site_with_no_racks_still_reports_the_base_service_fee
    """
    base = X.program_base(api)

    report = get_success_data(
        api.get_sustainability_report(
            base["site_id"],
            base["customer_headers"],
            F.report_params(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
                basis=SUSTAINABILITY_BASIS_RATED,
            ),
        )
    )
    assert report["rack_count"] == 0
    assert_cents(report["gross_savings_cents"], 0)
    assert_cents(report["chemical_spend_cents"], 0)
    assert_cents(report["gross_program_cost_cents"], 25000)
    assert_pct(report["service_fee_rate"], 0.08)
    assert_cents(report["service_fee_cents"], 0)
    assert_cents(report["sustainability_credit_cents"], 0)
    assert_cents(report["net_program_cost_cents"], 25000)
    assert_pct(report["goal_attainment_pct"], 0.00)

    validate_error(
        api.get_sustainability_report(
            base["site_id"],
            base["customer_headers"],
            F.report_params(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
                basis=BASIS_NAMEPLATE,
            ),
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_a_draft_review_closes_nothing_and_the_void_is_terminal(api):
    """
    The void is conditional on the covering review's status and a draft is explicitly
    not closing: the drop inside a draft review's window voids normally and bumps the
    site version a second time, where the same call under a published review would be
    refused. Voiding again is then an undeclared transition, because voided is terminal.

    PRD §3.7: "A review still in `DRAFT` blocks nothing."

    PRD §3.7: "A mis-keyed delivery moves `DELIVERED → VOIDED`, and only from
    `DELIVERED`: a second void attempt on an already-voided delivery is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/a_draft_review_does_not_freeze_the_deliveries_it_covers
    """
    base = X.program_base(api)
    version_before = X.site_version(api, base["site_id"])

    delivery = X.record_delivery(
        api, base, unit_count=10, delivered_at="2026-08-02T00:00:00Z"
    )
    assert delivery["status"] == DELIVERY_DELIVERED
    # 10 units earn the 5 percent tier: 9600 x 0.95 = 9120 per container.
    assert_cents(delivery["amount_cents"], 91200)

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-08T00:00:00Z",
    )
    assert review["status"] == REVIEW_DRAFT

    voided = validate_success(
        api.void_chemical_delivery(delivery["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert voided["status"] == DELIVERY_VOIDED
    assert X.site_version(api, base["site_id"]) == version_before + 2

    validate_error(
        api.void_chemical_delivery(delivery["id"], ACCOUNT_MANAGER_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
