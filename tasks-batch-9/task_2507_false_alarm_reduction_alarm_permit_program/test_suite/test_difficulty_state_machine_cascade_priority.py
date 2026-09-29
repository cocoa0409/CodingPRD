"""Cyclic state machines, multi-hop cascades and the fixed order of rejection.

Every test here builds its whole world through the program's own endpoints,
because the harness restarts the API against an empty database before each test.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def _at(instant: str) -> str:
    """The leading second-precision prefix of an instant, for prefix matching."""
    return instant[:19]


# =========================================================================== #
# non_linear_state_machine —
# appeal_denied_cycles_the_incident_back_to_counted_and_thaws_frozen_dunning
# =========================================================================== #
def _denied_cycle_world(api):
    """Three counted incidents at one commercial premises, the third one appealed,
    with a nightly run already taken while that appeal is live."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
        site_overrides={"occupancy_class": "COMMERCIAL", "police_beat": "B03"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=3,
    )
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        ["2026-02-05T01:00:00Z", "2026-02-12T01:00:00Z", "2026-02-20T01:00:00Z"],
    )
    third = incidents[2]
    X.set_clock(api, "2026-02-25T00:00:00Z")
    appeal_id = X.file_appeal(
        api,
        bundle,
        third.incident_id,
        grounds="COUNTING_ERROR",
        narrative="The February 20 activation was a utility brownout, not an operator error.",
    )
    docket_id = X.create_docket(
        api,
        "2026-03-10T09:00:00Z",
        "2026-03-10T12:00:00Z",
        location="Hearing Room A",
        capacity=4,
    )
    X.schedule_appeal(api, appeal_id, docket_id)
    X.set_clock(api, "2026-03-25T00:00:00Z")
    X.run_nightly(api)
    return bundle, third, appeal_id, docket_id


def test_appealed_incident_keeps_its_fee_and_freezes_its_invoice_dunning(api):
    """A nightly run taken while the incident sits in APPEALED leaves its fee invoice at CURRENT with no late penalty.

    PRD §3.6: "The incident stays in the chargeable set with its `occurrence_index` and `assessed_fee_cents` untouched; what freezes is the dunning: any invoice carrying that `false_alarm_incident_id` keeps its `collections_stage` exactly where it is and is excluded from nightly escalation for as long as the appeal is live."
    PRD §3.5: "An appealed incident deliberately *stays* in the set and keeps its index for as long as its appeal is live — only the dunning on its invoice freezes — and it leaves the set only if the appeal is granted or the determination is remanded."
    PRD §3.8: "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps require `outstanding_cents` above zero and require that the linked incident, when there is one, is not in `APPEALED`."

    Arithmetic: the third occurrence at this premises is index 3, whose marginal
    tier base is 10000 cents; the commercial occupancy multiplier of 1.50 with no
    surcharge and no unpermitted factor gives a single product of 15000 cents. The
    invoice carries a 15000-cent subtotal, an administrative fee of 5 percent of
    that, 750 cents, inside the 500-to-5000-cent clamp, so 15750 cents is assessed
    on 2026-02-20 and falls due 30 days later on 2026-03-22. The 2026-03-25
    nightly run therefore sees the invoice 3 whole days past due and would move it
    to NOTICE with a 1575-cent penalty were the appeal not live.

    Design: Difficulty/non_linear_state_machine/appeal_denied_cycles_the_incident_back_to_counted_and_thaws_frozen_dunning
    """
    bundle, third, _appeal_id, _docket_id = _denied_cycle_world(api)

    incident = X.get_incident(api, third.incident_id)
    A.assert_status(incident, "APPEALED")
    assert incident["occurrence_index"] == 3, incident["occurrence_index"]
    A.assert_money_cents(incident["assessed_fee_cents"], 15000, "assessed_fee_cents")

    invoice = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=15000,
        admin_fee_cents=750,
        assessed_cents=15750,
        paid_cents=0,
        adjusted_cents=0,
        outstanding_cents=15750,
        payment_status="UNPAID",
        collections_stage="CURRENT",
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 0, "late_penalty_cents")
    A.assert_outstanding_identity(invoice)

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 3, site["chargeable_count_window"]


def test_denied_appeal_returns_the_incident_to_counted_and_thaws_its_dunning(api):
    """Denying the appeal cycles the incident back to COUNTED and the next nightly run adds the penalty it had withheld.

    PRD §3.6: "`DENIED` is the conservative outcome: the count stands."
    PRD §3.6: "The incident returns from `APPEALED` to `COUNTED` with its `determination`, `occurrence_index` and `assessed_fee_cents` exactly as they were before the appeal, its invoice re-enters the nightly escalation set, and the incident becomes eligible for exactly one rehearing."
    PRD §3.6: "A docket may be held from either `OPEN` or `CLOSED_FOR_SCHEDULING` under identical preconditions and with identical effects: `held_at` is stamped with the logical clock, the docket becomes `HELD`, which is terminal, its `version` rises by 1, and every appeal on it in `SCHEDULED` advances to `HEARD`, becoming decidable."
    PRD §3.8: "The first step is where the late penalty is added, exactly once per invoice; the second adds no further penalty and merely makes the invoice referral-eligible once `days_delinquent` reaches `delinquency_days`."

    Arithmetic: the thawed fee invoice was assessed at 15750 cents, so the
    one-time overdue charge of 10 percent is 1575 cents and the assessment
    becomes 17325 cents. The three permit-issue invoices of 5500 cents each fell
    due on 2026-01-31 and took their own single 550-cent penalty at the earlier
    nightly run, standing at 6050 cents apiece, so the premises owes
    3 * 6050 + 17325 = 35475 cents.

    Design: Difficulty/non_linear_state_machine/appeal_denied_cycles_the_incident_back_to_counted_and_thaws_frozen_dunning
    """
    bundle, third, appeal_id, docket_id = _denied_cycle_world(api)

    X.hold_session(api, docket_id)
    decided = X.decide_appeal(
        api,
        appeal_id,
        "DENIED",
        findings="Utility records show no outage on the premises circuit; the counting stands.",
    )
    A.assert_status(decided, "DENIED")
    assert decided["decision"] == "DENIED", decided["decision"]
    assert decided["decided_by_user_id"] == U.HEARING_OFFICER_ID
    assert decided["rehearing_depth"] == 0, decided["rehearing_depth"]

    docket = A.data_of(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    A.assert_status(docket, "HELD")
    assert _at(docket["held_at"]) == _at("2026-03-25T00:00:00Z"), docket["held_at"]
    assert docket["scheduled_appeal_count"] == 1, docket["scheduled_appeal_count"]

    incident = X.get_incident(api, third.incident_id)
    A.assert_status(incident, "COUNTED")
    assert incident["determination"] == "COUNTED", incident["determination"]
    assert incident["occurrence_index"] == 3, incident["occurrence_index"]
    A.assert_money_cents(incident["assessed_fee_cents"], 15000, "assessed_fee_cents")
    assert incident["counted_window_mode"] == "ROLLING_365", incident["counted_window_mode"]
    assert incident["appeal_count"] == 1, incident["appeal_count"]
    assert incident["determined_by_user_id"] == U.REVIEW_OFFICER_ID

    X.set_clock(api, "2026-03-26T00:00:00Z")
    X.run_nightly(api)

    invoice = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=15000,
        admin_fee_cents=750,
        assessed_cents=17325,
        paid_cents=0,
        outstanding_cents=17325,
        payment_status="UNPAID",
        collections_stage="NOTICE",
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 1575, "late_penalty_cents")

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 3, site["chargeable_count_window"]
    A.assert_money_cents(site["outstanding_balance_cents"], 35475, "outstanding_balance_cents")


# =========================================================================== #
# non_linear_state_machine —
# appeal_remand_returns_a_counted_incident_to_under_review_and_voids_its_invoice
# =========================================================================== #
def _remand_world(api):
    """The same three counted incidents, with a 5000-cent part payment sitting on
    the third one's fee invoice and its appeal already heard."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
        site_overrides={"occupancy_class": "COMMERCIAL", "police_beat": "B03"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=3,
    )
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        ["2026-02-05T01:00:00Z", "2026-02-12T01:00:00Z", "2026-02-20T01:00:00Z"],
    )
    third = incidents[2]
    X.set_clock(api, "2026-02-22T00:00:00Z")
    payment_id = X.post_payment(
        api,
        bundle,
        5000,
        "2026-02-22T00:00:00Z",
        allocation_mode="EXPLICIT",
        method="CHECK",
        explicit_allocations=[{"penalty_invoice_id": third.invoice_id, "amount_cents": 5000}],
    )
    X.set_clock(api, "2026-02-25T00:00:00Z")
    appeal_id = X.file_appeal(
        api,
        bundle,
        third.incident_id,
        grounds="WRONG_CAUSE_CODE",
        narrative="The cause code was recorded before the technician report arrived.",
    )
    docket_id = X.create_docket(
        api,
        "2026-03-10T09:00:00Z",
        "2026-03-10T12:00:00Z",
        location="Hearing Room A",
        capacity=4,
    )
    X.schedule_appeal(api, appeal_id, docket_id)
    X.set_clock(api, "2026-03-10T10:00:00Z")
    X.hold_session(api, docket_id)
    return bundle, third, appeal_id, payment_id


def test_remanded_appeal_reverses_the_part_payment_and_voids_the_fee_invoice(api):
    """A REMANDED ruling drags the incident back to UNDER_REVIEW, voids its partially paid invoice and parks the reversed money as premises credit.

    PRD §3.6: "`REMANDED` sends the determination back for another look."
    PRD §3.6: "The incident returns from `APPEALED` to `UNDER_REVIEW` with `determination`, `determined_at`, `determined_by_user_id`, `occurrence_index`, `assessed_fee_cents` and `counted_window_mode` all cleared; any invoice carrying that `false_alarm_incident_id` is voided and its allocations reversed, the reversed amounts landing in the premises' `credit_balance_cents`; the premises' counters are recomputed and its remaining chargeable incidents renumbered contiguously."
    PRD §3.8: "Cascade voids — a remand, an incident void, a vacated order — carry the invoice from `UNPAID` or `PARTIALLY_PAID` to the terminal `VOIDED`: `assessed_cents` is preserved for audit, `outstanding_cents` becomes 0, the invoice leaves every premises rollup and every dunning set, and from `PARTIALLY_PAID` each applied allocation is reversed into the premises' `credit_balance_cents`."
    PRD §3.5: "An appealed incident deliberately *stays* in the set and keeps its index for as long as its appeal is live — only the dunning on its invoice freezes — and it leaves the set only if the appeal is granted or the determination is remanded."

    Arithmetic: the third incident's fee invoice was assessed at 15000 + 750 =
    15750 cents and a single 5000-cent explicit allocation left it at 10750 cents
    outstanding. The remand reverses that one allocation, so the whole 5000 cents
    lands in the premises' credit balance, and the chargeable set falls from three
    incidents to the two that remain.

    Design: Difficulty/non_linear_state_machine/appeal_remand_returns_a_counted_incident_to_under_review_and_voids_its_invoice
    """
    bundle, third, appeal_id, payment_id = _remand_world(api)

    before = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(before, paid_cents=5000, outstanding_cents=10750,
                            payment_status="PARTIALLY_PAID")

    decided = X.decide_appeal(
        api,
        appeal_id,
        "REMANDED",
        findings="The cause code must be re-examined against the technician report.",
    )
    A.assert_status(decided, "REMANDED")
    assert decided["decision"] == "REMANDED", decided["decision"]

    incident = X.get_incident(api, third.incident_id)
    A.assert_status(incident, "UNDER_REVIEW")
    assert incident["determination"] is None, incident["determination"]
    assert incident["occurrence_index"] is None, incident["occurrence_index"]
    # PRD §3.6 says the remand leaves `assessed_fee_cents` "cleared" without
    # picking a rendering, unlike §3.5's exempt branch which pins "0" and
    # §3.6's grant which pins "set to 0"; both null and 0 are faithful here.
    assert incident["assessed_fee_cents"] in (None, 0), incident["assessed_fee_cents"]
    assert incident["counted_window_mode"] is None, incident["counted_window_mode"]

    invoice = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(
        invoice,
        assessed_cents=15750,
        paid_cents=0,
        outstanding_cents=0,
        payment_status="VOIDED",
    )

    allocations = X.allocations_of_payment(api, payment_id)
    assert len(allocations) == 1, allocations
    A.assert_status(allocations[0], "REVERSED")
    A.assert_allocation_row(allocations[0])

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 5000, "credit_balance_cents")
    assert site["chargeable_count_window"] == 2, site["chargeable_count_window"]


def test_remanded_incident_is_re_determined_and_billed_on_a_brand_new_invoice(api):
    """A second review officer re-determines the remanded incident, which re-enters the count at index 3 on a fresh invoice while the voided one keeps its audited assessment.

    PRD §3.6: "A different review officer may then re-determine the incident, re-entering the counting cycle."
    PRD §3.8: "`issued_on` is the logical clock and `due_on` is `issued_on` plus `invoice_due_days` whole days."
    PRD §3.9: "Third, `lifetime_assessed_cents` is the sum of `assessed_cents` over every invoice of the premises whose `payment_status` is not `VOIDED` — so a written-off invoice still counts toward lifetime assessment even though it has left the outstanding balance."
    PRD §3.9: "A parked credit is not spent by itself: it is released only by a later payment's allocation or by a void reversal, never auto-consumed by the next invoice the premises incurs."

    Arithmetic: re-determination restores index 3, whose tier base of 10000 cents
    times the commercial multiplier of 1.50 is 15000 cents, plus a 750-cent
    administrative fee, so the replacement invoice is assessed at 15750 cents,
    issued at the logical clock of 2026-03-10T10:00:00Z and due 30 whole days
    later at 2026-04-09T10:00:00Z. The premises then owes the three 5500-cent
    permit-issue invoices plus that 15750, that is 16500 + 15750 = 32250 cents,
    and because the voided 15750-cent invoice is excluded from the lifetime total
    while the replacement is included, `lifetime_assessed_cents` is also 32250.

    Design: Difficulty/non_linear_state_machine/appeal_remand_returns_a_counted_incident_to_under_review_and_voids_its_invoice
    """
    bundle, third, appeal_id, _payment_id = _remand_world(api)
    X.decide_appeal(
        api,
        appeal_id,
        "REMANDED",
        findings="The cause code must be re-examined against the technician report.",
    )

    redetermined = A.data_of(
        api.determine_incident(
            third.incident_id,
            F.determination_payload(
                "COUNTED",
                review_notes="Re-determined after remand by a second officer; cause code confirmed.",
            ),
            U.REVIEW_OFFICER_2,
        )
    )
    A.assert_status(redetermined, "COUNTED")
    assert redetermined["occurrence_index"] == 3, redetermined["occurrence_index"]
    A.assert_money_cents(redetermined["assessed_fee_cents"], 15000, "assessed_fee_cents")
    assert redetermined["determined_by_user_id"] == U.REVIEW_OFFICER_ID_2

    fee_invoices = X.invoices_of_site(api, bundle.site_id, kind="FALSE_ALARM_FEE")
    assert len(fee_invoices) == 2, [(i["id"], i["payment_status"]) for i in fee_invoices]
    voided = [i for i in fee_invoices if i["payment_status"] == "VOIDED"]
    fresh = [i for i in fee_invoices if i["payment_status"] == "UNPAID"]
    assert len(voided) == 1 and len(fresh) == 1, fee_invoices
    A.assert_money_cents(voided[0]["assessed_cents"], 15750, "voided assessed_cents")
    A.assert_invoice_totals(
        fresh[0],
        subtotal_cents=15000,
        admin_fee_cents=750,
        assessed_cents=15750,
        paid_cents=0,
        outstanding_cents=15750,
        collections_stage="CURRENT",
    )
    assert _at(fresh[0]["issued_on"]) == _at("2026-03-10T10:00:00Z"), fresh[0]["issued_on"]
    assert _at(fresh[0]["due_on"]) == _at("2026-04-09T10:00:00Z"), fresh[0]["due_on"]

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 3, site["chargeable_count_window"]
    A.assert_money_cents(site["outstanding_balance_cents"], 32250, "outstanding_balance_cents")
    A.assert_money_cents(site["credit_balance_cents"], 5000, "credit_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 32250, "lifetime_assessed_cents")


# =========================================================================== #
# non_linear_state_machine —
# invoice_reaches_paid_while_its_dunning_dimension_still_reads_final_notice
# =========================================================================== #
def _final_notice_world(api):
    """One permit-issue invoice driven to FINAL_NOTICE by two nightly runs."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "permit_issue_fee_cents": 22857,
        },
        site_overrides={"occupancy_class": "RESIDENTIAL", "police_beat": "B05"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=1,
    )
    invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(invoices) == 1, invoices
    invoice_id = invoices[0]["id"]
    X.set_clock(api, "2026-02-01T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-03-05T00:00:00Z")
    X.run_nightly(api)
    return bundle, invoice_id


def test_settling_a_final_notice_invoice_leaves_its_dunning_stage_untouched(api):
    """Paying a FINAL_NOTICE invoice in full flips only the money dimension to PAID; the dunning dimension keeps reading FINAL_NOTICE.

    PRD §3.8: "`payment_status` tracks the money and `collections_stage` tracks the dunning, and they advance independently."
    PRD §3.8: "An invoice can be `REFERRED` and still reach `PAID`; it can be `PAID` while still sitting at `FINAL_NOTICE` until the next nightly run resettles the stage."
    PRD §3.8: "Settlement — `UNPAID → PAID` or `PARTIALLY_PAID → PAID` — occurs exactly when `paid_cents` plus `adjusted_cents` equals `assessed_cents` after the write, whether that is reached by an allocation covering the remainder or by a `WAIVE` adjustment; `outstanding_cents` becomes 0, the stage resettles to `CURRENT` on the next nightly run, and when every invoice for the premises is `PAID` a `REINSTATEMENT_PENDING` suspension order becomes liftable."
    PRD §3.8: "`days_delinquent` is the whole days between `due_on` and the logical clock, floored at zero."

    Arithmetic: the permit-issue fee of 22857 cents carries a 5 percent
    administrative fee of 1142.85 cents, which rounds half up to 1143, so 24000
    cents is assessed on 2026-01-01 and falls due on 2026-01-31. The 2026-02-01
    nightly run sees 1 whole day delinquent, moves the stage to NOTICE and adds
    the one-time 10 percent penalty of 2400 cents, lifting the assessment to
    26400 cents. On 2026-03-05 the invoice is 33 whole days past due, so the
    second nightly run moves it to FINAL_NOTICE and adds nothing further. A
    26400-cent ACH tender then settles it exactly.

    Design: Difficulty/non_linear_state_machine/invoice_reaches_paid_while_its_dunning_dimension_still_reads_final_notice
    """
    bundle, invoice_id = _final_notice_world(api)

    before = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        before,
        subtotal_cents=22857,
        admin_fee_cents=1143,
        assessed_cents=26400,
        paid_cents=0,
        outstanding_cents=26400,
        payment_status="UNPAID",
        collections_stage="FINAL_NOTICE",
    )
    A.assert_money_cents(before["late_penalty_cents"], 2400, "late_penalty_cents")
    assert before["days_delinquent"] == 33, before["days_delinquent"]

    payment_id = X.post_payment(
        api,
        bundle,
        26400,
        "2026-03-05T00:00:00Z",
        allocation_mode="EXPLICIT",
        method="ACH",
        explicit_allocations=[{"penalty_invoice_id": invoice_id, "amount_cents": 26400}],
    )

    settled = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        settled,
        assessed_cents=26400,
        paid_cents=26400,
        outstanding_cents=0,
        payment_status="PAID",
        collections_stage="FINAL_NOTICE",
    )
    A.assert_outstanding_identity(settled)

    payment = X.get_payment(api, payment_id)
    A.assert_status(payment, "APPLIED")
    A.assert_money_cents(payment["allocated_cents"], 26400, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 0, "credited_cents")
    A.assert_cash_conservation(payment)


def test_nightly_resettlement_drops_the_stage_to_current_without_refunding_the_penalty(api):
    """The next nightly run walks the dunning ladder backwards to CURRENT while the money dimension stays PAID and the late penalty already assessed is kept.

    PRD §3.8: "Settlement runs the ladder backwards: the nightly resettlement moves `NOTICE → CURRENT` or `FINAL_NOTICE → CURRENT` once `outstanding_cents` has become 0, dunning stops, and any late penalty already assessed is **not** refunded."
    PRD §3.8: "Neither dimension is derivable from the other."
    PRD §3.9: "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    Arithmetic: the resettled invoice keeps its 2400-cent penalty inside a 26400-cent
    assessment, so nothing is refunded. With that sole invoice fully paid the
    premises' outstanding balance is 0 cents, the tender left no residual so the
    credit balance is 0 cents, and 0 is below the 50000-cent block threshold, so
    the renewal block is off.

    Design: Difficulty/non_linear_state_machine/invoice_reaches_paid_while_its_dunning_dimension_still_reads_final_notice
    """
    bundle, invoice_id = _final_notice_world(api)
    X.post_payment(
        api,
        bundle,
        26400,
        "2026-03-05T00:00:00Z",
        allocation_mode="EXPLICIT",
        method="ACH",
        explicit_allocations=[{"penalty_invoice_id": invoice_id, "amount_cents": 26400}],
    )

    X.set_clock(api, "2026-03-06T00:00:00Z")
    X.run_nightly(api)

    resettled = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        resettled,
        assessed_cents=26400,
        paid_cents=26400,
        outstanding_cents=0,
        payment_status="PAID",
        collections_stage="CURRENT",
    )
    A.assert_money_cents(resettled["late_penalty_cents"], 2400, "late_penalty_cents")

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")
    assert site["renewal_block_active"] is False, site["renewal_block_active"]
    A.assert_money_cents(site["lifetime_assessed_cents"], 26400, "lifetime_assessed_cents")


# =========================================================================== #
# transitive_cascade —
# permit_expiry_cascades_through_unpermitted_status_penalty_invoice_and_a_sibling_permit_block
# =========================================================================== #
def _renew_permit(api, permit_id, headers=U.PERMIT_CLERK):
    """Renew a permit, reading its current revision first."""
    response = api.renew_permit(
        permit_id,
        {"expected_alarm_permit_version": X.permit_version(api, permit_id)},
        headers,
    )
    assert response.status_code in (200, 201), (
        f"renewal was refused with {response.status_code}: {response.text}"
    )
    return response.json()["data"]


def _expiry_cascade_world(api):
    """Two permits at one commercial premises; the second one renewed out of grace,
    the first one left to expire, then the nightly run that expires it."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "permit_term_days": 30,
            "renewal_grace_days": 10,
            "unpermitted_operation_penalty_cents": 60000,
            "invoice_due_days": 3650,
        },
        site_overrides={"occupancy_class": "COMMERCIAL", "police_beat": "B02"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=2,
    )
    permit_a, permit_b = bundle.permit_ids[0], bundle.permit_ids[1]
    system_a = bundle.system_ids[0]

    X.set_clock(api, "2026-01-05T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-02-01T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-02-05T00:00:00Z")
    _renew_permit(api, permit_b)
    X.set_clock(api, "2026-02-06T00:00:00Z")
    X.run_nightly(api)

    X.set_clock(api, "2026-02-11T00:00:00Z")
    X.run_nightly(api)
    return bundle, system_a, permit_a, permit_b


def test_permit_expiry_drives_its_system_unpermitted_and_issues_the_operation_penalty(api):
    """The nightly run that outruns the grace instant expires the permit and, in the same run, drops its system to UNPERMITTED with a 63000-cent operation penalty.

    PRD §3.3: "Past `term_end_at` the run moves `RENEWAL_DUE → GRACE`, and past `grace_through_at` it moves `GRACE → EXPIRED`."
    PRD §3.3: "Hop one: the nightly run moves `GRACE → EXPIRED` on the permit."
    PRD §3.3: "Hop two: because the permit expired, the system moves `PERMITTED → UNPERMITTED` with `unpermitted_since` stamped at the logical clock, the premises' `unpermitted_system_count` is incremented, and an `UNPERMITTED_OPERATION_PENALTY` invoice is issued against the premises and that permit at `unpermitted_operation_penalty_cents`."
    PRD §3.8: "An `UNPERMITTED_OPERATION_PENALTY` invoice carries one UNPERMITTED_OPERATION line at `unpermitted_operation_penalty_cents`."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."

    Arithmetic: both permits started on 2026-01-01 with a 30-day term, so
    `term_end_at` is 2026-01-31 and, with a 10-day grace, `grace_through_at` is
    2026-02-10. At the logical clock of 2026-02-11 the untouched permit is past
    that instant. The penalty invoice carries one line of 60000 cents, so the
    subtotal is 60000, the 5 percent administrative fee is 3000 cents — inside the
    500-to-5000-cent clamp — and 63000 cents is assessed.

    Design: Difficulty/transitive_cascade/permit_expiry_cascades_through_unpermitted_status_penalty_invoice_and_a_sibling_permit_block
    """
    bundle, system_a, permit_a, _permit_b = _expiry_cascade_world(api)

    permit = X.get_permit(api, permit_a)
    A.assert_status(permit, "EXPIRED")
    assert _at(permit["grace_through_at"]) == _at("2026-02-10T00:00:00Z"), permit["grace_through_at"]

    system = X.get_system(api, system_a)
    A.assert_status(system, "UNPERMITTED")
    assert _at(system["unpermitted_since"]) == _at("2026-02-11T00:00:00Z"), system["unpermitted_since"]

    penalties = X.invoices_of_site(api, bundle.site_id, kind="UNPERMITTED_OPERATION_PENALTY")
    assert len(penalties) == 1, penalties
    penalty = penalties[0]
    assert penalty["alarm_permit_id"] == permit_a, penalty["alarm_permit_id"]
    A.assert_invoice_totals(
        penalty,
        subtotal_cents=60000,
        admin_fee_cents=3000,
        assessed_cents=63000,
        paid_cents=0,
        outstanding_cents=63000,
        payment_status="UNPAID",
    )
    assert len(penalty["line_items"]) == 1, penalty["line_items"]
    assert penalty["line_items"][0]["code"] == "UNPERMITTED_OPERATION", penalty["line_items"][0]
    A.assert_money_cents(penalty["line_items"][0]["extended_cents"], 60000, "extended_cents")

    site = X.get_site(api, bundle.site_id)
    assert site["unpermitted_system_count"] == 1, site["unpermitted_system_count"]


def test_expiry_penalty_blocks_a_sibling_permit_the_request_never_touched(api):
    """The operation penalty pushes the premises balance over the block threshold, which drags the untouched sibling permit from RENEWAL_DUE to RENEWAL_BLOCKED and refuses its renewal.

    PRD §3.3: "Hop three: because that penalty pushed the premises' `outstanding_balance_cents` to or above `delinquent_balance_block_cents`, `renewal_block_active` flips to true and **every other permit at the same premises** sitting in `RENEWAL_DUE` moves to `RENEWAL_BLOCKED`."
    PRD §3.9: "Sixth, the permits follow that flag: every permit of the premises sitting in `RENEWAL_DUE` moves to `RENEWAL_BLOCKED` when the flag has just become true, and every `RENEWAL_BLOCKED` permit moves back to `RENEWAL_DUE` when it has just become false."
    PRD §2.10: "Permit renewal is refused on the same balance condition, with `ERR_PERMIT_RENEWAL_BLOCKED` at HTTP 409."
    PRD §3.3: "A renewal is therefore priced as one `PERMIT_RENEWAL` line at `permit_renewal_fee_cents`, plus — only when the late fee is above zero — one `LATE_RENEWAL` line at that fee."

    Arithmetic: the sibling permit was renewed on 2026-02-05, 5 whole days after
    its 2026-01-31 term end, which selects the first late tier at 1500 cents; its
    renewal invoice therefore has a 3000-cent PERMIT_RENEWAL line plus a 1500-cent
    LATE_RENEWAL line for a 4500-cent subtotal, whose 5 percent administrative fee
    of 225 cents is clamped up to the 500-cent floor, giving 5000 cents assessed,
    and its new 30-day term ends 2026-03-07. The premises therefore owes the two
    5500-cent permit-issue invoices, that 5000-cent renewal and the 63000-cent
    operation penalty: 11000 + 5000 + 63000 = 79000 cents, which is at or above
    the 50000-cent blocking threshold.

    Design: Difficulty/transitive_cascade/permit_expiry_cascades_through_unpermitted_status_penalty_invoice_and_a_sibling_permit_block
    """
    bundle, _system_a, _permit_a, permit_b = _expiry_cascade_world(api)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 79000, "outstanding_balance_cents")
    assert site["renewal_block_active"] is True, site["renewal_block_active"]
    A.assert_money_cents(site["lifetime_assessed_cents"], 79000, "lifetime_assessed_cents")

    sibling = X.get_permit(api, permit_b)
    A.assert_status(sibling, "RENEWAL_BLOCKED")
    assert sibling["renewal_count"] == 1, sibling["renewal_count"]
    assert _at(sibling["term_end_at"]) == _at("2026-03-07T00:00:00Z"), sibling["term_end_at"]

    renewals = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_RENEWAL_FEE")
    assert len(renewals) == 1, renewals
    renewal_invoice = renewals[0]
    A.assert_invoice_totals(
        renewal_invoice,
        subtotal_cents=4500,
        admin_fee_cents=500,
        assessed_cents=5000,
        outstanding_cents=5000,
    )
    codes = [line["code"] for line in renewal_invoice["line_items"]]
    assert codes == ["PERMIT_RENEWAL", "LATE_RENEWAL"], codes
    A.assert_money_cents(renewal_invoice["line_items"][0]["extended_cents"], 3000, "PERMIT_RENEWAL")
    A.assert_money_cents(renewal_invoice["line_items"][1]["extended_cents"], 1500, "LATE_RENEWAL")

    refused = api.renew_permit(
        permit_b,
        {"expected_alarm_permit_version": sibling["version"]},
        U.PERMIT_CLERK,
    )
    validate_error(refused, E.ERR_PERMIT_RENEWAL_BLOCKED, expected_status=409)

    after = X.get_permit(api, permit_b)
    A.assert_status(after, "RENEWAL_BLOCKED")
    A.assert_version_unchanged(sibling, after)


# =========================================================================== #
# transitive_cascade —
# granted_appeal_cascades_from_exemption_through_renumbering_repricing_and_order_vacatur
# =========================================================================== #
def _granted_cascade_world(api):
    """Three counted incidents, both fee invoices settled, an auto-proposed
    suspension order in place, and the MIDDLE incident's appeal already heard."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "free_alarm_allowance": 1,
            "probation_threshold_count": 2,
            "suspension_threshold_count": 3,
            "invoice_due_days": 3650,
            "fee_tiers": [
                {"from_index": 1, "to_index": 1, "base_fee_cents": 0},
                {"from_index": 2, "to_index": 2, "base_fee_cents": 10000},
                {"from_index": 3, "to_index": 3, "base_fee_cents": 20000},
                {"from_index": 4, "to_index": None, "base_fee_cents": 40000},
            ],
        },
        site_overrides={"occupancy_class": "RESIDENTIAL", "police_beat": "B06"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=3,
    )
    first, second, third = X.accumulate_counted_incidents(
        api,
        bundle,
        ["2026-02-05T02:00:00Z", "2026-02-12T02:00:00Z", "2026-02-20T02:00:00Z"],
    )
    orders = [o for o in X.orders_of_site(api, bundle.site_id) if o["status"] == "PROPOSED"]
    assert len(orders) == 1, orders
    order_id = orders[0]["id"]

    X.set_clock(api, "2026-02-25T00:00:00Z")
    X.post_payment(
        api,
        bundle,
        31500,
        "2026-02-25T00:00:00Z",
        allocation_mode="EXPLICIT",
        method="CARD",
        explicit_allocations=[
            {"penalty_invoice_id": second.invoice_id, "amount_cents": 10500},
            {"penalty_invoice_id": third.invoice_id, "amount_cents": 21000},
        ],
    )
    appeal_id = X.file_appeal(
        api,
        bundle,
        second.incident_id,
        grounds="EXEMPT_CAUSE",
        narrative="The February 12 activation coincided with a documented feeder outage.",
    )
    docket_id = X.create_docket(
        api,
        "2026-03-01T09:00:00Z",
        "2026-03-01T12:00:00Z",
        location="Hearing Room B",
        capacity=4,
    )
    X.schedule_appeal(api, appeal_id, docket_id)
    X.set_clock(api, "2026-03-01T10:00:00Z")
    X.hold_session(api, docket_id)
    return bundle, first, second, third, appeal_id, order_id


def _grant_the_appeal(api, appeal_id):
    return X.decide_appeal(
        api,
        appeal_id,
        "GRANTED",
        findings="Utility outage log confirms a feeder failure at the time of the activation.",
        exempt_cause_code="UTILITY_POWER_FAILURE",
    )


def test_granted_appeal_exempts_the_incident_and_renumbers_and_reprices_the_later_one(api):
    """Granting the middle incident's appeal exempts it and, in the same request, renumbers and reprices the later incident that nobody appealed.

    PRD §3.6: "Hop one: the incident moves from `APPEALED` to the terminal `EXEMPT_BY_APPEAL`, with `determination` set to `EXEMPT`, `exempt_cause_code` taken from the ruling, `occurrence_index` set to null and `assessed_fee_cents` set to 0."
    PRD §3.6: "Hop two: because the incident left the chargeable set, the premises' chargeable counters decrement and every remaining chargeable incident at that premises — those in `COUNTED` or `APPEALED` — is renumbered contiguously in order of occurrence instant ascending then creation instant ascending, and its fee re-derived at its new tier."
    PRD §3.5: "The set of `occurrence_index` values across those incidents is exactly the contiguous run from 1 to that count, with no gaps and no duplicates, assigned in order of occurrence instant ascending and, for ties, creation instant ascending."
    PRD §3.6: "And nobody reviews their own work: the deciding `X-User-ID` must differ both from the appealed incident's `determined_by_user_id` and from the appeal's `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Arithmetic: the three occurrences were numbered 1, 2 and 3 and priced from the
    schedule's tiers at 0, 10000 and 20000 cents against a residential multiplier
    of 1.00. Removing the middle one leaves two chargeable incidents, so the
    earliest keeps index 1 at a 0-cent tier and the latest falls from index 3 to
    index 2, whose tier base is 10000 cents, halving its fee from 20000 to 10000
    cents.

    Design: Difficulty/transitive_cascade/granted_appeal_cascades_from_exemption_through_renumbering_repricing_and_order_vacatur
    """
    bundle, first, second, third, appeal_id, _order_id = _granted_cascade_world(api)

    decided = _grant_the_appeal(api, appeal_id)
    A.assert_status(decided, "GRANTED")
    assert decided["decision"] == "GRANTED", decided["decision"]
    assert decided["decided_by_user_id"] == U.HEARING_OFFICER_ID

    exempted = X.get_incident(api, second.incident_id)
    A.assert_status(exempted, "EXEMPT_BY_APPEAL")
    assert exempted["determination"] == "EXEMPT", exempted["determination"]
    assert exempted["exempt_cause_code"] == "UTILITY_POWER_FAILURE", exempted["exempt_cause_code"]
    assert exempted["occurrence_index"] is None, exempted["occurrence_index"]
    A.assert_money_cents(exempted["assessed_fee_cents"], 0, "assessed_fee_cents")

    renumbered = X.get_incident(api, third.incident_id)
    assert renumbered["occurrence_index"] == 2, renumbered["occurrence_index"]
    A.assert_money_cents(renumbered["assessed_fee_cents"], 10000, "assessed_fee_cents")
    A.assert_fee_basis(
        renumbered["fee_basis"],
        tier_base_cents=10000,
        occupancy_multiplier=1.00,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        aggravation_cents=0,
        cap_applied=False,
    )

    unchanged = X.get_incident(api, first.incident_id)
    assert unchanged["occurrence_index"] == 1, unchanged["occurrence_index"]

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 2, site["chargeable_count_window"]
    assert site["chargeable_count_rolling_365"] == 2, site["chargeable_count_rolling_365"]


def test_granted_appeal_reassesses_the_settled_invoice_and_vacates_the_proposed_order(api):
    """The same grant re-assesses an already-settled invoice, refunds the overpayment into premises credit, and vacates the auto-proposed suspension order.

    PRD §3.6: "Hop three: because a renumbered incident's assessed fee changed, its invoice is re-assessed, `assessed_cents` recomputed, and any `paid_cents` above the new `assessed_cents` moved into the premises' `credit_balance_cents`."
    PRD §3.6: "Hop four: because the premises' `chargeable_count_window` has fallen below `suspension_threshold_count`, every suspension order for that premises in `PROPOSED`, `EFFECTIVE` or `REINSTATEMENT_PENDING` moves to `VACATED` and `response_status` is recomputed."
    PRD §3.6: "A single grant can therefore reprice invoices belonging to incidents that were never appealed and restore police response to a premises that had lost it."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."

    Arithmetic: the latest incident's fee falls from 20000 to 10000 cents, so its
    invoice is re-assessed to a 10000-cent subtotal plus a 5 percent
    administrative fee of 500 cents, that is 10500 cents; it had been paid 21000,
    so the 10500-cent excess moves to credit, and the exempted incident's own
    10500-cent settled invoice releases another 10500, giving a credit balance of
    21000 cents. Only the three 5500-cent permit-issue invoices are still open, so
    the premises owes 16500 cents. With the window count now 2 the count is at the
    probation threshold of 2 but below the suspension threshold of 3.

    Design: Difficulty/transitive_cascade/granted_appeal_cascades_from_exemption_through_renumbering_repricing_and_order_vacatur
    """
    bundle, _first, _second, third, appeal_id, order_id = _granted_cascade_world(api)

    settled_before = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(settled_before, assessed_cents=21000, paid_cents=21000,
                            outstanding_cents=0, payment_status="PAID")

    _grant_the_appeal(api, appeal_id)

    reassessed = X.get_invoice(api, third.invoice_id)
    A.assert_invoice_totals(
        reassessed,
        subtotal_cents=10000,
        admin_fee_cents=500,
        assessed_cents=10500,
        paid_cents=10500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_outstanding_identity(reassessed)

    order = X.get_order(api, order_id)
    A.assert_status(order, "VACATED")

    site = X.get_site(api, bundle.site_id)
    assert site["response_status"] == "RESPONSE_PROBATION", site["response_status"]
    A.assert_money_cents(site["credit_balance_cents"], 21000, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 16500, "outstanding_balance_cents")

    summary = X.get_summary(api, bundle.site_id)
    assert summary["chargeable_count_window"] == 2, summary["chargeable_count_window"]
    assert summary["response_status"] == "RESPONSE_PROBATION", summary["response_status"]


# =========================================================================== #
# priority_pair_validation_conflict —
# pair_a_open_dispatch_request_outranks_police_response_suspended_on_the_same_post
# =========================================================================== #
def _pair_a_world(api):
    """A suspended premises holding three permitted systems: one with an open
    VALIDATED request, one that produced the counted incident, one never used."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "free_alarm_allowance": 0,
            "probation_threshold_count": 1,
            "suspension_threshold_count": 1,
            "invoice_due_days": 3650,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
        },
        site_overrides={"occupancy_class": "RESIDENTIAL", "police_beat": "B02"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        contact_count=3,
        system_count=3,
    )
    system_a, system_b, system_c = bundle.system_ids

    X.set_clock(api, "2026-02-05T00:00:00Z")
    open_request_id = X.submit_dispatch_request(api, bundle, system_a, "2026-02-05T03:00:00Z")
    validate_success(api.validate_dispatch_request(open_request_id, U.DISPATCH_SUPERVISOR), 200)

    X.set_clock(api, "2026-02-06T00:00:00Z")
    X.create_counted_incident(api, bundle, system_b, "2026-02-06T03:00:00Z")
    proposed = [o for o in X.orders_of_site(api, bundle.site_id) if o["status"] == "PROPOSED"]
    assert len(proposed) == 1, proposed

    X.set_clock(api, "2026-02-10T00:00:00Z")
    validate_success(api.serve_suspension_order(proposed[0]["id"], U.PROGRAM_ADMIN), 200)
    X.set_clock(api, "2026-02-20T00:00:00Z")
    return bundle, system_a, system_c, open_request_id


def _dispatch_attempt(api, bundle, system_id, occurred_at):
    """Lodge a dispatch request without asserting that it is accepted."""
    return api.create_dispatch_request(
        F.dispatch_request_payload(
            system_id, occurred_at, X.two_call_attempts(bundle, occurred_at)
        ),
        bundle.operator_headers,
    )


def test_open_request_check_outranks_the_suspended_response_check(api):
    """A dispatch request that both duplicates an open request and targets a suspended premises is refused for the open request, not for the suspension.

    PRD §2.10: "A single request can violate several rules at once, and callers depend on a stable answer."
    PRD §2.10: "The service therefore evaluates its checks in one fixed sequence and returns the **first** failure it finds; later checks are never reached."
    PRD §2.10: "A dispatch request naming a system that already has an open dispatch request, at a premises whose posture is `RESPONSE_SUSPENDED`, fails both the open-request check at position 18 and the suspended-response check at position 26. The open-request check wins, and the caller receives `ERR_OPEN_DISPATCH_REQUEST_EXISTS`."
    PRD §2.10: "A new dispatch request is refused when the named alarm system already has a dispatch request in `SUBMITTED`, `VALIDATED` or `DISPATCHED`, with `ERR_OPEN_DISPATCH_REQUEST_EXISTS`."

    Arithmetic: the single counted occurrence takes the window count to 1, which
    equals the configured suspension threshold of 1, so an order was auto-proposed
    for the logical clock plus 10 days, that is 2026-02-16 through 2026-03-18. The
    order was served on 2026-02-10, at or before its effective instant, and the
    trigger runs at 2026-02-20, inside that closed interval, so the premises reads
    RESPONSE_SUSPENDED while the earlier request on the target system is still
    VALIDATED and therefore still open.

    Design: Difficulty/priority_pair_validation_conflict/pair_a_open_dispatch_request_outranks_police_response_suspended_on_the_same_post
    """
    bundle, system_a, _system_c, open_request_id = _pair_a_world(api)

    site = X.get_site(api, bundle.site_id)
    assert site["response_status"] == "RESPONSE_SUSPENDED", site["response_status"]
    still_open = A.data_of(api.get_dispatch_request(open_request_id, U.DISPATCH_SUPERVISOR))
    A.assert_status(still_open, "VALIDATED")

    refused = _dispatch_attempt(api, bundle, system_a, "2026-02-20T03:00:00Z")
    validate_error(refused, E.ERR_OPEN_DISPATCH_REQUEST_EXISTS, expected_status=409)

    A.assert_total_count(
        api.list_dispatch_requests(U.DISPATCH_SUPERVISOR, {"alarm_system_id": system_a}), 1
    )


def test_suspended_response_check_still_fires_on_a_system_with_no_open_request(api):
    """The very same request aimed at a never-used sibling system of the same suspended premises is refused for the suspension, which is what makes the ordering observable.

    PRD §2.10: "Next, the premises behind the named system must not sit at `RESPONSE_SUSPENDED` posture when a dispatch request is lodged, failing with `ERR_POLICE_RESPONSE_SUSPENDED`."
    PRD §3.7: "Serving also issues a `REINSTATEMENT_FEE` invoice against the premises with `suspension_order_id` set, recomputes the premises' `response_status` to `RESPONSE_SUSPENDED` along with its `outstanding_balance_cents` and `renewal_block_active`, and bumps the premises' `version` by 1."
    PRD §3.5: "If the premises has a suspension order in `EFFECTIVE` or `REINSTATEMENT_PENDING` whose closed interval contains the current instant, the posture is `RESPONSE_SUSPENDED`."

    Arithmetic: the third system at this premises has never carried a dispatch
    request, so its open-request count is 0 and only the suspended-response check
    at position 26 can fail. The refusal must therefore report
    ERR_POLICE_RESPONSE_SUSPENDED, and because a rejected request is never
    persisted the listing filtered to that system still reports 0 rows.

    Design: Difficulty/priority_pair_validation_conflict/pair_a_open_dispatch_request_outranks_police_response_suspended_on_the_same_post
    """
    bundle, _system_a, system_c, _open_request_id = _pair_a_world(api)

    site = X.get_site(api, bundle.site_id)
    assert site["response_status"] == "RESPONSE_SUSPENDED", site["response_status"]
    A.assert_total_count(
        api.list_dispatch_requests(U.DISPATCH_SUPERVISOR, {"alarm_system_id": system_c}), 0
    )

    refused = _dispatch_attempt(api, bundle, system_c, "2026-02-20T04:00:00Z")
    validate_error(refused, E.ERR_POLICE_RESPONSE_SUSPENDED, expected_status=409)

    A.assert_total_count(
        api.list_dispatch_requests(U.DISPATCH_SUPERVISOR, {"alarm_system_id": system_c}), 0
    )


def _pair_b_world(api):
    """A renewable permit at a premises whose balance has crossed the block."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "permit_issue_fee_cents": 30000,
            "permit_term_days": 30,
            "renewal_grace_days": 10,
            "delinquent_balance_block_cents": 50000,
            "invoice_due_days": 3650,
        },
        site_overrides={"occupancy_class": "COMMERCIAL", "police_beat": "B21"},
        contact_count=2,
        system_count=1,
    )
    permit_a = bundle.permit_ids[0]
    first = X.get_permit(api, permit_a)
    A.assert_status(first, "ACTIVE")
    assert _at(first["term_end_at"]) == _at("2026-01-31T00:00:00Z"), first["term_end_at"]

    X.set_clock(api, "2026-01-02T00:00:00Z")
    X.run_nightly(api)
    A.assert_status(X.get_permit(api, permit_a), "RENEWAL_DUE")
    assert X.get_site(api, bundle.site_id)["renewal_block_active"] is False

    X.add_permitted_system(api, bundle, installed_at="2026-01-02T00:00:00Z")
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 63000, "outstanding_balance_cents")
    assert site["renewal_block_active"] is True, site
    # PRD §3.3: "when the premises' `renewal_block_active` becomes true the run
    # moves `RENEWAL_DUE -> RENEWAL_BLOCKED`, and renewal attempts are then
    # refused with `ERR_PERMIT_RENEWAL_BLOCKED` until the balance clears".
    A.assert_status(X.get_permit(api, permit_a), "RENEWAL_BLOCKED")
    return bundle, permit_a


def test_missing_active_schedule_outranks_the_renewal_block_on_the_same_permit(api):
    """A renewal that is both unpriceable and fiscally blocked reports the schedule fault.

    PRD §2.10: "A permit renewal attempted when no fee schedule is `ACTIVE`, for a
    premises whose delinquent balance is at or above the blocking threshold, fails
    both the active-schedule check at position 43 and the renewal-block check at
    position 55."
    PRD §2.10: "The active-schedule check wins, and the caller receives
    `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §2.10: "Exactly one fee schedule must be `ACTIVE` at the logical clock to
    govern a fee about to be assessed, on registration approval, permit renewal and
    incident determination alike, failing with `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §2.9: "Where an operation is about to assess money and no schedule is
    `ACTIVE` at the logical clock, the operation is refused with
    `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §3.1: "Activating it moves it to `ACTIVE`, pushes any previously `ACTIVE`
    schedule to `SUPERSEDED` and stamps that outgoing row's `superseded_at` with the
    logical clock."
    PRD §3.3: "Renewal is available from both `RENEWAL_DUE` and `GRACE`, to an
    administrator, a clerk or the permit holder, and both branches carry the same
    requirements and the same effects."

    The premises is pinned to a schedule that charges 30000 cents to issue a permit,
    so each of its two approvals raises an invoice of 30000 plus a five-percent
    administrative charge of 1500, that is 31500 cents, and the two together leave
    63000 cents outstanding against a blocking threshold of 50000; the flag is
    therefore already true. Activating a second schedule whose `effective_from` is
    2026-06-01 supersedes the pinned one and leaves nothing governing at the logical
    clock of 2026-01-02, so the renewal now trips both rows and must answer with the
    earlier of the two.

    Design: Difficulty/priority_pair_validation_conflict/pair_b_missing_active_fee_schedule_outranks_the_delinquent_renewal_block
    """
    bundle, permit_a = _pair_b_world(api)

    future = X.create_active_fee_schedule(api, effective_from="2026-06-01T00:00:00Z")
    A.assert_status(A.data_of(api.get_fee_schedule(future, U.PROGRAM_ADMIN)), "ACTIVE")
    A.assert_status(
        A.data_of(api.get_fee_schedule(bundle.schedule_id, U.PROGRAM_ADMIN)), "SUPERSEDED"
    )

    before = X.get_permit(api, permit_a)
    validate_error(
        api.renew_permit(
            permit_a, {"expected_alarm_permit_version": before["version"]}, U.PERMIT_CLERK
        ),
        E.ERR_NO_ACTIVE_FEE_SCHEDULE,
        expected_status=409,
    )

    after = X.get_permit(api, permit_a)
    A.assert_version_unchanged(before, after)
    A.assert_status(after, "RENEWAL_BLOCKED")
    assert after["renewal_count"] == 0, after
    assert after["last_renewed_at"] is None, after
    renewal_invoices = [
        i for i in X.invoices_of_site(api, bundle.site_id) if i["kind"] == "PERMIT_RENEWAL_FEE"
    ]
    assert renewal_invoices == [], renewal_invoices


def test_renewal_block_still_fires_on_its_own_once_a_schedule_governs_the_clock(api):
    """With a schedule governing the clock the same renewal reports the fiscal block.

    PRD §2.10: "Permit renewal is refused on the same balance condition, with
    `ERR_PERMIT_RENEWAL_BLOCKED` at HTTP 409."
    PRD §2.10: "A permit renewal attempted when no fee schedule is `ACTIVE`, for a
    premises whose delinquent balance is at or above the blocking threshold, fails
    both the active-schedule check at position 43 and the renewal-block check at
    position 55."
    PRD §3.3: "When the logical clock reaches 30 days before `term_end_at`, the run
    moves `ACTIVE → RENEWAL_DUE`; no money moves, the permit simply becomes
    renewable."
    PRD §3.3: "A `PERMIT_RENEWAL_FEE` invoice is issued, the premises'
    `chargeable_count_permit_year` is reset to 0 so the permit-year variant restarts
    at the new term, and the permit's `version` is bumped by 1."

    This is the losing half of the pair on its own. The pinned schedule is still the
    only schedule and it is effective from 2026-01-01, so nothing is wrong with the
    pricing side at the logical clock of 2026-01-02; the sole remaining fault is the
    63000 cents outstanding against the 50000-cent blocking threshold. The refusal
    therefore surfaces the position-55 code rather than the position-43 code, and
    because the renewal never ran, no `PERMIT_RENEWAL_FEE` invoice exists, the
    permit's `renewal_count` is still 0 and its `version` has not moved.

    Design: Difficulty/priority_pair_validation_conflict/pair_b_missing_active_fee_schedule_outranks_the_delinquent_renewal_block
    """
    bundle, permit_a = _pair_b_world(api)
    A.assert_status(
        A.data_of(api.get_fee_schedule(bundle.schedule_id, U.PROGRAM_ADMIN)), "ACTIVE"
    )

    before = X.get_permit(api, permit_a)
    validate_error(
        api.renew_permit(
            permit_a, {"expected_alarm_permit_version": before["version"]}, U.PERMIT_CLERK
        ),
        E.ERR_PERMIT_RENEWAL_BLOCKED,
        expected_status=409,
    )

    after = X.get_permit(api, permit_a)
    A.assert_version_unchanged(before, after)
    A.assert_status(after, "RENEWAL_BLOCKED")
    assert after["renewal_count"] == 0, after
    assert _at(after["term_end_at"]) == _at("2026-01-31T00:00:00Z"), after["term_end_at"]
    renewal_invoices = [
        i for i in X.invoices_of_site(api, bundle.site_id) if i["kind"] == "PERMIT_RENEWAL_FEE"
    ]
    assert renewal_invoices == [], renewal_invoices
    site = X.get_site(api, bundle.site_id)
    assert site["renewal_block_active"] is True, site
    A.assert_money_cents(site["outstanding_balance_cents"], 63000, "outstanding_balance_cents")


def _pair_c_world(api):
    """Two counted incidents whose appeal windows close on different days."""
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "appeal_filing_days": 20,
            "free_alarm_allowance": 0,
            "invoice_due_days": 3650,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
        },
        site_overrides={"occupancy_class": "RESIDENTIAL", "police_beat": "B04"},
        contact_count=2,
        system_count=2,
    )
    system_a, system_b = bundle.system_ids

    X.set_clock(api, "2026-02-05T00:00:00Z")
    first = X.create_counted_incident(api, bundle, system_a, "2026-02-05T01:00:00Z")
    X.set_clock(api, "2026-02-20T00:00:00Z")
    second = X.create_counted_incident(api, bundle, system_b, "2026-02-20T01:00:00Z")

    early = X.get_incident(api, first.incident_id)
    late = X.get_incident(api, second.incident_id)
    assert _at(early["determined_at"]) == _at("2026-02-05T00:00:00Z"), early["determined_at"]
    assert _at(late["determined_at"]) == _at("2026-02-20T00:00:00Z"), late["determined_at"]

    X.set_clock(api, "2026-02-22T00:00:00Z")
    appeal_one = X.file_appeal(api, bundle, first.incident_id, grounds="COUNTING_ERROR")
    appeal_two = X.file_appeal(api, bundle, second.incident_id, grounds="COUNTING_ERROR")
    A.assert_status(X.get_appeal(api, appeal_one), "FILED")
    A.assert_status(X.get_appeal(api, appeal_two), "FILED")

    X.set_clock(api, "2026-02-26T00:00:00Z")
    return bundle, first.incident_id, second.incident_id


def _refile_appeal(api, bundle, incident_id):
    """Lodge a second appeal against an incident, carrying its current version."""
    return api.create_appeal(
        F.appeal_payload(
            incident_id,
            grounds="FEE_CALCULATION_ERROR",
            narrative="A second filing against an incident that already has a live appeal.",
            expected_false_alarm_incident_version=X.incident_version(api, incident_id),
        ),
        bundle.holder_headers,
    )


def test_closed_filing_window_outranks_the_live_appeal_on_the_older_incident(api):
    """A late second filing reports the closed window, not the pending appeal.

    PRD §2.10: "An appeal filed on the twenty-first day after determination, against
    an incident that also already has a live appeal, fails both the filing-window
    check at position 30 and the pending-appeal check at position 36."
    PRD §2.10: "The filing-window check wins, and the caller receives
    `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §3.6: "The filing window is measured from the ruling: the appeal must be
    filed no later than `determined_at` plus the governing schedule's
    `appeal_filing_days` whole days, the boundary being inclusive, else
    `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §3.6: "When both faults are present — a late filing against an incident that
    also already has a live appeal — the window rule is the higher-priority row and
    `ERR_APPEAL_WINDOW_CLOSED` is what the caller sees."

    The older incident was ruled chargeable at 2026-02-05T00:00:00Z, so with
    `appeal_filing_days` of 20 its window closes at 2026-02-25T00:00:00Z, that
    boundary instant still being acceptable. The trigger runs at 2026-02-26T00:00:00Z,
    the twenty-first day, so the window is shut; the appeal filed on 2026-02-22 is
    still `FILED`, so the pending-appeal row is violated too. The supplied
    `expected_false_alarm_incident_version` is read immediately before the call, so
    the version check cannot pre-empt either row.

    Design: Difficulty/priority_pair_validation_conflict/pair_c_closed_appeal_window_outranks_an_already_pending_appeal
    """
    bundle, early_incident, late_incident = _pair_c_world(api)

    before = X.get_incident(api, early_incident)
    A.assert_status(before, "APPEALED")
    validate_error(
        _refile_appeal(api, bundle, early_incident),
        E.ERR_APPEAL_WINDOW_CLOSED,
        expected_status=409,
    )

    after = X.get_incident(api, early_incident)
    A.assert_version_unchanged(before, after)
    A.assert_status(after, "APPEALED")
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": early_incident}), 1
    )
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": late_incident}), 1
    )


def test_pending_appeal_check_still_fires_while_the_newer_window_is_open(api):
    """Inside the filing window the same second filing reports the live appeal.

    PRD §2.10: "In order: the contested incident must have no appeal in `FILED`,
    `SCHEDULED` or `HEARD`, failing with `ERR_APPEAL_ALREADY_PENDING`."
    PRD §3.6: "Only one live appeal may exist per incident: if the incident already
    has an appeal in `FILED`, `SCHEDULED` or `HEARD`, the filing is rejected with
    `ERR_APPEAL_ALREADY_PENDING`."
    PRD §3.6: "The filing window is measured from the ruling: the appeal must be
    filed no later than `determined_at` plus the governing schedule's
    `appeal_filing_days` whole days, the boundary being inclusive, else
    `ERR_APPEAL_WINDOW_CLOSED`."

    This is the losing half of the pair on its own. The newer incident was ruled
    chargeable at 2026-02-20T00:00:00Z, so its window runs to 2026-03-12T00:00:00Z and
    the trigger clock of 2026-02-26T00:00:00Z is only the sixth day of it; the window
    row is therefore satisfied and the sole remaining fault is the appeal filed on
    2026-02-22, which is still `FILED`. Only the `determined_at` of the target
    incident differs between this test and its twin, and it is what changes which of
    the two codes the caller sees.

    Design: Difficulty/priority_pair_validation_conflict/pair_c_closed_appeal_window_outranks_an_already_pending_appeal
    """
    bundle, early_incident, late_incident = _pair_c_world(api)

    before = X.get_incident(api, late_incident)
    A.assert_status(before, "APPEALED")
    validate_error(
        _refile_appeal(api, bundle, late_incident),
        E.ERR_APPEAL_ALREADY_PENDING,
        expected_status=409,
    )

    after = X.get_incident(api, late_incident)
    A.assert_version_unchanged(before, after)
    A.assert_status(after, "APPEALED")
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": late_incident}), 1
    )
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": early_incident}), 1
    )
